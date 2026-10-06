#!/usr/bin/env python3
"""Package committed source, pinned images and scanner signatures for cold recovery."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile

from recovery_support import (Commands, IMAGE, NAME, REVISION, RecoveryError, fingerprint,
                              private_directory, release_bundle, sha, write_json)

ROOT = Path('/srv/volt-debt-platform') if Path('/srv/volt-debt-platform/.git').exists() else Path(__file__).resolve().parents[2]


def package(args):
    if not REVISION.fullmatch(args.revision):
        raise RecoveryError('Pin the full committed Git revision')
    images = {name: getattr(args, name+'_image') for name in ('api', 'web', 'db', 'scanner', 'edge')}
    if any(not IMAGE.fullmatch(image) for image in images.values()) or not NAME.fullmatch(args.scanner_container):
        raise RecoveryError('Pin all five recovery images and a scanner container')
    output = Path(args.output)
    if output.exists() or output.is_symlink() or not NAME.fullmatch(output.name):
        raise RecoveryError('Release bundles are immutable; choose a new output directory')
    private_directory(output.parent, create=True)
    temporary = Path(tempfile.mkdtemp(prefix='.release-bundle-', dir=output.parent))
    try:
        with (temporary/'package.log').open('w') as log:
            os.chmod(temporary/'package.log', 0o600)
            commands = Commands(log)
            root = Path(args.source).resolve(strict=True)
            actual = commands.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture=True, timeout=30)
            if actual != args.revision or commands.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root, capture=True, timeout=30):
                raise RecoveryError('Package source must be the clean pinned commit')
            for name, image in images.items():
                commands.image(image, revision=args.revision if name in ('api', 'web') else None, postgres=name == 'db')
            scanner = json.loads(commands.run(['docker', 'inspect', args.scanner_container], capture=True, timeout=30))[0]
            if scanner.get('Image') != images['scanner'] or not scanner.get('State', {}).get('Running'):
                raise RecoveryError('Scanner signature capture must use the pinned running scanner')
            commands.run(['git', 'archive', '--format=tar.gz', '--prefix=source/',
                          '--output='+str(temporary/'source.tar.gz'), args.revision], cwd=root)
            commands.run(['docker', 'save', '--output', str(temporary/'docker-images.tar'), *dict.fromkeys(images.values())], timeout=3600)
            signatures = temporary/'clamav'; signatures.mkdir(mode=0o700)
            commands.run(['docker', 'cp', args.scanner_container+':/var/lib/clamav/.', str(signatures)], timeout=300)
            files = [p for p in signatures.rglob('*') if p.is_file() and not p.is_symlink()]
            if (any(p.is_symlink() for p in signatures.rglob('*'))
                    or not any(p.name in ('main.cvd', 'main.cld') for p in files)
                    or not any(p.name in ('daily.cvd', 'daily.cld') for p in files)):
                raise RecoveryError('A complete scanner signature snapshot is required')
            with tarfile.open(temporary/'clamav.tar.gz', 'w:gz') as archive:
                archive.add(signatures, arcname='clamav')
            shutil.rmtree(signatures)
            created = datetime.now(timezone.utc).isoformat()
            manifest = {'format': 'volt-debt-release-bundle-v1', 'revision': args.revision,
                        'images': images, 'created_at_utc': created,
                        'production_host_fingerprint': fingerprint(),
                        'files': {name: sha(temporary/name) for name in ('source.tar.gz', 'docker-images.tar', 'clamav.tar.gz')}}
            write_json(temporary/'manifest.json', manifest)
            (temporary/'COMPLETE').write_text(created+'\n')
            names = [*manifest['files'], 'manifest.json', 'COMPLETE']
            (temporary/'SHA256SUMS').write_text(''.join(sha(temporary/name)+'  '+name+'\n' for name in names))
            for entry in temporary.iterdir():
                entry.chmod(0o600)
            release_bundle(temporary, revision=args.revision, images=images)
        # Diagnostics are kept beside the immutable payload, not in its checksum set.
        temporary.rename(output)
        return manifest
    except Exception:
        # Keep private incomplete payload/diagnostics for operator inspection.
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--revision', required=True)
    for name in ('api', 'web', 'db', 'scanner', 'edge'):
        parser.add_argument('--'+name+'-image', required=True)
    parser.add_argument('--scanner-container', default='volt-debt-scanner-1')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        package(args)
    except Exception as error:
        print('Release bundle failed ('+type(error).__name__+'); inspect private package diagnostics.')
        return 1
    print('Pinned source, five images and offline scanner signatures packaged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
