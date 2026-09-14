"""Provider-agnostic agent loop. Mirrors the run_conversation pattern from
notebook 001_tools_009.ipynb — bounded loop on stop_reason, run tools, append
results, repeat. Differences: yields normalized SSE events, calls into a
LLMProvider so the same loop covers Anthropic + OpenAI/Moonshot.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from runnrr.config import MAX_PARALLEL_TOOLS, MAX_TOKENS, MAX_TOOL_HOPS
from runnrr.profiles import AgentProfile, load_profile
from runnrr.providers.base import LLMProvider
from runnrr.tools import run_tool
from runnrr.types import SessionDict

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

    # TODO(mcp): if profile.mcp_servers is non-empty, spawn stdio MCP clients on
    # first use, list their tools, merge into provider.tools_for_provider(...)'s
    # catalog, and dispatch matching tool_use_complete events through the MCP
    # client (rather than run_tool). Out of scope for this task — the schema is
    # parsed and stored on AgentProfile.mcp_servers, but no client connects yet.
    # Built once per turn, not once per hop. AgentProfile is frozen and immutable
    # within a turn, so rebuilding was pure waste: a deepcopy per overridden schema
    # and, on Gemini, a full FunctionDeclaration reconstruction every hop. The
    # bigger win is prefix stability -- one object identity across all hops is what
    # keeps the prompt cache warm.
    system_block = provider.system_for_provider(profile)
    tool_schemas = provider.tools_for_provider(profile)

    for hop in range(MAX_TOOL_HOPS):
        hop_started = time.perf_counter()
        tool_calls_pending: list[dict] = []
        stop_reason: str = "end_turn"
        pending_usage: dict | None = None
        had_thinking = False

        try:
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
                    yield {"event": "error", "message": ev.get("text", "provider error")}
                    return
        except Exception as exc:
            # SDK/network failures (auth, timeout, disconnect) become one sanitized
            # error event instead of an exception escaping the SSE stream. Accepted
            # edge: the session may end with a trailing user message and no
            # assistant turn — all three provider APIs tolerate that on the next
            # request.
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
                    "category": "tools" if tool_calls_pending else "response",
                    "hop": hop,
                    "hop_ms": int((time.perf_counter() - hop_started) * 1000),
                    "had_thinking": had_thinking,
                    **pending_usage,
                }
            yield {"event": "error", "message": "model provider error; please retry"}
            return

        if pending_usage is not None:
            # Categorize by what the hop produced, not by whether thinking happened —
            # otherwise thinking-enabled models (Personal Agent can run Sonnet with extended
            # thinking on every hop) would always land in "reasoning" and the Tools /
            # Response buckets could never increment. Reasoning tokens travel
            # separately on `reasoning_tokens` so the frontend can fan them out.
            category = "tools" if tool_calls_pending else "response"
            yield {
                "event": "usage",
                "category": category,
                "hop": hop,
                "hop_ms": int((time.perf_counter() - hop_started) * 1000),
                "had_thinking": had_thinking,
                **pending_usage,
            }

        if stop_reason != "tool_use":
            yield {"event": "done", "stop_reason": stop_reason}
            return

        # asyncio.to_thread keeps every handler synchronous while getting the
        # blocking work off the event loop. That work is real: sync httpx calls
        # in web_search and web_fetch, time.sleep in the Voyage backoff, and a
        # synchronous Anthropic round-trip inside the RAG reranker. On the single
        # uvicorn worker, one of those used to stall every other in-flight stream.
        #
        # gather runs the calls in one hop concurrently AND preserves input order,
        # which matters beyond latency: the order of append_tool_results decides
        # the message log, and a stable message log is what keeps the prompt
        # prefix cacheable.
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

        results = list(
            await asyncio.gather(*(_run_one(tc) for tc in tool_calls_pending))
        )

        # Append BEFORE yielding. If the client disconnects mid-yield, GeneratorExit
        # propagates and anything after the yields never runs -- which used to leave
        # an assistant tool_use turn with no matching tool_result, and every later
        # request on that session_id 400s on Anthropic and OpenAI for the full
        # 30-minute session TTL. The messages do not depend on the yields, so
        # ordering them first is the whole fix.
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
