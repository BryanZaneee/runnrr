# Codebase maintenance — 2026-10-21

This implements the approved audit plan while preserving the pre-existing
workstation, usage, project, and portfolio-refresh changes. The owner subsequently
authorized committing and pushing the combined work. Deployment remains separate.

## Completed

| Area | Result |
| --- | --- |
| Product documentation | README explains noncoding business workflows, current provider-API support, cost reservations, temporary chats, persistent metadata, and source-checkout setup. |
| Organization | Design QA moved to `docs/design/qa.md`; the sales demo to `docs/examples/bzs-demo.md`; superseded plans to `docs/plans/archive/`. The roadmap now owns current priorities. |
| Confirmed unused files | Removed `bars-3.svg`, `view-columns.svg`, the old `workstation.webp`, and the duplicate uploaded feature inventory. Bundled profiles, public corpus, design references, licenses, and private data are preserved. |
| Sessions | Busy guard, active-session expiry protection, exact-model reset, user-turn counting, disconnect cleanup, and rollback of incomplete backend turns. |
| Retrieval | Serialized cross-thread SQLite access, single construction per cache miss, staged index generations, and off-loop inspection endpoints. |
| Fetch safety | Public addresses are validated and pinned at connection time, TLS still verifies the original hostname, redirects are revalidated, and response reading is capped. Environment proxies and compressed responses are disabled for this tool. |
| Completion and evaluation | Truncated/blocked tool calls cannot execute. Output limits are visible. Failed evaluations skip paid graders; a batch uses one event loop and owned provider clients are closed. |
| Performance | Pruned KB traversal, bounded search results, one-pass profile manifests, metadata-only project listings, cached BM25 frequencies, sanitized text-block caching, and retained completed transcript nodes. |
| Maintainability | Usage instrumentation extracted, long historical comments shortened, Python formatting/import checks standardized, and frontend handlers formatted. |
| Existing work | Workstation, project import, usage, and portfolio-refresh regression coverage is integrated. Frontend development dependencies and lockfile now live at the repository root. |
| Repeatable checks | `scripts/check.sh`, `scripts/check-browser.sh`, root npm scripts, and GitHub Actions checks. |

## Verification

443 Python tests passed, with one optional-dependency test skipped. Ruff
lint/format, Node assertions and syntax checks, Prettier, lockfile checks, and
65 browser assertions also passed locally.
The optional missing-sqlite-vec test skips because sqlite-vec is installed.
Starlette emits an existing AnyIO deprecation warning.

A synthetic BM25 comparison used 1,000 chunks of 600 repeated words and 30
queries: approximately 418 ms before and 15 ms after caching term frequencies,
with matching top-five results. This isolates scoring overhead; it is not an
end-to-end latency promise or a production workload benchmark.

## Operating notes

- Index builds publish `current` atomically inside the existing index root.
  Old flat indexes migrate on the next successful build. Compatibility file
  links remain, while readers resolve one immutable generation at a time.
  Previous generations are retained so in-flight readers remain valid. Remove
  obsolete generations only with the runtime and index builders stopped; keep
  the generation targeted by `current`. Builds require local symlink support.
- Source checkout remains required: standalone wheel distribution of the UI and
  profiles is not advertised. The existing deployment units were preserved;
  systemd execution and live provider integrations were not tested on this Mac.
- Cost bounds remain fail-closed. Tests did not make paid provider requests or
  refresh live portfolio data. Usage is still runtime-wide metadata; account
  authentication and per-user usage authorization await the auth milestone.
- Concurrent index builds publish complete generations; last publication wins.
  Use one build process per profile to avoid redundant paid embeddings.

## Remaining product work

No local cleanup task is running in the background. The previously uncommitted
workstation, project imports, and usage dashboard are now checked as an integrated
local feature set. Deployment remains pending a separate release decision.

The [roadmap](roadmap/README.md) plans the next deliverables and acceptance goals:
durable sessions and restart recovery; authentication/ownership; server-enforced
approvals and audit; writable workspaces/artifacts; customer-support integrations;
then MCP and installed-agent adapters, scheduling, memory, delegation, and voice.
These are future capabilities, not partially working controls in this release.
