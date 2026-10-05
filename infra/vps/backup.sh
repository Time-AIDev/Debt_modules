#!/usr/bin/env bash
# Root-only, local logical backup. No retention pruning or off-server transfer.
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

readonly PROJECT=volt-debt
readonly SOURCE_ROOT=/srv/volt-debt-platform
readonly BACKUP_ROOT=/srv/volt-debt-backups
readonly OBJECTS_ROOT=/srv/volt-debt-data/objects
readonly CONFIG_ROOT=/etc/volt-debt
readonly QUIESCE_WRITERS=${QUIESCE_WRITERS:-1}

stage=preflight
backup_dir=
completed=0
resume_ids=()
public_error_fd=2

log() { printf 'volt-debt-backup: %s\n' "$*"; }
fail() { log "$*" >&"$public_error_fd"; exit 1; }

running_containers() {
    docker ps --quiet --no-trunc \
        --filter "label=com.docker.compose.project=$PROJECT" \
        --filter "label=com.docker.compose.service=$1" --filter status=running
}

resume_writers() {
    local attempt
    ((${#resume_ids[@]})) || return 0
    for attempt in 1 2 3; do
        if docker start "${resume_ids[@]}" >>"$backup_dir/diagnostics.log" 2>&1; then
            resume_ids=()
            return 0
        fi
        sleep 1
    done
    log 'Writer restart failed; check the private diagnostics and start the API/worker.' >&"$public_error_fd"
    return 1
}

finish() {
    local status=$?
    trap - EXIT INT TERM
    set +e
    # Restart precisely the containers that were running before this backup.
    # Also runs when a dump/archive command fails or the service receives TERM.
    if ! resume_writers; then status=1; fi
    if ((completed == 0)); then
        log "Backup incomplete during $stage; any partial files were retained at ${backup_dir:-none}." >&"$public_error_fd"
        ((status != 0)) || status=1
    fi
    exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

((EUID == 0)) || fail 'Run as root.'
[[ "$QUIESCE_WRITERS" == 0 || "$QUIESCE_WRITERS" == 1 ]] || fail 'QUIESCE_WRITERS must be 0 or 1.'
for command in docker flock install mktemp realpath stat date tar sha256sum find awk timeout; do
    command -v "$command" >/dev/null || fail "Missing command: $command"
done
# This lock serializes manual and scheduled backups; deployments should honor it.
exec 9>/run/volt-debt-backup.lock
flock --nonblock 9 || fail 'Another backup holds the lock.'
[[ ! -L "$BACKUP_ROOT" ]] || fail 'The backup root must not be a symlink.'
install -d -o root -g root -m 0700 "$BACKUP_ROOT"
[[ "$(realpath -e "$BACKUP_ROOT")" == "$BACKUP_ROOT" ]] || fail 'The backup root contains a symlink.'
[[ "$(stat -c %u "$BACKUP_ROOT")" == 0 ]] || fail 'The backup root must belong to root.'
for path in "$OBJECTS_ROOT" "$CONFIG_ROOT"; do
    [[ -d "$path" && ! -L "$path" ]] || fail 'A required source directory is missing or is a symlink.'
done
for path in "$SOURCE_ROOT/infra/vps/compose.yaml" "$SOURCE_ROOT/infra/vps/Caddyfile"; do
    [[ -f "$path" && ! -L "$path" ]] || fail 'A required deployment file is missing or is a symlink.'
done

stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir=$(mktemp -d "$BACKUP_ROOT/.partial-$stamp-XXXXXX")
chmod 0700 "$backup_dir"
touch "$backup_dir/diagnostics.log"
printf 'volt-debt-backup-v1\n' >"$backup_dir/BACKUP_FORMAT"
# Docker and PostgreSQL diagnostics can contain private names. Keep them here.
exec 8>&2
public_error_fd=8
exec 2>>"$backup_dir/diagnostics.log"

stage=identify-containers
db_list=$(running_containers db)
db_ids=()
if [[ -n "$db_list" ]]; then mapfile -t db_ids <<<"$db_list"; fi
((${#db_ids[@]} == 1)) || fail 'Expected exactly one running production database container.'
db_id=${db_ids[0]}
# Explicitly reject a running migration, which is another database writer.
migrate_ids=$(running_containers migrate)
[[ -z "$migrate_ids" ]] || fail 'A migration is running; retry after it finishes.'
docker exec "$db_id" pg_isready --username=debt_migrate --dbname=debt \
    >>"$backup_dir/diagnostics.log"
docker ps --filter "label=com.docker.compose.project=$PROJECT" \
    --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}' >"$backup_dir/containers.txt"
docker inspect --format '{{.Image}}' "$db_id" >"$backup_dir/database-image-id.txt"

started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
consistency=database-transactional_objects-best-effort
if [[ "$QUIESCE_WRITERS" == 1 ]]; then
    stage=quiesce-writers
    for service in api worker; do
        writer_list=$(running_containers "$service")
        ids=()
        if [[ -n "$writer_list" ]]; then mapfile -t ids <<<"$writer_list"; fi
        resume_ids+=("${ids[@]}")
    done
    if ((${#resume_ids[@]})); then
        # Register all original IDs before stopping any, so EXIT can resume them.
        log 'Pausing API and worker while capturing database and private objects.'
        timeout --signal=TERM --kill-after=15s 90s \
            docker stop --time 60 "${resume_ids[@]}" >>"$backup_dir/diagnostics.log"
    fi
    for service in api worker; do
        running=$(running_containers "$service")
        [[ -z "$running" ]] || fail 'A writer is still running; backup aborted.'
    done
    consistency=database-and-objects_writers-stopped
fi

stage=database-dump
timeout --signal=TERM --kill-after=30s 15m \
    docker exec "$db_id" pg_dump --username=debt_migrate --dbname=debt \
    --format=custom --lock-wait-timeout=30s >"$backup_dir/database.dump"
timeout --signal=TERM --kill-after=30s 2m \
    docker exec "$db_id" pg_dumpall --username=debt_migrate --globals-only \
    >"$backup_dir/globals.sql"
# Count only: no customer identifiers or row values are written to metadata.
public_table_count=$(docker exec "$db_id" psql --username=debt_migrate --dbname=debt \
    --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command="SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';")
application_table_count=$(docker exec "$db_id" psql --username=debt_migrate --dbname=debt \
    --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command="SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('app', 'audit', 'landing', 'records') AND table_type = 'BASE TABLE';")
docker exec "$db_id" psql --username=debt_migrate --dbname=debt \
    --no-psqlrc --tuples-only --no-align --field-separator=$'\t' --set=ON_ERROR_STOP=1 \
    --command="SELECT 'schema_version' AS metric, version::bigint AS value FROM app.schema_version WHERE singleton = true UNION ALL SELECT 'app.business_record', count(*) FROM app.business_record UNION ALL SELECT 'audit.entry', count(*) FROM audit.entry UNION ALL SELECT 'app.auth_session', count(*) FROM app.auth_session UNION ALL SELECT 'app.task_outbox', count(*) FROM app.task_outbox ORDER BY 1;" \
    >"$backup_dir/database-counts.tsv"
awk -F '\t' 'NF != 2 || $2 !~ /^[0-9]+$/ {exit 1} END {if (NR != 5) exit 1}' \
    "$backup_dir/database-counts.tsv" || fail 'Unexpected database counts.'
server_version_num=$(docker exec "$db_id" psql --username=debt_migrate --dbname=debt \
    --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command='SHOW server_version_num;')
[[ "$public_table_count" =~ ^[0-9]+$ && "$application_table_count" =~ ^[0-9]+$ && "$server_version_num" =~ ^[0-9]+$ ]] || fail 'Unexpected database metadata.'

stage=private-objects
timeout --signal=TERM --kill-after=30s 15m \
    tar --create --gzip --numeric-owner --file="$backup_dir/objects.tar.gz" \
    --directory="$(dirname "$OBJECTS_ROOT")" "$(basename "$OBJECTS_ROOT")"
object_metadata=$(find -P "$OBJECTS_ROOT" -type f -printf '%s\n' | \
    awk '{n++; bytes += $1} END {printf "%d %.0f\n", n, bytes}')
read -r object_file_count object_bytes <<<"$object_metadata"
captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
stage=resume-writers
resume_writers || fail 'Could not resume writers.'
log 'Application writers resumed.'

stage=deployment-config
timeout --signal=TERM --kill-after=30s 2m \
    tar --create --gzip --numeric-owner --file="$backup_dir/config.tar.gz" \
    --directory=/etc volt-debt
install -m 0600 "$SOURCE_ROOT/infra/vps/compose.yaml" "$backup_dir/compose.yaml"
install -m 0600 "$SOURCE_ROOT/infra/vps/Caddyfile" "$backup_dir/Caddyfile"
source_commit=unavailable
if command -v git >/dev/null; then
    source_commit=$(git -C "$SOURCE_ROOT" rev-parse HEAD 2>/dev/null) || source_commit=unavailable
fi
[[ "$source_commit" == unavailable || "$source_commit" =~ ^[0-9a-f]{40,64}$ ]] || source_commit=unavailable
cat >"$backup_dir/manifest.txt" <<EOF
format=volt-debt-backup-v1
project=$PROJECT
started_at_utc=$started_at
captured_at_utc=$captured_at
consistency=$consistency
quiesce_writers=$QUIESCE_WRITERS
postgres_version_num=$server_version_num
public_table_count=$public_table_count
application_table_count=$application_table_count
object_regular_file_count=$object_file_count
object_regular_file_bytes=$object_bytes
source_commit=$source_commit
retention=manual-no-automatic-deletion
off_server_copy=not-configured
EOF

stage=verify-artifacts
timeout --signal=TERM --kill-after=30s 2m \
    docker exec --interactive "$db_id" pg_restore --list \
    <"$backup_dir/database.dump" >/dev/null
for archive in objects config; do
    timeout --signal=TERM --kill-after=30s 15m \
        tar --list --gzip --file="$backup_dir/$archive.tar.gz" >/dev/null
done
date -u +%Y-%m-%dT%H:%M:%SZ >"$backup_dir/COMPLETE"
find "$backup_dir" -type f -exec chmod 0600 {} +
(
    cd "$backup_dir"
    sha256sum BACKUP_FORMAT COMPLETE database.dump globals.sql objects.tar.gz config.tar.gz \
        compose.yaml Caddyfile containers.txt database-image-id.txt database-counts.tsv manifest.txt >SHA256SUMS
    sha256sum --check --status SHA256SUMS
)
chmod 0600 "$backup_dir/SHA256SUMS"
final_dir="$BACKUP_ROOT/${backup_dir##*/.partial-}"
[[ ! -e "$final_dir" ]] || fail 'The completed backup path already exists.'
mv --no-clobber --no-target-directory "$backup_dir" "$final_dir"
[[ ! -d "$backup_dir" ]] || fail 'Could not finalize backup.'
backup_dir=$final_dir
completed=1
exec 2>&8
log "Backup completed: $backup_dir"
