"""EasyAgent config — env loading + model registry.

Reads .env on import. KB_ROOT is the trust boundary for all KB tools.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from backend.types import AvailableModel, ModelConfig

load_dotenv()

KB_ROOT: Path = Path(os.environ.get("EASYAGENT_KB_ROOT", "./kb")).resolve()
PROFILE_ROOT: Path = Path(os.environ.get("EASYAGENT_PROFILE_ROOT", "./profiles")).resolve()

DEFAULT_PROFILE: str = os.environ.get("DEFAULT_PROFILE", "personal-agent")
DEFAULT_MODEL: str = os.environ.get("DEFAULT_MODEL", "claude-sonnet-4-5")
MAX_TOKENS: int = int(os.environ.get("MAX_TOKENS", "4096"))
MAX_TOOL_HOPS: int = int(os.environ.get("MAX_TOOL_HOPS", "8"))

SESSION_TTL: int = int(os.environ.get("SESSION_TTL_SECONDS", "1800"))
MAX_TURNS_PER_SESSION: int = int(os.environ.get("MAX_TURNS_PER_SESSION", "40"))
DAILY_TOKEN_BUDGET: int = int(os.environ.get("DAILY_TOKEN_BUDGET", "5000000"))
MAX_ACTIVE_SESSIONS: int = int(os.environ.get("MAX_ACTIVE_SESSIONS", "200"))

# Per-IP rate limit on POST /api/chat. slowapi syntax: "<count>/<period>" joined by ";".
RATE_LIMIT_CHAT: str = os.environ.get("RATE_LIMIT_CHAT", "10/minute;100/hour")
RATE_LIMIT_ENABLED: bool = os.environ.get("RATE_LIMIT_ENABLED", "1") == "1"

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
TOOL_DEBUG_ERRORS: bool = os.environ.get("EASYAGENT_TOOL_DEBUG_ERRORS", "0") == "1"

EMBEDDING_BACKEND: str = os.environ.get(
    "EASYAGENT_EMBEDDING_BACKEND", "voyage"
).strip().lower()
EMBEDDING_MODEL: str = os.environ.get("EASYAGENT_EMBEDDING_MODEL", "").strip()
VOYAGE_API_KEY: str = os.environ.get("VOYAGE_API_KEY", "").strip()
# Voyage free tier (no payment method) is ~3 req/min; use 8–16. Paid/default: 96.
EMBED_BATCH_SIZE: int = max(1, int(os.environ.get("EASYAGENT_EMBED_BATCH_SIZE", "96")))
_rag_index_root = os.environ.get("EASYAGENT_RAG_INDEX_ROOT", "").strip()
RAG_INDEX_ROOT: Path | None = (
    Path(_rag_index_root).expanduser().resolve() if _rag_index_root else None
)

GRADER_MODEL_ID: str = os.environ.get("EASYAGENT_GRADER_MODEL", "claude-haiku-4-5").strip()
ENABLE_EVALS_API: bool = os.environ.get("ENABLE_EVALS_API", "0") == "1"
RERANK_ENABLED: bool = os.environ.get("EASYAGENT_RERANK", "0") == "1"

ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# model_id -> {provider, model, label, [base_url], [api_key_env]}
# `model_id` is the public identifier sent by the frontend; `model` is what each provider's API expects.
MODEL_REGISTRY: dict[str, ModelConfig] = {
    "claude-opus-4-7": {
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "label": "Claude Opus 4.7",
        "vendor": "Anthropic",
        "thinking_budget": 2048,
    },
    "claude-sonnet-4-6": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6",
        "vendor": "Anthropic",
        "thinking_budget": 1500,
    },
    "claude-sonnet-4-5": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "label": "Claude Sonnet 4.5",
        "vendor": "Anthropic",
        "thinking_budget": 1500,
    },
    "claude-opus-4-5": {
        "provider": "anthropic",
        "model": "claude-opus-4-5",
        "label": "Claude Opus 4.5",
        "vendor": "Anthropic",
        "thinking_budget": 2048,
    },
    "claude-haiku-4-5": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "label": "Claude Haiku 4.5",
        "vendor": "Anthropic",
    },
    "kimi-k2.6": {
        "provider": "openai_compat",
        "model": "kimi-k2.6",
        "base_url": "https://api.moonshot.ai/v1",
        "api_key_env": "MOONSHOT_API_KEY",
        "token_param": "max_tokens",
        "stream_options": False,
        "label": "Kimi K2.6",
        "vendor": "Moonshot",
    },
    "kimi-k2.6-thinking": {
        "provider": "openai_compat",
        "model": "kimi-k2.6-thinking",
        "base_url": "https://api.moonshot.ai/v1",
        "api_key_env": "MOONSHOT_API_KEY",
        "token_param": "max_tokens",
        "stream_options": False,
        "label": "Kimi K2.6 Thinking",
        "vendor": "Moonshot",
    },
    "gpt-5": {
        "provider": "openai_compat",
        "model": "gpt-5",
        "base_url": None,  # default OpenAI
        "api_key_env": "OPENAI_API_KEY",
        "token_param": "max_completion_tokens",
        "stream_options": True,
        "label": "GPT-5",
        "vendor": "OpenAI",
    },
    "gpt-5-mini": {
        "provider": "openai_compat",
        "model": "gpt-5-mini",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
        "token_param": "max_completion_tokens",
        "stream_options": True,
        "label": "GPT-5 Mini",
        "vendor": "OpenAI",
    },
    "gpt-4.1": {
        "provider": "openai_compat",
        "model": "gpt-4.1",
        "base_url": None,
        "api_key_env": "OPENAI_API_KEY",
        "token_param": "max_completion_tokens",
        "stream_options": True,
        "label": "GPT-4.1",
        "vendor": "OpenAI",
    },
    "gemini-2.5-pro": {
        "provider": "gemini",
        "model": "gemini-2.5-pro",
        "api_key_env": "GEMINI_API_KEY",
        "label": "Gemini 2.5 Pro",
        "vendor": "Google",
    },
    "gemini-2.5-flash": {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "api_key_env": "GEMINI_API_KEY",
        "label": "Gemini 2.5 Flash",
        "vendor": "Google",
    },
    "deepseek-v4-flash": {
        "provider": "openai_compat",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "token_param": "max_tokens",
        "stream_options": True,
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}},
        "preserve_reasoning_content": True,
        "label": "DeepSeek V4 Flash",
        "vendor": "DeepSeek",
    },
}


def available_models() -> list[AvailableModel]:
    """Models whose required API key is present in env. Drives /api/models."""
    out: list[AvailableModel] = []
    for mid, cfg in MODEL_REGISTRY.items():
        if cfg["provider"] == "anthropic":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                continue
        elif cfg["provider"] in {"openai_compat", "gemini"}:
            if not os.environ.get(cfg["api_key_env"]):
                continue
        out.append(
            {"id": mid, "label": cfg["label"], "vendor": cfg["vendor"], "provider": cfg["provider"]}
        )
    return out
