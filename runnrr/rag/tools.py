"""Tool-facing wrapper around the RAG retriever."""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runnrr import config
from runnrr.profiles import AgentProfile
from runnrr.tool_errors import ToolExecutionError

if TYPE_CHECKING:
    from runnrr.rag.embeddings import EmbeddingProvider
    from runnrr.tools.definitions import ToolDef

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
    context: "ToolContext | None" = None,
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

    # Imported lazily so runnrr.tools.registry can build this tool's schema
    # without pulling the RAG retrieval graph (embeddings/reranker/retriever)
    # at import time — only profiles that actually call the tool load it.
    from runnrr.rag.retriever import (
        get_retriever_for_profile,
        hybrid_candidate_pool,
        run_hybrid_query,
    )

    q = query.strip()
    pool = hybrid_candidate_pool(k, rerank=config.RERANK_ENABLED)
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
    if context is not None:
        context.scratch["rag_trace_results"] = results
        # Cached retriever (run_hybrid_query just built it); one SUM query.
        retriever = get_retriever_for_profile(
            profile, embedding_provider=embedding_provider, index_dir=index_dir
        )
        context.scratch["rag_trace_kb_tokens"] = retriever.vector.total_tokens()
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


def build_semantic_search_tool() -> "ToolDef":
    """Construct the ``semantic_search_kb`` ToolDef.

    Imports from ``runnrr.tools`` are deferred into this factory so that
    importing ``runnrr.rag.tools`` never triggers ``runnrr.tools.__init__``
    at module load. That keeps ``python -m runnrr.rag.cli`` (which imports
    ``runnrr.rag.tools`` first) free of the ``registry`` <-> ``rag.tools``
    circular import; ``runnrr.tools.registry`` calls this factory once its own
    imports are already in place.
    """
    from runnrr.tools.definitions import ToolDef
    from runnrr.tools.source_metadata import semantic_search_metadata

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
        handler=lambda args, ctx: semantic_search_kb(
            args["query"],
            k=args.get("k", 5),
            profile=ctx.profile,
            context=ctx,
        ),
        source_metadata=semantic_search_metadata,
    )
