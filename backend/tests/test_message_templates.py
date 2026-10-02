"""Personal LINE/Facebook templates are durable and owner-isolated."""
import pytest
from fastapi.testclient import TestClient

from app import db, migrate
from app.main import app


@pytest.fixture
def client(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.exec_driver_sql("delete from records.message_template")
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    with TestClient(app) as test_client:
        yield test_client
    pg_conn.exec_driver_sql("delete from records.message_template")
    pg_conn.commit()
    db.reset()


def actor(name):
    return {"X-Volt-Officer": name}


def test_templates_are_personal_and_separate_by_channel(client):
    line = client.post("/v1/message-templates", headers=actor("alice"), json={
        "channel": "LINE", "name": "ทวงนัด", "body": "ขอแจ้งเตือนยอดนัดชำระ",
    })
    facebook = client.post("/v1/message-templates", headers=actor("alice"), json={
        "channel": "FACEBOOK", "name": "แจ้งยอด", "body": "กรุณาตรวจสอบยอดค้าง",
    })
    assert line.status_code == 201 and facebook.status_code == 201

    mine = client.get("/v1/message-templates", headers=actor("alice")).json()["items"]
    assert {(item["channel"], item["name"]) for item in mine} == {
        ("LINE", "ทวงนัด"), ("FACEBOOK", "แจ้งยอด"),
    }
    assert client.get("/v1/message-templates", headers=actor("bob")).json()["items"] == []


def test_only_the_owner_can_update_or_delete_a_template(client):
    created = client.post("/v1/message-templates", headers=actor("alice"), json={
        "channel": "LINE", "name": "เดิม", "body": "ข้อความเดิม",
    }).json()["template"]
    uid = created["uid"]

    assert client.put("/v1/message-templates/%s" % uid, headers=actor("bob"), json={
        "name": "แอบแก้", "body": "ห้ามสำเร็จ",
    }).status_code == 404
    changed = client.put("/v1/message-templates/%s" % uid, headers=actor("alice"), json={
        "name": "ใหม่", "body": "ข้อความใหม่",
    })
    assert changed.status_code == 200
    assert changed.json()["template"]["name"] == "ใหม่"
    assert client.delete("/v1/message-templates/%s" % uid, headers=actor("bob")).status_code == 404
    assert client.delete("/v1/message-templates/%s" % uid, headers=actor("alice")).status_code == 200
    assert client.get("/v1/message-templates", headers=actor("alice")).json()["items"] == []


def test_template_input_is_bounded_and_channel_is_explicit(client):
    bad = client.post("/v1/message-templates", headers=actor("alice"), json={
        "channel": "EMAIL", "name": "x", "body": "y",
    })
    blank = client.post("/v1/message-templates", headers=actor("alice"), json={
        "channel": "LINE", "name": " ", "body": " ",
    })
    assert bad.status_code == 422
    assert blank.status_code == 422
