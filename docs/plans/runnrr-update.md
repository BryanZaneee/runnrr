# EasyAgent → Runnrr: refactor, cut, and sandbox plan

## Context

EasyAgent is a multi-provider agent engine that today exists to serve bryanzane.com's
public chat (personal-agent profile, brand chrome, Caddy on a shared VPS). Bryan is
pivoting it into **Runnrr**: a business-task agent (invoices/paperwork, lead-gen,
receptionist) that runs continuously either on the customer's Mac or on a dedicated
cloud computer, is reached through a web UI with a Supabase login, and works inside
its own sandbox workspace (files + shell), Hermes/OpenClaw-style. Cost-effectiveness
(prompt-prefix caching, cheap models like DeepSeek V4 Flash) is a core constraint.

The repo currently carries: 3 stale Supabase SaaS PRs (#1–#3), a docs PR (#10) that
decided "Runnrr is only a product name, no sandbox", and 8 draft PRs (#11–#18) holding
design docs + skipped contract tests for durable sessions, audit/kill-switch, HITL,
SMS, voice, CRM adapters, MCP, and DLP. No sandbox, write tool, MCP client, auth, or
durable state exists on `main`.

## Decisions locked with the owner (2026-09-03/04)

| Topic | Decision |
| --- | --- |
| Name | Rename in place, fully: GitHub repo `runnrr`, local dir `~/programming-projects/Runnrr`, package `backend/` → `runnrr/`, env `EASYAGENT_*` → `RUNNRR_*`, loggers `runnrr.*`, `runnrr.service` |
| Shape | One **runtime per business** (the "hub"): runs on the customer's Mac (downloadable) or in a per-customer VPS container, continuously. Web UI (Bryan builds it in Claude Design, delivered later) talks to the runtime's HTTP API. Data lives with the runtime |
| Tenancy | Single business per runtime. **No `tenant_id`.** Sessions/audit carry `user_id` (employees of that business). Group management (boss buys account, delegates employees) = later PR on Supabase tables |
| Auth | **Supabase Auth from the start**: runtime verifies Supabase HS256 JWTs (salvage `backend/auth.py` from PR #2, 68 lines, PyJWT). `RUNNRR_AUTH_DISABLED=1` bypass only when `RUNNRR_ENV != production` |
| Data | Workspace folder per agent + one SQLite file (stdlib) for sessions, audit, approvals. No Supabase for business data |
| Sandbox | Local workspace dir, **full shell** jailed by cwd + timeout + output cap + env scrubbed of keys. No Docker inside the runtime (Docker is the deployment boundary between customers and the documented upgrade path) |
| bryanzane.com | Cut loose. Freeze the VPS deploy on the last EasyAgent commit |
| Delete | Agent Builder, Gemini provider, personal-agent/frampton/bzs-concierge profiles, `kb/frampton`, `personal_kb.py`, Caddyfile, deploy.sh, sales_pitch.md, RAG pca/inspect/reranker |
| Keep | Anthropic + OpenAI-compat providers, usage/pricing/budget, profiles, skills, RAG (trimmed), evals (generalize later), `web/` dashboard as dev tooling until the new UI lands |
| First slice | Invoice/paperwork intake profile |
| Draft PRs | Fold the 8 design docs into `docs/roadmap/`, close #1–#3 and #10–#18 |
| Model config file | Separate later PR (owner's call); `MODEL_REGISTRY` stays a dict for now |
| Conventions | Install CONTRIBUTING.md + PR template via the `repo-conventions` skill (never from memory) |
| Execution | Bulk coding delegated to Cursor CLI per phase (owner preference; autonomous flags need explicit OK each session). I review diffs + run tests before the next phase |

## Core constraints and what they change

**Cost effectiveness** and **usability for non-technical people** are the two constraints
every phase is checked against. Concrete consequences baked into the phases below:

| Constraint | What the plan does about it |
| --- | --- |
| Cost | Code default model becomes `deepseek-v4-flash` (today's code default is `claude-sonnet-4-5`; only `.env` overrides it). Prefix-cache rules enforced by tests on every new profile. Each profile declares its own `model`, so a cheap model is the default and a stronger one is an explicit per-agent choice. Per-turn `cost_usd` and the daily budget already exist and are surfaced to the UI unchanged |
| No model picker for users | `ChatRequest.model` becomes optional: resolved as request → `profile.model` → `DEFAULT_MODEL`. Non-technical users never see a model dropdown; the owner sets it once per agent |
| No terminal, no folders | Files reach an agent through the UI: `POST /api/workspace/{profile}/upload`, `GET .../files`, `GET .../download` (Phase 2). "Copy samples into a folder" is the developer path only |
| No `.env` editing | First-run settings API + settings screen: provider keys and the Supabase project settings are entered once in the UI and stored in `data/settings.json` (Phase 4). `.env` stays as the developer/cloud override |
| One click to run | `runnrr up` starts the runtime and opens the browser on the bundled UI (Phase 4); this is what the Mac installer wraps. The runtime serves the UI itself so local and cloud installs behave identically |
| Plain-language surfaces | Agents are created and edited through an authenticated agent-management API that backs the Claude Design UI. The old public Agent Builder is deleted now (owner's call), and its `save_profile` / notes / skills write paths come back lean, behind auth, when the UI arrives (roadmap `agent-management-api`) |
| Developer-only tooling deprioritized | The CLI moves from a phase to the roadmap. Evals and the `web/` dashboard stay as developer tools, not user surfaces |

## Target architecture

```
 Web UI (Claude Design, later)  ─┐   Supabase Auth JWT
 CLI (runnrr chat)               ─┼─▶ Runnrr runtime (FastAPI, one per business)
 SMS / voice adapters (roadmap)  ─┘        │
                                           ├─ runnrr/agent.py loop  ─▶ Anthropic / DeepSeek / OpenAI / Kimi
                                           ├─ tools: kb (read-only ref docs), workspace (files+shell), web, sales, skills
                                           ├─ workspace/<agent>/   (sandbox, mutable)
                                           └─ data/runnrr.sqlite3  (sessions, audit, approvals)
 Runs on: customer Mac  |  one container per customer on the VPS (same install)
```

Prefix-cache rules stay law: system block + tool schemas built once per turn, static
schemas, append-only messages, no volatile data in the system prompt.

## Phases (one PR each, strictly sequential, all off `main`)

Test command everywhere: `.venv/bin/python -m pytest -q`.

### Phase 0 — `chore/rename-runnrr`

Purpose: mechanical rename, zero behavior change; conventions; roadmap fold; close PRs.

1. **Freeze the old deploy first.** `git tag v0.1.0-easyagent-final ed536ff && git push origin --tags`. On the VPS, `/opt/easyagent` stays on that tag; remove `easyagent` from `/opt/deploy/deploy.sh`'s `REPO_MAP` so a stray dispatch can't pull Runnrr onto bryanzane.com.
2. `gh repo rename runnrr` (updates `origin`). `git mv backend runnrr`, `git mv easyagent.service runnrr.service`.
3. Anchored sed (macOS `sed -i ''`), excluding `.git`, `.venv`, `kb/`, `history.md` body:
   `\bbackend\.`→`runnrr.`, `\bfrom backend\b`→`from runnrr`, `\bbackend/`→`runnrr/`,
   `EASYAGENT_`→`RUNNRR_`, `EasyAgent`→`Runnrr`, `easyagent`→`runnrr`.
   Do **not** touch the embedding-backend sense of "backend" (`EMBEDDING_BACKEND`, `self.embedding.backend`). Verify with `grep -rnw backend` (only embedding hits) and `grep -rni easyagent` (only history.md).
   Tests that pin names: `caplog(logger="easyagent")` in `tests/test_instrument_log.py` (7×), `test_app.py` (2×), `test_app_runtime.py` (2×); regex `easyagent\[rag\]` at `tests/test_rag_foundation.py:190`; `tests/test_evals_runner.py:32` env name; `web/shared.js` localStorage key.
4. Hand edits: `pyproject.toml` (name, description, `packages=["runnrr"]`), `runnrr/app.py` `FastAPI(title="Runnrr")`, `runnrr.service` (`/opt/runnrr`, `runnrr.app:app`, drop `User=root`), `runnrr/tools/web_fetch.py:112` User-Agent, `.gitignore`, `web/index.html` title/mark, `.env.example`.
5. Docs: README first paragraph + CLAUDE.md "Project Overview" rewritten to the Runnrr positioning (self-hosted runtime, per-agent workspace, Supabase login); commands and VPS section updated; `history.md` gets a top naming note (Runnrr, formerly EasyAgent, formerly Strauss) and a dated entry "EasyAgent becomes Runnrr" with Choice/Why/Rejected (rejected: name-only split from PR #10, multi-tenant SaaS PRs #1–#3); `kb/README.md` still says `strauss`, fix.
6. Conventions: invoke the `repo-conventions` skill and copy its assets verbatim (CONTRIBUTING.md, `.github/pull_request_template.md`). The branch `docs/runnrr-engine-map` has an older hand-written copy; the skill's version wins.
7. Roadmap fold: `docs/roadmap/README.md` (order: supabase-auth → durable-sessions → audit-kill-switch → hitl → channel-webhooks → channel-voice → calendar-crm → mcp-runtime → dlp-redact → group-management → serve-ui-from-runtime → mac-packaging → cloud-provisioning → model-config-file → docker-sandbox). For each of the 8 branches: `git show origin/feat/<b>:docs/prs/feat-<b>.md > docs/roadmap/<b>.md`, prepend "Single-tenant: ignore every tenant_id / PR #2 reference", append the contract-test docstrings as an Acceptance list. Add a note that PR #2's `backend/auth.py` is the seed for supabase-auth.
8. Close PRs #1–#3 (single-tenant runtime; auth.py salvaged), #10 (superseded), #11–#18 (folded). Delete merged remote branches (`feat/caching-and-event-loop`, `feat/honest-accounting`, `feat/markdown-skills`, `feat/model-capabilities`, `chore/debloat-*`, `refactor/tools-rag-evals-split`); delete the draft/SaaS branches after this PR merges.
9. After merge: `mv ~/programming-projects/easyagent ~/programming-projects/Runnrr`, `rm -rf .venv && uv venv --python 3.13 && uv pip install -e ".[dev,rag]"` (editable `.pth` holds the old absolute path), rename keys in local `.env`.

Verify: tests green; `uvicorn runnrr.app:app --port 8001` boots; grep checks above return nothing.

### Phase 1 — three cut PRs (order matters)

**1a `chore/cut-builder-gemini`.** Delete `runnrr/builder.py`, `web/builder/`, `tests/test_builder_app.py`, `runnrr/providers/gemini_provider.py`. In `app.py`: drop builder routers, `X-Builder-Owner` CORS header, `"gemini"` from `REGISTERED_PROVIDERS`, the `p.builder` skip in `list_profiles`. `config.py`: drop `ENABLE_PROFILE_EDITOR`, `RATE_LIMIT_BUILDER`, `MAX_BUILDER_PROFILES`, `MAX_NOTES_PER_PROFILE`, `MAX_SKILLS_PER_PROFILE`, `BUILDER_PROFILE_TTL_DAYS`, both `gemini-2.5-*` entries; `available_models` branch. `types.py` `ProviderName` literal; `providers/registry.py` gemini branch; `profiles.py` `builder` field; `pyproject` drop `google-genai`; `.env.example` drop `GEMINI_API_KEY` + builder lines; `web/index.html` builder link. Tests: delete Gemini sections in `test_providers.py` (~392–594 and the ms-timeout test), `test_model_capabilities.py::TestGeminiCorrectness` (rewrite the synthetic-thinking case on `kimi-k2.6`), gemini cases in `test_usage_accounting.py`, `test_app.py:44–55`, `test_profiles_and_translators.py:270–275`.

**1b `chore/trim-rag`** (before 1c: `rag/inspect.py` imports `label_from_kb_path`). Delete `rag/pca.py`, `rag/inspect.py`, `rag/reranker.py`, `tests/test_rag_reranker.py`. `app.py`: drop `RagInspectRequest`, `POST /api/rag/inspect`, `RATE_LIMIT_RAG_INSPECT`. `config.py`: drop `RATE_LIMIT_RAG_INSPECT`, `RERANK_ENABLED`. `rag/retriever.py`: `hybrid_candidate_pool(k) = max(1,k)*4`, remove `rerank` params. `rag/tools.py`, `rag/indexer.py` (PCA sidecar call + method): remove. Evals: drop `hybrid_rerank` variant in `e2e.py`, `retrieval.py`, `runner.py`, `cli.py`, `web/evals/evals.js`. Tests: `test_app.py::TestRagInspect`, rerank tests in `test_rag_retriever.py`, PCA tests in `test_rag_indexer.py`.

**1c `chore/cut-personal-site`.** Delete `profiles/personal-agent/`, `profiles/frampton/`, `profiles/bzs-concierge/`, `kb/frampton/` (1,396 files), `runnrr/tools/personal_kb.py`, `Caddyfile`, `deploy.sh`, `docs/sales_pitch.md`. Also:
- Delete `build_kb_manifest` + `_MANIFEST_CACHE` + `clear_manifest_cache` + `inject_kb_manifest` (`profiles.py:36–129, 210–213`) and the `reset_manifest_cache` fixture. Only frampton used it; the skills catalog fills that slot.
- Simplify `runnrr/tools/source_metadata.py` 292 → ~110 LOC: the path-hiding layer existed for a public site. Keep `source_summary`, `source_items: [{label, kind}]`, `source_count`; `label` becomes the real relative path. Remove `hidden_count` everywhere (`results.py`, `agent.py:183`, `skills_tool.py`), `_label_from_slug`, `label_from_kb_path`, `_match_path_label`, `_cap_items`.
- Delete `AgentProfile.project_aliases/source_labels/source_path_labels`; drop `hero_icon`, `intro_ascii_name`, `grid`, `mark` from `BrandMetadata` and the three remaining `profile.json`s (keep `accent*`, `input_placeholder`).
- `app.py`: drop the `tool_hops` alias. `registry.py`: drop `PERSONAL_KB_TOOL_DEFS`. `config.py`/`.env.example`/`conftest.py:89`: `DEFAULT_PROFILE="customer-service"`. `.gitignore`: drop `!kb/frampton/`. CLAUDE.md/README: profile lists, file map, "Build phases" section deleted, VPS section → "manual: git pull && systemctl restart runnrr".
- Tests: `test_tools.py` (import at :20, resume/project tests :171–194, :213–215, :249–252, section :677–728 → one test asserting real paths in `source_items`), `test_agent_loop.py` (`make_test_profile` :80–104, invert `assert_public_source_metadata_is_safe` :107–127), `test_app.py` (:64–83 frampton→customer-service accent `#f0642f`, :107–119, :242–290), `test_profiles_and_translators.py` (:22–33, delete :35–131 and :223–250, :264–268, :359), `test_customer_service_profile.py` (:28–33, ascii asserts, smoke loop, :172 set), `test_caching_and_concurrency.py` (10× `personal-agent`→`customer-service`), `test_skills.py:130`, `test_evals_app.py:174`, `test_app_runtime.py:365,380`.

Verify after 1c: `grep -rn "personal-agent\|frampton\|bzs\|bryanzane\|hidden_count\|get_resume_summary\|inject_kb_manifest" runnrr tests web profiles README.md CLAUDE.md` → zero; `git ls-files kb` → only `kb/README.md`.

### Phase 2 — `feat/workspace-tools` (sandbox + invoice-clerk)

KB vs workspace: **stay separate**. KB = curated read-only reference docs (`profile.kb_root`, RAG-indexable). Workspace = mutable working dir (`profile.workspace`). Rename the KB reader `read_file` → `read_kb_file` (38 string hits, 15 files, sed-able) so the workspace family owns the natural names. Never ship two tools named `read_file`.

Add `runnrr/tools/workspace.py` (~220 LOC), five `ToolDef`s with static schemas, all through `kb_loader._safe_resolve(rel, root=ctx.workspace)`:
- `list_files(subdir="")` → reuse `kb_loader.list_kb(subdir, root=ws)`.
- `read_file(path, start_line, end_line)` → factor `_slice_lines()` out of `kb_loader.read_file` and reuse; `.pdf` via `pypdf` (new core dep, pure Python) with page separators; everything else plain text.
- `write_file(path, content)` → mkdir parents, reject dirs, 1 MB cap.
- `edit_file(path, old, new)` → exactly-one-occurrence rule (0 → "not found", >1 → "ambiguous, add context").
- `run_command(command, timeout=None)` → `subprocess.Popen(shell=True, cwd=ws, stdin=DEVNULL, start_new_session=True, env=_scrubbed_env())`; `communicate(timeout=min(timeout, RUN_COMMAND_TIMEOUT_SECONDS))`; on timeout `os.killpg(SIGKILL)` and return `timed_out: true`; stdout/stderr capped at 30k chars each. `_scrubbed_env` drops keys matching `(_KEY|_TOKEN|_SECRET|PASSWORD)$` (case-insensitive), keeps `HOME`/`PATH`, sets `RUNNRR_WORKSPACE`. Header: `# ponytail: shell=True + cwd is a convenience, not a security boundary — the jail applies to file tools only; trust model is "owner's own machine, agent is staff". Upgrade: swap _spawn() for docker run --rm -v ws:/work --network none. Unix only (killpg).`

Modify: `config.py` (`WORKSPACE_ROOT` from `RUNNRR_WORKSPACE_ROOT`, default `./workspace`; `RUN_COMMAND_TIMEOUT_SECONDS=60`; `MAX_TOOL_OUTPUT_BYTES=100_000`; `MAX_UPLOAD_BYTES=25_000_000`; `DEFAULT_PROFILE="invoice-clerk"`; `DEFAULT_MODEL="deepseek-v4-flash"`); `profiles.py` (`AgentProfile.workspace`, resolved as `config.WORKSPACE_ROOT / pid` unless `profile.json` overrides; no mkdir at load; `AgentProfile.model: str | None` from `profile.json`); `app.py` (`ChatRequest.model` optional, resolved request → `profile.model` → `DEFAULT_MODEL`; new `POST /api/workspace/{profile_id}/upload` (multipart, lands in `inbox/` via `_safe_resolve`, size cap, filename sanitized to basename), `GET /api/workspace/{profile_id}/files` (reuse `list_kb` on the workspace), `GET /api/workspace/{profile_id}/download?path=` (FileResponse through `_safe_resolve`); `python-multipart` added to deps); `tools/definitions.py` (`ToolContext.workspace`); `tools/dispatch.py` (thread `workspace=`, add the byte-cap backstop after `json.dumps`); `agent.py:156–159` (pass `workspace=profile.workspace`); `tools/registry.py`; `kb_loader.py` docstring ("Read-only" no longer true; error text "escapes root"); `.gitignore` `workspace/`; `conftest.py` autouse tmp workspace; `ChatRequest.message` max 4000 → 20 000.

Add `profiles/invoice-clerk/`: `profile.json` (tools: `list_files, read_file, write_file, edit_file, run_command, calculator, read_skill`), static `system.md` (no dates/paths; layout `inbox/`, `processed/`, `ledger.csv`, `anomalies.md`; never invent amounts; sums via `calculator`; call `read_skill('invoice-intake')` first), `skills/invoice-intake/SKILL.md` (ledger columns, anomaly rules: duplicate invoice_number, total ≠ subtotal+tax, due < issue date, missing vendor/total, total > 10k → review), `samples/` (2 txt, 1 csv, 1 duplicate, 1 minimal uncompressed PDF), `evals/smoke.json` (3 tool-trajectory cases in the `research-analyst` smoke shape), `README.md` (copy samples into `workspace/invoice-clerk/inbox/`, say "Process the inbox").

Tests `tests/test_workspace_tools.py`: upload lands in `inbox/` and a `../` filename is flattened, download refuses paths outside the workspace, chat without `model` uses the profile's model, jail (`../x`, absolute, symlink out), write→read round trip with nested dirs, edit exact/not-found/ambiguous, PDF read contains the invoice number, `pwd` == workspace, `sleep 5` with `timeout=1` → `timed_out` in < 3 s, `env` lacks `ANTHROPIC_API_KEY` but has `HOME`, `yes | head -c 200000` truncated, dispatch backstop truncates an oversized fake handler, `workspace=None` → error. Profile tests: invoice-clerk loads, skill catalog present, `test_prefix_is_byte_stable` extended to it, smoke.json in the structural loop.

Verify: tests; run uvicorn, drop samples in the inbox, POST "Process the inbox", confirm `ledger.csv` + `anomalies.md` flag the duplicate, and hop-2 `usage` shows `cache_read_input_tokens > 0` on an Anthropic model.

### Phase 3 — state and control (four PRs)

One SQLite file `RUNNRR_DATA_DIR/runnrr.sqlite3` (default `./data`), stdlib `sqlite3`, WAL, one `runnrr/store.py` of plain functions (no ORM, no Protocol), `init_schema()` run lazily on first connection. `conftest.py` autouse points `DATA_DIR` at `tmp_path`.

**3a `feat/durable-sessions`** (adapted from `docs/roadmap/durable-sessions.md`). Tables `sessions(id, profile_id, provider, user_id NULL, epoch, last_seen)`, `messages(session_id, epoch, seq, content_json)` append-only. `SESSIONS` dict stays as the in-process cache; `chat()` loads on miss, resets by bumping `epoch` (old rows kept), appends new messages in `_instrument`'s `finally`. JSON `default=` hook handles Anthropic SDK block objects (`model_dump`). Test: fresh app on the same file continues the session.

**3b `feat/supabase-auth`.** Copy PR #2's `backend/auth.py` → `runnrr/auth.py` (PyJWT HS256, `audience="authenticated"`, `CurrentUser(id, email)`, `require_user` dependency). Config: `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_ANON_KEY` (for the UI), `RUNNRR_ENV`, `RUNNRR_AUTH_DISABLED` (honored only when `RUNNRR_ENV != production`; production with no secret → fail at startup). `require_user` on every `/api/*` except `/api/health`; `chat()` stamps `user_id` on new sessions and 403s a session owned by another user. CORS `allow_headers` gains `Authorization`. Tests sign tokens with a test secret; existing tests run with the bypass. Roadmap note: group management adds `orgs/memberships/roles` tables in Supabase and a role claim check here.

**3c `feat/audit-kill-switch`.** Extract `_instrument` into `runnrr/instrument.py` (no FastAPI imports; the CLI and channels reuse it). Audit rows `user_message`, `tool_call`, `tool_result`, `assistant_message`, `error` with `user_id`; regex scrub for `sk-…`, `Bearer …`, `AKIA…`, `ghp_…`, `xox…`. `agent_flags(profile_id, disabled)`; `agent.py` checks `store.is_disabled` at the top of each hop; `chat()` 503s before the provider call; `POST /api/agents/{id}/disable|enable`, `GET /api/agents/{id}` behind `require_user`. Add `arguments` (2 KB cap) to the `tool_result` event.

**3d `feat/hitl-approvals`.** `ToolDef.requires_approval=False` default; `AgentProfile.tool_approval` (tighten-only from `profile.json`); `ToolContext.session_id`; dispatch returns `{"status":"queued_for_approval","approval_id":…}` instead of invoking; `approvals` table; `GET /api/approvals`, `POST /api/approvals/{id}/approve|reject`; approve runs the original handler and appends one user-role message (append-only, cache-safe). **`run_command`/`write_file` are not approval-gated by default**: the workspace is the blast radius, and a gated shell ends the turn on every command. External-side-effect tools (future `book_appointment`, `crm_note`, email) set it True. Any deployment can add `"tool_approval": {"run_command": true}`.

### Phase 4 — `feat/runnrr-up` (one command, settings in the UI, UI served by the runtime)

- `runnrr/settings.py`: `data/settings.json` holding provider keys, `default_model`, and Supabase project values; loaded at startup **after** `.env` so `.env` remains the developer/cloud override. Keys never returned by the API, only `configured: true/false` per provider. `available_models()` reads through it.
- `app.py`: `GET /api/settings` (which providers are configured, default model, auth state), `POST /api/settings` (write keys; behind `require_user`, or open only while no provider is configured yet so first run works). `GET /api/health` reports `setup_complete`.
- Static UI: `app.mount("/", StaticFiles(directory="ui", html=True))` after the API routes; `ui/` holds the Claude Design build (a placeholder page until Bryan delivers it). One process serves API and UI, so a Mac install and a cloud container are the same thing at different addresses.
- `runnrr/cli.py` + `__main__.py`, `[project.scripts] runnrr = "runnrr.cli:main"`, one subcommand `up [--port 8001] [--no-browser]`: starts uvicorn in-process and opens the browser with `webbrowser.open`. This is what the Mac installer wraps.
- Tests: settings round trip never echoes a key; unconfigured runtime lets `POST /api/settings` through once; `GET /` serves the placeholder; `available_models` picks up a key saved through settings.

Verify: fresh checkout, no `.env`, `runnrr up` opens the browser, enter a DeepSeek key on the settings screen, chat with invoice-clerk.

### Phase 5 — roadmap only (`docs/roadmap/`)

agent-management-api (authenticated CRUD for agents, knowledge notes, skills, per-agent model; the lean return of the builder's write paths, shaped by the Claude Design UI), channel-webhooks (Twilio SMS → `instrument(run_conversation_stream)`, session `sms:<from>`), channel-voice, mcp-runtime (implement the `TODO(mcp)` sketch, stdio only, frozen tool list per session), dlp-redact, calendar-crm-adapters (first `requires_approval=True` tools), group-management (Supabase orgs/memberships/roles + invites), mac-packaging (installer/menubar wrapper around `runnrr up`), cloud-provisioning (one container per customer on the VPS; the old Caddyfile's Sidekick blocks are prior art), model-config-file (`models.json` replacing the dict + pricing), docker-sandbox (swap `workspace._spawn()`), evals-generalization (tool-trajectory datasets), rag-over-workspace, developer-cli (`runnrr chat` REPL, in-process, for debugging only).

## Reuse map

- `kb_loader._safe_resolve(rel, root=)` — the jail for every workspace tool; already root-parameterized and symlink-safe.
- `kb_loader.list_kb` / `read_file` slicing — reused by `list_files` / workspace `read_file`.
- `tools/definitions.ToolDef` + `registry.TOOL_DEFS` — new tools are just more records; all three `tools_for_provider` derive from it.
- `dispatch.run_tool` — the one place for the output cap, approval interception, and `workspace` threading.
- `skills.py` — invoice-intake procedure ships as a `SKILL.md`, loaded via `read_skill` (tool result, never a prompt rewrite).
- PR #2 `backend/auth.py` — Supabase JWT verification, copied verbatim.
- `docs/prs/*.md` on the 8 draft branches — designs for Phase 3 and the roadmap.
- `profiles/research-analyst/evals/smoke.json` — shape for invoice-clerk's trajectory cases.

## Risks

- **Rename sed**: the embedding "backend" sense and `history.md`; logger-name pins in 11 tests; editable venv path. Rebuild the venv after the directory move.
- **Sequencing**: 1b before 1c; 3a before 3b/3c. Every phase edits `app.py`, `config.py`, CLAUDE.md, so never run two in parallel.
- **Usability check per phase**: any new capability must be reachable from the UI or the settings screen, not only from a terminal or `.env`. If a phase adds a knob only developers can turn, it goes in `.env.example` with a comment and the user-facing path is a roadmap line.
- **Prefix cache**: workspace schemas static; invoice-clerk `system.md` carries no dates/paths; approvals and resets are appends/epoch bumps; extend `test_prefix_is_byte_stable`.
- **Import cycles**: `store.py` imports only `config`; `instrument.py` imports `store/budget/pricing/usage`, never `app`.
- **`run_command`**: `shell=True` children need `start_new_session` + `killpg`; Unix only.
- **bryanzane.com**: only safe once `/opt/easyagent` is pinned to the tag and removed from the VPS dispatcher (Phase 0 step 1).
- **Memory**: after leaving plan mode, save two memories: the reversed `saas-control-plane` decision (single-tenant runtime, Supabase Auth only, PRs closed) and the owner's standing constraint that cost effectiveness and usability for non-technical people gate every design choice.

## Verification (end to end, after Phase 4)

1. `pytest -q` green on every phase; no `easyagent`/`bryanzane`/`gemini`/`builder` grep hits.
2. `uvicorn runnrr.app:app --port 8001` with `RUNNRR_AUTH_DISABLED=1`; `POST /api/chat` with a Supabase test JWT works, without one → 401.
3. Invoice slice: copy samples into `workspace/invoice-clerk/inbox/`, send "Process the inbox", confirm `ledger.csv` rows and the duplicate flagged in `anomalies.md`; hop-2 `usage` shows cache reads.
4. Kill uvicorn mid-conversation, restart, same `session_id` continues; `sqlite3 data/runnrr.sqlite3 'select kind,count(*) from audit group by 1'` shows rows.
5. Fresh checkout with no `.env`: `runnrr up` opens the browser, the settings screen accepts a DeepSeek key, an invoice PDF uploaded through the UI is processed without touching a terminal, and the turn's `cost_usd` is non-null.
