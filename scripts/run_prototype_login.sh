#!/usr/bin/env bash
#
# Run the Volt Debt prototype with login ON, for a demo or a guided test session.
#
#   API   http://127.0.0.1:8000   (uvicorn; AUTH_MODE=on in this shell's environment)
#   Web   http://localhost:5173   (vite dev server, proxying /api to the API)
#
# AUTH_MODE is exported into the real environment, never written to backend/.env: a
# .env that names AUTH_MODE is refused on purpose (backend/app/auth.py's docstring —
# the test suite reads that file, and one line there would put every test behind a
# login).
#
# Everything secret is made at run time and lives in this process only:
#   - AUTH_SESSION_SECRET: generated when the environment does not supply one
#     (auth.py needs at least 32 characters).
#   - one password shared by every test account: AUTH_TEST_PASSWORD if the
#     environment supplies one, else generated and printed once, here.
#   - six accounts — tester (any role), officer.test, supervisor.test, manager.test,
#     owner.test, ops.test — hashed with the backend's own auth.hash_password. Each
#     role is mapped to an officer read from app/officers.py's registry, and
#     auth.check_officers refuses to start if one is missing.
#
# Google sign-in is untouched: whatever GOOGLE_CLIENT_ID the environment (or
# backend/.env) already provides is what the login page offers.
#
# Usage:
#   scripts/run_prototype_login.sh
#   API_PORT=8001 WEB_PORT=5174 scripts/run_prototype_login.sh
#   AUTH_TEST_PASSWORD='...' scripts/run_prototype_login.sh
#   KEEP_UP=1 scripts/run_prototype_login.sh    # start, print, leave running, exit
#
# Anything that was ALREADY listening is reused and left alone: this script never
# kills a process it did not start. Everything this script started is stopped again
# on exit, including on Ctrl-C and on failure. Without KEEP_UP it waits for Ctrl-C.
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

UVICORN="$ROOT/backend/.venv/bin/uvicorn"
BACKEND_PYTHON="$ROOT/backend/.venv/bin/python"
VITE="$ROOT/frontend/node_modules/.bin/vite"
VITE_CONFIG="$ROOT/frontend/vite.config.js"

# token_urlsafe and the JSON parse below are standard library only.
PYTHON="$(command -v python3 || true)"
CURL="$(command -v curl || true)"

API_PID=""
WEB_PID=""
PIDS=()
LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/volt-debt-login.XXXXXX")"
TMP_VITE_CONFIG=""

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

cleanup() {
  local status=$?
  local pid
  trap - EXIT INT TERM
  if [ -n "$TMP_VITE_CONFIG" ]; then
    rm -f "$TMP_VITE_CONFIG"
  fi
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

# The mode /v1/auth/config reports, or "" when the route cannot be read.
api_auth_mode() {
  "$PYTHON" - "$API_URL/v1/auth/config" <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
        print(json.load(response).get("mode", ""))
except Exception:
    print("")
PY
}

# Wait for the just-started API to answer /v1/auth/config with mode=on. A server
# that is up but serving login-off is not the server this script promised.
wait_for_auth_on() {
  local i=0 mode=""
  while [ "$i" -lt 60 ]; do
    mode="$(api_auth_mode)"
    if [ "$mode" = "on" ]; then
      say "  /v1/auth/config reports login mode=on"
      return 0
    fi
    if ! kill -0 "$API_PID" 2>/dev/null; then
      break
    fi
    sleep 0.5
    i=$((i + 1))
  done
  say ""
  say "the API never reported login mode=on. Last 40 lines of $LOGDIR/api.log:"
  tail -40 "$LOGDIR/api.log" >&2 || true
  die "login did not turn on"
}

[ -n "$PYTHON" ] || die "python3 is not on PATH; this script needs it for secrets and JSON"
[ -x "$BACKEND_PYTHON" ] || die "no python at $BACKEND_PYTHON (build the venv: python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt)"
[ -x "$UVICORN" ] || die "no uvicorn at $UVICORN (build the venv: python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt)"

say "Volt Debt prototype - login ON"
say "  root  $ROOT"
say "  logs  $LOGDIR"
say ""

# --- the API -----------------------------------------------------------------------
# Reuse only a running API that itself has login on. Reusing a login-off server would
# quietly show an app with no login card and no session, which is the opposite of
# what this script promises.
if probe "$API_URL/healthz"; then
  if [ "$(api_auth_mode)" != "on" ]; then
    die "$API_URL is already serving a prototype with login off. Stop it, or pick another port: API_PORT=8001 scripts/run_prototype_login.sh"
  fi
  say "  API already up on $API_PORT with login on - reusing it, and leaving it running"
  say "  (its secret and accounts are the ones it was started with, not this run's)"
else
  SECRET="${AUTH_SESSION_SECRET:-}"
  if [ -z "$SECRET" ]; then
    SECRET="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  fi
  [ "${#SECRET}" -ge 32 ] || die "AUTH_SESSION_SECRET must be at least 32 characters"

  GENERATED_PASSWORD=""
  PASSWORD="${AUTH_TEST_PASSWORD:-}"
  if [ -z "$PASSWORD" ]; then
    PASSWORD="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(12))')"
    GENERATED_PASSWORD=1
  fi

  # One helper run does both jobs: read the officer registry and hash the password
  # with the backend's own helper. The password travels in an environment variable,
  # never on the command line where ps could see it. stdout is the AUTH_TEST_ACCOUNTS
  # JSON; stderr is the human-readable mapping, printed once here.
  ACCOUNTS_JSON="$(cd "$ROOT/backend" && env AUTH_MODE= AUTH_TEST_PASSWORD_GENERATED="$PASSWORD" "$BACKEND_PYTHON" - <<'PY'
import json
import os
import sys
from app import auth, officers

password = os.environ["AUTH_TEST_PASSWORD_GENERATED"]
rows = officers.registry()

def officer_for(role):
    for row in rows:
        if role in row.get("roles", ()) or row.get("role") == role:
            return row["uid"]
    raise SystemExit("no registry officer holds role %s" % role)

named = (("tester", "ANY", None),
         ("officer.test", "OFFICER", officer_for("OFFICER")),
         ("supervisor.test", "SUPERVISOR", officer_for("SUPERVISOR")),
         ("manager.test", "MANAGER", officer_for("MANAGER")),
         ("owner.test", "OWNER", officer_for("OWNER")),
         ("ops.test", "OPS", officer_for("OPS")))
accounts = {user: {"hash": auth.hash_password(password), "role": role, "officer": officer}
            for user, role, officer in named}
for user, role, officer in named:
    print("  account  %-16s %-11s %s" % (user, role, officer or "(chooses any role)"), file=sys.stderr)
print(json.dumps(accounts, separators=(",", ":")))
PY
)"

  # The servers need the hashes, never the plaintext: it exists only on this line and
  # in the terminal, not in the uvicorn or vite process environment.
  unset AUTH_TEST_PASSWORD

  say ""
  if [ -n "$GENERATED_PASSWORD" ]; then
    say "  test password  $PASSWORD"
    say "                 (generated now; printed once, stored nowhere - copy it before it scrolls)"
  else
    say "  test password  from AUTH_TEST_PASSWORD (not printed here)"
  fi
  say ""

  export AUTH_MODE="on"
  export AUTH_SESSION_SECRET="$SECRET"
  export AUTH_COOKIE_SECURE="false"
  export AUTH_ALLOW_TEST_ACCOUNTS="true"
  export AUTH_TEST_ACCOUNTS="$ACCOUNTS_JSON"

  say "  starting API on $API_PORT with AUTH_MODE=on"
  ( cd "$ROOT/backend" && exec "$UVICORN" app.main:app --host 127.0.0.1 --port "$API_PORT" ) \
    > "$LOGDIR/api.log" 2>&1 &
  API_PID=$!
  PIDS+=("$API_PID")
  wait_for "$API_URL/healthz" "API" "$LOGDIR/api.log" 60 "$API_PID"
  wait_for_auth_on
fi

# --- the web app -------------------------------------------------------------------
if probe "$WEB_URL"; then
  say "  web already up on $WEB_PORT - reusing it, and leaving it running"
  if [ "$API_PORT" != "8000" ]; then
    say "  note: its vite proxy may still point at :8000; check $WEB_URL/api/v1/auth/config"
  fi
else
  if [ ! -x "$VITE" ]; then
    command -v npm >/dev/null 2>&1 || die "no vite at $VITE and npm is not on PATH"
    say "  installing frontend dependencies (first run only)"
    ( cd "$ROOT/frontend" && npm install ) > "$LOGDIR/npm.log" 2>&1 \
      || { tail -40 "$LOGDIR/npm.log" >&2; die "npm install failed"; }
  fi
  VITE_CONFIG_ARG=()
  # The committed vite.config.js hard-codes the proxy target :8000. Overriding
  # API_PORT would break the browser's /api calls, so a throwaway config around the
  # committed one always re-points the proxy (a no-op at :8000), and cleanup removes
  # it. Always, not only for an override: bash 3.2 (macOS) refuses an empty array
  # under `set -u`.
  TMP_VITE_CONFIG="$(mktemp "${TMPDIR:-/tmp}/volt-vite-login.XXXXXX.mjs")"
  cat > "$TMP_VITE_CONFIG" <<EOF
import base from "$VITE_CONFIG"
export default {
  ...base,
  server: {
    ...base.server,
    proxy: { "/api": { ...base.server.proxy["/api"], target: "$API_URL" } },
  },
}
EOF
  VITE_CONFIG_ARG=(--config "$TMP_VITE_CONFIG")
  if [ "$API_PORT" != "8000" ]; then
    say "  vite proxy re-pointed at $API_URL through a temporary config"
  fi
  say "  starting web on $WEB_PORT"
  # The binary directly, not `npm run dev`: one process, so the trap can actually
  # stop it instead of orphaning vite under a dead npm.
  ( cd "$ROOT/frontend" && exec "$VITE" "${VITE_CONFIG_ARG[@]}" --port "$WEB_PORT" --strictPort ) \
    > "$LOGDIR/web.log" 2>&1 &
  WEB_PID=$!
  PIDS+=("$WEB_PID")
  wait_for "$WEB_URL" "web" "$LOGDIR/web.log" 120 "$WEB_PID"
fi

say ""
say "  login is ON - open $WEB_URL"
say "  test accounts: tester (any role) and officer/supervisor/manager/owner/ops .test"
say "  Google sign-in shows only when GOOGLE_CLIENT_ID is configured."
say ""

if [ -n "$KEEP_UP" ]; then
  if [ "${#PIDS[@]}" -eq 0 ]; then
    say "KEEP_UP set - both servers were already running; nothing to stop."
  fi
  # cleanup's KEEP_UP branch prints the URLs and the kill line for what we started.
  exit 0
fi

if [ "${#PIDS[@]}" -gt 0 ]; then
  say "  press Ctrl-C to stop."
  wait "${PIDS[@]}" || true
fi
