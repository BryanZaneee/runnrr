"""End-to-end evaluation: run a full agent turn per case and grade the answer."""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from backend.agent import run_conversation_stream
from backend.evals.datasets import RagCase
from backend.evals.graders import (
    grade_answer_relevance,
    grade_answer_vs_ground_truth,
    grade_faithfulness,
    grade_recall_at_k,
)
from backend.evals.records import build_record
from backend.usage import tally, zero_tokens
from backend.evals.retrieval import EvalCaseSkipped, retrieve
from backend.profiles import AgentProfile
from backend.providers.registry import build_provider
from backend import config

VARIANT_TOOLS: dict[str, tuple[str, ...]] = {
    "keyword": ("search_kb", "read_file"),
    "hybrid": ("semantic_search_kb", "read_file"),
    "hybrid_rerank": ("semantic_search_kb", "read_file"),
    "closed_book": (),
}


def _reduce_events(events: list[dict]) -> tuple[str, list[str], dict[str, int]]:
    answer_parts: list[str] = []
    tool_calls: list[str] = []
    tokens = zero_tokens()
    for ev in events:
        kind = ev.get("event")
        if kind == "delta":
            answer_parts.append(ev.get("text", ""))
        elif kind == "tool_use_start":
            name = ev.get("name")
            if name:
                tool_calls.append(name)
        elif kind == "usage":
            tally(tokens, ev)
    return "".join(answer_parts), tool_calls, tokens


async def _collect(agen: Any) -> list[dict]:
    out: list[dict] = []
    async for ev in agen:
        out.append(ev)
    return out


def end_to_end_record(
    profile: AgentProfile,
    case: RagCase,
    variant: str,
    model_id: str,
    model_cfg: dict,
    *,
    embedding: Any,
    index_dir: Path | None,
    grader_model_id: str,
    rerank_fn: Callable[..., Any] | None,
    grade_fn: Callable[[str], Any] | None,
    provider_factory: Callable[[str], Any] | None,
) -> dict:
    variant_profile = replace(profile, tools=VARIANT_TOOLS[variant])
    factory = provider_factory or (
        lambda mid: build_provider(mid, config.MODEL_REGISTRY[mid])
    )
    provider = factory(model_id)
    session: dict = {
        "messages": [],
        "last_seen": time.time(),
        "provider": model_cfg["provider"],
        "profile": profile.id,
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
            paths, chunk_ids, retrieved = retrieve(
                profile,
                case.query,
                variant,
                k=5,
                embedding=embedding,
                index_dir=index_dir,
                grader_model_id=grader_model_id,
                rerank_fn=rerank_fn,
            )
        except EvalCaseSkipped:
            paths, chunk_ids, retrieved = [], [], []
        context = "\n\n".join(r.get("snippet", "") for r in retrieved)
        recall = grade_recall_at_k(
            paths, list(case.expected_chunk_paths), k=5
        ).score

    grader_reasoning: dict[str, str] = {}
    faith = grade_faithfulness(answer, context, grade_fn=grade_fn)
    metrics: dict[str, float | None] = {
        "recall_at_k": recall,
        "context_precision": None,
        "reciprocal_rank": None,
        "faithfulness": faith.score,
        "answer_relevance": None,
        "answer_vs_ground_truth": None,
    }
    grader_reasoning["faithfulness"] = faith.reasoning

    rel = grade_answer_relevance(answer, case.query, grade_fn=grade_fn)
    metrics["answer_relevance"] = rel.score
    grader_reasoning["answer_relevance"] = rel.reasoning

    if case.ground_truth_answer.strip():
        gt = grade_answer_vs_ground_truth(
            answer, case.ground_truth_answer, grade_fn=grade_fn
        )
        metrics["answer_vs_ground_truth"] = gt.score
        grader_reasoning["answer_vs_ground_truth"] = gt.reasoning
    else:
        metrics["answer_vs_ground_truth"] = None

    return build_record(
        profile,
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
