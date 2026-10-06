"""Production startup and readiness fail closed, without printing configuration."""
import os
import time
from sqlalchemy import text
from . import db
from .runtime_policy import SCHEMA_VERSION, shared_state_enabled

_BOOK_INVALID = False


class BookRefreshRequired(Exception):
    """The request must release its reader lease and retry under an exclusive one."""


def book_marker():
    from . import book, import_sync, main
    return (import_sync._book_epoch["value"], book._VERSION,
            id(main.CUSTOMERS), id(main.BY_CUSTOMER), id(main.BY_CONTRACT))


def invalidate_book():
    """A rolled-back import may have rebound globals from uncommitted landing rows."""
    global _BOOK_INVALID
    _BOOK_INVALID = True


def _snapshot_epoch():
    from .production_unit import CURRENT
    unit = CURRENT.get()
    if unit is not None:
        return int(unit["conn"].execute(text("select coalesce(max(id),0) from app.data_epoch")).scalar_one())
    with db.connect() as conn:
        return int(conn.execute(text("select coalesce(max(id),0) from app.data_epoch")).scalar_one())


def validate_environment(environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("ENV") != "prd": return
    for key in ("DATABASE_URL", "GOOGLE_CLIENT_ID"):
        if not environ.get(key): raise RuntimeError("Production requires " + key)
    for key, expected in (("AUTH_MODE", "on"), ("AUTH_SESSION_POLICY", "tab"),
                          ("AUTH_ALLOW_TEST_ACCOUNTS", "false"), ("PEAK_OUTBOUND_ENABLED", "false")):
        if environ.get(key) != expected:
            raise RuntimeError("Production requires " + key + "=" + expected)
    if environ.get("VOLT_BUSINESS_DATE"):
        raise RuntimeError("Production refuses VOLT_BUSINESS_DATE")


def readiness():
    try:
        if not db.configured(): return False
        with db.connect() as conn, conn.begin():
            conn.execute(text("set local statement_timeout='1500ms'"))
            if conn.execute(text("select version from app.schema_version where singleton=true")).scalar_one() != SCHEMA_VERSION:
                return False
            if os.environ.get("REQUIRE_DEPENDENCY_READINESS") == "true":
                heartbeat = conn.execute(text(
                    "select state, extract(epoch from now()-last_seen_at), "
                    "extract(epoch from now()-job_started_at) from app.worker_heartbeat where name='local'"
                )).first()
                if heartbeat is None: return False
                idle_age = float(heartbeat[1])
                job_age = float(heartbeat[2] or 0)
                max_age = int(os.environ.get("WORKER_HEARTBEAT_MAX_AGE_SECONDS", "30"))
                max_job_age = int(os.environ.get("JOB_EXECUTION_TIMEOUT_SECONDS", "300"))
                if heartbeat[0] in ("working", "maintenance"):
                    if job_age > max_job_age: return False
                elif idle_age > max_age: return False
                from .attachments.scanner import configured
                if not configured(): return False
                host = os.environ.get("CLAMAV_HOST")
                if host:
                    import socket
                    with socket.create_connection((host, int(os.environ.get("CLAMAV_PORT", "3310"))), timeout=0.5) as scanner:
                        scanner.sendall(b"zPING\0")
                        if scanner.recv(32).rstrip(b"\0\n") != b"PONG": return False
                elif os.environ.get("SCANNER_URL"):
                    import requests
                    from .attachments.scanner import identity_token
                    audience = os.environ["SCANNER_URL"].rstrip("/")
                    if requests.get(audience + "/livez", timeout=0.5,
                                    headers={"Authorization": "Bearer " + identity_token(audience)}).status_code != 200:
                        return False
            return True
    except Exception:
        return False


def prepare_book(exclusive=True):
    """Book and request state use the same SQL snapshot; rebinds require exclusivity.

    A worker may commit an import while older reader snapshots are still running.
    Those readers finish against their old book. The first new-epoch reader
    releases its lease and retries under the writer lease before rebuilding.
    """
    global _BOOK_INVALID
    from . import book, data_epoch, import_sync, main
    from . import errors
    epoch = _snapshot_epoch()
    cached_epoch = import_sync._book_epoch["value"]
    cached = book._CACHE.get((None, book._VERSION))
    from_landing = bool(cached and (cached[1].get("source") or {}).get("origin") == "LANDING")
    if not _BOOK_INVALID and cached_epoch > epoch:
        # Never replace a newer committed process book with an older SQL snapshot.
        raise errors.Problem("production_snapshot_stale", 503, "Snapshot changed",
                             "Retry against a fresh database snapshot.",
                             "ข้อมูลเปลี่ยนระหว่างอ่าน กรุณาลองใหม่", "DEBT-PRD-503", retryable=True)
    if _BOOK_INVALID or not from_landing or cached_epoch != epoch:
        if not exclusive:
            raise BookRefreshRequired()
        book.invalidate(reads=True)
        # Force refresh also for an empty database (epoch zero).
        import_sync._book_epoch["value"] = -1
        main.reload_book()
        _BOOK_INVALID = False
    # Legacy staging helpers may use the short epoch cache. Seed it from THIS
    # authoritative snapshot before session healing; production rechecks SQL.
    data_epoch._cache.update(value=epoch, at=time.monotonic())
    import_sync.ensure_current()


def warm_projections():
    """Complete indexed state before readiness/traffic, with no auth impersonation.

    The system owns a durable transaction under the same global writer barrier
    as imports. Only seed/projection state is initialized; source/financial facts
    are neither imported nor reconciled here.
    """
    if not db.configured() or not shared_state_enabled():
        return False
    from . import main, read_projection, request_context, session
    from .production_unit import CURRENT, LOCK_KEY
    import uuid
    with db.connect() as conn, conn.begin():
        version = conn.execute(text("select version from app.schema_version where singleton")).scalar_one()
        if version < 3:
            return False
        conn.execute(text("select pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
        unit = {"conn": conn, "capacity": True, "mutation": False, "seeding": True,
                "subject": "system-projection", "version": conn.execute(text(
                    "select version from app.business_version where singleton")).scalar_one()}
        slot = "projection-startup:" + uuid.uuid4().hex
        tokens = (CURRENT.set(unit), session.CURRENT.set(slot), session.TOUCHED.set(set()),
                  main._VIEW_MEMO.set({}), request_context.begin_read())
        try:
            read_projection.current(conn)
        finally:
            for store in session.REGISTRY:
                store._by_session.pop(slot, None)
                store._written.pop(slot, None)
            request_context.end_read(tokens[4])
            main._VIEW_MEMO.reset(tokens[3])
            session.TOUCHED.reset(tokens[2])
            session.CURRENT.reset(tokens[1])
            CURRENT.reset(tokens[0])
    return True
