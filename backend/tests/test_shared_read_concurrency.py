"""Shared reads overlap without sharing mutable graphs or publishing stale books."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import auth, business_records, db, errors, migrate, production_runtime, session
from app.production_unit import CURRENT, ProductionUnitMiddleware, _ReadWriteGate, _STORE_TEMPLATES


@pytest.fixture
def shared(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    auth.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(production_runtime, "_BOOK_INVALID", False)
    old = len(session.REGISTRY)
    yield pg_conn
    auth.reset()
    del session.REGISTRY[old:]
    db.reset()


def test_writer_priority_and_cancelled_writer_release_reader_queue():
    async def run():
        gate = _ReadWriteGate(2)
        await gate.acquire("read")
        entered = []
        release_writer = asyncio.Event()
        async def writer():
            await gate.acquire("write")
            entered.append("writer")
            await release_writer.wait()
            await gate.release("write")
        async def reader():
            await gate.acquire("read")
            entered.append("reader")
            await gate.release("read")
        w = asyncio.create_task(writer())
        while not gate.waiting_writers:
            await asyncio.sleep(0)
        r = asyncio.create_task(reader())
        await asyncio.sleep(0)
        assert entered == []
        await gate.release("read")
        while not entered:
            await asyncio.sleep(0)
        assert entered == ["writer"]
        release_writer.set()
        await asyncio.gather(w, r)
        assert entered == ["writer", "reader"]
        await gate.acquire("read")
        cancelled = asyncio.create_task(gate.acquire("write"))
        while not gate.waiting_writers:
            await asyncio.sleep(0)
        resumed = asyncio.create_task(gate.acquire("read"))
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        await asyncio.wait_for(resumed, 1)
        assert gate.readers == 2 and gate.waiting_writers == 0
        await gate.release("read")
        await gate.release("read")
    asyncio.run(run())


def test_concurrent_gets_have_unique_mutable_slots_and_respect_reader_bound(shared):
    store = session.Store(dict, key="test.parallel-read")
    app = FastAPI()
    active = [0]
    peak = [0]
    @app.get("/v1/read/{value}")
    async def read(value: str):
        # Distinct requests mutate their private read graph while overlapping.
        await asyncio.to_thread(lambda: store.for_current().update(value=value))
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0.03)
        result = dict(store.for_current())
        active[0] -= 1
        return result
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            results = await asyncio.gather(*(client.get(f"/v1/read/{i}") for i in range(8)))
        assert [row.json()["value"] for row in results] == [str(i) for i in range(8)]
        assert all(row.status_code == 200 for row in results)
    asyncio.run(run())
    assert 1 < peak[0] <= 4
    assert store._by_session == {}


def test_cached_graph_is_copied_and_per_store_update_delete_invalidate_it(shared):
    store = session.Store(dict, key="test.cached-read")
    app = FastAPI()
    @app.post("/v1/value")
    def seed():
        store.for_current().update(value=1, visits=[])
        return {"saved": True}
    @app.get("/v1/value")
    def read():
        graph = store.for_current()
        graph["visits"].append("only-this-read")
        return graph
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    api = TestClient(app)
    assert api.post("/v1/value").status_code == 200
    version = api.get("/v1/value").headers["x-volt-state-version"]
    for _ in range(2):
        assert api.get("/v1/value").json() == {"value": 1, "visits": ["only-this-read"]}
    with db.connect() as conn, conn.begin():
        business_records.save(conn, store.key, {"value": 2, "visits": [], "temporary": True})
    assert api.get("/v1/value").json()["value"] == 2
    with db.connect() as conn, conn.begin():
        business_records.save(conn, store.key, {"value": 3, "visits": []})
    response = api.get("/v1/value")
    assert response.json() == {"value": 3, "visits": ["only-this-read"]}
    assert response.headers["x-volt-state-version"] == version  # per-store signature, not just global version
    with _STORE_TEMPLATES.lock:
        assert sum(key[1] == store.key for key in _STORE_TEMPLATES.entries) == 1


def test_new_epoch_reader_refreshes_under_exclusive_lease(shared, monkeypatch):
    config = auth.AuthConfig(on=True, secret=b"s" * 40)
    auth.set_config(config)
    refresh_modes = []
    ready = [False]
    def prepare(exclusive=True):
        refresh_modes.append(exclusive)
        if not ready[0] and not exclusive:
            raise production_runtime.BookRefreshRequired()
        ready[0] = True
    monkeypatch.setattr(production_runtime, "prepare_book", prepare)
    app = FastAPI()
    @app.get("/v1/read")
    def read():
        return {"fresh": ready[0]}
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    api = TestClient(app)
    actor = auth.new_session("owner", "TEST", "OWNER", "owner", False)
    api.cookies.set(auth.COOKIE, auth.sign_session(actor, config.secret))
    assert api.get("/v1/read").json() == {"fresh": True}
    assert refresh_modes == [False, True]
    assert api.get("/v1/read").status_code == 200
    assert refresh_modes[-1] is False


def test_older_snapshot_cannot_rewind_a_newer_book(monkeypatch):
    from app import book, import_sync, main
    monkeypatch.setattr(production_runtime, "_BOOK_INVALID", False)
    monkeypatch.setattr(import_sync, "_book_epoch", {"value": 2})
    monkeypatch.setattr(book, "_CACHE", {(None, book._VERSION): ([], {"source": {"origin": "LANDING"}})})
    def forbidden():
        raise AssertionError("a stale snapshot must not replace the process book")
    monkeypatch.setattr(main, "reload_book", forbidden)
    conn = SimpleNamespace(execute=lambda *_args, **_kwargs: SimpleNamespace(scalar_one=lambda: 1))
    token = CURRENT.set({"conn": conn})
    try:
        with pytest.raises(errors.Problem) as refused:
            production_runtime.prepare_book(exclusive=True)
        assert refused.value.code == "production_snapshot_stale"
        assert import_sync._book_epoch["value"] == 2
    finally:
        CURRENT.reset(token)


def test_failed_import_invalidates_rebound_book_before_next_reader(shared, monkeypatch):
    from app import import_sync, main
    from fastapi.responses import JSONResponse
    original = main.CUSTOMERS
    original_epoch = import_sync._book_epoch["value"]
    config = auth.AuthConfig(on=True, secret=b"s" * 40)
    auth.set_config(config)
    prepare_modes = []
    def prepare(exclusive=True):
        prepare_modes.append(exclusive)
        if production_runtime._BOOK_INVALID:
            if not exclusive:
                raise production_runtime.BookRefreshRequired()
            main.CUSTOMERS = original
            import_sync._book_epoch["value"] = original_epoch
            production_runtime._BOOK_INVALID = False
    monkeypatch.setattr(production_runtime, "prepare_book", prepare)
    app = FastAPI()
    @app.post("/v1/import-fails")
    def fail():
        main.CUSTOMERS = []
        import_sync._book_epoch["value"] += 1
        return JSONResponse({"code": "failed"}, status_code=503)
    @app.get("/v1/read")
    def read():
        return {"count": len(main.CUSTOMERS)}
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    api = TestClient(app)
    actor = auth.new_session("owner", "TEST", "OWNER", "owner", False)
    api.cookies.set(auth.COOKIE, auth.sign_session(actor, config.secret))
    try:
        assert api.post("/v1/import-fails").status_code == 503
        assert production_runtime._BOOK_INVALID
        assert api.get("/v1/read").json() == {"count": len(original)}
        assert prepare_modes[-2:] == [False, True]
        assert not production_runtime._BOOK_INVALID
    finally:
        main.CUSTOMERS = original
        import_sync._book_epoch["value"] = original_epoch


def test_subject_owned_store_templates_do_not_cross_accounts(shared, monkeypatch):
    config = auth.AuthConfig(on=True, secret=b"s" * 40)
    auth.set_config(config)
    monkeypatch.setattr(production_runtime, "prepare_book", lambda **_kwargs: None)
    store = session.Store(dict, key="criteria.default")
    app = FastAPI()
    @app.post("/v1/preferences/{value}")
    def write(value: str):
        store.for_current()["value"] = value
        return {"saved": True}
    @app.get("/v1/preferences")
    def read():
        return store.for_current()
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    clients = []
    for who in ("first", "second"):
        client = TestClient(app)
        actor = auth.new_session(who, "TEST", "OWNER", "owner", False)
        client.cookies.set(auth.COOKIE, auth.sign_session(actor, config.secret))
        assert client.post("/v1/preferences/" + who).status_code == 200
        clients.append(client)
    for _ in range(2):
        assert clients[0].get("/v1/preferences").json()["value"] == "first"
        assert clients[1].get("/v1/preferences").json()["value"] == "second"


def test_template_hit_cannot_bypass_record_schema_validation(shared):
    store = session.Store(dict, key="test.cached-schema")
    app = FastAPI()
    @app.post("/v1/value")
    def write():
        store.for_current()["value"] = 1
        return {"saved": True}
    @app.get("/v1/value")
    def read():
        return store.for_current()
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    api = TestClient(app)
    assert api.post("/v1/value").status_code == 200
    assert api.get("/v1/value").json()["value"] == 1
    assert api.get("/v1/value").json()["value"] == 1
    with db.connect() as conn, conn.begin():
        # Preserve versions/timestamps to exercise validation on the cache-hit path.
        conn.execute(text("update app.business_record set schema_version=2 where store_key=:k"), {"k": store.key})
    assert api.get("/v1/value").status_code == 503
