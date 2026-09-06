"""Optional LLM reranking over hybrid RRF retrieval candidates."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from runnrr import config
from runnrr.rag.retriever import RetrievalResult

log = logging.getLogger("runnrr.rag")

RERANK_CANDIDATES = 15
_SNIPPET_CHARS = 300
_MISSING_RELEVANCE = -1.0


class LLMReranker:
    def __init__(self, *, model_id: str | None = None, complete_fn=None) -> None:
        self.model_id = model_id or config.GRADER_MODEL_ID
        if complete_fn is None:
            from runnrr.llm_json import complete_json

            self._complete: Callable[[str], Any] = lambda p: complete_json(
                p, model_id=self.model_id
            )
        else:
            self._complete = complete_fn

    def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        *,
        top_k: int = RERANK_CANDIDATES,
    ) -> list[RetrievalResult]:
        """Reorder top candidates by LLM relevance; never raises."""
        try:
            candidates = results[:top_k]
            if len(candidates) < 2:
                return candidates

            raw = self._complete(_build_prompt(query, candidates))
            relevance = _parse_relevance(raw)
            scored: list[tuple[int, float, RetrievalResult]] = []
            for idx, result in enumerate(candidates):
                cid = result.chunk.chunk_id
                score = relevance.get(cid, _MISSING_RELEVANCE)
                scored.append((idx, score, result))
            scored.sort(key=lambda t: (-t[1], t[0]))
            return [r for _, _, r in scored]
        except Exception as exc:
            log.debug("LLM rerank failed, using RRF order: %s", exc)
            return results[:top_k]


def _build_prompt(query: str, candidates: list[RetrievalResult]) -> str:
    lines = [
        "Rank these knowledge-base chunks by relevance to the user query.",
        f'Query: "{query.strip()}"',
        "",
        "Candidates:",
    ]
    for i, result in enumerate(candidates):
        snippet = re.sub(r"\s+", " ", result.chunk.content).strip()
        if len(snippet) > _SNIPPET_CHARS:
            snippet = snippet[: _SNIPPET_CHARS - 3].rstrip() + "..."
        lines.append(
            f"{i}. chunk_id={result.chunk.chunk_id!r} path={result.chunk.path!r}\n"
            f"   {snippet}"
        )
    lines.append(
        "\nRespond with a JSON array only, one object per candidate you judged, "
        'each like {"chunk_id": "<id>", "relevance": <0-10>} where 10 is most relevant.'
    )
    return "\n".join(lines)


def _parse_relevance(raw: Any) -> dict[str, float]:
    if not isinstance(raw, list):
        return {}
    out: dict[str, float] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        cid = item.get("chunk_id")
        rel = item.get("relevance")
        if not isinstance(cid, str) or rel is None:
            continue
        try:
            out[cid] = float(rel)
        except (TypeError, ValueError):
            continue
    return out
