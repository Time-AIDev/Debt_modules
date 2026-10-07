"""Probe policy/entry simulations; actual offsite restore remains a separate gate."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

OPS = Path(__file__).resolve().parents[2]/'infra/vps'
sys.path.insert(0, str(OPS))
import recovery_worker_probe as probe
from recovery_support import sha

spec = importlib.util.spec_from_file_location('compatibility_probe_stack_tests', OPS/'restore-stack.py')
stack_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack_module)
ENVIRONMENT = {
    'ENV': 'stg', 'DEPLOYMENT_ENV': 'stg', 'AUTH_MODE': 'on',
    'AUTH_ALLOW_TEST_ACCOUNTS': 'false', 'PROD_GO_LIVE_ENABLED': 'false',
    'PEAK_OUTBOUND_ENABLED': 'false', 'VOLT_SHARED_STATE_ENABLED': 'true',
    'TASK_QUEUE_BACKEND': 'postgres',
    'VOLT_RECOVERY_READ_ONLY': 'true',
    'DATABASE_URL': 'postgresql+psycopg://debt_api:fixture@db/debt',
}


@pytest.mark.parametrize('change', [
    {'ENV': 'prod'}, {'DEPLOYMENT_ENV': 'prod'}, {'AUTH_MODE': 'off'},
    {'AUTH_ALLOW_TEST_ACCOUNTS': 'true'}, {'PROD_GO_LIVE_ENABLED': 'true'},
    {'PEAK_OUTBOUND_ENABLED': 'true'}, {'VOLT_SHARED_STATE_ENABLED': 'false'},
    {'TASK_QUEUE_BACKEND': 'memory'}, {'DATABASE_URL': 'postgresql://fixture@production/debt'},
    {'VOLT_RECOVERY_READ_ONLY': 'false'},
    {'DATABASE_URL': 'postgresql://fixture@db/another-database'},
])
def test_probe_refuses_unsafe_or_external_policy_before_heartbeat(change):
    with pytest.raises(RuntimeError):
        probe.run(dict(ENVIRONMENT, **change), tick=lambda *a: pytest.fail('must reject before heartbeat'))


def test_probe_only_updates_heartbeat_and_keeps_pending_jobs_and_business_data():
    state = {'business': [{'amount': '25.00'}], 'outbox': [{'uid': 'pending', 'finished_at': None}], 'heartbeat': []}
    before = deepcopy(state)
    def heartbeat(status):
        state['heartbeat'].append(status)
    def wait(seconds):
        assert seconds == 1
        if len(state['heartbeat']) == 2:
            raise StopIteration
    with pytest.raises(StopIteration):
        probe.run(ENVIRONMENT, tick=heartbeat, wait=wait)
    assert state['business'] == before['business'] and state['outbox'] == before['outbox']
    assert state['heartbeat'] == ['probe', 'probe']


@pytest.mark.parametrize('native', [False, True])
def test_old_image_uses_reviewed_entry_instead_of_unsafe_ignored_cli_flag(tmp_path, native):
    image = 'sha256:'+'1'*64
    stack = stack_module.RestoredStack(tmp_path, {'api': image}, None)
    arguments, metadata = stack.worker_probe_arguments(['--env-file', '/private/env', image], native)
    assert image in arguments
    if native:
        assert arguments[-4:] == ['python', '-m', 'app.local_worker', '--probe-only']
        assert metadata == {'kind': 'native', 'sha256': None}
        assert not (tmp_path/'worker-probe.py').exists()
    else:
        assert '--probe-only' not in arguments
        assert arguments[-2:] == ['python', '/app/recovery-worker-probe.py']
        assert str(tmp_path/'worker-probe.py')+':/app/recovery-worker-probe.py:ro' in arguments
        assert (tmp_path/'worker-probe.py').read_bytes() == (OPS/'recovery_worker_probe.py').read_bytes()
        assert metadata == {'kind': 'compatibility_heartbeat', 'sha256': sha(tmp_path/'worker-probe.py')}
