"""Public reports discard sensitive source fields and never inflate acceptance."""
import importlib.util
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("implementation_report", ROOT / "scripts/build_implementation_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
REV = "a" * 40
OLD = "b" * 40


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def fixture(tmp_path):
    evidence = tmp_path / "private"
    write(evidence / "progress.json", {"committed_revision": REV, "go_live_enabled": False,
        "external_inputs_pending": ["independent load generator", "PRIVATE-CUSTOMER-NAME"],
        "tokens": "PRIVATE-TOKEN", "customer_uid": "PRIVATE-CUSTOMER-UID", "notes": "PRIVATE-NOTE"})
    write(evidence / "component-real-file-validation.json", {"invoice": {"documents": 4, "component_total": "100.00",
        "customer_names": ["PRIVATE-CUSTOMER-NAME"], "tax_id": "PRIVATE-TAX-ID"}, "receipt": {"quarantined_documents": 2}})
    write(evidence / "qa/feature-matrix.json", {"revision": OLD, "score": 10,
        "flows": [{"status": "pending", "name": "PRIVATE-CUSTOMER-NAME", "browser_observed": False}],
        "findings": [{"detail": "PRIVATE-TOKEN"}], "routes": ["PRIVATE-CUSTOMER-UID"]})
    write(evidence / "qa/scenarios.template.json", [{"mutation": True, "steps": [{"customer_uid": "PRIVATE-CUSTOMER-UID"}]}])
    write(evidence / "diagnostic/owned-resources.json", {"revision": OLD, "api_image": "sha256:" + "c" * 64,
        "environment": {"AUTH_SESSION_SECRET": "PRIVATE-TOKEN"}})
    metrics = {}
    for name, rule in report.THRESHOLDS.items():
        value = 18000 if name.endswith("_ms") else .3 if name == "business_errors" else .8 if name == "checks" else .1
        metrics[name] = {"values": {"p(95)" if name.endswith("_ms") else "rate": value}, "thresholds": {rule: {"ok": False}}}
    prefix = evidence / "diagnostic/results/k6-bbbbbbb-historical-25vu"
    write(Path(str(prefix) + "-summary.json"), {"metrics": metrics, "tokens": "PRIVATE-TOKEN"})
    write(Path(str(prefix) + "-meta.json"), {"generator_co_located": True, "duration_seconds": 120,
        "process_return_code": 99, "dataset": {"customers": 500, "contracts": 500, "instalments_per_contract": 96},
        "actor_roles": {"OWNER": 25}, "headers": {"Authorization": "PRIVATE-TOKEN"}})
    return evidence


def test_whitelist_excludes_sensitive_unknown_fields_and_preserves_failures(tmp_path):
    data = report.build_aggregate(fixture(tmp_path), REV)
    text = json.dumps(data)
    for sentinel in ("PRIVATE-TOKEN", "PRIVATE-CUSTOMER-UID", "PRIVATE-CUSTOMER-NAME", "PRIVATE-NOTE", "PRIVATE-TAX-ID"):
        assert sentinel not in text
    assert data["k6"][0]["binding"] == "OLDER_REVISION"
    assert data["k6"][0]["native_exit_code"] == 99
    assert data["k6"][0]["original_thresholds_passed"] is False
    assert data["capacity_acceptance_certified"] is False
    assert data["ux"]["usability_estimate_score"] is None
    assert data["ux"]["execution_counts"]["skipped"] is None
    assert data["financial"]["source_validation"]["invoice"]["parsed_component_total"] == "100.00"
    assert data["financial"]["applied_or_allocated_cash_certified"] is False


def test_completed_matching_qa_keeps_real_skips_and_score(tmp_path):
    data = report.build_aggregate(fixture(tmp_path), REV, qa_execution={"revision": REV, "execution_status": "completed",
        "score": 8.5, "passed": 10, "failed": 1, "skipped": 3, "unexecuted": 0, "notes": "PRIVATE-NOTE"})
    assert data["ux"]["usability_estimate_score"] == 8.5
    assert data["ux"]["execution_counts"] == {"passed": 10, "failed": 1, "skipped": 3, "unexecuted": 0}


def test_unexecuted_scenarios_prevent_scoring_even_with_claimed_completion(tmp_path):
    data = report.build_aggregate(fixture(tmp_path), REV, qa_execution={"revision": REV, "execution_status": "completed",
        "score": 10, "passed": 10, "skipped": 0, "unexecuted": 7})
    assert data["ux"]["usability_estimate_score"] is None


def test_offsite_deferral_report_keeps_local_restore_alerts_and_external_inputs(tmp_path):
    evidence = fixture(tmp_path)
    images = {"api": "sha256:" + "1" * 64, "web": "sha256:" + "2" * 64}
    progress = {"candidate_revision": REV, "candidate_api_image": images["api"], "candidate_web_image": images["web"],
                "external_inputs_pending": list(report.INPUTS)}
    write(evidence / "progress.json", progress)
    decision = {"revision": REV, "images": images, "status": "deferred", "passed": False,
                "verified_at_utc": datetime.now(timezone.utc).isoformat(), "scope": "offsite_recovery",
                "authorization": "explicit_user_request", "reason": "PRIVATE-NOTE"}
    data = report.build_aggregate(evidence, REV, offsite_deferral=decision)
    policy = data["offsite_recovery_policy"]
    assert policy["status"] == "deferred" and policy["restore_certified"] is False
    assert policy["local_restore_required"] is True and policy["real_alerts_required"] is True
    assert data["pending_external_inputs"] == list(report.INPUTS[3:])
    assert "PRIVATE-NOTE" not in json.dumps(data)
    assert data["deployment_certified"] is False and data["completion_certified"] is False
    for change in ({"revision": OLD}, {"passed": True}, {"preparation_only": True},
                   {"images": {"api": images["api"], "web": None}}, {"reason": " "},
                   {"verified_at_utc": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()}):
        actual = report.build_aggregate(evidence, REV, offsite_deferral={**decision, **change})
        assert actual["offsite_recovery_policy"]["status"] == "required"
        assert actual["pending_external_inputs"] == list(report.INPUTS)


def test_full_score_requires_completed_checkpoints_and_no_open_defects(tmp_path):
    evidence = fixture(tmp_path)
    valid = {"revision": REV, "execution_status": "completed", "score": 10,
             "passed": 91, "failed": 0, "skipped": 0, "unexecuted": 0,
             "open_defects": 0, "feature_count": 19, "checkpoints_total": 33, "checkpoints_passed": 33,
             "roles_observed": ["OFFICER", "MANAGER", "OPS"],
             "dimensions": {name: 2 for name in report.UX_DIMENSIONS}}
    assert report.build_aggregate(evidence, REV, qa_execution=valid)["ux"]["usability_estimate_score"] == 10
    for change in ({"failed": 1}, {"failed": False}, {"skipped": 1}, {"open_defects": 1}, {"passed": 0},
                   {"checkpoints_passed": 32}, {"checkpoints_total": 1},
                   {"checkpoints_total": 19, "checkpoints_passed": 19}, {"feature_count": 18},
                   {"roles_observed": ["OFFICER", "MANAGER"]}, {"roles_observed": "OFFICER MANAGER OPS"},
                   {"dimensions": None}, {"dimensions": {**valid["dimensions"], "navigation": 1}},
                   {"dimensions": {**valid["dimensions"], "navigation": True}},
                   {"dimensions": {**valid["dimensions"], "PRIVATE-TOKEN": 2}}):
        actual = report.build_aggregate(evidence, REV, qa_execution={**valid, **change})
        assert actual["ux"]["usability_estimate_score"] is None
        assert "PRIVATE-TOKEN" not in json.dumps(actual)


def source_manifest(revision=REV, checksum="c" * 64, **extra):
    return {"revision": revision, "tracked_sha256": checksum, "tracked_clean": True,
            "untracked_code_files": 0, "notes": "PRIVATE-NOTE", **extra}


def test_component_results_keep_source_binding_without_promoting_focused_or_old_runs(tmp_path):
    evidence = fixture(tmp_path)
    summary = tmp_path / "summary.json"
    manifest = source_manifest()
    data = {"backend": {"tests": 41, "passed": 41, "failed": 0, "skipped": 0},
            "source_before": manifest, "source_after": manifest, "source_unchanged": True,
            "backend_selection": ["tests/test_capacity_projection.py"],
            "private_env": "PRIVATE-TOKEN"}
    write(summary, data)
    current = report.build_aggregate(evidence, REV, test_summaries=[summary])["tests"][0]
    assert current["binding"] == "MATCHING_REPORT_REVISION"
    assert current["source_unchanged"] is True and current["matching_report_revision"] is True
    assert current["source_bound_for_report_revision"] is True
    assert current["source_before"]["tracked_sha256"] == "c" * 64
    assert current["source_after"]["revision"] == REV
    assert current["final_regression_certified"] is False
    assert "PRIVATE-" not in json.dumps(current)
    old = source_manifest(OLD)
    write(summary, {**data, "source_before": old, "source_after": old})
    previous = report.build_aggregate(evidence, REV, test_summaries=[summary])["tests"][0]
    assert previous["binding"] == "OLDER_REVISION"
    assert previous["matching_report_revision"] is False
    assert previous["source_bound_for_report_revision"] is False
    assert previous["final_regression_certified"] is False
    assert "not final regression evidence" in previous["scope"]


def test_dirty_changed_or_untracked_source_cannot_become_final_regression_evidence(tmp_path):
    summary = tmp_path / "summary.json"
    clean = source_manifest()
    for before, after, unchanged in (
        (source_manifest(tracked_clean=False), source_manifest(tracked_clean=False), False),
        (clean, source_manifest(checksum="d" * 64), False),
        (clean, source_manifest(checksum="d" * 64), True),
        (source_manifest(untracked_code_files=1), source_manifest(untracked_code_files=1), True),
        ({}, {}, True),
    ):
        write(summary, {"source_before": before, "source_after": after, "source_unchanged": unchanged,
                        "backend": {"tests": 21, "passed": 21, "failed": 0, "skipped": 0}})
        actual = report.test_aggregate(summary, REV)
        assert actual["source_bound_for_report_revision"] is False
        assert actual["final_regression_certified"] is False
        assert actual["components"]["backend"]["passed"] == 21
        assert "not final regression evidence" in actual["scope"]


def test_docx_displays_mutable_source_and_qa_completion_with_only_whitelisted_fields(tmp_path):
    evidence = fixture(tmp_path)
    summary = tmp_path / "summary.json"
    dirty = source_manifest(tracked_clean=False)
    write(summary, {"source_before": dirty, "source_after": dirty, "source_unchanged": False,
                    "backend": {"tests": 21, "passed": 21, "failed": 0, "skipped": 0}})
    execution = {"revision": REV, "execution_status": "completed", "score": 8.5,
                 "passed": 10, "failed": 1, "skipped": 3, "unexecuted": 0,
                 "feature_count": 10, "checkpoints_total": 33, "checkpoints_passed": 10,
                 "open_defects": 1, "roles_observed": ["OFFICER", "PRIVATE-NAME"],
                 "dimensions": {"completion": 1, "PRIVATE-NAME": 2}}
    data = report.build_aggregate(evidence, REV, qa_execution=execution, test_summaries=[summary])
    assert data["ux"]["usability_estimate_score"] == 8.5
    assert data["ux"]["execution_completion"]["checkpoints_passed"] == 10
    docx = tmp_path / "result.docx"
    report.render_docx(data, docx)
    with zipfile.ZipFile(docx) as archive:
        xml = archive.read("word/document.xml").decode()
        assert "MUTABLE_SOURCE" in xml and "not final regression evidence" in xml
        assert "source unchanged=False" in xml and "Observed flows: 10; checkpoints: 10/33" in xml
        assert "PRIVATE-" not in xml


def test_staged_financial_report_preserves_counts_without_leaking_rows_or_promoting_old_runtime(tmp_path):
    evidence = fixture(tmp_path)
    checks = {name: True for name in report.staged_financial({}, REV)["checks"]}
    source = {"format": "volt-staging-financial-execution-v1", "execution_status": "completed",
              "revision": OLD, "runtime_kind": "ASGI", "production_mutated": False,
              "source_sha256": {kind: str(index) * 64 for index, kind in enumerate(("master", "invoice", "receipt"), 1)},
              "checks": checks, "counts": {"contracts_applied": 972, "served_case_errors": 0,
                  "customer_uid": "PRIVATE-CUSTOMER-UID"}, "totals": {"allocated": "100.10"},
              "customer_names": ["PRIVATE-CUSTOMER-NAME"], "raw_rows": [{"token": "PRIVATE-TOKEN"}]}
    write(evidence / "financial-execution.json", source)
    data = report.build_aggregate(evidence, REV)
    stage = data["financial"]["staging_execution"]
    assert stage["counts"]["contracts_applied"] == 972
    assert stage["totals"]["allocated"] == "100.10"
    assert stage["matching_report_revision"] is False
    assert stage["staged_workflow_verified_for_report_revision"] is False
    assert "PRIVATE-" not in json.dumps(stage)
    final = {**source, "revision": REV, "runtime_kind": "HTTP_IMAGE", "api_image": "sha256:" + "a" * 64}
    assert report.staged_financial(final, REV)["staged_workflow_verified_for_report_revision"] is False
    assert report.staged_financial(final, REV, expected_api_image=final["api_image"])["staged_workflow_verified_for_report_revision"] is True
    assert report.staged_financial(final, REV, expected_api_image="sha256:" + "b" * 64)["staged_workflow_verified_for_report_revision"] is False
    final["checks"]["operator_work_preserved"] = False
    assert report.staged_financial(final, REV, expected_api_image=final["api_image"])["staged_workflow_verified_for_report_revision"] is False


def test_wrong_revision_browser_does_not_promote_user_attestation(tmp_path):
    data = report.build_aggregate(fixture(tmp_path), REV, browser={"revision": OLD, "browser_login_performed": True,
        "authenticated_google_session": True, "authenticated_session_kind": "GOOGLE", "status": 200,
        "google_origin_denied": False, "target": "https://collection.volt.co.th", "failed_requests": [], "page_error_count": 0})
    assert data["google_login_status"] == "USER_ATTESTED_SUCCESS"


def test_docx_and_json_are_self_contained_aggregate_artifacts(tmp_path):
    output = tmp_path / "public"
    assert report.main(["--evidence-dir", str(fixture(tmp_path)), "--output-dir", str(output), "--revision", REV]) == 0
    with zipfile.ZipFile(output / "implementation-readiness-and-k6.docx") as archive:
        assert archive.testzip() is None
        xml = archive.read("word/document.xml").decode()
        assert "COLOCATED_PROVISIONAL" in xml and "FAIL / incomplete" in xml
        assert "PRIVATE-TOKEN" not in xml and "PRIVATE-CUSTOMER-NAME" not in xml
    assert json.loads((output / "implementation-aggregate.json").read_text())["deployment_certified"] is False


def passing_metrics(rules):
    return {name: {"values": {"p(95)" if name.endswith("_ms") else "count" if rule.startswith("count") else "rate":
                    100 if name.endswith("_ms") else 10 if rule.startswith("count") else 1 if name == "checks" else 0},
                   "thresholds": {rule: {"ok": True}}} for name, rule in rules.items()}


def test_approved_latency_policy_does_not_reinterpret_older_native_failures(tmp_path):
    evidence = fixture(tmp_path)
    prefix = evidence / 'diagnostic/results/k6-aaaaaaa-historical-25vu'
    metrics = passing_metrics(report.APPROVED_THRESHOLDS)
    for name in ('business_read_ms', 'business_write_ms'):
        metrics[name]['values']['p(95)'] = 2500
    write(Path(str(prefix) + '-summary.json'), {'metrics': metrics})
    write(Path(str(prefix) + '-meta.json'), {'revision': REV, 'api_image': 'sha256:' + 'd' * 64,
          'latency_policy': report.APPROVED_LATENCY_POLICY, 'latency_limit_ms': 3000,
          'process_return_code': 0, 'exit_code': 0, 'generator_co_located': True})
    runs = report.build_aggregate(evidence, REV)['k6']
    current = next(row for row in runs if row['revision'] == REV)
    prior = next(row for row in runs if row['revision'] == OLD)
    assert current['approved_thresholds_passed'] is True and current['original_thresholds_passed'] is None
    assert current['diagnostic_run_passed'] is True
    assert prior['native_exit_code'] == 99 and prior['original_thresholds_passed'] is False
    assert prior['latency_policy'] == 'legacy-2s' and prior['approved_thresholds_passed'] is None
    assert current['capacity_acceptance_certified'] is False


def test_import_failure_and_complete_action_failure_are_not_hidden_by_original_gates(tmp_path):
    evidence = fixture(tmp_path)
    metrics = {**passing_metrics(report.THRESHOLDS), **passing_metrics(report.SUPPLEMENTAL["debt-workflow"])}
    metrics["complete_action_ms"] = {"values": {"p(95)": 3000}, "thresholds": {"p(95)<2000": {"ok": False}}}
    prefix = evidence / "diagnostic/results/k6-aaaaaaa-debt-workflow-25vu-import"
    write(Path(str(prefix) + "-summary.json"), {"metrics": metrics})
    write(Path(str(prefix) + "-meta.json"), {"revision": REV, "api_image": "sha256:" + "d" * 64,
        "generator_co_located": True, "process_return_code": 0, "exit_code": 1,
        "concurrent_preview": {"profile": "debt_status", "started": True, "passed": False, "status": 429,
            "never_applied": True, "isolated_staging_only": True, "elapsed_ms": 120000, "tokens": "PRIVATE-TOKEN"}})
    run = next(run for run in report.build_aggregate(evidence, REV)["k6"] if run["scenario"] == "import")
    assert run["original_thresholds_passed"] is True
    assert run["supplemental_thresholds_passed"] is False and run["diagnostic_run_passed"] is False
    assert run["concurrent_preview"]["status"] == 429 and run["orchestration_exit_code"] == 1
    assert run["binding"] == "MATCHING_REPORT_REVISION" and run["api_image"] == "sha256:" + "d" * 64
    assert "PRIVATE-TOKEN" not in json.dumps(run)


def test_measured_old_image_binding_survives_new_runtime_and_dirty_revision_stays_unbound(tmp_path):
    evidence = fixture(tmp_path)
    write(evidence / "diagnostic/owned-resources.json", {"revision": REV, "api_image": "sha256:" + "d" * 64})
    prefix = evidence / "diagnostic/results/k6-bbbbbbb-historical-25vu-growth"
    write(Path(str(prefix) + "-summary.json"), {"metrics": passing_metrics(report.THRESHOLDS)})
    write(Path(str(prefix) + "-meta.json"), {"revision": OLD, "api_image": "sha256:" + "c" * 64,
        "generator_co_located": True, "process_return_code": 0, "exit_code": 0,
        "duration_seconds": 120, "dataset": {"customers": 1431, "contracts": 1431, "instalments_per_contract": 96}})
    prefix2 = evidence / "diagnostic/results/k6-aaaaaaa-historical-25vu-soak"
    write(Path(str(prefix2) + "-summary.json"), {"metrics": passing_metrics(report.THRESHOLDS)})
    write(Path(str(prefix2) + "-meta.json"), {"revision": None, "api_image": "sha256:" + "e" * 64,
        "generator_co_located": True, "process_return_code": 0, "exit_code": 0, "duration_seconds": 900})
    runs = report.build_aggregate(evidence, REV)["k6"]
    growth = next(run for run in runs if run["scenario"] == "growth")
    soak = next(run for run in runs if run["scenario"] == "soak")
    assert growth["binding"] == "OLDER_REVISION" and growth["api_image"] == "sha256:" + "c" * 64
    assert growth["dataset"]["customers"] == 1431 and growth["diagnostic_run_passed"] is True
    assert soak["binding"] == "UNBOUND" and soak["duration_seconds"] == 900


def test_paged_original_success_requires_its_native_page_gates(tmp_path):
    evidence = fixture(tmp_path)
    prefix = evidence / "diagnostic/results/k6-aaaaaaa-paged-25vu"
    write(Path(str(prefix) + "-summary.json"), {"metrics": passing_metrics(report.THRESHOLDS)})
    write(Path(str(prefix) + "-meta.json"), {"revision": REV, "api_image": "sha256:" + "d" * 64,
        "generator_co_located": True, "process_return_code": 0, "exit_code": 0})
    run = next(run for run in report.build_aggregate(evidence, REV)["k6"] if run["profile"] == "paged")
    assert run["original_thresholds_passed"] is True
    assert run["supplemental_thresholds_passed"] is False and run["diagnostic_run_passed"] is False


def test_host_guard_abort_is_visible_even_with_passing_native_metrics(tmp_path):
    evidence = fixture(tmp_path)
    prefix = evidence / "diagnostic/results/k6-aaaaaaa-historical-25vu"
    write(Path(str(prefix) + "-summary.json"), {"metrics": passing_metrics(report.THRESHOLDS)})
    write(Path(str(prefix) + "-meta.json"), {"revision": REV, "api_image": "sha256:" + "d" * 64,
        "generator_co_located": True, "process_return_code": 0, "exit_code": 0,
        "production_health_guard": {"enabled": True, "baseline_passed": True, "aborted": True,
            "reason": "production_health", "samples": [{"raw_response": "PRIVATE-TOKEN"}], "notes": "PRIVATE-NOTE"}})
    run = next(run for run in report.build_aggregate(evidence, REV)["k6"] if run["binding"] == "MATCHING_REPORT_REVISION")
    assert run["original_thresholds_passed"] is True and run["diagnostic_run_passed"] is False
    assert run["production_health_guard"]["reason"] == "production_health"
    assert "PRIVATE-TOKEN" not in json.dumps(run) and "PRIVATE-NOTE" not in json.dumps(run)
