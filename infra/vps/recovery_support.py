"""Private, bounded recovery I/O. Public errors never include private contents."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile

IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
REVISION = re.compile(r"[a-f0-9]{40}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")


class RecoveryError(RuntimeError):
    """Only fixed operational messages may leave the private diagnostics."""


def now():
    return datetime.now(timezone.utc)


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise RecoveryError('Recovery timestamp is invalid') from None


def fingerprint():
    raw = Path('/etc/machine-id').read_bytes().strip()
    if not re.fullmatch(b'[a-f0-9]{32}', raw):
        raise RecoveryError('A valid independent machine identity is required')
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def private_file(path, maximum=None):
    path = Path(path)
    if not path.is_absolute() or any(parent.is_symlink() for parent in [path, *path.parents]):
        raise RecoveryError('A private absolute regular file is required')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise RecoveryError('Recovery file ownership or permissions are unsafe')
    if maximum is not None and info.st_size > maximum:
        raise RecoveryError('Recovery metadata exceeds its size limit')
    return path


def private_directory(path, create=False):
    path = Path(path)
    if not path.is_absolute():
        raise RecoveryError('An absolute private directory is required')
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise RecoveryError('Recovery paths must not contain symlinks')
    if create and not path.exists():
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise RecoveryError('Recovery directory ownership or permissions are unsafe')
    return path


def write_json(path, value):
    path = Path(path)
    private_directory(path.parent, create=True)
    if path.is_symlink():
        raise RecoveryError('Recovery output must not be a symlink')
    descriptor, temporary = tempfile.mkstemp(prefix='.recovery-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as file:
            os.fchmod(file.fileno(), 0o600)
            json.dump(value, file, indent=2, sort_keys=True, allow_nan=False)
            file.write('\n'); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path, maximum=1048576):
    return json.loads(private_file(path, maximum).read_text())


def checksums(directory):
    directory = Path(directory)
    entries = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        digest, separator, name = line.partition('  ')
        if not separator or not re.fullmatch(r'[a-f0-9]{64}', digest) or not NAME.fullmatch(name) or name in entries:
            raise RecoveryError('Checksum manifest is malformed')
        target = directory / name
        if not target.is_file() or target.is_symlink() or sha(target) != digest:
            raise RecoveryError('Recovery artifact checksum mismatch')
        entries[name] = digest
    if not entries:
        raise RecoveryError('Checksum manifest is empty')
    return entries


def extract(archive_path, target, maximum_bytes=100 * 1024**3, maximum_members=200000):
    """Reject links, special files, traversal and duplicate names before extraction."""
    target = private_directory(target, create=True)
    with tarfile.open(archive_path, 'r:*') as archive:
        members, names, total = [], set(), 0
        for member in archive:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or '..' in name.parts or not name.parts or member.name in names
                    or not (member.isdir() or member.isfile()) or member.size < 0):
                raise RecoveryError('Recovery archive contains an unsafe entry')
            names.add(member.name); total += member.size; members.append(member)
            if len(members) > maximum_members or total > maximum_bytes:
                raise RecoveryError('Recovery archive exceeds extraction limits')
        archive.extractall(target, members=members, filter='data')
    for entry in target.rglob('*'):
        entry.chmod(0o700 if entry.is_dir() else 0o600)
    return {'members': len(members), 'bytes': total}


def parse_env(path):
    """Match quoted Docker env values without shell execution or interpolation."""
    values = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise RecoveryError('Restored environment syntax is invalid')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if '\x00' in value or '\r' in value:
            raise RecoveryError('Restored environment contains an unsafe value')
        values[key] = value
    return values


def docker_env(path, values):
    """Docker run --env-file uses raw values; do not apply Compose interpolation."""
    if any(any(char in str(value) for char in ('\n', '\r', '\x00')) for value in values.values()):
        raise RecoveryError('Recovery runtime settings cannot contain line breaks')
    Path(path).write_text(''.join(key+'='+str(value)+'\n' for key, value in values.items()))
    Path(path).chmod(0o600)


class Commands:
    def __init__(self, log):
        self.log = log

    def run(self, arguments, *, capture=False, stdin=None, cwd=None, timeout=1800):
        input_values = {'input': stdin.getvalue()} if hasattr(stdin, 'getvalue') else {'stdin': stdin}
        result = subprocess.run(arguments, **input_values, cwd=cwd, check=True, timeout=timeout,
                                stdout=subprocess.PIPE if capture else self.log, stderr=self.log)
        return result.stdout.decode().strip() if capture else None

    def image(self, identifier, revision=None, postgres=False):
        if not IMAGE.fullmatch(identifier):
            raise RecoveryError('Recovery images must use immutable SHA256 IDs')
        info = json.loads(self.run(['docker', 'image', 'inspect', identifier], capture=True, timeout=30))[0]
        if info['Id'] != identifier:
            raise RecoveryError('Loaded image differs from the recorded digest')
        if revision and info.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != revision:
            raise RecoveryError('Application image revision differs from source')
        if postgres and 'PG_MAJOR=16' not in info.get('Config', {}).get('Env', []):
            raise RecoveryError('Recovery requires the recorded PostgreSQL 16 image')
        return identifier


def release_bundle(path, *, revision=None, images=None):
    path = private_directory(path)
    manifest = read_json(path / 'manifest.json')
    if manifest.get('format') != 'volt-debt-release-bundle-v1' or not REVISION.fullmatch(manifest.get('revision', '')):
        raise RecoveryError('Release bundle format is invalid')
    actual = manifest.get('images', {})
    if set(actual) != {'api', 'web', 'db', 'scanner', 'edge'} or any(not IMAGE.fullmatch(v) for v in actual.values()):
        raise RecoveryError('Release bundle image set is incomplete')
    if revision and manifest['revision'] != revision or images and any(actual.get(k) != v for k, v in images.items()):
        raise RecoveryError('Release bundle does not match the candidate')
    verified = checksums(path)
    required = {'manifest.json', 'COMPLETE', 'source.tar.gz', 'docker-images.tar', 'clamav.tar.gz'}
    files = manifest.get('files', {})
    if set(verified) != required or set(files) != required - {'manifest.json', 'COMPLETE'} or any(verified[name] != digest for name, digest in files.items()):
        raise RecoveryError('Release bundle artifact hashes are incomplete')
    with tarfile.open(path / 'source.tar.gz', 'r:gz') as archive:
        archive.getmembers()
        if archive.pax_headers.get('comment') != manifest['revision']:
            raise RecoveryError('Source archive does not identify the pinned Git commit')
    return manifest
