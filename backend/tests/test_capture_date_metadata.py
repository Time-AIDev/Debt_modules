"""Cold payment position reads metadata, retaining snapshot and monetary rules."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from app import book_source, db, journey, landing, main, migrate, payment_position
from app.production_unit import CURRENT


@pytest.fixture
def metadata_db(pg_conn, pg_url, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("VOLT_SHARED_STATE_ENABLED", "false")
    db.reset()
    yield pg_conn
    db.reset()


@contextmanager
def unit(conn, mutation=False):
    token = CURRENT.set({"conn": conn, "mutation": mutation, "capacity": False})
    try:
        yield
    finally:
        CURRENT.reset(token)


def publish(conn, source, captured, *, status="OK", lead=True):
    run = landing.start_run(conn, source, meta={"door": "crm.lead"} if lead else {})
    conn.execute(text("update landing.import_run set status=:s,finished_at=:d where id=:id"),
                 {"s": status, "d": captured, "id": run})
    conn.execute(text("insert into app.data_epoch(kind,run_id) values ('capture-test',:id)"), {"id": run})
    return run


@pytest.mark.parametrize("source,stamp,expected", [
    ("SHEET", "2026-09-14T18:30:00Z", "2026-09-15"),
    ("ODOO", "2026-09-14T16:30:00Z", "2026-09-14"),
    ("SHEET", None, None),
])
def test_capture_date_matches_source_and_bangkok_semantics(metadata_db, source, stamp, expected):
    publish(metadata_db, source, stamp)
    with unit(metadata_db):
        old = book_source.load()["source"]["captured_on"]
        assert old == expected
        assert book_source.capture_date() == old
        assert payment_position._sheet_captured_on() == old


def test_sheet_precedes_newer_odoo_and_failed_runs(metadata_db):
    publish(metadata_db, "SHEET", "2026-09-01T00:00:00Z")
    publish(metadata_db, "ODOO", "2026-10-01T00:00:00Z")
    publish(metadata_db, "SHEET", "2026-11-01T00:00:00Z", status="FAILED")
    with unit(metadata_db):
        assert book_source.capture_date() == book_source.load()["source"]["captured_on"] == "2026-09-01"


def test_odoo_sale_order_sync_does_not_replace_lead_capture_date(metadata_db):
    publish(metadata_db, "ODOO", "2026-09-01T00:00:00Z")
    publish(metadata_db, "ODOO", "2026-10-01T00:00:00Z", lead=False)
    with unit(metadata_db):
        assert book_source.capture_date() == book_source.load()["source"]["captured_on"] == "2026-09-01"


def test_absent_and_null_dates_are_cached_only_in_read_unit(metadata_db):
    queries = []
    def recorded(_conn, _cursor, statement, *_args):
        queries.append(statement)
    event.listen(metadata_db.engine, "before_cursor_execute", recorded)
    try:
        with unit(metadata_db):
            assert book_source.capture_date() is None
            count = len(queries)
            assert book_source.capture_date() is None
            assert len(queries) == count
        assert all("select finished_at from landing.import_run" in q for q in queries)
        publish(metadata_db, "SHEET", None)
        with unit(metadata_db):
            assert book_source.capture_date() is None
            count = len(queries)
            assert book_source.capture_date() is None
            assert len(queries) == count
    finally:
        event.remove(metadata_db.engine, "before_cursor_execute", recorded)


def test_old_snapshot_and_new_publication_never_mix(metadata_db, pg_url):
    run = publish(metadata_db, "SHEET", "2026-09-01T00:00:00Z")
    metadata_db.commit()
    metadata_db.execute(text("set transaction isolation level repeatable read, read only"))
    other = create_engine(pg_url)
    try:
        with unit(metadata_db):
            assert book_source.capture_date() == "2026-09-01"
            with other.begin() as writer:
                writer.execute(text("update landing.import_run set finished_at='2026-09-14T18:30:00Z' where id=:id"), {"id": run})
                writer.execute(text("insert into app.data_epoch(kind,run_id) values ('new-capture',:id)"), {"id": run})
            payment_position.forget_capture_date()
            assert book_source.capture_date() == "2026-09-01"
            with other.connect() as reader, unit(reader):
                assert payment_position._sheet_captured_on() == "2026-09-15"
        metadata_db.rollback()
        with unit(metadata_db):
            assert book_source.capture_date() == "2026-09-15"
    finally:
        other.dispose()


def test_mutation_capture_changes_and_rollback_never_publish_a_scalar(metadata_db):
    run = publish(metadata_db, "SHEET", "2026-09-01T00:00:00Z")
    metadata_db.commit()
    with unit(metadata_db, mutation=True):
        assert payment_position._sheet_captured_on() == "2026-09-01"
        metadata_db.execute(text("update landing.import_run set finished_at='2026-10-01T00:00:00Z' where id=:id"), {"id": run})
        assert payment_position._sheet_captured_on() == "2026-10-01"
    metadata_db.rollback()
    with unit(metadata_db):
        assert payment_position._sheet_captured_on() == "2026-09-01"


def test_standalone_reads_follow_publication_and_database_changes(metadata_db, pg_url, monkeypatch):
    publish(metadata_db, "ODOO", "2026-09-01T00:00:00Z")
    metadata_db.commit()
    monkeypatch.setattr(payment_position, "_CAPTURED", "1999-01-01")
    assert payment_position._sheet_captured_on() == "2026-09-01"
    publish(metadata_db, "SHEET", "2026-10-01T00:00:00Z")
    metadata_db.commit()
    assert payment_position._sheet_captured_on() == "2026-10-01"
    other_url = make_url(pg_url).set(database="volt_test_capture_other")
    with metadata_db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text("create database volt_test_capture_other"))
    other = create_engine(other_url)
    try:
        with other.begin() as conn:
            migrate.apply(conn)
            publish(conn, "SHEET", "2026-11-01T00:00:00Z")
        monkeypatch.setenv("DATABASE_URL", other_url.render_as_string(hide_password=False))
        db.reset()
        assert payment_position._sheet_captured_on() == "2026-11-01"
        monkeypatch.setenv("DATABASE_URL", pg_url)
        db.reset()
        assert payment_position._sheet_captured_on() == "2026-10-01"
    finally:
        db.reset()
        other.dispose()
        with metadata_db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text("drop database volt_test_capture_other"))


def test_sheet_position_money_date_status_and_notes_match_without_portfolio_reads(metadata_db, monkeypatch):
    publish(metadata_db, "SHEET", "2026-09-14T18:30:00Z")
    metadata_db.commit()
    customer = next(c for c in main.CUSTOMERS if c.contracts)
    state = journey.for_current()
    contract = customer.contracts[0]
    state.invoices.clear()
    state.receipts.clear()
    from app.money.models import Instalment
    contract.instalments = [Instalment(due_date=date(2026, 8, 1), category="REGULAR",
                                      principal_amount=Decimal("123.45"), interest_amount=Decimal("0"))]
    journey.make_invoice(state, contract.uid, "SPV", "INSTALMENT", "123.45", date(2026, 8, 1), "OVERDUE")
    with unit(metadata_db):
        old_date = book_source.load()["source"]["captured_on"]
    original = payment_position._sheet_captured_on
    monkeypatch.setattr(payment_position, "_sheet_captured_on", lambda: old_date)
    expected = payment_position.build(customer, state, date(2026, 10, 7))
    monkeypatch.setattr(payment_position, "_sheet_captured_on", original)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("capture date must not hydrate or count the portfolio")
    for module, name in [(book_source, "load"), (book_source, "_landing_rows"),
                         (landing, "resolved_customers"), (landing, "count_customers")]:
        monkeypatch.setattr(module, name, forbidden)
    with unit(metadata_db):
        actual = payment_position.build(customer, state, date(2026, 10, 7))
        assert actual == expected
        later = payment_position.build(customer, state, date(2026, 11, 7))
    assert actual["source"] == "SHEET"
    assert actual["oldest_unpaid"]["outstanding"] == "123.45"
    assert later["as_of"] == actual["as_of"]
    assert later["as_of_days"] == actual["as_of_days"] + 31
    for key in ("oldest_unpaid", "last_money_in", "paid_count", "open_count", "total_count"):
        assert later[key] == actual[key]
