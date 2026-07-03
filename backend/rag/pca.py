"""PCA sidecar for 2-D retrieval map visualization at index build time."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.rag.vector_index import VectorIndex

log = logging.getLogger("easyagent.rag.pca")

PCA_FILENAME = "pca.json"
_SIDECAR_VERSION = 1


def compute_pca_sidecar(
    vector_index: VectorIndex,
    *,
    backend: str,
    model: str,
    dim: int,
) -> dict | None:
    try:
        import numpy as np
    except ImportError:
        log.warning("numpy unavailable; skipping PCA sidecar")
        return None

    pairs = vector_index.all_embeddings()
    if len(pairs) < 3:
        log.warning("fewer than 3 chunks; skipping PCA sidecar")
        return None

    vecs = [emb for _, emb in pairs]
    X = np.array(vecs)
    mean = X.mean(axis=0)
    _, _, vt = np.linalg.svd(X - mean, full_matrices=False)
    components = vt[:2]
    coords = (X - mean) @ components.T

    points = []
    for i, (chunk, _) in enumerate(pairs):
        heading = " > ".join(chunk.heading_path)
        points.append(
            {
                "id": chunk.chunk_id,
                "path": chunk.path,
                "heading": heading,
                "x": round(float(coords[i, 0]), 5),
                "y": round(float(coords[i, 1]), 5),
            }
        )

    return {
        "version": _SIDECAR_VERSION,
        "embedding_backend": backend,
        "embedding_model": model,
        "embedding_dim": dim,
        "mean": [round(float(v), 5) for v in mean],
        "components": [
            [round(float(v), 5) for v in components[0]],
            [round(float(v), 5) for v in components[1]],
        ],
        "points": points,
    }


def write_pca_sidecar(index_dir: Path, payload: dict) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / PCA_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def load_pca_sidecar(index_dir: Path) -> dict | None:
    path = index_dir / PCA_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != _SIDECAR_VERSION:
        return None
    mean = payload.get("mean")
    components = payload.get("components")
    dim = payload.get("embedding_dim")
    if (
        not isinstance(mean, list)
        or not isinstance(components, list)
        or len(components) != 2
        or not isinstance(dim, int)
        or len(mean) != dim
        or any(len(row) != dim for row in components)
    ):
        return None
    return payload


def project_query(payload: dict, embedding: list[float]) -> tuple[float, float]:
    mean = payload["mean"]
    components = payload["components"]
    if len(embedding) != len(mean):
        raise ValueError("embedding dim mismatch")
    dx = [embedding[i] - mean[i] for i in range(len(mean))]
    x = sum(dx[i] * components[0][i] for i in range(len(dx)))
    y = sum(dx[i] * components[1][i] for i in range(len(dx)))
    return round(x, 5), round(y, 5)
