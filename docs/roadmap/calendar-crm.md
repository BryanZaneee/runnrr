> **Single-tenant note (2026-09-06).** Runnrr is one runtime per business. Ignore every
> `tenant_id` and PR #2 reference below: sessions and audit rows carry `user_id` (an
> employee of the business) instead. `X-Admin-Token` / `ADMIN_TOKEN` are replaced by
> Supabase `require_user` (see `supabase-auth.md`). Env names use the `RUNNRR_*` prefix and
> `backend/` is `runnrr/`. Where this design and `docs/plans/runnrr-analysis.md` disagree,
> the analysis wins; the divergence is called out at the top of the file where it matters.

# feat/calendar-crm-adapters

**Status:** prepared (design + skipped contract tests). No implementation yet.

## Problem

The sales tools are previews on purpose (`lead_capture_preview` returns what *would* be sent). A paying Runnrr customer needs the real thing: an appointment on their Google Calendar and a note in their CRM — without the model ever having free-form write access to either.

## Design

- Two new `ToolDef`s in `backend/tools/adapters/`: `book_appointment` and `crm_note`. Both `requires_approval=True` by default (feat/hitl-actions) — the model proposes, a person approves, then the adapter writes. Previews stay as they are; nothing existing is replaced or renamed.
- **Allowlisted args.** Schemas are narrow: `book_appointment(start_iso, duration_min ∈ {15,30,60}, attendee_name, attendee_phone, summary ≤ 120 chars)`; `crm_note(contact_phone, text ≤ 500 chars)`. No free-form `fields` dict, no arbitrary calendar id — the calendar/pipeline is fixed per tenant in config, not chosen by the model.
- **Per-tenant OAuth.** Tokens live in the tenant store (PR #2) keyed by `tenant_id`; until #2 lands, `RUNNRR_TENANT_SECRETS_DIR` holds one JSON per tenant (git-ignored). Adapter handlers receive `tenant_id` through `ToolContext`; a missing token returns a `ToolResult(is_error=True)` telling the model to ask the business to connect the account — never a traceback.
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

## Acceptance (from the contract tests on `feat/calendar-crm-adapters`)

- `test_book_appointment_and_crm_note_require_approval_by_default` — Both ToolDefs declare requires_approval=True; a profile cannot relax it.
- `test_schemas_reject_out_of_allowlist_arguments` — duration_min=45, a summary over 120 chars, or an extra 'calendar_id' key is rejected at schema validation, before any handler runs.
- `test_missing_tenant_token_returns_tool_error_not_exception` — No OAuth token for the tenant → ToolResult(is_error=True) with a connect-your-account message; no traceback, no provider-visible secret.
- `test_calendar_insert_uses_approval_id_as_ical_uid` — Approving the same proposal twice sends the same iCalUID → one event.
- `test_oauth_refresh_on_expired_token` — A 401 from the calendar API triggers one refresh and one retry.
- `test_preview_tools_unchanged` — lead_capture_preview / checkout_link_preview still return previews and are not aliased to the live adapters.
