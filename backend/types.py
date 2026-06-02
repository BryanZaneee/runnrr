"""Small shared runtime contracts for EasyAgent.

These types document the dictionaries that cross module boundaries. They are
kept intentionally narrow so runtime code can stay plain and provider-specific
details can remain inside provider adapters.
"""
from __future__ import annotations

from typing import Any, Literal, NotRequired, Required, TypeAlias, TypedDict


ProviderName = Literal["anthropic", "openai_compat", "gemini"]
ProviderMessage: TypeAlias = Any


class UsagePayload(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int


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


class AvailableModel(TypedDict):
    id: str
    label: str
    vendor: str
    provider: ProviderName
