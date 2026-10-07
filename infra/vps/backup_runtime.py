"""Capture the deployed release for a backup without using checkout HEAD."""
import argparse
import json
from pathlib import Path
import tarfile

from recovery_support import Commands, IMAGE, REVISION, RecoveryError, private_directory, read_json, write_json

SERVICES = ('api', 'worker', 'web', 'db', 'scanner', 'edge')


def recorded_binding(path):
    value = read_json(path, maximum=16384)
    images = value.get('images', {}) if isinstance(value, dict) else {}
    if (not isinstance(value, dict) or value.get('format') != 'volt-backup-runtime-v1'
            or not isinstance(value.get('revision'), str) or not REVISION.fullmatch(value['revision'])
            or not isinstance(images, dict) or set(images) != set(SERVICES)-{'worker'}
            or any(not isinstance(image, str) or not IMAGE.fullmatch(image) for image in images.values())):
        raise RecoveryError('Backup runtime evidence is invalid')
    return value


def runtime_binding(commands):
    containers, images, revisions = {}, {}, {}
    for service in SERVICES:
        query = [
            'docker', 'ps', '--quiet', '--no-trunc', '--filter',
            'label=com.docker.compose.project=volt-debt', '--filter',
            'label=com.docker.compose.service='+service,
        ]
        identifiers = commands.run(query+['--filter', 'status=running'], capture=True, timeout=30).split()
        if not identifiers:
            # A stopped writer still identifies the deployed release. Backup
            # must not start it or accidentally select another stopped release.
            identifiers = commands.run(query+['--all'], capture=True, timeout=30).split()
        if len(identifiers) != 1:
            raise RecoveryError('Backup requires one identifiable container per production service')
        container = json.loads(commands.run(
            ['docker', 'inspect', identifiers[0]], capture=True, timeout=30))[0]
        labels = container.get('Config', {}).get('Labels', {})
        if (service == 'db' and not container.get('State', {}).get('Running')
                or labels.get('com.docker.compose.project') != 'volt-debt'
                or labels.get('com.docker.compose.service') != service
                or not IMAGE.fullmatch(container.get('Image', ''))):
            raise RecoveryError('Backup runtime container binding is invalid')
        containers[service] = container['Id']
        images[service] = container['Image']
        if service in ('api', 'worker', 'web'):
            info = commands.image(images[service])
            # Commands.image validates identity; obtain the immutable image label,
            # rather than trusting labels supplied when the container was created.
            image = json.loads(commands.run(
                ['docker', 'image', 'inspect', info], capture=True, timeout=30))[0]
            revisions[service] = image.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision')
    revision = revisions['api']
    if (not isinstance(revision, str) or not REVISION.fullmatch(revision)
            or any(value != revision for value in revisions.values())
            or images['worker'] != images['api']):
        raise RecoveryError('Backup application images must share one committed release')
    return {'format': 'volt-backup-runtime-v1', 'revision': revision,
            'images': {name: image for name, image in images.items() if name != 'worker'},
            'containers': containers}


def capture(source, output, *, commands):
    source = Path(source).resolve(strict=True)
    output = Path(output)
    private_directory(output)
    binding = runtime_binding(commands)
    if (output/'database-image-id.txt').read_text().strip() != binding['images']['db']:
        raise RecoveryError('Backup database differs from the captured runtime')
    revision = binding['revision']
    actual = commands.run(['git', 'rev-parse', '--verify', revision+'^{commit}'],
                          cwd=source, capture=True, timeout=30)
    if actual != revision:
        raise RecoveryError('Deployed backup source commit is unavailable')
    # These files belong to the deployed commit even when the checkout contains
    # the next candidate. Live private configuration is captured separately.
    names = {'infra/vps/compose.yaml', 'infra/vps/Caddyfile'}
    archive_path = output/'deployment-files.tar'
    commands.run(['git', 'archive', '--format=tar', '--output='+str(archive_path),
                  revision, *sorted(names)], cwd=source, timeout=30)
    archive_path.chmod(0o600)
    with tarfile.open(archive_path) as archive:
        files = {member.name: member for member in archive.getmembers() if not member.isdir()}
        if set(files) != names or any(not member.isfile() or member.size > 1048576 for member in files.values()):
            raise RecoveryError('Deployed configuration archive is invalid')
        for name, member in files.items():
            path = output/Path(name).name
            with archive.extractfile(member) as value:
                path.write_bytes(value.read())
            path.chmod(0o600)
    archive_path.unlink()
    write_json(output/'runtime-binding.json', binding)
    return binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    with (args.output/'diagnostics.log').open('a') as log:
        binding = capture(args.source, args.output, commands=Commands(log))
    print(binding['revision'])


if __name__ == '__main__':
    main()
