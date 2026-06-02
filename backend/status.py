"""Runtime status payloads for the local technical dashboard.

This module keeps the dashboard aggregation shape out of `backend.app`. The
individual `/api/health`, `/api/budget`, `/api/models`, and `/api/rag/index`
endpoints remain the stable public reads.
"""
from __future__ import annotations

from typing import Any

from backend import config


def runtime_status_payload(
    *,
    sessions: int,
    budget: dict[str, Any],
    registered_providers: set[str],
    native_tool_count: int,
) -> dict[str, Any]:
    """Return the dev-dashboard aggregate runtime snapshot."""
    available = [
        model
        for model in config.available_models()
        if model["provider"] in registered_providers
    ]
    return {
        "health": {"status": "ok", "sessions": sessions},
        "budget": budget,
        "defaults": {
            "profile": config.DEFAULT_PROFILE,
            "model": config.DEFAULT_MODEL,
        },
        "limits": {
            "max_tool_hops": config.MAX_TOOL_HOPS,
            "max_tokens": config.MAX_TOKENS,
            "session_ttl_seconds": config.SESSION_TTL,
            "max_active_sessions": config.MAX_ACTIVE_SESSIONS,
            "max_turns_per_session": config.MAX_TURNS_PER_SESSION,
            "rate_limit_chat": config.RATE_LIMIT_CHAT,
            "rate_limit_enabled": config.RATE_LIMIT_ENABLED,
        },
        "rag": {
            "embedding_backend": config.EMBEDDING_BACKEND,
            "embedding_model": config.EMBEDDING_MODEL or None,
        },
        "registry": {
            "providers": sorted(registered_providers),
            "native_tools": native_tool_count,
            "models_configured": len(config.MODEL_REGISTRY),
            "models_available": len(available),
        },
    }
