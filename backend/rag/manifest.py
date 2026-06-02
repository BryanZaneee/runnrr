"""On-disk manifest of indexed files.

Tracks (sha256, mtime, chunk_count) per file so the Indexer only re-embeds
files that actually changed. Lives at profiles/<id>/.index/manifest.json
alongside the sqlite-vec DB and the BM25 pickle.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.kb_loader import iter_markdown_files

MANIFEST_VERSION = 1


class ManifestError(ValueError):
    """Raised when a manifest file exists but cannot be trusted."""


@dataclass
class FileEntry:
    sha256: str
    mtime: float
    chunk_count: int


@dataclass
class Manifest:
    version: int = MANIFEST_VERSION
    last_built_at: str = ""
    embedding_backend: str = ""
    embedding_model: str = ""
    embedding_dim: int = 0
    files: dict[str, FileEntry] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "last_built_at": self.last_built_at,
            "embedding_backend": self.embedding_backend,
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "files": {rel: asdict(entry) for rel, entry in self.files.items()},
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "Manifest | None":
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManifestError(
                f"invalid manifest JSON at {path}: {exc.msg}"
            ) from exc
        except OSError as exc:
            raise ManifestError(f"could not read manifest at {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ManifestError(f"manifest at {path} must be a JSON object")
        version = payload.get("version", MANIFEST_VERSION)
        if version != MANIFEST_VERSION:
            raise ManifestError(
                f"unsupported manifest version {version!r} at {path}"
            )
        files_payload = payload.get("files", {})
        if not isinstance(files_payload, dict):
            raise ManifestError(f"manifest files at {path} must be an object")
        files = {
            rel: _file_entry_from_payload(path, rel, entry)
            for rel, entry in files_payload.items()
        }
        return cls(
            version=version,
            last_built_at=payload.get("last_built_at", ""),
            embedding_backend=payload.get("embedding_backend", ""),
            embedding_model=payload.get("embedding_model", ""),
            embedding_dim=payload.get("embedding_dim", 0),
            files=files,
        )

    def touch(self) -> None:
        self.last_built_at = datetime.now(timezone.utc).isoformat()


def _file_entry_from_payload(path: Path, rel: str, entry: object) -> FileEntry:
    if not isinstance(rel, str):
        raise ManifestError(f"manifest path keys at {path} must be strings")
    if not isinstance(entry, dict):
        raise ManifestError(f"manifest entry for {rel!r} at {path} must be an object")
    missing = {"sha256", "mtime", "chunk_count"} - set(entry)
    if missing:
        raise ManifestError(
            f"manifest entry for {rel!r} at {path} is missing {sorted(missing)}"
        )
    sha256 = entry["sha256"]
    if not isinstance(sha256, str) or not sha256:
        raise ManifestError(
            f"manifest entry for {rel!r} at {path} has invalid sha256"
        )
    try:
        mtime = float(entry["mtime"])
        chunk_count = int(entry["chunk_count"])
    except (TypeError, ValueError) as exc:
        raise ManifestError(
            f"manifest entry for {rel!r} at {path} has invalid numeric fields"
        ) from exc
    return FileEntry(sha256=sha256, mtime=mtime, chunk_count=chunk_count)


def scan_markdown_files(kb_root: Path) -> dict[str, tuple[str, float]]:
    """Return {rel_path: (sha256, mtime)} for every *.md under kb_root.

    Hidden files and __pycache__ are skipped. Paths are posix-style relative.
    """
    out: dict[str, tuple[str, float]] = {}
    for rel, path in iter_markdown_files(root=kb_root):
        data = path.read_bytes()
        out[rel] = (hashlib.sha256(data).hexdigest(), path.stat().st_mtime)
    return out


def compute_diff(
    kb_root: Path,
    manifest: Manifest | None,
    *,
    current_files: dict[str, tuple[str, float]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Return (added, modified, removed) rel paths vs. the manifest."""
    current = current_files if current_files is not None else scan_markdown_files(kb_root)
    if manifest is None or not manifest.files:
        return (sorted(current.keys()), [], [])
    added: list[str] = []
    modified: list[str] = []
    for rel, (sha, _mtime) in current.items():
        if rel not in manifest.files:
            added.append(rel)
        elif manifest.files[rel].sha256 != sha:
            modified.append(rel)
    removed = [rel for rel in manifest.files if rel not in current]
    return (sorted(added), sorted(modified), sorted(removed))
