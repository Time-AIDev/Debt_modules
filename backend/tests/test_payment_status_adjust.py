"""A person may change the case's payment status, with a reason (Arina, 2026-09-14).

Spec: docs/archive/superpowers/specs/2026-09-14-payment-status-adjustment-design.md
"""
import pytest
from fastapi.testclient import TestClient

from app import audit_store, cases
from app.cases import CaseError
from app.main import app


@pytest.fixture
def state():
    return cases.for_current()


def late_case(state):
    return next(c for c in state.cases.values() if c["payment_status"] == "LATE")


def events(state):
    return [e for e in state.events if e["kind"] == "PAYMENT_STATUS_SET"]


# --- the act (spec §3.1, §3.2) ------------------------------------------------------

def test_a_seeded_case_holds_the_system_answer_and_no_person_change(state):
    for case in state.cases.values():
        assert case["payment_status_system"] == case["payment_status"]
        assert case["payment_status_set_by"] is None
        assert case["payment_status_reason"] is None


def test_a_person_changes_it_with_a_reason_and_the_system_answer_stays_beside_it(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="ลูกค้าโอนครบแล้ว รอ PEAK")
    assert case["payment_status"] == "CURRENT"
    assert case["payment_status_system"] == "LATE"
    assert case["payment_status_set_by"] == "thip"
    assert case["payment_status_reason"] == "ลูกค้าโอนครบแล้ว รอ PEAK"
    event = events(state)[-1]
    assert (event["from"], event["code"], event["system"]) == ("LATE", "CURRENT", "LATE")
    assert event["by"] == "thip" and event["reason"] == "ลูกค้าโอนครบแล้ว รอ PEAK"
    assert event["ended"] is None and event["on"]


def test_no_reason_is_refused_and_changes_nothing(state):
    case = late_case(state)
    for blank in (None, "", "   "):
        with pytest.raises(CaseError) as err:
            cases.set_payment_status(state, case, "CURRENT", by="thip", reason=blank)
        assert err.value.code == "reason_required"
    assert case["payment_status"] == "LATE"
    assert events(state) == []


def test_an_unknown_status_is_refused_before_the_reason_is_checked(state):
    case = late_case(state)
    with pytest.raises(CaseError) as err:
        cases.set_payment_status(state, case, "PAID", by="thip", reason=None)
    assert err.value.code == "payment_status_unknown"
    assert case["payment_status"] == "LATE"


def test_the_value_it_already_holds_is_refused(state):
    case = late_case(state)
    with pytest.raises(CaseError) as err:
        cases.set_payment_status(state, case, "LATE", by="thip", reason="ซ้ำ")
    assert err.value.code == "status_unchanged"
    assert events(state) == []


def test_putting_it_back_to_the_system_answer_clears_the_person_change(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    cases.set_payment_status(state, case, "LATE", by="nantapol", reason="ยอดยังไม่เข้า")
    assert case["payment_status"] == "LATE"
    assert case["payment_status_set_by"] is None and case["payment_status_reason"] is None
    assert [e["by"] for e in events(state)] == ["thip", "nantapol"]


def _contract_of(case):
    from app import main
    return main.BY_CUSTOMER[case["customer_uid"]].contracts[0]


# --- the system wins (spec §3.3) ----------------------------------------------------

def test_a_contract_status_change_moves_the_case_to_the_system_answer(state):
    """Before this, nothing re-worked the status: declaring NPL on C-002032 left LATE."""
    case = late_case(state)
    cases._set_contract_fields(_contract_of(case), status="NON_PERFORMING")
    assert case["payment_status"] == "NPL"
    assert case["payment_status_system"] == "NPL"
    event = events(state)[-1]
    assert (event["from"], event["code"], event["by"], event["ended"]) == ("LATE", "NPL", "SYSTEM", None)


def test_the_system_ends_a_person_change_and_says_whose_it_was(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    cases._set_contract_fields(_contract_of(case), status="NON_PERFORMING")
    assert case["payment_status"] == "NPL"
    assert case["payment_status_set_by"] is None and case["payment_status_reason"] is None
    event = events(state)[-1]
    assert (event["by"], event["from"], event["code"]) == ("SYSTEM", "CURRENT", "NPL")
    assert event["ended"] == {"by": "thip", "code": "CURRENT", "reason": "โอนแล้ว"}


def test_a_status_write_that_leaves_the_system_answer_alone_keeps_the_person_change(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    before = len(events(state))
    cases._set_contract_fields(_contract_of(case), status="PAST_DUE")   # still LATE
    assert case["payment_status"] == "CURRENT" and case["payment_status_set_by"] == "thip"
    assert len(events(state)) == before


def test_a_write_without_status_does_not_re_work_it(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    before = len(events(state))
    cases._set_contract_fields(_contract_of(case), fee_state="SERVICE_HOLD_FAULT_CONFIRMED")
    assert case["payment_status"] == "CURRENT"
    assert len(events(state)) == before


def _journey_case(client, customer_no):
    from app import main
    for jc in client.get("/v1/cases").json()["cases"]:
        if main.BY_CUSTOMER[jc["customer_uid"]].customer_no == customer_no:
            return jc
    raise AssertionError("no journey case for %s" % customer_no)


def _latest_audit():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def test_declaring_npl_moves_the_case_and_the_declaration_row_says_so():
    """C-002032 read LATE after its NPL declaration before this change (spec §1.2)."""
    client = TestClient(app)
    jc = _journey_case(client, "C-002032")
    uid = jc["customer_uid"]
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "LATE"
    response = client.post("/v1/cases/%s:advance" % jc["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "note": "ครบ 90 วัน"})
    assert response.status_code == 200
    # Read the audit row BEFORE the next GET: opening a case is itself a logged read.
    entry = _latest_audit()
    assert entry["route_template"] == "/v1/cases/{uid}:advance"
    assert entry["detail"]["payment_status_followed_system"] == {"from": "LATE", "to": "NPL", "ended": None}
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "NPL"


# --- the route (spec §3.2, §3.5) ----------------------------------------------------

def _late_customer(client):
    rows = client.get("/v1/workbook").json()["rows"]
    return next(r["customer"]["uid"] for r in rows if r["case"]["payment_status"] == "LATE")


def test_the_route_changes_it_and_the_audit_row_says_from_to_system_and_why():
    client = TestClient(app)
    uid = _late_customer(client)
    response = client.post("/v1/cases/by-customer/%s/payment-status" % uid,
                           json={"code": "CURRENT", "reason": "ลูกค้าโอนครบแล้ว"},
                           # AUTHORISED TEST EDIT 43 (R-B, feedback-r2 TASK-220): the
                           # manual status is a Manager's exception now; the actor stays thip.
                           headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "thip"})
    assert response.status_code == 200
    body = response.json()["case"]
    assert body["payment_status"] == "CURRENT" and body["payment_status_system"] == "LATE"
    assert body["payment_status_set_by"] == "thip"
    assert body["payment_status_reason"] == "ลูกค้าโอนครบแล้ว"
    entry = _latest_audit()
    assert entry["act"] == "PAYMENT_STATUS_SET"
    assert (entry["subject_type"], entry["subject_uid"]) == ("customer", uid)
    assert entry["detail"]["from"] == "LATE" and entry["detail"]["to"] == "CURRENT"
    assert entry["detail"]["system"] == "LATE" and entry["detail"]["reason"] == "ลูกค้าโอนครบแล้ว"


def test_note_is_accepted_as_the_reason():
    client = TestClient(app)
    uid = _late_customer(client)
    response = client.post("/v1/cases/by-customer/%s/payment-status" % uid,
                           json={"code": "NPL", "note": "ผู้จัดการยืนยัน"},
                           headers={"X-Volt-Role": "MANAGER"})
    assert response.status_code == 200
    assert response.json()["case"]["payment_status_reason"] == "ผู้จัดการยืนยัน"


def test_the_route_refuses_no_reason_an_unknown_status_and_the_same_status():
    client = TestClient(app)
    uid = _late_customer(client)
    url = "/v1/cases/by-customer/%s/payment-status" % uid
    no_reason = client.post(url, json={"code": "CURRENT"}, headers={"X-Volt-Role": "MANAGER"})
    assert (no_reason.status_code, no_reason.json()["code"]) == (422, "reason_required")
    unknown = client.post(url, json={"code": "PAID", "reason": "x"}, headers={"X-Volt-Role": "MANAGER"})
    assert (unknown.status_code, unknown.json()["code"]) == (422, "payment_status_unknown")
    assert unknown.json()["error_id"] == "DEBT-COL-0459"
    assert unknown.json()["message_th"] == "ไม่รู้จักสถานะการชำระนี้"
    same = client.post(url, json={"code": "LATE", "reason": "x"}, headers={"X-Volt-Role": "MANAGER"})
    assert (same.status_code, same.json()["code"]) == (409, "status_unchanged")
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "LATE"


def test_an_unknown_customer_is_a_404():
    client = TestClient(app)
    response = client.post("/v1/cases/by-customer/no-such-customer/payment-status",
                           json={"code": "CURRENT", "reason": "x"})
    assert response.status_code == 404


# --- a case restored from an older saved session (final review M2) -----------------

def test_a_case_missing_the_new_fields_backfills_from_its_own_status(state):
    """A session restored from Postgres that predates this change has no
    payment_status_system / payment_status_set_by / payment_status_reason. Its
    status was the system's own answer then, so that is where the backfill starts."""
    case = late_case(state)
    del case["payment_status_system"], case["payment_status_set_by"], case["payment_status_reason"]
    cases._set_contract_fields(_contract_of(case), status="PAST_DUE")   # still LATE
    assert events(state) == []
    assert case["payment_status"] == "LATE"
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    cases.set_payment_status(state, case, "LATE", by="nantapol", reason="ยอดยังไม่เข้า")
    assert case["payment_status_set_by"] is None


# --- two outer routes have no test of the audit merge (final review M8) ------------

def test_confirming_npl_from_a_manager_review_says_so_in_the_audit_row():
    """C-000871's BROKEN_PTP review is OPEN, CONFIRM_NPL is on offer (not cash), and
    the case reads LATE — the review decision runs _set_contract_fields underneath."""
    from app import main
    client = TestClient(app)
    uid = next(c for c in main.CUSTOMERS if c.customer_no == "C-000871").uid
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "LATE"
    reviews = client.get("/v1/manager-review").json()["reviews"]
    review = next(r for r in reviews if r["customer"]["customer_no"] == "C-000871"
                  and r["status"] == "OPEN" and "CONFIRM_NPL" in r["available_decisions"])
    response = client.post("/v1/manager-review/%s:decide" % review["uid"],
                           json={"decision": "CONFIRM_NPL", "role": "OWNER"})
    assert response.status_code == 200
    entry = _latest_audit()
    assert entry["detail"]["payment_status_followed_system"] == {"from": "LATE", "to": "NPL", "ended": None}
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "NPL"


def test_writing_off_a_recovery_says_so_in_the_audit_row():
    """C-002034 (seeded recovery rec-0016 on K-2034-1) is already NPL; writing off its
    one contract closes it."""
    client = TestClient(app)
    uid = _journey_case(client, "C-002034")["customer_uid"]
    before = client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"]
    assert before == "NPL"
    recs = client.get("/v1/recovery-cases").json()["recovery_cases"]
    rec = next(r for r in recs if r["contract_uid"] == _contract_of({"customer_uid": uid}).uid)
    response = client.post("/v1/recovery-cases/%s:resolve" % rec["uid"],
                           json={"outcome": "CLOSED_WRITE_OFF", "role": "OWNER"})
    assert response.status_code == 200
    entry = _latest_audit()
    after = client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"]
    assert entry["detail"]["payment_status_followed_system"]["from"] == before
    assert entry["detail"]["payment_status_followed_system"]["to"] == after


# --- design F2: a PEAK-linked customer's LATE/CURRENT comes from PEAK (Task 11) ----

def test_a_linked_customers_status_is_peaks_not_the_sheets(monkeypatch):
    from app import cases, journey
    from app.config import settings
    from tests.test_peak_book import _with_peak, PAID, LATE
    # A LEASE customer the sheet marks LATE, whose PEAK invoices are all paid.
    customer, _ = _with_peak([PAID])
    assert cases._payment_status(customer) == "CURRENT"
    customer, _ = _with_peak([PAID, LATE])
    assert cases._payment_status(customer) == "LATE"
    monkeypatch.setattr(settings, "peak_report_drives_status", False)
    assert cases._payment_status(customer) == cases._payment_status_from_contracts(customer)


def test_npl_and_closed_still_win_over_peak():
    from app import cases
    from tests.test_peak_book import _with_peak, PAID
    customer, _ = _with_peak([PAID])
    cases._set_contract_fields(customer.contracts[0], status="NON_PERFORMING")
    assert cases._payment_status(customer) == "NPL"


def test_follow_system_for_all_writes_one_event_per_case_that_moved():
    from app import cases
    from tests.test_peak_book import _with_peak, PAID
    state = cases.for_current()
    customer, _ = _with_peak([PAID])
    case = state.cases[customer.uid]
    case["payment_status_system"], case["payment_status"] = "LATE", "LATE"
    moved = cases.follow_system_for_all()
    assert case in moved and case["payment_status"] == "CURRENT"
    ev = [e for e in state.events if e["kind"] == "PAYMENT_STATUS_SET" and e["case_uid"] == case["uid"]][-1]
    assert ev["by"] == "SYSTEM" and ev["code"] == "CURRENT" and ev["from"] == "LATE"
    assert cases.follow_system_for_all() == [], "nothing moved the second time"


# --- R-B / feedback-r2 TASK-220: the Manager's exception (ADDITION) ------------------

def test_the_manual_route_is_a_managers_exception_and_the_answer_names_the_system(state):
    """The manager's line (D04): the system owns this status. A person may still
    overrule it, as a Manager or the Owner, and the answer carries the system's own
    value in note_th. An OFFICER is refused before anything is written."""
    client = TestClient(app)
    client.cookies.set("volt_session", "shared")   # the same session the state fixture reads
    uid = _late_customer(client)
    case = state.cases[uid]
    before = (case["payment_status"], len(events(state)))

    refused = client.post("/v1/cases/by-customer/%s/payment-status" % uid,
                          json={"code": "CURRENT", "reason": "ลูกค้าโอนครบแล้ว"},
                          headers={"X-Volt-Officer": "thip"})
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    assert (case["payment_status"], len(events(state))) == before

    allowed = client.post("/v1/cases/by-customer/%s/payment-status" % uid,
                          json={"code": "CURRENT", "reason": "ลูกค้าโอนครบแล้ว"},
                          headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"})
    assert allowed.status_code == 200
    assert case["payment_status"] == "CURRENT"
    assert allowed.json()["note_th"] == "สถานะตามระบบคือ %s · ปรับด้วยมือโดยผู้จัดการ" % before[0]
