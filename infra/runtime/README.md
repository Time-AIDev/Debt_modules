# Shared local development and staging

`scripts/release.sh` selects an environment while `backend/app/runtime_policy.py`
provides the common settings. Development and staging use the production API and
web Dockerfiles, PostgreSQL, immutable private objects, ClamAV, the durable worker,
and schema version 2. Their projects and data volumes are separate from the
production `volt-debt` project.

Prepare settings without starting containers:

```sh
scripts/release.sh dev render --generate-test-account
scripts/release.sh staging render --generate-test-account
```

The flag explicitly enables a local OWNER test account. The password and database
credential are stored in `.runtime/dev/credentials.json` or
`.runtime/staging/credentials.json` with mode 0600; they are never printed or
committed. API environment files have the same permissions. Existing credentials
are retained between starts. Test accounts are disabled by production policy.

Start a stack on a development/staging host with enough RAM for its database,
scanner, API and worker:

```sh
scripts/release.sh dev up --generate-test-account
scripts/release.sh staging up --generate-test-account
scripts/release.sh staging status
scripts/release.sh staging down
```

The production VPS has approximately 4 GiB of RAM. Run these complete stacks on a
separate host when production is using that capacity. `down` preserves local
database and object volumes.

Development binds web/API to `127.0.0.1:18000` and `127.0.0.1:18001`; staging uses
`127.0.0.1:19000` and `127.0.0.1:19001`. PostgreSQL and ClamAV have no published
ports. The web image uses the committed nginx configuration plus a generated
private API proxy, so browser requests remain on one origin. Migrations finish
before the API and worker start; readiness requires schema, scanner and worker
heartbeat checks.

To use Google login, pass `--env-file /private/path/auth.env` containing the Google
client ID, allowlist and session secret. Register the actual web origin, including
its port, in the OAuth client. Do not supply a production `DATABASE_URL`: the
runner always creates an isolated database connection. Settings may use simple
`KEY=value` or quoted `KEY='value'` dotenv syntax.

For image promotion, use the tested API and web image digests in each environment:

```sh
scripts/release.sh staging up --generate-test-account \
  --api-image 'registry/api@sha256:<64 hexadecimal characters>' \
  --web-image 'registry/web@sha256:<64 hexadecimal characters>'
```

Without image arguments, the runner builds each artifact once per source
fingerprint and records its immutable local image ID in `.runtime/<env>/images.json`.
The default database/scanner artifacts are built from `infra/vps/Dockerfile.db.no_xml`
and `infra/vps/Dockerfile.scanner`, including the reviewed operating system patches
and gosu rebuild. Use `--postgres-image` and `--scanner-image` to promote the exact
digests tested for a release. PostgreSQL remains on major version 16, with ICU,
OpenSSL and compression retained. SQL XML and LLVM JIT are explicitly disabled;
the application uses JSONB and does not require those optional features. The
stock-feature `Dockerfile.db` recipe remains available for reviewed rollback
requirements and retains vendor-unfixed libxml2 findings.

`scripts/run_prototype.sh` and `scripts/run_prototype_login.sh` remain lightweight
local walkthroughs. `SERVE=fixtures` explicitly uses volatile fixture data;
`SERVE=crm-lead` migrates the local database and starts the shared worker. The
canonical Docker stack supplies its own scanner and is the preferred shared mode.

`scripts/deploy_gcp.sh` is an explicit legacy UAT compatibility profile, invoked
only with `LEGACY_GCP_UAT=1`. It uses cookie sessions and per-browser persisted
state. It does not provision the private uploads, scanner or durable worker needed
for production-equivalent staging. Use the shared staging stack for release
validation. Production deployments use `scripts/release.sh production`, which
delegates to the VPS release controller.
