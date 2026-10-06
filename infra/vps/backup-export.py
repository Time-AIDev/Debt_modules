#!/usr/bin/env python3
"""Encrypt completed backups for a configured off-server recipient and verify transfer.

Requires age and rclone. Recipient is public; the decryption identity stays off
this VPS. An unset destination is a failure, never a successful backup export.
"""
import argparse
import configparser
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile
import re
import socket
import sys
from urllib.parse import urlsplit
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_evidence import REMOTE_BACKENDS, hashes, sha
from recovery_support import NAME, fingerprint, release_bundle, timestamp, write_json


def remote_backend(destination):
    """Read only redacted configuration; reject same-server/local destinations."""
    name, separator, _ = destination.partition(':')
    if not separator or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Configure a named off-server rclone remote')
    result = subprocess.run(['rclone', 'config', 'redacted', name], check=True, timeout=30,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read_string(result.stdout)
    except configparser.Error:
        raise ValueError('Off-server remote configuration could not be parsed') from None
    if name not in config:
        raise ValueError('Off-server remote configuration was not found')
    remote = config[name]
    kind = remote.get('type', '')
    if kind not in REMOTE_BACKENDS:
        raise ValueError('The remote must be a supported off-server storage backend')
    host = None
    if kind == 'sftp':
        host = remote.get('host')
        if not host:
            raise ValueError('Off-server SFTP host is missing')
    elif remote.get('endpoint'):
        endpoint = urlsplit(remote['endpoint'])
        if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password:
            raise ValueError('Object storage endpoint must use HTTPS without URL credentials')
        host = endpoint.hostname
    if host:
        if host.lower().rstrip('.') in {'localhost', 'collection.volt.co.th', 'debtcollection.volt.co.th'}:
            raise ValueError('Backup destination must be outside this production server')
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for item in addresses:
            address = ipaddress.ip_address(item[4][0])
            if address.is_loopback or address.is_unspecified or str(address) == '143.198.207.143':
                raise ValueError('Backup destination resolves to this production server')
    return kind


def export(backup, bundle=None):
    backup = Path(backup)
    recipient = os.environ.get('BACKUP_AGE_RECIPIENT', '')
    destination = os.environ.get('BACKUP_REMOTE', '')
    if not recipient.startswith(('age1', 'ssh-ed25519 ', 'ssh-rsa ')) or not destination or ':' not in destination:
        raise ValueError('BACKUP_AGE_RECIPIENT and rclone BACKUP_REMOTE must be configured')
    if not (backup/'COMPLETE').is_file(): raise ValueError('Only completed backups may be exported')
    if not (backup/'restore-evidence.json').is_file(): raise ValueError('Restore evidence required before export')
    if json.loads((backup/'restore-evidence.json').read_text()).get('status') != 'passed':
        raise ValueError('A passed restore drill is required')
    backend = remote_backend(destination)
    proof = hashes(backup)
    release = release_bundle(bundle) if bundle else None
    if release:
        bundle = Path(bundle).resolve(strict=True)
        if backend != 's3' or not NAME.fullmatch(backup.name) or not NAME.fullmatch(bundle.name) or backup.name == bundle.name:
            raise ValueError('Cold recovery requires S3 and distinct safe archive roots')
        manifest = dict(line.split('=', 1) for line in (backup/'manifest.txt').read_text().splitlines())
        if manifest.get('source_commit') != release['revision'] or (backup/'database-image-id.txt').read_text().strip() != release['images']['db']:
            raise ValueError('Backup source/database image differs from the release bundle')
        if release['production_host_fingerprint'] != fingerprint():
            raise ValueError('Release bundle was not captured on this backup source host')
        if manifest.get('consistency') != 'database-and-objects_writers-stopped':
            raise ValueError('Cold recovery requires a coordinated database/object snapshot')
        # Use the earlier snapshot start for a conservative recovery-point age.
        captured = timestamp(manifest['started_at_utc'])
        age = (datetime.now(timezone.utc)-captured).total_seconds()
        if not 0 <= age <= 86400:
            raise ValueError('Recovery point must satisfy the 24-hour RPO')
    subprocess.run(['sha256sum','--check','--status','SHA256SUMS'],cwd=backup,check=True,timeout=120)
    with tempfile.TemporaryDirectory(prefix='volt-backup-export-',dir=backup.parent) as tmp:
        encrypted = Path(tmp)/(backup.name+'.tar.age')
        # Streaming avoids copying a growing database archive into memory.
        with encrypted.open('wb') as output:
            arguments = ['tar','-C',str(backup.parent),'-cf','-',backup.name]
            if bundle:
                arguments += ['-C',str(bundle.parent),bundle.name]
            archive = subprocess.Popen(arguments,stdout=subprocess.PIPE)
            try:
                result = subprocess.run(['age','-r',recipient],stdin=archive.stdout,stdout=output,check=True,timeout=1800)
                archive.stdout.close()
                if archive.wait(timeout=30) != 0: raise RuntimeError('backup packaging failed')
            finally:
                if archive.poll() is None: archive.kill(); archive.wait()
        digest = sha(encrypted)
        checksum = Path(tmp)/(encrypted.name+'.sha256')
        checksum.write_text(digest+'  '+encrypted.name+'\n')
        remote = destination.rstrip('/')+'/'+encrypted.name
        subprocess.run(['rclone','copyto',str(encrypted),remote],check=True,timeout=1800)
        subprocess.run(['rclone','copyto',str(checksum),remote+'.sha256'],check=True,timeout=60)
        # Download verification proves bytes at the destination, not only an accepted upload.
        downloaded = Path(tmp)/'download-verification.tar.age'
        subprocess.run(['rclone','copyto',remote,str(downloaded)],check=True,timeout=1800)
        if sha(downloaded) != digest: raise RuntimeError('off-server checksum mismatch')
        if release:
            if hashes(backup) != proof or release_bundle(bundle) != release:
                raise RuntimeError('Recovery source evidence changed during transfer')
            recovery = {'format':'volt-debt-recovery-point-v1','backup':backup.name,
                        'release_bundle':bundle.name,'archive':encrypted.name,'archive_sha256':digest,
                        'release_manifest_sha256':sha(bundle/'manifest.json'),
                        'backup_manifest_sha256':proof['manifest_sha256'],
                        'captured_at_utc':captured.isoformat(),'revision':release['revision'],
                        'images':release['images'],'production_host_fingerprint':fingerprint(),
                        'verified_at_utc':datetime.now(timezone.utc).isoformat(),
                        'encrypted':True,'remote_backend':'s3'}
            metadata = Path(tmp)/(backup.name+'.recovery-point.json')
            write_json(metadata,recovery)
            subprocess.run(['rclone','copyto',str(metadata),destination.rstrip('/')+'/'+metadata.name],check=True,timeout=60)
            # Update latest only after immutable payload upload and download verification.
            subprocess.run(['rclone','copyto',str(metadata),destination.rstrip('/')+'/latest-recovery-point.json'],check=True,timeout=60)
            write_json(backup/'recovery-point.json',recovery)
    if hashes(backup) != proof:
        raise RuntimeError('Backup evidence changed during off-server export')
    evidence = {'status':'verified','backup':backup.name,'sha256':digest,
                'verified_at_utc':datetime.now(timezone.utc).isoformat(),'encrypted':True,
                'remote_backend':backend, **proof}
    if release:
        evidence.update(release_manifest_sha256=recovery['release_manifest_sha256'],
                        revision=release['revision'],source_images_packaged=True)
    (backup/'offsite-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('Encrypted off-server backup transfer verified')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--release-bundle',type=Path)
    args=parser.parse_args()
    export(args.backup.resolve(),args.release_bundle)


if __name__=='__main__':main()
