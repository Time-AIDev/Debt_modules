"""Production startup and readiness fail closed, without printing configuration."""
import os
from sqlalchemy import text
from . import db
from .runtime_policy import SCHEMA_VERSION, shared_state_enabled


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


def prepare_book():
    """Check PostgreSQL's import version before trusting a process read cache."""
    from . import book, data_epoch, import_sync, main
    epoch = data_epoch.current()
    if not book.from_landing() or import_sync._book_epoch["value"] != epoch:
        book.invalidate()
        # Force refresh also for an empty database (epoch zero).
        import_sync._book_epoch["value"] = -1
        main.reload_book()
    import_sync.ensure_current()
