"""Build and inspect per-profile RAG indexes."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from backend import config
from backend.profiles import AgentProfile
from backend.rag.bm25_index import BM25Index
from backend.rag.chunker import Chunk, chunk_markdown
from backend.rag.embeddings import EmbeddingProvider, get_embedding_provider
from backend.kb_loader import _safe_resolve
from backend.rag.manifest import FileEntry, Manifest, compute_diff, scan_markdown_files
from backend.rag.pca import PCA_FILENAME, compute_pca_sidecar, write_pca_sidecar
from backend.rag.vector_index import VectorIndex

BM25_FILENAME = "bm25.pkl"
MANIFEST_FILENAME = "manifest.json"
VECTOR_FILENAME = "index.sqlite"


@dataclass(frozen=True)
class BuildReport:
    profile_id: str
    index_dir: str
    added: tuple[str, ...]
    modified: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged_files: int
    total_files: int
    total_chunks: int
    embedded_chunks: int
    deleted_bm25_chunks: int
    deleted_vector_chunks: int
    force: bool
    rebuilt: bool
    stale_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IndexInfo:
    profile_id: str
    index_dir: str
    manifest_exists: bool
    bm25_exists: bool
    vector_exists: bool
    embedding_backend: str
    embedding_model: str
    embedding_dim: int
    indexed_files: int
    indexed_chunks: int
    stale: bool
    stale_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def default_index_dir(profile: AgentProfile) -> Path:
    """Return the default profile-scoped index directory."""
    from backend import config

    if not profile.id or "/" in profile.id or "\\" in profile.id or profile.id in {".", ".."}:
        raise ValueError(f"unsafe profile id for index path: {profile.id!r}")
    if config.RAG_INDEX_ROOT is not None:
        return (config.RAG_INDEX_ROOT / profile.id).resolve()
    return (config.PROFILE_ROOT / profile.id / ".index").resolve()


class Indexer:
    def __init__(
        self,
        profile: AgentProfile,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        index_dir: Path | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.profile = profile
        self.embedding = embedding_provider or get_embedding_provider()
        self.index_dir = (index_dir or default_index_dir(profile)).resolve()
        self.batch_size = max(1, int(batch_size or config.EMBED_BATCH_SIZE))
        self.manifest_path = self.index_dir / MANIFEST_FILENAME
        self.bm25_path = self.index_dir / BM25_FILENAME
        self.vector_path = self.index_dir / VECTOR_FILENAME

    def build(self, *, force: bool = False) -> BuildReport:
        """Build or incrementally update the active profile index."""
        old_manifest = Manifest.load(self.manifest_path)
        current_files = scan_markdown_files(self.profile.kb_root)
        was_stale, stale_reason = self._stale_from_state(old_manifest, current_files)
        embedding_changed = old_manifest is not None and not self._manifest_matches_embedding(old_manifest)
        index_files_missing = self._index_files_missing()
        rebuilt = force or old_manifest is None or embedding_changed or index_files_missing

        if rebuilt:
            self._clear_cached_retriever()
            self._reset_index_files()
            old_manifest = None

        added, modified, removed = compute_diff(
            self.profile.kb_root,
            old_manifest,
            current_files=current_files,
        )
        changed = sorted(set(added + modified))
        if not rebuilt and (changed or removed):
            self._clear_cached_retriever()

        bm25 = BM25Index() if rebuilt else self._load_bm25()
        vector = VectorIndex(self.vector_path, dim=self.embedding.dim)
        deleted_bm25 = 0
        deleted_vector = 0
        embedded_chunks = 0
        chunk_counts: dict[str, int] = {}

        try:
            vector.ensure_schema()
            for rel_path in sorted(set(modified + removed)):
                deleted_bm25 += bm25.delete_by_path(rel_path)
                deleted_vector += vector.delete_by_path(rel_path)

            chunks_by_path = self._chunk_changed_files(changed)
            for rel_path, chunks in chunks_by_path.items():
                chunk_counts[rel_path] = len(chunks)
                embedded_chunks += self._embed_and_write(chunks, bm25=bm25, vector=vector)

            bm25.save(self.bm25_path)
            self._maybe_write_pca_sidecar(
                vector,
                embedded_chunks=embedded_chunks,
                deleted_vector_chunks=deleted_vector,
                rebuilt=rebuilt,
            )
        finally:
            vector.close()

        manifest = self._new_manifest(current_files, old_manifest, chunk_counts)
        manifest.save(self.manifest_path)
        total_chunks = sum(entry.chunk_count for entry in manifest.files.values())
        unchanged_files = max(0, len(current_files) - len(changed))
        return BuildReport(
            profile_id=self.profile.id,
            index_dir=str(self.index_dir),
            added=tuple(added),
            modified=tuple(modified),
            removed=tuple(removed),
            unchanged_files=unchanged_files,
            total_files=len(current_files),
            total_chunks=total_chunks,
            embedded_chunks=embedded_chunks,
            deleted_bm25_chunks=deleted_bm25,
            deleted_vector_chunks=deleted_vector,
            force=force,
            rebuilt=rebuilt,
            stale_reason=stale_reason if was_stale else "index was current",
        )

    def is_stale(self) -> tuple[bool, str]:
        """Return (is_stale, reason) for the active profile index."""
        manifest = Manifest.load(self.manifest_path)
        current_files = scan_markdown_files(self.profile.kb_root)
        return self._stale_from_state(manifest, current_files)

    def _stale_from_state(
        self,
        manifest: Manifest | None,
        current_files: dict[str, tuple[str, float]],
    ) -> tuple[bool, str]:
        if manifest is None:
            return True, "manifest missing"

        missing = [
            name
            for name, path in (
                (BM25_FILENAME, self.bm25_path),
                (VECTOR_FILENAME, self.vector_path),
            )
            if not path.exists()
        ]
        if missing:
            return True, "index files missing: " + ", ".join(missing)

        if not self._manifest_matches_embedding(manifest):
            return (
                True,
                "embedding config changed: "
                f"{manifest.embedding_backend}/{manifest.embedding_model}/{manifest.embedding_dim} "
                f"!= {self.embedding.backend}/{self.embedding.model}/{self.embedding.dim}",
            )

        added, modified, removed = compute_diff(
            self.profile.kb_root,
            manifest,
            current_files=current_files,
        )
        if added or modified or removed:
            return True, _diff_reason(added, modified, removed)
        return False, "index is current"

    def info(self) -> IndexInfo:
        stale, reason = self.is_stale()
        manifest = Manifest.load(self.manifest_path)
        indexed_files = len(manifest.files) if manifest else 0
        indexed_chunks = (
            sum(entry.chunk_count for entry in manifest.files.values())
            if manifest
            else 0
        )
        return IndexInfo(
            profile_id=self.profile.id,
            index_dir=str(self.index_dir),
            manifest_exists=self.manifest_path.exists(),
            bm25_exists=self.bm25_path.exists(),
            vector_exists=self.vector_path.exists(),
            embedding_backend=manifest.embedding_backend if manifest else self.embedding.backend,
            embedding_model=manifest.embedding_model if manifest else self.embedding.model,
            embedding_dim=manifest.embedding_dim if manifest else self.embedding.dim,
            indexed_files=indexed_files,
            indexed_chunks=indexed_chunks,
            stale=stale,
            stale_reason=reason,
        )

    def _manifest_matches_embedding(self, manifest: Manifest) -> bool:
        return (
            manifest.embedding_backend == self.embedding.backend
            and manifest.embedding_model == self.embedding.model
            and manifest.embedding_dim == self.embedding.dim
        )

    def _index_files_missing(self) -> bool:
        return not self.bm25_path.exists() or not self.vector_path.exists()

    def _reset_index_files(self) -> None:
        for path in (self.manifest_path, self.bm25_path, self.vector_path):
            if path.exists():
                path.unlink()

    def _maybe_write_pca_sidecar(
        self,
        vector: VectorIndex,
        *,
        embedded_chunks: int,
        deleted_vector_chunks: int,
        rebuilt: bool,
    ) -> None:
        pca_path = self.index_dir / PCA_FILENAME
        should_regenerate = (
            embedded_chunks > 0
            or deleted_vector_chunks > 0
            or rebuilt
            or not pca_path.exists()
        )
        if not should_regenerate:
            return
        payload = compute_pca_sidecar(
            vector,
            backend=self.embedding.backend,
            model=self.embedding.model,
            dim=self.embedding.dim,
        )
        if payload is None:
            if pca_path.exists():
                pca_path.unlink()
            return
        write_pca_sidecar(self.index_dir, payload)

    def _clear_cached_retriever(self) -> None:
        from backend.rag.retriever import clear_retriever_cache

        clear_retriever_cache(profile_id=self.profile.id, index_dir=self.index_dir)

    def _load_bm25(self) -> BM25Index:
        if not self.bm25_path.exists():
            return BM25Index()
        return BM25Index.load(self.bm25_path)

    def _chunk_changed_files(self, rel_paths: Iterable[str]) -> dict[str, list[Chunk]]:
        out: dict[str, list[Chunk]] = {}
        for rel_path in rel_paths:
            path = _safe_resolve(rel_path, root=self.profile.kb_root)
            text = path.read_text(encoding="utf-8", errors="replace")
            out[rel_path] = chunk_markdown(rel_path, text)
        return out

    def _embed_and_write(
        self,
        chunks: list[Chunk],
        *,
        bm25: BM25Index,
        vector: VectorIndex,
    ) -> int:
        written = 0
        for batch in _batches(chunks, self.batch_size):
            embeddings = self.embedding.embed_documents([chunk.content for chunk in batch])
            if len(embeddings) != len(batch):
                raise ValueError(
                    f"embedding provider returned {len(embeddings)} vectors for {len(batch)} chunks"
                )
            vector.add_documents(zip(batch, embeddings))
            for chunk in batch:
                bm25.add(chunk)
            written += len(batch)
        return written

    def _new_manifest(
        self,
        current_files: dict[str, tuple[str, float]],
        old_manifest: Manifest | None,
        chunk_counts: dict[str, int],
    ) -> Manifest:
        files: dict[str, FileEntry] = {}
        for rel_path, (sha256, mtime) in current_files.items():
            if rel_path in chunk_counts:
                count = chunk_counts[rel_path]
            elif old_manifest and rel_path in old_manifest.files:
                count = old_manifest.files[rel_path].chunk_count
            else:
                count = 0
            files[rel_path] = FileEntry(
                sha256=sha256,
                mtime=mtime,
                chunk_count=count,
            )
        manifest = Manifest(
            embedding_backend=self.embedding.backend,
            embedding_model=self.embedding.model,
            embedding_dim=self.embedding.dim,
            files=files,
        )
        manifest.touch()
        return manifest


def _batches(items: list[Chunk], batch_size: int) -> Iterable[list[Chunk]]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def _diff_reason(added: list[str], modified: list[str], removed: list[str]) -> str:
    parts = []
    if added:
        parts.append("added: " + ", ".join(added))
    if modified:
        parts.append("modified: " + ", ".join(modified))
    if removed:
        parts.append("removed: " + ", ".join(removed))
    return "; ".join(parts)
