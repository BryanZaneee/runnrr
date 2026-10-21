"""Per-turn usage persistence and the stable chat_complete log contract."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import AsyncIterator

from runnrr import metrics
from runnrr.config import MODEL_REGISTRY
from runnrr.pricing import cache_savings_usd, cost_breakdown, cost_usd
from runnrr.types import SessionDict
from runnrr.usage import billable_total, tally, zero_tokens

log = logging.getLogger("runnrr")


async def _instrument(
    events: AsyncIterator[dict],
    *,
    ip: str,
    session_id: str,
    model_id: str,
    profile_id: str,
    turn_id: str,
    session: SessionDict | None = None,
) -> AsyncIterator[dict]:
    """Pass events through; tally usage for the budget and emit one structured log.

    `chat_complete` has an out-of-repo consumer (the production chat UI lives in
    bryanzane_v3/runnrr), so fields here are ADDED, never renamed or removed.
    `tool_hops` is kept for that reason even though `tool_calls` supersedes it.
    """
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    tokens = zero_tokens()
    ttft_ms: int | None = None
    hops = 0
    tool_calls = 0
    estimated_usage = False
    reasoning_estimated = False
    usage_reports = 0
    context_tokens = None
    tool_errors = 0
    first_text_ms = None
    status = "interrupted"
    final_metrics = None
    error_class: str | None = None

    def snapshot():
        usage_status = (
            "unavailable"
            if not usage_reports
            else "complete"
            if status == "ok" and usage_reports == hops
            else "partial"
        )
        return {
            "usage_version": 2,
            "turn_id": turn_id,
            "started_at": started_at,
            "model": model_id,
            "provider": MODEL_REGISTRY.get(model_id, {}).get("vendor", "unknown"),
            "profile": profile_id,
            "tokens": dict(tokens),
            "tokens_total": billable_total(tokens),
            "usage_status": usage_status,
            "usage_estimated": estimated_usage,
            "reasoning_estimated": reasoning_estimated,
            "cost_usd": cost_usd(model_id, tokens) if usage_reports else None,
            "category_cost_usd": cost_breakdown(model_id, tokens) if usage_reports else None,
            "cache_savings_usd": cache_savings_usd(model_id, tokens) if usage_reports else None,
            "cost_source": "model_priced"
            if usage_reports and cost_usd(model_id, tokens) is not None
            else "unpriced",
            "context_tokens": context_tokens,
            "context_window": MODEL_REGISTRY.get(model_id, {}).get("context_window"),
            "ttft_ms": ttft_ms,
            "first_text_ms": first_text_ms,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "hops": hops,
            "tool_calls": tool_calls,
            "tool_errors": tool_errors,
            "status": status,
        }

    message_count = len(session["messages"]) if session is not None else 0
    try:
        async for ev in events:
            kind = ev.get("event")
            if kind == "model_start":
                hops += 1
            elif kind == "usage":
                tally(tokens, ev)
                usage_reports += 1
                context_tokens = ev.get("input_tokens")
                reasoning_estimated |= bool(ev.get("reasoning_estimated"))
                if ev.get("estimated"):
                    estimated_usage = True
            elif kind == "tool_result":
                tool_calls += 1
                tool_errors += bool(ev.get("is_error"))
            elif kind in ("delta", "thinking_delta") and ev.get("text"):
                elapsed = int((time.perf_counter() - started) * 1000)
                if ttft_ms is None:
                    ttft_ms = elapsed
                if kind == "delta" and first_text_ms is None:
                    first_text_ms = elapsed
            elif kind == "error":
                status = "error"
                error_class = error_class or "stream_error"
            elif kind == "done":
                status = "max_tokens" if ev.get("stop_reason") == "max_tokens" else "ok"
            if kind in ("done", "error"):
                final_metrics = snapshot()
                yield {"event": "metrics", **final_metrics}
            yield ev
    except Exception as exc:
        status = "exception"
        error_class = type(exc).__name__
        final_metrics = snapshot()
        yield {"event": "metrics", **final_metrics}
        raise
    finally:
        await events.aclose()
        if session is not None:
            if status != "ok":
                del session["messages"][message_count:]
            session["busy"] = False
            session["last_seen"] = time.time()
        final_metrics = final_metrics or snapshot()
        try:
            await asyncio.to_thread(metrics.record, final_metrics, session_id)
        except (OSError, sqlite3.Error):
            log.exception("usage history write failed", extra={"turn_id": turn_id})
        total = billable_total(tokens)
        log.info(
            "chat_complete",
            extra={
                "ip": ip,
                "turn_id": turn_id,
                "session": session_id[:8],
                "model": model_id,
                "profile": profile_id,
                "tokens_in": tokens["input"],
                "tokens_out": tokens["output"],
                "usage_version": 2,
                "usage_status": final_metrics["usage_status"],
                "tokens_reasoning": tokens["reasoning"],
                "tokens_total": total,
                "cache_read": tokens["cache_read"],
                "cache_write": tokens["cache_write"],
                "cost_usd": final_metrics["cost_usd"],
                "usage_estimated": estimated_usage,
                "ttft_ms": ttft_ms,
                "hops": hops,
                "tool_calls": tool_calls,
                "tool_hops": tool_calls,  # deprecated alias; see docstring
                "duration_ms": final_metrics["duration_ms"],
                "reasoning_estimated": reasoning_estimated,
                "status": status,
                "error_class": error_class,
            },
        )
