"""D05 / Q6 — a receipt before the promise date raises one notice (feedback-r2 TASK-221).

The money is visible (the receipt is on the case); the case owner gets a calendar
notice so they close the promise as paid. Every test here is an ADDITION.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import journey, notices, ptp_watch
from app.config import settings
from app.main import app

BD = settings.business_date
OFFICER = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _case_without_promise(state):
    return next(c for c in state.cases.values()
                if c["officer_uid"] and not c["open_ptp_uid"] and not c["review_uid"])


def _make_promise(client, uid, day):
    response = client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER,
                           json={"result": "REACHED_PTP", "counted": False, "amount_stated": True,
                                 "ptp": {"amount": "1000.00", "date": str(day)}})
    assert response.status_code == 201, response.text
    return response.json()["ptp"]


def _set_peak(customer, doc, paid_on, amount="1000.00", receipt_no="RE-1"):
    # the served book's own block shape (book_source.py); synthetic fixtures carry
    # no sheet at all, so the whole attribute is assigned.
    customer.sheet = {"peak": {"report_as_of": "2026-09-16", "invoices": [{
        "doc_no": doc, "status": "AWAITING", "amount_awaiting": amount,
        "payment": {"on": str(paid_on), "amount": amount, "receipt_no": receipt_no},
    }]}}


def test_a_receipt_before_the_date_stamps_the_promise_and_notices_once(client):
    state = cases_domain.for_current()
    case = _case_without_promise(state)
    promise = _make_promise(client, case["customer_uid"], BD + timedelta(days=10))
    customer = journey.customer_by_uid(case["customer_uid"])
    _set_peak(customer, "IVT-1", BD + timedelta(days=1))

    noticed = ptp_watch.notice_early_payments(journey.for_current(), state, BD)
    assert noticed == [promise["uid"]]
    stamped = state.ptps[promise["uid"]]
    assert stamped["paid_before_due"] == {"receipt_no": "RE-1", "on": str(BD + timedelta(days=1)),
                                          "amount": "1000.00"}
    assert any(e["kind"] == "PTP_PAYMENT_NOTICED" and e.get("ptp_uid") == promise["uid"]
               for e in state.events)
    rows = notices.list_for(case["officer_uid"], BD, BD)
    assert len(rows) == 1 and "เงินเข้าก่อนนัด" in rows[0]["title"]
    assert "RE-1" in rows[0]["text"] and "ยืนยันปิดนัดชำระ" in rows[0]["text"]

    # idempotent: the stamp is the guard, so a second apply notices nothing again
    assert ptp_watch.notice_early_payments(journey.for_current(), state, BD) == []
    assert len(notices.list_for(case["officer_uid"], BD, BD)) == 1


def test_a_receipt_after_the_date_is_not_noticed(client):
    state = cases_domain.for_current()
    case = _case_without_promise(state)
    promise = _make_promise(client, case["customer_uid"], BD + timedelta(days=5))
    _set_peak(journey.customer_by_uid(case["customer_uid"]), "IVT-2", BD + timedelta(days=6))
    assert ptp_watch.notice_early_payments(journey.for_current(), state, BD) == []
    assert state.ptps[promise["uid"]].get("paid_before_due") is None


def test_a_closed_promise_is_never_noticed(client):
    state = cases_domain.for_current()
    case = _case_without_promise(state)
    promise = _make_promise(client, case["customer_uid"], BD + timedelta(days=4))
    closed = client.post("/v1/case-ptps/%s:close" % promise["uid"],
                         json={"outcome": "KEPT", "reason": "ชำระแล้ว"})
    assert closed.status_code == 200, closed.text
    _set_peak(journey.customer_by_uid(case["customer_uid"]), "IVT-3", BD - timedelta(days=1))
    assert ptp_watch.notice_early_payments(journey.for_current(), state, BD) == []
    assert state.ptps[promise["uid"]].get("paid_before_due") is None


def test_the_officer_closes_the_noticed_promise_as_kept_with_the_receipt(client):
    state = cases_domain.for_current()
    case = _case_without_promise(state)
    promise = _make_promise(client, case["customer_uid"], BD + timedelta(days=9))
    _set_peak(journey.customer_by_uid(case["customer_uid"]), "IVT-4", BD + timedelta(days=2),
              receipt_no="RE-9")
    ptp_watch.notice_early_payments(journey.for_current(), state, BD)
    stamped = state.ptps[promise["uid"]]["paid_before_due"]

    response = client.post("/v1/case-ptps/%s:close" % promise["uid"], headers=OFFICER,
                           json={"outcome": "KEPT", "on": stamped["on"], "reason": stamped["receipt_no"]})
    assert response.status_code == 200, response.text
    assert response.json()["ptp"]["status"] == "KEPT"
    assert response.json()["ptp"]["closed_on"] == stamped["on"]


def test_every_payment_an_invoice_carries_is_read_not_only_the_latest():
    """Fix-all P2: a part-paid invoice serves each receipt in `payments`, and `payment`
    names only the latest — an earlier part payment before the promise date counts."""
    early = {"on": "2026-10-20", "amount": "300.00", "receipt_no": "RE-A"}
    late = {"on": "2026-11-05", "amount": "700.00", "receipt_no": "RE-B"}
    invoices = [{"doc_no": "IVT-3", "payment": late, "payments": [early, late]}]
    assert ptp_watch._paid_before(invoices, "2026-10-30", None) == {
        "receipt_no": "RE-A", "on": "2026-10-20", "amount": "300.00"}


def test_every_healing_session_notices_its_own_promise_and_the_officer_once():
    """Fix-all F2: the scan runs in import_sync.heal_session — every session that heals,
    not only the one that pressed Apply — and the notice uid is derived from owner,
    customer and receipt, so two sessions healing on one receipt write one notice."""
    from app import import_sync, session as session_domain

    sessions = {}
    for name in ("s-early-a", "s-early-b"):
        sessions[name] = TestClient(app)
        sessions[name].cookies.set("volt_session", name)
    token = session_domain.CURRENT.set("s-early-a")
    try:
        case = _case_without_promise(cases_domain.for_current())
    finally:
        session_domain.CURRENT.reset(token)
    uid = case["customer_uid"]
    promised = {name: _make_promise(c, uid, BD + timedelta(days=10))["uid"] for name, c in sessions.items()}
    _set_peak(journey.customer_by_uid(uid), "IVT-5", BD + timedelta(days=1), receipt_no="RE-5")

    for name in sessions:
        token = session_domain.CURRENT.set(name)
        try:
            import_sync.heal_session()
            assert cases_domain.for_current().ptps[promised[name]]["paid_before_due"]["receipt_no"] == "RE-5"
        finally:
            session_domain.CURRENT.reset(token)
    assert len([r for r in notices.list_for(case["officer_uid"], BD, BD) if "RE-5" in r["text"]]) == 1


def test_a_derived_notice_uid_is_written_once_in_postgres_too(pg_conn, monkeypatch):
    """`on conflict (uid) do nothing`: the second writer of the same notice gets None."""
    from sqlalchemy import text
    from app import db, migrate

    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        uid = notices.uid_for("nantapol", "cust-x", "RE-7")
        assert notices.looks_like_uid(uid) and uid == notices.uid_for("nantapol", "cust-x", "RE-7")
        fields = notices.clean({"title": "t", "on": str(BD)}, partial=False)
        assert notices.create("nantapol", fields, uid)["uid"] == uid
        assert notices.create("nantapol", fields, uid) is None
        assert [r["uid"] for r in notices.list_for("nantapol", BD, BD)] == [uid]
    finally:
        pg_conn.execute(text("delete from records.notice"))
        pg_conn.commit()
