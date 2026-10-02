"""The DDL applies on an empty database, twice, and round-trips a row.

Idempotence is not a nicety here: debt-migrate runs on every deploy, before the
new revision takes traffic, so a second run must be a no-op rather than an error.
"""
import pytest
from sqlalchemy import text

from app import migrate

EXPECTED_TABLES = {
    ("landing", "import_run"), ("landing", "customer"),
    ("landing", "order"), ("landing", "customer_block"),
    ("landing", "peak_receipt"),
    ("landing", "peak_webhook_event"),
    ("app", "session_state"),
    ("app", "user_state"), ("app", "user_state_archive"),
    ("app", "crm_eligibility_preview"),
    ("records", "message_template"),
}


def test_apply_creates_every_table(pg_conn):
    migrate.apply(pg_conn)
    rows = pg_conn.execute(text(
        "select table_schema, table_name from information_schema.tables "
        "where table_schema in ('landing','app','records')")).fetchall()
    assert EXPECTED_TABLES <= {(r[0], r[1]) for r in rows}


def test_apply_is_idempotent(pg_conn):
    migrate.apply(pg_conn)
    migrate.apply(pg_conn)          # must not raise
    count = pg_conn.execute(text(
        "select count(*) from information_schema.tables "
        "where table_schema in ('landing','app')")).scalar()
    assert count >= len(EXPECTED_TABLES)


def test_data_source_is_inside_the_customer_primary_key(pg_conn):
    """The property the whole overlay design rests on: a SHEET row and an ODOO
    row for the same volt_id coexist rather than overwrite."""
    migrate.apply(pg_conn)
    cols = pg_conn.execute(text("""
        select kcu.column_name
          from information_schema.table_constraints tc
          join information_schema.key_column_usage kcu
            on kcu.constraint_name = tc.constraint_name
         where tc.table_schema = 'landing' and tc.table_name = 'customer'
           and tc.constraint_type = 'PRIMARY KEY'
    """)).scalars().all()
    assert set(cols) == {"volt_id", "data_source"}


def test_customer_has_link_only_social_identifiers(pg_conn):
    migrate.apply(pg_conn)
    columns = set(pg_conn.execute(text(
        "select column_name from information_schema.columns "
        "where table_schema='landing' and table_name='customer'"
    )).scalars())
    assert {"line_id", "meta_id"} <= columns


def test_a_sheet_row_and_an_odoo_row_coexist(pg_conn):
    migrate.apply(pg_conn)
    run = pg_conn.execute(text(
        "insert into landing.import_run (source_system, status) "
        "values ('SHEET','OK') returning id")).scalar()
    for source in ("SHEET", "ODOO"):
        pg_conn.execute(text(
            "insert into landing.customer (volt_id, data_source, name_roman, import_run_id) "
            "values (:v, :s, :n, :r)"),
            {"v": "VID-1", "s": source, "n": "Testname", "r": run})
    assert pg_conn.execute(text(
        "select count(*) from landing.customer where volt_id='VID-1'")).scalar() == 2
