"""Production tab sessions use real Postgres, never a process-local token map."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import auth, db, migrate
from app.main import app


@pytest.fixture
def tab_login(monkeypatch, pg_url, pg_conn, tmp_path):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    config = auth.load_config({
        "AUTH_MODE": "on", "AUTH_SESSION_SECRET": "s" * 40,
        "AUTH_SESSION_POLICY": "tab", "GOOGLE_CLIENT_ID": "client.apps.googleusercontent.com",
        "AUTH_ALLOWLIST": json.dumps({"thip@volt.co.th": {"role": "OFFICER", "officer": "thip"}}),
    }, env_file=tmp_path / "none")
    auth.set_config(config)
    monkeypatch.setattr(auth, "verify_google_token", lambda *_: {
        "email": "thip@volt.co.th", "email_verified": True,
    })
    yield TestClient(app), pg_conn
    auth.reset()
    db.reset()


def sign_in(client):
    response = client.post("/v1/auth/google", json={"credential": "google-proof"})
    assert response.status_code == 200, response.text
    return response.json()


def test_tab_login_returns_nonexpiring_token_stored_only_as_hash(tab_login):
    client, conn = tab_login
    body = sign_in(client)
    assert body.get("session_policy") == "tab"
    assert body["expires_at"] is None
    token = body["session_token"]
    assert len(token) >= 43
    assert auth.COOKIE not in client.cookies
    stored = conn.execute(text("select token_hash from app.auth_session")).scalar_one()
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token != stored


def test_tab_session_survives_days_of_idle_and_process_restart(tab_login, monkeypatch):
    client, _ = tab_login
    body = sign_in(client)
    headers = {"Authorization": "Bearer " + body["session_token"]}
    now = auth._now()
    monkeypatch.setattr(auth, "_now", lambda: now + 90 * 86400)
    db.reset()
    response = TestClient(app).get("/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["subject"] == "thip@volt.co.th"
    assert client.get("/v1/auth/me").status_code == 401


def test_logout_revokes_only_the_presented_tab(tab_login):
    client, _ = tab_login
    first, second = sign_in(client), sign_in(client)
    one = {"Authorization": "Bearer " + first["session_token"]}
    two = {"Authorization": "Bearer " + second["session_token"]}
    assert client.post("/v1/auth/logout", headers=one).status_code == 200
    assert client.get("/v1/auth/me", headers=one).status_code == 401
    assert client.get("/v1/auth/me", headers=two).status_code == 200


def test_tab_mode_refuses_legacy_cookie_and_forged_bearer(tab_login):
    client, _ = tab_login
    signed = auth.sign_session(auth.new_session("thip@volt.co.th", "GOOGLE", "OFFICER", "thip", False), b"s" * 40)
    client.cookies.set(auth.COOKIE, signed)
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_new_tab_session_has_configurable_absolute_expiry(tab_login, monkeypatch):
    from dataclasses import replace
    client, _ = tab_login
    auth.set_config(replace(auth.current_config(), tab_absolute_seconds=60))
    before = auth._now()
    body = sign_in(client)
    assert before + 59 <= body["expires_at"] <= before + 61
    headers = {"Authorization": "Bearer " + body["session_token"]}
    assert client.get("/v1/auth/me", headers=headers).status_code == 200
    monkeypatch.setattr(auth, "_now", lambda: before + 62)
    assert client.get("/v1/auth/me", headers=headers).status_code == 401


def test_enabling_tab_ttl_does_not_rewrite_existing_credentials(tab_login):
    from dataclasses import replace
    client, _ = tab_login
    original = sign_in(client)
    auth.set_config(replace(auth.current_config(), tab_absolute_seconds=60))
    response = client.get("/v1/auth/me", headers={"Authorization": "Bearer " + original["session_token"]})
    assert response.status_code == 200
    assert response.json()["expires_at"] is None
