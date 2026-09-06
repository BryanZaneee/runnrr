"""Eval runner tests — deterministic, no network (fake embeddings + injected providers)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from runnrr.evals.datasets import RagCase, RagDataset
from runnrr.evals.runner import RAGEvaluator
from runnrr.profiles import AgentProfile
from runnrr.providers.base import Event
from runnrr.rag.embeddings import FakeEmbeddingProvider
from runnrr.rag.indexer import Indexer
from tests.conftest import FakeProvider

MINI_RAG_FIXTURE = (Path(__file__).parent / "fixtures" / "mini_rag_kb").resolve()


@pytest.fixture
def sqlite_vec_available():
    pytest.importorskip("sqlite_vec")


@pytest.fixture
def mini_rag_env(sqlite_vec_available, tmp_path, monkeypatch):
    kb = tmp_path / "mini_rag_kb"
    shutil.copytree(MINI_RAG_FIXTURE, kb)
    index_dir = tmp_path / "indexes" / "mini"
    runs_root = tmp_path / "runs"
    monkeypatch.setenv("RUNNRR_EMBEDDING_BACKEND", "fake")
    import importlib
    from runnrr import config

    importlib.reload(config)
    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
    monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")

    profile = AgentProfile(
        id="mini-eval",
        label="Mini Eval",
        description="Eval fixture profile",
        kb_root=kb,
        system_prompt="test",
        tools=("list_kb", "read_file", "search_kb", "semantic_search_kb"),
    )
    provider = FakeEmbeddingProvider()
    Indexer(profile, provider, index_dir=index_dir).build(force=True)

    dataset = RagDataset(
        profile_id="mini-eval",
        cases=(
            RagCase(
                id="alpha-retrieval",
                query="portable profile tool registry",
                expected_chunk_paths=("projects/alpha.md",),
                ground_truth_answer="",
            ),
            RagCase(
                id="alpha-e2e",
                query="What is Project Alpha?",
                expected_chunk_paths=("projects/alpha.md",),
                ground_truth_answer="A portable agent framework.",
            ),
        ),
    )
    return {
        "profile": profile,
        "dataset": dataset,
        "embedding": provider,
        "index_dir": index_dir,
        "runs_root": runs_root,
    }


def test_run_retrieval_only_writes_artifacts_and_hybrid_recall(mini_rag_env) -> None:
    evaluator = RAGEvaluator(
        mini_rag_env["profile"],
        embedding_provider=mini_rag_env["embedding"],
        index_dir=mini_rag_env["index_dir"],
        runs_root=mini_rag_env["runs_root"],
    )
    result = evaluator.run_retrieval_only(
        mini_rag_env["dataset"],
        variants=("keyword", "hybrid"),
        k=5,
    )

    assert (result.run_dir / "records.jsonl").is_file()
    assert (result.run_dir / "summary.json").is_file()

    hybrid_records = [r for r in result.records if r["variant"] == "hybrid"]
    assert hybrid_records
    assert hybrid_records[0]["status"] == "ok"
    assert hybrid_records[0]["metrics"]["recall_at_k"] > 0

    summary_hybrid = result.summary["per_variant"]["hybrid"]
    assert summary_hybrid["recall_at_k"] is not None
    assert summary_hybrid["n_ok"] >= 1


def test_run_end_to_end_with_fake_provider_and_graders(mini_rag_env) -> None:
    def provider_factory(_model_id: str) -> FakeProvider:
        return FakeProvider(
            scripted_turns=[
                [
                    {
                        "type": "tool_use_start",
                        "name": "semantic_search_kb",
                        "tool_use_id": "tu_1",
                    },
                    {
                        "type": "tool_use_complete",
                        "name": "semantic_search_kb",
                        "tool_use_id": "tu_1",
                        "arguments": {"query": "alpha"},
                    },
                    {"type": "message_done", "stop_reason": "tool_use"},
                    {
                        "type": "usage",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "cache_read_input_tokens": 0,
                            "reasoning_tokens": 0,
                        },
                    },
                ],
                [
                    {"type": "text_delta", "text": "Project Alpha is a portable framework."},
                    {"type": "message_done", "stop_reason": "end_turn"},
                    {
                        "type": "usage",
                        "usage": {
                            "input_tokens": 20,
                            "output_tokens": 12,
                            "cache_read_input_tokens": 1,
                            "reasoning_tokens": 2,
                        },
                    },
                ],
            ]
        )

    grade_fn = lambda prompt: {"score": 9, "reasoning": "ok"}  # noqa: E731

    evaluator = RAGEvaluator(
        mini_rag_env["profile"],
        embedding_provider=mini_rag_env["embedding"],
        index_dir=mini_rag_env["index_dir"],
        runs_root=mini_rag_env["runs_root"],
        provider_factory=provider_factory,
        grade_fn=grade_fn,
    )
    e2e_dataset = RagDataset(
        profile_id="mini-eval",
        cases=(mini_rag_env["dataset"].cases[1],),
    )
    result = evaluator.run_end_to_end(
        e2e_dataset, variant="hybrid", model_id="claude-haiku-4-5"
    )

    record = result.records[0]
    assert "portable framework" in record["answer"]
    assert "semantic_search_kb" in record["tool_calls"]
    assert record["metrics"]["faithfulness"] == pytest.approx(0.9)
    assert record["metrics"]["answer_vs_ground_truth"] == pytest.approx(0.9)

    no_gt_dataset = RagDataset(
        profile_id="mini-eval",
        cases=(mini_rag_env["dataset"].cases[0],),
    )
    result2 = evaluator.run_end_to_end(
        no_gt_dataset, variant="hybrid", model_id="claude-haiku-4-5"
    )
    assert result2.records[0]["metrics"]["answer_vs_ground_truth"] is None


def test_records_jsonl_roundtrip(mini_rag_env) -> None:
    evaluator = RAGEvaluator(
        mini_rag_env["profile"],
        embedding_provider=mini_rag_env["embedding"],
        index_dir=mini_rag_env["index_dir"],
        runs_root=mini_rag_env["runs_root"],
    )
    result = evaluator.run_retrieval_only(
        mini_rag_env["dataset"],
        variants=("keyword",),
        k=5,
    )
    lines = (result.run_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines if line.strip()]
    assert len(parsed) == len(mini_rag_env["dataset"].cases)
    assert parsed[0]["schema"] == 1
