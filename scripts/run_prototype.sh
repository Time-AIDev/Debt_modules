#!/usr/bin/env bash
#
# Start the Volt Debt prototype end to end.
#
#   API   http://127.0.0.1:8000   (uvicorn, from backend/.venv)
#   Web   http://127.0.0.1:5173   (vite dev server, proxying /api to the API)
#
# In the default crm-lead mode the servers stay up for the walkthrough; in fixtures
# mode the script runs scripts/e2e_check.py against the live API, prints its verdict
# and stops everything it started (including on Ctrl-C and on failure). Anything
# that was ALREADY listening is reused and left alone: this script never kills a
# process it did not start.
#
# Two data modes:
#
#   SERVE=crm-lead  (default)  Odoo crm.lead is the served book, on the repo's own
#                              local Postgres (scripts/pg_local.sh, database
#                              volt_debt) with sign-in on. This is the demo the
#                              team walks through: the login card, real leads in
#                              the Book. e2e_check.py is SKIPPED in this mode —
#                              it pins the sheet-fixture contract — and the
#                              servers are left up (the full gate is
#                              ./scripts/verify_all.sh, own API, no database).
#   SERVE=fixtures             The sheet fixtures, no database, sign-in off, and
#                              e2e_check.py runs at the end as before.
#
# Usage:  scripts/run_prototype.sh [extra args passed to e2e_check.py]
#   e.g.  scripts/run_prototype.sh --json
#         SERVE=fixtures scripts/run_prototype.sh
#         API_PORT=8001 WEB_PORT=5174 scripts/run_prototype.sh
#         KEEP_UP=1 scripts/run_prototype.sh     # leave both servers running
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
API_URL="http://127.0.0.1:${API_PORT}"
# localhost, not 127.0.0.1: vite binds [::1] only, so an IPv4 probe never sees it
# even while the dev server is happily serving the browser.
WEB_URL="http://localhost:${WEB_PORT}"
KEEP_UP="${KEEP_UP:-}"
SERVE="${SERVE:-crm-lead}"
VOLT_DB_NAME="${VOLT_DB_NAME:-volt_debt}"

UVICORN="$ROOT/backend/.venv/bin/uvicorn"
VITE="$ROOT/frontend/node_modules/.bin/vite"
CHECK="$ROOT/scripts/e2e_check.py"

# The check itself is standard library only, so the system python3 runs it. The venv
# is for the API, not for the test.
PYTHON="$(command -v python3 || true)"
CURL="$(command -v curl || true)"

API_PID=""
WEB_PID=""
LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/volt-debt-run.XXXXXX")"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

cleanup() {
  local status=$?
  local pid
  trap - EXIT INT TERM
  if [ -n "$KEEP_UP" ] && [ -n "${API_PID}${WEB_PID}" ]; then
    say ""
    say "KEEP_UP set - leaving up what this script started: $API_URL $WEB_URL"
    say "  stop it with:  kill ${API_PID} ${WEB_PID}"
    exit "$status"
  fi
  for pid in "$WEB_PID" "$API_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  if [ -n "${API_PID}${WEB_PID}" ]; then
    say "stopped everything this script started."
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

probe() {
  if [ -n "$CURL" ]; then
    "$CURL" -sf -o /dev/null --max-time 2 "$1"
  else
    "$PYTHON" -c 'import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)' \
      "$1" >/dev/null 2>&1
  fi
}

# Poll until it answers. 60 tries at half a second is 30 s, which is generous for
# uvicorn and about right for a cold vite start.
wait_for() {
  local url="$1" label="$2" logfile="$3" tries="${4:-60}" pid="${5:-}"
  local i=0
  while [ "$i" -lt "$tries" ]; do
    if probe "$url"; then
      say "  $label is answering at $url"
      return 0
    fi
    # Do not sit out the full timeout on a server that has already died.
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      say "  $label exited before it answered."
      break
    fi
    sleep 0.5
    i=$((i + 1))
  done
  say ""
  say "$label never answered at $url. Last 40 lines of $logfile:"
  tail -40 "$logfile" >&2 || true
  die "$label did not start"
}

[ -n "$PYTHON" ] || die "python3 is not on PATH; scripts/e2e_check.py needs it"
[ -f "$CHECK" ] || die "missing $CHECK"

say "Volt Debt prototype"
say "  root  $ROOT"
say "  logs  $LOGDIR"
say ""

# --- the data source -----------------------------------------------------------------
API_CMD=(env)
if [ "$SERVE" = "crm-lead" ]; then
  say "  data source: Odoo crm.lead on the local Postgres ($VOLT_DB_NAME), sign-in on"
  "$ROOT/scripts/pg_local.sh" start "$VOLT_DB_NAME" > /dev/null \
    || die "the local Postgres did not start"
  DB_URL="$("$ROOT/scripts/pg_local.sh" url "$VOLT_DB_NAME")"
  # DATABASE_URL in the real environment, never backend/.env — the same rule
  # AUTH_MODE follows, because the test suite reads that file.
  API_CMD+=("DATABASE_URL=$DB_URL" AUTH_MODE=on AUTH_COOKIE_SECURE=false)
  KEEP_UP=1
else
  say "  data source: sheet fixtures (no database, sign-in off)"
fi

# --- the API -----------------------------------------------------------------------
if probe "$API_URL/healthz"; then
  say "  API already up on $API_PORT - reusing it, and leaving it running afterwards"
else
  [ -x "$UVICORN" ] || die "no uvicorn at $UVICORN (build the venv: python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt)"
  say "  starting API on $API_PORT"
  API_CMD+=("$UVICORN" app.main:app --host 127.0.0.1 --port "$API_PORT")
  ( cd "$ROOT/backend" && exec "${API_CMD[@]}" ) > "$LOGDIR/api.log" 2>&1 &
  API_PID=$!
  wait_for "$API_URL/healthz" "API" "$LOGDIR/api.log" 60 "$API_PID"
fi

# --- the web app -------------------------------------------------------------------
if probe "$WEB_URL"; then
  say "  web already up on $WEB_PORT - reusing it, and leaving it running afterwards"
else
  if [ ! -x "$VITE" ]; then
    command -v npm >/dev/null 2>&1 || die "no vite at $VITE and npm is not on PATH"
    say "  installing frontend dependencies (first run only)"
    ( cd "$ROOT/frontend" && npm install ) > "$LOGDIR/npm.log" 2>&1 \
      || { tail -40 "$LOGDIR/npm.log" >&2; die "npm install failed"; }
  fi
  say "  starting web on $WEB_PORT"
  # The binary directly, not `npm run dev`: one process, so the trap can actually
  # stop it instead of orphaning vite under a dead npm.
  ( cd "$ROOT/frontend" && exec "$VITE" --port "$WEB_PORT" --strictPort ) \
    > "$LOGDIR/web.log" 2>&1 &
  WEB_PID=$!
  wait_for "$WEB_URL" "web" "$LOGDIR/web.log" 120 "$WEB_PID"
fi

say ""
say "  open $WEB_URL   (the browser talks to the API through the vite /api proxy)"
say ""

# --- the checks --------------------------------------------------------------------
if [ "$SERVE" != "fixtures" ]; then
  say "e2e_check.py pins the sheet-fixture contract, so the crm.lead demo skips it."
  say "  the full gate is ./scripts/verify_all.sh (its own API on :8099, no database)."
  say "  sign in with manager.test / officer.test — passwords in ~/.volt-test-accounts.json"
  exit 0
fi

set +e
"$PYTHON" "$CHECK" --base-url "$API_URL" "$@"
rc=$?
set -e

say ""
case "$rc" in
  0) say "e2e_check.py: every rule held." ;;
  2) say "e2e_check.py: the API stopped answering. See $LOGDIR/api.log" ;;
  *) say "e2e_check.py: a rule was broken (exit $rc). Nothing above is a flake - read the BROKEN line." ;;
esac

exit "$rc"
