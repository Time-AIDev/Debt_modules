"""B12a (Feedback Round 1 / WP11, design F14): /v1/auth/me and the sign-in answer carry
display_name — the person's own, else the e-mail's user part, else the username — and a
signed-in person sets their own from PUT /v1/auth/me/profile."""
import json

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from app import audit, audit_store, auth, user_accounts
from app.main import app

SECRET = "s" * 40
FAST = 1000


@pytest.fixture
def on(tmp_path):
    environ = {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET, "AUTH_COOKIE_SECURE": "false",
               "AUTH_ALLOW_TEST_ACCOUNTS": "true",
               "AUTH_TEST_ACCOUNTS": json.dumps({
                   "tester": {"hash": auth.hash_password("tester-pw", rounds=FAST), "role": "ANY", "officer": None},
                   "manager.test": {"hash": auth.hash_password("manager-pw", rounds=FAST), "role": "MANAGER",
                                    "officer": "settasak"}}),
               "GOOGLE_CLIENT_ID": "client-123.apps.googleusercontent.com",
               "AUTH_ALLOWLIST": json.dumps({"somchai.t@example.co.th": {"role": "OFFICER", "officer": "thip"}})}
    user_accounts.reset()
    auth.set_config(auth.load_config(environ, env_file=tmp_path / "none"))
    yield
    auth.reset()
    user_accounts.reset()


def _google(monkeypatch):
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": "Somchai.T@example.co.th", "email_verified": True})
    client = TestClient(app)
    return client, client.post("/v1/auth/google", json={"credential": "tok"})


def test_with_login_off_the_profile_answers_auth_off():
    user_accounts.reset()
    assert TestClient(app).put("/v1/auth/me/profile", json={"display_name": "x"}).json()["code"] == "auth_off"


def test_the_profile_needs_a_session(on):
    r = TestClient(app).put("/v1/auth/me/profile", json={"display_name": "x"})
    assert r.status_code == 401 and r.json()["code"] == "auth_required"


def test_a_google_person_with_no_name_set_is_greeted_by_the_e_mail_user_part(on, monkeypatch):
    client, signed = _google(monkeypatch)
    assert signed.json()["display_name"] == "somchai.t" and signed.json()["display_name_source"] == "EMAIL"
    me = client.get("/v1/auth/me").json()
    assert (me["display_name"], me["display_name_fallback"]) == ("somchai.t", "somchai.t")


def test_a_test_account_with_no_name_set_is_greeted_by_its_username(on):
    client = TestClient(app)
    signed = client.post("/v1/auth/password", json={"username": "manager.test", "password": "manager-pw"})
    assert signed.json()["display_name"] == "manager.test"


def test_a_person_names_themself_and_me_serves_it(on, monkeypatch):
    client, _signed = _google(monkeypatch)
    r = client.put("/v1/auth/me/profile", json={"display_name": "สมชาย"})
    assert r.status_code == 200 and r.json()["display_name"] == "สมชาย" and r.json()["subject"] == "somchai.t@example.co.th"
    me = client.get("/v1/auth/me").json()
    assert (me["display_name"], me["display_name_source"], me["display_name_fallback"]) == ("สมชาย", "PROFILE", "somchai.t")
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert (entry["act"], entry["detail"]) == ("PROFILE_SET", {"display_name": "set"})
    cleared = client.put("/v1/auth/me/profile", json={"display_name": ""})
    assert cleared.json()["display_name"] == "somchai.t"


def test_a_switching_test_account_may_name_itself_too(on):
    client = TestClient(app)
    client.post("/v1/auth/password", json={"username": "tester", "password": "tester-pw"})
    assert client.put("/v1/auth/me/profile", json={"display_name": "Somchai"}).json()["display_name"] == "Somchai"


def test_a_bad_name_and_a_key_that_is_not_the_name_are_refused(on, monkeypatch):
    client, _signed = _google(monkeypatch)
    r = client.put("/v1/auth/me/profile", json={"display_name": "x" * 61})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "display_name_invalid"
    r = client.put("/v1/auth/me/profile", json={"display_name": "x", "role": "OWNER"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not_editable"
    assert client.get("/v1/auth/me").json()["role"] == "OFFICER"


def test_the_login_core_me_payload_is_unchanged():
    """me_payload (pinned by test_auth_core) stays the session's own fields; the name is
    added by the route, which is the only place that reads the user list."""
    session = auth.new_session("a@example.co.th", "GOOGLE", "OFFICER", "thip", False, now=0)
    assert "display_name" not in auth.me_payload(session)


# --- controller rulings for B12a (2026-09-15) ---------------------------------------------
# user_accounts.set_profile (B10a) already refuses a NUL/lone surrogate and a non-str
# display_name, and never echoes the value: (a)-(c) below are tests only. (d) needed a real
# fix — set_profile now describes PROFILE_SET before any validation that can raise
# (backend/app/user_accounts.py), so a refused set still writes a REFUSED PROFILE_SET row.

def _raw_put(client, body):
    """httpx's own json= encodes with ensure_ascii=False, so it raises client-side on a
    lone surrogate before a request is ever built — a real browser's fetch()+
    JSON.stringify() sends ASCII-escaped text instead (ensure_ascii's own encoding), so
    that is what this sends: pre-encoded ASCII bytes, exactly what json.loads() on the
    server reconstructs the lone surrogate from (same approach as test_calendar_notices.py's
    _raw_json)."""
    payload = json.dumps(body, ensure_ascii=True).encode("ascii")
    return client.put("/v1/auth/me/profile", content=payload, headers={"content-type": "application/json"})


def _not_echoed(response, value):
    err = response.json()["errors"][0]
    assert str(value) not in err["message"] and str(value) not in err["message_th"]


def test_a_nul_or_lone_surrogate_in_the_name_is_refused_and_never_echoed(on, monkeypatch):
    """(a): [\\x00\\ud800-\\udfff] is refused 422 display_name_invalid by pointer
    /display_name, with message_th, and the raw value never appears in the refusal."""
    client, _signed = _google(monkeypatch)
    for bad in ("bad\x00name", "แจ้ง\ud800ลูกค้า", "bad\udfffname"):
        r = _raw_put(client, {"display_name": bad})
        assert r.status_code == 422, bad
        err = r.json()["errors"][0]
        assert (err["pointer"], err["code"]) == ("/display_name", "display_name_invalid")
        assert err["message_th"]
        _not_echoed(r, bad)
    me = client.get("/v1/auth/me").json()
    assert me["display_name_source"] == "EMAIL"          # nothing was ever stored


def test_a_real_emoji_surrogate_pair_is_governed_only_by_the_existing_rules(on, monkeypatch):
    """(a): a proper surrogate pair, once JSON-decoded into one Python code point, is a
    normal emoji character — accepted like any other visible glyph."""
    client, _signed = _google(monkeypatch)
    r = client.put("/v1/auth/me/profile", json={"display_name": "สมชาย 😀"})
    assert r.status_code == 200 and r.json()["display_name"] == "สมชาย 😀"


def test_a_non_string_name_is_refused_never_str_converted(on, monkeypatch):
    """(b): a number, a list or a dict is refused display_name_invalid, never str()'d
    into a stored name."""
    client, _signed = _google(monkeypatch)
    for bad in (42, ["x"], {"a": 1}):
        r = client.put("/v1/auth/me/profile", json={"display_name": bad})
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "display_name_invalid", bad
        _not_echoed(r, bad)
    me = client.get("/v1/auth/me").json()
    assert me["display_name_source"] == "EMAIL"


def test_a_refused_set_still_writes_a_refused_profile_set_row(on, monkeypatch):
    """(d): described before anything that can raise, so a not_editable refusal and a
    display_name_invalid refusal both land as a REFUSED PROFILE_SET row naming this
    person's own subject — never the audit middleware's untouched act=None default."""
    client, _signed = _google(monkeypatch)
    r1 = client.put("/v1/auth/me/profile", json={"display_name": "x", "role": "OWNER"})
    assert r1.status_code == 422 and r1.json()["errors"][0]["code"] == "not_editable"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert (entry["act"], entry["outcome"], entry["error_code"], entry["subject_type"], entry["subject_uid"]) == (
        "PROFILE_SET", "REFUSED", "validation_failed", "user_account", "somchai.t@example.co.th")
    assert entry["detail"] == {}
    r2 = client.put("/v1/auth/me/profile", json={"display_name": "x" * 61})
    assert r2.status_code == 422 and r2.json()["errors"][0]["code"] == "display_name_invalid"
    entry2 = audit_store.read({}, limit=1, before_seq=None)[0]
    assert (entry2["act"], entry2["outcome"], entry2["error_code"]) == ("PROFILE_SET", "REFUSED", "validation_failed")
    assert client.get("/v1/auth/me").json()["display_name_source"] == "EMAIL"   # neither refusal stored anything


def test_a_database_that_does_not_answer_refuses_the_set(on, monkeypatch):
    """set_profile's store failure follows the B10a SQL pattern: a configured database
    that does not answer is the retryable 503 user_list_unreachable, raised from None — a
    TEST-kind session so the middleware's own session_allowed check (GOOGLE only) never
    touches the down database first."""
    client = TestClient(app)
    client.post("/v1/auth/password", json={"username": "tester", "password": "tester-pw"})
    from app import db
    user_accounts.forget()

    def down():
        raise db.DatabaseUnreachable("no route")
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", down)
    r = client.put("/v1/auth/me/profile", json={"display_name": "x"})
    assert (r.status_code, r.json()["code"]) == (503, "user_list_unreachable")
    assert r.json()["message_th"]


def test_a_withdrawn_or_disabled_session_cannot_set_its_name(on, monkeypatch):
    """A disabled Google person's still-open cookie is refused by the same middleware
    gate every other protected route uses (PUT /v1/auth/me/profile is not in
    auth.OPEN_PATHS): 401, account_withdrawn, the cookie cleared, and the PUT never
    reaches the route, so no PROFILE_SET row is added. Final fix F-R1 now has
    AuthMiddleware write its own REFUSED audit row for the refusal, so exactly one row
    is added, not none: outcome REFUSED, error_code account_withdrawn, never a
    PROFILE_SET success."""
    client, _signed = _google(monkeypatch)
    admin = TestClient(app)
    admin.post("/v1/auth/password", json={"username": "manager.test", "password": "manager-pw"})
    uid = next(u["uid"] for u in admin.get("/v1/auth/users").json()["users"]
              if u["email"] == "somchai.t@example.co.th")
    assert admin.post("/v1/auth/users/%s:disable" % uid, json={}).status_code == 200
    before = audit_store.read({}, limit=1, before_seq=None)[0]
    r = client.put("/v1/auth/me/profile", json={"display_name": "x"})
    assert r.status_code == 401 and r.json()["code"] == "auth_required"
    assert r.json()["extensions"]["reason"] == "account_withdrawn"
    assert "Max-Age=0" in r.headers["set-cookie"]
    after = audit_store.read({}, limit=2, before_seq=None)
    assert after[1]["seq"] == before["seq"] and after[1]["act"] == "USER_DISABLED"
    assert after[0]["seq"] == before["seq"] + 1               # exactly one new row
    assert after[0]["outcome"] == "REFUSED" and after[0]["error_code"] == "account_withdrawn"
    assert after[0]["act"] != "PROFILE_SET"                   # no PROFILE_SET success


# --- controller ruling, B12a fix round 1 (2026-09-15) --------------------------------------
# me()'s order matters: _me(session) — which calls user_accounts.display_name_for(...,
# fresh=True), an UNCACHED read — must be built only AFTER the withdrawn-session check, so a
# withdrawn session never pays that read's cost and a database outage never turns its clean
# 401 into a 503. Nothing in routers/login.py changes for this: reading it shows the shipped
# order is already correct (session_allowed is checked, then and only then _me(session) is
# built), so these are regression tests guarding that order, not a fix.

def _disable_somchai(client):
    """Disables somchai.t@example.co.th (the client's own signed-in identity) through a
    separate Manager session, and returns the now-withdrawn cookie value the client held.
    A THROWAWAY TestClient carries that value from here on — the client's own cookie jar
    would otherwise drop the session on the very first 401 that clears it (fix round 1 /
    M4's clearing cookie) — the same reason test_auth_users.py's _withdrawn tests do this."""
    cookie = client.cookies.get(auth.COOKIE)
    admin = TestClient(app)
    admin.post("/v1/auth/password", json={"username": "manager.test", "password": "manager-pw"})
    uid = next(u["uid"] for u in admin.get("/v1/auth/users").json()["users"]
              if u["email"] == "somchai.t@example.co.th")
    assert admin.post("/v1/auth/users/%s:disable" % uid, json={}).status_code == 200
    return cookie


def _with_cookie(cookie):
    client = TestClient(app)
    client.cookies.set(auth.COOKIE, cookie)
    return client


def test_a_withdrawn_me_never_reads_the_display_name_and_clears_exactly_one_cookie(on, monkeypatch):
    client, _signed = _google(monkeypatch)
    cookie = _disable_somchai(client)

    def _boom(session, fresh=True):
        raise AssertionError("display_name_for must not run before the withdrawn check")
    monkeypatch.setattr(user_accounts, "display_name_for", _boom)

    r = _with_cookie(cookie).get("/v1/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "auth_required"
    assert r.json()["extensions"]["reason"] == "account_withdrawn"
    volt_auth_cookies = [c for c in r.headers.get_list("set-cookie") if c.startswith(auth.COOKIE + "=")]
    assert len(volt_auth_cookies) == 1 and "Max-Age=0" in volt_auth_cookies[0]


def test_a_withdrawn_me_during_a_database_outage_still_answers_401_not_503(on, monkeypatch):
    """The withdrawn check itself reads fresh=False (a cache lookaside): warm that cache
    with the disabled row while the store still answers (in-memory, not yet configured),
    THEN take the database down. The check then answers from cache and never touches the
    dead connection; a route that built _me() (an uncached fresh=True read) before the
    check would still hit that dead connection and turn the clean 401 into a 503."""
    client, _signed = _google(monkeypatch)
    cookie = _disable_somchai(client)
    _with_cookie(cookie).get("/v1/auth/me")          # warms the cache with the disabled row

    from app import db

    def down():
        raise db.DatabaseUnreachable("no route")
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", down)

    r = _with_cookie(cookie).get("/v1/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "auth_required"
    assert r.json()["extensions"]["reason"] == "account_withdrawn"


def test_the_profile_route_is_registered_and_logged_by_construction():
    """Ruling F13: a new PUT route, swept by neither the pinned test_audit_coverage.py
    (one act per router module — login.py's is already USER_INVITED) nor B10b's own
    test_user_audit_coverage.py (login.py's user-list ACTS tuple), so it is asserted here
    instead of in either pinned file."""
    routes = set()
    for route in app.routes:
        if isinstance(route, Route):
            routes |= {(method, route.path) for method in (route.methods or set())}
    assert ("PUT", "/v1/auth/me/profile") in routes
    assert audit.is_logged("PUT", "/v1/auth/me/profile")
