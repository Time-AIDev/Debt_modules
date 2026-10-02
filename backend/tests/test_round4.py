"""Blind UAT round 4 — one regression per finding on the judge's ordered fix list.

Every test goes through the HTTP surface with the session cookie the middleware issues,
exactly as the interface does. The id in each name is the judge's own (docs/uat/round-4/
judge.md §1 and §4), so a future round can trace a behaviour back to the finding that
put it there.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import peak_documents as pkd
from app.config import settings
from app.main import app

BD = settings.business_date
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Officer": "nantapol"}


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")     # the same session the `state` fixture reads
    return c


@pytest.fixture
def state():
    return cases_domain.for_current()


def _today(client, officer=None):
    return client.get("/v1/today" + ("?officer=%s" % officer if officer else "")).json()


def _case_with_open_invoice(client, state):
    """A LATE case that has an open invoice to confirm a slip against."""
    for case in state.cases.values():
        if case["payment_status"] != "LATE":
            continue
        rows = client.get("/v1/cases/by-customer/%s/invoices" % case["customer_uid"]).json().get("invoices") or []
        if rows:
            return case, rows[0]
    raise AssertionError("no LATE case in the book has an open invoice")


# --- P2 1. J4-01 ---------------------------------------------------------------------

def test_j4_01_a_contact_is_stamped_from_the_business_clock_and_the_list_moves_on(client):
    """The round's root cause: the drawer stamped the machine's day (2026-09-03) while
    /v1/today looks the lock up on the business day, so the desk was refused a second
    contact on a customer it was still being told to call first."""
    body = _today(client, officer="nantapol")
    next_up = body["meta"]["next_up"]
    assert next_up
    # the wall clock the browser would send — a different calendar day entirely
    logged = client.post("/v1/contacts", json={
        "customer_uid": next_up, "channel": "PHONE", "direction": "OUTBOUND",
        "disposition": "ANS_DISCUSSED", "at": "2026-09-03T10:00:00+07:00", "officer": "nantapol"})
    assert logged.status_code == 201
    written = logged.json()
    assert written["counted"] and written["lock_consumed"]
    assert written["stamped_from"] == "BUSINESS_CLOCK"
    assert written["business_date"] == written["lock_date"] == str(BD)
    assert written["at"].startswith(str(BD)) and written["at_reported"].startswith("2026-09-03")

    after = _today(client, officer="nantapol")
    row = next(i for i in after["items"] if i["customer"]["uid"] == next_up)
    assert row["contact_lock"]["state"] == "LOCKED"
    # Ruling 62 (Arina, 2026-09-06, the fifteenth and final authorised test edit):
    # closes R4-F55. The row-level key was "last_contact", sharing a name with the
    # unrelated case.last_contact_at (the imported history, set on 8/151) one level
    # down — renamed to session_last_contact (routers/journey.py) because this
    # assertion is, and always was, about THIS session's own dialling landing on
    # the business day, not the imported history. Same value, new name.
    assert row["session_last_contact"]["at"].startswith(str(BD))
    assert after["meta"]["next_up"] and after["meta"]["next_up"] != next_up


# --- P2 2. J4-14 ---------------------------------------------------------------------

def test_j4_14_a_band_set_is_validated_before_it_is_created_and_stays_reachable(client):
    blank_set = client.post("/v1/band-sets", headers=MANAGER,
                            json={"code": "", "bands": [{"low": 0, "high": None, "code": ""}]})
    assert blank_set.status_code == 422
    assert blank_set.json()["errors"][0]["pointer"] == "/code"
    assert _thai(blank_set.json()["errors"][0]["message_th"])

    blank_band = client.post("/v1/band-sets", headers=MANAGER,
                             json={"code": "R4_BLANK_BAND", "bands": [{"low": 0, "high": None, "code": "  "}]})
    assert blank_band.status_code == 422
    assert blank_band.json()["errors"][0]["pointer"] == "/bands/0/code"

    unroutable = client.post("/v1/band-sets", headers=MANAGER,
                             json={"code": "R4 BAD/CODE", "bands": [{"low": 0, "high": None, "code": "ALL"}]})
    assert unroutable.status_code == 422 and unroutable.json()["errors"][0]["pointer"] == "/code"

    assert client.post("/v1/band-sets", headers=MANAGER, json={
        "code": "R4_GOOD", "bands": [{"low": 0, "high": 29, "code": "R4_EARLY"},
                                     {"low": 30, "high": None, "code": "R4_LATE"}]}).status_code == 201

    # every set that exists is reachable by its own :deactivate route
    for row in client.get("/v1/band-sets").json()["band_sets"]:
        assert row["code"].strip() == row["code"] and row["code"]
        assert row["deactivate_path"] == "/v1/band-sets/%s:deactivate" % row["code"]
        r = client.post(row["deactivate_path"], headers=MANAGER, json={})
        assert r.status_code in (200, 409), (row["code"], r.status_code)   # 409 = the set in use
        if r.status_code == 200:
            assert client.post(row["activate_path"], headers=MANAGER, json={}).status_code == 200


# --- P2 3. J4-12 ---------------------------------------------------------------------

def test_j4_12_the_npl_type_is_gated_on_the_customer_being_npl(client, state):
    late = next(c for c in state.cases.values() if c["payment_status"] == "LATE")
    refused = client.post("/v1/cases/by-customer/%s/npl-type" % late["customer_uid"], headers=MANAGER,
                          json={"code": "NPL_2_COOPERATIVE_DECOMMISSION", "reason": "ขอถอดระบบ"})
    assert refused.status_code == 409 and refused.json()["code"] == "npl_type_not_applicable"
    assert _thai(refused.json()["message_th"]) and "NPL" in refused.json()["message_th"]
    ext = refused.json()["extensions"]
    assert ext["payment_status"] == "LATE" and ext["required_payment_status"] == "NPL" and ext["rule"] == "REQ-COL-075"
    assert late["npl_type"] is None
    # and it never reaches the log a lead pastes upstairs
    assert not [e for e in client.get("/v1/reports/weekly").json()["npl_changes"]
                if e["case_uid"] == late["uid"]]

    npl = next(c for c in state.cases.values() if c["payment_status"] == "NPL")
    ok = client.post("/v1/cases/by-customer/%s/npl-type" % npl["customer_uid"], headers=MANAGER,
                     json={"code": "NPL_2_COOPERATIVE_DECOMMISSION", "reason": "ลูกค้าขอถอดระบบเอง"})
    assert ok.status_code == 200
    case = ok.json()["case"]
    assert case["npl_type_set_by"] == "settasak" and case["npl_type_reason"] == "ลูกค้าขอถอดระบบเอง"
    assert case["npl_type_set_by_role"] == "MANAGER" and case["npl_type_set_on"] == str(BD)


# --- P2 4. J4-13 ---------------------------------------------------------------------

def test_j4_13_a_band_set_carries_its_own_thai_labels(client):
    assert client.post("/v1/band-sets", headers=MANAGER, json={
        "code": "R4_LABELLED", "label_th": "ชุดทดสอบรอบ 4",
        "bands": [{"low": 0, "high": 7, "code": "R4_A", "label_th": "ค้างไม่เกินหนึ่งสัปดาห์"},
                  {"low": 8, "high": None, "code": "R4_B"}]}).status_code == 201
    body = client.get("/v1/band-sets").json()
    mine = next(r for r in body["band_sets"] if r["code"] == "R4_LABELLED")
    assert mine["label_th"] == "ชุดทดสอบรอบ 4"
    assert [b["label_th"] for b in mine["bands"]] == ["ค้างไม่เกินหนึ่งสัปดาห์", "ค้าง 8 วันขึ้นไป"]
    # every band of every set has Thai words — no screen has to print a raw code
    for row in body["band_sets"]:
        assert all(_thai(b["label_th"]) for b in row["bands"]), row["code"]
    # a seeded set is named in Thai in the chooser too, never by its raw code
    assert all(_thai(c["label_th"]) for c in body["chooser"]
               if next(r for r in body["band_sets"] if r["code"] == c["code"])["seeded"])

    settings.band_set_code, previous = "R4_LABELLED", settings.band_set_code
    try:
        row = _today(client)["items"][0]
        assert row["band_set_code"] == "R4_LABELLED"
        assert _thai(row["aging_bucket_label_th"]) and row["aging_bucket_label_th"] != row["aging_bucket"]
    finally:
        settings.band_set_code = previous


# --- P2 5. J4-07 ---------------------------------------------------------------------

def test_j4_07_the_officers_own_next_action_survives_a_ticket(client, state):
    case = next(c for c in state.cases.values()
                if c["payment_status"] == "LATE" and not c["open_issue_uid"] and not c["open_ptp_uid"])
    r = client.post("/v1/cases/by-customer/%s/contacts" % case["customer_uid"], headers=OFFICER, json={
        "result": "SERVICE_ISSUE", "counted": True, "amount_stated": True,
        "next_action": "CALL", "next_action_on": str(BD + timedelta(days=4)),
        "issue": {"summary": "อินเวอร์เตอร์ดับ", "responsible_team": "O_AND_M",
                  "deadline": str(BD + timedelta(days=20))}})
    assert r.status_code == 201
    after = r.json()["case"]
    assert after["next_action"] == "CALL" and after["next_action_on"] == str(BD + timedelta(days=4))
    assert after["next_action_set_by"] == "nantapol"
    # the ticket's deadline is not lost — it is beside it, under its own name
    assert after["ticket_deadline"] == str(BD + timedelta(days=20))
    assert _thai(after["ticket_deadline_note_th"])
    assert r.json()["issue"]["deadline"] == str(BD + timedelta(days=20))
    # closing the ticket takes its deadline away with it
    client.post("/v1/case-issues/%s:close" % r.json()["issue"]["uid"], headers=OFFICER,
                json={"resolution_note": "O&M เปลี่ยนอินเวอร์เตอร์แล้ว"})
    assert state.cases[case["customer_uid"]]["ticket_deadline"] is None


# --- P2 6. J4-02 ---------------------------------------------------------------------

def test_j4_02_a_renegotiation_writes_a_contact_and_obeys_the_daily_check(client, state):
    case = next(c for c in state.cases.values()
                if c["payment_status"] == "LATE" and not c["open_ptp_uid"] and not c["open_issue_uid"]
                and not c["review_uid"])
    uid = case["customer_uid"]
    ptp = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_PTP", "counted": False, "amount_stated": True,
        "ptp": {"amount": "1000", "date": str(BD + timedelta(days=3))}}).json()["ptp"]
    before = len([r for r in state.contact_log if r["customer_uid"] == uid])

    first = client.post("/v1/case-ptps/%s:renegotiate" % ptp["uid"], headers=OFFICER,
                        json={"amount": "1000", "date": str(BD + timedelta(days=6))})
    assert first.status_code == 201 and first.json()["counted"] and first.json()["lock_consumed"]
    assert len([r for r in state.contact_log if r["customer_uid"] == uid]) == before + 1

    second = client.post("/v1/case-ptps/%s:renegotiate" % first.json()["ptp"]["uid"], headers=OFFICER,
                         json={"amount": "1000", "date": str(BD + timedelta(days=9))})
    assert second.status_code == 409 and second.json()["code"] == "contact_locked"
    codes = [a["code"] for a in second.json()["extensions"]["alternatives"]]
    assert "SECOND_CONTACT_NOT_COUNTED" in codes
    honest = next(a for a in second.json()["extensions"]["alternatives"] if a["code"] == "SECOND_CONTACT_NOT_COUNTED")
    assert honest["field"] == "not_counted" and _thai(honest["label_th"]) and _thai(honest["how_th"])
    # the way through does not require calling the officer's own call an inbound one
    again = client.post("/v1/case-ptps/%s:renegotiate" % first.json()["ptp"]["uid"], headers=OFFICER,
                        json={"amount": "1000", "date": str(BD + timedelta(days=9)), "not_counted": True})
    assert again.status_code == 201 and again.json()["counted"] is False
    row = [r for r in state.contact_log if r["customer_uid"] == uid][-1]
    assert row["direction"] == "OUTBOUND" and row["counted"] is False and row["not_counted_declared"] is True


def test_j4_02_a_case_contact_keeps_the_not_counted_declaration(client, state):
    """fix-all Leg R: the drawer's second call (the case's own row) carries the slot's
    `not_counted` too, so the case history shows its "ไม่นับ" chip — before this only
    the renegotiation path above kept the declaration."""
    uid = next(c for c in state.cases.values() if c["payment_status"] == "LATE")["customer_uid"]
    body = {"result": "REACHED_ANSWERED", "channel": "PHONE", "counted": False,
            "next_action": "CALL", "next_action_on": str(BD + timedelta(days=1))}
    declared = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER,
                           json={**body, "not_counted": True})
    assert declared.status_code == 201, declared.json()
    assert declared.json()["contact"]["not_counted_declared"] is True
    plain = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json=body)
    assert plain.status_code == 201 and plain.json()["contact"]["not_counted_declared"] is False
    history = client.get("/v1/cases/by-customer/%s" % uid).json()
    served = {c["uid"]: c for c in history["contact_log"]}
    assert served[declared.json()["contact"]["uid"]]["not_counted_declared"] is True


# --- P2 7. J4-06 ---------------------------------------------------------------------

def test_j4_06_the_weekly_report_carries_the_od_02_caveat_beside_the_ratio(client, state):
    weekly = client.get("/v1/reports/weekly").json()
    assert weekly["portfolio"]["allocation_hold_customers"] == 0
    assert weekly["portfolio"]["allocation_hold_note_th"] is None

    late, invoice = _case_with_open_invoice(client, state)
    slip = client.post("/v1/slips", headers=OFFICER,
                       json={"invoice_uid": invoice["uid"], "amount": invoice["amount_to_ask"], "slip_ref": "slip-r4"})
    assert slip.status_code == 201 and slip.json()["receipt"]["is_allocated"] is False
    client.post("/v1/peak-documents:refresh-all")

    weekly = client.get("/v1/reports/weekly").json()
    assert Decimal(weekly["management_summary"]["cash_in"]["total"]) > 0
    portfolio = weekly["portfolio"]
    assert portfolio["allocation_hold_customers"] >= 1 and portfolio["allocation_hold_receipts"] >= 1
    assert portfolio["allocation_hold_pending_decision"] == "OD-02"
    note = portfolio["allocation_hold_note_th"]
    assert _thai(note) and "ลำดับการจัดสรร" in note and "OD-02" not in note and "ล่าช้า" in note
    assert weekly["management_summary"]["allocation_hold_note_th"] == note


# --- P2 8. J4-03 ---------------------------------------------------------------------

def test_j4_03_the_lineage_note_reads_the_previous_promises_closed_on(client, state):
    case = next(c for c in state.cases.values()
                if c["payment_status"] == "LATE" and not c["open_ptp_uid"] and not c["broken_ptp_count"])
    uid = case["customer_uid"]
    promised = str(BD + timedelta(days=7))
    ptp = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_PTP", "counted": False, "amount_stated": True,
        "ptp": {"amount": "1000", "date": promised}}).json()["ptp"]
    closed = client.post("/v1/case-ptps/%s:close" % ptp["uid"], headers=OFFICER,
                         json={"outcome": "BROKEN", "on": str(BD), "reason": "ลูกค้าแจ้งว่าจะไม่ชำระตามนัด"})
    assert closed.status_code == 200 and closed.json()["ptp"]["closed_on"] == str(BD) != promised

    nxt = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_PTP", "counted": False, "amount_stated": True,
        "ptp": {"amount": "1000", "date": str(BD + timedelta(days=10))}}).json()["ptp"]
    assert nxt["lineage_from_uid"] == ptp["uid"]
    assert nxt["lineage_from_closed_on"] == str(BD) and nxt["lineage_from_promise_date"] == promised
    assert nxt["lineage_note_th"] == "ต่อเนื่องจากสัญญาที่ผิดนัดเมื่อ %s (%s)" % (BD, ptp["uid"])
    assert promised not in nxt["lineage_note_th"]


# --- P3 J4-04 ------------------------------------------------------------------------

def test_j4_04_breaking_a_promise_before_its_date_is_warned_about(client, state):
    case = next(c for c in state.cases.values()
                if c["payment_status"] == "LATE" and not c["open_ptp_uid"] and not c["broken_ptp_count"])
    ptp = client.post("/v1/cases/by-customer/%s/contacts" % case["customer_uid"], headers=OFFICER, json={
        "result": "REACHED_PTP", "counted": False, "amount_stated": True,
        "ptp": {"amount": "1000", "date": str(BD + timedelta(days=7))}}).json()["ptp"]
    r = client.post("/v1/case-ptps/%s:close" % ptp["uid"], headers=OFFICER, json={"outcome": "BROKEN", "on": str(BD)})
    assert r.status_code == 200
    warning = r.json()["warning"]
    assert warning["code"] == "ptp_broken_before_due" and warning["days_early"] == 7
    assert _thai(warning["message_th"]) and str(BD + timedelta(days=7)) in warning["message_th"]
    assert r.json()["ptp"]["broken_before_due"] is True

    # a promise broken on or after its own date carries no warning
    other = next(c for c in state.cases.values()
                 if c["payment_status"] == "LATE" and not c["open_ptp_uid"] and not c["broken_ptp_count"]
                 and c["uid"] != case["uid"])
    ptp2 = client.post("/v1/cases/by-customer/%s/contacts" % other["customer_uid"], headers=OFFICER, json={
        "result": "REACHED_PTP", "counted": False, "amount_stated": True,
        "ptp": {"amount": "1000", "date": str(BD - timedelta(days=1))}}).json()["ptp"]
    r2 = client.post("/v1/case-ptps/%s:close" % ptp2["uid"], headers=OFFICER, json={"outcome": "BROKEN", "on": str(BD)})
    assert r2.json()["warning"] is None and r2.json()["ptp"]["broken_before_due"] is False


# --- P3 J4-16 ------------------------------------------------------------------------

def test_j4_16_a_review_decision_sets_the_cases_next_action(client, state):
    case = next(c for c in state.cases.values() if not c["review_uid"] and c["payment_status"] == "LATE")
    uid = case["customer_uid"]
    review = client.post("/v1/cases/by-customer/%s/review-requests" % uid, headers=OFFICER,
                         json={"reason": "UNREACHABLE", "question_th": "ขอให้ลงพื้นที่"}).json()["review"]
    assert case["next_action"] == "AWAIT_REVIEW"
    r = client.post("/v1/reviews/%s:answer" % review["uid"], headers=MANAGER,
                    json={"decision": "LEGAL_REFER", "comment": "ส่งฝ่ายกฎหมายสัปดาห์นี้"})
    assert r.status_code == 200
    after = r.json()["case"]
    assert after["next_action"] == "ESCALATE" and after["next_action_set_by"] == "settasak"
    assert "ส่งฝ่ายกฎหมายสัปดาห์นี้" in after["next_action_note"]

    # and a Manager may name the step outright
    other = next(c for c in state.cases.values() if not c["review_uid"] and c["payment_status"] == "LATE"
                 and c["uid"] != case["uid"])
    rv = client.post("/v1/cases/by-customer/%s/review-requests" % other["customer_uid"], headers=OFFICER,
                     json={"reason": "UNREACHABLE", "question_th": "ขอคำแนะนำ"}).json()["review"]
    answered = client.post("/v1/reviews/%s:answer" % rv["uid"], headers=MANAGER,
                           json={"decision": "CONTINUE", "comment": "ไปเยี่ยมบ้าน",
                                 "next_action": "VISIT", "next_action_on": str(BD + timedelta(days=2))}).json()["case"]
    assert answered["next_action"] == "VISIT" and answered["next_action_on"] == str(BD + timedelta(days=2))


# --- P3 J4-18 ------------------------------------------------------------------------

def test_j4_18_the_weekly_sentences_have_thai_twins(client):
    weekly = client.get("/v1/reports/weekly").json()
    assert _thai(weekly["management_summary"]["note_th"])
    assert _thai(weekly["portfolio"]["ratio_definition_th"])
    assert _thai(weekly["portfolio"]["period_of_ratio_th"])
    assert _thai(weekly["portfolio"]["unit_th"])
    assert _thai(weekly["promises"]["period_of_ratio_th"])
    # the English originals stay beside them, they are not replaced
    assert weekly["portfolio"]["ratio_definition"] and weekly["management_summary"]["note"]


# --- P3 J4-19 ------------------------------------------------------------------------

def test_j4_19_a_snapshot_can_be_named_and_its_payload_fetched_back(client):
    snap = client.post("/v1/reports/weekly:snapshot", headers=MANAGER,
                       json={"name": "ก่อนประชุมทีมวันจันทร์"}).json()["snapshot"]
    assert snap["name"] == "ก่อนประชุมทีมวันจันทร์" and snap["label"] and snap["payload"]
    fetched = client.get("/v1/reports/weekly/snapshots/%s" % snap["snapshot_uid"])
    assert fetched.status_code == 200
    stored = fetched.json()["snapshot"]
    assert stored["payload"]["portfolio"]["in_collection"] == snap["payload"]["portfolio"]["in_collection"]
    renamed = client.post("/v1/reports/weekly/snapshots/%s:rename" % snap["snapshot_uid"], headers=MANAGER,
                          json={"name": "หลังปิดยอด"}).json()["snapshot"]
    assert renamed["name"] == "หลังปิดยอด"
    assert client.get("/v1/reports/weekly/snapshots/wks-99999").status_code == 404


# --- P3 J4-21 ------------------------------------------------------------------------

def test_j4_21_a_reminder_can_be_sent_on_demand_for_a_case_or_an_invoice(client, state):
    case, invoice = _case_with_open_invoice(client, state)
    uid = case["customer_uid"]
    sent = client.post("/v1/today/reminders:send", headers=OFFICER, json={"customer_uid": uid, "channel": "LINE"})
    assert sent.status_code == 200
    assert sent.json()["reminder"]["counted"] is False and sent.json()["contact"]["counted"] is False
    assert sent.json()["contact"]["occurred_at"].startswith(str(BD))       # J4-01: the business clock

    by_invoice = client.post("/v1/today/reminders:send", headers=OFFICER,
                             json={"invoice_uid": invoice["uid"], "channel": "LINE"})
    assert by_invoice.status_code == 200
    reminder = by_invoice.json()["reminder"]
    # Amount-led journey: one consolidated reminder per customer/month. A second
    # click from an invoice replays the original customer reminder instead of
    # creating a duplicate outbound contact.
    assert reminder["invoice_uid"] is None and reminder["customer_uid"] == uid
    assert reminder["consolidated"] is True
    assert by_invoice.json()["already_sent"] is True
    assert by_invoice.json()["contact"] is None
    assert client.post("/v1/today/reminders:send", headers=OFFICER, json={"invoice_uid": "inv-9999"}).status_code == 404

    # the batch answers its officer filter instead of handing every desk the whole book
    mine = client.get("/v1/today/reminders?days=21&officer=thip").json()
    assert mine["meta"]["officer"] == "thip"
    assert all(r["officer_uid"] == "thip" for r in mine["reminders"])


# --- P3 J4-23 ------------------------------------------------------------------------

def test_j4_23_the_export_carries_the_penalty_the_sheet_columns_and_the_invoice_state(client):
    meta = client.get("/v1/workbook").json()["meta"]
    for column in ("penalty_accrued_unbilled", "sheet_days_late", "sheet_late_fees",
                   "invoice_state", "invoice_peak_state", "fee_state", "aging_bucket_label_th"):
        assert column in meta["columns"]
    body = client.get("/v1/workbook:export").text
    header = body.lstrip("﻿").splitlines()[0].split(",")
    assert header == meta["columns"]
    assert len(body.splitlines()) == client.get("/v1/workbook").json()["meta"]["total"] + 1


# --- P3 J4-25 ------------------------------------------------------------------------

def test_j4_25_a_moved_out_of_window_row_is_counted_so_the_tiers_add_up(client):
    before = client.get("/v1/pipeline").json()
    item = next(i for i in before["items"] if not i["moved_out_of_window"] and i["install_outcome"] != "INSTALLED")
    r = client.post("/v1/pipeline/%s/install-outcome" % item["uid"], headers=OFFICER,
                    json={"outcome": "POSTPONED", "new_install_on": str(BD + timedelta(days=13)),
                          "reason": "ลูกค้าขอเลื่อน"})
    assert r.status_code == 200, r.json()
    after = client.get("/v1/pipeline").json()
    counts = after["meta"]["counts"]
    assert counts["moved_out_of_window"] >= 1
    assert counts["late"] + counts["today"] + counts["upcoming"] + counts["moved_out_of_window"] \
        == counts["counted_in_tiers"] == after["meta"]["total"] == len(after["items"])
    assert counts["partitions_total"] and _thai(counts["counts_note_th"])
    assert _thai(counts["moved_out_of_window_note_th"])


# --- P3 J4-27 ------------------------------------------------------------------------

def test_j4_27_the_simulation_sentence_and_the_caption_follow_the_state(client, state):
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    try:
        meta = client.get("/v1/peak-documents").json()["meta"]
        assert meta["transport_note_th"] == "จำลอง: อนุมัติเมื่อกดอ่านสถานะกลับ ไม่ใช่ PEAK จริง"
        assert "วินาที" not in meta["transport_note_th"]

        case, invoice = _case_with_open_invoice(client, state)
        uid = case["customer_uid"]
        client.post("/v1/slips", headers=OFFICER,
                    json={"invoice_uid": invoice["uid"], "amount": invoice["amount_to_ask"], "slip_ref": "slip-r4b"})
        drafted = client.get("/v1/cases/by-customer/%s" % uid).json()["allocation_note_th"]
        assert "รอ AR อนุมัติใน PEAK" in drafted and "ลำดับการจัดสรร" in drafted and "OD-02" not in drafted
        client.post("/v1/peak-documents:refresh-all")
        approved = client.get("/v1/cases/by-customer/%s" % uid).json()["allocation_note_th"]
        assert "อนุมัติใน PEAK แล้ว" in approved and "รอ AR" not in approved and "ลำดับการจัดสรร" in approved and "OD-02" not in approved
    finally:
        pkd.TRANSPORT_OVERRIDE = None


# --- P3 J4-29 ------------------------------------------------------------------------

def test_j4_29_a_cash_book_is_not_told_it_missed_eleven_monthly_instalments(client):
    items = _today(client, officer="thip")["items"]
    cash = next(i for i in items if i["missed_basis_th"])
    assert cash["missed_basis"] == "CASH_EQUIVALENT"
    assert "งวดเทียบเท่า" in cash["missed_count_label_th"]
    assert "สัญญาเงินสด" in cash["tier_label_th"] or "เทียบเท่า" in cash["tier_label_th"]
    assert "ค้างสองงวดขึ้นไป ไม่มีนัดชำระ" != cash["tier_label_th"]
    # a lease book keeps the plain instalment wording
    lease = next((i for i in items if not i["missed_basis_th"] and i["tier"] == "AT_RISK_TWO_MISSED"), None)
    if lease:
        assert lease["tier_label_th"] == "ค้างสองงวดขึ้นไป ไม่มีนัดชำระ" and lease["missed_basis"] == "INSTALMENT"


# --- P3 J4-31 ------------------------------------------------------------------------

def test_j4_31_the_app_says_plainly_that_it_has_no_payment_link(client, state):
    case, invoice = _case_with_open_invoice(client, state)
    uid = case["customer_uid"]
    assert invoice["payment_link"] is None and invoice["payment_link_state"] == "NOT_AVAILABLE"
    assert _thai(invoice["payment_link_note_th"]) and "ลิงก์" in invoice["payment_link_note_th"]

    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    try:
        client.post("/v1/slips", headers=OFFICER,
                    json={"invoice_uid": invoice["uid"], "amount": invoice["amount_to_ask"], "slip_ref": "slip-r4c"})
        client.post("/v1/peak-documents:refresh-all")
        row = next(i for i in client.get("/v1/cases/by-customer/%s" % uid).json()["invoices"]
                   if i["uid"] == invoice["uid"])
        if row.get("qr_payload"):
            assert row["payment_link_state"] == "PEAK_QR" and row["payment_qr_payload"] == row["qr_payload"]
            assert row["payment_link"] is None
    finally:
        pkd.TRANSPORT_OVERRIDE = None


# --- P3 J4-32 ------------------------------------------------------------------------

def test_j4_32_unreachable_attempts_since_the_last_reach_are_counted(client, state):
    case = next(c for c in state.cases.values() if c["payment_status"] == "LATE" and not c["open_issue_uid"])
    uid = case["customer_uid"]
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["unreachable_run"]["unreachable_since_last_reach"] == 0
    for day in (1, 2, 3):
        client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
            "result": "UNREACHABLE_NO_ANSWER", "counted": False,
            "next_action": "CALL", "next_action_on": str(BD + timedelta(days=day))})
    run = client.get("/v1/cases/by-customer/%s" % uid).json()["unreachable_run"]
    assert run["unreachable_since_last_reach"] == 3 and run["first_unreachable_at"] and _thai(run["note_th"])

    review = client.post("/v1/cases/by-customer/%s/review-requests" % uid, headers=OFFICER,
                         json={"reason": "UNREACHABLE", "question_th": "ติดต่อไม่ได้สามครั้ง"}).json()["review"]
    listed = next(r for r in client.get("/v1/reviews").json()["reviews"] if r["uid"] == review["uid"])
    assert listed["unreachable_run"]["unreachable_since_last_reach"] == 3

    client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "REACHED_ANSWERED", "counted": True, "amount_stated": True,
        "next_action": "CALL", "next_action_on": str(BD + timedelta(days=4))})
    after = client.get("/v1/cases/by-customer/%s" % uid).json()["unreachable_run"]
    assert after["unreachable_since_last_reach"] == 0 and after["last_reached_at"]


# --- Round 5 ------------------------------------------------------------------------

def test_amended_due_reaches_the_case_and_waits_for_ar(client):
    """T5-01: the pipeline said 'new due date 06/11' while the customer's own case
    still read the old date and never showed the amendment at all. The invoice now
    carries the request, the case lists the document, and the date only moves when
    AR approves it in PEAK (C3, draft-only)."""
    from app import invoice_pipeline as pipeline
    from app import peak_documents as pkd

    state = pipeline.for_current()
    item = next((i for i in state.items.values() if i.get("invoice_uid")), None)
    if item is None:                     # release one so there is an invoice to amend
        item = _release_one(client, state)
    original = _invoice_of(item)["due_date"]
    new_due = "2026-11-06"

    pipeline.reschedule(state, item, "AMEND_DUE_DATE", reason="ลูกค้าขอเลื่อน",
                        new_due=new_due, by="thip")
    inv = _invoice_of(item)
    assert inv["amended_due_date"] == new_due
    assert inv["amended_due_state"] == "PENDING_PEAK_APPROVAL"
    assert inv["original_due_date"] == original

    case = client.get("/v1/cases/by-customer/%s" % item["customer_uid"]).json()
    on_case = {i["uid"]: i for i in case["invoices"]}[inv["uid"]]
    # Until AR approves, the case shows the ORIGINAL date with the request beside it.
    assert on_case["due_date"] == original
    assert new_due in on_case["amended_due_note_th"]
    assert any(d["intent"] == "INVOICE_AMEND_DUE_DATE" for d in case["peak_documents"])

    # AR approves in PEAK; the date moves on the next load, and says why.
    docs = pkd.for_current()
    for record in docs.documents.values():
        if record["intent"] == "INVOICE_AMEND_DUE_DATE":
            record["state"] = "APPROVED_IN_PEAK"
    case = client.get("/v1/cases/by-customer/%s" % item["customer_uid"]).json()
    on_case = {i["uid"]: i for i in case["invoices"]}[inv["uid"]]
    assert on_case["due_date"] == new_due
    assert on_case["amended_due_state"] == "APPROVED_IN_PEAK"


def _invoice_of(item):
    from app import journey
    return journey.for_current().invoices[item["invoice_uid"]]


def _release_one(client, state):
    """Take the first pipeline row through the prototype's three release conditions
    (Delta-100 D2h) so there is an invoice to amend. The EPC date is recorded but is
    no longer a gate; contract_signed passes by attached evidence only."""
    from datetime import timedelta
    from app.config import settings
    row = sorted(state.items.values(), key=lambda i: i["uid"])[0]
    uid = row["uid"]
    assert client.post("/v1/pipeline/%s/gates/down-payment" % uid,
                       json={"slip_ref": "slip-t5", "amount": "5000.00", "by": "thip"}).status_code == 200
    assert client.post("/v1/pipeline/%s/gates/epc-confirmed" % uid,
                       json={"confirmed_on": str(settings.business_date + timedelta(days=2)),
                             "source": "ODOO"}).status_code == 200
    assert client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"}).status_code == 201
    assert client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"}).status_code == 201
    return state.items[uid]


# --- ruling 47: an explicit concurrency guard on approve_restructure --------------
#
# test_adversarial_regressions.py::test_two_sessions_cannot_both_apply_a_restructure
# already pins the OUTWARD behaviour (second session refused, one addendum applied).
# This test is new, not an edit to that one (ruling 47's own instruction: "an
# extension, not an edit"). It pins what changed INSIDE approve_restructure: the
# refusal is now a deliberate, inspectable lock (`journey.restructure_lock`) rather
# than an accidental side effect of reading `line.schedule_status` off the shared
# Contract — so it (a) carries a real audit record (who, which restructure, when),
# (b) refuses a THIRD session too, not just the second (a lock is global; a
# coincidence would have been also, so this alone doesn't distinguish old from new —
# the audit record at (a) and the pre-mutation check at (c) do), and (c) refuses
# BEFORE any schedule mutation is attempted for the loser, leaving the loser's own
# restructure record untouched at PROPOSED rather than silently advanced.
def test_a_second_sessions_restructure_is_refused_by_an_explicit_lock_not_a_side_effect():
    from app import journey
    from app import main

    contract = main.BY_CONTRACT["K-2032-1"][1]
    before = len(contract.instalments)

    a, b, c = TestClient(app), TestClient(app), TestClient(app)

    def _restructure_of(client):
        case = next(x for x in client.get("/v1/cases").json()["cases"]
                    if x["contract_uid"] == "K-2032-1")
        return case["restructure_uid"]

    rst_a, rst_b, rst_c = _restructure_of(a), _restructure_of(b), _restructure_of(c)

    approved = a.post("/v1/restructures/%s:approve" % rst_a, json={"role": "OWNER", "by": "nantapol"})
    assert approved.status_code == 200
    # A still sees its own restructure — a guard that isolates by losing the write
    # is not a guard.
    assert a.get("/v1/restructures/%s" % rst_a).json()["restructure"]["status"] == "ACTIVE"

    # B: refused, and refused as a REAL problem, not a bare 4xx.
    refused_b = b.post("/v1/restructures/%s:approve" % rst_b, json={"role": "OWNER", "by": "settasak"})
    assert refused_b.status_code == 422
    body_b = refused_b.json()
    assert refused_b.headers["content-type"].startswith("application/problem+json")
    assert body_b["code"] == "second_restructure_forbidden"     # the ONLY field a client branches on
    assert body_b["message_th"].strip()                          # always present
    assert body_b["errors"] == []                                # empty array, never absent
    assert isinstance(body_b.get("extensions"), dict) and body_b["extensions"].get("contract_uid") == "K-2032-1"
    # The loser's OWN restructure record never advanced — the refusal happened
    # before any mutation, not after a race.
    assert b.get("/v1/restructures/%s" % rst_b).json()["restructure"]["status"] == "PROPOSED"

    # A brand-new third session, never a party to A's call, is refused identically —
    # the lock is process-wide by design, not a two-session coincidence.
    refused_c = c.post("/v1/restructures/%s:approve" % rst_c, json={"role": "OWNER"})
    assert refused_c.status_code == 422
    assert refused_c.json()["code"] == "second_restructure_forbidden"

    # The lock itself is a real, inspectable record — not a derived fact re-read off
    # the schedule — carrying who restructured the contract and through which
    # session, the way `main._IDEMPOTENCY` records a fingerprint rather than
    # re-deriving one.
    lock = journey.restructure_lock("K-2032-1")
    assert lock is not None
    assert lock["restructure_uid"] == rst_a
    assert lock["approved_by"] == "nantapol"
    assert lock["on"] == str(BD)

    # Ruling 49: the schedule DATA is isolated too now (cases.py's
    # contract_field_of / _set_contract_fields overlay, a third field on the same
    # mechanism fee_state/status already used) — the raw shared attribute below is
    # never written by a request again, so it stays at `before`. A's OWN view,
    # read the way a served endpoint reads it (through the per-session accessor,
    # here via the HTTP surface so no cookie has to be hand-pinned), shows the one
    # addendum applied — never two, and never lost by the isolation that keeps B
    # and C from seeing it.
    assert len(contract.instalments) == before
    a_schedule = a.get("/v1/contracts/K-2032-1/instalments").json()["instalments"]
    assert len(a_schedule) == before + 72
    # B never restructured, so B's own read of the SAME contract still shows the
    # pre-restructure schedule — the data-isolation half of this ruling, not just
    # the refusal.
    b_schedule = b.get("/v1/contracts/K-2032-1/instalments").json()["instalments"]
    assert len(b_schedule) == before


# --- Productivity plan (round 4, build step 3) — F1 / F2 / F3 backend ---------------
#
# The specification is docs/design/round-4/productivity-api-change-request.md (leg F,
# 2026-09-06), amended over docs/design/round-4/productivity-plan.md wherever they
# differ. Sixteen additions; zero existing assertions moved.

# --- F1-BE1 / F1-BE2 --------------------------------------------------------------

def test_f1_the_export_carries_the_promise_record(client, state):
    """F1-BE1: kept_ptp_count and broken_ptp_count, read off the case (the owning
    store) — a column of zeroes at seed is the true fact (§1a: a census, not a
    confident wrong impression)."""
    import csv
    import io
    data = client.get("/v1/workbook").json()
    body = client.get("/v1/workbook:export").text.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(body)))
    assert "kept_ptp_count" in rows[0] and "broken_ptp_count" in rows[0]
    by_volt_id = {r["volt_id"]: r for r in rows}
    checked = 0
    for row in data["rows"]:
        out = by_volt_id.get(row["case"]["volt_id"])
        if out is None:
            continue
        assert out["kept_ptp_count"] == str(row["case"]["kept_ptp_count"])
        assert out["broken_ptp_count"] == str(row["case"]["broken_ptp_count"])
        checked += 1
    assert checked > 100, "the migrated book is in the file, not a handful of rows"

    # Only one case in the whole book carries an OPEN promise at seed (C-000912,
    # volt_id None — a non-sheet customer) — so the "moves off zero" half is proven
    # by making a fresh one on a case the export can trace by its own volt_id.
    case = next(c for c in state.cases.values() if c["volt_id"] and not c["open_ptp_uid"])
    made = client.post("/v1/cases/by-customer/%s/contacts" % case["customer_uid"], headers=OFFICER, json={
        "result": "REACHED_PTP", "amount_stated": True, "counted": True,
        "ptp": {"amount": "1000", "date": str(BD + timedelta(days=1))}})
    assert made.status_code == 201
    closed = client.post("/v1/case-ptps/%s:close" % made.json()["ptp"]["uid"], json={"outcome": "KEPT"})
    assert closed.status_code == 200
    body2 = client.get("/v1/workbook:export").text.lstrip("﻿")
    row2 = next(r for r in csv.DictReader(io.StringIO(body2)) if r["volt_id"] == case["volt_id"])
    assert row2["kept_ptp_count"] == "1"


def test_f1_the_desk_says_why_it_shows_only_broken_promises(client):
    """F1-BE2: fires only where the filtered desk actually carries promise history —
    nantapol (14 broken) and the whole book render it; thip (0 broken, 0 open) does
    not, because there is no wrong impression on thip's desk to correct."""
    nantapol = _today(client, officer="nantapol")
    assert _thai(nantapol["meta"]["ptp_history_note_th"])
    thip = _today(client, officer="thip")
    assert thip["meta"]["ptp_history_note_th"] is None
    whole_book = _today(client)
    assert _thai(whole_book["meta"]["ptp_history_note_th"])


def test_f1_the_note_disappears_when_a_promise_is_kept(client, state):
    before = _today(client, officer="nantapol")
    assert _thai(before["meta"]["ptp_history_note_th"])
    case = next(c for c in state.cases.values()
                if c["officer_uid"] == "nantapol" and c["payment_status"] != "CLOSED" and not c["open_ptp_uid"])
    made = client.post("/v1/cases/by-customer/%s/contacts" % case["customer_uid"], headers=OFFICER, json={
        "result": "REACHED_PTP", "amount_stated": True, "counted": True,
        "ptp": {"amount": "1000", "date": str(BD + timedelta(days=3))}})
    assert made.status_code == 201
    closed = client.post("/v1/case-ptps/%s:close" % made.json()["ptp"]["uid"], json={"outcome": "KEPT"})
    assert closed.status_code == 200
    after = _today(client, officer="nantapol")
    assert after["meta"]["ptp_history_note_th"] is None
    row = next(i for i in after["items"] if i["customer"]["uid"] == case["customer_uid"])
    assert row["case"]["kept_ptp_count"] == 1


# --- F2-CR-1 / F2-CR-2 -------------------------------------------------------------

def test_f2_the_ladder_filter_narrows_the_desk_and_everything_follows(client):
    unfiltered = client.get("/v1/today", params={"officer": "thip"}).json()
    assert unfiltered["meta"]["total"] == 74
    filtered = client.get("/v1/today", params={"officer": "thip", "ladder_indicative": "DEFAULT_CONFIRMED_90"}).json()
    assert filtered["meta"]["total"] == 34
    assert filtered["meta"]["total"] == len(filtered["items"])
    assert sum(filtered["meta"]["counts_by_tier"].values()) == filtered["meta"]["total"]
    uids = {i["customer"]["uid"] for i in filtered["items"]}
    assert filtered["meta"]["next_up"] in uids
    assert all((i.get("ladder") or {}).get("indicative") == "DEFAULT_CONFIRMED_90" for i in filtered["items"])
    assert filtered["meta"]["ladder_indicative"] == "DEFAULT_CONFIRMED_90"


def test_f2_an_unknown_rung_is_refused_with_the_known_list(client):
    for path in ("/v1/today", "/v1/workbook", "/v1/workbook:export"):
        response = client.get(path, params={"ladder_indicative": "ALMOST_NPL"})
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["code"] == "validation_failed"
        assert body["errors"][0]["pointer"] == "/ladder_indicative"
        assert len(body["errors"][0]["known"]) == 6
        assert _thai(body["errors"][0]["message_th"])


def test_f2_meta_carries_the_rungs_on_both_endpoints(client):
    today_meta = client.get("/v1/today").json()["meta"]
    workbook_meta = client.get("/v1/workbook").json()["meta"]
    assert today_meta["ladder_rungs"] == workbook_meta["ladder_rungs"]
    assert len(today_meta["ladder_rungs"]) == 6
    notice = next(r for r in today_meta["ladder_rungs"] if r["stage"] == "NOTICE_30")
    assert notice["kinds"] == ["LEASE", "CASH"]
    assert all(_thai(r["act_th"]) for r in today_meta["ladder_rungs"])
    assert today_meta["ladder_indicative"] is None and workbook_meta["ladder_indicative"] is None


def test_f2_the_export_honours_the_ladder_filter(client):
    """Folds in F2-CR-2: the two extra columns are checked here too, on the same
    filtered rows, rather than as a fifth test."""
    import csv
    import io
    filtered_meta = client.get("/v1/workbook", params={"ladder_indicative": "DEFAULT_CONFIRMED_90"}).json()["meta"]
    assert filtered_meta["total"] == 34
    body = client.get("/v1/workbook:export", params={"ladder_indicative": "DEFAULT_CONFIRMED_90"}).text.lstrip("﻿")
    lines = [line for line in body.splitlines() if line]
    assert lines[0].split(",") == filtered_meta["columns"]
    assert filtered_meta["columns"][-4:] == ["kept_ptp_count", "broken_ptp_count", "ladder_stage", "ladder_indicative"]
    rows = list(csv.DictReader(io.StringIO(body)))
    assert len(rows) == filtered_meta["total"]
    assert all(r["ladder_indicative"] == "DEFAULT_CONFIRMED_90" for r in rows)


def test_f3_the_closed_rows_carry_unreachable_run_and_honour_the_ladder_filter(client):
    """§6.8's verification: the CLOSED path bypasses build() (R4-F58's class) and
    builds its own rows — BE-1 and the CR-1 filter must both be added there too, or
    a CLOSED row silently disagrees with meta.total and the CSV."""
    wb = client.get("/v1/workbook").json()
    closed = [r for r in wb["rows"] if r["case"]["payment_status"] == "CLOSED"]
    assert len(closed) == 61 and wb["meta"]["total"] == 212
    assert all(isinstance(r.get("unreachable_run"), dict) for r in closed)
    assert all(_thai(r["unreachable_run"]["note_th"]) for r in closed)
    # R4-F58's septet is unchanged at 7 — this round's additions did not make an 8th.
    normal = next(r for r in wb["rows"] if r["case"]["payment_status"] != "CLOSED")
    missing = set(normal.keys()) - set(closed[0].keys())
    # Language pass: an `_en` twin rides with its `_th` member and is not an 8th key.
    missing -= {k for k in missing if k.endswith("_en") and k[:-3] + "_th" in missing}
    assert len(missing) == 7

    narrowed = client.get("/v1/workbook", params={"ladder_indicative": "DEFAULT_CONFIRMED_90"}).json()
    assert not any(r["case"]["payment_status"] == "CLOSED" for r in narrowed["rows"])


# --- F3 BE-1 / BE-2 / BE-3 / BE-4 --------------------------------------------------

def test_f3_the_daily_row_carries_the_unreachable_run(client, state):
    """BE-1, and the J5-01 regression guard: the object, never a bare number."""
    case = next(c for c in state.cases.values()
                if c["officer_uid"] == "nantapol" and c["payment_status"] == "LATE" and not c["open_issue_uid"])
    uid = case["customer_uid"]
    for day in (1, 2, 3):
        client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
            "result": "UNREACHABLE_NO_ANSWER", "counted": False,
            "next_action": "CALL", "next_action_on": str(BD + timedelta(days=day))})
    body = _today(client, officer="nantapol")
    row = next(i for i in body["items"] if i["customer"]["uid"] == uid)
    run = row["unreachable_run"]
    assert isinstance(run, dict)
    assert run["unreachable_since_last_reach"] == 3
    assert _thai(run["note_th"])


def test_f3_a_contact_can_raise_the_review_it_says_it_raised(client, state):
    """The regression guard for R4-F51: at the plan's original insertion point this
    returned 422 review_required, no review, zero contact rows written."""
    case = next(c for c in state.cases.values()
                if not c["review_uid"] and not c["open_ptp_uid"] and not c["open_issue_uid"]
                and c["payment_status"] != "CLOSED")
    before = client.get("/v1/reviews").json()["reviews"]
    made = client.post("/v1/cases/by-customer/%s/contacts" % case["customer_uid"], headers=OFFICER, json={
        "result": "UNREACHABLE_NO_ANSWER", "next_action": "AWAIT_REVIEW", "next_action_on": str(BD),
        "review": {"reason": "UNREACHABLE", "question_th": "ติดต่อไม่ได้สามวัน ขอให้ผู้จัดการช่วยดู"}})
    assert made.status_code == 201, made.json()
    body = made.json()
    assert body["review"]["uid"]
    after = client.get("/v1/reviews").json()["reviews"]
    assert len(after) == len(before) + 1
    assert body["review"]["reason"] == "UNREACHABLE"
    assert body["review"]["question_th"] == "ติดต่อไม่ได้สามวัน ขอให้ผู้จัดการช่วยดู"
    assert body["case"]["next_action"] == "AWAIT_REVIEW"
    assert body["contact"]["review_uid"] == body["review"]["uid"]


def test_f3_a_second_review_in_one_contact_is_refused_before_anything_is_written(client, state):
    case = next(c for c in state.cases.values()
                if not c["review_uid"] and not c["open_ptp_uid"] and not c["open_issue_uid"]
                and c["payment_status"] != "CLOSED")
    uid = case["customer_uid"]
    first = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "UNREACHABLE_NO_ANSWER", "next_action": "AWAIT_REVIEW", "next_action_on": str(BD),
        "review": {"reason": "UNREACHABLE", "question_th": "ครั้งที่หนึ่ง"}})
    assert first.status_code == 201
    before = len(state.contact_log)
    second = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
        "result": "UNREACHABLE_NO_ANSWER", "next_action": "AWAIT_REVIEW", "next_action_on": str(BD),
        "review": {"reason": "OTHER", "question_th": "ครั้งที่สอง"}})
    assert second.status_code == 409
    assert second.headers["content-type"].startswith("application/problem+json")
    body = second.json()
    assert body["code"] == "review_pending"
    assert _thai(body["message_th"])
    assert len(state.contact_log) == before


def test_f3_a_contact_without_a_review_key_is_unchanged(client, state):
    """Pins that the new branch is opt-in — the test_cases.py:245 shape, through HTTP."""
    case = next(c for c in state.cases.values()
                if not c["open_ptp_uid"] and not c["open_issue_uid"] and c["payment_status"] != "CLOSED")
    before = client.get("/v1/reviews").json()["reviews"]
    made = client.post("/v1/cases/by-customer/%s/contacts" % case["customer_uid"], headers=OFFICER, json={
        "result": "REACHED_ANSWERED", "counted": True, "amount_stated": True,
        "next_action": "CALL", "next_action_on": str(BD + timedelta(days=1))})
    assert made.status_code == 201
    assert made.json()["review"] is None
    after = client.get("/v1/reviews").json()["reviews"]
    assert len(after) == len(before)


def test_f3_the_run_sentence_reads_a_thai_date(client, state):
    """BE-3: dd/mm/yyyy, never clock.local_stamp_th (R4-F59 would print the business
    date, 23/10/2026, for a sentence about a past day)."""
    case = next(c for c in state.cases.values()
                if c["payment_status"] == "LATE" and not c["open_issue_uid"] and not c["open_ptp_uid"])
    uid = case["customer_uid"]
    for day in (1, 2, 3):
        client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
            "result": "UNREACHABLE_NO_ANSWER", "counted": False,
            "next_action": "CALL", "next_action_on": str(BD + timedelta(days=day))})
    run = client.get("/v1/cases/by-customer/%s" % uid).json()["unreachable_run"]
    assert "/" in run["note_th"] and "-" not in run["note_th"]
    assert _thai(run["note_th"])


def test_f3_the_unreachable_bucket_finds_the_unreachable(client, state):
    """BE-4: UNREACHABLE was never a member of PRIORITY_REASONS — the bucket found
    nothing, ever, on any book (a confident empty, §1a)."""
    before = client.get("/v1/working-list", params={"bucket": "UNREACHABLE"}).json()
    case = next(c for c in state.cases.values()
                if not c["open_issue_uid"] and not c["open_ptp_uid"] and c["payment_status"] != "CLOSED")
    uid = case["customer_uid"]
    for day in (1, 2, 3):
        client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
            "result": "UNREACHABLE_NO_ANSWER", "counted": False,
            "next_action": "CALL", "next_action_on": str(BD + timedelta(days=day))})
    after = client.get("/v1/working-list", params={"bucket": "UNREACHABLE"}).json()
    assert after["meta"]["total"] >= before["meta"]["total"] + 1
    assert any(i["customer"]["uid"] == uid for i in after["items"])


# --- R4-F31 twins (a): broken_ptp_count -------------------------------------------

def test_the_two_stores_agree_on_broken_promises(client):
    """R4-F54: before this fix, /v1/working-list?bucket=BROKEN_PTP found 1 of 14."""
    today = client.get("/v1/today").json()
    assert today["items"], "the today list is empty"
    for row in today["items"]:
        assert row["broken_ptp_count"] == row["case"]["broken_ptp_count"]
    # 2026-09-20: 150, not 151 — the book's one ended contract (the sheet's
    # Cooperative - Decommission tracking category) is TERMINATED now, and an ended
    # contract is off Today exactly like a closed one.
    assert len(today["items"]) == 150

    listed = client.get("/v1/working-list").json()["items"]
    expected = sum(1 for i in listed if (i["broken_ptp_count"] or 0) > 0)
    assert expected == 14
    bucketed = client.get("/v1/working-list", params={"bucket": "BROKEN_PTP"}).json()
    assert bucketed["meta"]["total"] == expected
    assert all(i["broken_ptp_count"] > 0 for i in bucketed["items"])


# --- next_up (§4.12) ---------------------------------------------------------------

def test_the_working_list_names_which_route_supersedes_its_order(client):
    """Additive, not a fix: both pinning tests (test_journey_rebuild.py's own and
    e2e_check.py's) read items/meta.next_up/meta.counts_by_reason and never touch
    run, so this costs them nothing."""
    run = client.get("/v1/working-list").json()["run"]
    assert run["superseded_by"] == "GET /v1/today — REQ-COL-071 (Amendment v2.6 §3.2) supersedes R11's order"


# --- R4-F63 -------------------------------------------------------------------------

def test_an_installed_row_with_no_invoice_is_never_silently_lost(client):
    """POST /install-outcome {"outcome":"INSTALLED"} on a card with both gates open
    and no invoice used to return 200 and drop the card from the officer's default
    view (measured 108 -> 107 on a fresh seed; leg F's own probe measured 107 -> 106
    on a warmed session — same mechanism, docs/design/round-4/pipeline-gate-order.md).
    Recording the outcome before release is deliberate elsewhere (J3-10 already
    protects POSTPONED the same way) — this is that same mechanism applied to the
    one terminal branch it did not cover. Marker, not a refusal: the fact is kept,
    the card stays visible, and it stays counted."""
    before = client.get("/v1/pipeline").json()
    item = next(i for i in before["items"]
                if i["gate_down_payment"]["state"] != "PASSED"
                and i["gate_epc_confirmed"]["state"] != "PASSED"
                and not i["released_at"])
    before_total = before["meta"]["total"]

    r = client.post("/v1/pipeline/%s/install-outcome" % item["uid"], headers=OFFICER,
                    json={"outcome": "INSTALLED"})
    assert r.status_code == 200, r.json()
    posted = r.json()["item"]
    assert posted["installed_uninvoiced"] is True and _thai(posted["installed_uninvoiced_note_th"])

    after = client.get("/v1/pipeline").json()
    assert after["meta"]["total"] == before_total, "the card must not silently drop out of the default view"
    row = next((i for i in after["items"] if i["uid"] == item["uid"]), None)
    assert row is not None, "the card stays visible with its marker"
    assert row["installed_uninvoiced"] is True and _thai(row["installed_uninvoiced_note_th"])

    # J4-25's own lesson: a row that stays visible must stay counted, or the
    # header's own total lies about the tiers partitioning it.
    counts = after["meta"]["counts"]
    assert counts["late"] + counts["today"] + counts["upcoming"] + counts["moved_out_of_window"] \
        == counts["counted_in_tiers"] == after["meta"]["total"] == len(after["items"])
    assert counts["partitions_total"] and counts["uncounted"] == 0

    # the marker is not a side door to release — the gates still gate it
    release = client.post("/v1/pipeline/%s:release" % item["uid"], json={"by": "nantapol"})
    assert release.status_code == 422 and release.json()["code"] == "gate_not_passed"


# --- reviews evidence (prototype 519-529) -------------------------------------------

def test_review_evidence_serves_the_last_contacts_the_counts_and_the_requesters_words(client, state):
    """The manager's work panel needs the evidence: the case's latest contact
    records, the snapshotted promise counts, and the requester's reason and note.
    Every field is read off a record that already exists; the panel invents none."""
    case = next(c for c in state.cases.values() if not c["open_issue_uid"] and not c["review_uid"])
    uid = case["customer_uid"]
    for day in (1, 2, 3, 4):
        r = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json={
            "result": "UNREACHABLE_NO_ANSWER", "counted": False,
            "next_action": "CALL", "next_action_on": str(BD + timedelta(days=day))})
        assert r.status_code in (200, 201), r.json()
    review = client.post("/v1/cases/by-customer/%s/review-requests" % uid, headers=OFFICER,
                         json={"reason": "UNREACHABLE", "question": "unreachable many times",
                               "question_th": "ติดต่อไม่ได้หลายครั้ง"}).json()["review"]

    listed = next(r for r in client.get("/v1/reviews").json()["reviews"] if r["uid"] == review["uid"])
    ev = listed["evidence"]
    # Four contacts are on the case; the panel takes the latest three, newest first.
    logged = [c for c in state.contact_log if c["customer_uid"] == uid]
    assert len(logged) >= 4
    assert [c["uid"] for c in ev["last_contacts"]] == [c["uid"] for c in reversed(logged[-3:])]
    for c in ev["last_contacts"]:
        assert set(c) >= {"uid", "occurred_at", "officer_uid", "channel", "direction",
                          "result", "result_label_th", "result_label_en", "note", "kind", "counted"}
        assert c["result"] == "UNREACHABLE_NO_ANSWER"
        assert _thai(c["result_label_th"]) and c["result_label_en"] == "Unreachable, no answer"
        assert c["officer_uid"] == "nantapol"

    # The promise counts are the review's own snapshot, not a second count.
    snap = listed["snapshot"]
    assert ev["kept_ptp_count"] == snap["kept_ptp_count"]
    assert ev["broken_ptp_count"] == snap["broken_ptp_count"]

    # The requester's reason and note travel in full.
    assert ev["reason"] == "UNREACHABLE"
    assert ev["reason_label_th"] and ev["reason_label_en"]
    assert ev["note_th"] == "ติดต่อไม่ได้หลายครั้ง"
    assert ev["note_en"] == "unreachable many times"


def test_review_evidence_never_invents_a_contact(client, state):
    """A case that has never been contacted serves an empty list and the screen says
    so — no placeholder row, no borrowed contact from another customer."""
    contact_uids = {c["customer_uid"] for c in state.contact_log}
    case = next(c for c in state.cases.values()
                if c["customer_uid"] not in contact_uids and c["payment_status"] != "CLOSED"
                and not c["review_uid"])
    uid = case["customer_uid"]
    review = client.post("/v1/cases/by-customer/%s/review-requests" % uid, headers=OFFICER,
                         json={"reason": "OTHER", "question_th": "ไม่มีบันทึกการติดต่อ"}).json()["review"]
    listed = next(r for r in client.get("/v1/reviews").json()["reviews"] if r["uid"] == review["uid"])
    assert listed["evidence"]["last_contacts"] == []
    assert listed["evidence"]["note_th"] == "ไม่มีบันทึกการติดต่อ"



# --- Delta-100 D2g — the review row's money, DPD, need and risk -----------------------

def test_review_rows_serve_the_money_dpd_need_sentence_and_risk(client, state):
    """R1/R4/R12/R13 and D2a: the side card joins the same customer aggregate every
    case screen reads; the need sentence is derived from the review's own state, SLA
    and reason (twins written, never composed); the risk score is app.risk's."""
    from app import journey as journey_domain
    from app import risk
    from app.main import _customer_aggregate

    case = next(c for c in state.cases.values()
                if not c["review_uid"] and not c["open_issue_uid"] and c["payment_status"] == "LATE")
    uid = case["customer_uid"]
    made = client.post("/v1/cases/by-customer/%s/review-requests" % uid, headers=OFFICER,
                       json={"reason": "OTHER", "question_th": "ขอให้ผู้จัดการช่วยดู"}).json()["review"]

    def _listed(review_uid):
        return next(r for r in client.get("/v1/reviews").json()["reviews"] if r["uid"] == review_uid)

    row = _listed(made["uid"])
    customer = journey_domain.customer_by_uid(uid)
    arrears, dpd, band, outstanding = _customer_aggregate(customer)
    assert row["aggregate_overdue"] == str(arrears)
    assert row["aggregate_outstanding"] == str(outstanding)
    assert row["oldest_dpd"] == dpd
    assert row["aging_bucket"] == band.code and row["band_set_code"] == band.band_set_code
    last = case["last_contact_at"]
    from datetime import date as _date
    days_since = max(0, (BD - _date.fromisoformat(str(last)[:10])).days) if last else None
    assert row["risk_score"] == risk.score(dpd=dpd, arrears=arrears, outstanding=outstanding,
                                           broken_ptps=case["broken_ptp_count"],
                                           days_since_contact=days_since)
    assert 0 <= row["risk_score"] <= 100
    assert row["age_days"] == row["age_hours"] // 24
    # A plain open request gets the two-business-day twin (prototype 1275).
    assert row["need_basis"] == "OPEN"
    assert row["need_th"] == "ตัดสินภายใน 2 วันทำการ"
    assert row["need_en"] == "Decide within 2 business days"
    # The raw money figure is the list's sort key; the served order stays open-first.
    assert client.get("/v1/reviews").json()["meta"]["row_sort_key"] == "aggregate_overdue"

    # A breached SLA asks for today (prototype 1273).
    state.reviews[made["uid"]]["raised_at_time"] = str(BD - timedelta(days=4)) + "T09:00:00"
    breached = _listed(made["uid"])
    assert breached["sla_breached"] is True
    assert breached["need_basis"] == "SLA_BREACHED" and breached["need_th"] == "ตัดสินภายในวันนี้"
    assert breached["need_en"] == "Decide today"

    # Answering changes the state the sentence is derived from.
    answered = client.post("/v1/reviews/%s:answer" % made["uid"], headers=MANAGER,
                           json={"decision": "CONTINUE", "comment": "ติดตามต่อ"})
    assert answered.status_code == 200, answered.json()
    after = _listed(made["uid"])
    assert after["need_basis"] == "ANSWERED" and _thai(after["need_th"]) and after["need_en"]

    # A board move asks for the reason first; a cut-off request is waiting on O&M even
    # when its SLA has already breached (the prototype's own precedence).
    def _open_case():
        return next(c for c in state.cases.values()
                    if not c["review_uid"] and not c["open_issue_uid"] and c["payment_status"] == "LATE")
    board = cases_domain.request_review(state, _open_case(), "BOARD_MOVE_ASK", "q", by="thip")
    board_row = _listed(board["uid"])
    assert board_row["need_basis"] == "BOARD_MOVE_ASK"
    assert board_row["need_th"] == "อ่านเหตุผลก่อนตัดสิน"
    assert board_row["need_en"] == "Read the reason before deciding"

    power = cases_domain.request_review(state, _open_case(), "POWER_CUTOFF_ASK", "q", by="thip")
    state.reviews[power["uid"]]["raised_at_time"] = str(BD - timedelta(days=4)) + "T09:00:00"
    power_row = _listed(power["uid"])
    assert power_row["sla_breached"] is True
    assert power_row["need_basis"] == "POWER_CUTOFF_ASK" and power_row["need_th"] == "O&M รอคำสั่ง"
    assert power_row["need_en"] == "O&M is waiting on the order"
