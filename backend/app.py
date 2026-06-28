"""FastAPI app endpoints for chat SSE, health, models, profile, and budget.

Sessions live in-memory; stale ones are swept lazily at the top of each chat request.
This pins deployment to a single uvicorn worker — multi-worker needs external
session storage.
Provider lookup goes through `get_provider()` so tests can monkeypatch it.

Abuse protection: per-IP slowapi rate limit on /api/chat, daily token budget enforced
before each request and recorded after, hard cap on concurrent sessions, structured
JSON logs of every chat completion.
"""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend import agents_store, config, db, templates, usage_store
from backend.agent import run_conversation_stream
from backend.auth import CurrentUser, optional_user, require_user
from backend.budget import TOKEN_BUDGET
from backend.config import (
    ALLOWED_ORIGINS,
    DEFAULT_MODEL,
    DEFAULT_PROFILE,
    LOG_LEVEL,
    MAX_ACTIVE_SESSIONS,
    MAX_TOKENS,
    MAX_TURNS_PER_SESSION,
    MODEL_REGISTRY,
    PROFILE_ROOT,
    RATE_LIMIT_CHAT,
    RATE_LIMIT_ENABLED,
    SESSION_TTL,
    available_models,
)
from backend.logging_config import configure_logging
from backend.providers.base import LLMProvider
from backend.providers.registry import ProviderSetupError, build_provider
from backend.evals import store
from backend.profiles import AgentProfile, ProfileConfigError, load_profile
from backend.rag.status import rag_index_payload
from backend.status import runtime_status_payload
from backend.tools import schemas_for_tools
from backend.tools.registry import TOOL_DEFS
from backend.types import SessionDict

configure_logging(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO))
log = logging.getLogger("easyagent")

# Providers wired up behind the shared engine.
REGISTERED_PROVIDERS: set[str] = {"anthropic", "openai_compat", "gemini"}


SESSIONS: dict[str, SessionDict] = {}


def _cleanup_stale_sessions() -> None:
    now = time.time()
    stale = [sid for sid, s in SESSIONS.items() if now - s["last_seen"] > SESSION_TTL]
    for sid in stale:
        del SESSIONS[sid]


def get_provider(model_id: str) -> LLMProvider:
    """Resolve model_id → provider instance. Tests monkeypatch this."""
    try:
        return build_provider(model_id, MODEL_REGISTRY[model_id])
    except ProviderSetupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_profile(profile_id: str = DEFAULT_PROFILE) -> AgentProfile:
    """Resolve profile id → profile. Tests can monkeypatch this if needed."""
    try:
        return load_profile(profile_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"profile not found: {profile_id}") from e
    except ProfileConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def warn_stale_indexes() -> None:
    """Log warnings for RAG-enabled profiles with stale/missing indexes. Never raises."""
    if not PROFILE_ROOT.is_dir():
        return
    for entry in sorted(PROFILE_ROOT.iterdir()):
        if not entry.is_dir() or not (entry / "profile.json").exists():
            continue
        try:
            p = load_profile(entry.name)
        except Exception as exc:
            log.warning("skipping unloadable profile %s: %s", entry.name, exc)
            continue
        payload = rag_index_payload(p)
        if not payload.get("rag_enabled"):
            continue
        if payload.get("status") in {"stale", "missing", "error"}:
            log.warning(
                "rag_index_stale",
                extra={
                    "profile": p.id,
                    "rag_status": payload.get("status"),
                    "rag_message": payload.get("message", ""),
                    "hint": f"run: python -m backend.rag.cli build {p.id}",
                },
            )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await db.init_pool()
    warn_stale_indexes()
    yield
    await db.close_pool()


app = FastAPI(title="EasyAgent", version="0.1.0", lifespan=lifespan)

limiter = Limiter(key_func=get_remote_address, enabled=RATE_LIMIT_ENABLED)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|\[::1\]):\d+$",
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)
    model: str = Field(..., min_length=1)
    profile: str = Field(default=DEFAULT_PROFILE, min_length=1, max_length=64)
    agent_id: str | None = None


class CreateAgentRequest(BaseModel):
    template_id: str = Field(..., min_length=1)
    label: str | None = None
    slug: str | None = None


class UpdateAgentRequest(BaseModel):
    label: str | None = None
    slug: str | None = None
    config: dict | None = None


def _parse_usage_range(range_str: str) -> timedelta:
    m = re.fullmatch(r"(\d+)([dhm])", range_str.strip())
    if not m:
        return timedelta(days=7)
    n, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        return timedelta(days=n)
    if unit == "h":
        return timedelta(hours=n)
    return timedelta(minutes=n)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "sessions": len(SESSIONS)}


@app.get("/api/public-config")
async def public_config() -> dict:
    return {
        "supabase_url": config.SUPABASE_URL,
        "supabase_anon_key": config.SUPABASE_ANON_KEY,
    }


@app.get("/api/budget")
async def budget() -> dict:
    return TOKEN_BUDGET.stats()


@app.get("/api/status")
async def status() -> dict:
    """Dev-dashboard aggregate; external clients should prefer the focused endpoints."""
    _cleanup_stale_sessions()
    return runtime_status_payload(
        sessions=len(SESSIONS),
        budget=TOKEN_BUDGET.stats(),
        registered_providers=REGISTERED_PROVIDERS,
        native_tool_count=len(TOOL_DEFS),
    )


@app.get("/api/rag/index")
async def rag_index(profile_id: str = DEFAULT_PROFILE) -> dict:
    """RAG index health for one profile. Used by the local technical dashboard."""
    return rag_index_payload(get_profile(profile_id))


def _require_evals_api() -> None:
    if not config.ENABLE_EVALS_API:
        raise HTTPException(status_code=404, detail="not found")


@app.get("/api/evals/runs/{profile_id}")
async def evals_list_runs(profile_id: str) -> dict:
    _require_evals_api()
    get_profile(profile_id)
    return {"profile_id": profile_id, "runs": store.list_runs(profile_id)}


@app.get("/api/evals/run/{profile_id}/{run_id}")
async def evals_read_run(profile_id: str, run_id: str) -> dict:
    _require_evals_api()
    get_profile(profile_id)
    try:
        return store.read_run(profile_id, run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="not found") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found") from None


@app.get("/api/evals/index-status/{profile_id}")
async def evals_index_status(profile_id: str) -> dict:
    _require_evals_api()
    return rag_index_payload(get_profile(profile_id))


@app.get("/api/models")
async def list_models() -> dict:
    models = [m for m in available_models() if m["provider"] in REGISTERED_PROVIDERS]
    default = DEFAULT_MODEL if any(m["id"] == DEFAULT_MODEL for m in models) else (
        models[0]["id"] if models else None
    )
    return {"default": default, "models": models}


@app.get("/api/profile")
async def profile(profile_id: str = DEFAULT_PROFILE) -> dict:
    # Intentionally cheap: no RAG-index inspection here (that scans/hashes the KB
    # filesystem). Production chat clients hit this on every agent switch. RAG
    # health lives at the dedicated GET /api/rag/index endpoint.
    p = get_profile(profile_id)
    return {
        "id": p.id,
        "label": p.label,
        "description": p.description,
        "welcome": p.welcome,
        "suggestions": list(p.suggestions),
        "tools": list(p.tools),
        "tool_schemas": schemas_for_tools(
            p.tools,
            description_overrides=p.tool_descriptions,
        ),
        "brand": p.brand,
        "mcp_servers": [s["name"] for s in p.mcp_servers],
    }


@app.get("/api/profiles")
async def list_profiles() -> dict:
    """List every profile with a profile.json under PROFILE_ROOT. Powers the agent switcher."""
    out: list[dict] = []
    if PROFILE_ROOT.is_dir():
        for entry in sorted(PROFILE_ROOT.iterdir()):
            if not entry.is_dir() or not (entry / "profile.json").exists():
                continue
            try:
                p = load_profile(entry.name)
            except Exception as exc:
                log.warning("skipping unloadable profile %s: %s", entry.name, exc)
                continue
            out.append({
                "id": p.id,
                "label": p.label,
                "description": p.description,
                "tools": list(p.tools),
                "brand": p.brand,
                "mcp_servers": [s["name"] for s in p.mcp_servers],
            })
    return {"default": DEFAULT_PROFILE, "profiles": out}


@app.get("/api/me")
async def me(user: CurrentUser = Depends(require_user)) -> dict:
    return {"id": user.id, "email": user.email}


@app.get("/api/templates")
async def list_templates_endpoint(user: CurrentUser = Depends(require_user)) -> dict:
    return {"templates": templates.list_templates()}


@app.get("/api/agents")
async def list_agents_endpoint(user: CurrentUser = Depends(require_user)) -> dict:
    return {"agents": await agents_store.list_agents(user.id)}


@app.post("/api/agents")
async def create_agent_endpoint(
    req: CreateAgentRequest,
    user: CurrentUser = Depends(require_user),
) -> dict:
    try:
        agent = await agents_store.create_agent_from_template(
            user.id,
            req.template_id,
            label=req.label,
            slug=req.slug,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"template not found: {req.template_id}") from exc
    return agent


@app.get("/api/agents/{agent_id}")
async def get_agent_endpoint(
    agent_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict:
    agent = await agents_store.get_agent(user.id, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@app.patch("/api/agents/{agent_id}")
async def update_agent_endpoint(
    agent_id: str,
    req: UpdateAgentRequest,
    user: CurrentUser = Depends(require_user),
) -> dict:
    agent = await agents_store.update_agent(
        user.id,
        agent_id,
        config=req.config,
        label=req.label,
        slug=req.slug,
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    try:
        agents_store.agent_row_to_profile(agent)
    except ProfileConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return agent


@app.delete("/api/agents/{agent_id}")
async def delete_agent_endpoint(
    agent_id: str,
    user: CurrentUser = Depends(require_user),
) -> dict:
    deleted = await agents_store.delete_agent(user.id, agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="agent not found")
    return {"deleted": True}


@app.get("/api/usage")
async def usage_endpoint(
    user: CurrentUser = Depends(require_user),
    range: str = "7d",
    agent_id: str | None = None,
) -> dict:
    since = datetime.now(timezone.utc) - _parse_usage_range(range)
    return await usage_store.usage_summary(user.id, since=since, agent_id=agent_id)


@app.post("/api/chat")
@limiter.limit(RATE_LIMIT_CHAT)
async def chat(
    request: Request,
    req: ChatRequest,
    user: CurrentUser | None = Depends(optional_user),
) -> StreamingResponse:
    if req.model not in MODEL_REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown model: {req.model}")
    if MODEL_REGISTRY[req.model]["provider"] not in REGISTERED_PROVIDERS:
        raise HTTPException(
            status_code=400, detail=f"provider not implemented for: {req.model}"
        )

    if not TOKEN_BUDGET.has_capacity():
        raise HTTPException(status_code=503, detail="daily token budget exhausted")

    _cleanup_stale_sessions()

    session_key = f"{user.id}:{req.session_id}" if user else req.session_id

    if session_key not in SESSIONS and len(SESSIONS) >= MAX_ACTIVE_SESSIONS:
        raise HTTPException(status_code=503, detail="server at session capacity")

    provider = get_provider(req.model)
    cfg = MODEL_REGISTRY[req.model]

    if user is not None and req.agent_id:
        row = await agents_store.get_agent(user.id, req.agent_id)
        if row is None:
            raise HTTPException(status_code=404, detail="agent not found")
        try:
            profile = agents_store.agent_row_to_profile(row)
        except ProfileConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        profile = get_profile(req.profile)

    session = SESSIONS.setdefault(
        session_key,
        {
            "messages": [],
            "last_seen": time.time(),
            "provider": cfg["provider"],
            "profile": profile.id,
        },
    )
    session["last_seen"] = time.time()
    if session.get("provider") != cfg["provider"] or session.get("profile") != profile.id:
        session["messages"] = []
        session["provider"] = cfg["provider"]
        session["profile"] = profile.id

    if len(session["messages"]) >= MAX_TURNS_PER_SESSION * 2:
        raise HTTPException(status_code=429, detail="session message cap reached")

    ip = request.client.host if request.client else "unknown"
    instrumented = _instrument(
        run_conversation_stream(req.message, session, provider, cfg["model"], profile),
        ip=ip,
        session_id=req.session_id,
        model_id=req.model,
        profile_id=profile.id,
        owner_id=user.id if user else None,
        agent_id=req.agent_id,
    )

    return StreamingResponse(
        _sse_format(instrumented),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _instrument(
    events: AsyncIterator[dict],
    *,
    ip: str,
    session_id: str,
    model_id: str,
    profile_id: str,
    owner_id: str | None = None,
    agent_id: str | None = None,
) -> AsyncIterator[dict]:
    """Pass events through; tally usage for the budget and emit one structured log."""
    started = time.time()
    tokens_in = 0
    tokens_out = 0
    cache_read = 0
    tool_hops = 0
    status = "ok"
    try:
        async for ev in events:
            kind = ev.get("event")
            if kind == "usage":
                tokens_in += int(ev.get("input_tokens") or 0)
                tokens_out += int(ev.get("output_tokens") or 0)
                cache_read += int(ev.get("cache_read_input_tokens") or 0)
            elif kind == "tool_use_start":
                tool_hops += 1
            elif kind == "error":
                status = "error"
            yield ev
    except Exception:
        status = "exception"
        raise
    finally:
        total = tokens_in + tokens_out
        duration_ms = int((time.time() - started) * 1000)
        TOKEN_BUDGET.record(total)
        log.info(
            "chat_complete",
            extra={
                "ip": ip,
                "session": session_id[:8],
                "model": model_id,
                "profile": profile_id,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_total": total,
                "cache_read": cache_read,
                "tool_hops": tool_hops,
                "duration_ms": duration_ms,
                "status": status,
            },
        )
        if owner_id is not None:
            try:
                await usage_store.record_usage(
                    owner_id=owner_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    model=model_id,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cache_read=cache_read,
                    tool_hops=tool_hops,
                    duration_ms=duration_ms,
                    status=status,
                )
            except Exception:
                log.warning("usage_record_failed", exc_info=True)


async def _sse_format(events: AsyncIterator[dict]) -> AsyncIterator[bytes]:
    """Convert {event, ...} dicts to SSE wire frames."""
    try:
        async for ev in events:
            ev_type = ev.pop("event")
            payload = json.dumps(ev, ensure_ascii=False)
            yield f"event: {ev_type}\ndata: {payload}\n\n".encode("utf-8")
    except Exception:
        # Never forward exception text to the public stream — it can carry
        # provider/internal details. Full traceback goes to the server log.
        log.exception("sse stream failed")
        payload = json.dumps({"message": "internal error while streaming the response"})
        yield f"event: error\ndata: {payload}\n\n".encode("utf-8")
