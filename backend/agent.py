"""Provider-agnostic agent loop. Mirrors the run_conversation pattern from
notebook 001_tools_009.ipynb — bounded loop on stop_reason, run tools, append
results, repeat. Differences: yields normalized SSE events, calls into a
LLMProvider so the same loop covers Anthropic + OpenAI/Moonshot.
"""
from __future__ import annotations

from typing import AsyncIterator

from backend.config import MAX_TOKENS, MAX_TOOL_HOPS
from backend.profiles import AgentProfile, load_profile
from backend.providers.base import LLMProvider
from backend.tools import run_tool
from backend.types import SessionDict


async def run_conversation_stream(
    user_message: str,
    session: SessionDict,
    provider: LLMProvider,
    model: str,
    profile: AgentProfile | None = None,
) -> AsyncIterator[dict]:
    """Run one user turn through the agent. Yields SSE-shaped event dicts.

    Mutates session["messages"] across the conversation. Hard-bounded by MAX_TOOL_HOPS.
    """
    profile = profile or load_profile()
    session["messages"].append(provider.format_user(user_message))

    # TODO(mcp): if profile.mcp_servers is non-empty, spawn stdio MCP clients on
    # first use, list their tools, merge into provider.tools_for_provider(...)'s
    # catalog, and dispatch matching tool_use_complete events through the MCP
    # client (rather than run_tool). Out of scope for this task — the schema is
    # parsed and stored on AgentProfile.mcp_servers, but no client connects yet.
    for hop in range(MAX_TOOL_HOPS):
        tool_calls_pending: list[dict] = []
        stop_reason: str = "end_turn"
        pending_usage: dict | None = None
        had_thinking = False

        async for ev in provider.stream(
            model=model,
            messages=session["messages"],
            system=provider.system_for_provider(profile),
            tools=provider.tools_for_provider(profile),
            max_tokens=MAX_TOKENS,
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
                "had_thinking": had_thinking,
                **pending_usage,
            }

        if stop_reason != "tool_use":
            yield {"event": "done", "stop_reason": stop_reason}
            return

        results = [
            run_tool(
                tc["name"],
                tc["arguments"],
                tc["tool_use_id"],
                root=profile.kb_root,
                data_root=profile.data_root,
                profile=profile,
                allowed_tools=profile.tools,
            )
            for tc in tool_calls_pending
        ]
        for r in results:
            yield {
                "event": "tool_result",
                "tool_use_id": r.tool_use_id,
                "name": r.name,
                "is_error": r.is_error,
                "source_summary": r.source_summary,
                "source_items": r.source_items,
                "source_count": r.source_count,
                "hidden_count": r.hidden_count,
            }
        provider.append_tool_results(session["messages"], results)

    yield {"event": "error", "message": f"hit MAX_TOOL_HOPS={MAX_TOOL_HOPS}"}
