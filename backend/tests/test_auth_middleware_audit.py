"""Final fix F-R1 (final-review-r1.md I-1, I-2): what the login middleware does to the
audit log, with login ON.

I1: the middleware re-serialises every POST body to put `by` in. It used to encode with
ensure_ascii=False + UTF-8, so a lone surrogate (what JSON.stringify sends for a string
cut mid-emoji) raised UnicodeEncodeError there: a text/plain 500, the route never ran,
and no audit row. Now the route's own validation refuses it 422 `text_invalid` and
audit_trail writes its REFUSED row; Thai text still arrives exactly as sent.

I2: a withdrawn or disabled session's 401, and the user list's own refusal (503), are
answered by AuthMiddleware, which sits outside audit_trail. On a path the log records
(audit.is_logged), the middleware now appends ONE REFUSED entry itself: actor the
session's subject, source SESSION, the status, and the refusal code. A request with no
session cookie at all stays unaudited (the F-R1 ruling), and an allowed request's rows
are unchanged.

Login is switched on per test through auth.set_config (never backend/.env, never
os.environ). Synthetic addresses only.
"""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import audit_store, auth, cases as cases_domain, user_accounts
from app.config import settings
from app.main import app

SECRET = "s" * 40
FAST = 1000
THIP = "thip@example.co.th"
SEED = {"boss@example.co.th": {"role": "OWNER", "officer": "owner"},
        "lead@example.co.th": {"role": "MANAGER", "officer": "settasak"},
        THIP: {"role": "OFFICER", "officer": "thip"}}
PHONE = "/v1/cases/by-customer/{customer_uid}/phone"
NOTICE = "/v1/calendar/notices"
MOVE = "/v1/calendar/next-actions/{customer_uid}:move"
PAYMENT_STATUS = "/v1/cases/by-customer/{customer_uid}/payment-status"
CASE_VIEW = "/v1/cases/by-customer/{customer_uid}"


def _environ():
    accounts = {
        "owner.test": {"hash": auth.hash_password("owner-pw", rounds=FAST), "role": "OWNER", "officer": "owner"},
        "officer.test": {"hash": auth.hash_password("officer-pw", rounds=FAST), "role": "OFFICER", "officer": "nantapol"},
    }
    return {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET, "AUTH_COOKIE_SECURE": "false",
            "AUTH_ALLOW_TEST_ACCOUNTS": "true", "AUTH_TEST_ACCOUNTS": json.dumps(accounts),
            "GOOGLE_CLIENT_ID": "client-123.apps.googleusercontent.com",
            "AUTH_ALLOWLIST": json.dumps(SEED)}


@pytest.fixture
def on(tmp_path):
    user_accounts.reset()
    auth.set_config(auth.load_config(_environ(), env_file=tmp_path / "none"))
    yield
    auth.reset()
    user_accounts.reset()


def _client():
    # The shared tester slot, so the domain reads this test makes outside a request
    # (cases.for_current) see the same book the requests act on.
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("volt_session", "shared")
    return client


def _password(username, password):
    client = _client()
    assert client.post("/v1/auth/password", json={"username": username, "password": password}).status_code == 200
    return client


def _google(monkeypatch, email):
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": email, "email_verified": True})
    client = _client()
    assert client.post("/v1/auth/google", json={"credential": "tok"}).status_code == 200
    return client


def _replay(cookie):
    """A fresh client carrying only the saved session cookie — a curl replay, which
    ignores the clearing Set-Cookie a refusal sends."""
    client = _client()
    client.cookies.set(auth.COOKIE, cookie)
    return client


def _head():
    rows = audit_store.read({}, limit=1, before_seq=None)
    return rows[0]["seq"] if rows else 0


def _rows_after(seq):
    return sorted((r for r in audit_store.read({}, limit=1000, before_seq=None) if r["seq"] > seq),
                  key=lambda r: r["seq"])


def _raw_post(client, path, body):
    """Pre-encoded ASCII JSON, the way fetch()+JSON.stringify sends a string cut
    mid-emoji: json.loads on the server reconstructs the lone surrogate from it."""
    payload = json.dumps(body, ensure_ascii=True).encode("ascii")
    return client.post(path, content=payload, headers={"content-type": "application/json"})


def _targets(client):
    """One customer for each act route, read through the signed-in client."""
    rows = client.get("/v1/workbook").json()["rows"]
    placeholder = next(r["customer"]["uid"] for r in rows
                       if r["customer"]["phone_on_file"] is False and r["case"]["payment_status"] != "CLOSED")
    late = next(r["customer"]["uid"] for r in rows if r["case"]["payment_status"] == "LATE")
    cs = cases_domain.for_current()
    bd = settings.business_date
    call = next(k for k in cs.cases.values()
                if k["next_action"] == "CALL" and k["next_action_on"] == str(bd) and not k["review_uid"])
    return {
        "phone": (PHONE, "/v1/cases/by-customer/%s/phone" % placeholder,
                  {"phone": "0899990301", "reason": "ลูกค้าให้เบอร์ใหม่"}),
        "notice": (NOTICE, NOTICE, {"title": "โทรตามสลิปเดือนกันยายน", "on": "2026-10-26"}),
        "move": (MOVE, "/v1/calendar/next-actions/%s:move" % call["customer_uid"],
                 {"on": str(bd + timedelta(days=4)), "reason": "ลูกค้าขอให้โทรวันอังคาร"}),
        "payment-status": (PAYMENT_STATUS, "/v1/cases/by-customer/%s/payment-status" % late,
                           {"code": "CURRENT", "reason": "ลูกค้าโอนครบแล้ว"}),
    }


# --- I1: the body re-encoding -------------------------------------------------------

def test_the_rewrite_is_ascii_json_that_decodes_to_the_same_thai_and_keeps_a_lone_surrogate():
    data = {"title": "โทรตามสลิป 🙂 เดือนกันยายน", "text": "ขอสลิปจากลูกค้า", "n": 3}
    rewritten = auth.AuthMiddleware._rewrite(NOTICE, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                             "OFFICER", "thip", "POST")
    rewritten.decode("ascii")                                    # nothing but ASCII bytes
    assert json.loads(rewritten) == dict(data, by="thip")
    cut = b'{"reason": "cut \\ud83d"}'
    rewritten = auth.AuthMiddleware._rewrite("/v1/x", cut, "OFFICER", "thip", "POST")
    assert json.loads(rewritten) == {"reason": "cut \ud83d", "by": "thip"}


def test_with_login_on_a_lone_surrogate_in_a_phone_body_is_the_routes_own_422_with_one_refused_row(on):
    officer = _password("officer.test", "officer-pw")
    target = _targets(officer)["phone"]
    before = _head()
    r = _raw_post(officer, target[1], {"phone": "0899990301", "reason": "cut \ud83d"})
    assert r.headers["content-type"].startswith("application/problem+json"), (r.status_code, r.text[:80])
    assert (r.status_code, r.json()["code"], r.json()["errors"][0]["pointer"]) == (422, "text_invalid", "/reason")
    rows = _rows_after(before)
    assert len(rows) == 1, rows
    assert (rows[0]["outcome"], rows[0]["status"], rows[0]["route_template"]) == ("REFUSED", 422, PHONE)
    assert (rows[0]["actor_claimed"], rows[0]["actor_source"]) == ("officer.test", "TEST_ACCOUNT")
    customer_uid = target[1].split("/")[4]
    rows = officer.get("/v1/workbook").json()["rows"]
    assert next(w for w in rows if w["customer"]["uid"] == customer_uid)["customer"]["phone_on_file"] is False


def test_with_login_on_a_lone_surrogate_in_a_notice_body_is_the_routes_own_422_with_one_refused_row(on):
    officer = _password("officer.test", "officer-pw")
    before = _head()
    r = _raw_post(officer, NOTICE, {"title": "t \ud83d", "on": "2026-10-26"})
    assert r.headers["content-type"].startswith("application/problem+json"), (r.status_code, r.text[:80])
    assert (r.status_code, r.json()["errors"][0]["code"]) == (422, "text_invalid")
    rows = _rows_after(before)
    assert len(rows) == 1, rows
    assert (rows[0]["outcome"], rows[0]["status"], rows[0]["route_template"]) == ("REFUSED", 422, NOTICE)
    week = officer.get("/v1/calendar", params={"from": "2026-10-26", "to": "2026-11-01"}).json()
    assert not [i for i in week["items"] if i["kind"] == "NOTICE"]


def test_with_login_on_a_thai_phone_reason_and_notice_are_stored_exactly_as_sent(on):
    officer = _password("officer.test", "officer-pw")
    target = _targets(officer)["phone"]
    reason = "ลูกค้าให้เบอร์ใหม่ โทรหลังเที่ยง 🙂"
    r = officer.post(target[1], json={"phone": "0899990301", "reason": reason})    # UTF-8 on the wire
    assert r.status_code == 200, r.json()
    assert r.json()["customer"]["phone_override"]["reason"] == reason
    assert audit_store.read({}, limit=1, before_seq=None)[0]["detail"]["reason"] == reason

    title, text = "โทรตามสลิปเดือนกันยายน 🙂", "ขอสลิปจากลูกค้า ก่อนบ่ายสอง"
    r = officer.post(NOTICE, json={"title": title, "text": text, "on": "2026-10-26"})
    assert r.status_code == 201, r.json()
    assert (r.json()["notice"]["title"], r.json()["notice"]["text"]) == (title, text)
    week = officer.get("/v1/calendar", params={"from": "2026-10-26", "to": "2026-11-01"}).json()
    served = next(i for i in week["items"] if i["kind"] == "NOTICE")
    assert (served["facts"]["title"], served["facts"]["text"]) == (title, text)


# --- I2: the middleware's own refusals ----------------------------------------------

@pytest.mark.parametrize("act", ["phone", "notice", "move", "payment-status"])
def test_a_disabled_google_cookie_replayed_on_an_act_route_leaves_one_refused_row(on, monkeypatch, act):
    thip = _google(monkeypatch, THIP)
    template, path, body = _targets(thip)[act]
    cookie = thip.cookies.get(auth.COOKIE)
    owner = _password("owner.test", "owner-pw")
    uid = next(u["uid"] for u in owner.get("/v1/auth/users").json()["users"] if u["email"] == THIP)
    assert owner.post("/v1/auth/users/%s:disable" % uid, json={}).status_code == 200

    for attempt in (1, 2):                                   # every replay is its own row
        before = _head()
        r = _replay(cookie).post(path, json=body)
        assert (r.status_code, r.json()["code"], r.json()["extensions"]["reason"]) == \
            (401, "auth_required", "account_withdrawn"), (attempt, r.json())
        rows = _rows_after(before)
        assert len(rows) == 1, (attempt, rows)
        row = rows[0]
        assert (row["outcome"], row["status"], row["error_code"]) == ("REFUSED", 401, "account_withdrawn")
        assert (row["actor_claimed"], row["actor_source"]) == (THIP, "SESSION")
        assert (row["verb"], row["route_template"], row["act"]) == ("POST", template, None)
        assert (row["subject_type"], row["subject_uid"], row["detail"]) == (None, None, {})
        assert row["request_id"] == r.headers["x-request-id"] and row["session_id"] == "shared"
    assert audit_store.verify()["ok"] is True


def test_a_request_with_no_session_cookie_leaves_no_row(on, monkeypatch):
    thip = _google(monkeypatch, THIP)
    targets = _targets(thip)
    anonymous = _client()
    before = _head()
    for _template, path, body in targets.values():
        r = anonymous.post(path, json=body)
        assert (r.status_code, r.json()["code"]) == (401, "auth_required")
        assert "reason" not in r.json()["extensions"]
    assert _rows_after(before) == []


def test_an_allowed_session_still_writes_exactly_its_own_rows(on, monkeypatch):
    thip = _google(monkeypatch, THIP)
    # AUTHORISED TEST EDIT 43 (R-B, feedback-r2 TASK-220): the manual payment status
    # is a Manager's audited exception now, so that one act is posted by a Manager's
    # session; an officer's session is refused by the route itself (covered in
    # test_payment_status_adjust.py's own gate test).
    lead = _google(monkeypatch, "lead@example.co.th")
    for name, (template, path, body) in _targets(thip).items():
        actor_client = lead if name == "payment-status" else thip
        expected_actor = "lead@example.co.th" if name == "payment-status" else THIP
        before = _head()
        r = actor_client.post(path, json=body)
        assert r.status_code in (200, 201), (name, r.json())
        rows = _rows_after(before)
        assert len(rows) == 1, (name, rows)
        assert (rows[0]["outcome"], rows[0]["status"], rows[0]["route_template"]) == ("OK", r.status_code, template)
        assert (rows[0]["actor_claimed"], rows[0]["actor_source"], rows[0]["error_code"]) == (expected_actor, "SESSION", None)
        assert rows[0]["act"] is not None


def test_officer_session_signs_unpaid_termination_as_itself(on, monkeypatch):
    thip = _google(monkeypatch, THIP)
    uid = next(c["customer_uid"] for c in cases_domain.for_current().cases.values()
               if c["customer_no"] == "C-002032")
    before = _head()
    response = thip.post("/v1/cases/by-customer/%s:terminate" % uid,
                         headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"},
                         json={"cause": "DEFAULT", "reason": "ยุติขณะมียอดคงเหลือ", "by": "owner"})
    assert response.status_code == 200, response.json()
    rows = _rows_after(before)
    assert len(rows) == 1
    assert (rows[0]["actor_claimed"], rows[0]["actor_source"], rows[0]["actor_role"]) == (
        THIP, "SESSION", "OFFICER")
    assert response.json()["termination"]["by"] == "thip"


def test_a_withdrawn_cookie_on_the_logged_case_read_is_recorded_and_an_unlogged_read_is_not(on, monkeypatch):
    thip = _google(monkeypatch, THIP)
    customer_uid = _targets(thip)["payment-status"][1].split("/")[4]
    cookie = thip.cookies.get(auth.COOKIE)
    owner = _password("owner.test", "owner-pw")
    uid = next(u["uid"] for u in owner.get("/v1/auth/users").json()["users"] if u["email"] == THIP)
    assert owner.post("/v1/auth/users/%s:disable" % uid, json={}).status_code == 200
    before = _head()
    assert _replay(cookie).get("/v1/workbook").status_code == 401
    assert _rows_after(before) == []
    r = _replay(cookie).get("/v1/cases/by-customer/%s" % customer_uid)
    assert r.status_code == 401
    rows = _rows_after(before)
    assert len(rows) == 1, rows
    # The same shape audit_trail gives a refused case read: the act it was.
    assert (rows[0]["verb"], rows[0]["route_template"], rows[0]["act"]) == ("GET", CASE_VIEW, "CASE_VIEWED")
    assert (rows[0]["outcome"], rows[0]["status"], rows[0]["error_code"]) == ("REFUSED", 401, "account_withdrawn")


@pytest.mark.parametrize("refusal", [user_accounts.list_unreachable, user_accounts.list_not_migrated])
def test_the_user_list_refusal_on_an_act_route_leaves_one_refused_row(on, monkeypatch, refusal):
    thip = _google(monkeypatch, THIP)
    template, path, body = _targets(thip)["phone"]

    def down():
        raise refusal()
    monkeypatch.setattr(user_accounts, "_read_rows", down)
    user_accounts.forget()
    code = refusal().code
    before = _head()
    assert thip.get("/v1/workbook").json()["code"] == code        # an unlogged read: no row
    assert _rows_after(before) == []
    r = thip.post(path, json=body)
    assert (r.status_code, r.json()["code"]) == (503, code)
    rows = _rows_after(before)
    assert len(rows) == 1, rows
    assert (rows[0]["outcome"], rows[0]["status"], rows[0]["error_code"]) == ("REFUSED", 503, code)
    assert (rows[0]["actor_claimed"], rows[0]["actor_source"], rows[0]["route_template"]) == (THIP, "SESSION", template)


def test_an_audit_store_that_fails_still_refuses_and_counts_a_gap_that_names_no_address(on, monkeypatch, capfd):
    thip = _google(monkeypatch, THIP)
    path, body = _targets(thip)["notice"][1:]
    cookie = thip.cookies.get(auth.COOKIE)
    owner = _password("owner.test", "owner-pw")
    uid = next(u["uid"] for u in owner.get("/v1/auth/users").json()["users"] if u["email"] == THIP)
    assert owner.post("/v1/auth/users/%s:disable" % uid, json={}).status_code == 200

    def broken(fields):
        raise RuntimeError("DETAIL:  Failing row contains (%s)." % fields["actor_claimed"])
    monkeypatch.setattr(audit_store, "append", broken)
    gaps = len(audit_store.MEMORY.gaps())
    capfd.readouterr()
    r = _replay(cookie).post(path, json=body)
    assert (r.status_code, r.json()["extensions"]["reason"]) == (401, "account_withdrawn")
    assert len(audit_store.MEMORY.gaps()) == gaps + 1
    assert "example.co.th" not in json.dumps(audit_store.MEMORY.gaps())
    out, err = capfd.readouterr()
    assert "example.co.th" not in out + err
