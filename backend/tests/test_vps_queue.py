import asyncio
import json
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app import db, migrate, task_objects


@pytest.fixture
def queue(monkeypatch, pg_url, pg_conn, tmp_path):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ENV", "prd")
    monkeypatch.setenv("TASK_QUEUE_BACKEND", "postgres")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("UPLOADS_BUCKET", "uploads")
    yield pg_conn
    db.reset()


def seed(conn, state="done"):
    conn.execute(text("insert into app.operation_run(uid,payload) values('local-job',cast(:p as jsonb))"),
                 {"p": json.dumps({"uid": "local-job", "state": state, "kind": "import",
                                   "finished_at": None, "started_at": 1})})
    conn.execute(text("insert into app.task_outbox(uid,payload) values('local-job',cast(:p as jsonb))"),
                 {"p": json.dumps({"object_name": "jobs/local-job/body", "sha256": "wrong"})})
    conn.commit()


def test_completed_job_is_acknowledged_once_without_cloud_identity(queue):
    from app import local_worker
    seed(queue)
    assert asyncio.run(local_worker.run_once()) == 1
    queue.commit()
    assert queue.execute(text("select finished_at is not null from app.task_outbox")).scalar_one()
    assert asyncio.run(local_worker.run_once()) == 0


def test_corrupt_payload_is_dead_lettered_without_retrying_permanent_failure(queue):
    from app import local_worker
    seed(queue, state="queued")
    task_objects.put("jobs/local-job/body", b"file")
    assert asyncio.run(local_worker.run_once()) == 1
    queue.commit()
    row = queue.execute(text("select finished_at,dead_lettered_at,attempt_count,next_attempt_at,last_error_code from app.task_outbox")).one()
    assert row.finished_at and row.dead_lettered_at and row.attempt_count == 1
    assert row.next_attempt_at is None and row.last_error_code == "job_body_changed"
    assert asyncio.run(local_worker.run_once()) == 0


def test_another_worker_cannot_execute_while_a_job_is_running(queue):
    from app import local_worker
    seed(queue)
    # The lock is session-scoped: a second process must leave the job pending.
    queue.execute(text("select pg_advisory_lock(812049712)"))
    try:
        assert asyncio.run(local_worker.run_once()) == 0
        assert queue.execute(text("select finished_at from app.task_outbox")).scalar_one() is None
    finally:
        queue.execute(text("select pg_advisory_unlock(812049712)"))


def test_local_relay_does_not_require_gcp_configuration(queue):
    from app import task_outbox
    seed(queue)
    assert task_outbox.relay() == 1
    queue.commit()
    assert queue.execute(text("select finished_at is not null from app.task_outbox")).scalar_one()


def test_worker_commits_business_write_and_does_not_replay_it(queue, monkeypatch):
    from fastapi import FastAPI
    from app import local_worker, main, session, business_records, task_outbox
    from app.production_unit import ProductionUnitMiddleware
    from app.pipelines import runs
    application = FastAPI()
    counter = session.Store(dict, key="test.vps.worker.counter")

    @application.post("/v1/counter")
    def increment():
        state = counter.for_current()
        state["count"] = state.get("count", 0) + 1
        return state

    application.add_middleware(ProductionUnitMiddleware)
    monkeypatch.setattr(main, "app", application)
    uid = runs.start("import")
    task_outbox.enqueue(uid, "/v1/counter", b"{}", b"", {"content-type": "application/json"},
                        {"sub": "worker-owner", "role": "OWNER", "officer": "owner"})
    assert asyncio.run(local_worker.run_once()) == 1
    queue.commit()
    state, found = business_records.load(queue, "test.vps.worker.counter")
    assert found and state["count"] == 1
    assert asyncio.run(local_worker.run_once()) == 0


def test_database_error_does_not_strand_the_worker_lock(queue):
    from app import local_worker
    queue.execute(text("alter table app.task_outbox rename to task_outbox_unavailable"))
    queue.commit()
    try:
        with pytest.raises(SQLAlchemyError):
            asyncio.run(local_worker.run_once())
        assert queue.execute(text("select pg_try_advisory_lock(812049712)")).scalar_one()
    finally:
        db.reset()
        queue.execute(text("select pg_advisory_unlock(812049712)"))
        queue.execute(text("alter table app.task_outbox_unavailable rename to task_outbox"))
        queue.commit()
