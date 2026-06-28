"""Bundled profile templates — clonable starting points for tenant agents."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.config import PROFILE_ROOT
from backend.profiles import load_profile

log = logging.getLogger("easyagent")


def list_templates() -> list[dict]:
    """Scan PROFILE_ROOT like list_profiles() — id, label, description, tools, brand."""
    out: list[dict] = []
    if PROFILE_ROOT.is_dir():
        for entry in sorted(PROFILE_ROOT.iterdir()):
            if not entry.is_dir() or not (entry / "profile.json").exists():
                continue
            try:
                p = load_profile(entry.name)
            except Exception as exc:
                log.warning("skipping unloadable template %s: %s", entry.name, exc)
                continue
            out.append({
                "id": p.id,
                "label": p.label,
                "description": p.description,
                "tools": list(p.tools),
                "brand": p.brand,
            })
    return out


def load_template_config(template_id: str) -> dict[str, Any]:
    """Read profile.json + system prompt; return snapshot dict for DB insert."""
    profile_dir = (PROFILE_ROOT / template_id).resolve()
    cfg_path = profile_dir / "profile.json"
    if not cfg_path.exists():
        raise FileNotFoundError(cfg_path)

    cfg: dict[str, Any] = json.loads(cfg_path.read_text(encoding="utf-8"))
    system_path = cfg.get("system_prompt_path")
    if system_path:
        sp = Path(system_path)
        if not sp.is_absolute():
            sp = profile_dir / sp
    else:
        sp = profile_dir / "system.md"
    system_prompt = sp.read_text(encoding="utf-8").strip()

    cfg = dict(cfg)
    cfg["system_prompt"] = system_prompt
    cfg.setdefault("id", template_id)
    cfg.setdefault("label", template_id.replace("-", " ").title())
    return cfg
