"""Bounded provider-agnostic agent loop with streamed text, tools, and usage."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from runnrr.budget import TOKEN_BUDGET, BudgetExhausted
from runnrr.config import (
    MAX_PARALLEL_TOOLS,
    MAX_REQUEST_TOKEN_RESERVATION,
    MAX_TOKENS,
    MAX_TOOL_HOPS,
)
from runnrr.profiles import AgentProfile, load_profile
from runnrr.providers.base import LLMProvider
from runnrr.tools import run_tool
from runnrr.types import SessionDict
from runnrr.usage import billable_total, tally, zero_tokens

log = logging.getLogger("runnrr.agent")


async def run_conversation_stream(
    user_message: str,
    session: SessionDict,
    provider: LLMProvider,
    model: str,
    profile: AgentProfile | None = None,
    turn_id: str = "",
    max_tokens: int | None = None,
) -> AsyncIterator[dict]:
    """Run one user turn through the agent. Yields SSE-shaped event dicts.

    Mutates session["messages"] across the conversation. Hard-bounded by MAX_TOOL_HOPS.
    """
    profile = profile or load_profile()
    # Bounded so a max-width hop cannot exhaust the default thread pool, which is
    # shared process-wide and would then stall unrelated requests.
    tool_slots = asyncio.Semaphore(MAX_PARALLEL_TOOLS)
    session["messages"].append(provider.format_user(user_message))

    # MCP clients are not connected yet. Keep prompts and tool schemas stable
    # across hops; skill bodies arrive separately as tool results.
    system_block = provider.system_for_provider(profile)
    tool_schemas = provider.tools_for_provider(profile)

    for hop in range(MAX_TOOL_HOPS):
        hop_started = time.perf_counter()
        tool_calls_pending: list[dict] = []
        stop_reason: str = "end_turn"
        pending_usage: dict | None = None
        had_thinking = False

        try:
            # UTF-8 JSON bytes plus framing conservatively bound text/tool inputs.
            # Anthropic may raise its output cap for extended thinking.
            output_cap = max(
                max_tokens or MAX_TOKENS, (getattr(provider, "thinking_budget", 0) or 0) + 1024
            )
            reservation = (
                len(
                    json.dumps(
                        [session["messages"], system_block, tool_schemas],
                        ensure_ascii=False,
                        default=lambda value: value.model_dump(mode="json"),
                    ).encode()
                )
                + 8192
                + output_cap
            )
            if MAX_REQUEST_TOKEN_RESERVATION and reservation > MAX_REQUEST_TOKEN_RESERVATION:
                raise BudgetExhausted("This thread is too large for the demo. Start a new thread.")
            day = TOKEN_BUDGET.reserve(reservation)
            yield {"event": "model_start", "hop": hop}
            async for ev in provider.stream(
                model=model,
                messages=session["messages"],
                system=system_block,
                tools=tool_schemas,
                max_tokens=max_tokens or MAX_TOKENS,
            ):
                t = ev.get("type")
                if t == "text_delta":
                    yield {"event": "delta", "text": ev["text"]}
                elif t == "thinking_delta":
                    had_thinking = True
                    yield {"event": "thinking_delta", "text": ev["text"]}
                elif t == "tool_use_start":
                    yield {"event": "tool_use_start", "name": ev["name"]}
                elif t == "tool_use_complete":
                    tool_calls_pending.append(ev)
                elif t == "usage":
                    # Buffer usage and emit once we know the turn outcome — providers
                    # yield usage before message_done, so we can't classify in-flight.
                    pending_usage = ev["usage"]
                elif t == "message_done":
                    stop_reason = ev.get("stop_reason") or "end_turn"
                elif t == "error":
                    # Use the shared failure path so any reported usage survives.
                    raise RuntimeError("provider reported a stream error")
            if pending_usage is not None:
                tokens = zero_tokens()
                tally(tokens, pending_usage)
                if not pending_usage.get("estimated"):
                    TOKEN_BUDGET.settle(day, reservation, billable_total(tokens))
        except BudgetExhausted as exc:
            yield {"event": "error", "message": str(exc)}
            return
        except Exception as exc:
            # Keep internal provider details out of the public error event.
            log.exception(
                "provider stream failed",
                extra={
                    # Without turn_id/profile this line could not be joined to the
                    # chat_complete record for the same turn.
                    "turn_id": turn_id,
                    "model": model,
                    "profile": profile.id,
                    "hop": hop,
                    "error_class": type(exc).__name__,
                },
            )
            if pending_usage is not None:
                # Tokens already consumed still count against the daily budget.
                yield {
                    "event": "usage",
                    "usage_version": 2,
                    "category": "tools" if tool_calls_pending else "response",
                    "hop": hop,
                    "hop_ms": int((time.perf_counter() - hop_started) * 1000),
                    "had_thinking": had_thinking,
                    **pending_usage,
                }
            yield {"event": "error", "message": "model provider error; please retry"}
            return

        if pending_usage is not None:
            # Reasoning is a subset of output; classify usage by tools vs final text.
            category = "tools" if tool_calls_pending else "response"
            yield {
                "event": "usage",
                "usage_version": 2,
                "category": category,
                "hop": hop,
                "hop_ms": int((time.perf_counter() - hop_started) * 1000),
                "had_thinking": had_thinking,
                **pending_usage,
            }

        if stop_reason == "blocked":
            yield {"event": "error", "message": "The model could not complete this response."}
            return

        if stop_reason != "tool_use":
            yield {"event": "done", "stop_reason": stop_reason}
            return

        # Run blocking tools off-loop; gather preserves message order for caching.
        async def _run_one(tc: dict):
            async with tool_slots:
                return await asyncio.to_thread(
                    run_tool,
                    tc["name"],
                    tc["arguments"],
                    tc["tool_use_id"],
                    root=profile.kb_root,
                    data_root=profile.data_root,
                    profile=profile,
                    allowed_tools=profile.tools,
                )

        results = list(await asyncio.gather(*(_run_one(tc) for tc in tool_calls_pending)))

        # Commit tool results before yielding so disconnects cannot break pairing.
        provider.append_tool_results(session["messages"], results)

        for r in results:
            payload = {
                "event": "tool_result",
                "tool_use_id": r.tool_use_id,
                "name": r.name,
                "is_error": r.is_error,
                "source_summary": r.source_summary,
                "source_items": r.source_items,
                "source_count": r.source_count,
                "hidden_count": r.hidden_count,
                "duration_ms": r.duration_ms,
            }
            if r.rag_trace:
                payload["rag_trace"] = r.rag_trace
            yield payload

    yield {"event": "error", "message": f"hit MAX_TOOL_HOPS={MAX_TOOL_HOPS}"}
