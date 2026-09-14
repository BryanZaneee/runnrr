"""Provider factory registry — maps model config to LLMProvider instances."""
from __future__ import annotations

import os

from runnrr.providers.base import LLMProvider
from runnrr.types import ModelConfig


class ProviderSetupError(RuntimeError):
    """Raised when a provider cannot be constructed from env + registry config."""


# Providers are stateless apart from their SDK client, so one instance per model
# is reusable. Before this, every chat turn built a fresh AsyncAnthropic /
# AsyncOpenAI / genai.Client with its own httpx pool -- a full TCP+TLS handshake
# per turn, and the pool was dropped to the GC rather than closed.
#
# Keyed by model_id only, because cfg is fully determined by it. Tests must call
# clear_provider_cache() between cases: the async SDK clients bind their
# transport to the event loop they are first used on, and FastAPI's TestClient
# runs each request through a fresh loop.
_PROVIDER_CACHE: dict[str, LLMProvider] = {}


def clear_provider_cache() -> None:
    """Drop cached providers. Called by an autouse test fixture."""
    _PROVIDER_CACHE.clear()


def _assert_capabilities_honorable(cfg: ModelConfig) -> None:
    """Raise if the config asks for something the resolved provider cannot do.

    If a provider cannot honor a field, fail with a stable error instead of
    silently dropping it. The live example: `thinking_budget` is read only on the
    Anthropic path, so setting it on a Gemini or OpenAI entry did nothing at all
    and nothing said so. Checked at construction time, so a misconfigured entry
    fails on the first request rather than degrading invisibly forever.
    """
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
