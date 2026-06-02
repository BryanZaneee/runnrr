"""Tool-facing wrapper around the RAG retriever."""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend import config
from backend.profiles import AgentProfile
from backend.rag.embeddings import EmbeddingProvider
from backend.rag.reranker import RERANK_CANDIDATES
from backend.rag.retriever import run_hybrid_query
from backend.tool_errors import ToolExecutionError

if TYPE_CHECKING:
    from backend.tools.definitions import ToolContext, ToolDef

SNIPPET_CHARS = 400


class SemanticSearchError(ToolExecutionError):
    """Raised when semantic_search_kb cannot run for the active profile."""


def semantic_search_kb(
    query: str,
    k: int = 5,
    *,
    profile: AgentProfile | None,
    embedding_provider: EmbeddingProvider | None = None,
    index_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Search the active profile's hybrid RAG index."""
    if profile is None:
        raise SemanticSearchError("semantic_search_kb requires an active profile")
    if not isinstance(query, str) or not query.strip():
        raise SemanticSearchError("query must be a non-empty string")
    try:
        k = max(1, min(int(k), 20))
    except (TypeError, ValueError) as exc:
        raise SemanticSearchError("k must be an integer") from exc

    q = query.strip()
    pool = max(k, RERANK_CANDIDATES) if config.RERANK_ENABLED else k
    try:
        results = run_hybrid_query(
            profile,
            q,
            pool=pool,
            rerank=config.RERANK_ENABLED,
            embedding_provider=embedding_provider,
            index_dir=index_dir,
        )[:k]
    except FileNotFoundError as exc:
        raise SemanticSearchError(str(exc)) from exc
    return [
        {
            "path": result.chunk.path,
            "heading_path": list(result.chunk.heading_path),
            "start_line": result.chunk.start_line,
            "end_line": result.chunk.end_line,
            "snippet": _snippet(result.chunk.content),
            "score": result.score,
        }
        for result in results
    ]


def _snippet(content: str) -> str:
    text = re.sub(r"\s+", " ", str(content)).strip()
    if len(text) <= SNIPPET_CHARS:
        return text
    return text[: SNIPPET_CHARS - 3].rstrip() + "..."


def _handle_semantic_search_kb(arguments: dict[str, Any], ctx: ToolContext) -> Any:
    return semantic_search_kb(
        arguments["query"],
        k=arguments.get("k", 5),
        profile=ctx.profile,
    )


def build_semantic_search_tool() -> "ToolDef":
    """Construct the ``semantic_search_kb`` ToolDef.

    Imports from ``backend.tools`` are deferred into this factory so that
    importing ``backend.rag.tools`` never triggers ``backend.tools.__init__``
    at module load. That keeps ``python -m backend.rag.cli`` (which imports
    ``backend.rag.tools`` first) free of the ``registry`` <-> ``rag.tools``
    circular import; ``backend.tools.registry`` calls this factory once its own
    imports are already in place.
    """
    from backend.tools.definitions import ToolDef
    from backend.tools.source_metadata import semantic_search_metadata

    return ToolDef(
        name="semantic_search_kb",
        description=(
            "Hybrid semantic search over the active profile's built RAG index. Use for "
            "conceptual questions or when you do not know the exact phrase to grep. "
            "Returns relevant markdown chunks with path and line ranges for follow-up "
            "read_file. This does not replace search_kb; use search_kb for exact "
            "substrings or regex."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum chunks to return. Default 5, hard cap 20.",
                },
            },
            "required": ["query"],
        },
        handler=_handle_semantic_search_kb,
        source_metadata=semantic_search_metadata,
    )
