"""Owner-scoped agent CRUD — backed by backend.db."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend import db, templates
from backend.config import KB_ROOT, PROFILE_ROOT
from backend.profiles import AgentProfile, profile_from_config, _project_path


def _parse_config(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    d["config"] = _parse_config(d["config"])
    return d


def _public_agent(row: dict[str, Any]) -> dict[str, Any]:
    cfg = row["config"]
    return {
        "id": str(row["id"]),
        "slug": row["slug"],
        "label": cfg.get("label", row["slug"]),
        "description": cfg.get("description", ""),
        "tools": list(cfg.get("tools", [])),
        "brand": cfg.get("brand", {}),
        "template_id": row.get("template_id"),
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


async def list_agents(owner_id: str) -> list[dict]:
    rows = await db.fetch(
        """
        SELECT id, slug, config, template_id, updated_at
        FROM agents
        WHERE owner_id = $1
        ORDER BY updated_at DESC
        """,
        owner_id,
    )
    return [_public_agent(_row_to_dict(r)) for r in rows]


async def get_agent(owner_id: str, agent_id: str) -> dict | None:
    row = await db.fetchrow(
        """
        SELECT id, owner_id, slug, config, template_id, created_at, updated_at
        FROM agents
        WHERE owner_id = $1 AND id = $2
        """,
        owner_id,
        agent_id,
    )
    if row is None:
        return None
    return _row_to_dict(row)


async def create_agent_from_template(
    owner_id: str,
    template_id: str,
    *,
    label: str | None = None,
    slug: str | None = None,
) -> dict:
    cfg = templates.load_template_config(template_id)
    if label:
        cfg["label"] = label
    resolved_slug = slug or template_id
    agent_id = str(uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        """
        INSERT INTO agents (id, owner_id, slug, config, template_id, created_at, updated_at)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $6)
        """,
        agent_id,
        owner_id,
        resolved_slug,
        json.dumps(cfg),
        template_id,
        now,
    )
    row = await get_agent(owner_id, agent_id)
    assert row is not None
    return row


async def update_agent(
    owner_id: str,
    agent_id: str,
    *,
    config: dict | None = None,
    label: str | None = None,
    slug: str | None = None,
) -> dict | None:
    row = await get_agent(owner_id, agent_id)
    if row is None:
        return None

    cfg = dict(row["config"])
    if config is not None:
        cfg.update(config)
    if label is not None:
        cfg["label"] = label

    new_slug = slug if slug is not None else row["slug"]
    now = datetime.now(timezone.utc)
    await db.execute(
        """
        UPDATE agents
        SET slug = $3, config = $4::jsonb, updated_at = $5
        WHERE owner_id = $1 AND id = $2
        """,
        owner_id,
        agent_id,
        new_slug,
        json.dumps(cfg),
        now,
    )
    return await get_agent(owner_id, agent_id)


async def delete_agent(owner_id: str, agent_id: str) -> bool:
    result = await db.execute(
        "DELETE FROM agents WHERE owner_id = $1 AND id = $2",
        owner_id,
        agent_id,
    )
    return result.endswith("1")


def agent_row_to_profile(row: dict) -> AgentProfile:
    cfg = _parse_config(row["config"])
    if cfg.get("kb_root"):
        kb_root = _project_path(cfg["kb_root"], KB_ROOT)
    elif row.get("template_id"):
        template_dir = (PROFILE_ROOT / row["template_id"]).resolve()
        template_cfg_path = template_dir / "profile.json"
        if template_cfg_path.exists():
            tcfg = json.loads(template_cfg_path.read_text(encoding="utf-8"))
            kb_root = _project_path(tcfg.get("kb_root"), KB_ROOT)
        else:
            kb_root = _project_path(None, KB_ROOT)
    else:
        kb_root = _project_path(cfg.get("kb_root"), KB_ROOT)

    data_root: Any = None
    if cfg.get("data_root"):
        data_root = _project_path(cfg["data_root"], PROFILE_ROOT / row["slug"] / "data")

    return profile_from_config(
        cfg,
        system_prompt=cfg.get("system_prompt", ""),
        kb_root=kb_root,
        data_root=data_root,
        profile_id=row["slug"],
    )
