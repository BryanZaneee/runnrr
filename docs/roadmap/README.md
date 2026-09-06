# Roadmap

Deferred features, one file each, in the order they are expected to land. Each
file is either a folded design doc from a former draft PR (#11–#18, closed) with
its contract-test docstrings as an acceptance list, or a short placeholder.

The executable plan lives in [`../plans/runnrr-analysis.md`](../plans/runnrr-analysis.md)
(§5, PR sequence). Where a roadmap file and the plan disagree, the plan wins.

Order:

1. `supabase-auth` — seed: `backend/auth.py` from PR #2 (PyJWT HS256, `require_user`, `optional_user`). Plan P3b.
2. `durable-sessions` — plan P3a.
3. `audit-kill-switch` — plan P3c.
4. `hitl` — plan P3d.
5. `channel-webhooks` — plan P8 (Telegram first, then Twilio SMS from this doc).
6. `channel-voice`
7. `calendar-crm` — first `requires_approval=True` tools.
8. `mcp-runtime` — plan P7.
9. `dlp-redact`
10. `group-management` — Supabase `orgs/memberships/roles` + invites; a role claim check in `require_user`.
11. `serve-ui-from-runtime` — plan P4 (`app.mount("/", StaticFiles(...))`).
12. `mac-packaging` — installer / menubar wrapper around `runnrr up`.
13. `cloud-provisioning` — one container per customer on the VPS; the frozen EasyAgent `Caddyfile` (tag `v0.1.0-easyagent-final`) has the Sidekick per-user container blocks as prior art.
14. `model-config-file` — `models.json` replacing `MODEL_REGISTRY` + pricing; add per-model minimum cacheable tokens and DeepSeek peak/off-peak rates.
15. `docker-sandbox` — swap `workspace._spawn()` for `docker run --rm -v ws:/work --network none`; bwrap/Seatbelt as the lighter option.

Also deferred (no file yet): agent-management-api (plan P6), agent-memory (P5a), capabilities-model (P5b), cron-and-artifacts (P5c), network egress allowlist proxy, browser-automation, rooms/A2A, skills-hub, escalation routing (cheap default → Sonnet on hop cap / repeated tool errors), evals-generalization (tool trajectories, pass^3), pre-compaction memory flush, hooks registry, deferred tool loading, developer CLI (`runnrr chat` REPL).
