"""Recovery command simulations and archive guards, never external delivery proof."""
from datetime import timedelta
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest

OPS = Path(__file__).resolve().parents[2]/'infra/vps'
sys.path.insert(0, str(OPS))
from recovery_support import (Commands, RecoveryError, checksums, extract, now,
                              private_directory, release_bundle, sha, write_json)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, OPS/filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


cold = load('cold_recovery_guard_tests', 'cold-restore.py')
installer = load('operations_install_tests', 'install-operations.py')
exporter = load('cold_recovery_export_tests', 'backup-export.py')
stack_module = load('cold_recovery_stack_tests', 'restore-stack.py')
offsite = load('scheduled_offsite_tests', 'offsite-backup.py')
IMAGES = {name: 'sha256:'+str(index)*64 for index, name in enumerate(('api', 'web', 'db', 'scanner', 'edge'), 1)}
REVISION = 'a'*40


def bundle(root):
    root.mkdir(mode=0o700)
    with tarfile.open(root/'source.tar.gz', 'w:gz', format=tarfile.PAX_FORMAT, pax_headers={'comment': REVISION}) as archive:
        member = tarfile.TarInfo('source/app.py'); member.size = 4
        archive.addfile(member, io.BytesIO(b'pass'))
    (root/'docker-images.tar').write_bytes(b'simulated image archive; not a real image')
    (root/'clamav.tar.gz').write_bytes(b'simulated scanner archive')
    manifest = {'format': 'volt-debt-release-bundle-v1', 'revision': REVISION, 'images': IMAGES,
                'production_host_fingerprint': 'f'*64,
                'files': {name: sha(root/name) for name in ('source.tar.gz', 'docker-images.tar', 'clamav.tar.gz')}}
    write_json(root/'manifest.json', manifest); (root/'COMPLETE').write_text(now().isoformat())
    names = [*manifest['files'], 'manifest.json', 'COMPLETE']
    (root/'SHA256SUMS').write_text(''.join(sha(root/name)+'  '+name+'\n' for name in names))
    for entry in root.iterdir(): entry.chmod(0o600)
    return root


def recovery_point(root):
    path = root/'point.json'
    data = {'format': 'volt-debt-recovery-point-v1', 'encrypted': True, 'remote_backend': 's3',
            'backup': 'backup1', 'release_bundle': 'release1', 'archive': 'backup1.tar.age',
            'archive_sha256': '1'*64, 'release_manifest_sha256': '2'*64, 'backup_manifest_sha256': '3'*64,
            'revision': REVISION, 'images': IMAGES, 'production_host_fingerprint': 'f'*64,
            'captured_at_utc': (now()-timedelta(hours=1)).isoformat()}
    write_json(path, data)
    return path, data


def args(root):
    return SimpleNamespace(revision=REVISION, api_image=IMAGES['api'], web_image=IMAGES['web'],
                           production_fingerprint='f'*64, identity=root/'key', work_root=root/'work',
                           evidence=root/'proof.json', remote='offsite:backups', point='latest-recovery-point.json')


def test_same_machine_is_refused_before_download_or_container_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(cold, 'fingerprint', lambda: 'f'*64)
    monkeypatch.setattr(cold, 'Commands', lambda *a: pytest.fail('must not create command runner'))
    with pytest.raises(RecoveryError, match='independent'):
        cold.restore(args(tmp_path))
    assert not (tmp_path/'work').exists()


def test_missing_private_identity_does_not_emit_a_passed_recovery(monkeypatch, tmp_path):
    monkeypatch.setattr(cold, 'fingerprint', lambda: 'e'*64)
    with pytest.raises(FileNotFoundError): cold.restore(args(tmp_path))
    assert not (tmp_path/'proof.json').exists()


@pytest.mark.parametrize('changes', [
    {'revision': 'b'*40}, {'production_host_fingerprint': '0'*64},
    {'images': dict(IMAGES, api='sha256:'+'0'*64)}, {'archive': '../escaped.tar.age'},
    {'encrypted': False}, {'remote_backend': 'local'}, {'archive_sha256': 'missing'},
    {'captured_at_utc': (now()-timedelta(hours=25)).isoformat()},
    {'captured_at_utc': (now()+timedelta(hours=1)).isoformat()},
])
def test_recovery_metadata_must_match_candidate_and_recovery_policy(tmp_path, changes):
    path, data = recovery_point(tmp_path); data.update(changes); write_json(path, data)
    with pytest.raises(RecoveryError): cold.recovery_point(path, args(tmp_path))


def test_valid_metadata_is_only_a_download_plan_not_passed_application_proof(tmp_path):
    path, data = recovery_point(tmp_path)
    assert cold.recovery_point(path, args(tmp_path)) == data
    assert 'status' not in data and 'application_ready' not in data


@pytest.mark.parametrize('name,kind', [('../outside', 'file'), ('/outside', 'file'),
                                      ('safe-link', 'symlink'), ('device', 'device')])
def test_archive_refuses_traversal_links_and_devices(tmp_path, name, kind):
    archive = tmp_path/'malicious.tar'
    with tarfile.open(archive, 'w') as output:
        member = tarfile.TarInfo(name)
        if kind == 'symlink': member.type = tarfile.SYMTYPE; member.linkname = '/etc/passwd'
        elif kind == 'device': member.type = tarfile.CHRTYPE
        else: member.size = 1
        output.addfile(member, io.BytesIO(b'x') if kind == 'file' else None)
    with pytest.raises(RecoveryError): extract(archive, tmp_path/'target')
    assert not (tmp_path/'outside').exists()


def test_archive_refuses_duplicate_members_and_bounds_expansion(tmp_path):
    archive = tmp_path/'duplicate.tar'
    with tarfile.open(archive, 'w') as output:
        for _ in range(2):
            member = tarfile.TarInfo('same'); member.size = 2; output.addfile(member, io.BytesIO(b'xx'))
    with pytest.raises(RecoveryError): extract(archive, tmp_path/'target')
    with tarfile.open(archive, 'w') as output:
        member = tarfile.TarInfo('large'); member.size = 10; output.addfile(member, io.BytesIO(b'x'*10))
    with pytest.raises(RecoveryError): extract(archive, tmp_path/'target', maximum_bytes=2)


def test_release_bundle_verifies_git_archive_identity_and_every_payload(tmp_path):
    path = bundle(tmp_path/'release')
    assert release_bundle(path, revision=REVISION, images=IMAGES)['revision'] == REVISION
    (path/'docker-images.tar').write_bytes(b'changed')
    with pytest.raises(RecoveryError): release_bundle(path)


def test_release_bundle_cannot_approve_another_image_or_revision(tmp_path):
    path = bundle(tmp_path/'release')
    with pytest.raises(RecoveryError): release_bundle(path, revision='b'*40)
    with pytest.raises(RecoveryError): release_bundle(path, images={'api': 'sha256:'+'0'*64})


def test_checksum_manifest_rejects_unlisted_traversal(tmp_path):
    (tmp_path/'SHA256SUMS').write_text('a'*64+'  ../secret\n')
    with pytest.raises(RecoveryError): checksums(tmp_path)


def test_private_directory_never_chmods_an_existing_shared_parent(tmp_path):
    shared = tmp_path/'shared'; shared.mkdir(mode=0o755)
    with pytest.raises(RecoveryError): private_directory(shared, create=True)
    assert shared.stat().st_mode & 0o777 == 0o755


def test_image_verification_checks_pinned_id_revision_and_pg16():
    class Runner(Commands):
        def run(self, *a, **kw):
            return json.dumps([{'Id': IMAGES['api'], 'Config': {'Labels': {'org.opencontainers.image.revision': REVISION}, 'Env': ['PG_MAJOR=16']}}])
    runner = Runner(None)
    assert runner.image(IMAGES['api'], revision=REVISION, postgres=True) == IMAGES['api']
    with pytest.raises(RecoveryError): runner.image(IMAGES['api'], revision='b'*40)
    with pytest.raises(RecoveryError): runner.image('latest')


def test_command_runner_streams_private_sql_bytes_without_putting_them_in_arguments(tmp_path):
    with (tmp_path/'commands.log').open('w') as log:
        commands = Commands(log)
        result = commands.run([sys.executable, '-c', 'import sys; print(sys.stdin.buffer.read().decode())'],
                              stdin=io.BytesIO(b'synthetic SQL input'), capture=True, timeout=10)
    assert result == 'synthetic SQL input'
    assert 'synthetic SQL input' not in (tmp_path/'commands.log').read_text()


def test_stack_commands_use_owned_internal_resources_and_do_not_publish_ports(tmp_path):
    calls = []
    class Runner:
        def run(self, arguments, **kwargs): calls.append(arguments); return ''
    stack = stack_module.RestoredStack(tmp_path, IMAGES, None, commands=Runner())
    stack.create('api', [IMAGES['api']])
    assert calls[0][:3] == ['docker', 'run', '--detach']
    assert '--network' in calls[0] and stack.network in calls[0]
    assert '--publish' not in calls[0] and '-p' not in calls[0]
    assert 'volt.cold-restore='+stack.token in calls[0]


def test_cleanup_refuses_resources_without_this_run_ownership_label(tmp_path):
    calls = []
    class Runner:
        def run(self, arguments, **kwargs): calls.append(arguments); return 'someone-else'
    stack = stack_module.RestoredStack(tmp_path, IMAGES, None, commands=Runner())
    stack.created = [stack.prefix+'-api']; stack.network_created = True
    with pytest.raises(RecoveryError): stack.cleanup()
    assert not any('rm' in arguments for arguments in calls)


def test_operations_default_inspection_is_non_mutating(tmp_path):
    root = tmp_path/'root'
    result = installer.install(root)
    assert result['applied'] is False and not root.exists()
    assert 'usr/local/lib/volt-debt-ops/incident_alerts.py' in result['files']
    assert 'usr/local/sbin/volt-debt-health' in result['files']


@pytest.mark.skipif(os.geteuid() != 0, reason='Installation mode verification requires root in an isolated temp root')
def test_operations_install_copies_dependencies_exactly_with_private_modes(tmp_path):
    root = tmp_path/'root'
    result = installer.install(root, apply=True)
    assert result['applied'] is True
    library = root/'usr/local/lib/volt-debt-ops'
    for name in ('healthcheck.py', 'incident_alerts.py', 'recovery_support.py'):
        assert (library/name).read_bytes() == (OPS/name).read_bytes()
        assert (library/name).stat().st_mode & 0o777 == 0o600
    assert library.stat().st_mode & 0o777 == 0o700
    wrapper = root/'usr/local/sbin/volt-debt-health'
    assert '/usr/local/lib/volt-debt-ops/healthcheck.py' in wrapper.read_text()
    assert wrapper.stat().st_mode & 0o777 == 0o755


def test_operations_install_refuses_symlink_targets_and_test_root_activation(tmp_path):
    root = tmp_path/'linked'; root.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError): installer.install(root, apply=True)
    with pytest.raises(ValueError): installer.install(tmp_path, apply=True, activate=True)


@pytest.mark.parametrize('mutate_source', [False, True])
def test_optional_release_export_publishes_latest_only_after_verified_transfer(monkeypatch, tmp_path, mutate_source):
    """Fake transport checks sequencing; it is not evidence of S3 delivery."""
    release = bundle(tmp_path/'release1')
    backup = tmp_path/'backup1'; backup.mkdir(mode=0o700)
    captured = now()-timedelta(hours=1)
    (backup/'COMPLETE').write_text(captured.isoformat()+'\n')
    (backup/'restore-evidence.json').write_text(json.dumps({'status': 'passed'}))
    (backup/'manifest.txt').write_text('source_commit='+REVISION+'\nconsistency=database-and-objects_writers-stopped\nstarted_at_utc='+captured.isoformat()+'\ncaptured_at_utc='+captured.isoformat()+'\n')
    (backup/'database-image-id.txt').write_text(IMAGES['db']+'\n')
    (backup/'SHA256SUMS').write_text(''.join(sha(backup/name)+'  '+name+'\n' for name in ('COMPLETE', 'manifest.txt', 'database-image-id.txt')))
    monkeypatch.setenv('BACKUP_AGE_RECIPIENT', 'age1simulationpublicrecipient')
    monkeypatch.setenv('BACKUP_REMOTE', 'offsite:backups')
    monkeypatch.setattr(exporter, 'fingerprint', lambda: 'f'*64)
    monkeypatch.setattr(exporter, 'remote_backend', lambda destination: 's3')
    calls, objects = [], {}
    class Archive:
        def __init__(self, arguments, **kwargs):
            calls.append(arguments); self.stdout = io.BytesIO(b'simulated tar')
        def wait(self, timeout): return 0
        def poll(self): return 0
        def kill(self): pass
    def command(arguments, **kwargs):
        calls.append(arguments)
        if arguments[0] == 'age': kwargs['stdout'].write(b'simulated ciphertext')
        if arguments[:2] == ['rclone', 'copyto']:
            source, target = arguments[2:]
            if source.startswith('offsite:'):
                Path(target).write_bytes(objects[source])
                if mutate_source: (backup/'SHA256SUMS').write_text('changed during transfer')
            else: objects[target] = Path(source).read_bytes()
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(exporter.subprocess, 'Popen', Archive)
    monkeypatch.setattr(exporter.subprocess, 'run', command)
    if mutate_source:
        with pytest.raises(RuntimeError): exporter.export(backup, release)
        assert not any(arguments[-1].endswith('latest-recovery-point.json') for arguments in calls)
    else:
        exporter.export(backup, release)
        download = next(index for index, command in enumerate(calls) if command[:2] == ['rclone', 'copyto'] and command[2].startswith('offsite:'))
        latest = next(index for index, command in enumerate(calls) if command[-1].endswith('latest-recovery-point.json'))
        assert download < latest
        point = json.loads((backup/'recovery-point.json').read_text())
        assert point['revision'] == REVISION and point['images'] == IMAGES
        assert point['release_manifest_sha256'] == sha(release/'manifest.json')
        assert point['captured_at_utc'] == captured.isoformat()
        assert point['archive_sha256'] == hashlib.sha256(b'simulated ciphertext').hexdigest()


def test_scheduled_offsite_configuration_requires_real_private_provider_configuration(tmp_path):
    config = tmp_path/'offsite.json'
    write_json(config, {'remote': 'offsite:backups', 'recipient': 'age1public', 'rclone_config': str(tmp_path/'missing')})
    with pytest.raises(FileNotFoundError): offsite.configuration(config)
    (tmp_path/'remote.conf').write_text('simulation'); (tmp_path/'remote.conf').chmod(0o644)
    write_json(config, {'remote': 'offsite:backups', 'recipient': 'age1public', 'rclone_config': str(tmp_path/'remote.conf')})
    with pytest.raises(RecoveryError): offsite.configuration(config)
