"""Tests for the bundled customer-service profile and the /api/profiles endpoint."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from runnrr.kb_loader import search_kb
from runnrr.profiles import AgentProfile, load_profile


def test_customer_service_profile_loads():
    p = load_profile("customer-service")
    assert p.id == "customer-service"
    assert p.label == "Customer Service"
    assert p.tools == ("list_kb", "read_file", "search_kb", "semantic_search_kb")
    assert p.mcp_servers == ()
    assert p.brand["accent"] == "#f0642f"
    assert p.brand["intro_ascii_name"]
    assert "Easy Coffee" in p.brand["input_placeholder"]
    assert "Easy Coffee" in p.welcome
    assert len(p.suggestions) == 3


def test_personal_agent_profile_brand_loads():
    p = load_profile("personal-agent")
    assert p.brand["accent"] == "#386f3d"
    assert p.brand["intro_ascii_name"]
    assert "Personal Agent" in p.brand["input_placeholder"]
    assert p.data_root is None


def test_research_analyst_profile_loads():
    p = load_profile("research-analyst")
    assert p.id == "research-analyst"
    assert p.label == "Research Analyst"
    assert p.tools == ("web_search", "fetch_url_text", "calculator")
    assert p.brand["accent"] == "#2f7de1"
    assert p.brand["intro_ascii_name"]
    assert "Research Analyst" in p.brand["input_placeholder"]
    assert p.data_root is None
    assert "<workflow>" in p.system_prompt
    assert "<quality_bar>" in p.system_prompt


def test_sales_concierge_profile_loads_with_data_root():
    p = load_profile("sales-concierge")
    assert p.id == "sales-concierge"
    assert p.label == "Sales Concierge"
    assert p.tools == (
        "catalog_lookup",
        "qualify_lead",
        "lead_capture_preview",
        "checkout_link_preview",
        "calculator",
    )
    assert p.brand["accent"] == "#7C3AED"
    assert p.brand["intro_ascii_name"]
    assert "BZS Software" in p.brand["input_placeholder"]
    assert p.data_root is not None
    assert p.data_root.parts[-2:] == ("sales-concierge", "data")
    assert (p.data_root / "catalog.json").exists()
    assert "BZS Software" in p.tool_descriptions["catalog_lookup"]
    assert "BZS Software" in p.tool_descriptions["qualify_lead"]
    assert "<workflow>" in p.system_prompt
    assert "<quality_bar>" in p.system_prompt


def test_new_profile_smoke_eval_datasets_are_structured():
    for path in (
        Path("profiles/research-analyst/evals/smoke.json"),
        Path("profiles/sales-concierge/evals/smoke.json"),
        Path("profiles/bzs-concierge/evals/smoke.json"),
    ):
        cases = json.loads(path.read_text(encoding="utf-8"))
        assert len(cases) >= 3
        for case in cases:
            assert case["id"]
            assert case["task"]
            assert isinstance(case["expected_tools"], list)
            assert case["expected_tools"]
            assert isinstance(case["criteria"], list)
            assert case["criteria"]


def test_customer_service_kb_root_resolves_to_profile_dir():
    p = load_profile("customer-service")
    assert p.kb_root.parts[-2:] == ("customer-service", "kb")
    assert p.kb_root.exists()
    assert p.kb_root.is_dir()


def test_customer_service_system_prompt_loaded():
    p = load_profile("customer-service")
    assert p.system_prompt
    assert "Easy Coffee" in p.system_prompt
    assert "I don't have that info" in p.system_prompt


def test_customer_service_kb_searchable():
    p = load_profile("customer-service")
    # Pass root= explicitly to bypass the use_mini_kb autouse monkeypatch.
    results = search_kb("hours", root=p.kb_root, max_results=5)
    assert results, "search_kb should return at least one match for 'hours'"
    paths = [r["path"] for r in results]
    assert any(path.endswith("hours.md") for path in paths), paths


def test_mcp_servers_field_round_trips(tmp_path, monkeypatch):
    """Write an ad-hoc profile with mcp_servers and verify it round-trips."""
    fake_root = tmp_path / "profiles"
    fake_root.mkdir()
    profile_dir = fake_root / "fixture-cs"
    profile_dir.mkdir()
    (profile_dir / "data").mkdir()

    (profile_dir / "system.md").write_text("test prompt")
    (profile_dir / "profile.json").write_text(json.dumps({
        "id": "fixture-cs",
        "label": "Fixture CS",
        "description": "MCP round-trip test profile",
        "kb_root": "kb",
        "system_prompt_path": str(profile_dir / "system.md"),
        "tools": ["search_kb"],
        "brand": {"accent": "#123456"},
        "data_root": str(profile_dir / "data"),
        "mcp_servers": [
            {"name": "calendar", "command": "npx", "args": ["-y", "@x/cal"], "env": {}},
            {"name": "crm", "command": "/usr/bin/foo", "args": [], "env": {"K": "v"}},
        ],
    }))

    from runnrr import profiles as profiles_mod

    monkeypatch.setattr(profiles_mod, "PROFILE_ROOT", fake_root)
    p = load_profile("fixture-cs")

    assert len(p.mcp_servers) == 2
    assert p.mcp_servers[0]["name"] == "calendar"
    assert p.mcp_servers[1]["env"] == {"K": "v"}
    assert p.brand == {"accent": "#123456"}
    assert p.data_root == (profile_dir / "data").resolve()


# --------------------------------------------------------------------------- #
# /api/profiles endpoint
# --------------------------------------------------------------------------- #


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from runnrr import config

    importlib.reload(config)
    from runnrr import app as app_module

    importlib.reload(app_module)
    app_module.limiter.enabled = False
    return TestClient(app_module.app)


def test_api_profiles_lists_both_bundled_profiles(client):
    r = client.get("/api/profiles")
    assert r.status_code == 200
    body = r.json()
    assert "default" in body
    ids = {p["id"] for p in body["profiles"]}
    assert {"personal-agent", "customer-service", "research-analyst", "sales-concierge"} <= ids


def test_api_profiles_includes_tools_and_mcp_servers(client):
    r = client.get("/api/profiles")
    body = r.json()
    cs = next(p for p in body["profiles"] if p["id"] == "customer-service")
    assert cs["label"] == "Customer Service"
    assert cs["tools"] == ["list_kb", "read_file", "search_kb", "semantic_search_kb"]
    assert cs["mcp_servers"] == []
    assert cs["brand"]["accent"] == "#f0642f"


def test_api_profile_includes_allowed_tool_schemas(client):
    r = client.get("/api/profile?profile_id=customer-service")
    assert r.status_code == 200
    body = r.json()

    assert body["tools"] == ["list_kb", "read_file", "search_kb", "semantic_search_kb"]
    assert body["brand"]["accent"] == "#f0642f"
    schemas = body["tool_schemas"]
    assert [schema["name"] for schema in schemas] == body["tools"]
    assert schemas[0]["input_schema"]["type"] == "object"
    assert {schema["name"] for schema in schemas}.isdisjoint({
        "get_resume_summary",
        "get_project_context",
        "web_search",
    })


def test_api_profile_skips_missing_tool_schemas(client, monkeypatch, tmp_path):
    from runnrr import app as app_module

    monkeypatch.setattr(
        app_module,
        "get_profile",
        lambda profile_id="test": AgentProfile(
            id="test",
            label="Test",
            description="Missing schema profile",
            kb_root=tmp_path,
            system_prompt="test",
            tools=("list_kb", "missing_tool", "search_kb"),
        ),
    )

    r = client.get("/api/profile?profile_id=test")
    assert r.status_code == 200
    body = r.json()

    assert body["tools"] == ["list_kb", "missing_tool", "search_kb"]
    assert [schema["name"] for schema in body["tool_schemas"]] == ["list_kb", "search_kb"]
