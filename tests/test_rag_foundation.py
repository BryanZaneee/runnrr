"""Focused tests for the model-free RAG foundation."""
from __future__ import annotations

import importlib.util

import pytest

from runnrr.rag.bm25_index import BM25Index
from runnrr.rag.chunker import Chunk
from runnrr.rag.manifest import (
    FileEntry,
    Manifest,
    ManifestError,
    compute_diff,
    scan_markdown_files,
)
from runnrr.rag.vector_index import VectorIndex, VectorIndexDependencyError


def _chunk(
    chunk_id: str,
    path: str,
    content: str,
    *,
    heading_path: tuple[str, ...] = (),
    start_line: int = 1,
    end_line: int = 2,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        path=path,
        heading_path=heading_path,
        start_line=start_line,
        end_line=end_line,
        content=content,
        tokens_est=max(1, len(content) // 4),
    )


def test_manifest_missing_file_returns_none(tmp_path) -> None:
    assert Manifest.load(tmp_path / "missing.json") is None


def test_manifest_save_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    manifest = Manifest(
        embedding_backend="fake",
        embedding_model="fake-64d",
        embedding_dim=64,
        files={
            "projects/alpha.md": FileEntry(
                sha256="a" * 64,
                mtime=123.0,
                chunk_count=2,
            )
        },
    )
    manifest.touch()

    manifest.save(path)
    loaded = Manifest.load(path)

    assert loaded is not None
    assert loaded.embedding_backend == "fake"
    assert loaded.files["projects/alpha.md"].chunk_count == 2
    assert loaded.last_built_at


def test_manifest_invalid_json_raises_clear_error(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ManifestError, match="invalid manifest JSON"):
        Manifest.load(path)


def test_manifest_malformed_entry_raises_clear_error(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        '{"version": 1, "files": {"bad.md": {"sha256": "abc"}}}',
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="missing"):
        Manifest.load(path)


def test_scan_markdown_files_and_compute_diff(tmp_path) -> None:
    kb = tmp_path / "kb"
    (kb / "projects").mkdir(parents=True)
    (kb / "projects" / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    (kb / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (kb / "ignore.txt").write_text("not markdown", encoding="utf-8")
    current = scan_markdown_files(kb)

    manifest = Manifest(
        files={
            "projects/alpha.md": FileEntry(
                sha256=current["projects/alpha.md"][0],
                mtime=current["projects/alpha.md"][1],
                chunk_count=1,
            ),
            "old.md": FileEntry(sha256="old", mtime=1.0, chunk_count=1),
        }
    )

    added, modified, removed = compute_diff(kb, manifest)

    assert added == ["notes.md"]
    assert modified == []
    assert removed == ["old.md"]

    (kb / "projects" / "alpha.md").write_text("# Alpha\nChanged\n", encoding="utf-8")
    added, modified, removed = compute_diff(kb, manifest)
    assert modified == ["projects/alpha.md"]


def test_scan_markdown_files_skips_symlink_escape(tmp_path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "inside.md").write_text("# Inside\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    link = kb / "leak.md"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    current = scan_markdown_files(kb)

    assert sorted(current) == ["inside.md"]


def test_bm25_uses_chunks_and_can_delete_by_path() -> None:
    alpha = _chunk(
        "alpha",
        "projects/alpha.md",
        "hybrid retrieval vector store portable profile",
        heading_path=("Alpha",),
    )
    beta = _chunk(
        "beta",
        "projects/beta.md",
        "customer service menu support policy",
        heading_path=("Beta",),
    )
    index = BM25Index()
    index.add(alpha)
    index.add(beta)

    results = index.search("vector retrieval", k=2)

    assert results[0][0] == alpha
    assert isinstance(results[0][0], Chunk)
    assert results[0][0].heading_path == ("Alpha",)

    assert index.delete_by_path("projects/alpha.md") == 1
    assert len(index) == 1
    assert index.search("vector retrieval") == []
    assert index.delete_by_path("missing.md") == 0


def test_bm25_save_load_roundtrip_preserves_chunks(tmp_path) -> None:
    path = tmp_path / "bm25.pkl"
    alpha = _chunk("alpha", "projects/alpha.md", "portable profile retrieval")
    beta = _chunk("beta", "projects/beta.md", "customer service support")
    index = BM25Index()
    index.add(alpha)
    index.add(beta)
    index.save(path)

    loaded = BM25Index.load(path)
    results = loaded.search("customer support", k=1)

    assert len(loaded) == 2
    assert results[0][0] == beta


def test_vector_index_module_import_does_not_require_sqlite_vec() -> None:
    index = VectorIndex(":memory:", dim=2)
    assert index.dim == 2


def test_vector_index_reports_missing_optional_dependency() -> None:
    if importlib.util.find_spec("sqlite_vec") is not None:
        pytest.skip("sqlite-vec is installed; missing-dependency path unavailable")
    index = VectorIndex(":memory:", dim=2)

    with pytest.raises(VectorIndexDependencyError, match="runnrr\\[rag\\]"):
        index.search([1.0, 0.0])


def test_vector_index_roundtrip_upsert_and_delete(tmp_path) -> None:
    pytest.importorskip("sqlite_vec")
    alpha = _chunk(
        "alpha",
        "projects/alpha.md",
        "alpha vector retrieval",
        heading_path=("Alpha",),
    )
    beta = _chunk("beta", "projects/beta.md", "beta customer support")
    index = VectorIndex(tmp_path / "index.sqlite", dim=3)
    try:
        assert index.add_documents(
            [
                (alpha, [1.0, 0.0, 0.0]),
                (beta, [0.0, 1.0, 0.0]),
            ]
        ) == 2
        assert len(index) == 2
        results = index.search([1.0, 0.0, 0.0], k=1)
        assert results[0][0] == alpha

        updated_alpha = _chunk(
            "alpha",
            "projects/alpha.md",
            "alpha updated dense vector",
            heading_path=("Alpha", "Updated"),
        )
        index.add(updated_alpha, [0.0, 0.0, 1.0])
        assert len(index) == 2
        results = index.search([0.0, 0.0, 1.0], k=1)
        assert results[0][0] == updated_alpha

        assert index.delete_by_path("projects/alpha.md") == 1
        assert len(index) == 1
        remaining = index.search([0.0, 0.0, 1.0], k=2)
        assert all(chunk.path != "projects/alpha.md" for chunk, _score in remaining)
    finally:
        index.close()
