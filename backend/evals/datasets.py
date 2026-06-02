"""Load per-profile RAG eval case lists from ``profiles/<id>/evals/rag.json``."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from backend.config import PROFILE_ROOT


@dataclass(frozen=True)
class RagCase:
    id: str
    query: str
    expected_chunk_paths: tuple[str, ...] = ()
    ground_truth_answer: str = ""
    criteria: tuple[str, ...] = ()


@dataclass(frozen=True)
class RagDataset:
    profile_id: str
    cases: tuple[RagCase, ...]


def _as_str_tuple(value: object, field: str, case_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(
            f"case {case_id!r}: {field} must be a list of strings"
        )
    return tuple(value)


def load_rag_dataset(
    profile_id: str, *, profile_root: Path | None = None
) -> RagDataset:
    """Read ``(profile_root or PROFILE_ROOT)/<profile_id>/evals/rag.json``."""
    root = (profile_root or PROFILE_ROOT).resolve()
    path = root / profile_id / "evals" / "rag.json"
    if not path.is_file():
        raise FileNotFoundError(f"RAG eval dataset not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON list of cases")

    cases: list[RagCase] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: each case must be a JSON object")
        case_id = item.get("id")
        query = item.get("query")
        if not case_id or not isinstance(case_id, str):
            raise ValueError(f"{path}: each case requires a non-empty string id")
        if not query or not isinstance(query, str):
            raise ValueError(f"{path}: case {case_id!r} requires a non-empty query")

        ground_truth = item.get("ground_truth_answer", "")
        if ground_truth is None:
            ground_truth = ""
        if not isinstance(ground_truth, str):
            raise ValueError(
                f"case {case_id!r}: ground_truth_answer must be a string"
            )

        cases.append(
            RagCase(
                id=case_id,
                query=query,
                expected_chunk_paths=_as_str_tuple(
                    item.get("expected_chunk_paths"), "expected_chunk_paths", case_id
                ),
                ground_truth_answer=ground_truth,
                criteria=_as_str_tuple(item.get("criteria"), "criteria", case_id),
            )
        )

    return RagDataset(profile_id=profile_id, cases=tuple(cases))
