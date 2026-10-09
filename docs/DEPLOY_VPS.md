# Deploying volt-debt-platform to a DigitalOcean VPS

This guide covers running **two isolated environments** on a single DigitalOcean VPS:

- **Staging** → `debt.volt.co.th` (auto-deploy on PR merge)
- **Production** → `collection.volt.co.th` (manual promote via tag)

> **Actual deployment status — 2026-10-08.** Staging runs as designed
> (`volt-debt-stg` project from `compose.staging.yaml`), on host ports
> **8091 (api) / 8090 (web)** because production holds 8081/8080. Production
> still runs on the **legacy single-environment stack** (`infra/vps/compose.yaml`
> + `/etc/volt-debt/compose.pool.override.yaml`, env `/etc/volt-debt/stack.env`)
> because it holds the live database — `collection.volt.co.th` routes to
> `api`/`web`. `compose.production.yaml` is **deferred**: do not start it without
> a planned production data migration and cutover. The shared edge
> (`volt-debt-edge-1`) is attached to the external network `volt-edge-net`
> (persisted in `/etc/volt-debt/compose.edge.override.yaml`) so it can resolve
> `api-stg`/`web-stg`. Staging's `db-stg` mounts
> `/etc/volt-debt/staging/init-runtime.sql` (must be owned by uid 999, the
> container's postgres user, or initdb silently skips it).

---

## Architecture

```
VPS (8GB RAM / 4 vCPU / 160GB SSD)
├── STAGING (debt.volt.co.th)
│   ├── db-stg (PostgreSQL 512MB)
│   ├── api-stg (FastAPI 1GB)
│   ├── worker-stg (queue 1.5GB)
│   ├── scanner-stg (ClamAV 2GB)
│   └── web-stg (nginx 128MB)
│
├── PRODUCTION (collection.volt.co.th)
│   ├── db-prd (PostgreSQL 512MB)
│   ├── api-prd (FastAPI 1GB)
│   ├── worker-prd (queue 1.5GB)
│   ├── scanner-prd (ClamAV 2GB)
│   └── web-prd (nginx 128MB)
│
└── SHARED
    └── edge (Caddy 128MB) — routes by Host header
```

**Complete isolation**: separate databases, separate scanners, separate data volumes, separate backups.

---

## 1. Provision the VPS

| Setting | Value |
|---------|-------|
| Provider | DigitalOcean Droplet |
| Image | Ubuntu 24.04 LTS |
| Size | **8GB RAM / 4 vCPU / 160GB SSD** |
| Region | Singapore (sfo3) — closest to Thailand |
| SSH key | Add your public key during creation |

### Run the provisioning script

```bash
# SSH into the VPS as root
ssh root@<VPS_IP>

# Download and run
curl -fsSL https://raw.githubusercontent.com/OWNER/volt-debt-platform/main/infra/vps/provision-vps.sh -o /tmp/provision.sh
chmod +x /tmp/provision.sh
/tmp/provision.sh
```

The script installs Docker, clones the repo, creates both environment directories, sets up firewall, and starts Caddy.

---

## 2. Configure Staging

### Edit environment

```bash
cd /srv/volt-debt-platform
nano .env.staging
```

Set:
- `POSTGRES_PASSWORD` — strong password for staging DB
- `API_IMAGE` / `WEB_IMAGE` / `SCANNER_IMAGE` — GHCR image tags

### Edit secrets

```bash
nano /etc/volt-debt/staging/api.env
```

Set:
- `DATABASE_URL` — staging DB connection string
- `AUTH_SESSION_SECRET` — random 32+ bytes
- `GOOGLE_CLIENT_ID` — from Google Cloud Console
- `CLAMAV_HOST` — should be `scanner-stg`

### Initialise staging database

```bash
cd /srv/volt-debt-platform
docker compose -f infra/vps/compose.staging.yaml --env-file .env.staging --profile setup run migrate-stg
```

### Start staging stack

```bash
docker compose -f infra/vps/compose.staging.yaml --env-file .env.staging --profile staging up -d
```

### Verify staging

```bash
curl -sf http://127.0.0.1:8090/healthz   # web-stg → "ok"
curl -sf http://127.0.0.1:8091/readyz    # api-stg → 200
```

---

## 3. Configure Production

> **Deferred — production currently runs on the legacy stack.** The steps below
> describe the future `volt-debt-prd` stack. The live site `collection.volt.co.th`
> is served by the existing `volt-debt` project (`api`/`web`, host ports
> 8081/8080, env `/etc/volt-debt/stack.env`) which holds the production database.
> Migrating production onto this stack requires a separate data-migration and
> cutover plan with backup and reconciliation — never start it as a fresh empty
> database in place of the live one.

### Edit environment

```bash
cd /srv/volt-debt-platform
nano .env.production
```

Set:
- `POSTGRES_PASSWORD` — **different** password from staging
- `API_IMAGE` / `WEB_IMAGE` / `SCANNER_IMAGE` — immutable version tags (e.g., `v1.0.0`)

### Edit secrets

```bash
nano /etc/volt-debt/production/api.env
```

Set:
- `DATABASE_URL` — production DB connection string
- `AUTH_SESSION_SECRET` — **different** secret from staging
- `GOOGLE_CLIENT_ID` — from Google Cloud Console
- `CLAMAV_HOST` — should be `scanner-prd`

### Initialise production database (fresh start)

```bash
cd /srv/volt-debt-platform
docker compose -f infra/vps/compose.production.yaml --env-file .env.production --profile setup run migrate-prd
```

### Start production stack

```bash
docker compose -f infra/vps/compose.production.yaml --env-file .env.production --profile production up -d
```

### Verify production

```bash
curl -sf http://127.0.0.1:8083/healthz   # web-prd → "ok"
curl -sf http://127.0.0.1:8082/readyz    # api-prd → 200
```

---

## 4. DNS Configuration

Add these A records at your DNS provider:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `debt` | `<VPS_IP>` | 300 |
| A | `collection` | `<VPS_IP>` | 300 |

TLS certificates will be issued automatically by Caddy on first request.

---

## 5. GitHub Actions Setup

### Add repository secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|--------|-------|
| `STAGING_HOST` | VPS IP address |
| `STAGING_SSH_KEY` | Private SSH key (ed25519) |

### Staging workflow (automatic)

```
feature-branch → PR → merge into `staging` branch
  ↓
GitHub Actions: test → build :staging → SSH deploy
  ↓
debt.volt.co.th updated automatically
```

### Production workflow (manual)

```bash
# 1. Tag a release (from main)
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# 2. GitHub Actions builds :v1.0.0 images → creates GitHub Release

# 3. SSH to VPS and deploy
ssh root@<VPS_IP>
cd /srv/volt-debt-platform
git fetch origin && git checkout v1.0.0

# Update image tags
sed -i 's|API_IMAGE=.*|API_IMAGE=ghcr.io/OWNER/volt-debt-api:v1.0.0|' .env.production
sed -i 's|WEB_IMAGE=.*|WEB_IMAGE=ghcr.io/OWNER/volt-debt-web:v1.0.0|' .env.production

# Pull and restart
docker compose -f infra/vps/compose.production.yaml --env-file .env.production pull
docker compose -f infra/vps/compose.production.yaml --env-file .env.production --profile production up -d --remove-orphans

# 4. Verify
curl -sf http://127.0.0.1:8083/healthz
curl -sf http://127.0.0.1:8082/readyz
```

---

## 6. Operations

### View logs

```bash
# Staging
docker compose -f infra/vps/compose.staging.yaml logs -f api-stg
docker compose -f infra/vps/compose.staging.yaml logs -f worker-stg

# Production
docker compose -f infra/vps/compose.production.yaml logs -f api-prd
docker compose -f infra/vps/compose.production.yaml logs -f worker-prd

# Edge (Caddy)
docker logs volt-debt-edge
```

### Restart a service

```bash
# Staging
docker compose -f infra/vps/compose.staging.yaml restart api-stg

# Production
docker compose -f infra/vps/compose.production.yaml restart api-prd
```

### Database backup

Backups run automatically via systemd timers:
- Staging: daily at 02:15 Bangkok time
- Production: daily at 03:15 Bangkok time

Manual backup:
```bash
systemctl start volt-debt-backup-staging.service
systemctl start volt-debt-backup-production.service
```

Backups stored in:
- `/var/backups/volt-debt-staging/`
- `/var/backups/volt-debt-production/`

### Health checks

Health checks run every 5 minutes via systemd timers. Manual:
```bash
systemctl start volt-debt-health-staging.service
systemctl start volt-debt-health-production.service
```

### Update Caddy config

```bash
nano /srv/volt-debt-platform/infra/vps/Caddyfile
docker restart volt-debt-edge
```

### Disk cleanup

```bash
docker system prune -af --filter "until=72h"
```

---

## 7. Rollback

### Staging (automatic — just revert the PR)

### Production (manual rollback)

```bash
ssh root@<VPS_IP>
cd /srv/volt-debt-platform

# Switch to previous version
sed -i 's|:v1.0.0|:v0.9.0|g' .env.production

# Pull and restart
docker compose -f infra/vps/compose.production.yaml --env-file .env.production pull
docker compose -f infra/vps/compose.production.yaml --env-file .env.production --profile production up -d --remove-orphans
```

---

## 8. What replaced what (GCP → VPS)

| GCP service | VPS replacement |
|-------------|-----------------|
| Cloud Run (debt-api) | Docker Compose service `api-stg` / `api-prd` |
| Cloud Run (debt-web) | Docker Compose service `web-stg` / `web-prd` |
| Cloud SQL (PostgreSQL) | Docker Compose service `db-stg` / `db-prd` |
| Pub/Sub | Docker Compose service `worker-stg` / `worker-prd` |
| Cloud Scheduler | Systemd timers |
| Cloud Build | GitHub Actions |
| Artifact Registry | GitHub Container Registry (ghcr.io) |
| Secret Manager | `/etc/volt-debt/{staging,production}/api.env` |
| Cloud Load Balancer + TLS | Caddy (automatic Let's Encrypt) |
| Cloud Monitoring | Health check timers + `healthcheck.py` |
| Terraform | Not needed (single host, compose files) |

---

## 9. Resource Allocation

| Service | Staging | Production | Total |
|---------|---------|------------|-------|
| PostgreSQL | 512MB | 512MB | 1GB |
| API | 1GB | 1GB | 2GB |
| Worker | 1.5GB | 1.5GB | 3GB |
| ClamAV | 2GB | 2GB | 4GB |
| Web (nginx) | 128MB | 128MB | 256MB |
| Caddy | — | — | 128MB |
| **Subtotal** | **5.1GB** | **5.1GB** | **~10.5GB** |

**Note**: If memory pressure occurs, options:
- Reduce ClamAV `mem_limit` to 1.5GB each
- Reduce worker `mem_limit` to 1GB each (may slow imports)
- Scale production worker to 0 when idle (scale-to-zero pattern)

---

## 10. File Structure

```
/srv/
├── volt-debt-platform/                    # Source code (Git repo)
│   ├── backend/
│   ├── frontend/
│   └── infra/
│       └── vps/
│           ├── compose.staging.yaml       # Staging stack definition
│           ├── compose.production.yaml    # Production stack definition
│           ├── Caddyfile                  # Routes debt.volt.co.th → staging, collection.volt.co.th → production
│           ├── .env.staging.example       # Staging env template
│           ├── .env.production.example    # Production env template
│           └── provision-vps.sh           # One-shot setup script
│
├── volt-debt-data-staging/                # Staging uploads
│   └── objects/
│
└── volt-debt-data-production/             # Production uploads
    └── objects/

/etc/volt-debt/
├── staging/
│   └── api.env                            # Staging secrets
└── production/
    └── api.env                            # Production secrets

/var/backups/
├── volt-debt-staging/                     # Staging backups
└── volt-debt-production/                  # Production backups
```
