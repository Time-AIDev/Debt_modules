"""A manager's manual payment status, shared by every session (Arina, 2026-09-24).

A person's change used to live only in the acting session's case store, so a second
manager in another browser kept reading the system's answer. It lives here once now:
records.payment_status_override when a database is configured (one active row per
customer; who, when and why kept; retired, never deleted), a process dict when not.

cases.for_current() re-applies the active rows to a session whenever version() moved
since that session last applied them. Nothing here bumps the data epoch, so setting a
status never makes every session run an import heal.
"""
import threading
import time
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from . import clock, db, errors

_MEMORY = {}                         # customer_uid -> the active row (no database)
_COUNTER = {"value": 0}              # moves on every set and retire (no database)
# No database: one lock over the dict and the counter, so a reader never sees the
# counter move before the row is there, nor the dict change under its loop.
_LOCK = threading.Lock()
_TTL_SECONDS = 1.0                   # data_epoch.current()'s cache, same shape
# "Read again now" is -inf, never 0.0: time.monotonic() may start near zero in a fresh
# process, and 0.0 would then look fresh for that process's whole first second.
_EXPIRED = float("-inf")
_cache = {"at": _EXPIRED, "value": None}


def _unreachable():
    return errors.Problem(
        code="payment_status_store_unreachable", status=503,
        title="The manual payment status cannot be read or saved right now",
        detail="A database is configured and did not answer.",
        message_th="บันทึกสถานะการชำระด้วยมือไม่ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง",
        error_id="DEBT-COL-0503", retryable=True)


def _changed_elsewhere():
    return errors.Problem(
        code="payment_status_changed_elsewhere", status=409,
        title="Someone else changed this payment status at the same moment",
        detail="Another change for this customer was saved first. Reload the case and try again.",
        message_th="มีผู้อื่นเปลี่ยนสถานะการชำระของลูกค้ารายนี้พร้อมกัน กรุณาโหลดเคสใหม่แล้วลองอีกครั้ง",
        error_id="DEBT-COL-0411")


@contextmanager
def _transaction():
    """One connection, one transaction, closed either way. Two sets for one customer at
    once meet the unique active index: the loser is the 409, not an outage. Any other
    driver error is the retryable 503 (the engine hides bound values; nothing chained)."""
    try:
        conn = db.connect()
    except db.DatabaseUnreachable:
        raise _unreachable() from None
    try:
        with conn.begin():
            yield conn
    except IntegrityError:
        raise _changed_elsewhere() from None
    except SQLAlchemyError:
        raise _unreachable() from None
    finally:
        conn.close()


def _now():
    """The app's one clock (Bangkok wall time when the date is live), so a row's date is
    the business day its events are counted on."""
    return clock.business_now().replace(tzinfo=clock.BANGKOK)


def _retire(conn, customer_uid, by, at):
    row = conn.execute(text(
        "update records.payment_status_override set retired_at = :at, retired_by = :by "
        "where customer_uid = :c and retired_at is null returning *"),
        {"c": customer_uid, "by": by, "at": at}).mappings().first()
    return dict(row) if row else None


def set(customer_uid, code, system_code, reason, by):     # the module's verb; shadows the builtin here only
    """The customer's one active override; the one it replaces is retired first."""
    at = _now()
    if not db.configured():
        with _LOCK:
            uid = _COUNTER["value"] + 1
            _MEMORY[customer_uid] = {
                "uid": uid, "customer_uid": customer_uid, "code": code,
                "system_code_at_set": system_code, "reason": reason, "set_by": by,
                "set_at": at, "retired_at": None, "retired_by": None}
            _COUNTER["value"] = uid     # only once the row is there
            return dict(_MEMORY[customer_uid])
    with _transaction() as conn:
        _retire(conn, customer_uid, by, at)
        row = conn.execute(text(
            "insert into records.payment_status_override "
            "(customer_uid, code, system_code_at_set, reason, set_by, set_at) "
            "values (:c, :code, :system, :reason, :by, :at) returning *"),
            {"c": customer_uid, "code": code, "system": system_code,
             "reason": reason, "by": by, "at": at}).mappings().one()
    _cache["at"] = _EXPIRED             # this process reads the new version at once
    return dict(row)


def retire(customer_uid, by):
    """Ends the customer's active override. The retired row, or None if none stood."""
    at = _now()
    if not db.configured():
        with _LOCK:
            row = _MEMORY.pop(customer_uid, None)
            if row is None:
                return None
            _COUNTER["value"] += 1
        return dict(row, retired_at=at, retired_by=by)
    with _transaction() as conn:
        row = _retire(conn, customer_uid, by, at)
    _cache["at"] = _EXPIRED
    return row


def active():
    """{customer_uid: row} of every active override, or None when the read failed —
    the caller applies nothing and asks again on its next call."""
    if not db.configured():
        with _LOCK:
            return {uid: dict(row) for uid, row in _MEMORY.items()}
    try:
        with _transaction() as conn:
            rows = conn.execute(text(
                "select * from records.payment_status_override where retired_at is null")).mappings().all()
    except errors.Problem:
        return None
    return {r["customer_uid"]: dict(r) for r in rows}


def version():
    """What moves whenever an override is set or retired: the in-process counter, or
    with a database (count(*), count(retired_at)) — rows are never deleted, so both
    only grow, whatever order transactions commit in. Cached for a second so a request
    burst pays one query; a failed read serves the cached value (an override shows a
    moment late, never wrongly)."""
    if not db.configured():
        return _COUNTER["value"]
    now = time.monotonic()
    if now - _cache["at"] < _TTL_SECONDS:
        return _cache["value"]
    try:
        with _transaction() as conn:
            value = tuple(conn.execute(text(
                "select count(*), count(retired_at) from records.payment_status_override")).one())
    except errors.Problem:
        return _cache["value"]
    _cache["at"], _cache["value"] = now, value
    return value


def reset():
    """Test seam: the memory rows, the counter and the cached version."""
    with _LOCK:
        _MEMORY.clear()
        _COUNTER["value"] = 0
    _cache["at"], _cache["value"] = _EXPIRED, None
