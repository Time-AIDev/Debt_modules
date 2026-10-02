"""One PostgreSQL schedule, dispatched by the authenticated Scheduler relay."""
import json
import os
from sqlalchemy import text
from . import auth, db, task_outbox, user_accounts
from .production_unit import CURRENT


def state():
    with db.connect() as conn:
        row = conn.execute(text("select enabled,interval_minutes,last_run_at,last_run_uid from app.schedule_config where name='crm-lead'")).mappings().first()
    from .pipelines.schedule import odoo_ready
    value = dict(row or {"enabled": False, "interval_minutes": 120, "last_run_at": None, "last_run_uid": None})
    stamp = value["last_run_at"]
    if stamp is not None: value["last_run_at"] = stamp.timestamp()
    value.update(in_process_only=False, auto=True, odoo_configured=odoo_ready(),
                 next_run_at=(value["last_run_at"] + value["interval_minutes"] * 60) if value["enabled"] and stamp else None)
    return value


def configure(actor, enabled, interval_minutes=120):
    interval = int(interval_minutes)
    if not 15 <= interval <= 1440: raise ValueError("schedule interval must be 15–1440 minutes")
    with db.connect() as conn, conn.begin():
        conn.execute(text("insert into app.schedule_config(name,enabled,interval_minutes,actor) values('crm-lead',:e,:i,cast(:a as jsonb)) "
                          "on conflict(name) do update set enabled=excluded.enabled,interval_minutes=excluded.interval_minutes,actor=excluded.actor"),
                     {"e": bool(enabled), "i": interval, "a": json.dumps(actor)})
    return state()


def enqueue_due():
    if os.environ.get("PROD_GO_LIVE_ENABLED") != "true": return 0
    from .pipelines import runs
    with db.connect() as conn, conn.begin():
        row = conn.execute(text("select actor from app.schedule_config where name='crm-lead' and enabled "
                                "and (last_run_at is null or last_run_at + interval_minutes * interval '1 minute' <= now()) "
                                "for update skip locked")).first()
        if not row: return 0
        token = CURRENT.set({"conn": conn, "subject": row.actor["sub"]})
        try:
            if not user_accounts.session_allowed(row.actor, auth.current_config().allowlist, fresh=True):
                conn.execute(text("update app.schedule_config set enabled=false where name='crm-lead'"))
                return 0
            uid = runs.start("odoo")
            task_outbox.enqueue(uid, "/v1/pipelines/crm-lead:start", b'{"mode":"NEW_ONLY"}', b"",
                                {"content-type": "application/json"}, row.actor)
            conn.execute(text("update app.schedule_config set last_run_at=now(),last_run_uid=:u where name='crm-lead'"), {"u": uid})
        finally: CURRENT.reset(token)
    return 1
