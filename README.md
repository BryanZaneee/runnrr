# Runnrr

A self-hosted control surface for agents doing work beyond coding: customer
support, research, and other business workflows.
Runnrr brings threads, project context, tool activity, and usage into one workstation.
The current runtime calls provider APIs; installed CLI agents and subscription
harnesses are a future integration.
Choose an agent, give it a task, and follow its response and tool activity in one place.

![Runnrr thread workspace](docs/screenshots/workstation-local.webp)

*The local Runnrr workstation. The separate [EasyAgent showcase](https://bryanzane.com/easyagent/) retains its older interface.*

Regenerate: `npm ci && npx playwright install chromium && npm run capture`
(Node.js and `cwebp` required; start the local runtime first).

Runnrr currently supports live streaming chat, configured agent profiles,
read-only knowledge tools, skills, web research, and usage accounting. The web
workstation is served by the runtime itself. Conversations, pins, and drafts
are temporary and clear when the page reloads; server restarts or inactivity
can reset conversation context too.

## Quick start

Run from a source checkout: the Python wheel alone does not include the web
workstation or bundled profiles.

Python 3.13 is pinned in
`.python-version` (supported range: 3.11–3.13).

```bash
uv sync --frozen --extra dev --extra rag
cp .env.example .env
```

Add a provider key to `.env` and choose its model with `DEFAULT_MODEL`.
Configure `DEMO_REQUEST_COST_BOUNDS` with reviewed maximum costs per provider
attempt (in microdollars, including full input/output limits). Its empty default
intentionally blocks paid requests. The runtime reserves those bounds against
a $0.50 daily allocation; do not substitute estimated average prices.
Use `DEFAULT_PROFILE=customer-service` for a bundled, self-contained KB.
Supported provider keys include `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`, and `GEMINI_API_KEY`.
Keys stay on the server. `TAVILY_API_KEY` enables web search.

```bash
.venv/bin/python -m uvicorn runnrr.app:app --host 127.0.0.1 --port 8001
```

Open **http://127.0.0.1:8001**. No frontend build or separate web server is required.
After frontend edits, reload the page. Add `--reload` for backend development.

## Workstation

- **Threads:** compact sidebar with search, rename, pins, snooze, settle,
  restore, and deletion with immediate undo. Thread organization is temporary.
  Snooze wakes a thread while this page is open; it does not schedule agent work.
- **Conversation:** streaming Markdown, expandable tool activity, source labels,
  copy response, and token usage, with a floating multiline composer.
- **Assistant and model selectors:** use the real profiles and available models.
  Changing either for an existing conversation starts a separate thread.
  Set `DEFAULT_PROFILE` in `.env` to choose the initial agent.
- **Workspace panel:** browse assistants, configured knowledge, tools and skills,
  sources, activity, and thread details. Resize it by dragging its divider or
  using the arrow keys on the focused divider. Side panels become drawers on mobile.

The workspace brings Runnrr's supported assistant capabilities together in one
place, with threads, tool activity, and project context.

Agent creation, editing capabilities, attachments, file generation/previews,
voice, approvals, messaging, scheduled work, authentication, and durable
history are not implemented in the workstation yet. No actions are simulated
as successful. The original supplied design is preserved in [docs/design/](docs/design/).

The former dashboard, builder, and eval pages have been removed. Their backend
APIs and eval CLI remain available. The builder write API is still disabled
by default (`ENABLE_PROFILE_EDITOR=0`).

## Usage analytics

Open **Workspace → Usage & costs** for persistent chat metrics by day, model,
provider and assistant. Expand a response’s usage line for token/cache/reasoning
breakdowns, estimated cost, timing and context usage. Reasoning is included in
output and counted once. Unknown pricing and partial reports are labeled.
Only accounting metadata persists; transcripts stay temporary. See
[usage accounting and API details](docs/usage.md).

## Validation

```bash
scripts/check.sh
npm ci
npx playwright install chromium
scripts/check-browser.sh
npm run format:check
```

Python tests and Node assertions use fake providers. Browser checks start an
isolated local runtime with temporary databases and block real chat requests.
They cover thread actions, model binding, streaming isolation, safe Markdown,
project import, usage, and responsive controls. Current visual verification is
recorded in [design QA](docs/design/qa.md).

## Architecture and privacy

FastAPI exposes `/api/chat` as SSE and read-only profile, model, health,
budget, tool, retrieval, and evaluation endpoints. Anthropic, OpenAI-compatible,
and Gemini adapters share one agent loop. Sessions live in process memory, so run a single worker. Budgets, usage metadata,
and imported projects persist in SQLite under `data/`.

Only `web/` is served as public static content. `.env`, profiles, local KBs,
and Git metadata are not web assets. Private knowledge, resumes, codebase
dumps, and credentials stay ignored. `kb/frampton/` is the exception: it
contains public third-party wiki material.

The product direction is one runtime per business with authenticated access,
durable sessions, a writable workspace, and business integrations. Those are
future backend work, tracked in [the implementation sequence](docs/roadmap/README.md).

## Documentation

- [Maintenance results and remaining work](docs/maintenance.md)
- [Project storage and refresh](docs/projects.md)
- [Usage accounting](docs/usage.md)
- [Bundled agents](docs/guide.md#bundled-agents)
- [Add an agent](docs/guide.md#add-an-agent)
- [Knowledge and evaluations](docs/guide.md#knowledge-and-evaluations)

## Contributing and deployment

See [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md), and
[history.md](history.md). Deployment remains manual; see [deploy/README.md](deploy/README.md).
The separate frozen public-site deployment is not changed by this repository.

## License

[MIT](LICENSE). Vendored frontend assets retain their [upstream licenses](web/vendor/README.md).

### Project workspaces

New thread → choose assistant → choose a project or No project. Use the folder
icons to search and import your own text folders. The hosted demo instead lists
Bryan’s public portfolio. See [project storage and refresh](docs/projects.md).

## Repository layout

- `runnrr/`: API, agent loop, providers, tools, retrieval, and evaluations.
- `web/`: browser workstation and licensed vendor assets; no build step.
- `profiles/`: agent configuration, prompts, and bundled example knowledge.
- `tests/`: Python, frontend, and browser checks.
- `docs/`: guides, design evidence, examples, and the current roadmap.
- `deploy/`: manual deployment and refresh service definitions.
