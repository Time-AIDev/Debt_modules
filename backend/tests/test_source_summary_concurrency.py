"""Real MVCC source snapshots must remain isolated during summary reuse."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading

import pytest
from sqlalchemy import create_engine, text

from app import book_source, data_epoch, db, landing, migrate
from app.production_unit import CURRENT


@contextmanager
def source_unit(conn, mutation=False):
    token = CURRENT.set({"conn": conn, "mutation": mutation})
    try:
        yield
    finally:
        CURRENT.reset(token)


def add_source(conn, identifier):
    run = landing.start_run(conn, "ODOO", meta={"door":"odoo"})
    landing.write_customer(conn, run, "ODOO", {"volt_id": identifier, "customer_no": identifier})
    landing.finish_run(conn, run, "OK", row_counts={"landed":1})


@pytest.fixture
def source_db(pg_conn, pg_url, monkeypatch):
    migrate.apply(pg_conn)
    add_source(pg_conn, "TEST-first")
    pg_conn.execute(text("insert into app.data_epoch(kind) values('TEST-source')"))
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("CRM_WON_ONLY", "false")
    monkeypatch.setattr(data_epoch, "current", lambda: 999999)  # must read actual SQL snapshot
    book_source.forget_summary()
    db.reset()
    yield pg_conn
    if pg_conn.in_transaction():
        pg_conn.rollback()
    book_source.forget_summary()
    db.reset()


def test_parallel_cold_readers_share_one_source_count_and_keep_return_values_private(source_db, monkeypatch):
    conn = source_db
    original = landing.count_customers
    started, release = threading.Event(), threading.Event()
    barrier = threading.Barrier(7)
    lock = threading.Lock()
    calls = []
    def count(reader, shaped_only=False):
        with lock:
            calls.append(shaped_only)
        if not shaped_only:
            started.set()
            assert release.wait(3)
        return original(reader, shaped_only)
    monkeypatch.setattr(landing, "count_customers", count)
    def read():
        with conn.engine.connect() as reader, reader.begin():
            reader.execute(text("set transaction isolation level repeatable read, read only"))
            barrier.wait(timeout=3)
            with source_unit(reader):
                return book_source.source_summary()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(read) for _ in range(6)]
        barrier.wait(timeout=3)
        assert started.wait(3)
        release.set()
        values = [future.result(timeout=5) for future in futures]
    assert calls == [False, True]
    assert all(value["served_customers"] == value["landed_customers"] == 1 for value in values)
    values[0]["served_customers"] = 12345
    assert all(value["served_customers"] == 1 for value in values[1:])


def test_old_repeatable_read_never_reuses_new_epoch_summary(source_db):
    engine = source_db.engine
    with engine.connect() as old, old.begin():
        old.execute(text("set transaction isolation level repeatable read, read only"))
        old_epoch = old.execute(text("select max(id) from app.data_epoch")).scalar_one()
        with engine.connect() as writer, writer.begin():
            add_source(writer, "TEST-second")
            writer.execute(text("insert into app.data_epoch(kind) values('TEST-new-source')"))
        with engine.connect() as newer, newer.begin(), source_unit(newer):
            new_summary = book_source.source_summary()
        assert new_summary["landed_customers"] == 2
        with source_unit(old):
            old_summary = book_source.source_summary()
        assert old.execute(text("select max(id) from app.data_epoch")).scalar_one() == old_epoch
        assert old_summary["landed_customers"] == 1
        with engine.connect() as current, current.begin(), source_unit(current):
            assert book_source.source_summary() == new_summary


def test_uncommitted_mutation_and_rollback_cannot_poison_same_epoch_reader(source_db):
    engine = source_db.engine
    with engine.connect() as reader, reader.begin(), source_unit(reader):
        committed = book_source.source_summary()
    with engine.connect() as writer:
        transaction = writer.begin()
        add_source(writer, "TEST-rollback")
        # Even before publication bumps the epoch, this transaction needs its own
        # source facts rather than the cached committed count at the same epoch.
        with source_unit(writer, mutation=True):
            assert book_source.source_summary()["landed_customers"] == 2
        with engine.connect() as reader, reader.begin(), source_unit(reader):
            assert book_source.source_summary() == committed
        transaction.rollback()
    with engine.connect() as reader, reader.begin(), source_unit(reader):
        assert book_source.source_summary() == committed


def test_same_epoch_different_engine_cannot_reuse_another_database_binding(source_db, pg_url, monkeypatch):
    calls = []
    original = landing.count_customers
    def count(conn, shaped_only=False):
        calls.append(conn.engine)
        return original(conn, shaped_only)
    monkeypatch.setattr(landing, "count_customers", count)
    other = create_engine(pg_url)
    try:
        with source_db.engine.connect() as first, first.begin(), source_unit(first):
            expected = book_source.source_summary()
        with other.connect() as second, second.begin(), source_unit(second):
            assert book_source.source_summary() == expected
        assert calls == [source_db.engine, source_db.engine, other, other]
    finally:
        other.dispose()


def test_failed_cold_source_count_is_not_cached_and_can_retry(source_db, monkeypatch):
    with source_db.engine.connect() as reader, reader.begin(), source_unit(reader):
        with monkeypatch.context() as failure:
            failure.setattr(landing, "count_customers", lambda *_args, **_kwargs:
                            (_ for _ in ()).throw(RuntimeError("TEST transient source failure")))
            with pytest.raises(RuntimeError, match="TEST transient"):
                book_source.source_summary()
        assert book_source.source_summary()["landed_customers"] == 1
