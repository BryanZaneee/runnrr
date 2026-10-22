# Project guide

[Back to the README](../README.md).

## Bundled agents

| Profile | Purpose |
| --- | --- |
| `personal-agent` | Candidate/resume assistant using a local knowledge base; current default |
| `customer-service` | Coffee-shop support example with a bundled knowledge base |
| `research-analyst` | Public research, page fetching, and calculations |
| `sales-concierge` | Catalog lookup, lead qualification, and checkout previews |
| `bzs-concierge` | Workflow-consulting discovery and lead previews |
| `frampton` | Dark Souls guide using bundled public wiki material |

Profiles gate which tools an agent can use. Sales tools are previews: they do
not persist leads to a CRM or charge customers. New business profiles can be
added without changing the engine.

The workstation picker intentionally omits `sales-concierge` and
`bzs-concierge`; both remain loadable by ID for their APIs and evaluations.
Their catalog and preview tools are active code, not abandoned integrations.
`research-analyst` uses web tools and does not require a bundled `kb/` folder;
`sales-concierge` reads its `data/catalog.json` instead. Missing local knowledge
for `personal-agent` is a setup concern, not a missing profile.

## Add an agent

Create `profiles/<id>/profile.json` and a `system.md` prompt. For example:

```json
{
  "id": "my-agent",
  "label": "My Agent",
  "description": "Answers questions about our business",
  "kb_root": "kb/my-agent",
  "system_prompt_path": "profiles/my-agent/system.md",
  "tools": ["list_kb", "read_file", "search_kb"]
}
```

Plain-English procedures live at `profiles/<id>/skills/<slug>/SKILL.md`, with
`name` and `description` frontmatter. Their bodies are loaded as tool results,
keeping the model's system prompt stable for caching. MCP configuration is
parsed but no MCP client connects yet.

## Knowledge and evaluations

Semantic retrieval is opt-in through the `semantic_search_kb` tool. Build a
profile index explicitly after changing its knowledge base:

```bash
.venv/bin/python -m runnrr.rag.cli build customer-service
.venv/bin/python -m runnrr.rag.cli info customer-service
.venv/bin/python -m runnrr.rag.cli query customer-service "opening hours" --k 3
```

For the bundled Dark Souls project, build its own index:

```bash
.venv/bin/python -m runnrr.rag.cli build frampton
```

Voyage embeddings require `VOYAGE_API_KEY` and a reviewed embedding cost bound.
The local backend is also supported with the optional `rag-local` dependencies;
configure the same backend and model when building and serving. Do not use the
fake test backend for a semantic-search demonstration. Until an index is built,
Frampton can search local text and read source pages, but semantic search reports
that the index is missing. `TAVILY_API_KEY` and a search cost bound enable the
optional web fallback. Tests use deterministic fixtures.
Indexes live under `profiles/<id>/.index/` and are ignored by Git. Chat never
rebuilds an index automatically; restart the runtime after rebuilding.

```bash
.venv/bin/python -m runnrr.evals.cli --backend fake run customer-service \
  --mode retrieval-only --variants keyword,hybrid --k 5
.venv/bin/python -m runnrr.evals.cli list customer-service
```

Evaluation datasets live with profiles and outputs are ignored under
`profiles/<id>/evals/runs/`. `ENABLE_EVALS_API=1` enables the read-only eval endpoints.
