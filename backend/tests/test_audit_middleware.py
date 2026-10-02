"""What the middleware records, without any domain module having to remember."""
from fastapi.testclient import TestClient

from app import audit, audit_store
from app.main import app

client = TestClient(app)


def _entries():
    # limit big enough that a long suite run never caps the count the tests compare
    return audit_store.read({}, limit=10**6, before_seq=None)


def test_a_successful_act_is_recorded_with_its_route_template_not_its_path():
    before = len(_entries())
    body = {"code": "CONTACT_BACK", "reason": "ลูกค้าขอให้โทรกลับ"}
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid, json=body,
                headers={"X-Volt-Officer": "nantapol"})
    rows = _entries()
    assert len(rows) == before + 1
    entry = rows[0]
    assert entry["verb"] == "POST"
    assert entry["route_template"] == "/v1/cases/by-customer/{customer_uid}/dc-status"
    assert entry["actor_claimed"] == "nantapol"
    assert entry["actor_source"] == "HEADER"
    assert entry["outcome"] == "OK"


def test_a_refused_act_is_recorded_with_its_problem_code():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    # Edit 22: a status change with no reason is refused.
    client.post("/v1/cases/by-customer/%s/dc-status" % uid, json={"code": "PAID"},
                headers={"X-Volt-Officer": "thip"})
    entry = _entries()[0]
    assert entry["outcome"] == "REFUSED"
    assert entry["status"] == 422
    assert entry["error_code"] == "reason_required"


def test_a_plain_read_is_not_recorded():
    before = len(_entries())
    client.get("/v1/workbook")
    client.get("/v1/today")
    assert len(_entries()) == before


def test_opening_a_customer_IS_recorded():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    before = len(_entries())
    client.get("/v1/cases/by-customer/%s" % uid)
    rows = _entries()
    assert len(rows) == before + 1
    assert rows[0]["verb"] == "GET"
    assert rows[0]["act"] == "CASE_VIEWED"


def test_opening_a_customer_names_the_customer():
    # Final-review finding 2: D3 exists precisely to answer "who opened this
    # customer's file" — route_template deliberately masks the uid, and until
    # case_detail called audit.describe(subject=...) the row could not answer
    # the question it exists for. subject_type/subject_uid were both None.
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.get("/v1/cases/by-customer/%s" % uid)
    entry = _entries()[0]
    assert entry["act"] == "CASE_VIEWED"
    assert entry["subject_type"] == "customer"
    assert entry["subject_uid"] == uid


def test_the_name_in_the_body_is_recorded_as_a_body_claim():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "UNREACHABLE", "reason": "ไม่รับสาย", "by": "settasak"})
    entry = _entries()[0]
    assert entry["actor_claimed"] == "settasak"
    assert entry["actor_source"] == "BODY"


def test_describe_outside_a_request_is_a_no_op_and_never_raises():
    audit.describe(act="X", subject=("customer", "cus-1"), detail={"a": 1})


def test_the_entry_carries_the_session_and_request_that_produced_it():
    # Ruling 12: audit_trail was registered AFTER tester_session and request_identity,
    # which made it the OUTERMOST of the three (add_middleware/the decorator both
    # insert at position 0, so the LAST-registered middleware wraps outermost — see
    # ApiPrefixMiddleware's docstring, which already said so correctly). Outermost
    # means its body ran BEFORE the other two set their ContextVars, so every entry
    # recorded session_id=None, request_id=None. Fixed by registering audit_trail
    # FIRST, making it innermost. request_id is checked against the response's own
    # X-Request-Id header — a stronger claim than merely "not None": it must be the
    # SAME request.
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    resp = client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                       json={"code": "UNREACHABLE", "reason": "ไม่รับสาย"},
                       headers={"X-Volt-Officer": "nantapol"})
    entry = _entries()[0]
    assert entry["session_id"] is not None
    assert entry["request_id"] is not None
    assert entry["request_id"] == resp.headers["X-Request-Id"]


def test_a_reasonless_dc_status_post_is_refused_not_a_server_error():
    # Regression guard: set_dc_status raised CaseError("reason_required", ...) with
    # nothing in the route to catch it, so this call answered 500, not 422, and no
    # test caught it — test_cases.py calls set_dc_status directly and sees the
    # CaseError; the frontend mocks the API. This is the black-box check that closes
    # that gap.
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    resp = client.post("/v1/cases/by-customer/%s/dc-status" % uid, json={"code": "PAID"},
                       headers={"X-Volt-Officer": "thip"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "reason_required"
    assert body["message_th"]


def test_an_unhandled_exception_is_recorded_as_a_refusal_not_a_success():
    # Final-review CRITICAL: audit_trail sits inside the framework's own error
    # handling, so a route that raises with no registered handler propagates
    # straight through call_next — and the code that would have filled in
    # outcome/status/error_code never ran. The `finally` block still appended
    # the entry, but with its INITIALISED values: outcome="OK", status=200,
    # error_code=None. Reproduced here exactly as the reviewer described it: a
    # route that raises KeyError answers 500, and the log swore it succeeded.
    #
    # The route is added to the live app for the life of this test only, and
    # removed in `finally` — a permanent test-only route would otherwise sit in
    # the API surface and be picked up by test_audit_coverage.py's router scan.
    @app.post("/v1/__test/boom")
    def _boom():
        raise KeyError("boom")

    try:
        boom_client = TestClient(app, raise_server_exceptions=False)
        before = len(_entries())
        resp = boom_client.post("/v1/__test/boom", json={})
        assert resp.status_code == 500
        rows = _entries()
        assert len(rows) == before + 1
        entry = rows[0]
        assert entry["route_template"] == "/v1/__test/boom"
        assert entry["status"] == 500
        assert entry["outcome"] == "REFUSED"
        assert entry["error_code"] == "unhandled"
    finally:
        app.router.routes[:] = [r for r in app.router.routes
                                if getattr(r, "path", None) != "/v1/__test/boom"]


def test_a_malformed_body_records_the_problem_code_not_null():
    # Final-review finding 4: only problem_handler ever called audit.note_error.
    # RequestValidationError — here, a body that is not valid JSON at all, on a
    # route typed `body: dict = Body(...)` — went through validation_handler,
    # which never did, so the row recorded {outcome: REFUSED, status: 400,
    # error_code: None} even though spec §4 says the Problem code is recorded
    # whenever an act is refused.
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    resp = client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                       content=b"not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    entry = _entries()[0]
    assert entry["outcome"] == "REFUSED"
    assert entry["status"] == 400
    assert entry["error_code"] == "malformed_request"


def test_a_routed_request_writes_an_audit_row():
    # 2026-09-26: staging (unpinned: FastAPI 0.141.1 / Starlette 1.7.0) wrote no rows
    # at all. include_router() stopped copying routes into app.routes, so every route
    # on an included router matched an entry with no path, _route_template returned
    # None and the middleware skipped the act without counting a gap. requirements.txt
    # pins FastAPI 0.136.3, the last release that lists them; a bump must pass this first.
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    before = len(_entries())
    client.get("/v1/cases/by-customer/%s" % uid)
    rows = _entries()
    assert len(rows) == before + 1
    assert rows[0]["route_template"] == "/v1/cases/by-customer/{customer_uid}"
