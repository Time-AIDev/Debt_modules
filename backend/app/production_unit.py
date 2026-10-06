"""Durable units: private reader graphs, exclusive writes, commit before send.

Bounded readers use their own repeatable snapshots and copied persisted state.
Mutations and book publication are locally exclusive; the PostgreSQL advisory
lock also serializes business mutations across worker/API processes. Capacity
still requires the unchanged measured load gate.
"""
import hashlib
import uuid
import time
import json
import os
import re
import copy
import threading
from collections import OrderedDict
from contextvars import ContextVar
from urllib.parse import parse_qs

import anyio
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from . import business_records, db, errors, session

CURRENT = ContextVar("production_unit", default=None)
LOCK_KEY = 0x564F4C54505244


def customer_scope(scope):
    """Only audited customer-owned routes may use the partitioned write model."""
    path = scope.get("path", "")
    if os.environ.get("VOLT_CUSTOMER_SCOPES_ENABLED", "true") != "true":
        return None
    match = re.fullmatch(r"/v1/cases/by-customer/([^/]+)(?:/(invoices|peak-codes|notes))?", path)
    if not match:
        return None
    method = scope.get("method")
    if method in ("GET", "HEAD") or (method == "POST" and match[2] == "notes"):
        return match[1]
    return None


def case_token(customer_uid, version):
    return 'case:%s:%d' % (customer_uid, version)


def independent_control(scope):
    if scope.get("path", "").startswith("/v1/operation-runs/"):
        return True
    if scope.get("path") not in ("/v1/imports", "/v1/imports:start") or scope.get("method") != "POST":
        return False
    try:
        query = parse_qs(scope.get("query_string", b"").decode("ascii"), keep_blank_values=True)
        profiles = query.get("profile", [])
        install = query.get("install", [])
    except (ValueError, UnicodeDecodeError):
        return False
    # These audited finance profiles parse/stage an owned preview only. Duplicate
    # selectors, legacy full-sheet imports, and every apply route retain the
    # exclusive business-publication barrier.
    return (len(profiles) == 1 and profiles[0] in ("debt_status", "contract_supplement")
            and (not install or len(install) == 1 and install[0].lower() in ("false", "0", "off", "no")))


class _StoreTemplates:
    """Bounded committed graphs, copied into each request; never response/auth data."""
    def __init__(self):
        self.lock = threading.RLock()
        self.entries = OrderedDict()
        self.bytes = 0

    def get(self, key):
        with self.lock:
            if key not in self.entries:
                return None, False
            graph, _size = self.entries[key]
            self.entries.move_to_end(key)
        return copy.deepcopy(graph), True

    def put(self, key, graph, size):
        max_bytes = int(os.environ.get("PROD_STORE_CACHE_BYTES", "8388608"))
        max_entries = int(os.environ.get("PROD_STORE_CACHE_ENTRIES", "16"))
        if not 0 < size <= max_bytes or max_entries < 1:
            return
        # The route receives the loader's graph. Cache a different graph so a
        # subsequent in-place route edit cannot alter the committed template.
        template = copy.deepcopy(graph)
        with self.lock:
            # Keep one version per physical store; each in-flight request already
            # owns its copy and can finish against its older SQL snapshot safely.
            for old_key in list(self.entries):
                if old_key[:2] == key[:2] and old_key != key:
                    self.bytes -= self.entries.pop(old_key)[1]
            previous = self.entries.pop(key, None)
            if previous:
                self.bytes -= previous[1]
            self.entries[key] = (template, size)
            self.bytes += size
            while len(self.entries) > max_entries or self.bytes > max_bytes:
                _old, (_graph, old_size) = self.entries.popitem(last=False)
                self.bytes -= old_size


_STORE_TEMPLATES = _StoreTemplates()


class _ReadWriteGate:
    """Bounded readers; writers and book refreshes exclude every business reader."""
    def __init__(self, readers=4):
        self.condition = anyio.Condition()
        self.limit = readers
        self.readers = 0
        self.writer = False
        self.waiting_writers = 0

    async def acquire(self, mode):
        async with self.condition:
            if mode == "read":
                while self.writer or self.waiting_writers or self.readers >= self.limit:
                    await self.condition.wait()
                self.readers += 1
            else:
                self.waiting_writers += 1
                try:
                    while self.writer or self.readers:
                        await self.condition.wait()
                    self.writer = True
                finally:
                    self.waiting_writers -= 1
                    self.condition.notify_all()

    async def release(self, mode):
        with anyio.CancelScope(shield=True):
            async with self.condition:
                if mode == "read":
                    self.readers -= 1
                else:
                    self.writer = False
                self.condition.notify_all()


_REFRESH_EXCLUSIVE = object()


def enabled():
    from .runtime_policy import shared_state_enabled
    return shared_state_enabled()


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
        # Intentional domain rollback must refuse success. Read-only cleanup uses
        # close(), whose real-connection implementation ends its own transaction.
        CURRENT.get()["rollback_requested"] = True


def store_key(key):
    # The saved personal filter stays with the authenticated user.
    unit = CURRENT.get()
    if key in ("criteria.default", "reports.snapshots") and unit:
        return key + ":" + unit.get("subject", "anonymous")
    return key


def restore(key, factory):
    unit = CURRENT.get()
    conn, saved_key = unit["conn"], store_key(key)
    if unit.get("capacity") and saved_key in business_records.PARTITIONED_STORES:
        value, found = business_records.load(conn, saved_key)
        if found:
            return value
        previous = unit.get("seeding")
        unit["seeding"] = True
        try:
            return factory()
        finally:
            if previous is None:
                unit.pop("seeding", None)
            else:
                unit["seeding"] = previous
    cached_key = None
    size = 0
    if os.environ.get("PROD_STORE_CACHE_ENABLED", "true") == "true" and getattr(conn, "engine", None):
        # The same repeatable-read snapshot supplies signature and payload. Row
        # versions plus count cover updates, insertions and deletions; the engine
        # identity prevents reuse across databases. Personal keys include subject.
        signature = conn.execute(text(
            "select count(*),coalesce(sum(version),0),max(updated_at),"
            "coalesce(sum(octet_length(payload::text)),0),min(schema_version),max(schema_version) "
            "from app.business_record where store_key=:k"),
            {"k": saved_key}).one()
        if signature[0]:
            if signature[4] != 1 or signature[5] != 1:
                raise ValueError("unsupported business record schema")
            cached_key = (conn.engine, saved_key, *signature[:3])
            size = int(signature[3])
            value, found = _STORE_TEMPLATES.get(cached_key)
            if found:
                unit["store_cache_hits"] = unit.get("store_cache_hits", 0) + 1
                return value
    value, found = business_records.load(conn, saved_key)
    if found and cached_key:
        _STORE_TEMPLATES.put(cached_key, value, size)
        unit["store_cache_misses"] = unit.get("store_cache_misses", 0) + 1
    # Factories depend on the current book/config/customer and are never cached.
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
        if unit.get("capacity") and unit.get("customer_uid"):
            # The portfolio version is a short commit fence, not a lock held
            # while decoding/recalculating this customer's entire response.
            unit["business_changed"] = True
            return True
        unit["version"] = unit["conn"].execute(text(
            "update app.business_version set version=version+1 where singleton=true returning version")).scalar_one()
    return changed


class ProductionUnitMiddleware:
    def __init__(self, app, enabled=enabled):
        self.app = app
        self.enabled = enabled
        readers = max(1, min(16, int(os.environ.get("PROD_READ_CONCURRENCY", "4"))))
        self.gate = _ReadWriteGate(readers)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.enabled() or not scope.get("path", "").startswith("/v1/"):
            return await self.app(scope, receive, send)
        if scope.get("path") == "/v1/auth/config":
            return await self.app(scope, receive, send)
        from . import auth
        if (auth.current_config().on and scope.get("path") not in auth.OPEN_PATHS
                and scope.get("path") not in auth.WEBHOOK_PATHS and scope.get("method") != "OPTIONS"
                and not scope.get("volt_resolved_auth")):
            token = (auth.bearer_token(scope) if auth.current_config().session_policy == "tab"
                     else auth._cookie(scope, auth.COOKIE))
            if not token or (auth.current_config().session_policy == "tab" and not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)):
                # Reject missing/malformed credentials before borrowing a business
                # connection or joining the global mutable-book queue.
                return await auth.auth_required().response()(scope, receive, send)
        try:
            receive = auth.bounded_receive(scope, receive)
        except errors.Problem as problem:
            return await problem.response()(scope, receive, send)
        queued = time.monotonic()
        # Controls only touch SQL operational state, never the mutable shared book.
        # Their independent request slot is cleaned without touching another slot.
        if independent_control(scope):
            return await self._request(scope, receive, send, queued, 0)
        scoped_customer = customer_scope(scope)
        projection_read = scope.get("method") in ("GET", "HEAD") and scope.get("path") in (
            "/v1/workbook", "/v1/today", "/v1/reports/monthly")
        if projection_read:
            result = await self._request(scope, receive, send, queued, 0, book_exclusive=False)
            if result is not _REFRESH_EXCLUSIVE:
                return result
            # Cold generation/old-schema publication uses the existing exclusive
            # retry; release the first snapshot before acquiring the book lease.
            scoped_customer = None
        # Customer edits own private request graphs. Their lease protects global
        # book publication only; it does not exclude other customer readers/writers.
        mode = "write" if projection_read else "read" if scope.get("method") in ("GET", "HEAD") or scoped_customer else "write"
        while True:
            try:
                with anyio.fail_after(float(os.environ.get("PROD_LOCK_WAIT_SECONDS", "15"))):
                    await self.gate.acquire(mode)
            except TimeoutError:
                print(json.dumps({"event": "production_lock_timeout", "wait_ms": round((time.monotonic() - queued) * 1000, 2)}), flush=True)
                return await self.problem("production_busy", 503).response()(scope, receive, send)
            try:
                result = await self._request(scope, receive, send, queued, time.monotonic() - queued,
                                             book_exclusive=mode == "write")
            finally:
                await self.gate.release(mode)
            if result is not _REFRESH_EXCLUSIVE:
                return result
            # A GET's first snapshot was discarded before touching domain state.
            # Retry once under the exclusive lease with a fresh SQL snapshot;
            # never upgrade while retaining a reader (which would deadlock).
            mode = "write"

    async def _request(self, scope, receive, send, started=None, lock_wait=0, book_exclusive=True):
        started = started if started is not None else time.monotonic()
        conn = transaction = None
        unit_token = session_token = touched_token = None
        read_token = memo_token = None
        book_marker = None
        refresh_retry = False
        slot = "prd-request:" + uuid.uuid4().hex
        messages = []
        async def capture(message): messages.append(message)
        try:
            conn = await run_in_threadpool(db.connect)
            transaction = await run_in_threadpool(conn.begin)
            await run_in_threadpool(conn.execute, text("set local lock_timeout='5s'"))
            await run_in_threadpool(conn.execute, text("set local statement_timeout='300s'"))
            mutation_request = scope.get("method") in ("POST", "PUT", "PATCH", "DELETE")
            control_request = independent_control(scope)
            if not mutation_request or control_request:
                await run_in_threadpool(conn.execute, text("set transaction isolation level repeatable read"))
            capacity = bool(await run_in_threadpool(lambda: conn.execute(text(
                "select to_regclass('app.projection_current') is not null and "
                "coalesce((select version from app.schema_version where singleton),0)>=3")).scalar_one()))
            scoped_customer = customer_scope(scope) if capacity else None
            if mutation_request and not control_request:
                if scoped_customer:
                    await run_in_threadpool(conn.execute, text("select pg_advisory_xact_lock_shared(:k)"), {"k": LOCK_KEY})
                    await run_in_threadpool(conn.execute, text("select pg_advisory_xact_lock(hashtextextended(:uid,0))"),
                                             {"uid": "volt-customer:" + scoped_customer})
                else:
                    await run_in_threadpool(conn.execute, text("select pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
            version = await run_in_threadpool(lambda: conn.execute(text(
                "select version from app.business_version where singleton=true")).scalar_one())
            from . import auth
            auth_session = await run_in_threadpool(auth.resolve_session, scope) if auth.current_config().on else None
            unit = {"conn": conn, "version": version, "subject": (auth_session or {}).get("sub", "anonymous"),
                    "capacity": capacity, "mutation": mutation_request, "book_exclusive": book_exclusive}
            if scoped_customer:
                unit["customer_uid"] = scoped_customer
                if mutation_request:
                    await run_in_threadpool(conn.execute, text("insert into app.customer_version(customer_uid) "
                        "values(:u) on conflict do nothing"), {"u": scoped_customer})
                unit["customer_version"] = await run_in_threadpool(lambda: conn.execute(text(
                    "select version from app.customer_version where customer_uid=:u"), {"u": scoped_customer}).scalar() or 0)
            unit_token = CURRENT.set(unit)
            session_token = session.CURRENT.set(slot)
            touched_token = session.TOUCHED.set(set())
            if not mutation_request or scoped_customer:
                # The legacy session middleware is bypassed in shared-state mode.
                # Preserve its request-scoped money memo and row indexes here;
                # otherwise a workbook rescans all invoices for every customer.
                from . import main, request_context
                memo_token = main._VIEW_MEMO.set({})
                read_token = request_context.begin_read()
            if (auth_session and not scope.get("volt_worker") and
                os.environ.get("PROD_GO_LIVE_ENABLED") != "true" and
                not scope["path"].startswith("/v1/auth/") and
                auth_session.get("role") not in ("OPS", "OWNER") and
                auth_session.get("sub") not in os.environ.get("PROD_CANDIDATE_TEST_SUBJECTS", "").split(",")):
                raise self.problem("production_maintenance", 503)
            if capacity and scoped_customer and (auth_session or not auth.current_config().on):
                from . import read_projection
                await run_in_threadpool(read_projection.current, conn)
                # A cold full generation seeded complete stores. Restore a fresh
                # customer slice for the route, never keep that full graph.
                for store in session.REGISTRY:
                    if store.key in business_records.PARTITIONED_STORES:
                        store._by_session.pop(slot, None)
                        (session.TOUCHED.get() or set()).discard(store)
                unit.pop("record_baselines", None)
                unit.pop("owner_baselines", None)
            projection_read = capacity and os.environ.get("VOLT_INDEXED_READS_ENABLED", "true") == "true" and not mutation_request and scope["path"] in (
                "/v1/workbook", "/v1/today", "/v1/reports/monthly")
            if auth_session and not projection_read and not control_request and not scope["path"].startswith(("/v1/auth/", "/v1/operation-runs/")):
                from .production_runtime import prepare_book
                await run_in_threadpool(prepare_book, exclusive=book_exclusive)
                from .production_runtime import book_marker as marker
                book_marker = marker()
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
                if not re.fullmatch(rb"[A-Za-z0-9_.:-]{1,200}", idem):
                    raise self.problem("invalid_idempotency_key", 422)
                chunks = []
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        raise RuntimeError("request disconnected")
                    chunks.append(message.get("body", b""))
                    if not message.get("more_body"): break
                body = b"".join(chunks)
                semantic_headers = [(name.decode("ascii"), headers.get(name, b"").decode("latin-1"))
                                    for name in (b"content-type", b"x-volt-filename", b"x-volt-upload", b"x-volt-attach-to")]
                fingerprint = hashlib.sha256(method.encode() + b"\0" + path.encode() + b"\0" +
                                             scope.get("query_string", b"") + b"\0" +
                                             json.dumps(semantic_headers, separators=(",", ":")).encode() + b"\0" + body).hexdigest()
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
                    # A replay is still an authenticated action. It must not bypass
                    # revocation, role changes or a changed case assignment.
                    if auth.current_config().on:
                        if not auth_session:
                            raise auth.auth_required()
                        from . import user_accounts, production_permissions
                        allowed = await run_in_threadpool(user_accounts.session_allowed,
                                                          auth_session, auth.current_config().allowlist, fresh=True)
                        if not allowed:
                            raise auth.session_withdrawn()
                        from . import officers
                        roster = officers.registry() if auth_session.get("can_switch") else []
                        role, officer = auth.effective_identity(auth_session, auth._header(scope, b"x-volt-role"),
                                                                auth._header(scope, b"x-volt-officer"), roster)
                        await run_in_threadpool(production_permissions.enforce, scope,
                                                dict(auth_session, role=role, officer=officer), body)
                    if cached.fingerprint != fingerprint:
                        raise self.problem("idempotency_conflict", 409)
                    await run_in_threadpool(transaction.rollback)
                    messages = [{"type": "http.response.start", "status": cached.status,
                                 "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in cached.headers]},
                                {"type": "http.response.body", "body": bytes(cached.body)}]
                    return await self.deliver(messages, scope, send)
            if (method in ("PUT", "PATCH", "DELETE") and not control_request and
                not path.startswith("/v1/auth/") and not scope.get("volt_worker") and
                os.environ.get("REQUIRE_STATE_VERSION") == "true" and not headers.get(b"if-match")):
                raise self.problem("state_version_required", 428)
            allowed_versions = (None, str(version).encode(), ('"%s"' % version).encode())
            if scoped_customer:
                token = case_token(scoped_customer, unit["customer_version"]).encode()
                allowed_versions += (token, b'"' + token + b'"')
            if mutation and headers.get(b"if-match") not in allowed_versions:
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
                if mutation and not control_request: await run_in_threadpool(flush)
                if mutation and not control_request and capacity and not path.startswith("/v1/auth/"):
                    from . import read_projection
                    await run_in_threadpool(read_projection.finish_write, conn)
                    if scoped_customer:
                        unit["customer_version"] = await run_in_threadpool(lambda: conn.execute(text(
                            "update app.customer_version set version=version+1 where customer_uid=:u returning version"),
                            {"u": scoped_customer}).scalar_one())
                if mutation and not control_request and not path.startswith("/v1/auth/") and unit["version"] == version:
                    numeric_match = headers.get(b"if-match", b"").strip(b'"')
                    conditional = bool(scoped_customer and re.fullmatch(rb"[0-9]+", numeric_match))
                    sql = "update app.business_version set version=version+1 where singleton=true"
                    if conditional:
                        sql += " and version=:expected"
                    committed_version = await run_in_threadpool(lambda: conn.execute(text(sql + " returning version"),
                        {"expected": int(numeric_match) if conditional else version}).scalar())
                    if committed_version is None:
                        raise self.problem("state_conflict", 409)
                    unit["version"] = committed_version
                start["headers"] = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"cache-control"] + [
                    (b"cache-control", b"no-store"), (b"x-volt-state-version", str(unit["version"]).encode())]
                if scoped_customer:
                    token = case_token(scoped_customer, unit["customer_version"]).encode()
                    start["headers"] += [(b"etag", b'"' + token + b'"'), (b"x-volt-case-version", token)]
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
            from .production_runtime import BookRefreshRequired
            if isinstance(exc, BookRefreshRequired):
                refresh_retry = True
                if transaction and transaction.is_active:
                    await run_in_threadpool(transaction.rollback)
                return _REFRESH_EXCLUSIVE
            print(json.dumps({"event": "production_refused", "cause": type(exc).__name__,
                              "sqlstate": getattr(getattr(exc, "orig", None), "sqlstate", None)}), flush=True)
            if transaction and transaction.is_active:
                await run_in_threadpool(transaction.rollback)
            # Error details can contain PII; the response and log contain no driver text.
            problem = exc if isinstance(exc, errors.Problem) else self.problem("production_write_unavailable", 503)
            messages = []
            await problem.response()(scope, receive, capture)
        finally:
            if book_marker is not None and not refresh_retry:
                from .production_runtime import book_marker as marker, invalidate_book
                failed = next((m["status"] for m in messages if m["type"] == "http.response.start"), 503) >= 400
                if failed and marker() != book_marker:
                    invalidate_book()
            if read_token is not None:
                from . import request_context
                request_context.end_read(read_token)
            if memo_token is not None:
                from . import main
                main._VIEW_MEMO.reset(memo_token)
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
                print(json.dumps({"event": "production_book_refresh_retry" if refresh_retry else "production_request", "route": route or "unmatched",
                                  "method": scope.get("method"),
                                  "status": next((m["status"] for m in messages if m["type"] == "http.response.start"), 503),
                                  "lock_wait_ms": round(lock_wait * 1000, 2),
                                  "store_cache_hits": unit.get("store_cache_hits", 0) if unit_token is not None else 0,
                                  "store_cache_misses": unit.get("store_cache_misses", 0) if unit_token is not None else 0,
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
