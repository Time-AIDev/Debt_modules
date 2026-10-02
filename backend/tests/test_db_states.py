"""§5.2.1 — configured, unconfigured, unreachable are three different states.

The middle one is the deployed path. The first is what keeps 569 tests and a
bare python:3.12-slim CI container working. The third must REFUSE: a configured
database that has gone away may never degrade to fixtures or to memory, because
that failure would look exactly like success.
"""
import pytest

from app import db


@pytest.fixture(autouse=True)
def _clean_engine(monkeypatch):
    db.reset()
    yield
    db.reset()


def test_unset_is_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.configured() is False
    assert db.engine() is None


def test_unset_connect_returns_none_rather_than_raising(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.connect() is None


def test_configured_and_reachable_connects(monkeypatch, pg_url):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    assert db.configured() is True
    with db.connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text("select 1")).scalar() == 1


def test_configured_but_unreachable_refuses(monkeypatch):
    monkeypatch.setenv("DATABASE_URL",
                       "postgresql+psycopg://volt@127.0.0.1:1/nothing_listens_here")
    assert db.configured() is True
    with pytest.raises(db.DatabaseUnreachable):
        db.connect()
