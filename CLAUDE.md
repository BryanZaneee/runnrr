# Repository guidance

`AGENTS.md` is a symlink to this file. Edit only `CLAUDE.md`.

## Product and current scope

Runnrr is a self-hosted workstation for business agents: customer support,
research, and other work beyond coding. FastAPI serves a vanilla HTML/CSS/JS UI.
The runtime uses provider APIs, with live SSE chat, configured profiles, knowledge
and web tools, skills, project imports, and persistent usage accounting.

The core product is a polished portfolio demo for employers. The support proof
of concept uses simulated customers with real model responses and a monitoring
panel; it does not send to external inboxes. Threads and provider context persist
in SQLite. Snooze only moves a thread between sidebar sections; settle keeps it
in the settled section until restored. Neither schedules work. Dark Souls
project knowledge uses the existing local retrieval tools with optional web search.
Never simulate success for an unavailable action.

Read [README.md](README.md) for setup, [docs/roadmap/README.md](docs/roadmap/README.md)
for current priorities, and [history.md](history.md) for decisions. Plans in
`docs/plans/archive/` are historical, not active deletion instructions. Preserve
all bundled profiles, including personal-agent, customer-service, research-analyst,
sales-concierge, bzs-concierge, and Frampton.

## Development and checks

Python 3.11–3.13, uv, and Node.js are required. No frontend build step.

```sh
uv sync --frozen --extra dev --extra rag
cp .env.example .env
.venv/bin/python -m uvicorn runnrr.app:app --reload --host 127.0.0.1 --port 8001
scripts/check.sh
scripts/check-browser.sh
```

Provider keys and reviewed paid-request bounds belong in local `.env`. Missing
bounds fail closed. Do not weaken reservations, tool-hop limits, or rate limits.
Use injected providers and temporary databases in tests; do not call paid models
for routine checks. `get_provider` in `runnrr.app` remains a patchable free function.
RAG and eval commands are documented in [docs/guide.md](docs/guide.md).

## Boundaries and contracts

- Keep the engine business-agnostic. Persona, brands, source labels, KB paths,
  and portfolio aliases belong in profile configuration or explicit domain tools.
  Brand fields remain an external API contract even if this UI doesn't use them.
- All KB filesystem access goes through `_safe_resolve`, including symlink checks.
  Profiles must resolve directly inside the configured profile directory.
- Register tools once as domain-owned `ToolDef` records. Derive provider schemas
  from the registry. `run_tool` must enforce the profile's tool allowlist.
- Providers append assistant messages before yielding completed tool calls.
  The agent loop appends tool results before streaming them to the client.
  Preserve ordering and safe message pairing across interruptions.
- `MODEL_REGISTRY` is the capability lookup. New models declare context window,
  output limit, and every `supports_*` flag. Unsupported capabilities fail clearly.
  Pricing is separate; unknown cost is `None`, never a fabricated zero.
- `runnrr/usage.py` owns usage v2: input includes cache subsets; output includes
  reasoning; billable total is input + output. Use shared tally functions in chat
  and evals. Preserve external SSE and `chat_complete` fields, including the
  deprecated `tool_hops` alias.
- Skill bodies arrive as tool results, never mid-conversation system rewrites
  that invalidate the prompt cache. MCP configuration is parsed but not connected.
- Active session locks remain process-local: deploy one uvicorn worker.
  Workspace threads and completed provider context persist in SQLite; legacy
  clients without a workspace header remain temporary. Busy sessions cannot
  expire or accept another request. Budgets use durable SQLite UTC-day reservations.
- Profile edits remain gated by `ENABLE_PROFILE_EDITOR=0` by default. Preserve
  owner-token checks, tool allowlists, note/profile caps, and path containment.
- Projects are owner-scoped SQLite snapshots. Only a browser workspace key persists
  client-side. `RUNNRR_PUBLIC_DEMO=1` exposes read-only shared portfolio projects;
  local mode must not expose those snapshots. See [docs/projects.md](docs/projects.md).
- `/api/profile` stays cheap; use `/api/rag/index` for expensive retrieval health.
  Blocking filesystem, embedding, and network work must run outside the event loop.

## Files and privacy

`runnrr/` contains API, loop, provider, tool, RAG, and eval modules. `web/` is the
only public static directory. `profiles/` contains reusable agents; `tests/`
contains regression coverage; `docs/design/` preserves design sources and QA.
Keep third-party libraries and their license notices together in `web/vendor/`.

Never commit credentials, private resumes, project dumps, `.env`, or local data.
`kb/` is private except `kb/README.md` and the public third-party `kb/frampton/`
corpus. Do not delete local KBs, databases, indexes, or in-progress user work.

## Delivery

Deployment is manual; follow [deploy/README.md](deploy/README.md). The separate
legacy public-site backend stays pinned at `ed536ff`. The newer workstation and
refresh services are separate; do not restart or deploy either implicitly.

Use Conventional Commits: subject under 50 characters, body wrapped at 72,
explaining why. Do not add a `Co-Authored-By: Claude` trailer. Preserve user work
and do not commit or push unless the task calls for it.
