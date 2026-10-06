"""Append-only invoice decisions, independent of replaceable import/session data."""
import json
import os
import sqlite3
from contextlib import contextmanager, nullcontext
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from . import db, errors, request_context

LOCK_KEY = 0x564F4C54495652


def unavailable():
    return errors.Problem("invoice_review_store_unavailable", 503, "Invoice review unavailable",
                          "Durable storage did not answer", "บันทึกการรับรองใบแจ้งหนี้ไม่ได้ กรุณาลองใหม่",
                          "DEBT-IVR-0503", retryable=True)


def local_path():
    return Path(os.environ.get("VOLT_INVOICE_REVIEWS_PATH") or
                Path(__file__).resolve().parents[1] / "var" / "invoice-reviews.sqlite3")


def invalidate():
    cache = request_context.reads()
    if cache is not None:
        cache.pop("invoice_reviews.rows", None)
        cache.pop("invoice_reviews.decisions", None)


def read():
    cache = request_context.reads()
    if cache is not None and "invoice_reviews.rows" in cache:
        return cache["invoice_reviews.rows"]
    try:
        if db.configured():
            conn = db.connect()
            try:
                with conn.begin() if not conn.in_transaction() else nullcontext():
                    rows = [r[0] for r in conn.execute(text(
                        "select payload from records.invoice_review order by sequence"))]
            finally:
                conn.close()
        elif not local_path().exists():
            rows = []
        else:
            with sqlite3.connect(str(local_path()), timeout=10) as conn:
                rows = [json.loads(r[0]) for r in conn.execute(
                    "select payload from invoice_review order by sequence")]
    except (db.DatabaseUnreachable, SQLAlchemyError, sqlite3.Error, OSError, ValueError):
        raise unavailable() from None
    if cache is not None:
        cache["invoice_reviews.rows"] = rows
    return rows


@contextmanager
def transaction():
    conn = None
    try:
        if db.configured():
            conn = db.connect()
            with conn.begin():
                conn.execute(text("select pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
                rows = [r[0] for r in conn.execute(text(
                    "select payload from records.invoice_review order by sequence"))]

                def save(row):
                    conn.execute(text("insert into records.invoice_review(uid,payload) values (:u,cast(:p as jsonb))"),
                                 {"u": row["uid"], "p": json.dumps(row, ensure_ascii=False)})
                yield rows, save
        else:
            path = local_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), timeout=10)
            conn.execute("create table if not exists invoice_review "
                         "(sequence integer primary key autoincrement, uid text unique not null, payload text not null)")
            conn.execute("begin immediate")
            rows = [json.loads(r[0]) for r in conn.execute("select payload from invoice_review order by sequence")]

            def save(row):
                conn.execute("insert into invoice_review(uid,payload) values (?,?)",
                             (row["uid"], json.dumps(row, ensure_ascii=False)))
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
