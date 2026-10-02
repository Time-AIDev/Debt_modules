#!/usr/bin/env bash
#
# Push the secret values (integrations + login) from backend/.env into Secret Manager.
# One exception: AUTH_SESSION_SECRET is never read from the file. Whoever holds the
# laptop's .env could otherwise mint staging sessions, so staging gets its own value,
# generated here once and kept after that.
#
#   ./scripts/push_secrets.sh               # dry run: names and byte lengths only
#   ./scripts/push_secrets.sh --apply       # adds one version per secret
#
# Values are piped from the file straight into gcloud. They are never echoed, never
# passed as an argument (argv is visible in ps), and never written to a log. This is
# the "from a laptop, never via CI" step of GCP Architecture v1.0 §15.1.

set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
ENV_FILE="${ENV_FILE:-backend/.env}"
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
DEFAULT_NAMES="ODOO_URL ODOO_DB ODOO_LOGIN ODOO_API_KEY PEAK_UAT_CONNECT_ID PEAK_UAT_PASSWORD PEAK_UAT_USER_TOKEN AUTH_SESSION_SECRET AUTH_TEST_ACCOUNTS AUTH_ALLOWLIST GOOGLE_CLIENT_ID"
# PUSH_SECRETS_NAMES selects a subset — needed because AUTH_TEST_ACCOUNTS is pushed
# by staging_accounts.sh (per-role passwords), and a full run would overwrite that
# version with the .env copy. Example: PUSH_SECRETS_NAMES=GOOGLE_CLIENT_ID ./scripts/push_secrets.sh --apply
NAMES="${PUSH_SECRETS_NAMES:-$DEFAULT_NAMES}"

# Paths are quoted against the repo root, so the script works from any directory.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# gcloud refuses Python 3.9 and macOS ships only 3.9, so a portable 3.12 is used.
[ -f "$HOME/.volt-gcloud-env" ] && . "$HOME/.volt-gcloud-env"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

BACKEND_PYTHON="$ROOT/backend/.venv/bin/python"
[ -x "$BACKEND_PYTHON" ] || { echo "backend/.venv is missing; run the backend once" >&2; exit 1; }

# The value exactly as the APP reads it — backend/app/integrations/__init__.py's
# reader: strip the line, split on the first '=', strip whitespace, then one layer of
# matching quotes. A grep/cut here disagreed with the app: backend/.env writes
# ODOO_URL="https://odoo.volt.co.th" with a space before the newline, so the pushed
# secret kept its quotes and the crm.lead job died "Request URL is missing an
# 'http://' or 'https://' protocol" on staging while every local run was green
# (2026-09-21). One reader, one meaning.
read_env_value() {
  "$BACKEND_PYTHON" - "$ENV_FILE" "$1" <<'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
for line in open(path, encoding="utf-8").read().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    if k.strip() != key:
        continue
    print(v.strip().strip('"').strip("'"), end="")
    break
PYEOF
}

say "Preflight"
[ -f "$ENV_FILE" ] || { echo "$ENV_FILE not found" >&2; exit 1; }
# The auth check gates --apply only. A dry run reads nothing from Google and writes
# nothing to it, so it stays useful before Arina has ever logged in.
if [ "$APPLY" -eq 1 ]; then
  if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
    echo "No active account. Run:  gcloud auth login" >&2; exit 1
  fi
else
  echo "DRY RUN — no version is added. Re-run with --apply."
fi

say "Secrets from $ENV_FILE"
for name in $NAMES; do
  if [ "$name" = "AUTH_SESSION_SECRET" ]; then
    if [ "$APPLY" -eq 1 ]; then
      gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1 \
        || gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic >/dev/null
      if gcloud secrets versions list "$name" --project "$PROJECT" --limit 1 --format='value(name)' 2>/dev/null | grep -q .; then
        # A new value would sign every tester out mid-round. Rotating is a deliberate act.
        echo "  $name: kept — a version exists"
      else
        # Generated and piped straight in: never echoed, never an argument, never in the file.
        python3 -c 'import secrets,sys;sys.stdout.write(secrets.token_urlsafe(48))' \
          | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=- >/dev/null
        echo "  $name: fresh value generated — version added"
      fi
    else
      echo "  $name: not read from $ENV_FILE — with --apply, a fresh value if the secret has no version, else kept"
    fi
    continue
  fi
  value="$(read_env_value "$name")"
  if [ -z "$value" ]; then echo "  $name: EMPTY in $ENV_FILE — skipped"; continue; fi
  if [ "$APPLY" -eq 1 ]; then
    gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1 \
      || gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic >/dev/null
    printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=- >/dev/null
    echo "  $name: version added"
  else
    # The length is the only thing safe to show: it catches a truncated or padded
    # value without putting the value itself on a terminal or into scrollback.
    echo "  $name: would add one version (${#value} bytes)"
  fi
done

cat <<OUT

Next:
  ./scripts/deploy_gcp.sh                    # wires these secrets onto the service
OUT
