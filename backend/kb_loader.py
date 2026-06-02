"""Knowledge-base primitives.

Single trust boundary: every path passes through `_safe_resolve()` before any
filesystem op. Read-only. No write operations exist by design.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from backend.config import KB_ROOT

MAX_BYTES_PER_CALL = 80_000
MAX_LINES_PER_READ = 3000
DEFAULT_LINES_PER_READ = 400
LIST_ROOT_DEPTH = 1
LIST_SUBDIR_DEPTH = 2

# Aliases the model might use for project lookup. Maps lowercase input → file slug
# under kb/projects/. Profile-specific aliases live in profile.json; this module
# accepts them via the `aliases` argument to get_project_context().
class KBError(Exception):
    """Raised for any KB violation (path escape, missing file, bad arg)."""


def _root(root: Path | None) -> Path:
    return (root or KB_ROOT).resolve()


def _safe_resolve(rel: str, *, root: Path | None = None) -> Path:
    """Resolve `rel` under root; reject absolute paths, traversal, and symlinks pointing outside."""
    if not isinstance(rel, str):
        raise KBError(f"path must be a string, got {type(rel).__name__}")
    if not rel:
        raise KBError("path must not be empty")
    if Path(rel).is_absolute():
        raise KBError(f"absolute paths not allowed: {rel}")
    base = _root(root)
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise KBError(f"path escapes kb root: {rel}")
    return candidate


def _ignored_path(path: Path) -> bool:
    return path.name.startswith(".") or "__pycache__" in path.parts


def iter_kb_files(
    subdir: str = "",
    *,
    root: Path | None = None,
    pattern: str = "*",
) -> Iterator[tuple[str, Path]]:
    """Yield safe ``(relative_path, resolved_path)`` file pairs under a KB root."""
    base_rel = subdir if subdir else "."
    base = _safe_resolve(base_rel, root=root)
    root_resolved = _root(root)
    if not base.exists() or not base.is_dir():
        return

    for path in sorted(base.rglob(pattern)):
        if _ignored_path(path):
            continue
        try:
            rel = path.relative_to(root_resolved).as_posix()
            resolved = _safe_resolve(rel, root=root_resolved)
        except (KBError, ValueError):
            continue
        if resolved.is_file():
            yield rel, resolved


def iter_markdown_files(*, root: Path | None = None) -> Iterator[tuple[str, Path]]:
    """Yield markdown files using the same path trust boundary as runtime KB tools."""
    yield from iter_kb_files(root=root, pattern="*.md")


def list_kb(subdir: str = "", *, root: Path | None = None) -> list[dict]:
    """List entries under `subdir`. Hidden/junk paths skipped.

    Empty `subdir` walks depth-1 (top-level only) so a root listing of a large KB
    returns categories without exploding into thousands of children. Explicit
    `subdir` walks depth-2 so the model sees one level of drill-down.
    """
    base_rel = subdir if subdir else "."
    base = _safe_resolve(base_rel, root=root)
    if not base.exists():
        return []
    if not base.is_dir():
        raise KBError(f"not a directory: {subdir}")

    max_depth = LIST_ROOT_DEPTH if not subdir else LIST_SUBDIR_DEPTH
    root_resolved = _root(root)
    out: list[dict] = []
    for entry in sorted(base.rglob("*")):
        if len(entry.relative_to(base).parts) > max_depth:
            continue
        if _ignored_path(entry):
            continue
        try:
            rel_to_root = entry.relative_to(root_resolved).as_posix()
            resolved = _safe_resolve(rel_to_root, root=root_resolved)
        except (KBError, ValueError):
            continue
        is_file = resolved.is_file()
        is_dir = resolved.is_dir()
        if not is_file and not is_dir:
            continue
        out.append(
            {
                "path": rel_to_root,
                "size_bytes": resolved.stat().st_size if is_file else 0,
                "kind": "file" if is_file else "dir",
            }
        )
    return out


def read_file(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    *,
    root: Path | None = None,
) -> dict:
    """Read a slice of a KB file. Returns {path, lines, content}.

    Always reports total lines so the caller knows what was omitted.
    """
    p = _safe_resolve(path, root=root)
    if not p.exists() or not p.is_file():
        raise KBError(f"not a file: {path}")

    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)

    if start_line < 1:
        start_line = 1
    cap_end = start_line + MAX_LINES_PER_READ - 1
    if end_line is None:
        end_line = min(start_line + DEFAULT_LINES_PER_READ - 1, total, cap_end)
    else:
        end_line = min(end_line, cap_end, total)
    if end_line < start_line:
        end_line = start_line

    slice_text = "\n".join(lines[start_line - 1 : end_line])

    encoded = slice_text.encode("utf-8")
    if len(encoded) > MAX_BYTES_PER_CALL:
        truncated = encoded[:MAX_BYTES_PER_CALL].decode("utf-8", errors="ignore")
        slice_text = (
            truncated
            + f"\n[truncated; {len(encoded) - MAX_BYTES_PER_CALL} bytes omitted]"
        )

    return {
        "path": path,
        "lines": f"{start_line}-{end_line} of {total}",
        "content": slice_text,
    }


def search_kb(
    query: str,
    regex: bool = False,
    subdir: str = "",
    max_results: int = 20,
    *,
    root: Path | None = None,
) -> list[dict]:
    """Substring (case-insensitive) or regex search across KB files. Returns matches with context."""
    if not query:
        raise KBError("query must not be empty")
    if regex:
        try:
            pat = re.compile(query, re.IGNORECASE)
        except re.error as e:
            raise KBError(f"invalid regex: {e}")
        matcher = lambda line: bool(pat.search(line))
    else:
        ql = query.lower()
        matcher = lambda line: ql in line.lower()

    results: list[dict] = []
    for rel, path in iter_kb_files(subdir, root=root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        size = path.stat().st_size
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if matcher(line):
                lo = max(0, i - 2)
                hi = min(len(lines), i + 1)
                ctx = "\n".join(lines[lo:hi])
                if len(ctx) > 240:
                    ctx = ctx[:240] + "…"
                results.append(
                    {"path": rel, "line": i, "size_bytes": size, "context": ctx}
                )
                if len(results) >= max_results:
                    return results
    return results
