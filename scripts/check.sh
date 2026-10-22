#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
.venv/bin/ruff check runnrr tests
.venv/bin/ruff format --check runnrr tests
.venv/bin/python -m pytest -q
node tests/unit/workstation.mjs
for file in web/js/*.mjs tests/browser/*.mjs; do node --check "$file"; done
