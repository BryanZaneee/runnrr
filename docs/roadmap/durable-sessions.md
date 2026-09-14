> **Single-tenant note (2026-09-06).** Runnrr is one runtime per business. Ignore every
> `tenant_id` and PR #2 reference below: sessions and audit rows carry `user_id` (an
> employee of the business) instead. `X-Admin-Token` / `ADMIN_TOKEN` are replaced by
> Supabase `require_user` (see `supabase-auth.md`). Env names use the `RUNNRR_*` prefix and
> `backend/` is `runnrr/`. Where this design and `docs/plans/runnrr-analysis.md` disagree,
> the analysis wins; the divergence is called out at the top of the file where it matters.

> **Divergence:** the implemented design (P3a in `runnrr-analysis.md`) uses one shared `data/runnrr.sqlite3`, plain functions in `runnrr/store.py` (no `SessionStore` Protocol), an `epoch` column bumped on reset instead of a marker row, a frozen `system_prompt`/`tools_json` per session, FTS5 search, and a sessions API. The problem statement and acceptance below still apply.

# feat/durable-sessions

**Status:** prepared (design + skipped contract tests). No implementation yet.

## Problem

`SESSIONS` in `backend/app.py` is a process-local dict swept by `SESSION_TTL_SECONDS`. A restart, a deploy, or the TTL drops every conversation. Runnrr channels (SMS, voice) need a conversation to resume hours later from the same phone number, and the control plane (PR #2) needs sessions attributable to a `tenant_id`.

## Design

- One small store behind the existing dict, same shape as `SessionDict` (`messages`, `last_seen`, `provider`, `profile`) plus `profile_id` and nullable `tenant_id`.
- **SQLite via stdlib `sqlite3`**, single file at `RUNNRR_SESSION_DB` (default `data/sessions.sqlite3`; `:memory:` keeps today's behavior for tests). No ORM, no new dependency. Postgres later is a config swap only if #2 lands on Postgres.
- Write-through: `chat()` loads the row on first touch, keeps the in-memory dict as a per-process cache, and appends the new turns after `run_conversation_stream` finishes. Messages are stored **append-only** (one row per message, ordered) so the persisted transcript is exactly the prefix the provider cache saw — never rewritten.
- TTL sweep moves from the dict to a `DELETE WHERE last_seen < ?` on the same cadence. `MAX_ACTIVE_SESSIONS` counts live rows.
- Profile/model switch still resets `messages` (existing contract); the reset is an appended `reset` marker row, not a delete, so audit (feat/audit-log-kill-switch) keeps the old turns.

## API sketch

No new endpoints. `POST /api/chat` semantics unchanged; `session_id` simply works across restarts.

```python
# backend/sessions.py
class SessionStore(Protocol):
    def load(self, session_id: str) -> SessionDict | None: ...
    def append(self, session_id: str, messages: list[dict], *, profile_id: str, tenant_id: str | None) -> None: ...
    def reset(self, session_id: str, *, profile_id: str, provider: str) -> None: ...
    def sweep(self, older_than: float) -> int: ...
    def count(self) -> int: ...

class SqliteSessionStore: ...  # the only implementation
```

Schema: `sessions(id TEXT PK, profile_id, tenant_id NULL, provider, last_seen REAL)` and `messages(session_id, seq INTEGER, role, content_json, PRIMARY KEY(session_id, seq))`.

## Tests to write

See `tests/test_durable_sessions_contract.py` (skipped). Key one: build the app with a file-backed store, POST a turn, **construct a fresh app/store against the same file** (simulates uvicorn restart), POST the same `session_id`, assert the first turn is in `messages` sent to the provider.

## Out of scope

Twilio, auth UI, multi-worker locking (still `workers=1`), Postgres.

## Dependencies

None to merge. Conceptually feeds PR #2 (`tenant_id` column is nullable until then) and every channel branch.

## Acceptance

Kill uvicorn, start again, POST the same `session_id` → history still there.

## Acceptance (from the contract tests on `feat/durable-sessions`)

- `test_session_survives_process_restart` — POST /api/chat with session_id S against a file-backed store; build a fresh app + store on the same file (simulated uvicorn restart); POST S again; the provider receives the first turn's user+assistant messages as prefix.
- `test_session_row_carries_profile_id_and_nullable_tenant_id` — Stored session exposes profile_id == the profile used; tenant_id is None until PR #2 supplies one.
- `test_messages_are_append_only` — Two turns produce strictly increasing seq rows; no row is ever updated or deleted by a normal turn (prefix-cache rule).
- `test_profile_switch_resets_messages_without_deleting_rows` — Switching profile mid-session yields an empty messages list on the next turn (existing contract) while the old rows remain readable for audit.
- `test_ttl_sweep_removes_only_stale_sessions` — Sessions with last_seen older than SESSION_TTL_SECONDS are swept; fresh ones survive; MAX_ACTIVE_SESSIONS counts live rows.
