# EasyAgent — Architectural History

A running log of decisions that future agents (or future-me) can't recover from reading
the source code alone. New decisions go at the top, dated. Each entry should answer
**why** the choice was made and **what was rejected**.

> **Naming note:** the framework is **EasyAgent**. The personal-site agent profile is now **Personal Agent**, bundled under `profiles/personal-agent/` as the showcase example. Older entries below may refer to the former **Strauss** name — read them in that historical context.

---

## 2026-06-05 — BZS Software owns the public sales positioning

### Decision: Keep EasyAgent internal while demos sell BZS workflow systems
**Choice:** Reframed `docs/sales_pitch.md` around BZS Software's public offer:
workflow mapping, AI opportunity discovery, AI-assisted workflow builds, and
managed tuning. The Sales Concierge profile, catalog, smoke prompts, and profile
copy now use BZS Software language so a customer demo does not expose
"EasyAgent" as the product name. The BZS wording lives in profile
`tool_descriptions` overrides — engine tool wording in `backend/tools/sales.py`
stays business-neutral and the checkout preview URL is a neutral placeholder,
per the "engine stays business-agnostic" rule. EasyAgent remains the internal
framework and technical proof point for reusable profiles, safe tools, provider
flexibility, guardrails, and evals.

**Why:** Customers will contact BZS Software for expertise in identifying where
AI can save time and money, not to buy a product called EasyAgent. The pitch
needs to start from business efficiency and workflow outcomes, then use the
EasyAgent repo as delivery evidence only when technical buyers ask how the work
is implemented.

**Rejected:** Renaming the internal `sales-concierge` profile id or package ids
in this pass. Those ids are stable test/tool handles; the customer-visible
names and descriptions can change without destabilizing routing.

## 2026-06-05 — Business sales pitch and demo runbook added

### Decision: Sell EasyAgent through concrete workflow demos, not generic AI claims
**Choice:** Added `docs/sales_pitch.md` as a buyer-facing pitch and call
runbook. The document frames EasyAgent around business pain points, a scoped
offer ladder, discovery questions, and two primary demos: Sales Concierge for
catalog-backed lead qualification and preview-only revenue actions, and Customer
Service for grounded support deflection and escalation. README now links to the
runbook from the "More detail" section.

**Why:** The repo already contains business-oriented profiles, safe preview
tools, profile-local prompts, RAG/eval datasets, and production guardrails. A
sales conversation should show those working boundaries through visible
workflow proof instead of over-positioning EasyAgent as a generic chatbot or
claiming live integrations that are still preview-only.

**Rejected:** Creating a slide deck before the demo story is stable; adding new
production CRM or Stripe behavior; or rewriting profile prompts just to make
the pitch sound bigger. The current value is best shown by the existing
portable profile architecture and safe tool loop.

## 2026-06-01 — Code review contracts made explicit

### Decision: Treat profile/API/tool contracts as runtime boundaries
**Choice:** RAG health now has a stable browser/API shape with `status`,
`error_type`, and `message`, while preserving the older dashboard fields such as
`rag_enabled`, `indexed_files`, `stale`, and `stale_reason`. `/api/rag/index`
is the canonical RAG health read. `/api/status` still exists for the local
technical dashboard, but its payload assembly moved to `backend/status.py` and
README now points external clients at the focused endpoints instead.

`load_profile()` now raises `FileNotFoundError` for any missing
`profile.json`, including the configured default profile. The old silent
generic-agent fallback hid deployment mistakes, including stale local
`DEFAULT_PROFILE` values. Runtime dictionaries that cross module boundaries are
now named in `backend/types.py` (`ModelConfig`, `BrandMetadata`, `UsagePayload`,
provider messages, and session state) without introducing a broader validation
framework.

Unexpected tool exceptions are still logged with stack traces, but production
tool results now return a non-leaky `"tool failed unexpectedly"` envelope. Set
`EASYAGENT_TOOL_DEBUG_ERRORS=1` to re-raise those unexpected exceptions while
developing a profile or native tool.

**Why:** The post-dashboard review showed that the biggest remaining risk was
not more RAG algorithm work; it was ambiguous API/error shape and soft
configuration boundaries. Making these contracts explicit keeps EasyAgent
portable for business profiles while preserving the known-good `search_kb`
baseline and additive `semantic_search_kb` rollout.

**Rejected:** Keeping the default-profile fallback for convenience; embedding
RAG health back into `/api/profile`; making `/api/status` a public integration
contract; or adding mypy/pyright as a new gate before the runtime contracts are
settled.

## 2026-06-01 — Native tool registration collapsed into `ToolDef`

### Decision: Register native tools once with schema, handler, and source metadata together
**Choice:** Native tools now declare a `ToolDef` that owns the
Anthropic-shaped schema, dispatch handler, and browser-safe source metadata
builder. Domain modules own their tool definitions (`backend/tools/kb.py`,
`web_fetch.py`, `sales.py`, `calculator.py`, `web_search_tool.py`, and
`backend/rag/tools.py`), while `backend/tools/registry.py` assembles the single
tool list used by `run_tool()`, `SCHEMAS`, and source metadata lookup. The
dispatch module is back to an envelope: allowlist checks, error normalization,
context construction, and JSON result wrapping.

**Why:** The review correctly identified that adding a business-specific tool
still required coordinated edits across schemas, dispatch, metadata, and profile
configuration. Co-locating each tool's contract and metadata keeps the framework
cheaper to tailor for customer-service, sales, research, and bespoke profiles,
and it prevents `source_metadata.py` from becoming another branch-heavy
monolith.

**Profile wording:** Shared resume/project tool schemas are now generic. The
Personal Agent profile supplies Bryan-specific descriptions through
`tool_descriptions` in `profiles/personal-agent/profile.json`, and provider
adapters pass those overrides when constructing model-facing schemas.

**Rejected:** Keeping separate `GENERIC_TOOL_HANDLERS` and
`PROFILE_TOOL_HANDLERS` maps. A single registry is clearer; profile gating
already happens through `profile.tools`, so a one-tool "profile" bucket added
labels without deleting conditionals.

### Decision: Make alternate profile roots explicit
**Choice:** `load_profile()` accepts `profile_root=...`, and the RAG CLI passes
that through directly instead of temporarily mutating `backend.profiles.PROFILE_ROOT`.

**Why:** CLI tests and alternate deployments should not rely on module-global
mutation. Passing the root as data is simpler and avoids cross-test or future
async leakage.

## 2026-06-01 — Native tools split into a package

### Decision: Keep `backend.tools` as the public API while moving tool internals into focused modules
**Choice:** `backend/tools.py` became the `backend/tools/` package. The stable
imports still work (`from backend.tools import SCHEMAS, ToolResult, run_tool`),
but schemas, result metadata, SSRF-guarded web fetching, calculator logic, sales
tools, and dispatch now live in separate modules. `ToolContext.profile` is typed
as `AgentProfile | None`, and profile system-prompt manifest generation now uses
the shared safe KB walker instead of raw markdown `rglob`.

**Why:** Eval and future business-profile tools need somewhere clean to land.
The handler registry fixed control-flow growth, but a 1k+ line module still made
unrelated changes collide. A package split keeps the provider/test import surface
stable while giving future work clear ownership boundaries.

**Rejected:** Leaving `backend/tools.py` as a temporary facade plus a second
internal package. That would preserve the filename but keep two tool entry
points to reason about. A normal Python package with re-exports is simpler and
keeps call sites unchanged.

## 2026-06-01 — RAG integration boundaries tightened after review

### Decision: Share KB walking, cache retrievers, and register tool handlers before more tool growth
**Choice:** KB enumeration now flows through `backend.kb_loader.iter_kb_files()`
and `iter_markdown_files()`, so runtime search and RAG manifest scans both reuse
the `_safe_resolve()` trust boundary and skip symlink escapes consistently. The
indexer also resolves changed manifest paths through `_safe_resolve()` before
reading, scans current markdown files once per build, and clears cached
retrievers before rewriting index files.

`get_retriever_for_profile()` now memoizes loaded retrievers by profile id,
index directory, embedding identity, and the manifest/BM25/vector file
fingerprint. Cache invalidation closes old vector connections so multi-hop
semantic searches do not repeatedly unpickle BM25 or reopen sqlite-vec, while
index rebuilds do not write over a cached open connection. `run_tool()` now uses
a small handler registry with separate profile-scoped handlers instead of adding
another branch to the dispatcher, and search source metadata shares one helper
for `search_kb` and `semantic_search_kb`. `SemanticSearchError` now subclasses
the shared `ToolExecutionError`, so tool errors return the clean envelope rather
than a runtime-exception prefix.

**Why:** The RAG core was modular, but review showed the framework boundary was
starting to absorb too much future complexity. These changes preserve the public
tool contract while making the next business-profile tool cheaper to add and
making index-time filesystem behavior match runtime KB safety. Retriever caching
also removes avoidable per-hop reload cost on the VPS path.

**Rejected:** A full physical split of `backend/tools.py` in this pass. The file
still needs decomposition, but the active branch already contains broad profile,
frontend, and RAG changes. A registry seam is the smaller safe move now; moving
schemas, metadata, web fetch, and sales handlers into separate modules should be
the next cleanup once this branch is stable.

## 2026-06-01 — Personal profile renamed from Strauss to personal-agent

### Decision: Use a descriptive profile id for the bundled personal agent
**Choice:** The bundled personal-site profile moved from `profiles/strauss/`
to `profiles/personal-agent/`, with profile id `personal-agent` and label
`Personal Agent`. The default profile, frontend fallback presentation, README
commands, `.env.example`, AGENTS guidance, and tests now use the descriptive
id. The persona and KB behavior remain the same: it is still Bryan's
candidate-advocate profile with the same tools, KB root, brand color, and
retrieval behavior.

**Why:** `Strauss` was memorable but opaque to future agents and collaborators.
`personal-agent` makes the profile's job obvious in config, CLI commands,
RAG index paths, and test names while preserving EasyAgent's profile-driven
architecture. Renaming the profile package is cleaner than special-casing a
display alias because the profile id is the stable operational handle for API
requests, defaults, CLI indexing, and frontend selection.

**Rejected:** Keeping the old id and only changing the display label. That
would leave commands like `backend.rag.cli build strauss` and defaults like
`DEFAULT_PROFILE=strauss`, which is exactly the ambiguity this rename is meant
to remove. Also rejected: changing the engine name or personal KB layout; those
are separate boundaries.

## 2026-06-01 — Semantic RAG ships as an additive profile tool

### Decision: Build per-profile hybrid indexes explicitly, then expose semantic search only by allowlist
**Choice:** `backend/rag/embeddings.py`, `indexer.py`, `retriever.py`,
`tools.py`, and `cli.py` now form the first usable semantic-search slice.
Embeddings use a small `EmbeddingProvider` protocol with Voyage, local
sentence-transformers, and deterministic fake providers; optional packages are
imported only when selected. The indexer writes `manifest.json`, `bm25.pkl`,
and `index.sqlite` under the profile's `.index/` directory by default, deletes
removed or modified paths from both sparse and vector indexes, embeds changed
chunks in batches, reports stale reasons, and is driven by
`python -m backend.rag.cli build ...`. The vector schema is created even for an
empty KB so a successful build does not leave the index permanently stale. The
retriever fuses BM25 and sqlite-vec results with plain Reciprocal Rank Fusion
and returns typed result metadata.

**Why:** This keeps EasyAgent's profile-driven architecture intact while making
RAG usable end to end. Each profile owns its KB, prompt, tool allowlist, and
index, so semantic retrieval can be enabled for Personal Agent, Customer
Service, and Frampton without changing Research Analyst or Sales Concierge
behavior. The
fake embedding backend keeps tests deterministic and model-free, while Voyage
and local providers remain opt-in runtime choices. README and `.env.example`
now document the live and fake embedding paths, and the test suite covers the
chat endpoint, agent loop, tool dispatcher, indexer, retriever, embeddings, and
storage primitives without requiring a live embedding API.

**Rejected:** Replacing or altering `search_kb`; rebuilding indexes in the chat
request path; exposing `semantic_search_kb` globally outside profile
allowlists; adding a reranker before it can be fully mocked and measured; and
importing `voyageai`, `sentence-transformers`, or sqlite-vec from core startup
paths. Browser-facing source metadata remains category-level and does not leak
raw KB paths.

## 2026-06-01 — RAG foundation stays optional and typed

### Decision: Keep RAG storage opt-in while making `Chunk` the canonical contract
**Choice:** `sqlite-vec` moved from core dependencies into the optional `rag`
extra, and `backend/rag/vector_index.py` now imports it only when a
`VectorIndex` opens a connection. `BM25Index` and `VectorIndex` now accept and
return `Chunk` objects directly instead of converting through dict-shaped
documents, and `Chunk.to_doc()` / `chunks_to_docs()` were removed. BM25 also
has `delete_by_path()` so future incremental re-indexing can delete changed
files from sparse and vector indexes symmetrically. `plan.md` and the RAG
package docstring were also corrected to describe this as a validated
foundation pass, with `semantic_search_kb` still future additive work.

**Why:** EasyAgent's normal profile/runtime imports should not require an
unused native sqlite extension while RAG is still opt-in. Keeping `Chunk` as the
one storage and retrieval type prevents heading path list/tuple drift before
the retriever, eval harness, and future `semantic_search_kb` tool are added.
Symmetric delete support keeps the planned manifest-driven indexer from
silently leaving stale sparse results behind when a file changes.

**Rejected:** Keeping `sqlite-vec` as a runtime dependency for every install,
keeping BM25/vector APIs on `dict[str, Any]`, or wiring semantic search into
`backend/tools.py` during this foundation pass. `search_kb` remains the
known-good baseline, and `semantic_search_kb` remains a future additive tool.

### Decision: Corrupt manifests fail loudly instead of looking missing
**Choice:** `Manifest.load()` still returns `None` when the manifest file is
absent, but it now raises `ManifestError` for invalid JSON, unsupported
versions, non-object payloads, and malformed file entries. Focused tests cover
manifest save/load, invalid manifests, BM25 save/load/delete behavior, and
sqlite-backed vector add/search/upsert/delete behavior when the optional extra
is installed.

**Why:** A missing manifest means an index has not been built; a corrupt
manifest means the index state cannot be trusted. Treating both states the same
would make future rebuild logic hide bad state and could duplicate or orphan
chunks. The tests lock down the foundation behavior before profile-specific RAG
integration begins.

**Rejected:** Swallowing JSON decode errors and rebuilding as if nothing had
ever been indexed. Also rejected: expanding this pass into tool integration,
profile allowlist changes, or replacing the current keyword search path.

## 2026-06-01 — README names June roadmap and future platform ideas

### Decision: Separate near-term foundation work from forward-looking platform features
**Choice:** `README.md` now has a compact capabilities list, a June 2026
roadmap, an implementation-direction section, and a forward-looking ideas
backlog. The June roadmap focuses on RAG cleanup, tool architecture boundaries,
additive `semantic_search_kb`, profile evals, CI, and onboarding docs. Bigger
business-platform ideas like MCP runtime execution, durable handoff,
multi-tenancy, channel adapters, observability dashboards, live Stripe/CRM
writes, voice, and fine-tuning are listed separately as future ideas.

**Why:** EasyAgent is already useful as a portable single-widget business-agent
framework, but the next work should strengthen the foundation before promising a
multi-tenant platform. Putting the immediate June work and the aspirational
backlog in different README sections makes the project easier to understand for
future agents, collaborators, and portfolio readers.

**Rejected:** Mixing every idea into the active roadmap. That would make the
near-term RAG, tooling, and eval work look less focused and could imply that
multi-channel or live-write integrations are already in scope for the current
runtime.

## 2026-05-27 — RAG plan favors simple readable code

### Decision: Make simplicity an explicit implementation constraint
**Choice:** `plan.md` now includes an "Implementation style" section for the
RAG work. It asks future implementation to stay small, typed, deterministic,
profile-scoped, and testable, with `semantic_search_kb` added beside
`search_kb` instead of replacing it. The vector index and retriever bullets now
also call out thin wrappers and plain readable RRF code.

**Why:** RAG projects can drift into generic retrieval platforms before the
first useful evaluation exists. EasyAgent's value is portability through a clear
profile + engine + tools shape, so the RAG layer should be understandable to a
future agent reading the source without needing to reconstruct a large hidden
framework.

**Rejected:** Adding broad registries, deep inheritance, or speculative
abstractions up front. Those can be introduced later only if repeated real
profiles prove they remove more complexity than they add.

## 2026-05-27 — RAG plan requires paired baseline evaluation

### Decision: Measure RAG against the current keyword search path before judging success
**Choice:** `plan.md` now makes the RAG eval harness run paired `keyword`,
`hybrid`, and optional `hybrid_rerank` variants, with retrieval-only and full
agent-loop comparisons. The `keyword` variant is the current `search_kb`
substring/regex behavior and acts as the "without RAG" control; `hybrid` is the
dense-vector + BM25 + RRF candidate; `hybrid_rerank` is measured separately so
reranking has to justify its latency and cost.

**Why:** A semantic index can look impressive in isolation while failing to
outperform the existing KB tool on real profile questions. Paired runs keep the
model, profile, prompt, session reset, and graders fixed so the score delta is
attributable to retrieval instead of random conversation drift. The report is
also designed to show regressions case by case, not only a pretty average.

**Rejected:** Treating "pytest passes" or a few manual semantic-search examples
as proof that RAG helped. Also rejected: comparing only against a closed-book
model. Closed-book is useful as a diagnostic, but the real product baseline is
the current keyword KB search path users already have.

## 2026-05-06 — Commit the Frampton Dark Souls KB to the repo

### Decision: Track `kb/frampton/` in git instead of leaving it as a local-only scrape
**Choice:** `.gitignore` now adds an exception (`!kb/frampton/`) so the categorized Fextralife scrape is committed alongside the profile. CLAUDE.md, AGENTS.md, README.md, and `kb/README.md` are updated to call out this single-profile exception to the broader "do not commit personal KB" rule.

**Why:** Unlike resume files or codebase XML dumps under `kb/`, the Frampton corpus is third-party but public Dark Souls wiki content with no privacy concern. Committing it makes deploys self-contained — `bash /opt/deploy/deploy.sh easyagent` ships everything the profile needs in one shot, instead of requiring a separate `rsync` of `kb/frampton/` every time the scrape changes.

**Rejected:** Continuing the rsync-only workflow. It was working but is two-step (push code, then rsync KB) and a deploy without the KB sync silently produces a broken Frampton agent on the VPS. Also rejected: committing other local KB folders (resume, codebases, projects, meta) — those remain private and gitignored.

## 2026-05-06 — Frampton brand contract turns red

### Decision: Make Frampton's Dark Souls identity canonical profile metadata
**Choice:** `profiles/frampton/profile.json` now declares a red primary accent, dark red controls, soft red surfaces, a red grid wash, a rose secondary mark, and a compact four-line monster `hero_icon` while keeping the profile limited to `list_kb`, `read_file`, and `search_kb`.

**Why:** bryanzane.com consumes `/api/profile` and `/api/profiles` as the production brand contract once a backend profile is deployed. Encoding the red Dark Souls identity in the profile itself prevents the public site, source web UI, and future clients from drifting into a frontend-only override.

**Rejected:** Styling Frampton only in the portfolio site's local fallback catalog. That would look right before deployment, but the API would still advertise Frampton with the old muted green profile colors.

## 2026-05-06 — Frampton uses a local Dark Souls 1 KB mount

### Decision: Add a DS1 profile without committing the scraped corpus
**Choice:** `profiles/frampton/` defines the Frampton Dark Souls 1 guide persona, points `kb_root` at `kb/frampton`, and enables only the generic read-only KB tools. The scraped Fextralife corpus remains ignored runtime data and can be mounted locally from the Desktop category scrape.

**Why:** The categorized scrape is large enough to be useful for an agent, but it is generated third-party content and does not belong in the public framework history. Keeping the data under the ignored `kb/` boundary preserves the EasyAgent profile/engine split: source code carries reusable agent behavior, while local KB content stays deployment-specific.

**Rejected:** Committing the 3,500 scraped Markdown files, hardcoding an absolute Desktop path in `profile.json`, or adding Dark-Souls-specific backend tools before the generic KB search/read path has been proven with real player questions.

## 2026-05-05 — Sales brand contract is purple/gold

### Decision: Sales Concierge brand metadata owns the public accent
**Choice:** `profiles/sales-concierge/profile.json` now declares Sales Concierge as purple (`#7C3AED`) with a dark purple control color, soft purple grid wash, and gold secondary mark. Agent guidance also calls out that profile `brand` metadata is the production UI contract consumed by `/api/profile` and `/api/profiles`.

**Why:** The deployed bryanzane.com EasyAgent page reads backend profile metadata once the API advertises the Sales profile. Leaving Sales green in the EasyAgent repo would override the site-copy fallback and make production drift from the requested purple/gold identity as soon as the VPS backend is current.

**Rejected:** Keeping the frontend as the only Sales color override. That would make the page look correct in one host, but the portable EasyAgent profile contract would still tell future clients to render Sales as emerald.

## 2026-05-05 — Web banner sweep matches production

### Decision: Agent switches reuse the production EasyAgent color wipe
**Choice:** The standalone `web/` frontend now includes the same large `EASY AGENT` ASCII hero used on bryanzane.com, with the production-style `--accent-banner-prev` gradient wipe and delayed mascot swap when the active profile changes. Initial profile load applies the brand directly; only successful agent switches animate.

**Why:** The production page already established the intended interaction: switching agents should feel like the banner is being recolored left-to-right, while the profile mascot changes as the sweep reaches it. The dev/source frontend needs to preserve that behavior so new Research and Sales profiles can be reviewed before deploy without drifting from prod.

**Rejected:** Designing a new transition or letting profile-brand updates snap instantly in the dev UI. The animation is already part of the EasyAgent visual language, so the source frontend should match it rather than become a separate reference.

## 2026-05-05 — Research and sales profiles use native preview tools

### Decision: Profile branding metadata ships before the frontend renderer
**Choice:** `AgentProfile` now carries optional `brand` metadata and optional `data_root`, and `/api/profile` plus `/api/profiles` return that metadata alongside the existing tool allowlist. Strauss, Customer Service, Research Analyst, and Sales Concierge all declare brand values even though the frontend rendering pass is separate.

**Why:** The visual direction is profile-specific: ASCII intro names, banner icons, accent colors, and placeholders change with the active agent. Keeping that as backend profile data preserves the profile/engine split and gives the future web pass one stable contract instead of hardcoded profile branches.

**Rejected:** Baking the new Research and Sales visual identity directly into CSS or JavaScript first. That would make the demo look right but leave no portable profile contract for future agents.

### Decision: New non-KB capabilities start as native safe tools
**Choice:** Research Analyst uses the existing server-side Tavily `web_search` plus native `fetch_url_text` and `calculator` tools. Sales Concierge uses native catalog lookup, lead qualification, lead-capture preview, checkout-link preview, and calculator tools backed by `profiles/sales-concierge/data/catalog.json`.

**Why:** These profiles need to prove EasyAgent can do more than read KB markdown, but the first implementation still needs to be deterministic, testable, and safe in a public demo. Native tools fit that slice because they use the existing schema translation, profile allowlists, source metadata, and provider loop.

**Rejected:** Wiring live Stripe, CRM, calendar, or MCP integrations in the first pass. Sales preview tools intentionally do not persist leads, send email, import Stripe, or create Checkout Sessions. MCP remains the right future shape for larger external tool surfaces, but the runtime does not connect MCP clients yet.

### Decision: New profile prompts carry workflow and smoke-eval expectations
**Choice:** Research Analyst and Sales Concierge system prompts use explicit XML sections for role, mission, grounding rules, tool-use rules, workflow, response style, and quality bar. Each profile also has a small `evals/smoke.json` dataset naming representative tasks, expected tools, and objective criteria.

**Why:** Tool-heavy agents need more than a persona. The workflow sections tell the model when to search, fetch, calculate, qualify, preview, ask a clarifying question, or stop. The smoke datasets make future prompt/tool changes testable instead of relying on a couple manual chats.

**Rejected:** Leaving evaluation guidance only in global docs. The global rules are useful, but profile behavior changes happen inside profile packages, so the smoke prompts need to live beside the system prompt they protect.

## 2026-05-05 — Agent details can inspect active tool schemas

### Decision: Tool transparency uses profile-scoped schema JSON
**Choice:** `/api/profile` now includes `tool_schemas` for only the active profile's allowed tools, and the web agent-details panel renders each tool name as a button that opens the canonical Anthropic-shaped schema JSON.

**Why:** Tool visibility belongs beside profile metadata because tools are part of what makes one agent profile different from another. Returning the shared schema shape keeps the UI honest about the source of truth while avoiding provider-specific translations that would make the same tool look different depending on the selected model.

**Follow-up:** `schemas_for_tools(...)` skips unknown tool names instead of raising, so `/api/profile` can still return the profile's full tool allowlist while omitting only schemas that are not authored in `SCHEMAS`. The frontend can then render those mismatches as disabled/unavailable chips.

**Rejected:** Adding a separate public endpoint that dumps every tool in `SCHEMAS`. That would be handy for debugging, but it blurs the profile allowlist boundary and could imply disabled tools are available to the current agent.

## 2026-05-05 — Chat chrome keeps usage and controls persistent

### Decision: Session usage lives in the header chrome
**Choice:** The web UI now mirrors the session token summary into the sticky EasyAgent header beside the banner while retaining the detailed values in the expandable agent panel.

**Why:** Token usage is operational status, not profile metadata. Keeping the compact counter in the page chrome makes it visible throughout long answers and while the bottom composer is focused, without requiring visitors to open the agent details panel.

**Rejected:** Leaving the only session counter inside `agent details`. That kept the implementation simple, but it hid the most useful cost/status signal behind a collapsible panel that could scroll out of view during longer conversations.

### Decision: The composer is fixed to the viewport bottom
**Choice:** The agent switcher, model chip, new-chat action, details panel, and message input now sit in a fixed bottom composer with extra message-feed padding so long responses scroll behind it instead of carrying it away.

**Why:** The chat page is meant to feel like a persistent terminal/chat surface. Users should be able to switch agent profiles or send the next prompt without scrolling back to the bottom after reading through a long answer.

**Rejected:** Relying on `position: sticky` inside the main chat column. Sticky positioning only holds within its container's scroll context and could still feel like part of the transcript rather than permanent app chrome.

## 2026-05-05 — Tool results expose safe source labels, not KB paths

### Decision: SSE tool-result metadata is public and sanitized
**Choice:** `tool_result` events now include browser-facing source metadata (`source_summary`, `source_items`, `source_count`, and `hidden_count`) derived after tool execution. The model still receives the full raw tool result through `ToolResult.content`, but public clients only receive category-level labels such as `Resume`, `Project: Widget`, `Portfolio knowledge base`, `Knowledge base index`, or public web domains.

**Why:** Visitors should be able to tell when the agent grounded an answer in a resume, project note, KB search, or web result. Raw KB paths are useful for debugging, but on a public portfolio they reveal private knowledge-base shape, filenames, and codebase dump organization that the browser does not need.

**Rejected:** Streaming relative KB paths and line ranges as a transparency feature. Even when paths are safely resolved under the KB root, they can still expose internal file naming and private organization. The public contract is evidence transparency, not filesystem observability.

## 2026-04-29 — Commit message convention wording

### Decision: Agent guidance names the commit format explicitly
**Choice:** `AGENTS.md` now refers to Conventional Commits labels with "50:72" formatting: an imperative labeled subject under 50 characters, a blank line, and body lines wrapped at 72 characters explaining why.

**Why:** The repo already used Conventional Commits-style labels and 50/72 wrapping, but spelling it as "50:72" matches the owner's release handoff language and gives future agents a stable instruction to follow before production pushes.

**Rejected:** Leaving this as an implicit preference. Commit-message shape is not visible from source code behavior, so it belongs in agent guidance and history rather than only in one-off chat context.

## 2026-04-29 — DeepSeek-only web UI and CSP-safe markdown rendering

### Decision: The demo UI no longer exposes model switching
**Choice:** `web/` now treats `deepseek-v4-flash` as the fixed browser model and shows it as a static chip instead of a dropdown. The frontend still calls `/api/models`, but only to confirm DeepSeek is available before accepting submissions.

**Why:** Bryan's production site is intentionally running DeepSeek for now. Keeping a selector in the UI suggests visitors can choose other providers even though the public deployment is being presented as a DeepSeek-backed showcase. The profile id remains `strauss` because that is the bundled persona; only the browser model control was removed.

**Rejected:** Hiding the dropdown with CSS while leaving selector state active. That would preserve unnecessary session-storage model state and keep a stale "switch model resets conversation" code path around after the product decision changed.

### Decision: Markdown rendering uses CSP-allowed libraries and sanitizes before injection
**Choice:** The static frontend loads pinned `marked@12.0.2` and `DOMPurify@3.1.6` from cdnjs, then buffers streamed deltas and re-renders sanitized markdown during streaming. Tool indicators use a FIFO queue and settle visibly as `done` or `error`.

**Why:** bryanzane.com already allows cdnjs in its Content Security Policy, while jsDelivr was blocked in production. Rendering markdown only after DOMPurify is present keeps the no-build frontend simple without injecting unsanitized HTML from model output.

**Rejected:** Expanding the Caddy CSP to allow another CDN just for this page. cdnjs already serves the exact pinned versions, so changing the page dependency URL is the smaller deployment surface.

## 2026-04-28 — Public repo hygiene and production guardrails

### Decision: Personal KB content stays out of the public repository
**Choice:** `kb/` is treated as local/private runtime data and ignored by git. The public repo documents the expected KB shape, but does not publish personal resume files, private project notes, or codebase XML dumps.

**Why:** Strauss is a reusable framework. The engine, profile loader, tools, provider adapters, tests, and docs are the reusable surface; Bryan's personal knowledge base is deployment data. Publishing the KB would mix private content into the framework's source history and make future profile reuse harder to reason about.

**Rejected:** Seeding the public repo with Bryan-specific KB markdown or XML dumps. That would make the demo feel richer on GitHub, but it creates an avoidable privacy and maintenance risk. Tests already use `tests/fixtures/mini_kb/`, which is the right public fixture boundary.

### Decision: Public project aliases can stay in code; private content stays in KB
**Choice:** `PROJECT_ALIASES` may include public-facing project names, domains, and common spellings so the default Strauss profile can resolve natural project questions to local KB slugs. The files those aliases point at still live under ignored `kb/` runtime data.

**Why:** Aliases are routing hints, not private source material. Keeping them in code improves tool reliability for site visitors without exposing resumes, codebase dumps, or private notes.

**Rejected:** Moving every alias into private KB metadata. That would keep the public framework slightly more generic, but it would also make a fresh deploy easier to misconfigure and weaken tests around the project lookup path.

### Decision: Production limits live in the app, not in the browser
**Choice:** The FastAPI app enforces a per-IP `/api/chat` rate limit, a process-local daily token budget with `/api/budget` introspection, an active-session cap, and structured JSON completion logs. The browser remains a thin SSE client.

**Why:** Abuse controls and usage accounting need to sit beside the provider keys and model calls. Keeping them server-side lets the same engine support a portfolio deployment today and other profiles later without asking every client to reimplement cost and safety rules.

**Rejected:** Client-only throttling. It is useful as polish, but it is not a security boundary and cannot protect server-side API keys or model spend.

---

## 2026-04-28 — DeepSeek thinking mode through OpenAICompatProvider

### Decision: DeepSeek slots in by extending OpenAICompatProvider, not adding a new provider class
**Choice:** `OpenAICompatProvider` gains three optional kwargs — `extra_body`, `reasoning_effort`, `preserve_reasoning_content` — plus a reasoning-accumulation branch in the streaming loop and a DeepSeek-specific KV-cache field in `_norm_usage`. Each piece is registry-driven and defaults to a no-op for OpenAI/Kimi/GPT-5.

**Why:** DeepSeek's `/chat/completions` is OpenAI-shape compatible for the parts that matter (streaming, function calls, role: tool results). The deltas it emits in thinking mode add `reasoning_content` chunks the standard OpenAI client surfaces via `getattr(delta, "reasoning_content", None)`, so we don't need a separate transport. Forking a `DeepSeekProvider` would have duplicated ~200 lines of streaming/tool-call accumulation logic for one new field.

**Rejected:** A dedicated `DeepSeekProvider` class. Tempting because thinking mode's quirks (round-tripping `reasoning_content` on tool-call turns or DeepSeek 400s the next request) feel provider-specific. But those quirks are gated by per-model registry flags (`preserve_reasoning_content`), not by the provider class — so the gating belongs at the registry level. One provider, multiple capability flags, beats N providers each repeating the same OpenAI-shape boilerplate.

### Decision: Reasoning content is preserved server-side on every thinking-mode turn, never crossed to the SSE stream
**Choice:** When a DeepSeek delta contains `reasoning_content`, the provider accumulates it into a per-call `reasoning_parts` list and `continue`s — it is *not* yielded as `text_delta`. When the assistant turn finishes, if (a) the registry opted in via `preserve_reasoning_content` and (b) reasoning was actually streamed, the concatenation is attached to the assistant message as `reasoning_content` so it round-trips to DeepSeek on the next request.

**Why:** DeepSeek requires `reasoning_content` to come back on **every** thinking-mode assistant turn that streamed reasoning, not just tool-call turns. The error surface confirms this empirically — a follow-up turn within the same session 400s with `"The reasoning_content in the thinking mode must be passed back to the API"` if any prior assistant turn (tool-call or plain-text) had reasoning streamed but didn't preserve it. At the same time, raw chain-of-thought is provider-protocol state, not user-facing answer text — surfacing it to the browser would leak working-out the model assumes is private. The split keeps the engine correct for multi-turn conversations *and* keeps the UI clean.

**Rejected (initially tried):** Gating preservation on `completed_tool_calls and reasoning_parts`. Tighter and seemed safer per the original DeepSeek docs framing ("when a thinking-mode response performs tool calls"), but multi-turn conversations 400 the moment a plain-text turn's reasoning is dropped. The smoke test that surfaced this was a recruiter-style chat: turn 1 "Tell me about Shuttrr" succeeded with a tool call → turn 2 "And what about Physiq?" 400'd because turn 1's *final answer* turn (plain-text after the tool result) had streamed reasoning that wasn't echoed back.

**Rejected:** Streaming reasoning to the browser as a separate `reasoning_delta` event so a "thinking…" UI could render it live. Cute, but it bakes provider-protocol leakage into the public API and would have to be sanitized at every UI layer. A `tool_use_start` event already exists for the "the agent is doing something" affordance — that's enough.

### Decision: Default sampling params are not sent for DeepSeek thinking mode
**Choice:** No `temperature`, `top_p`, `presence_penalty`, or `frequency_penalty` are passed for the `deepseek-v4-flash` model.

**Why:** DeepSeek docs state those parameters have no effect in thinking mode. Sending them is harmless wire bloat at best, confusing-to-debug at worst. The provider doesn't hardcode these today (they're only added if a caller passes them), so this is a documentation rule for future contributors rather than a code change.

---

## 2026-04-28 — Multi-provider wiring + reusable profiles

### Decision: Agent profile is separate from the engine
**Choice:** persona, welcome copy, suggestions, system prompt, and KB root now live under `profiles/<id>/`. The reusable engine receives an `AgentProfile` and passes `profile.kb_root` into tool dispatch.

**Why:** Strauss should be a reusable agent framework, not a one-off bot. A future social media video manager, customer support bot, or internal operations agent can add a profile package and point at a different KB without forking the provider loop.

### Decision: Profiles explicitly allow tools
**Choice:** `profile.json` declares the tools available to that agent. Providers translate only those schemas, and the tool dispatcher rejects calls outside the active profile's allowlist.

**Why:** exposing every future tool to every future agent would make behavior harder to evaluate and easier to misuse. Tool allowlists keep each profile's capabilities intentional while preserving the same engine.

### Decision: OpenAI and Kimi share one OpenAI-compatible provider
**Choice:** `OpenAICompatProvider` handles OpenAI and Moonshot/Kimi chat-completions streaming. Tool schemas are still authored once in Anthropic shape, then translated to OpenAI function-tool shape.

**Why:** Kimi documents OpenAI-compatible tool calls and `role: tool` results, including streamed argument accumulation by `tool_calls[index]`. Keeping OpenAI and Kimi in one provider makes their shared message shape explicit while still allowing per-model knobs like `base_url`, token parameter, and stream-usage support.

### Decision: Gemini gets a native provider
**Choice:** `GeminiProvider` uses Google's `google-genai` SDK, `GenerateContentConfig`, and manual function-call handling with automatic function calling disabled.

**Why:** Gemini's history and function response shape is different enough from OpenAI that pretending it is OpenAI-compatible would make the engine brittle. The provider preserves Gemini `Content`/`Part` history and returns function responses with the model's call id.

## 2026-04-26 — Phase 0/A/B foundation

### Decision: Two native SDKs + thin protocol layer (not LiteLLM, not OpenRouter)
**Choice:** `anthropic` SDK for Claude + `openai` SDK with configurable `base_url` for OpenAI/Moonshot. A small `LLMProvider` Protocol normalizes the wire formats into a common `Event` shape that the agent loop consumes.

**Rejected:**
- **LiteLLM** — would have collapsed the two providers into one `litellm.acompletion(...)` call. Mature, well-maintained, supports 100+ providers. Rejected because it hides the protocol differences entirely (you'd never see how Moonshot's tool_calls accumulate from JSON fragments vs Anthropic's typed events). Building this for educational value, so seeing the differences IS the value.
- **OpenRouter as a gateway** — single OpenAI-compatible endpoint that routes to all providers. Rejected for the same reason + adds a paid middleman + you lose Anthropic-native `cache_control` (OR converts to OpenAI shape).

If maintaining two providers ever becomes painful, swap both for a single `LiteLLMProvider` behind the same `LLMProvider` interface. ~1 day of work.

### Decision: Tool schemas authored in Anthropic shape, translated to OpenAI shape
**Choice:** [SCHEMAS](backend/tools.py) live in Anthropic's `{name, description, input_schema}` form. A trivial `tool_translator.to_openai()` (Phase D) emits the OpenAI/Moonshot `{type: "function", function: {parameters: ...}}` form on demand.

**Why:** the user's Anthropic-course notebooks (`001_tools_009.ipynb`) use `input_schema` natively. Authoring in that shape keeps a 1-to-1 correspondence with what was already studied. The JSON Schema body is identical between the two formats — only the wrapper differs — so translation is mechanical.

### Decision: Hybrid tool design (3 generic + 2 specialized), not all-generic
**Choice:** `list_kb`, `read_file`, `search_kb` cover the long tail; `get_resume_summary`, `get_project_context` are specialized shortcuts.

**Why:** the specialized tools signal to the model "this is the canonical answer for resume/project questions, don't go fishing." Without them, models tend to do 3-4 unnecessary `search_kb` → `read_file` round trips for canonical questions. Specialized tools earn their keep when the model's default behavior is wasteful.

### Decision: KB layering — four tiers, only two are tool-result layers
```
manifest (always loaded, cached system block)        ← navigable index
quick_info.md (always loaded, cached system block)   ← per-codebase technical cheat sheet
project pitch summaries (tool result)                ← why-it-matters narrative per project
raw repomix XMLs (tool result with line-slicing)     ← actual source for "show me the code"
```

**Why:** putting per-codebase summaries directly in the system prompt as a third cached block means 80%+ of "tell me about Bryan's projects" questions need zero tool calls. Cache reads cost 10% of input on Anthropic; auto-cache covers it on OpenAI/Moonshot. A model that has the cheat sheet in its context will naturally cite it instead of thrashing through XML.

### Decision: Provider mutates `messages` list inside `stream()`
**Choice:** [`AnthropicProvider.stream`](backend/providers/anthropic_provider.py) appends the assistant turn to the messages list internally, *before* yielding `tool_use_complete` events. The agent.py loop only mutates messages via `provider.append_tool_results()`.

**Why:** the assistant turn (containing tool_use blocks) MUST land in the message log before the next turn's tool_result blocks. Otherwise Anthropic's API rejects the next call with "tool_result without preceding tool_use." Putting this side effect inside the provider means there's only one ordering invariant to remember: provider writes assistant, loop writes user(tool_results). Clean, predictable.

**Trade-off:** the test `FakeProvider` has to mirror this contract too (it appends a placeholder assistant turn). Documented in [tests/test_agent_loop.py](tests/test_agent_loop.py).

### Decision: Mid-conversation model switch resets the session
**Choice:** When the user switches models in the dropdown, the frontend treats it as starting a fresh conversation (new `session_id`).

**Why:** `session["messages"]` is provider-specific (Anthropic uses content blocks; OpenAI uses `tool_calls` arrays + `role:"tool"` results). Switching mid-conversation would feed Anthropic-shaped messages into Kimi K2 (or vice versa) and the model wouldn't understand them.

**Rejected:** a normalized intermediate message-log shape with translation hooks. More code, more failure modes, and matches how ChatGPT/Claude/Cursor behave when you switch models. Defer to v2 if there's a real demand for "show recruiter both answers" UX.

### Decision: `MAX_TOOL_HOPS = 8` as a runaway-loop safety net
**Choice:** the agent loop is bounded by [`MAX_TOOL_HOPS`](backend/config.py).

**Why:** a normal profile-specific question should rarely need more than ~3 hops (one specialized tool call + at most one source read). 8 is generous for legitimate use, tight enough to catch a model that's stuck in a tool-thrashing loop. Loop terminates with an explicit `error` event so the frontend can surface it cleanly.

### Decision: In-memory sessions, swept lazily per request
**Choice:** `SESSIONS: dict[str, dict]` lives in process memory. Stale sessions (idle > `SESSION_TTL`) are pruned at the top of each `/api/chat` call.

**Why:** v1 is single-worker. Lazy sweeping avoids a background `asyncio.create_task` and the testing complications it creates with `TestClient` (which doesn't always run startup hooks the way uvicorn does). When a v2 multi-worker setup is needed, this graduates to sqlite or Redis.

**Rejected:** persistent sessions, cross-visit memory. Privacy implications are non-trivial and the use case doesn't demand it yet.

### Decision: Vanilla static frontend (no React, no Vite, no build step)
**Choice:** [`web/index.html`](web/index.html) + `styles.css` + `app.js`, served as static files.

**Why:** matches `bryanzane_v3`'s existing deployment philosophy (CDN Tailwind + GSAP + Formspree + zero build). The chat UI is small (~350 lines total) — a framework would add more weight than it saves. Same VPS, same nginx, same auto-deploy webhook flow.

### Decision: Streaming-first AnthropicProvider (skipping the non-streaming step)
**Choice:** `AnthropicProvider.stream()` is the only entry point. There is no non-streaming variant.

**Why:** the original phased plan (Phase B non-streaming, then Phase C streaming) would have required rewriting the provider's core method between phases. Going straight to streaming costs no clarity — the loop's `stop_reason` branching lives in `agent.py`, not the provider, so it's still visible.

### Decision: Provider DI via module-level factory + `monkeypatch`, not FastAPI `Depends()`
**Choice:** [`backend/app.py`](backend/app.py) exposes a `get_provider(model_id)` function. Tests `monkeypatch.setattr("backend.app.get_provider", ...)` to inject a `FakeProvider`.

**Why:** matches the existing `monkeypatch` pattern in [tests/conftest.py](tests/conftest.py) for `KB_ROOT`. One fewer FastAPI concept to learn while building. `Depends()` + `app.dependency_overrides` is the more "FastAPI-blessed" pattern and is worth knowing, but we don't need its features (composable dependencies, request-scoped caching) here.

### Decision: `MODEL_REGISTRY` declares all 6 models from day one; `REGISTERED_PROVIDERS` gates which are visible
**Choice:** [`config.py`](backend/config.py) declares Anthropic + OpenAI + Moonshot model entries simultaneously. A `REGISTERED_PROVIDERS = {"anthropic"}` constant in `app.py` filters `/api/models` to only return models whose provider is implemented. Phase D adds `"openai_compat"` to the set.

**Why:** keeps the registry stable across phases (no rework when adding providers). The frontend dropdown only ever sees what works. Footgun avoided: a Moonshot key set with no `OpenAICompatProvider` available wouldn't surface as a broken model in the dropdown.
