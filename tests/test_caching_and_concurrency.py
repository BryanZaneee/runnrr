"""Prompt-cache stability, tool concurrency, and the disconnect fix.

The cache tests are the ones that matter long-term: a cache breakpoint on an
UNSTABLE prefix is worse than no breakpoint, because every turn becomes a cache
write instead of a read. Nothing about that failure is loud — it shows up only
as a latency and cost curve that climbs with conversation length. These tests
are what stop a future edit from silently reintroducing it.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from runnrr.agent import run_conversation_stream
from runnrr.profiles import load_profile


# --------------------------------------------------------------------------- #
# Cache prefix
# --------------------------------------------------------------------------- #


class TestCacheBreakpoints:
    def test_system_block_carries_one_breakpoint(self):
        from runnrr.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider.__new__(AnthropicProvider)
        blocks = provider.system_for_provider(load_profile("personal-agent"))
        assert len(blocks) == 1
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_only_the_last_tool_carries_a_breakpoint(self):
        from runnrr.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider.__new__(AnthropicProvider)
        schemas = provider.tools_for_provider(load_profile("personal-agent"))
        marked = [s for s in schemas if "cache_control" in s]
        assert len(marked) == 1, "exactly one tool breakpoint"
        assert marked[0] is schemas[-1], "it must be the LAST tool (prefix caching)"

    def test_breakpoint_count_stays_within_the_api_limit(self):
        from runnrr.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider.__new__(AnthropicProvider)
        profile = load_profile("personal-agent")
        total = sum(
            1 for s in provider.tools_for_provider(profile) if "cache_control" in s
        ) + sum(
            1 for b in provider.system_for_provider(profile) if "cache_control" in b
        )
        assert total <= 4, "Anthropic allows at most 4 cache breakpoints per request"

    def test_prefix_is_byte_stable(self):
        """Two builds of the same profile must be byte-identical.

        This is the whole precondition for caching. If a future change makes the
        system prompt or tool list vary between calls — a timestamp, an unsorted
        dict, a per-request id — the prefix stops matching and the cache silently
        never hits.
        """
        import json

        from runnrr.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider.__new__(AnthropicProvider)
        profile = load_profile("personal-agent")
        first = json.dumps(
            [provider.system_for_provider(profile), provider.tools_for_provider(profile)],
            sort_keys=True,
        )
        second = json.dumps(
            [provider.system_for_provider(profile), provider.tools_for_provider(profile)],
            sort_keys=True,
        )
        assert first == second

    def test_tool_description_override_does_not_mutate_shared_schema(self):
        from runnrr.providers.anthropic_provider import AnthropicProvider
        from runnrr.tools.schemas import SCHEMAS_BY_NAME

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.tools_for_provider(load_profile("personal-agent"))
        # The breakpoint is attached to a copy; leaking it into the module-level
        # registry would put cache_control on every profile's tools.
        assert all("cache_control" not in s for s in SCHEMAS_BY_NAME.values())


# --------------------------------------------------------------------------- #
# Per-turn build count
# --------------------------------------------------------------------------- #


class CountingProvider:
    """Counts how often the system prompt and tool schemas get rebuilt."""

    def __init__(self, hops):
        self._hops = list(hops)
        self.system_builds = 0
        self.tool_builds = 0

    def format_user(self, text):
        return {"role": "user", "content": text}

    def system_for_provider(self, profile):
        self.system_builds += 1
        return [{"type": "text", "text": profile.system_prompt}]

    def tools_for_provider(self, profile):
        self.tool_builds += 1
        return []

    def append_tool_results(self, messages, results):
        messages.append({"role": "user", "content": "tool results"})

    async def stream(self, **kwargs):
        events = self._hops.pop(0)
        messages = kwargs["messages"]
        messages.append({"role": "assistant", "content": "..."})
        for ev in events:
            yield ev


@pytest.mark.asyncio
async def test_system_and_tools_built_once_per_turn():
    """Three hops must still be one build of each.

    Rebuilding per hop was pure waste (a deepcopy per overridden schema, and a
    full FunctionDeclaration reconstruction on Gemini), but the real reason this
    is a test is prefix stability — one object identity across hops.
    """
    hops = [
        [
            {"type": "tool_use_complete", "tool_use_id": "t1", "name": "list_kb", "arguments": {}},
            {"type": "message_done", "stop_reason": "tool_use"},
        ],
        [
            {"type": "tool_use_complete", "tool_use_id": "t2", "name": "list_kb", "arguments": {}},
            {"type": "message_done", "stop_reason": "tool_use"},
        ],
        [
            {"type": "text_delta", "text": "done"},
            {"type": "message_done", "stop_reason": "end_turn"},
        ],
    ]
    provider = CountingProvider(hops)
    session = {"messages": [], "last_seen": 0.0, "provider": "x", "profile": "p"}

    async for _ in run_conversation_stream(
        "hi", session, provider, "m", load_profile("personal-agent")
    ):
        pass

    assert provider.system_builds == 1
    assert provider.tool_builds == 1


# --------------------------------------------------------------------------- #
# Tool concurrency + ordering
# --------------------------------------------------------------------------- #


class SlowToolProvider(CountingProvider):
    def __init__(self, hops):
        super().__init__(hops)
        self.appended: list[list] = []

    def append_tool_results(self, messages, results):
        self.appended.append([r.tool_use_id for r in results])
        messages.append({"role": "user", "content": "tool results"})


@pytest.mark.asyncio
async def test_tools_in_one_hop_run_concurrently(monkeypatch):
    """Three 100ms tools should take ~100ms, not ~300ms.

    They were a list comprehension over a synchronous run_tool called straight
    from the async generator, so they ran serially AND blocked the event loop —
    on the single uvicorn worker that stalled every other in-flight stream.
    """
    import runnrr.agent as agent_module

    def slow_tool(name, arguments, tool_use_id, **kwargs):
        time.sleep(0.1)
        from runnrr.tools.results import ToolResult

        return ToolResult(tool_use_id=tool_use_id, name=name, content="{}")

    monkeypatch.setattr(agent_module, "run_tool", slow_tool)

    hops = [
        [
            {"type": "tool_use_complete", "tool_use_id": f"t{i}", "name": "list_kb", "arguments": {}}
            for i in range(3)
        ] + [{"type": "message_done", "stop_reason": "tool_use"}],
        [
            {"type": "text_delta", "text": "done"},
            {"type": "message_done", "stop_reason": "end_turn"},
        ],
    ]
    provider = SlowToolProvider(hops)
    session = {"messages": [], "last_seen": 0.0, "provider": "x", "profile": "p"}

    started = time.perf_counter()
    async for _ in run_conversation_stream(
        "hi", session, provider, "m", load_profile("personal-agent")
    ):
        pass
    elapsed = time.perf_counter() - started

    assert elapsed < 0.25, f"tools ran serially ({elapsed:.2f}s for 3x100ms)"


@pytest.mark.asyncio
async def test_event_loop_stays_responsive_during_tools(monkeypatch):
    """A blocking tool must not stall the loop — that is the multi-tenant fix."""
    import runnrr.agent as agent_module

    def slow_tool(name, arguments, tool_use_id, **kwargs):
        time.sleep(0.2)
        from runnrr.tools.results import ToolResult

        return ToolResult(tool_use_id=tool_use_id, name=name, content="{}")

    monkeypatch.setattr(agent_module, "run_tool", slow_tool)

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    hops = [
        [
            {"type": "tool_use_complete", "tool_use_id": "t1", "name": "list_kb", "arguments": {}},
            {"type": "message_done", "stop_reason": "tool_use"},
        ],
        [
            {"type": "text_delta", "text": "done"},
            {"type": "message_done", "stop_reason": "end_turn"},
        ],
    ]
    provider = SlowToolProvider(hops)
    session = {"messages": [], "last_seen": 0.0, "provider": "x", "profile": "p"}

    beat = asyncio.create_task(heartbeat())
    async for _ in run_conversation_stream(
        "hi", session, provider, "m", load_profile("personal-agent")
    ):
        pass
    beat.cancel()

    assert ticks > 5, f"event loop was blocked during tool execution (ticks={ticks})"


@pytest.mark.asyncio
async def test_parallel_tools_preserve_call_order(monkeypatch):
    """gather preserves input order, and the message log depends on it.

    Out-of-order tool results would make the message log non-deterministic, which
    destabilizes the very prefix the cache breakpoints rely on.
    """
    import runnrr.agent as agent_module

    delays = {"t0": 0.15, "t1": 0.01, "t2": 0.08}

    def variable_tool(name, arguments, tool_use_id, **kwargs):
        time.sleep(delays[tool_use_id])
        from runnrr.tools.results import ToolResult

        return ToolResult(tool_use_id=tool_use_id, name=name, content="{}")

    monkeypatch.setattr(agent_module, "run_tool", variable_tool)

    hops = [
        [
            {"type": "tool_use_complete", "tool_use_id": f"t{i}", "name": "list_kb", "arguments": {}}
            for i in range(3)
        ] + [{"type": "message_done", "stop_reason": "tool_use"}],
        [
            {"type": "text_delta", "text": "done"},
            {"type": "message_done", "stop_reason": "end_turn"},
        ],
    ]
    provider = SlowToolProvider(hops)
    session = {"messages": [], "last_seen": 0.0, "provider": "x", "profile": "p"}

    seen = []
    async for ev in run_conversation_stream(
        "hi", session, provider, "m", load_profile("personal-agent")
    ):
        if ev.get("event") == "tool_result":
            seen.append(ev["tool_use_id"])

    assert seen == ["t0", "t1", "t2"], "tool_result frames must follow call order"
    assert provider.appended == [["t0", "t1", "t2"]], "message log must follow call order"


# --------------------------------------------------------------------------- #
# Client disconnect
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_disconnect_midyield_leaves_a_valid_message_log(monkeypatch):
    """A client vanishing mid-stream must not brick the session.

    Results used to be yielded to SSE first and appended only afterward, so
    GeneratorExit meant append_tool_results never ran — leaving an assistant
    tool_use turn with no matching tool_result. Every later request on that
    session_id then 400s on Anthropic and OpenAI, for the full 30-minute TTL.
    """
    import runnrr.agent as agent_module

    def fast_tool(name, arguments, tool_use_id, **kwargs):
        from runnrr.tools.results import ToolResult

        return ToolResult(tool_use_id=tool_use_id, name=name, content="{}")

    monkeypatch.setattr(agent_module, "run_tool", fast_tool)

    hops = [
        [
            {"type": "tool_use_complete", "tool_use_id": "t1", "name": "list_kb", "arguments": {}},
            {"type": "message_done", "stop_reason": "tool_use"},
        ],
        [
            {"type": "text_delta", "text": "done"},
            {"type": "message_done", "stop_reason": "end_turn"},
        ],
    ]
    provider = SlowToolProvider(hops)
    session = {"messages": [], "last_seen": 0.0, "provider": "x", "profile": "p"}

    gen = run_conversation_stream(
        "hi", session, provider, "m", load_profile("personal-agent")
    )
    # Consume up to and including the first tool_result, then abandon the stream.
    async for ev in gen:
        if ev.get("event") == "tool_result":
            break
    await gen.aclose()

    assert provider.appended == [["t1"]], "tool results must be in the message log"
    assert session["messages"][-1]["content"] == "tool results"
