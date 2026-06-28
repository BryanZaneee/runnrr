"""Usage event recording and summaries — backed by backend.db."""
from __future__ import annotations

from datetime import datetime

from backend import db


async def record_usage(
    *,
    owner_id: str,
    agent_id: str | None,
    session_id: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cache_read: int,
    tool_hops: int,
    duration_ms: int,
    status: str,
) -> None:
    if not db.is_configured():
        return
    tokens_total = tokens_in + tokens_out
    await db.execute(
        """
        INSERT INTO usage_events (
            owner_id, agent_id, session_id, model,
            tokens_in, tokens_out, tokens_total, cache_read,
            tool_hops, duration_ms, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        owner_id,
        agent_id,
        session_id,
        model,
        tokens_in,
        tokens_out,
        tokens_total,
        cache_read,
        tool_hops,
        duration_ms,
        status,
    )


async def usage_summary(
    owner_id: str,
    *,
    since: datetime,
    agent_id: str | None = None,
) -> dict:
    params: list = [owner_id, since]
    agent_filter = ""
    if agent_id:
        agent_filter = " AND agent_id = $3"
        params.append(agent_id)

    totals = await db.fetchrow(
        f"""
        SELECT
            COALESCE(SUM(tokens_in), 0)::int AS tokens_in,
            COALESCE(SUM(tokens_out), 0)::int AS tokens_out,
            COALESCE(SUM(tokens_total), 0)::int AS tokens_total,
            COUNT(*)::int AS requests
        FROM usage_events
        WHERE owner_id = $1 AND created_at >= $2{agent_filter}
        """,
        *params,
    )

    per_day_rows = await db.fetch(
        f"""
        SELECT date_trunc('day', created_at AT TIME ZONE 'UTC')::date AS day,
               COALESCE(SUM(tokens_total), 0)::int AS tokens_total
        FROM usage_events
        WHERE owner_id = $1 AND created_at >= $2{agent_filter}
        GROUP BY 1
        ORDER BY 1
        """,
        *params,
    )

    per_model_rows = await db.fetch(
        f"""
        SELECT model, COALESCE(SUM(tokens_total), 0)::int AS tokens_total
        FROM usage_events
        WHERE owner_id = $1 AND created_at >= $2{agent_filter}
        GROUP BY model
        ORDER BY tokens_total DESC
        """,
        *params,
    )

    return {
        "tokens_in": totals["tokens_in"],
        "tokens_out": totals["tokens_out"],
        "tokens_total": totals["tokens_total"],
        "requests": totals["requests"],
        "per_day": [
            {"day": r["day"].isoformat(), "tokens_total": r["tokens_total"]}
            for r in per_day_rows
        ],
        "per_model": [
            {"model": r["model"], "tokens_total": r["tokens_total"]}
            for r in per_model_rows
        ],
    }
