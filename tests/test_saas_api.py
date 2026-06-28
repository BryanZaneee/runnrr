"""SaaS auth + agent/usage API tests — no live database."""
from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from backend.auth import AuthError, CurrentUser, verify_token

USER_A = CurrentUser(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="a@example.com")
USER_B = CurrentUser(id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", email="b@example.com")
TEST_SECRET = "test-jwt-secret-for-saas"


@pytest.fixture
def saas_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DEFAULT_PROFILE", "personal-agent")
    import importlib
    from backend import config

    importlib.reload(config)
    from backend import app as app_module

    importlib.reload(app_module)
    app_module.limiter.enabled = False
    return TestClient(app_module.app), app_module


@pytest.fixture
def fake_agents_store(monkeypatch):
    """In-memory agents keyed by (owner_id, agent_id)."""
    store: dict[tuple[str, str], dict] = {}

    async def list_agents(owner_id: str) -> list[dict]:
        return [
            {
                "id": row["id"],
                "slug": row["slug"],
                "label": row["config"].get("label", row["slug"]),
                "description": row["config"].get("description", ""),
                "tools": list(row["config"].get("tools", [])),
                "brand": row["config"].get("brand", {}),
                "template_id": row.get("template_id"),
                "updated_at": None,
            }
            for (oid, _), row in store.items()
            if oid == owner_id
        ]

    async def get_agent(owner_id: str, agent_id: str) -> dict | None:
        return store.get((owner_id, agent_id))

    async def create_agent_from_template(
        owner_id: str,
        template_id: str,
        *,
        label: str | None = None,
        slug: str | None = None,
    ) -> dict:
        agent_id = f"agent-{len(store)}"
        cfg = {"label": label or template_id, "tools": ["list_kb"], "system_prompt": "hi"}
        row = {
            "id": agent_id,
            "owner_id": owner_id,
            "slug": slug or template_id,
            "config": cfg,
            "template_id": template_id,
        }
        store[(owner_id, agent_id)] = row
        return row

    async def update_agent(owner_id, agent_id, **kwargs):
        row = store.get((owner_id, agent_id))
        if row is None:
            return None
        if kwargs.get("label"):
            row["config"]["label"] = kwargs["label"]
        return row

    async def delete_agent(owner_id, agent_id):
        return store.pop((owner_id, agent_id), None) is not None

    def agent_row_to_profile(row):
        from backend.profiles import profile_from_config

        cfg = row["config"]
        return profile_from_config(
            cfg,
            system_prompt=cfg.get("system_prompt", ""),
            kb_root=Path("/tmp"),
            data_root=None,
            profile_id=row["slug"],
        )

    from backend import agents_store as mod

    monkeypatch.setattr(mod, "list_agents", list_agents)
    monkeypatch.setattr(mod, "get_agent", get_agent)
    monkeypatch.setattr(mod, "create_agent_from_template", create_agent_from_template)
    monkeypatch.setattr(mod, "update_agent", update_agent)
    monkeypatch.setattr(mod, "delete_agent", delete_agent)
    monkeypatch.setattr(mod, "agent_row_to_profile", agent_row_to_profile)

    store[(USER_B.id, "agent-b1")] = {
        "id": "agent-b1",
        "owner_id": USER_B.id,
        "slug": "b-agent",
        "config": {"label": "B Agent", "tools": ["list_kb"], "system_prompt": "b"},
        "template_id": "personal-agent",
    }
    store[(USER_A.id, "agent-a1")] = {
        "id": "agent-a1",
        "owner_id": USER_A.id,
        "slug": "a-agent",
        "config": {"label": "A Agent", "tools": ["list_kb"], "system_prompt": "a"},
        "template_id": "personal-agent",
    }
    return store


@pytest.fixture
def fake_usage_store(monkeypatch):
    recorded: list[dict] = []

    async def record_usage(**kwargs):
        recorded.append(kwargs)

    async def usage_summary(owner_id, *, since, agent_id=None):
        return {
            "tokens_in": 10,
            "tokens_out": 5,
            "tokens_total": 15,
            "requests": 1,
            "per_day": [{"day": "2026-06-28", "tokens_total": 15}],
            "per_model": [{"model": "claude-sonnet-4-5", "tokens_total": 15}],
        }

    from backend import usage_store as mod

    monkeypatch.setattr(mod, "record_usage", record_usage)
    monkeypatch.setattr(mod, "usage_summary", usage_summary)
    return recorded


def _override_user(app_module, user: CurrentUser | None):
    if user is None:
        app_module.app.dependency_overrides[app_module.optional_user] = lambda: None
    else:
        app_module.app.dependency_overrides[app_module.require_user] = lambda: user
        app_module.app.dependency_overrides[app_module.optional_user] = lambda: user


class TestAgentsAPI:
    def test_list_agents_returns_owner_agents(
        self, saas_client, fake_agents_store, fake_usage_store
    ):
        c, app_module = saas_client
        _override_user(app_module, USER_A)
        r = c.get("/api/agents")
        assert r.status_code == 200
        ids = {a["id"] for a in r.json()["agents"]}
        assert ids == {"agent-a1"}
        app_module.app.dependency_overrides.clear()

    def test_get_agent_tenancy_isolation(
        self, saas_client, fake_agents_store, fake_usage_store
    ):
        c, app_module = saas_client
        _override_user(app_module, USER_A)
        r = c.get("/api/agents/agent-b1")
        assert r.status_code == 404
        app_module.app.dependency_overrides.clear()


class TestVerifyToken:
    def test_valid_token(self, monkeypatch):
        from backend import config

        monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", TEST_SECRET)
        token = jwt.encode(
            {"sub": USER_A.id, "email": USER_A.email, "aud": "authenticated"},
            TEST_SECRET,
            algorithm="HS256",
        )
        user = verify_token(token)
        assert user.id == USER_A.id
        assert user.email == USER_A.email

    def test_wrong_secret_raises(self, monkeypatch):
        from backend import config

        monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", TEST_SECRET)
        token = jwt.encode(
            {"sub": USER_A.id, "aud": "authenticated"},
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(AuthError):
            verify_token(token)

    def test_expired_token_raises(self, monkeypatch):
        from backend import config

        monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", TEST_SECRET)
        token = jwt.encode(
            {"sub": USER_A.id, "aud": "authenticated", "exp": int(time.time()) - 60},
            TEST_SECRET,
            algorithm="HS256",
        )
        with pytest.raises(AuthError):
            verify_token(token)


class TestChatAnonymous:
    def test_chat_without_auth_streams(
        self, saas_client, fake_agents_store, fake_usage_store, monkeypatch, fake_provider_cls
    ):
        c, app_module = saas_client
        _override_user(app_module, None)

        fake = fake_provider_cls(
            [
                [
                    {"type": "text_delta", "text": "Hello"},
                    {"type": "usage", "usage": {
                        "input_tokens": 5, "output_tokens": 2,
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
            json={"session_id": "anon-s1", "message": "hi", "model": "claude-sonnet-4-5"},
        ) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes()).decode("utf-8")

        assert "event: delta" in body
        assert "event: done" in body
        assert fake_usage_store == []
        assert "anon-s1" in app_module.SESSIONS
        app_module.app.dependency_overrides.clear()


class TestChatAuthenticated:
    def test_chat_with_user_and_agent_records_usage(
        self, saas_client, fake_agents_store, fake_usage_store, monkeypatch, fake_provider_cls
    ):
        c, app_module = saas_client
        _override_user(app_module, USER_A)

        fake = fake_provider_cls(
            [
                [
                    {"type": "text_delta", "text": "Hi"},
                    {"type": "usage", "usage": {
                        "input_tokens": 8, "output_tokens": 4,
                        "cache_read_input_tokens": 1, "cache_creation_input_tokens": 0,
                    }},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ]
            ]
        )
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)

        with c.stream(
            "POST",
            "/api/chat",
            json={
                "session_id": "auth-s1",
                "message": "hi",
                "model": "claude-sonnet-4-5",
                "agent_id": "agent-a1",
            },
        ) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes()).decode("utf-8")

        assert "event: done" in body
        assert len(fake_usage_store) == 1
        rec = fake_usage_store[0]
        assert rec["owner_id"] == USER_A.id
        assert rec["agent_id"] == "agent-a1"
        assert rec["tokens_in"] == 8
        assert rec["tokens_out"] == 4
        session_key = f"{USER_A.id}:auth-s1"
        assert session_key in app_module.SESSIONS
        app_module.app.dependency_overrides.clear()

    def test_chat_stream_completes_when_record_usage_raises(
        self, saas_client, fake_agents_store, monkeypatch, fake_provider_cls
    ):
        c, app_module = saas_client
        _override_user(app_module, USER_A)

        async def boom(**kwargs):
            raise RuntimeError("db down")

        from backend import usage_store as usage_mod

        monkeypatch.setattr(usage_mod, "record_usage", boom)

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
            json={
                "session_id": "auth-s2",
                "message": "hi",
                "model": "claude-sonnet-4-5",
                "agent_id": "agent-a1",
            },
        ) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes()).decode("utf-8")

        assert "event: done" in body
        app_module.app.dependency_overrides.clear()


class TestUsageRangeParser:
    def test_parse_usage_range(self):
        from backend.app import _parse_usage_range

        assert _parse_usage_range("7d") == timedelta(days=7)
        assert _parse_usage_range("30d") == timedelta(days=30)
        assert _parse_usage_range("24h") == timedelta(hours=24)
        assert _parse_usage_range("garbage") == timedelta(days=7)


class TestUsageEndpoint:
    def test_usage_returns_summary(
        self, saas_client, fake_agents_store, fake_usage_store
    ):
        c, app_module = saas_client
        _override_user(app_module, USER_A)
        r = c.get("/api/usage", params={"range": "7d"})
        assert r.status_code == 200
        body = r.json()
        assert body["tokens_total"] == 15
        assert body["requests"] == 1
        assert body["per_day"][0]["tokens_total"] == 15
        assert body["per_model"][0]["model"] == "claude-sonnet-4-5"
        app_module.app.dependency_overrides.clear()
