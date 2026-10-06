"""Host guards observe health without exposing responses or mutating production."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('capacity_guard', ROOT / 'scripts/capacity_health_guard.py')
guard_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard_module)


def healthy(memory=1024 ** 3, success=True):
    return {'production_healthy': success, 'available_memory_bytes': memory,
            'endpoints': {key: {'status': 200 if success else 503, 'json': True, 'elapsed_ms': 10}
                          for key in ('liveness', 'readiness')}}


def inventory():
    return [{'name': '/capacity-test-api', 'tag': 'capacity-test', 'memory': 1024 ** 3, 'quota': -1,
             'running': True, 'oom': False, 'restarts': 0},
            {'name': '/capacity-test-db', 'tag': 'capacity-test', 'memory': 512 * 1024 ** 2, 'quota': -1,
             'running': True, 'oom': False, 'restarts': 0}]


@pytest.fixture
def guard(monkeypatch):
    monkeypatch.setattr(guard_module, 'owned_inventory', lambda *args: inventory())
    monkeypatch.setattr(guard_module, 'probe_health', healthy)
    return guard_module.Guard('capacity-test-api', 'capacity-test-db')


def test_baseline_health_or_headroom_failure_prevents_start(guard, monkeypatch):
    monkeypatch.setattr(guard_module, 'probe_health', lambda: healthy(success=False))
    assert guard.poll(baseline=True) == 'production_health'
    assert guard.evidence['baseline_passed'] is False and guard.evidence['aborted'] is True
    assert guard.evidence['isolated_api_stopped'] is False


def test_baseline_low_memory_refuses_before_any_load(guard, monkeypatch):
    monkeypatch.setattr(guard_module, 'probe_health', lambda: healthy(memory=256 * 1024 ** 2))
    assert guard.poll(baseline=True) == 'host_low_memory'
    assert guard.evidence['baseline_passed'] is False


def test_probes_keep_only_status_timing_and_memory_not_raw_responses(monkeypatch):
    class Response:
        status = 200
        headers = SimpleNamespace(get_content_type=lambda: 'application/json')
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, cap):
            return json.dumps({'status': self.expected, 'private': 'PRIVATE-TOKEN'}).encode()
    class Opener:
        def open(self, request, **kwargs):
            assert request.full_url in guard_module.URLS.values()
            assert 'Authorization' not in request.headers
            response = Response()
            response.expected = 'ok' if request.full_url.endswith('/healthz') else 'ready'
            return response
    monkeypatch.setattr(guard_module.urllib.request, 'build_opener', lambda *args: Opener())
    result = guard_module.probe_health()
    assert result['production_healthy'] is True
    assert 'PRIVATE-TOKEN' not in json.dumps(result)


@pytest.mark.parametrize('body', [b'{}', b'{"status":"unavailable"}'])
def test_http200_without_expected_health_status_fails(monkeypatch, body):
    class Response:
        status = 200
        headers = SimpleNamespace(get_content_type=lambda: 'application/json')
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, cap):
            return body
    monkeypatch.setattr(guard_module.urllib.request, 'build_opener', lambda *args: SimpleNamespace(open=lambda *a, **kw: Response()))
    assert guard_module.probe_health()['production_healthy'] is False


def test_child_exit_race_still_stops_owned_api_and_records_complete_shutdown(guard, monkeypatch):
    class Child:
        done = False
        def poll(self):
            return 0 if self.done else None
        def terminate(self):
            self.done = True
            raise ProcessLookupError('Child completed during probe')
    calls = []
    def stopped():
        calls.append('only-owned-api')
        guard.evidence['isolated_api_stopped'] = True
    monkeypatch.setattr(guard, 'stop_isolated_api', stopped)
    guard.abort_load(Child())
    assert calls == ['only-owned-api'] and guard.evidence['generator_already_exited'] is True
    assert guard.evidence['shutdown_complete'] is True and guard.evidence['generator_alive'] is False


def test_unfinished_child_or_unstopped_api_never_claims_complete_shutdown(guard, monkeypatch):
    child = SimpleNamespace(poll=lambda: None, terminate=lambda: None)
    monkeypatch.setattr(guard, 'stop_isolated_api', lambda: None)
    guard.abort_load(child)
    assert guard.evidence['generator_alive'] is True and guard.evidence['shutdown_complete'] is False


def test_monitor_still_alive_after_bounded_join_records_failed_proof(guard):
    joined = []
    thread = SimpleNamespace(join=lambda **kwargs: joined.append(kwargs), is_alive=lambda: True)
    assert guard.finish_monitor(thread) is False
    assert joined == [{'timeout': 30}]
    assert guard.evidence['monitor_completed'] is False and guard.evidence['aborted'] is True
    assert guard.evidence['reason'] == 'guard_monitor_incomplete' and guard.evidence['shutdown_complete'] is False


def test_runner_refused_baseline_persists_metadata_without_starting_generator(tmp_path, monkeypatch):
    import sys
    runner_spec = importlib.util.spec_from_file_location('guarded_runner', ROOT / 'scripts/run_k6.py')
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    fixture = {'synthetic': True, 'customers': 1, 'contracts': 1, 'instalments_per_contract': 96}
    monkeypatch.setattr(runner, 'validate_fixtures', lambda *args: (fixture, [], tmp_path / 'data.json', tmp_path / 'tokens.json'))
    monkeypatch.setattr(runner, 'actor_roles', lambda *args: {'OWNER': 25})
    monkeypatch.setattr(runner, 'runtime_binding', lambda *args: {'revision': 'a' * 40, 'api_image': 'sha256:' + 'b' * 64})
    monkeypatch.setattr(runner.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout='k6 synthetic version'))
    def never_start(*args, **kwargs):
        raise AssertionError('Baseline refusal must not start load')
    monkeypatch.setattr(runner.subprocess, 'Popen', never_start)
    monkeypatch.setitem(sys.modules, 'capacity_health_guard', guard_module)
    monkeypatch.setattr(guard_module, 'owned_inventory', lambda *args: inventory())
    monkeypatch.setattr(guard_module, 'probe_health', lambda: healthy(success=False))
    output = tmp_path / 'private-results'
    code = runner.main(['--base-url', 'http://127.0.0.1:18081', '--tokens-file', str(tmp_path / 'tokens.json'),
        '--dataset-file', str(tmp_path / 'data.json'), '--api-container', 'capacity-test-api', '--db-container', 'capacity-test-db',
        '--production-health-guard', '--k6', '/synthetic/k6', '--run-id', 'aaaaaaa-historical-1vu', '--output-dir', str(output)])
    assert code == 1
    meta = json.loads((output / 'k6-aaaaaaa-historical-1vu-meta.json').read_text())
    assert meta['production_health_guard']['baseline_passed'] is False and meta['exit_code'] == 1
    assert meta['process_return_code'] is None
    assert not list(output.glob('*-summary.json'))


def test_healthy_baseline_and_three_production_failures_abort(guard, monkeypatch):
    assert guard.poll(baseline=True) is None and guard.evidence['baseline_passed'] is True
    monkeypatch.setattr(guard_module, 'probe_health', lambda: healthy(success=False))
    assert guard.poll() is None and guard.poll() is None
    assert guard.poll() == 'production_health'


def test_memory_failure_requires_two_consecutive_samples_and_resets_after_recovery(guard, monkeypatch):
    observations = iter([healthy(), healthy(memory=256 * 1024 ** 2), healthy(),
                         healthy(memory=256 * 1024 ** 2), healthy(memory=256 * 1024 ** 2)])
    monkeypatch.setattr(guard_module, 'probe_health', lambda: next(observations))
    assert guard.poll(baseline=True) is None
    assert guard.poll() is None and guard.poll() is None and guard.poll() is None
    assert guard.poll() == 'host_low_memory'


@pytest.mark.parametrize('field,value,reason', [('oom', True, 'target_oom'),
    ('restarts', 1, 'target_restart'), ('running', False, 'target_not_running')])
def test_target_failure_aborts_without_waiting_for_health_failure(guard, monkeypatch, field, value, reason):
    rows = inventory()
    rows[0][field] = value
    monkeypatch.setattr(guard_module, 'owned_inventory', lambda *args: rows)
    assert guard.poll() == reason


def test_stop_proves_ownership_again_and_never_stops_database_or_production(guard, monkeypatch):
    calls = []
    monkeypatch.setattr(guard_module.subprocess, 'run', lambda args, **kw: calls.append(args))
    guard.stop_isolated_api()
    assert calls == [['docker', 'stop', '--time', '2', 'capacity-test-api']]
    def withdrawn(*args):
        raise ValueError('Ownership changed')
    monkeypatch.setattr(guard_module, 'owned_inventory', withdrawn)
    with pytest.raises(ValueError):
        guard.stop_isolated_api()
    assert len(calls) == 1


@pytest.mark.parametrize('invalid', [False, True])
def test_inventory_reads_no_env_and_refuses_unowned_or_wrong_limits(monkeypatch, invalid):
    rows = inventory()
    if invalid:
        rows[0]['memory'] *= 2
    def inspect(args, **kwargs):
        assert args[:3] == ['docker', 'inspect', '--format'] and '.Config.Env' not in args[3]
        return SimpleNamespace(stdout='\n'.join(json.dumps(row) for row in rows))
    monkeypatch.setattr(guard_module.subprocess, 'run', inspect)
    if invalid:
        with pytest.raises(ValueError):
            guard_module.owned_inventory('capacity-test-api', 'capacity-test-db')
    else:
        assert guard_module.owned_inventory('capacity-test-api', 'capacity-test-db') == rows
