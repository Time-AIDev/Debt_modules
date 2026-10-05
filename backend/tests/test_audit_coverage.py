"""'Track all the action' is a claim, and this is the test that keeps it true.

A route added next month with no thought given to the log is still logged; a route
that somehow escapes capture fails the suite here rather than leaving a silent gap.
A trail with unknown gaps is worse than no trail — it invites confident conclusions
from partial evidence (design contract §1a).
"""
from fastapi.testclient import TestClient
from starlette.routing import Route

from app import audit, audit_store
from app.main import app

client = TestClient(app)

ACT_VERBS = {"POST", "PUT", "PATCH", "DELETE"}


def act_routes():
    out = []
    for route in app.routes:
        if not isinstance(route, Route):
            continue
        for method in (route.methods or set()) & ACT_VERBS:
            out.append((method, route.path))
    return sorted(set(out))


def test_there_is_no_mutating_route_under_v1_audit():
    for method, path in act_routes():
        assert not path.startswith("/v1/audit"), "%s %s must not exist" % (method, path)


def test_every_non_get_route_matches_is_logged_by_construction():
    # Final-review CRITICAL, on this very test: `is_logged` is
    # `method != "GET" or route_template in LOGGED_READS`. Every route this
    # function collects is already non-GET (ACT_VERBS excludes GET), so the
    # first half of that OR is true for every single one of them BY
    # CONSTRUCTION — no route_template, however wrong, could ever make this
    # assertion fail. The reviewer proved it live: patching main.py to stop
    # logging /v1/feedback left this test green.
    #
    # It is kept, honestly, as what it actually is: a record that act_routes()
    # produces only non-GET entries, not a coverage guarantee. Real coverage —
    # that an act on every router module actually produces a row in the log,
    # not merely that the predicate returns True for its path in the abstract
    # — is test_a_representative_act_on_every_router_lands_in_the_log below,
    # which calls the routes for real and reads the log back.
    assert act_routes(), "the app must expose acts at all"
    unlogged = [(method, path) for method, path in act_routes()
                if not audit.is_logged(method, path)]
    assert not unlogged, "these act routes are NOT logged: %s" % unlogged


def test_only_the_declared_read_is_logged():
    # D3's scope cannot widen by accident. Verify both the tuple value AND behavior.
    assert audit.LOGGED_READS == ("/v1/cases/by-customer/{customer_uid}", "/v1/terminated-customers/{archive_uid}")
    assert audit.is_logged("GET", "/v1/terminated-customers/{archive_uid}") is True
    assert audit.is_logged("GET", "/v1/terminated-customers") is False
    # Undeclared GETs are NOT logged.
    assert audit.is_logged("GET", "/v1/workbook") is False, "undeclared GETs must not be logged"
    # The declared GET IS logged.
    assert audit.is_logged("GET", "/v1/cases/by-customer/{customer_uid}") is True, "declared read must be logged"


def test_a_representative_act_on_every_router_lands_in_the_log():
    """One act per router MODULE (final-review fix 6), so a router that is
    registered but somehow bypasses the middleware is caught for real, not just
    asserted true of the abstract rule above. Every call below is made for its
    ROUTE, not for a realistic outcome: several deliberately name a resource that
    does not exist, or omit the role that would let the act succeed, because a
    REFUSED row still lands in the log by route_template — is_logged does not
    care whether the act succeeded, and neither does this test. Verified by
    CONTENT (route_template present in the log), not just by response status.

    migration.py is the one router with no act at all: it exposes only
    GET /v1/migration/report and GET /v1/migration/gap-list, no POST/PUT/DELETE —
    there is nothing here for the log to be asked to cover.
    """
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]

    calls = [
        # (router module, method, route_template, the actual call)
        ("today", "POST", "/v1/cases/by-customer/{customer_uid}/dc-status",
         lambda: client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                             json={"code": "CONTACT_BACK", "reason": "r"})),
        ("journey", "PUT", "/v1/ladder-mode",
         lambda: client.put("/v1/ladder-mode", json={"ladder_mode": "MANUAL"})),
        ("integrations", "POST", "/v1/orders/{no}/status-override",
         lambda: client.post("/v1/orders/999999999/status-override",
                             json={"adjusted_value": "x", "reason": "y"})),
        ("settings", "POST", "/v1/dictionaries/{name}/values",
         lambda: client.post("/v1/dictionaries/NOT_A_REAL_DICT/values",
                             json={"code": "X", "label_th": "x", "label_en": "x"},
                             headers={"X-Volt-Role": "MANAGER"})),
        ("pipeline", "POST", "/v1/pipeline/{uid}/gates/down-payment",
         lambda: client.post("/v1/pipeline/not-a-real-uid/gates/down-payment", json={})),
        ("payments", "POST", "/v1/peak-documents/{uid}:resend",
         lambda: client.post("/v1/peak-documents/not-a-real-uid:resend")),
        ("reports", "POST", "/v1/reports/weekly:snapshot",
         lambda: client.post("/v1/reports/weekly:snapshot", json={})),
        ("imports", "POST", "/v1/imports",
         lambda: client.post("/v1/imports", content=b"a,b\n1,2\n",
                             headers={"X-Volt-Filename": "x.csv"})),
        # Not a router module (defined directly on app in main.py) — kept as the
        # original coverage row.
        ("main.py", "POST", "/v1/feedback",
         lambda: client.post("/v1/feedback", json={"note": "x", "screen": "/"})),
    ]

    for _module, method, route_template, call in calls:
        assert (method, route_template) in act_routes(), \
            "%s %s is not a registered route — this test's own call is stale" % (method, route_template)
        call()

    all_entries = audit_store.read({}, limit=1000, before_seq=None)
    routes_logged = {e["route_template"] for e in all_entries}

    missing = [(module, route_template) for module, _method, route_template, _call in calls
              if route_template not in routes_logged]
    assert not missing, "these router modules' acts never reached the log: %s" % missing
