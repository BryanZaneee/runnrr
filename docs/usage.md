# Model usage and costs

Open **Workspace → Usage & costs** for runtime-wide chat analytics. Expand the
usage line beneath a response for that turn, or open **Thread details** for the
current conversation. History starts with this implementation; older stdout logs
are not imported.

The panel includes input, uncached input, cache reads/writes, output, reasoning,
processed totals, cache-hit rate, estimated USD by category, gross cache-read
savings, turns, distinct sessions, model calls, tool calls/failures, failed turns,
average latency and time to first token. It groups activity by UTC day, model,
provider vendor and assistant, with period/model/assistant filters. Per-turn
metrics also show time to first response text and the last reported input as a
share of the model's configured context window. This is not next-prompt usage;
output and later tool results can change the next prompt.

The runtime's existing daily token budget is shown separately. It includes
outstanding conservative reservations and other budgeted work, so it need not
match reported chat tokens. These analytics cover `/api/chat`, not evals,
embeddings, rerankers, tool API fees or provider-account subscription quotas.

## Accounting contract v2

Reasoning is **included in output**. `input_tokens` includes both cache fields.
Therefore:

- Processed/billable total = input + output.
- Reasoning is a subset of output, never another charge.
- Cache read/write are subsets of input, never additional tokens.
- Uncached input = input − cache read − cache write.

Anthropic/OpenAI-compatible output is kept inclusive. Gemini thoughts are added
to candidate output. Character-based fallback estimates follow the same contract.
Anthropic's reasoning split is approximate even when its total output is exact.

New SSE `usage` frames, terminal `metrics` frames, `chat_complete` logs and eval
records carry `usage_version: 2`. External consumers must not add reasoning to
output for v2. Earlier records without that version retain their old meaning;
eval summary generation reads them accordingly. Historical eval files and the
separately frozen public-site deployment are not rewritten.

`model_start` announces a provider attempt. `usage` still arrives once per
reported hop; `metrics` is the accumulated turn snapshot, emitted before `done`
or `error`. **Replace** a turn's cumulative values with that snapshot; don't add
it to previous usage frames. `usage_status` is `complete` when every started
call has a report and the turn ends normally, `partial` when some usage is known
but the turn failed or a call is missing, and `unavailable` without any reports.
`usage_estimated` and `reasoning_estimated` describe precision independently.
Interrupted requests retain whatever reports reached the server.

Costs are captured at turn time using `runnrr/pricing.py`, not a provider invoice. The existing table prices
Haiku 4.5 and DeepSeek V4 Flash; other models remain explicitly unpriced.
DeepSeek's configured off-peak rate is a floor. No rates are guessed or fetched
at request time. Output cost includes reasoning. Cache savings compare cached
reads with uncached input and exclude cache-write premiums. Mixed-price totals
expose `known_cost_usd` plus `unpriced_turns`; `cost_usd` is null if any turn is
unpriced. Partial reports can still understate known costs.

## Storage and API

`RUNNRR_USAGE_PATH` defaults to `data/usage.sqlite` (gitignored). SQLite stores one
idempotent record per turn: numeric usage/timing, UTC start time, model, provider,
profile, status and a session-ID hash for distinct counts. It stores **no prompts,
responses, reasoning text, tool arguments/results, IPs or raw session IDs**.
Transcripts and thread organization are saved separately in `data/sessions.sqlite3`. Back up this file to keep
usage history across host migrations; deleting a page-local thread does not
delete its accounting record. No automatic retention cleanup runs.

`GET /api/usage?since=2026-10-01&until=2026-10-16&model=...&profile=...` returns
`totals`, `days`, `models`, `providers`, and `profiles`. Dates are inclusive UTC;
the default is the last 30 days, maximum 366 days per query. Turns are grouped
by their start date, including turns that cross midnight. Parameters are bound
SQL values. The endpoint returns aggregate data only, without session hashes,
turn IDs or individual records. Like the existing runtime budget endpoint, this
is runtime-wide and currently unauthenticated, not an owner-scoped billing API.
Distinct session counts must not be added across groups.

Persistence errors are logged without failing a chat. History reads fail with a
503 rather than showing invented zero totals. A hard process kill can lose the
current unfinalized turn; budget reservations remain the separate spending guard.

## Verification

Run `.venv/bin/python -m pytest -q` and `node tests/unit/workstation.mjs`.
Evaluate `tests/browser/usage-browser.mjs` on the running workstation for synthetic chat,
history, filtering, escaping and failure checks. It mocks chat requests, uses an
isolated frame, and removes it afterward. Reload cached frontend assets before
browser checks after edits.


### Incomplete turns

Output-limit stops are recorded as `max_tokens`, with partial usage coverage,
and the workstation labels the answer incomplete. Failed or interrupted turns
roll back their backend conversation additions to avoid dangling tool calls;
the visible partial text remains available in the current browser page.
