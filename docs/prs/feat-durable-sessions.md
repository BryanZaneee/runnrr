# feat/durable-sessions

**Status:** prepared (design + skipped contract tests). No implementation yet.

## Problem

`SESSIONS` in `backend/app.py` is a process-local dict swept by `SESSION_TTL_SECONDS`. A restart, a deploy, or the TTL drops every conversation. Runnrr channels (SMS, voice) need a conversation to resume hours later from the same phone number, and the control plane (PR #2) needs sessions attributable to a `tenant_id`.

## Design

- One small store behind the existing dict, same shape as `SessionDict` (`messages`, `last_seen`, `provider`, `profile`) plus `profile_id` and nullable `tenant_id`.
- **SQLite via stdlib `sqlite3`**, single file at `EASYAGENT_SESSION_DB` (default `data/sessions.sqlite3`; `:memory:` keeps today's behavior for tests). No ORM, no new dependency. Postgres later is a config swap only if #2 lands on Postgres.
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
