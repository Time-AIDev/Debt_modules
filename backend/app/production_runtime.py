"""Production startup and readiness fail closed, without printing configuration."""
import os
from sqlalchemy import text
from . import db


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
            return conn.execute(text("select version from app.schema_version where singleton=true")).scalar_one() == 1
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
    import_sync._seen.for_current()
    import_sync.ensure_current()
