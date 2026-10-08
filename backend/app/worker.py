"""Private task receiver; verifies Google OIDC in addition to Cloud Run IAM."""
import hashlib
import os
import json
import re
import time
import httpx
from fastapi import Body, FastAPI, Header
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from . import db, errors, task_objects, task_outbox
from .durable_runs import WORKER_RUN

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def verify_caller(authorization, kind):
    from google.oauth2 import id_token
    from google.auth.transport.requests import Request
    audience = os.environ.get("WORKER_AUDIENCE")
    email = os.environ.get("TASK_CALLER_EMAIL" if kind == "tasks" else "SCHEDULER_CALLER_EMAIL")
    try:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token or not audience or not email: raise ValueError()
        claims = id_token.verify_oauth2_token(token, Request(), audience=audience)
        if claims.get("email") != email or claims.get("email_verified") is not True: raise ValueError()
    except Exception:
        raise errors.Problem("internal_caller_refused", 403, "Caller refused", "Invalid workload identity.",
                             "ไม่อนุญาตให้เรียกงานภายใน", "DEBT-JOB-403") from None


@app.exception_handler(errors.Problem)
async def problem_handler(request, problem): return problem.response()


@app.get("/livez")
def livez(): return {"status": "live"}


@app.post("/internal/jobs/relay")
async def relay(authorization: str = Header(default=None)):
    await run_in_threadpool(verify_caller, authorization, "scheduler")
    from .durable_schedule import enqueue_due
    await run_in_threadpool(enqueue_due)
    return {"dispatched": await run_in_threadpool(task_outbox.relay)}


@app.post("/internal/tasks/execute")
async def execute(body: dict = Body(...), authorization: str = Header(default=None)):
    await run_in_threadpool(verify_caller, authorization, "tasks")
    return await execute_job(str(body.get("uid") or ""))


async def execute_job(uid):
    """Execute a durable intent; called by authenticated HTTP or the private daemon."""
    # The same job cannot execute concurrently on two Cloud Tasks deliveries or
    # local worker processes. Release this session lock even after a SQL error.
    with db.connect() as lease:
        acquired = lease.execute(text("select pg_try_advisory_lock(hashtext(:k))"),
                                 {"k": "job:" + uid}).scalar_one()
        lease.commit()
        if not acquired:
            raise errors.Problem("job_already_running", 503, "Job running", "Another worker owns this job.",
                                 "งานนี้กำลังทำงานอยู่", "DEBT-JOB-503", retryable=True)
        try:
            with lease.begin():
                row = lease.execute(text("select finished_at,dead_lettered_at from app.task_outbox where uid=:u for update"),
                                    {"u": uid}).first()
                if not row:
                    raise errors.not_found("job")
                if row.finished_at or row.dead_lettered_at:
                    return {"completed": not bool(row.dead_lettered_at), "dead_letter": bool(row.dead_lettered_at)}
                attempt = lease.execute(text(
                    "update app.task_outbox set attempt_count=attempt_count+1,dispatched_at=now() "
                    "where uid=:u returning attempt_count"), {"u": uid}).scalar_one()
            try:
                return await _execute_job_body(uid)
            except Exception as exc:
                permanent = isinstance(exc, (FileNotFoundError, KeyError, ValueError)) or (
                    isinstance(exc, errors.Problem) and exc.status < 500 and
                    exc.status not in (408, 425, 429) and not exc.retryable)
                max_attempts = max(1, int(os.environ.get("MAX_JOB_ATTEMPTS", "5")))
                code = re.sub(r"[^a-zA-Z0-9_]", "", str(getattr(exc, "code", type(exc).__name__)))[:80]
                if permanent or attempt >= max_attempts:
                    await run_in_threadpool(_dead_letter, uid, code)
                    return {"completed": False, "dead_letter": True}
                delay = min(300, 5 * 2 ** min(attempt - 1, 6))
                await run_in_threadpool(_retry, uid, code, delay)
                raise
        finally:
            if lease.in_transaction():
                lease.rollback()
            lease.execute(text("select pg_advisory_unlock(hashtext(:k))"), {"k": "job:" + uid})
            lease.commit()


async def _execute_job_body(uid):
    with db.connect() as conn:
        row = conn.execute(text("select payload, finished_at from app.task_outbox where uid=:u"), {"u": uid}).first()
    if not row: raise errors.not_found("job")
    if row.finished_at: return {"completed": True}
    payload = row.payload
    from .pipelines import runs
    run = await run_in_threadpool(runs.get, uid)
    if run and run["state"] == "failed":
        problem = run.get("problem") or {}
        if problem.get("retryable") is True and not run.get("committed") and not run.get("cancel_requested_at"):
            await run_in_threadpool(_reset_retryable_run, uid)
        else:
            await run_in_threadpool(_dead_letter, uid, "run_failed")
            return {"completed": False, "dead_letter": True}
    if run and run["state"] in ("done", "cancelled"):
        await run_in_threadpool(_finished, uid)
        return {"completed": True}
    if run and run.get("cancel_requested_at"):
        await run_in_threadpool(runs.checkpoint, uid, raise_cancelled=False)
        await run_in_threadpool(_finished, uid)
        return {"completed": True}
    raw = await run_in_threadpool(task_objects.get, payload["object_name"])
    if hashlib.sha256(raw).hexdigest() != payload["sha256"]:
        raise errors.Problem("job_body_changed", 409, "Job refused", "Upload integrity check failed.",
                             "ไฟล์งานไม่ตรงกับไฟล์ที่รับไว้", "DEBT-JOB-409")
    from .main import app as api_app

    async def trusted(scope, receive, send):
        scope["volt_resolved_auth"] = payload["actor"]
        scope["volt_worker"] = True
        await api_app(scope, receive, send)
    token = WORKER_RUN.set(uid)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=trusted), base_url="http://worker") as client:
            response = await client.post(payload["path"] + ("?" + payload["query"] if payload["query"] else ""),
                                         content=raw, headers=payload["headers"])
            try:
                detail = response.json()
            except ValueError:
                detail = {}
            failed_run = isinstance(detail, dict) and detail.get("state") == "failed"
            if response.status_code >= 400 or failed_run:
                detail = (detail.get("problem") or {}) if failed_run else detail
                if not isinstance(detail, dict):
                    detail = {}
                status = int(detail.get("status") or 422) if failed_run else response.status_code
                retryable = bool(detail.get("retryable")) or status >= 500 or status in (408, 425, 429)
                raise errors.Problem(detail.get("code", "job_execution_refused"), status,
                                     "Job not committed", "The API refused the task execution.",
                                     "งานยังไม่สำเร็จ กรุณาตรวจสอบสถานะงาน", "DEBT-JOB-%s" % status,
                                     retryable=retryable)
    finally: WORKER_RUN.reset(token)
    await run_in_threadpool(_finished, uid)
    return {"completed": True}


def _finished(uid):
    with db.connect() as conn, conn.begin():
        name = conn.execute(text("update app.task_outbox set finished_at=now(),next_attempt_at=null "
                                 "where uid=:u returning payload->>'object_name'"), {"u": uid}).scalar()
    # Database commit precedes removal: a rolled-back business write must retain
    # its replay input. Cleanup failure is recoverable by the retention sweep.
    if name:
        try:
            task_objects.delete(name)
        except Exception as exc:
            print(json.dumps({"event": "job_input_cleanup_deferred", "cause": type(exc).__name__}), flush=True)


def _retry(uid, code, delay):
    with db.connect() as conn, conn.begin():
        conn.execute(text("update app.task_outbox set last_error_code=:e,"
                          "next_attempt_at=now()+:d * interval '1 second' where uid=:u"),
                     {"u": uid, "e": code, "d": delay})
        _reset_retryable_run(uid, conn=conn)


def _reset_retryable_run(uid, conn=None):
    """Requeue an uncommitted transient failure without losing attempt evidence."""
    if conn is None:
        with db.connect() as active, active.begin():
            return _reset_retryable_run(uid, conn=active)
    conn.execute(text(
        "update app.operation_run set payload=payload || "
        "jsonb_build_object('state','queued','phase','queued','problem',null,'finished_at',null, "
        "'last_attempt_problem',payload->'problem'),updated_at=now() "
        "where uid=:u and payload->>'state'='failed' "
        "and payload->'problem'->>'retryable'='true' "
        "and coalesce(payload->>'committed','false')='false' "
        "and (payload->'cancel_requested_at' is null or payload->'cancel_requested_at'='null'::jsonb)"),
        {"u": uid})


def _dead_letter(uid, code):
    problem = {"code": "job_dead_letter", "status": 422, "retryable": False,
               "detail": "Task requires operator review before a new submission.",
               "message_th": "งานหยุดแล้ว กรุณาให้ผู้ดูแลตรวจสอบก่อนส่งงานใหม่", "cause": code}
    with db.connect() as conn, conn.begin():
        payload = conn.execute(text("select payload from app.operation_run where uid=:u for update"),
                               {"u": uid}).scalar()
        original = (payload or {}).get("problem")
        if isinstance(original, dict) and original.get("code") and original.get("code") != "job_dead_letter":
            # Preserve the actionable business failure; delivery exhaustion must
            # not turn missing configuration into an opaque operator-review error.
            problem = dict(original, retryable=False, dead_letter=True, delivery_error_code=code)
        conn.execute(text("update app.task_outbox set finished_at=now(),dead_lettered_at=now(),"
                          "last_error_code=:e,next_attempt_at=null where uid=:u"), {"u": uid, "e": code})
        conn.execute(text("update app.operation_run set payload=payload || cast(:p as jsonb),updated_at=now() "
                          "where uid=:u and coalesce(payload->>'state','') not in ('done','cancelled')"),
                     {"u": uid, "p": json.dumps({"state": "failed", "phase": "failed", "problem": problem,
                                                 "finished_at": time.time()})})
    print(json.dumps({"event": "job_dead_letter", "job_uid": uid, "cause": code}), flush=True)
