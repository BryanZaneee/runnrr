# deploy/

`runnrr.service` is the systemd unit for a cloud install (uvicorn on `127.0.0.1:8001`,
one worker; sessions and the budget are process-local by design).

Deploys are manual:

```bash
ssh <host> 'cd /opt/runnrr && git pull --ff-only && .venv/bin/uv pip install -e ".[rag]" && systemctl restart runnrr'
```

The old bryanzane.com deploy is frozen at tag `v0.1.0-easyagent-final`
under `/opt/easyagent` and is no longer touched by this repository.
