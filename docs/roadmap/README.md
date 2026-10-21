# Roadmap

This is the current implementation sequence. Plans in `../plans/archive/` are
historical and do not authorize deleting active profiles or APIs.

## Finishing the current workstation

The local workstation, inclusive usage accounting, persistent usage dashboard,
owner-scoped project imports, and public portfolio refresh are implemented.
Their local integration checks cover concurrency, failure, and browser behavior.
Deployment and live-service verification remain separate. See
[maintenance results](../maintenance.md).

## Proposed next delivery sequence

These are candidates for the owner to prioritize, defer, or abandon; none is
automatically authorized by committing the current work.

1. Durable sessions: persist messages and recover interrupted turns; preserve
   exact profile/model/project binding and test restart recovery.
2. Authentication and ownership: protect sessions, projects, and usage per user;
   migrate browser workspace keys without losing existing projects.
3. Approvals and audit: persist pending actions, enforce decisions server-side,
   add cancellation and an operator kill switch before external write tools.
4. Writable workspaces and artifacts: path containment, quotas, previews, and
   downloads; establish isolation before executing arbitrary tools.
5. Support integrations: verified inbound events, idempotent thread routing,
   draft replies, and human approval before sending customer messages.
6. MCP and installed-agent adapters: explicit capability contracts, lifecycle
   handling, and permission propagation.
7. Scheduling, memory, delegation, and voice follow those foundations.

The individual documents here retain design notes and acceptance ideas. Serving
UI from the runtime is already complete. These future items are not claims of
current functionality. Deployment remains a separate manual operation.
