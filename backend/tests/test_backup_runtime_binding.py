"""Real Git archives with simulated Docker identities; no offsite proof."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

OPS = Path(__file__).resolve().parents[2]/'infra/vps'
sys.path.insert(0, str(OPS))
from backup_runtime import capture, recorded_binding, runtime_binding
from recovery_support import Commands, RecoveryError, release_bundle, write_json

spec = importlib.util.spec_from_file_location('backup_runtime_package_tests', OPS/'package-release.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)
IMAGES = {name: 'sha256:'+str(index)*64 for index, name in enumerate(('api', 'web', 'db', 'scanner', 'edge'), 1)}


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path/'source'; root.mkdir()
    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=root, stderr=subprocess.PIPE).decode().strip()
    git('init', '--quiet')
    git('config', 'user.name', 'Backup fixture')
    git('config', 'user.email', 'backup-fixture@example.invalid')
    directory = root/'infra/vps'; directory.mkdir(parents=True)
    contents = {'compose.yaml': b'\nservices:\n  api:\n    image: deployed\n\n',
                'Caddyfile': b'http://:8080 {\n respond "deployed"\n}\n\n'}
    for name, value in contents.items(): (directory/name).write_bytes(value)
    git('add', '.'); git('commit', '--quiet', '-m', 'Deployed fixture')
    deployed = git('rev-parse', 'HEAD')
    for name in contents: (directory/name).write_text('new candidate configuration\n')
    git('add', '.'); git('commit', '--quiet', '-m', 'New candidate fixture')
    assert git('rev-parse', 'HEAD') != deployed
    return root, deployed, contents


class DockerFixture(Commands):
    def __init__(self, log, revision):
        super().__init__(log)
        self.revision = revision
        self.images = dict(IMAGES, worker=IMAGES['api'])
        self.revisions = {value: revision for value in self.images.values()}
        self.counts = {}
        self.running = True
        self.running_by_service = {}
        self.container_revision = 'f'*40

    def run(self, arguments, **kwargs):
        if arguments[0] != 'docker': return super().run(arguments, **kwargs)
        if arguments[1] == 'ps':
            service = next(value.split('=', 1)[1] for value in arguments
                           if value.startswith('label=com.docker.compose.service='))
            service = service.rsplit('=', 1)[-1]
            if '--all' not in arguments and not self.running_by_service.get(service, self.running): return ''
            return '\n'.join('fixture-'+service for _ in range(self.counts.get(service, 1)))
        if arguments[1:3] == ['image', 'inspect']:
            image = arguments[3]
            return json.dumps([{'Id': image, 'Config': {'Labels': {
                'org.opencontainers.image.revision': self.revisions.get(image)}, 'Env': ['PG_MAJOR=16']}}])
        if arguments[1] == 'inspect':
            service = 'scanner' if arguments[2] == 'volt-debt-scanner-1' else arguments[2].removeprefix('fixture-')
            return json.dumps([{'Id': 'fixture-'+service, 'Image': self.images[service],
                               'State': {'Running': self.running_by_service.get(service, self.running)}, 'Config': {'Labels': {
                                   'com.docker.compose.project': 'volt-debt',
                                   'com.docker.compose.service': service,
                                   'org.opencontainers.image.revision': self.container_revision}}}])
        if arguments[1] == 'save':
            Path(arguments[arguments.index('--output')+1]).write_bytes(b'simulated image archive')
            return None
        if arguments[1] == 'cp':
            directory = Path(arguments[-1])
            for name in ('main.cvd', 'daily.cvd'): (directory/name).write_bytes(b'simulated scanner signature')
            return None
        raise AssertionError('Unexpected simulated Docker command')


def test_capture_archives_deployed_bytes_when_checkout_head_has_advanced(checkout, tmp_path):
    root, revision, contents = checkout
    output = tmp_path/'backup'; output.mkdir(mode=0o700)
    (output/'database-image-id.txt').write_text(IMAGES['db']+'\n')
    with (output/'diagnostics.log').open('w') as log:
        result = capture(root, output, commands=DockerFixture(log, revision))
    assert result['revision'] == revision and result['images'] == IMAGES
    assert recorded_binding(output/'runtime-binding.json') == result
    for name, value in contents.items():
        assert (output/name).read_bytes() == value
        assert (output/name).stat().st_mode & 0o777 == 0o600
    assert (output/'runtime-binding.json').stat().st_mode & 0o777 == 0o600
    assert not (output/'deployment-files.tar').exists()


@pytest.mark.parametrize('failure', ['mixed_revision', 'worker_image', 'missing', 'multiple', 'stopped', 'missing_label'])
def test_mixed_or_incomplete_runtime_cannot_name_a_backup_release(tmp_path, failure):
    with (tmp_path/'log').open('w') as log:
        commands = DockerFixture(log, 'a'*40)
        if failure == 'mixed_revision': commands.revisions[IMAGES['web']] = 'b'*40
        elif failure == 'worker_image': commands.images['worker'] = IMAGES['web']
        elif failure == 'missing': commands.counts['api'] = 0
        elif failure == 'multiple': commands.counts['web'] = 2
        elif failure == 'stopped': commands.running = False
        elif failure == 'missing_label': commands.revisions[IMAGES['api']] = None
        with pytest.raises(RecoveryError): runtime_binding(commands)


def test_capture_refuses_database_swap_before_writers_are_paused(checkout, tmp_path):
    root, revision, _ = checkout
    output = tmp_path/'backup'; output.mkdir(mode=0o700)
    (output/'database-image-id.txt').write_text('sha256:'+'0'*64+'\n')
    with (output/'log').open('w') as log:
        with pytest.raises(RecoveryError, match='database'):
            capture(root, output, commands=DockerFixture(log, revision))
    assert not (output/'runtime-binding.json').exists()


def test_stopped_writers_can_be_bound_without_starting_them(tmp_path):
    with (tmp_path/'log').open('w') as log:
        commands = DockerFixture(log, 'a'*40)
        commands.running_by_service = {'api': False, 'worker': False}
        assert runtime_binding(commands)['images'] == IMAGES


@pytest.mark.parametrize('change', [
    {'revision': 'main'}, {'images': dict(IMAGES, api='latest')},
    {'images': {key: value for key, value in IMAGES.items() if key != 'web'}},
    {'format': 'unknown'},
])
def test_recorded_binding_rejects_unpinned_or_incomplete_images(tmp_path, change):
    value = {'format': 'volt-backup-runtime-v1', 'revision': 'a'*40, 'images': IMAGES}
    value.update(change)
    path = tmp_path/'binding.json'; write_json(path, value)
    with pytest.raises(RecoveryError): recorded_binding(path)


def test_package_uses_deployed_commit_available_in_a_different_clean_head(checkout, tmp_path, monkeypatch):
    root, revision, _ = checkout
    monkeypatch.setattr(packager, 'Commands', lambda log: DockerFixture(log, revision))
    output = tmp_path/'release1'
    arguments = SimpleNamespace(source=root, revision=revision, output=output,
                                scanner_container='volt-debt-scanner-1',
                                **{name+'_image': image for name, image in IMAGES.items()})
    result = packager.package(arguments)
    assert result['revision'] == revision
    assert release_bundle(output, revision=revision, images=IMAGES)['revision'] == revision
