# Server setup status — 2026-10-05

Verified on `143.198.207.143` at `/srv/volt-debt-platform`, approximately 09:57
Asia/Bangkok. This supersedes the initial installation history below.

- Six application containers running: PostgreSQL, ClamAV, API, worker, web, Caddy.
  No additional application workloads found. SSH, editor/agent processes and
  required host services remain available.
- API, web, database and scanner healthy. API/worker use an init process,
  `no-new-privileges` and startup dependency health checks. Worker remains a
  serial private queue runner without a published listener. No unfinished outbox
  tasks or recent worker error events were found during final verification.
- Database has no published host port. API/web bind `127.0.0.1:8081/8080` only.
  Public listeners are TCP 22, 80 and 443.
- UFW enabled with inbound deny by default. Persistent Docker IPv4/IPv6 rules
  filter traffic from eth0/eth1 into bridges, allowing original TCP ports 80/443.
  Firewall service is attached to host boot and Docker startup.
- SSH key authentication only; root password login and X11 forwarding disabled.
  Docker and SSH socket activation enabled at boot.
- Persistent 4 GiB swap, swappiness 10. Host RAM is 3.8 GiB; final observation
  showed approximately 800 MiB available and 188 MiB swap used. This is a baseline
  observation, not peak-load validation.
- Three available OS package upgrades installed. Automatic security updates
  were already enabled. Dangling Docker images cleared, reclaiming 58.55 MB;
  current/release images, database volumes and private data preserved.
- HTTPS temporary hostname returns 200 with certificate verification enabled;
  HTTP redirects to HTTPS with 308. Unauthenticated auth/me and workbook API
  requests return 401. Google auth configured, seven allowlist entries,
  zero test accounts, tab sessions, `PROD_GO_LIVE_ENABLED=false`.
- ClamAV accepted clean bytes and refused standard EICAR test bytes through the
  API's scanner adapter; private object directory writable by the application.
- Daily backup timer enabled for 03:15–03:25 Asia/Bangkok, capturing PostgreSQL,
  globals, private objects and root-only configuration. Writers pause during
  capture; the latest observed capture took approximately two seconds plus API
  startup. No automatic deletion or off-server transfer configured.
- Five-minute local health timer checks containers, readiness, auth, disk/memory
  and completed backup age. Both service results are success; no failed units.

Verified backup: `/srv/volt-debt-backups/20261005T025356Z-tvw7OV`, directory 0700,
files 0600, checksums valid. Restore on a disposable network-isolated PostgreSQL
container passed and the container/volume were removed. Verified schema version
1, 40 application tables, 52 business records, 12 audit entries, one auth session,
one outbox task and one private object (56 bytes), matching capture metadata.
Root-only `restore-evidence.json` and `restore-drill.log` are in that backup.
Database/configuration values were not printed or committed.

Host configuration before changes is archived under
`/srv/volt-debt-backups/2026-10-05-before-host-setup` with root-only access.
Operational instructions: [README.md](README.md), [BACKUPS.md](BACKUPS.md).

## Still required before public production use

1. DNS A record `debtcollection.volt.co.th` → `143.198.207.143`; resolution still
   failed during final checks. Do not publish AAAA without global IPv6.
2. Production-host certificate issuance and a real Google login, with that origin
   registered in the OAuth client.
3. Role/workflow, representative import/load and reconciliation validation on
   this 4 GiB host. Swap does not establish production capacity; ClamAV's official
   recommended minimum alone is 3 GiB. See [ClamAV Docker documentation](https://docs.clamav.net/manual/Installing/Docker.html).
4. Off-server backup destination and incident notification contact. Local journal
   monitoring is installed; external alert delivery is not.
5. Controlled go-live after the above checks. Maintenance remains enabled;
   OWNER/OPS and worker access can still perform permitted candidate operations.

## Initial installation — 2026-10-02 (historical)

The following records the initial state only; current status is above.

Prepared on `143.198.207.143` at `/srv/volt-debt-platform`:

- Docker Engine and Compose installed and enabled.
- PostgreSQL 16 healthy; migration applied; schema version 1.
- API role has no superuser/database/role-creation rights and cannot delete audit rows.
- API image built with locked Python dependencies; frontend image built successfully.
- Private filesystem storage and PostgreSQL queue adapter implemented.
- Serial worker persists retry times and releases the job lock after SQL failures.
- ClamAV healthy; clean document accepted and EICAR test rejected.
- Frontend healthy at server loopback `127.0.0.1:8080`.
- Caddy HTTPS configuration validated. Edge is stopped.
- Database backup restored into an isolated database: schema version 1, 39 business tables.

Server verification logs: `/var/log/debt-vps-tests.log`,
`/var/log/debt-migration-vps.log`. Prelaunch backup:
`/srv/volt-debt-backups/2026-10-02-prelaunch`, mode 0700; backup files mode 0600.
This is a single manual backup; recurring and off-server backups are not configured.

Pending:

1. DNS A record `debt.volt.co.th` → `143.198.207.143`; last lookup returned NXDOMAIN.
2. Production Google OAuth Client ID with origin `https://debt.volt.co.th`.
3. Authorized email for the first OWNER (registry identity `owner` exists).
4. Full-stack capacity and workflow validation on the 4 GiB host. ClamAV's official
   minimum alone is 3 GiB; baseline health checks do not prove peak capacity.
5. HTTPS issuance and actual Google sign-in, then controlled go-live.

API and private worker remain stopped while OAuth is incomplete. Production auth
stays enabled, test accounts disabled, database starts empty, integration schedules
disabled and `PROD_GO_LIVE_ENABLED=false`. No staging secrets or customer data were copied.
