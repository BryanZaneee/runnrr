"""Per-model token prices, in USD per 1,000,000 tokens.

Deliberately separate from `MODEL_REGISTRY`. Capabilities are read when a
request is constructed and a missing one must *raise*; prices are read when a
turn is logged and a missing one must be *null*. Folding them into one dict
would force one failure mode onto both.

`cost_usd()` returns `None` for a model with no entry here. That is the point:
an unpriced model logs `cost_usd: null`, never `0.0`. A zero would read as
"this turn was free" and quietly under-report spend — the exact class of bug
this module exists to end.

Sources
-------
Anthropic list prices, and the standard cache multipliers (write = 1.25x input,
read = 0.1x input). DeepSeek publishes off-peak/peak rates that differ by 2x;
the off-peak figure is used here, so DeepSeek cost is a floor, not an exact.

Unpriced today: claude-opus-4-7, claude-sonnet-4-6, claude-opus-4-5,
claude-sonnet-4-5, kimi-k2.6, kimi-k2.6-thinking, gpt-5, gpt-5-mini, gpt-4.1,
gemini-2.5-pro, gemini-2.5-flash. Add them as their rates are confirmed — the
`test_unpriced_model_returns_none` test guards the null-not-zero contract while
the table fills in.
"""
from __future__ import annotations

from typing import Mapping, TypedDict


class ModelPrice(TypedDict):
    input: float
    output: float
    cache_read: float
    cache_write: float


def _anthropic(input_rate: float, output_rate: float) -> ModelPrice:
    """Anthropic bills cache writes at 1.25x input and cache reads at 0.1x."""
    return {
        "input": input_rate,
        "output": output_rate,
        "cache_write": input_rate * 1.25,
        "cache_read": input_rate * 0.10,
    }


PRICING: dict[str, ModelPrice] = {
    "claude-haiku-4-5": _anthropic(1.00, 5.00),
    # DeepSeek off-peak; peak (01:00-04:00 and 06:00-10:00 UTC) is 2x. No cache
    # write charge — the cache is implicit, so writes bill at the input rate.
    "deepseek-v4-flash": {
        "input": 0.22,
        "output": 0.66,
        "cache_read": 0.007,
        "cache_write": 0.22,
    },
}


def cost_usd(model_id: str, usage: Mapping[str, int]) -> float | None:
    """USD cost of one turn, or None when the model has no published entry.

    `usage` is a `runnrr.usage` accumulator: `input` is the full prompt size,
    with `cache_read` and `cache_write` as subsets of it, so the uncached
    remainder is what bills at the full input rate.
    """
    price = PRICING.get(model_id)
    if price is None:
        return None

    cache_read = int(usage.get("cache_read") or 0)
    cache_write = int(usage.get("cache_write") or 0)
    fresh_input = max(0, int(usage.get("input") or 0) - cache_read - cache_write)
    output = int(usage.get("output") or 0) + int(usage.get("reasoning") or 0)

    total = (
        fresh_input * price["input"]
        + cache_read * price["cache_read"]
        + cache_write * price["cache_write"]
        + output * price["output"]
    )
    return round(total / 1_000_000, 8)
