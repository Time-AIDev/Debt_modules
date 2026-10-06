"""Integration regressions discovered by the production review."""
import asyncio
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import auth, db, errors, migrate, monthly_history, production_permissions, session
from app.production_unit import ProductionUnitMiddleware

@pytest.fixture
def shared(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    auth.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    old = len(session.REGISTRY)
    yield pg_conn
    auth.reset()
    del session.REGISTRY[old:]
    db.reset()

def test_monthly_read_preserves_surrounding_production_write(shared):
    store = session.Store(dict, key="test.monthly-read")
    app = FastAPI()
    @app.post("/v1/snapshot-write")
    def write():
        store.for_current()["saved"] = True
        monthly_history._read("select count(*) as n from records.customer_month", {})
        return {"saved": True}
    @app.get("/v1/snapshot-write")
    def read():
        return store.for_current()
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    client = TestClient(app)
    assert client.post("/v1/snapshot-write").status_code == 200
    assert client.get("/v1/snapshot-write").json() == {"saved": True}

def test_explicit_business_rollback_refuses_success(shared):
    app = FastAPI()
    @app.post("/v1/rollback")
    def rollback():
        db.connect().rollback()
        return {"saved": True}
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    assert TestClient(app).post("/v1/rollback").status_code == 503

def test_cached_response_rechecks_account_permission(shared, monkeypatch):
    from app import production_runtime, user_accounts
    allowed = [True]
    monkeypatch.setattr(production_runtime, "prepare_book", lambda: None)
    monkeypatch.setattr(user_accounts, "session_allowed", lambda *_a, **_kw: allowed[0])
    config = auth.AuthConfig(on=True, secret=b"s" * 40)
    auth.set_config(config)
    app = FastAPI()
    @app.post("/v1/write")
    def write():
        return {"saved": True}
    app.add_middleware(auth.AuthMiddleware, still_allowed=lambda _: allowed[0])
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    client = TestClient(app)
    payload = auth.new_session("owner", "TEST", "OWNER", "owner", False)
    client.cookies.set(auth.COOKIE, auth.sign_session(payload, config.secret))
    headers = {"Idempotency-Key": "permission-replay"}
    assert client.post("/v1/write", headers=headers).status_code == 200
    allowed[0] = False
    assert client.post("/v1/write", headers=headers).status_code == 401

@pytest.mark.parametrize("path, collection", [
    ("/v1/ptps/child:close", "ptps"), ("/v1/ptps/child:cancel", "ptps"),
    ("/v1/service-issues/child:resolve", "issues"), ("/v1/cases/child:advance", "cases"),
    ("/v1/cash-cases/child:advance", "cash_cases"),
    ("/v1/recovery-cases/child/recoveries", "recovery_cases"),
    ("/v1/invoices/child:link-sent", "invoices")])
def test_legacy_child_assignment(monkeypatch, path, collection):
    from app import cases, journey
    current = SimpleNamespace(cases={"other": {"uid": "case-other", "customer_uid": "other", "officer_uid": "nantapol"}})
    monkeypatch.setattr(cases, "for_current", lambda: current)
    legacy = SimpleNamespace(**{collection: {"child": {"uid": "child", "customer_uid": "other"}}})
    monkeypatch.setattr(journey, "for_current", lambda: legacy)
    with pytest.raises(errors.Problem) as refused:
        production_permissions.enforce({"type": "http", "path": path, "method": "POST"},
                                       {"role": "OFFICER", "officer": "thip"}, b'{}')
    assert refused.value.code == "assignment_required"

@pytest.mark.parametrize("path, method", [("/v1/orders/1/approve", "POST"), ("/v1/orders/1", "DELETE"),
    ("/v1/ladder-mode", "PUT"), ("/v1/config/approval-paths", "POST"),
    ("/v1/pipeline/item/gates/down-payment", "POST")])
def test_sensitive_role_gates(path, method):
    with pytest.raises(errors.Problem) as refused:
        production_permissions.enforce({"type": "http", "path": path, "method": method},
                                       {"role": "OFFICER", "officer": "thip"}, b'{}')
    assert refused.value.status == 403

def test_chunked_body_limit_counts_before_joining(monkeypatch):
    monkeypatch.setenv("REQUEST_JSON_MAX_BYTES", "5")
    messages = iter([{"type": "http.request", "body": b"123", "more_body": True},
                     {"type": "http.request", "body": b"456", "more_body": False}])
    async def receive():
        return next(messages)
    async def run():
        return await auth._read_body(auth.bounded_receive({"path": "/v1/write", "headers": []}, receive))
    with pytest.raises(errors.Problem) as refused:
        asyncio.run(run())
    assert refused.value.status == 413

def test_declared_oversized_login_body_refused_before_read():
    with pytest.raises(errors.Problem) as refused:
        auth.bounded_receive({"path": "/v1/auth/google", "headers": [(b"content-length", b"100000")]}, None)
    assert refused.value.status == 413

def test_disabled_password_route_does_not_hash(monkeypatch):
    from app.routers.login import password_login
    auth.set_config(auth.AuthConfig(on=True, secret=b"s" * 40))
    def expensive(*_args):
        raise AssertionError("disabled password login performed PBKDF2")
    monkeypatch.setattr(auth, "check_password", expensive)
    try:
        with pytest.raises(errors.Problem):
            password_login({"username": "random", "password": "x"})
        assert auth._FAILURES == {}
    finally:
        auth.reset()

def test_rotating_names_cannot_bypass_peer_login_limit(monkeypatch):
    auth.reset()
    monkeypatch.setenv("AUTH_LOGIN_RATE_LIMIT", "2")
    scope = {"path": "/v1/auth/password", "method": "POST", "client": ("127.0.0.1", 1234)}
    auth.check_login_rate(scope)
    auth.check_login_rate(scope)
    with pytest.raises(errors.Problem) as refused:
        auth.check_login_rate(scope)
    assert refused.value.status == 429
    auth.reset()

def test_operation_control_bypasses_busy_domain_lock(monkeypatch):
    middleware = ProductionUnitMiddleware(None, enabled=lambda: True)
    reached = []
    async def request(*_args):
        reached.append(True)
    monkeypatch.setattr(middleware, "_request", request)
    async def run():
        await middleware.local_lock.acquire()
        try:
            await asyncio.wait_for(middleware({"type": "http", "path": "/v1/operation-runs/uid", "headers": []}, None, None), 0.1)
        finally:
            middleware.local_lock.release()
    asyncio.run(run())
    assert reached == [True]


def test_run_initiator_and_cancellation_permissions(monkeypatch):
    from app.pipelines import runs
    from app.routers.operation_runs import cancel_operation_run
    runs.reset()
    auth.set_config(auth.AuthConfig(on=True, secret=b"s" * 40))
    token = auth.ACTOR.set({"sub": "first", "role": "OFFICER"})
    try:
        uid = runs.start("master-sheet")
    finally:
        auth.ACTOR.reset(token)
    assert runs.get(uid)["initiated_by"] == auth.actor_key({"sub": "first"})
    actor = [{"sub": "second", "role": "OFFICER"}]
    monkeypatch.setattr(auth, "resolve_session", lambda _scope: actor[0])
    request = SimpleNamespace(scope={})
    try:
        with pytest.raises(errors.Problem) as refused:
            cancel_operation_run(uid, request)
        assert refused.value.status == 403
        actor[0] = {"sub": "first", "role": "OFFICER"}
        assert cancel_operation_run(uid, request)["state"] == "cancel_requested"
    finally:
        auth.reset()
        runs.reset()


def test_monthly_report_and_optional_snapshot_commit_in_production_unit(shared):
    app = FastAPI()
    store = session.Store(dict, key="test.snapshot-commit")
    @app.get("/v1/reports/monthly")
    def report():
        return monthly_history.report()
    @app.post("/v1/refresh")
    def refresh():
        store.for_current()["saved"] = True
        monthly_history.safe_snapshot("test-landing")
        return {"saved": True}
    @app.get("/v1/refresh")
    def read():
        return store.for_current()
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    client = TestClient(app)
    assert client.get("/v1/reports/monthly").status_code == 200
    assert client.post("/v1/refresh").status_code == 200
    assert client.get("/v1/refresh").json() == {"saved": True}


def test_upload_target_cannot_bypass_assignment(monkeypatch):
    from app import cases
    state = SimpleNamespace(cases={"other": {"uid": "case-other", "customer_uid": "other", "officer_uid": "nantapol"}})
    monkeypatch.setattr(cases, "for_current", lambda: state)
    scope = {"type": "http", "method": "POST", "path": "/v1/attachments:start", "headers": [(b"x-volt-attach-to", b"case:other")]}
    with pytest.raises(errors.Problem) as refused:
        production_permissions.enforce(scope, {"role": "OFFICER", "officer": "thip"}, b'raw')
    assert refused.value.code == "assignment_required"


def test_missing_credentials_do_not_join_business_lock_or_open_database(monkeypatch):
    auth.set_config(auth.AuthConfig(on=True, secret=b"s" * 40, session_policy="tab"))
    middleware = ProductionUnitMiddleware(None, enabled=lambda: True)
    messages = []
    async def expensive(*_args):
        raise AssertionError("unauthenticated request reached business transaction")
    monkeypatch.setattr(middleware, "_request", expensive)
    async def send(message):
        messages.append(message)
    async def run():
        await middleware.local_lock.acquire()
        try:
            await asyncio.wait_for(middleware({"type": "http", "method": "GET", "path": "/v1/workbook", "headers": []}, None, send), 0.1)
        finally:
            middleware.local_lock.release()
    try:
        asyncio.run(run())
        assert messages[0]["status"] == 401
    finally:
        auth.reset()


def test_optional_snapshot_sql_failure_rolls_back_only_its_savepoint(shared, monkeypatch):
    from sqlalchemy import text
    from app import main
    monkeypatch.setattr(main, "CUSTOMERS", [SimpleNamespace(uid="synthetic", volt_id="synthetic")])
    monkeypatch.setattr(monthly_history, "_row", lambda *_args: {"customer_uid": "synthetic"})
    monkeypatch.setattr(monthly_history, "_UPSERT", text("insert into records.missing_review_table values (1)"))
    app = FastAPI()
    store = session.Store(dict, key="test.optional-snapshot-failure")
    @app.post("/v1/snapshot")
    def write():
        store.for_current()["saved"] = True
        assert monthly_history.safe_snapshot("test-failure") == 0
        return {"saved": True}
    @app.get("/v1/snapshot")
    def read():
        return store.for_current()
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    client = TestClient(app)
    assert client.post("/v1/snapshot").status_code == 200
    assert client.get("/v1/snapshot").json() == {"saved": True}


def test_shared_get_preserves_request_caches_across_threadpool(pg_url, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import main, db, migrate, auth, request_context
    from app.production_unit import ProductionUnitMiddleware
    from starlette.concurrency import run_in_threadpool
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ENV", "prd")
    db._engine = None
    with db.connect() as conn, conn.begin(): migrate.apply(conn)
    auth.set_config(auth.load_config({"AUTH_MODE": "off"}, env_file="/tmp/no-runtime-env"))
    mini = FastAPI()
    @mini.get("/v1/cache-scope")
    async def scope():
        def first():
            request_context.reads()["shared-value"] = 42
            main._VIEW_MEMO.get()["marker"] = "present"
        await run_in_threadpool(first)
        def second():
            return {"value":request_context.reads()["shared-value"],
                    "marker":main._VIEW_MEMO.get()["marker"]}
        return await run_in_threadpool(second)
    mini.add_middleware(ProductionUnitMiddleware)
    response = TestClient(mini).get("/v1/cache-scope")
    assert response.status_code == 200, response.text
    assert response.json() == {"value":42,"marker":"present"}
