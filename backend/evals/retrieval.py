"""Retrieval evaluation: per-variant retrieval and deterministic retrieval records."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from backend.evals.datasets import RagCase
from backend.evals.graders import (
    grade_context_precision,
    grade_recall_at_k,
    reciprocal_rank,
)
from backend.evals.records import build_record, dedupe_paths, zero_tokens
from backend.kb_loader import search_kb
from backend.profiles import AgentProfile
from backend.rag.retriever import hybrid_candidate_pool, run_hybrid_query


class EvalCaseSkipped(Exception):
    """Raised when a variant cannot run (e.g. missing RAG index)."""


def retrieve(
    profile: AgentProfile,
    query: str,
    variant: str,
    k: int,
    *,
    embedding: Any,
    index_dir: Path | None,
    grader_model_id: str,
    rerank_fn: Callable[..., Any] | None,
) -> tuple[list[str], list[str], list[dict]]:
    if variant == "keyword":
        hits = search_kb(
            query,
            root=profile.kb_root,
            max_results=max(k * 4, 20),
        )
        paths = dedupe_paths([h["path"] for h in hits])
        retrieved = [
            {
                "path": h["path"],
                "line": h["line"],
                "snippet": h["context"],
            }
            for h in hits[:k]
        ]
        return paths, [], retrieved

    if variant in ("hybrid", "hybrid_rerank"):
        do_rerank = variant == "hybrid_rerank"
        pool = hybrid_candidate_pool(k, rerank=do_rerank)
        reranker = None
        if do_rerank:
            from backend.rag.reranker import LLMReranker

            reranker = LLMReranker(
                model_id=grader_model_id,
                complete_fn=rerank_fn,
            )
        try:
            results = run_hybrid_query(
                profile,
                query,
                pool=pool,
                rerank=do_rerank,
                embedding_provider=embedding,
                index_dir=index_dir,
                reranker=reranker,
            )
        except FileNotFoundError as exc:
            raise EvalCaseSkipped(str(exc)) from exc

        paths = dedupe_paths([r.chunk.path for r in results])
        chunk_ids = [r.chunk.chunk_id for r in results][:k]
        retrieved = [
            {
                "path": r.chunk.path,
                "start_line": r.chunk.start_line,
                "end_line": r.chunk.end_line,
                "score": r.score,
                "snippet": r.chunk.content[:400],
            }
            for r in results[:k]
        ]
        return paths, chunk_ids, retrieved

    raise ValueError(f"unknown retrieval variant: {variant}")


def retrieval_record(
    profile: AgentProfile,
    case: RagCase,
    variant: str,
    k: int,
    *,
    embedding: Any,
    index_dir: Path | None,
    grader_model_id: str,
    rerank_fn: Callable[..., Any] | None,
) -> dict:
    t0 = time.perf_counter()
    try:
        paths, chunk_ids, retrieved = retrieve(
            profile,
            case.query,
            variant,
            k,
            embedding=embedding,
            index_dir=index_dir,
            grader_model_id=grader_model_id,
            rerank_fn=rerank_fn,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        recall = grade_recall_at_k(
            paths, list(case.expected_chunk_paths), k=k
        ).score
        precision = grade_context_precision(
            paths, list(case.expected_chunk_paths), k=k
        ).score
        rr = reciprocal_rank(paths, list(case.expected_chunk_paths))
        metrics = {
            "recall_at_k": recall,
            "context_precision": precision,
            "reciprocal_rank": rr,
            "faithfulness": None,
            "answer_relevance": None,
            "answer_vs_ground_truth": None,
        }
        status = "ok"
        skip_reason = None
    except EvalCaseSkipped as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        paths, chunk_ids, retrieved = [], [], []
        metrics = {
            "recall_at_k": None,
            "context_precision": None,
            "reciprocal_rank": None,
            "faithfulness": None,
            "answer_relevance": None,
            "answer_vs_ground_truth": None,
        }
        status = "skipped"
        skip_reason = str(exc)

    return build_record(
        profile,
        run_id="",
        mode="retrieval-only",
        variant=variant,
        case=case,
        paths=paths,
        chunk_ids=chunk_ids,
        retrieved=retrieved,
        metrics=metrics,
        grader_reasoning={},
        answer="",
        tool_calls=[],
        latency_ms=latency_ms,
        tokens=zero_tokens(),
        status=status,
        k=k,
        skip_reason=skip_reason,
    )
