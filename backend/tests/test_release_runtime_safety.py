"""Configuration parity and safe backup retention without touching a live stack."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app import auth, runtime_policy

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load('runtime_launcher_review', 'scripts/run_runtime.py')
exporter = load('backup_export_review', 'infra/vps/backup-export.py')
pruner = load('backup_prune_review', 'infra/vps/backup-prune.py')


def test_environment_defaults_share_hardening_and_keep_production_gates():
    modes = [runtime_policy.environment_defaults(env) for env in ('dev', 'staging', 'production')]
    for key in runtime_policy.DEFAULTS:
        assert modes[0][key] == modes[1][key] == modes[2][key]
    assert all(values['VOLT_SHARED_STATE_ENABLED'] == 'true' for values in modes)
    assert modes[2]['AUTH_ALLOW_TEST_ACCOUNTS'] == 'false'
    assert modes[2]['PROD_GO_LIVE_ENABLED'] == 'false'
    with pytest.raises(ValueError):
        runtime_policy.environment_defaults('production', 'fixtures')


def test_local_credentials_require_explicit_generation_and_stay_private(tmp_path):
    with pytest.raises(ValueError, match='explicitly'):
        runtime.configure('dev', tmp_path / 'default')
    credentials, values = runtime.configure('dev', tmp_path / 'dev', generate_test_account=True)
    config = auth.load_config(values, env_file=tmp_path / 'absent.env')
    assert config.on and config.session_policy == 'tab'
    assert auth.check_password(credentials['password'], config.test_accounts['owner.test']['hash'])
    auth.check_officers(config, [{'uid': 'owner'}])
    for path in ('api.env', 'credentials.json'):
        assert (tmp_path / 'dev' / path).stat().st_mode & 0o777 == 0o600
    assert (tmp_path / 'dev').stat().st_mode & 0o777 == 0o700
    assert runtime.read_env(tmp_path / 'dev' / 'api.env') == values
    assert values['DATABASE_URL'].endswith('@db/debt')
    assert values['CLAMAV_HOST'] == 'scanner'
    assert values['REQUIRE_DEPENDENCY_READINESS'] == 'true'


def test_local_stack_refuses_production_db_or_floating_application_image(tmp_path):
    with pytest.raises(ValueError):
        runtime.configure('staging', tmp_path / 'stage', {'DATABASE_URL': 'postgresql://production'}, True)
    with pytest.raises(ValueError, match='immutable'):
        runtime.images(SimpleNamespace(api_image='api:latest', web_image='web:latest'), False)
    pinned = 'sha256:' + 'a' * 64
    assert runtime.images(SimpleNamespace(api_image=pinned, web_image=pinned), False) == (pinned, pinned)


def test_local_compose_is_isolated_and_password_hash_survives_dotenv(tmp_path):
    if not subprocess.run(['docker', 'compose', 'version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        pytest.skip('Docker Compose is not installed')
    credentials, values = runtime.configure('staging', tmp_path, generate_test_account=True)
    runtime.private_write(tmp_path / 'nginx.conf', runtime.proxy_config())
    compose_values = {'RUNTIME_PROJECT': 'volt-debt-staging', 'RUNTIME_ENVIRONMENT': 'staging',
                      'RUNTIME_API_ENV': tmp_path / 'api.env', 'RUNTIME_NGINX_CONFIG': tmp_path / 'nginx.conf',
                      'RUNTIME_API_PORT': 19001, 'RUNTIME_WEB_PORT': 19000,
                      'POSTGRES_PASSWORD': credentials['database_password'], 'API_IMAGE': 'api:review',
                      'WEB_IMAGE': 'web:review', 'SCANNER_IMAGE': runtime.SCANNER_IMAGE,
                      'POSTGRES_IMAGE': runtime.POSTGRES_IMAGE}
    runtime.private_write(tmp_path / 'compose.env', runtime.dotenv(compose_values))
    model = json.loads(subprocess.check_output(['docker', 'compose', '--env-file', str(tmp_path / 'compose.env'),
                       '-f', str(runtime.COMPOSE), 'config', '--format', 'json'], text=True))
    assert model['name'] == 'volt-debt-staging'
    assert model['services']['api']['image'] == model['services']['worker']['image']
    # Compose config re-escapes every '$' as '$$' for safe round-tripping its
    # output (cmd/compose/config.go: escapeDollarSign); the service env is resolved.
    assert model['services']['api']['environment']['AUTH_TEST_ACCOUNTS'].replace('$$', '$') == values['AUTH_TEST_ACCOUNTS']
    for service in model['services'].values():
        for port in service.get('ports', []):
            assert port['host_ip'] == '127.0.0.1'
            assert int(port['published']) >= 18000
    assert all(volume['name'].startswith('volt-debt-staging_') for volume in model['volumes'].values())
    assert 'proxy_pass http://api:8080;' in runtime.proxy_config()
    assert 'Content-Security-Policy' in runtime.proxy_config()


@pytest.mark.parametrize('destination', ['/tmp/local', ':local:/tmp', 'local:/tmp'])
def test_backup_export_refuses_local_storage_as_offsite(monkeypatch, destination):
    def config(command, **kwargs):
        return SimpleNamespace(stdout='[local]\ntype = local\n')
    monkeypatch.setattr(exporter.subprocess, 'run', config)
    with pytest.raises(ValueError):
        exporter.remote_backend(destination)


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '143.198.207.143', 'collection.volt.co.th'])
def test_backup_export_refuses_same_server_sftp(monkeypatch, host):
    monkeypatch.setattr(exporter.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(stdout='[offsite]\ntype=sftp\nhost=%s\n' % host))
    with pytest.raises(ValueError):
        exporter.remote_backend('offsite:backups')


def test_backup_export_accepts_external_cloud_and_rejects_cleartext_endpoint(monkeypatch):
    monkeypatch.setattr(exporter.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(stdout='[offsite]\ntype=googlecloudstorage\n'))
    assert exporter.remote_backend('offsite:backups') == 'googlecloudstorage'
    monkeypatch.setattr(exporter.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(stdout='[offsite]\ntype=s3\nendpoint=http://example.com\n'))
    with pytest.raises(ValueError):
        exporter.remote_backend('offsite:backups')


def _backup(root, name, age=45):
    backup = root / name
    backup.mkdir()
    (backup / 'COMPLETE').write_text((datetime.now(timezone.utc)-timedelta(days=age)).isoformat()+'\n')
    (backup / 'SHA256SUMS').write_text('local backup artifact checksums\n')
    (backup / 'restore-evidence.json').write_text(json.dumps({'status': 'passed'}))
    evidence = {'status': 'verified', 'encrypted': True, 'backup': name, 'remote_backend': 'googlecloudstorage',
                'sha256': 'a'*64, 'verified_at_utc': datetime.now(timezone.utc).isoformat()}
    for key, filename in {'manifest_sha256': 'SHA256SUMS', 'complete_sha256': 'COMPLETE',
                          'restore_evidence_sha256': 'restore-evidence.json'}.items():
        evidence[key] = hashlib.sha256((backup / filename).read_bytes()).hexdigest()
    (backup / 'offsite-evidence.json').write_text(json.dumps(evidence))
    at = time.time() - age * 86400
    os.utime(backup, (at, at))
    return backup


def test_prune_preserves_newest_and_refuses_copied_or_changed_evidence(tmp_path):
    first = _backup(tmp_path, 'oldest', age=45)
    second = _backup(tmp_path, 'middle', age=40)
    _backup(tmp_path, 'newest', age=1)
    assert list(pruner.candidates(tmp_path, 30, 2)) == [first]
    (first / 'offsite-evidence.json').write_bytes((second / 'offsite-evidence.json').read_bytes())
    assert list(pruner.candidates(tmp_path, 30, 2)) == []
    evidence = json.loads((first / 'offsite-evidence.json').read_text())
    evidence['backup'] = 'oldest'
    (first / 'offsite-evidence.json').write_text(json.dumps(evidence))
    (first / 'SHA256SUMS').write_text('a changed local artifact manifest\n')
    assert list(pruner.candidates(tmp_path, 30, 2)) == []


def test_backup_transfer_verification_has_a_deadline_and_binds_evidence(monkeypatch, tmp_path):
    backup = _backup(tmp_path, 'completed-backup', age=1)
    monkeypatch.setenv('BACKUP_AGE_RECIPIENT', 'age1syntheticpublicrecipient')
    monkeypatch.setenv('BACKUP_REMOTE', 'offsite:backups')
    remote_files, calls = {}, []
    class Archive:
        def __init__(self, *args, **kwargs):
            self.stdout = io.BytesIO(b'synthetic archive')
        def wait(self, timeout): return 0
        def poll(self): return 0
        def kill(self): pass
    def command(arguments, **kwargs):
        calls.append((arguments, kwargs.get('timeout')))
        if arguments[:3] == ['rclone', 'config', 'redacted']:
            return SimpleNamespace(stdout='[offsite]\ntype=googlecloudstorage\n', returncode=0)
        if arguments[0] == 'age':
            kwargs['stdout'].write(b'synthetic encrypted archive')
        elif arguments[:2] == ['rclone', 'copyto']:
            source, destination = arguments[2:]
            if source.startswith('offsite:'):
                Path(destination).write_bytes(remote_files[source])
            else:
                remote_files[destination] = Path(source).read_bytes()
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(exporter.subprocess, 'Popen', Archive)
    monkeypatch.setattr(exporter.subprocess, 'run', command)
    exporter.export(backup)
    evidence = json.loads((backup / 'offsite-evidence.json').read_text())
    assert evidence['backup'] == backup.name and evidence['status'] == 'verified'
    assert evidence['manifest_sha256'] == hashlib.sha256((backup / 'SHA256SUMS').read_bytes()).hexdigest()
    assert evidence['complete_sha256'] == hashlib.sha256((backup / 'COMPLETE').read_bytes()).hexdigest()
    assert evidence['restore_evidence_sha256'] == hashlib.sha256((backup / 'restore-evidence.json').read_bytes()).hexdigest()
    downloads = [(args, timeout) for args, timeout in calls
                 if args[:2] == ['rclone', 'copyto'] and args[2].startswith('offsite:')]
    assert len(downloads) == 1 and downloads[0][1] == 1800


@pytest.mark.parametrize('environment', ['dev', 'stg', 'prd'])
def test_shared_peak_outbound_flag_refuses_before_transport(monkeypatch, environment):
    from app.integrations import peak
    monkeypatch.setenv('ENV', environment)
    monkeypatch.setenv('VOLT_SHARED_STATE_ENABLED', 'true')
    monkeypatch.setenv('PEAK_OUTBOUND_ENABLED', 'false')
    called = []
    monkeypatch.setattr(peak.httpx, 'post', lambda *args, **kwargs: called.append(args))
    with pytest.raises(Exception) as failure:
        peak.create_draft({'intent': 'INVOICE_CREATE'})
    assert getattr(failure.value, 'code', None) == 'feature_disabled'
    assert not called


def test_private_http_scanner_readiness_sends_workload_identity(monkeypatch, pg_url, pg_conn):
    from sqlalchemy import text
    from app import db, migrate, production_runtime
    from app.attachments import scanner
    migrate.apply(pg_conn)
    pg_conn.execute(text("insert into app.worker_heartbeat(name,state) values('local','idle')"))
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv('DATABASE_URL', pg_url)
    monkeypatch.setenv('ENV', 'prd')
    monkeypatch.setenv('REQUIRE_DEPENDENCY_READINESS', 'true')
    monkeypatch.setenv('CLAMAV_HOST', '')
    monkeypatch.setenv('SCANNER_URL', 'https://scanner.private')
    calls = []
    monkeypatch.setattr(scanner, 'identity_token', lambda audience: 'synthetic-workload-token')
    import requests
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr(requests, 'get', get)
    try:
        assert production_runtime.readiness()
        assert calls == [('https://scanner.private/livez', {
            'timeout': 0.5, 'headers': {'Authorization': 'Bearer synthetic-workload-token'}})]
    finally:
        db.reset()
