"""Attachment metadata plus integrity-checked private bytes.

Production stores clean bytes in immutable private filesystem/GCS objects. Local
database mode uses records.attachment; without a DB files are explicitly volatile.
Private bytes and their contents never appear in a log line.
"""
import uuid
import hashlib
from datetime import datetime, timezone

from sqlalchemy import text

from .. import db


def _verified(row, raw):
    if len(raw) != row["size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
        from ..errors import Problem
        raise Problem("attachment_integrity_failed", 409, "File refused",
                      "Stored file integrity verification failed.",
                      "ไฟล์ที่จัดเก็บไม่ตรงกับข้อมูลต้นฉบับ กรุณาติดต่อผู้ดูแลระบบ", "DEBT-ATT-409")
    return raw

NOT_DURABLE_EN = "No database — this file is held in memory and is lost on restart"
NOT_DURABLE_TH = "ไม่มีฐานข้อมูล — ไฟล์นี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
COLUMNS = ("uid", "sha256", "kind", "content_type", "size", "filename", "uploaded_by", "uploaded_at",
           "scan_state", "scan_by", "attached_to", "deleted_at", "deleted_by")

_MEMORY = {}


def reset():
    _MEMORY.clear()


def _uid():
    return "att-" + uuid.uuid4().hex[:12]


def _public(row, durable):
    rec = {k: row.get(k) for k in COLUMNS}
    for k in ("uploaded_at", "deleted_at"):
        if hasattr(rec.get(k), "isoformat"):
            rec[k] = rec[k].isoformat()
    rec["durable"] = durable
    if not durable:
        rec["note_th"] = NOT_DURABLE_TH
        rec["note_en"] = NOT_DURABLE_EN
    return rec


def put(meta, raw, uploaded_by, scan):
    _verified(meta, raw)
    # I2 (fix round 1): uploaded_at is stamped tz-aware on the memory path, and on
    # the Postgres path the INSERT ... RETURNING hands back the column's own
    # DEFAULT now() value rather than this module's clock guess — so put() and a
    # later get() always agree on the same uploaded_at.
    row = {"uid": _uid(), "sha256": meta["sha256"], "kind": meta["kind"], "content_type": meta["content_type"],
           "size": meta["size"], "filename": meta["filename"], "uploaded_by": uploaded_by,
           "uploaded_at": datetime.now(timezone.utc), "scan_state": scan["state"], "scan_by": scan["by"],
           "attached_to": None, "deleted_at": None, "deleted_by": None}
    if not db.configured():
        _MEMORY[row["uid"]] = dict(row, bytes=raw)
        return _public(row, durable=False)
    conn = db.connect()
    try:
        from ..production_unit import enabled
        from .. import task_objects
        object_name = None
        if enabled():
            if scan["state"] != "CLEAN": raise ValueError("production requires a clean scan")
            object_name = task_objects.put("attachments/" + row["uid"], raw, bucket_env="CLEAN_BUCKET")
        with conn.begin():
            returned = conn.execute(text(
                "insert into records.attachment (uid, sha256, kind, content_type, size, filename, uploaded_by, "
                "scan_state, scan_by, bytes, object_name) values (:uid, :sha256, :kind, :content_type, :size, :filename, "
                ":uploaded_by, :scan_state, :scan_by, :bytes, :object_name) returning " + ", ".join(COLUMNS)),
                dict(row, bytes=None if object_name else raw, object_name=object_name)).mappings().first()
    finally:
        conn.close()
    return _public(dict(returned), durable=True)


def get(uid):
    if not db.configured():
        row = _MEMORY.get(uid)
        return (None if row is None or row["deleted_at"] else (_public(row, False), _verified(row, row["bytes"])))
    conn = db.connect()
    try:
        row = conn.execute(text("select * from records.attachment where uid = :u and deleted_at is null"),
                           {"u": uid}).mappings().first()
    finally:
        conn.close()
    if row is None: return None
    if row["object_name"]:
        from .. import task_objects
        raw = task_objects.get(row["object_name"], bucket_env="CLEAN_BUCKET")
    else:
        raw = bytes(row["bytes"])
    return _public(dict(row), True), _verified(row, raw)


def metadata(uid):
    """Permission checks need attachment targets without loading private bytes."""
    if not db.configured():
        row = _MEMORY.get(uid)
        return _public(row, False) if row else None
    with db.connect() as conn:
        row = conn.execute(text("select " + ", ".join(COLUMNS) + " from records.attachment where uid=:u"),
                           {"u": uid}).mappings().first()
    return _public(dict(row), True) if row else None


def attach(uid, target):
    if not db.configured():
        # I1 (fix round 1): an unknown or already-deleted uid answers None here,
        # matching the Postgres path's UPDATE ... RETURNING finding no row.
        row = _MEMORY.get(uid)
        if row is None or row["deleted_at"]:
            return None
        row["attached_to"] = target
        return _public(row, False)
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text("update records.attachment set attached_to = :t where uid = :u and deleted_at is null "
                                    "returning " + ", ".join(COLUMNS)), {"t": target, "u": uid}).mappings().first()
    finally:
        conn.close()
    return _public(dict(row), True) if row else None


def delete(uid, by):
    if not db.configured():
        row = _MEMORY.get(uid)
        if row is None or row["deleted_at"]:
            return None
        row["deleted_at"], row["deleted_by"] = datetime.now(timezone.utc).replace(tzinfo=None), by
        return _public(row, False)
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text("update records.attachment set deleted_at = now(), deleted_by = :b "
                                    "where uid = :u and deleted_at is null returning " + ", ".join(COLUMNS)),
                               {"b": by, "u": uid}).mappings().first()
    finally:
        conn.close()
    return _public(dict(row), True) if row else None


def list_for(target):
    if not db.configured():
        return [_public(r, False) for r in _MEMORY.values() if r["attached_to"] == target and not r["deleted_at"]]
    conn = db.connect()
    try:
        rows = conn.execute(text("select " + ", ".join(COLUMNS) + " from records.attachment where attached_to = :t "
                                 "and deleted_at is null order by uploaded_at"), {"t": target}).mappings().all()
    finally:
        conn.close()
    return [_public(dict(r), True) for r in rows]
