"""Runtime, budget, and RAG health endpoint tests."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi.testclient import TestClient

from runnrr.profiles import AgentProfile
from runnrr.providers.base import Event
from runnrr.tools import SCHEMAS, ToolResult


class _LoopFake:
    """Provider that emits the same canned turn for repeated chat requests."""

    def __init__(self, turn: list[Event]) -> None:
        self.turn = turn

    async def stream(self, **kwargs: Any) -> AsyncIterator[Event]:
        kwargs["messages"].append({"role": "assistant", "content": "<scripted>"})
        for ev in self.turn:
            yield ev

    def format_user(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def append_tool_results(self, messages: list, results: list[ToolResult]) -> None:
        messages.append({"role": "user", "content": [r.tool_use_id for r in results]})

    def tools_for_provider(self, profile: AgentProfile) -> list[dict]:
        return SCHEMAS

    def system_for_provider(self, profile: AgentProfile) -> Any:
        return "test-system"


def _stale_warn_profile_tree(
    tmp_path: Path,
    *,
    profile_id: str = "stale-warn",
) -> tuple[Path, AgentProfile]:
    """Minimal on-disk profile for warn_stale_indexes() tests."""
    profiles_root = tmp_path / "profiles"
    kb_root = tmp_path / profile_id / "kb"
    kb_root.mkdir(parents=True)
    (kb_root / "note.md").write_text(
        "# Note\n\nSemantic retrieval fixture.\n",
        encoding="utf-8",
    )
    prof_dir = profiles_root / profile_id
    prof_dir.mkdir(parents=True)
    (prof_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": profile_id,
                "label": "Stale Warn",
                "description": "startup staleness warning test",
                "kb_root": str(kb_root),
                "tools": ["semantic_search_kb"],
            }
        ),
        encoding="utf-8",
    )
    (prof_dir / "system.md").write_text("Test profile.", encoding="utf-8")
    from runnrr.profiles import load_profile

    return profiles_root, load_profile(profile_id, profile_root=profiles_root)


def _rag_profile(tmp_path: Path, *, profile_id: str = "rag-dash") -> AgentProfile:
    kb_root = tmp_path / profile_id / "kb"
    kb_root.mkdir(parents=True)
    (kb_root / "note.md").write_text(
        "# Note\n\nSemantic retrieval fixture.\n",
        encoding="utf-8",
    )
    return AgentProfile(
        id=profile_id,
        label="RAG Dash",
        description="dashboard test profile",
        kb_root=kb_root,
        system_prompt="Test profile.",
        tools=("semantic_search_kb",),
    )


class TestRuntimeStatus:
    def test_budget_endpoint_reports_stats(self, client):
        c, _ = client
        r = c.get("/api/budget")
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] > 0
        assert body["used"] >= 0
        assert body["remaining"] >= 0
        assert "date" in body

    def test_status_endpoint_reports_runtime(self, client):
        c, _ = client
        r = c.get("/api/status")
        assert r.status_code == 200
        body = r.json()
        assert body["health"]["status"] == "ok"
        assert "sessions" in body["health"]
        assert body["budget"]["limit"] > 0
        assert "defaults" in body
        assert "limits" in body
        assert "registry" in body
        assert body["registry"]["native_tools"] > 0


class TestRagIndexStatus:
    def test_rag_index_endpoint_for_non_rag_profile(self, client):
        c, _ = client
        r = c.get("/api/rag/index", params={"profile_id": "research-analyst"})
        assert r.status_code == 200
        body = r.json()
        assert body["rag_enabled"] is False
        assert body["status"] == "disabled"
        assert body["error_type"] is None
        assert body["message"] == body["reason"]

    def test_rag_index_endpoint_for_missing_index(self, client, tmp_path, monkeypatch):
        c, app_module = client
        from runnrr import config

        profile = _rag_profile(tmp_path, profile_id="missing-rag")
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
        monkeypatch.setattr(app_module, "get_profile", lambda profile_id="missing-rag": profile)

        r = c.get("/api/rag/index", params={"profile_id": "missing-rag"})

        assert r.status_code == 200
        body = r.json()
        assert body["rag_enabled"] is True
        assert body["status"] == "missing"
        assert body["error_type"] == "index_missing"
        assert body["message"] == "manifest missing"
        assert body["manifest_exists"] is False

    def test_rag_index_endpoint_for_current_index(self, client, tmp_path, monkeypatch):
        c, app_module = client
        from runnrr import config
        from runnrr.rag.indexer import Indexer

        profile = _rag_profile(tmp_path, profile_id="current-rag")
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
        monkeypatch.setattr(app_module, "get_profile", lambda profile_id="current-rag": profile)

        Indexer(profile).build(force=True)

        r = c.get("/api/rag/index", params={"profile_id": "current-rag"})
        assert r.status_code == 200
        body = r.json()
        assert body["rag_enabled"] is True
        assert body["status"] == "current"
        assert body["error_type"] is None
        assert body["message"] == "index is current"
        assert body["indexed_files"] == 1
        assert body["stale"] is False

    def test_rag_index_endpoint_for_stale_index(self, client, tmp_path, monkeypatch):
        c, app_module = client
        from runnrr import config
        from runnrr.rag.indexer import Indexer

        profile = _rag_profile(tmp_path, profile_id="stale-rag")
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
        monkeypatch.setattr(app_module, "get_profile", lambda profile_id="stale-rag": profile)

        Indexer(profile).build(force=True)
        (profile.kb_root / "note.md").write_text(
            "# Note\n\nSemantic retrieval fixture changed.\n",
            encoding="utf-8",
        )

        r = c.get("/api/rag/index", params={"profile_id": "stale-rag"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "stale"
        assert body["error_type"] is None
        assert body["stale"] is True
        assert "modified: note.md" in body["message"]

    def test_rag_index_endpoint_for_corrupt_manifest(self, client, tmp_path, monkeypatch):
        c, app_module = client
        from runnrr import config

        profile = _rag_profile(tmp_path, profile_id="bad-manifest")
        index_dir = tmp_path / "indexes" / profile.id
        index_dir.mkdir(parents=True)
        (index_dir / "manifest.json").write_text("{ not valid json", encoding="utf-8")
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
        monkeypatch.setattr(app_module, "get_profile", lambda profile_id="bad-manifest": profile)

        r = c.get("/api/rag/index", params={"profile_id": "bad-manifest"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "error"
        assert body["error_type"] == "invalid_manifest"
        assert "invalid manifest JSON" in body["message"]
        assert body["error"] == body["message"]

    def test_rag_index_endpoint_for_embedding_misconfig(self, client, tmp_path, monkeypatch):
        c, app_module = client
        from runnrr import config

        profile = _rag_profile(tmp_path, profile_id="embedding-bad")
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "voyage")
        monkeypatch.setattr(config, "VOYAGE_API_KEY", "")
        monkeypatch.setattr(app_module, "get_profile", lambda profile_id="embedding-bad": profile)

        r = c.get("/api/rag/index", params={"profile_id": "embedding-bad"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "error"
        assert body["error_type"] == "embedding_misconfigured"
        assert "VOYAGE_API_KEY" in body["message"]

    def test_rag_index_endpoint_for_dependency_error(self, client, tmp_path, monkeypatch):
        c, app_module = client
        from runnrr import config
        from runnrr.rag import indexer as indexer_module
        from runnrr.rag.vector_index import VectorIndexDependencyError

        class MissingDependencyIndexer:
            def __init__(self, profile):
                self.profile = profile

            def info(self):
                raise VectorIndexDependencyError("sqlite-vec unavailable")

        profile = _rag_profile(tmp_path, profile_id="dependency-bad")
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
        monkeypatch.setattr(indexer_module, "Indexer", MissingDependencyIndexer)
        monkeypatch.setattr(app_module, "get_profile", lambda profile_id="dependency-bad": profile)

        r = c.get("/api/rag/index", params={"profile_id": "dependency-bad"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "error"
        assert body["error_type"] == "dependency_missing"
        assert "sqlite-vec unavailable" in body["message"]


class TestStaleIndexWarning:
    def test_current_index_emits_no_stale_warning(
        self, tmp_path, monkeypatch, caplog
    ):
        from runnrr import app as app_module
        from runnrr import config
        from runnrr import profiles as profiles_module
        from runnrr.app import warn_stale_indexes
        from runnrr.rag.indexer import Indexer

        profiles_root, profile = _stale_warn_profile_tree(
            tmp_path, profile_id="warn-current"
        )
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
        monkeypatch.setattr(config, "PROFILE_ROOT", profiles_root)
        monkeypatch.setattr(profiles_module, "PROFILE_ROOT", profiles_root)
        monkeypatch.setattr(app_module, "PROFILE_ROOT", profiles_root)

        Indexer(profile).build(force=True)

        with caplog.at_level(logging.WARNING, logger="runnrr"):
            warn_stale_indexes()

        stale_records = [r for r in caplog.records if r.message == "rag_index_stale"]
        assert stale_records == []

    def test_missing_index_emits_stale_warning(self, tmp_path, monkeypatch, caplog):
        from runnrr import app as app_module
        from runnrr import config
        from runnrr import profiles as profiles_module
        from runnrr.app import warn_stale_indexes

        profiles_root, profile = _stale_warn_profile_tree(
            tmp_path, profile_id="warn-missing"
        )
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "indexes")
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
        monkeypatch.setattr(config, "PROFILE_ROOT", profiles_root)
        monkeypatch.setattr(profiles_module, "PROFILE_ROOT", profiles_root)
        monkeypatch.setattr(app_module, "PROFILE_ROOT", profiles_root)

        with caplog.at_level(logging.WARNING, logger="runnrr"):
            warn_stale_indexes()

        stale_records = [r for r in caplog.records if r.message == "rag_index_stale"]
        assert len(stale_records) == 1
        assert getattr(stale_records[0], "profile", None) == profile.id
        assert getattr(stale_records[0], "rag_status", None) == "missing"


class TestAbuseProtection:
    def test_budget_exhausted_returns_503(self, client, monkeypatch, fake_provider_cls):
        c, app_module = client
        from runnrr.budget import TOKEN_BUDGET

        TOKEN_BUDGET.record(TOKEN_BUDGET.daily_limit)

        fake = fake_provider_cls([[{"type": "message_done", "stop_reason": "end_turn"}]])
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)

        r = c.post(
            "/api/chat",
            json={"session_id": "s-budget", "message": "hi", "model": "claude-sonnet-4-5"},
        )
        assert r.status_code == 503
        assert "budget" in r.json()["detail"].lower()

    def test_budget_records_actual_usage(self, client, monkeypatch):
        c, app_module = client
        from runnrr.budget import TOKEN_BUDGET

        fake = _LoopFake(
            [
                {"type": "text_delta", "text": "hi"},
                {
                    "type": "usage",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
                {"type": "message_done", "stop_reason": "end_turn"},
            ]
        )
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)

        before = TOKEN_BUDGET.stats()["used"]
        with c.stream(
            "POST",
            "/api/chat",
            json={"session_id": "s-record", "message": "hi", "model": "claude-sonnet-4-5"},
        ) as r:
            list(r.iter_bytes())

        after = TOKEN_BUDGET.stats()["used"]
        assert after - before == 150

    def test_session_capacity_returns_503(self, client, monkeypatch, fake_provider_cls):
        c, app_module = client

        monkeypatch.setattr(app_module, "MAX_ACTIVE_SESSIONS", 1)
        import time as _time

        app_module.SESSIONS["existing"] = {
            "messages": [],
            "last_seen": _time.time(),
            "provider": "anthropic",
            "profile": "personal-agent",
        }

        fake = fake_provider_cls([[{"type": "message_done", "stop_reason": "end_turn"}]])
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)

        r = c.post(
            "/api/chat",
            json={"session_id": "s-new", "message": "hi", "model": "claude-sonnet-4-5"},
        )
        assert r.status_code == 503
        assert "capacity" in r.json()["detail"].lower()

    def test_rate_limit_returns_429(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("DEFAULT_PROFILE", "personal-agent")
        monkeypatch.setenv("RATE_LIMIT_CHAT", "2/minute")
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")

        import importlib
        from runnrr import config, ratelimit

        importlib.reload(config)
        importlib.reload(ratelimit)  # limiter is built from RATE_LIMIT_* at import
        from runnrr import app as app_module

        importlib.reload(app_module)
        c = TestClient(app_module.app)

        fake = _LoopFake([{"type": "message_done", "stop_reason": "end_turn"}])
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)

        statuses: list[int] = []
        for i in range(5):
            with c.stream(
                "POST",
                "/api/chat",
                json={
                    "session_id": f"s-rl-{i}",
                    "message": "hi",
                    "model": "claude-sonnet-4-5",
                },
            ) as r:
                list(r.iter_bytes())
                statuses.append(r.status_code)

        assert 429 in statuses, f"expected at least one 429, got {statuses}"
        assert statuses.count(200) <= 2, (
            f"limit was 2/minute but got more than 2 successes: {statuses}"
        )
