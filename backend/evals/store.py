"""Read-only access to persisted eval run artifacts under each profile."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend import config

log = logging.getLogger(__name__)


def runs_root_for(profile_id: str) -> Path:
    return config.PROFILE_ROOT / profile_id / "evals" / "runs"


def _safe_run_id(run_id: str) -> str:
    if not run_id or run_id in {"", ".", ".."}:
        raise ValueError("invalid run_id")
    if run_id != Path(run_id).name:
        raise ValueError("invalid run_id")
    return run_id


def list_runs(profile_id: str) -> list[dict]:
    root = runs_root_for(profile_id)
    if not root.is_dir():
        return []
    summaries: list[dict] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        summary_path = entry / "summary.json"
        if not summary_path.is_file():
            continue
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                summaries.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            log.debug("skipping unreadable summary %s: %s", summary_path, exc)
            continue
    summaries.sort(
        key=lambda s: (s.get("created_at") or "", s.get("run_id") or ""),
        reverse=True,
    )
    return summaries


def read_run(profile_id: str, run_id: str) -> dict:
    safe_id = _safe_run_id(run_id)
    run_dir = runs_root_for(profile_id) / safe_id
    summary_path = run_dir / "summary.json"
    if not run_dir.is_dir() or not summary_path.is_file():
        raise FileNotFoundError(run_id)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    records: list[dict] = []
    records_path = run_dir / "records.jsonl"
    if records_path.is_file():
        for line in records_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    records.append(rec)
            except json.JSONDecodeError:
                continue
    return {"summary": summary, "records": records}
