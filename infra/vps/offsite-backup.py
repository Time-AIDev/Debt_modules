#!/usr/bin/env python3
"""Scheduled coordinated capture, restore check, release package and encrypted S3 export."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil

from recovery_support import (Commands, RecoveryError, now, private_directory, private_file,
                              read_json, release_bundle, timestamp, write_json)

HERE = Path(__file__).resolve().parent


def configuration(path):
    value = read_json(path, maximum=65536)
    if not isinstance(value, dict) or not value.get('remote') or not value.get('recipient', '').startswith(('age1', 'ssh-ed25519 ', 'ssh-rsa ')):
        raise RecoveryError('Offsite S3 destination and encryption recipient are required')
    private_file(Path(value.get('rclone_config', '/etc/volt-debt/rclone.conf')), maximum=1048576)
    return value


def run(path, backup_root=Path('/srv/volt-debt-backups')):
    started = now()
    settings = configuration(path)
    status_path = Path(settings.get('status_path', '/var/lib/volt-debt-ops/offsite-status.json'))
    private_directory(status_path.parent, create=True)
    previous = read_json(status_path) if status_path.exists() else {}
    status = {'format': 'volt-offsite-job-v1', 'status': 'running', 'started_at_utc': started.isoformat(),
              'last_success_at_utc': previous.get('last_success_at_utc'), 'stage': 'capture'}
    write_json(status_path, status)
    log_path = status_path.parent/'offsite-job.log'
    with log_path.open('a') as log:
        log_path.chmod(0o600)
        commands = Commands(log)
        try:
            for tool in ('age', 'rclone', 'docker', 'git'):
                if not shutil.which(tool):
                    raise RecoveryError('A required offsite operations tool is unavailable')
            os.environ['RCLONE_CONFIG'] = settings.get('rclone_config', '/etc/volt-debt/rclone.conf')
            os.environ['BACKUP_REMOTE'] = settings['remote']
            os.environ['BACKUP_AGE_RECIPIENT'] = settings['recipient']
            commands.run(['systemctl', 'start', 'volt-debt-backup.service'], timeout=3000)
            backups = [entry for entry in backup_root.iterdir() if not entry.is_symlink() and entry.is_dir()
                       and not entry.name.startswith('.') and (entry/'COMPLETE').is_file()
                       and not (entry/'COMPLETE').is_symlink()]
            if not backups:
                raise RecoveryError('No completed coordinated backup is available')
            backup = max(backups, key=lambda entry: timestamp((entry/'COMPLETE').read_text()))
            if timestamp((backup/'COMPLETE').read_text()) < started:
                raise RecoveryError('Scheduled capture did not produce a fresh completed backup')
            status['stage'] = 'local_restore'; write_json(status_path, status)
            commands.run(['/usr/bin/python3', str(HERE/'restore-drill.py'), '--backup', str(backup)], timeout=2400)
            status['stage'] = 'release_package'; write_json(status_path, status)
            current = json.loads(commands.run(['docker', 'inspect', *['volt-debt-'+name+'-1' for name in ('api', 'worker', 'web', 'db', 'scanner', 'edge')]], capture=True, timeout=30))
            by_name = {value['Name'].rsplit('-', 2)[-2]: value for value in current}
            images = {name: by_name[name]['Image'] for name in ('api', 'web', 'db', 'scanner', 'edge')}
            revision = by_name['api']['Config'].get('Labels', {}).get('org.opencontainers.image.revision')
            if by_name['worker']['Image'] != images['api']:
                raise RecoveryError('API and worker release images differ')
            bundles = Path(settings.get('bundle_root', str(backup_root/'release-bundles')))
            private_directory(bundles, create=True)
            bundle = bundles/('release-'+str(revision))
            if bundle.exists():
                release_bundle(bundle, revision=revision, images=images)
            else:
                command = ['/usr/bin/python3', str(HERE/'package-release.py'), '--source', settings.get('source', '/srv/volt-debt-platform'),
                           '--revision', revision, '--output', str(bundle)]
                for name, image in images.items(): command += ['--'+name+'-image', image]
                commands.run(command, timeout=4800)
            status['stage'] = 'encrypt_export'; write_json(status_path, status)
            commands.run(['/usr/bin/python3', str(HERE/'backup-export.py'), '--backup', str(backup),
                          '--release-bundle', str(bundle)], timeout=7200)
            proof = read_json(backup/'recovery-point.json')
            completed = now().isoformat()
            status.update(status='passed', stage='complete', last_success_at_utc=completed,
                          verified_at_utc=completed, captured_at_utc=proof['captured_at_utc'],
                          archive_sha256=proof['archive_sha256'], revision=proof['revision'])
            write_json(status_path, status)
        except Exception as error:
            status.update(status='failed', completed_at_utc=now().isoformat(), failure_type=type(error).__name__)
            write_json(status_path, status)
            log.write('Offsite job failed: '+type(error).__name__+'\n')
            raise RecoveryError('Scheduled offsite backup failed') from None
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/etc/volt-debt/offsite.json'))
    args = parser.parse_args(); os.umask(0o077)
    if os.geteuid() != 0:
        parser.error('Run as root')
    try:
        with open('/run/volt-debt-offsite.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run(args.config)
    except Exception as error:
        print('Scheduled offsite backup failed ('+type(error).__name__+').')
        return 1
    print('Scheduled encrypted S3 recovery point verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
