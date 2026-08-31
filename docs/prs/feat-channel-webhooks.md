# feat/channel-webhooks (SMS first)

**Status:** prepared (design + skipped contract tests). No implementation yet. **No Twilio keys in repo — env vars only.**

## Problem

Runnrr's first inbound channel is SMS on a business's Twilio number. The engine only speaks `POST /api/chat` over SSE. We need the smallest adapter that turns an inbound text into a chat turn and a reply — without a second harness (see README "Runnrr engine map").

## Design

- New router `backend/channels/twilio_sms.py` mounted at `POST /webhooks/twilio/sms`. Twilio POSTs `application/x-www-form-urlencoded` with `From`, `To`, `Body`, `MessageSid`.
- **Signature check.** Validate `X-Twilio-Signature` (HMAC-SHA1 of full URL + sorted POST params, keyed by `TWILIO_AUTH_TOKEN`) using stdlib `hmac`/`hashlib` — ~15 lines, no `twilio` SDK. `EASYAGENT_TWILIO_SKIP_VERIFY=1` disables it **only** when `ENV != production`; tests set it. Missing token in production → 503 at startup, never "verify off by default".
- **Routing.** `To` (the business's number) → `tenant_id` + `profile_id` via `TWILIO_NUMBER_MAP` env (JSON `{"+15551234567": {"tenant": "acme", "profile": "inbound-sms"}}`) until PR #2 supplies a tenants table. Unknown `To` → 404, logged.
- **Session key** `sms:{tenant}:{from}` — durable (feat/durable-sessions) so a customer texting back tomorrow continues the thread.
- **Call the engine in-process**, not over HTTP: reuse the same `run_conversation_stream(...)` the `/api/chat` handler uses, collect `text_delta` into one string. Per-turn volatile data (`From`, time, channel) goes in the user turn, not the system prompt (prefix-cache rule).
- **Auto-reply policy.** Reply with TwiML `<Response><Message>…</Message></Response>` only when the profile declares `"channels": {"sms": {"auto_reply": true}}` — i.e. an FAQ-safe profile with a tiny tool pack. Otherwise return empty `<Response/>` (Twilio sends nothing) and queue the draft as an approval (feat/hitl-actions): AI drafts, people send.
- Reply length: truncate to 3 segments (~480 chars) with "…" and log; SMS is not the place for essays.

## API sketch

```
POST /webhooks/twilio/sms   (form: From, To, Body, MessageSid; header X-Twilio-Signature)
  → 200 text/xml  <Response><Message>reply</Message></Response>   (auto_reply profile)
  → 200 text/xml  <Response/>                                      (draft queued for approval)
  → 403           bad signature
  → 404           unmapped To number
```

Env: `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER_MAP`, `EASYAGENT_TWILIO_SKIP_VERIFY` (non-prod only). Add all three to `.env.example` with empty values.

## Tests to write

See `tests/test_channel_webhooks_contract.py` (skipped). Signature test uses a known-answer vector computed with stdlib hmac; no network.

## Out of scope

Voice (feat/channel-voice), WhatsApp, MMS, outbound campaigns / TCPA outbound, delivery receipts, opt-out keyword handling beyond passing STOP through to Twilio's built-in handling.

## Dependencies

feat/durable-sessions (session key must outlive the process). feat/hitl-actions for the non-auto-reply path; until it lands, non-auto-reply profiles simply log the draft.
