"""Round-1 blind UAT, P3 findings (2026-09-02) — one regression per judge item.

Every test goes through the HTTP surface with the session cookie the middleware
issues, exactly as the interface does, so a fix that works only in the shared
slot cannot pass here.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import peak_documents as pkd
from app.config import settings
from app.main import app

BD = settings.business_date
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "jo"}


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def stub():
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    yield pkd.TRANSPORT_OVERRIDE
    pkd.TRANSPORT_OVERRIDE = None


def _today_items(client):
    return client.get("/v1/today").json()["items"]


def _counting_contact(client, customer_uid, at="2026-10-23T09:10:00+07:00"):
    return client.post("/v1/contacts", json={"customer_uid": customer_uid, "channel": "PHONE", "direction": "OUTBOUND",
                                             "disposition": "ANS_DISCUSSED", "at": at})


def _released_item(client):
    """Gates passed, released, approved in PEAK — the delivery-ready pipeline row."""
    items = client.get("/v1/pipeline?all=true").json()["items"]
    uid = next(i for i in items if i["entity"] and i["amount_due"])["uid"]
    assert client.post("/v1/pipeline/%s/gates/down-payment" % uid, json={"slip_ref": "slip-p3", "by": "thip"}).status_code == 200
    assert client.post("/v1/pipeline/%s/gates/epc-confirmed" % uid, json={"confirmed_on": str(BD + timedelta(days=2)), "source": "ODOO"}).status_code == 200
    # Delta-100 D2h: the third condition, contract signed, passes by evidence only.
    assert client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"}).status_code == 201
    r = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"})
    assert r.status_code == 201, r.json()
    doc_uid = r.json()["peak_document"]["uid"]
    assert client.post("/v1/peak-documents/%s:refresh" % doc_uid).json()["document"]["state"] == "APPROVED_IN_PEAK"
    return uid, doc_uid


# --- J-04 ---------------------------------------------------------------------------

def test_j04_contact_locked_names_the_way_through(client):
    items = [i for i in _today_items(client) if not i["case"]["open_ptp"]]
    with_ptp, without = items[0], items[1]
    # every sheet promise has already broken on the business date, so open one on the first case
    r = client.post("/v1/cases/by-customer/%s/contacts" % with_ptp["customer"]["uid"],
                    json={"result": "INBOUND", "counted": False, "ptp": {"amount": "1000", "date": str(BD + timedelta(days=1))}})
    assert r.status_code == 201 and r.json()["case"]["open_ptp_uid"]
    for item in (with_ptp, without):
        assert _counting_contact(client, item["customer"]["uid"]).status_code == 201
    locked = _counting_contact(client, with_ptp["customer"]["uid"], at="2026-10-23T15:00:00+07:00")
    assert locked.status_code == 409 and locked.json()["code"] == "contact_locked"
    codes = [a["code"] for a in locked.json()["extensions"]["alternatives"]]
    # Round-4 J4-02: the honest second-contact route joins the list, so the way through
    # is no longer "write that the customer called you".
    assert codes == ["INBOUND_NOT_COUNTED", "SECOND_CONTACT_NOT_COUNTED", "RENEGOTIATE_OPEN_PTP"]
    assert all(_thai(a["label_th"]) for a in locked.json()["extensions"]["alternatives"])
    assert "ทางเลือกที่ยังทำได้" in locked.json()["message_th"]
    locked = _counting_contact(client, without["customer"]["uid"], at="2026-10-23T15:00:00+07:00")
    assert [a["code"] for a in locked.json()["extensions"]["alternatives"]] == [
        "INBOUND_NOT_COUNTED", "SECOND_CONTACT_NOT_COUNTED"]


# --- J-12a --------------------------------------------------------------------------

def test_j12a_every_review_carries_question_th_and_system_reviews_are_thai(client):
    reviews = client.get("/v1/reviews").json()["reviews"]
    assert reviews
    for r in reviews:
        assert r["question_th"] is not None and "question_th" in r
        if r["raised_by"] == "SYSTEM":
            assert _thai(r["question"]) and _thai(r["question_th"]), r["question"]
    # the renegotiation escalation (cases.py) is Thai too
    item = next(i for i in _today_items(client) if not i["case"]["open_ptp"] and not i["case"]["review_uid"])
    uid = item["customer"]["uid"]
    for n in range(3):
        ptp = client.post("/v1/cases/by-customer/%s/contacts" % uid, json={"result": "INBOUND", "counted": False,
                          "ptp": {"amount": "1000", "date": str(BD + timedelta(days=1))}}).json()["ptp"]
        client.post("/v1/case-ptps/%s:close" % ptp["uid"], json={"outcome": "BROKEN"})
    case = client.post("/v1/cases/by-customer/%s/contacts" % uid, json={"result": "INBOUND", "counted": False,
                       "ptp": {"amount": "1000", "date": str(BD + timedelta(days=2))}}).json()["case"]
    review = next(r for r in client.get("/v1/reviews").json()["reviews"] if r["uid"] == case["review_uid"])
    assert review["reason"] == "REPEATED_BROKEN_PTP" and _thai(review["question"]) and review["question_en"]


# --- J-12b --------------------------------------------------------------------------

def test_j12b_manager_review_open_counts_case_reviews(client):
    item = next(i for i in _today_items(client) if not i["case"]["review_uid"] and i["manager_review_open"] == 0)
    uid = item["customer"]["uid"]
    r = client.post("/v1/cases/by-customer/%s/review-requests" % uid, json={"reason": "OTHER", "question": "ขอคำแนะนำ"})
    assert r.status_code == 201
    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    assert detail["work_item"]["manager_review_open"] == 1
    today = next(i for i in _today_items(client) if i["customer"]["uid"] == uid)
    assert today["manager_review_open"] == 1


# --- J-12c --------------------------------------------------------------------------

def test_j12c_the_daily_lock_is_per_session():
    a, b = TestClient(app), TestClient(app)
    uid = a.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    assert _counting_contact(a, uid).status_code == 201
    assert _counting_contact(b, uid).status_code == 201, "a fresh browser profile is a fresh world"
    assert _counting_contact(a, uid, at="2026-10-23T15:00:00+07:00").status_code == 409
    assert a.get("/v1/today").json()["items"] != [] and \
        next(i for i in b.get("/v1/today").json()["items"] if i["customer"]["uid"] == uid)["contact_lock"]["state"] == "LOCKED"


# --- J-13 ---------------------------------------------------------------------------

def test_j13_closing_a_ticket_needs_a_resolution_note_and_records_who_closed(client):
    item = next(i for i in _today_items(client) if not i["case"]["open_issue"] and i["case"]["payment_status"] == "LATE")
    uid = item["customer"]["uid"]
    r = client.post("/v1/cases/by-customer/%s/contacts" % uid, json={
        "result": "SERVICE_ISSUE", "counted": True, "amount_stated": True,
        "issue": {"summary": "อินเวอร์เตอร์ดับ", "responsible_team": "O_AND_M", "ticket_url": "https://odoo.volt.co.th/odoo/helpdesk-tickets/77"}})
    issue = r.json()["issue"]
    # Round-2 N2-07 / T2-08: the workflow freezes the fee and the DPD clock while a ticket is open.
    assert issue["fee_clock"] == "PAUSED" and _thai(issue["fee_clock_note_th"])
    refused = client.post("/v1/case-issues/%s:close" % issue["uid"], json={}, headers={"X-Volt-Officer": "nantapol"})
    assert refused.status_code == 422 and refused.json()["code"] == "resolution_note_required" and _thai(refused.json()["message_th"])
    closed = client.post("/v1/case-issues/%s:close" % issue["uid"], json={"resolution_note": "O&M เปลี่ยนอินเวอร์เตอร์แล้ว"},
                         headers={"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"})
    assert closed.status_code == 200
    assert closed.json()["issue"]["closed_by"] == "nantapol" and closed.json()["issue"]["resolution_note"].startswith("O&M")
    waiting = next(i for i in _today_items(client) if i["customer"]["uid"] == uid)["waiting"]
    ticket = next(w for w in waiting if w["kind"] == "TICKET_CLOSED")
    assert _thai(ticket["text"]) and ticket["text_th"] == ticket["text"] and ticket["text_en"] == "ticket closed, resume follow-up"


# --- J-15 ---------------------------------------------------------------------------

def test_j15_review_age_is_never_negative(client):
    reviews = client.get("/v1/reviews").json()["reviews"]
    assert reviews
    for r in reviews:
        assert r["age_hours"] is not None and r["age_hours"] >= 0
        assert r["raised_at_time"].startswith(str(BD)) and "T" in r["raised_at_time"]


# --- J-18 ---------------------------------------------------------------------------

def test_j18_pipeline_meta_counts_late_today_upcoming(client):
    body = client.get("/v1/pipeline").json()
    counts = body["meta"]["counts"]
    # J2-26 (round-2 judge): "beyond" and "window_days" joined the block so the
    # heading can never count an out-of-window row as "within N days".
    # Round-3 J3-10: `beyond` is now counted over the WHOLE BOOK (it was structurally 0
    # in the default view), so it carries its scope and note and is excluded from the
    # rows-returned reconciliation below.
    # Round-4 J4-25: the moved-out-of-window rows are COUNTED, so the tiers add back up
    # to the header's own total instead of stopping one short of it.
    assert set(counts) == {"late", "today", "upcoming", "beyond", "window_days",
                           "beyond_scope", "beyond_note_th", "moved_out_of_window",
                           "moved_out_of_window_note_th", "counted_in_tiers", "rows",
                           "uncounted", "partitions_total", "counts_note_th",
                           # Language pass: additive English twins.
                           "beyond_note_en", "moved_out_of_window_note_en", "counts_note_en"}
    assert counts["beyond_scope"] == "whole_book"
    dated = counts["late"] + counts["today"] + counts["upcoming"]
    assert counts["moved_out_of_window"] == sum(1 for i in body["items"] if i.get("moved_out_of_window"))
    assert dated + counts["moved_out_of_window"] == counts["counted_in_tiers"] \
        == body["meta"]["total"] == len(body["items"])
    assert counts["partitions_total"] and counts["uncounted"] == 0
    assert counts["late"] == sum(1 for i in body["items"] if i["late_install"])
    assert counts["today"] == sum(1 for i in body["items"] if i["planned_install_on"] == str(BD))


# --- J-26 ---------------------------------------------------------------------------

def test_j26_delivery_has_a_moment_a_day_and_a_reply(client, stub):
    uid, _ = _released_item(client)
    delivery = client.post("/v1/pipeline/%s/delivery" % uid, json={"channel": "LINE", "by": "thip"}).json()["item"]["delivery"]
    assert delivery["sent_at"].startswith(str(BD) + "T") and len(delivery["sent_at"]) == 19
    assert delivery["sent_on"] == str(BD) and delivery["reply"] is None and delivery["replied_at"] is None
    r = client.post("/v1/pipeline/%s/delivery/reply" % uid, json={"reply": "  "})
    assert r.status_code == 422 and r.json()["code"] == "reply_required" and _thai(r.json()["message_th"])
    r = client.post("/v1/pipeline/%s/delivery/reply" % uid, json={"reply": "จะโอนพรุ่งนี้ค่ะ"}, headers={"X-Volt-Officer": "thip"})
    assert r.status_code == 200
    assert r.json()["item"]["delivery"]["reply"] == "จะโอนพรุ่งนี้ค่ะ" and r.json()["item"]["delivery"]["replied_at"].startswith(str(BD) + "T")


# --- J-27 ---------------------------------------------------------------------------

def test_j27_amend_due_date_stores_the_new_due_and_the_document_uids(client, stub):
    uid, release_doc = _released_item(client)
    r = client.post("/v1/pipeline/%s/reschedule" % uid, json={"decision": "AMEND_DUE_DATE", "reason": "EPC moved the crew"})
    assert r.status_code == 422 and r.json()["code"] == "new_due_required" and _thai(r.json()["message_th"])
    new_due = str(BD + timedelta(days=9))
    r = client.post("/v1/pipeline/%s/reschedule" % uid, json={"decision": "AMEND_DUE_DATE", "reason": "EPC moved the crew", "new_due": new_due})
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["amended_due"] == new_due
    assert item["peak_document_uids"][0] == release_doc and r.json()["peak_documents"][0]["uid"] in item["peak_document_uids"]
    listed = next(i for i in client.get("/v1/pipeline", params={"all": "true"}).json()["items"] if i["uid"] == uid)
    assert listed["amended_due"] == new_due and len(listed["peak_document_uids"]) == 2


# --- J-37 ---------------------------------------------------------------------------

def test_j37_peak_documents_meta_names_the_transport(client):
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    try:
        meta = client.get("/v1/peak-documents").json()["meta"]
        # Round-4 J4-27: the stub approves when the app READS the state back — nothing
        # runs on a timer, and the sentence no longer promises one.
        assert meta["transport"] == "STUB" and meta["transport_note_th"] == "จำลอง: อนุมัติเมื่อกดอ่านสถานะกลับ ไม่ใช่ PEAK จริง"
    finally:
        pkd.TRANSPORT_OVERRIDE = None
    meta = client.get("/v1/peak-documents", headers={"X-Volt-Role": "OFFICER"}).json()["meta"]
    assert meta["transport"] == "LIVE" and _thai(meta["transport_note_th"]) and meta["write_mode"] == "DRAFT_ONLY"


# --- J-46 / J-50 --------------------------------------------------------------------

def test_j46_npl_type_needs_a_reason_and_the_event_carries_it(client):
    item = next(i for i in _today_items(client) if i["case"]["payment_status"] == "NPL")
    uid = item["customer"]["uid"]
    r = client.post("/v1/cases/by-customer/%s/npl-type" % uid, json={"code": "NPL_2_COOPERATIVE_DECOMMISSION"}, headers=MANAGER)
    assert r.status_code == 422 and r.json()["code"] == "reason_required"
    assert r.json()["message_th"] == "ต้องระบุเหตุผลในการกำหนดประเภท NPL"
    r = client.post("/v1/cases/by-customer/%s/npl-type" % uid,
                    json={"code": "NPL_2_COOPERATIVE_DECOMMISSION", "reason": "ลูกค้าขอถอดระบบเอง"}, headers=MANAGER)
    assert r.status_code == 200
    event = [e for e in client.get("/v1/cases/by-customer/%s" % uid).json()["events"] if e["kind"] == "NPL_TYPE_SET"][-1]
    assert event["reason"] == "ลูกค้าขอถอดระบบเอง" and event["code"] == "NPL_2_COOPERATIVE_DECOMMISSION"
    assert event["by"] == "settasak" and event["on"] == str(BD)
    # J-50: the review path stores the code too
    other = next(i for i in _today_items(client) if i["case"]["payment_status"] == "NPL" and i["case"]["review_uid"] and i["customer"]["uid"] != uid)
    r = client.post("/v1/reviews/%s:answer" % other["case"]["review_uid"],
                    json={"decision": "NPL_TYPE_SET", "npl_type": "NPL_3_UNCOOPERATIVE_LEGAL", "comment": "ไม่ตอบทุกช่องทาง"}, headers=MANAGER)
    assert r.status_code == 200, r.json()
    event = [e for e in client.get("/v1/cases/by-customer/%s" % other["customer"]["uid"]).json()["events"] if e["kind"] == "NPL_TYPE_SET"][-1]
    assert event["code"] == "NPL_3_UNCOOPERATIVE_LEGAL" and event["reason"] == "ไม่ตอบทุกช่องทาง"


# --- J-47 ---------------------------------------------------------------------------

def test_j47_npl_cases_lists_every_npl_case_with_its_type(client):
    npl_today = {i["customer"]["uid"] for i in _today_items(client) if i["case"]["payment_status"] == "NPL"}
    body = client.get("/v1/npl-cases").json()
    rows = body["npl_cases"]
    assert npl_today and npl_today <= {r["customer_uid"] for r in rows}
    for r in rows:
        for key in ("npl_type", "npl_type_label", "display_name", "volt_id", "aggregate_overdue", "source", "contract_uid"):
            assert key in r, key
        assert r["source"] in ("SHEET", "DEMO")
    assert body["meta"]["by_source"]["SHEET"] >= 1
    assert any(r["npl_type"] and _thai(r["npl_type_label"]) for r in rows)
    # the demo declarations keep their shape
    demo = [r for r in rows if r["declared_on"]]
    assert demo and all("recovery_uid" in r and "pending_decision" in r for r in demo)


# --- J-48 ---------------------------------------------------------------------------

def test_j48_power_restriction_needs_a_reason(client):
    item = next(i for i in _today_items(client) if i["case"]["payment_status"] == "LATE" and i["case"]["power_state"] == "ON")
    uid = item["customer"]["uid"]
    r = client.post("/v1/cases/by-customer/%s/power-restriction" % uid, json={}, headers={"X-Volt-Officer": "nantapol"})
    assert r.status_code == 422 and r.json()["code"] == "reason_required" and _thai(r.json()["message_th"])
    r = client.post("/v1/cases/by-customer/%s/power-restriction" % uid, json={"reason": "ค้างนาน"}, headers={"X-Volt-Officer": "nantapol"})
    # with a reason the existing preconditions still decide
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        assert r.json()["power"]["request_reason"] == "ค้างนาน"
    else:
        assert r.json()["code"] == "power_restriction_preconditions"


# --- J-52 ---------------------------------------------------------------------------

def test_j52_weekly_snapshot_freezes_the_report_newest_first(client):
    assert client.post("/v1/reports/weekly:snapshot", headers={"X-Volt-Role": "OFFICER"}).status_code == 403
    first = client.post("/v1/reports/weekly:snapshot", headers=MANAGER)
    assert first.status_code == 201
    snap = first.json()["snapshot"]
    assert snap["snapshot_uid"] and snap["taken_at"].startswith(str(BD) + "T") and snap["taken_by"] == "settasak"
    assert snap["payload"]["portfolio"]["in_collection"] == client.get("/v1/reports/weekly").json()["portfolio"]["in_collection"]
    second = client.post("/v1/reports/weekly:snapshot", headers=OWNER).json()["snapshot"]
    listed = client.get("/v1/reports/weekly/snapshots").json()["snapshots"]
    assert [s["snapshot_uid"] for s in listed] == [second["snapshot_uid"], snap["snapshot_uid"]]
    assert listed[0]["label"] == snap["payload"]["period"]["label"] and listed[0]["taken_by"] == "jo"


# --- J-53 ---------------------------------------------------------------------------

def test_r7_an_open_decision_is_read_only_at_every_role_the_owner_included(client):
    """Redesign v2 ruling R7 (supersedes J-53's Owner-edits-OPEN): a ruling is made by
    decision, not by typing a value — an OPEN key is locked for everyone."""
    for role in ("OFFICER", "MANAGER", "OWNER"):
        config = client.get("/v1/config", headers={"X-Volt-Role": role}).json()["config"]
        for key in ("invoice_owner_role", "npl_review_dpd"):
            row = config[key]
            assert row["editable"] is False and row["editable_by"] is None and row["lock"] == "locked"
            assert row["state"] == "OPEN" and row["owner"] and row["note_th"] and row["note_en"]
        assert config["peak_write_mode"]["lock"] == "locked"
        assert config["late_payment_daily_rate"]["lock"] == "owner_only"
        assert config["pipeline_lookahead_days"]["lock"] == "manager"
    for headers in (MANAGER, OWNER):
        r = client.put("/v1/config", json={"invoice_owner_role": "AR"}, headers=headers)
        assert r.status_code == 422 and r.json()["code"] == "config_awaiting_ruling"
        assert r.json()["extensions"]["key"] == "invoice_owner_role"
    assert client.get("/v1/config", headers=OWNER).json()["config"]["invoice_owner_role"]["changed_by"] is None


def test_r6_87_decided_rules_report_decided_and_stay_owner_only(client):
    """Rulings 87/88: CF1 and OD-31 are closed. The rows must say DECIDED and carry
    their provenance — and a MANAGER must still be refused, because Arina ruled them
    configurable by the Owner, not by anyone."""
    config = client.get("/v1/config", headers=OWNER).json()["config"]
    for key, decision, ruling in (("late_payment_daily_rate", "CF1", 87),
                                  ("late_payment_grace_days", "OD-31", 88)):
        row = config[key]
        assert row["state"] == "DECIDED"
        assert row["decision"] == decision
        assert row["ruling"] == ruling
        assert row["decided_by"] == "Arina"
        assert row["decided_on"] == "2026-09-09"
        assert row["basis"]
        assert row["editable_by"] == "OWNER"
    r = client.put("/v1/config", json={"late_payment_daily_rate": "0.01"}, headers=MANAGER)
    assert r.status_code == 403 and r.json()["extensions"]["editable_by"] == "OWNER"


def test_r6_87_the_three_ruled_constants_hold_their_ruled_values():
    assert settings.late_payment_daily_rate == Decimal("0.0003")   # ruling 87
    assert settings.late_payment_grace_days == 0                   # ruling 88
    assert settings.uninstall_fee_thb_per_watt == Decimal("5")     # ruling 89


# --- J-54 ---------------------------------------------------------------------------

def test_j54_band_sets_deactivate_never_delete_and_never_the_active_one(client):
    assert client.post("/v1/band-sets/LEGACY_SHEET:deactivate", headers={"X-Volt-Role": "OFFICER"}).status_code == 403
    r = client.post("/v1/band-sets/%s:deactivate" % settings.band_set_code, headers=MANAGER)
    assert r.status_code == 409 and r.json()["code"] == "band_set_in_use" and _thai(r.json()["message_th"])
    r = client.post("/v1/band-sets/LEGACY_SHEET:deactivate", headers=MANAGER)
    assert r.status_code == 200 and r.json()["band_set"]["active"] is False
    sets = {s["code"]: s for s in client.get("/v1/band-sets").json()["band_sets"]}
    assert sets["LEGACY_SHEET"]["active"] is False and sets["OPERATIONAL"]["active"] is True
    assert "LEGACY_SHEET" in sets, "deactivated, not deleted"


def test_put_config_rejects_unknown_band_set_and_returns_rows(client):
    """Round-2 outage (thip T2-07): a Manager saved band_set_code 'X'; every band lookup
    raised for every session. The gate refuses, and a valid save returns the rows."""
    from app.config import settings
    before = settings.band_set_code
    h = {"X-Volt-Role": "MANAGER"}
    r = client.put("/v1/config", json={"band_set_code": "NOT_A_SET"}, headers=h)
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "band_set_unknown"
    assert settings.band_set_code == before
    assert client.get("/v1/today").status_code == 200
    ok = client.put("/v1/config", json={"band_set_code": "LEGACY_SHEET"}, headers=h)
    assert ok.status_code == 200 and ok.json()["config"]["band_set_code"]["value"] == "LEGACY_SHEET"
    assert client.get("/v1/today").status_code == 200
    client.put("/v1/config", json={"band_set_code": before}, headers=h)
