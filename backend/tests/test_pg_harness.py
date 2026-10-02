"""The test database harness itself. If this file fails, nothing downstream is trustworthy.

The suite must stay green on a machine with no Postgres — that is what keeps the
569-test contract and infra/cloudbuild.yaml's bare python:3.12-slim step working —
so every database test SKIPS rather than fails when the server is absent.
"""
import pytest


def test_pg_url_fixture_points_at_a_live_server(pg_conn):
    from sqlalchemy import text
    assert pg_conn.execute(text("select 1")).scalar() == 1


def test_server_is_postgres_16_or_newer(pg_conn):
    from sqlalchemy import text
    version = pg_conn.execute(text("show server_version")).scalar()
    assert int(version.split(".")[0]) >= 16, version


def test_jsonb_round_trips(pg_conn):
    """SQLite could not do this, which is why the harness is real Postgres."""
    from sqlalchemy import text
    value = pg_conn.execute(
        text("select cast(:doc as jsonb)"), {"doc": '{"a": [1, 2], "b": "ค"}'}).scalar()
    assert value == {"a": [1, 2], "b": "ค"}
