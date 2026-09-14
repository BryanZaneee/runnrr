# Runnrr Feature Inventory
### Reverse-engineered from the Hermes Agent desktop app screenshots (v0.21.0)

Goal: a business-facing agent workstation with the same feature surface as Hermes Agent. This doc lists every piece of functionality visible in the screenshots, grouped by area, then proposes a data model, an epic/PR breakdown, and a roadmap. Items marked **(biz)** are additions Hermes doesn't have but a business product will need.

---

## 1. App shell and navigation

| Feature | Detail seen |
|---|---|
| Desktop app chrome | macOS traffic lights, sidebar collapse toggle, split-view toggle, top-right icon cluster (layout, chat, help, settings, right panel toggle) |
| Left sidebar with two top tabs | **SESSIONS** and **BOTS**. Switching tabs swaps the whole sidebar body |
| Primary nav (Sessions tab) | New session (⌘N), Capabilities, Messaging, Artifacts, Scheduled jobs |
| Session search | Search input in sidebar, ⌘K style |
| Pinned sessions | "Shift-click a chat to pin" hint, PINNED section |
| Session list | Grouped by date (Today / YESTERDAY), each row shows title + relative time ("now", "1m", "1d"), status dot |
| Multi-tab workspace | Open sessions and group chats as tabs across the top of the main pane, with a "+" to open more |
| Profile switcher | Bottom-left row of small avatar icons plus "+", lets you swap between agent profiles |
| Empty state | Large wordmark, tagline, "No sessions yet", "+ New project" |
| Status bar | Bottom bar: gateway status ("Gateway: inference unavailable" warning vs "Gateway ready"), logged-in username, version + commit hash + update delta ("v0.21.0 (+4297)") |
| Theme | Dark and light themes both visible, so a theme toggle exists |
| Keyboard shortcuts | ⌘N new session, ⌘K search, "/" focuses skill search |

---

## 2. Onboarding and provider setup

First-run modal: "Let's get you set up. Connect a model provider to start chatting. Most options take one click."

**Collapsed view**
- Recommended option with a RECOMMENDED badge (the vendor's own subscription: "one subscription, 300+ frontier models")
- "Run models locally" (no account, download and run on this machine)
- "Other providers ∨" expander
- Footer links: "I'll choose a provider later" / "I have an API key"

**Expanded provider list** (each row = name, one-line description, chevron)
- Subscription / OAuth style (opens a browser verification page, connects automatically): ChatGPT or Codex subscription, MiniMax, xAI Grok
- Terminal sign-in style: Qwen Code ("sign in once in your terminal, then come back")
- Direct API key style: Fireworks AI, Anthropic API key
- Collapse ∧

**API key entry screen**
- "Back to sign in" link
- Two-column grid of providers, scrollable: Fireworks AI, OpenRouter (one key, many models), OpenAI, Google Gemini, xAI Grok, Local/custom endpoint (self-hosted), Actual Computer, Alibaba Cloud (4 variants: Coding/Token plan, China/global), Arcee AI, more below the fold
- Selected provider shows description, "Get a key ↗" deep link, "Paste API key" input, Connect button
- "I'll choose a provider later"

**Runtime behavior implied**
- Provider errors surface in-chat as red cards: `HTTP 404: model: claude-sonnet-4-20250514` with actions **Retry, Switch provider, Open logs, Send diagnostics, Copy error details**
- Agent init failure banner: "No inference provider configured. Run `hermes model` to choose a provider and model, or set an API key (OPENROUTER_API_KEY, OPENAI_API_KEY, etc.) in ~/.hermes/.env" (so CLI and env-file config paths coexist with the GUI)
- Model can be changed mid-session; a "model changed" divider is inserted in the transcript

---

## 3. Sessions and chat

| Feature | Detail seen |
|---|---|
| Composer | "+" attach button, placeholder text that varies ("Give Hermes a task", "Push it further", "What's next?", "Send a follow-up"), attached-file chips with x (e.g. `hello.html`), mic button (speech-to-text), two extra icons (likely tools/voice), round send/stop button |
| Model selector in composer | Shows model name + reasoning effort: "Opus 4.6 · Med", "Sonnet 4 · Med", "Muse Spark 1.3 Con..." with dropdown |
| User messages | Full-width dark rounded bubbles |
| Assistant messages | Plain text, markdown rendered |
| Thinking blocks | Collapsible "Thinking · 9s" / "Thought for 16s" with summary lines of the plan |
| Tool-run rows | Compact inline rows: "Ran `uv run --with reportlab python /Users/.../gen_pdf.py`", "Ran `mkdir -p ~/Desktop/hello-files` + 3 commands" (command collapsing) |
| Diff cards | Per-file cards with filename, `+17 -1` stats, chevron, close x, syntax highlighted green/red diff, copy button |
| Generated-file rows | Numbered list "1. TXT, boxed ASCII postcard" then a row with file icon, filename, **Download**, **Hide** |
| Image attachments | Inline thumbnail of uploaded image in the transcript |
| Clarifying Questions widget | Interactive form injected by the agent: "0 of 2 answered" counter, multiple-choice with A/B/C/D/E keys and a "(Recommended)" tag, "Other (type your answer)" option, free-text question, **Skip** / **Confirm and continue** |
| Message action bar | Small icon row under assistant messages (copy, regenerate, etc.) |
| Scroll-to-bottom | Floating down-arrow button |
| Session titles | Auto-generated from first message ("Hey man", "yo") |

---

## 4. Right-hand file preview panel

Opens alongside the chat (split view) when the agent produces files.

- Tab strip of open files (HELLO.TXT, HELLO.MD, HELLO.PY, HELLO.HTML, HELLO.PDF, HELLO.PPTX, HELLO.CSV, HELLO.DOCX, HELLO.XLSX)
- Per-type viewers:
  - Text/code: line numbers, syntax coloring, **Edit** button
  - Markdown: **PREVIEW / SOURCE** toggle + Edit
  - CSV: colorized columns
  - HTML: live rendered page with `file://` path bar
  - PDF: rendered document with download and print icons, overflow menu
  - Binary (pptx/docx/xlsx): "This looks like a binary file. Previewing may show unreadable text." with **Preview anyway**
- Agent can also act on the host OS (copied files to ~/Desktop and opened Finder)

---

## 5. Capabilities (Skills / Tools / MCP)

Three tabs across the top of the main pane with counts: **Skills 60 · Tools 23 · MCP**. Search box with contextual placeholder ("Try 'software-development'", "Try 'process_manage'"). "Most used" section at top of the list. Footer note everywhere: **"Changes apply to new sessions."**

### 5a. Skills
- List rows: name, category label (Productivity, Apple, Creative, Research), toggle, optional **learned** badge (skills the agent taught itself)
- Detail panel: title, category chip, description, metadata table: name, description, version, author (community), license (MIT), platforms [linux, macos, windows], prerequisites (env_vars, commands), metadata (tags, homepage)
- **Skills Hub** embedded browser below the detail:
  - Header nav: Docs, Skills, Download, language picker, Home, GitHub, Discord, theme toggle, Search (⌘K)
  - Hero: "Discover, search, and install from 90,696 skills across 11 registries"
  - Stats: BUILT-IN 58 · OPTIONAL 137 · COMMUNITY 90,501 · CATEGORIES 200
  - "Catalog refreshed 1 month ago · auto-rebuilt twice daily"
  - Search ("/" to focus), filter chips by source (All, Built-in, Optional, Anthropic, OpenAI, HuggingFace, NVIDIA, skills.sh, ClawHub...)
  - "Hit '+ Add to this Agent' on any skill, it installs and appears in the list above"
  - Actions: **Update installed**, **Hide the hub browser**

### 5b. Tools (tool groups)
Each row: group name, one-line description, tool count, toggle. Seen groups:

| Group | Tools | Notes |
|---|---|---|
| A2A | 5 | Agent-to-Agent protocol v1.0, off by default |
| Browser Automation | 14 | see 5c |
| Clarifying Questions | 1 | powers the Q&A widget |
| Code Execution | 1 | execute_code |
| Computer Use (macOS/Windows/Linux) | 1 | desktop control |
| Cron Jobs | 1 | create/list/pause/resume/run |
| File Operations | 4 | read, write, patch, search |
| Home Assistant | 0 | smart home, disabled |
| Image Generation | 1 | |
| Memory | 1 | persistent cross-session memory |
| Session Search | 1 | search past conversations |
| Skills | 3 | list, view, manage |
| Speech-to-Text | 0 | voice transcription |
| Spotify | 7 | disabled |
| Task Delegation | 1 | delegate_task (sub-agents) |
| Task Planning | 1 | todo_list |
| Terminal & Processes | 2 | terminal, process |

### 5c. Browser Automation detail
- Tool name chips: browser_back, browser_cdp, browser_click, browser_console, browser_dialog, browser_exec, browser_get_images, browser_navigate, browser_press, browser_scroll, browser_snapshot, browser_type, browser_vision, web_search
- **Use My Real Browser Profile** toggle: copies default browser logins/cookies into a managed snapshot, live profile never opened directly, applies to new sessions
- **Backend picker** with status badges: Local Browser (recommended, free, Ready), Lightpanda (free, local, no Chromium, Setup required), vendor cloud subscription (Needs sign-in), Camofox (free, local), Browser Use (free, local, cloud, **Active**, "This is your active backend", "No API key required", Installed ✓, **Re-run setup**), Browserbase (paid)

### 5d. MCP
Tab exists; presumably add/list MCP servers (not shown in detail).

---

## 6. Messaging (chat platform gateways)

Left list of platforms, each with status dot: Telegram, Discord, Slack, Mattermost, Matrix, WhatsApp, Signal, BlueBubbles (iMessage), Home Assistant, Email, SMS (Twilio), DingTalk, Feishu/Lark, Google Chat, WeCom (group bot), WeCom (app), Weixin/WeChat (Personal), QQ Bot, Yuanbao, more below.

Detail panel (Telegram example):
- Status chips: Disabled · Needs setup · Messaging gateway stopped
- Description: "Run [agent] from Telegram DMs, groups, and topics"
- GET YOUR CREDENTIALS: step text + **Open setup guide ↗**
- REQUIRED: Bot token (paste input with external-link icon)
- RECOMMENDED: Allowed user IDs (comma-separated) with security warning "Without this, anyone can DM your bot"
- **Save changes** button, carousel dot indicator at bottom (multi-page setup)

---

## 7. Artifacts

- Filter tabs with counts: All · Images · Files · Links, refresh button
- Empty state: "No artifacts found. Generated images and file outputs will appear here as sessions produce them."
- Aggregates outputs across all sessions

---

## 8. Scheduled jobs (cron)

Modal overlay: "Scheduled jobs · 0 jobs", search, "+" to create, close x.
- Right pane: "Schedule a prompt to run on a cron expression. [Agent] will run it and deliver results to the destination you pick" (destination = any connected messaging channel)
- **Blueprints** (templates) list: Morning briefing, Important-mail monitor, Weekly review, Workday start reminder, Custom reminder, Evening wind-down, Topic news digest, Bills & renewals reminder, Price & availability watch, Competitor news watch, Habit check-in, Hydration & movement nudge, Weekly meal plan, Daily learning drip, Gratitude & reflection prompt, On-this-day discovery
- Also reachable from a vertical "SCHEDULED JOBS" tab on the right edge of the chat view

---

## 9. Bots (named agents)

Sidebar BOTS tab: list of bots with avatar, name, last-message preview, time; icons for search and "+ new bot"; filter icon.

**New bot modal**: "A named teammate with its own memory, skills, and chat. It can message your other agents."
- Avatar builder: tabs **Bot / Generate / Upload / Pet**, grid of geometric "face" avatars + Auto, **Randomize**, **Lock face**, "Face follows the name", "Classic shapes"
- Fields: Name (slug, e.g. `inbox-triage`), Title (Inbox Triage), Description ("What should this bot help with?")
- **Advanced** expander, tabs **General / Capabilities**:
  - Clone from profile (dropdown, default)
  - Provider: Inherit (launch profile) / Model: inherited from launch profile
  - SOUL.md (optional persona file that replaces the generated persona; "Leave blank to auto-generate from name/title/description + agent-messaging roster")
  - ☑ Share keys & accounts with the main profile (subscriptions, OAuth, API keys shared not copied so token refreshes never invalidate each other; uncheck for an isolated snapshot)
  - ☐ Create empty (skip bundled skills)
- Cancel / **Create Bot**

**Bot chat**: same chat UI, big bot name wordmark + avatar, "Say something to get started." Each bot gets its own sessions, memory, and profile.

---

## 10. Group chats (multi-agent rooms)

**New group chat modal**: "Pick 2-6 bots. Local memberships sync through each Bot profile; cross-machine members stay scoped to this room."
- Search bots, checkbox list with @handles (@test-man-yaya), selected-bot chips with x
- Group avatar + **Upload**, Group name input, **Create Group (2)** with live count

**Room view**
- Header: Back, avatar, room name, "2 bots", settings gear, delete
- Collapsible **Activity** feed ("Show room activity" tooltip)
- Empty state: "Say something, every bot in this group hears the room"
- Composer: "New thread in [room]... (@name to direct, @everyone for all)", attach, **New Thread** button (threaded conversations inside rooms)
- Rooms appear as tabs alongside sessions

---

## 11. Cross-cutting behaviors

- Gateway process separate from UI (status: unavailable / ready)
- Diagnostics pipeline: Open logs, Send diagnostics, Copy error details on every error
- Config lives in both GUI and `~/.hermes/.env` + CLI (`hermes model`)
- Agent can execute on the host: run Python via uv, mkdir, open Finder, write to Desktop
- Persistent memory tool + session search tool = agent recalls across sessions
- Everything toggleable says "Changes apply to new sessions" (capabilities snapshot per session)

---

## 12. Business additions (biz)

Hermes is single-user/local. For a business product add:
- **Org + workspace model**, SSO (Google/Microsoft/SAML), roles (owner/admin/member/viewer)
- **Per-org secrets vault** for provider keys and channel tokens, with key sharing rules like the "share keys with main profile" toggle but at team level
- **Audit log** of every tool call, file write, message sent, cron run
- **Approval gates** on dangerous tools (terminal, browser with real profile, computer use)
- **Usage metering + billing** per org/bot/model
- **Hosted gateway** (cloud runner) instead of only local machine, with optional local runner for on-prem
- **Shared bots and rooms** across teammates, not just across one person's machines
- **Templates marketplace** for bots and cron blueprints tuned to business tasks (lead follow-up, invoice chasing, support triage, competitor watch)

---

## 13. Data model sketch

```
Org ─┬─ User (role)
     ├─ ProviderCredential (provider, kind: api_key|oauth|subscription|local, secret_ref, shared)
     ├─ Profile (name, default_provider, default_model, reasoning_effort, soul_md, cloned_from)
     ├─ Bot (slug, title, description, avatar, profile_id, capabilities_snapshot)
     ├─ Session (title, bot_id?, profile_id, model, pinned, created_at)
     │    └─ Message (role, content_blocks[], model_at_time)
     │         └─ Block: text | thinking | tool_run | diff | file | image | clarifying_q | error | model_changed
     ├─ Artifact (session_id, type: image|file|link, path/url)
     ├─ Room (name, avatar, bot_ids[]) ─ Thread ─ Message
     ├─ Skill (source: builtin|optional|community|learned, enabled, metadata)
     ├─ ToolGroup (name, enabled, config json e.g. browser backend)
     ├─ McpServer (url, auth, enabled)
     ├─ Channel (platform, credentials_ref, allowed_ids[], status)
     └─ CronJob (cron_expr, prompt, destination_channel_id, blueprint_id?, last_run, status)
```

---

## 14. Epics and PR breakdown

**Epic 0: Foundation**
- PR: monorepo scaffold (TS frontend, Python agent runtime, Docker/Caddy deploy)
- PR: auth + org/workspace + roles (biz)
- PR: gateway service with health endpoint, status bar wiring

**Epic 1: Providers**
- PR: provider registry (metadata, auth kind, get-key URL)
- PR: onboarding modal (collapsed/expanded/API key grid)
- PR: OAuth-in-browser flow + local model runner option
- PR: provider error cards with Retry/Switch/Logs/Diagnostics/Copy

**Epic 2: Core chat**
- PR: session CRUD, list grouping, pin, search, tabs
- PR: composer (attachments, model+effort picker, mic)
- PR: streaming transcript with block renderer (text, thinking, tool_run, model_changed)
- PR: diff cards + generated-file rows (Download/Hide)
- PR: clarifying questions widget
- PR: right-hand file preview panel (text/md/csv/html/pdf/binary viewers, Edit)

**Epic 3: Capabilities**
- PR: skills list + detail + toggles + "learned" badge
- PR: skills hub browser (registry aggregation, install, update)
- PR: tool groups list + per-group config panels
- PR: browser automation backend picker + real-profile snapshot
- PR: MCP server management

**Epic 4: Messaging gateways**
- PR: channel adapter interface + Telegram, Slack, Discord, Email first
- PR: channel setup UI (required/recommended fields, allowlists, save)
- PR: remaining adapters incrementally

**Epic 5: Automation**
- PR: cron engine + job CRUD + destination routing
- PR: blueprints library (business-flavored)
- PR: artifacts page with filters

**Epic 6: Bots and rooms**
- PR: profiles (clone, inherit provider/model, SOUL.md, key sharing)
- PR: bot CRUD + avatar builder
- PR: rooms (2-6 bots), threads, @mentions, activity feed
- PR: agent-to-agent messaging (A2A)

**Epic 7: Business layer (biz)**
- PR: audit log, approval gates, usage metering, billing, shared team resources

---

## 15. Roadmap

| Phase | Weeks | Ships |
|---|---|---|
| 1. MVP chat | 1-3 | Epics 0, 1, 2 (single provider, sessions, streaming, file preview) |
| 2. Power tools | 4-6 | Epic 3 (skills, tools, browser, MCP) |
| 3. Reach | 7-8 | Epic 4 (3-4 channels) + Epic 5 (cron, artifacts) |
| 4. Teams of agents | 9-11 | Epic 6 (bots, rooms, A2A) |
| 5. Sell it | 12+ | Epic 7 (audit, approvals, billing, hosted runner) |

Design work (Claude Design) can run in parallel from day 1 using the companion prompt file.
