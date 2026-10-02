"""Small-team production unit of work: durable shared state, commit before send.

The advisory lock deliberately serializes domain adapters while they still mutate
objects in place. It is cross-process; it must pass the 10-user load gate before
release. It is not advertised as a solution for an unbounded workload.
"""
import hashlib
import uuid
import time
import json
from contextvars import ContextVar

import anyio
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from . import business_records, db, errors, session

CURRENT = ContextVar("production_unit", default=None)
LOCK_KEY = 0x564F4C54505244


def enabled():
    import os
    return os.environ.get("ENV") == "prd"


class BorrowedConnection:
    """Domain transaction scopes are savepoints; only the outer unit may commit."""
    def __init__(self, conn): self.conn = conn
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def __getattr__(self, name): return getattr(self.conn, name)
    def begin(self): return self.conn.begin_nested()
    def execute(self, statement, *args, **kwargs):
        # Legacy import adapters used session locks. Production must release all
        # locks on rollback as well as success, before returning a pooled socket.
        from sqlalchemy.sql.elements import TextClause
        if isinstance(statement, TextClause):
            sql = str(statement)
            if "pg_advisory_unlock(" in sql:
                return self.conn.execute(text("select true"))
            sql = sql.replace("pg_try_advisory_lock(", "pg_try_advisory_xact_lock(")
            sql = sql.replace("pg_advisory_lock(", "pg_advisory_xact_lock(")
            statement = text(sql)
        return self.conn.execute(statement, *args, **kwargs)
    def in_transaction(self): return False
    def close(self): pass
    def commit(self): pass
    def rollback(self):
        # Explicit rollback is used by some optional snapshot readers. Those readers
        # must not roll back another domain's writes in the enclosing request.
        CURRENT.get()["rollback_requested"] = True


def store_key(key):
    # The saved personal filter stays with the authenticated user.
    unit = CURRENT.get()
    if key in ("criteria.default", "reports.snapshots") and unit:
        return key + ":" + unit.get("subject", "anonymous")
    return key


def restore(key, factory):
    unit = CURRENT.get()
    value, found = business_records.load(unit["conn"], store_key(key))
    return value if found else factory()


def flush():
    unit = CURRENT.get()
    touched = session.TOUCHED.get() or set()
    changed = False
    for store in touched:
        if session.current() in store._by_session:
            changed = business_records.save(unit["conn"], store_key(store.key),
                                             store._by_session[session.current()]) or changed
    if changed:
        unit["version"] = unit["conn"].execute(text(
            "update app.business_version set version=version+1 where singleton=true returning version")).scalar_one()
    return changed


class ProductionUnitMiddleware:
    def __init__(self, app, enabled=enabled):
        self.app = app
        self.enabled = enabled
        self.local_lock = anyio.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.enabled() or not scope.get("path", "").startswith("/v1/"):
            return await self.app(scope, receive, send)
        async with self.local_lock:
            return await self._request(scope, receive, send)

    async def _request(self, scope, receive, send):
        started = time.monotonic()
        conn = transaction = None
        unit_token = session_token = touched_token = None
        slot = "prd-request:" + uuid.uuid4().hex
        messages = []
        async def capture(message): messages.append(message)
        try:
            conn = await run_in_threadpool(db.connect)
            transaction = await run_in_threadpool(conn.begin)
            await run_in_threadpool(conn.execute, text("set local lock_timeout='5s'"))
            mutation_request = scope.get("method") in ("POST", "PUT", "PATCH", "DELETE")
            control_request = scope.get("path", "").startswith("/v1/operation-runs/")
            if mutation_request and not control_request:
                await run_in_threadpool(conn.execute, text("select pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
            elif not mutation_request:
                await run_in_threadpool(conn.execute, text("set transaction isolation level repeatable read"))
            version = await run_in_threadpool(lambda: conn.execute(text(
                "select version from app.business_version where singleton=true")).scalar_one())
            from . import auth
            auth_session = await run_in_threadpool(auth.resolve_session, scope) if auth.current_config().on else None
            unit = {"conn": conn, "version": version, "subject": (auth_session or {}).get("sub", "anonymous")}
            unit_token = CURRENT.set(unit)
            session_token = session.CURRENT.set(slot)
            touched_token = session.TOUCHED.set(set())
            import os
            if (auth_session and not scope.get("volt_worker") and
                os.environ.get("PROD_GO_LIVE_ENABLED") != "true" and
                not scope["path"].startswith("/v1/auth/") and
                auth_session.get("role") not in ("OPS", "OWNER") and
                auth_session.get("sub") not in os.environ.get("PROD_CANDIDATE_TEST_SUBJECTS", "").split(",")):
                raise self.problem("production_maintenance", 503)
            if auth_session and not scope["path"].startswith(("/v1/auth/", "/v1/operation-runs/")):
                from .production_runtime import prepare_book
                await run_in_threadpool(prepare_book)
            from .durable_runs import WORKER_RUN
            if WORKER_RUN.get():
                from .pipelines import runs
                existing_run = await run_in_threadpool(runs.get, WORKER_RUN.get())
                if existing_run and existing_run["state"] in ("done", "cancelled", "failed"):
                    await run_in_threadpool(transaction.rollback)
                    messages = [{"type": "http.response.start", "status": 200, "headers": [(b"cache-control", b"no-store")]},
                                {"type": "http.response.body", "body": b'{"completed":true}'}]
                    return await self.deliver(messages, scope, send)
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            method, path = scope.get("method"), scope["path"]
            mutation = method in ("POST", "PUT", "PATCH", "DELETE")
            idem = headers.get(b"idempotency-key") if mutation and not path.startswith("/v1/auth/") else None
            fingerprint = None
            if idem:
                if len(idem) > 200:
                    raise self.problem("invalid_idempotency_key", 422)
                chunks = []
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        raise RuntimeError("request disconnected")
                    chunks.append(message.get("body", b""))
                    if sum(map(len, chunks)) > 25 * 1024 * 1024:
                        raise self.problem("request_too_large", 413)
                    if not message.get("more_body"): break
                body = b"".join(chunks)
                fingerprint = hashlib.sha256(method.encode() + path.encode() + scope.get("query_string", b"") + body).hexdigest()
                original_receive = receive
                delivered = False
                async def replay_receive():
                    nonlocal delivered
                    if delivered: return await original_receive()
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                receive = replay_receive
                cached = await run_in_threadpool(lambda: conn.execute(text(
                    "select fingerprint, status, headers, body from app.request_result where subject=:s and key=:k"),
                    {"s": unit["subject"], "k": idem.decode("ascii")}).first())
                if cached:
                    if cached.fingerprint != fingerprint:
                        raise self.problem("idempotency_conflict", 409)
                    await run_in_threadpool(transaction.rollback)
                    messages = [{"type": "http.response.start", "status": cached.status,
                                 "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in cached.headers]},
                                {"type": "http.response.body", "body": bytes(cached.body)}]
                    return await self.deliver(messages, scope, send)
            if mutation and headers.get(b"if-match") not in (None, str(version).encode(), ('"%s"' % version).encode()):
                raise self.problem("state_conflict", 409)
            await self.app(scope, receive, capture)
            start = next(m for m in messages if m["type"] == "http.response.start")
            from .durable_runs import WORKER_RUN
            failed_run = None
            if WORKER_RUN.get():
                from .pipelines import runs
                view = await run_in_threadpool(runs.get, WORKER_RUN.get())
                if view and (view.get("state") == "failed" or
                             view.get("state") == "cancelled" and not view.get("committed")):
                    failed_run = view
            if start["status"] >= 400 or failed_run:
                await run_in_threadpool(transaction.rollback)
                if unit.get("refusal_audit"):
                    from . import audit_store
                    borrowed = CURRENT.set(None)
                    try: await run_in_threadpool(audit_store.append, unit["refusal_audit"])
                    finally: CURRENT.reset(borrowed)
                if failed_run:
                    borrowed = CURRENT.set(None)
                    try:
                        problem = failed_run.get("problem") or {}
                        transient = failed_run["state"] == "failed" and (problem.get("retryable") or problem.get("status", 500) >= 500)
                        if transient:
                            await run_in_threadpool(runs.progress, failed_run["uid"], phase="queued", problem=problem, committed=False)
                        else:
                            await run_in_threadpool(runs.fail, failed_run["uid"], problem)
                    finally: CURRENT.reset(borrowed)
                    if transient: raise self.problem("job_execution_unavailable", 503)
            else:
                if unit.get("rollback_requested"):
                    raise RuntimeError("domain requested rollback")
                if mutation: await run_in_threadpool(flush)
                if mutation and not path.startswith("/v1/auth/") and unit["version"] == version:
                    unit["version"] = await run_in_threadpool(lambda: conn.execute(text(
                        "update app.business_version set version=version+1 where singleton=true returning version")).scalar_one())
                start["headers"] = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"cache-control"] + [
                    (b"cache-control", b"no-store"), (b"x-volt-state-version", str(unit["version"]).encode())]
                if idem:
                    await run_in_threadpool(conn.execute, text(
                        "insert into app.request_result(subject,key,fingerprint,status,headers,body) "
                        "values (:s,:k,:f,:c,cast(:h as jsonb),:b)"), {
                            "s": unit["subject"], "k": idem.decode("ascii"), "f": fingerprint, "c": start["status"],
                            "h": json.dumps([(k.decode("latin-1"), v.decode("latin-1")) for k, v in start["headers"]
                                             if k.lower() != b"set-cookie"]),
                            "b": b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")})
                await run_in_threadpool(transaction.commit)
        except Exception as exc:
            print(json.dumps({"event": "production_refused", "cause": type(exc).__name__,
                              "sqlstate": getattr(getattr(exc, "orig", None), "sqlstate", None)}), flush=True)
            if transaction and transaction.is_active:
                await run_in_threadpool(transaction.rollback)
            # Error details can contain PII; the response and log contain no driver text.
            problem = exc if isinstance(exc, errors.Problem) else self.problem("production_write_unavailable", 503)
            messages = []
            await problem.response()(scope, receive, capture)
        finally:
            for store in session.REGISTRY:
                store._by_session.pop(slot, None)
                store._written.pop(slot, None)
            from . import import_sync
            with import_sync._LOCKS_GUARD:
                import_sync._LOCKS.pop(slot, None)
            if touched_token is not None: session.TOUCHED.reset(touched_token)
            if session_token is not None: session.CURRENT.reset(session_token)
            if unit_token is not None: CURRENT.reset(unit_token)
            if conn is not None: await run_in_threadpool(conn.close)
            try:
                from . import auth
                route = auth._route_template(scope)
                print(json.dumps({"event": "production_request", "route": route or "unmatched",
                                  "method": scope.get("method"),
                                  "status": next((m["status"] for m in messages if m["type"] == "http.response.start"), 503),
                                  "latency_ms": round((time.monotonic() - started) * 1000, 2)}), flush=True)
            except Exception:
                # Observation must not change the result of an already committed act.
                pass
        await self.deliver(messages, scope, send)

    @staticmethod
    async def deliver(messages, scope, send):
        for message in messages:
            if message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"] + [(b"cache-control", b"no-store")]
            await send(message)

    @staticmethod
    def problem(code, status):
        return errors.Problem(code, status, "Request could not be committed",
                              "Reload current data before retrying; the request was not committed.",
                              "ยังไม่บันทึกข้อมูล กรุณาโหลดข้อมูลล่าสุดแล้วลองใหม่", "DEBT-PRD-001", retryable=status == 503)
