> **Single-tenant note (2026-09-06).** Runnrr is one runtime per business. Ignore every
> `tenant_id` and PR #2 reference below: sessions and audit rows carry `user_id` (an
> employee of the business) instead. `X-Admin-Token` / `ADMIN_TOKEN` are replaced by
> Supabase `require_user` (see `supabase-auth.md`). `EASYAGENT_*` env names are `RUNNRR_*`,
> `backend/` is `runnrr/`. Where this design and `docs/plans/runnrr-analysis.md` disagree,
> the analysis wins; the divergence is called out at the top of the file where it matters.

> **Divergence:** audit rows live in the shared SQLite file (P3c), not a JSONL stream; `disabled` is an `agent_flags` table, not `disabled.json`.

# feat/audit-log-kill-switch

**Status:** prepared (design + skipped contract tests). No implementation yet.

## Problem

Runnrr sells "AI drafts, people send" to businesses that will ask two questions on day one: *what did it say and do?* and *how do I turn it off right now?* Today `_instrument()` logs one JSON line per completed turn (tokens, cost, latency) — no prompt, no tool args, no results — and the only off switch is stopping the service for every tenant at once.

## Design

**Audit log.** One append-only JSONL stream (`EASYAGENT_AUDIT_LOG`, default `data/audit.jsonl`; or the durable-sessions SQLite file if that branch lands first) with one record per event: `user_message`, `tool_call` (name + arguments), `tool_result` (truncated output + `is_error`), `assistant_message`, `disabled_rejection`. Every record carries `ts`, `session_id`, `profile_id`, `tenant_id`, `turn_id`, `model_id`. Emitted from the existing `_instrument()` wrapper by watching the normalized event stream — no changes inside the loop or providers.

**No secrets in plaintext (cheap version).** Before writing, run the record through a regex scrub for obvious keys (`sk-…`, `AIza…`, `xoxb-…`, bearer tokens, `TWILIO_AUTH_TOKEN`-shaped strings) and replace with `[REDACTED]`. Full DLP lives in feat/dlp-redact and will reuse this hook.

**Kill switch.** `POST /api/agents/{id}/disable` and `POST /api/agents/{id}/enable`, where `{id}` is a profile id today and a tenant agent id once PR #2 lands. Disabled ids live in a small set persisted alongside the audit log (`data/disabled.json`) so a restart doesn't silently re-enable. `chat()` checks it **before** the provider call and again **before each tool hop** and returns 503 `agent disabled` — an in-flight turn stops at the next hop, it does not wait for `MAX_TOOL_HOPS`.

Auth on the switch: reuse the builder's `X-Builder-Owner` shape as an `X-Admin-Token` header (`ADMIN_TOKEN` env) until PR #2 supplies real auth. Missing/wrong token → 403. No token configured → endpoint returns 404 (not exposed).

## API sketch

```
POST /api/agents/{id}/disable   X-Admin-Token: …   → 200 {"id": …, "disabled": true}
POST /api/agents/{id}/enable    X-Admin-Token: …   → 200 {"id": …, "disabled": false}
GET  /api/agents/{id}           X-Admin-Token: …   → 200 {"id": …, "disabled": bool}
POST /api/chat  (disabled profile)                 → 503 {"detail": "agent disabled"}
```

Audit record: `{"ts","kind","session_id","profile_id","tenant_id","turn_id","model_id","payload"}`.

## Tests to write

See `tests/test_audit_log_kill_switch_contract.py` (skipped).

## Out of scope

Full SIEM, log shipping, retention policies, per-user attribution beyond IP, UI.

## Dependencies

None hard. feat/durable-sessions gives the audit log a `tenant_id`; until then it is `null`. feat/hitl-actions reads the audit log for approval context.

## Acceptance (from the contract tests on `feat/audit-log-kill-switch`)

- `test_turn_writes_prompt_tool_call_result_and_reply_records` — One chat turn with one tool hop appends user_message, tool_call, tool_result, assistant_message records, all sharing session_id/turn_id.
- `test_audit_records_scrub_obvious_secrets` — A user message containing an sk-… key is stored as [REDACTED].
- `test_disable_endpoint_requires_admin_token` — POST /api/agents/{id}/disable without X-Admin-Token → 403; with ADMIN_TOKEN unset the endpoint is 404.
- `test_disabled_agent_rejects_chat_with_503` — After POST /api/agents/{id}/disable, POST /api/chat for that profile → 503 'agent disabled' and a disabled_rejection audit record.
- `test_disable_stops_in_flight_turn_at_next_hop` — Disable mid-turn (between tool hops) → the loop stops before the next provider call instead of running to MAX_TOOL_HOPS.
- `test_disabled_set_survives_restart` — Disabled ids persist to disk; a fresh app on the same data dir still rejects the agent.
