"""PEAK webhooks, Stage A: key gate, storage, duplicates, PDPA mask, and no login needed."""
import pytest
from fastapi.testclient import TestClient

from app import auth, peak_webhooks
from app.main import app

KEY = "k" * 64
client = TestClient(app)


@pytest.fixture(autouse=True)
def keyed(monkeypatch):
    monkeypatch.setenv("PEAK_WEBHOOK_KEY", KEY)
    peak_webhooks.reset()
    yield
    peak_webhooks.reset()


def _post(kind="invoice", body=b'{"id":"inv-1","status":"paid"}', key=KEY):
    headers = {"content-type": "application/json"}
    if key:
        headers["x-api-key"] = key
    return client.post("/v1/webhooks/peak/%s" % kind, content=body, headers=headers)


def test_the_right_key_stores_the_event_once():
    first = _post()
    assert first.status_code == 200 and first.json() == {"received": True, "duplicate": False}
    assert _post().json() == {"received": True, "duplicate": True}
    assert len(peak_webhooks._MEMORY) == 1
    # fix-all P7 (M10): an event carries no browser, so no session cookie is minted for it
    assert "volt_session" not in first.headers.get("set-cookie", "")


@pytest.mark.parametrize("key", [None, "wrong"])
def test_a_missing_or_wrong_key_is_refused_and_nothing_is_stored(key):
    assert _post(key=key).status_code == 401
    assert not peak_webhooks._MEMORY


def test_no_configured_key_refuses_everyone_and_asks_for_a_retry(monkeypatch):
    monkeypatch.delenv("PEAK_WEBHOOK_KEY")
    response = _post()
    assert response.status_code == 503 and response.json()["retryable"] is True


def test_an_unknown_kind_is_404_and_payments_is_gone_naming_the_real_paths():
    assert _post(kind="expense").status_code == 404
    # fix-all P10c (M8): it answered 202 recorded:true and stored nothing
    gone = client.post("/v1/webhooks/peak/payments", json={})
    assert gone.status_code == 410 and gone.json()["code"] == "webhook_gone"
    assert gone.json()["extensions"]["paths"] == list(auth.WEBHOOK_PATHS)


def test_an_empty_body_is_stored_not_refused():
    """Fix-all P7: PEAK does not retry a 4xx, so refusing an empty body lost the event."""
    response = _post(body=b"")
    assert response.status_code == 200 and response.json()["duplicate"] is False
    assert list(peak_webhooks._MEMORY.values()) == [b""]


def test_two_bodies_differing_only_in_a_thirteen_digit_run_are_two_events():
    """Fix-all P7: the duplicate key was taken after the mask, so an epoch-millisecond
    timestamp made the second event read as a duplicate of the first."""
    assert _post(body=b'{"id":"inv-1","updatedAt":1727164800000}').json()["duplicate"] is False
    assert _post(body=b'{"id":"inv-1","updatedAt":1727164800001}').json()["duplicate"] is False
    assert len(peak_webhooks._MEMORY) == 2


def test_an_oversized_body_is_stored_cut_and_answered_200(monkeypatch):
    monkeypatch.setattr(peak_webhooks, "MAX_BYTES", 16)
    response = _post(body=b'{"id":"inv-1","note":"' + b"x" * 40 + b'"}')
    assert response.status_code == 200
    assert list(peak_webhooks._MEMORY.values()) == [b'{"id":"inv-1","n']


def test_any_failure_to_store_is_a_retryable_503_that_never_says_why(monkeypatch, caplog):
    def _boom(body):
        raise RuntimeError("secret-name 1234567890123")
    monkeypatch.setattr(peak_webhooks, "mask", _boom)
    response = _post()
    assert response.status_code == 503 and response.json()["retryable"] is True
    assert response.json()["code"] == "webhook_store_unreachable"
    assert "secret-name" not in response.text and "secret-name" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_a_thirteen_digit_id_is_masked_before_storage():
    _post(kind="contact", body=b'{"taxNumber":"1234567890123","phone":"0812345678"}')
    (stored,) = peak_webhooks._MEMORY.values()
    assert b"1234567890123" not in stored and b"#############" in stored
    assert b"0812345678" in stored


def test_a_thirteen_digit_id_written_with_dashes_is_masked_too():
    _post(kind="contact", body=b'{"taxNumber":"1-2345-67890-12-3","ref":"1-2345-67890-12-34"}')
    (stored,) = peak_webhooks._MEMORY.values()
    assert stored == b'{"taxNumber":"#############","ref":"1-2345-67890-12-34"}'


def test_peak_needs_no_login_session_when_login_is_on(tmp_path):
    auth.set_config(auth.load_config({"AUTH_MODE": "on", "AUTH_SESSION_SECRET": "s" * 40},
                                     env_file=tmp_path / "none"))
    try:
        assert _post(kind="receipt").status_code == 200
        assert client.post("/v1/webhooks/peak/payments", json={}).status_code == 401
    finally:
        auth.reset()


def test_postgres_keeps_one_masked_row_per_body(pg_url, pg_conn, monkeypatch):
    from sqlalchemy import text

    from app import db, migrate

    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        body = b'{"id":"r-1","taxNumber":"1234567890123"}'
        assert peak_webhooks.record("receipt", body, "application/json") is True
        assert peak_webhooks.record("receipt", body, "application/json") is False
        rows = pg_conn.execute(text("select kind, body from landing.peak_webhook_event")).fetchall()
        assert [(k, bytes(b)) for k, b in rows] == [("receipt", b'{"id":"r-1","taxNumber":"#############"}')]
        # fix-all P7: an oversized body is kept cut, flagged, with its real size
        monkeypatch.setattr(peak_webhooks, "MAX_BYTES", 16)
        big = b'{"id":"i-1","note":"' + b"x" * 40 + b'"}'
        assert peak_webhooks.record("invoice", big, None) is True
        row = pg_conn.execute(text("select body, truncated, size_bytes from landing.peak_webhook_event "
                                   "where kind = 'invoice'")).one()
        assert (bytes(row[0]), row[1], row[2]) == (b'{"id":"i-1","not', True, len(big))
    finally:
        db.reset()
