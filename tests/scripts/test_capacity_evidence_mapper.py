"""Observed native metrics cannot become fabricated independent capacity proof."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('capacity_mapper', ROOT / 'scripts/build_capacity_evidence.py')
mapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapper)
REVISION = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
RUN = 'aaaaaaa-historical-25vu'
PLANNED = {'run_id': RUN, 'scenario': 'historical', 'vus': 25}


def write(path, data):
    path.write_text(json.dumps(data))


def artifacts(tmp_path):
    summary = {'metrics': {'business_read_ms': {'values': {'p(95)': 18000}}}}
    meta = {'revision': REVISION, 'api_image': IMAGE, 'exit_code': 99, 'process_return_code': 99,
            'duration_seconds': 120, 'vus': 25, 'profile': 'historical', 'workload_sha256': mapper.ORIGINAL,
            'dataset': {'customers': 500, 'instalments_per_contract': 96}, 'actor_roles': {'OWNER': 25},
            'production_health_guard': {'baseline_passed': True, 'monitor_completed': True, 'aborted': False}}
    resources = {'samples': [{'containers': [{'name': name, 'oom_killed': False, 'restart_count': 0}
                                             for name in ('owned-api', 'owned-db')]} for _ in range(2)]}
    for kind, value in (('summary', summary), ('meta', meta), ('resources', resources)):
        write(tmp_path / ('k6-' + RUN + '-' + kind + '.json'), value)
    return summary


def test_missing_runs_remain_unexecuted_and_missing_queue_counts_are_unknown(tmp_path):
    missing = mapper.map_run(tmp_path, PLANNED, REVISION, IMAGE, {})
    assert missing['execution'] == 'not_executed' and missing['exit_code'] is None
    native = artifacts(tmp_path)
    observed = mapper.map_run(tmp_path, PLANNED, REVISION, IMAGE, {})
    assert observed['queue_growth'] is None and observed['exit_code'] == 99
    assert observed['summary'] == native and observed['summary']['metrics']['business_read_ms']['values']['p(95)'] == 18000


def test_exact_bound_queue_counts_are_required_and_restart_failure_is_preserved(tmp_path):
    artifacts(tmp_path)
    counts = {RUN: {'revision': REVISION, 'api_image': IMAGE, 'isolated_read_only': True, 'pending_before': 0, 'pending_after': 1}}
    run = mapper.map_run(tmp_path, PLANNED, REVISION, IMAGE, counts)
    assert run['queue_growth'] is True and run['restart_delta'] == 0
    counts[RUN]['revision'] = 'c' * 40
    assert mapper.map_run(tmp_path, PLANNED, REVISION, IMAGE, counts)['queue_growth'] is None


def test_local_fingerprints_and_provisional_status_cannot_pass_independent_host_policy(tmp_path):
    artifacts(tmp_path)
    data = mapper.build(tmp_path, {'runs': [PLANNED], 'target_isolated': True}, REVISION, IMAGE, IMAGE, {})
    assert data['status'] == 'provisional' and data['capacity_acceptance_certified'] is False
    assert data['generator_fingerprint'] == data['target_fingerprint']
    assert data['historical'][0]['summary']['metrics']['business_read_ms']['values']['p(95)'] == 18000


def test_meta_without_native_summary_is_incomplete_not_silently_unexecuted(tmp_path):
    artifacts(tmp_path)
    (tmp_path / ('k6-' + RUN + '-summary.json')).unlink()
    run = mapper.map_run(tmp_path, PLANNED, REVISION, IMAGE, {})
    assert run['execution'] == 'incomplete_native_evidence' and run['exit_code'] == 99
