#!/usr/bin/env bash
#
# Create the tester accounts for a user-testing round and push them to Secret
# Manager as one new version of AUTH_TEST_ACCOUNTS.
#
#   ./scripts/staging_accounts.sh                 # dry run: roster + what would be pushed
#   ./scripts/staging_accounts.sh --show-roster   # roster only, no hashing, nothing pushed
#   ./scripts/staging_accounts.sh --apply         # hash + push one secret version
#
# Four accounts, one per role — the 2026-09-21 choice for a shared-account round:
# testers hand these around, the audit log records the ROLE (not the person), and the
# invitation asks testers to say who they are in their feedback. The hashes are
# produced by the backend's own auth.hash_password, so the deploy cannot drift from
# the checker.
#
# PER-ROLE PASSWORDS (owner, 2026-09-21): one password per role, so only the officer
# password goes to the officers and only the manager password to the managers. Give a
# password with AUTH_TEST_PASSWORD_<ROLE> (OFFICER / SUPERVISOR / MANAGER / OWNER);
# any role left unsaid gets a fresh generated password. --apply writes a private
# handoff file, never passwords to stdout. AUTH_TEST_PASSWORD remains a fallback
# (the previous single-password model).
#
# After pushing, the service needs a new revision to read the new version:
#   gcloud run services update volt-debt-uat --region asia-southeast1 \
#     --update-secrets AUTH_TEST_ACCOUNTS=AUTH_TEST_ACCOUNTS:latest
set -euo pipefail
umask 077

PROJECT="${PROJECT:?set PROJECT to the GCP project id}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="dry"
case "${1:-}" in
  --apply) MODE="apply" ;;
  --show-roster) MODE="roster" ;;
  "") ;;
  *) echo "unknown flag: $1 (use --apply or --show-roster)" >&2; exit 2 ;;
esac

# gcloud refuses Python 3.9 and macOS ships only 3.9, so a portable 3.12 is used.
[ -f "$HOME/.volt-gcloud-env" ] && . "$HOME/.volt-gcloud-env"
BACKEND_PYTHON="$ROOT/backend/.venv/bin/python"
[ -x "$BACKEND_PYTHON" ] || { echo "backend/.venv is missing; run the backend once" >&2; exit 1; }

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

say "Preflight"
if [ "$MODE" = "apply" ]; then
  if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
    echo "No active account. Run:  gcloud auth login" >&2; exit 1
  fi
elif [ "$MODE" = "dry" ]; then
  echo "DRY RUN — nothing is pushed. Re-run with --apply."
fi

ROLES="OFFICER SUPERVISOR MANAGER OWNER"
GENERATED=""
if [ "$MODE" != "roster" ]; then
  # One password per role. bash 3.2 supports ${!name} indirect expansion, which is
  # what keeps the four variables out of four near-identical branches.
  for role in $ROLES; do
    var="AUTH_TEST_PASSWORD_$role"
    pw="${!var:-}"
    if [ -z "$pw" ]; then pw="${AUTH_TEST_PASSWORD:-}"; fi
    if [ -z "$pw" ]; then
      pw="$("$BACKEND_PYTHON" -c 'import secrets; print(secrets.token_urlsafe(12))')"
      GENERATED="$GENERATED $role"
    fi
    export "AUTH_TEST_PW_$role=$pw"
    unset pw
  done
fi

# One helper run: read the officer registry and hash with the backend's own helper.
# Passwords travel in environment variables, never as argv (ps is public). stdout is
# the AUTH_TEST_ACCOUNTS JSON; stderr is the human-readable roster.
HASH_PY='
import json, os, sys
from app import auth, officers

rows = officers.registry()

def officer_for(role):
    for row in rows:
        if role in row.get("roles", ()) or row.get("role") == role:
            return row["uid"]
    raise SystemExit("no registry officer holds role %s" % role)

# Each account is bound to a real registry officer of that role so every act signs as
# somebody the registry knows.
named = (("officer", "OFFICER"), ("supervisor", "SUPERVISOR"),
         ("manager", "MANAGER"), ("owner", "OWNER"))
accounts, roster = {}, []
for user, role in named:
    officer = officer_for(role)
    password = os.environ.get("AUTH_TEST_PW_%s" % role, "")
    accounts[user] = {"hash": auth.hash_password(password), "role": role, "officer": officer} \
        if password else {"role": role, "officer": officer}
    roster.append((user, role, officer))
for user, role, officer in roster:
    print("  account  %-12s %-11s %s" % (user, role, officer), file=sys.stderr)
print(json.dumps(accounts, separators=(",", ":")), end="")
'

say "Accounts (roster from the officer registry)"
ACCOUNTS_JSON="$(cd "$ROOT/backend" && env AUTH_MODE= "$BACKEND_PYTHON" -c "$HASH_PY")"
if [ "$MODE" = "roster" ]; then
  echo
  echo "  (roster only — no password is generated, hashed or pushed)"
  exit 0
fi

if [ "$MODE" = "apply" ]; then
  # Save recoverable handoff BEFORE publishing hashes. Only the file path is
  # printed; supplied and generated passwords never enter terminal/CI logs.
  HANDOFF_FILE="$(env AUTH_TEST_GENERATED_ROLES="$GENERATED" "$BACKEND_PYTHON" - <<'PY'
import json, os, secrets
from datetime import datetime, timezone
from pathlib import Path

directory = Path(os.environ.get("VOLT_TEST_HANDOFF_DIR", str(Path.home() / ".volt-test-account-handoff")))
if not directory.is_absolute() or directory.is_symlink() or directory.resolve() != directory:
    raise SystemExit("Handoff directory must be absolute and contain no symlinks")
directory.mkdir(parents=True, mode=0o700, exist_ok=True)
info = directory.stat()
if info.st_uid != os.geteuid():
    raise SystemExit("Handoff directory must belong to the invoking user")
if info.st_mode & 0o077:
    raise SystemExit("Existing handoff directory must already be private (mode 0700)")
created = datetime.now(timezone.utc)
generated = set(os.environ.get("AUTH_TEST_GENERATED_ROLES", "").split())
accounts = [{"username": role.lower(), "role": role,
             "password": os.environ["AUTH_TEST_PW_" + role], "generated": role in generated}
            for role in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER")]
name = "accounts-" + created.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(8) + ".json"
directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    with os.fdopen(descriptor, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump({"created_at_utc": created.isoformat(), "project": os.environ["PROJECT"],
                   "accounts": accounts, "handoff_prepared": True}, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
print(directory / name)
PY
)"
  say "Private password handoff prepared: $HANDOFF_FILE"
  say "Pushing AUTH_TEST_ACCOUNTS:latest to $PROJECT"
  printf '%s' "$ACCOUNTS_JSON" | gcloud secrets versions add AUTH_TEST_ACCOUNTS \
    --project "$PROJECT" --data-file=- --quiet
  unset ACCOUNTS_JSON
  echo "  Secret version uploaded successfully; handoff remains mode 0600."
  say ""
  echo "  The service needs a NEW revision to read this version:"
  echo "    gcloud run services update volt-debt-uat --region asia-southeast1 \\"
  echo "      --update-secrets AUTH_TEST_ACCOUNTS=AUTH_TEST_ACCOUNTS:latest"
  echo "  The previous passwords stop working only after that revision serves."
else
  echo
  echo "  (dry run: no secret version added)"
fi
for role in $ROLES; do unset "AUTH_TEST_PW_$role"; done
