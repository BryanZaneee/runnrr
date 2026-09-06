"""Hybrid BM25 + vector retrieval with plain Reciprocal Rank Fusion."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Protocol

from runnrr.profiles import AgentProfile
from runnrr.rag.bm25_index import BM25Index
from runnrr.rag.chunker import Chunk
from runnrr.rag.embeddings import EmbeddingProvider, get_embedding_provider
from runnrr.rag.indexer import (
    BM25_FILENAME,
    MANIFEST_FILENAME,
    VECTOR_FILENAME,
    default_index_dir,
)
from runnrr.rag.vector_index import VectorIndex

if TYPE_CHECKING:
    from runnrr.rag.reranker import LLMReranker

DEFAULT_RRF_K = 60
_INDEX_FINGERPRINT_FILES = (MANIFEST_FILENAME, BM25_FILENAME, VECTOR_FILENAME)


class SearchIndex(Protocol):
    def search(self, query, k: int = 5): ...


@dataclass(frozen=True)
class RetrievalResult:
    chunk: Chunk
    score: float
    bm25_score: float | None = None
    bm25_rank: int | None = None
    vector_score: float | None = None
    vector_rank: int | None = None


@dataclass(frozen=True)
class RetrievalSignals:
    query_embedding: list[float]
    bm25_results: list[tuple[Chunk, float]]
    vector_results: list[tuple[Chunk, float]]
    fused: list[RetrievalResult]
    timings: dict[str, float]


class Retriever:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        bm25_index: SearchIndex,
        vector_index: SearchIndex,
    ) -> None:
        self.embedding = embedding_provider
        self.bm25 = bm25_index
        self.vector = vector_index

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        candidate_k: int | None = None,
        k_rrf: int = DEFAULT_RRF_K,
    ) -> list[RetrievalResult]:
        return self.search_with_signals(
            query, k=k, candidate_k=candidate_k, k_rrf=k_rrf
        ).fused

    def search_with_signals(
        self,
        query: str,
        *,
        k: int = 5,
        candidate_k: int | None = None,
        k_rrf: int = DEFAULT_RRF_K,
    ) -> RetrievalSignals:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        k = max(1, int(k))
        candidate_k = max(k, int(candidate_k or k * 4))

        t0 = time.perf_counter()
        bm25_results = self.bm25.search(query, k=candidate_k)
        bm25_ms = round((time.perf_counter() - t0) * 1000, 1)

        t0 = time.perf_counter()
        query_embedding = self.embedding.embed_query(query)
        embed_ms = round((time.perf_counter() - t0) * 1000, 1)

        t0 = time.perf_counter()
        vector_results = self.vector.search(query_embedding, k=candidate_k)
        vector_ms = round((time.perf_counter() - t0) * 1000, 1)

        fused = reciprocal_rank_fusion(
            bm25_results=bm25_results,
            vector_results=vector_results,
            k=k,
            k_rrf=k_rrf,
        )
        return RetrievalSignals(
            query_embedding=query_embedding,
            bm25_results=bm25_results,
            vector_results=vector_results,
            fused=fused,
            timings={
                "embed_ms": embed_ms,
                "bm25_ms": bm25_ms,
                "vector_ms": vector_ms,
            },
        )

    def close(self) -> None:
        close = getattr(self.vector, "close", None)
        if callable(close):
            close()


@dataclass
class _FusionRow:
    chunk: Chunk
    score: float = 0.0
    bm25_score: float | None = None
    bm25_rank: int | None = None
    vector_score: float | None = None
    vector_rank: int | None = None


def reciprocal_rank_fusion(
    *,
    bm25_results: list[tuple[Chunk, float]],
    vector_results: list[tuple[Chunk, float]],
    k: int = 5,
    k_rrf: int = DEFAULT_RRF_K,
) -> list[RetrievalResult]:
    """Fuse ranked sparse and dense results using Reciprocal Rank Fusion."""
    by_id: dict[str, _FusionRow] = {}

    def add_source(source: str, results: list[tuple[Chunk, float]]) -> None:
        for rank, (chunk, raw_score) in enumerate(results, start=1):
            row = by_id.setdefault(chunk.chunk_id, _FusionRow(chunk=chunk))
            row.score += 1.0 / (k_rrf + rank)
            if source == "bm25":
                row.bm25_score = float(raw_score)
                row.bm25_rank = rank
            else:
                row.vector_score = float(raw_score)
                row.vector_rank = rank

    add_source("bm25", bm25_results)
    add_source("vector", vector_results)

    rows = sorted(
        by_id.values(),
        key=lambda row: (-row.score, row.chunk.path, row.chunk.start_line),
    )
    return [
        RetrievalResult(
            chunk=row.chunk,
            score=float(row.score),
            bm25_score=row.bm25_score,
            bm25_rank=row.bm25_rank,
            vector_score=row.vector_score,
            vector_rank=row.vector_rank,
        )
        for row in rows[: max(1, int(k))]
    ]


@dataclass(frozen=True)
class _RetrieverCacheKey:
    profile_id: str
    index_dir: str
    embedding_backend: str
    embedding_model: str
    embedding_dim: int
    fingerprint: tuple[tuple[str, int, int], ...]


_RETRIEVER_CACHE: dict[_RetrieverCacheKey, Retriever] = {}
_RETRIEVER_CACHE_LOCK = RLock()


def get_retriever_for_profile(
    profile: AgentProfile,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    index_dir: Path | None = None,
) -> Retriever:
    """Load the active profile's persisted indexes."""
    embedding = embedding_provider or get_embedding_provider()
    root = (index_dir or default_index_dir(profile)).resolve()
    manifest_path = root / MANIFEST_FILENAME
    bm25_path = root / BM25_FILENAME
    vector_path = root / VECTOR_FILENAME
    missing = [
        path.name
        for path in (manifest_path, bm25_path, vector_path)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"RAG index missing for profile {profile.id!r}; "
            f"missing {', '.join(missing)}; "
            f"run `python -m runnrr.rag.cli build {profile.id}`"
        )
    fingerprint = _index_fingerprint(root)
    key = _RetrieverCacheKey(
        profile_id=profile.id,
        index_dir=str(root),
        embedding_backend=embedding.backend,
        embedding_model=embedding.model,
        embedding_dim=embedding.dim,
        fingerprint=fingerprint,
    )
    with _RETRIEVER_CACHE_LOCK:
        cached = _RETRIEVER_CACHE.get(key)
        if cached is not None:
            return cached

    retriever = Retriever(
        embedding_provider=embedding,
        bm25_index=BM25Index.load(bm25_path),
        vector_index=VectorIndex(vector_path, dim=embedding.dim),
    )
    with _RETRIEVER_CACHE_LOCK:
        _evict_matching_locked(
            profile_id=profile.id,
            index_dir=str(root),
            keep_key=key,
        )
        _RETRIEVER_CACHE[key] = retriever
    return retriever


def hybrid_candidate_pool(k: int, *, rerank: bool) -> int:
    """Canonical candidate-pool size for hybrid retrieval.

    Shared by the ``semantic_search_kb`` tool and the eval runner so retrieval
    quality matches between production and metrics. With rerank enabled the pool
    is widened to ``RERANK_CANDIDATES`` so the reranker has enough to reorder;
    otherwise it tracks ``Retriever.search``'s ``k * 4`` candidate default.

    ``RERANK_CANDIDATES`` is imported lazily because runnrr.rag.reranker imports
    RetrievalResult from this module — a module-level import would close a cycle.
    """
    k = max(1, int(k))
    if rerank:
        from runnrr.rag.reranker import RERANK_CANDIDATES

        return max(k, RERANK_CANDIDATES)
    return max(k, k * 4)


def run_hybrid_query(
    profile: AgentProfile,
    query: str,
    *,
    pool: int,
    rerank: bool,
    embedding_provider: EmbeddingProvider | None = None,
    index_dir: Path | None = None,
    reranker: "LLMReranker | None" = None,
) -> list[RetrievalResult]:
    """Canonical hybrid retrieval (+ optional rerank) shared by the tool and evals.

    Returns the full candidate pool (length up to ``pool``); callers truncate to
    their own ``k``. Callers size ``pool`` via ``hybrid_candidate_pool`` rather
    than ad-hoc rules. ``reranker`` is injectable so the eval runner can pass a
    configured ``LLMReranker``; the tool uses the default.

    ``LLMReranker`` is imported lazily because runnrr.rag.reranker imports
    RetrievalResult from this module — a module-level import would close a cycle.
    """
    retriever = get_retriever_for_profile(
        profile,
        embedding_provider=embedding_provider,
        index_dir=index_dir,
    )
    results = retriever.search(query, k=pool)
    if rerank:
        from runnrr.rag.reranker import LLMReranker

        rk = reranker or LLMReranker()
        results = rk.rerank(query, results, top_k=pool)
    return results


def clear_retriever_cache(
    *,
    profile_id: str | None = None,
    index_dir: Path | None = None,
) -> None:
    """Close and remove cached retrievers, optionally scoped to one profile/index."""
    resolved_index_dir = str(index_dir.resolve()) if index_dir is not None else None
    with _RETRIEVER_CACHE_LOCK:
        for key in list(_RETRIEVER_CACHE):
            if profile_id is not None and key.profile_id != profile_id:
                continue
            if resolved_index_dir is not None and key.index_dir != resolved_index_dir:
                continue
            _RETRIEVER_CACHE.pop(key).close()


def _index_fingerprint(root: Path) -> tuple[tuple[str, int, int], ...]:
    parts = []
    for name in _INDEX_FINGERPRINT_FILES:
        stat = (root / name).stat()
        parts.append((name, stat.st_mtime_ns, stat.st_size))
    return tuple(parts)


def _evict_matching_locked(
    *,
    profile_id: str,
    index_dir: str,
    keep_key: _RetrieverCacheKey,
) -> None:
    for key in list(_RETRIEVER_CACHE):
        if key == keep_key:
            continue
        if key.profile_id == profile_id and key.index_dir == index_dir:
            _RETRIEVER_CACHE.pop(key).close()
