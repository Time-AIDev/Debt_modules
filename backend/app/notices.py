"""Personal notices on the calendar — vault note 10 §3 WP6 (F16).

records.notice when a database is configured; a process dict labelled not-durable when
it is not — the attachments store's own seam (attachments/store.py). A notice belongs
to ONE owner: the acting identity (X-Volt-Officer, which the login middleware rewrites
to the session's own identity when AUTH_MODE is on). Nobody else reads, edits or
deletes it, a Manager included: F16 rules out sharing. Title and text are the owner's
words and never go into an audit row or a log.

SQL error handling follows B10a's pattern (user_accounts.py's `_transaction()` /
`_connect()`): no driver exception ever leaves here, because its text can quote a
bound value — a notice's title or text. A connection lost mid-query is the same
retryable 503 as one that never opened; anything else becomes an opaque Problem,
raised `from None`. db.engine() also hides bound parameters from every statement
error (db.py, hide_parameters=True).
"""
import hashlib
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError, SQLAlchemyError

from . import db, errors, journey
from .config import settings

NOT_DURABLE_EN = "No database — this note is held in memory and is lost on restart"
NOT_DURABLE_TH = "ไม่มีฐานข้อมูล — โน้ตนี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
FIELDS = ("title", "on", "time", "customer_uid", "text", "done")
COLUMNS = {"title": "title", "on": "on_date", "time": "at_time", "customer_uid": "customer_uid",
           "text": "note_text", "done": "done"}
SELECT = "uid, owner, title, on_date, at_time, customer_uid, note_text, done, created_at, updated_at"
TITLE_MAX, TEXT_MAX = 120, 2000
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
UID_RE = re.compile(r"^ntc-[0-9a-f]{12}$")
# Fix round 1 / I1: a NUL, and a lone surrogate (U+D800-U+DFFF — what a string cut mid
# emoji decodes to from JSON, since json.loads does not require surrogates to pair) —
# not a literal string, so \x00 and \ud800-\udfff are Python escapes decoded once here,
# not regex escapes re-interpreted by the engine.
DANGEROUS_RE = re.compile("[\x00\ud800-\udfff]")

_MEMORY = {}


class NoticeRefused(Exception):
    def __init__(self, code, pointer, message, message_th):
        super().__init__(message)
        self.code = code
        self.pointer = pointer
        self.message = message
        self.message_th = message_th

    def error(self):
        return {"pointer": self.pointer, "code": self.code, "message": self.message, "message_th": self.message_th}


def reset():
    _MEMORY.clear()


def new_uid():
    return "ntc-" + uuid.uuid4().hex[:12]


def uid_for(*parts):
    """A uid derived from what the notice is about, in the same shape as new_uid(), so
    writing it again is a no-op (create() skips a uid that exists). Fix-all F2: every
    healing session runs the early-payment scan, and one officer gets one notice."""
    return "ntc-" + hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def looks_like_uid(uid):
    """Fix round 1 / M3: a path segment that does not match the shape this module
    itself generates is never a real notice — worth refusing before it is quoted
    anywhere, the audit log included."""
    return bool(UID_RE.match(uid or ""))


def _pointer(key):
    """RFC 6901 (fix round 1 / M2): '~' before '/', so a key carrying either is never
    misread as a path separator by a reader that un-escapes the pointer."""
    return "/" + str(key).replace("~", "~0").replace("/", "~1")


def _on(raw):
    value = str(raw or "")
    try:
        if len(value) != 10:
            raise ValueError(value)
        day = date.fromisoformat(value)
    except ValueError:
        raise NoticeRefused("date_invalid", "/on", "on must be a date (yyyy-mm-dd)",
                            "วันที่ของโน้ตไม่ถูกต้อง ใช้รูปแบบ ปี-เดือน-วัน")
    if abs(day.year - settings.business_date.year) > 2:
        raise NoticeRefused("date_invalid", "/on", "on is not within two years of the business date",
                            "วันที่ของโน้ตต้องอยู่ภายในสองปีจากวันทำการ")
    return day.isoformat()


def clean(body, partial):
    """The fields a notice may carry, checked. An unknown field is refused, never
    dropped. Fix round 1 / M1: no refusal echoes a submitted value — the pointer alone
    identifies the field."""
    body = body or {}
    unknown = sorted(key for key in body if key not in FIELDS and key != "by")
    if unknown:
        raise NoticeRefused("field_unknown", _pointer(unknown[0]), "an unknown field was given",
                            "มีชื่อช่องข้อมูลที่ไม่รู้จัก")
    # I1: a NUL or a lone surrogate in ANY string field is refused here, before it is
    # ever a bound parameter — Postgres refuses a NUL on its own (DataError), but a lone
    # surrogate raises a raw UnicodeEncodeError past that, and the memory store accepts
    # either and then fails later, at render time, on every read. Checked before the
    # per-field parsing below so it always wins over a more specific code.
    for key in FIELDS:
        if key == "done" or key not in body:
            continue
        value = body.get(key)
        if isinstance(value, str) and DANGEROUS_RE.search(value):
            raise NoticeRefused("text_invalid", _pointer(key),
                                "text carries a character that cannot be stored",
                                "มีอักขระที่บันทึกไม่ได้ในข้อความ")
    out = {}
    if not partial or "title" in body:
        title = str(body.get("title") or "").strip()
        if not title:
            raise NoticeRefused("required", "/title", "a notice needs a title", "ต้องใส่หัวข้อโน้ต")
        if len(title) > TITLE_MAX:
            raise NoticeRefused("too_long", "/title", "title is at most %d characters" % TITLE_MAX,
                                "หัวข้อยาวได้ไม่เกิน %d ตัวอักษร" % TITLE_MAX)
        out["title"] = title
    if not partial or "on" in body:
        out["on"] = _on(body.get("on"))
    if "time" in body:
        raw = body.get("time")
        if raw in (None, ""):
            out["time"] = None
        elif not TIME_RE.match(str(raw)):
            raise NoticeRefused("time_invalid", "/time", "time is HH:MM, 00:00 to 23:59",
                                "เวลาไม่ถูกต้อง ใช้รูปแบบ ชั่วโมง:นาที")
        else:
            out["time"] = str(raw)
    if "customer_uid" in body:
        raw = body.get("customer_uid")
        if raw in (None, ""):
            out["customer_uid"] = None
        elif journey.customer_by_uid(str(raw)) is None:
            raise NoticeRefused("customer_unknown", "/customer_uid", "no customer matches the given id",
                                "ไม่พบลูกค้าที่ระบุ")
        else:
            out["customer_uid"] = str(raw)
    if "text" in body:
        value = str(body.get("text") or "").strip()
        if len(value) > TEXT_MAX:
            raise NoticeRefused("too_long", "/text", "text is at most %d characters" % TEXT_MAX,
                                "รายละเอียดยาวได้ไม่เกิน %d ตัวอักษร" % TEXT_MAX)
        out["text"] = value or None
    if "done" in body:
        if not isinstance(body.get("done"), bool):
            raise NoticeRefused("done_invalid", "/done", "done is true or false", "สถานะเสร็จต้องเป็น true หรือ false")
        out["done"] = body["done"]
    return out


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _public(row, durable):
    at_time = row.get("at_time")
    rec = {"uid": row["uid"], "owner": row["owner"], "title": row["title"], "on": _iso(row["on_date"]),
           "time": at_time.strftime("%H:%M") if hasattr(at_time, "strftime") else at_time,
           "customer_uid": row.get("customer_uid"), "text": row.get("note_text"), "done": bool(row.get("done")),
           "created_at": _iso(row.get("created_at")), "updated_at": _iso(row.get("updated_at")),
           "durable": durable}
    if not durable:
        rec["note_th"] = NOT_DURABLE_TH
        rec["note_en"] = NOT_DURABLE_EN
    return rec


def _bind(columns):
    """Date and time as Python objects for the driver; strings stay in the memory store."""
    out = dict(columns)
    if out.get("on_date"):
        out["on_date"] = date.fromisoformat(out["on_date"])
    if out.get("at_time"):
        out["at_time"] = datetime.strptime(out["at_time"], "%H:%M").time()
    return out


# --- the durable store, B10a's error-handling pattern (user_accounts.py) --------------

def store_unreachable():
    return errors.Problem(
        code="notice_store_unreachable", status=503, title="Notices cannot be read or saved",
        detail="A database is configured and did not answer.",
        message_th="บันทึกโน้ตไม่ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง",
        error_id="DEBT-CAL-0503", retryable=True)


def _connect():
    try:
        return db.connect()
    except db.DatabaseUnreachable:
        raise store_unreachable() from None


def _connection_lost(exc):
    return (isinstance(exc, (OperationalError, InterfaceError, DisconnectionError))
            or bool(getattr(exc, "connection_invalidated", False)))


@contextmanager
def _transaction():
    """One connection, closed either way, and no driver exception ever leaves it: its
    text can quote a bound value — a notice's title or text — so each becomes an
    opaque Problem raised `from None`. A connection lost after it opened (killed
    mid-query) is the same retryable 503 as one that never opened; anything else
    (DataError, ProgrammingError, ...) is internal_error, never the title or text.

    Fix round 1 / I1 backstop: `clean()` already refuses a NUL or a lone surrogate
    before it is ever bound, but a `UnicodeEncodeError` the driver itself raises (a
    lone surrogate reaching psycopg's UTF-8 encode) is a `UnicodeError`/`ValueError`,
    never a `SQLAlchemyError` — so it is caught here too, same answer, same reason.
    """
    conn = _connect()
    try:
        with conn.begin():
            yield conn
    except (SQLAlchemyError, UnicodeError) as exc:
        if _connection_lost(exc):
            raise store_unreachable() from None
        raise errors.internal_error() from None
    finally:
        try:
            conn.close()
        except SQLAlchemyError:
            pass          # a dead connection's close; the answer above already stands


def _run(sql, params):
    with _transaction() as conn:
        return conn.execute(text(sql), params).mappings().all()


def create(owner, fields, uid):
    """The new notice, or None when `uid` already exists (deleted included) — a
    uid_for() notice is written once, whoever writes it again."""
    now = datetime.now(timezone.utc)
    row = {"uid": uid, "owner": owner, "title": fields["title"], "on_date": fields["on"],
           "at_time": fields.get("time"), "customer_uid": fields.get("customer_uid"),
           "note_text": fields.get("text"), "done": bool(fields.get("done", False)),
           "created_at": now, "updated_at": now, "deleted_at": None, "deleted_by": None}
    if not db.configured():
        if uid in _MEMORY:
            return None
        _MEMORY[uid] = row
        return _public(row, durable=False)
    got = _run("insert into records.notice (uid, owner, title, on_date, at_time, customer_uid, note_text, done) "
               "values (:uid, :owner, :title, :on_date, :at_time, :customer_uid, :note_text, :done) "
               "on conflict (uid) do nothing returning " + SELECT, _bind(row))
    return _public(dict(got[0]), durable=True) if got else None


def list_for(owner, start, end):
    """The owner's notices dated start..end (inclusive). Another owner's are never read."""
    if not owner:
        return []
    if not db.configured():
        rows = [r for r in _MEMORY.values() if r["owner"] == owner and r["deleted_at"] is None
                and start.isoformat() <= r["on_date"] <= end.isoformat()]
        rows.sort(key=lambda r: (r["on_date"], r["at_time"] or "", r["uid"]))
        return [_public(r, durable=False) for r in rows]
    rows = _run("select " + SELECT + " from records.notice where owner = :owner and deleted_at is null "
                "and on_date between :start and :end order by on_date, at_time nulls first, uid",
                {"owner": owner, "start": start, "end": end})
    return [_public(dict(r), durable=True) for r in rows]


def _mine(owner, uid):
    row = _MEMORY.get(uid)
    return row if row is not None and row["owner"] == owner and row["deleted_at"] is None else None


def update(owner, uid, fields):
    columns = {COLUMNS[field]: value for field, value in fields.items()}
    if not db.configured():
        row = _mine(owner, uid)
        if row is None:
            return None
        row.update(columns)
        row["updated_at"] = datetime.now(timezone.utc)
        return _public(row, durable=False)
    sets = ", ".join("%s = :%s" % (column, column) for column in columns)   # names from COLUMNS only
    got = _run("update records.notice set " + sets + ", updated_at = now() "
               "where uid = :uid and owner = :owner and deleted_at is null returning " + SELECT,
               dict(_bind(columns), uid=uid, owner=owner))
    return _public(dict(got[0]), durable=True) if got else None


def delete(owner, uid):
    if not db.configured():
        row = _mine(owner, uid)
        if row is None:
            return None
        row["deleted_at"], row["deleted_by"] = datetime.now(timezone.utc), owner
        return _public(row, durable=False)
    got = _run("update records.notice set deleted_at = now(), deleted_by = :owner "
               "where uid = :uid and owner = :owner and deleted_at is null returning " + SELECT,
               {"uid": uid, "owner": owner})
    return _public(dict(got[0]), durable=True) if got else None
