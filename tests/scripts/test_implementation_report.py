"""Public reports discard sensitive source fields and never inflate acceptance."""
import importlib.util
import json
from pathlib import Path
import sys
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
