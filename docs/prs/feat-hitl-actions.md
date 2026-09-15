# feat/hitl-actions

**Status:** prepared (design + skipped contract tests). No implementation yet.

## Problem

"AI drafts, people send" is the product promise, but the engine has no concept of a proposed action. Every tool the model calls runs immediately. The sales tools sidestep this by being previews (`lead_capture_preview`, `checkout_link_preview`) — fine for a demo, useless once a real calendar or CRM is wired in (feat/calendar-crm-adapters).

## Design

- `ToolDef` gains `requires_approval: bool = False`. When True, `run_tool` does **not** invoke the handler. It records a pending approval `{id, session_id, tool, arguments, created_at}` and returns a `ToolResult` whose content tells the model the action is queued for a human (`"Queued for approval as apr_… — do not retry."`). The model's next text turn naturally says "I've drafted this for your team to send."
- Approving runs the original handler with the original arguments (arguments are frozen at proposal time; the approver cannot edit them in v1 — reject and re-ask instead). The result is appended to the session as a new user-role message (`"[approved action apr_… result]: …"`) so the transcript stays append-only and the provider prefix cache is preserved.
- Pending approvals live in the durable store when feat/durable-sessions lands; until then a process-local dict with the same TTL as sessions.
- **No current tool flips to live.** `lead_capture_preview` and `checkout_link_preview` keep `requires_approval=False` and keep returning previews. The flag exists for the real adapters that come next; the first tools to set it are in feat/calendar-crm-adapters.
- Profile JSON may override per tool: `"tool_approval": {"crm_note": true}` — a profile can only make a tool *stricter*, never relax a `ToolDef` that declares `requires_approval=True`.

## API sketch

```
GET  /api/approvals?session_id=…             → [{id, tool, arguments, status, created_at}]
POST /api/approvals/{id}/approve             → 200 {id, status: "approved", result: …}
POST /api/approvals/{id}/reject  {reason?}   → 200 {id, status: "rejected"}
```

Auth: same `X-Admin-Token` gate as feat/audit-log-kill-switch until PR #2 supplies per-tenant auth. Approving an unknown or already-decided id → 404 / 409.

```python
@dataclass(frozen=True)
class ToolDef:
    ...
    requires_approval: bool = False
```

## Tests to write

See `tests/test_hitl_actions_contract.py` (skipped).

## Out of scope

Payments, editing arguments at approval time, approval UI (dashboard PR #3 can render `GET /api/approvals`), notifications.

## Dependencies

Soft: feat/durable-sessions (pending approvals survive restart), feat/audit-log-kill-switch (approval decisions are audit records). Hard dependency *of* feat/calendar-crm-adapters.
