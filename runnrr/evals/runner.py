"""RAG eval harness facade: retrieval-only and end-to-end runs with persisted artifacts.

The implementation is split across sibling modules — runnrr.evals.retrieval
(per-variant retrieval + retrieval records), runnrr.evals.e2e (full-turn runs +
answer grading), and runnrr.evals.records (record/summary construction +
persistence) — and composed here behind the RAGEvaluator orchestration class.
RunResult, EvalCaseSkipped, and VARIANT_TOOLS are re-exported for callers that
imported them from this module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from runnrr import config
from runnrr.evals.datasets import RagDataset
from runnrr.evals.e2e import VARIANT_TOOLS, end_to_end_record
from runnrr.evals.records import RunResult, finalize
from runnrr.evals.retrieval import EvalCaseSkipped, retrieval_record
from runnrr.profiles import AgentProfile
from runnrr.rag.embeddings import EmbeddingProvider, get_embedding_provider

__all__ = ["RAGEvaluator", "RunResult", "EvalCaseSkipped", "VARIANT_TOOLS"]


class RAGEvaluator:
    def __init__(
        self,
        profile: AgentProfile,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        grader_model_id: str | None = None,
        grade_fn: Callable[[str], Any] | None = None,
        provider_factory: Callable[[str], Any] | None = None,
        runs_root: Path | None = None,
        index_dir: Path | None = None,
    ) -> None:
        self.profile = profile
        self.embedding = embedding_provider or get_embedding_provider()
        self.grade_fn = grade_fn
        self.provider_factory = provider_factory
        self.grader_model_id = grader_model_id or config.GRADER_MODEL_ID
        self.runs_root = (runs_root or _default_runs_root(profile)).resolve()
        self.index_dir = index_dir
        self._rerank_fn: Callable[..., Any] | None = None

    def run_retrieval_only(
        self,
        dataset: RagDataset,
        *,
        variants: tuple[str, ...] = ("keyword", "hybrid", "hybrid_rerank"),
        k: int = 5,
    ) -> RunResult:
        records: list[dict] = []
        for case in dataset.cases:
            for variant in variants:
                records.append(
                    retrieval_record(
                        self.profile,
                        case,
                        variant,
                        k,
                        embedding=self.embedding,
                        index_dir=self.index_dir,
                        grader_model_id=self.grader_model_id,
                        rerank_fn=self._rerank_fn,
                    )
                )
        return finalize(
            records,
            profile=self.profile,
            embedding=self.embedding,
            runs_root=self.runs_root,
            index_dir=self.index_dir,
            mode="retrieval-only",
            variants=variants,
            model_id=None,
        )

    def run_end_to_end(
        self,
        dataset: RagDataset,
        *,
        variant: str,
        model_id: str,
    ) -> RunResult:
        if model_id not in config.MODEL_REGISTRY:
            raise KeyError(f"unknown model_id: {model_id}")
        model_cfg = config.MODEL_REGISTRY[model_id]
        records: list[dict] = []
        for case in dataset.cases:
            records.append(
                end_to_end_record(
                    self.profile,
                    case,
                    variant,
                    model_id,
                    model_cfg,
                    embedding=self.embedding,
                    index_dir=self.index_dir,
                    grader_model_id=self.grader_model_id,
                    rerank_fn=self._rerank_fn,
                    grade_fn=self.grade_fn,
                    provider_factory=self.provider_factory,
                )
            )
        return finalize(
            records,
            profile=self.profile,
            embedding=self.embedding,
            runs_root=self.runs_root,
            index_dir=self.index_dir,
            mode="end-to-end",
            variants=(variant,),
            model_id=model_id,
        )


def _default_runs_root(profile: AgentProfile) -> Path:
    return (config.PROFILE_ROOT / profile.id / "evals" / "runs").resolve()
