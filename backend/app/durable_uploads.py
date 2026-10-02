"""Cross-instance upload metadata in Postgres, bytes in private GCS."""
import uuid
from sqlalchemy import text
from . import db, task_objects
from .production_unit import CURRENT


def owner(by):
    return (CURRENT.get() or {}).get("subject") or by


def refused():
    from .imports import UploadRefused
    return UploadRefused("/upload_id", "The upload is missing, incomplete or expired; send the file again.",
                         "ไฟล์ที่อัปโหลดไม่ครบหรือหมดเวลา — อัปโหลดใหม่อีกครั้ง")


def put(upload_id, index, of, raw, by):
    from .imports import MAX_BYTES
    with db.connect() as conn, conn.begin():
        conn.execute(text("select pg_advisory_xact_lock(hashtext(:u))"), {"u": "upload:" + upload_id})
        conn.execute(text("insert into app.upload_session(upload_id,owner,parts) values(:u,:o,:n) "
                          "on conflict do nothing"), {"u": upload_id, "o": owner(by), "n": of})
        meta = conn.execute(text("select owner,parts,consumed_at,created_at > now()-interval '24 hours' as active "
                                 "from app.upload_session where upload_id=:u for update"), {"u": upload_id}).one()
        if meta.owner != owner(by) or meta.parts != of or meta.consumed_at or not meta.active: raise refused()
        total = conn.execute(text("select coalesce(sum(size),0) from app.upload_part "
                                  "where upload_id=:u and part_index!=:i"), {"u": upload_id, "i": index}).scalar()
        if total + len(raw) > MAX_BYTES: raise refused()
        name = task_objects.put("chunks/%s/%s/%s" % (upload_id, index, uuid.uuid4().hex), raw)
        conn.execute(text("insert into app.upload_part(upload_id,part_index,object_name,size) values(:u,:i,:b,:s) "
                          "on conflict(upload_id,part_index) do update set object_name=excluded.object_name,size=excluded.size"),
                     {"u": upload_id, "i": index, "b": name, "s": len(raw)})
        return conn.execute(text("select count(*) from app.upload_part where upload_id=:u"), {"u": upload_id}).scalar()


def take(upload_id, by):
    with db.connect() as conn, conn.begin():
        meta = conn.execute(text("select owner,parts,consumed_at,created_at > now()-interval '24 hours' as active "
                                 "from app.upload_session where upload_id=:u for update"), {"u": upload_id}).first()
        if not meta or meta.owner != owner(by) or meta.consumed_at or not meta.active: raise refused()
        parts = conn.execute(text("select part_index,object_name from app.upload_part where upload_id=:u order by part_index"),
                             {"u": upload_id}).fetchall()
        if [p.part_index for p in parts] != list(range(meta.parts)): raise refused()
        raw = b"".join(task_objects.get(p.object_name) for p in parts)
        conn.execute(text("update app.upload_session set consumed_at=now() where upload_id=:u"), {"u": upload_id})
        return raw


def discard(upload_id, by):
    with db.connect() as conn, conn.begin():
        return conn.execute(text("update app.upload_session set consumed_at=now() "
                                 "where upload_id=:u and owner=:o and consumed_at is null"),
                            {"u": upload_id, "o": owner(by)}).rowcount > 0
