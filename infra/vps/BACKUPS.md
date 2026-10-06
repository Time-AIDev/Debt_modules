# VPS backups

`backup.sh` is a root-operated logical backup for the `volt-debt` Compose project.
It writes a new directory under `/srv/volt-debt-backups` with directory mode `0700`
and file mode `0600`. It never deletes old backups, containers, volumes, or source
data. PostgreSQL role passwords, application credentials, and private customer
objects are included: keep the entire backup private.

The daily timer runs between **03:15 and 03:25 Asia/Bangkok**. By default the
script gracefully stops the running API and worker, captures the database and
object directory, and starts exactly those containers again. The web and Caddy
remain running, but API requests are unavailable during the capture. Interruption
usually depends on database and object sizes; each dump/object archive has a
15-minute deadline. Do not run migrations or deployments during a backup.

An EXIT/INT/TERM trap retries writer startup after failures and ordinary service
stops. SIGKILL, power loss, or Docker failure cannot execute the trap: following
such an interruption, check and start the API and worker manually. The service
gives the shell 180 seconds to recover on stop. If the VPS reboots during the
backup, containers stopped by `docker stop` may need an explicit `docker start`.

`QUIESCE_WRITERS=0 /usr/local/sbin/volt-debt-backup` avoids stopping writers. Its
database dump is transactionally consistent, but the object archive is best
effort and may disagree with database references. The manifest records the mode.
Use this only when that weaker consistency is acceptable. Both modes assume
API/worker are the only object and database writers and no direct SQL client or
deployment changes the data/configuration concurrently.

## Install and verify

Run on the production VPS as root, from `/srv/volt-debt-platform`:

```sh
install -o root -g root -m 0750 infra/vps/backup.sh /usr/local/sbin/volt-debt-backup
install -o root -g root -m 0644 infra/vps/volt-debt-backup.service /etc/systemd/system/
install -o root -g root -m 0644 infra/vps/volt-debt-backup.timer /etc/systemd/system/
systemd-analyze calendar '*-*-* 03:15:00 Asia/Bangkok'
systemd-analyze verify /etc/systemd/system/volt-debt-backup.service /etc/systemd/system/volt-debt-backup.timer
systemctl daemon-reload
systemctl start volt-debt-backup.service
systemctl status volt-debt-backup.service --no-pager
```

After the first backup and an isolated restore succeed, enable the timer. With
`Persistent=true`, enabling after a missed calendar event can trigger a catch-up
run; an additional backup also briefly interrupts the API.

```sh
systemctl enable --now volt-debt-backup.timer
systemctl list-timers volt-debt-backup.timer --no-pager
journalctl -u volt-debt-backup.service --since today --no-pager
```

Completion paths and generic progress appear in the journal. Command diagnostics
stay in each backup's root-only `diagnostics.log`. Partial backups retain their
`.partial-` prefix and are never counted as complete. There is a nonblocking
`/run/volt-debt-backup.lock` lock to prevent overlapping scheduled/manual backups.
No periodic restore verification, off-server upload, encryption, failure alert,
or retention deletion is configured by these templates. Monitor service failures
and free space; an on-server backup does not cover loss of the VPS or its disk.

## Contents and validation

Each completed backup contains:

- `database.dump`: PostgreSQL custom-format dump of `debt`.
- `globals.sql`: global roles and grants, including role password hashes.
- `objects.tar.gz`: the `objects/` directory and its numeric ownership.
- `config.tar.gz`: `/etc/volt-debt`, including credentials and configuration.
- `compose.yaml` and `Caddyfile`: deployment and edge configuration.
- `manifest.txt`: UTC capture times, consistency mode, PostgreSQL version, table
  counts for `public` and application schemas (`app`, `audit`, `landing`,
  `records`), total regular object file count/bytes, and source commit if known.
- `database-counts.tsv`: schema version and row counts for `app.business_record`,
  `audit.entry`, `app.auth_session`, and `app.task_outbox`, captured before
  restarting writers. It contains metric names and counts, not customer values.
- `containers.txt` and `database-image-id.txt`: image/container inventory without
  environment variables.
- `SHA256SUMS`, `BACKUP_FORMAT` and `COMPLETE`: checksums, fixed format marker and
  UTC completion timestamp for monitoring the latest completed backup's age.

The script verifies dump readability, both archive indexes and SHA256 hashes
before removing the partial prefix. It does not prove the dump can restore or
that all application workflows work. `diagnostics.log` is excluded from the
checksum list because later cleanup diagnostics may append to it. Caddy's cached
certificates and ClamAV signature volume are omitted; reissue certificates after
DNS/network checks and redownload scanner signatures. The application source and
container image layers are not archived; retain the source commit and release
images separately, including any local source changes.

## Restore drill: isolated instance only

The checked-in runner automates a disposable container, checksum verification,
schema/table/row-count comparison and object extraction/counts, then removes the
temporary container, volume and extraction directory. It writes root-only
`restore-evidence.json` and `restore-drill.log` into the selected backup:

```sh
python3 infra/vps/restore-drill.py --backup /srv/volt-debt-backups/COMPLETED_DIRECTORY
```

It waits for the final PostgreSQL TCP listener, avoiding the image's temporary
Unix-socket-only initialization server. A manual equivalent follows.

Never point these commands at the production database, Compose project, object
directory, or network. Choose a completed backup directory explicitly as root;
replace the placeholder below. Keep this shell's umask restrictive. This drill
creates only a separate PostgreSQL container without published ports or attached
production volumes.

```sh
umask 077
backup=/srv/volt-debt-backups/REPLACE_WITH_COMPLETED_DIRECTORY
test "$(cat "$backup/BACKUP_FORMAT")" = volt-debt-backup-v1
(cd "$backup" && sha256sum --check SHA256SUMS)
docker run --detach --name volt-debt-restore-drill --network none \
  --env POSTGRES_USER=volt_restore_admin --env POSTGRES_DB=postgres \
  --env POSTGRES_HOST_AUTH_METHOD=trust postgres:16
until docker exec volt-debt-restore-drill pg_isready --host=127.0.0.1 --username=volt_restore_admin --dbname=postgres; do sleep 1; done
docker exec --interactive volt-debt-restore-drill psql --username=volt_restore_admin --dbname=postgres \
  --set=ON_ERROR_STOP=1 <"$backup/globals.sql"
docker exec volt-debt-restore-drill createdb --username=volt_restore_admin --owner=debt_migrate debt
docker exec --interactive volt-debt-restore-drill pg_restore \
  --username=volt_restore_admin --dbname=debt --exit-on-error <"$backup/database.dump"
docker exec volt-debt-restore-drill psql --username=volt_restore_admin --dbname=debt \
  --set=ON_ERROR_STOP=1 \
  --command="SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('app', 'audit', 'landing', 'records') AND table_type = 'BASE TABLE';"
docker exec volt-debt-restore-drill psql --username=volt_restore_admin --dbname=debt \
  --no-psqlrc --tuples-only --no-align --field-separator="$(printf '\t')" --set=ON_ERROR_STOP=1 \
  --command="SELECT 'schema_version' AS metric, version::bigint AS value FROM app.schema_version WHERE singleton = true UNION ALL SELECT 'app.business_record', count(*) FROM app.business_record UNION ALL SELECT 'audit.entry', count(*) FROM audit.entry UNION ALL SELECT 'app.auth_session', count(*) FROM app.auth_session UNION ALL SELECT 'app.task_outbox', count(*) FROM app.task_outbox ORDER BY 1;"
restore_dir=$(mktemp -d /srv/volt-debt-backups/restore-drill-XXXXXX)
tar --extract --gzip --file="$backup/objects.tar.gz" --directory="$restore_dir"
find "$restore_dir/objects" -type f -printf '%s\n' \
  | awk '{n++; bytes += $1} END {printf "files=%d bytes=%.0f\n", n, bytes}'
```

The isolated drill uses PostgreSQL 16 to match this deployment. Pin the image to
the recorded database image digest when reproducibility is required. `trust` is
confined to the disposable container's isolated network; never use it for the
production database. Inspect globals first if restoring into an existing cluster,
because an existing role can conflict; the example requires a fresh instance.
The separate `volt_restore_admin` bootstrap role avoids colliding with a backed-up
`postgres` or `debt_migrate` role; choose another distinct name if that role also
exists in the source. Keep dump diagnostics private and check every command's exit
status. Match application table and object counts with the manifest and the five
database metrics with `database-counts.tsv`, then verify schema/application
invariants, then run application checks with isolated credentials and a copied
object root if needed. Record backup and recovery timestamps and drill results.

After recording the drill, remove only its explicitly named container:

```sh
docker rm --force --volumes volt-debt-restore-drill
```

Remove only the specific temporary object extraction directory after inspecting
its absolute path. Keep completed backup directories until an explicit retention
policy and verified off-server copies exist. No `docker system prune`, volume
pruning, or wildcard backup deletion is required.

For a real disaster recovery, provision a separate replacement VPS, retrieve a
verified backup and release images from independent storage, restore globals and
database, and extract objects/configuration into that replacement only. Preserve
root-only config permissions and object ownership, validate authentication and
workflows with public traffic disabled, then switch traffic after validation.
Do not restore over a primary containing newer writes.

## Encrypted offsite recovery points

The implementation supports S3 through a named `rclone` remote and `age` public-key
encryption. Configuration is required before an offsite transfer can succeed. Keep
the age decryption identity on the independent recovery host, outside this VPS.
Use Python 3.12+, Docker, Git, age and rclone on the relevant operations hosts.
No remote bucket, credentials, encryption recipient, or recovery machine is
generated or assumed by these commands.

`package-release.py` requires a clean committed source revision, the matching API
and web image labels, and immutable IDs for PostgreSQL 16, scanner and edge. It
captures a running scanner's signature database so recovery does not need a
Freshclam download. The private release directory contains a Git source archive,
all five saved Docker images, scanner signatures, and checksum-bound manifests.
Application images must include the staging-only worker `--probe-only` support.

```sh
umask 077
install -d -m 0700 /srv/volt-debt-backups/release-bundles
python3 infra/vps/package-release.py \
  --source /srv/volt-debt-platform --revision FULL_COMMIT_SHA \
  --api-image sha256:API_ID --web-image sha256:WEB_ID \
  --db-image sha256:POSTGRES16_ID --scanner-image sha256:SCANNER_ID \
  --edge-image sha256:EDGE_ID \
  --output /srv/volt-debt-backups/release-bundles/release-FULL_COMMIT_SHA
python3 infra/vps/backup-export.py --backup /srv/volt-debt-backups/COMPLETED_BACKUP \
  --release-bundle /srv/volt-debt-backups/release-bundles/release-FULL_COMMIT_SHA
```

The export requires `BACKUP_REMOTE`, `BACKUP_AGE_RECIPIENT`, and a private rclone
configuration. Existing exports without `--release-bundle` retain their transfer
verification behavior. A complete recovery point additionally requires S3, a
writers-stopped backup, matching backup/source/database image identities, and a
passed local restore. Its RPO timestamp conservatively uses snapshot start.
The archive is encrypted before upload; a download must reproduce its SHA256.
Only then are immutable recovery-point metadata and `latest-recovery-point.json`
uploaded. An accepted upload or downloaded checksum alone is not a cold restore.

For recurring capture, create `/etc/volt-debt/offsite.json` mode 0600 with these
operator-supplied fields (the JSON contains a public recipient, not a private key):

```json
{
  "remote": "offsite:volt-debt",
  "recipient": "AGE_PUBLIC_RECIPIENT",
  "rclone_config": "/etc/volt-debt/rclone.conf",
  "source": "/srv/volt-debt-platform",
  "bundle_root": "/srv/volt-debt-backups/release-bundles",
  "status_path": "/var/lib/volt-debt-ops/offsite-status.json"
}
```

The separate offsite timer runs at 03:45 and 15:45 Bangkok time with at most five
minutes randomized delay. It coordinates a fresh local capture, local restore
check, reusable immutable release bundle, and encrypted S3 transfer. Only its
explicit installer activation flag enables it. Missing settings or tools fail;
the private status marker records actual success/failure and last success. No
automatic deletion policy is added.

## Independent cold restore

Run `cold-restore.py` on a separate recovery host. Supply the trusted production
machine fingerprint, final source revision, and exact API/web IDs. A matching
machine fingerprint is refused before downloads or container changes. The private
age identity must already exist on that recovery host; it is never copied into a
container or recovery evidence. The remote rclone configuration must independently
authorize reading the same S3 prefix.

```sh
umask 077
install -d -m 0700 /srv/volt-debt-recovery
python3 infra/vps/cold-restore.py --remote offsite:volt-debt \
  --identity /root/recovery-secrets/volt.agekey \
  --production-fingerprint PRODUCTION_MACHINE_SHA256 \
  --revision FULL_COMMIT_SHA --api-image sha256:API_ID --web-image sha256:WEB_ID \
  --work-root /srv/volt-debt-recovery \
  --evidence /srv/volt-debt-recovery/offsite-recovery.json
```

Recovery verifies ciphertext, age decryption, bounded link-free archives, backup
and source manifests, Git archive identity, and loaded image IDs/labels. It restores
PostgreSQL 16, all private object bytes, and original configuration into a private
workspace. The application uses separate database/session credentials, disabled
external connector credentials, `ENV=stg`, and `PROD_GO_LIVE_ENABLED=false`.
API, probe-only worker, offline scanner, web, and an isolated plain-HTTP edge proxy
must actually become ready on an internal Docker network without published ports.
Queued jobs and business-record fingerprints must remain unchanged. Public TLS,
Google sign-in, outbound PEAK, DNS cutover, and resumed job execution are separate
release checks, not claimed by this isolated recovery.

Evidence records observed start/end, conservative RPO, RTO, counts, checksums,
source/image identity and readiness. RPO over 24 hours or RTO over four hours fails.
Only labeled containers/volumes/network created by this run are removed; downloaded
images and private diagnostics stay available on the recovery host. A failed or
simulated test cannot satisfy the `offsite_recovery` production quality gate.
