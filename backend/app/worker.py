"""Private task receiver; verifies Google OIDC in addition to Cloud Run IAM."""
import hashlib
import os
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
    with db.connect() as conn:
        row = conn.execute(text("select payload, finished_at from app.task_outbox where uid=:u"), {"u": uid}).first()
    if not row: raise errors.not_found("job")
    if row.finished_at: return {"completed": True}
    payload = row.payload
    from .pipelines import runs
    run = await run_in_threadpool(runs.get, uid)
    if run and run["state"] in ("done", "cancelled", "failed"):
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
            if response.status_code >= 400:
                raise errors.Problem("job_execution_unavailable", 503, "Job not committed",
                                     "Task execution can be retried.", "งานยังไม่สำเร็จ ระบบจะลองใหม่", "DEBT-JOB-503")
    finally: WORKER_RUN.reset(token)
    await run_in_threadpool(_finished, uid)
    return {"completed": True}


def _finished(uid):
    with db.connect() as conn, conn.begin():
        conn.execute(text("update app.task_outbox set finished_at=now() where uid=:u"), {"u": uid})
