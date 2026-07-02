"""Agent Builder write API — create/edit profiles and their knowledge notes.

Gated by ENABLE_PROFILE_EDITOR (default off): every endpoint 404s unless the
flag is set. When enabled this is a PUBLIC write surface (the bryanzane.com
builder page), so it carries its own guards: per-IP rate limits, an owner
token binding each profile to its creating browser, global profile and
per-profile note caps, a lazy TTL sweep of abandoned profiles, and a
server-side tool allowlist. All mutations are POST because the CORS
middleware only allows GET/POST.

Ownership is honor-system-lite: the browser mints a random token
(X-Builder-Owner header); we store its sha256 in profile.json and require a
match for every read/write of builder endpoints. Builder agents are unlisted
(excluded from /api/profiles), not secret — anyone with the slug can chat.

Only profiles carrying ``"builder": true`` may be edited — bundled example
profiles stay pristine (409). KB paths go through ``_safe_resolve`` (the
existing trust boundary) and are confined to ``profiles/<id>/kb``.

Written profiles deliberately omit ``inject_kb_manifest``: the manifest is
memoized per kb_root for the process lifetime, so setting it would serve stale
indexes while a user edits notes. Single uvicorn worker → last-write-wins on
concurrent saves is acceptable.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import shutil
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from backend import config, profiles
from backend.kb_loader import KBError, _safe_resolve, iter_kb_files
from backend.profiles import ProfileConfigError, _validate_tool_names, load_profile
from backend.ratelimit import limiter
from backend.tools.registry import TOOL_DEFS

def _require_builder() -> None:
    if not config.ENABLE_PROFILE_EDITOR:
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter()  # ungated: /api/tools only
# Gate runs as a dependency so a disabled builder 404s before body validation
# can leak endpoint existence via 422s.
builder_router = APIRouter(
    prefix="/api/builder", dependencies=[Depends(_require_builder)]
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
OWNER_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
MAX_NOTE_BYTES = 200_000

# Tools a builder profile may enable. Excludes portfolio-specific shortcuts
# (get_resume_summary, get_project_context) and semantic_search_kb (needs a
# CLI-built RAG index a visitor can't produce). Enforced server-side — the
# frontend picker hides the rest, but a direct POST must not bypass that.
BUILDER_ALLOWED_TOOLS = frozenset({
    "list_kb",
    "read_file",
    "search_kb",
    "web_search",
    "fetch_url_text",
    "calculator",
    "catalog_lookup",
    "qualify_lead",
    "lead_capture_preview",
    "checkout_link_preview",
})

# Tools that read catalog.json from the profile's data_root. Selecting any of
# them provisions the generic demo catalog below so the tool actually works.
CATALOG_TOOLS = frozenset({"catalog_lookup", "qualify_lead", "checkout_link_preview"})

DEMO_CATALOG = {
    "name": "Demo catalog",
    "packages": [
        {
            "id": "starter-widget",
            "name": "Starter Package",
            "category": "starter",
            "description": "Entry-level offering for trying the service out.",
            "best_for": "First-time customers",
            "price_display": "$49",
            "timeline": "Same week",
            "features": ["Quick setup", "Email support"],
            "keywords": ["starter", "basic", "small", "widget"],
            "next_step": "Start a trial",
        },
        {
            "id": "research-profile",
            "name": "Research Package",
            "category": "research",
            "description": "In-depth research and analysis engagement.",
            "best_for": "Teams that need market or competitor briefs",
            "price_display": "$499",
            "timeline": "2 weeks",
            "features": ["Custom report", "Source citations"],
            "keywords": ["research", "analysis", "report", "brief", "market"],
            "next_step": "Book a scoping call",
        },
        {
            "id": "sales-profile",
            "name": "Sales Package",
            "category": "sales",
            "description": "Sales-workflow support: lead handling and pricing help.",
            "best_for": "Small sales teams",
            "price_display": "$299/mo",
            "timeline": "1 week",
            "features": ["Lead routing", "Pricing playbook"],
            "keywords": ["sales", "lead", "revenue", "pricing", "checkout"],
            "next_step": "Talk to sales",
        },
        {
            "id": "custom-tools",
            "name": "Integration Package",
            "category": "integrations",
            "description": "Custom tool and API integration work.",
            "best_for": "Products needing bespoke integrations",
            "price_display": "$1,500+",
            "timeline": "3-4 weeks",
            "features": ["API integration", "Custom tooling"],
            "keywords": ["tool", "api", "integration", "crm", "calendar", "stripe"],
            "next_step": "Request a quote",
        },
        {
            "id": "production-hardening",
            "name": "Production Package",
            "category": "operations",
            "description": "Reliability, security, and operations hardening.",
            "best_for": "Teams preparing to launch",
            "price_display": "$2,000",
            "timeline": "2-3 weeks",
            "features": ["Security review", "Monitoring setup"],
            "keywords": ["production", "deploy", "security", "logging", "budget"],
            "next_step": "Schedule an audit",
        },
    ],
}


class ProfileEdit(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    instructions: str = Field(default="", max_length=20_000)
    welcome: str = Field(default="", max_length=1000)
    suggestions: list[str] = Field(default_factory=list, max_length=8)
    tools: list[str] = Field(default_factory=list, max_length=32)
    accent: str = Field(default="", pattern=r"^(#[0-9a-fA-F]{6})?$")


class NoteWrite(BaseModel):
    path: str = Field(..., min_length=1, max_length=200)
    content: str = Field(default="")


class NotePath(BaseModel):
    path: str = Field(..., min_length=1, max_length=200)


def _profile_dir(profile_id: str):
    if not SLUG_RE.match(profile_id):
        raise HTTPException(
            status_code=400,
            detail="agent id must be lowercase letters, numbers, and hyphens",
        )
    return profiles.PROFILE_ROOT / profile_id


def _owner_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _require_owner_token(owner: str | None) -> str:
    if not owner or not OWNER_TOKEN_RE.match(owner):
        raise HTTPException(status_code=400, detail="missing or malformed owner token")
    return owner


def _require_editable(profile_id: str, owner: str | None):
    """Return the profile dir; 409 for bundled profiles, 403 for someone else's.

    Legacy builder profiles without an owner_sha256 (written before ownership
    existed) stay editable and get bound to the caller's token on next save.
    """
    profile_dir = _profile_dir(profile_id)
    cfg_path = profile_dir / "profile.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
        if not cfg.get("builder"):
            raise HTTPException(
                status_code=409,
                detail=f"'{profile_id}' is a bundled profile and cannot be edited here",
            )
        stored = cfg.get("owner_sha256")
        if stored:
            token = _require_owner_token(owner)
            if not hmac.compare_digest(_owner_hash(token), str(stored)):
                raise HTTPException(status_code=403, detail="you don't own this agent")
    return profile_dir


def _sweep_expired_builder_profiles() -> None:
    """Delete builder profiles whose newest file is older than the TTL.

    Mirrors _cleanup_stale_sessions: runs lazily (on each create), stays dumb.
    Only dirs whose profile.json parses with "builder": true are ever removed,
    so bundled profiles are untouchable regardless of mtime.
    """
    root = profiles.PROFILE_ROOT
    if not root.is_dir():
        return
    cutoff = time.time() - config.BUILDER_PROFILE_TTL_DAYS * 86400
    for entry in root.iterdir():
        cfg_path = entry / "profile.json"
        if not entry.is_dir() or not cfg_path.is_file():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not cfg.get("builder"):
            continue
        newest = max(
            (p.stat().st_mtime for p in entry.rglob("*") if p.is_file()),
            default=cfg_path.stat().st_mtime,
        )
        if newest < cutoff:
            shutil.rmtree(entry, ignore_errors=True)


def _count_builder_profiles() -> int:
    root = profiles.PROFILE_ROOT
    if not root.is_dir():
        return 0
    count = 0
    for entry in root.iterdir():
        cfg_path = entry / "profile.json"
        if not entry.is_dir() or not cfg_path.is_file():
            continue
        try:
            if json.loads(cfg_path.read_text(encoding="utf-8")).get("builder"):
                count += 1
        except (json.JSONDecodeError, OSError):
            continue
    return count


def _kb_dir(profile_id: str, owner: str | None):
    profile_dir = _require_editable(profile_id, owner)
    if not (profile_dir / "profile.json").exists():
        raise HTTPException(status_code=404, detail=f"no agent named '{profile_id}'")
    return profile_dir / "kb"


def _kb_note_path(profile_id: str, rel: str, owner: str | None):
    kb_dir = _kb_dir(profile_id, owner)
    try:
        resolved = _safe_resolve(rel, root=kb_dir)
    except KBError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if resolved.suffix != ".md":
        raise HTTPException(status_code=400, detail="notes must be .md files")
    return kb_dir, resolved


@router.get("/api/tools")
async def list_tools() -> dict:
    """Registry tool catalog for the builder's ability picker. Read-only, ungated."""
    return {"tools": [{"name": t.name, "description": t.description} for t in TOOL_DEFS]}


@builder_router.get("/profile/{profile_id}")
async def read_profile(
    profile_id: str,
    x_builder_owner: str | None = Header(default=None, alias="X-Builder-Owner"),
) -> dict:
    profile_dir = _require_editable(profile_id, x_builder_owner)
    cfg_path = profile_dir / "profile.json"
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail=f"no agent named '{profile_id}'")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    system_path = profile_dir / "system.md"
    return {
        "id": profile_id,
        "label": cfg.get("label", ""),
        "description": cfg.get("description", ""),
        "instructions": system_path.read_text(encoding="utf-8") if system_path.exists() else "",
        "welcome": cfg.get("welcome", ""),
        "suggestions": cfg.get("suggestions", []),
        "tools": cfg.get("tools", []),
        "accent": (cfg.get("brand") or {}).get("accent", ""),
    }


@builder_router.post("/profile/{profile_id}")
@limiter.limit(config.RATE_LIMIT_BUILDER)
async def save_profile(
    request: Request,
    profile_id: str,
    req: ProfileEdit,
    x_builder_owner: str | None = Header(default=None, alias="X-Builder-Owner"),
) -> dict:
    profile_dir = _require_editable(profile_id, x_builder_owner)
    token = _require_owner_token(x_builder_owner)

    is_create = not (profile_dir / "profile.json").exists()
    if is_create:
        _sweep_expired_builder_profiles()
        if _count_builder_profiles() >= config.MAX_BUILDER_PROFILES:
            raise HTTPException(
                status_code=503, detail="the builder is at capacity right now"
            )

    # Validate before writing anything so a bad request leaves no broken file.
    disallowed = sorted(set(req.tools) - BUILDER_ALLOWED_TOOLS)
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail=f"tool(s) not available in the builder: {', '.join(disallowed)}",
        )
    try:
        _validate_tool_names(tuple(req.tools), profile_id=profile_id)
    except ProfileConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    cfg = {
        "id": profile_id,
        "label": req.label.strip(),
        "description": req.description.strip(),
        "kb_root": f"profiles/{profile_id}/kb",
        "tools": req.tools,
        "welcome": req.welcome.strip(),
        "suggestions": [s.strip()[:200] for s in req.suggestions if s.strip()],
        "brand": {"accent": req.accent} if req.accent else {},
        "builder": True,
        "owner_sha256": _owner_hash(token),
    }
    if set(req.tools) & CATALOG_TOOLS:
        # These tools read catalog.json from data_root; give them the demo one.
        cfg["data_root"] = f"profiles/{profile_id}/data"
        data_dir = profile_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "catalog.json").write_text(
            json.dumps(DEMO_CATALOG, indent=2) + "\n", encoding="utf-8"
        )
    (profile_dir / "kb").mkdir(parents=True, exist_ok=True)
    (profile_dir / "system.md").write_text(
        req.instructions.strip() or f"You are {cfg['label']}, a helpful assistant.",
        encoding="utf-8",
    )
    (profile_dir / "profile.json").write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    p = load_profile(profile_id, profile_root=profiles.PROFILE_ROOT)  # smoke-load
    return {
        "id": p.id,
        "label": p.label,
        "description": p.description,
        "welcome": p.welcome,
        "suggestions": list(p.suggestions),
        "tools": list(p.tools),
        "brand": p.brand,
    }


@builder_router.get("/kb/{profile_id}")
async def list_notes(
    profile_id: str,
    x_builder_owner: str | None = Header(default=None, alias="X-Builder-Owner"),
) -> dict:
    kb_dir = _kb_dir(profile_id, x_builder_owner)
    files = [
        {"path": rel, "size_bytes": path.stat().st_size}
        for rel, path in iter_kb_files(root=kb_dir, pattern="*.md")
    ]
    return {"files": files}


@builder_router.get("/kb/{profile_id}/file")
async def read_note(
    profile_id: str,
    path: str,
    x_builder_owner: str | None = Header(default=None, alias="X-Builder-Owner"),
) -> dict:
    _, resolved = _kb_note_path(profile_id, path, x_builder_owner)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"no note at '{path}'")
    return {"path": path, "content": resolved.read_text(encoding="utf-8")}


@builder_router.post("/kb/{profile_id}/file")
@limiter.limit(config.RATE_LIMIT_BUILDER)
async def write_note(
    request: Request,
    profile_id: str,
    req: NoteWrite,
    x_builder_owner: str | None = Header(default=None, alias="X-Builder-Owner"),
) -> dict:
    if len(req.content.encode("utf-8")) > MAX_NOTE_BYTES:
        raise HTTPException(status_code=400, detail="note is too large (200 KB max)")
    kb_dir, resolved = _kb_note_path(profile_id, req.path, x_builder_owner)
    if not resolved.exists():
        note_count = sum(1 for _ in iter_kb_files(root=kb_dir, pattern="*.md"))
        if note_count >= config.MAX_NOTES_PER_PROFILE:
            raise HTTPException(
                status_code=400,
                detail=f"note limit reached ({config.MAX_NOTES_PER_PROFILE} per agent)",
            )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(req.content, encoding="utf-8")
    return {"ok": True, "path": req.path}


@builder_router.post("/kb/{profile_id}/file/delete")
@limiter.limit(config.RATE_LIMIT_BUILDER)
async def delete_note(
    request: Request,
    profile_id: str,
    req: NotePath,
    x_builder_owner: str | None = Header(default=None, alias="X-Builder-Owner"),
) -> dict:
    _, resolved = _kb_note_path(profile_id, req.path, x_builder_owner)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"no note at '{req.path}'")
    resolved.unlink()
    return {"ok": True, "path": req.path}
