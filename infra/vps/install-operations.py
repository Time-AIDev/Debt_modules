#!/usr/bin/env python3
"""Install reviewed operational helpers and their dependencies; default is inspection."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parent
MODULES = ('healthcheck.py', 'incident_alerts.py', 'external-watchdog.py', 'backup_evidence.py', 'backup-export.py',
           'backup-prune.py', 'restore-drill.py', 'resume-writers.py', 'recovery_support.py',
           'package-release.py', 'cold-restore.py', 'restore-stack.py', 'offsite-backup.py', 'quality_evidence.py', 'backup_runtime.py', 'backup.sh')
ENTRYPOINTS = {'volt-debt-health': ('python3', 'healthcheck.py'),
              'volt-debt-backup': ('bash', 'backup.sh'),
              'volt-debt-resume-writers': ('python3', 'resume-writers.py'),
              'volt-debt-backup-export': ('python3', 'backup-export.py'),
              'volt-debt-backup-prune': ('python3', 'backup-prune.py'),
              'volt-debt-restore-drill': ('python3', 'restore-drill.py'),
              'volt-debt-package-release': ('python3', 'package-release.py'),
              'volt-debt-cold-restore': ('python3', 'cold-restore.py'),
              'volt-debt-offsite-backup': ('python3', 'offsite-backup.py')}
ENTRYPOINTS['volt-debt-external-watchdog'] = ('python3', 'external-watchdog.py')
UNITS = ('volt-debt-health.service', 'volt-debt-health.timer', 'volt-debt-backup.service',
         'volt-debt-backup.timer', 'volt-debt-resume-writers.service', 'volt-debt-resume-writers.timer',
         'volt-debt-offsite.service', 'volt-debt-offsite.timer',
         'volt-debt-watchdog.service', 'volt-debt-watchdog.timer')


def safe(path):
    path = Path(path)
    if not path.is_absolute() or any(parent.is_symlink() for parent in [path, *path.parents]):
        raise ValueError('Operations installation paths must be absolute and contain no symlinks')
    return path


def install_file(path, contents, mode):
    path = safe(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if path.exists() and (not path.is_file() or path.stat().st_uid != os.geteuid()):
        raise ValueError('Refusing to replace an unowned operations file')
    descriptor, name = tempfile.mkstemp(prefix='.ops-install-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as file:
            os.fchmod(file.fileno(), mode); file.write(contents); file.flush(); os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def install(root=Path('/'), *, apply=False, activate=False, activate_offsite=False, activate_watchdog=False):
    root = safe(root)
    if (activate or activate_offsite or activate_watchdog) and (not apply or root != Path('/')):
        raise ValueError('Activation requires an actual host installation')
    if activate_offsite:
        import importlib.util
        spec = importlib.util.spec_from_file_location('volt_install_offsite', SOURCE/'offsite-backup.py')
        offsite = importlib.util.module_from_spec(spec); spec.loader.exec_module(offsite)
        offsite.configuration(Path('/etc/volt-debt/offsite.json'))
    if activate_watchdog:
        import importlib.util
        spec = importlib.util.spec_from_file_location('volt_install_watchdog', SOURCE/'external-watchdog.py')
        watchdog = importlib.util.module_from_spec(spec); spec.loader.exec_module(watchdog)
        watchdog.configuration(Path('/etc/volt-debt/watchdog.json'))
    items = {}
    for name in MODULES:
        source = SOURCE/name
        if source.is_symlink() or not source.is_file():
            raise ValueError('Operations dependency is missing')
        items['usr/local/lib/volt-debt-ops/'+name] = (source.read_bytes(), 0o600)
    for name, (interpreter, module) in ENTRYPOINTS.items():
        target = '/usr/bin/python3' if interpreter == 'python3' else '/bin/bash'
        body = '#!/bin/sh\nexec '+target+' /usr/local/lib/volt-debt-ops/'+module+' "$@"\n'
        items['usr/local/sbin/'+name] = (body.encode(), 0o755)
    for name in UNITS:
        items['etc/systemd/system/'+name] = ((SOURCE/name).read_bytes(), 0o644)
    report = {'format': 'volt-operations-install-v1', 'applied': apply, 'activated': False, 'offsite_activated': False,
              'watchdog_activated': False,
              'files': {name: {'sha256': hashlib.sha256(contents).hexdigest(), 'mode': oct(mode)}
                        for name, (contents, mode) in items.items()}}
    if apply:
        if os.geteuid() != 0:
            raise ValueError('Operations installation requires root')
        library = root/'usr/local/lib/volt-debt-ops'
        safe(library); library.mkdir(parents=True, exist_ok=True, mode=0o700); library.chmod(0o700)
        state = root/'var/lib/volt-debt-ops'
        safe(state); state.mkdir(parents=True, exist_ok=True, mode=0o700); state.chmod(0o700)
        for name, (contents, mode) in items.items():
            install_file(root/name, contents, mode)
        manifest = json.dumps(report, indent=2, sort_keys=True).encode()+b'\n'
        install_file(library/'installed-manifest.json', manifest, 0o600)
        for name, (contents, mode) in items.items():
            path = root/name
            if path.read_bytes() != contents or stat.S_IMODE(path.stat().st_mode) != mode:
                raise ValueError('Installed operations bytes or modes differ from source')
        if root == Path('/'):
            subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if activate:
            subprocess.run(['systemctl', 'enable', '--now', 'volt-debt-health.timer',
                            'volt-debt-backup.timer', 'volt-debt-resume-writers.timer'],
                           check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            report['activated'] = True
            install_file(library/'installed-manifest.json', json.dumps(report, indent=2, sort_keys=True).encode()+b'\n', 0o600)
        if activate_offsite:
            subprocess.run(['systemctl', 'enable', '--now', 'volt-debt-offsite.timer'], check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            report['offsite_activated'] = True
            install_file(library/'installed-manifest.json', json.dumps(report, indent=2, sort_keys=True).encode()+b'\n', 0o600)
        if activate_watchdog:
            subprocess.run(['systemctl', 'enable', '--now', 'volt-debt-watchdog.timer'], check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            report['watchdog_activated'] = True
            install_file(library/'installed-manifest.json', json.dumps(report, indent=2, sort_keys=True).encode()+b'\n', 0o600)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/'), help='Alternate root for installation tests')
    parser.add_argument('--apply', action='store_true'); parser.add_argument('--activate', action='store_true')
    parser.add_argument('--activate-offsite', action='store_true')
    parser.add_argument('--activate-watchdog', action='store_true', help='Only on the independent monitoring host')
    args = parser.parse_args(); os.umask(0o077)
    try:
        report = install(args.root, apply=args.apply, activate=args.activate, activate_offsite=args.activate_offsite,
                         activate_watchdog=args.activate_watchdog)
    except Exception as error:
        print('Operations installation failed ('+type(error).__name__+').')
        return 1
    print(json.dumps({'applied': report['applied'], 'activated': report['activated'],
                      'verified_files': len(report['files'])}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
