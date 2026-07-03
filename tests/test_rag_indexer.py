from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.profiles import AgentProfile
from backend.rag.embeddings import FakeEmbeddingProvider
from backend.rag.indexer import Indexer
from backend.rag.pca import PCA_FILENAME, load_pca_sidecar, project_query
from backend.rag.retriever import get_retriever_for_profile

MINI_RAG_FIXTURE = (Path(__file__).parent / "fixtures" / "mini_rag_kb").resolve()


@pytest.fixture
def sqlite_vec_available():
    pytest.importorskip("sqlite_vec")


@pytest.fixture
def mini_rag_kb(tmp_path) -> Path:
    dest = tmp_path / "mini_rag_kb"
    shutil.copytree(MINI_RAG_FIXTURE, dest)
    return dest


@pytest.fixture
def mini_profile(mini_rag_kb) -> AgentProfile:
    return AgentProfile(
        id="mini",
        label="Mini",
        description="Mini RAG profile",
        kb_root=mini_rag_kb,
        system_prompt="test",
        tools=("list_kb", "read_file", "search_kb", "semantic_search_kb"),
    )


def test_indexer_build_info_and_query(sqlite_vec_available, tmp_path, mini_profile) -> None:
    index_dir = tmp_path / "indexes" / "mini"
    provider = FakeEmbeddingProvider()
    indexer = Indexer(mini_profile, provider, index_dir=index_dir)

    stale, reason = indexer.is_stale()
    assert stale is True
    assert "manifest missing" in reason

    report = indexer.build()
    info = indexer.info()

    assert report.added == (
        "INDEX.md",
        "notes/release.md",
        "projects/alpha.md",
        "projects/beta.md",
    )
    assert report.embedded_chunks > 0
    assert report.total_files == 4
    assert report.total_chunks > 0
    assert (index_dir / "manifest.json").exists()
    assert (index_dir / "bm25.pkl").exists()
    assert (index_dir / "index.sqlite").exists()
    assert info.stale is False
    assert info.indexed_files == 4
    assert info.indexed_chunks == report.total_chunks

    retriever = get_retriever_for_profile(
        mini_profile,
        embedding_provider=provider,
        index_dir=index_dir,
    )
    results = retriever.search("portable profile tool registry", k=2)
    assert results
    assert results[0].chunk.path == "projects/alpha.md"


def test_indexer_no_op_second_build(sqlite_vec_available, tmp_path, mini_profile) -> None:
    indexer = Indexer(mini_profile, FakeEmbeddingProvider(), index_dir=tmp_path / "index")
    first = indexer.build()

    second = indexer.build()

    assert first.embedded_chunks > 0
    assert second.added == ()
    assert second.modified == ()
    assert second.removed == ()
    assert second.embedded_chunks == 0
    assert second.total_chunks == first.total_chunks
    assert second.stale_reason == "index was current"


def test_get_retriever_for_profile_reuses_cache_until_index_changes(
    sqlite_vec_available,
    tmp_path,
    mini_profile,
) -> None:
    provider = FakeEmbeddingProvider()
    index_dir = tmp_path / "index"
    indexer = Indexer(mini_profile, provider, index_dir=index_dir)
    indexer.build()

    first = get_retriever_for_profile(
        mini_profile,
        embedding_provider=provider,
        index_dir=index_dir,
    )
    second = get_retriever_for_profile(
        mini_profile,
        embedding_provider=provider,
        index_dir=index_dir,
    )

    assert second is first

    alpha = mini_profile.kb_root / "projects" / "alpha.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8") + "\n\n## Cache Bust\n\nfresh detail",
        encoding="utf-8",
    )
    indexer.build()
    third = get_retriever_for_profile(
        mini_profile,
        embedding_provider=provider,
        index_dir=index_dir,
    )

    assert third is not first


def test_get_retriever_cache_ignores_provider_identity(
    sqlite_vec_available,
    tmp_path,
    mini_profile,
) -> None:
    # Two DISTINCT provider instances with identical backend/model/dim must share
    # the cache entry. The cache key no longer keys on id(embedding_provider), so
    # wrapping/re-instantiating a provider (common in tests) is not a cache miss.
    index_dir = tmp_path / "index"
    Indexer(mini_profile, FakeEmbeddingProvider(), index_dir=index_dir).build()

    first = get_retriever_for_profile(
        mini_profile,
        embedding_provider=FakeEmbeddingProvider(),
        index_dir=index_dir,
    )
    second = get_retriever_for_profile(
        mini_profile,
        embedding_provider=FakeEmbeddingProvider(),
        index_dir=index_dir,
    )

    assert second is first


def test_indexer_modified_file_reindexes_only_that_file(
    sqlite_vec_available,
    tmp_path,
    mini_profile,
) -> None:
    indexer = Indexer(mini_profile, FakeEmbeddingProvider(), index_dir=tmp_path / "index")
    first = indexer.build()

    alpha = mini_profile.kb_root / "projects" / "alpha.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8") + "\n\n## New Note\n\nfresh semantic detail",
        encoding="utf-8",
    )

    stale, reason = indexer.is_stale()
    assert stale is True
    assert "modified: projects/alpha.md" in reason

    second = indexer.build()

    assert second.added == ()
    assert second.modified == ("projects/alpha.md",)
    assert second.removed == ()
    assert second.embedded_chunks > 0
    assert second.embedded_chunks < first.embedded_chunks
    assert second.deleted_bm25_chunks > 0
    assert second.deleted_vector_chunks > 0
    assert indexer.is_stale() == (False, "index is current")


def test_indexer_removed_file_deletes_from_both_indexes(
    sqlite_vec_available,
    tmp_path,
    mini_profile,
) -> None:
    indexer = Indexer(mini_profile, FakeEmbeddingProvider(), index_dir=tmp_path / "index")
    indexer.build()

    (mini_profile.kb_root / "projects" / "beta.md").unlink()
    report = indexer.build()

    assert report.removed == ("projects/beta.md",)
    assert report.deleted_bm25_chunks > 0
    assert report.deleted_vector_chunks > 0
    retriever = get_retriever_for_profile(
        mini_profile,
        embedding_provider=FakeEmbeddingProvider(),
        index_dir=tmp_path / "index",
    )
    results = retriever.search("customer service profile demo", k=5)
    assert all(result.chunk.path != "projects/beta.md" for result in results)


def test_indexer_force_rebuild(sqlite_vec_available, tmp_path, mini_profile) -> None:
    indexer = Indexer(mini_profile, FakeEmbeddingProvider(), index_dir=tmp_path / "index")
    indexer.build()

    report = indexer.build(force=True)

    assert report.force is True
    assert report.rebuilt is True
    assert report.embedded_chunks == report.total_chunks


def test_indexer_builds_vector_schema_for_empty_kb(
    sqlite_vec_available,
    tmp_path,
) -> None:
    empty_kb = tmp_path / "empty-kb"
    empty_kb.mkdir()
    profile = AgentProfile(
        id="empty",
        label="Empty",
        description="Empty RAG profile",
        kb_root=empty_kb,
        system_prompt="test",
        tools=("semantic_search_kb",),
    )
    index_dir = tmp_path / "index"
    indexer = Indexer(profile, FakeEmbeddingProvider(), index_dir=index_dir)

    report = indexer.build()

    assert report.total_files == 0
    assert report.total_chunks == 0
    assert (index_dir / "index.sqlite").exists()
    assert indexer.is_stale() == (False, "index is current")


def test_cli_build_info_and_query_with_fake_backend(
    sqlite_vec_available,
    tmp_path,
    mini_rag_kb,
    capsys,
) -> None:
    profile_root = tmp_path / "profiles"
    profile_dir = profile_root / "mini"
    profile_dir.mkdir(parents=True)
    (profile_dir / "system.md").write_text("test", encoding="utf-8")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "mini",
                "label": "Mini",
                "description": "Mini RAG profile",
                "kb_root": str(mini_rag_kb),
                "system_prompt_path": str(profile_dir / "system.md"),
                "tools": ["list_kb", "read_file", "search_kb", "semantic_search_kb"],
            }
        ),
        encoding="utf-8",
    )
    index_root = tmp_path / "indexes"

    from backend.rag import cli

    assert cli.main(
        [
            "--profile-root",
            str(profile_root),
            "--index-root",
            str(index_root),
            "--backend",
            "fake",
            "build",
            "mini",
        ]
    ) == 0
    build_out = json.loads(capsys.readouterr().out)
    assert build_out["embedded_chunks"] > 0

    assert cli.main(
        [
            "--profile-root",
            str(profile_root),
            "--index-root",
            str(index_root),
            "--backend",
            "fake",
            "info",
            "mini",
        ]
    ) == 0
    info_out = json.loads(capsys.readouterr().out)
    assert info_out["stale"] is False

    assert cli.main(
        [
            "--profile-root",
            str(profile_root),
            "--index-root",
            str(index_root),
            "--backend",
            "fake",
            "query",
            "mini",
            "portable profile retrieval",
            "--k",
            "2",
        ]
    ) == 0
    query_out = json.loads(capsys.readouterr().out)
    assert query_out[0]["path"] == "projects/alpha.md"


def test_indexer_writes_pca_sidecar(sqlite_vec_available, tmp_path, mini_profile) -> None:
    index_dir = tmp_path / "index"
    provider = FakeEmbeddingProvider(dim=64)
    report = Indexer(mini_profile, provider, index_dir=index_dir).build()

    pca_path = index_dir / PCA_FILENAME
    assert pca_path.exists()
    payload = load_pca_sidecar(index_dir)
    assert payload is not None
    assert len(payload["mean"]) == 64
    assert len(payload["components"]) == 2
    assert all(len(row) == 64 for row in payload["components"])
    assert len(payload["points"]) == report.total_chunks

    from backend.rag.vector_index import VectorIndex

    vector = VectorIndex(index_dir / "index.sqlite", dim=64)
    try:
        pairs = vector.all_embeddings()
        stored = {p["id"]: (p["x"], p["y"]) for p in payload["points"]}
        for chunk, emb in pairs[:3]:
            px, py = project_query(payload, emb)
            sx, sy = stored[chunk.chunk_id]
            assert abs(px - sx) < 1e-3
            assert abs(py - sy) < 1e-3
    finally:
        vector.close()


def test_indexer_builds_without_pca_when_numpy_missing(
    sqlite_vec_available,
    tmp_path,
    mini_profile,
    monkeypatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("numpy blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    index_dir = tmp_path / "index"
    report = Indexer(
        mini_profile, FakeEmbeddingProvider(dim=64), index_dir=index_dir
    ).build()
    assert report.embedded_chunks > 0
    assert not (index_dir / PCA_FILENAME).exists()
