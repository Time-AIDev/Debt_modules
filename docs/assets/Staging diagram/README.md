# Staging stacks — free public UAT first, GCP next

| | |
|---|---|
| Made | 2026-09-13, on request: "the quickest, simplest way to put this online for free for UAT, then the easiest move to GCP" |
| Made from | The tree at `a568c13`: `backend/Dockerfile`, `backend/app/db.py`, `backend/app/main.py`, `backend/app/sheet_loader.py`, `scripts/deploy_gcp.sh`. Free-tier limits come from Render's and Neon's own pages, read 2026-09-13. |
| Rank | **Not a ranked row** on the Amendment v2.6 §1 authority ladder. It is a proposal, not a ruling. |
| Rebuild | `./src/build.sh` regenerates all six files from `src/*.py` (emitter shared with `docs/assets/HLD/src/hld_lib.py`) |

## The sheets

| File | What it settles |
| --- | --- |
| `00-the-path` | Laptop → Stage 1 (Render + Neon) → Stage 2 (Cloud Run + Cloud SQL), and a nine-row table of what changes between the two stacks |
| `01-free-uat-stack` | The free stack: people and source, the Render web service and its container, Neon Postgres, the one-time setup in order, what is not wired, and the limits testers will notice |
| `02-gcp-staging-stack` | The GCP stack as `deploy_gcp.sh` builds it: IAP, Cloud Run, Cloud SQL, Cloud Build, Artifact Registry, Secret Manager, the two Jobs, Scheduler, Odoo/PEAK, and the move from Stage 1 |

## The proposal in one paragraph

The app already ships as **one container on one origin**: FastAPI serves `/api/v1/*` and the built React app from `backend/static`. So "frontend hosting" and "backend hosting" are the same host, in both stages. **Stage 1** runs that container on a **Render free web service** and keeps state in **Neon free Postgres**, both in Singapore. A database is needed even for a free UAT, because Render puts the service to sleep after 15 idle minutes and in-memory state would disappear with it. With `DATABASE_URL` set, `app.session_state` keeps tester work. **Stage 2** is the Cloud Run + Cloud SQL estate that `provision_stg.sh` has already half-built and `deploy_gcp.sh` finishes. The move is small because the image, the schema and the `DATABASE_URL` seam are unchanged. Only the database address, the secrets store and the front door (IAP) change.

## Stage 1 — what it needs that the repo does not yet have

1. **A root `Dockerfile`** (two stages: `node:22` builds `frontend/`, then `python:3.12-slim` copies in `backend/app`, `frontend/dist` → `static/`, and `scripts/import_master_sheet.py` → `scripts/`). This is the job `deploy_gcp.sh` does by hand-staging files into `backend/`. Render cannot run that staging, and a Docker build can. The same file also works for `gcloud run deploy --source .` later. **Not written yet.**
2. **A private GitHub repo.** Render deploys from git, and this repo has no remote. Keep it **private**: `backend/app/fixtures_sheet.json` holds 418 customers with real Thai names.
3. **Schema and seed, once, from the laptop:**

   ```bash
   cd backend
   export DATABASE_URL='postgresql+psycopg://USER:PASS@ep-XXXX.ap-southeast-1.aws.neon.tech/neondb?sslmode=require'
   .venv/bin/python -m app.migrate
   .venv/bin/python -c "import json; from app import db, sheet_loader
   c = db.connect()
   with c.begin(): print(sheet_loader.load_payload(c, json.load(open('app/fixtures_sheet.json'))))
   c.close()"
   ```

   The `+psycopg` part is required. A bare `postgresql://` makes SQLAlchemy look for psycopg2, which is not installed.
4. **Environment variables on Render:** `ENV=uat`, `DATABASE_URL`, `AUTH_MODE=on`, `AUTH_ALLOW_TEST_ACCOUNTS=true`, `AUTH_SESSION_SECRET` (a new one, never the laptop's), `AUTH_TEST_ACCOUNTS`, `AUTH_ALLOWLIST`, and later `GOOGLE_CLIENT_ID`. Set the health check path to `/healthz`. **Do not** set the Odoo or PEAK variables: ERP credentials stay off third-party hosts.

## Before a public URL goes out — decisions for Arina

- **Personal data on a public URL.** Stage 1 has no IAP, so the app login is the only thing between the internet and real customer names. Login must be on from the very first deploy. The alternative is a pseudonymised fixture for Stage 1. This is a PDPA call, not an engineering one.
- **Pushing the repo to GitHub**, even privately, puts the fixture on a third party's servers.

## Stage 1 → Stage 2

Follow sheet 02's left-hand note. **Tester work does not carry over.** `app.session_state` is keyed to the browser cookie on the `onrender.com` domain, and that cookie never reaches the GCP URL. If the UAT record matters, export `audit.entry` from Neon before deleting it.

## Not verified

- No Render or Neon account was used. The limits on sheet 01 are the vendors' published numbers, and nothing was measured.
- `gcloud` tokens on this machine had expired (2026-09-13), so the GCP facts on sheet 02 come from the scripts and the 2026-09-10 provisioning record, not a live `describe`.
