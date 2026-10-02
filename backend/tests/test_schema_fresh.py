"""schema.sql must apply, in order, to a FRESH database.

The staging deploy (2026-09-21) caught what the long-lived local databases could
not: `import_run_lead_idx` was declared next to `app.session_state` but its predicate
references `landing.import_run.meta`, a column the ALTER near the bottom of the file
adds. Every local database already had the column from an earlier migration, so
every local run was green while a fresh database could not migrate at all
(`column "meta" does not exist`). This test builds a scratch database, applies the
whole file, and drops it.
"""
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import migrate


def test_the_whole_schema_applies_to_a_fresh_database(pg_url):
    name = "volt_fresh_" + uuid.uuid4().hex[:12]
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as conn:
            conn.execute(text('CREATE DATABASE "%s"' % name))
    except Exception as exc:                       # noqa: BLE001 — a locked-down server skips
        admin.dispose()
        pytest.skip("cannot create a scratch database: %s" % exc)

    fresh_url = make_url(pg_url).set(database=name).render_as_string(hide_password=False)
    engine = create_engine(fresh_url, future=True)
    try:
        with engine.connect() as conn:
            with conn.begin():
                executed = migrate.apply(conn)
        # The full file ran — not a prefix that happened to stop before the bug.
        assert len(executed) >= 50, executed[-3:]
        with engine.connect() as conn:
            schemas = conn.execute(text(
                "select count(*) from pg_namespace "
                "where nspname in ('landing', 'app', 'records', 'audit')")).scalar()
            assert schemas == 4
            index = conn.execute(text(
                "select 1 from pg_indexes where indexname = 'import_run_lead_idx'")).scalar()
            assert index == 1
    finally:
        engine.dispose()
        with admin.connect() as conn:
            try:
                conn.execute(text('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name))
            except Exception:                      # noqa: BLE001 — pre-13 servers
                conn.execute(text('DROP DATABASE IF EXISTS "%s"' % name))
        admin.dispose()
