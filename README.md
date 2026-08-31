# EasyAgent

EasyAgent is a portable framework for building reusable agentic AI apps across different model providers. Define an agent profile, give it a focused local knowledge base and toolset, then run it through Claude, OpenAI, Gemini, Kimi, or DeepSeek without rewriting the workflow each time.

**Product: Runnrr.** EasyAgent is the internal engine name; [Runnrr](#runnrr-engine-map) is the BZS Software product that runs on it — AI integration for small and mid-size businesses (inbox, support, invoices, 24/7 inbound calls/SMS). Buyers see Runnrr; this repo and its Python package stay `easyagent`.

The engine is provider-agnostic and business-agnostic: profiles, knowledge bases, providers, and tools are separated so the same loop can power a personal-site agent, a customer-support bot, a sales assistant, or an internal-ops agent. Keys stay server-side; browsers talk to the FastAPI backend over SSE and never see provider credentials.

## Bundled profiles

- [`profiles/personal-agent/`](./profiles/personal-agent/) — showcase personal-site candidate/resume agent (default). KB + semantic RAG + web search.
- [`profiles/customer-service/`](./profiles/customer-service/) — tier-1 in-widget support agent for a fictional coffee shop, with a self-contained KB and an adaptation `TEMPLATE.md`.
- [`profiles/research-analyst/`](./profiles/research-analyst/) — public research with web search, safe page fetching, and a calculator.
- [`profiles/sales-concierge/`](./profiles/sales-concierge/) — catalog lookup, lead qualification, and preview-only lead/checkout flows.
- [`profiles/bzs-concierge/`](./profiles/bzs-concierge/) — public concierge demo for bzssoftware.com: catalog-backed discovery, lead qualification, and preview-only lead capture (no checkout tool).
- [`profiles/frampton/`](./profiles/frampton/) — Dark Souls 1 guide grounded in a public Fextralife scrape committed at `kb/frampton/`.

Multi-channel/multi-tenant agents (WhatsApp, Instagram, Gmail, Google Business, Twilio SMS/voice) are **out of engine scope today**. When built, channel adapters will sit *outside* the agent loop and call the same `POST /api/chat` — not a second harness. See the [engine map](#runnrr-engine-map) and the prepared `feat/channel-webhooks` / `feat/channel-voice` branches.

## Runnrr engine map

How the product decomposes onto this repo, and the rules that follow from it.

### Architecture one-pager

```
                 ┌──────────────────────────────────────────┐
                 │ Control plane (future: tenants, auth,     │
                 │ usage, dashboard — stacked PRs #1–#3)     │
                 └───────────────┬──────────────────────────┘
                                 │ profile_id, tenant_id, budget
 Channel adapters                ▼
 (SMS / voice — future) ──▶  POST /api/chat  ──▶  EasyAgent loop  ──▶  providers
 Twilio webhooks, TwiML          SSE           backend/agent.py       Anthropic / OpenAI /
 STT ⇄ TTS                                     profiles + tool         Gemini / Kimi / DeepSeek
                                               allowlists + KB/RAG
```

- **One agent, one job, one tool pack.** A profile is a scoped persona with a tool allowlist. Voice and SMS profiles get a *tiny* pack (see recipe below), never the kitchen sink.
- **Channel adapters are not a second harness.** A Twilio SMS webhook maps `From/To/Body` onto `/api/chat` with a durable session key and returns TwiML. Voice is STT → the same endpoint → TTS. Nothing about the loop changes per channel.
- **Decision (made): no vendored harness for client traffic.** DeepSeek Harness, Hermes, and OpenClaw are not vendored into this repo. We steal the ideas — append-only transcripts so the provider prefix cache hits, one agent / one job / one tool pack — and keep client chat = this engine + a model API. DeepSeek Harness stays optional for internal Runnrr staff later, never on a customer's phone line.

### What Runnrr sells (and doesn't)

Sells: scoped profiles, tool allowlists, RAG over a business's own documents, evals, human-in-the-loop actions ("AI drafts, people send"), enterprise model APIs (not personal ChatGPT accounts), and 24/7 inbound calls/SMS later. Does **not** sell fully autonomous employees, "#1 on Google" SEO, or outbound AI voice (TCPA).

### HAVE / NOT YET

| Capability | Status | Where |
| --- | --- | --- |
| Multi-provider loop (Anthropic, OpenAI, Gemini, Kimi, DeepSeek) | HAVE | `backend/agent.py`, `backend/providers/` |
| Profiles + tool allowlists + `system.md` + KB | HAVE | `profiles/`, `backend/profiles.py`, `backend/tools/` |
| RAG (hybrid BM25 + dense, optional rerank) + evals | HAVE | `backend/rag/`, `backend/evals/` |
| Prefix / prompt caching, `cache_control` on Anthropic | HAVE | PR #9 |
| Honest token, cost, and budget accounting | HAVE | PR #4, `backend/usage.py`, `backend/pricing.py` |
| Markdown skills (`SKILL.md`, progressive disclosure) | HAVE | PR #6, `backend/skills.py` |
| Model capability declaration (fail loud) | HAVE | PR #7, `MODEL_REGISTRY` |
| FastAPI + SSE, server-side keys, rate limits, daily budget | HAVE | `backend/app.py` |
| Local builder (`ENABLE_PROFILE_EDITOR`) + operator dashboard | HAVE | `backend/builder.py`, `web/` |
| Sales concierge tools | HAVE (preview only — no real CRM/Stripe) | `backend/tools/sales.py` |
| Multi-tenant control plane (agents, usage, auth, dashboard) | NOT YET — open stacked PRs #1 → #2 → #3 | see below |
| Durable sessions (survive restart, keyed by profile/tenant) | NOT YET | `feat/durable-sessions` |
| Audit log + per-agent kill switch | NOT YET | `feat/audit-log-kill-switch` |
| HITL actions (`requires_approval` tools, approvals API) | NOT YET | `feat/hitl-actions` |
| Inbound SMS webhook (Twilio) | NOT YET | `feat/channel-webhooks` |
| Inbound voice (Twilio Media Streams, STT/TTS) | NOT YET | `feat/channel-voice` |
| Real calendar + CRM adapters (per-tenant OAuth, HITL on) | NOT YET | `feat/calendar-crm-adapters` |
| MCP runtime for `mcp_servers` already declared in profiles | NOT YET | `feat/mcp-runtime` |
| DLP redaction before provider calls; "do not embed" RAG label | NOT YET | `feat/dlp-redact` |
| Live Stripe | NOT YET — last, optional | `feat/stripe-live` (not started) |

Each NOT YET row has a draft PR whose body is `docs/prs/<branch>.md` — problem, design, API sketch, tests to write, out-of-scope, dependencies — plus skipped contract tests. They are scaffolds, not implementations.

### Stacked SaaS PRs (open — do not merge from here)

The control plane is three open, stacked PRs. They are intentionally left open and must not be merged, rebased, or squashed as part of any docs change:

1. [#1 `refactor/profile-from-config`](https://github.com/BryanZaneee/easyagent/pull/1) — extract `profile_from_config` (base was `refactor/tools-rag-evals-split`).
2. [#2 `feat/saas-auth-db-endpoints`](https://github.com/BryanZaneee/easyagent/pull/2) — per-tenant agents, usage, optional auth.
3. [#3 `feat/saas-dashboard-ui`](https://github.com/BryanZaneee/easyagent/pull/3) — authed dashboard.

### Prefix-cache rules for contributors

The prompt prefix is cached per session ([PR #9](https://github.com/BryanZaneee/easyagent/pull/9)). Every provider benefits when the prefix is byte-stable; Anthropic additionally gets explicit `cache_control` breakpoints. To keep hits high:

- **Append-only messages.** Never rewrite, reorder, or drop earlier turns. Compaction, if ever added, is a new prefix — not an in-place edit.
- **Freeze the system prompt and tool schemas for the session.** Switching profile or model already resets the session; don't mutate either mid-conversation. Skill bodies arrive as tool results, never as a system-prompt rewrite.
- **Inject volatile data after the cached prefix.** Current time, caller id, channel metadata, and per-turn context go in the user turn (or a trailing block), never in the system prompt.
- **Don't "clean" history.** A bad tool result stays where it is; append a correction turn instead of editing the transcript.

### Profile recipe: inbound SMS / voice

A future `inbound-sms` or `inbound-voice` profile is deliberately small:

```json
{
  "id": "inbound-sms",
  "label": "Front Desk (SMS)",
  "kb_root": "kb/<tenant>-faq",
  "system_prompt_path": "profiles/inbound-sms/system.md",
  "tools": ["search_kb", "read_file", "book_appointment", "crm_note", "transfer_to_human"]
}
```

- Tiny tool pack: FAQ (KB read/search), book, note, transfer-to-human. Anything that sends, exports, or deletes is `requires_approval` (HITL).
- **No** shell, **no** MCP, **no** browser, **no** `web_search`. These profiles run on a customer's phone number; the blast radius must stay small.
- Volatile caller data (number, time, channel) is injected per turn, not into `system.md` (see cache rules).

## Quick start

```bash
# Python 3.11–3.13 (voyageai does not support 3.14+). `.python-version` pins 3.13.
uv venv --python 3.13
uv pip install -e ".[dev,rag]"
cp .env.example .env
```

Set one or more provider keys in `.env` (all stay server-side):

```bash
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GEMINI_API_KEY=...
MOONSHOT_API_KEY=...
DEEPSEEK_API_KEY=...
TAVILY_API_KEY=...   # optional; needed for web_search / Research Analyst
```

Run the backend, then (optionally) the local dashboard:

```bash
.venv/bin/python -m uvicorn backend.app:app --reload --port 8001
.venv/bin/python -m http.server 8000 --directory web
```

Visit `http://localhost:8000` for the dashboard (it defaults to `http://127.0.0.1:8001` for API calls). The public chat UI lives in the separate [`bryanzane_v3`](https://github.com/BryanZaneee/bryanzane_v3) repo under `easyagent/`, deployed at [bryanzane.com/easyagent](https://bryanzane.com/easyagent/).

## Agent Builder (local)

A no-code page for creating and configuring an agent, then trying it immediately in a chat pane. Gated by `ENABLE_PROFILE_EDITOR` (default off) so the write API has no surface in production.

```bash
echo "ENABLE_PROFILE_EDITOR=1" >> .env
.venv/bin/python -m uvicorn backend.app:app --reload --port 8001
.venv/bin/python -m http.server 8000 --directory web
```

Open `http://localhost:8000/builder/`. Agents you create there are written under `profiles/<id>/` and can only be edited by the builder that made them — bundled example profiles stay read-only. Keep `ENABLE_PROFILE_EDITOR` unset (or `0`) in production.

## Usability guide

### Pick a profile

Set `DEFAULT_PROFILE=<id>` in `.env`, or pass `?profile_id=<id>` to the API per request. Switching profile or model mid-session resets the conversation.

### Technical dashboard (`web/`)

A no-build vanilla page for runtime health: provider/key status, available models, daily token budget, active sessions, and per-profile RAG index status. It is a read-only operator view, not the chat UI. It reads the aggregate `/api/status`; external clients should prefer the focused `/api/health`, `/api/budget`, `/api/models`, `/api/profile`, and `/api/rag/index` endpoints.

### Semantic RAG

`semantic_search_kb` is additive to `search_kb` (literal keyword/regex) and only appears for profiles that list it in `profile.json`. Build and query a profile index with the CLI:

```bash
# Build (Voyage embeddings). Free tier without a payment method: EASYAGENT_EMBED_BATCH_SIZE=8
VOYAGE_API_KEY=... EASYAGENT_EMBEDDING_BACKEND=voyage \
  .venv/bin/python -m backend.rag.cli build personal-agent
.venv/bin/python -m backend.rag.cli info personal-agent
.venv/bin/python -m backend.rag.cli query personal-agent "portable profile retrieval" --k 3

# Model-free local fixtures / CI use the deterministic fake backend:
.venv/bin/python -m backend.rag.cli --backend fake build customer-service
```

Indexes live under `profiles/<id>/.index/` (git-ignored); set `EASYAGENT_RAG_INDEX_ROOT=/path` to relocate. Retrieval is hybrid BM25 + dense vectors fused with RRF; set `EASYAGENT_RERANK=1` to enable the optional LLM reranker. **Rebuild after any KB change** — chat boot only warns on a stale index, it never rebuilds in the request path. A long-running dev server caches the manifest and retriever, so restart it after rebuilding.

### Evals

Measure retrieval and answer quality before shipping prompt, tool, or retrieval changes. Datasets live at `profiles/<id>/evals/rag.json`.

```bash
# Retrieval-only quality (no model keys needed with --backend fake)
.venv/bin/python -m backend.evals.cli --backend fake run personal-agent \
  --mode retrieval-only --variants keyword,hybrid,hybrid_rerank --k 5

.venv/bin/python -m backend.evals.cli list personal-agent
.venv/bin/python -m backend.evals.cli compare personal-agent \
  --latest --baseline keyword --candidate hybrid
.venv/bin/python -m backend.evals.cli report personal-agent --latest
```

Runs persist under `profiles/<id>/evals/runs/<run_id>/` as `records.jsonl` + `summary.json`. Metrics include `recall_at_k`, `context_precision`, `reciprocal_rank` (MRR), and—on end-to-end runs—`faithfulness`, `answer_relevance`, and `answer_vs_ground_truth`.

To browse runs visually, open the eval dashboard at `web/evals/` and set `ENABLE_EVALS_API=1` so the backend exposes the read-only `/api/evals/runs/{profile}`, `/api/evals/run/{profile}/{run_id}`, and `/api/evals/index-status/{profile}` endpoints.

The Research Analyst and Sales Concierge profiles also ship tool-sequencing smoke datasets at `profiles/<id>/evals/smoke.json`. Keep both dataset kinds close to the profile prompts and update them when behavior changes.

## Adding a profile

Create `profiles/<id>/` with a `profile.json` and a `system.md` prompt — no git branches or engine edits required:

```json
{
  "id": "my-agent",
  "label": "My Custom Agent",
  "kb_root": "kb/my-agent-kb",
  "system_prompt_path": "profiles/my-agent/system.md",
  "tools": ["list_kb", "read_file", "search_kb"],
  "brand": { "accent": "#386f3d", "intro_ascii_name": "My Agent" }
}
```

To activate it, set `DEFAULT_PROFILE=my-agent` and restart, or pass `?profile_id=my-agent`. Profiles fail-fast on unknown tool names. Optional `profile.json` keys:

- `tool_descriptions` — profile-specific wording for a shared tool.
- `source_path_labels` — ordered `[match, label]` pairs mapping KB paths to public source labels in the UI (trailing `/` matches by prefix, else exact; first match wins), e.g. `[["menu/", "Menu"], ["policies/", "Store policy"]]`.
- `mcp_servers` — standard MCP stdio configs. Parsed and shown in the agent-info panel today; full MCP client execution is a follow-up.

Native tools live in `backend/tools/` and `backend/rag/tools.py`. Each is a `ToolDef` pairing its schema, handler, and browser-safe source metadata; profiles only see the tools they list. Use native tools for small, stable server-owned capabilities (KB reads, web search, URL fetch, calculator, catalog/lead/checkout previews). The Sales Concierge tools are intentionally safe demos — `lead_capture_preview` does not persist to a CRM and `checkout_link_preview` does not touch Stripe.

## Privacy boundary

This public repo does **not** include the personal knowledge base, resume files, codebase dumps, API keys, or deployment secrets for the personal site. The `kb/` directory is git-ignored; create your own local KB matching a profile's `kb_root` (e.g. `kb/resume/`, `kb/projects/`). Tests run against `tests/fixtures/mini_kb/`, so the framework develops and verifies without private data. The exception is `kb/frampton/`, public Fextralife content that ships in-repo so its profile travels with every deploy.

## More detail

- [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) — standing rules and a one-screen architecture tour for contributors and agents.
- [`history.md`](history.md) — dated decision log (what was chosen and what was rejected), including the June 2026 RAG + eval roadmap.
- [`docs/sales_pitch.md`](docs/sales_pitch.md) — BZS Software pitch, discovery questions, and demo runbooks for business workflow conversations.
- [`docs/agent_best_practices.md`](docs/agent_best_practices.md) — checklist for API boundaries, model selection, prompts, tools, streaming, retrieval, and evals.

## Roadmap

The forward-looking work is tracked as prepared branches, one concern each — see the [HAVE / NOT YET table](#have--not-yet) for the full list and `docs/prs/` for each design. In rough dependency order: durable sessions → audit log + kill switch → HITL actions → SMS webhook → voice → calendar/CRM adapters → MCP runtime → DLP redaction → (last, optional) live Stripe. Multi-tenant budgets and auth come from the stacked PRs #1–#3. Observability traces for tool calls, latency, cost, and retrieval quality remain an unscheduled idea.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

[`CONTRIBUTING.md`](CONTRIBUTING.md) is the source of truth for branch naming, commit format, and the PR flow. Two repo-specific rules on top of it:

- `.venv/bin/python -m pytest -v` must pass before you open a PR, and behavioral changes need tests.
- Never commit `kb/` content (except the tracked `kb/frampton/` scrape), `.env` files, or provider keys — see [Privacy boundary](#privacy-boundary) above.

## License

[MIT](LICENSE)
