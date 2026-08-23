"""Canonical token-usage semantics for the whole engine.

Every provider's `_norm_usage` must satisfy these invariants, and every consumer
must read them the same way. Before this module the rules were implicit and two
consumers disagreed, so the same turn produced different totals depending on who
counted it.

The contract
------------
``input_tokens``
    The FULL prompt size, cached portions included.

``cache_read_input_tokens`` / ``cache_creation_input_tokens``
    SUBSETS of ``input_tokens`` — never independent addends. Three of the four
    vendors already report it this way (OpenAI ``cached_tokens``, Gemini
    ``cached_content_token_count``, DeepSeek ``prompt_cache_hit_tokens``);
    Anthropic is the outlier and is normalized to match in its provider.

``reasoning_tokens``
    DISJOINT from ``output_tokens``. Anthropic and OpenAI subtract it out
    because their APIs roll it into output; Gemini's ``thoughts_token_count`` is
    already separate from ``candidates_token_count``, so it is left alone.

``reasoning_estimated``
    True when ``reasoning_tokens`` was inferred rather than measured. Only
    Anthropic sets it — the API exposes no per-block split, so the provider
    apportions by character length. Consumers that need exactness must check it.

Billing
-------
A turn costs ``input + output + reasoning``. Cache fields are excluded from the
total precisely because they are subsets of input; adding them double-counts.
"""
from __future__ import annotations

from typing import Mapping


def zero_tokens() -> dict[str, int]:
    """A fresh accumulator. Keys are stable — they are persisted in eval records."""
    return {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write": 0,
        "reasoning": 0,
    }


def tally(acc: dict[str, int], usage: Mapping) -> dict[str, int]:
    """Fold one `usage` event (or raw UsagePayload) into `acc`, in place."""
    acc["input"] += int(usage.get("input_tokens") or 0)
    acc["output"] += int(usage.get("output_tokens") or 0)
    acc["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
    acc["cache_write"] += int(usage.get("cache_creation_input_tokens") or 0)
    acc["reasoning"] += int(usage.get("reasoning_tokens") or 0)
    return acc


def billable_total(acc: Mapping[str, int]) -> int:
    """Tokens charged against the budget. Cache fields are subsets of input."""
    return (
        int(acc.get("input") or 0)
        + int(acc.get("output") or 0)
        + int(acc.get("reasoning") or 0)
    )
