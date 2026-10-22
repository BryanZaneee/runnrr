# Runnrr thread workspace QA — 2026-10-16

final result: passed

## Scope and result

The thread workspace UI passes visual and interaction checks for this overhaul.
The reference is the owner's `Screenshot 2026-10-16 at 9.31.39 AM.png` attachment.
This is an adaptation for general assistants: coding-only controls, desktop
window buttons, and branch information are intentionally replaced or omitted.
No actionable P0/P1/P2 findings remain in this scope.

Storage, subscription connections, custom-tool creation, assistant editing, and
uploads are not implemented by this change. Thread actions are explicitly
page-local; the composer and information dialog disclose that limitation.

## Reference and evidence

- Reference: supplied 2048 × 1104 screenshot.
- Live route: `http://127.0.0.1:8001/`.
- Native preview: 1169 × 731 CSS pixels, captured as 1280 × 800 pixels.
- The preview resize command timed out. Responsive verification instead used
  same-origin browser frames with real CSS viewports of 320, 390, 760, 1024,
  1440, and 2048 pixels. No alternate browser automation was used.
- For reference comparison, the frame was 2048 × 1104 CSS pixels, scaled by
  1169/2048 to fit the preview. Its capture was cropped to 1280 × 690 pixels;
  the original reference was resized to the same dimensions. The frame was
  scaled for capture only; the app's layout viewport remained 2048 × 1104.
- A 390 × 844 CSS mobile frame was captured at scale 0.8 and cropped to
  342 × 739 capture pixels. The same viewport was tested interactively.
- Local ignored evidence: `tmp/design-qa/comparison.png`,
  `comparison-final.png`, `sidebar-comparison.png`, `composer-final.png`,
  `panel-final.png`, `desktop-final.png`, and `mobile-final.png`.
- Full comparison sheets and focused composer/sidebar/panel crops were opened
  and reviewed together. The populated frame used mocked streamed responses,
  not fabricated production history. All test frames were removed afterward.
- `docs/screenshots/workstation-local.webp` shows the real app's empty state,
  with no mocked API responses. The dev build remains open for review.

State differences: the reference has three coding threads and a longer response;
our populated QA frame has general assistant threads and a shorter response.
Compare layout, typography, controls, and hierarchy rather than exact line breaks.

## Findings and corrections

1. **P2 — Typography too small.** The first comparison made the transcript and
   composer controls noticeably denser than the supplied image. Increased
   conversation text to 16px, composer text to 15px, model/assistant controls to
   13px, and thread titles to 14px. Final comparison and focused crops verify
   the corrected hierarchy. Compact mobile selectors use 12px text.
2. **P2 — Draft height after viewport changes.** A populated desktop composer
   kept its previous height when narrowed to mobile. Recalculate textarea
   height on resize. Fresh mobile capture verifies the entire draft fits:
   `clientHeight = scrollHeight = 119px` at 390px width.
3. **Resolved during development — Stale preview assets.** A preview navigation
   temporarily mixed old CSS/JS with new markup. Reloading the assets and page
   resolved it. The isolated browser checks report no application errors.

## Fidelity review

| Surface | Result |
| --- | --- |
| Typography | System font stack; compact sidebar; readable transcript; quiet metadata. No external font dependency. |
| Spacing/layout | Narrow sidebar, centered conversation, floating rounded composer, subtle dividers, independent scrolling, collapsible navigation, resizable right panel. |
| Colors | Pale neutral surfaces, muted secondary text, blue actions, green completed status, visible error states. Orange branding and dark user bubbles removed. |
| Assets/icons | Pinned upstream Heroicons; no generated art, custom SVG illustrations, or external image dependencies. Existing Markdown libraries retained. |
| Content | Live assistant/model/tool metadata. Coding controls replaced by assistants, knowledge, tools/skills, sources, activity, and details. Unsupported capabilities remain clearly unavailable. |
| Responsive behavior | No page overflow at 320–2048px. Mobile drawers make underlying content inert; composer controls remain reachable. |
| Accessibility | Labeled inputs and icon buttons, native selects/dialogs/details, visible focus, reduced-motion support, drawer focus cycling, keyboard panel resizing. |

Accepted differences: no macOS traffic lights, repository controls, terminal,
diff, or PR panels; system initials identify real assistants; a temporary-history
notice replaces repository context below the composer. Tool activity uses actual
step counts rather than an invented work duration. The reference's rich editor
is implemented as a native multiline textarea for Runnrr's text-only chat API.

## Verification

- `node tests/unit/workstation.mjs`: passed SSE fragmentation/Unicode, tool/error
  events, safe URLs, session isolation, and new thread lifecycle checks.
- `.venv/bin/python -m pytest tests/api/test_workstation.py -q`: 2 passed. Existing
  Starlette/AnyIO deprecation warning only.
- `tests/browser/workstation-browser.mjs`, evaluated in the collaborative browser:
  **36 checks passed**, four intercepted chat requests, no model-provider calls.
  Checks cover sanitization, sources, collapsed activity, model changes, original
  model/session binding, draft preservation, rename, pin, snooze, restore,
  settle, undo, delete/undo, busy-action guards, background streaming isolation,
  error presentation, panel resize, mobile drawers, and responsive overflow.
- Additional fresh mobile capture checked multiline resize behavior.
- `git diff --check`: passed.

Not checked: live provider authentication or billing, full backend suite,
OS-specific native dropdown rendering outside this browser, or durable history.
The screenshot regeneration script was updated for the local UI; this capture
was made through the collaborative preview.

## 2026-10-16 — Usage analytics

Verified the new Usage & costs panel and response disclosures through the
collaborative preview at localhost:8001. `tests/browser/usage-browser.mjs` uses an isolated
frame with synthetic chat/history responses; no paid provider call is needed.
Checks cover inclusive reasoning, context size, partial and unpriced labels,
estimated reasoning, model filters, HTML escaping, explicit read failures and
reachable controls without page overflow at 320, 390, 760 and 1280 pixels.
Inspected the populated panel visually at 390 pixels, including token details,
missing prices, chart and daily table. Removed the synthetic frame afterward.

Backend validation: 418 passed, 1 skipped in the full pytest suite; the focused
metrics/accounting checks and `node tests/unit/workstation.mjs` also pass. One environment-dependent
check was skipped. Live provider billing was not exercised.

## 2026-10-16 — Assistant/project picker and local/website separation

final result: passed

### Visual truth and evidence

References: owner attachments `Screenshot 2026-10-16 at 12.16.13 PM.png`
(project picker, 1088 × 786 pixels) and `12.17.44 PM.png` (sidebar,
374 × 2048 pixels). The original attachments remain the visual references.

Live route: https://bryanzane.com/easyagent/. Local build: localhost:8002.
Desktop CSS viewport 1082 × 731; captured at 1280 × 864 pixels. The picker is
680 × 548 CSS pixels. The comparison normalizes the reference to 680 pixels
wide and crops/resizes the implementation at capture density 1280/1082.
Source viewport/DPR is unavailable because the supplied image is a modal crop.
State: assistant already selected, project step open, No project highlighted.
The extra No project row and public-project metadata are intentional.

Evidence (ignored local directory `tmp/design-qa/`):
- `projects-comparison.png`: entire reference picker and current picker together.
- `projects-sidebar-comparison.png`: top and footer regions together, normalized
  to the same 218-pixel sidebar width. The source has a taller original viewport;
  its whitespace is excluded from this focused component comparison.
- `projects-desktop.png`: complete deployed UI with selected project/knowledge.
- `projects-mobile.png`: 390 × 844 CSS frame, captured at 0.8 scale.

Opened and reviewed both comparison sheets, desktop and mobile captures. The
mobile modal remains inside the viewport; the page has no horizontal overflow.

### Findings and corrections

- P2, resolved: the public Knowledge panel instructed visitors to use Add
  project, but portfolio mode intentionally hides that control. It now directs
  them to choose a portfolio project when starting a thread. Local wording
  retains the folder import guidance. Recaptured the deployed panel after fix.
- No remaining P0/P1/P2 visual findings. Live provider completion is a separate
  deployment limitation below, not a passed model-response check.

### Fidelity surfaces

- Typography: system font family matching the supplied interface, medium row
  titles, muted secondary metadata, native inputs and truncated long descriptions.
- Layout: rounded search modal, highlighted selection, independently scrolling
  results, bottom shortcut strip, compact sidebar and bottom-left settings.
  Rows are slightly taller than the normalized source to support general users.
- Colors: pale neutral surfaces, subtle dividers, blue actions, muted metadata,
  and restrained initial badges; no new raster art or gradient approximations.
- Icons: pinned upstream Heroicons plus Lucide's distinct panel-left/panel-right
  assets with licenses. No hand-drawn icons. Public mode hides folder-plus;
  local mode retains folder search, folder-plus, and new-thread controls.
- Copy: assistant first, then project or No project. Local folders and public
  website/GitHub sources have distinct labels. Private repositories are not read.
- Keyboard/accessibility: native modal focus containment, Escape dismissal,
  arrow/Enter selection, labeled icon buttons/fields, visible focus states.

### Verification

- Full isolated backend suite: 411 passed, 1 skipped; existing AnyIO warning.
- Workstation Node checks: passed.
- Browser regression: 35 checks passed, mocked chat only; thread lifecycle,
  sanitization, streaming/session isolation and 320–2048px responsive checks.
- Project browser flow: 11 checks passed; real disposable folder import and
  cleanup, assistant/project binding, No project, search, settings and icons.
- Deployed browser: 14 read-only portfolio projects, correct /runnrr-api prefix,
  assistant-first flow, project header and working Settings. Local picker hides
  all shared portfolio records. API tests enforce the same separation.
- Recent browser diagnostics: no new UI errors; historical CORS diagnostics from
  an earlier, unrelated local static-preview setup were not counted as current.
- Live chat request reached the project-bound backend and returned the expected
  daily-spending-limit event. A completed paid reply was NOT verified: the
  initial legacy embedding migration exhausted the conservative daily allowance.
  It was not reset; daily portfolio refresh now uses direct text without paid
  calls. Replies resume at the normal UTC-day reset.

P3/accepted differences: no coding branches, PR controls, platform window chrome
or numerical project shortcuts. Repository metadata replaces machine paths in
the public demo. Folder imports are explicit snapshots, not filesystem watchers;
transcripts remain temporary. No additional polish loop needed.


## 2026-10-21 — Cleanup regression checks

`tests/browser/browser-runner.mjs` now executes the existing workstation, usage, and
project scenarios against a disposable local runtime. The 37 workstation,
17 usage, and 11 project assertions passed in headless Chromium, including
320–2048 px layouts, sanitization, stream isolation, project persistence, and
retention of completed transcript nodes during a follow-up response. Chat is
mocked and blocked at the browser network boundary; no provider was called.
This is interaction/layout regression evidence, not a fresh visual redesign.
