"""Bind restore/export proof to the exact immutable local backup artifacts."""
import hashlib
from pathlib import Path
import re
from datetime import datetime

REMOTE_BACKENDS = {'s3', 'googlecloudstorage', 'b2', 'azureblob', 'sftp', 'drive',
                   'onedrive', 'dropbox', 'box', 'swift', 'storj', 'oracleobjectstorage'}
ARTIFACTS = {'manifest_sha256': 'SHA256SUMS', 'complete_sha256': 'COMPLETE',
             'restore_evidence_sha256': 'restore-evidence.json'}


def sha(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def hashes(backup):
    backup = Path(backup)
    if any((backup / name).is_symlink() for name in ARTIFACTS.values()):
        raise ValueError('Backup artifacts must not be symlinks')
    return {key: sha(backup / name) for key, name in ARTIFACTS.items()}


def verified_offsite(backup, evidence):
    try:
        backup = Path(backup)
        if (not isinstance(evidence, dict) or evidence.get('status') != 'verified' or
                evidence.get('encrypted') is not True or evidence.get('backup') != backup.name or
                evidence.get('remote_backend') not in REMOTE_BACKENDS or
                not re.fullmatch(r'[a-f0-9]{64}', evidence.get('sha256', ''))):
            return False
        captured = datetime.fromisoformat((backup / 'COMPLETE').read_text().strip().replace('Z', '+00:00'))
        verified = datetime.fromisoformat(evidence['verified_at_utc'].replace('Z', '+00:00'))
        if captured.tzinfo is None or verified.tzinfo is None or verified < captured:
            return False
        return all(evidence.get(key) == value for key, value in hashes(backup).items())
    except (OSError, ValueError, TypeError, KeyError):
        return False
