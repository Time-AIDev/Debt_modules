"""A declared latency change must not rewrite historical traffic or other SLOs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("latency_runner", ROOT / "scripts/run_k6.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_default_historical_declares_new_entry_and_exact_original_baseline():
    script, meta = runner.workload("historical")
    assert script.name == "production-3s.js"
    assert meta["latency_policy"] == "user-approved-3s-20261007"
    assert meta["latency_limit_ms"] == 3000
    assert meta["baseline_workload_sha256"] == runner.ORIGINAL_SHA256
    assert meta["workload_sha256"] == hashlib.sha256(script.read_bytes()).hexdigest()
    assert meta["workload_sha256"] != meta["baseline_workload_sha256"]
    assert meta["historical_payload_unchanged"] is True


def test_original_baseline_remains_a_separate_strict_profile():
    script, meta = runner.workload("historical-original")
    assert script == runner.SCRIPT
    assert meta["latency_policy"] == "original-2s" and meta["latency_limit_ms"] == 2000
    assert meta["workload_sha256"] == meta["baseline_workload_sha256"] == runner.ORIGINAL_SHA256


def test_changed_baseline_is_refused_before_any_network(monkeypatch, tmp_path):
    changed = tmp_path / "changed-original.js"
    changed.write_text("export default function () {}")
    monkeypatch.setattr(runner, "SCRIPT", changed)
    with pytest.raises(ValueError, match="original historical workload changed"):
        runner.workload("historical")


def inspect(script, tmp_path):
    binary = shutil.which("k6") or "/srv/volt-hardening-tools/k6-v2.3.0-linux-amd64/k6"
    if not Path(binary).is_file():
        pytest.skip("native k6 is unavailable")
    data, tokens = tmp_path / "data.json", tmp_path / "tokens.json"
    data.write_text(json.dumps({"customers":1,"customer_uids":["sheet-LOAD000001"]}))
    tokens.write_text(json.dumps([{"token":"synthetic-token","role":"OWNER"}]))
    command = [binary,"inspect","--env","DATASET_FILE="+str(data),"--env","TOKENS_FILE="+str(tokens),
               "--env","BASE_URL=http://127.0.0.1:18081",str(ROOT / "tests/load" / script)]
    result = subprocess.run(command,capture_output=True,text=True,timeout=20,check=True)
    return json.loads(result.stdout)


def test_native_wrapper_overrides_only_read_write_latency(tmp_path):
    baseline = inspect("production.js",tmp_path)
    revised = inspect("production-3s.js",tmp_path)
    expected = json.loads(json.dumps(baseline))
    for metric in ("business_read_ms","business_write_ms"):
        expected["thresholds"][metric] = ["p(95)<3000"]
    assert revised == expected


@pytest.mark.parametrize("script,latency_metrics", [
    ("capacity.js", ["business_read_ms","business_write_ms","capacity_page_ms"]),
    ("debt_workflow.js", ["business_read_ms","business_write_ms","complete_action_ms"]),
])
def test_native_supplements_preserve_error_replay_and_commit_gates(tmp_path,script,latency_metrics):
    options = inspect(script,tmp_path)
    thresholds = options["thresholds"]
    for metric in latency_metrics:
        assert thresholds[metric] == ["p(95)<3000"]
    assert thresholds["business_errors"] == ["rate<0.01"]
    assert thresholds["checks"] == ["rate>0.99"]
    assert thresholds["idempotency_replay_errors"] == ["rate==0"]
    if script == "debt_workflow.js":
        assert thresholds["debt_mutations_committed"] == ["count>0"]
        assert thresholds["role_denial_errors"] == ["rate==0"]
    else:
        assert thresholds["capacity_page_errors"] == ["rate<0.01"]
