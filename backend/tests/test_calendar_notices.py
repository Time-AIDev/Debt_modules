"""WP6 — personal notices: one owner, audited, never shared (F16)."""
import json as json_module
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app import audit_store, db, errors, migrate, notices
from app.main import app

client = TestClient(app)
NANTAPOL = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}
THIP = {"X-Volt-Officer": "thip", "X-Volt-Role": "OFFICER"}
MANAGER = {"X-Volt-Officer": "settasak", "X-Volt-Role": "MANAGER"}
WEEK = {"from": "2026-10-26", "to": "2026-11-01"}


def _raw_json(method, path, body, headers):
    """httpx's own json= encodes with ensure_ascii=False, so it raises client-side on a
    lone surrogate before a request is ever built — a real browser's fetch()+
    JSON.stringify() sends ASCII-escaped text instead (ensure_ascii's own encoding), so
    that is what this sends: pre-encoded ASCII bytes, exactly what json.loads() on the
    server reconstructs the lone surrogate FROM (I1)."""
    payload = json_module.dumps(body, ensure_ascii=True).encode("ascii")
    return client.request(method, path, content=payload, headers=dict(headers, **{"content-type": "application/json"}))


@pytest.fixture(autouse=True)
def _fresh_notices():
    notices.reset()
    yield
    notices.reset()


def _latest():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def _create(headers=NANTAPOL, **fields):
    body = dict({"title": "โทรตามสลิปเดือนกันยายน", "on": "2026-10-26"}, **fields)
    return client.post("/v1/calendar/notices", json=body, headers=headers)


def test_a_notice_is_created_for_its_owner_and_audited_without_its_words():
    r = _create(time="09:30", text="ขอสลิปจากลูกค้า")
    assert r.status_code == 201, r.json()
    n = r.json()["notice"]
    assert (n["owner"], n["on"], n["time"], n["done"]) == ("nantapol", "2026-10-26", "09:30", False)
    assert n["durable"] is False and n["note_th"]
    entry = _latest()
    assert entry["act"] == "NOTICE_CREATED" and (entry["subject_type"], entry["subject_uid"]) == ("notice", n["uid"])
    assert "สลิป" not in str(entry["detail"]) and entry["detail"]["on"] == "2026-10-26"


def test_the_calendar_serves_a_notice_to_its_owner_only_a_manager_included():
    uid = _create().json()["notice"]["uid"]
    mine = client.get("/v1/calendar", params=WEEK, headers=NANTAPOL).json()
    row = next(i for i in mine["items"] if i["kind"] == "NOTICE")
    assert row["facts"]["notice_uid"] == uid and row["source"] == "records.notice"
    assert mine["meta"]["notices"] == {"owner": "nantapol", "scope": "OWNER_ONLY", "durable": False, "total": 1}
    for other in (THIP, MANAGER):
        theirs = client.get("/v1/calendar", params=WEEK, headers=other).json()
        assert not any(i["kind"] == "NOTICE" for i in theirs["items"])
    filtered = client.get("/v1/calendar", params=dict(WEEK, officer="thip"), headers=NANTAPOL).json()
    assert any(i["kind"] == "NOTICE" for i in filtered["items"])       # a notice is not a case item
    # Fix round 1 / M4 (also tighten): a MANAGER filtering the board to nantapol's own
    # work (officer=nantapol) still gets none of nantapol's PERSONAL notices — ownership
    # is decided by the caller's own X-Volt-Officer, never by the officer filter param.
    as_manager_on_nantapol = client.get("/v1/calendar", params=dict(WEEK, officer="nantapol"),
                                        headers=MANAGER).json()
    assert not any(i["kind"] == "NOTICE" for i in as_manager_on_nantapol["items"])


def test_only_the_owner_edits_or_deletes_and_anyone_else_meets_a_404():
    uid = _create().json()["notice"]["uid"]
    refused_1 = client.put("/v1/calendar/notices/%s" % uid, json={"done": True}, headers=THIP)
    refused_2 = client.delete("/v1/calendar/notices/%s" % uid, headers=MANAGER)
    assert refused_1.status_code == 404 and refused_2.status_code == 404
    # Fix round 1 / M4 (also tighten): the 404 body is the ordinary not_found shape
    # (existence is never leaked — the same body a missing uid gets), and the notice
    # itself is UNCHANGED by either failed attempt.
    assert refused_1.json()["code"] == "not_found" and refused_1.json()["message_th"]
    assert refused_2.json()["code"] == "not_found" and refused_2.json()["message_th"]
    still_mine = next(i for i in client.get("/v1/calendar", params=WEEK, headers=NANTAPOL).json()["items"]
                      if i["kind"] == "NOTICE")
    assert still_mine["facts"]["title"] == "โทรตามสลิปเดือนกันยายน" and still_mine["facts"]["done"] is False
    r = client.put("/v1/calendar/notices/%s" % uid, json={"done": True, "title": "โทรแล้ว"}, headers=NANTAPOL)
    assert r.status_code == 200 and r.json()["notice"]["done"] is True and r.json()["notice"]["title"] == "โทรแล้ว"
    entry = _latest()
    assert entry["act"] == "NOTICE_UPDATED" and entry["detail"]["fields"] == ["done", "title"]
    assert "โทรแล้ว" not in str(entry["detail"])
    assert client.delete("/v1/calendar/notices/%s" % uid, headers=NANTAPOL).status_code == 200
    assert _latest()["act"] == "NOTICE_DELETED"
    assert client.put("/v1/calendar/notices/%s" % uid, json={"done": False}, headers=NANTAPOL).status_code == 404


def test_bad_fields_are_refused_by_pointer_and_an_unknown_field_is_not_dropped():
    def err(**body):
        r = client.post("/v1/calendar/notices", json=body, headers=NANTAPOL)
        assert r.status_code == 422, r.json()
        return r.json()["errors"][0]
    assert err(on="2026-10-26")["pointer"] == "/title"
    assert err(title="x", on="26/10/2026")["code"] == "date_invalid"
    assert err(title="x", on="2030-10-26")["code"] == "date_invalid"
    assert err(title="x", on="2026-10-26", time="25:00")["code"] == "time_invalid"
    assert err(title="x", on="2026-10-26", customer_uid="nobody")["code"] == "customer_unknown"
    assert err(title="x", on="2026-10-26", done="yes")["code"] == "done_invalid"
    assert err(title="x", on="2026-10-26", colour="red")["code"] == "field_unknown"
    assert err(title="x" * 121, on="2026-10-26")["code"] == "too_long"


def test_a_notice_with_no_owner_and_an_edit_that_changes_nothing_are_refused():
    r = client.post("/v1/calendar/notices", json={"title": "x", "on": "2026-10-26"}, headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 422 and r.json()["code"] == "owner_required" and r.json()["message_th"]
    uid = _create().json()["notice"]["uid"]
    r = client.put("/v1/calendar/notices/%s" % uid, json={}, headers=NANTAPOL)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "nothing_to_change"


def test_a_notice_may_name_a_customer_and_carries_their_name_on_the_calendar():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    assert _create(customer_uid=uid).status_code == 201
    row = next(i for i in client.get("/v1/calendar", params=WEEK, headers=NANTAPOL).json()["items"]
               if i["kind"] == "NOTICE")
    assert row["customer_uid"] == uid and row["display_name"]


def test_the_postgres_store_round_trips_and_keeps_owners_apart(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()        # the store opens its own conn.begin() (attachments ruling, 2026-09-15)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    day = date(2026, 10, 26)
    try:
        fields = notices.clean({"title": "t", "on": "2026-10-26", "time": "08:05"}, partial=False)
        n = notices.create("nantapol", fields, notices.new_uid())
        assert n["durable"] is True and (n["on"], n["time"]) == ("2026-10-26", "08:05")
        assert [r["uid"] for r in notices.list_for("nantapol", day, day)] == [n["uid"]]
        assert notices.list_for("thip", day, day) == []
        assert notices.update("thip", n["uid"], {"done": True}) is None
        assert notices.update("nantapol", n["uid"], {"done": True, "time": None})["done"] is True
        # Fix round 1 / M4(a): a mutant that drops "and owner = :owner" from the DELETE
        # would let thip delete nantapol's row. Asserted directly, then the row proven
        # still there before the rightful owner deletes it.
        assert notices.delete("thip", n["uid"]) is None
        assert [r["uid"] for r in notices.list_for("nantapol", day, day)] == [n["uid"]]
        assert notices.delete("nantapol", n["uid"])["uid"] == n["uid"]
        assert notices.list_for("nantapol", day, day) == []
    finally:
        pg_conn.execute(text("delete from records.notice"))
        pg_conn.commit()


# --- Fix round 1 (opus review of 47c4ab6): I1, M1-M6 ----------------------------------

def test_a_lone_surrogate_or_a_nul_is_refused_not_stored_memory_store():
    """I1: what JSON.stringify sends for a string cut mid-emoji (a lone surrogate) or a
    NUL must never reach the store. Left unchecked, the memory store accepted either
    and failed LATER, at render time — every subsequent GET /v1/calendar for that owner
    a text/plain 500 until restart. A mutant that dropped this guard fails here on
    POST and PUT, for both title and text."""
    bad_title = _raw_json("POST", "/v1/calendar/notices", {"title": "แจ้ง\ud800ลูกค้า", "on": "2026-10-26"}, NANTAPOL)
    assert bad_title.status_code == 422 and bad_title.json()["errors"][0]["code"] == "text_invalid"
    bad_text = client.post("/v1/calendar/notices", json={"title": "x", "on": "2026-10-26", "text": "a\x00b"},
                           headers=NANTAPOL)
    assert bad_text.status_code == 422 and bad_text.json()["errors"][0]["code"] == "text_invalid"
    assert client.get("/v1/calendar", params=WEEK, headers=NANTAPOL).status_code == 200

    uid = _create().json()["notice"]["uid"]
    bad_put_title = _raw_json("PUT", "/v1/calendar/notices/%s" % uid, {"title": "แจ้ง\ud800ลูกค้า"}, NANTAPOL)
    assert bad_put_title.status_code == 422 and bad_put_title.json()["errors"][0]["code"] == "text_invalid"
    bad_put_text = client.put("/v1/calendar/notices/%s" % uid, json={"text": "a\x00b"}, headers=NANTAPOL)
    assert bad_put_text.status_code == 422 and bad_put_text.json()["errors"][0]["code"] == "text_invalid"
    assert client.get("/v1/calendar", params=WEEK, headers=NANTAPOL).status_code == 200


def test_the_postgres_backstop_catches_a_lone_surrogate_that_bypassed_clean(pg_conn, monkeypatch):
    """I1 backstop: `clean()` is the primary guard for both POST and PUT, but the
    ruling asks for the `_transaction()` backstop to be proven independently — calling
    the store directly, as if clean()'s guard were bypassed, must still turn the
    driver's raw UnicodeEncodeError into an opaque internal_error, never let it
    escape as a bare 500 with a traceback."""
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        with pytest.raises(errors.Problem) as caught:
            notices.create("nantapol", {"title": "bad\ud800", "on": "2026-10-26"}, notices.new_uid())
        assert (caught.value.status, caught.value.code) == (500, "internal_error")
        assert "bad" not in str(vars(caught.value))
    finally:
        pg_conn.rollback()
        pg_conn.execute(text("delete from records.notice"))
        pg_conn.commit()


def test_no_refusal_echoes_a_submitted_value():
    """M1: no refusal MESSAGE carries a submitted value. A fake phone sent as
    customer_uid appears nowhere at all (the pointer is the fixed name
    "/customer_uid", never the value). An unknown field's own NAME necessarily appears
    in the pointer — that is the pointer's job, and M2 (separately) says how it is
    escaped — but a mutant that put it back into the prose message/message_th too
    (redundant with the pointer, and the shape M1 actually flagged) fails here."""
    r = client.post("/v1/calendar/notices", json={"title": "x", "on": "2026-10-26",
                                                   "customer_uid": "0812345678"}, headers=NANTAPOL)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "customer_unknown"
    assert "0812345678" not in str(r.json())
    r = client.post("/v1/calendar/notices", json={"title": "x", "on": "2026-10-26", "colour": "red"},
                    headers=NANTAPOL)
    assert r.status_code == 422
    err = r.json()["errors"][0]
    assert err["code"] == "field_unknown" and err["pointer"] == "/colour"
    assert "colour" not in err["message"] and "colour" not in err["message_th"]


def test_an_unknown_field_pointer_is_escaped_per_rfc_6901():
    """M2: '~' becomes '~0' and '/' becomes '~1' (escape order matters — '~' first, so
    a key's own literal '~1' does not get misread as an already-escaped '/'). A mutant
    that reverted to the bare "/" + key fails here."""
    r = client.post("/v1/calendar/notices", json={"title": "x", "on": "2026-10-26", "a/b~c": "y"}, headers=NANTAPOL)
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/a~1b~0c"


def test_a_malformed_uid_is_refused_before_any_audit_row_and_a_wellformed_unknown_one_is_audited():
    """M3: a path segment that does not look like a notice uid (a fake phone number
    typed or pasted into the URL) must never be quoted into the append-only audit log
    as subject_uid — it is refused BEFORE audit.describe runs. A mutant that removed
    the shape check, or that moved it after audit.describe, fails here: the base
    per-request row the middleware always appends would then carry act=NOTICE_UPDATED
    and subject_uid="0812345678" instead of act=None, subject_uid=None. A well-formed
    but simply unknown uid keeps today's behaviour: audited, then a 404."""
    bad = client.put("/v1/calendar/notices/0812345678", json={"done": True}, headers=NANTAPOL)
    assert bad.status_code == 404
    recent = _latest()
    assert recent["act"] is None and recent["subject_uid"] is None

    bad2 = client.delete("/v1/calendar/notices/0812345678", headers=NANTAPOL)
    assert bad2.status_code == 404
    recent2 = _latest()
    assert recent2["act"] is None and recent2["subject_uid"] is None

    unknown_but_shaped = "ntc-000000000000"
    r = client.put("/v1/calendar/notices/%s" % unknown_but_shaped, json={"done": True}, headers=NANTAPOL)
    assert r.status_code == 404
    entry = _latest()
    assert entry["act"] == "NOTICE_UPDATED" and entry["subject_uid"] == unknown_but_shaped


def test_a_down_database_refuses_every_notices_operation_with_the_retryable_503(monkeypatch):
    """M4(b): a mutant that dropped the SQLAlchemyError-to-Problem mapping in
    _transaction() would let a raw DatabaseUnreachable (or worse, an unhandled 500)
    escape instead of the same retryable 503 every other durable store in this
    codebase answers with."""
    monkeypatch.setattr(db, "configured", lambda: True)

    def down():
        raise db.DatabaseUnreachable("no route")
    monkeypatch.setattr(db, "connect", down)

    def problem(call):
        with pytest.raises(errors.Problem) as caught:
            call()
        return caught.value

    calls = (
        lambda: notices.create("nantapol", {"title": "t", "on": "2026-10-26"}, notices.new_uid()),
        lambda: notices.list_for("nantapol", date(2026, 10, 26), date(2026, 10, 26)),
        lambda: notices.update("nantapol", "ntc-000000000000", {"done": True}),
        lambda: notices.delete("nantapol", "ntc-000000000000"),
    )
    for call in calls:
        p = problem(call)
        assert (p.status, p.code, p.retryable) == (503, "notice_store_unreachable", True)


def test_a_forced_sql_error_is_an_opaque_internal_error_never_the_words(pg_conn, monkeypatch):
    """M4(b): a mutant that dropped the SQLAlchemyError mapping would let a raw driver
    exception — whose text quotes the bound title — escape as-is instead of the same
    opaque internal_error every other durable store in this codebase answers with."""
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    secret = "เอกลักษณ์ลับ12345"

    def boom(*a, **k):
        raise ProgrammingError("insert into records.notice ...", {"title": secret},
                               Exception("syntax error near %s" % secret))
    monkeypatch.setattr(pg_conn, "execute", boom)
    with pytest.raises(errors.Problem) as caught:
        notices.create("nantapol", {"title": secret, "on": "2026-10-26"}, notices.new_uid())
    assert (caught.value.status, caught.value.code) == (500, "internal_error")
    dump = repr(vars(caught.value))
    assert secret not in dump
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True


def test_the_audit_row_survives_even_when_the_write_itself_fails(monkeypatch):
    """M4(c): audit.describe() runs BEFORE notices.create() in the route, so a write
    that then fails must not erase the fact the act was attempted. A mutant that moved
    the audit.describe call to AFTER notices.create() fails here: the route would
    raise before describe() ever ran, and the base per-request row the middleware
    always appends would carry act=None instead of NOTICE_CREATED."""
    def boom(*a, **k):
        raise errors.internal_error()
    monkeypatch.setattr(notices, "create", boom)
    r = client.post("/v1/calendar/notices", json={"title": "x", "on": "2026-10-26"}, headers=NANTAPOL)
    assert r.status_code == 500
    entry = _latest()
    assert entry["act"] == "NOTICE_CREATED" and entry["outcome"] == "REFUSED"


def test_get_calendar_refuses_with_the_retryable_503_when_the_notice_store_is_down(monkeypatch):
    """C2b re-review ruling: GET /v1/calendar reads notices too (notices.list_for), so
    a notice store that is configured but unreachable must refuse the whole request
    with the same retryable 503 the notices write routes already answer with — not a
    bare 500, and not a silently empty notices list. Scoped to `notices.db` alone (a
    fake whose `configured()` is true and whose `connect()` raises
    `db.DatabaseUnreachable`) — never the global `app.db`, which `session._restore`
    calls uncaught — and undone automatically by `monkeypatch` at teardown."""
    class _NoticeStoreDown:
        DatabaseUnreachable = db.DatabaseUnreachable

        @staticmethod
        def configured():
            return True

        @staticmethod
        def connect():
            raise db.DatabaseUnreachable("test: notice store down")

    monkeypatch.setattr(notices, "db", _NoticeStoreDown)
    r = client.get("/v1/calendar", params=WEEK, headers=NANTAPOL)
    assert r.status_code == 503
    assert r.json()["code"] == "notice_store_unreachable" and r.json()["message_th"]


def test_migrate_apply_twice_keeps_the_notice_row_and_both_indexes(pg_conn):
    """M6: schema.sql's records.notice block is not a pinned schema test's concern
    (test_landing_schema.py only checks landing/app), so this proves it here — applied
    twice on a database already holding a row, the row and both indexes survive."""
    migrate.apply(pg_conn)
    pg_conn.commit()
    pg_conn.execute(text("insert into records.notice (uid, owner, title, on_date) values "
                         "('ntc-migrationcheck01', 'nantapol', 't', '2026-10-26')"))
    pg_conn.commit()
    try:
        migrate.apply(pg_conn)          # second apply, with a row already present
        pg_conn.commit()
        assert pg_conn.execute(text(
            "select uid from records.notice where uid = 'ntc-migrationcheck01'")).scalar() == "ntc-migrationcheck01"
        idx = {r[0] for r in pg_conn.execute(text(
            "select indexname from pg_indexes where schemaname = 'records' and tablename = 'notice'")).all()}
        assert {"notice_pkey", "notice_owner_on_idx"} <= idx
    finally:
        pg_conn.execute(text("delete from records.notice"))
        pg_conn.commit()
