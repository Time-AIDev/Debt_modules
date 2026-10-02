import pytest
from app import db, migrate, imports, task_objects


@pytest.fixture
def uploads(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ENV", "prd")
    objects = {}
    def put(name, raw): objects[name] = raw; return name
    monkeypatch.setattr(task_objects, "put", put)
    monkeypatch.setattr(task_objects, "get", lambda name: objects[name])
    yield
    db.reset()


def test_chunked_upload_survives_restart_and_joins_in_index_order(uploads):
    imports.put_part("11111111-1111-4111-8111-111111111111", 1, 2, b"second", "actor")
    imports.put_part("11111111-1111-4111-8111-111111111111", 0, 2, b"first", "actor")
    imports._PARTS.clear()
    assert imports.take_upload("11111111-1111-4111-8111-111111111111", "actor") == b"firstsecond"


def test_other_actor_cannot_take_or_discard_an_upload(uploads):
    imports.put_part("22222222-2222-4222-8222-222222222222", 0, 1, b"file", "one")
    assert imports.discard_upload("22222222-2222-4222-8222-222222222222", "two") is False
    with pytest.raises(imports.UploadRefused): imports.take_upload("22222222-2222-4222-8222-222222222222", "two")
    assert imports.take_upload("22222222-2222-4222-8222-222222222222", "one") == b"file"
