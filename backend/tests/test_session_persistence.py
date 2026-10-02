"""Tester work survives a restart — simulated by throwing away every in-memory
dict and rebuilding the Stores from Postgres, which is exactly what a Cloud Run
revision restart does to the process."""
import pytest

from app import db, migrate, session as session_domain, session_store_db


@pytest.fixture(autouse=True)
def _isolate_context():
    """Put CURRENT and REGISTRY back afterwards.

    CURRENT is a ContextVar: a bare set() in one test leaks its session id into
    every test that runs after it in the same context, and the next file along then
    reads a different session's state. That is exactly what happened the first time
    this file ran — test_pip_005 failed in the suite and passed alone.

    REGISTRY is process-wide by design, so the Stores these tests create must be
    removed too, or flush_current() keeps trying to persist them forever.
    """
    token = session_domain.CURRENT.set(session_domain.SHARED)
    registered = len(session_domain.REGISTRY)
    try:
        yield
    finally:
        del session_domain.REGISTRY[registered:]
        session_domain.CURRENT.reset(token)


@pytest.fixture
def wired(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    yield
    db.reset()


def test_unconfigured_store_is_memory_exactly_as_before(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.reset()
    store = session_domain.Store(dict, key="test.unconfigured")
    session_domain.CURRENT.set("s-aaa")
    store.for_current()["x"] = 1
    assert store.for_current() == {"x": 1}


def test_a_written_value_survives_losing_every_in_memory_dict(wired):
    store = session_domain.Store(dict, key="test.survives")
    session_domain.CURRENT.set("s-bbb")
    store.for_current()["approved"] = ["order-1", "order-2"]
    session_domain.flush_current()

    store._by_session.clear()          # the restart
    assert store.for_current() == {"approved": ["order-1", "order-2"]}


def test_sessions_stay_separate_across_the_restart(wired):
    store = session_domain.Store(dict, key="test.separate")
    session_domain.CURRENT.set("s-ccc")
    store.for_current()["who"] = "first"
    session_domain.flush_current()
    session_domain.CURRENT.set("s-ddd")
    store.for_current()["who"] = "second"
    session_domain.flush_current()

    store._by_session.clear()
    session_domain.CURRENT.set("s-ccc")
    assert store.for_current()["who"] == "first"
    session_domain.CURRENT.set("s-ddd")
    assert store.for_current()["who"] == "second"


def test_legacy_browser_row_from_another_code_version_is_ignored(wired, pg_conn, monkeypatch):
    store = session_domain.Store(dict, key="test.version")
    session_domain.CURRENT.set("s-eee")
    store.for_current()["stale"] = True
    session_domain.flush_current()

    monkeypatch.setattr(session_store_db, "CODE_VERSION", "a-different-revision")
    store._by_session.clear()
    assert store.for_current() == {}, "a new revision must start fresh, not unpickle stale classes"


def test_authenticated_user_state_survives_a_revision_change(wired, monkeypatch):
    store = session_domain.Store(dict, key="test.user.revision")
    session_domain.CURRENT.set("user:person@example.com")
    store.for_current()["notes"] = ["keep me"]
    session_domain.flush_current()

    monkeypatch.setattr(session_store_db, "CODE_VERSION", "another-cloud-run-revision")
    store._by_session.clear()

    assert store.for_current() == {"notes": ["keep me"]}


def test_unreadable_user_state_is_not_silently_reset(wired, pg_conn):
    pg_conn.execute(session_store_db.text(
        "insert into app.user_state "
        "(principal_key, key, payload, codec, schema_version) "
        "values ('user:broken@example.com', 'test.user.broken', :p, 'pickle-v1', 2)"
    ), {"p": b"not-a-pickle"})
    pg_conn.commit()
    store = session_domain.Store(dict, key="test.user.broken")
    session_domain.CURRENT.set("user:broken@example.com")

    with pytest.raises(session_store_db.StateUnreadable):
        store.for_current()


class Holder:
    """Module level on purpose: pickle stores a class by reference, so one defined
    inside a test function cannot be found again on load. All twenty real Stores
    hold module-level classes — ContactLog, DocumentState, Settings and the rest."""

    def __init__(self):
        self.items = set()


def test_a_set_and_a_custom_class_both_round_trip(wired):
    """JSONB could hold neither. This is why the column is bytea."""
    store = session_domain.Store(Holder, key="test.custom")
    session_domain.CURRENT.set("s-fff")
    store.for_current().items.add("removed-order-7")
    session_domain.flush_current()

    store._by_session.clear()
    assert store.for_current().items == {"removed-order-7"}


def test_an_unpicklable_value_is_reported_and_does_not_crash(wired, capsys):
    """It stays in memory, and it says so. Silent non-persistence would look
    exactly like success, which is the failure mode this whole module removes."""
    store = session_domain.Store(lambda: {}, key="test.unpicklable")
    session_domain.CURRENT.set("s-ggg")
    store.for_current()["fn"] = lambda: None     # a lambda cannot be pickled
    session_domain.flush_current()
    assert "not picklable" in capsys.readouterr().err


def test_a_request_checks_only_the_stores_it_touched(wired, monkeypatch):
    """Inside a request (TOUCHED set) the flush pickles only what that request asked
    for; outside one it still checks every store. At 10x, pickling a session's whole
    17.7 MB copy after every request cost ~230 ms and wrote nothing."""
    a = session_domain.Store(dict, key="test.touched.a")
    b = session_domain.Store(dict, key="test.touched.b")
    session_domain.CURRENT.set("s-touched")
    a.for_current()["n"] = 1
    b.for_current()["n"] = 1
    assert session_domain.flush_current() == 2

    pickled = []
    dump = session_store_db.dump
    monkeypatch.setattr(session_store_db, "dump", lambda value: pickled.append(value) or dump(value))
    token = session_domain.TOUCHED.set(set())
    try:
        a.for_current()["n"] = 2
        assert session_domain.flush_current() == 1
        assert pickled == [{"n": 2}]                 # b was never pickled
    finally:
        session_domain.TOUCHED.reset(token)
    a._by_session.clear()
    assert a.for_current() == {"n": 2}
