from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from runnrr.profiles import AgentProfile
from runnrr.rag.embeddings import FakeEmbeddingProvider
from runnrr.rag.indexer import Indexer
from runnrr.tools import run_tool

MINI_RAG_FIXTURE = (Path(__file__).parent / "fixtures" / "mini_rag_kb").resolve()


@pytest.fixture
def sqlite_vec_available():
    pytest.importorskip("sqlite_vec")


@pytest.fixture
def semantic_profile(tmp_path, monkeypatch) -> AgentProfile:
    kb = tmp_path / "mini_rag_kb"
    shutil.copytree(MINI_RAG_FIXTURE, kb)
    index_root = tmp_path / "indexes"

    from runnrr import config

    monkeypatch.setattr(config, "RAG_INDEX_ROOT", index_root)
    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "")

    profile = AgentProfile(
        id="mini",
        label="Mini",
        description="Mini profile",
        kb_root=kb,
        system_prompt="test",
        tools=("list_kb", "read_file", "search_kb", "semantic_search_kb"),
    )
    Indexer(
        profile,
        FakeEmbeddingProvider(),
        index_dir=index_root / profile.id,
    ).build()
    return profile


def test_semantic_search_dispatch_returns_json_safe_results(
    sqlite_vec_available,
    semantic_profile,
) -> None:
    result = run_tool(
        "semantic_search_kb",
        {"query": "portable profile retrieval", "k": 2},
        tool_use_id="semantic1",
        root=semantic_profile.kb_root,
        profile=semantic_profile,
        allowed_tools=semantic_profile.tools,
    )

    assert result.is_error is False
    payload = json.loads(result.content)
    assert payload
    assert set(payload[0]) == {
        "path",
        "heading_path",
        "start_line",
        "end_line",
        "snippet",
        "score",
    }
    assert payload[0]["path"] == "projects/alpha.md"
    assert result.source_summary.startswith("semantic searched")
    assert result.source_items
    public_blob = json.dumps(
        {
            "source_summary": result.source_summary,
            "source_items": result.source_items,
        }
    )
    assert "projects/alpha.md" not in public_blob
    assert "/" not in public_blob


def test_semantic_search_requires_active_profile(sqlite_vec_available) -> None:
    result = run_tool(
        "semantic_search_kb",
        {"query": "portable profile retrieval"},
        tool_use_id="semantic-missing-profile",
        allowed_tools=("semantic_search_kb",),
    )

    assert result.is_error is True
    assert (
        json.loads(result.content)["error"]
        == "semantic_search_kb requires an active profile"
    )


def test_semantic_search_respects_profile_allowlist(
    sqlite_vec_available,
    semantic_profile,
) -> None:
    result = run_tool(
        "semantic_search_kb",
        {"query": "portable profile retrieval"},
        tool_use_id="semantic-blocked",
        profile=semantic_profile,
        allowed_tools=("search_kb",),
    )

    assert result.is_error is True
    assert "not enabled" in json.loads(result.content)["error"]


def test_semantic_search_reports_missing_index(tmp_path, monkeypatch) -> None:
    pytest.importorskip("sqlite_vec")
    from runnrr import config

    monkeypatch.setattr(config, "RAG_INDEX_ROOT", tmp_path / "missing-indexes")
    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
    profile = AgentProfile(
        id="missing",
        label="Missing",
        description="Missing index",
        kb_root=tmp_path,
        system_prompt="test",
        tools=("semantic_search_kb",),
    )

    result = run_tool(
        "semantic_search_kb",
        {"query": "anything"},
        tool_use_id="semantic-missing-index",
        profile=profile,
        allowed_tools=profile.tools,
    )

    assert result.is_error is True
    assert "RAG index missing" in json.loads(result.content)["error"]
