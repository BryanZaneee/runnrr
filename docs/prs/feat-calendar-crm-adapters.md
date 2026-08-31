# feat/calendar-crm-adapters

**Status:** prepared (design + skipped contract tests). No implementation yet.

## Problem

The sales tools are previews on purpose (`lead_capture_preview` returns what *would* be sent). A paying Runnrr customer needs the real thing: an appointment on their Google Calendar and a note in their CRM — without the model ever having free-form write access to either.

## Design

- Two new `ToolDef`s in `backend/tools/adapters/`: `book_appointment` and `crm_note`. Both `requires_approval=True` by default (feat/hitl-actions) — the model proposes, a person approves, then the adapter writes. Previews stay as they are; nothing existing is replaced or renamed.
- **Allowlisted args.** Schemas are narrow: `book_appointment(start_iso, duration_min ∈ {15,30,60}, attendee_name, attendee_phone, summary ≤ 120 chars)`; `crm_note(contact_phone, text ≤ 500 chars)`. No free-form `fields` dict, no arbitrary calendar id — the calendar/pipeline is fixed per tenant in config, not chosen by the model.
- **Per-tenant OAuth.** Tokens live in the tenant store (PR #2) keyed by `tenant_id`; until #2 lands, `EASYAGENT_TENANT_SECRETS_DIR` holds one JSON per tenant (git-ignored). Adapter handlers receive `tenant_id` through `ToolContext`; a missing token returns a `ToolResult(is_error=True)` telling the model to ask the business to connect the account — never a traceback.
- First backends: Google Calendar (REST via stdlib `urllib` + the OAuth refresh dance, ~60 lines) and a generic "CRM = webhook" note poster (`POST` JSON to a per-tenant URL with a shared secret) so HubSpot/Pipedrive/etc. can be added without touching the engine. No vendor SDKs.
- Idempotency: `book_appointment` sends the approval id as the event's `iCalUID` so approving twice cannot double-book.

## API sketch

Tools only; no new HTTP endpoints. Profile opts in by listing `book_appointment` / `crm_note` in `tools`. Connect/disconnect endpoints for OAuth belong to the control plane (PR #2/#3).

## Tests to write

See `tests/test_calendar_crm_adapters_contract.py` (skipped). Network is faked at the `urllib` boundary; the OAuth refresh test uses a canned expired-token response.

## Out of scope

Stripe / payments, two-way calendar sync, availability search across multiple calendars, CRM reads.

## Dependencies

feat/hitl-actions (hard — default-on approval). PR #2 for real per-tenant secrets; file-per-tenant fallback until then.
