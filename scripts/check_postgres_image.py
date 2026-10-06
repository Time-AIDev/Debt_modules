#!/usr/bin/env python3
"""Verify a PostgreSQL 16 image against an isolated synthetic cluster and restore.

Every container and volume has a unique test-only name, no network and no ports.
No production data is accessed. The output includes diagnostics on failure.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
import lzma
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
TEST_LABEL = 'volt-debt.image-smoke'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(args, *, data=None, timeout=60, check=True):
    return subprocess.run(args, input=data, check=check, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout)


def sql(container, statement, database='probe', check=True):
    return run(['docker', 'exec', '--interactive', container, 'psql', '--username', 'debt_migrate',
                '--dbname', database, '--no-psqlrc', '--tuples-only', '--no-align',
                '--set', 'ON_ERROR_STOP=1'], data=statement.encode(), check=check)


def start(container, image, volume, init_directory=None):
    args = ['docker', 'run', '--detach', '--pull', 'never', '--name', container,
            '--label', TEST_LABEL + '=true', '--network', 'none', '--memory', '256m',
            '--cpus', '0.5', '--volume', volume + ':/var/lib/postgresql/data',
            '--env', 'POSTGRES_USER=debt_migrate', '--env', 'POSTGRES_DB=probe',
            '--env', 'POSTGRES_HOST_AUTH_METHOD=trust']
    if init_directory:
        args.extend(['--mount', 'type=bind,src=' + init_directory + ',dst=/docker-entrypoint-initdb.d,readonly'])
    run(args + [image])
    for _ in range(90):
        ready = run(['docker', 'exec', container, 'pg_isready', '--host', '127.0.0.1',
                     '--username', 'debt_migrate', '--dbname', 'probe'], check=False)
        if ready.returncode == 0:
            return
        inspected = run(['docker', 'inspect', container], check=False)
        if inspected.returncode == 0:
            require(json.loads(inspected.stdout)[0]['State']['Running'],
                    'Isolated PostgreSQL container exited during startup')
        time.sleep(.5)
    raise RuntimeError('Isolated PostgreSQL startup timed out')


def inspect_test_container(container):
    inspected = json.loads(run(['docker', 'inspect', container]).stdout)[0]
    require(inspected['HostConfig']['NetworkMode'] == 'none', 'Smoke container has a network')
    require(not inspected['HostConfig'].get('PortBindings'), 'Smoke container publishes ports')
    require(inspected['HostConfig']['Memory'] == 268435456, 'Smoke memory limit differs')
    require(not inspected['State'].get('OOMKilled'), 'Smoke container was killed for memory use')
    return inspected


def stop(container):
    run(['docker', 'stop', '--time', '30', container], timeout=45)
    inspected = inspect_test_container(container)
    require(not inspected['State']['Running'] and inspected['State']['ExitCode'] == 0,
            'Isolated PostgreSQL did not shut down cleanly')


def diagnostics(container):
    result = {}
    for key, args in (('logs', ['docker', 'logs', '--tail', '150', container]),
                      ('inspect', ['docker', 'inspect', container])):
        try:
            output = run(args, check=False, timeout=15)
            if output.returncode == 0:
                result[key] = (output.stdout + output.stderr).decode(errors='replace')[-20000:]
        except Exception as error:
            result[key + '_error'] = str(error)
    return result


def remove_owned(kind, name):
    inspected = run(['docker', kind, 'inspect', name], check=False, timeout=15)
    if inspected.returncode:
        message = inspected.stderr.decode(errors='replace')
        if 'No such' in message:
            return
        raise RuntimeError('Unable to inspect smoke ' + kind + ': ' + message.strip())
    metadata = json.loads(inspected.stdout)[0]
    labels = metadata.get('Labels') if kind == 'volume' else metadata['Config'].get('Labels')
    require((labels or {}).get(TEST_LABEL) == 'true', 'Refusing to remove an unowned smoke ' + kind)
    args = ['docker', kind, 'rm']
    if kind == 'container':
        args.extend(['--force', '--volumes'])
    run(args + [name], timeout=45)


def check_image(candidate, original):
    suffix = uuid.uuid4().hex
    old = 'volt-db-old-smoke-' + suffix
    new = 'volt-db-new-smoke-' + suffix
    restored_container = 'volt-db-restore-smoke-' + suffix
    volume = 'volt-db-compatibility-' + suffix
    restored_volume = 'volt-db-restore-' + suffix
    containers = (old, new, restored_container)
    volumes = (volume, restored_volume)
    archived = {}
    init_directory = tempfile.TemporaryDirectory(prefix='volt-db-image-init-')
    evidence = {'network': 'none', 'memory_limit_bytes': 268435456, 'production_modified': False,
                'cluster_source': 'isolated synthetic data initialized by the original image',
                'candidate_image': candidate, 'original_image': original, 'status': 'running'}
    locale_query = "select datcollate || '|' || datctype || '|' || pg_encoding_to_char(encoding) from pg_database where datname=current_database();"
    collation_query = "select coalesce(datcollversion,'') || '|' || coalesce(pg_database_collation_actual_version(oid),'') from pg_database where datname=current_database(); select collversion || '|' || pg_collation_actual_version(oid) from pg_collation where collname='image_smoke_icu';"
    extension_query = "select name || '|' || default_version from pg_available_extensions where name <> 'xml2' order by name;"
    indexed_query = "set enable_seqscan=off; select party from public.image_compatibility order by party collate public.image_smoke_icu;"
    values_query = "select count(*) || '|' || sum(amount) from public.image_compatibility; select party from public.image_compatibility where uid=1; select count(*) from public.image_compatibility where payload @> '{\"kind\":\"smoke\"}'; select version from app.schema_version; select count(*) from audit.entry where route_template='/image-smoke';"
    try:
        evidence['phase'] = 'original cluster initialization'
        for name in volumes:
            run(['docker', 'volume', 'create', '--label', TEST_LABEL + '=true', name])
        start(old, original, volume)
        evidence['original_image_id'] = inspect_test_container(old)['Image']
        before = sql(old, locale_query).stdout.decode().strip()
        sql(old, (ROOT / 'backend/app/schema.sql').read_text())
        sql(old, "insert into audit.entry(business_date,actor_source,verb,route_template,outcome,status,prev_hash,hash) "
                 "values(current_date,'NONE','POST','/image-smoke','OK',200,'synthetic-chain','synthetic-hash');")
        sql(old, "create table public.image_compatibility(uid integer primary key,party text,amount numeric(12,2),payload jsonb); "
                 "insert into public.image_compatibility values(1,'ลูกค้าทดสอบ',0.10,'{\"kind\":\"smoke\"}'),(2,'บริษัทตัวอย่าง',0.20,'{\"kind\":\"smoke\"}'); "
                 "create collation public.image_smoke_icu (provider=icu,locale='en_US'); "
                 "create index image_compatibility_party on public.image_compatibility(party collate public.image_smoke_icu);")
        original_collations = sql(old, collation_query).stdout.decode().splitlines()
        original_extensions = sql(old, extension_query).stdout.decode().splitlines()
        original_indexed = sql(old, indexed_query).stdout.decode().splitlines()
        dumped = run(['docker', 'exec', old, 'pg_dump', '--username', 'debt_migrate',
                      '--dbname', 'probe', '--format', 'custom']).stdout
        stop(old)
        archived[old] = diagnostics(old)
        remove_owned('container', old)

        evidence['phase'] = 'candidate existing cluster compatibility'
        start(new, candidate, volume)
        inspected = inspect_test_container(new)
        evidence['image_id'] = inspected['Image']
        version_num = sql(new, "select current_setting('server_version_num');").stdout.decode().strip()
        require(version_num == '160015', 'Candidate must run PostgreSQL 16.15')
        after = sql(new, locale_query).stdout.decode().strip()
        require(before == after, 'Candidate changed existing database locale or encoding')
        require(after == 'en_US.utf8|en_US.utf8|UTF8', 'Expected en_US.utf8 / UTF8 cluster')
        candidate_collations = sql(new, collation_query).stdout.decode().splitlines()
        require(original_collations == candidate_collations, 'Existing libc or ICU collation versions changed')
        require(all(row.split('|')[0] == row.split('|')[1] for row in candidate_collations),
                'Stored and actual libc or ICU collation versions differ')
        candidate_extensions = sql(new, extension_query).stdout.decode().splitlines()
        require(set(original_extensions) <= set(candidate_extensions), 'Candidate lost a supported contrib extension')
        values = sql(new, values_query).stdout.decode().splitlines()
        require(values == ['2|0.30', 'ลูกค้าทดสอบ', '2', '2', '1'], 'Existing app schema or synthetic records changed')
        indexed = sql(new, indexed_query).stdout.decode().splitlines()
        require(indexed == original_indexed and set(indexed[-2:]) == {'ลูกค้าทดสอบ', 'บริษัทตัวอย่าง'},
                'Existing ICU text index changed ordering or is unreadable')
        xml = sql(new, "select xmlparse(document '<root>test</root>');", check=False)
        require(xml.returncode and b'unsupported XML feature' in xml.stderr, 'SQL XML must be disabled')
        require(sql(new, 'select pg_jit_available();').stdout.decode().strip() == 'f', 'LLVM JIT must be disabled')
        configure = run(['docker', 'exec', new, 'pg_config', '--configure']).stdout.decode().strip()
        configure_flags = set(shlex.split(configure))
        for flag in ('--with-icu', '--with-openssl', '--with-lz4', '--with-zstd',
                     '--without-libxml', '--without-libxslt', '--without-llvm'):
            require(flag in configure_flags, 'Missing PostgreSQL build feature: ' + flag)
        for binary in ('pg_dump', 'pg_restore', 'createdb', 'psql', 'gzip', 'xz', 'zstd'):
            run(['docker', 'exec', new, 'sh', '-c', 'command -v ' + binary])
        guarded = sql(new, "insert into records.invoice_review(uid,payload) values('smoke-review','{}'); "
                           "update records.invoice_review set payload='{}' where uid='smoke-review';", check=False)
        require(guarded.returncode and b'append-only' in guarded.stderr, 'Invoice history update was not refused')
        audit_guard = sql(new, "update audit.entry set status=201 where route_template='/image-smoke';", check=False)
        require(audit_guard.returncode and b'append-only' in audit_guard.stderr, 'Audit update was not refused')
        uid = run(['docker', 'exec', new, 'stat', '--format', '%u', '/proc/1']).stdout.decode().strip()
        require(uid == '999', 'PostgreSQL process must use UID 999')
        runtime_packages = run(['docker', 'exec', new, 'dpkg-query', '--show',
                                'base-files', 'libc6', 'libicu76']).stdout.decode().splitlines()

        evidence['phase'] = 'candidate compressed init and fresh cluster restore'
        init_path = Path(init_directory.name)
        init_path.chmod(0o755)
        gzip_sql = b"create table public.image_init_tools(tool text primary key); insert into public.image_init_tools values ('gzip');"
        xz_sql = b"insert into public.image_init_tools values ('xz');"
        zstd_sql = b"insert into public.image_init_tools values ('zstd');"
        (init_path / '01-tools.sql.gz').write_bytes(gzip.compress(gzip_sql))
        (init_path / '02-tools.sql.xz').write_bytes(lzma.compress(xz_sql))
        compressed = run(['docker', 'exec', '--interactive', new, 'zstd', '--compress', '--stdout', '--quiet'], data=zstd_sql).stdout
        (init_path / '03-tools.sql.zst').write_bytes(compressed)
        for init_file in init_path.iterdir():
            init_file.chmod(0o644)
        stop(new)
        archived[new] = diagnostics(new)
        remove_owned('container', new)
        start(restored_container, candidate, restored_volume, init_directory.name)
        restored_inspection = inspect_test_container(restored_container)
        require(restored_inspection['Image'] == evidence['image_id'], 'Candidate tag changed during smoke checks')
        initialized = sql(restored_container, 'select tool from public.image_init_tools order by tool;').stdout.decode().splitlines()
        require(initialized == ['gzip', 'xz', 'zstd'], 'Compressed entrypoint init SQL was not processed')
        require(sql(restored_container, locale_query).stdout.decode().strip() == before, 'Candidate fresh initialization changed locale')
        require(sql(restored_container, 'show listen_addresses;').stdout.decode().strip() == '*',
                'Candidate fresh initialization must listen on container network interfaces')
        run(['docker', 'exec', restored_container, 'createdb', '--username', 'debt_migrate', 'restored'])
        run(['docker', 'exec', '--interactive', restored_container, 'pg_restore', '--username', 'debt_migrate',
             '--dbname', 'restored', '--exit-on-error'], data=dumped, timeout=120)
        restored = sql(restored_container, values_query, database='restored').stdout.decode().splitlines()
        require(restored == ['2|0.30', 'ลูกค้าทดสอบ', '2', '2', '1'], 'Fresh restore changed app schema or synthetic records')
        restored_guard = sql(restored_container, "update audit.entry set status=201 where route_template='/image-smoke';",
                             database='restored', check=False)
        require(restored_guard.returncode and b'append-only' in restored_guard.stderr, 'Restore lost the audit update guard')
        inspect_test_container(restored_container)
        evidence.update(status='passed', existing_cluster_preserved=True, server_version_num=int(version_num),
                        schema_version=2, locale=after, collation_versions=candidate_collations, icu_text_index=True,
                        runtime_packages=runtime_packages, pg_config_configure=configure,
                        preserved_extensions=original_extensions, thai_utf8=True, jsonb=True, money_decimal=True,
                        append_only_history=True, audit_migration=True, audit_append_only=True, dump_restore=True,
                        sql_xml_disabled=True, llvm_jit_disabled=True, icu_openssl_compression=True,
                        backup_init_tools=True, compressed_init_sql=True, fresh_initdb=True,
                        fresh_listen_addresses='*', postgres_uid=999, oom=False)
    except Exception as error:
        evidence.update(status='failed', error_type=type(error).__name__, error=str(error))
        if isinstance(error, subprocess.CalledProcessError):
            evidence['command_stderr'] = (error.stderr or b'').decode(errors='replace')[-20000:]
        evidence['diagnostics'] = {name: archived.get(name) or diagnostics(name) for name in containers}
    finally:
        cleanup_errors = []
        for kind, names in (('container', containers), ('volume', volumes)):
            for name in names:
                try:
                    remove_owned(kind, name)
                except Exception as error:
                    cleanup_errors.append({'kind': kind, 'name': name, 'error': str(error)})
        if cleanup_errors:
            evidence.update(status='failed', cleanup_errors=cleanup_errors)
        try:
            init_directory.cleanup()
        except Exception as error:
            evidence.update(status='failed', init_directory_cleanup_error=str(error))
        evidence['completed_at_utc'] = datetime.now(timezone.utc).isoformat()
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-image', required=True)
    parser.add_argument('--original-image', default='postgres@sha256:65b16a8b326e0cfbdf33fa7e783f2a0cb352a61448616ccccfd616ef42aa0f65')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = check_image(args.candidate_image, args.original_image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    if evidence['status'] != 'passed':
        print('PostgreSQL isolated image checks failed; diagnostics: ' + str(args.output))
        return 1
    print('PostgreSQL isolated synthetic cluster, compressed init and restore checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
