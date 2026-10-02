"""Shared, durable service deferrals. Postgres in deployment; SQLite locally.

The lock covers re-reading the preview inputs and saving, not just the INSERT.
Never fall back to local storage when a configured database is unavailable.
"""
import json
import os
import sqlite3
from contextlib import contextmanager, nullcontext
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import db, errors, request_context

LOCK_KEY = 0x564F4C54444546


def unavailable():
    return errors.Problem("service_deferral_store_unavailable", 503,
                          "Service deferrals are unavailable", "Durable storage did not answer",
                          "อ่านหรือบันทึกการเลื่อนงวดไม่ได้ กรุณาลองใหม่", "DEBT-DEF-0503", retryable=True)


def local_path():
    return Path(os.environ.get("VOLT_SERVICE_DEFERRALS_PATH") or
                Path(__file__).resolve().parents[1] / "var" / "service-deferrals.sqlite3")


def invalidate():
    cache = request_context.reads()
    if cache is not None:
        cache.pop("service_deferrals.rows", None)


def read():
    cache = request_context.reads()
    if cache is not None and "service_deferrals.rows" in cache:
        return cache["service_deferrals.rows"]
    try:
        if db.configured():
            conn = db.connect()
            try:
                with conn.begin() if not conn.in_transaction() else nullcontext():
                    rows = [r[0] for r in conn.execute(text(
                        "select payload from records.service_deferral order by uid"))]
            finally:
                conn.close()
        elif not local_path().exists():
            rows = []
        else:
            with sqlite3.connect(str(local_path()), timeout=10) as conn:
                rows = [json.loads(r[0]) for r in conn.execute(
                    "select payload from service_deferral order by uid")]
    except (db.DatabaseUnreachable, SQLAlchemyError, sqlite3.Error, OSError, ValueError):
        raise unavailable() from None
    if cache is not None:
        cache["service_deferrals.rows"] = rows
    return rows


@contextmanager
def transaction():
    """Yield current records and an atomic writer under a cross-process lock."""
    conn = None
    try:
        if db.configured():
            conn = db.connect()
            with conn.begin():
                conn.execute(text("select pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
                rows = [r[0] for r in conn.execute(text(
                    "select payload from records.service_deferral order by uid"))]

                def save(row):
                    conn.execute(text(
                        "insert into records.service_deferral(uid, payload) values (:u, cast(:p as jsonb)) "
                        "on conflict (uid) do update set payload=excluded.payload"),
                        {"u": row["uid"], "p": json.dumps(row, ensure_ascii=False)})
                yield rows, save
        else:
            path = local_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), timeout=10)
            conn.execute("create table if not exists service_deferral (uid text primary key, payload text not null)")
            conn.execute("begin immediate")
            rows = [json.loads(r[0]) for r in conn.execute("select payload from service_deferral order by uid")]

            def save(row):
                conn.execute("insert into service_deferral values (?, ?) on conflict(uid) "
                             "do update set payload=excluded.payload", (row["uid"], json.dumps(row, ensure_ascii=False)))
            try:
                yield rows, save
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
    except (db.DatabaseUnreachable, SQLAlchemyError, sqlite3.Error, OSError):
        raise unavailable() from None
    finally:
        if conn is not None:
            conn.close()
        invalidate()
