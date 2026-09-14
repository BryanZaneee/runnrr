"""Small shared runtime contracts for Runnrr.

These types document the dictionaries that cross module boundaries. They are
kept intentionally narrow so runtime code can stay plain and provider-specific
details can remain inside provider adapters.
"""
from __future__ import annotations

from typing import Any, Literal, NotRequired, Required, TypeAlias, TypedDict


ProviderName = Literal["anthropic", "openai_compat", "gemini"]
ProviderMessage: TypeAlias = Any


class UsagePayload(TypedDict, total=False):
    """Normalized per-hop token usage. Semantics are defined in runnrr/usage.py.

    `input_tokens` is the full prompt size; the two cache fields are subsets of
    it. `reasoning_tokens` is disjoint from `output_tokens`.
    """

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    # True when the WHOLE payload is a chars/4 fallback because the endpoint
    # reported no usage at all (see _estimate_usage in the OpenAI-compat provider).
    estimated: bool
    # True when only `reasoning_tokens` is approximate — Anthropic exposes no
    # per-block split, so it is apportioned by character length.
    reasoning_estimated: bool


class SessionDict(TypedDict):
    messages: list[ProviderMessage]
    last_seen: float
    provider: str
    profile: str


class BrandMetadata(TypedDict, total=False):
    accent: str
    accent_dark: str
    accent_soft: str
    accent_gold: str
    grid: str
    mark: str
    hero_icon: str
    intro_ascii_name: str
    input_placeholder: str


class ModelConfig(TypedDict):
    provider: Required[ProviderName]
    model: Required[str]
    label: Required[str]
    vendor: Required[str]
    api_key_env: NotRequired[str]
    base_url: NotRequired[str | None]
    token_param: NotRequired[str]
    stream_options: NotRequired[bool]
    thinking_budget: NotRequired[int]
    reasoning_effort: NotRequired[str]
    extra_body: NotRequired[dict[str, Any]]
    preserve_reasoning_content: NotRequired[bool]
    include_tool_result_name: NotRequired[bool]
    usage_unsupported: NotRequired[bool]
    # Capability metadata. Read when a request is constructed, so a capability we
    # cannot honor must RAISE rather than be silently dropped. Prices live in
    # runnrr/pricing.py instead, because a missing price must log null.
    context_window: NotRequired[int]
    max_output_tokens: NotRequired[int]
    supports_tools: NotRequired[bool]
    supports_thinking: NotRequired[bool]
    supports_caching: NotRequired[bool]
    supports_vision: NotRequired[bool]


class AvailableModel(TypedDict):
    id: str
    label: str
    vendor: str
    provider: ProviderName
