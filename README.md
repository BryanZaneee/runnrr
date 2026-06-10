# EasyAgent

EasyAgent is a portable framework for building reusable agentic AI apps across different model providers. Define an agent profile, give it a focused local knowledge base and toolset, then run it through Claude, OpenAI, Gemini, Kimi, or DeepSeek without rewriting the workflow each time.

The engine is provider-agnostic and business-agnostic: profiles, knowledge bases, providers, and tools are separated so the same loop can power a personal-site agent, a customer-support bot, a sales assistant, or an internal-ops agent. Keys stay server-side; browsers talk to the FastAPI backend over SSE and never see provider credentials.

## Bundled profiles

- [`profiles/personal-agent/`](./profiles/personal-agent/) — showcase personal-site candidate/resume agent (default). KB + semantic RAG + web search.
- [`profiles/customer-service/`](./profiles/customer-service/) — tier-1 in-widget support agent for a fictional coffee shop, with a self-contained KB and an adaptation `TEMPLATE.md`.
- [`profiles/research-analyst/`](./profiles/research-analyst/) — public research with web search, safe page fetching, and a calculator.
- [`profiles/sales-concierge/`](./profiles/sales-concierge/) — catalog lookup, lead qualification, and preview-only lead/checkout flows.
- [`profiles/frampton/`](./profiles/frampton/) — Dark Souls 1 guide grounded in a public Fextralife scrape committed at `kb/frampton/`.

A sibling [`profiles-advanced/`](./profiles-advanced/) folder is reserved for tier-2 multi-channel/multi-tenant agents (WhatsApp, Instagram, Gmail, Google Business). It sits outside `profiles/` so the loader does not pick it up.

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

## Forward-looking ideas

- MCP runtime execution for CRM, calendar, Drive, Notion, Stripe, and browser tools.
- Durable conversation storage with human handoff.
- Multi-tenant business profiles with per-tenant budgets and channel adapters (WhatsApp, Instagram, Gmail, Google Business).
- Observability traces for tool calls, latency, token cost, and retrieval quality.
- Live Stripe Checkout and CRM lead capture behind explicit production credentials.

## License

MIT
