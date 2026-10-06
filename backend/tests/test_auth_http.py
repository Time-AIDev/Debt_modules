"""Login through HTTP: the middleware, the routes, and what the audit log records."""
import asyncio
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import audit_store, auth
from app.main import app

SECRET = "s" * 40
FAST = 1000


def _accounts():
    return {
        "tester": {"hash": auth.hash_password("tester-pw", rounds=FAST), "role": "ANY", "officer": None},
        "manager.test": {"hash": auth.hash_password("manager-pw", rounds=FAST), "role": "MANAGER", "officer": "settasak"},
        "ops.test": {"hash": auth.hash_password("ops-pw", rounds=FAST), "role": "OPS", "officer": "ops"},
    }


@pytest.fixture
def on(tmp_path):
    environ = {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET, "AUTH_COOKIE_SECURE": "false",
               "AUTH_ALLOW_TEST_ACCOUNTS": "true", "AUTH_TEST_ACCOUNTS": json.dumps(_accounts()),
               "GOOGLE_CLIENT_ID": "client-123.apps.googleusercontent.com",
               "AUTH_ALLOWLIST": json.dumps({"thip@volt.co.th": {"role": "OFFICER", "officer": "thip"}})}
    auth.set_config(auth.load_config(environ, env_file=tmp_path / "none"))
    yield
    auth.reset()


def _login(client, username, password):
    return client.post("/v1/auth/password", json={"username": username, "password": password})


def test_off_by_default_headers_still_decide():
    client = TestClient(app)
    assert client.get("/v1/auth/config").json() == {
        "mode": "off", "google_client_id": None, "password_enabled": False,
        "environment": "development", "data_mode": "fixtures"}
    assert client.get("/v1/workbook").status_code == 200
    assert client.get("/v1/auth/me").json()["code"] == "auth_off"


def test_on_without_a_session_every_v1_call_is_refused(on):
    client = TestClient(app)
    r = client.get("/v1/workbook")
    assert r.status_code == 401 and r.json()["code"] == "auth_required"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert client.get("/healthz").status_code == 200
    assert client.get("/v1/auth/config").json()["mode"] == "on"


def test_password_login_sets_a_cookie_and_me_answers(on):
    client = TestClient(app)
    r = _login(client, "manager.test", "manager-pw")
    assert r.status_code == 200
    assert r.json()["role"] == "MANAGER" and r.json()["kind"] == "TEST" and r.json()["can_switch"] is False
    assert auth.COOKIE in client.cookies
    assert client.get("/v1/auth/me").json()["subject"] == "manager.test"
    assert client.get("/v1/workbook").status_code == 200


def test_wrong_password_then_lockout(on):
    client = TestClient(app)
    for _ in range(auth.LOCK_AFTER):
        assert _login(client, "tester", "nope").json()["code"] == "login_failed"
    r = _login(client, "tester", "tester-pw")
    assert r.status_code == 429 and r.json()["code"] == "login_locked"


def test_unknown_username_is_the_same_refusal_as_a_wrong_password(on):
    assert _login(TestClient(app), "nobody", "x").json()["code"] == "login_failed"


# Fix round 1, finding 3 (IMPORTANT): an unknown username used to refuse instantly
# while a known one paid PBKDF2's real cost — a timing oracle telling a guesser
# which usernames exist. An unknown username must now pay the same check_password
# cost against a decoy hash before it is refused.
def test_an_unknown_username_still_pays_the_password_check_cost(on, monkeypatch):
    calls = []
    real_check_password = auth.check_password

    def spy(password, stored):
        calls.append(stored)
        return real_check_password(password, stored)

    monkeypatch.setattr(auth, "check_password", spy)
    _login(TestClient(app), "nobody", "x")
    assert len(calls) == 1


# What the middleware hands a route is read back through a tiny echo app wrapped in
# the SAME middleware class: spying on the real routes would test FastAPI's body
# parsing, not the rewrite.
ROSTER = [{"uid": "nantapol", "role": "OFFICER"}, {"uid": "settasak", "role": "MANAGER"},
          {"uid": "owner", "role": "OWNER"}, {"uid": "ops", "role": "OPS"}]


def _echo_client():
    from fastapi import Body, FastAPI, Request

    mini = FastAPI()

    @mini.post("/v1/contacts")
    async def contacts(request: Request):
        # AUTHORISED TEST EDIT 45: reads its JSON by hand, as routers/pipelines.py does, so a body
        # with no Content-Type still reaches it (FastAPI >=0.132 no longer parses one into Body()).
        body = json.loads(await request.body())
        return {"body": body, "role": request.headers.get("x-volt-role"),
                "officer": request.headers.get("x-volt-officer")}

    @mini.post("/v1/config/approval-paths")
    def approval(body: dict = Body(...)):
        return {"body": body}

    # Not JSON-shaped by contract: echoes the RAW bytes it received, so a body the
    # middleware must pass through byte-identical (not JSON, or JSON but not a
    # dict) can be checked without a pydantic dict validator getting in the way.
    @mini.post("/v1/raw-echo")
    async def raw_echo(request: Request):
        raw = await request.body()
        return {"raw": raw.decode("utf-8"), "content_length": request.headers.get("content-length")}

    mini.add_middleware(auth.AuthMiddleware, roster=lambda: ROSTER)
    return TestClient(mini)


def _cookie_for(username, role, officer, can_switch):
    session = auth.new_session(username, "TEST", role, officer, can_switch)
    return {auth.COOKIE: auth.sign_session(session, SECRET.encode())}


def test_a_locked_account_cannot_claim_another_role_by_header_or_body(on):
    client = _echo_client()
    client.cookies.update(_cookie_for("manager.test", "MANAGER", "settasak", False))
    r = client.post("/v1/contacts", json={"role": "OFFICER", "by": "nantapol", "note": "สวัสดี"},
                    headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}).json()
    assert r["role"] == "MANAGER" and r["officer"] == "settasak"
    assert r["body"] == {"role": "MANAGER", "by": "settasak", "note": "สวัสดี", "officer": "settasak"}


def test_approval_path_body_role_is_left_alone_but_by_is_not(on):
    client = _echo_client()
    client.cookies.update(_cookie_for("tester", "OFFICER", "nantapol", True))
    r = client.post("/v1/config/approval-paths", json={"role": "DEBT_MANAGER", "by": "Nok"},
                    headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}).json()
    assert r["body"] == {"role": "DEBT_MANAGER", "by": "owner"}


# Fix round 1, finding 1 (CRITICAL): the middleware used to gate its body read on
# a literal "application/json" substring in Content-Type. FastAPI/Starlette parse
# JSON with NO Content-Type, with `Application/JSON`, and with a JSON vendor type
# alike, so all three shapes reached the route un-rewritten — a locked session's
# real role/identity sent past the middleware, then trusted by the route. The body
# is now read (and, when it parses to a dict, rewritten) for every non-GET/HEAD
# request regardless of Content-Type; only the parsed shape decides.
def test_body_is_rewritten_no_matter_what_content_type_says(on):
    client = _echo_client()
    client.cookies.update(_cookie_for("manager.test", "MANAGER", "settasak", False))
    payload = json.dumps({"role": "OWNER", "by": "owner"}).encode("utf-8")
    cases = [
        ("no Content-Type at all", {}),
        ("mixed-case Application/JSON", {"Content-Type": "Application/JSON"}),
        ("a JSON vendor type", {"Content-Type": "application/vnd.x+json"}),
    ]
    for label, headers in cases:
        r = client.post("/v1/contacts", content=payload, headers=headers)
        body = r.json()["body"]
        assert body == {"role": "MANAGER", "by": "settasak", "officer": "settasak"}, (label, body)


def test_a_non_json_body_passes_through_byte_identical(on):
    client = _echo_client()
    client.cookies.update(_cookie_for("tester", "OFFICER", "nantapol", True))
    r = client.post("/v1/raw-echo", content=b"hello", headers={"Content-Type": "text/plain"})
    assert r.json()["raw"] == "hello"


def test_a_json_list_body_passes_through_unchanged(on):
    client = _echo_client()
    client.cookies.update(_cookie_for("tester", "OFFICER", "nantapol", True))
    r = client.post("/v1/raw-echo", json=[1, 2, 3])
    assert json.loads(r.json()["raw"]) == [1, 2, 3]


# Fix round 1, finding 2 (IMPORTANT): _read_body returns None on a client
# disconnect mid-body (an http.disconnect ASGI message rather than http.request).
# The middleware must never forward that request to the inner app with a
# half-drained receive() — it must simply stop.
def test_a_client_disconnect_mid_body_never_reaches_the_inner_app(on):
    called = False

    async def inner_app(scope, receive, send):
        nonlocal called
        called = True

    cookie_value = auth.sign_session(
        auth.new_session("tester", "TEST", "OFFICER", "nantapol", True), SECRET.encode())
    scope = {
        "type": "http", "method": "POST", "path": "/v1/contacts",
        "headers": [(b"cookie", ("%s=%s" % (auth.COOKIE, cookie_value)).encode("latin-1")),
                    (b"content-type", b"application/json")],
    }

    messages = [
        {"type": "http.request", "body": b'{"by":', "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive():
        return messages.pop(0)

    sent = []

    async def send(message):
        sent.append(message)

    middleware = auth.AuthMiddleware(inner_app, roster=lambda: ROSTER)
    asyncio.run(middleware(scope, receive, send))

    assert called is False
    assert sent == []


def test_tester_switches_within_the_roles(on):
    client = TestClient(app)
    _login(client, "tester", "tester-pw")
    r = client.post("/v1/reports/weekly:snapshot", headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"})
    assert r.json()["snapshot"]["taken_by_role"] == "OWNER"


def test_google_sign_in_on_the_allow_list(on, monkeypatch):
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": "Thip@volt.co.th", "email_verified": True})
    client = TestClient(app)
    r = client.post("/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 200 and r.json()["officer"] == "thip" and r.json()["kind"] == "GOOGLE"


def test_google_sign_in_refusals(on, monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": "stranger@volt.co.th", "email_verified": True})
    assert client.post("/v1/auth/google", json={"credential": "t"}).json()["code"] == "not_on_allow_list"
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": "thip@volt.co.th", "email_verified": False})
    assert client.post("/v1/auth/google", json={"credential": "t"}).json()["code"] == "google_token_invalid"

    def boom(credential, client_id):
        raise ValueError("bad signature")
    monkeypatch.setattr(auth, "verify_google_token", boom)
    assert client.post("/v1/auth/google", json={"credential": "t"}).json()["code"] == "google_token_invalid"


# Final review I2: google-auth missing from the image is a service that cannot do
# Google sign-in — a 503 "not configured", not a 401 blaming the person's token.
def test_google_sign_in_without_the_library_is_not_configured(on, monkeypatch):
    def missing(credential, client_id):
        raise ImportError("No module named 'google'")
    monkeypatch.setattr(auth, "verify_google_token", missing)
    r = TestClient(app).post("/v1/auth/google", json={"credential": "t"})
    assert r.status_code == 503 and r.json()["code"] == "google_not_configured"
    assert r.json()["detail"] == "google-auth is not installed on this service."


# Final review C1, second ruling: a POST that leaves `by` out used to record the
# route's demo default ("Nok") rather than the session's officer.
def test_a_locked_session_posting_a_promise_without_by_signs_as_itself(on):
    client = TestClient(app)
    _login(client, "manager.test", "manager-pw")
    items = client.get("/v1/working-list").json()["items"]
    target = next(i for i in items if i["open_ptp"] is None and float(i["aggregate_overdue"]) > 0)
    r = client.post("/v1/ptps", json={"customer_uid": target["customer"]["uid"],
                                      "promised_amount": "5000", "promise_date": "2026-10-30"})
    assert r.status_code == 201, r.json()
    assert r.json()["ptp"]["created_by"] == "settasak"


# ...and only a POST gains a `by`. PUT /v1/config refuses any key it does not edit,
# so a `by` added there would fail every settings save with login on.
def test_a_put_is_not_given_a_by_so_a_settings_save_still_works(on):
    from app.config import settings
    client = TestClient(app)
    _login(client, "manager.test", "manager-pw")
    before = settings.band_set_code
    try:
        r = client.put("/v1/config", json={"band_set_code": "LEGACY_SHEET"})
        assert r.status_code == 200, r.json()
        assert r.json()["config"]["band_set_code"]["value"] == "LEGACY_SHEET"
    finally:
        client.put("/v1/config", json={"band_set_code": before})


# Final review I4: the attributes are read off the raw header. The client jar keeps a
# cookie whatever its flags say, so it cannot show HttpOnly or Secure went missing.
def test_the_session_cookie_is_httponly_lax_rooted_and_secure(tmp_path):
    environ = {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET,
               "AUTH_ALLOW_TEST_ACCOUNTS": "true", "AUTH_TEST_ACCOUNTS": json.dumps(_accounts())}
    auth.set_config(auth.load_config(environ, env_file=tmp_path / "none"))
    try:
        r = _login(TestClient(app), "manager.test", "manager-pw")
        assert r.status_code == 200
        [raw] = [h for h in r.headers.get_list("set-cookie") if h.startswith(auth.COOKIE + "=")]
        parts = [p.strip() for p in raw.split(";")]
        for flag in ("HttpOnly", "SameSite=Lax", "Path=/", "Secure"):
            assert flag in parts, (flag, parts)
    finally:
        auth.reset()


# Final review C1: POST /v1/contacts takes the acting officer from body `officer`,
# which the middleware did not touch. A locked manager naming nantapol spent the
# daily slot as nantapol. Read back through the lock the Today list shows.
def test_a_locked_session_cannot_log_a_contact_as_another_officer(on):
    client = TestClient(app)
    _login(client, "manager.test", "manager-pw")
    uid = client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    r = client.post("/v1/contacts", json={
        "customer_uid": uid, "channel": "PHONE", "direction": "OUTBOUND",
        "disposition": "ANS_DISCUSSED", "officer": "nantapol"})
    assert r.status_code == 201, r.json()
    row = next(i for i in client.get("/v1/today-list").json()["items"] if i["customer"]["uid"] == uid)
    assert row["contact_lock"]["locked_by"] == "settasak"


def test_google_not_configured(tmp_path):
    auth.set_config(auth.load_config({"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET}, env_file=tmp_path / "x"))
    try:
        r = TestClient(app).post("/v1/auth/google", json={"credential": "t"})
        assert r.status_code == 503 and r.json()["code"] == "google_not_configured"
    finally:
        auth.reset()


def test_logout_clears_the_session(on):
    client = TestClient(app)
    _login(client, "tester", "tester-pw")
    assert client.post("/v1/auth/logout").json() == {"signed_out": True}
    assert client.get("/v1/workbook").status_code == 401


def test_an_expired_session_is_refused(on, monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(auth, "_now", lambda: 1_000_000)
    _login(client, "tester", "tester-pw")
    monkeypatch.setattr(auth, "_now", lambda: 1_000_000 + auth.IDLE_SECONDS + 1)
    assert client.get("/v1/workbook").status_code == 401


def test_staging_six_hour_idle_window_through_middleware(on, monkeypatch):
    auth.set_config(replace(auth.current_config(), idle_seconds=6 * 60 * 60))
    client = TestClient(app)
    monkeypatch.setattr(auth, "_now", lambda: 1_000_000)
    assert _login(client, "tester", "tester-pw").status_code == 200
    monkeypatch.setattr(auth, "_now", lambda: 1_000_000 + 6 * 60 * 60)
    assert client.get("/v1/workbook", headers={"X-Volt-Background": "1"}).status_code == 200
    monkeypatch.setattr(auth, "_now", lambda: 1_000_000 + 6 * 60 * 60 + 1)
    assert client.get("/v1/workbook").status_code == 401


def test_audit_records_the_session_as_the_source(on):
    client = TestClient(app)
    _login(client, "manager.test", "manager-pw")
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid, json={"code": "PAID"})
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["actor_source"] == "TEST_ACCOUNT" and entry["actor_claimed"] == "manager.test"


def test_the_ops_identity_is_in_the_registry():
    body = TestClient(app).get("/v1/officers").json()
    assert {"uid": "ops", "role": "OPS"}.items() <= next(o for o in body["officers"] if o["uid"] == "ops").items()


# Fix-all F4: the screen polls /v1/data-state every 30 s while it is visible, and a
# new epoch sets off refetches. A request the page sent on its own (X-Volt-Background)
# must not move `seen`, or an open, idle screen would never sign out (SEC-002).
def test_a_background_request_never_moves_the_idle_clock(on, monkeypatch):
    client = TestClient(app)
    real_now = auth._now
    monkeypatch.setattr(auth, "_now", lambda: real_now() - 120)    # signed in two minutes ago
    assert _login(client, "manager.test", "manager-pw").status_code == 200
    monkeypatch.setattr(auth, "_now", real_now)                     # so the refresh is due

    def refreshed(response):
        return [h for h in response.headers.get_list("set-cookie") if h.startswith(auth.COOKIE + "=")]

    polled = client.get("/v1/data-state", headers={"X-Volt-Background": "1"})
    assert polled.status_code == 200 and refreshed(polled) == []
    assert len(refreshed(client.get("/v1/data-state"))) == 1        # a person's request still does
