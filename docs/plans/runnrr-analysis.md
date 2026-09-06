# EasyAgent → Runnrr: analysis, corrections, and the PR sequence

## Context

Bryan is pivoting EasyAgent (multi-provider agent engine serving bryanzane.com) into
Runnrr: a single-tenant business-task runtime with a sandbox workspace, Supabase
login, and a Hermes-Agent-shaped feature surface (`runnrr-feature-inventory.md`).
`Runnrr-update.md` already holds a phased plan (rename → cuts → workspace → state →
`runnrr up`). This document is the result of auditing that plan against the code at
`ed536ff`, auditing the backend hot path for speed/cache/cost, mapping the feature
inventory to what exists, and researching other harnesses (Hermes, pi, Deep Agents,
OpenClaw, Claude Code/Codex) plus 2025–26 agent-optimization findings.

UI is out of scope (Bryan designs it separately). Backend only. Cost effectiveness
and non-technical usability gate every choice. Ponytail applies: shortest working diff,
stdlib first, no speculative abstractions.

Outcome: a corrected, extended PR sequence that (1) fixes the plan's drift, (2) adds the
performance/caching PR that was missing, (3) organizes the repo root, and (4) turns the
feature inventory into grouped, sequential backend PRs that land on the Runnrr phases.

Execution model (unchanged from Runnrr-update.md): bulk coding delegated to Cursor CLI
per PR; Claude reviews diffs and runs tests before the next PR starts.

---

## 1. Codebase analysis

### Solid (do not redo)

- SDK clients cached per model, event-loop-binding caveat handled (`backend/providers/registry.py:14-60`).
- Tools run concurrently, off-loop, order-preserving, semaphore-bounded (`backend/agent.py:149-172`), three tests pin it.
- System + tool schemas built once per turn; Anthropic breakpoints on system and last tool, attached to a copy; byte-stability pinned by `test_prefix_is_byte_stable`.
- Tool results appended before yielding, so a client disconnect cannot brick a session.
- One canonical token contract (`backend/usage.py`); pricing returns `None`, never `0.0`.
- Skill bodies arrive as tool results, never a prompt rewrite (`backend/skills.py`). Every harness surveyed (Hermes, pi, Claude Code, Codex, Deep Agents) does exactly this.
- DeepSeek `reasoning_content` already round-trips on every turn (required with tools present, or 400).
- RAG retriever cached by mtime+size fingerprint with eviction (`backend/rag/retriever.py:186-239`).

### Broken or costly (ranked; fixed in P1.5 below)

| # | Issue | Where |
|---|---|---|
| 1 | **Bug.** Cached RAG sqlite connection uses default `check_same_thread=True`; tools now run on arbitrary threadpool threads → the second `semantic_search_kb` from another thread raises `ProgrammingError`, swallowed into "tool failed unexpectedly". Live for customer-service. | `backend/rag/vector_index.py:63`, `backend/rag/retriever.py:186` |
| 2 | **Cost.** No cache breakpoint on messages. Breakpoints cover ~1.2–4.8k tokens; the growing tool-result-laden message log is re-sent uncached on every hop (quadratic in hops). The customer-service tool breakpoint (~651 tok) is below Anthropic's 1024-token minimum, so it is a silent no-op. | `backend/providers/anthropic_provider.py:83-99` |
| 3 | **Correctness.** Turn cap = `len(messages) >= MAX_TURNS*2`; tool hops add 1–N messages, so tool-heavy OpenAI-compat sessions 429 at ~¼ of the intended turn count. No compaction anywhere. A continuously running business agent cannot live with a dead-end cap. | `backend/app.py:338` |
| 4 | **Perf.** `search_kb` reads and splits every KB file per call; `max_results` unclamped. | `backend/kb_loader.py:169-209`, `backend/tools/kb.py:105` |
| 5 | **Perf.** `load_profile` does 2+N blocking file reads on the event loop per request (N× for `/api/profiles`). | `backend/app.py:321`, `backend/profiles.py:192-262` |
| 6 | **Perf.** When an endpoint reports no usage (documented Kimi behavior), the full message log is `json.dumps`'d on the loop per hop. | `backend/providers/openai_compat_provider.py:234` |
| 7 | Fresh `voyageai.Client` per semantic search; no shared `httpx.Client` for `web_search`/`fetch_url_text`; `catalog.json` re-parsed per call. | `retriever.py:197`, `web_search.py:58`, `web_fetch.py:108`, `sales.py:33` |
| 8 | `list_kb` result count uncapped → an unbounded tool result lives in the session forever. | `backend/kb_loader.py:82-120` |
| 9 | Session reuse keyed on provider family, not model: gpt-5 → kimi keeps a log Kimi/DeepSeek may 400 on. | `backend/app.py:333` |
| 10 | `supports_caching` unread and wrong for DeepSeek/OpenAI/Kimi (all three cache automatically and the code reads their hit counters). | `backend/config.py` registry |
| 11 | `MAX_TOKENS=4096` global ceiling silently caps every model; DeepSeek thinking shares that budget. | `backend/config.py:23,289-298` |
| 12 | Budget checked before / recorded after: N concurrent turns can overshoot the daily cap. TTL sweep is lazy-only. | `backend/budget.py`, `backend/app.py:72-76` |
| 13 | Errors reach the client as one generic string; the UI cannot offer Retry / Switch provider. | `backend/agent.py:86,116` |

(Items in code that Phase 1 deletes — reranker's per-call sync `Anthropic()` in `backend/llm_json.py:32`, Gemini's missing `max_retries` — are not fixed; they are removed.)

---

## 2. Corrections to `Runnrr-update.md` (verified drift)

All file:line anchors were checked against `ed536ff`. Apply these before execution:

| Phase | Claim | Actual |
|---|---|---|
| 1b | `hybrid_rerank` in 5 files | also `web/evals/index.html:48` |
| 1c | delete `profiles.py:36–129` | **`class ProfileConfigError` is at :41–42 inside that range**, imported by `app.py:54`. Delete 36–38, 45–59, 60–129 only. |
| 1c | manifest "only used by frampton" | runtime yes; also tested directly in `tests/test_profiles_and_translators.py:70-97`, referenced in `tests/test_skills.py:157`, `tests/test_builder_app.py:87`, `backend/builder.py:20`, `CLAUDE.md:108` |
| 1c | drop `grid`/`mark` from the three surviving profile.json | only frampton has them (deleted anyway); survivors carry `hero_icon`/`intro_ascii_name` only |
| 1c | drop `tool_hops` alias | also pinned by `tests/test_instrument_log.py:114,136,143` |
| 1c | test ranges | `test_tools.py:249–253`, `:676–728`, `test_agent_loop.py:107–129` |
| 1c | "skills catalog fills the manifest slot" | no bundled profile ships `skills/` today; true only once invoice-clerk lands |
| 2 | `read_file` rename "38 hits, 15 files" | 42 / 18 in py+js+json today (85 / 30 incl. md/html); 38/15 assumes 1a+1c already ran |
| 2 | "factor `_slice_lines` out" | no such helper; slicing is inline at `kb_loader.py:123-168` — an extraction, not a rename |
| 3 | `runnrr/store.py` | collides with `from backend.evals import store` at `app.py:53`; alias the evals import |
| 3a | "adapted from durable-sessions doc" | the draft doc specifies a `SessionStore` Protocol, `EASYAGENT_SESSION_DB`, a reset marker row; the plan says no Protocol, one file, epoch bump. Deliberate; say so in the roadmap fold. |
| 3 | fold note "ignore tenant_id / PR #2" | audit + hitl docs also specify `X-Admin-Token`; note must add "replaced by Supabase `require_user`" |
| 3b | PR #2 `auth.py` | 68 lines confirmed; also has `optional_user()` (401s on a bad token, `None` on no header) — keep it, it is the bypass path |
| 0 | `Runnrr-update.md`, `runnrr-feature-inventory.md` | untracked and unignored; move to `docs/plans/` in P0 |
| 9 | DeepSeek `reasoning_effort` | valid values are `low|high|max` (no `medium`); registry's `high` is the cost-max setting |

---

## 3. Feature inventory → what exists (backend only)

| Inventory area | Status on main | Lands in |
|---|---|---|
| Sessions: storage, TTL, cap | PARTIAL (in-process dict; no list/search/pin/title/persist) | P3a |
| Per-profile model + reasoning effort | NO (`ChatRequest.model` required) | P2 |
| Bots (named agents, CRUD, clone) | PARTIAL (builder API, gated; deleted in 1a) | P6 |
| Skills: SKILL.md, catalog, `read_skill` | YES (name+description only) | P5b adds spec fields, toggles, learned |
| Tools: registry, allowlist, parallel exec | YES | P5b adds groups |
| `requires_approval` / HITL | NO (design doc on branch) | P3d |
| Workspace files + shell | NO (KB is read-only by design) | P2 |
| Memory (cross-session), session search | NO | P5a |
| MCP | schema parsed, no client | P7 |
| Cron / scheduled jobs, artifacts | NO | P5c |
| Messaging gateways | NO (Twilio design docs on branches) | P8 |
| Sub-agents, todo tool, clarifying-questions tool | NO | P5a |
| Settings API / key entry / first-run | NO (env only) | P4 |
| Audit log, kill switch, usage per user | logs only; global budget | P3c |
| Provider error surfacing with codes | generic string only | P1.5 |
| Evals | YES (JSON+JSONL under `profiles/<id>/evals/runs/`) | roadmap: pass^k |
| Browser automation, computer use, image gen, STT, A2A, rooms, skills hub | NO | roadmap only |

---

## 4. Repo organization (root cleanup)

Target root after P0/P1:

```
.github/pull_request_template.md   (repo-conventions skill)
CONTRIBUTING.md                    (repo-conventions skill)
CLAUDE.md, AGENTS.md -> CLAUDE.md, README.md, LICENSE, history.md
pyproject.toml, uv.lock, .python-version, .env.example, .gitignore
runnrr/            (was backend/)
profiles/  tests/  web/  kb/
docs/
  agent_best_practices.md
  roadmap/README.md + one file per deferred feature (8 draft-branch docs folded)
  plans/runnrr-update.md, runnrr-feature-inventory.md   (moved from root)
deploy/
  runnrr.service   (was easyagent.service; drop User=root, /opt/runnrr, runnrr.app:app)
  README.md        (10 lines: manual deploy = git pull && systemctl restart runnrr)
```

- `git mv easyagent.service deploy/runnrr.service`; delete `Caddyfile`, `deploy.sh` (nothing references them by filename).
- `git mv` both planning docs to `docs/plans/`.
- Delete empty `.cursor/`. `.gitignore`: drop stale `easyagent-walkthrough.html`; add `workspace/`, `data/`.
- `uv lock` and commit `uv.lock` (P0 step 9's venv rebuild becomes reproducible; `.gitignore` already anticipates it).
- `pyproject.toml`: minimal `[tool.ruff]` (`line-length = 100`, `select = ["E","F","I"]`); no mypy. `name`/`description`/`packages=["runnrr"]`; drop `google-genai`; add `pypdf`, `python-multipart`, `PyJWT` in the phases that need them.

---

## 5. PR sequence

Every PR: branch `<prefix>/<slug>` off `main`, strictly sequential (each edits
`app.py`/`config.py`/CLAUDE.md). Test: `.venv/bin/python -m pytest -q`. Each PR
ends with its CLAUDE.md/README delta and a dated `history.md` entry.

### P0 `chore/rename-runnrr` — Runnrr-update.md Phase 0, plus §4 actions
Roadmap fold note must cover `X-Admin-Token` → `require_user` and the 3a divergence.

### P1a / P1b / P1c cuts — as written, with §2 corrections applied.

### P1.5 `perf/hot-path-and-cache` — NEW (after the cuts, so nothing deleted gets optimized)

Ordered by impact, smallest diff each:

1. **sqlite thread bug.** `vector_index.py`: `check_same_thread=False` + one `threading.Lock` around query. Test: two threads query one cached retriever.
2. **Message-log caching (Anthropic).** Prefer the request-level automatic `cache_control` if the installed SDK exposes it (one kwarg, breakpoint moves forward each turn). Fallback: send `messages[:-1] + [copy of the last message with cache_control on its last block]`; `format_user` emits list content. Never mutate the stored log. `RUNNRR_CACHE_TTL=5m|1h` → `{"type":"ephemeral","ttl":"1h"}` on system+tools (1h costs 2× write vs 1.25×; pays when turns are >5 min apart, which `SESSION_TTL=1800` implies; 1h entries must precede 5m ones). Extend `test_prefix_is_byte_stable`; assert ≤4 breakpoints. Log a warning when an Anthropic turn reports zero cache read and zero cache write (prefix below the model's cacheable minimum).
3. **OpenAI proper:** send `prompt_cache_key=f"{profile_id}:{session_id}"` only when `base_url is None`. One line.
4. **Turn cap + compaction.** Count user messages, not `len*2`. Two tiers, both cheap and append-safe:
   - *Mask* (default): when the last hop's `input_tokens` > `RUNNRR_COMPACT_AT` (0.5) × `context_window`, replace the bodies of tool_result blocks older than the last 4 turns with `"[output cleared; re-run the tool if needed]"`, in one bulk pass (each pass invalidates the cache from that point, so do it rarely and in bulk). Research: masking halves cost and matches LLM summarization on SWE-bench (arXiv 2508.21433). On Anthropic use the server-side `context_management` `clear_tool_uses` param instead of editing the log (thinking blocks on newer Claude models are bound to their prefix; client-side edits can 400).
   - *Summarize* (ceiling): at 0.75 × `context_window`, one call with the same model (override `RUNNRR_COMPACT_MODEL`) using a fixed template (Goal / Constraints / Progress done-in progress-blocked / Key decisions / Files touched / Next steps, ~1k tokens), then replace the log with `[summary as user message, last 2 turns]`. Never cut between a tool_use and its tool_result. Becomes an epoch bump once P3a lands; old rows stay searchable.
5. **`search_kb`:** clamp `max_results ≤ 50`; cache file text by `(path, mtime, size)` in a module dict. `# ponytail: unbounded dict; KB is small and read-only`.
6. **`load_profile`:** memoize by `(profile_dir, mtime of profile.json, system.md, skills dir)`; keeps "new skill visible next turn" without re-reading per request. Superseded by the per-session snapshot in P3a.
7. **`_estimate_usage`:** running char count instead of `json.dumps` of the whole log.
8. Module-level `httpx.Client()` in `web_search.py`/`web_fetch.py`; memoize the embedding provider next to the retriever; cache `catalog.json` by mtime; cap `list_kb` at 500 entries.
9. Session key includes the model id (reset on any model switch; already the contract for provider/profile).
10. Registry: set `supports_caching: True` for DeepSeek, OpenAI, Kimi (they are read-only automatic caches) and keep the flag; it now means "usage will carry cache-hit counters".
11. `MAX_TOKENS` default → 8192.
12. Error events carry a stable `code` (`provider_error`, `rate_limited`, `budget_exhausted`, `max_hops`, `session_capped`). Additive to the SSE contract; lets the UI render Retry / Switch provider (inventory §2).
13. `PROVIDER_MAX_RETRIES` 2 → 3 (529 overload is the common failure). Skipped: a hop-level retry layer and fallback model; add when logs show `stream_error` rates that matter.

### P2 `feat/workspace-tools` — as written, plus
- `AgentProfile.model`, `reasoning_effort`, `max_tokens` from `profile.json`; `ChatRequest.model` optional (request → profile → `DEFAULT_MODEL`). `reasoning_effort` maps to the OpenAI-compat param (DeepSeek `low|high|max`) and to Anthropic `thinking_budget` (`low`=1024, `high`=registry default, `max`=2× ). Registry default for DeepSeek stays `high`; invoice-clerk sets `low` and the smoke evals decide.
- `ToolDef.side_effect: bool` (`write_file`, `edit_file`, `run_command`, later `memory`, adapters). In `agent.py`: read-only calls fan out via `gather`; side-effect calls run sequentially in emission order. One result per `tool_use_id` always.
- **Tool-output offload** in `dispatch.run_tool`: over `MAX_TOOL_OUTPUT_BYTES`, write the full output to `<workspace>/.runnrr/tool-output/<tool_use_id>.txt`, return head + `{"truncated": true, "full_output_path": …, "hint": "read_file with start_line/end_line, or search narrower"}`. Deep Agents (20k-token evict to `/large_tool_results/{id}`), Claude Code (`tool-results/<id>.txt`), Cursor (−46.9% tokens) all do this. Keeps the log small, which is the biggest per-hop cost lever.
- Workspace deny list in `_safe_resolve` callers: `.env*`, `.git/`, `.runnrr/` are unreadable/unwritable by file tools. `run_command` as written (`start_new_session`, `killpg`, env scrubbed, 30k caps, Unix only); network stays on (`# ponytail: no network jail; upgrade path is bwrap/Seatbelt like Codex/Claude Code`).
- `edit_file` exactly-one-occurrence; `write_file` 1 MB cap; `read_file(path, start_line, end_line)` with the `_slice_lines` extraction.

### P3a–3d state and control — as written, plus
- **3a session row** copies Hermes' proven column set: `id, profile_id, provider, model, user_id, epoch, title, pinned, source, started_at, last_seen, message_count, tool_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, system_prompt, tools_json`. `system_prompt` and `tools_json` are **frozen at session creation**: the skills catalog, tool list, and (P5a) memory are snapshotted once, so the prefix cannot drift mid-session and profile edits apply to new sessions (the inventory's "Changes apply to new sessions"; Hermes/OpenClaw do the same). `messages(session_id, epoch, seq, role, content_json, tool_name, token_count, active)` append-only; compaction marks old rows `active=0`. FTS5 virtual table over message text (stdlib sqlite ships FTS5 on macOS/Linux builds; test asserts it).
- **Sessions API** (needed by the UI): `GET /api/sessions` (grouped-by-date fields: id, title, profile, model, pinned, last_seen, message_count), `POST /api/sessions/{id}/pin`, `POST /api/sessions/{id}/delete`, `GET /api/sessions/search?q=` (FTS5), `GET /api/sessions/{id}/messages`. Title = first 60 chars of the first user message (no LLM call). Export = JSONL of the rows (pi's format is the reference).
- WAL, `BEGIN IMMEDIATE`, `busy_timeout=1000`, one `runnrr/store.py` of plain functions; `init_schema()` lazy on first connect.
- 3c `_instrument` → `runnrr/instrument.py`; audit rows carry `user_id`, secret-scrub regex; `tool_result` rows for `write_file`/`edit_file` double as artifact records (P5c).
- 3d `requires_approval` as written; approval events also get a stable SSE `code`.

### P4 `feat/runnrr-up` — as written
- `GET /api/settings` returns `providers: [{id, label, configured, get_key_url}]` so the first-run screen is data-driven; `POST /api/settings` open only while no provider is configured.

### P5a `feat/agent-memory-and-planning` (inventory: Memory, Session Search, Task Planning, Clarifying Questions, Task Delegation)
- **Memory** = one `<workspace>/MEMORY.md` per agent, hard cap 2,000 chars (Hermes: 2,200), loaded into the session's frozen `system_prompt` snapshot at session start (cache-safe; visible next session). Tool `memory(action: add|replace|remove, text, old_text?)`, `side_effect=True`. No vector memory (Letta's benchmark: file-based memory beats Mem0 on LoCoMo).
- `search_sessions(query, limit)` → FTS5 from P3a; returns session id, title, snippet.
- `todo_write(items)`: stores the list in `ToolContext.scratch` for the turn and echoes it back (Manus-style recitation). No persistence; the workspace `progress.md` written via `write_file` covers cross-session state.
- `ask_user(questions[{text, options[], recommended?}])`: returns `{"status": "awaiting_user"}`, the loop emits an SSE `question` event and ends the turn; the answer is the next user message. Append-only.
- `delegate_task(goal, context)`: nested `run_conversation_stream` with a fresh message list, same profile minus `delegate_task`/`memory`/`ask_user`, hop cap 6, returns final text only, off by default (`profile.json` `"delegation": true`). Anthropic's multi-agent post: sub-agents help only for context isolation and cost ~15× tokens; that is the only use we claim. `# ponytail: same process, same model, no concurrency; Hermes-style max_spawn_depth=1`.

### P5b `feat/capabilities-model` (inventory §5 Skills/Tools)
- `ToolDef.group` and `GET /api/tools` grouped with counts (`File Operations`, `Terminal`, `Knowledge`, `Web`, `Memory`, `Planning`, `Skills`, `Sales`).
- Profile `skills_disabled: [slug]`; honored by `discover_skills`.
- SKILL.md frontmatter validated against the agentskills.io spec (`name` matches directory, ≤64, `[a-z0-9-]`; `description` ≤1024; optional `license`, `compatibility`, `metadata`, `allowed-tools`); `allowed-tools` narrows the tool allowlist while the skill is active (tool-result-level, no prefix change). Catalog lines encourage "when NOT to use" text.
- `save_skill(name, description, body)` tool → `learned: true` in `metadata`; capped by `MAX_SKILLS_PER_PROFILE`; excluded from the catalog until the next session (snapshot).

### P5c `feat/cron-and-artifacts` (inventory §7, §8)
- `cron_jobs(id, profile_id, name, cron_expr, prompt, enabled, state, last_run_at, last_status, next_run_at, deliver)` table. `asyncio` ticker in lifespan every 60 s (single worker makes in-process correct — Hermes and OpenClaw both do this). 5-field cron matcher, ~40 lines, `# ponytail: minute granularity, local time, no seconds/timezones; croniter if ever needed`. Due job → fresh session `cron:<job_id>` through `instrument(run_conversation_stream)`; cron tool disabled inside cron runs; output stored as an artifact; `deliver` = `none|channel:<id>` (P8).
- `GET/POST /api/cron`, `POST /api/cron/{id}/pause|resume|run`. Blueprints = `runnrr/blueprints.json` (invoice chasing, lead follow-up, weekly review, competitor watch).
- `GET /api/artifacts?type=file|text` = audit `tool_result` rows for `write_file`/`edit_file` plus cron outputs.

### P6 `feat/agent-management-api` (inventory §9 Bots)
Authenticated CRUD for profiles: create/clone (`cloned_from`), update `system.md`/tools/model/effort, knowledge notes, skills; `avatar` stored as a string. The lean return of the builder's write paths, behind `require_user`.

### P7 `feat/mcp-runtime`
Implement the `TODO(mcp)` sketch: stdio only, tool list frozen into the session's `tools_json` at creation, MCP tools dispatched by name prefix `mcp__<server>__`. Cap total tools at 20 per session (accuracy cliff at 30–50); skip deferred loading/tool search until a profile exceeds it.

### P8 `feat/channel-adapters`
One `Adapter` shape: `connect() / send(target, text)` + inbound → `handle_message(platform, chat_type, chat_id, user, text)`. Session key from one function `channel_session_key(platform, chat_type, chat_id)`; default-deny allowlist of chat ids; per-session turn lease. First adapter: **Telegram** (long-poll bot API: no public URL, works on a Mac install, one class, stdlib `urllib` or the existing `httpx`). Twilio SMS second, from the draft-branch design doc (needs an inbound URL, cloud installs only).

Order after P4 (owner's call, 2026-09-06): P5a memory + planning → P5b capabilities → P5c cron + artifacts → P6 agent CRUD → P7 MCP → P8 channels.

### Roadmap only (`docs/roadmap/`)
channel-voice, calendar-crm adapters (first `requires_approval=True` tools), dlp-redact, group-management, mac-packaging, cloud-provisioning, model-config-file (`models.json` + pricing + min cacheable tokens + peak/off-peak DeepSeek rates), docker/bwrap sandbox, network egress allowlist proxy, browser-automation, rooms/A2A, skills-hub, escalation routing (cheap default → Sonnet on hop cap / repeated tool errors), evals-generalization (tool trajectories, pass^3), pre-compaction memory flush, hooks registry, deferred tool loading.

---

## 6. What we borrow, and from where

| Idea | Source | Applied in |
|---|---|---|
| Stable/volatile split: nothing per-turn in the system block; per-session frozen snapshot of system+tools+memory | Hermes prompt assembly, OpenClaw cache boundary, Claude Code layering | P3a, P5a |
| Rolling breakpoint on the newest message; 5m/1h TTL knob | Hermes `system_and_3`, OpenClaw `cacheRetention`, Anthropic docs | P1.5 |
| Observation masking before summarization; bulk, rare passes | arXiv 2508.21433, Anthropic context editing | P1.5 |
| Fixed summary template, never split tool pairs, old rows kept `active=0` | pi compaction entry, Hermes head/tail zones | P1.5, P3a |
| Tool-result eviction to a file + head/path pointer | Deep Agents, Claude Code, Cursor | P2 |
| Sequential side-effect tools, parallel read-only | pi `executionMode`, Anthropic parallel-tool docs | P2 |
| SQLite WAL + FTS5 session store with Hermes' column set; JSONL export | Hermes `state.db`, pi session format | P3a |
| Bounded `MEMORY.md` with `add/replace/remove`, snapshot at session start | Hermes memory, Claude Code auto-memory | P5a |
| `todo` recitation, `progress.md` for crash recovery | Manus, Anthropic long-running harness post | P5a |
| Clarifying-questions as a tool that ends the turn | Hermes `clarify` toolset, Codex approvals | P5a |
| Delegation = same loop, reduced toolset, summary-only return, depth 1 | Hermes `delegate_task`, OpenClaw `sessions_spawn` | P5a |
| agentskills.io frontmatter, `allowed-tools`, catalog budget, session snapshot of eligible skills | pi, Deep Agents, OpenClaw, Codex 2% budget | P5b |
| In-process 60 s cron ticker, isolated session per run, recursion guard | Hermes `InProcessCronScheduler`, OpenClaw `sessionTarget: isolated` | P5c |
| Channel session-key builder, default-deny allowlist, turn lease | Hermes gateway, OpenClaw `dmScope` | P8 |
| Tool cap ~20/session; defer/search only above it | Anthropic tool-search data, RAG-MCP paper, pi's "no MCP" rationale | P7 |
| Sandbox policy shape (writable cwd, deny `.env`/`.git`, env allowlist) | Codex, Claude Code sandbox-runtime | P2 (partial), roadmap |

Rejected on purpose: pi's JSONL branching/fork tree (TUI feature); OpenClaw's WebSocket control plane and 25 adapters; Deep Agents' LangGraph stack (SQLite covers it); a hooks/plugin registry (approvals and audit live inline in `dispatch.py`); vector memory (files win on LoCoMo and need no dependency); strict/grammar-constrained schemas (schema change wipes the Anthropic cache; DeepSeek strict is beta on a separate base URL); server-side Anthropic `compact_20260112` (bills via `usage.iterations`, which would need `tally()` changes; client-side is provider-neutral).

---

## 7. Verification

1. Every PR: `pytest -q` green; the grep gates from Runnrr-update.md.
2. P1.5: a 4-hop Anthropic turn on customer-service logs `cache_read > 0` on hops 2–4; the two-thread semantic-search test passes; a 60-turn tool-heavy DeepSeek session masks at 50% and summarizes at 75% instead of 429ing; `prompt_cache_hit_tokens` on DeepSeek stays > 90% of input across a session.
3. P2–P4: the Runnrr-update.md end-to-end list (invoice inbox → `ledger.csv` + `anomalies.md`; restart-resume; `runnrr up` with no `.env`). Plus: a `run_command` that prints 1 MB is truncated with a `full_output_path` the model can `read_file`.
4. P3a: `GET /api/sessions/search?q=invoice` finds the session; a profile `system.md` edit does not change the running session's prefix (assert `cache_read > 0` on the next turn) and does apply to a new session.
5. P5a: "remember that our VAT rate is 20%" → new session answers from memory; `ask_user` yields a `question` event and the next POST continues the same session; `delegate_task` returns only text and its tokens show in the parent's `chat_complete`.
6. P5c: a `* * * * *` job fires within 60 s and its output appears in `GET /api/artifacts`; the cron session does not appear in the chat session list.
