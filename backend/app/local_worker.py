"""Private PostgreSQL queue runner for the SSH server; no HTTP listener."""
import asyncio
import json
import os
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
                    "select uid,attempt_count from app.task_outbox where finished_at is null "
                    "and (next_attempt_at is null or next_attempt_at <= now()) order by created_at,uid limit 1"
                )).first()
                if row is None:
                    return 0
                delay = min(300, 5 * 2 ** min(row.attempt_count, 6))
                lease.execute(text(
                    "update app.task_outbox set attempt_count=attempt_count+1,dispatched_at=now(),"
                    "next_attempt_at=now()+:delay * interval '1 second' where uid=:u"
                ), {"u": row.uid, "delay": delay})
            try:
                await execute_job(row.uid)
            except Exception as exc:
                # Persisted backoff survives a process restart; never print payloads.
                print(json.dumps({"event": "local_job_retry", "cause": type(exc).__name__}), flush=True)
            return 1
        finally:
            lease.execute(text("select pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lease.commit()


async def serve():
    if os.environ.get("TASK_QUEUE_BACKEND") != "postgres":
        raise RuntimeError("Private local worker requires TASK_QUEUE_BACKEND=postgres")
    from . import main  # Validate production environment and configure authentication.
    from .durable_schedule import enqueue_due
    while True:
        try:
            enqueue_due()
            handled = await run_once()
        except Exception as exc:
            print(json.dumps({"event": "local_worker_unavailable", "cause": type(exc).__name__}), flush=True)
            handled = 0
        await asyncio.sleep(0.1 if handled else 1)


if __name__ == "__main__":
    asyncio.run(serve())
