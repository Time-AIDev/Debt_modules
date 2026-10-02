"""The daily loop — Requirements Amendment v2.6 §3.1–3.8, test cases DAY-001..010."""
from datetime import date, timedelta

import pytest

from app import cases, dictionaries
from app.cases import CaseError
from app.config import settings

BD = settings.business_date


@pytest.fixture
def state():
    return cases.for_current()


def any_case(state, **where):
    for case in state.cases.values():
        if all(case.get(k) == v for k, v in where.items()):
            return case
    raise AssertionError("no case matches %r" % where)


def test_every_seeded_case_has_a_next_action(state):
    """REQ-COL-070 — the seed leaves nobody without a next action, real book included.

    A pre-install card's case (2026-09-20) is deliberately the exception: there is no
    next action before its invoice is released, so the calendar does not carry a
    reminder for work that has not started."""
    assert len(state.cases) > 100
    for case in state.cases.values():
        if case.get("opened_from") == "PRE_INSTALL_CARD" and not case.get("pipeline_released"):
            assert case["next_action"] is None and case["next_action_on"] is None, case["uid"]
            continue
        assert case["next_action"], case["uid"]
        assert case["next_action_on"], case["uid"]


def test_sheet_ptp_dates_become_promises_and_past_ones_are_broken_by_the_system(state):
    broken = [p for p in state.ptps.values() if p["status"] == "BROKEN"]
    assert broken, "the sheet carries PTP dates before the business date"
    for p in broken:
        assert p["broken_detected_at"] is not None
        assert state.cases[p["customer_uid"]]["broken_ptp_count"] >= 1


def test_maplog_rows_are_contact_log_rows_with_officer_and_result(state):
    imported = [r for r in state.contact_log if r["source"] == "MAPLOG_IMPORT"]
    assert imported, "the MapLog strings were imported"
    row = imported[0]
    assert row["officer_uid"] in ("nantapol", "ทิพย์อักษร", "thiphakson")
    assert row["result"] in ("REACHED_ANSWERED", "UNREACHABLE_NO_ANSWER", "REACHED_PTP")
    case = state.cases[row["customer_uid"]]
    assert case["last_contact_at"] is not None


def test_contact_without_next_action_refuses_unless_a_promise_or_issue_is_made(state):
    case = any_case(state, payment_status="LATE", open_ptp_uid=None)
    with pytest.raises(CaseError) as err:
        cases.log_contact(state, case, {"result": "REACHED_ANSWERED", "amount_stated": True, "counted": True}, by="nantapol")
    assert err.value.code == "next_action_required"
    row, ptp, issue = cases.log_contact(state, case, {
        "result": "REACHED_PTP", "amount_stated": True, "counted": True,
        "ptp": {"amount": "3199.00", "date": str(BD + timedelta(days=3))},
    }, by="nantapol")
    assert ptp["status"] == "OPEN"
    assert case["next_action"] == "FOLLOW_PTP" and case["next_action_on"] == str(BD + timedelta(days=3))
    assert row["ptp_uid"] == ptp["uid"] and state.contact_log[-1] is row


def test_callback_sets_the_next_action_and_the_log_row_carries_it(state):
    case = any_case(state, payment_status="CURRENT", open_ptp_uid=None)
    row, _, _ = cases.log_contact(state, case, {
        "result": "CALLBACK_REQUESTED", "counted": False,
        "next_action": "CALLBACK", "next_action_on": str(BD + timedelta(days=2)), "note": "โทรกลับวันพฤหัส",
    }, by="thip")
    assert case["next_action"] == "CALLBACK"
    assert row["next_action_on"] == str(BD + timedelta(days=2))


def test_promise_counts_are_computed_never_typed(state):
    case = any_case(state, payment_status="LATE", open_ptp_uid=None)
    before = case["broken_ptp_count"]
    _, ptp, _ = cases.log_contact(state, case, {
        "result": "REACHED_PTP", "counted": True, "amount_stated": True,
        "ptp": {"amount": "3199", "date": str(BD + timedelta(days=1))},
    }, by="nantapol")
    # Round 3, ruling 10 (Arina, 2026-09-04), tightened by ruling 15 (2026-09-04):
    # detect_broken_ptps is a global, case-unscoped sweep. Ruling 7 legitimately
    # mirrors a second real, open promise (C-000912's) into the cases store, so it
    # is now also swept here — correctly, and the fixture may grow further still.
    # Ruling 10's plain membership assertion (`ptp["uid"] in ...`) cannot catch an
    # over-reporting detect_broken_ptps: a sweep that wrongly returned every open
    # promise in the book would still pass it. Ruling 15 recovers that protection
    # by scoping the equality to the promises belonging to THIS test's own case —
    # never breaks when seed data grows a promise elsewhere, but still fails if
    # this case's own broken set stops being exactly {ptp["uid"]}.
    broken = cases.detect_broken_ptps(state, BD + timedelta(days=2))
    case_broken = [uid for uid in broken if state.ptps[uid]["customer_uid"] == case["customer_uid"]]
    assert case_broken == [ptp["uid"]]
    assert case["broken_ptp_count"] == before + 1
    assert case["open_ptp_uid"] is None and case["next_action"] == "CALL"
    assert "broken_ptp_count" not in cases.set_next_action.__code__.co_varnames


def test_third_renegotiation_escalates_to_review(state):
    case = any_case(state, payment_status="LATE", open_ptp_uid=None, review_uid=None)
    _, ptp, _ = cases.log_contact(state, case, {"result": "REACHED_PTP", "counted": True, "amount_stated": True,
                                                 "ptp": {"amount": "1000", "date": str(BD + timedelta(days=1))}}, by="nantapol")
    # Round-2 N2-05: renegotiate_ptp returns (new promise, review or None) — the third is
    # recorded AND escalated, never refused half-way.
    p2, r2 = cases.renegotiate_ptp(state, case, ptp["uid"], "1000", str(BD + timedelta(days=5)), by="nantapol")
    p3, r3 = cases.renegotiate_ptp(state, case, p2["uid"], "1000", str(BD + timedelta(days=9)), by="nantapol")
    assert case["review_uid"] is None and r2 is None and r3 is None
    p4, r4 = cases.renegotiate_ptp(state, case, p3["uid"], "1000", str(BD + timedelta(days=12)), by="nantapol")
    assert p4["renegotiation_count"] == 3 and p4["status"] == "OPEN" and r4["uid"] == case["review_uid"]
    assert state.reviews[case["review_uid"]]["reason"] == "REPEATED_BROKEN_PTP"


def test_review_request_answer_returns_to_the_officer_and_second_open_refuses(state):
    case = any_case(state, payment_status="LATE", review_uid=None)
    review = cases.request_review(state, case, "NO_COMMITMENT", "ลูกค้าไม่ให้คำตอบสามรอบ", by="nantapol")
    assert case["next_action"] == "AWAIT_REVIEW"
    with pytest.raises(CaseError) as err:
        cases.request_review(state, case, "OTHER", "again", by="nantapol")
    assert err.value.code == "review_pending"
    with pytest.raises(CaseError):
        cases.answer_review(state, review["uid"], "CONTINUE", "x", by="nantapol", role="OFFICER")
    cases.answer_review(state, review["uid"], "CONTINUE", "ให้โทรอีกสองครั้งแล้วส่ง Legal", by="settasak", role="MANAGER")
    item = state.today_items[-1]
    assert item["kind"] == "REVIEW_ANSWERED" and item["officer_uid"] == case["officer_uid"]
    assert case["next_action"] == "CALL"
    with pytest.raises(CaseError) as err:
        cases.answer_review(state, review["uid"], "CONTINUE", "x", by="settasak", role="MANAGER")
    assert err.value.code == "review_already_decided"


def test_two_statuses_are_independent(state):
    case = any_case(state, payment_status="LATE")
    # AUTHORISED TEST EDIT 22 — Arina, 2026-09-11, option A: "made all the status can
    # adjust by user with reason". A person's dc_status now REFUSES without one
    # (cases.set_dc_status), so the two calls in this file that set it with no note
    # gain one. Priced before it was spent: 4 test functions across 3 files — this
    # one, test_round2.py's N2-09, and two in CustomerCase.test.jsx. Nothing else in
    # this test moves: what it asserts (the two statuses are independent) is untouched.
    cases.set_dc_status(state, case, "Contact Back", by="thip", note="ลูกค้าขอให้โทรกลับ")
    assert case["dc_status"] == "CONTACT_BACK" and case["payment_status"] == "LATE"
    with pytest.raises(dictionaries.DictionaryError):
        cases.set_dc_status(state, case, "Made Up", by="thip")


def test_a_person_changing_the_dc_status_must_say_why(state):
    """Arina, 2026-09-11: every status a person adjusts carries a reason.

    Before this, `note` was optional and the record FABRICATED one — the reason field
    was written as "ตั้งโดย nantapol", which reads like a justification and is only a
    restatement of `by`. set_npl_type three functions below has refused without a
    reason since J-46; this is the same rule on the field beside it.
    """
    case = any_case(state, payment_status="LATE")
    with pytest.raises(CaseError) as err:
        cases.set_dc_status(state, case, "Contact Back", by="thip")
    assert err.value.code == "reason_required"
    with pytest.raises(CaseError):
        cases.set_dc_status(state, case, "Contact Back", by="thip", note="   ")
    # The refusal changed nothing.
    assert case["dc_status"] != "CONTACT_BACK"


def test_the_dc_status_trail_says_from_what_to_what_and_why(state):
    case = any_case(state, payment_status="LATE")
    before = case["dc_status"]
    cases.set_dc_status(state, case, "Contact Back", by="thip", note="ลูกค้าขอให้โทรกลับพรุ่งนี้")
    assert case["dc_status"] == "CONTACT_BACK"
    assert case["dc_status_reason_th"] == "ลูกค้าขอให้โทรกลับพรุ่งนี้"
    event = [e for e in state.events if e["kind"] == "DC_STATUS_SET"][-1]
    # R14's four questions: what it was, what it became, who, and why.
    assert event["from"] == before
    assert event["code"] == "CONTACT_BACK"
    assert event["by"] == "thip"
    assert event["reason"] == "ลูกค้าขอให้โทรกลับพรุ่งนี้"


def test_setting_the_status_it_already_holds_is_refused(state):
    """R14's rule, borrowed: an adjustment that changes nothing still leaves an audit
    row claiming someone changed something (errors.override_source_unchanged)."""
    case = any_case(state, payment_status="LATE")
    cases.set_dc_status(state, case, "Contact Back", by="thip", note="ลูกค้าขอให้โทรกลับ")
    trail = len([e for e in state.events if e["kind"] == "DC_STATUS_SET"])
    with pytest.raises(CaseError) as err:
        cases.set_dc_status(state, case, "Contact Back", by="thip", note="เหตุผลอื่น")
    assert err.value.code == "status_unchanged"
    assert len([e for e in state.events if e["kind"] == "DC_STATUS_SET"]) == trail


def test_npl_type_is_manager_only(state):
    case = any_case(state, payment_status="NPL")
    with pytest.raises(CaseError):
        cases.set_npl_type(state, case, "NPL 3 - Uncooperative - Legal action", by="nantapol", role="OFFICER")
    cases.set_npl_type(state, case, "NPL 3 - Uncooperative - Legal action", by="settasak", role="MANAGER", reason="ไม่ให้ความร่วมมือ")   # J-46: a reason is required
    assert case["npl_type"] == "NPL_3_UNCOOPERATIVE_LEGAL"


def test_power_restriction_is_governed(state):
    case = any_case(state, payment_status="LATE", power_state="ON", review_uid=None)
    case["broken_ptp_count"] = 0
    with pytest.raises(CaseError) as err:
        cases.request_power(state, case, by="nantapol", missed_count=2, reason="ค้าง 2 งวด ผิดนัด ติดต่อแล้ว")   # J-48: a reason is required
    assert err.value.code == "power_restriction_preconditions"
    case["broken_ptp_count"] = 1
    # The SOP chases before it cuts: a case with no contact evidence is refused too.
    # Round-2 S2-03: evidence is a contact row OR a recorded promise (the sheet's PTP).
    if not any(r["customer_uid"] == case["customer_uid"] for r in state.contact_log) and \
            not any(p["customer_uid"] == case["customer_uid"] for p in state.ptps.values()):
        with pytest.raises(CaseError) as err:
            cases.request_power(state, case, by="nantapol", missed_count=2, reason="ค้าง 2 งวด ผิดนัด ติดต่อแล้ว")   # J-48: a reason is required
        assert err.value.code == "power_restriction_preconditions"
        cases.log_contact(state, case, {"result": "UNREACHABLE_NO_ANSWER", "counted": False,
                                        "next_action": "CALL", "next_action_on": str(BD)}, by="nantapol")
    rec = cases.request_power(state, case, by="nantapol", missed_count=2, reason="ค้าง 2 งวด ผิดนัด ติดต่อแล้ว")   # J-48: a reason is required
    assert case["power_state"] == "RESTRICTION_REQUESTED" and rec["reason"] == "ARREARS"
    with pytest.raises(CaseError):
        cases.approve_power(state, case, by="nantapol", role="OFFICER")
    review = state.reviews[case["review_uid"]]
    cases.answer_review(state, review["uid"], "POWER_CUTOFF_APPROVE", "ok", by="owner", role="OWNER")
    assert rec["state"] == "APPROVED"
    cases.execute_power(state, case, by="om-krit", notified_om=True)
    assert case["power_state"] == "RESTRICTED" and case["dc_status"] == "POWER_CUTOFF" and rec["notified_om_at"]
    cases.payment_confirmed(state, case, on=BD)
    assert case["power_state"] == "RESTORE_DUE" and rec["restore_due_at"]
    cases.restore_power(state, case, by="om-krit")
    assert case["power_state"] == "ON" and rec["state"] == "RESTORED"


def test_ticket_closure_raises_a_today_item_and_keeps_the_officer_in_charge(state):
    case = any_case(state, payment_status="LATE", open_issue_uid=None)
    _, _, issue = cases.log_contact(state, case, {
        "result": "SERVICE_ISSUE", "counted": True, "amount_stated": True,
        "issue": {"summary": "อินเวอร์เตอร์ดับ", "responsible_team": "O_AND_M",
                  "ticket_url": "https://odoo.volt.co.th/odoo/helpdesk-tickets/999", "deadline": str(BD + timedelta(days=7))},
    }, by="nantapol")
    assert case["next_action"] == "AWAIT_TICKET" and issue["ticket_url"].endswith("/999")
    cases.close_issue(state, case, issue["uid"], by="cx", resolution_note="O&M ยืนยันแก้แล้ว")   # J-13: resolution_note is required
    assert state.today_items[-1]["kind"] == "TICKET_CLOSED"
    assert case["next_action"] == "CALL"


def test_refusal_to_pay_raises_a_review_from_the_contact(state):
    case = any_case(state, payment_status="LATE", review_uid=None)
    cases.log_contact(state, case, {"result": "REFUSED_PAY", "counted": True, "amount_stated": True,
                                    "next_action": "ESCALATE", "next_action_on": str(BD)}, by="nantapol")
    assert case["review_uid"] and state.reviews[case["review_uid"]]["raised_by"] == "SYSTEM"


def test_sheet_dc_status_and_npl_type_resolve_through_the_dictionary(state):
    dc = {c["dc_status"] for c in state.cases.values()}
    assert "NO_ACTION" in dc and "PTP" in dc
    assert any(c["npl_type"] for c in state.cases.values())
    for case in state.cases.values():
        if case["dc_status"] == "POWER_CUTOFF":
            assert case["power_state"] == "RESTRICTED" and state.power[case["power_uid"]]["backfilled"]


# --- round-1 regressions (2026-09-02) -------------------------------------------

def test_closing_an_issue_clears_the_case_pointer_and_logging_one_sets_tech_issue(state):
    case = any_case(state, payment_status="LATE", open_issue_uid=None, dc_status="NO_ACTION")
    _, _, issue = cases.log_contact(state, case, {"result": "SERVICE_ISSUE", "counted": True, "amount_stated": True,
                                                  "issue": {"summary": "inverter", "responsible_team": "O_AND_M", "ticket_url": "https://odoo.volt.co.th/odoo/helpdesk-tickets/1"}}, by="nantapol")
    assert case["dc_status"] == "TECH_ISSUE" and case["open_issue_uid"] == issue["uid"]
    cases.close_issue(state, case, issue["uid"], by="cx", resolution_note="O&M ยืนยันแก้แล้ว")   # J-13: resolution_note is required
    assert case["open_issue_uid"] is None and issue["closed_by"] == "cx"


def test_a_promise_after_a_broken_one_continues_the_renegotiation_lineage(state):
    case = any_case(state, payment_status="LATE", open_ptp_uid=None, review_uid=None, broken_ptp_count=0)
    for n in range(3):
        _, ptp, _ = cases.log_contact(state, case, {"result": "INBOUND", "counted": False,
                                                    "ptp": {"amount": "1000", "date": str(BD + timedelta(days=1))}}, by="nantapol")
        cases.close_ptp(state, case, ptp["uid"], "BROKEN", BD, by="system")
    assert case["broken_ptp_count"] == 3
    _, ptp, _ = cases.log_contact(state, case, {"result": "INBOUND", "counted": False,
                                                "ptp": {"amount": "1000", "date": str(BD + timedelta(days=2))}}, by="nantapol")
    assert ptp["renegotiation_count"] == 3
    assert state.reviews[case["review_uid"]]["reason"] == "REPEATED_BROKEN_PTP"


def test_npl_type_decision_sets_the_type_or_refuses(state):
    case = any_case(state, payment_status="NPL")
    review = state.reviews[case["review_uid"]] if case["review_uid"] else cases.request_review(state, case, "NPL_TYPE_ASK", "?", by="SYSTEM")
    with pytest.raises(CaseError) as err:
        cases.answer_review(state, review["uid"], "NPL_TYPE_SET", "no type", by="settasak", role="MANAGER")
    assert err.value.code == "npl_type_required" and review["status"] == "OPEN"
    cases.answer_review(state, review["uid"], "NPL_TYPE_SET", "type 2", by="settasak", role="MANAGER", npl_type="NPL_2_COOPERATIVE_DECOMMISSION")
    assert case["npl_type"] == "NPL_2_COOPERATIVE_DECOMMISSION" and review["status"] == "ANSWERED"


def test_power_approval_by_the_wrong_role_is_refused_not_stored(state):
    case = any_case(state, payment_status="LATE", power_state="ON", review_uid=None)
    case["broken_ptp_count"] = 1
    cases.log_contact(state, case, {"result": "UNREACHABLE_NO_ANSWER", "counted": False, "next_action": "CALL", "next_action_on": str(BD)}, by="nantapol")
    cases.request_power(state, case, by="nantapol", missed_count=2, reason="ค้าง 2 งวด ผิดนัด ติดต่อแล้ว")   # J-48: a reason is required
    review = state.reviews[case["review_uid"]]
    with pytest.raises(CaseError) as err:
        cases.answer_review(state, review["uid"], "POWER_CUTOFF_APPROVE", "ok", by="settasak", role="MANAGER")
    assert err.value.code == "forbidden" and review["status"] == "OPEN" and case["review_uid"] == review["uid"]
    cases.answer_review(state, review["uid"], "POWER_CUTOFF_APPROVE", "ok", by="jo", role="OWNER")
    cases.execute_power(state, case, by="om")
    with pytest.raises(CaseError):
        cases.restore_power(state, case, by="nantapol", role="OFFICER")
    cases.restore_power(state, case, by="ops", role="SUPERVISOR")
    assert case["dc_status"] == "NO_ACTION" and case["power_state"] == "ON"
