"""Chunker tests. Deterministic IDs, header tracking, sliding-window overlap."""
from __future__ import annotations

from backend.rag.chunker import (
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TARGET_TOKENS,
    chunk_markdown,
)


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_markdown("foo.md", "") == []
    assert chunk_markdown("foo.md", "   \n\n  ") == []


def test_no_headings_produces_single_chunk() -> None:
    text = "Just a paragraph.\nAnother line.\nThird."
    chunks = chunk_markdown("notes/release.md", text)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.path == "notes/release.md"
    assert c.heading_path == ()
    assert c.start_line == 1
    assert c.end_line == 3
    assert "Just a paragraph." in c.content


def test_h1_and_h2_build_heading_path() -> None:
    text = "# Alpha\n\nIntro paragraph.\n\n## Overview\n\nOverview body.\n\n## Architecture\n\nArchitecture body."
    chunks = chunk_markdown("projects/alpha.md", text)
    # 3 sections: H1 "Alpha", H2 "Overview", H2 "Architecture"
    assert len(chunks) == 3
    assert chunks[0].heading_path == ("Alpha",)
    assert chunks[1].heading_path == ("Alpha", "Overview")
    assert chunks[2].heading_path == ("Alpha", "Architecture")


def test_h2_only_file_inherits_no_h1() -> None:
    text = "## Beta\n\nBody.\n\n## Caveats\n\nMore body."
    chunks = chunk_markdown("projects/beta.md", text)
    assert len(chunks) == 2
    assert chunks[0].heading_path == ("Beta",)
    assert chunks[1].heading_path == ("Caveats",)


def test_chunk_id_is_deterministic_across_runs() -> None:
    text = "# Alpha\n\nFirst.\n\n## Overview\n\nBody body body."
    a = chunk_markdown("projects/alpha.md", text)
    b = chunk_markdown("projects/alpha.md", text)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]


def test_chunk_id_changes_when_path_changes() -> None:
    text = "## Section\n\nBody."
    a = chunk_markdown("a.md", text)
    b = chunk_markdown("b.md", text)
    assert a[0].chunk_id != b[0].chunk_id


def test_long_section_splits_with_overlap() -> None:
    # Build a single section well over target_tokens.
    body_lines = ["# Doc"]
    # ~10 tokens per line at len("word " * 8) = 40 chars / 4
    body_lines.extend(["word " * 8 for _ in range(200)])
    text = "\n".join(body_lines)
    chunks = chunk_markdown("big.md", text, target_tokens=100, overlap_tokens=20)
    assert len(chunks) >= 3
    # Heading carries to every chunk in the section
    for c in chunks:
        assert c.heading_path == ("Doc",)
    # Overlap: every chunk after the first should start no later than the
    # previous chunk's end_line + 1, and usually earlier (overlap > 0).
    overlaps_present = 0
    for prev, curr in zip(chunks, chunks[1:]):
        assert curr.start_line <= prev.end_line + 1
        if curr.start_line <= prev.end_line:
            overlaps_present += 1
    assert overlaps_present >= 1


def test_chunks_content_includes_heading_line() -> None:
    text = "# Title\n\nFirst body line."
    chunks = chunk_markdown("doc.md", text)
    assert len(chunks) == 1
    assert chunks[0].content.startswith("# Title")


def test_chunk_keeps_heading_path_as_tuple() -> None:
    chunks = chunk_markdown("doc.md", "## S\n\nbody")
    assert chunks[0].heading_path == ("S",)


def test_default_target_and_overlap_are_used_when_unset() -> None:
    # Short doc fits in a single chunk under defaults.
    chunks = chunk_markdown("doc.md", "## S\n\nshort body")
    assert len(chunks) == 1
    assert chunks[0].tokens_est <= DEFAULT_TARGET_TOKENS
    # Sanity: defaults exist and are sane.
    assert DEFAULT_OVERLAP_TOKENS < DEFAULT_TARGET_TOKENS
