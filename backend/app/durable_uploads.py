"""Cross-instance upload metadata in Postgres, bytes in immutable private objects."""
import uuid
import hashlib
from sqlalchemy import text
from . import db, task_objects
from .production_unit import CURRENT
from .integrations import env


def owner(by):
    return (CURRENT.get() or {}).get("subject") or by


def refused():
    from .imports import UploadRefused
    return UploadRefused("/upload_id", "The upload is missing, incomplete or expired; send the file again.",
                         "ไฟล์ที่อัปโหลดไม่ครบหรือหมดเวลา — อัปโหลดใหม่อีกครั้ง")


def put(upload_id, index, of, raw, by):
    from .imports import MAX_BYTES, PART_BYTES, check_part
    check_part(upload_id, index, of)
    if not raw or len(raw) > PART_BYTES:
        raise refused()
    actor = owner(by)
    digest = hashlib.sha256(raw).hexdigest()
    with db.connect() as conn, conn.begin():
        # All quota checks and writes share one transaction lock. Per-upload
        # locking alone permits concurrent sessions to exceed the owner's cap.
        conn.execute(text("select pg_advisory_xact_lock(hashtext('upload:quota'))"))
        conn.execute(text("select pg_advisory_xact_lock(hashtext(:u))"), {"u": "upload:" + upload_id})
        conn.execute(text("insert into app.upload_session(upload_id,owner,parts) values(:u,:o,:n) "
                          "on conflict do nothing"), {"u": upload_id, "o": actor, "n": of})
        meta = conn.execute(text("select owner,parts,consumed_at,created_at > now()-interval '24 hours' as active "
                                 "from app.upload_session where upload_id=:u for update"), {"u": upload_id}).one()
        if meta.owner != actor or meta.parts != of or meta.consumed_at or not meta.active: raise refused()
        existing = conn.execute(text("select object_name,size,sha256 from app.upload_part "
                                     "where upload_id=:u and part_index=:i"), {"u": upload_id, "i": index}).first()
        if existing:
            # Retrying a part is safe; changing an already accepted part requires
            # a new upload. Never create replacement objects that can leak bytes.
            previous_digest = existing.sha256 or hashlib.sha256(task_objects.get(existing.object_name)).hexdigest()
            if existing.size != len(raw) or previous_digest != digest:
                raise refused()
            return conn.execute(text("select count(*) from app.upload_part where upload_id=:u"), {"u": upload_id}).scalar()
        total = conn.execute(text("select coalesce(sum(size),0) from app.upload_part "
                                  "where upload_id=:u and part_index!=:i"), {"u": upload_id, "i": index}).scalar()
        if total + len(raw) > MAX_BYTES: raise refused()
        quota = conn.execute(text(
            "select coalesce(sum(p.size),0) as total,coalesce(sum(p.size) filter(where s.owner=:o),0) as owned "
            "from app.upload_part p join app.upload_session s using(upload_id) "
            "where s.consumed_at is null and s.created_at > now()-interval '24 hours'"
        ), {"o": actor}).one()
        if (quota.owned + len(raw) > int(env("UPLOAD_OWNER_MAX_BYTES", str(2 * MAX_BYTES))) or
                quota.total + len(raw) > int(env("UPLOAD_TOTAL_MAX_BYTES", str(10 * MAX_BYTES)))):
            raise refused()
        name = task_objects.put("chunks/%s/%s/%s" % (upload_id, index, uuid.uuid4().hex), raw)
        conn.execute(text("insert into app.upload_part(upload_id,part_index,object_name,size,sha256) values(:u,:i,:b,:s,:h)"),
                     {"u": upload_id, "i": index, "b": name, "s": len(raw), "h": digest})
        return conn.execute(text("select count(*) from app.upload_part where upload_id=:u"), {"u": upload_id}).scalar()


def take(upload_id, by):
    with db.connect() as conn, conn.begin():
        meta = conn.execute(text("select owner,parts,consumed_at,created_at > now()-interval '24 hours' as active "
                                 "from app.upload_session where upload_id=:u for update"), {"u": upload_id}).first()
        if not meta or meta.owner != owner(by) or meta.consumed_at or not meta.active: raise refused()
        parts = conn.execute(text("select part_index,object_name,size,sha256 from app.upload_part where upload_id=:u order by part_index"),
                             {"u": upload_id}).fetchall()
        if [p.part_index for p in parts] != list(range(meta.parts)): raise refused()
        from .imports import MAX_BYTES
        if sum(part.size for part in parts) > MAX_BYTES:
            raise refused()
        chunks = []
        for part in parts:
            chunk = task_objects.get(part.object_name)
            if len(chunk) != part.size or part.sha256 and hashlib.sha256(chunk).hexdigest() != part.sha256:
                raise refused()
            chunks.append(chunk)
        raw = b"".join(chunks)
        conn.execute(text("update app.upload_session set consumed_at=now() where upload_id=:u"), {"u": upload_id})
        return raw


def discard(upload_id, by):
    with db.connect() as conn, conn.begin():
        return conn.execute(text("update app.upload_session set consumed_at=now() "
                                 "where upload_id=:u and owner=:o and consumed_at is null"),
                            {"u": upload_id, "o": owner(by)}).rowcount > 0
