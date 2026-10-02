"""A response must not outlive the transaction that makes its claim true."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db, migrate, session


@pytest.fixture
def shared(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    old = len(session.REGISTRY)
    yield pg_conn
    del session.REGISTRY[old:]
    db.reset()


def client(store, fail=False):
    from app.production_unit import ProductionUnitMiddleware
    mini = FastAPI()

    @mini.post("/v1/value")
    def write():
        store.for_current()["value"] = store.for_current().get("value", 0) + 1
        if fail:
            raise RuntimeError("simulate crash")
        return {"value": store.for_current()["value"]}

    @mini.get("/v1/value")
    def read():
        return {"value": store.for_current().get("value", 0)}

    mini.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    return TestClient(mini, raise_server_exceptions=False)


def test_two_instance_caches_read_the_same_committed_business_records(shared):
    first = session.Store(dict, key="test.production")
    assert client(first).post("/v1/value").json() == {"value": 1}
    # A second process starts cold, not with the first process's objects.
    first._by_session.clear()
    assert client(first).get("/v1/value").json() == {"value": 1}
    assert shared.execute(text("select count(*) from app.business_record")).scalar() > 0
    assert shared.execute(text("select count(*) from app.user_state")).scalar() == 0


def test_route_failure_does_not_leak_mutated_memory_into_next_request(shared):
    store = session.Store(dict, key="test.production")
    assert client(store, fail=True).post("/v1/value").status_code == 503
    assert client(store).get("/v1/value").json() == {"value": 0}


def test_stale_version_refuses_a_write(shared):
    store = session.Store(dict, key="test.production")
    api = client(store)
    old = api.get("/v1/value").headers["x-volt-state-version"]
    assert api.post("/v1/value").status_code == 200
    assert api.post("/v1/value", headers={"If-Match": old}).status_code == 409
    assert api.get("/v1/value").json()["value"] == 1


def test_duplicate_idempotency_key_replays_without_mutating_twice(shared):
    store = session.Store(dict, key="test.production")
    api = client(store)
    headers = {"Idempotency-Key": "reliable-write-1"}
    assert api.post("/v1/value", headers=headers).json()["value"] == 1
    assert api.post("/v1/value", headers=headers).json()["value"] == 1
    assert api.get("/v1/value").json()["value"] == 1


def test_failed_commit_never_sends_success(shared, monkeypatch):
    from sqlalchemy.engine.base import RootTransaction
    store = session.Store(dict, key="test.failed.commit")
    with monkeypatch.context() as patch:
        def fail_commit(self): raise RuntimeError("connection dropped during commit")
        patch.setattr(RootTransaction, "commit", fail_commit)
        assert client(store).post("/v1/value").status_code == 503
    assert client(store).get("/v1/value").json()["value"] == 0


def test_restructure_schedule_can_be_saved_as_versioned_json(shared):
    from app import business_records, fixtures
    contract = fixtures.seed()[0].contracts[0]
    value = {"instalments": contract.instalments}
    decoded = business_records.decode(business_records.encode(value))
    assert decoded["instalments"] == contract.instalments
