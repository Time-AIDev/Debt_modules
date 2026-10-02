"""The import epoch and the session heal (sync audit, 2026-09-20).

Before this, only the session that pressed Apply reseeded its PEAK invoices; a
crm.lead pull invalidated the build cache and nothing else, so the served book and
every other session kept the pre-import facts. These tests pin the replacement:
one landing seam (refresh.after_landing), one counter (app.data_epoch), and a
per-request heal gate (import_sync.ensure_current).
"""
from fastapi.testclient import TestClient
import pytest

from app import data_epoch, db, import_sync, refresh, session as session_domain
from app.main import app

client = TestClient(app)


@pytest.fixture
def store_db(monkeypatch):
    """`db.configured() is True` without a live database.

    The session Store's `_restore` reads through db.connect() when configured, so a
    configured-but-unreachable pair needs both ends stubbed: no persisted row (the
    factory's default) and a connection object that can be closed."""
    from app import session_store_db, service_deferral_store

    class _Conn:
        def close(self):
            pass

    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: _Conn())
    monkeypatch.setattr(session_store_db, "load", lambda conn, s, k: session_store_db.MISSING)
    # This fixture deliberately has no SQL connection; shared adjustment storage
    # is stubbed alongside session storage, leaving the actual heal under test.
    monkeypatch.setattr(service_deferral_store, "read", lambda: [])


class _Spy:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return dict(self.value)


def vi_spy(monkeypatch, module, name, value):
    spy = _Spy(value)
    monkeypatch.setattr(module, name, spy)
    return spy


def test_after_landing_reloads_the_book_and_bumps_the_epoch(monkeypatch):
    calls = []
    from app import main

    monkeypatch.setattr(refresh, "_landing_has_a_run", lambda: True)
    monkeypatch.setattr(refresh.book_module, "invalidate", lambda: calls.append("invalidate"))
    monkeypatch.setattr(main, "reload_book", lambda: calls.append("reload"))
    monkeypatch.setattr(data_epoch, "bump", lambda kind, run_id=None: 7)
    result = refresh.after_landing("crm-lead", 42)

    assert result["served"] is True
    assert result["epoch"] == 7
    assert calls == ["reload"]
    assert refresh.last()["kind"] == "crm-lead"


def test_after_landing_reports_the_failure_but_still_bumps(monkeypatch):
    from app import book as book_mod
    from app import main

    monkeypatch.setattr(refresh, "_landing_has_a_run", lambda: True)
    monkeypatch.setattr(main, "reload_book", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(book_mod, "invalidate", lambda: None)
    monkeypatch.setattr(data_epoch, "current", lambda: 1)
    monkeypatch.setattr(data_epoch, "bump", lambda kind, run_id=None: 2)
    result = refresh.after_landing("odoo", 9)

    assert result["served"] is False
    assert result["problem"]["code"] == "serve_refresh_failed"
    # the class only: a driver's message can quote the row that failed (2026-09-25)
    assert result["problem"]["detail"] == "RuntimeError"
    # The epoch still moved: sessions must not keep seeding from the old facts just
    # because THIS process could not rebind its own copy.
    assert result["epoch"] == 2


def test_after_landing_skips_the_reload_when_nothing_landed(monkeypatch):
    from app import main

    monkeypatch.setattr(refresh, "_landing_has_a_run", lambda: False)
    monkeypatch.setattr(main, "reload_book", lambda: (_ for _ in ()).throw(AssertionError("no")))
    monkeypatch.setattr(data_epoch, "bump", lambda kind, run_id=None: 3)
    result = refresh.after_landing("boot")

    assert result["served"] is True
    assert result["epoch"] == 3


def test_after_landing_with_nothing_changed_neither_rebuilds_nor_bumps(monkeypatch):
    """2026-09-25: a crm.lead pull that landed and retired nothing changed no fact, so
    no book rebuild and no epoch — every session would otherwise heal for nothing."""
    from app import main

    monkeypatch.setattr(refresh, "_landing_has_a_run", lambda: True)
    monkeypatch.setattr(main, "reload_book", lambda: (_ for _ in ()).throw(AssertionError("no rebuild")))
    monkeypatch.setattr(data_epoch, "bump", lambda kind, run_id=None: (_ for _ in ()).throw(AssertionError("no bump")))
    monkeypatch.setattr(data_epoch, "current", lambda: 5)
    result = refresh.after_landing("odoo", 12, changed=False)

    assert result == {"served": True, "epoch": 5, "problem": None, "changed": False}


def test_ensure_current_heals_only_when_the_epoch_moved(store_db, monkeypatch):
    from app import journey, main

    monkeypatch.setattr(data_epoch, "current", lambda: 5)
    monkeypatch.setattr(main, "reload_book", lambda: None)
    heal = vi_spy(monkeypatch, import_sync, "heal_session", {"cards_added": 1})
    import_sync.reset()

    token = session_domain.CURRENT.set("s-heal-gate")
    try:
        # A store this session already seeded: the heal is for sessions that exist,
        # not for the fresh-session skip (its own test below).
        journey.for_current()
        first = import_sync.ensure_current()
        assert first["cards_added"] == 1
        assert first["seen_before"] is False
        assert heal.calls == 1
        assert import_sync.seen_epoch() == 5
        # caught up: the next request pays one cached read and does nothing
        assert import_sync.ensure_current() is None
        assert heal.calls == 1
        # the screen's button can ask again
        assert import_sync.ensure_current(force=True) is not None
        assert heal.calls == 2
    finally:
        session_domain.CURRENT.reset(token)


def test_a_fresh_session_skips_the_heal_and_still_stamps_seen(store_db, monkeypatch):
    """A session that has touched no store seeds from the CURRENT book on first
    touch; healing it first would seed everything twice (646 ms on the 34k landing)."""
    from app import main

    monkeypatch.setattr(data_epoch, "current", lambda: 7)
    monkeypatch.setattr(main, "reload_book", lambda: None)
    heal = vi_spy(monkeypatch, import_sync, "heal_session", {})
    import_sync.reset()

    token = session_domain.CURRENT.set("s-fresh-session")
    try:
        summary = import_sync.ensure_current()
        assert summary["fresh_session"] is True
        assert heal.calls == 0
        assert import_sync.seen_epoch() == 7
        assert import_sync.ensure_current() is None       # already caught up
        assert heal.calls == 0
    finally:
        session_domain.CURRENT.reset(token)


def test_the_seen_epoch_is_per_session(store_db, monkeypatch):
    from app import main

    monkeypatch.setattr(data_epoch, "current", lambda: 9)
    monkeypatch.setattr(main, "reload_book", lambda: None)
    monkeypatch.setattr(import_sync, "heal_session", lambda: {})
    import_sync.reset()

    token = session_domain.CURRENT.set("s-heal-one")
    try:
        assert import_sync.ensure_current() is not None
        session_domain.CURRENT.set("s-heal-two")
        # a session that never saw this epoch heals on its own first request
        assert import_sync.ensure_current() is not None
        assert import_sync.seen_epoch() == 9
    finally:
        session_domain.CURRENT.reset(token)


def test_only_api_requests_heal_and_flush_the_session(monkeypatch):
    """The page shell, a static file or a probe neither heals nor pickles a session:
    only /v1 touches its stores (measured at 10x: ~230 ms of pickling per JS file)."""
    heal = vi_spy(monkeypatch, import_sync, "ensure_current", {})
    flush = vi_spy(monkeypatch, session_domain, "flush_current", {})
    for path in ("/healthz", "/readyz", "/today"):
        client.get(path)
    assert (heal.calls, flush.calls) == (0, 0)
    client.get("/v1/meta/version")
    assert (heal.calls, flush.calls) == (1, 1)


def test_the_real_heal_runs_every_reseed_without_a_database():
    """The gate tests stub heal_session; this runs the real one against the fixture
    book, so an import error inside a reseed (the settings path once was one) fails
    here instead of only in a live request."""
    summary = import_sync.heal_session()
    for key in ("invoices_updated", "invoices_added", "cards_updated", "cards_added",
                "cases_moved", "cases_refreshed", "documents_flagged"):
        assert isinstance(summary[key], int)


def test_data_state_reads_zero_and_not_stale_without_epochs():
    r = client.get("/v1/data-state")
    assert r.status_code == 200
    body = r.json()
    assert body["epoch"] == 0
    assert body["stale"] is False


def test_refresh_imports_is_honest_without_a_database():
    r = client.post("/v1/session:refresh-imports")
    assert r.status_code == 200
    body = r.json()
    assert body["refreshed"] is False
    assert "epoch" in body


def test_after_landing_notes_the_book_epoch_so_the_next_request_does_not_rebuild(store_db, monkeypatch):
    """Two full book builds per import per instance before this (473 ms each here):
    the eager reload here, then the lazy one in ensure_current that did not know."""
    from app import main

    reloads = _Spy({})
    monkeypatch.setattr(refresh, "_landing_has_a_run", lambda: True)
    monkeypatch.setattr(main, "reload_book", reloads)
    monkeypatch.setattr(data_epoch, "bump", lambda kind, run_id=None: 11)
    import_sync.reset()

    result = refresh.after_landing("crm-lead")
    assert result["served"] is True
    assert import_sync._book_epoch["value"] == 11

    monkeypatch.setattr(data_epoch, "current", lambda: 11)
    monkeypatch.setattr(import_sync, "heal_session", lambda: {})
    import_sync.ensure_current()
    assert reloads.calls == 1                       # no second rebuild for the same epoch


def test_the_data_sources_overview_composes_the_whole_screen():
    r = client.get("/v1/data-sources/overview")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"migration", "integrations", "crm", "peak"}
    assert "source_chain" in body["migration"]
    assert "last" in body["crm"] and "schedule" in body["crm"]
    # 2026-09-25: the crm.lead run history ("รอบที่ผ่านมา"); empty without a database
    assert body["crm"]["runs"] == []
    assert "last" in body["peak"] and "doors" in body["peak"]


# --- fix-all F1: the heal off the event loop, one at a time, and on a new day ---------

def test_the_middleware_heals_and_flushes_off_the_event_loop(monkeypatch):
    """A heal is a second or more at 10x; run on the event loop it held every other
    browser's request that long. Both the heal and the flush run in the threadpool."""
    import asyncio

    def on_loop():
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def heal():
        session_domain.TOUCHED.get().add("a store the heal read")
        seen.append(("heal", on_loop(), session_domain.current()))

    def flush():
        seen.append(("flush", on_loop(), session_domain.current(),
                     "a store the heal read" in session_domain.TOUCHED.get()))

    seen = []
    monkeypatch.setattr(import_sync, "ensure_current", heal)
    monkeypatch.setattr(session_domain, "flush_current", flush)
    browser = TestClient(app)
    browser.cookies.set("volt_session", "s-off-loop")
    browser.get("/v1/meta/version")
    # the thread carries the session, and the TOUCHED set the heal filled reaches the flush
    assert seen == [("heal", False, "s-off-loop"),
                    ("flush", False, "s-off-loop", True)]


def test_two_requests_of_one_session_heal_it_once(store_db, monkeypatch):
    """Off the loop, two requests of one session reach the heal together: the second
    waits on the session's lock and finds the first one's stamp."""
    import threading
    import time
    from app import journey, main

    monkeypatch.setattr(data_epoch, "current", lambda: 5)
    monkeypatch.setattr(main, "reload_book", lambda: None)
    heals = []
    monkeypatch.setattr(import_sync, "heal_session", lambda: heals.append(1) or time.sleep(0.2) or {})
    import_sync.reset()
    token = session_domain.CURRENT.set("s-heal-twice")
    try:
        journey.for_current()               # a session that exists, not the fresh-session skip
    finally:
        session_domain.CURRENT.reset(token)

    def request():
        session_domain.CURRENT.set("s-heal-twice")     # a new thread starts with a new context
        import_sync.ensure_current()

    threads = [threading.Thread(target=request) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert heals == [1]


def test_a_new_business_date_heals_the_session_once(store_db, monkeypatch):
    """The live date turns at Bangkok midnight; a session seeded the day before kept
    that day's derived dates until the next import."""
    from app import journey, main

    monkeypatch.setattr(data_epoch, "current", lambda: 5)
    monkeypatch.setattr(main, "reload_book", lambda: None)
    heal = vi_spy(monkeypatch, import_sync, "heal_session", {})
    import_sync.reset()
    token = session_domain.CURRENT.set("s-new-day")
    try:
        journey.for_current()
        import_sync.ensure_current()
        assert import_sync.ensure_current() is None and heal.calls == 1
        monkeypatch.setenv("VOLT_BUSINESS_DATE", "2026-10-24")     # midnight, same epoch
        assert import_sync.ensure_current() is not None and heal.calls == 2
        assert import_sync.ensure_current() is None and heal.calls == 2
    finally:
        session_domain.CURRENT.reset(token)


def test_callers_that_wait_on_the_build_lock_build_an_epoch_once(monkeypatch):
    """main.reload_book re-reads the epoch under its build lock: three requests that
    all saw the book behind build it once, and builds never overlap."""
    import threading
    import time
    from app import main

    running, builds = [0], []

    def slow_build():
        running[0] += 1
        builds.append(running[0])
        time.sleep(0.1)
        running[0] -= 1
        return main.CUSTOMERS, main.IDENTITIES

    monkeypatch.setattr(main, "_serve_book", slow_build)
    monkeypatch.setattr(data_epoch, "current", lambda: 9)
    import_sync.reset()
    threads = [threading.Thread(target=main.reload_book) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert builds == [1]
    assert import_sync._book_epoch["value"] == 9


def test_after_landing_bumps_the_epoch_before_it_rebuilds(monkeypatch):
    """The rebuild reads the epoch — main.reload_book skips an epoch this process
    serves, book_source keeps its non-PEAK reads per non-PEAK epoch — so the landing's
    own epoch must exist first."""
    from app import main

    order = []
    monkeypatch.setattr(refresh, "_landing_has_a_run", lambda: True)
    monkeypatch.setattr(data_epoch, "bump", lambda kind, run_id=None: order.append("bump") or 4)
    monkeypatch.setattr(main, "reload_book", lambda: order.append("reload"))
    assert refresh.after_landing("sheet", 1)["served"] is True
    assert order == ["bump", "reload"]


def test_an_epoch_that_cannot_be_written_rebuilds_nothing(monkeypatch):
    """Nothing records the change, so this process does not serve it either: the old
    book keeps serving and the caller shows the problem (an apply says 'refresh')."""
    from app import main

    monkeypatch.setattr(refresh, "_landing_has_a_run", lambda: True)
    monkeypatch.setattr(data_epoch, "bump", lambda kind, run_id=None: (_ for _ in ()).throw(RuntimeError("db")))
    monkeypatch.setattr(main, "reload_book", lambda: (_ for _ in ()).throw(AssertionError("no rebuild")))
    result = refresh.after_landing("sheet", 1)
    assert result["served"] is False
    assert result["problem"]["code"] == "epoch_write_failed"


# --- 2026-09-27: a cold start is not a new session ---------------------------------

@pytest.fixture
def wired(monkeypatch, pg_url, pg_conn):
    """A real, migrated Postgres (VOLT_TEST_PG_URL): the Stores persist and restore."""
    from app import migrate

    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    yield
    db.reset()


def test_a_session_restored_after_a_cold_start_heals_to_the_new_epoch(wired, pg_conn, monkeypatch):
    """Cloud Run keeps K_REVISION across a cold start, so a returning browser's stores
    come back from app.session_state as they were at the epoch it last saw. With no
    slot in memory it was taken for a new session: stamped, never healed, and it served
    the pre-restart book until the next import."""
    from sqlalchemy import text
    from app import book, main

    monkeypatch.setattr(main, "reload_book", lambda: None)
    browser = TestClient(app)
    browser.cookies.set("volt_session", "s-cold-start")
    data_epoch.bump("sheet")
    card = browser.get("/v1/pipeline?all=true").json()["items"][0]
    saved = pg_conn.execute(text(
        "select key from app.session_state where session_id = 's-cold-start'")).scalars().all()
    assert {"import.seen_epoch", "invoice_pipeline.state"} <= set(saved)   # what the restart restores

    # The 2-hourly crm.lead Job lands while the instance is scaled to zero.
    for customer in book.build()[1]["registry"]:
        if customer.uid == card["customer_uid"]:
            monkeypatch.setattr(customer, "display_name", "Renamed by the import")
    data_epoch.bump("crm-lead")

    for store in session_domain.REGISTRY:                                 # the restart
        store._by_session.clear()
        store._written.clear()
    data_epoch.reset_cache()

    items = browser.get("/v1/pipeline?all=true").json()["items"]
    # Flags, not names: the seed holds real ones, and a failure prints this line.
    # [False] is the bug — the restored card kept its pre-restart name.
    assert [i["display_name"] == "Renamed by the import"
            for i in items if i["uid"] == card["uid"]] == [True]
