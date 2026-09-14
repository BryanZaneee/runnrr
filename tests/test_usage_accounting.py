"""Token-accounting invariants.

These lock down the contract in runnrr/usage.py. Before it existed, the same
turn produced different totals depending on which consumer counted it, and
`cache_read` meant three different things depending on the provider.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from runnrr.config import MODEL_REGISTRY
from runnrr.pricing import PRICING, cost_usd
from runnrr.providers.anthropic_provider import _norm_usage as anthropic_usage
from runnrr.providers.gemini_provider import _norm_usage as gemini_usage
from runnrr.providers.openai_compat_provider import _norm_usage as openai_usage
from runnrr.usage import billable_total, tally, zero_tokens


class TestCacheSemantics:
    """`cache_read` must be a subset of `input_tokens` on every provider."""

    def test_anthropic_input_includes_cache(self):
        # Anthropic reports input_tokens EXCLUDING cache; we add it back so the
        # field means the same thing as it does on the other three.
        u = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=800,
            cache_creation_input_tokens=200,
        )
        got = anthropic_usage(u)
        assert got["input_tokens"] == 1100
        assert got["cache_read_input_tokens"] <= got["input_tokens"]
        assert got["cache_creation_input_tokens"] <= got["input_tokens"]

    def test_openai_input_already_includes_cache(self):
        u = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=50,
            prompt_cache_hit_tokens=800,
        )
        got = openai_usage(u)
        assert got["input_tokens"] == 1000
        assert got["cache_read_input_tokens"] == 800
        assert got["cache_read_input_tokens"] <= got["input_tokens"]

    def test_openai_reads_cached_tokens_detail(self):
        # OpenAI proper puts the hit count on prompt_tokens_details.cached_tokens.
        # It was never read, so every OpenAI cache hit logged as zero.
        u = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=50,
            prompt_tokens_details=SimpleNamespace(cached_tokens=640),
        )
        assert openai_usage(u)["cache_read_input_tokens"] == 640

    def test_gemini_cache_is_subset(self):
        u = SimpleNamespace(
            prompt_token_count=1000,
            candidates_token_count=20,
            thoughts_token_count=7,
            cached_content_token_count=300,
        )
        got = gemini_usage(u)
        assert got["cache_read_input_tokens"] <= got["input_tokens"]

    def test_anthropic_change_is_a_noop_without_caching(self):
        # cache_control is not sent yet, so Anthropic's cache fields are always
        # zero and this normalization must not move any existing number.
        u = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        assert anthropic_usage(u)["input_tokens"] == 100


class TestReasoningDisjointness:
    def test_anthropic_subtracts_reasoning_from_output(self):
        u = SimpleNamespace(input_tokens=10, output_tokens=100)
        got = anthropic_usage(u, thinking_tokens=30)
        assert got["output_tokens"] == 70
        assert got["reasoning_tokens"] == 30
        assert got["reasoning_estimated"] is True

    def test_anthropic_flags_estimate_only_when_present(self):
        u = SimpleNamespace(input_tokens=10, output_tokens=100)
        assert anthropic_usage(u, thinking_tokens=0)["reasoning_estimated"] is False

    def test_gemini_reasoning_disjoint_from_output(self):
        # Gemini's contract is total = prompt + candidates + thoughts, so thoughts
        # are ALREADY disjoint. Subtracting here (as the other two must) would
        # double-discount. This pins that Gemini is deliberately left alone.
        u = SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=20,
            thoughts_token_count=7,
        )
        got = gemini_usage(u)
        assert got["output_tokens"] == 20
        assert got["reasoning_tokens"] == 7

    def test_openai_subtracts_reasoning_from_output(self):
        u = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=100,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=40),
        )
        got = openai_usage(u)
        assert got["output_tokens"] == 60
        assert got["reasoning_tokens"] == 40


class TestReducer:
    def test_billable_total_charges_reasoning(self):
        # The old total was input + output only, so extended thinking was billed
        # by the vendor and free against DAILY_TOKEN_BUDGET.
        acc = tally(zero_tokens(), {
            "input_tokens": 100,
            "output_tokens": 50,
            "reasoning_tokens": 25,
        })
        assert billable_total(acc) == 175

    def test_billable_total_excludes_cache_fields(self):
        # They are subsets of input; adding them would double-count.
        acc = tally(zero_tokens(), {
            "input_tokens": 1000,
            "output_tokens": 10,
            "cache_read_input_tokens": 900,
            "cache_creation_input_tokens": 50,
        })
        assert billable_total(acc) == 1010

    def test_tally_accumulates_across_hops(self):
        acc = zero_tokens()
        tally(acc, {"input_tokens": 10, "output_tokens": 1})
        tally(acc, {"input_tokens": 20, "output_tokens": 2})
        assert acc["input"] == 30 and acc["output"] == 3


class TestPricing:
    def test_unpriced_model_returns_none_not_zero(self):
        # A 0.0 would read as "this turn was free" and under-report spend.
        acc = tally(zero_tokens(), {"input_tokens": 1_000_000, "output_tokens": 0})
        assert cost_usd("gpt-5", acc) is None

    def test_cache_read_is_cheaper_than_fresh_input(self):
        fresh = tally(zero_tokens(), {"input_tokens": 1_000_000})
        cached = tally(zero_tokens(), {
            "input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
        })
        assert cost_usd("claude-haiku-4-5", cached) < cost_usd("claude-haiku-4-5", fresh)

    def test_reasoning_billed_at_output_rate(self):
        acc = tally(zero_tokens(), {"input_tokens": 0, "reasoning_tokens": 1_000_000})
        assert cost_usd("claude-haiku-4-5", acc) == pytest.approx(5.00)

    def test_every_price_entry_names_a_real_model(self):
        unknown = set(PRICING) - set(MODEL_REGISTRY)
        assert not unknown, f"pricing entries for unregistered models: {unknown}"


class TestRegistryUsageReporting:
    def test_no_model_silently_disables_usage(self):
        """A model that reports no usage spends unmetered budget.

        Kimi did exactly this via `stream_options: False`. Usage may only be
        disabled with an explicit `usage_unsupported` marker, so silence is
        always a declared choice rather than an accident.
        """
        offenders = [
            mid
            for mid, cfg in MODEL_REGISTRY.items()
            if cfg.get("stream_options") is False and not cfg.get("usage_unsupported")
        ]
        assert not offenders, f"models with usage silently off: {offenders}"
