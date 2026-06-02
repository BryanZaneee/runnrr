from __future__ import annotations

from backend.rag.chunker import Chunk
from backend.rag.embeddings import FakeEmbeddingProvider
from backend.rag.retriever import Retriever, reciprocal_rank_fusion


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
