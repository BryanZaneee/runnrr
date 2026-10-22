# Saved threads

The workstation saves threads and provider conversation context in SQLite at
`data/sessions.sqlite3`; override this with `RUNNRR_SESSION_DB`. No database
service is needed. Keep one runtime worker: active requests still use an
in-memory busy guard. Back up this file with the runtime stopped.

A browser workspace key owns its threads. The browser stores that key, not
transcripts. Clearing browser storage loses access to the saved workspace;
there is no account recovery or cross-device sign-in. The database contains
conversation content and must be protected like other private runtime data.
Legacy API clients without `X-Workspace-Owner` retain temporary sessions.

## Behavior

- Titles, drafts, pins, and shelf state save automatically. Drafts save after
  a short typing pause; allow that save to finish before closing the page.
- Completed responses and provider context survive reloads, inactivity, and
  runtime restarts. Assistant, model, and project stay bound to the thread.
- Snooze hides a thread until its deadline. It returns to the main section on
  expiry or the next app load. No agent work is scheduled.
- Settle moves a thread to the settled section until manually restored.
- Interrupted turns are marked incomplete. Partial provider messages are
  rolled back so unmatched tool calls cannot contaminate future context.
  A hard runtime shutdown may retain only the prompt of an unfinished turn.
  The UI asks for a fresh thread rather than silently retrying paid work.
- Delete hides a thread; immediate Undo restores its transcript and context.
  Deleted records are purged on database access after 24 hours.

The store allows 100 active threads per workspace and 1,000 across the runtime.
The existing per-thread turn limit still applies; saved provider context plus
the current turn's events are capped at 2 MB. Storage failures are shown as errors.
This is a small demonstration store, not a multi-user account system. Multiple
open tabs share persisted data but do not receive live updates from each other.

## Support demonstration

Open Workspace → Customer service demo and start a run. Three simulated
customers each get a separate customer-service thread. The monitor shows real
model output and tool activity; Open full thread displays the whole response.
The run stops on errors or Stop run. Keep the page open while it works. Existing
conversation threads survive reloads, but the in-progress demo queue does not
restart automatically. Nothing is sent to an external customer inbox.
