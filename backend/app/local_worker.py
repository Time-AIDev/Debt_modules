"""Private PostgreSQL queue runner for the SSH server; no HTTP listener."""
import asyncio
import json
import os
import sys
import time
from sqlalchemy import text
from . import db

LOCK_KEY = 812049712


async def run_once():
    from .worker import execute_job
    with db.connect() as lease:
        acquired = lease.execute(text("select pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar_one()
        lease.commit()
        if not acquired:
            return 0
        try:
            with lease.begin():
                row = lease.execute(text(
                    "select uid from app.task_outbox where finished_at is null and dead_lettered_at is null "
                    "and (next_attempt_at is null or next_attempt_at <= now()) order by created_at,uid limit 1"
                )).first()
                if row is None:
                    return 0
            heartbeat("working", row.uid)
            try:
                await execute_job(row.uid)
            except Exception as exc:
                # Persisted backoff survives a process restart; never print payloads.
                print(json.dumps({"event": "local_job_retry", "job_uid": row.uid, "cause": type(exc).__name__}), flush=True)
            finally:
                heartbeat("idle")
            return 1
        finally:
            if lease.in_transaction():
                lease.rollback()
            lease.execute(text("select pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lease.commit()


async def serve(probe_only=False):
    if probe_only and (os.environ.get("ENV") not in ("stg", "staging")
                       or os.environ.get("VOLT_RECOVERY_READ_ONLY") != "true"):
        raise RuntimeError("Recovery probe worker is restricted to an explicit isolated staging restore")
    if os.environ.get("TASK_QUEUE_BACKEND") != "postgres":
        raise RuntimeError("Private local worker requires TASK_QUEUE_BACKEND=postgres")
    from . import main  # Validate production environment and configure authentication.
    from .durable_schedule import enqueue_due
    if probe_only:
        print(json.dumps({"event": "recovery_worker_probe", "business_jobs_enabled": False}), flush=True)
    cleanup_at = 0
    while True:
        try:
            heartbeat("idle")
            if probe_only:
                await asyncio.sleep(1)
                continue
            enqueue_due()
            handled = await run_once()
            if time.monotonic() >= cleanup_at:
                from .object_retention import cleanup
                cleanup_at = time.monotonic() + 3600
                heartbeat("maintenance", "retention")
                result = await asyncio.to_thread(cleanup, apply=True)
                print(json.dumps({"event": "transient_retention", **result}), flush=True)
                heartbeat("idle")
        except Exception as exc:
            print(json.dumps({"event": "local_worker_unavailable", "cause": type(exc).__name__}), flush=True)
            handled = 0
        await asyncio.sleep(0.1 if handled else 1)


def heartbeat(state, uid=None):
    with db.connect() as conn, conn.begin():
        conn.execute(text(
            "insert into app.worker_heartbeat(name,state,job_uid,job_started_at) "
            "values('local',:s,:u,case when cast(:u as text) is null then null else now() end) "
            "on conflict(name) do update set last_seen_at=now(),state=excluded.state,"
            "job_uid=excluded.job_uid,job_started_at=excluded.job_started_at"
        ), {"s": state, "u": uid})


def healthy():
    with db.connect() as conn:
        return bool(conn.execute(text(
            "select case when state in ('working','maintenance') "
            "then job_started_at > now()-:deadline * interval '1 second' "
            "else last_seen_at > now()-:age * interval '1 second' end "
            "from app.worker_heartbeat where name='local'"
        ), {"age": int(os.environ.get("WORKER_HEARTBEAT_MAX_AGE_SECONDS", "30")),
            "deadline": int(os.environ.get("JOB_EXECUTION_TIMEOUT_SECONDS", "300"))}).scalar())


if __name__ == "__main__":
    if "--healthcheck" in sys.argv:
        try:
            sys.exit(0 if healthy() else 1)
        except Exception:
            sys.exit(1)
    asyncio.run(serve(probe_only="--probe-only" in sys.argv))
