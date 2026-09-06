"""Eval API endpoint tests — gated by ENABLE_EVALS_API."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _write_eval_profile_tree(
    profiles_root: Path,
    *,
    profile_id: str = "eval-api-test",
    run_id: str = "2026-06-01T12-00-00Z",
) -> Path:
    kb_root = profiles_root.parent / "kb" / profile_id
    kb_root.mkdir(parents=True, exist_ok=True)
    (kb_root / "note.md").write_text("# Note\n\nFixture.\n", encoding="utf-8")

    prof_dir = profiles_root / profile_id
    prof_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": profile_id,
                "label": "Eval API Test",
                "description": "eval endpoint fixture",
                "kb_root": str(kb_root),
                "tools": ["semantic_search_kb"],
            }
        ),
        encoding="utf-8",
    )
    (prof_dir / "system.md").write_text("Test profile.", encoding="utf-8")

    run_dir = prof_dir / "evals" / "runs" / run_id
    run_dir.mkdir(parents=True)
    summary = {
        "schema": 1,
        "run_id": run_id,
        "created_at": "2026-06-01T12:00:00+00:00",
        "profile_id": profile_id,
        "mode": "retrieval_only",
        "variants": ["keyword", "hybrid"],
        "model_id": None,
        "embedding": {},
        "index": {},
        "n_cases": 1,
        "per_variant": {
            "keyword": {
                "recall_at_5": 0.5,
                "context_precision": 0.6,
                "mrr": 0.5,
                "faithfulness": None,
                "answer_relevance": None,
                "latency_ms_avg": 10.0,
                "tokens_total": 0,
                "n_ok": 1,
                "n_skipped": 0,
            },
            "hybrid": {
                "recall_at_5": 1.0,
                "context_precision": 0.9,
                "mrr": 1.0,
                "faithfulness": None,
                "answer_relevance": None,
                "latency_ms_avg": 12.0,
                "tokens_total": 0,
                "n_ok": 1,
                "n_skipped": 0,
            },
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    record = {
        "schema": 1,
        "run_id": run_id,
        "profile_id": profile_id,
        "mode": "retrieval_only",
        "variant": "hybrid",
        "case_id": "case-1",
        "query": "test query",
        "expected_chunk_paths": ["note.md"],
        "retrieved_paths": ["note.md"],
        "retrieved_chunk_ids": ["note.md:1"],
        "retrieved": [
            {
                "path": "note.md",
                "start_line": 1,
                "end_line": 2,
                "score": 0.9,
                "snippet": "Fixture.",
            }
        ],
        "metrics": {
            "recall_at_5": 1.0,
            "context_precision": 1.0,
            "reciprocal_rank": 1.0,
            "faithfulness": None,
            "answer_relevance": None,
            "answer_vs_ground_truth": None,
        },
        "grader_reasoning": "",
        "answer": "",
        "tool_calls": [],
        "latency_ms": 12,
        "tokens": {},
        "status": "ok",
        "failure_label": None,
    }
    (run_dir / "records.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return profiles_root


@pytest.fixture
def evals_enabled_client(client, tmp_path, monkeypatch):
    """Client with eval API enabled and an isolated profile tree."""
    c, app_module = client
    from runnrr import config
    from runnrr import profiles as profiles_module

    profile_id = "eval-api-test"
    profiles_root = tmp_path / "profiles"
    _write_eval_profile_tree(profiles_root, profile_id=profile_id)

    monkeypatch.setattr(config, "ENABLE_EVALS_API", True)
    monkeypatch.setattr(config, "PROFILE_ROOT", profiles_root)
    monkeypatch.setattr(profiles_module, "PROFILE_ROOT", profiles_root)
    monkeypatch.setattr(app_module, "PROFILE_ROOT", profiles_root)
    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
    monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")

    return c, profile_id, "2026-06-01T12-00-00Z"


class TestEvalsApiEnabled:
    def test_list_runs(self, evals_enabled_client):
        c, profile_id, run_id = evals_enabled_client
        r = c.get(f"/api/evals/runs/{profile_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["profile_id"] == profile_id
        assert len(body["runs"]) == 1
        assert body["runs"][0]["run_id"] == run_id

    def test_read_run(self, evals_enabled_client):
        c, profile_id, run_id = evals_enabled_client
        r = c.get(f"/api/evals/run/{profile_id}/{run_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["summary"]["run_id"] == run_id
        assert len(body["records"]) == 1
        assert body["records"][0]["case_id"] == "case-1"

    def test_read_run_rejects_traversal(self, evals_enabled_client):
        c, profile_id, _run_id = evals_enabled_client
        for bad_id in ("..%2f..", "../x", "..", "."):
            r = c.get(f"/api/evals/run/{profile_id}/{bad_id}")
            assert r.status_code == 404

    def test_index_status(self, evals_enabled_client):
        c, profile_id, _run_id = evals_enabled_client
        r = c.get(f"/api/evals/index-status/{profile_id}")
        assert r.status_code == 200
        body = r.json()
        assert "rag_enabled" in body
        assert body["rag_enabled"] is True


class TestEvalsApiDisabled:
    def test_endpoints_hidden_when_flag_off(self, client):
        c, _ = client
        profile_id = "personal-agent"
        run_id = "any-run"
        endpoints = [
            f"/api/evals/runs/{profile_id}",
            f"/api/evals/run/{profile_id}/{run_id}",
            f"/api/evals/index-status/{profile_id}",
        ]
        for path in endpoints:
            r = c.get(path)
            assert r.status_code == 404, path
