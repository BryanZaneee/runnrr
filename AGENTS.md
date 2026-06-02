# AGENTS.md

This file is for Codex (and other agents) working in this repo. Read it before making changes.

## Project Overview

EasyAgent is a portable framework for reusable agentic AI across multiple model providers. Bryan's personal site runs a profile on top of it (the bundled `personal-agent` showcase profile under `profiles/personal-agent/`), but the engine is meant to support many professional agent profiles with different knowledge bases and tools.

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
.venv/bin/python -m http.server 8000 --directory web              # dev dashboard
```

### VPS Deployment
The application is deployed on a VPS. Connect using: `ssh root@100.88.216.70`

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

`MODEL_REGISTRY` in [`backend/config.py`](backend/config.py) maps `model_id` → `{provider, model, base_url, ...}`. `REGISTERED_PROVIDERS` in [`backend/app.py`](backend/app.py) gates which models the dropdown shows based on what's actually wired up.
Agent persona and KB root are loaded from [`profiles/`](profiles/) through [`backend/profiles.py`](backend/profiles.py), so the engine can be reused for another agent by adding a profile package instead of forking the loop.

## File Map

- [`backend/agent.py`](backend/agent.py) — the bounded tool-use loop
- [`backend/providers/base.py`](backend/providers/base.py) — `LLMProvider` Protocol + normalized `Event` shape
- [`backend/providers/anthropic_provider.py`](backend/providers/anthropic_provider.py) — Anthropic path
- [`backend/providers/openai_compat_provider.py`](backend/providers/openai_compat_provider.py) — OpenAI + Kimi path
- [`backend/providers/gemini_provider.py`](backend/providers/gemini_provider.py) — Gemini path
- [`backend/profiles.py`](backend/profiles.py) — profile loader for persona + KB root
- [`backend/tools/`](backend/tools/) — domain-owned `ToolDef` records, source metadata helpers, and `run_tool` dispatch. Personal-site shortcuts (`get_resume_summary`/`get_project_context`) live in [`backend/tools/personal_kb.py`](backend/tools/personal_kb.py) and are NOT in `DEFAULT_PROFILE_TOOLS`. Metadata builders take `(arguments, output, ToolContext)`.
- [`backend/kb_loader.py`](backend/kb_loader.py) — `_safe_resolve()` is the trust boundary; everything else uses it. Generic FS ops only — no personal path conventions.
- [`backend/app.py`](backend/app.py) — FastAPI: POST `/api/chat` (SSE), GET `/api/models`, GET `/api/health`, GET `/api/profile` (cheap — no RAG scan), GET `/api/rag/index` (canonical RAG health)
- [`backend/config.py`](backend/config.py) — env loading, `MODEL_REGISTRY`, limits
- `web/` — local technical dashboard (health, budget, profiles, RAG index). Public chat UI lives in `bryanzane_v3/easyagent/`.
- Profile-specific KB aliases and public source labels belong in `profile.json` as `project_aliases`, `source_labels`, and `source_path_labels`, not in engine modules.
- `profiles/` — reusable agent profiles; `profiles/personal-agent/` is the bundled example (default)
- `kb/` — local/private content such as resume files, project notes, and codebase XML dumps; ignored by git (only `kb/README.md` and `kb/frampton/` are tracked). The `frampton` Fextralife scrape is third-party but public, so it ships with the repo so deploys are self-contained.
- [`tests/conftest.py`](tests/conftest.py) — `use_mini_kb` autouse fixture monkeypatches `KB_ROOT` to `tests/fixtures/mini_kb/`

## Conventions

- **Native tools are registered as `ToolDef` records.** When adding a tool, define its Anthropic-shaped schema, handler, and source metadata in the owning domain module (for example `backend/tools/kb.py`, `backend/tools/sales.py`, `backend/tools/web_fetch.py`, or `backend/rag/tools.py`) and include that `ToolDef` in [`backend/tools/registry.py`](backend/tools/registry.py). Provider adapters read schemas derived from the registry. Don't author the same tool twice.
- **Keep the engine business-agnostic.** `DEFAULT_PROFILE_TOOLS` is generic only (`list_kb`, `read_file`, `search_kb`, `web_search`). Personal/portfolio tooling and KB-path → public-label rules belong in profile config (`source_path_labels`) or a clearly-named module like `personal_kb.py`, never as engine defaults.
- **Agent identity belongs in profiles, not providers.** Add/edit `profiles/<id>/profile.json` and `system.md` for persona, welcome copy, suggestions, and KB root.
- **Profile brand metadata is the production UI contract.** `/api/profile` and `/api/profiles` feed the site accent colors, ASCII names, banner mascots, and placeholders. Keep these values in profile JSON when changing an agent's identity. Current bundled accents are Personal Agent green, Customer Service/Easy Coffee orange, Research Analyst cool blue, and Sales Concierge purple with gold secondary details.
- **Do not commit personal KB or secrets.** `kb/`, `.env*` files other than `.env.example`, API keys, private resumes, and XML codebase dumps must stay local/private. The exception is `kb/frampton/`, which is a public third-party Fextralife scrape and is tracked.
- **Follow the agent practices checklist.** [`docs/agent_best_practices.md`](docs/agent_best_practices.md) captures the standing rules for API boundaries, model selection, prompts, tools, streaming, retrieval, evals, and portability.
- **All KB filesystem ops go through `_safe_resolve()`.** It rejects `..`, absolute paths, and symlink escapes. Never bypass it.
- **The provider mutates `messages` inside `stream()`.** After the API call completes, append the assistant turn to `messages` *before* yielding `tool_use_complete` events. Mirror this contract in any new provider — otherwise the next API call rejects with "tool_result without preceding tool_use."
- **Loop bound: `MAX_TOOL_HOPS = 8`.** A normal profile-specific question should rarely need more than 3 hops. The cap is a runaway-loop safety net.
- **Commits use Conventional Commits labels + 50:72 format.** Subject: `<label>(<optional scope>): <imperative summary>` under 50 chars (labels: `feat`, `fix`, `chore`, `style`, `refactor`, `docs`, `test`, `perf`, `revert`). Blank line, then body lines wrapped at 72 chars explaining *why*. No trailing period in the subject.
- **No `Co-Authored-By: Codex` in commits.** Per repo owner's preference.

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
- ✅ **Phase G**: production hardening — per-IP rate limit, daily token budget, active-session cap, structured JSON logs
