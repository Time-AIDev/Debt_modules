"""WP6 (F16) — a next action moved on the calendar goes through set_next_action, with a reason."""
import json as json_module

from fastapi.testclient import TestClient

from app import audit_store
from app import cases as cases_domain
from app.config import settings
from app.customer_contact import _without_numbers
from app.main import app

BD = settings.business_date
HEAD = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


def _client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _call_case():
    cs = cases_domain.for_current()
    return next(k for k in cs.cases.values()
                if k["next_action"] == "CALL" and k["next_action_on"] == str(BD) and not k["review_uid"])


def _move(c, customer_uid, **body):
    return c.post("/v1/calendar/next-actions/%s:move" % customer_uid, json=body, headers=HEAD)


def _raw_json(c, path, body, headers):
    """httpx's own json= encodes with ensure_ascii=False, so it raises client-side on a
    lone surrogate before a request is ever built — a real browser's fetch()+
    JSON.stringify() sends ASCII-escaped text instead (ensure_ascii's own encoding),
    the same technique test_calendar_notices.py uses for the same reason: this sends
    pre-encoded ASCII bytes, exactly what json.loads() on the server reconstructs the
    lone surrogate FROM."""
    payload = json_module.dumps(body, ensure_ascii=True).encode("ascii")
    return c.post(path, content=payload, headers=dict(headers, **{"content-type": "application/json"}))


def test_a_next_action_moves_to_another_day_with_its_reason_and_keeps_its_action():
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on="2026-10-27", reason="ลูกค้าขอให้โทรวันอังคาร")
    assert r.status_code == 200, r.json()
    assert r.json()["moved"] == {"action": "CALL", "from": str(BD), "to": "2026-10-27"}
    assert (case["next_action"], case["next_action_on"]) == ("CALL", "2026-10-27")
    assert case["next_action_set_by"] == "nantapol" and case["next_action_note"] == "ลูกค้าขอให้โทรวันอังคาร"
    event = cases_domain.for_current().events[-1]
    assert event["kind"] == "NEXT_ACTION_SET" and event["on"] == "2026-10-27"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["act"] == "NEXT_ACTION_MOVED" and entry["subject_uid"] == case["customer_uid"]
    assert {k: entry["detail"][k] for k in ("action", "from", "to", "reason")} == {
        "action": "CALL", "from": str(BD), "to": "2026-10-27", "reason": "ลูกค้าขอให้โทรวันอังคาร"}
    week = c.get("/v1/calendar", params={"from": "2026-10-26", "to": "2026-11-01"}, headers=HEAD).json()
    assert any(i["kind"] == "NEXT_ACTION" and i["customer_uid"] == case["customer_uid"] and i["on"] == "2026-10-27"
               for i in week["items"])


def test_a_move_without_a_reason_or_a_day_is_refused_and_nothing_moves():
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on="2026-10-27", reason="   ")
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/reason"
    r = _move(c, case["customer_uid"], reason="x")
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/on"
    assert case["next_action_on"] == str(BD)


def test_the_refusals_set_next_action_makes_are_this_routes_refusals():
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on="61024-02-20", reason="typo")
    assert r.status_code == 422 and r.json()["code"] == "next_action_date_invalid"
    case["next_action"] = "AWAIT_REVIEW"          # waiting on a review nobody raised (T5-03)
    r = _move(c, case["customer_uid"], on="2026-10-27", reason="รอผู้จัดการ")
    assert r.status_code == 422 and r.json()["code"] == "review_required" and r.json()["message_th"]
    assert r.json()["title"] != "Refused"
    case["next_action"] = None
    r = _move(c, case["customer_uid"], on="2026-10-27", reason="x")
    assert r.status_code == 422 and r.json()["code"] == "next_action_required"
    assert case["next_action_on"] == str(BD)


def test_a_move_to_the_day_it_is_already_on_is_a_conflict_not_a_silent_success():
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on=str(BD), reason="x")
    assert r.status_code == 409 and r.json()["code"] == "next_action_unchanged" and r.json()["message_th"]


def test_an_unknown_customer_is_a_404():
    assert _move(_client(), "no-such-customer", on="2026-10-27", reason="x").status_code == 404


# --- fix round 1: audit.describe runs before EVERY refusal, not only set_next_action's ---

def test_a_refusal_set_next_action_makes_still_writes_an_audited_next_action_moved_row():
    """Fix round 1: audit.describe runs before set_next_action is even called, so a
    refusal it makes (here: an invalid date) still names what was asked — act,
    subject and detail are never left at the base per-request row's blanks."""
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on="61024-02-20", reason="typo เบอร์ 081-234-5678")
    assert r.status_code == 422 and r.json()["code"] == "next_action_date_invalid"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["act"] == "NEXT_ACTION_MOVED" and entry["outcome"] == "REFUSED"
    assert (entry["subject_type"], entry["subject_uid"]) == ("customer", case["customer_uid"])
    assert entry["detail"] == {"action": "CALL", "from": str(BD), "to": "61024-02-20"[:10],
                               "reason": _without_numbers("typo เบอร์ 081-234-5678")}


def test_a_same_day_conflict_still_writes_an_audited_next_action_moved_row():
    """Fix round 1: the same-day (next_action_unchanged) refusal is now raised AFTER
    audit.describe, not before — the exact defect the review found in the
    already-committed code (e1c2017), which described nothing for this refusal."""
    c = _client()
    case = _call_case()
    r = _move(c, case["customer_uid"], on=str(BD), reason="x")
    assert r.status_code == 409 and r.json()["code"] == "next_action_unchanged"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["act"] == "NEXT_ACTION_MOVED" and entry["outcome"] == "REFUSED"
    assert (entry["subject_type"], entry["subject_uid"]) == ("customer", case["customer_uid"])
    assert entry["detail"] == {"action": "CALL", "from": str(BD), "to": str(BD), "reason": "x"}


# --- B6/C2b rulings, applied up front (controller dispatch) --------------------------

def test_a_phone_number_typed_in_the_reason_is_cut_from_the_audit_log_and_the_case_trail():
    """F18 (PDPA): a phone number in the reason must never reach the append-only
    audit log — AND must not sit unredacted in the case's own trail (next_action_note,
    served straight back in this very response's `case` object) either, since leaving
    it there would just move the leak, not close it."""
    c = _client()
    case = _call_case()
    raw_reason = "โทร 081-234-5678 พรุ่งนี้เช้า"
    expected = _without_numbers(raw_reason)
    assert "081" not in expected and "5678" not in expected      # the helper actually redacts
    r = _move(c, case["customer_uid"], on="2026-10-27", reason=raw_reason)
    assert r.status_code == 200, r.json()
    assert "081" not in json_module.dumps(r.json()) and "5678" not in json_module.dumps(r.json())
    assert r.json()["case"]["next_action_note"] == expected
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["detail"]["reason"] == expected
    # The scan is scoped to `detail` — the only field that could carry the reason.
    # The whole row's JSON also holds the wall-clock timestamp, whose microseconds
    # contain "081" once in a while; that is a clock, not a leak (the assertion used
    # to fail on random timestamps).
    detail = json_module.dumps(entry["detail"])
    assert "081-234" not in detail and "234-5678" not in detail
    assert "081" not in detail and "5678" not in detail
    assert case["next_action_note"] == expected


def test_a_nul_or_lone_surrogate_in_the_reason_is_refused_and_a_real_emoji_is_accepted():
    """B6/C2b ruling (a): [\\x00\\ud800-\\udfff] is refused 422 text_invalid, by pointer,
    with no echo, before audit.describe or set_next_action run — and a real emoji (a
    proper surrogate PAIR once decoded, never a lone surrogate) still goes through."""
    c = _client()
    case = _call_case()

    r = _move(c, case["customer_uid"], on="2026-10-27", reason="a\x00b")
    assert r.status_code == 422
    err = r.json()["errors"][0]
    assert err["pointer"] == "/reason" and err["code"] == "text_invalid" and err["message_th"]
    assert "a\x00b" not in json_module.dumps(r.json())
    # The base per-request row the middleware always appends still lands (every
    # request gets a seq), but the dangerous-character check ran before
    # audit.describe, so it names no act and no subject — the same shape M3 gives an
    # unshaped notice uid refused before it is ever quoted.
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["act"] is None and entry["subject_uid"] is None

    r2 = _raw_json(c, "/v1/calendar/next-actions/%s:move" % case["customer_uid"],
                   {"on": "2026-10-27", "reason": "แจ้ง\ud800ลูกค้า"}, HEAD)
    assert r2.status_code == 422
    err2 = r2.json()["errors"][0]
    assert err2["pointer"] == "/reason" and err2["code"] == "text_invalid"
    entry2 = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry2["act"] is None and entry2["subject_uid"] is None

    assert case["next_action_on"] == str(BD)

    ok = _move(c, case["customer_uid"], on="2026-10-27", reason="โทรแล้ว 😀 พรุ่งนี้")
    assert ok.status_code == 200, ok.json()
    assert ok.json()["case"]["next_action_note"] == "โทรแล้ว 😀 พรุ่งนี้"


def test_pr9_a_moved_next_action_carries_moved_and_where_it_came_from():
    c = _client()
    case = _call_case()
    before = c.get("/v1/calendar", params={"from": str(BD), "to": str(BD)}, headers=HEAD).json()
    row = next(i for i in before["items"] if i["uid"] == "na:%s" % case["customer_uid"])
    assert row["moved"] is False and row["moved_from"] is None
    assert _move(c, case["customer_uid"], on="2026-10-28", reason="customer asked for later").status_code == 200
    week = c.get("/v1/calendar", params={"from": "2026-10-26", "to": "2026-11-01"}, headers=HEAD).json()
    row = next(i for i in week["items"] if i["uid"] == "na:%s" % case["customer_uid"])
    assert row["moved"] is True and row["moved_from"] == str(BD)
    cases_domain.set_next_action(cases_domain.for_current(), case, "CALL", "2026-10-29", by="nantapol")
    week = c.get("/v1/calendar", params={"from": "2026-10-26", "to": "2026-11-01"}, headers=HEAD).json()
    row = next(i for i in week["items"] if i["uid"] == "na:%s" % case["customer_uid"])
    assert row["moved"] is False and row["moved_from"] is None, "a next action set afresh is not a moved one"


def test_review_and_board_refusals_carry_an_english_title_not_the_catch_all():
    """Language pass: both codes used to fall through to the bare "Refused"."""
    from app.routers.today import problem_from
    for code in ("review_required", "board_decision_required"):
        p = problem_from(cases_domain.CaseError(code, "detail"))
        assert p.title and p.title != "Refused" and "_" not in p.title and p.error_id != "DEBT-PLT-0422"
