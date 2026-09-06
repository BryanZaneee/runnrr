from __future__ import annotations

import runnrr.rag.retriever as retriever_mod
from runnrr.rag.chunker import Chunk
from runnrr.rag.embeddings import FakeEmbeddingProvider
from runnrr.rag.reranker import RERANK_CANDIDATES
from runnrr.rag.retriever import (
    RetrievalResult,
    Retriever,
    hybrid_candidate_pool,
    reciprocal_rank_fusion,
    run_hybrid_query,
)


class StubIndex:
    def __init__(self, results):
        self.results = results

    def search(self, query, k: int = 5):  # noqa: ANN001
        return self.results[:k]


def _chunk(chunk_id: str, path: str, content: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        path=path,
        heading_path=(),
        start_line=1,
        end_line=1,
        content=content,
        tokens_est=1,
    )


def test_hybrid_candidate_pool_without_rerank_widens_to_k_times_four() -> None:
    assert hybrid_candidate_pool(1, rerank=False) == 4
    assert hybrid_candidate_pool(5, rerank=False) == 20
    # Defensive: non-positive k floors to 1 before widening.
    assert hybrid_candidate_pool(0, rerank=False) == 4


def test_hybrid_candidate_pool_with_rerank_uses_rerank_floor() -> None:
    assert hybrid_candidate_pool(1, rerank=True) == RERANK_CANDIDATES
    # A large k past the rerank floor still wins.
    assert hybrid_candidate_pool(RERANK_CANDIDATES + 10, rerank=True) == RERANK_CANDIDATES + 10


def test_reciprocal_rank_fusion_merges_sources_and_keeps_ranks() -> None:
    a = _chunk("a", "a.md", "alpha")
    b = _chunk("b", "b.md", "beta")
    c = _chunk("c", "c.md", "gamma")

    results = reciprocal_rank_fusion(
        bm25_results=[(a, 0.10), (b, 0.20)],
        vector_results=[(b, 0.01), (c, 0.02)],
        k=3,
        k_rrf=60,
    )

    assert [result.chunk.chunk_id for result in results] == ["b", "a", "c"]
    assert results[0].bm25_rank == 2
    assert results[0].vector_rank == 1
    assert results[0].bm25_score == 0.20
    assert results[0].vector_score == 0.01
    assert results[0].score > results[1].score


def test_retriever_queries_both_indexes() -> None:
    a = _chunk("a", "a.md", "portable profile retrieval")
    b = _chunk("b", "b.md", "customer service policy")
    retriever = Retriever(
        embedding_provider=FakeEmbeddingProvider(),
        bm25_index=StubIndex([(a, 0.1)]),
        vector_index=StubIndex([(b, 0.2)]),
    )

    results = retriever.search("portable profile", k=2)

    assert {result.chunk.chunk_id for result in results} == {"a", "b"}
    assert results[0].score > 0


def test_search_with_signals_matches_search_fused_and_exposes_embedding() -> None:
    a = _chunk("a", "a.md", "portable profile retrieval")
    b = _chunk("b", "b.md", "customer service policy")
    provider = FakeEmbeddingProvider()
    retriever = Retriever(
        embedding_provider=provider,
        bm25_index=StubIndex([(a, 0.1)]),
        vector_index=StubIndex([(b, 0.2)]),
    )

    signals = retriever.search_with_signals("portable profile", k=2)
    fused = retriever.search("portable profile", k=2)

    assert len(signals.query_embedding) == provider.dim
    assert [r.chunk.chunk_id for r in signals.fused] == [
        r.chunk.chunk_id for r in fused
    ]
    for key in ("embed_ms", "bm25_ms", "vector_ms"):
        assert key in signals.timings
        assert signals.timings[key] >= 0.0


class _RecordingRetriever:
    """Stand-in for a built Retriever; records the pool size it was queried with."""

    def __init__(self, results):
        self.results = results
        self.searched_k = None

    def search(self, query, *, k):  # noqa: ANN001
        self.searched_k = k
        return self.results


def test_run_hybrid_query_returns_full_pool_without_rerank(monkeypatch) -> None:
    pool_results = [
        RetrievalResult(chunk=_chunk("a", "a.md", "alpha"), score=0.9),
        RetrievalResult(chunk=_chunk("b", "b.md", "beta"), score=0.5),
    ]
    rec = _RecordingRetriever(pool_results)
    monkeypatch.setattr(retriever_mod, "get_retriever_for_profile", lambda profile, **kw: rec)

    out = run_hybrid_query(object(), "alpha", pool=7, rerank=False)

    # No truncation in the helper: the full pool comes back, queried at k=pool.
    assert out == pool_results
    assert rec.searched_k == 7


def test_run_hybrid_query_applies_injected_reranker(monkeypatch) -> None:
    pool_results = [
        RetrievalResult(chunk=_chunk("a", "a.md", "alpha"), score=0.9),
        RetrievalResult(chunk=_chunk("b", "b.md", "beta"), score=0.5),
        RetrievalResult(chunk=_chunk("c", "c.md", "gamma"), score=0.1),
    ]
    monkeypatch.setattr(
        retriever_mod,
        "get_retriever_for_profile",
        lambda profile, **kw: _RecordingRetriever(pool_results),
    )

    class FakeReranker:
        def __init__(self):
            self.top_k = None

        def rerank(self, query, results, top_k):  # noqa: ANN001
            self.top_k = top_k
            return list(reversed(results))[:top_k]

    fake = FakeReranker()
    out = run_hybrid_query(object(), "alpha", pool=3, rerank=True, reranker=fake)

    assert fake.top_k == 3
    assert [r.chunk.chunk_id for r in out] == ["c", "b", "a"]
