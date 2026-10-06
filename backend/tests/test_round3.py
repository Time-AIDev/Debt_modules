"""Blind UAT round 3 — backend findings, one regression per item.

Judge: docs/uat/round-3/judge.md (§1 the evidence, §4 the ordered fix list).
Personas: docs/uat/round-3/{nantapol,thip,settasak}.md.

Customers named here are the ones the judge re-ran:
  sheet-99999000027  ลูกค้าทดสอบ 0028   J3-02 (one LATE cell, one OVERDUE invoice)
  sheet-99999000073  ลูกค้าทดสอบ 0127      J3-03 (three LATE cells, 8,697.00)
  sheet-99999000139  สรายุทธิ์             J3-08 / J3-09 (slip, OD-02 hold, PEAK read-back)
  sheet-99999000179  the cut-off chain     J3-06 / J3-07
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import clock
from app import journey
from app import today as today_domain
from app.config import settings
from app.main import app
from app.money import band_sets

BD = settings.business_date
JIDAPA = "sheet-99999000027"
BANJERD = "sheet-99999000073"
SARAYUT = "sheet-99999000139"
OFFICER = {"X-Volt-Officer": "nantapol"}
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "nantapol"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


@pytest.fixture
def state():
    return cases_domain.for_current()


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


def _detail(client, uid):
    return client.get("/v1/cases/by-customer/%s" % uid).json()


# --- 1. J3-02 + J3-03 — one month axis, and an overdue invoice says overdue ---------

def test_j3_02_03_the_sheet_cells_are_the_one_month_axis(client):
    """The grid, `late_cells` and `link_sent_cells` count the SHEET's month columns;
    `month_index` counted the contract schedule, so a cell the sheet called paid also
    carried an overdue invoice. And an invoice past due read SENT because the sheet's
    LINK_SENT cell overwrote its state."""
    for uid, cells, link, arrears in ((JIDAPA, [26], [27], Decimal("11649.00")),
                                      (BANJERD, [23, 24, 25], [26], Decimal("8697.00"))):
        body = _detail(client, uid)
        contract = body["contracts"][0]
        assert contract["late_cells"] == cells and contract["link_sent_cells"] == link
        overdue = [i for i in body["invoices"] if i["state"] == "OVERDUE"]
        # count and index both come from the cells
        assert sorted(i["month_index"] for i in overdue) == cells
        assert sum(Decimal(i["outstanding"]) for i in overdue) == arrears
        # no cell is both paid and outstanding
        paid_cells = {c["index"] for c in body["month_grid"] if c.get("kind") == "PAID"}
        assert not paid_cells & {i["month_index"] for i in body["invoices"]}
        # the not-yet-due instalment sits on the LINK_SENT cell and carries the link
        assert not any(i["month_index"] == link[0] for i in body["invoices"])
        nxt = [i for i in journey.for_current().invoices.values()
               if i["contract_uid"] == contract["uid"] and i["month_index"] == link[0]]
        assert len(nxt) == 1 and nxt[0]["due_date"] > str(BD) and nxt[0]["link_sent"] is True
        # "link sent" is a fact beside the state, never the state
        for inv in body["invoices"]:
            if inv["due_date"] < str(BD) and Decimal(inv["outstanding"]) > 0:
                assert inv["state"] in ("OVERDUE", "PARTIALLY_PAID"), inv["uid"]
            assert "link_sent" in inv and _thai(inv["link_sent_note_th"])
    # the judge's named row: inv-0061, due 10/10/2026, thirteen days past, reads OVERDUE
    banjerd = _detail(client, BANJERD)
    row = next(i for i in banjerd["invoices"] if i["due_date"] == "2026-10-10")
    assert row["state"] == "OVERDUE" and row["link_sent"] is False


# --- 2. J3-04 — one number per tier -------------------------------------------------

def test_j3_04_the_tier_chips_partition_the_list(client, state):
    body = client.get("/v1/today", headers=OFFICER).json()
    meta = body["meta"]
    assert sum(meta["counts_by_tier"].values()) == meta["total"] == len(body["items"])
    assert meta["counts_by_tier"] == meta["tier_partition"]
    # an answer waiting on a case that sits in a HIGHER tier is reported beside the chip
    target = next(i for i in body["items"] if i["tier"] != "ANSWER_WAITING" and not i["case"]["review_uid"])["customer"]["uid"]
    review = client.post("/v1/cases/by-customer/%s/review-requests" % target,
                         json={"reason": "UNREACHABLE", "question_th": "ขอให้ลงพื้นที่"}, headers=OFFICER).json()["review"]
    client.post("/v1/reviews/%s:answer" % review["uid"], json={"decision": "CONTINUE", "comment": "ลงพื้นที่ได้"}, headers=MANAGER)
    body = client.get("/v1/today", headers=OFFICER).json()
    meta = body["meta"]
    assert sum(meta["counts_by_tier"].values()) == meta["total"]
    assert meta["counts_by_tier"]["ANSWER_WAITING"] + meta["answers_waiting_elsewhere"] == meta["answers_waiting"]
    assert meta["answers_waiting_elsewhere"] >= 1 and _thai(meta["answers_waiting_elsewhere_note_th"])
    # วันนี้ and the weekly report agree on the same business date
    weekly = client.get("/v1/reports/weekly", headers=MANAGER).json()
    team = client.get("/v1/today").json()["meta"]
    assert weekly["counts_by_tier"] == team["counts_by_tier"]


# --- 3. J3-05 — the ladder ranks a cash book too ------------------------------------

def test_j3_05_a_cash_book_is_ranked_and_every_routine_row_says_why(client):
    body = client.get("/v1/today?officer=thip").json()
    assert body["meta"]["next_up"] is not None
    rows = {i["customer"]["display_name"]: i for i in client.get("/v1/today").json()["items"]}
    big = next(i for i in rows.values() if Decimal(i["aggregate_overdue"]) == Decimal("548000.00"))
    small = next(i for i in rows.values() if Decimal(i["aggregate_overdue"]) == Decimal("5580.00"))
    assert big["oldest_dpd"] == 270 and small["oldest_dpd"] == 3
    # a one-invoice cash contract at DPD 270 outranks a three-day arrear
    assert big["tier_rank"] < small["tier_rank"]
    assert _thai(big["missed_basis_th"]) and "270" in big["missed_basis_th"]
    # no invented tier: it ranks inside the seven
    assert big["tier"] in today_domain.TIERS
    for row in client.get("/v1/today").json()["items"]:
        if row["tier"] == "ROUTINE":
            assert _thai(row["tier_reason_th"])
            assert "ติดตามตามรอบ" in row["tier_reason_th"] or "ไม่มียอดค้าง" in row["tier_reason_th"]


# --- 4. J3-06 — a cut-off request is decided, not answered ---------------------------

def _request_cutoff(client, state, evidence_for_power):
    for case in state.cases.values():
        if case["product"] == "LEASE" and case["power_state"] == "ON" and not case["review_uid"]:
            evidence_for_power(case["customer_uid"])
    def _ok(case):
        customer = journey.customer_by_uid(case["customer_uid"])
        if customer is None:
            return False
        missed = max((journey.missed_count(k) for k in customer.contracts), default=0)
        return not [p for p in cases_domain.power_preconditions(state, case, missed) if not p["met"]]

    uid = next(c["customer_uid"] for c in state.cases.values()
               if c["power_state"] == "ON" and not c["review_uid"] and _ok(c))
    r = client.post("/v1/cases/by-customer/%s/power-restriction" % uid,
                    json={"reason": "ค้างหลายงวดและผิดนัด"}, headers=OFFICER)
    assert r.status_code == 201
    return uid, state.cases[uid]


def test_j3_06_a_cutoff_review_takes_only_approve_or_reject_from_the_approver(client, state, evidence_for_power):
    uid, case = _request_cutoff(client, state, evidence_for_power)
    review_uid = case["review_uid"]
    # the card offers only the two decisions, and only to the approver named by OQ-44
    as_manager = next(r for r in client.get("/v1/reviews", headers=MANAGER).json()["reviews"] if r["uid"] == review_uid)
    assert as_manager["approver_role"] == settings.power_restriction_approver == "OWNER"
    assert as_manager["decisions"] == [] and _thai(as_manager["decision_note_th"])
    as_owner = next(r for r in client.get("/v1/reviews", headers=OWNER).json()["reviews"] if r["uid"] == review_uid)
    assert [d["code"] for d in as_owner["decisions"]] == list(cases_domain.POWER_DECISIONS)
    # CONTINUE from a Manager is refused, and the refusal names the approver
    r = client.post("/v1/reviews/%s:answer" % review_uid, json={"decision": "CONTINUE", "comment": "ติดตามต่อ"}, headers=MANAGER)
    assert r.status_code == 422 and r.json()["code"] == "power_decision_required"
    assert r.json()["extensions"]["approver_role"] == "OWNER" and "เจ้าของ" in r.json()["message_th"]
    assert case["power_state"] == "RESTRICTION_REQUESTED" and state.reviews[review_uid]["status"] == "OPEN"
    # CONTINUE from the Owner is refused too: the request is decided, not answered
    r = client.post("/v1/reviews/%s:answer" % review_uid, json={"decision": "CONTINUE"}, headers=OWNER)
    assert r.status_code == 422 and r.json()["code"] == "power_decision_required"
    # APPROVE from a Manager is refused on the role
    r = client.post("/v1/reviews/%s:answer" % review_uid, json={"decision": "POWER_CUTOFF_APPROVE"},
                    headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak", "X-Volt-Sign-As": "settasak"})
    assert r.status_code in (403, 422)
    # REJECT from the Owner closes it: the power goes back to ON with an event
    r = client.post("/v1/reviews/%s:answer" % review_uid,
                    json={"decision": "POWER_CUTOFF_REJECT", "comment": "ยังไม่ตัด รอเจรจาอีกครั้ง"}, headers=OWNER)
    assert r.status_code == 200
    assert case["power_state"] == "ON" and case["power_uid"] is None
    assert any(e["kind"] == "POWER_REJECTED" for e in state.events if e.get("case_uid") == case["uid"])


# --- 5. J3-07 — the cut-off can be executed and restored after approval --------------

def test_j3_07_every_power_state_has_a_thai_label_and_the_lifecycle_exists(client, state, evidence_for_power):
    # every value in POWER_STATES has a Thai label, served by the API
    served = {row["code"]: row["label_th"] for row in client.get("/v1/config", headers=MANAGER).json()["power_states"]}
    assert set(served) == set(cases_domain.POWER_STATES)
    assert all(_thai(v) for v in served.values())

    uid, case = _request_cutoff(client, state, evidence_for_power)
    detail = _detail(client, uid)["case"]
    assert detail["power_next_act"]["act"] == "approve" and detail["power_next_act"]["roles"] == ["OWNER"]
    client.post("/v1/reviews/%s:answer" % case["review_uid"], json={"decision": "POWER_CUTOFF_APPROVE"}, headers=OWNER)
    assert case["power_state"] == "RESTRICTION_APPROVED"
    detail = _detail(client, uid)["case"]
    assert detail["power_state_label_th"] == "อนุมัติตัดไฟแล้ว รอดำเนินการ"
    assert detail["power_next_act"]["act"] == "execute" and "OPS" in detail["power_next_act"]["roles"]
    pwr = case["power_uid"]
    # an officer may not cut the power; O&M / a Supervisor may
    assert client.post("/v1/power-restrictions/%s:execute" % pwr, headers=OFFICER).status_code == 403
    r = client.post("/v1/power-restrictions/%s:execute" % pwr, json={}, headers={"X-Volt-Role": "OPS", "X-Volt-Officer": "om"})
    assert r.status_code == 200 and case["power_state"] == "RESTRICTED"
    detail = _detail(client, uid)["case"]
    assert detail["power_state_label_th"] == "ตัดไฟแล้ว" and detail["power_next_act"]["act"] == "restore"
    r = client.post("/v1/power-restrictions/%s:restore" % pwr, json={}, headers={"X-Volt-Role": "SUPERVISOR", "X-Volt-Officer": "ops"})
    assert r.status_code == 200 and case["power_state"] == "ON"
    kinds = [e["kind"] for e in state.events if e.get("case_uid") == case["uid"]]
    assert "POWER_REQUESTED" in kinds and "POWER_APPROVED" in kinds
    assert "POWER_EXECUTED" in kinds and "POWER_RESTORED" in kinds


# --- 6. J3-08 — the OD-02 hold sits beside the money --------------------------------

def test_j3_08_a_confirmed_receipt_does_not_make_the_case_read_paid(client, state):
    body = _detail(client, SARAYUT)
    invoice = next(i for i in body["invoices"] if Decimal(i["outstanding"]) > 0)
    r = client.post("/v1/slips", json={"invoice_uid": invoice["uid"], "amount": invoice["outstanding"]}, headers=OFFICER)
    assert r.status_code in (200, 201)
    case = state.cases[SARAYUT]
    after = _detail(client, SARAYUT)
    assert Decimal(after["work_item"]["aggregate_overdue"]) == 0
    assert after["work_item"]["money_position"]["review_required"] is True
    assert case["dc_status"] != "PAID"
    assert case["allocation_hold"] is True
    assert case["allocation_hold_note_th"] == "ยอดค้างยังไม่เปลี่ยน — รอบัญชีตัดสินลำดับการจัดสรร"
    assert after["case"]["allocation_hold_note_th"] == case["allocation_hold_note_th"]
    assert after["allocation_hold_note_th"] == case["allocation_hold_note_th"]


# --- 7. J3-09 — the case reads the PEAK state back ----------------------------------

def test_j3_09_the_case_and_the_queue_agree_on_the_peak_state(client, state):
    body = _detail(client, SARAYUT)
    invoice = next(i for i in body["invoices"] if Decimal(i["outstanding"]) > 0)
    receipt = client.post("/v1/slips", json={"invoice_uid": invoice["uid"], "amount": invoice["outstanding"]},
                          headers=OFFICER).json()["receipt"]
    client.post("/v1/peak-documents/stub", json={"on": True}, headers=OWNER)
    client.post("/v1/peak-documents:refresh-all")
    queue = {d["uid"]: d for d in client.get("/v1/peak-documents").json()["documents"]}
    on_case = next(r for r in _detail(client, SARAYUT)["receipts"] if r["uid"] == receipt["uid"])
    doc = queue[on_case["peak_document_uid"]]
    assert on_case["peak_state"] == doc["state"]
    assert on_case["peak_number"] == doc["peak_number"]
    assert on_case["peak_state_note_th"] == doc["state_note_th"]


# --- 8. J3-10 — a postponed row is never silently lost ------------------------------

def test_j3_10_a_row_moved_out_of_the_window_keeps_its_marker(client):
    before = client.get("/v1/pipeline").json()
    item = next(i for i in before["items"] if not i["released_at"])
    new_on = str(BD + timedelta(days=13))
    r = client.post("/v1/pipeline/%s/install-outcome" % item["uid"],
                    json={"outcome": "POSTPONED", "new_install_on": new_on}, headers=OFFICER)
    assert r.status_code == 200
    row = r.json()["item"]
    assert row["moved_out_of_window"] is True and _thai(row["moved_note_th"])
    assert "ย้ายออกนอกช่วง" in row["moved_note_th"] and new_on[8:10] + "/" + new_on[5:7] in row["moved_note_th"]
    after = client.get("/v1/pipeline").json()
    assert any(i["uid"] == item["uid"] for i in after["items"]), "the card stays visible with its marker"
    # counts.beyond is computed over the whole book, not the filtered rows
    everything = client.get("/v1/pipeline?all=true").json()["meta"]["counts"]
    assert after["meta"]["counts"]["beyond"] == everything["beyond"] > 0
    assert after["meta"]["counts"]["beyond_scope"] == "whole_book"


# --- 9. J3-11 + J3-38 — bands say plainly they cannot be edited, and come back -------

def test_j3_11_38_bands_are_not_editable_and_a_set_can_be_reactivated(client):
    body = client.get("/v1/band-sets", headers=MANAGER).json()
    assert body["editable"] is False
    assert body["edit_refusal_th"] == "แก้ไขไม่ได้ — สร้างชุดใหม่แล้วเปลี่ยนชุดที่ใช้"
    for row in body["band_sets"]:
        assert row["editable"] is False and row["reason_th"] == body["edit_refusal_th"]
    # the report's chooser marks a deactivated set instead of offering it silently
    assert client.post("/v1/band-sets/LEGACY_SHEET:deactivate", json={}, headers=MANAGER).status_code == 200
    chooser = {c["code"]: c for c in client.get("/v1/band-sets", headers=MANAGER).json()["chooser"]}
    assert chooser["LEGACY_SHEET"]["active"] is False and "ปิดใช้งาน" in chooser["LEGACY_SHEET"]["label_th"]
    assert _thai(chooser["LEGACY_SHEET"]["note_th"])
    flow = client.get("/v1/reports/bucket-flow?band_set=LEGACY_SHEET", headers=MANAGER).json()
    assert flow["band_set_active"] is False and _thai(flow["band_set_note_th"])
    # J3-38: one click, and a way back
    assert client.post("/v1/band-sets/LEGACY_SHEET:activate", json={}, headers=OFFICER).status_code == 403
    r = client.post("/v1/band-sets/LEGACY_SHEET:activate", json={}, headers=MANAGER)
    assert r.status_code == 200 and r.json()["band_set"]["active"] is True
    assert band_sets.SET_HISTORY[-1]["act"] == "ACTIVATE"


# --- 10. J3-12 — a period stamp means the period -------------------------------------

def test_j3_12_the_officer_table_counts_inside_its_own_period(client, state):
    body = client.get("/v1/reports/officers", headers=MANAGER).json()
    meta = body["meta"]
    assert meta["period_scope"] == "IN_PERIOD" and _thai(meta["period_note_th"])
    assert set(meta["period_basis"]) == {"contacts", "counted_contacts", "ptps_taken", "ptps_kept", "ptps_broken"}
    start, end = meta["period"].split("..")
    for row in body["officers"]:
        assert row["period"] == meta["period"]
        # nothing in the period columns can exceed the all-time figure beside it
        assert row["contacts"] <= row["contacts_all_time"]
        assert row["ptps_broken"] <= row["ptps_broken_all_time"]
        # the July promises the judge saw are outside the week and no longer counted
        broken_in_period = [p for p in state.ptps.values() if p["status"] == "BROKEN"
                            and start <= str(p.get("broken_detected_at") or p.get("closed_on") or "")[:10] <= end]
        assert row["ptps_broken"] <= len(broken_in_period)


# --- 11. the P3 backend halves -------------------------------------------------------

def test_j3_13_batch_label_is_authoritative_and_names_the_cf1_conflict(client):
    meta = client.get("/v1/today/reminders?days=21", headers=OFFICER).json()["meta"]
    assert meta["batch_label"] == "D-3 / D0" and meta["batch_label_authoritative"] is True
    assert _thai(meta["batch_label_note_th"])
    conflict = meta["offsets_conflict"]
    assert conflict["app"] == "3,0" and conflict["sop"] == "1,0" and conflict["open_question"] == "CF1"
    assert "D-1" in conflict["note_th"] and _thai(conflict["note_th"])


def test_j3_15_the_contact_lock_refusal_quotes_the_business_day_in_local_time(client):
    payload = {"customer_uid": JIDAPA, "channel": "PHONE", "direction": "OUTBOUND",
               "disposition": "ANS_DISCUSSED", "at": "2026-09-02T17:42:30+00:00", "officer": "nantapol"}
    assert client.post("/v1/contacts", json=payload).status_code == 201
    second = client.post("/v1/contacts", json={**payload, "at": "2026-09-02T18:10:00+00:00"})
    assert second.status_code == 409 and second.json()["code"] == "contact_locked"
    body = second.json()
    day = "%02d/%02d/%d" % (BD.day, BD.month, BD.year)
    assert day in body["message_th"] and "+00:00" not in body["message_th"]
    assert body["extensions"]["locked_at_local_th"].startswith(day)
    assert body["extensions"]["business_date"] == str(BD)


def test_j3_16_a_seeded_next_action_says_why_it_does_not_raise_the_tier(client):
    items = client.get("/v1/today", headers=OFFICER).json()["items"]
    seeded = [i for i in items if i["case"]["next_action_set_by"] in ("SEED", "SYSTEM")
              and i["case"]["next_action_on"] and i["tier"] != "NEXT_ACTION_DUE"]
    assert seeded
    for row in seeded:
        note = row["next_action_tiering"]
        assert note["counts_as_tier"] is False and _thai(note["reason_th"])
        assert note["set_by"] in ("SEED", "SYSTEM")
    counted = [i for i in items if i["tier"] == "NEXT_ACTION_DUE"]
    assert all(i["next_action_tiering"]["counts_as_tier"] for i in counted)


def test_j3_17_the_days_gap_names_the_snapshot_date_and_the_grace(client):
    block = _detail(client, JIDAPA)["sheet_reconciliation"]
    assert block["sheet_snapshot_date"] == "2026-09-02" and block["business_date"] == str(BD)
    assert block["sheet_days_late"] == 54 and block["app_oldest_dpd"] is None
    assert block["late_payment_grace_days"] == settings.late_payment_grace_days == 0
    assert "02/09/2026" in block["note_th"] and "23/10/2026" in block["note_th"]
    assert "ระยะผ่อนผัน 0 วัน" in block["note_th"] and "OD-31" not in block["note_th"]


def test_j3_18_the_fee_freezes_where_it_stands_when_the_ticket_opens(client, state):
    from app import main
    case = next(c for c in state.cases.values()
                if c["payment_status"] == "LATE" and not c["open_issue_uid"] and c["product"] == "LEASE")
    contract = journey.customer_by_uid(case["customer_uid"]).contracts[0]
    _c, _dpd, _b, before, _p = main._contract_view(contract, as_of=BD)
    r = client.post("/v1/cases/by-customer/%s/contacts" % case["customer_uid"],
                    json={"result": "SERVICE_ISSUE", "counted": True, "channel": "PHONE",
                          "issue": {"summary": "อินเวอร์เตอร์ดับ", "responsible_team": "O_AND_M"}}, headers=OFFICER)
    assert r.status_code == 201
    issue = r.json()["issue"]
    _c, _dpd, _b, during, _p = main._contract_view(contract, as_of=BD)
    assert during.penalty_accrued_unbilled == before.penalty_accrued_unbilled, "the freeze holds the number"
    assert issue["fee_frozen_at_on"] == str(BD) and str(BD) in issue["fee_clock_note_th"]
    closed = client.post("/v1/case-issues/%s:close" % issue["uid"],
                         json={"resolution_note": "O&M เปลี่ยนอินเวอร์เตอร์แล้ว"}, headers=OFFICER).json()["issue"]
    _c, _dpd, _b, after, _p = main._contract_view(contract, as_of=BD)
    assert after.penalty_accrued_unbilled == before.penalty_accrued_unbilled
    assert str(BD) in closed["fee_clock_note_th"]
    contract.fee_state, contract.fee_state_from, contract.fee_state_until, contract.fee_state_history = None, None, None, []


def test_j3_19_one_clock_stamps_the_business_day_in_working_hours(client, state):
    r = client.post("/v1/cases/by-customer/%s/contacts" % BANJERD,
                    json={"result": "UNREACHABLE_NO_ANSWER", "counted": False, "channel": "PHONE",
                          "next_action": "CALL", "next_action_on": str(BD + timedelta(days=1))}, headers=OFFICER)
    assert r.status_code == 201
    rows = [x for x in state.contact_log if x["customer_uid"] == BANJERD and x["source"] != "MAPLOG_IMPORT"]
    stamps = [x["occurred_at"] for x in rows]
    assert stamps and all(s.startswith(str(BD)) for s in stamps)
    for s in stamps:
        assert clock.DAY_OPENS.strftime("%H:%M:%S") <= s[11:] <= clock.DAY_CLOSES.strftime("%H:%M:%S")
        assert not s.endswith("23:59:00") and s[11:16] not in ("00:09", "00:10", "23:59")
    # and the clock never runs backwards
    a, b = clock.stamp(), clock.stamp()
    assert a < b


def test_j3_24_a_broken_promise_clears_the_extend_payment_status(client, state):
    case = next(c for c in state.cases.values()
                if c["payment_status"] == "LATE" and not c["open_ptp_uid"] and not c["open_issue_uid"])
    ptp = cases_domain._make_ptp(state, case, "1000", str(BD + timedelta(days=3)), created_by="nantapol", source="CALL")
    cases_domain.derive_dc_status(state, case, "PTP")
    assert case["dc_status"] in ("EXTEND_PAYMENT_TO", "PTP")
    cases_domain.close_ptp(state, case, ptp["uid"], "BROKEN", BD, by="nantapol")
    assert case["dc_status"] not in ("EXTEND_PAYMENT_TO", "PTP")
    assert "ผิดนัด" in case["dc_status_reason_th"] and case["dc_status_set_by"] == "SYSTEM"


def test_j3_28_the_penalty_sentence_carries_the_grace(client):
    money = _detail(client, BANJERD)["work_item"]["money_position"]
    assert money["penalty_grace_days"] == 0
    assert "ระยะผ่อนผัน 0 วัน" in money["note_th"] and "OD-31" not in money["note_th"]
    assert money["penalty_formula_th"] == "ยอดค้าง × 0.03%/วัน × (จำนวนวันค้าง − 0)"


def test_j3_30_a_released_invoice_is_never_already_late(client):
    rows = client.get("/v1/pipeline?all=true").json()["items"]
    item = next(r for r in rows if (r["planned_install_on"] or "") < str(BD) and not r["released_at"])
    client.post("/v1/pipeline/%s/gates/down-payment" % item["uid"], json={"receipt_ref": "slip-x", "amount": "5000"})
    client.post("/v1/pipeline/%s/gates/epc-confirmed" % item["uid"], json={"confirmed_on": item["planned_install_on"]})
    # Delta-100 D2h: contract_signed is one of the prototype's three release
    # conditions and has no source document — attached evidence is its only path.
    client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % item["uid"],
                json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    # a due date already past is refused outright when a person names it
    bad = client.post("/v1/pipeline/%s:release" % item["uid"], json={"due_date": str(BD - timedelta(days=5))}, headers=OFFICER)
    assert bad.status_code == 422 and bad.json()["code"] == "due_date_in_past"
    r = client.post("/v1/pipeline/%s:release" % item["uid"], json={}, headers=OFFICER)
    assert r.status_code == 201
    invoice = r.json()["invoice"]
    assert invoice["due_date"] >= str(BD)
    assert invoice["due_date_source"] == "adjusted_from_install_date"
    assert _thai(invoice["due_date_note_th"]) and item["planned_install_on"] in invoice["due_date_note_th"]


def test_j3_31_every_contact_result_says_why_it_counts_or_does_not(client):
    rows = client.get("/v1/dictionaries/CONTACT_RESULT").json()
    values = rows.get("values") or rows.get("dictionary") or rows.get("CONTACT_RESULT")
    for row in values:
        assert _thai(row["counts_reason_th"]), row["code"]
    answered = next(r for r in values if r["code"] == "CALLBACK_REQUESTED")
    assert answered["counts"] is False and "ยังไม่ได้ทวงถาม" in answered["counts_reason_th"]


def test_j3_34_a_pre_install_customer_gets_a_case_when_an_invoice_is_released(client, state):
    rows = client.get("/v1/pipeline?all=true").json()["items"]
    item = next(r for r in rows if not r["released_at"])
    # 2026-09-20: the case exists from the moment the card does. The case page is
    # where the conditions, their evidence and the release finish; before the release
    # the case exists but does not count on the book (pipeline_released stays False).
    fresh = client.get("/v1/cases/by-customer/%s" % item["customer_uid"])
    assert fresh.status_code == 200
    assert fresh.json()["pre_install"] is True
    assert fresh.json()["case"]["opened_from"] == "PRE_INSTALL_CARD"
    assert fresh.json()["case"]["pipeline_released"] is False
    assert fresh.json()["pipeline_item"]["uid"] == item["uid"]
    assert [c["key"] for c in fresh.json()["pipeline_item"]["conditions"]] == \
        ["contract_signed", "down_payment", "entity_resolved"]

    client.post("/v1/pipeline/%s/gates/down-payment" % item["uid"], json={"receipt_ref": "slip-y", "amount": "5000"})
    client.post("/v1/pipeline/%s/gates/epc-confirmed" % item["uid"], json={"confirmed_on": str(BD)})
    client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % item["uid"],
                json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    r = client.post("/v1/pipeline/%s:release" % item["uid"], json={}, headers=OFFICER)
    assert r.status_code == 201 and r.json()["item"]["has_case"] is True
    detail = client.get("/v1/cases/by-customer/%s" % item["customer_uid"])
    assert detail.status_code == 200
    body = detail.json()
    assert body["pre_install"] is True and _thai(body["pre_install_note_th"])
    assert body["case"]["pipeline_released"] is True and body["invoices"]
    assert body["case"]["opened_from"] == "PRE_INSTALL_CARD"
    assert body["pipeline_item"]["uid"] == item["uid"]
    events = [e["kind"] for e in state.events if e.get("case_uid") == body["case"]["uid"]]
    assert "CASE_OPENED" in events and "INVOICE_RELEASED" in events
    assert body["case"]["next_action"] == "SEND_INVOICE_LINK"


# --- reviews evidence (prototype 519-529) -------------------------------------------

def test_a_review_serves_the_evidence_block_even_when_the_contact_log_is_empty(client, state):
    """The manager's work panel reads one `evidence` object per review. On a case
    nobody has contacted, the contact list is served EMPTY — no placeholder contact,
    no borrowed one — while the snapshot's promise counts and the requester's own
    reason still travel."""
    contacted = {r["customer_uid"] for r in state.contact_log}
    uid = next(c["customer_uid"] for c in state.cases.values()
               if not c["review_uid"] and c["customer_uid"] not in contacted)
    review = client.post("/v1/cases/by-customer/%s/review-requests" % uid,
                         json={"reason": "OTHER", "question_th": "ขอตรวจเคสนี้"}, headers=OFFICER).json()["review"]
    row = next(r for r in client.get("/v1/reviews").json()["reviews"] if r["uid"] == review["uid"])
    ev = row["evidence"]
    assert ev["last_contacts"] == []
    assert ev["kept_ptp_count"] == row["snapshot"]["kept_ptp_count"]
    assert ev["broken_ptp_count"] == row["snapshot"]["broken_ptp_count"]
    assert ev["reason"] == "OTHER" and _thai(ev["reason_label_th"])
    assert ev["note_th"] == "ขอตรวจเคสนี้"



# --- Delta-100 D2h — EPC keeps its data, loses its vote --------------------------------

def test_epc_date_is_not_a_release_gate_but_the_after_release_card_still_reads_it(client):
    """The prototype's gate set is contract signed / down payment / issuing company
    (563-578). The EPC date stays on the row — the after-release card reads it — but
    a confirmed EPC no longer substitutes for the contract evidence."""
    rows = client.get("/v1/pipeline?all=true").json()["items"]
    item = next(r for r in rows if not r["released_at"] and r["entity"] and r["amount_due"])
    uid = item["uid"]
    client.post("/v1/pipeline/%s/gates/down-payment" % uid,
                json={"slip_ref": "slip-d100-r3", "amount": item["amount_due"], "by": "thip"})
    assert client.post("/v1/pipeline/%s/gates/epc-confirmed" % uid,
                       json={"confirmed_on": str(BD), "source": "ODOO"}).status_code == 200

    refused = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"})
    assert refused.status_code == 422 and refused.json()["code"] == "gate_not_passed"
    assert refused.json()["extensions"]["gates"] == ["contract_signed"], \
        "the EPC date must not appear among the gates any more"
    assert client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                       json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"}).status_code == 201
    released = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"})
    assert released.status_code == 201, released.json()
    row = released.json()["item"]
    assert row["gate_epc_confirmed"]["state"] == "PASSED" and row["confirmed_install_on"] == str(BD)
    assert all(c["state"] == "PASSED" for c in row["conditions"])
