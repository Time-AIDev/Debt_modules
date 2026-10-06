"""Blind UAT round 2 — backend findings, one regression per item.

Persona reports: docs/uat/round-2/{nantapol,thip,settasak}.md. Customers named
here are the ones the personas worked (all from the migrated sheet):
  sheet-99999000140  ลูกค้าทดสอบ 0153 (1)   N2-03 / N2-04
  sheet-99999000146  ลูกค้าทดสอบ 0153 (2)   her other contract
  sheet-99999000073  ลูกค้าทดสอบ 0127      S2-03 (refused power request)
  sheet-99999000158  ลูกค้าทดสอบ 0157      N2-08 (dropped out of BROKEN_PTP)
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import journey
from app import peak_documents as pkd
from app.config import settings
from app.main import app

BD = settings.business_date
PAT1, PAT2 = "sheet-99999000140", "sheet-99999000146"
BANJERD, SUKRI = "sheet-99999000073", "sheet-99999000158"
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER_AS_MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "nantapol"}
OFFICER_AS_OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "nantapol"}


@pytest.fixture
def client():
    # The client and the `state` fixture look at the SAME session: the middleware keys
    # state by the volt_session cookie, and the test process sits in the shared one.
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


def _today_item(client, uid):
    return next(i for i in client.get("/v1/today").json()["items"] if i["customer"]["uid"] == uid)


def _a_case(state, **where):
    for case in state.cases.values():
        if all(case.get(k) == v for k, v in where.items()):
            return case
    raise AssertionError("no case matches %r" % where)


def _contact(client, uid, result, **extra):
    body = {"result": result, "counted": False, **extra}
    return client.post("/v1/cases/by-customer/%s/contacts" % uid, json=body, headers={"X-Volt-Officer": "nantapol"})


# --- 1. N2-03 ---------------------------------------------------------------------

def test_n2_03_one_instalment_figure_per_contract_and_the_header_sums_them(client):
    """ปัทมวรรณ (1): the grid, the old promise, the header, the invoices and the contract
    all say 5,799.00; the note is flagged as her other contract's; the sibling is linked."""
    d = _detail(client, PAT1)
    k = d["contracts"][0]
    assert k["pmt"] == "5799.00" and "most frequent paid month cell" in k["derivation"]["pmt"]
    assert k["month_grid"] == d["month_grid"] and k["sheet_row"] == d["sheet_row"]
    assert all(cell["contract_uid"] == k["uid"] for cell in d["month_grid"])
    assert all(inv["amount"] == "5799.00" for inv in d["invoices"])
    assert d["ptps"][0]["promised_amount"] == "5799.00"
    # footer cells that differ from the instalment differ from 5,799 (25,299 = +19,500)
    odd = {c["index"]: c["diff_from_pmt"] for c in d["month_grid"] if c.get("diff_from_pmt")}
    assert odd and odd[min(odd)] == "19500.00"
    mp = d["work_item"]["money_position"]
    assert mp["per_contract"][0]["uid"] == k["uid"] and mp["contract_count"] == 1
    assert Decimal(mp["instalments_overdue"]) == sum(Decimal(c["instalments_overdue"]) for c in mp["per_contract"]) == Decimal("0.00")
    assert mp["review_required"] is True
    assert d["work_item"]["aggregate_overdue"] == "0.00"
    assert d["case"]["sheet"]["comment_ref_no"] == "99999000146" and "99999000146" in d["case"]["sheet"]["comment_note_th"]
    assert [r["customer_uid"] for r in d["related_cases"]] == [PAT2] and _thai(d["related_cases"][0]["note_th"])
    # her other contract keeps its own instalment
    assert _detail(client, PAT2)["contracts"][0]["pmt"] == "25299.00"


# --- 2. N2-04 ---------------------------------------------------------------------

def test_n2_04_invoices_and_missed_count_follow_the_month_grid(client):
    d = _detail(client, PAT1)
    k = d["contracts"][0]
    late = [c["index"] for c in d["month_grid"] if c.get("kind") == "LATE"]
    assert late == [26] and k["late_cells"] == late
    overdue = [i for i in d["invoices"] if i["state"] == "OVERDUE"]
    assert [i["month_index"] for i in overdue] == late and overdue[0]["due_date"] == "2026-10-10"
    assert _today_item(client, PAT1)["missed_count"] == 0
    assert _today_item(client, PAT1)["money_position"]["review_required"] is True
    assert "LATE month cell" in k["derivation"]["invoices"] and "LATE month cells" in k["derivation"]["paid_through"]
    # no LINK_SENT cell: the next instalment is ISSUED and claims no link, no invented date
    assert not any(i["state"] == "ISSUED" for i in d["invoices"])
    nxt = next(i for i in journey.for_current().invoices.values()
               if i["contract_uid"] == k["uid"] and i["state"] == "ISSUED")
    assert nxt["month_index"] == 27 and nxt["link_sent"] is False and nxt["link_sent_on"] is None
    # somewhere in the book a LINK_SENT cell exists: that month's invoice is SENT and says the sheet said so
    jstate = journey.for_current()
    linked = [i for i in jstate.invoices.values() if i.get("link_sent")]
    assert linked and all(i["state"] == "SENT" and i["link_sent_source"] == "SHEET_CELL" and _thai(i["link_sent_note_th"]) for i in linked)
    for inv in linked:
        contract = journey.contract_by_uid(inv["contract_uid"])[1]
        assert inv["month_index"] in contract.link_sent_cells


# --- 3. N2-05 ---------------------------------------------------------------------

def test_n2_05_third_renegotiation_is_recorded_and_escalated_the_fourth_is_a_named_409(client, state):
    case = _a_case(state, payment_status="LATE", open_ptp_uid=None, review_uid=None, open_issue_uid=None, broken_ptp_count=0)
    uid = case["customer_uid"]
    r = _contact(client, uid, "REACHED_PTP", counted=True, amount_stated=True, ptp={"amount": "1000", "date": str(BD + timedelta(days=3))})
    assert r.status_code == 201
    ptp = r.json()["ptp"]
    for n, days in enumerate((6, 9, 12), start=1):
        # Round-4 J4-02: a renegotiation is a contact and now spends the same daily slot
        # as the drawer. The first call of the day counts; the second and third on the
        # same customer are recorded as declared not-counted contacts.
        r = client.post("/v1/case-ptps/%s:renegotiate" % ptp["uid"],
                        json={"amount": "1000", "date": str(BD + timedelta(days=days)), "not_counted": n > 1},
                        headers={"X-Volt-Officer": "nantapol"})
        assert r.status_code == 201, r.json()
        body = r.json()
        assert body["ptp"]["status"] == "OPEN" and body["renegotiation_count"] == n == body["ptp"]["renegotiation_count"]
        assert body["previous_ptp"]["uid"] == ptp["uid"] and body["ptp"]["promise_date"] == str(BD + timedelta(days=days))
        assert body["case"]["open_ptp_uid"] == body["ptp"]["uid"]
        if n < 3:
            assert body["review"] is None and body["escalated"] is False
        else:
            assert body["escalated"] and body["review"]["reason"] == "REPEATED_BROKEN_PTP" and body["review"]["ptp_uid"] == body["ptp"]["uid"]
            assert cases_domain.THIRD_RENEGOTIATION_TH in body["message_th"]
        ptp = body["ptp"]
    events = [e for e in _detail(client, uid)["events"] if e["kind"] == "PTP_RENEGOTIATED"]
    assert len(events) == 3 and events[-1]["old_date"] == str(BD + timedelta(days=9)) and events[-1]["new_date"] == str(BD + timedelta(days=12))
    # a fourth while the Manager has not answered: refused, the rule named, the date kept
    r = client.post("/v1/case-ptps/%s:renegotiate" % ptp["uid"], json={"amount": "1000", "date": str(BD + timedelta(days=20))})
    assert r.status_code == 409 and r.json()["code"] == "renegotiation_awaiting_review"
    assert cases_domain.THIRD_RENEGOTIATION_TH in r.json()["message_th"] and r.json()["extensions"]["review_uid"]
    assert state.ptps[ptp["uid"]]["status"] == "OPEN" and state.ptps[ptp["uid"]]["promise_date"] == str(BD + timedelta(days=12))


# --- 4. N2-07 / T2-08 -------------------------------------------------------------

def test_n2_07_open_service_issue_freezes_fee_and_dpd_until_closure(client, state):
    from app import main
    candidates = [c for c in state.cases.values() if c["payment_status"] == "LATE" and not c["open_issue_uid"]]
    case = next(c for c in candidates if (_today_item(client, c["customer_uid"])["oldest_dpd"] or 0) >= 20)
    uid = case["customer_uid"]
    contract = journey.customer_by_uid(uid).contracts[0]
    _c, dpd_before, _b, block_before, _p = main._contract_view(contract, as_of=BD)
    _c, dpd_ctl, _b, block_ctl, _p = main._contract_view(contract, as_of=BD + timedelta(days=10))
    assert dpd_ctl == dpd_before + 10 and block_ctl.penalty_accrued_unbilled > block_before.penalty_accrued_unbilled
    r = _contact(client, uid, "SERVICE_ISSUE", counted=True, issue={"summary": "อินเวอร์เตอร์ดับ", "responsible_team": "O_AND_M",
                                                                  "ticket_url": "https://cx.volt.co.th/tickets/12345"})
    assert r.status_code == 201
    issue = r.json()["issue"]
    # Round-3 J3-18: a freeze that starts today HOLDS the number where it stands. The
    # opening day still accrues; the pause runs from the day after, and the panel names
    # both dates. (Before, the fee fell one day's worth the moment the ticket opened.)
    assert issue["fee_clock"] == "PAUSED" and issue["fee_clock_from"] == str(BD)
    assert issue["fee_frozen_at_on"] == str(BD) and str(BD) in issue["fee_clock_note_th"]
    # Ruling 46a: fee_state and its siblings are per-session overlay fields since
    # ruling 43 / R4-F01 (cases.py:121-150) — read through the accessor, never the
    # raw attribute, which the product no longer writes. This `client` fixture is
    # pinned to the "shared" session (line 35), matching the ContextVar default a
    # direct (non-request) call resolves to, so the overlay slot the POST above
    # wrote into is the same one read here.
    assert cases_domain.fee_state_of(contract) == "SERVICE_HOLD_FAULT_CONFIRMED" and \
        cases_domain.fee_state_of(contract, "fee_state_from") == BD
    assert _detail(client, uid)["contracts"][0]["fee_state_from"] == str(BD)
    _c, dpd0, _b, block0, _p = main._contract_view(contract, as_of=BD)
    assert dpd0 == dpd_before and block0.penalty_accrued_unbilled == block_before.penalty_accrued_unbilled
    saved = settings.business_date
    try:
        settings.business_date = BD + timedelta(days=10)
        _c, dpd1, _b, block1, _p = main._contract_view(contract, as_of=settings.business_date)
        assert dpd1 == dpd0 + 10 and block1.penalty_accrued_unbilled == block0.penalty_accrued_unbilled
        r = client.post("/v1/case-issues/%s:close" % issue["uid"], json={"resolution_note": "O&M เปลี่ยนอินเวอร์เตอร์แล้ว"},
                        headers={"X-Volt-Officer": "nantapol"})
        assert r.status_code == 200
        closed = r.json()["issue"]
        assert closed["fee_clock"] == "RESUMED" and closed["fee_clock_until"] == str(settings.business_date)
        assert str(BD) in closed["fee_clock_note_th"] and str(settings.business_date) in closed["fee_clock_note_th"]
        assert str(BD) in closed["fee_clock_note_th"]                 # J3-18: frozen at the opening day
        assert cases_domain.fee_state_of(contract) is None and \
            cases_domain.fee_state_of(contract, "fee_state_history")[-1]["until"] == settings.business_date
        # the clock runs again after closure; the ten paused days stay paused
        _c, dpd2, _b, block2, _p = main._contract_view(contract, as_of=settings.business_date + timedelta(days=10))
        assert dpd2 == dpd0 + 10 and block2.penalty_accrued_unbilled > block0.penalty_accrued_unbilled
    finally:
        settings.business_date = saved
        # Ruling 46a: reset through the same accessor's write path (cases.py:139-150)
        # rather than writing the four raw attributes back — that direct write is
        # exactly what ruling 43 stopped the product doing, and a test that did it
        # anyway would be the same defect one file over. The overlay is also cleared
        # per-session by `cases.reset()` before the next test (conftest.py:34), so
        # this is defensive, not load-bearing — but it must go through the accessor
        # regardless.
        cases_domain._set_fee_state(contract, fee_state=None, fee_state_from=None,
                                     fee_state_until=None, fee_state_history=[])


# --- 5. N2-08 ---------------------------------------------------------------------

def test_n2_08_a_no_answer_call_keeps_a_broken_unrenegotiated_promise_in_broken_ptp(client, state):
    before = _today_item(client, SUKRI)
    assert before["tier"] == "BROKEN_PTP" and "ptp-" in before["tier_reason_th"]
    r = _contact(client, SUKRI, "UNREACHABLE_NO_ANSWER", next_action="CALL", next_action_on=str(BD + timedelta(days=3)),
                 note="ไม่รับสายวันที่ 3 ติดต่อกัน")
    assert r.status_code == 201
    after = _today_item(client, SUKRI)
    assert after["tier"] == "BROKEN_PTP" and after["case"]["next_action_on"] == str(BD + timedelta(days=3))
    # a successor promise is what ends it
    broken = next(p for p in state.ptps.values() if p["customer_uid"] == SUKRI and p["status"] == "BROKEN")
    r = client.post("/v1/case-ptps/%s:renegotiate" % broken["uid"], json={"amount": broken["promised_amount"], "date": str(BD + timedelta(days=5))})
    assert r.status_code == 201
    assert _today_item(client, SUKRI)["tier"] != "BROKEN_PTP"


# --- 6. N2-09 / T2-15 -------------------------------------------------------------

def test_n2_09_dc_status_follows_what_is_logged_unless_a_person_governs_it(state):
    case = _a_case(state, payment_status="LATE", open_ptp_uid=None, review_uid=None, open_issue_uid=None, dc_status="NO_ACTION", product="LEASE")
    log = lambda result, **f: cases_domain.log_contact(state, case, {"result": result, "counted": False, **f}, by="nantapol")
    log("REACHED_ANSWERED", next_action="CALLBACK", next_action_on=str(BD + timedelta(days=2)))
    assert case["dc_status"] == "CONTACT_BACK" and case["dc_status_set_by"] == "SYSTEM" and _thai(case["dc_status_reason_th"])
    log("UNREACHABLE_NO_ANSWER", next_action="CALL", next_action_on=str(BD + timedelta(days=1)))
    assert case["dc_status"] == "UNREACHABLE"
    _row, ptp, _i = log("REACHED_PTP", ptp={"amount": "1000", "date": str(BD + timedelta(days=4))})
    assert case["dc_status"] == "EXTEND_PAYMENT_TO"
    cases_domain.close_ptp(state, case, ptp["uid"], "BROKEN", BD, by="nantapol")
    # Round-3 J3-24: a broken promise is no longer an arrangement — "ขอเลื่อนชำระ" is
    # cleared with a reason instead of standing on a promise that failed.
    assert case["dc_status"] == "NO_ACTION" and "ผิดนัด" in case["dc_status_reason_th"]
    _row, _p, issue = log("SERVICE_ISSUE", issue={"summary": "x", "responsible_team": "O_AND_M"})
    assert case["dc_status"] == "TECH_ISSUE" and case["dc_status_before_issue"] == "NO_ACTION"
    cases_domain.close_issue(state, case, issue["uid"], by="nantapol", resolution_note="แก้แล้ว")
    assert case["dc_status"] == "NO_ACTION" and case["dc_status_before_issue"] is None
    # Round-3 J3-08: OD-02 holds the allocation, so the arrears do not move. A case with
    # arrears above zero must not read "ชำระแล้ว"; the hold is carried beside the money.
    arrears = cases_domain.case_arrears(case)
    assert arrears > 0
    cases_domain.payment_confirmed(state, case, on=BD)
    assert case["dc_status"] != "PAID"
    assert case["allocation_hold"] and case["allocation_hold_note_th"] == cases_domain.ALLOCATION_HOLD_TH
    # the same trigger on a case that owes nothing does read PAID, and clears the hold
    settled = _a_case(state, payment_status="CURRENT")
    assert cases_domain.case_arrears(settled) == 0
    cases_domain.payment_confirmed(state, settled, on=BD)
    assert settled["dc_status"] == "PAID" and not settled["allocation_hold"]
    # a person's governed status survives every later contact
    cases_domain.set_dc_status(state, case, "LEGAL_LETTER", by="settasak", note="ส่งหนังสือแล้ว")
    log("UNREACHABLE_NO_ANSWER", next_action="CALL", next_action_on=str(BD + timedelta(days=1)))
    assert case["dc_status"] == "LEGAL_LETTER" and case["dc_status_set_by"] == "settasak"
    # a person's NON-governed status is kept only until the next contact
    # AUTHORISED TEST EDIT 22 — see tests/test_cases.py. A reason is now required; the
    # governed/non-governed distinction this line proves is unchanged.
    cases_domain.set_dc_status(state, case, "CONTACT_BACK", by="settasak", note="ลูกค้าขอให้โทรกลับ")
    log("UNREACHABLE_NO_ANSWER", next_action="CALL", next_action_on=str(BD + timedelta(days=1)))
    assert case["dc_status"] == "UNREACHABLE"
    # the cash book uses the sheet's own PTP code
    cash = _a_case(state, product="CASH", open_ptp_uid=None, review_uid=None, open_issue_uid=None)
    # AUTHORISED TEST EDIT 42 (feedback-r2, R-E): a promise result now requires an
    # amount server-side, so this one call carries the ptp it always implied.
    cases_domain.log_contact(state, cash, {"result": "PROMISED", "counted": False, "next_action": "CALL", "next_action_on": str(BD),
                                           "ptp": {"amount": "1000.00", "date": str(BD + timedelta(days=7))}}, by="thip")
    assert cash["dc_status"] == "PTP"


# --- 7. S2-03 ---------------------------------------------------------------------

def test_s2_03_power_refusal_names_each_precondition_and_banjerd_qualifies(client, state, evidence_for_power):
    evidence_for_power(BANJERD)
    r = client.post("/v1/cases/by-customer/%s/power-restriction" % BANJERD, json={"reason": "ค้าง 3 งวด ผิดนัด"},
                    headers={"X-Volt-Officer": "nantapol"})
    assert r.status_code == 201, r.json()
    assert r.json()["power"]["state"] == "REQUESTED" and all(p["met"] for p in r.json()["power"]["preconditions"])
    case = _a_case(state, payment_status="LATE", power_state="ON", review_uid=None, broken_ptp_count=0)
    r = client.post("/v1/cases/by-customer/%s/power-restriction" % case["customer_uid"], json={"reason": "ทดสอบ"})
    assert r.status_code == 422 and r.json()["code"] == "power_restriction_preconditions" and r.json()["error_id"] == "DEBT-MOD-0442"
    pre = r.json()["extensions"]["preconditions"]
    assert {p["code"] for p in pre} == {"MIN_MISSED", "BROKEN_PTP", "CONTACT_LOGGED"}
    assert all(set(p) >= {"code", "met", "label_th", "value"} and _thai(p["label_th"]) for p in pre)
    broken = next(p for p in pre if p["code"] == "BROKEN_PTP")
    assert broken["met"] is False and broken["label_th"] in r.json()["message_th"] and "BROKEN_PTP" in r.json()["extensions"]["unmet"]


# --- 8. S2-04 ---------------------------------------------------------------------

def test_s2_04_governed_acts_are_signed_by_a_holder_of_the_role(client, state):
    body = client.get("/v1/officers").json()
    roles = {o["uid"]: o["role"] for o in body["officers"]}
    assert roles["nantapol"] == "OFFICER" and roles["thip"] == "OFFICER" and roles["settasak"] == "MANAGER" and roles["owner"] == "OWNER"
    assert all(set(o) >= {"uid", "display_name_th", "role"} for o in body["officers"])
    review = next(r for r in state.reviews.values() if r["status"] == "OPEN" and r["reason"] != "POWER_CUTOFF_ASK")
    r = client.post("/v1/reviews/%s:answer" % review["uid"], json={"decision": "CONTINUE", "comment": "ติดตามต่อ"}, headers=OFFICER_AS_MANAGER)
    assert r.status_code == 200
    assert r.json()["review"]["answered_by"] == "settasak" and r.json()["review"]["answered_by_role"] == "MANAGER"
    snap = client.post("/v1/reports/weekly:snapshot", headers=OFFICER_AS_OWNER).json()["snapshot"]
    assert snap["taken_by"] == "owner" and snap["taken_by_role"] == "OWNER"
    snap = client.post("/v1/reports/weekly:snapshot", headers=MANAGER).json()["snapshot"]
    assert snap["taken_by"] == "settasak" and snap["taken_by_role"] == "MANAGER"
    # an officer's own act keeps the officer's name
    case = _a_case(state, payment_status="LATE", open_ptp_uid=None, review_uid=None, open_issue_uid=None)
    r = _contact(client, case["customer_uid"], "UNREACHABLE_NO_ANSWER", next_action="CALL", next_action_on=str(BD))
    assert r.json()["contact"]["officer_uid"] == "nantapol"


# --- 9. S2-05 ---------------------------------------------------------------------

def test_s2_05_setting_the_npl_type_closes_the_system_ask(client, state):
    case = next(c for c in state.cases.values() if c["payment_status"] == "NPL" and not c["npl_type"] and c["review_uid"])
    review = state.reviews[case["review_uid"]]
    assert review["reason"] == "NPL_TYPE_ASK" and review["raised_by"] == "SYSTEM"
    r = client.post("/v1/cases/by-customer/%s/npl-type" % case["customer_uid"],
                    json={"code": "NPL_2_COOPERATIVE_DECOMMISSION", "reason": "ลูกค้ายินยอมถอดระบบ"}, headers=MANAGER)
    assert r.status_code == 200
    assert review["status"] == "ANSWERED" and review["decision"] == "NPL_TYPE_SET" and review["answered_by"] == "settasak"
    assert case["review_uid"] is None and case["npl_type"] == "NPL_2_COOPERATIVE_DECOMMISSION"
    assert review["uid"] not in [r["uid"] for r in client.get("/v1/reviews?status=OPEN").json()["reviews"]]


# --- 10. T2-02 --------------------------------------------------------------------

def test_t2_02_refresh_on_an_unsent_document_is_200_and_the_invoice_mirrors_it(client):
    from app.integrations import peak as peak_client
    if peak_client.status()["configured"]:
        pytest.skip("PEAK UAT credentials present — the UNSENT path needs their absence")
    pkd.TRANSPORT_OVERRIDE = None
    item = next(i for i in client.get("/v1/pipeline?all=true").json()["items"] if i["entity"] and i["amount_due"])
    uid = item["uid"]
    client.post("/v1/pipeline/%s/gates/down-payment" % uid, json={"slip_ref": "slip-t2-02", "by": "thip"})
    client.post("/v1/pipeline/%s/gates/epc-confirmed" % uid, json={"confirmed_on": str(BD + timedelta(days=2)), "source": "ODOO"})
    client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % uid,
                json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    body = client.post("/v1/pipeline/%s:release" % uid, json={"by": "thip"}).json()
    doc = body["peak_document"]
    assert doc["state"] == "UNSENT" == body["invoice"]["peak_state"] and doc["state_note_th"].startswith("ยังไม่ส่ง")
    r = client.post("/v1/peak-documents/%s:refresh" % doc["uid"])
    assert r.status_code == 200 and r.json()["document"]["state"] == "UNSENT"
    assert r.json()["document"]["state_note_th"] == "ยังไม่ส่ง: ไม่มีการเชื่อมต่อ PEAK (ตั้งค่า PEAK_UAT_* หรือเปิดตัวจำลอง)"
    assert r.json()["document"]["attempts"] == 2      # re-attempted once
    # once PEAK answers (the stub), the same refresh sends it and the invoice follows
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    r = client.post("/v1/peak-documents/%s:refresh" % doc["uid"])
    # the stub creates the draft and, on the read-back the same refresh does, approves it
    assert r.status_code == 200 and r.json()["document"]["state"] == "APPROVED_IN_PEAK" and r.json()["document"]["peak_ref"]
    inv = next(i for i in client.get("/v1/ar/pipeline?customer_uid=%s" % item["customer_uid"]).json()["invoices"] if i["uid"] == body["invoice"]["uid"])
    assert inv["peak_state"] == "APPROVED_IN_PEAK" and _thai(inv["peak_state_note_th"])


# --- 11. T2-04 --------------------------------------------------------------------

def test_t2_04_invoice_list_is_uncapped_filterable_and_a_customer_route_prefills_the_ask(client):
    body = client.get("/v1/ar/pipeline").json()
    assert body["meta"]["total"] == len(body["invoices"]) > 100 and body["meta"]["cap"] is None
    rows = client.get("/v1/ar/pipeline?q=99999000297").json()["invoices"]
    assert rows and all("99999000297" in r["customer"]["volt_id"] for r in rows)
    rows = client.get("/v1/ar/pipeline?q=ลูกค้าทดสอบ%200153&open_only=true").json()["invoices"]
    assert rows and {r["customer"]["uid"] for r in rows} == {PAT1, PAT2}
    rows = client.get("/v1/ar/pipeline?customer_uid=%s" % PAT1).json()["invoices"]
    assert rows and all(r["customer"]["uid"] == PAT1 for r in rows)
    mine = client.get("/v1/cases/by-customer/%s/invoices" % PAT1).json()
    assert mine["meta"]["total"] == len(mine["invoices"]) == 1
    overdue = next(i for i in mine["invoices"] if i["state"] == "OVERDUE")
    assert overdue["amount_to_ask"] is None and overdue["review_required"] is True
    assert overdue["outstanding"] == "5799.00" and mine["money_position"]["amount_to_ask"] == "0.00"
    assert client.get("/v1/cases/by-customer/nobody/invoices").status_code == 404


# --- 12. T2-09 --------------------------------------------------------------------

def test_t2_09_lease_pipeline_rows_hint_twenty_percent_of_the_contract_price(client):
    items = client.get("/v1/pipeline?all=true").json()["items"]
    hinted = [i for i in items if i["amount_hint"]]
    assert hinted, "the order rows that carry a price get a hint"
    for i in hinted:
        assert i["amount_due"] is None
        total = Decimal(i["amount_hint_basis"]["total_inc_vat"])
        assert Decimal(i["amount_hint"]) == (total * Decimal("0.20")).quantize(Decimal("0.01"))
        assert i["amount_hint_note_th"] == "ประมาณการ 20% ของราคาสัญญา ยืนยันยอดจากสัญญาก่อนปล่อย"
    # the hint is not the amount: release still needs the entered figure
    item = hinted[0]
    client.post("/v1/pipeline/%s/gates/down-payment" % item["uid"], json={"slip_ref": "slip-t2-09", "by": "thip"})
    client.post("/v1/pipeline/%s/gates/epc-confirmed" % item["uid"], json={"confirmed_on": str(BD + timedelta(days=1)), "source": "ODOO"})
    # Delta-100 D2h: contract evidence must be on file or release stops at the gate
    # instead of reaching the amount check this test is about.
    client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % item["uid"],
                json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    r = client.post("/v1/pipeline/%s:release" % item["uid"], json={"by": "thip"})
    assert r.status_code == 422 and r.json()["code"] == "amount_required"
    rows_without = [i for i in items if not i["amount_due"] and not i["amount_hint"]]
    assert all(i["amount_hint_note_th"] is None for i in rows_without)


# --- 13. N2-16 --------------------------------------------------------------------

def test_n2_16_broken_on_the_promise_date_with_a_reason_and_the_lineage_is_named(client, state):
    case = _a_case(state, payment_status="LATE", open_ptp_uid=None, review_uid=None, open_issue_uid=None, broken_ptp_count=0)
    uid = case["customer_uid"]
    past = str(BD - timedelta(days=5))
    ptp = _contact(client, uid, "INBOUND", ptp={"amount": "1000", "date": past}).json()["ptp"]
    assert ptp["renegotiation_count"] == 0 and ptp["lineage_note_th"] is None
    r = client.post("/v1/case-ptps/%s:close" % ptp["uid"], json={"outcome": "BROKEN", "reason": "ลูกค้าไม่โอนตามนัด"},
                    headers={"X-Volt-Officer": "nantapol"})
    assert r.status_code == 200
    assert r.json()["ptp"]["closed_on"] == past and r.json()["ptp"]["broken_detected_at"] == str(BD)
    assert r.json()["ptp"]["broken_reason"] == "ลูกค้าไม่โอนตามนัด"
    nxt = _contact(client, uid, "INBOUND", ptp={"amount": "1000", "date": str(BD + timedelta(days=2))}).json()["ptp"]
    assert nxt["renegotiation_count"] == 1 and nxt["lineage_from_uid"] == ptp["uid"]
    assert nxt["lineage_note_th"] == "ต่อเนื่องจากสัญญาที่ผิดนัดเมื่อ %s (%s)" % (past, ptp["uid"])
    # the sheet's July promises are broken on their own date, not on the business day
    sheet_broken = [p for p in state.ptps.values() if p["source"] == "SHEET" and p["status"] == "BROKEN"]
    assert sheet_broken and all(p["closed_on"] == p["promise_date"] and p["broken_detected_at"] == str(BD) for p in sheet_broken)


# --- 14. N2-15 --------------------------------------------------------------------

def test_n2_15_sheet_invoices_without_a_peak_number_are_sheet_recorded(client):
    rows = client.get("/v1/ar/pipeline").json()["invoices"]
    sheet = [r for r in rows if r.get("scenario") == "SHEET"]
    assert sheet
    for r in sheet:
        if r.get("peak_number"):
            assert r["peak_state"] == "APPROVED_IN_PEAK"
        else:
            assert r["peak_state"] == "SHEET_RECORDED" and r["peak_state_note_th"] == "ตามชีต ยังไม่มีเลข PEAK"
    assert any(r.get("peak_number") for r in sheet) and any(not r.get("peak_number") for r in sheet)


# --- 15. N2-13 --------------------------------------------------------------------

def test_n2_13_reminder_offsets_are_a_manager_config_key(client):
    saved = settings.reminder_offsets_days
    try:
        meta = client.get("/v1/today/reminders").json()["meta"]
        assert meta["offsets"] == [3, 0] and meta["batch_label"] == "D-3 / D0" and _thai(meta["note_th"])
        assert client.put("/v1/config", json={"reminder_offsets_days": "1,0"}, headers={"X-Volt-Role": "OFFICER"}).status_code == 403
        r = client.put("/v1/config", json={"reminder_offsets_days": "D-1 / D0"}, headers=MANAGER)
        assert r.status_code == 200 and r.json()["config"]["reminder_offsets_days"]["editable_by"] == "MANAGER"
        meta = client.get("/v1/today/reminders").json()["meta"]
        assert meta["offsets"] == [1, 0] and meta["batch_label"] == "D-1 / D0"
        assert client.get("/v1/today").json()["meta"]["reminder_offsets"] == [1, 0]
        assert client.put("/v1/config", json={"reminder_offsets_days": "x"}, headers=MANAGER).status_code == 422
    finally:
        settings.reminder_offsets_days = saved


# --- 16. S2-07 / S2-08 ------------------------------------------------------------

def test_s2_07_08_tier_order_zero_arrears_answers_waiting_npl_total_and_the_power_line(client, state, evidence_for_power):
    evidence_for_power(BANJERD)
    risk = next(c for c in state.cases.values() if c["product"] == "LEASE"
                and c["customer_uid"] != BANJERD
                and journey.customer_by_uid(c["customer_uid"]).contracts)
    risk.update(open_ptp_uid=None, review_uid=None, broken_ptp_count=0,
                next_action_set_by="SYSTEM")
    evidence_for_power(risk["customer_uid"])
    body = client.get("/v1/today").json()
    items = body["items"]
    broken = [i for i in items if i["tier"] == "BROKEN_PTP"]
    assert broken and all(Decimal(i["aggregate_overdue"]) > 0 or i["money_position"]["review_required"] for i in broken)
    dpds = [i["oldest_dpd"] or 0 for i in broken]
    assert dpds == sorted(dpds, reverse=True)
    parked = [i for i in items if i["case"]["broken_ptp_count"] and Decimal(i["aggregate_overdue"]) == 0 and not i["case"]["open_ptp"] and not i["money_position"]["review_required"]]
    assert all(i["tier"] != "BROKEN_PTP" and "ไม่มียอดค้าง" in i["tier_reason_th"] for i in parked)
    assert all(_thai(i["tier_reason_th"]) and i["tier_label_th"] for i in items)
    # an answer waiting on a customer who sits in a higher tier is still counted
    target = next(i for i in items if i["tier"] == "AT_RISK_TWO_MISSED" and not i["case"]["review_uid"])["customer"]["uid"]
    review = client.post("/v1/cases/by-customer/%s/review-requests" % target, json={"reason": "UNREACHABLE", "question_th": "ขอให้ลงพื้นที่"},
                         headers={"X-Volt-Officer": "nantapol"}).json()["review"]
    client.post("/v1/reviews/%s:answer" % review["uid"], json={"decision": "CONTINUE", "comment": "ลงพื้นที่ได้"}, headers=MANAGER)
    body = client.get("/v1/today").json()
    row = next(i for i in body["items"] if i["customer"]["uid"] == target)
    # Round-4 J4-16: the Manager's answer now sets the case's next step and signs it, so
    # the row rises to tier 2 (a person's next action, due today) instead of sitting in
    # tier 4 under a SYSTEM default. Nothing is hidden — the waiting answer is still
    # counted on the row and reported as answers_waiting_elsewhere.
    assert row["tier"] == "NEXT_ACTION_DUE" and row["answers_waiting"] == 1
    assert row["case"]["next_action"] == "CALL" and row["case"]["next_action_set_by"] == "settasak"
    # Round-3 J3-04: counts_by_tier is now the PARTITION (it sums to meta.total); the
    # answer that sits in a higher tier is reported beside it, not inside the chip.
    assert body["meta"]["answers_waiting"] >= 1 == body["meta"]["answers_waiting_elsewhere"]
    assert body["meta"]["counts_by_tier"] == body["meta"]["tier_partition"]
    assert sum(body["meta"]["tier_partition"].values()) == body["meta"]["total"]
    # Recovery: the NPL list total is the number of NPL customers the weekly report counts
    npl = client.get("/v1/npl-cases").json()
    assert npl["meta"]["total"] == len({r["customer_uid"] for r in npl["npl_cases"]}) == client.get("/v1/reports/weekly").json()["portfolio"]["npl"]
    # the power line after an approval reads APPROVED, and the weekly report lists the act
    client.post("/v1/cases/by-customer/%s/power-restriction" % BANJERD, json={"reason": "ค้าง 3 งวด ผิดนัด"}, headers={"X-Volt-Officer": "nantapol"})
    case = state.cases[BANJERD]
    r = client.post("/v1/reviews/%s:answer" % case["review_uid"], json={"decision": "POWER_CUTOFF_APPROVE", "comment": "อนุมัติ"}, headers=OFFICER_AS_OWNER)
    assert r.status_code == 200 and case["power_state"] == "RESTRICTION_APPROVED"
    detail = _detail(client, BANJERD)
    assert detail["case"]["power_state_label_th"] == "อนุมัติตัดไฟแล้ว รอดำเนินการ" and detail["power"][-1]["approved_by"] == "owner"
    acts = client.get("/v1/reports/weekly").json()["power_actions"]
    approved = next(a for a in acts if a["kind"] == "POWER_APPROVED" and a["case_uid"] == case["uid"])
    assert approved["power_state"] == "RESTRICTION_APPROVED" and "รออนุมัติ" not in approved["power_state_label_th"]


# --- 17. T2-13 --------------------------------------------------------------------

def test_t2_13_postponement_needs_the_new_date_and_moves_the_card(client):
    item = next(i for i in client.get("/v1/pipeline?all=true").json()["items"] if i["install_outcome"] is None)
    uid, old = item["uid"], item["planned_install_on"]
    r = client.post("/v1/pipeline/%s/install-outcome" % uid, json={"outcome": "POSTPONED"})
    assert r.status_code == 422 and r.json()["code"] == "new_install_on_required" and _thai(r.json()["message_th"])
    new = str(date.fromisoformat(old) + timedelta(days=7))
    r = client.post("/v1/pipeline/%s/install-outcome" % uid, json={"outcome": "POSTPONED", "new_install_on": new}, headers={"X-Volt-Officer": "thip"})
    assert r.status_code == 200
    moved = r.json()["item"]
    assert moved["planned_install_on"] == new and moved["previous_install_on"] == old and moved["install_outcome"] == "POSTPONED"
    assert moved["history"][-1] == {"act": "INSTALL_POSTPONED", "on": None, "new_install_on": new, "by": "thip"}
    listed = next(i for i in client.get("/v1/pipeline?all=true").json()["items"] if i["uid"] == uid)
    assert listed["planned_install_on"] == new


# --- 18. Final v2: enumerated settings serve their option sets ---------------------

def test_final_v2_enumerated_config_rows_serve_select_options(client):
    """Prototype 1384-1389, 2605-2606: a setting the design draws as a select is
    chosen from served options, never typed. Only values the API accepts are offered."""
    rows = client.get("/v1/config", headers=MANAGER).json()["config"]
    for key in ("band_set_code", "reminder_offsets_days"):
        options = rows[key]["options"]
        assert options, key
        for option in options:
            assert option["value"] and option["label_th"] and option["label_en"], (key, option)
    assert [o["value"] for o in rows["reminder_offsets_days"]["options"]] == ["3,0", "1,0", "7,1,0"]
    # A retired band set is not offered: PUT refuses it, so the select must not carry it.
    active = {r["code"] for r in client.get("/v1/band-sets").json()["band_sets"] if r["active"]}
    assert {o["value"] for o in rows["band_set_code"]["options"]} == active


def test_final_v2_the_pending_keys_the_design_draws_are_read_only_rows_with_options(client):
    """OD-02, SVC-37 and OD-04 (config.py PENDING) are drawn in the register. They are
    rulings nobody has closed, so every role reads them locked; the options are what a
    ruling would choose between, never something this API writes."""
    keys = ("allocation_component_order", "service_month37_decline_allowed", "npl_dpd_threshold_days")
    for role in ("OFFICER", "MANAGER", "OWNER"):
        rows = client.get("/v1/config", headers={"X-Volt-Role": role}).json()["config"]
        for key in keys:
            row = rows[key]
            assert row["state"] == "OPEN" and row["editable"] is False and row["editable_by"] is None, (role, key)
            assert row["lock"] == "locked" and row["owner"] and row["note_th"] and row["note_en"], (role, key)
    rows = client.get("/v1/config", headers=MANAGER).json()["config"]
    assert [o["label_en"] for o in rows["allocation_component_order"]["options"]] == \
        ["Not yet decided", "Penalty first", "Instalment first"]
    assert [o["label_th"] for o in rows["service_month37_decline_allowed"]["options"]] == \
        ["ออกบิลตามแนวทางที่ใช้อยู่", "ให้ลูกค้าปฏิเสธได้"]
    assert rows["npl_dpd_threshold_days"]["options"] == []
    # Not editable: a pending key is refused by name before anything is written.
    r = client.put("/v1/config", json={"allocation_component_order": "INSTALMENT_FIRST"}, headers=MANAGER)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not_editable"
    assert client.get("/v1/config", headers=MANAGER).json()["config"]["allocation_component_order"]["value"] is None


# --- 19. Delta-100 SE3 / D2e: the register keeps its seven rows ---------------------

def test_delta100_flat_register_keeps_seven_rows_and_kpi_targets_stay_out(client):
    """Final v2 733-759: the register is a flat seven-row list (its SETTINGS rows
    1383-1389). Delta-100 adds the missing per-customer contact-limit row (SE3) and
    five config-tunable KPI targets (D2e) — the targets must not grow the register,
    so REGISTER names exactly the seven rows the screen draws and the targets are
    served as ordinary config keys beside it."""
    from app.routers.settings import CONFIG_CASTS, REGISTER
    rows = client.get("/v1/config", headers=MANAGER).json()["config"]
    assert len(REGISTER) == 7 and len(set(REGISTER)) == 7
    for key in REGISTER:
        assert key in rows, key
    # SE3: the daily contact limit the prototype draws is now a manager row.
    cap = rows["daily_contact_limit_per_customer"]
    assert cap["value"] == "1" and cap["lock"] == "manager" and cap["editable"] is True
    # The KPI targets are config-tunable but in none of the seven register rows.
    for key in CONFIG_CASTS:
        assert key in rows and key not in REGISTER, key
        assert rows[key]["value"] is None and rows[key]["editable_by"] == "MANAGER"
    r = client.put("/v1/config", json={"daily_contact_limit_per_customer": 2}, headers=MANAGER)
    assert r.status_code == 200
    assert r.json()["config"]["daily_contact_limit_per_customer"]["value"] == "2"
    assert client.put("/v1/config", json={"daily_contact_limit_per_customer": 0}, headers=MANAGER).status_code == 422
