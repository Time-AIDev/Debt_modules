"""Pre-install: the card comes with its case, evidence passes the gate, and the
customer's own page is where the work finishes (2026-09-20).

The team asked for one place to finish pre-install work. These pin the four claims
that make that true: a card opens a case that is not on the book until released,
the case page serves the annotated conditions, attaching a slip passes the gate it
belongs to and lands on the case timeline, and removing the last slip reopens only
the gate the evidence itself passed.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import journey
from app.config import settings
from app.main import app

BD = settings.business_date
OFFICER = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _unreleased(client):
    rows = client.get("/v1/pipeline?all=true").json()["items"]
    return next(r for r in rows if not r["released_at"])


def test_a_card_opens_its_case_but_it_is_not_on_the_book_until_released(client):
    item = _unreleased(client)
    case = cases_domain.for_current().cases.get(item["customer_uid"])
    assert case is not None, "the card and its case are opened together"
    assert case["opened_from"] == "PRE_INSTALL_CARD"
    assert case["pipeline_uid"] == item["uid"]
    assert case["pipeline_released"] is False
    assert case["next_action"] is None, "no next action before anything is released"
    assert cases_domain.is_book_case(case) is False

    # The team's own count excludes it: the report's denominator is the book, not
    # pipeline work.
    team = client.get("/v1/reports/team").json()["team"]
    book = [c for c in cases_domain.for_current().cases.values() if cases_domain.is_book_case(c)]
    assert team["cases_total"] == len(book)


def test_the_case_page_serves_the_annotated_pre_install_card(client):
    item = _unreleased(client)
    body = client.get("/v1/cases/by-customer/%s" % item["customer_uid"]).json()
    assert body["pre_install"] is True
    assert body["pipeline_item"]["uid"] == item["uid"]
    assert [c["key"] for c in body["pipeline_item"]["conditions"]] == \
        ["contract_signed", "down_payment", "entity_resolved"]
    assert body["pipeline_meta"]["invoice_owner_role"]
    assert body["case"]["opened_from"] == "PRE_INSTALL_CARD"


def test_a_down_payment_slip_passes_the_gate_fills_the_amount_and_logs_the_case(client):
    item = _unreleased(client)
    uid = item["uid"]
    made = client.post("/v1/pipeline/%s/conditions/down_payment/evidence" % uid,
                       json={"note": "สลิปโอนเงินดาวน์", "amount": "5000.00", "by": "thip"})
    assert made.status_code == 201, made.json()
    row = made.json()["item"]
    assert row["gate_down_payment"]["state"] == "PASSED"
    assert row["gate_down_payment"]["ref"] == "EVIDENCE:%s" % made.json()["evidence"]["uid"]
    assert row["gate_down_payment"]["source"] == "EVIDENCE"
    assert row["amount_due"] == "5000.00"
    assert next(c for c in row["conditions"] if c["key"] == "down_payment")["state"] == "PASSED"

    detail = client.get("/v1/cases/by-customer/%s" % item["customer_uid"]).json()
    kinds = [e["kind"] for e in detail["events"]]
    assert "CONDITION_EVIDENCE_ATTACHED" in kinds


def test_removing_the_last_slip_reopens_the_gate_it_passed(client):
    item = _unreleased(client)
    uid = item["uid"]
    made = client.post("/v1/pipeline/%s/conditions/down_payment/evidence" % uid,
                       json={"note": "สลิปโอนเงินดาวน์", "by": "thip"})
    evidence_uid = made.json()["evidence"]["uid"]
    assert made.json()["item"]["gate_down_payment"]["state"] == "PASSED"

    removed = client.post("/v1/pipeline/%s/conditions/down_payment/evidence/%s:remove"
                          % (uid, evidence_uid), json={"by": "thip"})
    assert removed.status_code == 200, removed.json()
    row = removed.json()["item"]
    assert row["gate_down_payment"]["state"] == "OPEN"
    assert next(c for c in row["conditions"] if c["key"] == "down_payment")["state"] == "OPEN"
    assert "GATE_REOPENED" in [h["act"] for h in row["history"]]
    detail = client.get("/v1/cases/by-customer/%s" % item["customer_uid"]).json()
    assert "CONDITION_EVIDENCE_REMOVED" in [e["kind"] for e in detail["events"]]


def test_a_gate_a_person_passed_is_not_reopened_by_evidence_removal(client):
    item = _unreleased(client)
    uid = item["uid"]
    assert client.post("/v1/pipeline/%s/gates/down-payment" % uid,
                       json={"slip_ref": "slip-from-contract", "by": "thip"}).status_code == 200
    made = client.post("/v1/pipeline/%s/conditions/down_payment/evidence" % uid,
                       json={"note": "สำเนาสลิป", "by": "thip"})
    evidence_uid = made.json()["evidence"]["uid"]
    removed = client.post("/v1/pipeline/%s/conditions/down_payment/evidence/%s:remove"
                          % (uid, evidence_uid), json={"by": "thip"}).json()["item"]
    assert removed["gate_down_payment"]["state"] == "PASSED"
    assert removed["gate_down_payment"]["ref"] == "slip-from-contract", "a person's gate is theirs"


def test_release_marks_the_case_released_and_it_starts_counting(client):
    item = _unreleased(client)
    uid = item["uid"]
    assert client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"}).status_code == 201
    assert client.post("/v1/pipeline/%s/conditions/down_payment/evidence" % uid,
                       json={"note": "สลิปโอนเงินดาวน์", "amount": "5000.00", "by": "thip"}).status_code == 201
    released = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"}, headers=OFFICER)
    assert released.status_code == 201, released.json()

    case = cases_domain.for_current().cases[item["customer_uid"]]
    assert case["pipeline_released"] is True
    assert cases_domain.is_book_case(case) is True
    assert case["next_action"] == "SEND_INVOICE_LINK" and case["next_action_on"] == str(BD)
    body = client.get("/v1/cases/by-customer/%s" % item["customer_uid"]).json()
    assert "INVOICE_RELEASED" in [e["kind"] for e in body["events"]]


def test_removing_evidence_releases_its_stored_file(client):
    from tests.test_attachments_guard import _png
    item = _unreleased(client)
    uid = item["uid"]
    scope = "pipeline:%s:condition:contract_signed" % uid
    uploaded = client.post("/v1/attachments", content=_png(),
                           headers={"X-Volt-Role": "OFFICER", "X-Volt-Officer": "thip",
                                    "X-Volt-Filename": "contract.png",
                                    "Content-Type": "application/octet-stream"})
    assert uploaded.status_code == 201, uploaded.json()
    file_uid = uploaded.json()["attachment"]["uid"]
    made = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "ไฟล์สัญญา", "file_uid": file_uid, "by": "thip"})
    assert made.status_code == 201, made.json()
    assert [a["uid"] for a in client.get("/v1/attachments", params={"attached_to": scope})
            .json()["attachments"]] == [file_uid]

    evidence_uid = made.json()["evidence"]["uid"]
    assert client.post("/v1/pipeline/%s/conditions/contract_signed/evidence/%s:remove"
                       % (uid, evidence_uid), json={"by": "thip"}).status_code == 200
    assert client.get("/v1/attachments", params={"attached_to": scope}).json()["attachments"] == []
    # The file is free to back another scope now, rather than stuck forever.
    again = client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                        json={"note": "แนบใหม่", "file_uid": file_uid, "by": "thip"})
    assert again.status_code == 201, again.json()


def test_an_identity_with_no_card_still_opens_as_an_identity(client):
    cs = cases_domain.for_current()
    identity = next(c for c in journey.identity_customers() if c.uid not in cs.cases)
    body = client.get("/v1/cases/by-customer/%s" % identity.uid).json()
    assert body["identity_only"] is True and body["case"] is None


def test_a_released_case_carries_the_release_date_as_its_first_action(client):
    # `next_action_on` is the release date, not the planned install date, so a moved
    # install date cannot silently change an already-released case's reminder.
    item = _unreleased(client)
    uid = item["uid"]
    client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                json={"note": "สัญญา", "by": "thip"})
    client.post("/v1/pipeline/%s/conditions/down_payment/evidence" % uid,
                json={"note": "สลิป", "amount": "5000.00", "by": "thip"})
    assert client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"}, headers=OFFICER).status_code == 201
    case = cases_domain.for_current().cases[item["customer_uid"]]
    assert case["next_action_on"] == str(BD)
    assert str(BD - timedelta(days=1)) not in str(case["next_action_on"])
