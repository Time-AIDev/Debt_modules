"""A recovery can be opened on every NPL row GET /v1/npl-cases serves.

J-47 widened the list to every case whose payment_status is NPL — the sheet's four NPL
customers among them — but POST /v1/npl-cases/{uid}/recovery kept looking only in the
demo declarations. So the Recovery tab offered four "open a recovery case" buttons on
each sheet customer and every one answered 404, while SOP step 16 (sop.py) sent the
officer to exactly that act. The list and the act now read the same rows.

A payment-status row's uid is its customer-level case uid; the recovery records it as
`source_ref`, the same field a declaration's or a cash case's recovery already uses.
Opening one declares nothing: no journey case, no NPL declaration, no contract status.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
# Opening a recovery is MANAGER+ (fix-all Leg R); the officer id is made up.
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "mgr-test"}


def _rows():
    return client.get("/v1/npl-cases").json()["npl_cases"]


def _payment_status_row():
    return next(r for r in _rows() if r.get("origin") == "PAYMENT_STATUS" and not r["recovery_uid"])


def test_a_payment_status_npl_row_can_open_a_recovery():
    row = _payment_status_row()
    r = client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "LEGAL"}, headers=MANAGER)
    assert r.status_code == 201, r.json()
    rec = r.json()["recovery"]
    assert rec["strategy"] == "LEGAL"
    assert rec["status"] == "IN_PROGRESS"
    assert rec["contract_uid"] == row["contract_uid"]
    assert rec["source_ref"] == row["uid"]
    assert r.json()["lot"] is None


def test_the_list_row_then_carries_the_recovery_it_opened():
    row = _payment_status_row()
    rec = client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "COOP_DECOMMISSION"}, headers=MANAGER).json()["recovery"]
    again = next(r for r in _rows() if r["uid"] == row["uid"])
    assert again["recovery_uid"] == rec["uid"]
    listed = client.get("/v1/recovery-cases").json()["recovery_cases"]
    assert rec["uid"] in {x["uid"] for x in listed}


def test_repossession_on_a_payment_status_row_plans_its_lot():
    row = _payment_status_row()
    body = client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "REPOSSESSION"}, headers=MANAGER).json()
    lot = body["lot"]
    assert lot["recovery_uid"] == body["recovery"]["uid"]
    assert lot["contract_uid"] == row["contract_uid"]
    assert lot["status"] == "PLANNED"


def test_a_second_recovery_on_the_same_row_is_refused_like_a_declared_one():
    row = _payment_status_row()
    first = client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "LEGAL"}, headers=MANAGER)
    assert first.status_code == 201
    second = client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "LEGAL"}, headers=MANAGER)
    assert second.status_code == 409
    assert second.json()["code"] == "review_already_decided"
    assert len([x for x in client.get("/v1/recovery-cases").json()["recovery_cases"]
                if x["source_ref"] == row["uid"]]) == 1


def test_an_unknown_strategy_is_still_named_before_anything_is_opened():
    row = _payment_status_row()
    r = client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "PRAYER"}, headers=MANAGER)
    assert r.status_code == 422
    assert next(x for x in _rows() if x["uid"] == row["uid"])["recovery_uid"] is None


def test_opening_a_recovery_declares_nothing():
    row = _payment_status_row()
    journey_cases = client.get("/v1/cases").json()["cases"]
    client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "LEGAL"}, headers=MANAGER)
    assert client.get("/v1/cases").json()["cases"] == journey_cases
    again = next(r for r in _rows() if r["uid"] == row["uid"])
    assert again["origin"] == "PAYMENT_STATUS"
    assert again["declared_on"] is None and again["declared_by"] is None


def test_a_case_that_is_not_npl_is_still_not_found():
    from app import cases as cases_domain
    not_npl = next(c for c in cases_domain.for_current().cases.values() if c["payment_status"] != "NPL")
    r = client.post("/v1/npl-cases/%s/recovery" % not_npl["uid"], json={"strategy": "LEGAL"}, headers=MANAGER)
    assert r.status_code == 404
    assert client.post("/v1/npl-cases/nothing-here/recovery", json={"strategy": "LEGAL"}).status_code == 404


def test_a_declared_row_still_opens_as_before():
    declared = next(r for r in _rows() if r.get("origin") != "PAYMENT_STATUS" and not r["recovery_uid"])
    r = client.post("/v1/npl-cases/%s/recovery" % declared["uid"], json={"strategy": "LEGAL"}, headers=MANAGER)
    assert r.status_code == 201
    assert r.json()["recovery"]["source_ref"] == declared["uid"]
    assert next(x for x in _rows() if x["uid"] == declared["uid"])["recovery_uid"] == r.json()["recovery"]["uid"]


# --- fix-all Leg R: the open is a Manager's act, signed and explained ---------------

def _latest_audit():
    from app import audit_store
    return audit_store.read({}, limit=1, before_seq=None)[0]


def test_an_officer_is_refused_even_with_a_manager_body_and_nothing_opens():
    row = _payment_status_row()
    before = len(client.get("/v1/recovery-cases").json()["recovery_cases"])
    r = client.post("/v1/npl-cases/%s/recovery" % row["uid"],
                    json={"strategy": "LEGAL", "role": "MANAGER"},
                    headers={"X-Volt-Role": "OFFICER", "X-Volt-Officer": "officer-test"})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert len(client.get("/v1/recovery-cases").json()["recovery_cases"]) == before
    assert next(x for x in _rows() if x["uid"] == row["uid"])["recovery_uid"] is None


def test_the_record_and_the_audit_row_carry_who_opened_it_and_why():
    row = _payment_status_row()
    r = client.post("/v1/npl-cases/%s/recovery" % row["uid"],
                    json={"strategy": "LEGAL", "reason": "ลูกค้าไม่ตอบรับการเจรจา"}, headers=MANAGER)
    assert r.status_code == 201, r.json()
    rec = r.json()["recovery"]
    assert rec["opened_by"] == "mgr-test"            # the X-Volt-Officer header, no body `by`
    assert rec["opened_reason"] == "ลูกค้าไม่ตอบรับการเจรจา"
    from app.config import settings
    assert rec["opened_on"] == str(settings.business_date)
    entry = _latest_audit()
    assert entry["act"] == "RECOVERY_OPENED"
    assert entry["detail"] == {"strategy": "LEGAL", "reason": "ลูกค้าไม่ตอบรับการเจรจา",
                               "role": "MANAGER", "recovery_uid": rec["uid"]}
    by_body = client.post("/v1/npl-cases/%s/recovery" % _payment_status_row()["uid"],
                          json={"strategy": "LEGAL", "by": "mgr-body"}, headers=MANAGER)
    assert by_body.json()["recovery"]["opened_by"] == "mgr-body"


def test_after_a_strategy_change_the_row_serves_the_new_recovery_and_still_refuses_a_second_open():
    row = _payment_status_row()
    first = client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "LEGAL"},
                        headers=MANAGER).json()["recovery"]
    changed = client.post("/v1/recovery-cases/%s:change-strategy" % first["uid"], headers=MANAGER,
                          json={"strategy": "REPOSSESSION", "reason": "ลูกค้ายินยอมให้ถอดระบบ"})
    assert changed.status_code == 200, changed.json()
    new = changed.json()["recovery"]
    again = next(r for r in _rows() if r["uid"] == row["uid"])
    assert again["recovery_uid"] == new["uid"] and again["strategy"] == "REPOSSESSION"
    second = client.post("/v1/npl-cases/%s/recovery" % row["uid"], json={"strategy": "LEGAL"}, headers=MANAGER)
    assert second.status_code == 409 and second.json()["code"] == "review_already_decided"
