# Debt Platform SSH server

Server: `debt-production` / `143.198.207.143`. Source directory:
`/srv/volt-debt-platform`. Intended domain: `collection.volt.co.th`.

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

The two-CPU VPS API uses the shared `API_WORKERS=2` launcher, with
`API_WORKER_HEALTHCHECK_SECONDS=30` passed explicitly to Uvicorn. This internal
process liveness window gives Python worker boot more headroom than the implicit
five-second default. It is a conservative mitigation: earlier child deaths were
observed without a reproduced cause. Business read/write p95 remains below three
seconds, the HTTP health guard remains two seconds, and job/readiness budgets are
unchanged. Validate native startup cycles and real financial reads before release.
The shared database connection policy uses
`PROD_READ_CONCURRENCY=4` and pool size 5 + overflow 2 **per process** (up to 14 API
connections in total). The API's 1 GiB memory limit covers both workers. Dev and
staging containers use the same launcher/defaults. The separate single-CPU Cloud
Run profile explicitly sets one worker; its capacity needs its own measurements.

On 2026-10-07 the user changed business read/write and complete-action latency
acceptance to p95 <3,000 ms. Error <1%, checks >99% and replay errors =0 remain.
The original two-second `production.js` is retained; `production-3s.js` imports
its identical requests/payloads with the declared new threshold. Earlier failed
native runs remain failed under their original policy.
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

Caddy is running with `collection.volt.co.th` and the existing temporary
`debt.143-198-207-143.sslip.io` hostname. Ports 80 and 443 are published; Docker
and containers are configured to restart automatically.

Create DNS A record `collection.volt.co.th` → `143.198.207.143` (host label
`collection` in the `volt.co.th` zone). Do not add an AAAA record: this server
has no global IPv6 address. Caddy obtains and renews the HTTPS certificate
automatically once public DNS resolves to this server and ports 80/443 are reachable.
Certificate issuance and HTTPS on the new hostname remain pending DNS.

Add `https://collection.volt.co.th` to the existing Google OAuth client's
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


## Shared release workflow — 2026-10-06

The current target is `https://collection.volt.co.th` on `143.198.207.143`.
Use `scripts/release.sh` for dev, staging and production; `infra/runtime/README.md`
describes isolated local stacks. `scripts/runtime_env.py` and
`backend/app/runtime_policy.py` supply common limits, session policy, disabled
external financial writes, durable state and worker health. The legacy GCP UAT
script requires explicit `LEGACY_GCP_UAT=1` and retains its compatibility model.

Build once from the canonical locked Dockerfiles and promote exact image digests.
Pass `VOLT_GIT_REVISION` as a build argument and keep the tested Git commit.
Production release performs a read-only preflight (`--check`), keeps maintenance
while migrating and testing the candidate, and opens traffic only with `--go-live`.
Always pass a rollback API compatible with additive schema version2; never
point an old version1-only readiness image at schema2 and call rollback healthy.

The k6 scenario is `tests/load/production.js`. It operates on a separately seeded
synthetic database through genuine auth, transaction, case-note writes and
idempotent retries. Private load credentials remain outside Git. Record cold
first-request/priming separately from steady workload. The DOCX generator
`scripts/build_production_report.py` reads JSON/JUnit evidence without inventing
successful results; final artifacts are under `reports/production-20261006`.

The production Google OAuth client administrator must add
`https://collection.volt.co.th` as an authorized JavaScript origin. A browser
smoke test found an origin-denied error; displaying the login page or obtaining
HTTP200 does not prove Google login works. Do not open the maintenance gate until
that browser check passes.

The backup now persists paused-writer IDs, and recovery uses the same backup lock
at boot/every minute to resume writers after an interrupted capture. Off-server
backup export requires `age`, configured `rclone`, an off-server public encryption
recipient and a passed restore. Export verifies remote bytes and binds its proof
to this backup's manifests. Pruning defaults to preview and only removes old
verified-offsite backups; it preserves a minimum recovery set. An external backup
recipient/destination and incident receiver are still operator configuration.

### Installing the reviewed operational helpers

`install-operations.py` inspects by default. `--apply` copies the health script,
`incident_alerts.py`, backup/recovery helpers and their Python dependencies into
`/usr/local/lib/volt-debt-ops` with private modes, installs explicit entrypoints
under `/usr/local/sbin`, verifies source bytes/modes, and reloads systemd. This
avoids deploying a newer health entrypoint with an older or missing alert helper.
It does not create provider credentials or claim successful delivery.

```sh
python3 infra/vps/install-operations.py
python3 infra/vps/install-operations.py --apply --activate
```

After real S3 and age recipient configuration is in place, the separate
`--activate-offsite` flag enables the twice-daily offsite timer. Read
[BACKUPS.md](BACKUPS.md#encrypted-offsite-recovery-points) before configuring or
running it. Keep the incident JSON receiver configuration private; verify real
incident and recovery acknowledgments plus the external watchdog before go-live.
Unit command simulations establish guard behavior, not actual offsite restoration
or alert delivery.

On the independent monitoring host, configure `/etc/volt-debt/watchdog.json` and
private S3 read credentials before using `install-operations.py --apply
--activate-watchdog`. The configuration includes the verified production machine
SHA256, `recovery_point_remote`, `rclone_config`, `alerts_config`, and a private
`state_path`. Activation refuses the production host. The installed executable
wrapper launches the private Python helper; it checks HTTPS/readiness and the
encrypted recovery point every minute, and uses the same acknowledged incident
and recovery transport. An enabled timer alone does not satisfy the alert gate.

### Explicitly postponing offsite recovery

When the owner postpones S3 and offsite recovery, promotion accepts only the
specific `--defer-offsite-recovery` option and a checksum-bound `offsite_recovery`
artifact for the exact candidate. The artifact must use `status: "deferred"`,
`passed: false`, `scope: "offsite_recovery"`, `authorization: "explicit_user_request"`,
and a nonempty `reason`, together with the normal revision, API/Web images and
fresh timestamp. Keep all eight artifact entries; the other seven checks must
actually pass. Without the option, offsite recovery remains mandatory.

The resulting evidence reports `eligible_for_rollout: true`, `passed: false`,
and the deferred check separately. It does not certify external RPO or RTO.
Local backup, checksum verification, local restore and rollback remain required.

On the independent watchdog host, set `offsite_monitoring: "deferred"` in its
private configuration to postpone only the S3 recovery-point checks. The default
is `"required"`. Independent-host validation, HTTPS/readiness probing, private
receiver authentication, durable retries/deduplication and real incident/recovery
acknowledgments are still required; no S3 credentials or rclone configuration are
needed in this explicit mode. Deferred recovery is not a successful restore.
