"""Production promotion requires observed, exact-release quality evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "infra/vps/quality_evidence.py"
spec = importlib.util.spec_from_file_location("release_quality_test", SOURCE)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
REVISION = "a" * 40
IMAGES = {"api": "sha256:" + "1" * 64, "web": "sha256:" + "2" * 64}


def run(vus=25, duration=120, **extra):
    metrics = {}
    for name, (stat, _limit, expression) in quality.LIMITS.items():
        actual = 1 if name == "checks" else (0 if stat == "rate" else 100)
        metrics[name] = {"values": {stat: actual, "passes": 0, "fails": 10},
                         "thresholds": {expression: {"ok": True}}}
    metrics["http_reqs"] = {"values": {"count": 100}}
    metrics["vus_max"] = {"values": {"max": vus}}
    for name, stat, value, expression in (
        ("capacity_page_ms", "p(95)", 100, "p(95)<3000"),
        ("capacity_page_errors", "rate", 0, "rate<0.01"),
        ("complete_action_ms", "p(95)", 100, "p(95)<3000"),
        ("debt_mutations_committed", "count", 100, "count>0"),
    ):
        metrics[name] = {"values": {stat: value}, "thresholds": {expression: {"ok": True}}}
    return {"vus": vus, "duration_seconds": duration, "exit_code": 0,
            "customers": 500, "instalments_per_contract": 96, "unchanged_workload": True,
            "historical_payload_unchanged": True,
            "workload_sha256": quality.APPROVED_WORKLOAD_SHA256,
            "baseline_workload_sha256": quality.HISTORICAL_WORKLOAD_SHA256,
            "latency_policy": quality.LATENCY_POLICY, "latency_limit_ms": quality.LATENCY_LIMIT_MS,
            "legacy_unpaged_today": True, "oom_observed": False, "restart_delta": 0,
            "queue_growth": False,
            "concurrent_preview": {"profile": "debt_status", "started": True, "passed": True,
                                   "never_applied": True, "isolated_staging_only": True},
            "summary": {"metrics": metrics, "state": {"testRunDurationMs": duration * 1000}}, **extra}


def artifacts():
    common = {"status": "passed", "revision": REVISION, "images": IMAGES,
              "verified_at_utc": NOW.isoformat()}
    source = {"revision": REVISION, "tracked_sha256": "c" * 64, "tracked_files": 904,
              "tracked_clean": True, "untracked_code_files": 0}
    payloads = {
        "lint": {"errors": 0, "areas": ["backend", "frontend"]},
        "regression": {"scope": "full_backend_frontend", "backend_selection": ["tests"],
                       "frontend_selection": "all", "actual_pg_executed": True,
                       "source_before": source, "source_after": deepcopy(source), "source_unchanged": True,
                       "backend": {"passed": 10, "failed": 0, "errors": 0, "skipped": 0},
                       "frontend": {"passed": 10, "failed": 0, "errors": 0, "skipped": 0},
                       "flows": [{"id": name, "observed_tests": 1, "passed": 1, "failed": 0, "skipped": 0}
                                 for name in sorted(quality.REGRESSION_FLOWS)],
                       "frontend_build_exit": 0, "runtime_parity": True},
        "capacity": {"target_isolated": True, "matching_resource_profile": True,
                     "generator_fingerprint": "3" * 64, "target_fingerprint": "4" * 64,
                     "historical": [run(vus) for vus in (1, 10, 25)],
                     "supplemental": [run(scenario=name, duration=900 if name == "soak" else 120,
                                          customers=1431, roles=["OWNER", "MANAGER", "SUPERVISOR", "OFFICER", "OPS"])
                                      for name in ("paged_ui", "mixed_roles", "import_concurrency", "soak")]},
        "financial": {"staging_isolated": True, "actual_input_files": True,
                      "rows_accounted": True, "cash_conserved": True,
                      "snapshot_cash_not_double_counted": True, "duplicate_import_once": True,
                      "book_preserved": True, "unexplained_differences": 0, "tests_failed": 0,
                      "input_files": [{"sha256": str(n) * 64} for n in (1, 2, 3)]},
        "usability": {"method": "simulated_debt_team", "score": 10, "critical": 0,
                      "high": 0, "open_defects": 0, "failed": 0, "skipped": 0,
                      "unexercised": 0, "feature_count": 19, "checkpoints_total": 33,
                      "checkpoints_passed": 33, "roles_observed": ["OFFICER", "MANAGER", "OPS"],
                      "dimensions": {x: 2 for x in ("completion", "navigation", "financial_clarity",
                                                   "recovery", "accessibility")}},
        "offsite_recovery": {"simulated": False, "recovery_host_fingerprint": "5" * 64,
                             **{x: True for x in ("encrypted", "download_checksum_verified", "decrypted",
                                                 "database_restored", "objects_restored", "configuration_restored",
                                                 "application_ready", "source_images_verified", "counts_compared")},
                             "captured_at_utc": (NOW - timedelta(hours=1)).isoformat(),
                             "started_at_utc": (NOW - timedelta(minutes=10)).isoformat(),
                             "completed_at_utc": NOW.isoformat()},
        "alerts": {"simulated": False, "protocol": "http_json", "failure_acknowledged": True,
                   "recovery_acknowledged": True, "external_watchdog": True},
        "rollback": {"isolated": True, "schema_compatible": True, "preserves_new_writes": True,
                     "database_downgraded": False},
    }
    return {kind: {**common, **payload} for kind, payload in payloads.items()}


def bundle(tmp_path, documents):
    checks = {}
    for kind, data in documents.items():
        path = tmp_path / (kind + ".json")
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        checks[kind] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    result = {"format": "volt-quality-bundle-v1", "revision": REVISION,
              "images": IMAGES, "created_at_utc": NOW.isoformat(), "checks": checks}
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(result))
    return path


def validate(path):
    return quality.validate_bundle(path, revision=REVISION, api_image=IMAGES["api"],
                                   web_image=IMAGES["web"], reader=lambda file: file.read_bytes(),
                                   now=NOW, production_fingerprint="6" * 64)


def test_complete_exact_release_evidence_passes_without_exporting_contents(tmp_path):
    result = validate(bundle(tmp_path, artifacts()))
    assert result["passed"] is True
    assert set(result["checks"]) == set(quality.REQUIRED)
    assert result["policy"]["max_vus"] == 25
    assert "recovery_host_fingerprint" not in str(result)


@pytest.mark.parametrize("mutation", [
    lambda d: d.pop("alerts"),
    lambda d: d["lint"].update(errors=1),
    lambda d: d["regression"]["backend"].update(failed=1),
    lambda d: d["regression"]["backend"].update(errors=1),
    lambda d: d["regression"]["frontend"].update(failed=1),
    lambda d: d["regression"]["frontend"].update(errors=1),
    lambda d: d["regression"]["backend"].update(passed=True),
    lambda d: d["regression"]["frontend"].update(passed=0.5),
    lambda d: d["regression"]["backend"].update(skipped=1),
    lambda d: d["regression"]["frontend"].update(skipped=1),
    lambda d: d["regression"]["backend"].pop("skipped"),
    lambda d: d["regression"].update(scope="focused"),
    lambda d: d["regression"].update(backend_selection=["tests/test_capacity_projection.py"]),
    lambda d: d["regression"].update(frontend_selection="focused"),
    lambda d: d["regression"].update(actual_pg_executed=False),
    lambda d: d["regression"].pop("actual_pg_executed"),
    lambda d: d["regression"].pop("source_before"),
    lambda d: d["regression"].pop("source_after"),
    lambda d: d["regression"].update(source_unchanged=False),
    lambda d: d["regression"].update(source_unchanged=1),
    lambda d: d["regression"].pop("source_unchanged"),
    lambda d: d["regression"]["source_after"].update(tracked_sha256="d" * 64),
    lambda d: d["regression"]["source_before"].update(tracked_clean=False),
    lambda d: d["regression"]["source_after"].update(untracked_code_files=1),
    lambda d: d["regression"]["source_before"].update(untracked_code_files=False),
    lambda d: d["regression"]["source_before"].update(tracked_sha256="PRIVATE-TOKEN"),
    lambda d: d["regression"]["source_after"].update(revision="b" * 40),
    lambda d: d["regression"]["source_before"].update(revision=REVISION[:7]),
    lambda d: d["regression"]["flows"].pop(),
    lambda d: d["regression"]["flows"][0].update(id="unrecognized-flow"),
    lambda d: d["regression"]["flows"][0].update(id=d["regression"]["flows"][1]["id"]),
    lambda d: d["regression"]["flows"][0].update(observed_tests=0),
    lambda d: d["regression"]["flows"][0].update(observed_tests=True),
    lambda d: d["regression"]["flows"][0].update(passed=0),
    lambda d: d["regression"]["flows"][0].update(failed=1),
    lambda d: d["regression"]["flows"][0].update(skipped=1),
    lambda d: d["regression"].pop("flows"),
    lambda d: d["regression"].update(revision="b" * 40),
    lambda d: d["capacity"].update(generator_fingerprint="4" * 64),
    lambda d: d["capacity"]["historical"].pop(),
    lambda d: d["capacity"]["historical"][2].update(legacy_unpaged_today=False),
    lambda d: d["capacity"]["historical"][2].update(workload_sha256="f" * 64),
    lambda d: d["capacity"]["historical"][2].update(historical_payload_unchanged=False),
    lambda d: d["capacity"]["historical"][2].update(baseline_workload_sha256="f" * 64),
    lambda d: d["capacity"]["historical"][2].update(latency_policy="legacy-2s"),
    lambda d: d["capacity"]["historical"][2].update(latency_limit_ms=5000),
    lambda d: d["capacity"]["historical"][2]["summary"]["metrics"]["business_read_ms"]["values"].update({"p(95)": 3000}),
    lambda d: d["capacity"]["historical"][2]["summary"]["metrics"]["business_errors"]["values"].update(rate=.01),
    lambda d: d["capacity"]["historical"][2]["summary"]["metrics"]["checks"]["values"].update(rate=.99),
    lambda d: d["capacity"]["historical"][2]["summary"]["metrics"]["business_read_ms"].update(thresholds={"p(95)<5000": {"ok": True}}),
    lambda d: d["capacity"]["historical"][2]["summary"]["metrics"]["idempotency_replay_errors"]["values"].update(fails=0),
    lambda d: d["capacity"]["historical"][0].update(duration_seconds=30),
    lambda d: d["capacity"]["historical"][0]["summary"]["state"].update(testRunDurationMs=1000),
    lambda d: d["capacity"]["historical"][2]["summary"]["metrics"]["vus_max"]["values"].update(max=1),
    lambda d: d["capacity"]["historical"][2].update(exit_code=False),
    lambda d: d["capacity"]["supplemental"][-1].update(duration_seconds=899),
    lambda d: d["capacity"]["supplemental"][-1].update(oom_observed=True),
    lambda d: d["capacity"]["supplemental"][0]["summary"]["metrics"].pop("capacity_page_ms"),
    lambda d: d["capacity"]["supplemental"][1]["summary"]["metrics"]["complete_action_ms"]["values"].update({"p(95)": 3000}),
    lambda d: d["capacity"]["supplemental"][1]["summary"]["metrics"]["debt_mutations_committed"]["values"].update(count=0),
    lambda d: d["capacity"]["supplemental"][1].update(roles=["OWNER", "OFFICER"]),
    lambda d: d["capacity"]["supplemental"][2]["concurrent_preview"].update(passed=False),
    lambda d: d["financial"].update(cash_conserved=False),
    lambda d: d["financial"].update(actual_input_files=False),
    lambda d: d["usability"].update(unexercised=1),
    lambda d: d["usability"].update(open_defects=1),
    lambda d: d["usability"].update(feature_count=1),
    lambda d: d["usability"].update(checkpoints_passed=32),
    lambda d: d["usability"].update(checkpoints_total=19, checkpoints_passed=19),
    lambda d: d["usability"].update(failed=1),
    lambda d: d["usability"].update(skipped=1),
    lambda d: d["usability"]["dimensions"].update(financial_clarity=1),
    lambda d: d["offsite_recovery"].update(recovery_host_fingerprint="6" * 64),
    lambda d: d["offsite_recovery"].update(simulated=True),
    lambda d: d["offsite_recovery"].update(decrypted=False),
    lambda d: d["offsite_recovery"].update(captured_at_utc=(NOW - timedelta(hours=25)).isoformat()),
    lambda d: d["offsite_recovery"].update(started_at_utc=(NOW - timedelta(hours=5)).isoformat()),
    lambda d: d["alerts"].update(simulated=True),
    lambda d: d["rollback"].update(preserves_new_writes=False),
])
def test_incomplete_or_failed_proof_blocks_go_live(tmp_path, mutation):
    data = artifacts()
    mutation(data)
    with pytest.raises(quality.QualityError):
        validate(bundle(tmp_path, data))


def test_regression_required_flows_follow_actual_source_runner_inventory():
    plan = json.loads((SOURCE.parents[2] / "tests/dataflow/coverage-map.json").read_text())
    assert quality.REGRESSION_FLOWS == {flow["id"] for flow in plan["flows"]}
    assert len(quality.REGRESSION_FLOWS) == 19


def test_optional_extra_skips_do_not_replace_or_suppress_required_execution(tmp_path):
    data = artifacts()
    data["regression"]["extra_optional_tests"] = {
        "backend": {"passed": 2, "failed": 0, "skipped": 2},
        "frontend": {"passed": 1, "failed": 0, "skipped": 1},
    }
    assert validate(bundle(tmp_path, data))["passed"] is True
    data["regression"]["flows"][0]["skipped"] = 1
    with pytest.raises(quality.QualityError):
        validate(bundle(tmp_path, data))


def test_equal_dirty_or_old_manifests_and_missing_sha_never_certify_source(tmp_path):
    for changes in ({"tracked_clean": False}, {"revision": "b" * 40}, {"tracked_sha256": None},
                    {"untracked_code_files": 1}, {"revision": REVISION[:7]}, {"tracked_clean": 1},
                    {"untracked_code_files": False}):
        data = artifacts()
        source = {**data["regression"]["source_before"], **changes}
        data["regression"].update(source_before=source, source_after=deepcopy(source))
        with pytest.raises(quality.QualityError) as error:
            validate(bundle(tmp_path, data))
        assert "PRIVATE-TOKEN" not in str(error.value)


def test_changed_checksum_and_stale_manifest_are_rejected(tmp_path):
    path = bundle(tmp_path, artifacts())
    original = deepcopy(json.loads(path.read_text()))
    (tmp_path / "lint.json").write_text("{}")
    with pytest.raises(quality.QualityError, match="checksum"):
        validate(path)
    bundle(tmp_path, artifacts())
    original["created_at_utc"] = (NOW - timedelta(hours=25)).isoformat()
    path.write_text(json.dumps(original))
    with pytest.raises(quality.QualityError, match="stale"):
        validate(path)


def test_approved_three_second_policy_accepts_2500ms_and_remains_strict(tmp_path):
    data = artifacts()
    measured = data['capacity']['historical'][2]
    for name in ('business_read_ms', 'business_write_ms'):
        measured['summary']['metrics'][name]['values']['p(95)'] = 2500
    assert validate(bundle(tmp_path, data))['passed'] is True
    measured['summary']['metrics']['business_write_ms']['values']['p(95)'] = 3000
    with pytest.raises(quality.QualityError):
        validate(bundle(tmp_path, data))
    measured['summary']['metrics']['business_write_ms']['values']['p(95)'] = 2500
    measured['summary']['metrics']['business_read_ms']['thresholds'] = {'p(95)<2000': {'ok': False}}
    with pytest.raises(quality.QualityError):
        validate(bundle(tmp_path, data))


def test_missing_quality_stops_before_any_production_mutation(monkeypatch):
    source = SOURCE.with_name("release.py")
    spec = importlib.util.spec_from_file_location("quality_preflight_release", source)
    release_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_module)
    args = SimpleNamespace(revision=REVISION, api_image=IMAGES["api"], web_image=IMAGES["web"], go_live=True)
    release = release_module.Release(args)
    monkeypatch.setattr(release, "preflight", lambda: None)
    monkeypatch.setattr(release, "compose", lambda *a, **kw: pytest.fail("production must not be mutated"))
    with pytest.raises(release_module.ReleaseError, match="quality evidence"):
        release.deploy()
    assert release.mutated is False
