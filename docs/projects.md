# Projects and portfolio knowledge

Click **New thread**, choose an assistant, then choose a project or **No
project**. The folder icon searches projects; folder-plus adds one. Settings
lives at the bottom left. The two panel controls use distinct left/right icons.

## Local workspaces

By default the picker shows only projects imported by this browser. It never
lists the bundled personal-agent portfolio. Choose a folder of text files to
save a snapshot on your local Runnrr runtime. The agent can search that snapshot
and read individual files. It cannot edit the originals or watch later changes;
remove/reimport the project to update a folder snapshot.

Projects live in SQLite (`data/projects.sqlite3`, configurable with
`RUNNRR_PROJECT_DB`). A random browser workspace key scopes access. Clearing
browser storage loses that key; this is not an account or recovery system.
Transcripts, drafts, and pins still disappear on reload.

Imports accept up to 80 text files, 200 KB each, 1 MB total. Hidden files,
dependencies, and binaries are skipped. Choose a smaller folder if necessary.
Project selection is bound to the chat session; it cannot silently switch on an
existing thread. Paths are document identifiers, never arbitrary server paths.

## Public portfolio demo

`RUNNRR_PUBLIC_DEMO=1` exposes only shared portfolio projects and disables all
project mutations. The website uses `/runnrr-api/` on its separate runtime;
legacy `/api/` clients remain unchanged. The browser sends requests to the
prefix in `<html data-api-base>`.

`python -m runnrr.github_sync personal-agent` reads the website configured in
`profiles/personal-agent/github.json`. It discovers every `article.work-row` on
bryanzane.com and records its published description. Linked public GitHub repos
add metadata, README and latest release. No GitHub credential is used. A project
without a public repository gets website facts only, never private source code.

Snapshots carry source URLs and retrieval dates. Failed refreshes keep the last
good copy; an empty/unparseable inventory fails rather than wiping knowledge.
The command writes the private KB under `github/` and shared project snapshots
in SQLite. It does not publish the rest of the KB or alter the resume.

The public demo uses direct read/search tools for updated portfolio knowledge.
Its daily refresh needs no embeddings or model calls. The optional semantic
index is separate and is not rebuilt by the public timer.

## Checks

Run `pytest tests/test_projects.py -q`, `node tests/workstation.mjs`, and evaluate
`tests/projects-browser.mjs` in the local collaborative browser. The latter
imports/deletes a disposable folder and mocks only the chat response. The
workstation browser regression covers thread transitions and responsive layout.
