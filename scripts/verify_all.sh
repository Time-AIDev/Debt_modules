#!/usr/bin/env bash
# One command that proves the prototype still holds together.
# Backend units -> frontend components -> the app running -> black-box checks.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILED=0

step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

step "backend unit tests (written before the code)"
( cd "$ROOT/backend" && .venv/bin/python -m pytest tests/ -q ) || FAILED=1

step "frontend component tests"
( cd "$ROOT/frontend" && npx vitest run 2>&1 | tail -6 ) || FAILED=1

step "frontend production build (the browser bundle must load)"
# 2026-09-20: a duplicate export in lib/api.js passed vitest and every API check while
# the browser showed a blank page. Vite's build refuses what dev quietly tolerates.
( cd "$ROOT/frontend" && npm run build >/dev/null 2>&1 ) || { echo "vite build FAILED — run 'npm run build' in frontend/ to see why"; FAILED=1; }

step "starting the API for the black-box pass"
# `exec` so $! is uvicorn's own pid, not the subshell's — killing the subshell would
# leave uvicorn running, holding the pipe open, and this script would never return.
# Output goes to a log so the server never holds stdout either.
LOG="$(mktemp -t volt-debt-verify)"
( cd "$ROOT/backend" && exec env DATABASE_URL= AUTH_MODE=off ENV=dev VOLT_SHARED_STATE_ENABLED=false ODOO_URL= ODOO_DB= ODOO_LOGIN= ODOO_API_KEY= VOLT_BUSINESS_DATE=2026-10-23 .venv/bin/uvicorn app.main:app --port 8099 --log-level warning ) >"$LOG" 2>&1 &
API_PID=$!
cleanup() { kill "$API_PID" 2>/dev/null; wait "$API_PID" 2>/dev/null; rm -f "$LOG"; }
trap cleanup EXIT

for _ in $(seq 1 40); do
  curl -sf http://127.0.0.1:8099/healthz >/dev/null 2>&1 && break
  sleep 0.25
done
if ! curl -sf http://127.0.0.1:8099/healthz >/dev/null 2>&1; then
  echo "the API did not come up; its log follows:"; cat "$LOG"; exit 1
fi

step "black-box checks against the running API"
"$ROOT/scripts/e2e_check.py" --base-url http://127.0.0.1:8099 || FAILED=1

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  printf '\033[32mEVERYTHING PASSED\033[0m\n'
else
  printf '\033[31mSOMETHING FAILED — see above\033[0m\n'
fi
exit $FAILED
