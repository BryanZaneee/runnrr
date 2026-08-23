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
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend import builder, config
from backend.agent import run_conversation_stream
from backend.budget import TOKEN_BUDGET
from backend.pricing import cost_usd
from backend.usage import billable_total, tally, zero_tokens
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
    RATE_LIMIT_RAG_INSPECT,
    SESSION_TTL,
    available_models,
)
from backend.logging_config import configure_logging
from backend.providers.base import LLMProvider
from backend.providers.registry import ProviderSetupError, build_provider
from backend.ratelimit import limiter
from backend.evals import store
from backend.profiles import AgentProfile, ProfileConfigError, load_profile
from backend.rag.inspect import inspect_payload
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
    warn_stale_indexes()
    yield


app = FastAPI(title="EasyAgent", version="0.1.0", lifespan=lifespan)
app.include_router(builder.router)
app.include_router(builder.builder_router)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Builder-Owner"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|\[::1\]):\d+$",
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Builder-Owner"],
    )


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)
    model: str = Field(..., min_length=1)
    profile: str = Field(default=DEFAULT_PROFILE, min_length=1, max_length=64)


class RagInspectRequest(BaseModel):
    profile: str = Field(default=DEFAULT_PROFILE, min_length=1, max_length=64)
    query: str = Field(..., min_length=1, max_length=400)
    k: int = Field(default=5, ge=1, le=8)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "sessions": len(SESSIONS)}


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


@app.post("/api/rag/inspect")
@limiter.limit(RATE_LIMIT_RAG_INSPECT)
async def rag_inspect(request: Request, req: RagInspectRequest) -> dict:
    profile = get_profile(req.profile)
    if profile.builder or "semantic_search_kb" not in profile.tools:
        raise HTTPException(
            status_code=404, detail="retrieval inspection not available for this profile"
        )
    try:
        return inspect_payload(profile, req.query.strip(), req.k)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503, detail="retrieval index not built for this profile"
        ) from exc


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
            if p.builder:
                # Visitor-created agents are unlisted; creators reach them by id.
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


@app.post("/api/chat")
@limiter.limit(RATE_LIMIT_CHAT)
async def chat(request: Request, req: ChatRequest) -> StreamingResponse:
    if req.model not in MODEL_REGISTRY:
        raise HTTPException(status_code=400, detail=f"unknown model: {req.model}")
    if MODEL_REGISTRY[req.model]["provider"] not in REGISTERED_PROVIDERS:
        raise HTTPException(
            status_code=400, detail=f"provider not implemented for: {req.model}"
        )

    if not TOKEN_BUDGET.has_capacity():
        raise HTTPException(status_code=503, detail="daily token budget exhausted")

    _cleanup_stale_sessions()

    if req.session_id not in SESSIONS and len(SESSIONS) >= MAX_ACTIVE_SESSIONS:
        raise HTTPException(status_code=503, detail="server at session capacity")

    turn_id = uuid.uuid4().hex[:12]
    provider = get_provider(req.model)
    cfg = MODEL_REGISTRY[req.model]
    profile = get_profile(req.profile)

    session = SESSIONS.setdefault(
        req.session_id,
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
        turn_id=turn_id,
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
    turn_id: str,
) -> AsyncIterator[dict]:
    """Pass events through; tally usage for the budget and emit one structured log.

    `chat_complete` has an out-of-repo consumer (the production chat UI lives in
    bryanzane_v3/easyagent), so fields here are ADDED, never renamed or removed.
    `tool_hops` is kept for that reason even though `tool_calls` supersedes it.
    """
    started = time.perf_counter()
    tokens = zero_tokens()
    ttft_ms: int | None = None
    hops = 0
    tool_calls = 0
    estimated_usage = False
    status = "ok"
    error_class: str | None = None
    try:
        async for ev in events:
            kind = ev.get("event")
            if kind == "usage":
                tally(tokens, ev)
                # Exactly one usage event per hop (see agent.run_conversation_stream),
                # which makes this a real hop count. The old `tool_hops` counted
                # tool_use_start events, so a hop calling three tools logged 3 —
                # and two providers dedupe that event by tool name, so the number
                # also differed per provider for identical work.
                hops += 1
                if ev.get("estimated"):
                    estimated_usage = True
            elif kind == "tool_result":
                tool_calls += 1
            elif kind in ("delta", "thinking_delta") and ttft_ms is None:
                ttft_ms = int((time.perf_counter() - started) * 1000)
            elif kind == "error":
                status = "error"
                error_class = error_class or "stream_error"
            yield ev
    except Exception as exc:
        status = "exception"
        error_class = type(exc).__name__
        raise
    finally:
        total = billable_total(tokens)
        TOKEN_BUDGET.record(total)
        log.info(
            "chat_complete",
            extra={
                "ip": ip,
                "turn_id": turn_id,
                "session": session_id[:8],
                "model": model_id,
                "profile": profile_id,
                "tokens_in": tokens["input"],
                "tokens_out": tokens["output"],
                # Reasoning was previously charged to nobody: both Anthropic and
                # OpenAI subtract it out of output_tokens, and the old total was
                # input + output only. Vendors bill it; now so do we.
                "tokens_reasoning": tokens["reasoning"],
                "tokens_total": total,
                "cache_read": tokens["cache_read"],
                "cache_write": tokens["cache_write"],
                "cost_usd": cost_usd(model_id, tokens),
                "usage_estimated": estimated_usage,
                "ttft_ms": ttft_ms,
                "hops": hops,
                "tool_calls": tool_calls,
                "tool_hops": tool_calls,  # deprecated alias; see docstring
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "status": status,
                "error_class": error_class,
            },
        )


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
