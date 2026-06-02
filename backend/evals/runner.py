"""RAG eval harness: retrieval-only and end-to-end runs with persisted artifacts."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend import config
from backend.agent import run_conversation_stream
from backend.evals.datasets import RagCase, RagDataset
from backend.evals.graders import (
    grade_answer_relevance,
    grade_answer_vs_ground_truth,
    grade_context_precision,
    grade_faithfulness,
    grade_recall_at_k,
    reciprocal_rank,
)
from backend.kb_loader import search_kb
from backend.profiles import AgentProfile
from backend.providers.registry import build_provider
from backend.rag.embeddings import EmbeddingProvider, get_embedding_provider
from backend.rag.indexer import Indexer
from backend.rag.reranker import RERANK_CANDIDATES
from backend.rag.retriever import get_retriever_for_profile

VARIANT_TOOLS: dict[str, tuple[str, ...]] = {
    "keyword": ("search_kb", "read_file"),
    "hybrid": ("semantic_search_kb", "read_file"),
    "hybrid_rerank": ("semantic_search_kb", "read_file"),
    "closed_book": (),
}


class EvalCaseSkipped(Exception):
    """Raised when a variant cannot run (e.g. missing RAG index)."""


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    summary: dict
    records: list[dict]


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _avg_optional(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _embedding_info(embedding: EmbeddingProvider) -> dict[str, Any]:
    return {
        "backend": embedding.backend,
        "model": embedding.model,
        "dim": embedding.dim,
    }


def _zero_tokens() -> dict[str, int]:
    return {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0}


def _reduce_events(events: list[dict]) -> tuple[str, list[str], dict[str, int]]:
    answer_parts: list[str] = []
    tool_calls: list[str] = []
    tokens = _zero_tokens()
    for ev in events:
        kind = ev.get("event")
        if kind == "delta":
            answer_parts.append(ev.get("text", ""))
        elif kind == "tool_use_start":
            name = ev.get("name")
            if name:
                tool_calls.append(name)
        elif kind == "usage":
            tokens["input"] += int(ev.get("input_tokens") or 0)
            tokens["output"] += int(ev.get("output_tokens") or 0)
            tokens["cache_read"] += int(ev.get("cache_read_input_tokens") or 0)
            tokens["reasoning"] += int(ev.get("reasoning_tokens") or 0)
    return "".join(answer_parts), tool_calls, tokens


def _failure_label(
    *,
    status: str,
    recall: float | None,
    expected: tuple[str, ...],
    skip_reason: str | None = None,
) -> str | None:
    if status == "skipped" and skip_reason:
        return skip_reason
    if (
        status == "ok"
        and recall is not None
        and recall == 0.0
        and expected
    ):
        return "missed_expected_chunk"
    return None


async def _collect(agen: Any) -> list[dict]:
    out: list[dict] = []
    async for ev in agen:
        out.append(ev)
    return out


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

    def _retrieve(
        self, query: str, variant: str, k: int
    ) -> tuple[list[str], list[str], list[dict]]:
        if variant == "keyword":
            hits = search_kb(
                query,
                root=self.profile.kb_root,
                max_results=max(k * 4, 20),
            )
            paths = _dedupe_paths([h["path"] for h in hits])
            retrieved = [
                {
                    "path": h["path"],
                    "line": h["line"],
                    "snippet": h["context"],
                }
                for h in hits[:k]
            ]
            return paths, [], retrieved

        if variant in ("hybrid", "hybrid_rerank"):
            try:
                retr = get_retriever_for_profile(
                    self.profile,
                    embedding_provider=self.embedding,
                    index_dir=self.index_dir,
                )
            except FileNotFoundError as exc:
                raise EvalCaseSkipped(str(exc)) from exc

            pool = (
                max(k, RERANK_CANDIDATES)
                if variant == "hybrid_rerank"
                else max(k, k * 3)
            )
            results = retr.search(query, k=pool)
            if variant == "hybrid_rerank":
                from backend.rag.reranker import LLMReranker

                results = LLMReranker(
                    model_id=self.grader_model_id,
                    complete_fn=self._rerank_fn,
                ).rerank(query, results, top_k=pool)

            paths = _dedupe_paths([r.chunk.path for r in results])
            chunk_ids = [r.chunk.chunk_id for r in results][:k]
            retrieved = [
                {
                    "path": r.chunk.path,
                    "start_line": r.chunk.start_line,
                    "end_line": r.chunk.end_line,
                    "score": r.score,
                    "snippet": r.chunk.content[:400],
                }
                for r in results[:k]
            ]
            return paths, chunk_ids, retrieved

        raise ValueError(f"unknown retrieval variant: {variant}")

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
                records.append(self._retrieval_record(case, variant, k))
        return self._finalize(
            records,
            mode="retrieval-only",
            variants=variants,
            model_id=None,
        )

    def _retrieval_record(self, case: RagCase, variant: str, k: int) -> dict:
        run_id_placeholder = ""
        t0 = time.perf_counter()
        try:
            paths, chunk_ids, retrieved = self._retrieve(case.query, variant, k)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            recall = grade_recall_at_k(
                paths, list(case.expected_chunk_paths), k=k
            ).score
            precision = grade_context_precision(
                paths, list(case.expected_chunk_paths), k=k
            ).score
            rr = reciprocal_rank(paths, list(case.expected_chunk_paths))
            metrics = {
                "recall_at_5": recall,
                "context_precision": precision,
                "reciprocal_rank": rr,
                "faithfulness": None,
                "answer_relevance": None,
                "answer_vs_ground_truth": None,
            }
            status = "ok"
            skip_reason = None
        except EvalCaseSkipped as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            paths, chunk_ids, retrieved = [], [], []
            metrics = {
                "recall_at_5": None,
                "context_precision": None,
                "reciprocal_rank": None,
                "faithfulness": None,
                "answer_relevance": None,
                "answer_vs_ground_truth": None,
            }
            status = "skipped"
            skip_reason = str(exc)

        return self._build_record(
            run_id=run_id_placeholder,
            mode="retrieval-only",
            variant=variant,
            case=case,
            paths=paths,
            chunk_ids=chunk_ids,
            retrieved=retrieved,
            metrics=metrics,
            grader_reasoning={},
            answer="",
            tool_calls=[],
            latency_ms=latency_ms,
            tokens=_zero_tokens(),
            status=status,
            k=k,
            skip_reason=skip_reason,
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
                self._end_to_end_record(case, variant, model_id, model_cfg)
            )
        return self._finalize(
            records,
            mode="end-to-end",
            variants=(variant,),
            model_id=model_id,
        )

    def _end_to_end_record(
        self,
        case: RagCase,
        variant: str,
        model_id: str,
        model_cfg: dict,
    ) -> dict:
        variant_profile = replace(self.profile, tools=VARIANT_TOOLS[variant])
        factory = self.provider_factory or (
            lambda mid: build_provider(mid, config.MODEL_REGISTRY[mid])
        )
        provider = factory(model_id)
        session: dict = {
            "messages": [],
            "last_seen": time.time(),
            "provider": model_cfg["provider"],
            "profile": self.profile.id,
        }

        t0 = time.perf_counter()
        events = asyncio.run(
            _collect(
                run_conversation_stream(
                    case.query,
                    session,
                    provider,
                    model_cfg["model"],
                    variant_profile,
                )
            )
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        answer, tool_calls, tokens = _reduce_events(events)

        if variant == "closed_book":
            paths, chunk_ids, retrieved = [], [], []
            context = ""
            recall: float | None = None
        else:
            try:
                paths, chunk_ids, retrieved = self._retrieve(case.query, variant, k=5)
            except EvalCaseSkipped:
                paths, chunk_ids, retrieved = [], [], []
            context = "\n\n".join(r.get("snippet", "") for r in retrieved)
            recall = grade_recall_at_k(
                paths, list(case.expected_chunk_paths), k=5
            ).score

        grader_reasoning: dict[str, str] = {}
        faith = grade_faithfulness(answer, context, grade_fn=self.grade_fn)
        metrics: dict[str, float | None] = {
            "recall_at_5": recall,
            "context_precision": None,
            "reciprocal_rank": None,
            "faithfulness": faith.score,
            "answer_relevance": None,
            "answer_vs_ground_truth": None,
        }
        grader_reasoning["faithfulness"] = faith.reasoning

        rel = grade_answer_relevance(answer, case.query, grade_fn=self.grade_fn)
        metrics["answer_relevance"] = rel.score
        grader_reasoning["answer_relevance"] = rel.reasoning

        if case.ground_truth_answer.strip():
            gt = grade_answer_vs_ground_truth(
                answer, case.ground_truth_answer, grade_fn=self.grade_fn
            )
            metrics["answer_vs_ground_truth"] = gt.score
            grader_reasoning["answer_vs_ground_truth"] = gt.reasoning
        else:
            metrics["answer_vs_ground_truth"] = None

        return self._build_record(
            run_id="",
            mode="end-to-end",
            variant=variant,
            case=case,
            paths=paths,
            chunk_ids=chunk_ids,
            retrieved=retrieved,
            metrics=metrics,
            grader_reasoning=grader_reasoning,
            answer=answer,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            tokens=tokens,
            status="ok",
            k=5,
            skip_reason=None,
        )

    def _build_record(
        self,
        *,
        run_id: str,
        mode: str,
        variant: str,
        case: RagCase,
        paths: list[str],
        chunk_ids: list[str],
        retrieved: list[dict],
        metrics: dict[str, float | None],
        grader_reasoning: dict[str, str],
        answer: str,
        tool_calls: list[str],
        latency_ms: float,
        tokens: dict[str, int],
        status: str,
        k: int,
        skip_reason: str | None,
    ) -> dict:
        recall = metrics.get("recall_at_5")
        return {
            "schema": 1,
            "run_id": run_id,
            "profile_id": self.profile.id,
            "mode": mode,
            "variant": variant,
            "case_id": case.id,
            "query": case.query,
            "expected_chunk_paths": list(case.expected_chunk_paths),
            "retrieved_paths": _dedupe_paths(paths)[:k],
            "retrieved_chunk_ids": chunk_ids,
            "retrieved": retrieved,
            "metrics": metrics,
            "grader_reasoning": grader_reasoning,
            "answer": answer,
            "tool_calls": tool_calls,
            "latency_ms": latency_ms,
            "tokens": tokens,
            "status": status,
            "failure_label": _failure_label(
                status=status,
                recall=recall,
                expected=case.expected_chunk_paths,
                skip_reason=skip_reason,
            ),
        }

    def _finalize(
        self,
        records: list[dict],
        *,
        mode: str,
        variants: tuple[str, ...],
        model_id: str | None,
    ) -> RunResult:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        for rec in records:
            rec["run_id"] = run_id

        summary = self._build_summary(
            run_id, records, mode=mode, variants=variants, model_id=model_id
        )

        records_path = run_dir / "records.jsonl"
        with records_path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

        summary_path = run_dir / "summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return RunResult(run_id=run_id, run_dir=run_dir, summary=summary, records=records)

    def _build_summary(
        self,
        run_id: str,
        records: list[dict],
        *,
        mode: str,
        variants: tuple[str, ...],
        model_id: str | None,
    ) -> dict:
        try:
            index_info = Indexer(
                self.profile, self.embedding, index_dir=self.index_dir
            ).info().to_dict()
        except Exception:
            index_info = {}

        per_variant: dict[str, dict] = {}
        for variant in variants:
            variant_records = [r for r in records if r.get("variant") == variant]
            ok_records = [r for r in variant_records if r.get("status") == "ok"]
            skipped = len(variant_records) - len(ok_records)

            def metric_values(key: str) -> list[float]:
                vals: list[float] = []
                for rec in ok_records:
                    val = rec.get("metrics", {}).get(key)
                    if val is not None:
                        vals.append(float(val))
                return vals

            tokens_total = 0
            for rec in ok_records:
                tok = rec.get("tokens") or {}
                tokens_total += sum(int(tok.get(k) or 0) for k in _zero_tokens())

            latency_vals = [float(r["latency_ms"]) for r in ok_records]
            per_variant[variant] = {
                "recall_at_5": _avg_optional(metric_values("recall_at_5")),
                "context_precision": _avg_optional(metric_values("context_precision")),
                "mrr": _avg_optional(metric_values("reciprocal_rank")),
                "faithfulness": _avg_optional(metric_values("faithfulness")),
                "answer_relevance": _avg_optional(metric_values("answer_relevance")),
                "latency_ms_avg": _avg_optional(latency_vals),
                "tokens_total": tokens_total,
                "n_ok": len(ok_records),
                "n_skipped": skipped,
            }

        return {
            "schema": 1,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "profile_id": self.profile.id,
            "mode": mode,
            "variants": list(variants),
            "model_id": model_id,
            "embedding": _embedding_info(self.embedding),
            "index": index_info,
            "n_cases": len({r["case_id"] for r in records}),
            "per_variant": per_variant,
        }


def _default_runs_root(profile: AgentProfile) -> Path:
    return (config.PROFILE_ROOT / profile.id / "evals" / "runs").resolve()
