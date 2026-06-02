"""Keyword-only retrieval baseline scores (no-RAG bar)."""
from __future__ import annotations

from pathlib import Path

from backend.evals.datasets import load_rag_dataset
from backend.evals.runner import RAGEvaluator
from backend.profiles import load_profile
from backend.rag.embeddings import EmbeddingProvider, get_embedding_provider


def score_baseline(
    profile_ids: list[str] | None = None,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    profile_root: Path | None = None,
) -> dict:
    """Run keyword retrieval-only eval per profile; return per-profile keyword summary."""
    from backend.config import PROFILE_ROOT

    root = (profile_root or PROFILE_ROOT).resolve()
    ids = profile_ids
    if ids is None:
        ids = [
            p.name
            for p in sorted(root.iterdir())
            if p.is_dir() and (p / "profile.json").is_file()
        ]

    embedding = embedding_provider or get_embedding_provider()
    out: dict = {}

    for pid in ids:
        try:
            load_rag_dataset(pid, profile_root=root)
        except FileNotFoundError:
            out[pid] = {"skipped": "rag.json missing"}
            continue

        profile = load_profile(pid, profile_root=root)
        runs_root = (root / pid / "evals" / "runs").resolve()
        evaluator = RAGEvaluator(
            profile, embedding_provider=embedding, runs_root=runs_root
        )
        dataset = load_rag_dataset(pid, profile_root=root)
        result = evaluator.run_retrieval_only(dataset, variants=("keyword",))
        out[pid] = result.summary["per_variant"]["keyword"]

    return out
