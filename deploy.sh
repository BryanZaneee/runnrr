#!/bin/bash
set -euo pipefail

LOGFILE="/var/log/deploy-webhook.log"

# Maps GitHub repo names to /var/www/ directories
declare -A REPO_MAP=(
    ["bryanzane_v3"]="/var/www/bryanzane.com"
    ["itsupinthe.cloud"]="/var/www/itsupinthe.cloud"
    ["Shuttrr"]="/var/www/shuttrr.com"
    ["Sendaway"]="/var/www/ftrmsg.com"
    ["auth-server"]="/opt/auth-server"
    ["llmbench"]="/var/www/llmbench"
    ["easyagent"]="/opt/easyagent"
)

# Repos that need a build step after pull
declare -A BUILD_CMD=(

    ["Sendaway"]="npm install && npm run deploy"
    ["easyagent"]="for p in personal-agent customer-service frampton; do .venv/bin/python -m backend.rag.cli build \"\$p\" || echo \"WARN: rag build failed for \$p\"; done; systemctl restart easyagent"
)

# Repos that need Docker container rebuild after pull
declare -A DOCKER_REBUILD=(
    ["Shuttrr"]="true"
    ["auth-server"]="true"
)

REPO_NAME="$1"
DEPLOY_DIR="${REPO_MAP[$REPO_NAME]:-}"

if [[ -z "$DEPLOY_DIR" ]]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') ERROR: Unknown repo '$REPO_NAME'" | tee -a "$LOGFILE"
    exit 1
fi

if [[ ! -d "$DEPLOY_DIR/.git" ]]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') ERROR: '$DEPLOY_DIR' is not a git repo" | tee -a "$LOGFILE"
    exit 1
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') Deploying $REPO_NAME to $DEPLOY_DIR..." | tee -a "$LOGFILE"

cd "$DEPLOY_DIR"
git fetch origin main 2>&1 | tee -a "$LOGFILE"
git reset --hard origin/main 2>&1 | tee -a "$LOGFILE"

# Rebuild Docker containers if defined for this repo
if [[ -n "${DOCKER_REBUILD[$REPO_NAME]:-}" ]]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') Rebuilding Docker containers for $REPO_NAME..." | tee -a "$LOGFILE"
    docker container prune -f && docker compose up -d --build --remove-orphans 2>&1 | tee -a "$LOGFILE"
fi

# Run build step if defined for this repo
if [[ -n "${BUILD_CMD[$REPO_NAME]:-}" ]]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') Building $REPO_NAME..." | tee -a "$LOGFILE"
    eval "${BUILD_CMD[$REPO_NAME]}" 2>&1 | tee -a "$LOGFILE"
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') Deploy complete: $REPO_NAME ($(git rev-parse --short HEAD))" | tee -a "$LOGFILE"
