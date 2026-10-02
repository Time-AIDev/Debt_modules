"""The manual payment status is shared for everyone (Arina, 2026-09-24; fix-all Leg R).

A manager's change used to live in the acting session only, so a second manager in
another browser kept reading the system's answer. It is written through
app/payment_overrides.py now — records.payment_status_override with a database, a
process dict without one — and every session applies the active rows when the store's
version moves. Setting it back to the system's answer, or the system moving on in any
session, retires it for everyone.
"""
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import cases, db, migrate, payment_overrides
from app import session as session_domain
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "mgr-test"}


def _client(session_id):
    c = TestClient(app)
    c.cookies.set("volt_session", session_id)
    return c


def _late_uid():
    return next(c["customer_uid"] for c in cases.for_current().cases.values() if c["payment_status"] == "LATE")


def _case(client, uid):
    return client.get("/v1/cases/by-customer/%s" % uid).json()["case"]


@pytest.fixture
def in_session():
    """Run domain calls as a named session; CURRENT is put back afterwards."""
    token = session_domain.CURRENT.set(session_domain.SHARED)

    def use(session_id):
        session_domain.CURRENT.set(session_id)
        return cases.for_current()
    try:
        yield use
    finally:
        session_domain.CURRENT.reset(token)


def test_a_second_session_sees_the_override_and_setting_it_back_retires_it_for_both():
    uid = _late_uid()
    first, second = _client("s-shared-a"), _client("s-shared-b")
    assert _case(second, uid)["payment_status"] == "LATE"      # B exists before the change
    url = "/v1/cases/by-customer/%s/payment-status" % uid
    set_ = first.post(url, json={"code": "CURRENT", "reason": "โอนครบแล้ว รอ PEAK"}, headers=MANAGER)
    assert set_.status_code == 200, set_.json()

    seen = _case(second, uid)
    assert seen["payment_status"] == "CURRENT" and seen["payment_status_system"] == "LATE"
    assert seen["payment_status_set_by"] == "mgr-test" and seen["payment_status_reason"] == "โอนครบแล้ว รอ PEAK"
    late_comer = _case(_client("s-shared-c"), uid)                 # a session seeded afterwards
    assert late_comer["payment_status"] == "CURRENT" and late_comer["payment_status_set_by"] == "mgr-test"

    back = second.post(url, json={"code": "LATE", "reason": "ยอดยังไม่เข้า"},
                       headers={"X-Volt-Role": "MANAGER", "X-Volt-Officer": "mgr-other"})
    assert back.status_code == 200, back.json()
    for client in (first, second):
        case = _case(client, uid)
        assert case["payment_status"] == "LATE"
        assert case["payment_status_set_by"] is None and case["payment_status_reason"] is None
    assert payment_overrides.active() == {}


def test_the_system_moving_in_one_session_retires_the_change_for_every_session(in_session):
    from app import main
    state_a = in_session("s-follow-a")
    case_a = next(c for c in state_a.cases.values() if c["payment_status"] == "LATE")
    uid = case_a["customer_uid"]
    cases.set_payment_status(state_a, case_a, "CURRENT", by="mgr-test", reason="โอนแล้ว")

    case_b = in_session("s-follow-b").cases[uid]
    assert case_b["payment_status"] == "CURRENT" and case_b["payment_status_set_by"] == "mgr-test"
    # Session B's contract turns non-performing: its system answer moves, which ends the
    # person's change — for B, and through the shared row for A as well.
    cases._set_contract_fields(main.BY_CUSTOMER[uid].contracts[0], status="NON_PERFORMING")
    assert case_b["payment_status"] == "NPL" and case_b["payment_status_set_by"] is None
    assert payment_overrides.active() == {}

    case_a = in_session("s-follow-a").cases[uid]
    assert case_a["payment_status"] == "LATE"                      # A's own system answer
    assert case_a["payment_status_set_by"] is None and case_a["payment_status_reason"] is None


def test_a_row_set_against_another_system_answer_does_not_apply_and_is_retired(in_session):
    """The row stands only while the case's system answer is still the one it overruled;
    a caught-up session that reads another answer retires it as moot (audit fix)."""
    state = in_session("s-mismatch")
    uid = next(c["customer_uid"] for c in state.cases.values() if c["payment_status"] == "CURRENT")
    payment_overrides.set(uid, "NPL", "LATE", "ตั้งจากเซสชันที่ระบบยังเป็นค้างชำระ", "mgr-test")
    case = in_session("s-mismatch").cases[uid]
    assert case["payment_status"] == "CURRENT" and case["payment_status_set_by"] is None
    assert uid not in payment_overrides.active()


def test_a_row_the_book_moved_away_from_is_retired_and_never_comes_back(in_session, monkeypatch):
    """Audit P4: the book moved while no session holding the row healed (every session
    fresh after a deploy). The first fresh session retires the moot row, so when the book
    returns to the answer it overruled nobody reads the months-old change again."""
    state_a = in_session("s-p4-a")
    case_a = next(c for c in state_a.cases.values() if c["payment_status"] == "LATE")
    uid = case_a["customer_uid"]
    cases.set_payment_status(state_a, case_a, "CURRENT", by="mgr-test", reason="โอนแล้ว รอ PEAK")
    real = cases._payment_status
    monkeypatch.setattr(cases, "_payment_status", lambda c: "CURRENT" if c.uid == uid else real(c))
    moved = in_session("s-p4-b").cases[uid]                       # fresh: the book says CURRENT
    assert (moved["payment_status"], moved["payment_status_set_by"]) == ("CURRENT", None)
    assert uid not in payment_overrides.active()
    monkeypatch.setattr(cases, "_payment_status", lambda c: "LATE" if c.uid == uid else real(c))
    back = in_session("s-p4-c").cases[uid]                        # fresh: the book says LATE again
    assert (back["payment_status"], back["payment_status_set_by"], back["payment_status_reason"]) == ("LATE", None, None)
    held = in_session("s-p4-a").cases[uid]                        # the setter's own session
    assert (held["payment_status"], held["payment_status_set_by"]) == ("LATE", None)


def test_a_session_behind_the_imports_never_judges_a_row_moot(in_session, monkeypatch):
    """A session that has not healed reads the old answer; it leaves the row for a
    caught-up session, and asks again on its next read."""
    from app import data_epoch
    state = in_session("s-behind")
    uid = next(c["customer_uid"] for c in state.cases.values() if c["payment_status"] == "CURRENT")
    payment_overrides.set(uid, "NPL", "LATE", "ผู้จัดการยืนยัน", "mgr-test")
    monkeypatch.setattr(data_epoch, "current", lambda: 7)          # an import this session has not seen
    assert in_session("s-behind").cases[uid]["payment_status"] == "CURRENT"
    assert uid in payment_overrides.active()
    monkeypatch.setattr(data_epoch, "current", lambda: 0)
    in_session("s-behind")
    assert uid not in payment_overrides.active()


def test_a_session_that_applies_or_ends_a_shared_change_writes_it_in_its_history(in_session):
    """Audit fix: the weekly status_changes and npl_movement read the case events, so a
    change another session applied, and its end, are written there too."""
    from app import journey, weekly_figures
    from app.config import settings
    bd = settings.business_date
    state_a = in_session("s-ev-a")
    case_a = next(c for c in state_a.cases.values() if c["payment_status"] == "LATE")
    uid = case_a["customer_uid"]
    in_session("s-ev-b")                                          # B exists before the change
    cases.set_payment_status(state_a, case_a, "NPL", by="mgr-test", reason="ไม่ติดต่อกลับ 90 วัน")

    def history(state):
        return [e for e in state.events if e["kind"] == "PAYMENT_STATUS_SET"
                and e["case_uid"] == state.cases[uid]["uid"]]
    state_b = in_session("s-ev-b")
    assert [(e["from"], e["code"], e["by"], e["reason"], e["on"]) for e in history(state_b)] == [
        ("LATE", "NPL", "mgr-test", "ไม่ติดต่อกลับ 90 วัน", str(bd))]
    movement = weekly_figures.npl_movement(bd, bd, state_b, journey.for_current())
    assert movement["entered"]["by_status_change"] == 1
    assert [r["by"] for r in movement["rows"] if r["customer_uid"] == uid] == ["mgr-test"]
    assert len(history(in_session("s-ev-a"))) == 1                # the setter's own event, once

    cases.set_payment_status(in_session("s-ev-a"), case_a, "LATE", by="mgr-other", reason="ติดต่อได้แล้ว")
    ended = history(in_session("s-ev-b"))[-1]
    assert (ended["from"], ended["code"], ended["by"], ended["ended"]["by"]) == ("NPL", "LATE", "SYSTEM", "mgr-test")


def _lone_case_state(uid):
    return SimpleNamespace(events=[], cases={uid: {
        "uid": "case-" + uid, "customer_uid": uid, "payment_status": "LATE",
        "payment_status_system": "LATE", "payment_status_set_by": None, "payment_status_reason": None}})


def test_memory_mode_never_records_a_version_whose_row_it_missed(monkeypatch):
    """Audit fix: set() moved the counter before it stored the row, so a reader in
    between recorded the new version with no row and never applied it."""
    class SlowDict(dict):
        def __setitem__(self, key, value):
            time.sleep(0.2)                     # the writer is switched out mid-store
            super().__setitem__(key, value)
    monkeypatch.setattr(payment_overrides, "_MEMORY", SlowDict())
    state = _lone_case_state("cust-m")
    writer = threading.Thread(target=lambda: payment_overrides.set("cust-m", "CURRENT", "LATE", "โอนแล้ว", "mgr-test"))
    writer.start()
    time.sleep(0.05)
    cases._apply_shared_overrides(state)        # another session's request, mid-set
    writer.join()
    cases._apply_shared_overrides(state)
    assert state.cases["cust-m"]["payment_status"] == "CURRENT"


# --- with a database: records.payment_status_override ---------------------------------

@pytest.fixture
def wired(monkeypatch, pg_url, pg_conn):
    """The app on the test database. conftest truncates landing/app only, so this file
    clears records.payment_status_override itself, before and after."""
    migrate.apply(pg_conn)
    pg_conn.execute(text("delete from records.payment_status_override"))
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    payment_overrides.reset()
    yield pg_conn
    pg_conn.rollback()
    pg_conn.execute(text("delete from records.payment_status_override"))
    pg_conn.commit()
    payment_overrides.reset()
    db.reset()


def _rows(conn, uid):
    return [dict(r) for r in conn.execute(text(
        "select code, system_code_at_set, reason, set_by, retired_by, retired_at is null as active "
        "from records.payment_status_override where customer_uid = :c order by uid"), {"c": uid}).mappings()]


def test_the_store_keeps_one_active_row_and_its_version_moves(wired):
    before = payment_overrides.version()
    first = payment_overrides.set("cust-x", "CURRENT", "LATE", "โอนแล้ว", "mgr-test")
    assert first["code"] == "CURRENT" and first["set_at"] is not None
    second = payment_overrides.set("cust-x", "NPL", "LATE", "ผู้จัดการยืนยัน", "mgr-other")
    moved = payment_overrides.version()
    assert moved != before
    assert _rows(wired, "cust-x") == [
        {"code": "CURRENT", "system_code_at_set": "LATE", "reason": "โอนแล้ว", "set_by": "mgr-test",
         "retired_by": "mgr-other", "active": False},
        {"code": "NPL", "system_code_at_set": "LATE", "reason": "ผู้จัดการยืนยัน", "set_by": "mgr-other",
         "retired_by": None, "active": True}]
    assert payment_overrides.active()["cust-x"]["uid"] == second["uid"]
    assert payment_overrides.retire("cust-x", "mgr-test")["uid"] == second["uid"]
    assert payment_overrides.retire("cust-x", "mgr-test") is None
    assert payment_overrides.active() == {} and payment_overrides.version() != moved


def test_with_a_database_a_second_session_sees_it_and_setting_it_back_retires_it(wired, in_session):
    state_a = in_session("s-db-a")
    case_a = next(c for c in state_a.cases.values() if c["payment_status"] == "LATE")
    uid = case_a["customer_uid"]
    cases.set_payment_status(state_a, case_a, "CURRENT", by="mgr-test", reason="โอนครบแล้ว รอ PEAK")
    assert _rows(wired, uid) == [{"code": "CURRENT", "system_code_at_set": "LATE", "reason": "โอนครบแล้ว รอ PEAK",
                                  "set_by": "mgr-test", "retired_by": None, "active": True}]

    state_b = in_session("s-db-b")
    case_b = state_b.cases[uid]
    assert case_b["payment_status"] == "CURRENT" and case_b["payment_status_set_by"] == "mgr-test"
    cases.set_payment_status(state_b, case_b, "LATE", by="mgr-other", reason="ยอดยังไม่เข้า")
    assert [r["active"] for r in _rows(wired, uid)] == [False]
    assert _rows(wired, uid)[0]["retired_by"] == "mgr-other"

    case_a = in_session("s-db-a").cases[uid]
    assert case_a["payment_status"] == "LATE" and case_a["payment_status_set_by"] is None


def test_the_version_moves_whatever_order_two_sets_commit_in(wired):
    """Audit P3: max(uid) did not move when a lower uid committed after a higher one."""
    held = wired.execute(text(
        "insert into records.payment_status_override (customer_uid, code, system_code_at_set, reason, set_by) "
        "values ('cust-lo', 'CURRENT', 'LATE', 'ช้ากว่า', 'mgr-test') returning uid")).scalar()
    payment_overrides.set("cust-hi", "CURRENT", "LATE", "เร็วกว่า", "mgr-other")
    payment_overrides._cache["at"] = payment_overrides._EXPIRED
    between = payment_overrides.version()
    wired.commit()                               # the lower uid lands last
    payment_overrides._cache["at"] = payment_overrides._EXPIRED
    assert payment_overrides.version() != between
    assert payment_overrides.active()["cust-lo"]["uid"] == held


def _waiting_on_a_lock():
    conn = db.connect()
    try:
        return conn.execute(text("select count(*) from pg_stat_activity "
                                 "where wait_event_type = 'Lock' and datname = current_database()")).scalar()
    finally:
        conn.close()


def test_two_managers_at_once_the_second_is_told_to_reload_not_that_the_store_is_down(wired):
    """Audit P1: the unique active index lets one through; the other is a 409."""
    wired.execute(text(
        "insert into records.payment_status_override (customer_uid, code, system_code_at_set, reason, set_by) "
        "values ('cust-race', 'CURRENT', 'LATE', 'คนแรก', 'mgr-test')"))            # held open
    out = {}

    def second():
        try:
            payment_overrides.set("cust-race", "NPL", "LATE", "คนที่สอง", "mgr-other")
        except Exception as exc:                                                   # noqa: BLE001
            out["problem"] = exc
    thread = threading.Thread(target=second)
    thread.start()
    deadline = time.monotonic() + 5
    while not _waiting_on_a_lock() and time.monotonic() < deadline:
        time.sleep(0.05)
    wired.commit()
    thread.join(10)
    problem = out.get("problem")
    assert problem is not None and (problem.status, problem.code) == (409, "payment_status_changed_elsewhere")
    assert [r["set_by"] for r in _rows(wired, "cust-race") if r["active"]] == ["mgr-test"]
