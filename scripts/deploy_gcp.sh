#!/usr/bin/env bash
#
# Deploy the Volt Debt prototype to Cloud Run for a UAT feedback round.
#
# ONE service, not two. Production keeps debt-api and debt-web apart (§5.1, §5.2)
# and both Dockerfiles still stand for that. But a split web tier has to mint an
# identity token for every call to a private API service, which nginx cannot do
# natively; one origin removes that, and CORS and a second IAP session with it.
#
# This creates: one Cloud Run service. It does NOT create Cloud SQL, KMS, Pub/Sub,
# Cloud Tasks, Scheduler, VPC, NAT, Cloud Armor or GCS — everything in
# infra/terraform stays unapplied until the MVP needs it.
#
# ACCESS=public (the 2026-09-21 user-testing choice) serves the link with the app's
# own login page as the gate; ACCESS=iap keeps the Google-IAP gate. The service
# always has a database by the end of this script, and tester state lives in
# `app.session_state` on Cloud SQL — a revision restart does NOT clear it.

set -euo pipefail

PROJECT="${PROJECT:?set PROJECT to the GCP project id}"
REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-volt-debt-uat}"
DOMAIN="${DOMAIN:-volt.co.th}"
INSTANCE="${INSTANCE:-debt-pg-stg}"
# public | iap. Public is the user-testing default: testers outside the org have no
# Google account in the project, and the app's own login (AUTH_MODE=on, role test
# accounts) plus the audit log are the gates. IAP stays available for locked rounds.
ACCESS="${ACCESS:-public}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

say "Toolchain"
# gcloud refuses Python 3.9 and macOS ships only 3.9, so a portable 3.12 is used.
[ -f "$HOME/.volt-gcloud-env" ] && . "$HOME/.volt-gcloud-env"
gcloud --version | head -1
gcloud config set project "$PROJECT" >/dev/null
gcloud config set run/region "$REGION" >/dev/null

say "Preflight"
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
  echo "No active account. Run:  gcloud auth login" >&2
  exit 1
fi
if ! gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  echo "Billing is not enabled on $PROJECT. Cloud Run and Cloud Build both require it." >&2
  exit 1
fi

say "Enabling the four APIs this needs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com iap.googleapis.com --quiet

say "Verifying before shipping"
# A deploy that ships a red build wastes a tester's morning, so the suites run first.
( cd backend && .venv/bin/python -m pytest -q )
( cd frontend && npx vitest run )

say "Building the interface into the API image"
( cd frontend && npm ci --no-audit --no-fund >/dev/null 2>&1 || npm install --no-audit --no-fund >/dev/null )
( cd frontend && npm run build )
rm -rf backend/static
cp -R frontend/dist backend/static

# app/imports.py loads scripts/import_master_sheet.py at import time, and `--source
# backend` uploads only backend/. Without this the container builds fine and then
# dies on start-up with FileNotFoundError, which no local test can catch: in a
# checkout the file resolves one directory higher and is always found.
rm -rf backend/scripts
mkdir -p backend/scripts
cp scripts/import_master_sheet.py backend/scripts/

# Same reason, one directory over: app/pipelines/rules.py reads
# docs/odoo-comparison/odoo_compare.md, which `--source backend` cannot see. Staged
# into backend/docs/ so the reader's second candidate finds it (2026-09-21: the
# crm.lead pull on staging exited "rules_unreadable" without this).
rm -rf backend/docs
mkdir -p backend/docs/odoo-comparison
cp docs/odoo-comparison/odoo_compare.md backend/docs/odoo-comparison/

# Odoo and PEAK UAT credentials (push_secrets.sh). Named once: the first deploy and the
# Cloud SQL update below both carry them.
INTEGRATION_SECRETS="ODOO_URL=ODOO_URL:latest,ODOO_DB=ODOO_DB:latest,ODOO_LOGIN=ODOO_LOGIN:latest,ODOO_API_KEY=ODOO_API_KEY:latest,PEAK_UAT_CONNECT_ID=PEAK_UAT_CONNECT_ID:latest,PEAK_UAT_PASSWORD=PEAK_UAT_PASSWORD:latest,PEAK_UAT_USER_TOKEN=PEAK_UAT_USER_TOKEN:latest,PEAK_WEBHOOK_KEY=peak-webhook-key-uat:latest"

say "Login (design 2026-09-13)"
# Decided BEFORE the first deploy, and carried by it. `run deploy --set-env-vars`
# replaces every variable, so a login added by a later update left each redeploy
# serving a login-off revision until that update landed — and if it failed, the
# open revision stayed. Configured but broken must refuse, never fall back to open.
# Only secrets that HOLD a version are wired; a secret with no version fails the
# whole deploy. GOOGLE_CLIENT_ID stays empty until the OAuth Web client exists, and
# until then the login page offers test accounts only.
# A secret that does not exist, or exists with no version, is "not wired". Any OTHER
# gcloud failure (permissions, network, expired login) stops the deploy: treated as
# "no version", it used to ship a login-OFF revision behind one yellow line.
AUTH_SECRETS=""
for name in AUTH_SESSION_SECRET AUTH_TEST_ACCOUNTS AUTH_ALLOWLIST GOOGLE_CLIENT_ID; do
  # state:ENABLED — a DESTROYED version still appears in the list, and wiring it made
  # `latest` resolve to a tombstone: the deploy failed with "Secret Version ... is in
  # DESTROYED state" (2026-09-21, after GOOGLE_CLIENT_ID's versions were destroyed for
  # the test-accounts-only round). Destroyed means not wired, like absent.
  if versions="$(gcloud secrets versions list "$name" --project "$PROJECT" --limit 1 \
        --filter='state:ENABLED' --format='value(name)' 2>/tmp/volt-secret-check.err)"; then
    :
  elif grep -q "NOT_FOUND" /tmp/volt-secret-check.err; then
    versions=""
  else
    echo "  $name: the version check itself failed — refusing to guess whether login is on:" >&2
    cat /tmp/volt-secret-check.err >&2
    exit 1
  fi
  if [ -n "$versions" ]; then
    AUTH_SECRETS="${AUTH_SECRETS:+$AUTH_SECRETS,}$name=$name:latest"
  else
    echo "  $name: no version — not wired"
  fi
done
rm -f /tmp/volt-secret-check.err
LOGIN_ON=0
if printf '%s' "$AUTH_SECRETS" | grep -q "AUTH_SESSION_SECRET="; then LOGIN_ON=1; fi
# Never empty, so bash 3.2 (macOS) expands it safely under set -u.
# Structured phase timing starts before the 1.5 s warning line, and SQL over 100 ms
# is logged separately so staging traces show which layer owns the latency.
DEPLOY_FLAGS=(--set-env-vars "ENV=uat,SLOW_REQUEST_MS=1200,SLOW_SQL_MS=100")
if [ "$LOGIN_ON" -eq 1 ]; then
  # The service account rides on the first deploy too: the secrets are readable by
  # debt-api-sa only, and the first revision already needs AUTH_SESSION_SECRET.
  # --set-secrets replaces every mapping, so the integrations ride along; without them
  # the new revision ran with Odoo and PEAK dark until the Cloud SQL step below.
  DEPLOY_FLAGS=(--set-env-vars "ENV=uat,AUTH_MODE=on,AUTH_ALLOW_TEST_ACCOUNTS=true,SLOW_REQUEST_MS=1200,SLOW_SQL_MS=100"
                --set-secrets "$INTEGRATION_SECRETS,$AUTH_SECRETS"
                --service-account "debt-api-sa@$PROJECT.iam.gserviceaccount.com")
  echo "  on — AUTH_MODE=on from the first revision"
else
  printf '\033[33m  SKIPPED — AUTH_SESSION_SECRET has no version; login stays off.\033[0m\n'
fi

say "Deploying to Cloud Run (Cloud Build compiles the image — no local Docker)"
# Four requests per instance avoids CPU/JSON contention; capacity comes from up to
# five instances. Session state is restored from app.session_state on first touch.
# The lockout counter in auth.py is per process too, and one instance keeps it whole.
# --no-allow-unauthenticated: the service is closed until IAP is attached below.
# Nothing is ever public, not even for the seconds between deploy and IAP.
# 2026-09-21 sizing for the user-testing round: 1Gi because a 25 MB sheet upload can
# hold several hundred MB while parsing (app/imports.py's own ceiling note), and
# --no-cpu-throttling because the crm.lead thread and the upload threads must keep
# running between requests. min 1 also pre-warms the revision before testers arrive.
# 2026-09-25: 2Gi — the New Order Master-6 upload (23 MB) went past 1Gi twice on
# staging (1,222 MiB, then 1,079 MiB) and the instance was killed mid-install.
ACCESS_FLAGS=(--allow-unauthenticated)
[ "$ACCESS" = "iap" ] && ACCESS_FLAGS=(--no-allow-unauthenticated)
gcloud run deploy "$SERVICE" \
  --source backend \
  --region "$REGION" \
  --platform managed \
  "${ACCESS_FLAGS[@]}" \
  --port 8080 \
  --cpu 1 --memory 2Gi --no-cpu-throttling \
  --concurrency 4 --min-instances 1 --max-instances 5 \
  "${DEPLOY_FLAGS[@]}" \
  --quiet

say "Putting IAP in front of it"
if [ "$ACCESS" != "iap" ]; then
  printf '\033[33m  SKIPPED — ACCESS=%s. The link is PUBLIC; the app login page and the\n' "$ACCESS"
  printf '  audit log are the gates. Set ACCESS=iap for a locked round.\033[0m\n'
else
# The consent screen is console-only: the IAP OAuth Admin API that once created it
# was shut down in March 2026. Without one, --iap fails, and set -e would take the
# database, the secrets, both Jobs and the Scheduler job down with it. So the step
# is skipped LOUDLY rather than fatally. The service is still closed either way —
# --no-allow-unauthenticated is already in force and nobody holds run.invoker — but
# no tester can sign in until the screen exists and this script is run again.
IAP_ATTACHED=0
if gcloud iap oauth-brands list --project "$PROJECT" --format='value(name)' 2>/dev/null | grep -q .; then
  gcloud run services update "$SERVICE" --region "$REGION" --iap --quiet
  say "Admitting $DOMAIN"
  gcloud iap web add-iam-policy-binding \
    --resource-type=cloud-run --service="$SERVICE" --region="$REGION" \
    --member="domain:$DOMAIN" --role='roles/iap.httpsResourceAccessor' --quiet
  IAP_ATTACHED=1
else
  printf '\033[33m  SKIPPED — no IAP consent screen exists on %s.\033[0m\n' "$PROJECT"
  printf '  Create it in the console, then re-run this script to attach IAP.\n'
  printf '  Until then the service is deployed but UNREACHABLE by testers.\n'
  fi
fi

CONN="$PROJECT:$REGION:${INSTANCE:-debt-pg-stg}"
# One URL per identity, not one URL. With IAM database authentication the token is
# minted for whoever the container RUNS as, so the username in the URL must name that
# same account. The service runs as debt-api-sa and the Jobs as debt-jobs-sa; sharing
# one URL made the Jobs present a jobs token under the api name, which Postgres
# rejects as "Cloud SQL IAM service account authentication failed".
db_url_for() { printf 'postgresql+psycopg://%s@%s.iam@/debt?host=/cloudsql/%s' "$1" "$PROJECT" "$CONN"; }
DB_URL_API="$(db_url_for debt-api-sa)"
DB_URL_JOBS="$(db_url_for debt-jobs-sa)"

say "Cloud Run Jobs"
# debt-odoo-sync (the sale.order pull) went on 2026-09-25 — the crm.lead job is the only
# Odoo door. An estate deployed before then still carries it: delete it by hand.
for job in "debt-migrate:app.migrate" "debt-crm-lead-sync:app.jobs.crm_lead_sync"; do
  name="${job%%:*}"; module="${job##*:}"
  env="DATABASE_URL=$DB_URL_JOBS"
  # Only the migration grants: it is the job that creates the schemas and therefore
  # the only one that owns them. DATABASE_URL carries no comma, so this stays one
  # --set-env-vars value.
  [ "$name" = "debt-migrate" ] && env="$env,DB_RUNTIME_ROLE=debt-api-sa@$PROJECT.iam"
  # --set-secrets: the crm.lead job talks to Odoo, so it needs the same integration
  # credentials the service carries. Without this the scheduled refetch exited 2
  # ("odoo is not configured") on a correctly-provisioned estate (found 2026-09-21).
  # debt-jobs-sa holds secretAccessor at the project level (provision_stg.sh).
  gcloud run jobs deploy "$name" --region "$REGION" --source backend \
    --command python --args="-m,$module" \
    --set-cloudsql-instances "$CONN" \
    --service-account "debt-jobs-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-secrets "$INTEGRATION_SECRETS" \
    --set-env-vars "$env" --quiet
done

say "Migrating the database BEFORE the service is pointed at it"
# Order matters and cost a deploy to learn. app/main.py reads app.session_state at
# import time, so a service handed DATABASE_URL before the schema exists cannot start
# at all — it fails the startup probe with UndefinedTable and the revision is rolled
# back. The job owns the schema, so the job has to run first. Idempotent: migrate.py
# is CREATE TABLE IF NOT EXISTS throughout, so re-running it costs nothing.
gcloud run jobs execute debt-migrate --region "$REGION" --wait --quiet

say "The first crm.lead pull, BEFORE the service is pointed at the database"
# 2026-09-21, learned on a fresh estate: with DATABASE_URL attached, the service
# builds its book from landing — and officers.registry() is built from the served
# rows. An empty landing means an allow-listed officer is missing from
# /v1/officers, and auth.check_officers refuses to start (correctly). So the first
# pull runs here, while the service still serves the fixture book. Best-effort: a
# staging round with no Odoo credentials must not block the deploy — the service
# can still start if every allow-listed officer exists as a fixture identity.
gcloud run jobs execute debt-crm-lead-sync --region "$REGION" --wait --quiet \
  || printf '\033[33m  the first pull failed or is not configured — the service will start on the fixture book\033[0m\n'

say "Attaching Cloud SQL, the secrets, and DATABASE_URL"
# --update-*, not --set-*: a set here replaced every variable and secret the deploy
# above carried, and the login went with them.
gcloud run services update "$SERVICE" --region "$REGION" \
  --add-cloudsql-instances "$CONN" \
  --service-account "debt-api-sa@$PROJECT.iam.gserviceaccount.com" \
  --update-env-vars "DATABASE_URL=$DB_URL_API" \
  --update-secrets "$INTEGRATION_SECRETS" \
  --quiet

say "The 2-hour crm.lead refetch (2026-09-25; was 15 minutes)"
# The durable copy of the in-process schedule: Cloud Run scales to zero, so a daemon
# thread in the service cannot promise a cadence. (The 02:00 odoo-reconcile schedule
# of the sale.order job went with that job on 2026-09-25.)
gcloud scheduler jobs create http crm-lead-refresh --location "$REGION" \
  --schedule "0 */2 * * *" --time-zone "Asia/Bangkok" \
  --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/debt-crm-lead-sync:run" \
  --http-method POST \
  --oauth-service-account-email "debt-jobs-sa@$PROJECT.iam.gserviceaccount.com" \
  --quiet || echo "  (already exists)"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
say "Deployed"
cat <<OUT
  URL      $URL
  Access   $([ "$ACCESS" = "iap" ] && echo "Google sign-in via IAP, $DOMAIN accounts only" \
             || echo "PUBLIC link + app login (role test accounts); audit log on")
  Login    $([ "$LOGIN_ON" -eq 1 ] && echo "on — the app's own login page is the gate" || echo "off")
  Data     crm.lead / Odoo UAT + PEAK UAT. 13-digit ids are never written; phone masked with an audited reveal.
  State    Per browser session, in app.session_state on Cloud SQL. A revision restart does NOT clear it.
  Sync     crm.lead refetches every 2 hours via the debt-crm-lead-sync Job (crm-lead-refresh).

  Tell testers the penalty figures are INDICATIVE: the rate (CF1) is not agreed.
OUT
