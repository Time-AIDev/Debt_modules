"""Closed vs Terminated — 2026-09-20 ruling.

CLOSED means the customer paid off the balance per the terms and conditions, and
nothing else. Every other way a contract ends — VOLT terminating on default, or the
customer asking to terminate — is TERMINATED, and it must carry its cause. These
tests pin the split: the derivation, the terminate act, the
cause stamped by the write-off and by a cooperative decommission, the sheet's own
tracking categories, and the reconciliation row that stays honest while the sheet
does not carry the value yet.
"""
import types
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import audit_store, book, cases, dictionaries, imports, journey, sop
from app.cases import CaseError
from app.main import app

client = TestClient(app)
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "ploy"}


def _case_of(customer_no):
    state = cases.for_current()
    return next(c for c in state.cases.values() if c["customer_no"] == customer_no)


def _contract_of(customer_uid):
    customer = journey.customer_by_uid(customer_uid)
    return customer.contracts[0]


def _latest_audit():
    return audit_store.read({}, limit=1, before_seq=None)[0]


# --- the derivation -------------------------------------------------------------------

def test_all_contracts_paid_is_closed_and_any_other_end_is_terminated(state=None):
    """One contract either way: CLOSED stays paid-off; WRITTEN_OFF and TERMINATED do not
    fold into it (they used to — a written-off default read as "ปิด")."""
    case = _case_of("C-002032")            # NPL, one contract, live
    contract = _contract_of(case["customer_uid"])
    for status, expected in (("CLOSED", "CLOSED"), ("WRITTEN_OFF", "TERMINATED"),
                             ("TERMINATED", "TERMINATED"), ("NON_PERFORMING", "NPL")):
        cases._set_contract_fields(contract, status=status)
        cases.follow_system_payment_status(contract)
        assert case["payment_status"] == expected, status


def test_a_live_contract_keeps_the_case_out_of_terminated():
    """A second, still-active contract means the account has not ended: the status
    follows the live one, never the terminated one."""
    customer = journey.customer_by_uid(_case_of("C-002032")["customer_uid"])
    original = cases.contract_field_of(customer.contracts[0], "status")
    extra = types.SimpleNamespace(uid="ct-extra", customer_uid=customer.uid, status="ACTIVE")
    customer.contracts.append(extra)
    try:
        cases._set_contract_fields(customer.contracts[0], status="TERMINATED")
        assert cases._payment_status_from_contracts(customer) == "CURRENT"
    finally:
        customer.contracts.remove(extra)
        cases._set_contract_fields(customer.contracts[0], status=original)


# --- the act and its money record -------------------------------------------------------

def test_termination_gate_blocks_a_live_contract_that_owes(monkeypatch):
    from app import main
    block = types.SimpleNamespace(closing_balance=Decimal("1000.00"),
                                  full_payoff_amount=Decimal("1200.00"))
    monkeypatch.setattr(main, "_contract_view", lambda contract: (contract, 0, None, block, None))
    contract = types.SimpleNamespace(uid="ct-1", customer_uid="c-1")
    customer = types.SimpleNamespace(contracts=[contract])
    blocking, checks = cases.termination_gate(customer)
    assert blocking == [{"contract_uid": "ct-1", "outstanding": "1000.00", "payoff_amount": "1200.00"}]
    assert checks == []


@pytest.mark.parametrize("role,actor", [
    ("OFFICER", "thip"), ("SUPERVISOR", "settasak"),
    ("MANAGER", "settasak"), ("OWNER", "owner"),
])
def test_the_terminate_route_allows_officer_and_above_with_a_balance(role, actor):
    case = _case_of("C-002032")
    uid = case["customer_uid"]
    contract = _contract_of(uid)
    from app import main
    assert main._contract_view(contract)[3].closing_balance > 0
    before = client.get("/v1/cases/by-customer/%s" % uid).json()
    response = client.post("/v1/cases/by-customer/%s:terminate" % uid,
                           headers={"X-Volt-Role": role, "X-Volt-Officer": actor},
                           json={"cause": "CUSTOMER_REQUEST", "reason": "ลูกค้าแจ้งขอยกเลิกทาง LINE"})
    assert response.status_code == 200, response.json()
    entry = _latest_audit()
    assert entry["act"] == "CONTRACT_TERMINATED"
    assert (entry["actor_claimed"], entry["actor_role"]) == (actor, role)
    assert entry["detail"]["contract_terminated"]["cause"] == "CUSTOMER_REQUEST"
    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    assert detail["case"]["payment_status"] == "TERMINATED"
    assert detail["case"]["termination"]["by"] == actor
    assert detail["case"]["termination"]["instrument"] == "TERMINATE_ACT"
    assert detail["contracts"][0]["status"] == "TERMINATED"
    assert detail["work_item"]["aggregate_outstanding"] == before["work_item"]["aggregate_outstanding"]
    assert detail["payment_summary"]["totals"]["outstanding_amount"] == before["payment_summary"]["totals"]["outstanding_amount"]
    assert detail["invoices"] == before["invoices"]
    assert detail["receipts"] == before["receipts"]
    assert not any(item["customer"]["uid"] == uid for item in client.get("/v1/today").json()["items"])


def test_terminate_route_excludes_ops_and_requires_cause_and_reason():
    uid = _case_of("C-002032")["customer_uid"]
    ops = client.post("/v1/cases/by-customer/%s:terminate" % uid,
                      headers={"X-Volt-Role": "OPS"}, json={"cause": "DEFAULT", "reason": "x"})
    assert (ops.status_code, ops.json()["code"]) == (403, "forbidden")
    unknown = client.post("/v1/cases/by-customer/%s:terminate" % uid, headers=MANAGER,
                          json={"cause": "WHATEVER", "reason": "x"})
    assert (unknown.status_code, unknown.json()["code"]) == (422, "termination_cause_unknown")
    blank = client.post("/v1/cases/by-customer/%s:terminate" % uid, headers=MANAGER,
                        json={"cause": "DEFAULT", "reason": "  "})
    assert (blank.status_code, blank.json()["code"]) == (422, "reason_required")


def test_terminate_route_does_not_require_instalment_review(monkeypatch):
    uid = _case_of("C-002032")["customer_uid"]
    monkeypatch.setattr(cases, "termination_gate", lambda customer: (
        [{"contract_uid": customer.contracts[0].uid, "reason": "BALANCE_REQUIRES_REVIEW",
          "outstanding": None, "payoff_amount": None}], []))
    response = client.post("/v1/cases/by-customer/%s:terminate" % uid,
                           headers={"X-Volt-Role": "OFFICER", "X-Volt-Officer": "thip"},
                           json={"cause": "DEFAULT", "reason": "หลักฐานยังรอตรวจ"})
    assert response.status_code == 200, response.json()


def test_the_terminate_route_cannot_run_twice():
    case = _case_of("C-002032")
    uid = case["customer_uid"]
    first = client.post("/v1/cases/by-customer/%s:terminate" % uid, headers=MANAGER,
                        json={"cause": "DEFAULT", "reason": "ยึดคืนแล้ว"})
    assert first.status_code == 200, first.json()
    archive_count = client.get("/v1/terminated-customers", params={"q": uid}).json()["meta"]["total"]
    again = client.post("/v1/cases/by-customer/%s:terminate" % uid, headers=MANAGER,
                        json={"cause": "DEFAULT", "reason": "ยึดคืนแล้ว"})
    assert again.json()["code"] == "status_unchanged"
    assert client.get("/v1/terminated-customers", params={"q": uid}).json()["meta"]["total"] == archive_count


def test_the_payment_status_route_refuses_terminated():
    uid = _case_of("C-002032")["customer_uid"]
    r = client.post("/v1/cases/by-customer/%s/payment-status" % uid,
                    json={"code": "TERMINATED", "reason": "x"},
                    # AUTHORISED TEST EDIT 43 (R-B): the manual status is Manager-only now.
                    headers={"X-Volt-Role": "MANAGER"})
    assert (r.status_code, r.json()["code"], r.json()["error_id"]) == (
        422, "payment_status_terminate_via_route", "DEBT-COL-0475")


def test_record_termination_refuses_an_unknown_cause_and_a_blank_reason():
    contract = _contract_of(_case_of("C-002032")["customer_uid"])
    with pytest.raises(CaseError) as bad_cause:
        cases.record_termination(contract, cause="NOPE", by="ploy", reason="x", instrument="TEST")
    assert bad_cause.value.code == "termination_cause_unknown"
    with pytest.raises(CaseError) as bad_reason:
        cases.record_termination(contract, cause="DEFAULT", by="ploy", reason="  ", instrument="TEST")
    assert bad_reason.value.code == "reason_required"


def test_the_write_off_stamps_the_default_cause_and_keeps_its_own_act():
    """The OWNER write-off is the instrument that ends a default contract; the audit
    row stays the route's RECOVERY_RESOLVED and carries the termination as detail."""
    uid = _case_of("C-002034")["customer_uid"]
    rec = next(r for r in client.get("/v1/recovery-cases").json()["recovery_cases"]
               if r["contract_uid"] == _contract_of(uid).uid)
    r = client.post("/v1/recovery-cases/%s:resolve" % rec["uid"],
                    json={"outcome": "CLOSED_WRITE_OFF", "role": "OWNER"})
    assert r.status_code == 200, r.json()
    entry = _latest_audit()          # before any further GET: the read is its own act
    assert entry["act"] == "RECOVERY_RESOLVED"
    assert entry["detail"]["contract_terminated"]["status"] == "WRITTEN_OFF"
    # The contract's own status travels on the served case detail (session-scoped read
    # inside the request's own session — the test's process context is a different one).
    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    case = detail["case"]
    assert case["payment_status"] == "TERMINATED"
    assert case["termination"]["cause"] == "DEFAULT"
    assert case["termination"]["instrument"] == "WRITE_OFF"
    assert next(k["status"] for k in detail["contracts"]) == "WRITTEN_OFF"


def test_a_cooperative_decommission_terminates_at_the_customers_request():
    rows = client.get("/v1/npl-cases").json()["npl_cases"]
    npl = next(r for r in rows if not r.get("recovery_uid"))
    opened = client.post("/v1/npl-cases/%s/recovery" % npl["uid"],
                         json={"strategy": "COOP_DECOMMISSION"}, headers=MANAGER)
    assert opened.status_code in (200, 201), opened.json()
    rec = opened.json()["recovery"]
    resolved = client.post("/v1/recovery-cases/%s:resolve" % rec["uid"],
                           json={"outcome": "FULL", "role": "MANAGER"})
    assert resolved.status_code == 200, resolved.json()
    case = client.get("/v1/cases/by-customer/%s" % npl["customer_uid"]).json()["case"]
    assert case["payment_status"] == "TERMINATED"
    assert case["termination"]["cause"] == "CUSTOMER_REQUEST"
    assert case["termination"]["instrument"] == "RECOVERY_FULL"
    contract_statuses = {k["status"] for k in client.get(
        "/v1/cases/by-customer/%s" % npl["customer_uid"]).json()["contracts"]}
    assert contract_statuses == {"TERMINATED"}


def test_sop_says_why_the_account_is_off_the_journey():
    case = _case_of("C-002032")
    cases.record_termination(_contract_of(case["customer_uid"]), cause="CUSTOMER_REQUEST",
                             by="ploy", reason="ลูกค้าขอยกเลิก", instrument="TERMINATE_ACT")
    step = sop.walkthrough(case)
    assert step["placement"] == "OFF_JOURNEY"
    assert "ลูกค้าขอยุติสัญญา" in step["reason_th"]
    assert "customer's request" in step["reason_en"]


# --- the sheet's own vocabulary and the honest reconciliation row -----------------------

def test_the_tracking_category_mapping_names_both_scenarios():
    default = cases.termination_from_tracking({"category": "Repossessed - Sold"})
    assert default["cause"] == "DEFAULT" and default["instrument"] == "SHEET_CATEGORY"
    assert cases.termination_from_tracking({"category": "Repossessed - Ready Resell"})["cause"] == "DEFAULT"
    requested = cases.termination_from_tracking({"category": "NPL - Cooperative - Decommission"})
    assert requested["cause"] == "CUSTOMER_REQUEST"
    assert cases.termination_from_tracking({"category": "NPL - Restructure"}) is None
    assert cases.termination_from_tracking({}) is None


def test_the_sheets_own_decommission_row_builds_as_terminated():
    """The fixture book really carries one: the sheet's Cooperative - Decommission row
    is the customer-request termination, and the case derives TERMINATED — never the
    NPL it used to read."""
    customers = book.build()[0]
    customer = next(c for c in customers if c.customer_no == "99999000171")
    assert customer.contracts[0].status == "TERMINATED"
    assert customer.contracts[0].termination["cause"] == "CUSTOMER_REQUEST"
    assert cases._payment_status_from_contracts(customer) == "TERMINATED"


def test_the_reconciliation_names_terminated_as_unjudged_while_the_sheet_cannot_say_it():
    result = imports._reconcile(
        [{"payment_status": "Current"}, {"payment_status": "Terminated"}],
        [{"payment_status": "Current", "npl_type": None, "count": 1}], None, None)
    row = next(r for r in result["rows"] if r["payment_status"] == "TERMINATED")
    assert row["sheet"] is None and row["imported"] == 1 and row["judged"] is False
    assert "TERMINATED" in result["unjudged"]     # the synthetic pivot expresses none of them
    # The rows the sheet DOES express still decide the basis — an unjudged value is not
    # allowed to turn a matching import red, and it is never a green tick either.
    assert result["basis"] == "RECONCILED"
    assert "Terminated" in row["note"]


def test_the_cause_dictionary_carries_both_scenarios():
    codes = {row["code"] for row in dictionaries.for_current().resolve.__self__.all("TERMINATION_CAUSE")} \
        if False else {row["code"] for row in dictionaries.SEED["TERMINATION_CAUSE"]}
    assert codes == {"DEFAULT", "CUSTOMER_REQUEST"}
    d = dictionaries.for_current()
    assert d.resolve("TERMINATION_CAUSE", "Terminated - Customer request") == "CUSTOMER_REQUEST"
