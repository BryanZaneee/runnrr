"""RAG pipeline inspection payload for the /api/rag/inspect endpoint."""
from __future__ import annotations

import math
from pathlib import PurePosixPath

from backend import config
from backend.profiles import AgentProfile
from backend.rag.indexer import VECTOR_FILENAME, default_index_dir
from backend.rag.pca import load_pca_sidecar, project_query
from backend.rag.retriever import (
    DEFAULT_RRF_K,
    RetrievalResult,
    get_retriever_for_profile,
    hybrid_candidate_pool,
)
from backend.rag.tools import _snippet
from backend.rag.vector_index import VectorIndex
from backend.tools.source_metadata import label_from_kb_path


# Bm25Index.search returns exp(-factor * raw) so LOWER is better; invert it back
# to the raw Okapi score for display, where higher = more relevant.
_BM25_NORMALIZATION_FACTOR = 0.1  # matches Bm25Index.search's default

# Cap map points shipped per response (frampton has ~7k chunks → ~800 KB raw).
_MAX_MAP_POINTS = 1500


def _bm25_display_score(normalized: float) -> float:
    return -math.log(max(float(normalized), 1e-9)) / _BM25_NORMALIZATION_FACTOR


def _sample_map_points(points: list[dict], result_ids: list[str]) -> list[dict]:
    if len(points) <= _MAX_MAP_POINTS:
        return points
    keep_ids = set(result_ids)
    stride = len(points) / _MAX_MAP_POINTS
    sampled = [points[int(i * stride)] for i in range(_MAX_MAP_POINTS)]
    sampled_ids = {p["id"] for p in sampled}
    sampled.extend(p for p in points if p["id"] in keep_ids - sampled_ids)
    return sampled


def _cosine_unit(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _heading_label(chunk_heading_path: tuple[str, ...]) -> str:
    return " > ".join(chunk_heading_path)


def inspect_payload(profile: AgentProfile, query: str, k: int) -> dict:
    pool = hybrid_candidate_pool(k, rerank=config.RERANK_ENABLED)
    retriever = get_retriever_for_profile(profile)
    signals = retriever.search_with_signals(query, k=k, candidate_k=pool)

    index_dir = default_index_dir(profile)
    vector_path = index_dir / VECTOR_FILENAME
    vector = VectorIndex(vector_path, dim=retriever.embedding.dim)
    try:
        fused_ids = [r.chunk.chunk_id for r in signals.fused]
        fused_embeddings = vector.embeddings_for(fused_ids)
    finally:
        vector.close()

    labels_cfg = profile.source_labels
    path_labels = profile.source_path_labels

    def label_for(path: str) -> str:
        # The explorer exposes paths by design, so when the sanitizer has no
        # profile mapping, prefer the readable filename over the generic label.
        label = label_from_kb_path(path, labels_cfg, path_labels)
        if label == "Knowledge base document":
            return PurePosixPath(path).stem.replace("_", " ") or label
        return label

    bm25_out = [
        {
            "id": chunk.chunk_id,
            "label": label_for(chunk.path),
            "heading": _heading_label(chunk.heading_path),
            "rank": rank,
            "score": round(_bm25_display_score(score), 3),
        }
        for rank, (chunk, score) in enumerate(signals.bm25_results[:10], start=1)
    ]
    vector_out = [
        {
            "id": chunk.chunk_id,
            "label": label_for(chunk.path),
            "heading": _heading_label(chunk.heading_path),
            "rank": rank,
            "distance": float(distance),
            "similarity": max(0.0, 1.0 - float(distance) ** 2 / 2.0),
        }
        for rank, (chunk, distance) in enumerate(signals.vector_results[:10], start=1)
    ]

    results_out = [
        _result_entry(r, signals.query_embedding, fused_embeddings, label_for)
        for r in signals.fused
    ]

    preview_len = min(retriever.embedding.dim, 64)
    embedding_block = {
        "backend": retriever.embedding.backend,
        "model": retriever.embedding.model,
        "dim": retriever.embedding.dim,
        "preview": [
            round(v, 4) for v in signals.query_embedding[:preview_len]
        ],
    }

    pca = load_pca_sidecar(index_dir)
    if pca is not None and len(signals.query_embedding) == pca.get("embedding_dim"):
        qx, qy = project_query(pca, signals.query_embedding)
        map_block: dict = {
            "available": True,
            "points": _sample_map_points(pca.get("points", []), fused_ids),
            "query": {"x": qx, "y": qy},
            "result_ids": fused_ids,
        }
    else:
        map_block = {"available": False}

    return {
        "profile_id": profile.id,
        "query": query,
        "k": k,
        "pipeline": {
            "rrf_k": DEFAULT_RRF_K,
            "candidate_pool": pool,
            "rerank_enabled": config.RERANK_ENABLED,
        },
        "embedding": embedding_block,
        "bm25": bm25_out,
        "vector": vector_out,
        "results": results_out,
        "map": map_block,
    }


def _result_entry(
    result: RetrievalResult,
    query_embedding: list[float],
    fused_embeddings: dict[str, list[float]],
    label_for,
) -> dict:
    chunk = result.chunk
    emb = fused_embeddings.get(chunk.chunk_id)
    cosine = _cosine_unit(query_embedding, emb) if emb is not None else None
    return {
        "id": chunk.chunk_id,
        "label": label_for(chunk.path),
        "path": chunk.path,
        "heading_path": list(chunk.heading_path),
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "snippet": _snippet(chunk.content),
        "score": result.score,
        "bm25_score": result.bm25_score,
        "bm25_rank": result.bm25_rank,
        "vector_distance": result.vector_score,
        "vector_rank": result.vector_rank,
        "cosine": cosine,
    }
