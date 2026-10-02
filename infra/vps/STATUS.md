# Server setup status — 2026-10-02

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
