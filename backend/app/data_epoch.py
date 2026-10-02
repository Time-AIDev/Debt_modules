"""The import epoch: a monotone counter of acts that changed the imported facts.

Every landing run and every PEAK apply inserts one row (see app/refresh.py). A
session stores the highest id it has seeded from; the per-request check in
app/import_sync.py heals the session when the global value moved. Without this,
a tester who did not press Apply kept a book from before the import until their
process-restored state was reset by hand (sync audit, 2026-09-20).

No database — the fixtures this prototype falls back to never change — so the
epoch is 0 and no session ever needs healing.
"""
import time
import os

from . import db

_TTL_SECONDS = 1.0
_cache = {"at": float("-inf"), "value": 0}   # -inf: a fresh process always reads the table


def bump(kind, run_id=None):
    """Records one change and returns the new epoch. Raises on failure: a sync that
    cannot say it happened is a finding, not a detail (the caller reports it)."""
    if not db.configured():
        return 0
    from sqlalchemy import text
    conn = db.connect()
    try:
        with conn.begin():
            value = conn.execute(text(
                "insert into app.data_epoch (kind, run_id) values (:k, :r) returning id"),
                {"k": kind, "r": run_id}).scalar()
    finally:
        conn.close()
    _cache["value"] = int(value)
    _cache["at"] = time.monotonic()
    return int(value)


def current():
    """The newest epoch, cached for a second so a request burst pays one query. A
    failed read falls back to the cached value — serving a slightly older epoch
    delays a heal, it never invents one."""
    if not db.configured():
        return 0
    now = time.monotonic()
    production = os.environ.get("ENV") == "prd"
    if not production and now - _cache["at"] < _TTL_SECONDS:
        return _cache["value"]
    from sqlalchemy import text
    try:
        conn = db.connect()
    except Exception:                                  # noqa: BLE001 — fall back to the cache
        if production: raise
        return _cache["value"]
    try:
        if conn.in_transaction():
            conn.rollback()
        with conn.begin():
            value = conn.execute(text(
                "select coalesce(max(id), 0) from app.data_epoch")).scalar()
    except Exception:                                  # noqa: BLE001 — the table may not exist yet
        if production: raise
        return _cache["value"]
    finally:
        conn.close()
    # max(): epochs only grow; a read that started before a bump must not write an
    # older value back over the bump's (fix-all F audit — reload_book would skip).
    _cache["value"] = int(value or 0) if production else max(_cache["value"], int(value or 0))
    _cache["at"] = now
    return _cache["value"]


def reset_cache():
    """Test seam: forget the cached value so the next current() reads the table."""
    _cache["at"] = float("-inf")
    _cache["value"] = 0
