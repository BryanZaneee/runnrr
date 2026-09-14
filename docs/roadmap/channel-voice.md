> **Single-tenant note (2026-09-06).** Runnrr is one runtime per business. Ignore every
> `tenant_id` and PR #2 reference below: sessions and audit rows carry `user_id` (an
> employee of the business) instead. `X-Admin-Token` / `ADMIN_TOKEN` are replaced by
> Supabase `require_user` (see `supabase-auth.md`). Env names use the `RUNNRR_*` prefix and
> `backend/` is `runnrr/`. Where this design and `docs/plans/runnrr-analysis.md` disagree,
> the analysis wins; the divergence is called out at the top of the file where it matters.

# feat/channel-voice (inbound only)

**Status:** prepared (design + skipped contract tests). No implementation yet. **Branched from `main`; rebase onto `feat/channel-webhooks` once that branch has real code** — voice reuses its number map, signature check, and session-key convention.

## Problem

"24/7 inbound calls" is on the Runnrr menu. A caller to a business's Twilio number should reach the same scoped agent that answers SMS, with a tiny tool pack, and be able to book, leave a note, or get transferred to a person.

## Design

- Inbound PSTN via **Twilio Media Streams**: `POST /webhooks/twilio/voice` returns TwiML `<Connect><Stream url="wss://…/webhooks/twilio/voice/stream"/></Connect>`; the WebSocket receives 8 kHz μ-law audio frames.
- Pipeline per call: STT (streaming) → `run_conversation_stream` on session `voice:{tenant}:{from}` → TTS → μ-law frames back on the stream. STT/TTS vendors sit behind two tiny Protocols (`SpeechToText`, `TextToSpeech`) with env-selected implementations; first implementation is whichever the operator has a key for (`RUNNRR_STT`, `RUNNRR_TTS`). No vendor SDK is a hard dependency.
- Turn-taking v1: endpoint on STT "final" segments; barge-in cancels TTS. Good enough for FAQ/booking; not a conversational-AI research project.
- **Tools (the whole pack):** `search_kb`/`read_file` (FAQ), `book_appointment`, `crm_note`, `transfer_to_human` (returns TwiML `<Dial>` to a configured human number and ends the AI leg). Book and note are `requires_approval` unless the profile explicitly relaxes that for its own calendar (feat/hitl-actions, feat/calendar-crm-adapters).
- Same profile shape as SMS: `"channels": {"voice": {"transfer_number": "+1…", "greeting": "…"}}`. **No shell, no MCP, no browser, no web_search** on voice profiles — `mcp_servers` non-empty on a voice profile is a load-time error.
- Volatile data (caller id, time) goes in the user turn (prefix-cache rule). The greeting is TTS'd directly, not generated, so the first audio is instant.

## Recording / compliance

README warning only in this pass: call recording and consent rules vary by state (two-party consent). The adapter does **not** record by default; if `RUNNRR_VOICE_RECORD=1` is ever added it must play a consent notice first. Outbound AI voice is explicitly not built (TCPA).

## API sketch

```
POST /webhooks/twilio/voice          → 200 text/xml  <Response><Connect><Stream url=…/></Connect></Response>
WS   /webhooks/twilio/voice/stream   Twilio Media Streams protocol (start/media/stop events)
```

Env: reuses `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER_MAP`; adds `RUNNRR_STT`, `RUNNRR_TTS`, vendor keys.

## Tests to write

See `tests/test_channel_voice_contract.py` (skipped). Audio path tested with a fake STT that yields scripted transcripts and a fake TTS that records what it was asked to say — no vendor calls.

## Out of scope

Outbound AI voice, recording/consent beyond the README warning, voicemail, IVR menus, hold music, multi-language.

## Dependencies

feat/channel-webhooks (hard — shared adapter plumbing), feat/durable-sessions, feat/hitl-actions.

## Acceptance (from the contract tests on `feat/channel-voice`)

- `test_voice_webhook_returns_connect_stream_twiml` — POST /webhooks/twilio/voice with a valid signature → TwiML containing <Connect><Stream url=…/></Connect>.
- `test_final_transcript_runs_agent_turn_and_tts_reply` — Fake STT yields a final segment → one run_conversation_stream call on session 'voice:{tenant}:{from}' → fake TTS receives the agent's text.
- `test_barge_in_cancels_tts` — New speech during TTS playback stops the current TTS stream.
- `test_transfer_to_human_ends_ai_leg_with_dial` — transfer_to_human tool result → <Dial> to the profile's transfer_number and no further agent turns on that call.
- `test_voice_profile_rejects_mcp_shell_browser_tools` — A profile with channels.voice and non-empty mcp_servers, or with web_search/fetch_url_text in tools, fails to load.
- `test_no_recording_by_default` — The voice handler never sets <Record> or Twilio recording params unless RUNNRR_VOICE_RECORD=1 (which is not implemented in this branch).
