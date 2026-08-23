"""Provider-level tests for OpenAICompatProvider and GeminiProvider.

Fake clients mock each SDK's streaming entry point (AsyncOpenAI's
chat.completions.create(), genai's aio.models.generate_content_stream) and are
injected via the providers' `client=` kwarg, so no real API is called. Covers
DeepSeek thinking mode, cache fields, SDK timeouts, and the Gemini streaming /
message-mutation / tool-pairing contracts.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.providers.openai_compat_provider import OpenAICompatProvider, _norm_usage


# --------------------------------------------------------------------------- #
# Fake OpenAI streaming client — mirrors AsyncOpenAI.chat.completions.create()
# --------------------------------------------------------------------------- #


def _delta(*, text=None, reasoning=None, tool_calls=None):
    return SimpleNamespace(content=text, reasoning_content=reasoning, tool_calls=tool_calls)


def _choice(*, delta=None, finish_reason=None):
    return SimpleNamespace(delta=delta, finish_reason=finish_reason)


def _chunk(*, choices=None, usage=None):
    return SimpleNamespace(choices=choices or [], usage=usage)


def _tool_call(*, index=0, id_="", name="", args=""):
    return SimpleNamespace(
        index=index,
        id=id_,
        type="function",
        function=SimpleNamespace(name=name, arguments=args),
    )


class FakeOpenAIClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.last_request: dict | None = None
        # Match the SDK shape: client.chat.completions.create(...)
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.last_request = kwargs

        async def _gen():
            for c in self._chunks:
                yield c

        return _gen()


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #


async def _drain(provider, messages, tools=None):
    events = []
    async for ev in provider.stream(
        model="deepseek-v4-flash",
        messages=messages,
        system={"role": "system", "content": "sys"},
        tools=tools or [],
        max_tokens=1024,
    ):
        events.append(ev)
    return events


# --------------------------------------------------------------------------- #
# SDK client timeouts — PROVIDER_TIMEOUT_SECONDS reaches each constructed client
# --------------------------------------------------------------------------- #


class TestProviderTimeouts:
    def test_anthropic_client_gets_timeout(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        from backend.config import PROVIDER_TIMEOUT_SECONDS
        from backend.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()
        assert provider.client.timeout == PROVIDER_TIMEOUT_SECONDS

    def test_openai_compat_client_gets_timeout(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        from backend.config import PROVIDER_TIMEOUT_SECONDS

        provider = OpenAICompatProvider(api_key_env="OPENAI_API_KEY")
        assert provider.client.timeout == PROVIDER_TIMEOUT_SECONDS

    def test_gemini_client_gets_timeout_in_milliseconds(self, monkeypatch):
        import backend.providers.gemini_provider as gp
        from backend.config import PROVIDER_TIMEOUT_SECONDS

        recorded: dict = {}

        class RecorderClient:
            def __init__(self, **kwargs):
                recorded.update(kwargs)

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setattr(gp.genai, "Client", RecorderClient)

        gp.GeminiProvider()
        assert recorded["http_options"].timeout == int(PROVIDER_TIMEOUT_SECONDS * 1000)

    def test_injected_test_client_is_untouched(self):
        client = FakeOpenAIClient([])
        provider = OpenAICompatProvider(api_key_env="NO_SUCH_KEY", client=client)
        assert provider.client is client


# --------------------------------------------------------------------------- #
# Thinking-mode wiring — extra_body + reasoning_effort
# --------------------------------------------------------------------------- #


class TestThinkingModeWiring:
    @pytest.mark.asyncio
    async def test_extra_body_and_reasoning_effort_passed_through(self):
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(text="hi"), finish_reason="stop")]),
        ])
        provider = OpenAICompatProvider(
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            token_param="max_tokens",
            extra_body={"thinking": {"type": "enabled"}},
            reasoning_effort="high",
            preserve_reasoning_content=True,
            client=client,
        )

        await _drain(provider, [])

        assert client.last_request["extra_body"] == {"thinking": {"type": "enabled"}}
        assert client.last_request["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_no_extra_fields_when_unconfigured(self):
        """OpenAI/Kimi/GPT-5 callers don't pass these kwargs; nothing should leak in."""
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(text="hi"), finish_reason="stop")]),
        ])
        provider = OpenAICompatProvider(api_key_env="OPENAI_API_KEY", client=client)

        await _drain(provider, [])

        assert "extra_body" not in client.last_request
        assert "reasoning_effort" not in client.last_request


# --------------------------------------------------------------------------- #
# reasoning_content handling — accumulate, never yield as text_delta,
# preserve only on tool-call turns when the flag is on.
# --------------------------------------------------------------------------- #


class TestReasoningContentHandling:
    @pytest.mark.asyncio
    async def test_reasoning_streams_as_thinking_delta_not_text(self):
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(reasoning="thinking step 1"))]),
            _chunk(choices=[_choice(delta=_delta(reasoning="thinking step 2"))]),
            _chunk(choices=[_choice(delta=_delta(text="actual answer"))]),
            _chunk(choices=[_choice(delta=_delta(), finish_reason="stop")]),
        ])
        provider = OpenAICompatProvider(
            api_key_env="DEEPSEEK_API_KEY",
            preserve_reasoning_content=True,
            client=client,
        )

        events = await _drain(provider, [])

        text_deltas = [e for e in events if e["type"] == "text_delta"]
        assert text_deltas == [{"type": "text_delta", "text": "actual answer"}]

        # Reasoning surfaces in thinking_delta events (so the UI can render it),
        # but never bleeds into text_delta or any non-thinking event.
        thinking_deltas = [e for e in events if e["type"] == "thinking_delta"]
        assert thinking_deltas == [
            {"type": "thinking_delta", "text": "thinking step 1"},
            {"type": "thinking_delta", "text": "thinking step 2"},
        ]
        for ev in events:
            if ev["type"] == "thinking_delta":
                continue
            for value in ev.values():
                assert "thinking step" not in str(value)

    @pytest.mark.asyncio
    async def test_reasoning_preserved_on_tool_call_turn(self):
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(reasoning="planning..."))]),
            _chunk(choices=[_choice(delta=_delta(tool_calls=[
                _tool_call(index=0, id_="call_a", name="list_kb", args='{"subdir":""}')
            ]))]),
            _chunk(choices=[_choice(delta=_delta(), finish_reason="tool_calls")]),
        ])
        provider = OpenAICompatProvider(
            api_key_env="DEEPSEEK_API_KEY",
            preserve_reasoning_content=True,
            client=client,
        )

        messages: list = []
        await _drain(provider, messages)

        assistant_msg = messages[-1]
        assert assistant_msg["role"] == "assistant"
        assert "tool_calls" in assistant_msg
        assert assistant_msg.get("reasoning_content") == "planning..."

    @pytest.mark.asyncio
    async def test_reasoning_dropped_when_flag_off(self):
        """Even if the model streams reasoning, no preservation when flag is off."""
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(reasoning="planning..."))]),
            _chunk(choices=[_choice(delta=_delta(tool_calls=[
                _tool_call(index=0, id_="call_b", name="list_kb", args='{"subdir":""}')
            ]))]),
            _chunk(choices=[_choice(delta=_delta(), finish_reason="tool_calls")]),
        ])
        provider = OpenAICompatProvider(
            api_key_env="OPENAI_API_KEY",
            preserve_reasoning_content=False,
            client=client,
        )

        messages: list = []
        await _drain(provider, messages)

        assert "reasoning_content" not in messages[-1]

    @pytest.mark.asyncio
    async def test_reasoning_preserved_on_plain_text_turn(self):
        """DeepSeek 400s the next request if reasoning_content is dropped from any
        thinking-mode turn — including plain-text turns. So preserve whenever it
        streamed, regardless of whether tool_calls are also present."""
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(reasoning="thinking..."))]),
            _chunk(choices=[_choice(delta=_delta(text="plain answer"))]),
            _chunk(choices=[_choice(delta=_delta(), finish_reason="stop")]),
        ])
        provider = OpenAICompatProvider(
            api_key_env="DEEPSEEK_API_KEY",
            preserve_reasoning_content=True,
            client=client,
        )

        messages: list = []
        await _drain(provider, messages)

        assistant_msg = messages[-1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == "plain answer"
        assert "tool_calls" not in assistant_msg
        assert assistant_msg["reasoning_content"] == "thinking..."

    @pytest.mark.asyncio
    async def test_no_reasoning_field_when_no_reasoning_streamed(self):
        """If the model never emits reasoning_content, the field isn't synthesized."""
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(text="just an answer"))]),
            _chunk(choices=[_choice(delta=_delta(), finish_reason="stop")]),
        ])
        provider = OpenAICompatProvider(
            api_key_env="DEEPSEEK_API_KEY",
            preserve_reasoning_content=True,
            client=client,
        )

        messages: list = []
        await _drain(provider, messages)

        assert "reasoning_content" not in messages[-1]


# --------------------------------------------------------------------------- #
# Tool-call argument accumulation regression
# --------------------------------------------------------------------------- #


class TestToolCallAccumulation:
    @pytest.mark.asyncio
    async def test_split_tool_call_arguments_reassemble(self):
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(tool_calls=[
                _tool_call(index=0, id_="call_x", name="search_kb", args='{"que')
            ]))]),
            _chunk(choices=[_choice(delta=_delta(tool_calls=[
                _tool_call(index=0, id_="", name="", args='ry":"foo"}')
            ]))]),
            _chunk(choices=[_choice(delta=_delta(), finish_reason="tool_calls")]),
        ])
        provider = OpenAICompatProvider(api_key_env="OPENAI_API_KEY", client=client)

        events = await _drain(provider, [])

        completes = [e for e in events if e["type"] == "tool_use_complete"]
        assert len(completes) == 1
        assert completes[0]["arguments"] == {"query": "foo"}
        assert completes[0]["tool_use_id"] == "call_x"

    @pytest.mark.asyncio
    async def test_malformed_arguments_yield_raw_sentinel(self):
        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(tool_calls=[
                _tool_call(index=0, id_="call_bad", name="search_kb", args='{"query": broke')
            ]))]),
            _chunk(choices=[_choice(delta=_delta(), finish_reason="tool_calls")]),
        ])
        provider = OpenAICompatProvider(api_key_env="OPENAI_API_KEY", client=client)

        events = await _drain(provider, [])

        completes = [e for e in events if e["type"] == "tool_use_complete"]
        assert len(completes) == 1
        # run_tool recognizes this sentinel and asks the model to retry.
        assert completes[0]["arguments"] == {"_raw_arguments": '{"query": broke'}


# --------------------------------------------------------------------------- #
# _norm_usage — DeepSeek prompt_cache_hit_tokens mapping
# --------------------------------------------------------------------------- #


class TestNormUsageCacheFields:
    def test_deepseek_cache_hit_mapped_to_cache_read(self):
        u = SimpleNamespace(prompt_tokens=100, completion_tokens=20, prompt_cache_hit_tokens=80)
        out = _norm_usage(u)
        assert out["input_tokens"] == 100
        assert out["output_tokens"] == 20
        assert out["cache_read_input_tokens"] == 80

    def test_no_cache_field_defaults_to_zero(self):
        u = SimpleNamespace(prompt_tokens=50, completion_tokens=10)
        out = _norm_usage(u)
        assert out["cache_read_input_tokens"] == 0


# --------------------------------------------------------------------------- #
# Surface check — /api/models lists DeepSeek when DEEPSEEK_API_KEY is set
# --------------------------------------------------------------------------- #


class TestDeepSeekModelSurface:
    def test_deepseek_in_models_list_and_default(self, monkeypatch):
        # Clear other keys so DeepSeek is the only model present and gets to be the default
        # via the first-available fallback in app.py:list_models.
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        # Pin DEFAULT_MODEL so the test doesn't depend on what's in local .env.
        monkeypatch.setenv("DEFAULT_MODEL", "deepseek-v4-flash")

        from backend import config
        importlib.reload(config)
        from backend import app as app_module
        importlib.reload(app_module)
        app_module.limiter.enabled = False

        c = TestClient(app_module.app)
        r = c.get("/api/models")
        assert r.status_code == 200

        body = r.json()
        ids = [m["id"] for m in body["models"]]
        assert "deepseek-v4-flash" in ids
        assert body["default"] == "deepseek-v4-flash"

        # The DeepSeek entry should be flagged as openai_compat.
        deepseek_entry = next(m for m in body["models"] if m["id"] == "deepseek-v4-flash")
        assert deepseek_entry["provider"] == "openai_compat"
        assert deepseek_entry["vendor"] == "DeepSeek"


# --------------------------------------------------------------------------- #
# GeminiProvider — streaming, message mutation, tool pairing, usage mapping
# --------------------------------------------------------------------------- #


def _gemini_chunk(*, text=None, parts=None, usage=None, finish_reason=None):
    candidates = []
    if parts is not None or finish_reason is not None:
        candidates = [
            SimpleNamespace(
                content=SimpleNamespace(parts=parts or []),
                # Real Gemini responses always carry a finish_reason; the provider
                # reads it rather than inferring stop_reason from content.
                finish_reason=(
                    SimpleNamespace(name=finish_reason) if finish_reason else None
                ),
            )
        ]
    return SimpleNamespace(text=text, candidates=candidates, usage_metadata=usage)


def _gemini_fc_part(*, id_=None, name="", args=None):
    return SimpleNamespace(
        function_call=SimpleNamespace(id=id_, name=name, args=args or {})
    )


class FakeGeminiClient:
    """Mirrors genai.Client's aio.models.generate_content_stream(...)."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.last_request: dict | None = None
        self.aio = SimpleNamespace(
            models=SimpleNamespace(generate_content_stream=self._stream)
        )

    async def _stream(self, **kwargs):
        self.last_request = kwargs

        async def _gen():
            for c in self._chunks:
                yield c

        return _gen()


async def _drain_gemini(provider, messages):
    events = []
    async for ev in provider.stream(
        model="gemini-2.5-flash",
        messages=messages,
        system="sys",
        tools=[],
        max_tokens=1024,
    ):
        events.append(ev)
    return events


class TestGeminiStreaming:
    @pytest.mark.asyncio
    async def test_text_stream_yields_deltas_and_end_turn(self):
        from google.genai import types

        from backend.providers.gemini_provider import GeminiProvider

        client = FakeGeminiClient([
            _gemini_chunk(text="Hello"),
            _gemini_chunk(text=" there."),
        ])
        provider = GeminiProvider(client=client)
        messages = []

        events = await _drain_gemini(provider, messages)

        deltas = [e["text"] for e in events if e["type"] == "text_delta"]
        assert deltas == ["Hello", " there."]
        assert events[-1] == {"type": "message_done", "stop_reason": "end_turn"}

        # Message-mutation contract: the assistant turn was appended.
        assert len(messages) == 1
        assert isinstance(messages[0], types.Content)
        assert messages[0].role == "model"
        assert messages[0].parts[0].text == "Hello there."

    @pytest.mark.asyncio
    async def test_function_call_turn_pairs_and_falls_back_to_synthetic_id(self):
        from backend.providers.gemini_provider import GeminiProvider

        client = FakeGeminiClient([
            _gemini_chunk(parts=[
                _gemini_fc_part(name="search_kb", args={"query": "boss weakness"}),
            ]),
        ])
        provider = GeminiProvider(client=client)
        messages = []

        # Iterate manually so we can assert the assistant turn is already in
        # messages when tool_use_complete fires (the base.py contract — the next
        # append_tool_results call must produce a valid message log).
        events = []
        async for ev in provider.stream(
            model="gemini-2.5-flash", messages=messages, system="sys",
            tools=[], max_tokens=1024,
        ):
            if ev["type"] == "tool_use_complete":
                assert len(messages) == 1 and messages[0].role == "model"
            events.append(ev)

        starts = [e for e in events if e["type"] == "tool_use_start"]
        assert [e["name"] for e in starts] == ["search_kb"]

        completes = [e for e in events if e["type"] == "tool_use_complete"]
        assert len(completes) == 1
        assert completes[0]["name"] == "search_kb"
        assert completes[0]["arguments"] == {"query": "boss weakness"}
        # fc.id is None → synthetic fallback id.
        assert completes[0]["tool_use_id"] == "gemini_call_0"

        assert events[-1] == {"type": "message_done", "stop_reason": "tool_use"}

    @pytest.mark.asyncio
    async def test_tool_use_start_emitted_per_call(self):
        from backend.providers.gemini_provider import GeminiProvider

        client = FakeGeminiClient([
            _gemini_chunk(parts=[
                _gemini_fc_part(id_="fc_1", name="search_kb", args={"query": "a"}),
                _gemini_fc_part(id_="fc_2", name="search_kb", args={"query": "b"}),
            ]),
        ])
        provider = GeminiProvider(client=client)

        events = await _drain_gemini(provider, [])

        # One event per CALL, matching Anthropic. Deduping by name meant a hop
        # calling the same tool twice announced once, so identical work looked
        # different depending on which provider ran it.
        starts = [e for e in events if e["type"] == "tool_use_start"]
        assert len(starts) == 2
        completes = [e for e in events if e["type"] == "tool_use_complete"]
        assert [c["tool_use_id"] for c in completes] == ["fc_1", "fc_2"]

    @pytest.mark.asyncio
    async def test_append_tool_results_pairs_function_responses(self):
        from google.genai import types

        from backend.providers.gemini_provider import GeminiProvider
        from backend.tools.results import ToolResult

        provider = GeminiProvider(client=FakeGeminiClient([]))
        messages = []
        provider.append_tool_results(
            messages,
            [ToolResult(tool_use_id="fc_1", name="search_kb", content='{"hits": []}')],
        )

        assert len(messages) == 1
        assert isinstance(messages[0], types.Content)
        assert messages[0].role == "user"
        fr = messages[0].parts[0].function_response
        assert fr.id == "fc_1"
        assert fr.name == "search_kb"
        # Raw string passthrough, matching what Anthropic and OpenAI show the
        # model. Parsing and re-wrapping meant the model saw a different shape
        # per provider for the same tool.
        assert fr.response == {"content": '{"hits": []}'}

    @pytest.mark.asyncio
    async def test_usage_maps_thinking_and_cache_fields(self):
        from backend.providers.gemini_provider import GeminiProvider

        client = FakeGeminiClient([
            _gemini_chunk(
                text="ok",
                usage=SimpleNamespace(
                    prompt_token_count=100,
                    candidates_token_count=20,
                    thoughts_token_count=7,
                    cached_content_token_count=30,
                ),
            ),
        ])
        provider = GeminiProvider(client=client)

        events = await _drain_gemini(provider, [])

        usages = [e for e in events if e["type"] == "usage"]
        assert len(usages) == 1
        assert usages[0]["usage"] == {
            "input_tokens": 100,
            "output_tokens": 20,
            "reasoning_tokens": 7,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 0,
        }


# --------------------------------------------------------------------------- #
# Usage is never silently absent
# --------------------------------------------------------------------------- #


class TestUsageAlwaysEmitted:
    """An endpoint that reports no usage must not spend unmetered budget.

    Kimi did exactly this on every turn: `stream_options: False` meant
    `include_usage` was never sent, `usage` stayed None, and the provider yielded
    no usage event at all — so `TOKEN_BUDGET.record(0)` was a no-op and the
    traffic was free. An explicit estimate is strictly better than silence.
    """

    @pytest.mark.asyncio
    async def test_missing_usage_yields_estimated_event(self):
        from backend.providers.openai_compat_provider import OpenAICompatProvider

        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(text="hello there"))]),
            _chunk(choices=[_choice(finish_reason="stop")]),
        ])
        provider = OpenAICompatProvider(
            api_key_env="X", stream_options=False, client=client
        )

        events = await _drain(provider, [{"role": "user", "content": "hi"}])

        usages = [e for e in events if e["type"] == "usage"]
        assert len(usages) == 1, "a usage event must always be emitted"
        u = usages[0]["usage"]
        assert u["estimated"] is True
        assert u["input_tokens"] > 0
        assert u["output_tokens"] > 0

    @pytest.mark.asyncio
    async def test_reported_usage_is_not_marked_estimated(self):
        from backend.providers.openai_compat_provider import OpenAICompatProvider

        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(text="hi"))]),
            _chunk(choices=[_choice(finish_reason="stop")]),
            _chunk(usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2)),
        ])
        provider = OpenAICompatProvider(api_key_env="X", client=client)

        events = await _drain(provider, [{"role": "user", "content": "hi"}])

        u = [e for e in events if e["type"] == "usage"][0]["usage"]
        assert u.get("estimated") is not True
        assert u["input_tokens"] == 7
