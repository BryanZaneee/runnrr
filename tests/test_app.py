"""Phase C tests: FastAPI endpoints with a monkeypatched provider.

Hits /api/health, /api/models, and /api/chat. Verifies the SSE stream is well-formed
when the provider is replaced with a FakeProvider that yields canned events.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.profiles import AgentProfile

MINI_RAG_FIXTURE = (Path(__file__).parent / "fixtures" / "mini_rag_kb").resolve()


# --------------------------------------------------------------------------- #
# /api/health
# --------------------------------------------------------------------------- #


class TestHealth:
    def test_health_ok(self, client):
        c, _ = client
        r = c.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "sessions" in body


# --------------------------------------------------------------------------- #
# /api/models
# --------------------------------------------------------------------------- #


class TestModels:
    def test_lists_all_configured_providers_with_keys(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setenv("MOONSHOT_API_KEY", "would-be-key")
        monkeypatch.setenv("OPENAI_API_KEY", "would-be-key")
        monkeypatch.setenv("GEMINI_API_KEY", "would-be-key")
        r = c.get("/api/models")
        assert r.status_code == 200
        body = r.json()
        assert body["default"] is not None
        ids = {m["id"] for m in body["models"]}
        providers = {m["provider"] for m in body["models"]}
        assert {"anthropic", "openai_compat", "gemini"} <= providers
        assert "claude-sonnet-4-5" in ids
        assert "gpt-5" in ids
        assert "kimi-k2.6" in ids
        assert "gemini-2.5-flash" in ids


# --------------------------------------------------------------------------- #
# /api/profile
# --------------------------------------------------------------------------- #


class TestProfiles:
    def test_frampton_profile_exposes_red_brand_and_kb_tool_schemas(self, client):
        c, _ = client
        r = c.get("/api/profile", params={"profile_id": "frampton"})
        assert r.status_code == 200
        body = r.json()

        assert body["id"] == "frampton"
        assert body["label"] == "Frampton"
        assert body["tools"] == ["list_kb", "read_file", "search_kb", "semantic_search_kb"]
        assert [schema["name"] for schema in body["tool_schemas"]] == body["tools"]
        assert body["mcp_servers"] == []
        assert body["brand"]["accent"] == "#B3261E"
        assert body["brand"]["accent_dark"] == "#4A0F0B"
        assert body["brand"]["accent_soft"] == "#F8D8D4"
        assert body["brand"]["grid"] == "rgba(179, 38, 30, 0.14)"
        assert body["brand"]["mark"] == "#E11D48"
        assert body["brand"]["hero_icon"] == " /\\_/\\\n( o_o )\n/|___|\\\n  v v"
        assert "Dark Souls 1 questions" in body["welcome"]
        assert "Explain Artorias and the Abyss." in body["suggestions"]

    def test_profile_excludes_rag_index_summary(self, client):
        # /api/profile is intentionally cheap and must NOT embed RAG-index health
        # (that scans the KB filesystem). RAG health lives at /api/rag/index.
        c, _ = client
        r = c.get("/api/profile", params={"profile_id": "research-analyst"})
        assert r.status_code == 200
        assert "rag_index" not in r.json()

    def test_profile_with_unknown_tool_returns_400(self, client, monkeypatch):
        from backend import app as app_module
        from backend.profiles import ProfileConfigError

        def boom(profile_id):
            raise ProfileConfigError(
                f"profile '{profile_id}' lists unknown tool(s): serch_kb."
            )

        c, _ = client
        monkeypatch.setattr(app_module, "load_profile", boom)
        r = c.get("/api/profile", params={"profile_id": "typoprof"})
        assert r.status_code == 400
        assert "serch_kb" in r.json()["detail"]

    def test_personal_agent_profile_loads_aliases_and_labels(self):
        from backend.profiles import load_profile

        profile = load_profile("personal-agent")
        assert profile.project_aliases["bryanzane.com"] == "bryanzane-com"
        assert profile.source_labels["shuttrr"] == "Shuttrr"

    def test_personal_agent_profile_loads_source_path_labels(self):
        from backend.profiles import load_profile

        profile = load_profile("personal-agent")
        assert ("resume/resume.md", "Resume") in profile.source_path_labels
        assert ("meta/", "Portfolio knowledge base") in profile.source_path_labels

    def test_list_profiles_logs_and_skips_broken(self, client, monkeypatch, tmp_path, caplog):
        import logging

        from backend import app as app_module
        from backend import profiles as profiles_module

        c, _ = client
        root = tmp_path / "profiles"
        root.mkdir()
        good = root / "good"
        good.mkdir()
        (good / "system.md").write_text("good agent", encoding="utf-8")
        (good / "profile.json").write_text(
            json.dumps(
                {
                    "id": "good",
                    "label": "Good",
                    "description": "ok",
                    "kb_root": str(tmp_path),
                    "system_prompt_path": str(good / "system.md"),
                }
            ),
            encoding="utf-8",
        )
        broken = root / "broken"
        broken.mkdir()
        (broken / "profile.json").write_text("{ not valid json", encoding="utf-8")

        # list_profiles iterates app's PROFILE_ROOT; load_profile reads its own.
        monkeypatch.setattr(app_module, "PROFILE_ROOT", root)
        monkeypatch.setattr(profiles_module, "PROFILE_ROOT", root)

        with caplog.at_level(logging.WARNING, logger="easyagent"):
            r = c.get("/api/profiles")

        assert r.status_code == 200
        ids = {p["id"] for p in r.json()["profiles"]}
        assert "good" in ids
        assert "broken" not in ids
        assert any("broken" in rec.getMessage() for rec in caplog.records)


# --------------------------------------------------------------------------- #
# SSE wire format
# --------------------------------------------------------------------------- #


class TestSSEFormat:
    @pytest.mark.asyncio
    async def test_stream_exception_is_sanitized(self, caplog):
        import logging

        from backend.app import _sse_format

        async def exploding_events():
            yield {"event": "delta", "text": "partial"}
            raise RuntimeError("sk-secret-123 internal detail")

        with caplog.at_level(logging.ERROR, logger="easyagent"):
            frames = [f async for f in _sse_format(exploding_events())]

        body = b"".join(frames).decode("utf-8")
        # The partial event still went out, then a generic error frame.
        assert "event: delta" in body
        assert body.rstrip().split("\n\n")[-1].startswith("event: error")
        assert "internal error while streaming the response" in body
        assert "sk-secret-123" not in body
        # Full traceback lands in the server log instead.
        assert any("sse stream failed" in rec.getMessage() for rec in caplog.records)
        assert any("sk-secret-123" in str(rec.exc_info) for rec in caplog.records if rec.exc_info)


# --------------------------------------------------------------------------- #
# /api/chat
# --------------------------------------------------------------------------- #


class TestChat:
    def test_unknown_model_400(self, client):
        c, _ = client
        r = c.post(
            "/api/chat",
            json={"session_id": "s1", "message": "hi", "model": "definitely-not-a-model"},
        )
        assert r.status_code == 400

    def test_streams_well_formed_sse(self, client, monkeypatch, fake_provider_cls):
        c, app_module = client

        fake = fake_provider_cls(
            [
                [
                    {"type": "text_delta", "text": "Hello"},
                    {"type": "text_delta", "text": " there."},
                    {"type": "usage", "usage": {
                        "input_tokens": 10, "output_tokens": 3,
                        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                    }},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ]
            ]
        )
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)

        with c.stream(
            "POST",
            "/api/chat",
            json={"session_id": "s2", "message": "hi", "model": "claude-sonnet-4-5"},
        ) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            body = b"".join(r.iter_bytes()).decode("utf-8")

        # SSE frames are separated by blank lines and contain `event:` + `data:` pairs.
        frames = [f for f in body.split("\n\n") if f.strip()]
        assert frames, "no SSE frames received"
        kinds = [f.split("\n", 1)[0] for f in frames]
        assert "event: delta" in kinds
        assert "event: usage" in kinds
        assert kinds[-1] == "event: done"

    def test_streams_sanitized_tool_sources(
        self, client, monkeypatch, kb_root, fake_provider_cls
    ):
        c, app_module = client

        fake = fake_provider_cls(
            [
                [
                    {"type": "tool_use_complete", "tool_use_id": "tu_read",
                     "name": "read_file", "arguments": {"path": "resume/resume.md"}},
                    {"type": "message_done", "stop_reason": "tool_use"},
                ],
                [
                    {"type": "text_delta", "text": "Done."},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ],
            ]
        )
        profile = AgentProfile(
            id="test",
            label="Test",
            description="Test profile",
            kb_root=kb_root,
            system_prompt="test-system",
            source_path_labels=(("resume/resume.md", "Resume"),),
        )
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)
        monkeypatch.setattr(app_module, "get_profile", lambda profile_id="test": profile)

        with c.stream(
            "POST",
            "/api/chat",
            json={
                "session_id": "s-tool-sources",
                "message": "read resume",
                "model": "claude-sonnet-4-5",
                "profile": "test",
            },
        ) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes()).decode("utf-8")

        assert "event: tool_result" in body
        assert '"source_items": [{"label": "Resume", "kind": "kb_read"}]' in body
        assert "resume/resume.md" not in body
        assert "resume.md" not in body
        assert str(kb_root) not in body

    def test_semantic_search_runs_through_chat_endpoint(
        self,
        client,
        monkeypatch,
        tmp_path,
        fake_provider_cls,
        parse_sse,
    ):
        pytest.importorskip("sqlite_vec")
        from backend import config
        from backend.rag.embeddings import FakeEmbeddingProvider
        from backend.rag.indexer import Indexer

        c, app_module = client
        kb = tmp_path / "mini_rag_kb"
        shutil.copytree(MINI_RAG_FIXTURE, kb)
        index_root = tmp_path / "indexes"
        monkeypatch.setattr(config, "RAG_INDEX_ROOT", index_root)
        monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
        monkeypatch.setattr(config, "EMBEDDING_MODEL", "")
        profile = AgentProfile(
            id="mini",
            label="Mini",
            description="Mini RAG profile",
            kb_root=kb,
            system_prompt="test-system",
            tools=("list_kb", "read_file", "search_kb", "semantic_search_kb"),
        )
        Indexer(
            profile,
            FakeEmbeddingProvider(),
            index_dir=index_root / profile.id,
        ).build()
        fake = fake_provider_cls(
            [
                [
                    {
                        "type": "tool_use_complete",
                        "tool_use_id": "tu_semantic",
                        "name": "semantic_search_kb",
                        "arguments": {"query": "portable profile retrieval", "k": 2},
                    },
                    {"type": "message_done", "stop_reason": "tool_use"},
                ],
                [
                    {"type": "text_delta", "text": "Done."},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ],
            ]
        )
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)
        monkeypatch.setattr(app_module, "get_profile", lambda profile_id="mini": profile)

        with c.stream(
            "POST",
            "/api/chat",
            json={
                "session_id": "s-semantic-e2e",
                "message": "find conceptual retrieval context",
                "model": "claude-sonnet-4-5",
                "profile": "mini",
            },
        ) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes()).decode("utf-8")

        events = parse_sse(body)
        tool_payloads = [
            payload for event, payload in events if event == "tool_result"
        ]
        assert tool_payloads
        assert tool_payloads[0]["name"] == "semantic_search_kb"
        assert tool_payloads[0]["is_error"] is False
        assert tool_payloads[0]["source_summary"].startswith("semantic searched")
        assert tool_payloads[0]["source_items"][0]["kind"] == "kb_semantic_search"
        assert "projects/alpha.md" not in body
        assert str(kb) not in body

    def test_session_state_grows(self, client, monkeypatch, fake_provider_cls):
        c, app_module = client

        fake = fake_provider_cls(
            [
                [
                    {"type": "text_delta", "text": "ok"},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ]
            ]
        )
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)

        with c.stream(
            "POST",
            "/api/chat",
            json={"session_id": "session-grow", "message": "hi", "model": "claude-sonnet-4-5"},
        ) as r:
            list(r.iter_bytes())  # drain stream

        # Session was created and accumulated user + assistant turns.
        sess = app_module.SESSIONS["session-grow"]
        assert len(sess["messages"]) == 2
        assert sess["messages"][0]["role"] == "user"

    def test_session_resets_when_profile_changes(self, client, monkeypatch, tmp_path, fake_provider_cls):
        c, app_module = client

        fake = fake_provider_cls(
            [
                [
                    {"type": "text_delta", "text": "a"},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ],
                [
                    {"type": "text_delta", "text": "b"},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ],
            ]
        )
        profile_a = AgentProfile(
            id="profile-a",
            label="Profile A",
            description="",
            kb_root=tmp_path,
            system_prompt="a",
        )
        profile_b = AgentProfile(
            id="profile-b",
            label="Profile B",
            description="",
            kb_root=tmp_path,
            system_prompt="b",
        )
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)
        monkeypatch.setattr(
            app_module,
            "get_profile",
            lambda profile_id="profile-a": profile_b if profile_id == "profile-b" else profile_a,
        )

        with c.stream(
            "POST",
            "/api/chat",
            json={
                "session_id": "session-reset",
                "message": "hi",
                "model": "claude-sonnet-4-5",
                "profile": "profile-a",
            },
        ) as r:
            list(r.iter_bytes())
        assert app_module.SESSIONS["session-reset"]["profile"] == "profile-a"
        assert len(app_module.SESSIONS["session-reset"]["messages"]) == 2

        with c.stream(
            "POST",
            "/api/chat",
            json={
                "session_id": "session-reset",
                "message": "hi again",
                "model": "claude-sonnet-4-5",
                "profile": "profile-b",
            },
        ) as r:
            list(r.iter_bytes())

        sess = app_module.SESSIONS["session-reset"]
        assert sess["profile"] == "profile-b"
        assert len(sess["messages"]) == 2
        assert sess["messages"][0]["content"] == "hi again"
