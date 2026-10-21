"""Chat usage history only: never transcripts, tool payloads, IPs or raw session IDs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

DB_PATH = Path(os.environ.get("RUNNRR_USAGE_PATH", "data/usage.sqlite"))
router = APIRouter()


@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=2)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS usage_turns (
            turn_id TEXT PRIMARY KEY, day TEXT NOT NULL, session_hash TEXT NOT NULL,
            model TEXT NOT NULL, provider TEXT NOT NULL, profile TEXT NOT NULL,
            metrics TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS usage_day ON usage_turns(day)")
        with conn:
            yield conn
    finally:
        conn.close()


def record(metrics: dict, session_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO usage_turns VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (
                metrics["turn_id"],
                metrics["started_at"][:10],
                hashlib.sha256(session_id.encode()).hexdigest(),
                metrics["model"],
                metrics["provider"],
                metrics["profile"],
                json.dumps(metrics),
            ),
        )


def summary(since: date, until: date, model: str | None = None, profile: str | None = None) -> dict:
    where = "day >= ? AND day <= ?"
    params = [since.isoformat(), until.isoformat()]
    for key, value in (("model", model), ("profile", profile)):
        if value:
            where += f" AND {key} = ?"
            params.append(value)

    sums = {
        **{
            key: f"tokens.{key}"
            for key in ("input", "output", "reasoning", "cache_read", "cache_write")
        },
        **{
            key: key for key in ("tokens_total", "hops", "tool_calls", "tool_errors", "duration_ms")
        },
    }
    columns = [
        f"COALESCE(SUM(json_extract(metrics, '$.{path}')), 0) AS {key}"
        for key, path in sums.items()
    ]
    columns += [
        "COUNT(*) AS turns",
        "COUNT(DISTINCT session_hash) AS sessions",
        "COALESCE(SUM(json_extract(metrics, '$.cost_usd')), 0) AS known_cost_usd",
        "COALESCE(SUM(json_extract(metrics, '$.cost_usd') IS NULL), 0) AS unpriced_turns",
        "COALESCE(SUM(json_extract(metrics, '$.usage_status') != 'complete'), 0) AS incomplete_turns",
        "COALESCE(SUM(json_extract(metrics, '$.status') != 'ok'), 0) AS failed_turns",
        "COALESCE(SUM(json_extract(metrics, '$.usage_estimated')), 0) AS estimated_turns",
        "COALESCE(SUM(json_extract(metrics, '$.reasoning_estimated')), 0) AS reasoning_estimated_turns",
        "SUM(json_extract(metrics, '$.cache_savings_usd')) AS cache_savings_usd",
        "AVG(json_extract(metrics, '$.ttft_ms')) AS avg_ttft_ms",
        "AVG(json_extract(metrics, '$.duration_ms')) AS avg_duration_ms",
    ]
    for key in ("input", "output", "cache_read", "cache_write"):
        columns.append(f"SUM(json_extract(metrics, '$.category_cost_usd.{key}')) AS cost_{key}")

    def read(conn, group=None):
        # Group names are internal constants, never request values.
        grouping = f", {group} AS label" if group else ""
        suffix = f" GROUP BY {group} ORDER BY {group}" if group else ""
        rows = conn.execute(
            f"SELECT {', '.join(columns)}{grouping} FROM usage_turns WHERE {where}{suffix}", params
        )
        result = []
        for row in rows:
            item = dict(row)
            item["cost_usd"] = None if item["unpriced_turns"] else item["known_cost_usd"]
            item["cache_hit_rate"] = item["cache_read"] / item["input"] if item["input"] else None
            item["uncached_input"] = max(
                0, item["input"] - item["cache_read"] - item["cache_write"]
            )
            result.append(item)
        return result

    with connection() as conn:
        conn.execute("BEGIN")
        return {
            "since": since.isoformat(),
            "until": until.isoformat(),
            "time_zone": "UTC",
            "scope": "chat",
            "totals": read(conn)[0],
            "days": read(conn, "day"),
            "models": read(conn, "model"),
            "providers": read(conn, "provider"),
            "profiles": read(conn, "profile"),
        }


@router.get("/api/usage")
def usage_history(
    since: date | None = None,
    until: date | None = None,
    model: str | None = Query(None, max_length=100),
    profile: str | None = Query(None, max_length=100),
) -> dict:
    until = until or datetime.now(timezone.utc).date()
    since = since or until - timedelta(days=29)
    if since > until or (until - since).days >= 366:
        raise HTTPException(422, "Choose an ordered date range of at most 366 days.")
    try:
        return summary(since, until, model, profile)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "Usage history is unavailable.") from exc
