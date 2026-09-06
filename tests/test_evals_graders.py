"""Unit tests for eval graders (no network, no API keys)."""
from __future__ import annotations

import pytest

from runnrr.evals import graders


def test_dedupe_collapses_repeats_for_recall_and_precision():
    retrieved = ["a.md", "a.md", "b.md", "c.md"]
    expected = ["a.md", "x.md"]

    recall = graders.grade_recall_at_k(retrieved, expected, k=5)
    assert recall.score == pytest.approx(0.5)
    assert recall.reasoning == "1/2 expected paths in top-5"

    precision = graders.grade_context_precision(retrieved, expected, k=3)
    assert precision.score == pytest.approx(1 / 3)
    assert precision.reasoning == "1/3 retrieved paths in top-3 are expected"


def test_recall_two_of_three_expected():
    retrieved = ["p1.md", "p2.md", "noise.md", "other.md"]
    expected = ["p1.md", "p2.md", "missing.md"]

    result = graders.grade_recall_at_k(retrieved, expected, k=5)
    assert result.score == pytest.approx(2 / 3, rel=1e-3)
    assert result.reasoning == "2/3 expected paths in top-5"


def test_reciprocal_rank_second_position():
    retrieved = ["noise.md", "hit.md", "hit.md"]
    expected = ["hit.md"]
    assert graders.reciprocal_rank(retrieved, expected) == pytest.approx(0.5)


def test_empty_expected_recall_vacuous():
    result = graders.grade_recall_at_k(["a.md"], [], k=5)
    assert result.score == 1.0
    assert "vacuously" in result.reasoning


def test_empty_retrieved_precision_zero():
    result = graders.grade_context_precision([], ["a.md"], k=5)
    assert result.score == 0.0
    assert result.reasoning == "no retrieved context"


def test_llm_grader_injected_grade_fn():
    def fake(_prompt: str) -> dict:
        return {"score": 8, "reasoning": "ok"}

    result = graders.grade_faithfulness("ans", "ctx", grade_fn=fake)
    assert result.score == pytest.approx(0.8)
    assert result.reasoning == "ok"
    assert result.extra == {"score": 8, "reasoning": "ok"}


def test_score_clamp_and_missing_score():
    assert graders._score_from({"score": 99, "reasoning": "high"})[0] == pytest.approx(
        1.0
    )
    assert graders._score_from({}) == (0.0, "grader returned no score")
    assert graders._score_from("x") == (0.0, "grader returned no score")


def test_grade_answer_vs_ground_truth_empty():
    result = graders.grade_answer_vs_ground_truth("ans", "", grade_fn=lambda p: {})
    assert result.score == 0.0
    assert result.reasoning == "no ground truth"


def test_default_grade_fn_uses_complete_json(monkeypatch):
    calls: list[str] = []

    def fake_complete_json(prompt: str, **kwargs):
        calls.append(prompt)
        return {"score": 7, "reasoning": "patched"}

    monkeypatch.setattr("runnrr.llm_json.complete_json", fake_complete_json)

    result = graders.grade_faithfulness("my answer", "my context")
    assert result.score == pytest.approx(0.7)
    assert result.reasoning == "patched"
    assert len(calls) == 1
    assert "my answer" in calls[0]
    assert "my context" in calls[0]
