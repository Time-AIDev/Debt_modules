"""The audit constraint admits the two session sources and re-applies cleanly."""
from sqlalchemy import text

from app import migrate


def test_actor_source_constraint_admits_session_sources_and_reapplies(pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    migrate.apply(pg_conn)  # idempotent: a second deploy re-runs schema.sql
    pg_conn.commit()
    definition = pg_conn.execute(text(
        "select pg_get_constraintdef(oid) from pg_constraint where conname = 'entry_actor_source_check'"
    )).scalar()
    assert "SESSION" in definition and "TEST_ACCOUNT" in definition and "HEADER" in definition
