"""Only genuinely customer-owned Debt mutations may leave the global barrier."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text

from app import business_records, cases, main, migrate, session
from app import customer_transactions as transactions
from app.production_unit import CURRENT


def scope(action, uid="synthetic-a"):
    return {"method": "POST", "path": "/v1/cases/by-customer/%s/%s" % (uid, action)}


@pytest.mark.parametrize("action,body", [("notes", {"text": "Synthetic note"}),
    ("next-action", {"next_action": "CALLBACK", "next_action_on": "2026-10-24"}),
    ("dc-status", {"code": "CONTACT_BACK", "reason": "Synthetic follow-up"}),
    ("contacts", {"result": "REACHED_PTP", "ptp": {"amount": "100", "date": "2026-10-24"}})])
def test_safe_direct_plans_use_uri_owner_and_capture_json(action, body):
    request = scope(action)
    assert transactions.captures_json(request)
    planned = transactions.plan(request, dict(body, customer_uid="attacker-other-owner"))
    assert planned.customer_uid == "synthetic-a"


@pytest.mark.parametrize("action,body", [("notes", {"attachment_uids": ["attachment"]}),
    ("contacts", {"issue": {"ticket": "synthetic"}}),
    ("contacts", {"service_ticket": {"ticket": "synthetic"}}),
    ("contacts", {"notes": [{"text": "Synthetic", "attachment_uids": ["attachment"]}]}),
    ("contacts", {"ptp": {"attachments": ["attachment"]}}), ("next-action", []),
    ("payment-status", {"code": "PAID"}), ("npl-type", {"code": "NPL"})])
def test_shared_side_effects_and_unaudited_actions_stay_global(action, body):
    assert transactions.plan(scope(action), body) is None


def test_person_daily_slot_and_renegotiation_never_take_customer_shortcut():
    for path in ("/v1/contacts", "/v1/case-ptps/ptp-synthetic:renegotiate"):
        request = {"method": "POST", "path": path}
        assert not transactions.captures_json(request)
        assert transactions.plan(request, {}) is None


@pytest.fixture
def capacity(pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    return pg_conn


@contextmanager
def owned_unit(conn, uid=None):
    unit = {"conn": conn, "capacity": True, "mutation": True, "subject": "synthetic-owner", "version": 0}
    if uid:
        unit["customer_uid"] = uid
    token = CURRENT.set(unit)
    slot = session.CURRENT.set("scope-test-" + str(uid))
    touched = session.TOUCHED.set(set())
    try:
        yield unit
    finally:
        for store in session.REGISTRY:
            store._by_session.pop(session.current(), None)
        session.TOUCHED.reset(touched)
        session.CURRENT.reset(slot)
        CURRENT.reset(token)


def seed_state(conn):
    value = cases.CaseState()
    for index, customer in enumerate(main.CUSTOMERS[:2]):
        value.cases[customer.uid] = cases._blank_case("case-synthetic-%d" % index, customer.uid,
            customer.customer_no, getattr(customer, "volt_id", None), "LEASE", "synthetic-owner", "LATE", "SYNTHETIC", {})
    with owned_unit(conn):
        business_records.save(conn, "cases.state", value)
    conn.commit()
    return list(value.cases)


def test_child_owner_is_indexed_and_revalidated_after_lock(capacity):
    capacity.execute(text("insert into app.business_record(store_key,record_key,payload,customer_uid) "
                          "values('cases.state','ptps/\"ptp-synthetic\"','{}','owner-a')"))
    request = {"method": "POST", "path": "/v1/case-ptps/ptp-synthetic:close"}
    assert transactions.captures_json(request)
    planned = transactions.plan(request, {"outcome": "BROKEN"}, capacity)
    assert planned.customer_uid == "owner-a"
    transactions.revalidate(capacity, planned)
    capacity.execute(text("update app.business_record set customer_uid='owner-b' where store_key='cases.state'"))
    with pytest.raises(Exception) as changed:
        transactions.revalidate(capacity, planned)
    assert changed.value.code == "case_ownership_changed"
    assert transactions.plan({"method": "POST", "path": "/v1/case-ptps/missing:close"}, {}, capacity) is None


def test_parallel_customer_dc_and_next_actions_do_not_overwrite_each_other(capacity, pg_url):
    uids = seed_state(capacity)
    barrier = Barrier(2)
    engine = create_engine(pg_url, hide_parameters=True)
    def mutate(index):
        with engine.connect() as conn, conn.begin():
            conn.execute(text("select pg_advisory_xact_lock(hashtextextended(:u,0))"), {"u": "volt-customer:" + uids[index]})
            with owned_unit(conn, uids[index]):
                own, _ = business_records.load(conn, "cases.state")
                barrier.wait(timeout=5)
                case = own.cases[uids[index]]
                cases.set_dc_status(own, case, "CONTACT_BACK", "synthetic-owner", note="Synthetic worker %d" % index)
                cases.set_next_action(own, case, "CALLBACK", "2026-10-24", "synthetic-owner")
                business_records.save(conn, "cases.state", own)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(mutate, range(2)))
        with owned_unit(capacity):
            saved, _ = business_records.load(capacity, "cases.state")
        assert all(saved.cases[uid]["dc_status"] == "CONTACT_BACK" for uid in uids)
        assert all(saved.cases[uid]["next_action"] == "CALLBACK" for uid in uids)
        assert sum(row["kind"] == "DC_STATUS_SET" for row in saved.events) == 2
        assert sum(row["kind"] == "NEXT_ACTION_SET" for row in saved.events) == 2
    finally:
        engine.dispose()


def test_real_contact_ptp_and_close_are_customer_atomic(capacity):
    first, second = seed_state(capacity)
    with owned_unit(capacity, first):
        own, _ = business_records.load(capacity, "cases.state")
        case = own.cases[first]
        contact, ptp, issue = cases.log_contact(own, case, {"result": "REACHED_PTP", "counted": False,
            "not_counted": True, "ptp": {"amount": "100.00", "date": "2026-10-24"}}, by="synthetic-owner")
        assert issue is None and contact["customer_uid"] == first and ptp["customer_uid"] == first
        cases.close_ptp(own, case, ptp["uid"], "BROKEN", "2026-10-23", "synthetic-owner", reason="Synthetic explicit early break")
        business_records.save(capacity, "cases.state", own)
    with owned_unit(capacity):
        saved, _ = business_records.load(capacity, "cases.state")
    assert len(saved.contact_log) == 1 and len(saved.ptps) == 1
    assert saved.cases[first]["broken_ptp_count"] == 1
    assert saved.cases[second]["broken_ptp_count"] == 0
    assert saved.ptps[ptp["uid"]]["status"] == "BROKEN"


def test_failure_rolls_back_contact_ptp_and_derived_status(capacity):
    first, second = seed_state(capacity)
    savepoint = capacity.begin_nested()
    with owned_unit(capacity, first):
        own, _ = business_records.load(capacity, "cases.state")
        cases.log_contact(own, own.cases[first], {"result": "REACHED_PTP", "ptp": {"amount": "100", "date": "2026-10-24"}}, "synthetic-owner")
        business_records.save(capacity, "cases.state", own)
    savepoint.rollback()
    with owned_unit(capacity):
        saved, _ = business_records.load(capacity, "cases.state")
    assert saved.contact_log == [] and saved.ptps == {}
    assert saved.cases[first]["open_ptp_uid"] is None and saved.cases[second]["open_ptp_uid"] is None
