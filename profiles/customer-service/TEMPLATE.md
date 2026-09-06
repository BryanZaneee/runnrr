# Customer-service profile — adaptation guide

This profile ships as a working demo for a fictional neighborhood coffee shop ("Easy Coffee") so that a fresh clone of Runnrr runs end-to-end against realistic content. To adapt it for a real business, copy this folder and swap the parts called out below.

## Quickstart

1. Copy this folder: `cp -r profiles/customer-service profiles/<your-business-id>`.
2. In the new copy's `profile.json`, change `id`, `label`, `description`, `welcome`, `suggestions`, and `kb_root` (point it at the new folder's `kb/`).
3. In `system.md`, swap the business name and the location detail in `<role>`, and update the sign-off in `<response_style>`.
4. Replace each file in `kb/` with your real business content (see the table below).
5. Set `DEFAULT_PROFILE=<your-business-id>` in `.env`, restart the backend, and try it.

## KB files to edit

Each file in `kb/` is searchable by the agent via the `search_kb` and `read_file` tools. Keep them in plain markdown — short headings and bullet lists work best for retrieval.

| File           | What goes in it                                                                 |
| -------------- | ------------------------------------------------------------------------------- |
| `hours.md`     | Weekly hours, holiday closures, seasonal changes.                               |
| `services.md`  | What you offer — menu items, services, things customers can ask about.          |
| `pricing.md`   | Prices and price ranges. Include a "subject to change" note if relevant.        |
| `faq.md`       | The questions you get asked all the time. WiFi, parking, allergens, gift cards. |
| `policies.md`  | Refunds, lost & found, accessibility, code of conduct, privacy.                 |

Add more files if your business needs them (`catering.md`, `events.md`, `loyalty.md`, etc.). The agent's tools work on whatever markdown lives under `kb_root`.

## Tone & sign-off

The sign-off line lives in `system.md` under `<response_style>` (currently "— Easy Coffee"). Update it to match your business voice. The `<role>` section also names the business — swap it there too.

## Welcome message + suggestions

These live in `profile.json`:
- `welcome` — the first message the user sees in the chat widget.
- `suggestions` — three quick-tap prompts shown under the welcome.

Pick suggestions that map to questions the agent can actually answer from your KB (otherwise users will tap a suggestion and immediately get the off-KB fallback).

## Tools

The bundled allowlist is `["list_kb", "read_file", "search_kb"]` — KB-only, no web search, no side effects. This is the recommended baseline. Add `web_search` only if your business genuinely needs live external info (e.g., weather, traffic). Adding it widens the surface for off-script answers.

## Adding MCP servers

The `mcp_servers` field on `profile.json` is parsed by the engine but not yet wired up — the integration is a follow-up task. You can populate the field today; it will activate when the integration ships.

The expected shape mirrors the standard MCP stdio config:

```json
"mcp_servers": [
  {
    "name": "calendar",
    "command": "npx",
    "args": ["-y", "@some-org/calendar-mcp"],
    "env": { "CALENDAR_API_KEY": "..." }
  }
]
```

The `name` becomes a prefix on the tool names exposed by that MCP server (so the agent can disambiguate two servers that both expose a `book` tool). Until the engine integration lands, populating this field has no runtime effect — but the agent switcher panel in the web UI will show the configured server names so visitors see what additional knowledge sources a profile would have.

## Branding / theming

Profiles can include optional brand metadata for the web UI to consume:

```json
"brand": {
  "accent": "#f0642f",
  "accent_dark": "#7a2f17",
  "accent_soft": "#fff0e7",
  "hero_icon": " ((\n [__]",
  "intro_ascii_name": "Easy Coffee",
  "input_placeholder": "ask Easy Coffee about hours, menu, ordering..."
}
```

The backend exposes this through `/api/profile` and `/api/profiles`. Full frontend theming support is intentionally a separate web pass; until that lands, treat these fields as profile metadata that future UI work can render consistently.
