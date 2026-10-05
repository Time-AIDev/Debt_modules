# Debt Platform SSH server

Server: `debt-production` / `143.198.207.143`. Source directory:
`/srv/volt-debt-platform`. Intended domain: `debtcollection.volt.co.th`.

The Compose deployment prepares PostgreSQL 16 and application images. It is a
single-server deployment, without the regional HA described in `infra/production`.
Database has no host port; candidate web/API ports bind only to loopback.

Secrets are generated on the server under `/etc/volt-debt` (root-only). Never copy
staging `.env`, customer data, or test accounts into this deployment.

```sh
ssh debt-production
cd /srv/volt-debt-platform
docker compose --env-file /etc/volt-debt/stack.env -f infra/vps/compose.yaml up -d db
docker compose --env-file /etc/volt-debt/stack.env -f infra/vps/compose.yaml --profile setup run --rm migrate
```

Before starting candidate API, supply the production `GOOGLE_CLIENT_ID` and the
authorized initial owner in `AUTH_ALLOWLIST` in `/etc/volt-debt/api.env`. The officer
identity must exist in the application registry; do not invent an identity.
Authentication, tab sessions, test-account refusal and maintenance mode stay enabled.

Set `OBJECT_STORAGE_BACKEND=filesystem`, `OBJECT_STORAGE_ROOT=/private-objects`,
`UPLOADS_BUCKET=uploads`, `CLEAN_BUCKET=clean`, `DOCS_BUCKET=documents`,
`TASK_QUEUE_BACKEND=postgres`, and `CLAMAV_HOST=scanner` in the server API env file.
API and private worker share the application-owned private volume
at `/srv/volt-debt-data/objects`. PostgreSQL stores intent, progress and retry times.
The worker polls the durable queue serially and has no HTTP listener. ClamAV runs
on the private Docker network with no published port. No GCP workload credentials
are required; Google Login still requires a real production OAuth client.

ClamAV needs at least 3 GiB RAM by its official recommendation; this server has
4 GiB total. The full stack must be sized and load-tested before release. Container
limits are ceilings, not evidence that the host can satisfy concurrent peak demand.
See https://docs.clamav.net/manual/Installing/Docker.html.

Publish only after DNS, HTTPS, authentication, complete workflows and backup restore
are verified. API and web candidate profiles do not provide an HTTPS edge or a
worker unless their profiles are explicitly selected. Caddy's `public` profile
provides HTTPS after DNS points at the server. Keep `PROD_GO_LIVE_ENABLED=false`
until release validation succeeds.

The remote Git repository records workspace snapshots, including work not yet
committed on the laptop. It is not a checkout of the upstream branch history.
Do not push these snapshots to replace the GitHub repository.

## Domain setup — 2026-10-05

Caddy is running with `debtcollection.volt.co.th` and the existing temporary
`debt.143-198-207-143.sslip.io` hostname. Ports 80 and 443 are published; Docker
and containers are configured to restart automatically.

Create DNS A record `debtcollection.volt.co.th` → `143.198.207.143` (host label
`debtcollection` in the `volt.co.th` zone). Do not add an AAAA record: this server
has no global IPv6 address. Caddy obtains and renews the HTTPS certificate
automatically once public DNS resolves to this server and ports 80/443 are reachable.
Certificate issuance and HTTPS on the new hostname remain pending DNS.

Add `https://debtcollection.volt.co.th` to the existing Google OAuth client's
Authorized JavaScript origins before using Google sign-in on the new hostname.
The OAuth client itself is managed outside this server.

Verified: Caddy configuration validation/reload; new-host HTTP redirect (308);
new-host frontend routing (200) and `/api/v1/auth/config` routing (200), using
the existing hostname for TLS SNI and the new HTTP Host header; internal API
`/healthz` and `/readyz` report ok/ready. `PROD_GO_LIVE_ENABLED=false` remains
in effect. STATUS.md records the current server checks and the initial history.

## Server operations — 2026-10-05

Current verified state is recorded in [STATUS.md](STATUS.md). The six application
containers are running; API, frontend, PostgreSQL and scanner have health checks.
API/worker use an init process and `no-new-privileges`, and wait for database and
scanner health at startup. Docker restarts the application after a host reboot;
an unhealthy check reports a problem but does not itself restart a container.

The host has a persistent 4 GiB swap file `/swapfile.volt-debt` and
`vm.swappiness=10`. Swap provides room for transient pressure; the 4 GiB host and
approximately 6.5 GiB combined container memory ceilings still require load
validation. UFW allows inbound TCP 22, 80 and 443 only. The
`volt-debt-firewall.service` also filters traffic entering Docker bridges from
`eth0`/`eth1`, using original destination ports so Docker cannot bypass that
policy. See [Docker's firewall documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
SSH accepts keys only and X11 forwarding is disabled; SSH socket activation
remains enabled for remote administration.

Daily backups run at 03:15–03:25 Asia/Bangkok. They briefly stop API/worker to
capture PostgreSQL and private objects together, then resume them. Read
[BACKUPS.md](BACKUPS.md) for recovery and permissions. Run an isolated verification
on an explicitly selected completed backup with:

```sh
python3 infra/vps/restore-drill.py --backup /srv/volt-debt-backups/COMPLETED_DIRECTORY
```

`volt-debt-health.timer` checks services, database readiness, production auth,
capacity and a backup completed in the last 26 hours every five minutes. Its
failures appear in the local journal; external alerts are not configured.

```sh
systemctl list-timers volt-debt-backup.timer volt-debt-health.timer
systemctl --failed
journalctl -u volt-debt-health.service -u volt-debt-backup.service --since today
```

Before go-live: add the production DNS A record, verify its certificate and actual
Google sign-in, validate roles/workflows and load, and provide an independent
backup destination and incident notification contact. The current local backup
does not survive loss of this VPS. Maintenance remains enabled.
