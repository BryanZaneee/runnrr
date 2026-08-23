"""Provider factory registry — maps model config to LLMProvider instances."""
from __future__ import annotations

import os

from backend.providers.base import LLMProvider
from backend.types import ModelConfig


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


def build_provider(model_id: str, cfg: ModelConfig) -> LLMProvider:
    """Return a provider for one MODEL_REGISTRY entry, reusing its SDK client."""
    cached = _PROVIDER_CACHE.get(model_id)
    if cached is not None:
        return cached
    provider = _construct_provider(cfg)
    _PROVIDER_CACHE[model_id] = provider
    return provider


def _construct_provider(cfg: ModelConfig) -> LLMProvider:
    """Build a fresh provider. Kept pure so construction stays directly testable."""
    provider = cfg["provider"]
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ProviderSetupError("missing ANTHROPIC_API_KEY")
        from backend.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(thinking_budget=cfg.get("thinking_budget"))

    if provider == "openai_compat":
        api_key_env = cfg["api_key_env"]
        if not os.environ.get(api_key_env):
            raise ProviderSetupError(f"missing {api_key_env}")
        from backend.providers.openai_compat_provider import OpenAICompatProvider

        return OpenAICompatProvider(
            api_key_env=api_key_env,
            base_url=cfg.get("base_url"),
            token_param=cfg.get("token_param", "max_completion_tokens"),
            stream_options=cfg.get("stream_options", True),
            include_tool_result_name=bool(cfg.get("base_url")),
            extra_body=cfg.get("extra_body"),
            reasoning_effort=cfg.get("reasoning_effort"),
            preserve_reasoning_content=bool(cfg.get("preserve_reasoning_content")),
        )

    if provider == "gemini":
        api_key_env = cfg["api_key_env"]
        if not os.environ.get(api_key_env):
            raise ProviderSetupError(f"missing {api_key_env}")
        from backend.providers.gemini_provider import GeminiProvider

        return GeminiProvider(api_key_env=api_key_env)

    raise ProviderSetupError(f"provider not implemented yet: {provider}")
