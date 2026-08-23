"""Model capability declaration, and the provider divergences it exposes.

The theme: a capability we cannot honor must fail with a stable error rather
than disappear. Silent degradation is the worst failure mode for
interoperability, because the symptom shows up as "the model is worse" rather
than "the adapter dropped the field".
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.config import MODEL_REGISTRY, MAX_TOKENS, max_tokens_for
from backend.providers.registry import ProviderSetupError, build_provider

CAPABILITY_FLAGS = (
    "supports_tools",
    "supports_thinking",
    "supports_caching",
    "supports_vision",
)


class TestRegistryCompleteness:
    @pytest.mark.parametrize("model_id", sorted(MODEL_REGISTRY))
    def test_every_entry_declares_capabilities(self, model_id):
        """Guards the registry against rotting the moment a model is added."""
        cfg = MODEL_REGISTRY[model_id]
        for flag in CAPABILITY_FLAGS:
            assert flag in cfg, f"{model_id} does not declare {flag}"
            assert isinstance(cfg[flag], bool)
        assert cfg.get("context_window", 0) > 0
        assert cfg.get("max_output_tokens", 0) > 0

    def test_moonshot_quirk_is_declared_not_inferred(self):
        """`include_tool_result_name` used to be `bool(cfg.get("base_url"))`.

        That applied a Moonshot-specific quirk to DeepSeek and to every future
        custom OpenAI-compatible endpoint, by accident rather than by decision.
        """
        assert MODEL_REGISTRY["kimi-k2.6"].get("include_tool_result_name") is True
        assert not MODEL_REGISTRY["deepseek-v4-flash"].get("include_tool_result_name")


class TestMaxTokens:
    def test_per_model_cap_is_bounded_by_the_global(self):
        # The global stays a spend ceiling; raising one model's limit alone must
        # not blow up cost.
        for model_id in MODEL_REGISTRY:
            assert max_tokens_for(model_id) <= MAX_TOKENS

    def test_unknown_model_falls_back_to_the_global(self):
        assert max_tokens_for("not-a-model") == MAX_TOKENS


class TestNoSilentCapabilityLoss:
    def test_thinking_budget_on_a_non_thinking_model_raises(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "x")
        cfg = {
            **MODEL_REGISTRY["gemini-2.5-flash"],
            "thinking_budget": 2048,
        }
        with pytest.raises(ProviderSetupError) as exc:
            build_provider("synthetic-gemini-thinking", cfg)
        assert "CAPABILITY_UNSUPPORTED" in str(exc.value)

    def test_thinking_budget_on_an_unwired_provider_raises(self, monkeypatch):
        # thinking_budget is read only on the Anthropic path, so setting it
        # anywhere else did nothing and nothing said so.
        monkeypatch.setenv("OPENAI_API_KEY", "x")
        cfg = {
            **MODEL_REGISTRY["gpt-5"],
            "thinking_budget": 1024,
            "supports_thinking": True,
        }
        with pytest.raises(ProviderSetupError) as exc:
            build_provider("synthetic-openai-thinking", cfg)
        assert "CAPABILITY_UNSUPPORTED" in str(exc.value)

    def test_valid_config_still_builds(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
        assert build_provider(
            "claude-sonnet-4-5", MODEL_REGISTRY["claude-sonnet-4-5"]
        ) is not None


class TestGeminiCorrectness:
    """Gemini diverged from the other two on several counts. Each is now pinned."""

    def _usage(self, **kw):
        base = dict(
            prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0
        )
        base.update(kw)
        return SimpleNamespace(**base)

    @pytest.mark.asyncio
    async def test_max_tokens_finish_is_not_reported_as_a_clean_end(self):
        """A truncated answer used to look like a completed one.

        stop_reason was inferred from content alone, so MAX_TOKENS reported
        end_turn and the user saw a half-answer with no signal.
        """
        from tests.test_providers import (
            FakeGeminiClient,
            _drain_gemini,
            _gemini_chunk,
        )
        from backend.providers.gemini_provider import GeminiProvider

        chunk = _gemini_chunk(text="partial", finish_reason="MAX_TOKENS")
        provider = GeminiProvider(client=FakeGeminiClient([chunk]))

        events = await _drain_gemini(provider, [])
        done = [e for e in events if e["type"] == "message_done"]
        assert done[0]["stop_reason"] == "max_tokens"

    @pytest.mark.asyncio
    async def test_safety_finish_surfaces_an_error_event(self):
        from tests.test_providers import (
            FakeGeminiClient,
            _drain_gemini,
            _gemini_chunk,
        )
        from backend.providers.gemini_provider import GeminiProvider

        chunk = _gemini_chunk(text="", finish_reason="SAFETY")
        provider = GeminiProvider(client=FakeGeminiClient([chunk]))

        events = await _drain_gemini(provider, [])
        assert [e for e in events if e["type"] == "error"], "SAFETY must not look clean"

    @pytest.mark.asyncio
    async def test_normal_finish_still_ends_the_turn(self):
        from tests.test_providers import (
            FakeGeminiClient,
            _drain_gemini,
            _gemini_chunk,
        )
        from backend.providers.gemini_provider import GeminiProvider

        chunk = _gemini_chunk(text="all done", finish_reason="STOP")
        provider = GeminiProvider(client=FakeGeminiClient([chunk]))

        events = await _drain_gemini(provider, [])
        done = [e for e in events if e["type"] == "message_done"]
        assert done[0]["stop_reason"] == "end_turn"


class TestToolResultParityAcrossProviders:
    def test_all_three_show_the_model_the_same_string(self, monkeypatch):
        """Cross-model comparison is only valid if the input is identical.

        Gemini used to json.loads the tool content and re-wrap non-dicts, so the
        model saw a structurally different payload than on Anthropic or OpenAI
        for the very same tool — quietly invalidating any eval that compares
        models against each other.
        """
        from backend.providers.anthropic_provider import AnthropicProvider
        from backend.providers.gemini_provider import GeminiProvider
        from backend.providers.openai_compat_provider import OpenAICompatProvider
        from backend.tools.results import ToolResult

        payload = '{"hits": []}'
        result = ToolResult(tool_use_id="t1", name="search_kb", content=payload)

        anthropic_msgs: list = []
        AnthropicProvider.append_tool_results(
            AnthropicProvider.__new__(AnthropicProvider), anthropic_msgs, [result]
        )
        assert anthropic_msgs[0]["content"][0]["content"] == payload

        openai_msgs: list = []
        oc = OpenAICompatProvider.__new__(OpenAICompatProvider)
        oc.include_tool_result_name = False
        oc.append_tool_results(openai_msgs, [result])
        assert openai_msgs[0]["content"] == payload

        gemini_msgs: list = []
        GeminiProvider.append_tool_results(
            GeminiProvider.__new__(GeminiProvider), gemini_msgs, [result]
        )
        fr = gemini_msgs[0].parts[0].function_response
        assert fr.response == {"content": payload}


class TestToolUseStartParity:
    @pytest.mark.asyncio
    async def test_openai_emits_one_event_per_call(self):
        """Two calls to the same tool in one hop must announce twice.

        OpenAI and Gemini deduped by tool NAME, so identical work reported
        different counts depending on which provider ran it. Anthropic was
        already correct.
        """
        from tests.test_providers import (
            FakeOpenAIClient,
            _choice,
            _chunk,
            _delta,
            _drain,
            _tool_call,
        )
        from backend.providers.openai_compat_provider import OpenAICompatProvider

        client = FakeOpenAIClient([
            _chunk(choices=[_choice(delta=_delta(tool_calls=[
                _tool_call(index=0, id_="c1", name="read_file", args="{}"),
            ]))]),
            _chunk(choices=[_choice(delta=_delta(tool_calls=[
                _tool_call(index=1, id_="c2", name="read_file", args="{}"),
            ]))]),
            _chunk(choices=[_choice(finish_reason="tool_calls")]),
        ])
        provider = OpenAICompatProvider(api_key_env="X", client=client)

        events = await _drain(provider, [])
        starts = [e for e in events if e["type"] == "tool_use_start"]
        assert len(starts) == 2
