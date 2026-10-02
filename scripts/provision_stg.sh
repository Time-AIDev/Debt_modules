#!/usr/bin/env bash
#
# Stand up the Volt Debt staging estate on an EXISTING project.
#
#   ./scripts/provision_stg.sh              # dry run: prints every command, changes nothing
#   ./scripts/provision_stg.sh --apply      # actually creates
#
# Thin by decision (spec §4). Cloud Run's native Cloud SQL connector needs no VPC,
# no serverless connector and no NAT, which is what keeps this to one page.

set -euo pipefail

PROJECT="${PROJECT:?set PROJECT to the GCP project id, e.g. volt-debt-stg}"
REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-volt-debt-uat}"
INSTANCE="${INSTANCE:-debt-pg-stg}"
DB_NAME="${DB_NAME:-debt}"
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1

# gcloud refuses Python 3.9 and macOS ships only 3.9, so a portable 3.12 is used.
[ -f "$HOME/.volt-gcloud-env" ] && . "$HOME/.volt-gcloud-env"

# Every mutating call goes through run(), so a dry run is a readable transcript of
# exactly what --apply would do. Nothing here creates anything on its own.
run() {
  printf '\033[36m$ %s\033[0m\n' "$*"
  [ "$APPLY" -eq 1 ] && "$@"
  return 0
}
say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# Creates are the only steps that break on a re-run: "already exists" is an error
# and set -e would stop the script halfway. run_new() forgives exactly that one
# message and nothing else, so a retry finishes the job but a real fault still fails.
run_new() {
  printf '\033[36m$ %s\033[0m\n' "$*"
  [ "$APPLY" -eq 1 ] || return 0
  local out
  if out=$("$@" 2>&1); then
    [ -n "$out" ] && printf '%s\n' "$out"
    return 0
  fi
  if printf '%s' "$out" | grep -qiE 'already exists|alreadyExists|entityAlreadyExists'; then
    printf '  (already exists — left alone)\n'
    return 0
  fi
  printf '%s\n' "$out" >&2
  return 1
}

say "Preflight"
# Before authentication there is nothing safe to do, not even in --apply: an
# anonymous gcloud would either fail halfway or act on somebody else's default project.
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
  echo "No active account. Run:  gcloud auth login" >&2; exit 1
fi
if ! gcloud billing projects describe "$PROJECT" \
     --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  echo "Billing is not enabled on $PROJECT." >&2; exit 1
fi
[ "$APPLY" -eq 1 ] || echo "DRY RUN — nothing will be created. Re-run with --apply."

say "APIs"
run gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    secretmanager.googleapis.com cloudscheduler.googleapis.com \
    cloudbuild.googleapis.com artifactregistry.googleapis.com iap.googleapis.com \
    --project "$PROJECT" --quiet

say "Service accounts"
for sa in debt-api-sa debt-jobs-sa; do
  run_new gcloud iam service-accounts create "$sa" --project "$PROJECT" \
      --display-name "$sa" --quiet
done
for sa in debt-api-sa debt-jobs-sa; do
  # cloudsql.client permits the connection; cloudsql.instanceUser carries
  # cloudsql.instances.login, which is what IAM database auth actually checks.
  for role in roles/cloudsql.client roles/cloudsql.instanceUser roles/secretmanager.secretAccessor; do
    run gcloud projects add-iam-policy-binding "$PROJECT" \
        --member "serviceAccount:$sa@$PROJECT.iam.gserviceaccount.com" \
        --role "$role" --quiet
  done
done

# The public endpoint is deliberate (ruled 2026-09-10, superseding spec §97's "public
# IP disabled"). Cloud Run's native connector only removes the VPC when the instance
# has an address; a private-IP instance would need a VPC, a subnet and PSC, which
# decision D4 refused. No authorized networks are set, so nothing can dial the
# instance over IP — the connector plus IAM is the only way in, and ENCRYPTED_ONLY
# rejects any unencrypted connection.
say "Cloud SQL — PostgreSQL 16, public endpoint with zero authorized networks, IAM auth"
run_new gcloud sql instances create "$INSTANCE" --project "$PROJECT" \
    --database-version POSTGRES_16 --edition ENTERPRISE \
    --tier db-custom-1-3840 --region "$REGION" \
    --storage-type SSD --storage-size 20 --storage-auto-increase \
    --assign-ip --ssl-mode ENCRYPTED_ONLY --availability-type ZONAL \
    --database-flags cloudsql.iam_authentication=on \
    --backup-start-time 18:00 --enable-point-in-time-recovery --quiet
run_new gcloud sql databases create "$DB_NAME" --instance "$INSTANCE" --project "$PROJECT" --quiet
for sa in debt-api-sa debt-jobs-sa; do
  run_new gcloud sql users create "$sa@$PROJECT.iam" --instance "$INSTANCE" \
      --project "$PROJECT" --type CLOUD_IAM_SERVICE_ACCOUNT --quiet
done

say "Secrets — names only; values are pushed separately from backend/.env"
for name in ODOO_URL ODOO_DB ODOO_LOGIN ODOO_API_KEY \
            PEAK_UAT_CONNECT_ID PEAK_UAT_PASSWORD PEAK_UAT_USER_TOKEN; do
  run_new gcloud secrets create "$name" --project "$PROJECT" --replication-policy automatic --quiet
done

say "Budget alert"
echo "  (budgets need a billing account id; see the guidebook — one console step)"

cat <<OUT

Next, in order:
  1. ./scripts/push_secrets.sh --apply       # reads backend/.env, echoes no values
  2. ./scripts/deploy_gcp.sh                 # builds and deploys, attaches Cloud SQL
  3. gcloud run jobs execute debt-migrate --region $REGION
OUT
