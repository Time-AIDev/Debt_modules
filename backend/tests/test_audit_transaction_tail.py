"""Concurrent readers must not hold audit locks through portfolio calculations."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text

from app import audit_store, db, errors, migrate
from app.production_unit import CURRENT, append_audit_tail


def fields(index=0):
    return {"request_id": "synthetic-audit-%d" % index, "act": "CASE_VIEWED",
            "actor_source": "NONE", "verb": "GET", "route_template": "/v1/synthetic-audit",
            "outcome": "OK", "status": 200, "detail": {"index": index}}


def test_owned_unit_queues_a_copy_without_borrowing_another_connection(monkeypatch):
    monkeypatch.setattr(audit_store, "persisted", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pytest.fail("audit cannot check out a second connection"))
    unit = {}
    token = CURRENT.set(unit)
    value = fields()
    try:
        audit_store.append(value)
        value["detail"]["index"] = 100
        assert unit["pending_audits"][0]["detail"]["index"] == 0
        with pytest.raises(ValueError):
            audit_store.append({**value, "unknown_field": "bad"})
    finally:
        CURRENT.reset(token)


def test_repeatable_readers_end_snapshot_before_short_audit_tail(pg_url, pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    engine = create_engine(pg_url, pool_size=12, max_overflow=0)
    barrier = Barrier(12)
    def reader(index):
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            txn = conn.begin()
            conn.execute(text("select count(*) from audit.entry")).scalar_one()
            barrier.wait(timeout=10)
            txn.commit()
            append_audit_tail(conn, {"pending_audits": [fields(index)]}, fresh=True)
    try:
        with ThreadPoolExecutor(max_workers=12) as workers:
            list(workers.map(reader, range(12)))
        with engine.connect() as conn:
            rows = conn.execute(text("select seq,prev_hash,hash from audit.entry order by seq")).mappings().all()
        assert len(rows) == 12
        assert [row["seq"] for row in rows] == list(range(1, 13))
        assert all(next_row["prev_hash"] == previous["hash"] for previous, next_row in zip(rows, rows[1:]))
        assert audit_store.verify()["ok"] is True
    finally:
        engine.dispose()
        db.reset()


def test_rolled_back_write_audit_records_actual_refusal_not_planned_success(pg_url, pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.execute(text("create table app.audit_probe(value integer not null)"))
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    unit = {"pending_audits": [{**fields(999), "verb": "POST", "status": 201}]}
    with db.connect() as conn:
        with pytest.raises(RuntimeError):
            with conn.begin():
                conn.execute(text("insert into app.audit_probe values(123)"))
                append_audit_tail(conn, unit)
                raise RuntimeError("commit must not happen")
        refused = errors.Problem("state_conflict", 409, "stale", "stale", "ข้อมูลเปลี่ยนแล้ว", "TEST-409")
        append_audit_tail(conn, unit, refused, fresh=True)
        assert conn.execute(text("select count(*) from app.audit_probe")).scalar_one() == 0
        row = conn.execute(text("select outcome,status,error_code from audit.entry "
                                "where request_id='synthetic-audit-999'")).mappings().one()
        assert dict(row) == {"outcome": "REFUSED", "status": 409, "error_code": "state_conflict"}
        assert "pending_audits" not in unit
        append_audit_tail(conn, unit, refused, fresh=True)
        assert conn.execute(text("select count(*) from audit.entry where request_id='synthetic-audit-999'")).scalar_one() == 1
    db.reset()
