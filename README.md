# EasyAgent

EasyAgent is a portable framework for building reusable agentic AI apps across different model providers.

The goal is simple: define an agent profile, give it a focused local knowledge base and toolset, then run it through Claude, OpenAI, Gemini, Kimi, or DeepSeek without rewriting the workflow each time.

Bundled profiles:

- `profiles/personal-agent/` — the showcase personal-site profile for Bryan's candidate/resume agent.
- `profiles/customer-service/` — a tier-1 in-widget customer-service agent for a fictional coffee shop, with realistic KB content and an adaptation `TEMPLATE.md`.
- `profiles/research-analyst/` — a public research profile with web search, safe page fetching, and deterministic calculations.
- `profiles/sales-concierge/` — an EasyAgent sales profile with catalog lookup, lead qualification, and preview-only lead/checkout flows.
- `profiles/frampton/` — a Dark Souls 1 guide profile that expects a local categorized wiki scrape mounted at `kb/frampton`.

The bundled `web/` app is a **local technical dashboard** (health, budget, limits, models, profiles, and per-profile RAG-index status) — not the production chat UI. The dashboard uses `/api/status` as a local aggregate; external clients should prefer the focused `/api/health`, `/api/budget`, `/api/models`, `/api/profile`, and `/api/rag/index` endpoints. The public chat experience lives in the separate `bryanzane_v3/easyagent/` app and talks to this backend over SSE.

A sibling top-level folder, [`profiles-advanced/`](./profiles-advanced/), is reserved for tier-2 multi-channel/multi-tenant agents (WhatsApp, Instagram, Gmail, Google Business). It is intentionally outside `profiles/` so the in-widget loader does not pick it up — see its README for details.

## Why I Made It

EasyAgent is built around portability and usability. Profiles, knowledge bases, model providers, and tools are separated so the same engine can be reused for different professional workflows, like a social media video manager, customer support bot, sales assistant, internal operations agent, or personal site agent.

I use it personally on my site (Personal Agent profile), but the framework is meant to move anywhere.

## What It Does

- Runs a streaming FastAPI/SSE agent backend with a vanilla technical dashboard
- Supports Claude, OpenAI, Gemini, Kimi, and DeepSeek through one provider interface
- Keeps API keys on the server, never in the browser
- Uses profile-specific prompts, KB roots, and tool allowlists
- Reads/searches local knowledge bases instead of relying on model memory
- Adds optional profile-scoped semantic RAG through `semantic_search_kb`,
  with `search_kb` preserved for literal keyword and regex lookup
- Supports native non-KB tools, such as public URL fetches, calculators, catalog lookup, lead qualification, and preview-only checkout links
- Preserves provider-specific protocol details, such as DeepSeek thinking-mode `reasoning_content`, inside the server only
- Adds production guardrails: per-IP chat rate limits, daily token budget tracking, active-session caps, and structured JSON logs
- Keeps the core agent loop small enough to understand and change

## Capabilities

- Multi-profile agents with profile prompts, KB roots, tool allowlists, and brand metadata
- Streaming FastAPI/SSE chat backend with a no-build vanilla technical dashboard (`web/`)
- Provider adapters for Claude, OpenAI, Gemini, Kimi, and DeepSeek
- Local KB tools plus web search, URL fetch, calculator, catalog, lead, and checkout-preview tools
- Server-owned API keys, rate limits, token budgets, session caps, and structured logs
- Profile smoke datasets for tool-heavy agents
- Optional RAG indexes with BM25 + sqlite-vec retrieval, deterministic fake
  embeddings for tests, and Voyage/local embedding providers for live use

## June 2026 Roadmap

This roadmap is a working June plan, not a hard release contract. The goal is to strengthen EasyAgent's foundation while keeping it a focused single-widget framework; multi-tenant and multi-channel work stays forward-looking for now.

- **Week 1: Foundation cleanup** — make RAG optional, lazy-load `sqlite-vec`, unify indexes around `Chunk`, harden manifest/BM25 behavior, and keep `history.md` current.
- **Week 2: Tool architecture cleanup** — split large native tool code into focused modules, introduce registry-backed `ToolDef` records, and keep `backend/tools/` as stable dispatch/schema glue.
- **Week 3: RAG integration** — continue hardening `semantic_search_kb` beside `search_kb`, build per-profile indexes, expose an index CLI, and keep keyword search as the baseline.
- **Week 4: Eval + docs** — add a smoke-eval CLI, paired keyword-vs-hybrid RAG reports, CI coverage, and profile onboarding docs.

### Implementation Direction

- **Keep semantic RAG opt-in and measured.** The current slice validates optional vector storage, `Chunk`-shaped retrieval internals, and profile-level tool exposure. The next step is eval reporting that compares `search_kb` and `semantic_search_kb` on the same profile questions.
- **Refactor RAG storage around `Chunk`.** One canonical retrieval type prevents `heading_path` list/tuple drift and keeps retriever, eval, and tool output behavior predictable. This improves hybrid retrieval, eval wiring, and incremental indexing.
- **Add lightweight tool architecture boundaries.** Business-specific tools will keep growing, so each native tool keeps its schema, handler, and source metadata in a domain-owned `ToolDef` while `backend/tools/` stays as dispatch/schema glue. This makes custom support, sales, research, and future MCP-backed workflows easier to add.
- **Add an eval-first workflow.** Business agents need regression checks before prompt, tool, or retrieval changes ship. Profile smoke tests and paired no-RAG/RAG reports make quality improvements visible instead of anecdotal.

## Adding Agent Profiles

Adding a new agent profile is straightforward and does not require git branches. The framework is designed to swap agents easily by adding a new folder under `profiles/`:

1. **Create a directory:** `profiles/my-agent/`
2. **Add `profile.json`:** Define the agent's identity, KB root, and tools:
   ```json
   {
     "id": "my-agent",
     "label": "My Custom Agent",
     "kb_root": "kb/my-agent-kb",
     "data_root": "profiles/my-agent/data",
     "system_prompt_path": "profiles/my-agent/system.md",
     "tools": ["list_kb", "read_file", "search_kb"],
     "brand": {
       "accent": "#386f3d",
       "accent_dark": "#1f4d28",
       "accent_soft": "#e8f3e6",
       "hero_icon": "(..)",
       "intro_ascii_name": "My Agent",
       "input_placeholder": "ask My Agent..."
     }
   }
   ```
3. **Add `system.md`:** Write the system prompt defining the agent's persona.

Optional source-attribution config in `profile.json`: `source_path_labels` is an ordered list of `[match, label]` pairs that maps KB paths to public source labels shown in the UI (a trailing `/` matches by prefix, otherwise exact path; first match wins). For example `[["menu/", "Menu"], ["policies/", "Store policy"]]`. The engine ships no business-specific label rules, so this is how a profile names its own sources without touching engine code.

To use the new profile, change `DEFAULT_PROFILE=my-agent` in your `.env` file and restart the server, or pass `?profile_id=my-agent` to the API.

`profile.json` also accepts an `mcp_servers` array — each entry mirrors the standard MCP stdio config (`name`, `command`, `args`, `env`). The schema is parsed and shown in the agent-info panel today; full MCP client integration is a follow-up task.

### Native tools vs. MCP tools

Native tools live in `backend/tools/` and `backend/rag/tools.py`. Each tool is authored as a `ToolDef` that pairs its Anthropic-shaped schema with its handler and browser-safe source metadata. Provider adapters read schemas derived from the registry, `run_tool` dispatches through the same registry, and profiles expose only the tools listed in `profile.json`. A profile can also override tool descriptions with `tool_descriptions` when a shared tool needs profile-specific wording.

Use native tools for small, stable server-owned capabilities that should be easy to test in this repo: KB reads, Tavily web search, public URL fetches, deterministic calculators, catalog lookups, lead qualification, and preview-only checkout links.

Use `mcp_servers` for future tool surfaces that should come from an external MCP server, such as calendar, CRM, Drive, Notion, Stripe, or browser automation. The profile schema already stores those server declarations, but the EasyAgent runtime does not connect to MCP servers yet.

The Sales Concierge profile intentionally uses safe demo tools. `lead_capture_preview` does not persist to a CRM, and `checkout_link_preview` does not import Stripe or create a live Checkout Session. A production Stripe integration should use server-side credentials and Stripe Checkout Sessions with Prices.

The Research Analyst and Sales Concierge profiles also ship small smoke datasets under `profiles/<id>/evals/smoke.json`. Keep those close to the profile prompts and update them whenever tool sequencing, prompt structure, or output expectations change.

## Privacy Boundary

This public repo intentionally does **not** include my personal knowledge base, resume files, private codebase XML dumps, API keys, or deployment secrets found for my personal site.

The `kb/` directory is ignored by git. To run a real profile, create your own local KB that matches the profile's `kb_root`:

```text
kb/
  resume/
  projects/
  codebases/
  meta/
```

Tests use `tests/fixtures/mini_kb/`, so the framework can be developed and verified without committing private data.

The Frampton profile is the exception: its Dark Souls 1 wiki scrape is public Fextralife content, so it ships in-repo at `kb/frampton/` and travels with the code on every deploy.

## Run It

```bash
# Python 3.11–3.13 (voyageai does not support 3.14+). `.python-version` pins 3.13.
uv venv --python 3.13
uv pip install -e ".[dev,rag]"
cp .env.example .env
```

Set one or more API keys in `.env`:

```bash
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GEMINI_API_KEY=...
MOONSHOT_API_KEY=...
DEEPSEEK_API_KEY=...
TAVILY_API_KEY=...  # optional; needed for web_search / Research Analyst
```

All keys stay server-side. Browser clients call the FastAPI server over SSE; they never receive provider credentials.

### Optional Semantic RAG

`semantic_search_kb` is additive to `search_kb` and only appears for profiles
that list it in `profile.json`. To build or query a profile RAG index, install
the optional RAG extra and run the CLI:

```bash
VOYAGE_API_KEY=... EASYAGENT_EMBEDDING_BACKEND=voyage \
  .venv/bin/python -m backend.rag.cli build personal-agent
# Voyage free tier (no payment method): EASYAGENT_EMBED_BATCH_SIZE=8
.venv/bin/python -m backend.rag.cli query personal-agent "portable profile retrieval" --k 3
```

For model-free smoke tests or local fixtures, use the deterministic fake
embedding backend:

```bash
.venv/bin/python -m backend.rag.cli --backend fake build customer-service
```

Indexes live under `profiles/<id>/.index/` by default and are ignored by git.
Set `EASYAGENT_RAG_INDEX_ROOT=/path/to/indexes` to keep them elsewhere.

Start the backend:

```bash
.venv/bin/python -m uvicorn backend.app:app --reload --port 8001
```

Open the local **technical dashboard** (read-only runtime view — profiles, models, budget, RAG index health):

```bash
.venv/bin/python -m http.server 8000 --directory web
```

Then visit `http://localhost:8000`. The dashboard defaults to `http://127.0.0.1:8001` for API calls.

The public chat UI lives in the separate [`bryanzane_v3`](https://github.com/BryanZaneee/bryanzane_v3) repo under `easyagent/` and is deployed at [bryanzane.com/easyagent](https://bryanzane.com/easyagent/).

## Forward-Looking Ideas

- MCP runtime execution for CRM, calendar, Drive, Notion, Stripe, and browser tools
- Durable conversation storage with human handoff
- Multi-tenant business profiles with per-tenant budgets and settings
- Channel adapters for WhatsApp, Instagram DMs, Gmail, and Google Business
- Admin dashboard for profile health, usage, evals, and failed conversations
- Observability traces for tool calls, latency, token cost, and retrieval quality
- Live Stripe Checkout and CRM lead capture behind explicit production credentials
- Voice/realtime agent mode as a separate product track
- Fine-tuning or preference-tuning from approved EasyAgent traces
- Profile marketplace/templates for common business agent types

## License

MIT
