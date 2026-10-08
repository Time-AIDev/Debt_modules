"""Actual PEAK enqueue controls retain quota, replay and fresh-role boundaries."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

import pytest
from sqlalchemy import text

from app import auth, business_records, db, main, production_runtime, read_projection, task_objects
from app.pipelines import peak_service
from app.production_unit import LOCK_KEY
from .test_production_http import production as _production_fixture

production = _production_fixture

SUBJECT = "first@load.example.test"
SECOND = "second@load.example.test"
RAW = b"synthetic queue bytes, no financial application\n"
PATHS = ("/api/v1/pipelines/peak-report:start", "/api/v1/pipelines/peak-receipt:start")


@pytest.mark.parametrize("kind", ("peak-report", "peak-receipt"))
def test_apply_submission_is_durable_and_replayed_without_reading_portfolio(enqueue_api, kind):
    api, actor, totals, objects = enqueue_api
    path = "/api/v1/pipelines/%s/landing-runs/42:apply" % kind
    headers = dict(actor(key="synthetic-apply"), **{"Content-Type": "application/json"})
    before = totals()
    with db.connect() as barrier, barrier.begin():
        barrier.execute(text("select pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        response = api.post(path, json={}, headers=headers)
        assert response.status_code == 202
    replay = api.post(path, json={}, headers=headers)
    assert replay.status_code == 202 and replay.content == response.content
    assert totals() == (before[0] + 1, before[1] + 1, *before[2:])
    assert [p.read_bytes() for p in objects.rglob("body")] == [b"{}"]


@pytest.fixture
def enqueue_api(production, monkeypatch, tmp_path):
    api, headers = production
    auth.set_config(auth.load_config({"AUTH_MODE": "on", "AUTH_SESSION_SECRET": "s" * 40,
        "AUTH_SESSION_POLICY": "tab", "GOOGLE_CLIENT_ID": "client", "AUTH_ALLOWLIST": json.dumps({
            SUBJECT: {"role": "OWNER", "officer": "owner"},
            SECOND: {"role": "OWNER", "officer": "owner"}})}, env_file=tmp_path / "none"))
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("UPLOADS_BUCKET", "synthetic-jobs")
    monkeypatch.setenv("OBJECT_STORAGE_MIN_FREE_BYTES", "0")
    with db.connect() as conn, conn.begin():
        conn.execute(text("delete from records.user_account where email=any(:s)"), {"s": [SUBJECT, SECOND]})
    def forbidden(*args, **kwargs):
        raise AssertionError("Queue submission touched portfolio or processing")
    for module, name in ((production_runtime, "prepare_book"), (business_records, "load"),
                         (business_records, "save"), (read_projection, "finish_write"),
                         (read_projection, "current"), (peak_service, "run_upload"),
                         (peak_service, "run_receipt_upload"), (peak_service, "run_api")):
        monkeypatch.setattr(module, name, forbidden)
    def actor(subject=SUBJECT, role="OWNER", officer="owner", key="synthetic-enqueue"):
        return {**headers(subject, role, officer), "Content-Type": "application/octet-stream",
                "X-Volt-Filename": "synthetic-report.csv", "Idempotency-Key": key}
    def totals():
        with db.connect() as conn:
            return tuple(conn.execute(text("select "
                "(select count(*) from app.task_outbox), (select count(*) from app.operation_run), "
                "(select version from app.business_version where singleton), "
                "(select count(*) from app.data_epoch), (select count(*) from app.customer_projection)")).one())
    yield api, actor, totals, tmp_path / "objects"
    with db.connect() as conn, conn.begin():
        conn.execute(text("delete from records.user_account where email=any(:s)"), {"s": [SUBJECT, SECOND]})


@pytest.mark.parametrize("path", PATHS)
def test_queue_start_ignores_business_barrier_and_replays_identically_without_portfolio_side_effects(enqueue_api, path):
    api, actor, totals, objects = enqueue_api
    credentials = actor()
    before = totals()
    with db.connect() as barrier, barrier.begin():
        barrier.execute(text("select pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        first = api.post(path, content=RAW, headers=credentials)
        assert first.status_code == 202, first.status_code
    replay = api.post(path, content=RAW, headers=credentials)
    assert replay.status_code == 202 and replay.content == first.content
    assert first.json()["state"] == "queued"
    assert totals() == (before[0] + 1, before[1] + 1, *before[2:])
    assert [p.read_bytes() for p in objects.rglob("body")] == [RAW]
    changed = api.post(path, content=RAW + b"changed", headers=credentials)
    assert changed.status_code == 409 and changed.json()["code"] == "idempotency_conflict"
    assert totals() == (before[0] + 1, before[1] + 1, *before[2:])


def competing_submissions(api, path, first_headers, second_headers, monkeypatch):
    original = task_objects.put
    entered, release, competing = threading.Event(), threading.Event(), threading.Event()
    puts = []
    def paused_put(name, raw, *args, **kwargs):
        puts.append(name)
        if len(puts) == 1:
            entered.set()
            assert release.wait(5), "Synthetic upload gate did not release"
        return original(name, raw, *args, **kwargs)
    monkeypatch.setattr(task_objects, "put", paused_put)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(api.post, path, content=RAW, headers=first_headers)
        assert entered.wait(5), "First upload never reached immutable object storage"
        def second_request():
            competing.set()
            return api.post(path, content=RAW, headers=second_headers)
        second = pool.submit(second_request)
        try:
            assert competing.wait(2)
            # Observe an actual database lock waiter, never rely on a sleep to
            # claim concurrency. This connection is to the private test DB only.
            deadline, observed = time.monotonic() + 3, False
            while time.monotonic() < deadline:
                with db.connect() as conn:
                    observed = bool(conn.execute(text("select count(*) from pg_stat_activity "
                        "where datname=current_database() and wait_event='advisory'")).scalar_one())
                if observed:
                    break
                time.sleep(.01)
            assert observed, "No concurrent idempotency/quota lock waiter was observed"
        finally:
            release.set()
        return first.result(timeout=5), second.result(timeout=5), puts


@pytest.mark.parametrize("path", PATHS)
def test_concurrent_same_key_start_has_one_job_one_object_and_identical_202(enqueue_api, path, monkeypatch):
    api, actor, totals, objects = enqueue_api
    credentials, before = actor(), totals()
    first, second, puts = competing_submissions(api, path, credentials, credentials, monkeypatch)
    assert first.status_code == second.status_code == 202
    assert first.content == second.content
    assert len(puts) == 1 and len(list(objects.rglob("body"))) == 1
    assert totals() == (before[0] + 1, before[1] + 1, *before[2:])


def test_concurrent_distinct_key_quota_reads_after_lock_and_refuses_before_creating_orphan(enqueue_api, monkeypatch):
    api, actor, totals, objects = enqueue_api
    monkeypatch.setenv("JOB_OWNER_MAX_BYTES", str(len(RAW)))
    monkeypatch.setenv("JOB_TOTAL_MAX_BYTES", str(len(RAW)))
    before = totals()
    first, second, puts = competing_submissions(api, PATHS[0], actor(key="first"), actor(key="second"), monkeypatch)
    assert first.status_code == 202 and second.status_code == 429
    assert second.json()["code"] == "job_storage_quota"
    assert len(puts) == 1 and len(list(objects.rglob("body"))) == 1
    assert totals() == (before[0] + 1, before[1] + 1, *before[2:])


@pytest.mark.parametrize("path", PATHS)
def test_saved_enqueue_refuses_disabled_user_and_new_ops_role(enqueue_api, path):
    api, actor, totals, objects = enqueue_api
    credentials = actor()
    first = api.post(path, content=RAW, headers=credentials)
    assert first.status_code == 202
    after = totals()
    with db.connect() as conn, conn.begin():
        conn.execute(text("insert into records.user_account(kind,email,role,officer,disabled_at) "
            "values('GOOGLE',:s,'OWNER','owner',now())"), {"s": SUBJECT})
    disabled = api.post(path, content=RAW, headers=credentials)
    assert disabled.status_code == 401
    with db.connect() as conn, conn.begin():
        conn.execute(text("update records.user_account set disabled_at=null,role='OPS',officer='ops' where email=:s"), {"s": SUBJECT})
    # A newly issued OPS credential is valid for the changed account. It must
    # still pass the exact route's permissions before any saved202 is returned.
    ops = actor(role="OPS", officer="ops")
    denied = api.post(path, content=RAW, headers=ops)
    assert denied.status_code == 403
    assert totals() == after and len(list(objects.rglob("body"))) == 1


def test_idempotency_keys_remain_per_authenticated_subject(enqueue_api):
    api, actor, totals, objects = enqueue_api
    first = api.post(PATHS[0], content=RAW, headers=actor())
    second = api.post(PATHS[0], content=RAW, headers=actor(subject=SECOND))
    assert first.status_code == second.status_code == 202
    assert first.json()["uid"] != second.json()["uid"]
    assert totals()[0:2] == (2, 2) and len(list(objects.rglob("body"))) == 2


@pytest.mark.parametrize("mode", ["worker_scope", "worker_context", "json_api", "unknown_query"])
def test_worker_api_and_unproved_query_paths_keep_global_business_lock(enqueue_api, mode, monkeypatch):
    from fastapi.testclient import TestClient
    from app.durable_runs import WORKER_RUN
    from app.production_unit import CURRENT
    api, actor, totals, objects = enqueue_api
    held = []
    def inspect_global_barrier(**kwargs):
        conn = CURRENT.get()["conn"]
        held.append(bool(conn.execute(text("select count(*) from pg_locks where locktype='advisory' "
            "and pid=pg_backend_pid() and classid=:hi and objid=:lo and mode='ExclusiveLock' and granted"),
            {"hi": LOCK_KEY >> 32, "lo": LOCK_KEY & 0xffffffff}).scalar_one()))
        raise RuntimeError("Synthetic stop before any business processing")
    monkeypatch.setattr(production_runtime, "prepare_book", inspect_global_barrier)
    async def trusted(scope, receive, send):
        if mode == "worker_scope":
            scope["volt_worker"] = True
        token = WORKER_RUN.set("synthetic-worker-probe") if mode == "worker_context" else None
        try:
            await main.app(scope, receive, send)
        finally:
            if token is not None:
                WORKER_RUN.reset(token)
    client = TestClient(trusted, raise_server_exceptions=False)
    headers, path = actor(), PATHS[0]
    if mode == "json_api":
        headers["Content-Type"] = "application/json"
    if mode == "unknown_query":
        path += "?install=true"
    response = client.post(path, content=RAW, headers=headers)
    assert response.status_code == 503 and held == [True]
    assert totals() == (0, 0, 0, 0, 0) and list(objects.rglob("body")) == []
