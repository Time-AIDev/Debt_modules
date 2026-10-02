# Debt Platform SSH server

Server: `debt-production` / `143.198.207.143`. Source directory:
`/srv/volt-debt-platform`. Intended domain: `debt.volt.co.th`.

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
