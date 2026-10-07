#!/usr/bin/env python3
"""Download, decrypt and restore a complete recovery point on an independent host."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import shutil
import tempfile

from recovery_support import (Commands, IMAGE, NAME, REVISION, RecoveryError, checksums, extract,
                              fingerprint, now, private_directory, private_file, read_json,
                              release_bundle, sha, timestamp, write_json)
from backup_runtime import recorded_binding

HERE = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE/filename)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def independent_host(production_fingerprint):
    if not re.fullmatch(r'[a-f0-9]{64}', production_fingerprint or ''):
        raise RecoveryError('Pin the production machine fingerprint')
    actual = fingerprint()
    if actual == production_fingerprint:
        raise RecoveryError('Cold recovery must run on an independent machine')
    return actual


def recovery_point(path, args):
    data = read_json(path)
    if data.get('format') != 'volt-debt-recovery-point-v1' or data.get('encrypted') is not True or data.get('remote_backend') != 's3':
        raise RecoveryError('An encrypted S3 recovery point is required')
    if data.get('revision') != args.revision or data.get('production_host_fingerprint') != args.production_fingerprint:
        raise RecoveryError('Recovery point source identity differs from the candidate')
    if not REVISION.fullmatch(data['revision']) or any(not NAME.fullmatch(data.get(key, '')) for key in ('backup', 'release_bundle', 'archive')):
        raise RecoveryError('Recovery point references are invalid')
    if data['backup'] == data['release_bundle'] or not data['archive'].endswith('.tar.age'):
        raise RecoveryError('Recovery archive roots are invalid')
    for key in ('archive_sha256', 'release_manifest_sha256', 'backup_manifest_sha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', data.get(key, '')):
            raise RecoveryError('Recovery point artifact hashes are missing')
    images = data.get('images', {})
    if set(images) != {'api', 'web', 'db', 'scanner', 'edge'} or any(not IMAGE.fullmatch(value) for value in images.values()):
        raise RecoveryError('Recovery point images are incomplete')
    if images['api'] != args.api_image or images['web'] != args.web_image:
        raise RecoveryError('Recovery point application images differ from the candidate')
    age = (now()-timestamp(data.get('captured_at_utc'))).total_seconds()
    if not 0 <= age <= 86400:
        raise RecoveryError('Recovery point exceeds the agreed 24-hour RPO')
    return data


def restore(args):
    started = now()
    host = independent_host(args.production_fingerprint)
    identity = private_file(args.identity, maximum=65536)
    if not REVISION.fullmatch(args.revision) or not IMAGE.fullmatch(args.api_image) or not IMAGE.fullmatch(args.web_image):
        raise RecoveryError('Pin the candidate source and application images')
    private_directory(args.work_root, create=True)
    private_directory(args.evidence.parent, create=True)
    directory = Path(tempfile.mkdtemp(prefix='cold-restore-', dir=args.work_root))
    evidence = {'format': 'volt-offsite-recovery-v1', 'status': 'failed', 'simulated': False,
                'revision': args.revision, 'images': {'api': args.api_image, 'web': args.web_image},
                'started_at_utc': started.isoformat(), 'recovery_host_fingerprint': host,
                'stage': 'download', 'diagnostics_directory': str(directory)}
    stack = None
    failure = None
    with (directory/'diagnostics.log').open('w') as log:
        (directory/'diagnostics.log').chmod(0o600)
        commands = Commands(log)
        try:
            if module('volt_recovery_export', 'backup-export.py').remote_backend(args.remote) != 's3':
                raise RecoveryError('Independent recovery requires the configured S3 backend')
            remote = args.remote.rstrip('/')
            metadata = directory/'recovery-point.json'
            commands.run(['rclone', 'copyto', remote+'/'+args.point, str(metadata)], timeout=120)
            metadata.chmod(0o600)
            point = recovery_point(metadata, args)
            evidence.update(captured_at_utc=point['captured_at_utc'], encrypted=True,
                            archive_sha256=point['archive_sha256'], release_images=point['images'])
            encrypted = directory/'recovery.tar.age'
            commands.run(['rclone', 'copyto', remote+'/'+point['archive'], str(encrypted)], timeout=3600)
            encrypted.chmod(0o600)
            if sha(encrypted) != point['archive_sha256']:
                raise RecoveryError('Downloaded recovery ciphertext checksum mismatch')
            evidence['download_checksum_verified'] = True; evidence['stage'] = 'decrypt'
            archive = directory/'recovery.tar'
            commands.run(['age', '--decrypt', '--identity', str(identity), '--output', str(archive), str(encrypted)], timeout=1800)
            archive.chmod(0o600); evidence['decrypted'] = True
            evidence['stage'] = 'verify_archives'
            restored = directory/'restored'
            maximum = min(args.max_bytes, max(0, shutil.disk_usage(directory).free - 1024**3))
            extract(archive, restored, maximum_bytes=maximum)
            roots = {entry.name for entry in restored.iterdir()}
            if roots != {point['backup'], point['release_bundle']}:
                raise RecoveryError('Decrypted archive does not contain the exact recovery roots')
            backup, bundle = restored/point['backup'], restored/point['release_bundle']
            if sha(backup/'SHA256SUMS') != point['backup_manifest_sha256'] or sha(bundle/'manifest.json') != point['release_manifest_sha256']:
                raise RecoveryError('Decrypted recovery manifest hash mismatch')
            verified = checksums(backup)
            if not {'database.dump', 'globals.sql', 'objects.tar.gz', 'config.tar.gz', 'manifest.txt', 'database-counts.tsv', 'database-image-id.txt', 'COMPLETE', 'BACKUP_FORMAT'} <= set(verified):
                raise RecoveryError('Recovery backup artifact set is incomplete')
            if (backup/'BACKUP_FORMAT').read_text().strip() != 'volt-debt-backup-v1':
                raise RecoveryError('Recovery backup format is unsupported')
            snapshot = dict(line.split('=', 1) for line in (backup/'manifest.txt').read_text().splitlines())
            if (snapshot.get('source_commit') != args.revision or snapshot.get('consistency') != 'database-and-objects_writers-stopped'
                    or timestamp(snapshot['started_at_utc']) != timestamp(point['captured_at_utc'])):
                raise RecoveryError('Backup snapshot differs from the recovery point')
            release = release_bundle(bundle, revision=args.revision, images=point['images'])
            if (backup/'runtime-binding.json').exists():
                binding = recorded_binding(backup/'runtime-binding.json')
                if binding['revision'] != args.revision or binding['images'] != point['images']:
                    raise RecoveryError('Recovered runtime differs from the captured backup')
            if (release['production_host_fingerprint'] != args.production_fingerprint
                    or (backup/'database-image-id.txt').read_text().strip() != point['images']['db']):
                raise RecoveryError('Backup and source images are not bound to the same source')
            evidence['stage'] = 'load_images'
            commands.run(['docker', 'load', '--input', str(bundle/'docker-images.tar')], timeout=3600)
            for name, image in point['images'].items():
                commands.image(image, revision=args.revision if name in ('api', 'web') else None, postgres=name == 'db')
            source = directory/'source'
            extract(bundle/'source.tar.gz', source, maximum_bytes=maximum)
            evidence.update(source_images_verified=True, source_archive_sha256=sha(bundle/'source.tar.gz'))
            objects_root, config_root, scanner_root = directory/'objects-restored', directory/'config-restored', directory/'scanner-restored'
            extract(backup/'objects.tar.gz', objects_root, maximum_bytes=maximum)
            extract(backup/'config.tar.gz', config_root, maximum_bytes=maximum)
            extract(bundle/'clamav.tar.gz', scanner_root, maximum_bytes=maximum)
            objects = objects_root/'objects'; config = config_root/'volt-debt'; signatures = scanner_root/'clamav'
            if not objects.is_dir() or not config.is_dir() or not signatures.is_dir():
                raise RecoveryError('Restored object/configuration/signature roots are missing')
            files = [p for p in objects.rglob('*') if p.is_file()]
            if (len(files) != int(snapshot['object_regular_file_count']) or sum(p.stat().st_size for p in files) != int(snapshot['object_regular_file_bytes'])):
                raise RecoveryError('Restored private object counts differ from backup metadata')
            private_file(config/'api.env'); private_file(config/'stack.env')
            evidence.update(objects_restored=True, configuration_restored=True,
                            object_files=len(files), object_bytes=sum(p.stat().st_size for p in files),
                            configuration_archive_sha256=sha(backup/'config.tar.gz'))
            evidence['stage'] = 'restore_database'
            stack = module('volt_recovery_stack', 'restore-stack.py').RestoredStack(directory, point['images'], log)
            counts = stack.restore_database(backup)
            if counts['application_tables'] != int(snapshot['application_table_count']):
                raise RecoveryError('Restored application table count differs from snapshot')
            before = stack.business_fingerprints()
            evidence.update(database_restored=True, counts_compared=True, counts=counts, business_counts={key: row['count'] for key, row in before.items()})
            evidence['stage'] = 'verify_application'
            readiness = stack.application(config, objects, signatures, args.revision)
            if stack.business_fingerprints() != before:
                raise RecoveryError('Readiness probes changed restored business records or queued jobs')
            evidence.update(application_ready=True, readiness=readiness, queued_jobs_preserved=True,
                            status='passed', stage='complete')
        except Exception as error:
            failure = error
            evidence.update(status='failed', failure_type=type(error).__name__)
            log.write('Failure type: '+type(error).__name__+'\n')
        finally:
            if stack:
                try:
                    stack.cleanup(); evidence['owned_resources_cleaned'] = True
                except Exception as error:
                    failure = error; evidence.update(status='failed', owned_resources_cleaned=False, failure_type=type(error).__name__)
    completed = now()
    evidence.update(completed_at_utc=completed.isoformat(), verified_at_utc=completed.isoformat(),
                    rto_seconds=(completed-started).total_seconds())
    if 'captured_at_utc' in evidence:
        evidence['rpo_seconds'] = (completed-timestamp(evidence['captured_at_utc'])).total_seconds()
    if evidence['rto_seconds'] > 14400 or evidence.get('rpo_seconds', 0) > 86400:
        evidence.update(status='failed', failure_type='RecoveryPolicyExceeded')
        failure = RecoveryError('Recovery exceeded the agreed RPO or RTO')
    write_json(args.evidence, evidence)
    if failure:
        raise RecoveryError('Cold recovery failed; inspect the private evidence and diagnostics') from None
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', required=True, help='Configured S3 rclone remote and prefix')
    parser.add_argument('--point', default='latest-recovery-point.json')
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--production-fingerprint', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--api-image', required=True); parser.add_argument('--web-image', required=True)
    parser.add_argument('--work-root', type=Path, default=Path('/srv/volt-debt-recovery'))
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--max-bytes', type=int, default=100*1024**3)
    args = parser.parse_args(); os.umask(0o077)
    if os.geteuid() != 0 or not NAME.fullmatch(args.point) or args.max_bytes < 1:
        parser.error('Run as root with a safe recovery point filename and extraction limit')
    try:
        restore(args)
    except Exception as error:
        print('Independent cold recovery failed ('+type(error).__name__+'); no production proof is emitted as passed.')
        return 1
    print('Independent cold recovery passed: ciphertext, data, configuration and application verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
