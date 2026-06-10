# AGENTS.md

This file is for Codex (and other agents) working in this repo. Read it before making changes.

`CLAUDE.md` is the same content for Claude Code; keep them in sync when changing standing rules.

## Project Overview

EasyAgent is a portable framework for reusable agentic AI across multiple model providers. Bryan's personal site runs a profile on top of it (the bundled `personal-agent` showcase profile under `profiles/personal-agent/`), but the engine is meant to support many professional agent profiles with different knowledge bases and tools.

Bundled profiles under `profiles/`:

- `personal-agent` — personal-site candidate-advocate (default). Tools: KB + semantic RAG + `web_search`.
- `customer-service` — tier-1 small-business demo (Easy Coffee) with self-contained KB and `TEMPLATE.md` adaptation guide.
- `research-analyst` — public web research with `web_search`, `fetch_url_text`, `calculator`.
- `sales-concierge` — preview-only sales flow with `catalog_lookup`, `qualify_lead`, `lead_capture_preview`, `checkout_link_preview`, `calculator`. Reads its catalog from `data_root`. BZS Software branding lives in profile JSON (`tool_descriptions`), not engine code.
- `bzs-concierge` — public concierge demo for bzssoftware.com: catalog-backed discovery, lead qualification, and preview-only lead capture (no checkout tool). Ships its own `kb/`, `data/catalog.json`, and `evals/smoke.json`.
- `frampton` — Dark Souls 1 guide. Reads a categorized Fextralife scrape committed under `kb/frampton/`.

## Tech Stack

- Python 3.11–3.13 (3.14+ blocked: `voyageai` RAG backend), FastAPI, uvicorn, Server-Sent Events
- `anthropic` SDK for Claude models
- `openai` SDK with configurable `base_url` for OpenAI proper, Moonshot Kimi K2.6, and DeepSeek
- `google-genai` SDK for Gemini models
- Vanilla HTML / CSS / JS frontend — no bundler, no build step
- pytest with `monkeypatch`-based provider injection

## Development

```bash
uv venv --python 3.13 && uv pip install -e ".[dev,rag]"
cp .env.example .env  # set one or more provider keys locally; never commit secrets

.venv/bin/python -m pytest -v                                     # tests
.venv/bin/python -m uvicorn backend.app:app --reload --port 8001  # backend
.venv/bin/python -m http.server 8000 --directory web              # frontend
```

## Architecture (one-screen tour)

The agent loop in [`backend/agent.py`](backend/agent.py) mirrors the `run_conversation()` pattern from `Anthropic-course/001_tools_009.ipynb`. It iterates normalized events from a `LLMProvider` and calls `run_tool` for each `tool_use_complete`.

```
agent.run_conversation_stream(user_msg, session, provider, model, profile)
       │
       │  async for ev in provider.stream(...)
       ▼
   { text_delta, tool_use_complete, message_done, ... }   ← normalized Event
       │
       ▼
   run_tool(name, args, id, root=profile.kb_root) → ToolResult
       │
       ▼
   provider.append_tool_results(messages, results)
       │
       ▼  loop or done (bounded by MAX_TOOL_HOPS)
```

Providers under [`backend/providers/`](backend/providers/):

- `anthropic_provider.py` — uses `anthropic.AsyncAnthropic.messages.stream(...)`.
- `openai_compat_provider.py` — uses `openai.AsyncOpenAI` with configurable `base_url`. **One class** covers both OpenAI and Moonshot Kimi K2.6.
- `gemini_provider.py` — uses `google-genai` async streaming with manual function-call handling.

`MODEL_REGISTRY` in [`backend/config.py`](backend/config.py) maps `model_id` → `{provider, model, base_url, ...}`. `REGISTERED_PROVIDERS` in [`backend/app.py`](backend/app.py) gates which models the dropdown shows based on what's actually wired up. `available_models()` further filters by which provider API keys are present in env, so the same registry produces a different dropdown on dev vs. prod.

Agent persona and KB root are loaded from [`profiles/`](profiles/) through [`backend/profiles.py`](backend/profiles.py), so the engine can be reused for another agent by adding a profile package instead of forking the loop. `AgentProfile` carries: `id`, `label`, `description`, `kb_root`, `system_prompt`, `welcome`, `suggestions`, `tools`, `tool_descriptions`, `brand`, `data_root` (optional, profile-local data dir), `mcp_servers` (parsed but not yet connected), and the source-attribution config `project_aliases`, `source_labels`, and `source_path_labels` (ordered `(match, label)` pairs mapping KB paths to public labels; a trailing `/` is a prefix match, else exact). The engine ships **no** business-specific path-label rules — they live in profile JSON.

The agent loop normalizes provider events to: `text_delta`, `thinking_delta`, `tool_use_start`, `tool_use_complete`, `usage`, `message_done`, `error`. The SSE wire format prepends `event:` / `data:` frames in [`backend/app.py`](backend/app.py) `_sse_format()`. Each hop emits one `usage` event categorized as `tools` (the hop produced tool calls) or `response` (the hop produced final text) — the frontend uses this to fan out per-turn token classification, so don't classify by `had_thinking` (thinking-enabled models would always look like reasoning).

## File Map

- [`backend/agent.py`](backend/agent.py) — the bounded tool-use loop
- [`backend/providers/base.py`](backend/providers/base.py) — `LLMProvider` Protocol + normalized `Event` shape
- [`backend/providers/anthropic_provider.py`](backend/providers/anthropic_provider.py) — Claude path
- [`backend/providers/openai_compat_provider.py`](backend/providers/openai_compat_provider.py) — OpenAI + Kimi path
- [`backend/providers/gemini_provider.py`](backend/providers/gemini_provider.py) — Gemini path
- [`backend/profiles.py`](backend/profiles.py) — profile loader for persona + KB root
- [`backend/tools/`](backend/tools/) — domain-owned `ToolDef` records, registry-derived `SCHEMAS`, source metadata helpers, `run_tool` dispatch, and `ToolResult`. Current tool roster: `list_kb`, `read_file`, `search_kb`, `semantic_search_kb`, `get_resume_summary`, `get_project_context`, `web_search`, `fetch_url_text`, `calculator`, `catalog_lookup`, `qualify_lead`, `lead_capture_preview`, `checkout_link_preview`. A profile only sees the tools listed in its `profile.json`. The personal-site shortcuts `get_resume_summary`/`get_project_context` live in [`backend/tools/personal_kb.py`](backend/tools/personal_kb.py) (they encode `resume/resume.md` + `projects/{slug}.md` path conventions) and are **not** in `DEFAULT_PROFILE_TOOLS` — a profile must opt in by listing them.
- Metadata builders receive the same `ToolContext` as handlers (`(arguments, output, ctx)`); KB builders read `ctx.profile.source_labels`/`source_path_labels`, others ignore it.
- [`backend/kb_loader.py`](backend/kb_loader.py) — `_safe_resolve()` is the trust boundary; everything else uses it
- [`backend/web_search.py`](backend/web_search.py) — Tavily-backed `web_search()` helper used by the `web_search` tool. `TAVILY_API_KEY` required; raises `WebSearchError` otherwise.
- [`backend/app.py`](backend/app.py) — FastAPI: POST `/api/chat` (SSE), GET `/api/models`, GET `/api/health`, GET `/api/budget`, GET `/api/profile`, GET `/api/profiles` (lists all bundled profiles for the agent switcher; logs and skips unloadable profiles), GET `/api/rag/index`, GET `/api/status`, and GET `/api/evals/*` (run history/detail/index-status; gated by `ENABLE_EVALS_API`). **`/api/profile` is intentionally cheap** — it does NOT embed RAG-index health (that scans/hashes the KB). RAG health is the canonical job of `GET /api/rag/index`.
- [`backend/config.py`](backend/config.py) — env loading, `MODEL_REGISTRY`, limits, rate-limit + budget knobs, plus `PROVIDER_TIMEOUT_SECONDS`, RAG knobs (`EASYAGENT_EMBEDDING_BACKEND`, `EASYAGENT_RERANK` → `RERANK_ENABLED`), and eval knobs (`EASYAGENT_GRADER_MODEL` → `GRADER_MODEL_ID`, `ENABLE_EVALS_API`)
- [`backend/budget.py`](backend/budget.py) — process-local `TOKEN_BUDGET` enforced before each chat and recorded after; resets on local-date change
- [`backend/logging_config.py`](backend/logging_config.py) — `configure_logging()` installs a JSON-line stdout formatter; `extra={...}` fields merge into the record
- `web/` — local **technical dashboard** (health, budget, limits, models, profiles, and per-profile RAG-index status). It is NOT the production chat UI — public chat lives in the separate `bryanzane_v3/easyagent/` app. The dashboard fetches RAG health from `GET /api/rag/index` (not from `/api/profile`).
- `profiles/` — reusable agent profiles loaded by the engine. `personal-agent` is the bundled personal showcase (default); `customer-service` ships its own self-contained KB; `sales-concierge` and `bzs-concierge` ship a `data/catalog.json`; `research-analyst`, `sales-concierge`, and `bzs-concierge` also ship per-profile `evals/smoke.json`; `frampton` uses the tracked Fextralife scrape at `kb/frampton`.
- `profiles-advanced/` — placeholder for tier-2 multi-channel/multi-tenant profiles (WhatsApp/IG/Gmail/GBP). Sibling of `profiles/` so the loader does not pick it up
- `kb/` — local/private content such as resume files, project notes, and codebase XML dumps; ignored by git (only `kb/README.md` and `kb/frampton/` are tracked). The `frampton` Fextralife scrape is third-party but public, so it ships with the repo so deploys are self-contained.
- [`tests/conftest.py`](tests/conftest.py) — autouse fixtures: `use_mini_kb` (points `KB_ROOT` at `tests/fixtures/mini_kb/`) and `reset_budget` (clears `TOKEN_BUDGET` between tests)
- `tests/` — `test_tools.py` (KB + non-KB tool dispatch, including the `_safe_resolve` boundary), `test_agent_loop.py` (loop + provider stubs, provider-failure normalization), `test_providers.py` (OpenAI-compat + Gemini streaming/translation, SDK timeouts; Anthropic streaming tests remain a gap), `test_app.py` (endpoints, SSE, rate limit, budget), `test_app_runtime.py` (runtime status surface), `test_customer_service_profile.py` and `test_profiles_and_translators.py` (profile loading + tool-allowlist filtering), `test_evals_app.py` / `test_evals_graders.py` / `test_evals_runner.py` (eval API, graders, runner), and seven `test_rag_*.py` files (chunker, embeddings, foundation, indexer, reranker, retriever, tools)

## Conventions

- **Native tools are registered as `ToolDef` records.** When adding a tool, define its Anthropic-shaped schema, handler, and source metadata in the owning domain module (for example `backend/tools/kb.py`, `backend/tools/sales.py`, `backend/tools/web_fetch.py`, or `backend/rag/tools.py`) and include that `ToolDef` in [`backend/tools/registry.py`](backend/tools/registry.py). Provider adapters translate schemas derived from the registry. Don't author the same tool twice.
- **Profiles gate tool visibility.** `run_tool` rejects any name not in `profile.tools`. Adding a `ToolDef` doesn't expose it — opt the profile in by listing it in `profile.json`. Use `tool_descriptions` in profile JSON when a shared tool needs profile-specific wording.
- **Keep the engine business-agnostic.** `DEFAULT_PROFILE_TOOLS` is generic only (`list_kb`, `read_file`, `search_kb`, `web_search`). Personal/portfolio tooling and KB-path → public-label rules belong in profile config (`source_path_labels`) or a clearly-named module like `personal_kb.py`, never as engine defaults. A business profile must work without editing engine code.
- **Agent identity belongs in profiles, not providers.** Add/edit `profiles/<id>/profile.json` and `system.md` for persona, welcome copy, suggestions, and KB root. Switching profile or model mid-session **resets `session["messages"]`** (see `chat()` in `backend/app.py`) — tests rely on this.
- **Profile brand metadata is the production UI contract.** `/api/profile` and `/api/profiles` feed the site accent colors, ASCII names, banner mascots, and placeholders. Keep these values in profile JSON when changing an agent's identity. Current bundled accents: Personal Agent green, Customer Service/Easy Coffee orange, Research Analyst cool blue, Sales Concierge purple+gold, Frampton red.
- **Do not commit personal KB or secrets.** `kb/`, `.env*` files other than `.env.example`, API keys, private resumes, and XML codebase dumps must stay local/private. The exception is `kb/frampton/`, which is a public third-party Fextralife scrape and is tracked.
- **Follow the agent practices checklist.** [`docs/agent_best_practices.md`](docs/agent_best_practices.md) captures the standing rules for API boundaries, model selection, prompts, tools, streaming, retrieval, evals, and portability.
- **All KB filesystem ops go through `_safe_resolve()`.** It rejects `..`, absolute paths, and symlink escapes. Never bypass it.
- **The provider mutates `messages` inside `stream()`.** After the API call completes, append the assistant turn to `messages` *before* yielding `tool_use_complete` events. Mirror this contract in any new provider — otherwise the next API call rejects with "tool_result without preceding tool_use."
- **Loop bound: `MAX_TOOL_HOPS = 8`.** A normal profile-specific question should rarely need more than 3 hops. The cap is a runaway-loop safety net.
- **Production limits (defaults):** `RATE_LIMIT_CHAT=10/minute;100/hour` per IP, `DAILY_TOKEN_BUDGET=5_000_000`, `MAX_ACTIVE_SESSIONS=200`, `SESSION_TTL_SECONDS=1800`, `MAX_TURNS_PER_SESSION=40`, `PROVIDER_TIMEOUT_SECONDS=120` (per-read inactivity timeout on provider SDK clients). All overridable via `.env`.
- **Sessions are process-local.** The in-memory `SESSIONS` dict is correct on uvicorn's single event loop but pins deployment to one worker (`workers=1`, the current systemd setup). Multi-worker requires external session storage.
- **Default model differs between code and prod.** `config.py` falls back to `claude-sonnet-4-5`, but `.env.example` (and the deployed `.env`) sets `DEFAULT_MODEL=deepseek-v4-flash`. Treat the env value as authoritative for prod behavior.
- **MCP is parsed, not connected.** `profile.mcp_servers` is loaded onto `AgentProfile` and surfaced in `/api/profile(s)`, but no client connects yet. The planned wiring is sketched in the `TODO(mcp)` block at the top of `run_conversation_stream` — extend there, not in providers.
- **Tests monkeypatch `get_provider`.** Endpoint tests in `tests/test_app.py` swap in fake providers via `backend.app.get_provider`. Keep the helper a free function so it stays patchable.
- **Commits use Conventional Commits labels + 50/72 format.** Subject: `<label>(<optional scope>): <imperative summary>` under 50 chars (labels: `feat`, `fix`, `chore`, `style`, `refactor`, `docs`, `test`, `perf`, `revert`). Blank line, then body lines wrapped at 72 chars explaining *why*. No trailing period in the subject.
- **No `Co-Authored-By: Claude` in commits.** Per repo owner's preference.

## Reading order for a new contributor / agent

1. [`README.md`](README.md) — what + how to run
2. [`history.md`](history.md) — why each decision was made (and what was rejected)
3. [`backend/agent.py`](backend/agent.py) — the loop (~50 lines)
4. [`backend/providers/base.py`](backend/providers/base.py) + [`anthropic_provider.py`](backend/providers/anthropic_provider.py) — the Protocol + an implementation

## Build phases (tracking)

- ✅ **Phase 0**: scaffold
- ✅ **Phase A**: `kb_loader.py` + `tools.py` + 32 unit tests
- ✅ **Phase B**: `AnthropicProvider` + provider-agnostic loop + 4 mocked-provider tests
- ✅ **Phase C**: FastAPI SSE + chat UI + 5 endpoint tests
- ✅ **Phase D**: `OpenAICompatProvider` + `tool_translator.py` + Kimi K2.6 / GPT-5 wiring
- ✅ **Profile split**: reusable engine (EasyAgent) + `profiles/personal-agent/` persona and KB root
- ⏳ **Phase E**: prompt caching / usage overlay across providers
- ⏳ **Phase F**: populate a local/private `kb/` (resume, quick_info, project pitches, meta) + smoke prompts
- ✅ **Phase G**: production hardening — per-IP `slowapi` rate limit on `/api/chat`, `TOKEN_BUDGET` daily cap with `/api/budget` introspection, `MAX_ACTIVE_SESSIONS` cap with lazy stale-session sweep, JSON-line structured logs via `_instrument()` per chat completion
- ✅ **Customer-service profile + agent switcher**: bundled `profiles/customer-service/` (Lantern Lane Coffee) + sibling `profiles-advanced/` placeholder + `mcp_servers` schema field on `AgentProfile` (parsed; full MCP integration deferred) + `GET /api/profiles` endpoint + web UI agent switcher dropdown and details panel showing description, tools, MCP servers, and per-turn classified token usage
- ✅ **Research + Sales profiles**: `profiles/research-analyst/` (web_search + fetch_url_text + calculator) and `profiles/sales-concierge/` (catalog_lookup + qualify_lead + preview-only lead_capture/checkout) with per-profile `evals/smoke.json`. Sales reads its catalog from `data_root` rather than the KB.
- ✅ **Frampton profile**: Dark Souls 1 guide grounded in a categorized Fextralife scrape committed at `kb/frampton/` (third-party but public).

## VPS / deployment access

- **SSH**: `ssh root@100.88.216.70` (Tailscale IP; the public Caddy bind for HTTPS is `76.13.107.219`).
- **Project root on VPS**: `/opt/easyagent`.
- **systemd unit**: `easyagent.service` (uvicorn FastAPI on `127.0.0.1:8001`, fronted by Caddy at `bryanzane.com/api/*`).
- **Code deploys are manual.** Pushing to `main` does NOT auto-deploy — the easyagent repo is not webhook-wired. After pushing, SSH and run the multi-repo dispatcher:
  ```bash
  ssh root@100.88.216.70 'bash /opt/deploy/deploy.sh easyagent'
  ```
  That script (a copy of [`deploy.sh`](deploy.sh) in this repo) does `git fetch origin main && git reset --hard origin/main && systemctl restart easyagent`.
- **KB syncs (`kb/`) are manual.** `kb/` is gitignored (see history.md "Personal KB content stays out of the public repository"), so a code deploy never carries resume/project/codebase content. After updating local `kb/`, push it explicitly:
  ```bash
  rsync -avz --delete --exclude='.DS_Store' --exclude='.localized' \
    kb/ root@100.88.216.70:/opt/easyagent/kb/
  ```
  Rebuild each RAG-enabled profile index so `semantic_search_kb` stays current (repeat per profile that uses it):
  ```bash
  python -m backend.rag.cli build personal-agent
  ```
  Then restart the service:
  ```bash
  ssh root@100.88.216.70 systemctl restart easyagent
  ```
