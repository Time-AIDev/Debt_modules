"""The acts whose history gets asked about read as sentences, not as URLs."""
from fastapi.testclient import TestClient

from app import audit, audit_store
from app import cases as cases_domain
from app import journey
from app.main import app

client = TestClient(app)

OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "nantapol"}
OPS = {"X-Volt-Role": "OPS", "X-Volt-Officer": "om"}


def _latest():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def _a_customer():
    return client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]


def test_a_status_change_records_what_it_changed_from_to_and_why():
    uid = _a_customer()
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "CONTACT_BACK", "reason": "ลูกค้าขอให้โทรกลับ"},
                headers={"X-Volt-Officer": "nantapol"})
    entry = _latest()
    assert entry["act"] == "DC_STATUS_SET"
    assert entry["subject_type"] == "customer" and entry["subject_uid"] == uid
    assert entry["detail"]["to"] == "CONTACT_BACK"
    assert entry["detail"]["reason"] == "ลูกค้าขอให้โทรกลับ"
    assert "from" in entry["detail"]


def test_an_r14_override_records_the_source_value_it_disagreed_with():
    # /v1/orders serves its rows under "items" (main.py:423), not "orders" — the
    # brief's draft assumed the latter without checking.
    no = client.get("/v1/orders").json()["items"][0]["no"]
    client.post("/v1/orders/%d/status-override" % no,
                json={"adjusted_value": "Declined", "reason": "ลูกค้ายกเลิก", "by": "settasak"})
    entry = _latest()
    assert entry["act"] == "R14_OVERRIDE"
    assert entry["detail"]["reason"] == "ลูกค้ายกเลิก"
    assert "from" in entry["detail"] and "to" in entry["detail"]


def test_a_minor_act_still_produces_a_complete_named_row():
    # The floor: no act is invisible. R13 (redesign v2 PR 4) raised it: no write lands
    # act=None any more, so even feedback names itself (test_audit_actor_role.py covers
    # every write route).
    client.post("/v1/feedback", json={"note": "x", "screen": "/"})
    entry = _latest()
    assert entry["act"] == "FEEDBACK_SUBMITTED"
    assert entry["verb"] == "POST" and entry["route_template"] == "/v1/feedback"
    assert entry["outcome"] in ("OK", "REFUSED")


def _shared_client():
    """Pinned to the 'shared' session (test_round3.py's own `client` fixture does the
    same), so the plain domain calls below — made with no request in flight, where
    session.CURRENT defaults to SHARED (session.py:24) — see the exact case state
    these HTTP calls go on to mutate."""
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _cutoff_candidate():
    """The same eligibility check test_round3.py's _request_cutoff helper uses for
    the J3-06/J3-07 cut-off chain: ON, no open review, every power_preconditions
    gate met."""
    cs = cases_domain.for_current()

    def _ok(case):
        customer = journey.customer_by_uid(case["customer_uid"])
        if customer is None:
            return False
        missed = max((journey.missed_count(k) for k in customer.contracts), default=0)
        return not [p for p in cases_domain.power_preconditions(cs, case, missed) if not p["met"]]

    return next(c["customer_uid"] for c in cs.cases.values()
                if c["power_state"] == "ON" and not c["review_uid"] and _ok(c))


def test_executing_a_power_cutoff_does_not_inherit_the_nested_dc_status_detail(evidence_for_power):
    # RULING 13: execute_power calls set_dc_status internally, and set_dc_status
    # describes ITSELF first (act=DC_STATUS_SET, detail={from, to, reason} for the
    # POWER_CUTOFF transition). execute_power's own describe(act=POWER_EXECUTED)
    # then runs with no detail of its own — before the audit.describe fix, the
    # merge-only-if-detail rule let that inner act's detail survive under the
    # outer act's name, so a POWER_EXECUTED row read as an explanation of a status
    # change it never made. This exercises the real call path (the API route ->
    # cases.execute_power -> cases.set_dc_status), not a unit stand-in for it.
    c = _shared_client()
    for case in cases_domain.for_current().cases.values():
        if case["product"] == "LEASE":
            evidence_for_power(case["customer_uid"])
    uid = _cutoff_candidate()
    r = c.post("/v1/cases/by-customer/%s/power-restriction" % uid,
              json={"reason": "ค้างหลายงวดและผิดนัด"}, headers={"X-Volt-Officer": "nantapol"})
    assert r.status_code == 201
    review_uid = r.json()["case"]["review_uid"]
    pwr = r.json()["power"]["uid"]
    r = c.post("/v1/reviews/%s:answer" % review_uid,
              json={"decision": "POWER_CUTOFF_APPROVE"}, headers=OWNER)
    assert r.status_code == 200
    r = c.post("/v1/power-restrictions/%s:execute" % pwr, json={}, headers=OPS)
    assert r.status_code == 200
    entry = _latest()
    assert entry["act"] == "POWER_EXECUTED"
    assert entry["detail"] == {}


def test_a_nested_act_change_resets_subject_too_not_only_detail():
    # Fix 8 (final review): Ruling 13 reset `detail` when a nested describe()
    # changes the act, because a confident wrong value outranks a blank. `subject`
    # is exactly the same shape of risk -- an inner act's subject (an order, a
    # document) surviving under an outer act's name reads just as wrong -- so it
    # must reset the same way.
    token = audit.CURRENT.set({"act": None, "detail": {}, "subject_type": None, "subject_uid": None})
    try:
        audit.describe(act="INNER", subject=("order", "ord-1"), detail={"a": 1})
        audit.describe(act="OUTER")   # no subject of its own
        entry = audit.CURRENT.get()
    finally:
        audit.CURRENT.reset(token)
    assert entry["act"] == "OUTER"
    assert entry["detail"] == {}
    assert entry["subject_type"] is None
    assert entry["subject_uid"] is None


def test_same_act_enrichment_still_merges():
    # The behaviour RULING 13's reset must NOT break: several describe() calls
    # for the SAME act keep adding to one detail dict, as set_dc_status's own
    # multi-field call and the router-enriched acts all rely on.
    token = audit.CURRENT.set({"act": None, "detail": {}})
    try:
        audit.describe(act="X", detail={"a": 1})
        audit.describe(act="X", detail={"b": 2})
        entry = audit.CURRENT.get()
    finally:
        audit.CURRENT.reset(token)
    assert entry["detail"] == {"a": 1, "b": 2}
