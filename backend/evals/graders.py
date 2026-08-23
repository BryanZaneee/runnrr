"""Deterministic retrieval graders and optional LLM rubric graders."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# One definition of order-preserving dedup; this logic used to live here
# byte-for-byte identically to the copy in records.py.
from backend.evals.records import dedupe_paths as _dedupe_keep_order

GRADER_SYSTEM = "You are a strict evaluation grader. Respond with one JSON object only."


@dataclass(frozen=True)
class GradeResult:
    score: float
    reasoning: str = ""
    extra: dict | None = None


def _top_k_deduped(retrieved_paths: list[str], k: int) -> list[str]:
    return _dedupe_keep_order(retrieved_paths)[:k]


def grade_recall_at_k(
    retrieved_paths: list[str],
    expected_paths: list[str],
    *,
    k: int = 5,
) -> GradeResult:
    """Recall@k: fraction of unique expected paths present in deduped top-k retrieved."""
    expected_unique = _dedupe_keep_order(list(expected_paths))
    if not expected_unique:
        return GradeResult(1.0, "no expected paths; vacuously satisfied")

    topk = _top_k_deduped(retrieved_paths, k)
    expected_set = set(expected_unique)
    hits = len(expected_set.intersection(topk))
    score = hits / len(expected_unique)
    return GradeResult(
        score,
        f"{hits}/{len(expected_unique)} expected paths in top-{k}",
    )


def grade_context_precision(
    retrieved_paths: list[str],
    expected_paths: list[str],
    *,
    k: int = 5,
) -> GradeResult:
    """Precision@k: relevant deduped retrieved paths / deduped top-k retrieved."""
    topk = _top_k_deduped(retrieved_paths, k)
    if not topk:
        return GradeResult(0.0, "no retrieved context")

    expected_set = set(_dedupe_keep_order(list(expected_paths)))
    hits = sum(1 for p in topk if p in expected_set)
    score = hits / len(topk)
    return GradeResult(
        score,
        f"{hits}/{len(topk)} retrieved paths in top-{k} are expected",
    )


def reciprocal_rank(
    retrieved_paths: list[str], expected_paths: list[str]
) -> float:
    """Reciprocal rank of the first relevant path in deduped retrieval order."""
    expected_set = set(_dedupe_keep_order(list(expected_paths)))
    if not expected_set:
        return 1.0

    for rank, path in enumerate(_dedupe_keep_order(retrieved_paths), start=1):
        if path in expected_set:
            return 1.0 / rank
    return 0.0


def _default_grade_fn(prompt: str) -> Any:
    from backend import config
    from backend.llm_json import complete_json

    return complete_json(
        prompt, model_id=config.GRADER_MODEL_ID, system=GRADER_SYSTEM
    )


def _score_from(raw: Any) -> tuple[float, str]:
    if not isinstance(raw, dict):
        return 0.0, "grader returned no score"
    score_val = raw.get("score")
    if not isinstance(score_val, (int, float)):
        return 0.0, "grader returned no score"
    normalized = max(0.0, min(1.0, float(score_val) / 10.0))
    reasoning = raw.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)
    return normalized, reasoning


def grade_faithfulness(
    answer: str,
    context: str,
    *,
    grade_fn: Callable[[str], Any] | None = None,
) -> GradeResult:
    """Is the answer supported by the retrieved context?"""
    gf = grade_fn or _default_grade_fn
    prompt = (
        "Rate whether the answer is fully supported by the context (0=no support, "
        "10=fully supported).\n"
        f'Context:\n"""\n{context}\n"""\n'
        f'Answer:\n"""\n{answer}\n"""\n'
        'Respond with JSON: {"score": <0-10>, "reasoning": "<brief>"}'
    )
    raw = gf(prompt)
    score, reasoning = _score_from(raw)
    return GradeResult(
        score, reasoning, extra=raw if isinstance(raw, dict) else None
    )


def grade_answer_relevance(
    answer: str,
    query: str,
    *,
    grade_fn: Callable[[str], Any] | None = None,
) -> GradeResult:
    """Does the answer address the query?"""
    gf = grade_fn or _default_grade_fn
    prompt = (
        "Rate how well the answer addresses the query (0=irrelevant, 10=fully "
        "addresses).\n"
        f'Query:\n"""\n{query}\n"""\n'
        f'Answer:\n"""\n{answer}\n"""\n'
        'Respond with JSON: {"score": <0-10>, "reasoning": "<brief>"}'
    )
    raw = gf(prompt)
    score, reasoning = _score_from(raw)
    return GradeResult(
        score, reasoning, extra=raw if isinstance(raw, dict) else None
    )


def grade_answer_vs_ground_truth(
    answer: str,
    ground_truth: str,
    *,
    grade_fn: Callable[[str], Any] | None = None,
) -> GradeResult:
    """Semantic match to the reference answer.

    If ``ground_truth`` is empty, returns score 0.0 with reasoning
    ``"no ground truth"`` so callers can treat the metric as N/A.
    """
    if not ground_truth.strip():
        return GradeResult(0.0, "no ground truth")

    gf = grade_fn or _default_grade_fn
    prompt = (
        "Rate semantic equivalence of the answer to the reference (0=no match, "
        "10=equivalent meaning).\n"
        f'Reference:\n"""\n{ground_truth}\n"""\n'
        f'Answer:\n"""\n{answer}\n"""\n'
        'Respond with JSON: {"score": <0-10>, "reasoning": "<brief>"}'
    )
    raw = gf(prompt)
    score, reasoning = _score_from(raw)
    return GradeResult(
        score, reasoning, extra=raw if isinstance(raw, dict) else None
    )
