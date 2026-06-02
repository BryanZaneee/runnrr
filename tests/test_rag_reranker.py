from __future__ import annotations

import pytest

from backend import config
from backend.profiles import AgentProfile
from backend.rag.chunker import chunk_markdown
from backend.rag.embeddings import FakeEmbeddingProvider
from backend.rag.indexer import Indexer
from backend.rag.reranker import LLMReranker, RERANK_CANDIDATES
from backend.rag.retriever import RetrievalResult
from backend.rag.tools import semantic_search_kb


def _results_from_markdown() -> list[RetrievalResult]:
    chunks = chunk_markdown(
        "doc.md",
        "# One\n\nFirst chunk about alpha.\n\n# Two\n\nSecond about beta.\n\n"
        "# Three\n\nThird about gamma.",
    )
    assert len(chunks) >= 3
    return [
        RetrievalResult(chunk=c, score=1.0 - i * 0.1) for i, c in enumerate(chunks[:3])
    ]


def test_rerank_reorders_by_injected_scores() -> None:
    results = _results_from_markdown()
    last_id = results[-1].chunk.chunk_id

    def complete_fn(_prompt: str) -> list[dict]:
        return [
            {"chunk_id": last_id, "relevance": 10},
            {"chunk_id": results[0].chunk.chunk_id, "relevance": 1},
            {"chunk_id": results[1].chunk.chunk_id, "relevance": 2},
        ]

    reranked = LLMReranker(complete_fn=complete_fn).rerank(
        "gamma topic", results, top_k=3
    )
    assert reranked[0].chunk.chunk_id == last_id
    assert len(reranked) == 3


def test_rerank_falls_back_on_complete_fn_error() -> None:
    results = _results_from_markdown()

    def boom(_prompt: str) -> list[dict]:
        raise RuntimeError("api down")

    out = LLMReranker(complete_fn=boom).rerank("q", results, top_k=3)
    assert [r.chunk.chunk_id for r in out] == [
        r.chunk.chunk_id for r in results[:3]
    ]


def test_rerank_falls_back_on_malformed_json() -> None:
    results = _results_from_markdown()

    def bad(_prompt: str) -> dict:
        return {"not": "an array"}

    out = LLMReranker(complete_fn=bad).rerank("q", results, top_k=3)
    assert [r.chunk.chunk_id for r in out] == [
        r.chunk.chunk_id for r in results[:3]
    ]


def test_rerank_respects_top_k() -> None:
    results = _results_from_markdown()
    extra = chunk_markdown("extra.md", "# X\n\nFourth chunk.\n")
    results = results + [
        RetrievalResult(chunk=extra[0], score=0.1),
    ]

    def complete_fn(_prompt: str) -> list[dict]:
        return [{"chunk_id": results[-1].chunk.chunk_id, "relevance": 10}]

    out = LLMReranker(complete_fn=complete_fn).rerank("q", results, top_k=2)
    assert len(out) == 2
    assert [r.chunk.chunk_id for r in out] == [
        r.chunk.chunk_id for r in results[:2]
    ]


def test_semantic_search_honors_rerank_enabled(tmp_path, monkeypatch) -> None:
    pytest.importorskip("sqlite_vec")
    from pathlib import Path
    import shutil

    mini = (Path(__file__).parent / "fixtures" / "mini_rag_kb").resolve()
    kb = tmp_path / "mini_rag_kb"
    shutil.copytree(mini, kb)
    index_root = tmp_path / "indexes"
    monkeypatch.setattr(config, "RAG_INDEX_ROOT", index_root)
    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "")
    profile = AgentProfile(
        id="mini",
        label="Mini",
        description="Mini",
        kb_root=kb,
        system_prompt="test",
        tools=("semantic_search_kb",),
    )
    Indexer(
        profile,
        FakeEmbeddingProvider(),
        index_dir=index_root / profile.id,
    ).build()

    monkeypatch.setattr(config, "RERANK_ENABLED", False)
    baseline_paths = [
        row["path"]
        for row in semantic_search_kb(
            "portable profile retrieval",
            k=3,
            profile=profile,
        )
    ]

    rerank_calls: list[int] = []

    class StubReranker:
        def rerank(self, query, results, *, top_k=RERANK_CANDIDATES):
            rerank_calls.append(len(results[:top_k]))
            return list(reversed(results[:top_k]))

    monkeypatch.setattr(config, "RERANK_ENABLED", True)
    # The tool now reranks via run_hybrid_query, which lazily imports LLMReranker
    # from its canonical module — patch there, not in backend.rag.tools.
    monkeypatch.setattr("backend.rag.reranker.LLMReranker", StubReranker)

    reranked_paths = [
        row["path"]
        for row in semantic_search_kb(
            "portable profile retrieval",
            k=3,
            profile=profile,
        )
    ]

    assert rerank_calls and rerank_calls[0] >= 3
    assert len(baseline_paths) >= 2
    assert reranked_paths != baseline_paths
