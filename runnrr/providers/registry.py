"""Provider factory registry — maps model config to LLMProvider instances."""

from __future__ import annotations

import os

from runnrr.providers.base import LLMProvider
from runnrr.types import ModelConfig


class ProviderSetupError(RuntimeError):
    """Raised when a provider cannot be constructed from env + registry config."""


# SDK clients belong to one event loop. Reuse them in the server; evals own
# separate clients and tests clear this cache between isolated loops.
_PROVIDER_CACHE: dict[str, LLMProvider] = {}


def clear_provider_cache() -> None:
    """Drop cached providers. Called by an autouse test fixture."""
    _PROVIDER_CACHE.clear()


def _assert_capabilities_honorable(cfg: ModelConfig) -> None:
    """Reject capabilities the configured adapter cannot honor."""
    if cfg.get("thinking_budget") and not cfg.get("supports_thinking", False):
        raise ProviderSetupError(
            f"CAPABILITY_UNSUPPORTED: {cfg['model']} declares no thinking support "
            "but a thinking_budget is configured"
        )
    if cfg.get("thinking_budget") and cfg["provider"] != "anthropic":
        raise ProviderSetupError(
            f"CAPABILITY_UNSUPPORTED: thinking_budget is only wired for the "
            f"anthropic provider, not {cfg['provider']} ({cfg['model']})"
        )


def build_provider(model_id: str, cfg: ModelConfig) -> LLMProvider:
    """Return a provider for one MODEL_REGISTRY entry, reusing its SDK client."""
    cached = _PROVIDER_CACHE.get(model_id)
    if cached is not None:
        return cached
    _assert_capabilities_honorable(cfg)
    provider = _construct_provider(cfg)
    _PROVIDER_CACHE[model_id] = provider
    return provider


def _construct_provider(cfg: ModelConfig) -> LLMProvider:
    """Build a fresh provider. Kept pure so construction stays directly testable."""
    provider = cfg["provider"]
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ProviderSetupError("missing ANTHROPIC_API_KEY")
        from runnrr.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(thinking_budget=cfg.get("thinking_budget"))

    if provider == "openai_compat":
        api_key_env = cfg["api_key_env"]
        if not os.environ.get(api_key_env):
            raise ProviderSetupError(f"missing {api_key_env}")
        from runnrr.providers.openai_compat_provider import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key_env=api_key_env,
            base_url=cfg.get("base_url"),
            token_param=cfg.get("token_param", "max_completion_tokens"),
            stream_options=cfg.get("stream_options", True),
            # Was inferred from the presence of a base_url -- a Moonshot quirk
            # accidentally applied to DeepSeek and every future custom endpoint.
            # Now declared per model.
            include_tool_result_name=bool(cfg.get("include_tool_result_name")),
            extra_body=cfg.get("extra_body"),
            reasoning_effort=cfg.get("reasoning_effort"),
            preserve_reasoning_content=bool(cfg.get("preserve_reasoning_content")),
        )

    if provider == "gemini":
        api_key_env = cfg["api_key_env"]
        if not os.environ.get(api_key_env):
            raise ProviderSetupError(f"missing {api_key_env}")
        from runnrr.providers.gemini_provider import GeminiProvider

        return GeminiProvider(api_key_env=api_key_env)

    raise ProviderSetupError(f"provider not implemented yet: {provider}")
