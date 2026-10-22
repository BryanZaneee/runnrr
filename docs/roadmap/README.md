# Roadmap

Runnrr's core product is a polished portfolio demo for employers. The aim is a
convincing agent workstation with real responses, visible tool activity, and
clear boundaries around simulated work. Archived plans are historical, not
instructions to expand scope or delete active profiles.

## Implemented locally

- Workstation threads, project imports, streaming, and usage analytics.
- SQLite persistence for workspace threads, drafts, organization, and completed
  provider context. Interrupted responses remain visible as incomplete.
- Snoozed and settled sections: snooze returns a thread after its deadline;
  settle waits for manual restore. Neither launches agent work.
- Dark Souls knowledge selection using the local corpus and existing retrieval
  tools, with optional web search. Hybrid search requires an index build.
- Customer-service proof of concept: simulated customers, real model replies,
  a small live monitoring panel, tool activity, and saved conversation threads.
- Public portfolio project snapshots and refresh tooling.

## Remaining demonstration preparation

1. Build the Dark Souls semantic index with the chosen embedding backend and
   verify retrieval quality against representative questions. Keyword search
   and file reading are available before that build.
2. Configure provider keys and reviewed cost bounds, then rehearse a real model
   demo. Automated checks use injected responses and do not spend provider budget.
3. Review screenshots and the employer presentation with the final content.
4. Decide whether to publish this version. Deployment and live-service checks
   remain a separate, manual release task.

## Outside this delivery scope

Real customer inboxes, enterprise authentication, autonomous scheduling,
external write approvals, writable agent workspaces, installed-agent adapters,
MCP connections, voice, and delegation are possible extensions, not prerequisites
for the portfolio demo. Existing design notes retain context without making
these promised features. Preserve the existing profiles and local user data.
