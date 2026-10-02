"""F13: B10b's two acts (USER_INVITED, USER_DISABLED) are audited, by construction and
for real.

A new file, not an edit to the pinned tests/test_audit_coverage.py, whose sweep takes one
act per router module and does not reach routers/login.py's user list. Login is switched
on per test through auth.set_config (never backend/.env, never os.environ). Synthetic
addresses only.
"""
import json

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from app import audit, audit_store, auth, user_accounts
from app.main import app

SECRET = "s" * 40
FAST = 1000
SEED = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"}}
ACTS = (("POST", "/v1/auth/users"), ("POST", "/v1/auth/users/{uid}:disable"))


@pytest.fixture
def on(tmp_path):
    accounts = {
        "owner.test": {"hash": auth.hash_password("owner-pw", rounds=FAST), "role": "OWNER", "officer": "owner"},
        "officer.test": {"hash": auth.hash_password("officer-pw", rounds=FAST), "role": "OFFICER", "officer": "nantapol"},
    }
    environ = {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET, "AUTH_COOKIE_SECURE": "false",
               "AUTH_ALLOW_TEST_ACCOUNTS": "true", "AUTH_TEST_ACCOUNTS": json.dumps(accounts),
               "AUTH_ALLOWLIST": json.dumps(SEED)}
    user_accounts.reset()
    auth.set_config(auth.load_config(environ, env_file=tmp_path / "none"))
    yield
    auth.reset()
    user_accounts.reset()


def _password(username, password):
    client = TestClient(app)
    assert client.post("/v1/auth/password", json={"username": username, "password": password}).status_code == 200
    return client


def test_the_user_list_acts_are_registered_and_logged_by_construction():
    routes = set()
    for route in app.routes:
        if isinstance(route, Route):
            routes |= {(method, route.path) for method in (route.methods or set())}
    for method, path in ACTS:
        assert (method, path) in routes, "%s %s is not a registered route" % (method, path)
        assert audit.is_logged(method, path)
    assert ("GET", "/v1/auth/users") in routes and not audit.is_logged("GET", "/v1/auth/users")


def test_an_invite_and_a_disable_land_in_the_log_refused_or_done(on):
    """A refused act is logged REFUSED with its code; a done one names the act and the
    e-mail as its subject, the session as the actor, and never an e-mail in detail."""
    officer = _password("officer.test", "officer-pw")
    owner = _password("owner.test", "owner-pw")
    officer.post("/v1/auth/users", json={"email": "x@example.co.th", "role": "OFFICER", "officer": "thip"})
    officer.post("/v1/auth/users/1:disable", json={})
    r = owner.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"})
    assert r.status_code == 201, r.json()
    assert owner.post("/v1/auth/users/%s:disable" % r.json()["user"]["uid"], json={}).status_code == 200
    rows = [e for e in audit_store.read({}, limit=20, before_seq=None)
            if (e["route_template"] or "").startswith("/v1/auth/users")][:4]
    got = [(e["verb"], e["route_template"], e["outcome"], e["error_code"], e["act"], e["subject_type"],
            e["subject_uid"], e["actor_claimed"], e["actor_source"]) for e in reversed(rows)]
    assert got == [
        ("POST", "/v1/auth/users", "REFUSED", "forbidden", None, None, None, "officer.test", "TEST_ACCOUNT"),
        ("POST", "/v1/auth/users/{uid}:disable", "REFUSED", "forbidden", None, None, None, "officer.test", "TEST_ACCOUNT"),
        ("POST", "/v1/auth/users", "OK", None, "USER_INVITED", "user_account", "new@example.co.th",
         "owner.test", "TEST_ACCOUNT"),
        ("POST", "/v1/auth/users/{uid}:disable", "OK", None, "USER_DISABLED", "user_account", "new@example.co.th",
         "owner.test", "TEST_ACCOUNT"),
    ]
    assert [e["detail"] for e in reversed(rows)][2:] == [
        {"role": "OFFICER", "officer": "nantapol", "reenabled": False}, {"role": "OFFICER", "seeded": False}]
