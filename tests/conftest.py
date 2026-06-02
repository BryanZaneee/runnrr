"""Shared pytest fixtures. Points the KB at tests/fixtures/mini_kb/ for all tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient

from backend.profiles import AgentProfile
from backend.providers.base import Event
from backend.tools import SCHEMAS, ToolResult

FIXTURE_KB = (Path(__file__).parent / "fixtures" / "mini_kb").resolve()


@pytest.fixture(autouse=True)
def use_mini_kb(monkeypatch):
    """Override KB_ROOT in both modules that import it. Autouse so every test is isolated."""
    from backend import config, kb_loader

    monkeypatch.setattr(config, "KB_ROOT", FIXTURE_KB)
    monkeypatch.setattr(kb_loader, "KB_ROOT", FIXTURE_KB)
    return FIXTURE_KB


@pytest.fixture(autouse=True)
def reset_budget():
    """Reset the daily token budget between tests so they don't leak state."""
    from backend.budget import TOKEN_BUDGET

    TOKEN_BUDGET.reset()
    yield
    TOKEN_BUDGET.reset()


@pytest.fixture(autouse=True)
def reset_manifest_cache():
    """Clear the KB-manifest cache between tests (it is process-lifetime in prod)."""
    from backend.profiles import clear_manifest_cache

    clear_manifest_cache()
    yield
    clear_manifest_cache()


@pytest.fixture
def kb_root(use_mini_kb):
    """Convenience alias when a test wants to reference the path explicitly."""
    return use_mini_kb


class FakeProvider:
    """Minimal provider used by endpoint and agent-loop tests."""

    def __init__(self, scripted_turns: list[list[Event]]) -> None:
        self.scripted_turns = scripted_turns
        self.turn_index = 0

    async def stream(self, **kwargs: Any) -> AsyncIterator[Event]:
        events = self.scripted_turns[self.turn_index]
        self.turn_index += 1
        kwargs["messages"].append({"role": "assistant", "content": "<scripted>"})
        for ev in events:
            yield ev

    def format_user(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def append_tool_results(self, messages: list, results: list[ToolResult]) -> None:
        messages.append({"role": "user", "content": [r.tool_use_id for r in results]})

    def tools_for_provider(self, profile: AgentProfile) -> list[dict]:
        return SCHEMAS

    def system_for_provider(self, profile: AgentProfile) -> Any:
        return "test-system"


@pytest.fixture
def fake_provider_cls():
    return FakeProvider


@pytest.fixture
def client(monkeypatch):
    # Pretend Anthropic key is set so /api/models returns at least one model.
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
def parse_sse():
    import json

    def _parse(body: str) -> list[tuple[str, dict]]:
        events: list[tuple[str, dict]] = []
        for frame in body.split("\n\n"):
            if not frame.strip():
                continue
            lines = frame.splitlines()
            event = lines[0].removeprefix("event: ")
            data = lines[1].removeprefix("data: ")
            events.append((event, json.loads(data)))
        return events

    return _parse
