"""A phone number a person enters for a customer — Feedback Round 1 / WP9 (design F9 (a)).

Any role may set it, with a reason; it is audited PHONE_SET with "set"/"cleared" and
never the number; every read (the work item, the case detail) serves the masked string
plus `phone_revealable`; the sheet's masked string is never touched
(test_journey_rebuild.py:63). Since 2026-09-20 the full number is NOT served on any
list or case detail either — `POST /v1/cases/by-customer/{uid}/phone:reveal` answers
it, audited PHONE_REVEALED with source and kind, never the digits.
"""
import contextvars
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import audit_store, customer_contact, db, errors, migrate
from app.cases import CaseError
from app.main import app

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "thip"}


def _placeholder_customer():
    """A sheet customer whose import carried no phone (159 of 212)."""
    rows = client.get("/v1/workbook").json()["rows"]
    return next(r["customer"]["uid"] for r in rows
                if r["customer"]["phone_on_file"] is False and r["case"]["payment_status"] != "CLOSED")


def _latest_audit():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def _post(uid, body):
    return client.post("/v1/cases/by-customer/%s/phone" % uid, headers=OFFICER, json=body)


# --- the shape rule --------------------------------------------------------------------

@pytest.mark.parametrize("raw, e164, kind, shown", [
    ("0812345678", "+66812345678", "MOBILE", "081-234-5678"),
    ("081-234-5678", "+66812345678", "MOBILE", "081-234-5678"),
    ("+66 81 234 5678", "+66812345678", "MOBILE", "081-234-5678"),
    ("66912345678", "+66912345678", "MOBILE", "091-234-5678"),
    ("06.1234.5678", "+66612345678", "MOBILE", "061-234-5678"),
    ("(02) 123-4567", "+6621234567", "LANDLINE", "02-123-4567"),
    ("053123456", "+6653123456", "LANDLINE", "053-123-456"),
    ("+6674123456", "+6674123456", "LANDLINE", "074-123-456"),
    # Fix round 1 / M2: a redundant national 0 kept after the country code.
    ("+66 (0)81 234 5678", "+66812345678", "MOBILE", "081-234-5678"),
    ("+660812345678", "+66812345678", "MOBILE", "081-234-5678"),
])
def test_a_thai_mobile_or_landline_is_normalised_to_e164(raw, e164, kind, shown):
    assert customer_contact.normalise(raw) == (e164, kind)
    assert customer_contact.display(e164, kind) == shown


@pytest.mark.parametrize("raw", ["12345", "+14155552671", "0112345678", "08123456789", "812345678",
                                 "0812345abc", "0012345678", "",
                                 # Fix round 1 / I2: a mixed-script number — \d with no
                                 # flag matches any Unicode digit, Thai digits included
                                 # (the reviewer's probe, verbatim).
                                 "08" + "๙๙๙๙๐๐๐๔"])
def test_anything_else_is_refused_without_echoing_what_was_typed(raw):
    with pytest.raises(CaseError) as caught:
        customer_contact.normalise(raw)
    assert caught.value.code == "phone_invalid"
    assert caught.value.extra["pointer"] == "/phone"
    if raw:
        assert raw not in caught.value.detail and raw not in caught.value.message_th


# --- the route and every read -----------------------------------------------------------

def test_a_person_sets_a_number_and_every_read_serves_it_first():
    uid = _placeholder_customer()
    r = _post(uid, {"phone": "081-234-5678", "reason": "ลูกค้าให้เบอร์ทางไลน์"})
    assert r.status_code == 200, r.json()
    served = r.json()["customer"]
    assert served["uid"] == uid
    assert served["phone_revealable"] is True and served["phone_on_file"] is True
    assert "phone_e164" not in served          # the number never rides the response
    assert served["phone_on_sheet"] is False and served["phone_masked"] == "xxx-xxx-xxxx"
    assert served["phone_override"] == {
        "kind": "MOBILE", "set_by": "thip",
        "set_at": served["phone_override"]["set_at"], "reason": "ลูกค้าให้เบอร์ทางไลน์", "durable": False,
        "note_th": customer_contact.NOT_DURABLE_TH, "note_en": customer_contact.NOT_DURABLE_EN}
    assert "phone_e164" not in served["phone_override"] and "display" not in served["phone_override"]
    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    for customer in (detail["work_item"]["customer"], detail["customer"]):
        assert customer["phone_revealable"] is True and customer["phone_on_file"] is True
        assert "phone_e164" not in customer
        assert "x" in customer["phone_masked"]
    row = next(r for r in client.get("/v1/workbook").json()["rows"] if r["customer"]["uid"] == uid)
    assert row["customer"]["phone_revealable"] is True
    assert "display" not in row["customer"]["phone_override"]
    listed = [i for i in client.get("/v1/working-list").json()["items"] if i["customer"]["uid"] == uid]
    assert listed and all(i["customer"]["phone_revealable"] is True for i in listed)
    assert all("phone_e164" not in i["customer"] for i in listed)


def test_the_reveal_route_answers_the_number_once_and_audits_it():
    """The one audited door. PHONE_REVEALED names source and kind and never the
    digits — the audit rule PHONE_SET already follows."""
    uid = _placeholder_customer()
    assert _post(uid, {"phone": "081-234-5678", "reason": "first"}).status_code == 200
    r = client.post("/v1/cases/by-customer/%s/phone:reveal" % uid, headers=OFFICER)
    assert r.status_code == 200, r.json()
    revealed = r.json()["customer"]
    assert revealed["uid"] == uid
    assert revealed["phone_e164"] == "+66812345678"
    assert revealed["phone_display"] == "081-234-5678" and revealed["kind"] == "MOBILE"
    assert revealed["source"] == "OVERRIDE"
    entry = _latest_audit()
    assert entry["act"] == "PHONE_REVEALED" and (entry["subject_type"], entry["subject_uid"]) == ("customer", uid)
    assert entry["detail"] == {"kind": "MOBILE", "source": "OVERRIDE"}
    flat = json.dumps(entry, ensure_ascii=False)
    for fragment in ("0812345678", "812345678", "234-5678", "+66"):
        assert fragment not in flat
    # Every read is its own act; a second open is a second row, not a memo.
    assert client.post("/v1/cases/by-customer/%s/phone:reveal" % uid, headers=OFFICER).status_code == 200
    assert _latest_audit()["act"] == "PHONE_REVEALED"
    assert client.post("/v1/cases/by-customer/no-such-customer/phone:reveal", headers=OFFICER).status_code == 404


def test_the_reveal_route_answers_an_imported_number_too():
    """Odoo (and, after the 2026-09-20 pipeline fix, the sheet) lands a number with
    the run; it reveals with source IMPORT, formatted when it parses."""
    item = next(i for i in client.get("/v1/working-list").json()["items"]
                if i["customer"]["phone_revealable"] and i["customer"]["phone_override"] is None)
    uid = item["customer"]["uid"]
    r = client.post("/v1/cases/by-customer/%s/phone:reveal" % uid, headers=OFFICER)
    assert r.status_code == 200, r.json()
    revealed = r.json()["customer"]
    assert revealed["source"] == "IMPORT" and revealed["phone_e164"]
    assert "x" in item["customer"]["phone_masked"]      # the served mask stays the display
    assert _latest_audit()["detail"] == {"kind": revealed["kind"], "source": "IMPORT"}


def test_a_customer_nobody_touched_serves_exactly_what_the_import_said():
    uid = _placeholder_customer()
    customer = client.get("/v1/cases/by-customer/%s" % uid).json()["work_item"]["customer"]
    assert customer["phone_override"] is None and customer["phone_revealable"] is False
    assert "phone_e164" not in customer
    assert customer["phone_on_file"] is False and customer["phone_on_sheet"] is False
    nothing = client.post("/v1/cases/by-customer/%s/phone:reveal" % uid, headers=OFFICER)
    assert (nothing.status_code, nothing.json()["code"], nothing.json()["error_id"]) == (
        404, "phone_not_on_file", "DEBT-COL-0472")


def test_the_audit_row_says_set_and_never_carries_the_number():
    uid = _placeholder_customer()
    assert _post(uid, {"phone": "0812345678", "reason": "โทรเข้ามาจากเบอร์ 081-234-5678 วันที่ 2026-10-23"}).status_code == 200
    entry = _latest_audit()
    assert entry["act"] == "PHONE_SET" and (entry["subject_type"], entry["subject_uid"]) == ("customer", uid)
    assert entry["detail"]["phone"] == "set" and entry["detail"]["kind"] == "MOBILE"
    assert entry["detail"]["reason"] == "โทรเข้ามาจากเบอร์ [ตัดเบอร์ออก] วันที่ 2026-10-23"
    flat = json.dumps(entry, ensure_ascii=False)
    for fragment in ("0812345678", "812345678", "234-5678", "+66"):
        assert fragment not in flat


# --- I3: _without_numbers joins digits across any short run of separators ----------------

@pytest.mark.parametrize("separator", ["/", ",", "_", "–", "—", " - "])
def test_without_numbers_joins_a_run_across_any_short_separator(separator):
    reason = "โทร 081%s234%s5678 ครับ" % (separator, separator)
    redacted = customer_contact._without_numbers(reason)
    assert redacted == "โทร [ตัดเบอร์ออก] ครับ"
    assert "081" not in redacted and "234" not in redacted and "5678" not in redacted


@pytest.mark.parametrize("separator", ["/", ",", "_", "–", "—", " - "])
def test_without_numbers_strips_thai_digits_too(separator):
    reason = "โทร ๐๘๑%s๒๓๔%s๕๖๗๘ ครับ" % (separator, separator)
    redacted = customer_contact._without_numbers(reason)
    assert redacted == "โทร [ตัดเบอร์ออก] ครับ"


def test_without_numbers_over_strips_a_long_id_and_that_is_accepted():
    """A 13-digit id, not a phone number — deliberately over-stripped (I3's ruling:
    a confident redaction beats a missed number)."""
    reason = "เลขที่ 1-2345-67890-12-3 อ้างอิง"
    redacted = customer_contact._without_numbers(reason)
    assert redacted == "เลขที่ [ตัดเบอร์ออก] อ้างอิง"


def test_without_numbers_leaves_a_short_run_alone():
    """An eight-digit date is still left alone — the ≥9-digit count is unchanged."""
    assert customer_contact._without_numbers("วันที่ 2026-10-23") == "วันที่ 2026-10-23"


def test_refusals_name_the_field_and_write_nothing():
    uid = _placeholder_customer()
    no_reason = _post(uid, {"phone": "0812345678", "reason": "  "})
    assert (no_reason.status_code, no_reason.json()["code"]) == (422, "reason_required")
    assert no_reason.json()["errors"][0]["pointer"] == "/reason"
    bad = _post(uid, {"phone": "12345", "reason": "x"})
    assert (bad.status_code, bad.json()["code"], bad.json()["error_id"]) == (422, "phone_invalid", "DEBT-COL-0463")
    assert bad.json()["errors"][0]["pointer"] == "/phone" and bad.json()["message_th"] == customer_contact.INVALID_TH
    nothing_to_clear = _post(uid, {"phone": None, "reason": "x"})
    assert (nothing_to_clear.status_code, nothing_to_clear.json()["code"]) == (409, "phone_unchanged")
    assert customer_contact._HISTORY == []
    assert _post(uid, {"phone": "0812345678", "reason": "ใหม่"}).status_code == 200
    same = _post(uid, {"phone": "+66 81 234 5678", "reason": "ซ้ำ"})
    assert (same.status_code, same.json()["code"], same.json()["error_id"]) == (409, "phone_unchanged", "DEBT-COL-0464")
    assert len(customer_contact._HISTORY) == 1
    assert _post("no-such-customer", {"phone": "0812345678", "reason": "x"}).status_code == 404


def test_a_new_number_replaces_the_old_and_clearing_puts_the_import_answer_back():
    uid = _placeholder_customer()
    assert _post(uid, {"phone": "0812345678", "reason": "แรก"}).status_code == 200
    assert _post(uid, {"phone": "021234567", "reason": "เบอร์บ้าน"}).json()["customer"]["phone_override"]["kind"] == "LANDLINE"
    cleared = _post(uid, {"phone": "", "reason": "ลูกค้าขอให้ลบ"})
    assert cleared.status_code == 200
    served = cleared.json()["customer"]
    assert served["phone_override"] is None and served["phone_revealable"] is False
    assert "phone_e164" not in served and served["phone_on_file"] is False
    assert _latest_audit()["detail"]["phone"] == "cleared"
    assert [(r["phone_e164"], r["active"]) for r in customer_contact._HISTORY] == [
        ("+66812345678", False), ("+6621234567", False), (None, False)]


# --- M1: every SERVED reason is redacted and capped; the stored one is not ---------------

def test_every_served_reason_is_redacted_and_capped_but_the_stored_one_is_not():
    uid = _placeholder_customer()
    long_reason = ("ลูกค้าโทรจากเบอร์ 081-234-5678 " + ("ก" * 250))
    assert _post(uid, {"phone": "0812345678", "reason": long_reason}).status_code == 200

    row = next(r for r in client.get("/v1/workbook").json()["rows"] if r["customer"]["uid"] == uid)
    list_reason = row["customer"]["phone_override"]["reason"]
    assert "081-234-5678" not in list_reason and "234-5678" not in list_reason
    assert list_reason.startswith("ลูกค้าโทรจากเบอร์ [ตัดเบอร์ออก]")
    assert len(list_reason) == customer_contact.REASON_SERVED_MAX + 1 and list_reason.endswith("…")

    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    for customer in (detail["work_item"]["customer"], detail["customer"]):
        assert customer["phone_override"]["reason"] == list_reason

    # The stored row keeps the reason exactly as typed — unredacted, untruncated.
    stored = customer_contact._HISTORY[-1]["reason"]
    assert stored == long_reason and "081-234-5678" in stored and len(stored) > customer_contact.REASON_SERVED_MAX


def test_a_pre_install_case_serves_the_same_phone_keys():
    from app.config import settings
    rows = client.get("/v1/pipeline?all=true").json()["items"]
    item = next(r for r in rows if not r["released_at"])
    client.post("/v1/pipeline/%s/gates/down-payment" % item["uid"], json={"receipt_ref": "slip-y", "amount": "5000"})
    client.post("/v1/pipeline/%s/gates/epc-confirmed" % item["uid"], json={"confirmed_on": str(settings.business_date)})
    # Delta-100 D2h: contract_signed is the third condition and passes by evidence only.
    client.post("/v1/pipeline/%s/conditions/contract_signed/evidence" % item["uid"],
                json={"note": "สำเนาสัญญาที่ลงนามทั้งสองฝ่าย", "by": "thip"})
    assert client.post("/v1/pipeline/%s:release" % item["uid"], json={}, headers=OFFICER).status_code == 201
    uid = item["customer_uid"]
    assert _post(uid, {"phone": "021234567", "reason": "ก่อนติดตั้ง"}).status_code == 200
    customer = client.get("/v1/cases/by-customer/%s" % uid).json()["customer"]
    assert customer["phone_revealable"] is True and customer["phone_override"]["kind"] == "LANDLINE"
    assert "phone_e164" not in customer and "display" not in customer["phone_override"]
    assert customer["phone_masked"] is None and customer["phone_on_sheet"] is False


def test_any_role_may_set_it():
    uid = _placeholder_customer()
    for n, role in enumerate(("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS")):
        r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": role},
                        json={"phone": "08123456%02d" % n, "reason": role})
        assert r.status_code == 200, (role, r.json())


# --- one read per request -----------------------------------------------------------------

def test_the_table_is_read_once_per_request_not_once_per_row(monkeypatch):
    loads = []
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(customer_contact, "_load_active", lambda: loads.append(1) or {})

    def one_request():
        for n in range(212):
            customer_contact.active_for("cu-%d" % n)

    contextvars.copy_context().run(one_request)
    contextvars.copy_context().run(one_request)
    assert len(loads) == 2


def test_a_failed_write_never_carries_the_number_into_the_error(monkeypatch):
    """Fix round 1 / I1: SQLAlchemy puts the bound parameters in its message, and an
    unhandled error's traceback is logged — a bare RuntimeError used to be a plain-text
    500. The write now answers the same opaque Problem user_accounts.py's own writes
    do: internal_error(), unchained, with nothing in its body but the fixed sentence."""
    from sqlalchemy.exc import IntegrityError

    class Refusing:
        def begin(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, params=None):
            if params and "p" in params:
                raise IntegrityError(str(statement), params, Exception("duplicate key"))
            return _ScalarFalse()          # the _table_missing probe, inside except

        def close(self):
            pass

    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: Refusing())
    monkeypatch.setattr(customer_contact, "_load_active", lambda: {})
    with pytest.raises(errors.Problem) as caught:
        contextvars.copy_context().run(customer_contact.set_phone, "cu-x", "0812345678", "thip", "x")
    assert caught.value.code == "internal_error" and caught.value.status == 500
    flat = caught.value.response().body.decode("utf-8")
    assert "812345678" not in flat and "IntegrityError" not in flat
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True


def test_a_lost_connection_answers_a_retryable_503(monkeypatch):
    """Fix round 1 / I1: a connection lost mid-write (or one that never opens —
    db.DatabaseUnreachable) is the SAME retryable 503 a reachability problem gets
    everywhere else in the backend — never the opaque internal_error()."""
    from sqlalchemy.exc import OperationalError

    class DroppedMidQuery:
        def begin(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, params=None):
            if params and "p" in params:
                raise OperationalError(str(statement), params, Exception("server closed the connection unexpectedly"))

        def close(self):
            pass

    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: DroppedMidQuery())
    monkeypatch.setattr(customer_contact, "_load_active", lambda: {})
    with pytest.raises(errors.Problem) as caught:
        contextvars.copy_context().run(customer_contact.set_phone, "cu-y", "0812345678", "thip", "x")
    assert (caught.value.status, caught.value.retryable) == (503, True)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True

    def _never_connects():
        raise db.DatabaseUnreachable("no route to host")

    monkeypatch.setattr(db, "connect", _never_connects)
    with pytest.raises(errors.Problem) as caught2:
        contextvars.copy_context().run(customer_contact.set_phone, "cu-z", "0812345678", "thip", "x")
    assert (caught2.value.status, caught2.value.retryable) == (503, True)
    assert caught2.value.__cause__ is None and caught2.value.__suppress_context__ is True


# --- I2: every column is validated before a row carrying a number reaches SQL ------------

def test_a_non_string_actor_is_refused_without_reaching_sql(monkeypatch):
    calls = []
    monkeypatch.setattr(db, "configured", lambda: True)

    class Unreached:
        def begin(self):
            calls.append(1)
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, params=None):
            calls.append(1)

        def close(self):
            pass

    monkeypatch.setattr(db, "connect", lambda: Unreached())
    monkeypatch.setattr(customer_contact, "_load_active", lambda: {})
    for bad_by in (["thip"], {"name": "thip"}, "", "   ", None, 42):
        with pytest.raises(CaseError) as caught:
            contextvars.copy_context().run(customer_contact.set_phone, "cu-actor", "0812345678", bad_by, "x")
        assert caught.value.code == "phone_actor_invalid"
        assert caught.value.extra["pointer"] == "/by"
    assert calls == []


# --- R1: a lone surrogate or NUL in phone/reason/by (fix round 2) ------------------------

def _raw_post(uid, raw_json):
    """p3_surrogate.py's own technique: the RAW json text, with a JSON unicode
    escape written literally (\\ud83d — six ASCII characters), sent as bytes. This
    is exactly what JSON.stringify sends for a string cut mid-emoji, and it never
    asks Python to encode an actual surrogate character on the way out."""
    # AUTHORISED TEST EDIT 44: FastAPI >=0.132 refuses a JSON body with no Content-Type.
    return client.post("/v1/cases/by-customer/%s/phone" % uid, headers={**OFFICER, "Content-Type": "application/json"}, content=raw_json.encode())


def test_a_lone_surrogate_in_reason_is_refused_text_invalid():
    uid = _placeholder_customer()
    r = _raw_post(uid, '{"phone": "0899990301", "reason": "\\u0e42\\u0e17\\u0e23 0899990399 \\ud83d"}')
    assert (r.status_code, r.json()["code"], r.json()["error_id"]) == (422, "text_invalid", "DEBT-COL-0466")
    assert r.json()["errors"][0]["pointer"] == "/reason"
    assert r.json()["message_th"] == customer_contact.TEXT_INVALID_TH
    assert customer_contact._HISTORY == []


def test_a_nul_in_by_is_refused_text_invalid():
    uid = _placeholder_customer()
    r = _raw_post(uid, '{"phone": "0899990302", "reason": "probe", "by": "a\\u0000b"}')
    assert (r.status_code, r.json()["code"]) == (422, "text_invalid")
    assert r.json()["errors"][0]["pointer"] == "/by"
    assert customer_contact._HISTORY == []


def test_a_nul_in_reason_is_refused_text_invalid_the_same_as_a_surrogate():
    """R1's finding: a NUL used to behave differently per store (Postgres 500,
    memory 200). Both now refuse identically, before either store is touched."""
    uid = _placeholder_customer()
    r = _raw_post(uid, '{"phone": "0899990303", "reason": "pro\\u0000be"}')
    assert (r.status_code, r.json()["code"]) == (422, "text_invalid")
    assert r.json()["errors"][0]["pointer"] == "/reason"


def test_after_a_refused_dangerous_field_every_read_still_answers_200():
    uid = _placeholder_customer()
    assert _raw_post(uid, '{"phone": "0899990304", "reason": "x\\ud83dy"}').status_code == 422
    assert _raw_post(uid, '{"phone": "0899990305", "reason": "probe", "by": "\\u0000"}').status_code == 422
    for path in ("/v1/today", "/v1/workbook", "/v1/working-list", "/v1/cases/by-customer/%s" % uid):
        assert client.get(path).status_code == 200


def test_a_dangerous_field_is_refused_the_same_way_with_a_database_configured(pg_conn, pg_url, monkeypatch):
    """Both stores (R1's own framing): the shared validation runs before the
    `if not db.configured()` branch, so a database configured and reachable refuses
    identically and writes no row."""
    migrate.apply(pg_conn)
    pg_conn.commit()
    engine = create_engine(pg_url, future=True)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", engine.connect)
    try:
        with pytest.raises(CaseError) as caught:
            contextvars.copy_context().run(customer_contact.set_phone, "cu-r1-pg", "0812345678", "thip", "x\ud83dy")
        assert caught.value.code == "text_invalid" and caught.value.extra["pointer"] == "/reason"
        with pytest.raises(CaseError) as caught2:
            contextvars.copy_context().run(customer_contact.set_phone, "cu-r1-pg", "0812345678", "a\x00b", "probe")
        assert caught2.value.code == "text_invalid" and caught2.value.extra["pointer"] == "/by"
        rows = pg_conn.execute(text("select count(*) from records.customer_contact "
                                    "where customer_uid = 'cu-r1-pg'")).scalar()
        assert rows == 0
    finally:
        pg_conn.execute(text("delete from records.customer_contact"))
        pg_conn.commit()
        engine.dispose()


class _ScalarFalse:
    """A `to_regclass(...) is null` answer of False — the table exists — so
    `_table_missing`'s own check (run inside the except handler on the SAME mock
    connection) does not misreport a driver-raised UnicodeError as a missing table."""
    def scalar(self):
        return False


def test_a_forced_unicode_error_on_write_answers_a_problem_not_text_plain(monkeypatch):
    """R1: `_transaction`'s claim that no driver exception ever leaves it was false
    for a UnicodeError — the class SQLAlchemyError does not cover."""
    class RaisesUnicodeError:
        def begin(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, params=None):
            if params and "p" in params:
                raise UnicodeEncodeError("utf-8", "\ud83d", 0, 1, "surrogates not allowed")
            return _ScalarFalse()          # the _table_missing probe, inside except

        def close(self):
            pass

    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: RaisesUnicodeError())
    monkeypatch.setattr(customer_contact, "_load_active", lambda: {})
    with pytest.raises(errors.Problem) as caught:
        contextvars.copy_context().run(customer_contact.set_phone, "cu-uce", "0812345678", "thip", "x")
    assert caught.value.code == "internal_error" and caught.value.status == 500
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True


def test_a_forced_unicode_error_on_read_answers_a_problem_not_text_plain(monkeypatch):
    class RaisesUnicodeErrorOnSelect:
        def __init__(self):
            self.calls = 0

        def begin(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, statement, params=None):
            self.calls += 1
            if self.calls == 1:
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return _ScalarFalse()          # the _table_missing probe, inside except

        def close(self):
            pass

    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: RaisesUnicodeErrorOnSelect())
    with pytest.raises(errors.Problem) as caught:
        contextvars.copy_context().run(customer_contact.active_for, "cu-uce-read")
    assert caught.value.code == "internal_error" and caught.value.status == 500


# --- M4: separator runs of 4+ characters (fix round 2) ------------------------------------

@pytest.mark.parametrize("reason", [
    "โทร 081 -- 234 -- 5678 ครับ",
    "โทร 081  -  234  5678 ครับ",
    "โทร 081 .  234 . 5678 ครับ",
])
def test_a_wide_separator_run_still_joins_the_digits(reason):
    redacted = customer_contact._without_numbers(reason)
    assert "081" not in redacted and "234" not in redacted and "5678" not in redacted
    assert "[ตัดเบอร์ออก]" in redacted


def test_an_eight_digit_date_stays_untouched_even_with_wide_runs_allowed():
    assert customer_contact._without_numbers("วันที่ 2026-10-23") == "วันที่ 2026-10-23"


# --- M5: a non-string reason is refused, not stringified (fix round 2) -------------------

def test_a_non_string_reason_is_refused_reason_required():
    uid = _placeholder_customer()
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers=OFFICER,
                    json={"phone": "0899990306", "reason": {"a": 1}})
    assert (r.status_code, r.json()["code"]) == (422, "reason_required")
    assert r.json()["errors"][0]["pointer"] == "/reason"
    assert customer_contact._HISTORY == []


# --- M6: a missing table answers phone_store_not_migrated (fix round 2) ------------------

def test_a_missing_table_answers_phone_store_not_migrated(pg_conn, pg_url, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    pg_conn.execute(text("drop table records.customer_contact"))
    pg_conn.commit()
    engine = create_engine(pg_url, future=True)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", engine.connect)
    try:
        with pytest.raises(errors.Problem) as caught:
            contextvars.copy_context().run(customer_contact.active_for, "cu-no-table")
        assert caught.value.code == "phone_store_not_migrated"
        assert (caught.value.status, caught.value.retryable) == (503, True)
        assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True
    finally:
        migrate.apply(pg_conn)          # recreate for every test that runs after this one
        pg_conn.commit()
        engine.dispose()


# --- M7: the audit row names the act even when the read fails (fix round 2) --------------

def test_an_unreachable_write_still_audits_the_attempted_act(monkeypatch):
    """The read inside set_phone (active_for's "changes nothing" check) used to fail
    BEFORE audit.describe ran, so main.py's audit_trail middleware wrote the
    request's row with its write-time default act=None. Scoped to customer_contact's
    OWN `db` name only (p3_surrogate.py's own technique), so audit_store's real
    view of `db` — and so the in-memory audit chain this test reads back from —
    is untouched."""
    import types
    uid = _placeholder_customer()
    monkeypatch.setattr(customer_contact, "db", types.SimpleNamespace(
        configured=lambda: True,
        connect=lambda: (_ for _ in ()).throw(db.DatabaseUnreachable("no route to host")),
        DatabaseUnreachable=db.DatabaseUnreachable))
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers=OFFICER,
                    json={"phone": "0899990600", "reason": "m7"})
    assert r.status_code == 503
    entry = _latest_audit()
    assert entry["act"] == "PHONE_SET"
    assert (entry["subject_type"], entry["subject_uid"]) == ("customer", uid)


# --- M8: a `by` of only invisible characters is refused (fix round 2) --------------------

def test_a_by_of_only_invisible_characters_is_refused():
    uid = _placeholder_customer()
    zero_width_space = "\u200b"          # an explicit escape, never a literal invisible character
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": "OFFICER"},
                    json={"phone": "0899990601", "reason": "probe", "by": zero_width_space + " " + zero_width_space})
    assert (r.status_code, r.json()["code"]) == (422, "phone_actor_invalid")
    assert r.json()["errors"][0]["pointer"] == "/by"
    assert customer_contact._HISTORY == []


def test_customer_contact_module_agrees_a_zero_width_space_is_not_visible():
    """Direct unit check of the M8 helper, independent of the HTTP round trip above."""
    assert customer_contact._has_visible_actor("thip") is True
    assert customer_contact._has_visible_actor("\u200b \u200b") is False
    assert customer_contact._has_visible_actor("") is False


# --- M13: invisible non-Cf characters (fix round 3) ---------------------------------------

@pytest.mark.parametrize("invisible, label", [
    ("\u3164", "Hangul filler (Lo)"),
    ("\u2800", "Braille pattern blank (So)"),
    ("\u0301", "a lone combining acute accent (Mn)"),
])
def test_by_of_invisible_non_cf_characters_is_refused(invisible, label):
    assert customer_contact._has_visible_actor(invisible) is False, label
    uid = _placeholder_customer()
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": "OFFICER"},
                    json={"phone": "0899990602", "reason": "probe", "by": invisible})
    assert (r.status_code, r.json()["code"]) == (422, "phone_actor_invalid"), label
    assert customer_contact._HISTORY == []


def test_visible_text_with_a_trailing_combining_mark_is_still_accepted():
    """M13 excludes marks/Cf/fillers from VISIBILITY only \u2014 a real base character
    elsewhere in the string still makes the whole value a visible actor."""
    assert customer_contact._has_visible_actor("thip" + "\u0301") is True


# --- Critical: _without_numbers is linear-time by construction (fix round 3) -------------

def _best_of_3(fn):
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times)


def test_timing_a_digit_then_5000_spaces_then_a_letter_stays_under_50ms():
    s = "3" + " " * 5000 + "a"
    best = _best_of_3(lambda: customer_contact._without_numbers(s))
    assert best < 0.05, best


def test_timing_a_digit_then_5000_dashes_then_a_letter_stays_under_50ms():
    s = "3" + "-" * 5000 + "a"
    best = _best_of_3(lambda: customer_contact._without_numbers(s))
    assert best < 0.05, best


def test_timing_a_digit_then_2500_space_dash_pairs_then_a_letter_stays_under_50ms():
    s = "3" + " -" * 2500 + "a"
    best = _best_of_3(lambda: customer_contact._without_numbers(s))
    assert best < 0.05, best


def test_timing_5000_repeats_of_a_short_phone_like_group_stays_under_200ms():
    s = "081 " * 5000
    best = _best_of_3(lambda: customer_contact._without_numbers(s))
    assert best < 0.2, best


def test_timing_a_100000_character_mixed_input_stays_under_500ms():
    import random
    rng = random.Random(20260915)
    alphabet = list("0123456789") + list("\u0e50\u0e51\u0e52\u0e53\u0e54\u0e55\u0e56\u0e57\u0e58\u0e59") + list(" ,.-_") + ["\u2013", "\u2014"]
    s = "".join(rng.choice(alphabet) for _ in range(100000))
    best = _best_of_3(lambda: customer_contact._without_numbers(s))
    assert best < 0.5, best


# --- Critical (3): a write-side reason cap, independent of the scanner above -------------

def test_a_500_character_reason_is_accepted():
    uid = _placeholder_customer()
    r = _post(uid, {"phone": "0899990810", "reason": "\u0e01" * 500})
    assert r.status_code == 200, r.json()


def test_a_501_character_reason_is_refused_reason_too_long_and_does_not_echo():
    uid = _placeholder_customer()
    r = _post(uid, {"phone": "0899990811", "reason": "\u0e01" * 501})
    assert (r.status_code, r.json()["code"], r.json()["error_id"]) == (422, "reason_too_long", "DEBT-COL-0468")
    assert r.json()["errors"][0]["pointer"] == "/reason"
    assert r.json()["message_th"] == customer_contact.REASON_TOO_LONG_TH
    assert "\u0e01" * 50 not in r.text
    assert customer_contact._HISTORY == []


def test_a_reason_too_long_refusal_happens_before_audit_and_before_any_store_call(monkeypatch):
    calls = []
    from app import audit
    monkeypatch.setattr(audit, "describe", lambda **kw: calls.append("describe"))
    monkeypatch.setattr(db, "configured", lambda: True)

    def _spy_connect():
        calls.append("connect")
        raise AssertionError("db.connect must never be reached for a refused reason")

    monkeypatch.setattr(db, "connect", _spy_connect)
    with pytest.raises(CaseError) as caught:
        contextvars.copy_context().run(customer_contact.set_phone, "cu-toolong", "0812345678", "thip", "\u0e01" * 501)
    assert caught.value.code == "reason_too_long"
    assert calls == []


# --- M9: the R1 guard's order is pinned (fix round 3) -------------------------------------

def test_r1_guard_runs_before_audit_and_before_any_store_call(monkeypatch):
    """A mutant moving the R1 guard after audit.describe and the first store read
    passed all 63 fix-round-2 tests. Spies both, so it cannot again."""
    calls = []
    from app import audit
    monkeypatch.setattr(audit, "describe", lambda **kw: calls.append("describe"))
    monkeypatch.setattr(db, "configured", lambda: True)

    def _spy_connect():
        calls.append("connect")
        raise AssertionError("db.connect must never be reached for a refused body")

    monkeypatch.setattr(db, "connect", _spy_connect)
    with pytest.raises(CaseError) as caught:
        contextvars.copy_context().run(customer_contact.set_phone, "cu-m9", "0812345678", "thip", "x\ud83dy")
    assert caught.value.code == "text_invalid"
    assert calls == []


# --- M10: the M6 write-path branch is pinned on a real POST (fix round 3, fix round 4) ---

def test_a_post_with_the_table_missing_answers_phone_store_not_migrated(pg_conn, pg_url, monkeypatch):
    """Fix round 4 / M10: fix round 3's version of this test got its 503 from
    `_load_active` — the POST calls `active_for` first, and the read path has its own
    missing-table branch — so a mutant deleting `_table_missing` from `_transaction`
    still passed. The read is stubbed here, so the write is the only store call left,
    and the statements the engine actually sent prove the 503 came from inside it: the
    write's UPDATE failed, then the missing-table probe ran, and the read never did."""
    from sqlalchemy import event

    uid = _placeholder_customer()          # picked before the database switches on
    migrate.apply(pg_conn)
    pg_conn.commit()
    pg_conn.execute(text("drop table records.customer_contact"))
    pg_conn.commit()
    engine = create_engine(pg_url, future=True)
    sent = []
    event.listen(engine, "before_cursor_execute",
                 lambda conn, cursor, statement, *rest: sent.append(" ".join(statement.split())))
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", engine.connect)
    monkeypatch.setattr(customer_contact, "active_for", lambda customer_uid: None)
    try:
        r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers=OFFICER,
                        json={"phone": "0899990700", "reason": "m10"})
        assert (r.status_code, r.json()["code"]) == (503, "phone_store_not_migrated")
        assert r.json()["retryable"] is True
        mine = [s for s in sent if "records.customer_contact" in s]
        assert not any(s.startswith("select customer_uid") for s in mine), mine      # the read never ran
        writes = [k for k, s in enumerate(mine) if s.startswith("update records.customer_contact")]
        probes = [k for k, s in enumerate(mine) if "to_regclass('records.customer_contact')" in s]
        assert writes and probes and writes[0] < probes[0], mine                     # the write path was reached
    finally:
        migrate.apply(pg_conn)          # recreate for every test that runs after this one
        pg_conn.commit()
        engine.dispose()


# --- M14: a dangerous claimed actor no longer drops the audit row (fix round 3) ----------

def test_a_lone_surrogate_by_still_leaves_exactly_one_audit_row():
    """main.py's audit_trail middleware reads `by` from the SAME body independently
    of the route/customer_contact.set_phone \u2014 before this fix, main.py's _actor_of
    copied a lone surrogate straight into actor_claimed, and hashing that entry
    (audit.hash_entry's own .encode("utf-8")) raised, caught by the middleware's
    `except Exception: audit_store.record_gap(exc)` \u2014 the refused request (422
    text_invalid, from customer_contact's OWN, independent R1 guard) left no audit
    row at all."""
    uid = _placeholder_customer()
    before = len(audit_store.MEMORY.entries())
    # No X-Volt-Officer header — main.py's _actor_of falls through to the BODY,
    # which is exactly the path that used to crash the hash on this same value.
    # AUTHORISED TEST EDIT 44: the same header; still no X-Volt-Officer, so `by` comes from the body.
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": "OFFICER", "Content-Type": "application/json"},
                    content='{"phone": "0899990812", "reason": "probe", "by": "a\\ud83db"}'.encode())
    assert (r.status_code, r.json()["code"]) == (422, "text_invalid")
    after = len(audit_store.MEMORY.entries())
    assert after == before + 1
    entry = audit_store.MEMORY.entries()[-1]
    assert entry["outcome"] == "REFUSED" and entry["status"] == 422
    assert entry["actor_claimed"] is None


# --- fix round 4 / item 2: control and format characters in `by` -------------------------
#
# M13's rewrite (fix round 3) copied user_accounts._shaped_like_a_name, which only ever
# sees a name that _clean_name has already put through " ".join(value.split()) and a
# category-C refusal. Without those two steps a `by` of only tab/LF/VT/FF/U+001C-U+001F/NEL
# answered 200 and Postgres stored set_by = ''. Every value below is an escape.

_ACTOR_REFUSED = [
    pytest.param("\t", id="tab"),
    pytest.param("\n", id="LF"),
    pytest.param("\r\n", id="CRLF"),
    pytest.param("\x0b", id="VT"),
    pytest.param("\x0c", id="FF"),
    pytest.param("\x1c", id="U+001C"),
    pytest.param("\x1d", id="U+001D"),
    pytest.param("\x1e", id="U+001E"),
    pytest.param("\x1f", id="U+001F"),
    pytest.param("\x1c\x1f", id="U+001C-U+001F"),
    pytest.param("\x85", id="NEL"),
    pytest.param("\x01", id="U+0001-not-whitespace"),
    pytest.param("\t\u200b ", id="tab-zwsp-space"),
    pytest.param("Nok\x01", id="visible-name-with-a-control-character"),
    pytest.param("Nok\u200b", id="visible-name-with-a-format-character"),
]


@pytest.mark.parametrize("by", _ACTOR_REFUSED)
def test_a_by_carrying_control_or_format_characters_is_refused(by):
    uid = _placeholder_customer()
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": "OFFICER"},
                    json={"phone": "0899990901", "reason": "probe", "by": by})
    assert (r.status_code, r.json().get("code")) == (422, "phone_actor_invalid"), r.json()
    assert r.json()["errors"][0]["pointer"] == "/by"
    assert customer_contact._HISTORY == []


def test_a_control_character_by_writes_no_row_with_a_database_configured(pg_conn, pg_url, monkeypatch):
    """The reviewer's Postgres half: the same refusals, and a name that arrives
    wrapped in control whitespace is stored normalised, never as ''."""
    migrate.apply(pg_conn)
    pg_conn.commit()
    engine = create_engine(pg_url, future=True)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", engine.connect)
    try:
        for bad_by in ("\t", "\r\n", "\x0b\x0c", "\x1c\x1f", "\x85", "\x01", "\t\u200b "):
            with pytest.raises(CaseError) as caught:
                contextvars.copy_context().run(customer_contact.set_phone, "cu-ctrl-pg", "0899990902", bad_by, "probe")
            assert caught.value.code == "phone_actor_invalid", repr(bad_by)
            assert caught.value.extra["pointer"] == "/by", repr(bad_by)
        assert pg_conn.execute(text("select count(*) from records.customer_contact "
                                    "where customer_uid = 'cu-ctrl-pg'")).scalar() == 0
        saved = contextvars.copy_context().run(customer_contact.set_phone, "cu-ctrl-pg", "0899990902",
                                               "\tทิพย์\n", "probe")
        assert saved["set_by"] == "ทิพย์"
        assert pg_conn.execute(text("select set_by from records.customer_contact "
                                    "where customer_uid = 'cu-ctrl-pg'")).scalar() == "ทิพย์"
    finally:
        pg_conn.execute(text("delete from records.customer_contact"))
        pg_conn.commit()
        engine.dispose()


@pytest.mark.parametrize("by", ["ทิพย์", "สมศักดิ์", "นิ่ม", "Nok"])
def test_a_real_name_in_by_is_still_accepted_and_served_as_typed(by):
    uid = _placeholder_customer()
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": "OFFICER"},
                    json={"phone": "0899990903", "reason": "probe", "by": by})
    assert r.status_code == 200, r.json()
    assert r.json()["customer"]["phone_override"]["set_by"] == by


def test_by_is_normalised_the_way_a_display_name_is_before_it_is_stored():
    uid = _placeholder_customer()
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": "OFFICER"},
                    json={"phone": "0899990904", "reason": "probe", "by": "\t Nok \n\n Thip \x85"})
    assert r.status_code == 200, r.json()
    assert r.json()["customer"]["phone_override"]["set_by"] == "Nok Thip"
    assert customer_contact._HISTORY[-1]["set_by"] == "Nok Thip"


# --- fix round 4 / item 5: phone_actor_invalid has its own error id -----------------------

def test_phone_actor_invalid_answers_its_own_error_id_not_the_generic_refusal():
    uid = _placeholder_customer()
    r = client.post("/v1/cases/by-customer/%s/phone" % uid, headers={"X-Volt-Role": "OFFICER"},
                    json={"phone": "0899990905", "reason": "probe", "by": "\u200b"})
    body = r.json()
    assert (r.status_code, body["code"], body["error_id"]) == (422, "phone_actor_invalid", "DEBT-COL-0469")
    assert body["title"] == "The acting person is required"
    assert body["message_th"] == customer_contact.ACTOR_REQUIRED_TH
    assert body["errors"][0]["pointer"] == "/by"


# --- fix round 4 / item 3: a digit is a DECIMAL digit (category Nd) -----------------------

@pytest.mark.parametrize("value", [
    pytest.param("a \u2070\u2078\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078 b", id="superscripts"),
    pytest.param("a \u2080\u2088\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088 b", id="subscripts"),
    pytest.param("a \u24ea\u2467\u2460\u2461\u2462\u2463\u2464\u2465\u2466\u2467 b", id="circled-digits"),
    pytest.param("a \u2070\u2078\u00b9 \u00b2\u00b3\u2074 \u2075\u2076\u2077\u2078 b", id="spaced-superscripts"),
])
def test_superscripts_subscripts_and_circled_digits_are_left_untouched(value):
    """Fix round 3's ruling (a) listed superscripts as a form that stays untouched; the
    scanner tested str.isdigit(), which is true for them (and for subscripts and
    circled digits), instead of str.isdecimal() — category Nd, the class the old
    `\\d` matched."""
    assert customer_contact._without_numbers(value) == value


@pytest.mark.parametrize("value", [
    pytest.param("a 0899990906 b", id="ascii"),
    pytest.param("a ๐๘๑๒๓๔๕๖๗๘ b", id="thai"),
    pytest.param("a \uff10\uff18\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18 b", id="fullwidth"),
    pytest.param("a \u0660\u0668\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668 b", id="arabic-indic"),
])
def test_every_decimal_digit_script_still_strips(value):
    assert customer_contact._without_numbers(value) == "a [ตัดเบอร์ออก] b"


# --- fix round 4 / item 4 (and fix round 3 / M11): escapes, never literal invisibles ------

def test_neither_file_holds_a_literal_invisible_or_control_character():
    import unicodedata
    from pathlib import Path

    for path in (Path(customer_contact.__file__), Path(__file__)):
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            for ch in line:
                if ch != " " and unicodedata.category(ch)[0] in "CZ":
                    pytest.fail("%s:%d holds a literal U+%04X (%s)" % (
                        path.name, number, ord(ch), unicodedata.category(ch)))


# --- durable ---------------------------------------------------------------------------

def test_the_number_is_durable_in_records_customer_contact(pg_conn, pg_url, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    engine = create_engine(pg_url, future=True)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", engine.connect)
    try:
        first = contextvars.copy_context().run(customer_contact.set_phone, "cu-pg", "0812345678", "thip", "แรก")
        assert first["durable"] is True and "note_th" not in first
        again = contextvars.copy_context().run(customer_contact.set_phone, "cu-pg", "0898765432", "noon", "เปลี่ยน")
        assert again["phone_e164"] == "+66898765432" and again["set_by"] == "noon"
        assert contextvars.copy_context().run(customer_contact.active_for, "cu-pg")["display"] == "089-876-5432"
        contextvars.copy_context().run(customer_contact.set_phone, "cu-pg", None, "thip", "ลบ")
        rows = pg_conn.execute(text("select phone_e164, active, reason from records.customer_contact "
                                    "where customer_uid = 'cu-pg' order by uid")).fetchall()
        assert [tuple(r) for r in rows] == [("+66812345678", False, "แรก"), ("+66898765432", False, "เปลี่ยน"),
                                           (None, False, "ลบ")]
        assert contextvars.copy_context().run(customer_contact.active_for, "cu-pg") is None
    finally:
        # pg_conn's teardown truncates only landing and app — records is cleaned here.
        pg_conn.execute(text("delete from records.customer_contact"))
        pg_conn.commit()
        engine.dispose()


# --- M3: the memo holds over a real HTTP request, and does not leak across requests ------

def test_the_memo_holds_over_http_and_does_not_leak_across_requests(pg_conn, pg_url, monkeypatch):
    """test_the_table_is_read_once_per_request_not_once_per_row proves the ContextVar
    memo in a unit test; this proves the same thing through TestClient — a real
    request, not a manually copied context — and that a number inserted BETWEEN two
    requests is visible on the next one (the memo dies with the request)."""
    uid = _placeholder_customer()          # picked before the database switches on
    migrate.apply(pg_conn)
    pg_conn.commit()
    engine = create_engine(pg_url, future=True)
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", engine.connect)
    real_load = customer_contact._load_active
    calls = []
    monkeypatch.setattr(customer_contact, "_load_active", lambda: calls.append(1) or real_load())
    try:
        r1 = client.get("/v1/workbook")
        assert r1.status_code == 200
        assert len(calls) == 1

        with engine.connect() as conn:
            conn.execute(text(
                "insert into records.customer_contact "
                "(customer_uid, phone_e164, kind, set_by, reason, active) "
                "values (:u, '+66812345678', 'MOBILE', 'noon', 'inserted between requests', true)"),
                {"u": uid})
            conn.commit()

        r2 = client.get("/v1/workbook")
        assert r2.status_code == 200
        assert len(calls) == 2
        row = next(r for r in r2.json()["rows"] if r["customer"]["uid"] == uid)
        assert row["customer"]["phone_revealable"] is True
        assert "phone_e164" in customer_contact.active_for(uid)
    finally:
        pg_conn.execute(text("delete from records.customer_contact"))
        pg_conn.commit()
        engine.dispose()
