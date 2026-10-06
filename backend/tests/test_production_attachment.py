import hashlib
from sqlalchemy import text
from app import db, migrate, task_objects
from app.attachments import store


def test_clean_production_file_lives_in_gcs_not_database(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ENV", "prd")
    objects = {}
    def put(name, raw, bucket_env="UPLOADS_BUCKET"):
        assert bucket_env == "CLEAN_BUCKET"
        objects[name] = raw
        return name
    monkeypatch.setattr(task_objects, "put", put)
    monkeypatch.setattr(task_objects, "get", lambda name, bucket_env: objects[name])
    row = store.put({"sha256": hashlib.sha256(b"file").hexdigest(), "kind": "PDF", "content_type": "application/pdf", "size": 4,
                     "filename": "file.pdf"}, b"file", "owner", {"state": "CLEAN", "by": "clamd"})
    try:
        record = pg_conn.execute(text("select bytes,object_name from records.attachment where uid=:u"), {"u": row["uid"]}).first()
        assert record.bytes is None
        assert objects[record.object_name] == b"file"
        assert store.get(row["uid"])[1] == b"file"
    finally:
        pg_conn.execute(text("delete from records.attachment where uid=:u"), {"u": row["uid"]})
        pg_conn.commit()
        db.reset()
