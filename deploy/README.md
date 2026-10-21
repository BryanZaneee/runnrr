# deploy/

`runnrr.service` is the systemd unit for a cloud install (uvicorn on `127.0.0.1:8001`,
one worker; sessions are process-local; budget reservations persist in SQLite).

Deploys are manual:

```bash
ssh <host> 'cd /opt/runnrr && git pull --ff-only && .venv/bin/uv pip install -e ".[rag]" && systemctl restart runnrr'
```

The separate public-site deployment remains frozen at commit `ed536ff`.
It is not managed by this repository.

## Separate portfolio workstation (2026-10-16)

The legacy `/opt/easyagent` stays pinned. The project picker demo runs from
`/opt/runnrr-workstation`, with `deploy/runnrr-workstation.service` on loopback
8002 and Caddy `/runnrr-api/*` rewritten to `/api/*`. Its static frontend is
published by the bryanzane_v3 repo under `/runnrr/`; Caddy redirects
`/easyagent` and `/easyagent/*` to `/runnrr/`. Workstation assets revalidate
on each load. Agent person badges and project initials share `identity.mjs`
with the local UI.

Install `runnrr-knowledge-refresh.service` and `.timer` for the daily public
website/GitHub snapshot. This task does not rebuild embeddings. The deployment's
personal-agent profile omits `semantic_search_kb`; direct KB and project tools
read the fresh text. Preserve that deployment override on future syncs.

The units read existing credentials from `/opt/easyagent/.env` and non-secret
local overrides from `/opt/runnrr-workstation/demo.env`:

```dotenv
RUNNRR_PUBLIC_DEMO=1
RUNNRR_MAX_REQUEST_TOKENS=100000
MAX_TOKENS=4096
DEMO_REQUEST_COST_BOUNDS={"llm:deepseek-v4-flash":40000,"embed:voyage-3-large":25000}
```

The request limit includes serialized UTF-8 input, framing allowance and output
reservation. The DeepSeek bound covers peak $0.30/M input and $1.20/M output;
Voyage's bound covers its 120K request maximum at $0.18/M. Rates were checked on
2026-10-16 against the official DeepSeek and Voyage pricing pages. Re-review
before changing providers, limits or pricing. Unknown calls remain paused. The
existing $0.50/day guard is retained, including failed-call reservations.

The first legacy-index migration exhausted that guard on 2026-10-16. It was not
reset. Chat resumes at the normal UTC-day reset; all subsequent portfolio
refreshes are free HTTP reads. Do not retry the full embedding migration in the
public service. System changes are recorded in `/root/VPS_CHANGELOG.md`.

Rollback: restore the prior static site revision (3b7e38e) to use the legacy
`/api` backend, then disable the new service/timer. Project SQLite data and the
legacy runtime can remain intact. Caddy's pre-change backup is
`/etc/caddy/Caddyfile.before-runnrr-projects-20261016`.
