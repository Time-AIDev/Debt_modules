"""Transactional intent; Cloud Tasks delivery happens after the request commits."""
import base64
import hashlib
import json
from sqlalchemy import text
from . import db, task_objects
from .integrations import env

SAFE_HEADERS = {"content-type", "x-volt-filename", "x-volt-role", "x-volt-officer", "x-volt-attach-to"}


def enqueue(uid, path, raw, query, headers, actor):
    object_name = task_objects.put("jobs/%s/body" % uid, raw)
    payload = {"path": path, "query": query.decode("ascii"), "object_name": object_name,
               "sha256": hashlib.sha256(raw).hexdigest(), "actor": actor,
               "headers": {k.lower(): v for k, v in headers.items() if k.lower() in SAFE_HEADERS}}
    with db.connect() as conn, conn.begin():
        conn.execute(text("insert into app.task_outbox(uid,payload) values(:u,cast(:p as jsonb))"),
                     {"u": uid, "p": json.dumps(payload)})


def enqueue_request(request, uid, raw):
    from . import auth
    actor = auth.resolve_session(request.scope)
    if not actor: raise auth.auth_required()
    enqueue(uid, request.scope["path"], raw, request.scope.get("query_string", b""), dict(request.headers), actor)


def relay():
    required = [env(k) for k in ("GCP_PROJECT", "GCP_REGION", "TASK_QUEUE", "WORKER_AUDIENCE", "TASK_CALLER_EMAIL")]
    if not all(required): raise RuntimeError("task delivery configuration is incomplete")
    project, region, queue, worker, caller = required
    parent = "projects/%s/locations/%s/queues/%s" % (project, region, queue)
    sent = 0
    with db.connect() as conn, conn.begin():
        # Bounded batches avoid holding the database pool through a large backlog.
        rows = conn.execute(text("select uid from app.task_outbox where dispatched_at is null "
                                 "and finished_at is null order by created_at limit 10 for update skip locked")).fetchall()
        with task_objects.client() as transport:
            for row in rows:
                task = {"name": parent + "/tasks/" + row.uid,
                        "dispatchDeadline": "300s",
                        "httpRequest": {"httpMethod": "POST", "url": worker + "/internal/tasks/execute",
                                        "headers": {"Content-Type": "application/json"},
                                        "body": base64.b64encode(json.dumps({"uid": row.uid}).encode()).decode(),
                                        "oidcToken": {"serviceAccountEmail": caller, "audience": worker}}}
                response = transport.post("https://cloudtasks.googleapis.com/v2/%s/tasks" % parent,
                                          json={"task": task}, timeout=15)
                # A process that crashed after create recovers with the same task name.
                if response.status_code != 409: response.raise_for_status()
                conn.execute(text("update app.task_outbox set dispatched_at=now() where uid=:u"), {"u": row.uid})
                sent += 1
    return sent
