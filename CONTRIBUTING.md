# Contributing

Runnrr is early software. Keep changes focused and preserve the business-agnostic
runtime. Read [README.md](README.md), [AGENTS.md](AGENTS.md), and the
[current roadmap](docs/roadmap/README.md) before changing architecture.

## Local development

Use Python 3.11–3.13, uv, and Node.js. From a source checkout:

```sh
uv sync --frozen --extra dev --extra rag
cp .env.example .env
```

Configure local provider keys and reviewed request-cost bounds as described in
the README. Tests use injected providers and temporary databases; they do not
need credentials. Never commit `.env`, private knowledge, or generated databases.

## Before submitting

Run `scripts/check.sh`. Install frontend tools with `npm ci` and
`npx playwright install chromium`. For browser changes, also run `scripts/check-browser.sh`
against the disposable local test runtime it starts. Add regression coverage
for changed behavior, and update the relevant guide when behavior changes.

Keep provider events, usage accounting, and external API/log fields compatible.
Do not remove bundled profiles, licenses, or archived design evidence as cleanup.
Explain the problem, resulting behavior, and checks in the pull request.

Use Conventional Commits with a subject under 50 characters and body lines
wrapped at 72. Do not add a `Co-Authored-By: Claude` trailer. Deployment is manual
and separate from merging; see [deploy/README.md](deploy/README.md).
