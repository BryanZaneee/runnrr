"""RAG index summary helpers shared by API endpoints."""
from __future__ import annotations

from typing import Any

from backend.profiles import AgentProfile
from backend.rag.embeddings import EmbeddingProviderError
from backend.rag.manifest import ManifestError
from backend.rag.vector_index import VectorIndexDependencyError


def rag_index_payload(profile: AgentProfile) -> dict[str, Any]:
    """Return RAG index health for a profile, or a disabled reason."""
    if "semantic_search_kb" not in profile.tools:
        return {
            "profile_id": profile.id,
            "rag_enabled": False,
            "status": "disabled",
            "error_type": None,
            "message": "semantic_search_kb not in profile tool allowlist",
            "reason": "semantic_search_kb not in profile tool allowlist",
        }
    try:
        from backend.rag.indexer import Indexer

        info = Indexer(profile).info().to_dict()
        status = _status_from_info(info)
        message = str(info.get("stale_reason") or "index is current")
        return {
            "rag_enabled": True,
            "status": status,
            "error_type": "index_missing" if status == "missing" else None,
            "message": message,
            **info,
        }
    except ManifestError as exc:
        return _error_payload(profile, "invalid_manifest", exc)
    except EmbeddingProviderError as exc:
        return _error_payload(profile, "embedding_misconfigured", exc)
    except VectorIndexDependencyError as exc:
        return _error_payload(profile, "dependency_missing", exc)
    except Exception as exc:
        return _error_payload(profile, "unknown", exc)


def _status_from_info(info: dict[str, Any]) -> str:
    if not info.get("stale"):
        return "current"
    index_missing = (
        not info.get("manifest_exists")
        or not info.get("bm25_exists")
        or not info.get("vector_exists")
    )
    if index_missing:
        return "missing"
    return "stale"


def _error_payload(
    profile: AgentProfile,
    error_type: str,
    exc: Exception,
) -> dict[str, Any]:
    message = f"{type(exc).__name__}: {exc}"
    return {
        "profile_id": profile.id,
        "rag_enabled": True,
        "status": "error",
        "error_type": error_type,
        "message": message,
        "error": message,
    }
