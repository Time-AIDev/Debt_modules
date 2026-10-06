import json
from sqlalchemy import text
from app import auth, db, durable_schedule, migrate, task_objects


def test_schedule_enqueues_once_and_survives_process_restart(monkeypatch, pg_conn, pg_url, tmp_path):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ENV", "prd")
    monkeypatch.setenv("PROD_GO_LIVE_ENABLED", "true")
    db.reset()
    auth.set_config(auth.load_config({"AUTH_MODE": "on", "AUTH_SESSION_SECRET": "s" * 40,
                                     "AUTH_SESSION_POLICY": "tab", "GOOGLE_CLIENT_ID": "client",
                                     "AUTH_ALLOWLIST": json.dumps({"owner@volt.co.th": {"role": "OWNER", "officer": "owner"}})}, env_file=tmp_path / "none"))
    submitted = []
    monkeypatch.setattr(task_objects, "put", lambda name, raw: submitted.append(raw) or name)
    try:
        actor = auth.new_session("owner@volt.co.th", "GOOGLE", "OWNER", "owner", False)
        durable_schedule.configure(actor, True, 120)
        assert durable_schedule.enqueue_due() == 1
        assert durable_schedule.enqueue_due() == 0
        from app.routers.pipelines import _read_mode
        assert _read_mode(submitted[0], True) == "NEW_ONLY"
        db.reset()
        assert durable_schedule.state()["enabled"] is True
        assert pg_conn.execute(text("select count(*) from app.task_outbox")).scalar() == 1
    finally:
        auth.reset()
        db.reset()


def test_candidate_never_starts_automatic_odoo(monkeypatch):
    monkeypatch.setenv("PROD_GO_LIVE_ENABLED", "false")
    assert durable_schedule.enqueue_due() == 0
