import pytest
from sqlalchemy import text
from app import db, migrate


@pytest.fixture
def wired(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.execute(text("insert into app.operation_run(uid,payload) values "
                         "('run-1','{}'),('run-rollback','{}')"))
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    yield pg_conn
    db.reset()


def test_enqueue_does_not_contain_a_bearer_token_and_is_durable(wired, monkeypatch):
    from app import task_outbox, task_objects
    monkeypatch.setattr(task_objects, "put", lambda name, raw: name)
    task_outbox.enqueue("run-1", "/v1/imports:start", b"file", b"install=true",
                        {"x-volt-filename": "book.xlsx", "authorization": "Bearer secret"},
                        {"sub": "officer@volt.co.th", "role": "MANAGER", "kind": "GOOGLE"})
    row = wired.execute(text("select payload from app.task_outbox where uid='run-1'")).scalar_one()
    assert row["path"] == "/v1/imports:start"
    assert "Bearer" not in str(row)
    assert row["object_name"] == "jobs/run-1/body"


def test_outbox_is_rolled_back_with_business_transaction(wired, monkeypatch):
    from app import task_outbox, task_objects
    from app.production_unit import CURRENT
    monkeypatch.setattr(task_objects, "put", lambda name, raw: name)
    with db.connect() as conn:
        tx = conn.begin()
        token = CURRENT.set({"conn": conn})
        try:
            task_outbox.enqueue("run-rollback", "/v1/imports:start", b"file", b"", {}, {"sub": "actor"})
            tx.rollback()
        finally: CURRENT.reset(token)
    assert wired.execute(text("select count(*) from app.task_outbox")).scalar() == 0


def test_internal_oidc_rejects_wrong_service_account(monkeypatch):
    from app.worker import verify_caller
    monkeypatch.setenv("WORKER_AUDIENCE", "https://worker.example")
    monkeypatch.setenv("TASK_CALLER_EMAIL", "tasks@example.iam.gserviceaccount.com")
    monkeypatch.setenv("SCHEDULER_CALLER_EMAIL", "scheduler@example.iam.gserviceaccount.com")
    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", lambda *a, **k: {
        "email": "attacker@example.com", "email_verified": True,
    })
    with pytest.raises(Exception) as refused:
        verify_caller("Bearer identity-token", "tasks")
    assert getattr(refused.value, "status", None) == 403
