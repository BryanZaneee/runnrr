> **Single-tenant note (2026-09-06).** Runnrr is one runtime per business. Ignore every
> `tenant_id` and PR #2 reference below: sessions and audit rows carry `user_id` (an
> employee of the business) instead. `X-Admin-Token` / `ADMIN_TOKEN` are replaced by
> Supabase `require_user` (see `supabase-auth.md`). Env names use the `RUNNRR_*` prefix and
> `backend/` is `runnrr/`. Where this design and `docs/plans/runnrr-analysis.md` disagree,
> the analysis wins; the divergence is called out at the top of the file where it matters.

# feat/mcp-runtime

**Status:** prepared (design + skipped contract tests). No implementation yet.

## Problem

`AgentProfile.mcp_servers` is parsed and shown in the UI, but no client ever connects (see the `TODO(mcp)` block at the top of `run_conversation_stream` in `backend/agent.py`). Runnrr customers with an existing MCP server (their own CRM wrapper, an internal docs server) should be able to use it from a scoped profile without us writing a native `ToolDef` per integration.

## Design

- Implement exactly the `TODO(mcp)` sketch, in `backend/mcp.py`, called from the loop — **not** from providers: on first use per session, spawn each declared stdio server, `initialize`, `tools/list`, and merge the returned schemas into the tool catalog passed to `provider.tools_for_provider(...)`. `tool_use_complete` events whose name belongs to an MCP server are dispatched to that client instead of `run_tool`; results are wrapped in the same `ToolResult`.
- Tool names are namespaced `mcp__{server}__{tool}` so they cannot shadow native tools; the profile's `tools` allowlist must list them explicitly (or `"mcp__{server}__*"`) — declaring a server does not expose its tools.
- **Sandbox + allowlist.** `RUNNRR_MCP_ALLOWED_COMMANDS` is a JSON list of permitted executables (absolute paths); a server whose `command` is not on it fails profile load. Servers run with a minimal env (only keys named in the server config's `env`), `cwd` = the profile dir, no inherited provider keys, and a per-call timeout (`PROVIDER_TIMEOUT_SECONDS` reuse). Output is capped like native tool output.
- **Never on SMS/voice profiles.** A profile with `channels.sms` or `channels.voice` and non-empty `mcp_servers` is a load-time error (also asserted in feat/channel-voice).
- Schemas merged into the catalog are frozen for the session (prefix-cache rule): `tools/list` runs once per session, and a server whose tool list changes mid-session is ignored until the next session.
- Transport: stdio only. Use the `mcp` PyPI package if it's already pulled in by another dependency; otherwise the JSON-RPC-over-stdio surface we need (initialize, tools/list, tools/call) is ~80 lines with stdlib `asyncio.subprocess` — decide at implementation time, prefer no new dependency.

## API sketch

No new endpoints. `GET /api/profile` already surfaces `mcp_servers`; add `mcp_status: {server: "connected"|"error"|"not-started"}` to `/api/status`.

## Tests to write

See `tests/test_mcp_runtime_contract.py` (skipped). Tests use a tiny in-repo fake MCP server script (`tests/fixtures/fake_mcp_server.py`) that speaks the minimal protocol.

## Out of scope

Arbitrary GitHub MCP servers, HTTP/SSE MCP transports, MCP resources/prompts (tools only), a marketplace UI.

## Dependencies

None hard. feat/hitl-actions so MCP tools can be marked `requires_approval` via profile `tool_approval`.

## Acceptance (from the contract tests on `feat/mcp-runtime`)

- `test_declared_server_tools_appear_namespaced_in_catalog` — A profile declaring server 'notes' whose tools/list returns 'add' exposes 'mcp__notes__add' to the provider — only if the allowlist names it.
- `test_mcp_tool_use_is_dispatched_to_client_not_run_tool` — tool_use_complete for mcp__notes__add calls the fake server and returns a ToolResult; run_tool is never invoked for that name.
- `test_command_not_on_allowlist_fails_profile_load` — mcp_servers[].command absent from RUNNRR_MCP_ALLOWED_COMMANDS → profile load error, no subprocess spawned.
- `test_server_env_is_minimal_and_excludes_provider_keys` — The spawned server sees only the env keys named in its config; no ANTHROPIC_API_KEY / OPENAI_API_KEY etc. leak in.
- `test_sms_and_voice_profiles_cannot_declare_mcp_servers` — channels.sms or channels.voice + non-empty mcp_servers → load-time error.
- `test_tool_list_frozen_per_session` — tools/list is called once per session; a changed list mid-session does not alter the schemas sent to the provider (prefix-cache rule).
