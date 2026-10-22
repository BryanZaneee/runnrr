#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
RUNNRR_TEST_DATA=$(mktemp -d)
export RUNNRR_TEST_DATA
cleanup() {
  if [ -n "${RUNNRR_TEST_PID:-}" ]; then kill "$RUNNRR_TEST_PID" 2>/dev/null || true; wait "$RUNNRR_TEST_PID" 2>/dev/null || true; fi
  rm -rf "$RUNNRR_TEST_DATA"
}
trap cleanup EXIT INT TERM
# Disable dotenv and all paid capabilities; mock requests in the browser.
PYTHON_DOTENV_DISABLED=1 ANTHROPIC_API_KEY=browser-test OPENAI_API_KEY=browser-test \
DEEPSEEK_API_KEY= MOONSHOT_API_KEY= GEMINI_API_KEY= TAVILY_API_KEY= VOYAGE_API_KEY= \
DEMO_REQUEST_COST_BOUNDS='{}' DEFAULT_PROFILE=customer-service \
DEFAULT_MODEL=claude-sonnet-4-5 RUNNRR_PUBLIC_DEMO=0 RATE_LIMIT_ENABLED=0 \
RUNNRR_EMBEDDING_BACKEND=fake RUNNRR_PROJECT_DB="$RUNNRR_TEST_DATA/projects.sqlite" \
RUNNRR_SESSION_DB="$RUNNRR_TEST_DATA/sessions.sqlite" \
RUNNRR_BUDGET_PATH="$RUNNRR_TEST_DATA/budget.sqlite" \
RUNNRR_USAGE_PATH="$RUNNRR_TEST_DATA/usage.sqlite" \
.venv/bin/python -m uvicorn runnrr.app:app --host 127.0.0.1 --port 8765 >"$RUNNRR_TEST_DATA/server.log" 2>&1 &
RUNNRR_TEST_PID=$!
export RUNNRR_TEST_URL=http://127.0.0.1:8765
.venv/bin/python - <<'PY'
import os, time, urllib.request
for _ in range(100):
    try:
        urllib.request.urlopen(os.environ['RUNNRR_TEST_URL'] + '/api/health', timeout=1)
        break
    except OSError:
        time.sleep(.1)
else:
    from pathlib import Path
    print((Path(os.environ["RUNNRR_TEST_DATA"]) / "server.log").read_text())
    raise SystemExit('Disposable test server did not start')
PY
npm run test:browser
