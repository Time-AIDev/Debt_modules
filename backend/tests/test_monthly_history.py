"""Monthly history (Arina, 2026-09-25): one row per customer per month — payment
status, where it came from, overdue, outstanding, DPD, officer. The current month's
row follows every landing; a month that has turned is never written again."""
import io
import zipfile
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import cases, db, imports, main, migrate, monthly_history, payment_overrides
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


@pytest.fixture
def db_env(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    # records is not truncated between tests, and other tests' landings write the demo
    # month's rows through refresh.after_landing: start from an empty history.
    pg_conn.execute(text("delete from records.customer_month"))
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    monkeypatch.setattr(monthly_history, "current_month", lambda: "2026-09")
    try:
        yield pg_conn
    finally:
        pg_conn.rollback()
        pg_conn.execute(text("delete from records.customer_month"))
        pg_conn.execute(text("delete from records.payment_status_override"))
        pg_conn.commit()


def _book():
    return [c for c in main.CUSTOMERS if getattr(c, "volt_id", None)]


def _rows(conn, month="2026-09"):
    got = {r["customer_uid"]: dict(r) for r in conn.execute(text(
        "select * from records.customer_month where month = :m"), {"m": month}).mappings()}
    conn.commit()                  # the code under test opens its own transactions on this connection
    return got


def test_a_snapshot_writes_one_row_per_book_customer_with_the_served_status(db_env):
    written = monthly_history.snapshot("test")
    rows = _rows(db_env)
    book = _book()
    assert written == len(book) == len(rows) > 0
    c = book[0]
    row = rows[c.uid]
    assert row["payment_status"] == cases._payment_status(c)
    assert row["status_source"] in ("PEAK", "SHEET", "CONTRACT")
    arrears, dpd, _band, outstanding = main._customer_aggregate(c)
    assert (row["overdue"], row["outstanding"], row["oldest_dpd"]) == (arrears, outstanding, dpd)
    assert row["volt_id"] == c.volt_id and row["taken_by_kind"] == "test"


def test_snapshot_reads_service_deferrals_once_per_batch(db_env):
    from sqlalchemy import event
    observed = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "select payload from records.service_deferral" in statement:
            observed.append(statement)

    event.listen(db_env, "before_cursor_execute", observe)
    try:
        monthly_history.snapshot("test")
        assert len(observed) == 1
        monthly_history.snapshot("test")
        assert len(observed) == 2  # A new batch reads fresh committed decisions.
    finally:
        event.remove(db_env, "before_cursor_execute", observe)


def test_snapshot_restores_outer_read_context_after_failure(db_env, monkeypatch):
    from app import request_context
    token = request_context.begin_read()
    outer = request_context.reads()
    outer["marker"] = "caller"

    def fail(*args):
        assert request_context.reads() is not outer
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(monthly_history, "_row", fail)
    try:
        with pytest.raises(RuntimeError, match="snapshot failed"):
            monthly_history.snapshot("test")
        assert request_context.reads() is outer
        assert outer["marker"] == "caller"
    finally:
        request_context.end_read(token)


def test_boot_scan_reads_deferrals_once_and_releases_its_scope(db_env, monkeypatch):
    import asyncio
    from sqlalchemy import event
    from app import journey, ptp_watch, request_context, service_deferral_store
    from app.pipelines import service, schedule
    observed = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "select payload from records.service_deferral" in statement:
            observed.append(statement)

    def seed_cases():
        for _ in range(3):
            service_deferral_store.read()
        return {}

    monkeypatch.setattr(cases, "for_current", seed_cases)
    monkeypatch.setattr(journey, "for_current", lambda: {})
    monkeypatch.setattr(ptp_watch, "notice_early_payments", lambda *args: None)
    monkeypatch.setattr(service, "refresh_if_stale", lambda: False)
    monkeypatch.setattr(schedule, "ensure_auto", lambda: None)
    monkeypatch.setattr(schedule, "shutdown", lambda: None)
    monkeypatch.setattr(monthly_history, "safe_snapshot", lambda *args: 0)

    async def boot():
        async with main._lifespan(main.app):
            assert request_context.reads() is None

    event.listen(db_env, "before_cursor_execute", observe)
    try:
        asyncio.run(boot())
        assert len(observed) == 1
    finally:
        event.remove(db_env, "before_cursor_execute", observe)


def test_the_current_month_follows_an_override_and_a_turned_month_stays(db_env, monkeypatch):
    monthly_history.snapshot("sheet")
    c = _book()[0]
    system = cases._payment_status(c)
    other = "NPL" if system != "NPL" else "CURRENT"
    payment_overrides.set(c.uid, other, system, "test", "settasak")
    monthly_history.snapshot("override", uids=[c.uid])
    row = _rows(db_env)[c.uid]
    assert (row["payment_status"], row["status_source"]) == (other, "OVERRIDE")

    # The month turns: September is final, October starts from the book.
    monkeypatch.setattr(monthly_history, "current_month", lambda: "2026-10")
    payment_overrides.retire(c.uid, "settasak")
    monthly_history.snapshot("sheet")
    assert _rows(db_env)[c.uid]["payment_status"] == other            # September untouched
    assert _rows(db_env, "2026-10")[c.uid]["payment_status"] == system


def test_the_source_names_which_answer_decided():
    for c in _book():
        code, source = cases.payment_status_with_source(c)
        assert code == cases._payment_status(c) and source in ("PEAK", "SHEET", "CONTRACT")
        if source == "CONTRACT" and code not in ("NPL", "CLOSED", "TERMINATED", "NOT_INSTALLED"):
            assert cases._peak_says(c) is None and cases.sheet_says(c)[0] is None


def _insert(conn, month, uid, status, outstanding="100.00", overdue="0.00"):
    conn.execute(text(
        "insert into records.customer_month (month, customer_uid, payment_status, status_source, "
        "overdue, outstanding) values (:m, :u, :s, 'SHEET', :o, :b)"),
        {"m": month, "u": uid, "s": status, "o": overdue, "b": outstanding})


def test_the_monthly_report_counts_by_status_and_moves_in_and_out_of_npl(db_env):
    for uid, aug, sep in (("u1", "CURRENT", "NPL"), ("u2", "NPL", "CURRENT"), ("u3", "LATE", "LATE"),
                          ("u4", "NPL", "NPL")):
        _insert(db_env, "2026-08", uid, aug)
        _insert(db_env, "2026-09", uid, sep, overdue="10.00" if sep != "CURRENT" else "0.00")
    _insert(db_env, "2026-09", "u5", "CURRENT")          # new this month
    db_env.commit()
    r = TestClient(app).get("/v1/reports/monthly?months=12", headers=OFFICER)
    assert r.status_code == 200
    months = {m["month"]: m for m in r.json()["months"]}
    sep, aug = months["2026-09"], months["2026-08"]
    assert sep["by_status"]["NPL"]["count"] == 2 and sep["by_status"]["CURRENT"]["count"] == 2
    assert (sep["npl_in"], sep["npl_out"]) == (1, 1)
    assert aug["npl_in"] is None                          # no month before it to compare
    assert sep["customers"] == 5 and sep["mom"]["customers"] == 1
    assert sep["outstanding"] == "500.00" and sep["mom"]["outstanding"] == "100.00"
    assert [m["month"] for m in r.json()["months"]] == ["2026-09", "2026-08"]


def test_a_month_leaves_as_xlsx_only_with_a_manager_and_a_reason(db_env):
    monthly_history.snapshot("sheet")
    client = TestClient(app)
    body = {"month": "2026-09", "reason": "month-end review"}
    assert client.post("/v1/reports/monthly:export", json=body, headers=OFFICER).status_code == 403
    assert client.post("/v1/reports/monthly:export", json={"month": "2026-09"}, headers=MANAGER).status_code == 422
    assert client.post("/v1/reports/monthly:export", json={"month": "Sept", "reason": "x"},
                       headers=MANAGER).status_code == 422
    r = client.post("/v1/reports/monthly:export", json=body, headers=MANAGER)
    assert r.status_code == 200 and "2026-09" in r.headers["content-disposition"]
    sheet = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode()
    assert _book()[0].volt_id.split("_")[0] in sheet


def test_monthly_xlsx_summary_matches_the_month_api_status_and_totals(db_env):
    monthly_history.snapshot("sheet")
    client = TestClient(app)
    api_month = next(row for row in client.get("/v1/reports/monthly?months=12", headers=OFFICER).json()["months"]
                     if row["month"] == "2026-09")
    response = client.post("/v1/reports/monthly:export",
                           json={"month": "2026-09", "reason": "month parity"}, headers=MANAGER)
    sheets = imports.read_xlsx(response.content)
    detail, summary = sheets[0]["rows"], sheets[1]["rows"]
    assert [row[0] for row in detail[1:]] == [row["volt_id"] for row in monthly_history.month_rows("2026-09")]
    exported = {row[0]: row[1:] for row in summary[1:] if row[0] != "รวม"}
    for status, served in api_month["by_status"].items():
        assert int(exported[status][0]) == served["count"]
        assert Decimal(str(exported[status][1])) == Decimal(str(served["overdue"]))
        assert Decimal(str(exported[status][2])) == Decimal(str(served["outstanding"]))
    total = summary[-1]
    assert int(total[1]) == api_month["customers"]
    assert Decimal(str(total[2])) == Decimal(str(api_month["overdue"]))
    assert Decimal(str(total[3])) == Decimal(str(api_month["outstanding"]))


def test_the_case_carries_its_monthly_history(db_env):
    monthly_history.snapshot("sheet")
    c = _book()[0]
    history = monthly_history.for_customer(c.uid)
    assert [h["month"] for h in history] == ["2026-09"]
    assert history[0]["payment_status"] == _rows(db_env)[c.uid]["payment_status"]


def test_the_case_page_serves_the_history(monkeypatch):
    """The route wiring, on the in-memory book (the one-connection DB fixture cannot
    serve a whole case request)."""
    c = _book()[0]
    monkeypatch.setattr(monthly_history, "for_customer", lambda uid: [{"month": "2026-09", "uid": uid}])
    r = TestClient(app).get("/v1/cases/by-customer/%s" % c.uid, headers=OFFICER)
    assert r.json()["case"]["monthly_history"] == [{"month": "2026-09", "uid": c.uid}]


def test_a_snapshot_reads_the_shared_session_not_the_triggering_one(db_env):
    """Review 2026-09-25 (MAJOR): a landing started by one person wrote that person's
    session-only reassignment into everyone's history."""
    from app import journey, session
    c = _book()[0]
    token = session.CURRENT.set("someone-private")
    try:
        journey.for_current().officer_overlay[c.uid] = "private-officer"
        monthly_history.snapshot("sheet")
    finally:
        session.CURRENT.reset(token)
    assert _rows(db_env)[c.uid]["officer"] != "private-officer"


def test_a_pull_that_changed_nothing_still_refreshes_the_month(monkeypatch):
    from app import refresh
    calls = []
    monkeypatch.setattr(monthly_history, "safe_snapshot", lambda kind, uids=None: calls.append(kind))
    refresh.after_landing("odoo", changed=False)
    assert calls == ["odoo"]


def test_a_missing_month_compares_against_nothing(db_env):
    _insert(db_env, "2026-07", "u1", "NPL")
    _insert(db_env, "2026-09", "u1", "CURRENT")
    db_env.commit()
    sep = monthly_history.report(12)[0]
    assert sep["month"] == "2026-09" and (sep["npl_in"], sep["npl_out"], sep["mom"]) == (None, None, None)


def test_a_business_date_moved_back_does_not_rewrite_a_finished_month(db_env, monkeypatch):
    monthly_history.snapshot("sheet")
    monkeypatch.setattr(monthly_history, "current_month", lambda: "2026-08")
    assert monthly_history.snapshot("sheet") == 0
    assert _rows(db_env, "2026-08") == {}


def test_a_customer_who_leaves_the_book_is_not_counted_in_the_month(db_env, monkeypatch):
    monthly_history.snapshot("sheet")
    book = _book()
    gone = book[0]
    monkeypatch.setattr(main, "CUSTOMERS", [c for c in main.CUSTOMERS if c.uid != gone.uid])
    monthly_history.snapshot("sheet")
    assert _rows(db_env)[gone.uid]["in_book"] is False
    assert monthly_history.report(1)[0]["customers"] == len(book) - 1
