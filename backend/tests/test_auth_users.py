"""B10b (Feedback Round 1 / WP10, design F13): the user list over HTTP — who may call
it, what sign-in does with it, and what a disabled person's cookie does next.

Login is switched on per test through auth.set_config (never backend/.env, never
os.environ). Synthetic addresses only.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import audit_store, auth, user_accounts
from app.main import app

SECRET = "s" * 40
FAST = 1000
SEED = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"},
        "lead@example.co.th": {"role": "MANAGER", "officer": "settasak"},
        "thip@example.co.th": {"role": "OFFICER", "officer": "thip"}}


def _accounts():
    return {
        "tester": {"hash": auth.hash_password("tester-pw", rounds=FAST), "role": "ANY", "officer": None},
        "owner.test": {"hash": auth.hash_password("owner-pw", rounds=FAST), "role": "OWNER", "officer": "owner"},
        "manager.test": {"hash": auth.hash_password("manager-pw", rounds=FAST), "role": "MANAGER", "officer": "settasak"},
        "officer.test": {"hash": auth.hash_password("officer-pw", rounds=FAST), "role": "OFFICER", "officer": "nantapol"},
    }


def _environ(seed=None):
    return {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET, "AUTH_COOKIE_SECURE": "false",
            "AUTH_ALLOW_TEST_ACCOUNTS": "true", "AUTH_TEST_ACCOUNTS": json.dumps(_accounts()),
            "GOOGLE_CLIENT_ID": "client-123.apps.googleusercontent.com",
            "AUTH_ALLOWLIST": json.dumps(SEED if seed is None else seed)}


@pytest.fixture
def on(tmp_path):
    user_accounts.reset()
    auth.set_config(auth.load_config(_environ(), env_file=tmp_path / "none"))
    yield
    auth.reset()
    user_accounts.reset()


def _password(username, password):
    client = TestClient(app)
    assert client.post("/v1/auth/password", json={"username": username, "password": password}).status_code == 200
    return client


def _google(monkeypatch, email):
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": email, "email_verified": True})
    client = TestClient(app)
    return client, client.post("/v1/auth/google", json={"credential": "tok"})


def _uid(client, email):
    return next(u["uid"] for u in client.get("/v1/auth/users").json()["users"] if u["email"] == email)


def test_with_login_off_every_user_route_answers_auth_off():
    client = TestClient(app)
    assert client.get("/v1/auth/users", headers={"X-Volt-Role": "OWNER"}).json()["code"] == "auth_off"
    assert client.post("/v1/auth/users", json={"email": "a@example.co.th"}, headers={"X-Volt-Role": "OWNER"}).status_code == 404
    assert client.post("/v1/auth/users/1:disable", headers={"X-Volt-Role": "OWNER"}).json()["code"] == "auth_off"


def test_the_user_routes_are_not_open_the_way_sign_in_is(on):
    client = TestClient(app)
    for call in (lambda: client.get("/v1/auth/users"), lambda: client.post("/v1/auth/users", json={}),
                 lambda: client.post("/v1/auth/users/1:disable", json={})):
        r = call()
        assert r.status_code == 401 and r.json()["code"] == "auth_required"
    assert client.get("/v1/auth/config").status_code == 200


def test_only_a_fixed_manager_or_owner_manages_users(on):
    officer = _password("officer.test", "officer-pw")
    r = officer.get("/v1/auth/users")
    assert (r.status_code, r.json()["code"]) == (403, "forbidden") and r.json()["message_th"]
    tester = _password("tester", "tester-pw")
    r = tester.get("/v1/auth/users", headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"})
    assert (r.status_code, r.json()["code"]) == (403, "identity_not_fixed")
    manager = _password("manager.test", "manager-pw")
    body = manager.get("/v1/auth/users").json()
    assert {u["email"] for u in body["users"]} == set(SEED)
    assert body["grantable_roles"] == ["OFFICER", "SUPERVISOR", "MANAGER", "OPS"]
    assert body["durable"] is False and body["note_th"]
    from app import reports
    served = {o["officer_uid"]: o["caseload"] for o in reports.officers()}
    for u in body["users"]:
        assert u["caseload"] == (served.get(u["officer"], 0) if u["officer"] else None)
    assert any(u["caseload"] for u in body["users"]), "the seeded officers carry work"


def test_a_manager_invites_and_the_invited_person_signs_in_as_invited(on, monkeypatch):
    manager = _password("manager.test", "manager-pw")
    r = manager.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"})
    assert r.status_code == 201, r.json()
    assert r.json()["user"]["invited_by"] == "settasak" and r.json()["user"]["state"] == "ACTIVE"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert (entry["act"], entry["subject_type"], entry["subject_uid"]) == ("USER_INVITED", "user_account", "new@example.co.th")
    assert "new@example.co.th" not in json.dumps(entry["detail"])
    _client, signed = _google(monkeypatch, "new@example.co.th")
    assert signed.status_code == 200 and signed.json()["officer"] == "nantapol" and signed.json()["role"] == "OFFICER"


def test_an_invitation_above_the_inviters_role_is_refused(on):
    manager = _password("manager.test", "manager-pw")
    r = manager.post("/v1/auth/users", json={"email": "x@example.co.th", "role": "OWNER", "officer": "owner"})
    assert (r.status_code, r.json()["code"]) == (403, "role_above_actor") and r.json()["message_th"]


def test_a_bad_invitation_names_each_field(on):
    owner = _password("owner.test", "owner-pw")
    r = owner.post("/v1/auth/users", json={"email": "no", "role": "KING", "officer": "ghost"})
    assert r.status_code == 422 and [e["code"] for e in r.json()["errors"]] == ["email_invalid", "role_unknown", "officer_unknown"]


def test_a_manager_cannot_disable_an_owner_or_themselves(on, monkeypatch):
    lead, signed = _google(monkeypatch, "lead@example.co.th")
    assert signed.status_code == 200
    r = lead.post("/v1/auth/users/%s:disable" % _uid(lead, "boss@example.co.th"), json={})
    assert (r.status_code, r.json()["code"]) == (403, "role_above_actor")
    me = next(u for u in lead.get("/v1/auth/users").json()["users"] if u["self"])
    assert me["email"] == "lead@example.co.th"
    r = lead.post("/v1/auth/users/%s:disable" % me["uid"], json={})
    assert (r.status_code, r.json()["code"]) == (409, "cannot_disable_self") and r.json()["message_th"]


def test_a_disabled_person_cannot_sign_in_and_their_open_session_ends(on, monkeypatch):
    thip, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200 and thip.get("/v1/workbook").status_code == 200
    cookie = thip.cookies.get(auth.COOKIE)
    owner = _password("owner.test", "owner-pw")
    r = owner.post("/v1/auth/users/%s:disable" % _uid(owner, "thip@example.co.th"), json={})
    assert r.status_code == 200 and r.json()["user"]["state"] == "DISABLED"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert (entry["act"], entry["subject_uid"]) == ("USER_DISABLED", "thip@example.co.th")
    me = thip.get("/v1/auth/me")                       # open route: it checks for itself
    assert me.status_code == 401 and me.json()["extensions"]["reason"] == "account_withdrawn"
    # fix round 1 (M4): that /me answer cleared the cookie too, so the same cookie is sent again
    thip = TestClient(app)
    thip.cookies.set(auth.COOKIE, cookie)
    ended = thip.get("/v1/workbook")
    assert ended.status_code == 401 and ended.json()["code"] == "auth_required"
    assert ended.json()["extensions"]["reason"] == "account_withdrawn"
    assert "Max-Age=0" in ended.headers["set-cookie"]
    _again, refused = _google(monkeypatch, "thip@example.co.th")
    assert (refused.status_code, refused.json()["code"]) == (403, "account_disabled") and refused.json()["message_th"]


def test_the_seed_has_no_delete_route_and_a_disabled_seed_comes_back_by_invitation(on, monkeypatch):
    from starlette.routing import Route
    for route in app.routes:
        if isinstance(route, Route) and route.path.startswith("/v1/auth/users"):
            assert not ({"DELETE"} & set(route.methods or ())), route.path
    owner = _password("owner.test", "owner-pw")
    owner.post("/v1/auth/users/%s:disable" % _uid(owner, "thip@example.co.th"), json={})
    r = owner.post("/v1/auth/users", json={"email": "thip@example.co.th", "role": "OFFICER", "officer": "thip"})
    assert r.status_code == 201 and r.json()["user"]["state"] == "ACTIVE" and r.json()["user"]["seeded"] is True
    _client, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200


def test_a_password_test_account_is_untouched_by_the_list(on):
    manager = _password("manager.test", "manager-pw")
    assert manager.get("/v1/workbook").status_code == 200
    assert "manager.test" not in {u["email"] for u in manager.get("/v1/auth/users").json()["users"]}


def test_a_database_that_does_not_answer_refuses_the_session_check(on, monkeypatch, capfd):
    thip, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200
    from app import db
    user_accounts.forget()
    monkeypatch.setattr(db, "configured", lambda: True)

    def down():
        raise db.DatabaseUnreachable("no route")
    monkeypatch.setattr(db, "connect", down)
    capfd.readouterr()
    r = thip.get("/v1/auth/users")
    assert (r.status_code, r.json()["code"]) == (503, "user_list_unreachable")
    # fix round 2 captured the tester-session flush meeting the same dead database. The
    # flush now checks only the stores a request touched (session.TOUCHED), and this one
    # touched none, so it never opens a connection and has nothing to report.
    out, err = capfd.readouterr()
    assert (out, err) == ("", "")


# --- controller rulings for B10b (2026-09-15) -------------------------------------------

def test_the_open_paths_are_exactly_the_five_sign_in_routes(on, monkeypatch):
    """P3's security fix: the old "/v1/auth/" prefix would have opened the user list
    (and anything else ever put under /v1/auth/) to a request with no session."""
    assert auth.OPEN_PATHS == ("/v1/auth/config", "/v1/auth/password", "/v1/auth/google",
                               "/v1/auth/me", "/v1/auth/logout")
    assert not hasattr(auth, "OPEN_PREFIX")
    client = TestClient(app)
    for path in ("/v1/auth/users", "/v1/auth/users/", "/v1/auth/anything-new", "/v1/auth/me/users"):
        r = client.get(path)
        assert (r.status_code, r.json()["code"]) == (401, "auth_required"), path
    assert client.post("/v1/auth/logout").status_code == 200
    # an Officer — a Google one and a test one — is refused on every user route
    thip, _signed = _google(monkeypatch, "thip@example.co.th")
    officer = _password("officer.test", "officer-pw")
    for who in (thip, officer):
        for r in (who.get("/v1/auth/users"),
                  who.post("/v1/auth/users", json={"email": "x@example.co.th", "role": "OFFICER", "officer": "thip"}),
                  who.post("/v1/auth/users/1:disable", json={})):
            assert (r.status_code, r.json()["code"]) == (403, "forbidden")
            assert r.json()["message_th"]
    assert "x@example.co.th" not in {u["email"] for u in user_accounts.listed(auth.current_config().allowlist, None)}


def test_the_session_check_runs_in_the_threadpool_not_on_the_event_loop(on):
    """session_allowed() can block on a database read when the cache is cold, so the
    middleware must never call it on the event loop."""
    import asyncio

    from fastapi import FastAPI

    where = []

    def still_allowed(session):
        try:
            asyncio.get_running_loop()
            where.append("event loop")
        except RuntimeError:
            where.append("worker thread")
        return True

    mini = FastAPI()

    @mini.get("/v1/ping")
    async def ping():
        return {"ok": True}

    mini.add_middleware(auth.AuthMiddleware, roster=lambda: [], still_allowed=still_allowed)
    client = TestClient(mini)
    session = auth.new_session("thip@example.co.th", "GOOGLE", "OFFICER", "thip", False)
    client.cookies.set(auth.COOKIE, auth.sign_session(session, SECRET.encode()))
    assert client.get("/v1/ping").status_code == 200
    assert where == ["worker thread"]


@pytest.mark.parametrize("bad", [
    "thip\u200b@example.co.th",          # a zero-width space
    "thip@ex\u0430mple.co.th",           # a Cyrillic a
    "\u00e9lise@example.co.th",          # non-ASCII, however real
    "not-an-address",
    "two words@example.co.th",
])
def test_a_seed_address_the_store_would_refuse_fails_at_load_by_position(tmp_path, bad):
    """auth.load_config lower-cased AUTH_ALLOWLIST keys and checked nothing else, so a
    look-alike seed signed in and then broke disable() with a 500. It now fails at
    start-up with the store's own rule, naming the entry's position — never the address
    (the message reaches the service log)."""
    seed = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"},
            bad: {"role": "OFFICER", "officer": "thip"}}
    with pytest.raises(auth.AuthConfigError) as caught:
        auth.load_config(_environ(seed), env_file=tmp_path / "none")
    message = str(caught.value)
    assert "AUTH_ALLOWLIST entry 2" in message, message
    assert "example" not in message and bad not in message and "address" in message
    # a valid address in another case and with spaces still loads, lower-cased
    config = auth.load_config(_environ({" Boss@Example.CO.TH ": {"role": "OWNER", "officer": "owner"}}),
                              env_file=tmp_path / "none")
    assert config.allowlist == {"boss@example.co.th": {"role": "OWNER", "officer": "owner"}}


def test_a_seed_address_repeated_in_another_case_fails_at_load_by_position(tmp_path):
    """Two keys that lower-case to one address used to load with the last one's role,
    chosen silently."""
    seed = {"Boss@example.co.th": {"role": "OFFICER", "officer": "thip"},
            "lead@example.co.th": {"role": "MANAGER", "officer": "settasak"},
            "boss@example.co.th": {"role": "OWNER", "officer": "owner"}}
    with pytest.raises(auth.AuthConfigError) as caught:
        auth.load_config(_environ(seed), env_file=tmp_path / "none")
    assert "AUTH_ALLOWLIST entry 3 (of 3) repeats" in str(caught.value)
    assert "example" not in str(caught.value)


def test_the_start_up_merge_reads_the_list_once_and_a_refusal_there_is_not_fatal(on, monkeypatch, capfd):
    """main._lifespan reads the rows at boot so the first request needs no query; a
    database that does not answer then prints the Problem's code (never its context)
    and the app still starts — every sign-in and session check refuses 503 until it
    answers."""
    import asyncio

    from app import db, main

    async def boot():
        async with main._lifespan(main.app):
            return user_accounts._CACHE["rows"]

    user_accounts.forget()
    assert asyncio.run(boot()) == {}                  # read once at start-up (memory: no rows)

    def down():
        try:
            raise RuntimeError("DETAIL:  Failing row contains (thip@example.co.th)")
        except RuntimeError:
            raise db.DatabaseUnreachable("no route")
    user_accounts.forget()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", down)
    capfd.readouterr()
    assert asyncio.run(boot()) is None                # started anyway, nothing cached
    _out, err = capfd.readouterr()
    assert "user list not read at start-up: user_list_unreachable" in err
    assert "example.co.th" not in err and "DETAIL" not in err


def test_the_token_email_is_normalised_and_checked_with_the_stores_own_rule(on, monkeypatch):
    _client, r = _google(monkeypatch, "  Thip@Example.CO.TH ")
    assert r.status_code == 200 and r.json()["subject"] == "thip@example.co.th"
    for look_alike in ("thip\u200b@example.co.th", "\ufeffthip@example.co.th", "thip@ex\u0430mple.co.th",
                       "thip@example.co.th\x00", "thip@example.co.th\u202e"):
        client, refused = _google(monkeypatch, look_alike)
        assert (refused.status_code, refused.json()["code"]) == (403, "not_on_allow_list"), ascii(look_alike)
        assert "example" not in refused.text and auth.COOKIE not in client.cookies
    calls = []
    real = user_accounts.valid_email
    monkeypatch.setattr(user_accounts, "valid_email", lambda email: calls.append(email) or real(email))
    _client, r = _google(monkeypatch, "THIP@example.co.th")
    assert r.status_code == 200 and calls == ["thip@example.co.th"]


def test_on_another_instance_a_disabled_session_ends_within_cache_seconds(on, monkeypatch):
    """The bound the report and auth.py state: another instance learns of a disable at
    its first request after its cached read is older than CACHE_SECONDS — never later.
    Simulated by changing the shared rows without this process's forget()."""
    clock = [5000.0]
    monkeypatch.setattr(user_accounts, "_clock", lambda: clock[0])
    thip, signed = _google(monkeypatch, "thip@example.co.th")        # a fresh read, cached at 5000
    assert signed.status_code == 200 and thip.get("/v1/workbook").status_code == 200
    user_accounts._memory_row("GOOGLE", email="thip@example.co.th").update(
        role="OFFICER", officer="thip", disabled_at=user_accounts._now(), disabled_by="owner")
    clock[0] = 5000.0 + user_accounts.CACHE_SECONDS
    assert thip.get("/v1/workbook").status_code == 200                # still inside the bound
    clock[0] += 0.5
    ended = thip.get("/v1/workbook")
    assert (ended.status_code, ended.json()["extensions"]["reason"]) == (401, "account_withdrawn")


def test_a_store_refusal_whose_context_quotes_an_email_leaks_it_nowhere(on, monkeypatch, caplog, capfd):
    """B10a's re-review: a Problem raised `from None` still carries the driver exception
    on __context__, and Postgres puts the failing row — the e-mail — in that exception's
    own text. The middleware and every route render the Problem only: nothing logs,
    prints or answers the context."""
    import logging

    from app import errors

    thip, _signed = _google(monkeypatch, "thip@example.co.th")
    manager = _password("manager.test", "manager-pw")

    def leaky_read():
        try:
            raise RuntimeError('new row for relation "user_account" violates check constraint\n'
                               'DETAIL:  Failing row contains (7, GOOGLE, thip@example.co.th, null).')
        except RuntimeError:
            raise errors.internal_error() from None

    monkeypatch.setattr(user_accounts, "_read_rows", leaky_read)
    user_accounts.forget()
    caplog.set_level(logging.DEBUG)
    capfd.readouterr()
    answers = [
        thip.get("/v1/workbook"),                                     # the middleware's session check
        thip.get("/v1/auth/me"),
        _google(monkeypatch, "thip@example.co.th")[1],                # sign-in
        manager.get("/v1/auth/users"),
        manager.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"}),
        manager.post("/v1/auth/users/1:disable", json={}),
    ]
    for r in answers:
        assert (r.status_code, r.json()["code"]) == (500, "internal_error"), r.request.url
        assert "example.co.th" not in r.text and "DETAIL" not in r.text
    out, err = capfd.readouterr()
    assert "example.co.th" not in caplog.text + out + err
    assert "Failing row" not in caplog.text + out + err


# --- against Postgres: the durable rows, and a table the migration never made ----------

@pytest.fixture
def on_postgres(on, pg_url, monkeypatch):
    """The store alone on the task database (a real engine, a pooled connection per
    call, the production shape); the rest of the app stays in memory."""
    from types import SimpleNamespace

    from sqlalchemy import create_engine, text

    from app import db, migrate

    engine = create_engine(pg_url, future=True)
    with engine.begin() as conn:
        migrate.apply(conn)
        conn.execute(text("delete from records.user_account"))
    monkeypatch.setattr(user_accounts, "db", SimpleNamespace(
        configured=lambda: True, connect=engine.connect, DatabaseUnreachable=db.DatabaseUnreachable))
    user_accounts.forget()
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            migrate.apply(conn)                       # puts back a table a test dropped
            conn.execute(text("delete from records.user_account"))
        engine.dispose()


def test_on_postgres_an_invitation_and_a_disable_are_rows_and_the_session_ends(on_postgres, monkeypatch):
    from sqlalchemy import text

    owner = _password("owner.test", "owner-pw")
    r = owner.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"})
    assert r.status_code == 201, r.json()
    new, signed = _google(monkeypatch, "new@example.co.th")
    assert signed.status_code == 200 and new.get("/v1/workbook").status_code == 200
    assert owner.post("/v1/auth/users/%s:disable" % r.json()["user"]["uid"], json={}).status_code == 200
    ended = new.get("/v1/workbook")                    # the instance that disabled: at once
    assert (ended.status_code, ended.json()["extensions"]["reason"]) == (401, "account_withdrawn")
    with on_postgres.connect() as conn:
        row = conn.execute(text("select role, officer, invited_by, disabled_by from records.user_account "
                                "where email = 'new@example.co.th'")).first()
    assert tuple(row) == ("OFFICER", "nantapol", "owner", "owner")


def test_a_missing_user_account_table_answers_the_labelled_503_not_a_500(on_postgres, monkeypatch):
    """The migration not applied: records.user_account is not there. The store used to
    answer internal_error (500) to every Google session's every request, every sign-in
    and the list; now each is a 503 whose message names the migration. Password test
    accounts are not on the list and keep working."""
    from sqlalchemy import text

    thip, signed = _google(monkeypatch, "thip@example.co.th")
    manager = _password("manager.test", "manager-pw")
    assert signed.status_code == 200
    with on_postgres.begin() as conn:
        conn.execute(text("drop table records.user_account"))
    user_accounts.forget()
    answers = [thip.get("/v1/workbook"), thip.get("/v1/auth/me"),
               _google(monkeypatch, "thip@example.co.th")[1], manager.get("/v1/auth/users"),
               manager.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "OFFICER", "officer": "nantapol"})]
    for r in answers:
        assert (r.status_code, r.json()["code"]) == (503, "user_list_not_migrated"), (r.request.url, r.json())
        assert "debt-migrate" in r.json()["message_th"] and "debt-migrate" in r.json()["detail"]
        assert "example.co.th" not in r.text
    assert manager.get("/v1/workbook").status_code == 200


# --- fix round 1 (opus review of 83c0937): I1, I2, M1-M4 --------------------------------

def _withdrawn(r):
    assert (r.status_code, r.json()["code"], r.json()["extensions"].get("reason")) == \
        (401, "auth_required", "account_withdrawn"), (r.request.url, r.json())
    # fix round 2: exactly ONE session cookie header, and it is the clearing one — a
    # refreshed cookie sent after it would win and keep the withdrawn session alive.
    session_cookies = [h for h in r.headers.get_list("set-cookie") if h.startswith(auth.COOKIE + "=")]
    assert len(session_cookies) == 1, session_cookies
    assert session_cookies[0].startswith(auth.COOKIE + "=;") and "Max-Age=0" in session_cookies[0], session_cookies


def test_a_cookie_from_before_a_disable_stays_dead_after_a_same_role_re_invite(on, monkeypatch):
    """I1: disabling is the answer to a lost laptop or a leaked cookie. A cookie signed
    before the disable used to work again once the person was re-invited with the same
    role and officer; a row invited after the session's iat now ends it."""
    real_now = auth._now
    monkeypatch.setattr(auth, "_now", lambda: real_now() - 120)       # signed in two minutes ago
    thip, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200
    stolen = thip.cookies.get(auth.COOKIE)
    monkeypatch.setattr(auth, "_now", real_now)
    owner = _password("owner.test", "owner-pw")
    assert owner.post("/v1/auth/users/%s:disable" % _uid(owner, "thip@example.co.th"), json={}).status_code == 200
    r = owner.post("/v1/auth/users", json={"email": "thip@example.co.th", "role": "OFFICER", "officer": "thip"})
    assert r.status_code == 201 and r.json()["user"]["state"] == "ACTIVE"
    for path in ("/v1/workbook", "/v1/auth/me"):
        thief = TestClient(app)
        thief.cookies.set(auth.COOKIE, stolen)
        _withdrawn(thief.get(path))
    # a cookie issued after the re-invitation works, even within the same second
    fresh, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200
    assert fresh.get("/v1/workbook").status_code == 200 and fresh.get("/v1/auth/me").status_code == 200


def test_a_refused_google_sign_in_body_carries_no_address(on, monkeypatch):
    """I2: not_on_allow_list used to echo the address in extensions.email."""
    for email in ("stranger@example.co.th", "thip\u200b@example.co.th"):
        _client, r = _google(monkeypatch, email)
        assert (r.status_code, r.json()["code"]) == (403, "not_on_allow_list")
        assert "@" not in r.text and r.json()["extensions"] == {}
    assert auth.not_on_allow_list("someone@example.co.th").extensions == {}     # the old argument is ignored


def test_a_manager_disabled_on_another_instance_cannot_use_the_user_list(on, monkeypatch):
    """M1: the middleware answers from this process's cache, so a Manager disabled on
    another instance kept reading every e-mail on the list for up to CACHE_SECONDS.
    _admin() re-checks a Google actor with a fresh read."""
    clock = [7000.0]
    monkeypatch.setattr(user_accounts, "_clock", lambda: clock[0])
    # fix round 2: signed in two minutes ago, so the middleware's cookie refresh
    # (REFRESH_AFTER, 60 s) is due on every call below — a refusal must still carry
    # only the clearing cookie (_withdrawn asserts exactly one).
    real_now = auth._now
    monkeypatch.setattr(auth, "_now", lambda: real_now() - 120)
    lead, signed = _google(monkeypatch, "lead@example.co.th")
    assert signed.status_code == 200 and lead.get("/v1/workbook").status_code == 200
    stolen = lead.cookies.get(auth.COOKIE)
    monkeypatch.setattr(auth, "_now", real_now)
    stale = (user_accounts._CACHE["at"], user_accounts._CACHE["rows"])       # this instance's snapshot
    # another instance disables lead: the shared rows change, this cache is not told
    user_accounts._memory_row("GOOGLE", email="lead@example.co.th").update(
        role="MANAGER", officer="settasak", disabled_at=user_accounts._now(), disabled_by="owner")
    thip_uid = next(u["uid"] for u in user_accounts.listed(SEED, None) if u["email"] == "thip@example.co.th")
    calls = (lambda c: c.get("/v1/workbook"),
             lambda c: c.get("/v1/auth/users"),
             lambda c: c.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "OFFICER",
                                                      "officer": "nantapol"}),
             lambda c: c.post("/v1/auth/users/%s:disable" % thip_uid, json={}))
    answers = []
    for call in calls:
        user_accounts._CACHE["at"], user_accounts._CACHE["rows"] = stale       # still the stale instance
        client = TestClient(app)
        client.cookies.set(auth.COOKIE, stolen)
        answers.append(call(client))
    assert answers[0].status_code == 200            # the middleware alone would still let lead through
    refreshed = [h for h in answers[0].headers.get_list("set-cookie") if h.startswith(auth.COOKIE + "=")]
    assert len(refreshed) == 1 and "Max-Age=0" not in refreshed[0]      # the refresh really was due
    for r in answers[1:]:
        _withdrawn(r)
    assert user_accounts.allow_entry("thip@example.co.th", SEED)[1] == "ACTIVE"
    assert "new@example.co.th" not in {u["email"] for u in user_accounts.listed(SEED, None)}


def test_a_due_cookie_refresh_never_follows_a_401_or_a_route_that_set_the_cookie(on, monkeypatch):
    """Fix round 2: each of the two conditions on its own keeps the middleware from
    appending a re-signed cookie — read back through the same middleware class on a
    tiny app, with a session whose refresh is due."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    mini = FastAPI()

    @mini.get("/v1/refused")
    def refused():
        return JSONResponse({"code": "auth_required"}, status_code=401)

    @mini.get("/v1/sets-its-own")
    def sets_its_own():
        response = JSONResponse({"ok": True})
        response.headers["set-cookie"] = auth.cookie_header("route-value", auth.current_config(), 5)
        return response

    @mini.get("/v1/plain")
    def plain():
        return {"ok": True}

    mini.add_middleware(auth.AuthMiddleware, roster=lambda: [])
    session = auth.new_session("owner.test", "TEST", "OWNER", "owner", False, now=auth._now() - 120)

    def session_cookies(path):
        client = TestClient(mini)                        # a fresh jar: the stale session only
        client.cookies.set(auth.COOKIE, auth.sign_session(session, SECRET.encode()))
        r = client.get(path)
        return [h for h in r.headers.get_list("set-cookie") if h.startswith(auth.COOKIE + "=")]
    assert len(session_cookies("/v1/plain")) == 1                                # the refresh is due
    assert session_cookies("/v1/refused") == []
    own = session_cookies("/v1/sets-its-own")
    assert len(own) == 1 and own[0].startswith(auth.COOKIE + "=route-value;")


def test_an_officer_is_refused_the_user_list_before_any_uncached_read(on, monkeypatch):
    """Fix round 2: _admin checks the role before M1's fresh read, so a Google Officer's
    403 costs no database read — and the order tells nothing new: an Officer gets 403
    whether or not withdrawn, while a withdrawn Manager still gets 401."""
    clock = [9000.0]
    monkeypatch.setattr(user_accounts, "_clock", lambda: clock[0])
    thip, signed = _google(monkeypatch, "thip@example.co.th")
    lead, lead_signed = _google(monkeypatch, "lead@example.co.th")
    assert signed.status_code == lead_signed.status_code == 200
    assert thip.get("/v1/workbook").status_code == 200                      # the cache is warm
    reads = []
    real = user_accounts._read_rows
    monkeypatch.setattr(user_accounts, "_read_rows", lambda: reads.append(1) or real())
    for r in (thip.get("/v1/auth/users"),
              thip.post("/v1/auth/users", json={"email": "x@example.co.th", "role": "OFFICER", "officer": "thip"}),
              thip.post("/v1/auth/users/1:disable", json={})):
        assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    assert reads == []                                                          # no uncached read
    # withdrawn on another instance (this cache not told): the Officer still gets 403 ...
    stale = (user_accounts._CACHE["at"], user_accounts._CACHE["rows"])
    for email in ("thip@example.co.th", "lead@example.co.th"):
        user_accounts._memory_row("GOOGLE", email=email).update(
            role=SEED[email]["role"], officer=SEED[email]["officer"],
            disabled_at=user_accounts._now(), disabled_by="owner")
    r = thip.get("/v1/auth/users")
    assert (r.status_code, r.json()["code"]) == (403, "forbidden") and reads == []
    # ... and the Manager, whose role passes, is refused withdrawn by the fresh read
    user_accounts._CACHE["at"], user_accounts._CACHE["rows"] = stale
    _withdrawn(lead.get("/v1/auth/users"))
    assert reads == [1]


def test_start_up_errors_name_a_seed_entry_by_position_never_its_address(tmp_path):
    """M2: an uncaught AuthConfigError reaches stderr and Cloud Logging."""
    bad_role = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"},
                "thip@example.co.th": {"role": "ROOT", "officer": "thip"}}
    with pytest.raises(auth.AuthConfigError) as caught:
        auth.load_config(_environ(bad_role), env_file=tmp_path / "none")
    assert "AUTH_ALLOWLIST entry 2 (of 2) needs a role" in str(caught.value) and "@" not in str(caught.value)
    ghost = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"},
             "thip@example.co.th": {"role": "OFFICER", "officer": "ghost"}}
    config = auth.load_config(_environ(ghost), env_file=tmp_path / "none")
    with pytest.raises(auth.AuthConfigError) as caught:
        auth.check_officers(config, [{"uid": "owner", "role": "OWNER"}, {"uid": "nantapol", "role": "OFFICER"},
                                     {"uid": "settasak", "role": "MANAGER"}])
    message = str(caught.value)
    assert "AUTH_ALLOWLIST entry 2 (of 2) acts as officer ghost" in message and "@" not in message


def test_an_invitation_cannot_bind_an_officer_identity_above_the_inviter(on, monkeypatch):
    """M3: a Manager invited a MANAGER tied to officer `owner`, whose records would then
    read "by owner"."""
    manager = _password("manager.test", "manager-pw")
    r = manager.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "MANAGER", "officer": "owner"})
    assert (r.status_code, r.json()["code"], r.json()["extensions"]["role"]) == (403, "role_above_actor", "OWNER")
    assert r.json()["message_th"]
    # the same for a re-invitation of a disabled person
    owner = _password("owner.test", "owner-pw")
    assert owner.post("/v1/auth/users/%s:disable" % _uid(owner, "thip@example.co.th"), json={}).status_code == 200
    r = manager.post("/v1/auth/users", json={"email": "thip@example.co.th", "role": "OFFICER", "officer": "owner"})
    assert (r.status_code, r.json()["code"]) == (403, "role_above_actor")
    # an equal registry role is not above, an unknown officer keeps its own refusal, and an Owner may bind owner
    assert manager.post("/v1/auth/users", json={"email": "peer@example.co.th", "role": "OFFICER",
                                                "officer": "settasak"}).status_code == 201
    r = manager.post("/v1/auth/users", json={"email": "x@example.co.th", "role": "OFFICER", "officer": "ghost"})
    assert r.status_code == 422 and [e["code"] for e in r.json()["errors"]] == ["officer_unknown"]
    assert owner.post("/v1/auth/users", json={"email": "new@example.co.th", "role": "MANAGER",
                                              "officer": "owner"}).status_code == 201


def test_a_withdrawn_me_clears_the_cookie(on, monkeypatch):
    """M4: /v1/auth/me refused a withdrawn session but left the cookie in place."""
    thip, signed = _google(monkeypatch, "thip@example.co.th")
    assert signed.status_code == 200
    owner = _password("owner.test", "owner-pw")
    assert owner.post("/v1/auth/users/%s:disable" % _uid(owner, "thip@example.co.th"), json={}).status_code == 200
    _withdrawn(thip.get("/v1/auth/me"))
    assert auth.COOKIE not in thip.cookies
