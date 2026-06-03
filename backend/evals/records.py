"""Eval record + summary construction and run-artifact persistence.

Base layer of the eval harness: no imports from other backend.evals modules, so
backend.evals.retrieval and backend.evals.e2e can depend on it without cycles.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.evals.datasets import RagCase
from backend.profiles import AgentProfile
from backend.rag.embeddings import EmbeddingProvider
from backend.rag.indexer import Indexer


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    summary: dict
    records: list[dict]


def recall_metric(metrics: dict[str, Any]) -> float | None:
    """Read the recall metric, tolerating older runs keyed as ``recall_at_5``."""
    value = metrics.get("recall_at_k")
    if value is None:
        value = metrics.get("recall_at_5")
    return value


def dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def zero_tokens() -> dict[str, int]:
    return {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0}


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


def build_record(
    profile: AgentProfile,
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
    recall = recall_metric(metrics)
    return {
        "schema": 1,
        "run_id": run_id,
        "profile_id": profile.id,
        "mode": mode,
        "variant": variant,
        "case_id": case.id,
        "query": case.query,
        "expected_chunk_paths": list(case.expected_chunk_paths),
        "retrieved_paths": dedupe_paths(paths)[:k],
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


def finalize(
    records: list[dict],
    *,
    profile: AgentProfile,
    embedding: EmbeddingProvider,
    runs_root: Path,
    index_dir: Path | None,
    mode: str,
    variants: tuple[str, ...],
    model_id: str | None,
) -> RunResult:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    for rec in records:
        rec["run_id"] = run_id

    summary = build_summary(
        records,
        run_id=run_id,
        profile=profile,
        embedding=embedding,
        index_dir=index_dir,
        mode=mode,
        variants=variants,
        model_id=model_id,
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


def build_summary(
    records: list[dict],
    *,
    run_id: str,
    profile: AgentProfile,
    embedding: EmbeddingProvider,
    index_dir: Path | None,
    mode: str,
    variants: tuple[str, ...],
    model_id: str | None,
) -> dict:
    try:
        index_info = Indexer(
            profile, embedding, index_dir=index_dir
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
            tokens_total += sum(int(tok.get(k) or 0) for k in zero_tokens())

        latency_vals = [float(r["latency_ms"]) for r in ok_records]
        per_variant[variant] = {
            "recall_at_k": _avg_optional(metric_values("recall_at_k")),
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
        "profile_id": profile.id,
        "mode": mode,
        "variants": list(variants),
        "model_id": model_id,
        "embedding": _embedding_info(embedding),
        "index": index_info,
        "n_cases": len({r["case_id"] for r in records}),
        "per_variant": per_variant,
    }
