#!/usr/bin/env bash
# ============================================================
# provision-vps.sh — one-shot DigitalOcean VPS setup
# Supports dual-environment: staging (debt.volt.co.th) + production (collection.volt.co.th)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/OWNER/volt-debt-platform/main/infra/vps/provision-vps.sh | bash
#
# Or copy to the VPS and run:
#   chmod +x provision-vps.sh && sudo ./provision-vps.sh
#
# What it does:
#   1. Installs Docker, Compose plugin, UFW firewall
#   2. Creates the volt-debt system user (docker group)
#   3. Clones the repository
#   4. Creates /etc/volt-debt/staging/ and /etc/volt-debt/production/
#   5. Creates both data directories
#   6. Creates .env.staging and .env.production from templates
#   7. Copies systemd timers for both environments
#   8. Installs the edge proxy (Caddy)
#   9. Prints next steps for each environment
# ============================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/YOUR_GHCR_OWNER/volt-debt-platform.git}"
REPO_DIR="/srv/volt-debt-platform"
SECRETS_BASE="/etc/volt-debt"
DATA_STAGING="/srv/volt-debt-data-staging"
DATA_PRODUCTION="/srv/volt-debt-data-production"
COMPOSE_STAGING="infra/vps/compose.staging.yaml"
COMPOSE_PRODUCTION="infra/vps/compose.production.yaml"

# ── Helpers ──────────────────────────────────────────────────
log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m⚠\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ── Pre-flight ───────────────────────────────────────────────
[[ $(id -u) -eq 0 ]] || die "Run as root (or via sudo)."

log "Updating system packages…"
apt-get update -qq
apt-get upgrade -y -qq

log "Installing Docker & Compose plugin…"
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
apt-get install -y -qq docker-compose-plugin git curl jq ufw

log "Enabling & starting Docker…"
systemctl enable --now docker

log "Creating volt-debt system user (docker group)…"
if ! id volt-debt &>/dev/null; then
  useradd -m -s /bin/bash volt-debt
fi
usermod -aG docker volt-debt

# ── Directories ──────────────────────────────────────────────
log "Creating directories…"
mkdir -p "$SECRETS_BASE/staging" "$SECRETS_BASE/production"
mkdir -p "$DATA_STAGING/objects" "$DATA_PRODUCTION/objects"
chmod 700 "$SECRETS_BASE/staging" "$SECRETS_BASE/production"
chown -R volt-debt:volt-debt "$DATA_STAGING" "$DATA_PRODUCTION"

# ── Repository ───────────────────────────────────────────────
if [[ -d "$REPO_DIR/.git" ]]; then
  log "Repository already present at $REPO_DIR — pulling latest…"
  cd "$REPO_DIR"
  git pull --ff-only origin main || warn "git pull failed; continuing with existing checkout"
else
  log "Cloning repository…"
  git clone --depth 1 "$REPO_URL" "$REPO_DIR"
  cd "$REPO_DIR"
fi

# ── Environment files ────────────────────────────────────────
ENV_STAGING="$REPO_DIR/.env.staging"
ENV_PRODUCTION="$REPO_DIR/.env.production"

if [[ ! -f "$ENV_STAGING" ]]; then
  log "Creating $ENV_STAGING from template…"
  cp infra/vps/.env.staging.example "$ENV_STAGING"
  warn "Edit $ENV_STAGING and set POSTGRES_PASSWORD before starting staging."
fi

if [[ ! -f "$ENV_PRODUCTION" ]]; then
  log "Creating $ENV_PRODUCTION from template…"
  cp infra/vps/.env.production.example "$ENV_PRODUCTION"
  warn "Edit $ENV_PRODUCTION and set POSTGRES_PASSWORD (different from staging) before starting production."
fi

# ── Secrets (per-environment) ────────────────────────────────
create_api_env() {
  local env_name=$1
  local env_file="$SECRETS_BASE/$env_name/api.env"
  
  if [[ -f "$env_file" ]]; then
    log "$env_file already exists — skipping."
    return
  fi
  
  log "Creating $env_file…"
  cat > "$env_file" <<EOF
# /etc/volt-debt/$env_name/api.env — read by the API & worker containers.
# Fill in real values. Chmod 600.

# ── Core ─────────────────────────────────────────────────────
ENV=$([[ "$env_name" == "production" ]] && echo "prd" || echo "stg")
DATABASE_URL=postgresql://debt_api:CHANGE_ME@$([[ "$env_name" == "production" ]] && echo "db-prd" || echo "db-stg"):5432/debt
AUTH_SESSION_SECRET=CHANGE_ME
AUTH_MODE=on
AUTH_SESSION_POLICY=tab
AUTH_ALLOW_TEST_ACCOUNTS=$([[ "$env_name" == "production" ]] && echo "false" || echo "true")
PEAK_OUTBOUND_ENABLED=false

# ── Google Identity Platform ────────────────────────────────
GOOGLE_CLIENT_ID=CHANGE_ME

# ── ClamAV scanner (in-network) ─────────────────────────────
CLAMAV_HOST=scanner-$([[ "$env_name" == "production" ]] && echo "prd" || echo "stg")
CLAMAV_PORT=3310

# ── Odoo / PEAK (UAT) ──────────────────────────────────────
ODOO_URL=
ODOO_DB=
ODOO_LOGIN=
ODOO_API_KEY=
PEAK_UAT_CONNECT_ID=
PEAK_UAT_PASSWORD=
PEAK_UAT_USER_TOKEN=

# ── Feature flags ───────────────────────────────────────────
CRM_WON_ONLY=1
REQUIRE_DEPENDENCY_READINESS=true
TASK_QUEUE_BACKEND=postgres
EOF
  chmod 600 "$env_file"
  warn "Edit $env_file with real credentials before starting the API."
}

create_api_env "staging"
create_api_env "production"

# ── Systemd timers (per-environment) ─────────────────────────
log "Installing systemd services…"
for svc in infra/vps/volt-debt-*.service infra/vps/volt-debt-*.timer; do
  [[ -f "$svc" ]] || continue
  install -m 644 "$svc" /etc/systemd/system/
done
systemctl daemon-reload

for timer in volt-debt-backup-staging.timer volt-debt-backup-production.timer \
             volt-debt-health-staging.timer volt-debt-health-production.timer \
             volt-debt-watchdog-staging.timer volt-debt-watchdog-production.timer \
             volt-debt-resume-writers-staging.timer volt-debt-resume-writers-production.timer; do
  systemctl enable --now "$timer" 2>/dev/null || warn "Could not enable $timer (may not exist yet)"
done

# ── Firewall ─────────────────────────────────────────────────
log "Configuring UFW firewall…"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    comment 'SSH'
ufw allow 80/tcp    comment 'HTTP'
ufw allow 443/tcp   comment 'HTTPS'
ufw --force enable

# ── Docker network ───────────────────────────────────────────
log "Creating Docker network…"
docker network create volt-debt 2>/dev/null || true

# ── Caddy (edge proxy) — shared by both environments ─────────
log "Starting Caddy edge proxy…"
cd "$REPO_DIR"
docker pull caddy:2.8
docker run -d --name volt-debt-edge \
  --restart unless-stopped \
  -p 80:80 -p 443:443 \
  -v "$REPO_DIR/infra/vps/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v caddy_data:/data \
  -v caddy_config:/config \
  caddy:2.8

# ── Done ─────────────────────────────────────────────────────
cat <<EOF

\033[1;32m✅ VPS provisioned for dual-environment.\033[0m

\033[1;36m═══════════════════════════════════════════════════════════════\033[0m
\033[1;33mNEXT STEPS — STAGING (debt.volt.co.th)\033[0m
\033[1;36m═══════════════════════════════════════════════════════════════\033[0m

  1. Edit secrets:
       nano $ENV_STAGING                     # Set POSTGRES_PASSWORD, image tags
       nano $SECRETS_BASE/staging/api.env    # Set DATABASE_URL, GOOGLE_CLIENT_ID, etc.

  2. Initialise database (first run only):
       cd $REPO_DIR
       docker compose -f $COMPOSE_STAGING --env-file $ENV_STAGING --profile setup run migrate-stg

  3. Start staging stack:
       docker compose -f $COMPOSE_STAGING --env-file $ENV_STAGING --profile staging up -d

  4. Verify staging:
       curl -sf http://127.0.0.1:8080/healthz   # web-stg
       curl -sf http://127.0.0.1:8081/readyz    # api-stg

\033[1;36m═══════════════════════════════════════════════════════════════\033[0m
\033[1;33mNEXT STEPS — PRODUCTION (collection.volt.co.th)\033[0m
\033[1;36m═══════════════════════════════════════════════════════════════\033[0m

  1. Edit secrets:
       nano $ENV_PRODUCTION                   # Set POSTGRES_PASSWORD, image tags
       nano $SECRETS_BASE/production/api.env  # Set DATABASE_URL, GOOGLE_CLIENT_ID, etc.

  2. Initialise database (first run only):
       cd $REPO_DIR
       docker compose -f $COMPOSE_PRODUCTION --env-file $ENV_PRODUCTION --profile setup run migrate-prd

  3. Start production stack:
       docker compose -f $COMPOSE_PRODUCTION --env-file $ENV_PRODUCTION --profile production up -d

  4. Verify production:
       curl -sf http://127.0.0.1:8083/healthz   # web-prd
       curl -sf http://127.0.0.1:8082/readyz    # api-prd

\033[1;36m═══════════════════════════════════════════════════════════════\033[0m
\033[1;33mDNS CONFIGURATION\033[0m
\033[1;36m═══════════════════════════════════════════════════════════════\033[0m

  Add these A records at your DNS provider:

    Type  Name          Value
    ----  ----          -----
    A     debt          $(curl -sf ifconfig.me || echo '<VPS_IP>')
    A     collection    $(curl -sf ifconfig.me || echo '<VPS_IP>')

  TLS certificates will be issued automatically on first request.

\033[1;36m═══════════════════════════════════════════════════════════════\033[0m
\033[1;33mGITHUB ACTIONS SETUP\033[0m
\033[1;36m═══════════════════════════════════════════════════════════════\033[0m

  Add these repository secrets:

    STAGING_HOST    = $(curl -sf ifconfig.me || echo '<VPS_IP>')
    STAGING_SSH_KEY = <private key matching the root authorized_key>

EOF
