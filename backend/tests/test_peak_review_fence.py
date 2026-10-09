"""The review fence on a staged PEAK run — ADDITIONS to the conflict routes.

Four answers the fence needs around it: re-check a staged run against the version
that stands now (its repair, instead of a re-upload the duplicate refusal would
turn away), see what committed after the review was made, one decision for every
undecided field at once, and a manager's forced confirm — role-gated, reason-named
and carrying no fence of its own. The fence's own refusal
(state_conflict / preview_stale, 409 DEBT-PRD-001) is production-mode and is
tested in test_upload_operational.py.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import audit_store, db, landing, migrate
from app.book import SHEET
from app.main import app
from app.pipelines import field_decisions, peak_links, peak_writer
from tests.test_peak_router import _exact, _inv, _parsed

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


def _book_customer_no():
    from app import journey
    return next(c.customer_no for c in journey.book_customers() if c.data_source == SHEET and c.contracts)


def _identity(no):
    return {"name_th": "สมชาย ธรรมดี", "name_roman": "Somchai Tamdee", "volt_id": "VL0010158_head",
            "customer_no": no, "product": "LEASE", "order": {"watt": "5000"}}


def _staged(conn, doc, code, no):
    """One staged (OK, not applied) invoice run matched to `no`, with an identity
    that disagrees — the review tabs have something to decide."""
    written = peak_writer.write(conn, _parsed(_inv(doc, code)),
                                [dict(_exact(no), rule="LINK")],
                                door="upload", filename="export_as_of_20240101_20260914.xlsx",
                                identities={str(no): _identity(no)})
    conn.commit()
    return written


@pytest.fixture
def db_env(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        yield pg_conn
    finally:
        pg_conn.execute(text("delete from records.field_decision"))
        pg_conn.execute(text("delete from records.identity_link"))
        pg_conn.commit()


def _current_version(conn):
    return str(conn.execute(text("select version from app.business_version where singleton")).scalar_one())


# --- the re-check: the fence's honest repair -----------------------------------------

def test_recheck_re_binds_a_staged_run_to_the_version_that_stands_now(db_env):
    conn = db_env
    no = _book_customer_no()
    peak_links.confirm(conn, "VC-RECHECK-1", no, by="settasak")
    written = _staged(conn, "IVT-90200", "VC-RECHECK-1", no)

    r = client.post("/v1/pipelines/peak-report/landing-runs/%d:recheck" % written["run_id"], headers=OFFICER)
    assert r.status_code == 200, r.text
    version = r.json()["review_state_version"]
    assert version == _current_version(conn)

    meta = landing.get_run(conn, written["run_id"])["meta"]
    assert meta["review_state_version"] == version
    assert meta["review_state_version_at"], "the re-check also stamps when, so changes can be read"
    entry = audit_store.read({"act": "PEAK_RUN_RECHECKED"}, limit=1, before_seq=None)[0]
    assert entry["subject_uid"] == str(written["run_id"])
    assert entry["detail"]["review_state_version"] == version


def test_recheck_refuses_a_run_that_is_absent_applied_or_another_kind(db_env):
    conn = db_env
    no = _book_customer_no()
    peak_links.confirm(conn, "VC-RECHECK-2", no, by="settasak")
    written = _staged(conn, "IVT-90201", "VC-RECHECK-2", no)

    missing = client.post("/v1/pipelines/peak-report/landing-runs/9999999:recheck", headers=OFFICER)
    assert missing.status_code == 404

    # The receipt door's run is a different source_system: not its re-check.
    other = client.post("/v1/pipelines/peak-receipt/landing-runs/%d:recheck" % written["run_id"], headers=OFFICER)
    assert other.status_code == 404

    peak_writer.apply_run(conn, written["run_id"], by="settasak")
    conn.commit()
    applied = client.post("/v1/pipelines/peak-report/landing-runs/%d:recheck" % written["run_id"], headers=OFFICER)
    assert applied.status_code == 409 and applied.json()["code"] == "run_not_staged"
    assert applied.json()["message_th"]


def test_the_receipt_report_has_its_own_recheck(db_env):
    conn = db_env
    written = peak_writer.write_receipts(
        conn, {"report_as_of": "2026-09-14", "receipts": []},
        [], door="upload", filename="receipts_as_of_20260914.xlsx")
    conn.commit()
    r = client.post("/v1/pipelines/peak-receipt/landing-runs/%d:recheck" % written["run_id"], headers=OFFICER)
    assert r.status_code == 200, r.text
    assert r.json()["review_state_version"] == _current_version(conn)
    # The invoice door's re-check does not take the receipt run.
    wrong = client.post("/v1/pipelines/peak-report/landing-runs/%d:recheck" % written["run_id"], headers=OFFICER)
    assert wrong.status_code == 404


# --- what changed since the review ----------------------------------------------------

def test_changes_serve_what_committed_after_the_fence_and_skip_the_runs_own_acts(db_env):
    conn = db_env
    no = _book_customer_no()
    peak_links.confirm(conn, "VC-CHANGES-1", no, by="settasak")
    written = _staged(conn, "IVT-90210", "VC-CHANGES-1", no)
    client.post("/v1/pipelines/peak-report/landing-runs/%d:recheck" % written["run_id"], headers=OFFICER)

    # One committed act and one refused act after the fence; a refused act changed
    # nothing, so it is not "what changed".
    audit_store.append({"act": "PEAK_LINK_CONFIRMED", "subject_type": "customer",
                        "subject_uid": "sheet-%s" % no, "detail": {"contact_code": "VC-CHANGES-1"}})
    audit_store.append({"act": "CASE_NOTE_ADDED", "subject_type": "customer", "subject_uid": "case-other"})
    audit_store.append({"act": "PEAK_DOCUMENT_RESUBMITTED", "subject_type": "peak_document",
                        "subject_uid": "pkd-1", "outcome": "REFUSED", "status": 409})
    conn.commit()

    r = client.get("/v1/pipelines/peak-report/landing-runs/%d/changes" % written["run_id"])
    assert r.status_code == 200, r.text
    body = r.json()
    acts = {row["act"] for row in body["rows"]}
    assert "PEAK_LINK_CONFIRMED" in acts and "CASE_NOTE_ADDED" in acts
    assert "PEAK_DOCUMENT_RESUBMITTED" not in acts, "a refused act changed nothing"
    # The run's own staging/re-check rows are its lifecycle, not "what changed".
    assert "PEAK_RUN_RECHECKED" not in acts
    assert body["since"] and body["review_state_version"] == _current_version(conn)
    link = next(row for row in body["rows"] if row["act"] == "PEAK_LINK_CONFIRMED")
    assert link["subject_uid"] == "sheet-%s" % no and link["actor"] == "nantapol"
    assert link["actor_role"] == "OFFICER" and link["route"] is not None


def test_changes_of_an_unknown_run_is_a_404(db_env):
    assert client.get("/v1/pipelines/peak-report/landing-runs/9999999/changes").status_code == 404


# --- one decision for every field ------------------------------------------------------

def test_decide_all_takes_one_source_for_every_undecided_field_and_never_volt_id(db_env):
    conn = db_env
    no = _book_customer_no()
    peak_links.confirm(conn, "VC-ALL-1", no, by="settasak")
    written = _staged(conn, "IVT-90220", "VC-ALL-1", no)
    undecided = {c["field"] for c in peak_writer.conflict_rows(conn, written["run_id"])[0]["conflicts"]
                 if not c.get("same")}
    assert "customer_name" in undecided

    r = client.post("/v1/pipelines/peak-report/landing-runs/%d/conflicts:decide-all" % written["run_id"],
                    headers=OFFICER, json={"source": "PEAK", "reason": "the sheet's spelling is wrong"})
    assert r.status_code == 200, r.text
    assert r.json()["decisions"] == len(undecided - {"volt_id"})
    assert r.json()["customers"] >= 1
    loaded = field_decisions.load(conn)[no]
    for field in undecided - {"volt_id"}:
        assert loaded[field]["chosen_source"] == "PEAK"
        assert loaded[field]["decided_by"] == "nantapol"
        assert loaded[field]["reason"] == "the sheet's spelling is wrong"
    assert "volt_id" not in loaded, "only a person decides volt_id"


def test_decide_all_keeps_a_persons_decision_and_is_empty_the_second_time(db_env):
    conn = db_env
    no = _book_customer_no()
    peak_links.confirm(conn, "VC-ALL-2", no, by="settasak")
    written = _staged(conn, "IVT-90221", "VC-ALL-2", no)
    field_decisions.decide(conn, no, "product", "ODOO", by="settasak", reason="checked by hand")
    conn.commit()

    r = client.post("/v1/pipelines/peak-report/landing-runs/%d/conflicts:decide-all" % written["run_id"],
                    headers=OFFICER, json={"source": "PEAK"})
    assert r.status_code == 200, r.text
    loaded = field_decisions.load(conn)[no]
    assert loaded["product"]["chosen_source"] == "ODOO", "a person's own decision stays"
    assert loaded["customer_name"]["chosen_source"] == "PEAK"
    assert "volt_id" not in loaded, "only a person decides volt_id"

    again = client.post("/v1/pipelines/peak-report/landing-runs/%d/conflicts:decide-all" % written["run_id"],
                        headers=OFFICER, json={"source": "PEAK"})
    assert again.status_code == 200
    assert again.json()["decisions"] == 0


def test_decide_all_refuses_an_unknown_source(db_env):
    conn = db_env
    no = _book_customer_no()
    written = _staged(conn, "IVT-90222", no, no)
    bad = client.post("/v1/pipelines/peak-report/landing-runs/%d/conflicts:decide-all" % written["run_id"],
                      headers=OFFICER, json={"source": "WHOEVER"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/source"
    assert field_decisions.load(conn) == {}
