"""The executive overview, saved criteria, and record editing.

The facts under test are the ones that are easy to get wrong and expensive when
they are: a progress bar drawn without a target, a default that nobody chose, and
a deletion that orphans a lease.
"""
import pytest
from fastapi.testclient import TestClient

from app import criteria as criteria_domain
from app import orders as orders_domain
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    orders_domain.reset()
    criteria_domain.reset()
    yield
    orders_domain.reset()
    criteria_domain.reset()


def kpi(body, key):
    return next(k for k in body["kpis"] if k["key"] == key)


# --- targets and progress ------------------------------------------------------

def test_a_kpi_without_a_target_reports_no_progress():
    body = client.get("/v1/overview").json()
    for row in body["kpis"]:
        assert row["target"] is None
        # Nothing in the source data carries a target, so a bar here would be
        # inventing its own denominator.
        assert row["progress_pct"] is None


def test_progress_appears_only_for_the_kpi_that_was_given_a_target():
    client.put("/v1/criteria/default", json={"by": "Nok", "targets": {"orders_approved": 4}})
    body = client.get("/v1/overview").json()
    assert kpi(body, "orders_approved")["progress_pct"] == 0
    assert kpi(body, "leases")["target"] is None
    assert kpi(body, "leases")["progress_pct"] is None

    client.post("/v1/orders/1/approve", json={"by": "Nok"})
    client.post("/v1/orders/2/approve", json={"by": "Nok"})
    body = client.get("/v1/overview").json()
    assert kpi(body, "orders_approved")["value"] == 2
    assert kpi(body, "orders_approved")["progress_pct"] == 50


# A "zero customers at risk" target is real, and it divides by zero.
def test_a_zero_target_is_met_or_not_rather_than_dividing_by_zero():
    client.put("/v1/criteria/default", json={"by": "Nok", "targets": {"at_risk_30": 0}})
    row = kpi(client.get("/v1/overview").json(), "at_risk_30")
    assert row["target"] == 0
    assert row["progress_pct"] == (100 if row["value"] == 0 else 0)


def test_progress_never_exceeds_its_own_track():
    client.put("/v1/criteria/default", json={"by": "Nok", "targets": {"orders_awaiting": 1}})
    row = kpi(client.get("/v1/overview").json(), "orders_awaiting")
    assert row["value"] > 1
    assert row["progress_pct"] == 100


# --- the default is chosen, never implicit -------------------------------------

def test_there_is_no_default_until_a_person_saves_one():
    assert client.get("/v1/criteria/default").json()["default"] is None
    body = client.get("/v1/overview").json()
    assert body["criteria_source"] == "fallback"
    # And the screen is told to say so.
    assert any(a["key"] == "no_default" for a in body["next_actions"])


def test_a_saved_default_carries_who_saved_it_and_when():
    saved = client.put("/v1/criteria/default",
                       json={"by": "Whan", "population": "awaiting_approval"}).json()["default"]
    assert saved["set_by"] == "Whan"
    assert saved["set_at"]
    body = client.get("/v1/overview").json()
    assert body["criteria_source"] == "saved_default"
    assert body["criteria"]["set_by"] == "Whan"
    assert not any(a["key"] == "no_default" for a in body["next_actions"])


def test_an_explicit_query_beats_the_saved_default_and_says_which_it_used():
    client.put("/v1/criteria/default", json={"by": "Nok", "population": "approved_this_run"})
    body = client.get("/v1/overview", params={"population": "all_orders"}).json()
    assert body["criteria_source"] == "query"
    assert body["criteria"]["population"] == "all_orders"


def test_a_target_on_a_measured_total_is_refused():
    # Book value is not something a person sets; a target on it reads as a forecast.
    response = client.put("/v1/criteria/default", json={"targets": {"book_value_usd": 10}})
    assert response.status_code == 422
    assert response.json()["code"] == "criteria_invalid"
    assert client.get("/v1/criteria/default").json()["default"] is None


def test_an_unknown_population_is_refused_not_widened():
    response = client.put("/v1/criteria/default", json={"population": "everything"})
    assert response.status_code == 422
    assert response.json()["extensions"]["reason"] == "population_unknown"


def test_the_population_actually_narrows_the_orders_counted():
    everything = client.get("/v1/overview", params={"population": "all_orders"}).json()
    client.post("/v1/orders/1/approve", json={"by": "Nok"})
    approved = client.get("/v1/overview", params={"population": "approved_this_run"}).json()
    assert approved["scope"]["orders_in_scope"] == 1
    assert approved["scope"]["orders_total"] == everything["scope"]["orders_total"]


# --- next actions --------------------------------------------------------------

def test_next_actions_are_derived_from_live_counts_and_carry_a_route():
    body = client.get("/v1/overview").json()
    approve = next(a for a in body["next_actions"] if a["key"] == "approve")
    assert approve["count"] == kpi(body, "orders_awaiting")["value"]
    assert approve["route"] == "/orders"
    # The one action nobody can click carries no route, so it cannot pretend to.
    assert next(a for a in body["next_actions"] if a["key"] == "no_default")["route"] is None


def test_the_overview_no_longer_offers_the_open_decisions_action():
    """Arina, 2026-09-11: "remove decision still open from overview."

    It was served whenever config.PENDING was non-empty — five entries, so always —
    and it linked to `/pending`, a route retired in the 2026-09-02 realignment that
    redirects to /settings (App.jsx). The card promised a list of open decisions and
    delivered the settings screen.
    """
    body = client.get("/v1/overview").json()
    assert all(a["key"] != "decisions" for a in body["next_actions"])
    # and nothing else quietly took over the retired route
    assert all(a.get("route") != "/pending" for a in body["next_actions"])


# --- editing records -----------------------------------------------------------

def test_a_created_order_enters_the_queue_awaiting_approval():
    before = client.get("/v1/orders").json()["counts"]["pending"]
    created = client.post("/v1/orders", json={
        "by": "Nok", "first_name": "Somchai", "last_name": "Wongtest", "crm_id": "28009999001",
    })
    assert created.status_code == 201
    order = created.json()["order"]
    assert order["order_status"] == orders_domain.STATUS_PENDING
    assert order["origin"] == "added"
    # It never came from the sheet, so it must not claim a sheet status.
    assert order["sheet_order_status"] is None
    assert client.get("/v1/orders").json()["counts"]["pending"] == before + 1


def test_a_cash_order_created_here_follows_the_sheet_s_own_term_convention():
    order = client.post("/v1/orders", json={
        "first_name": "A", "last_name": "B", "crm_id": "28009999002", "order_type": "Cash",
    }).json()["order"]
    assert order["term_months"] == "Cash"


def test_creating_an_order_without_the_required_fields_names_them():
    response = client.post("/v1/orders", json={"first_name": "Solo"})
    assert response.status_code == 422
    pointers = {e["pointer"] for e in response.json()["errors"]}
    assert pointers == {"/last_name", "/crm_id"}


def test_two_orders_may_not_share_a_crm_id():
    payload = {"first_name": "A", "last_name": "B", "crm_id": "SYN-ORDER-001"}
    response = client.post("/v1/orders", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "crm_id_taken"


def test_removing_an_order_takes_it_out_of_the_run_and_says_the_sheet_is_untouched():
    before = len(client.get("/v1/orders").json()["items"])
    response = client.delete("/v1/orders/2")
    assert response.status_code == 200
    assert "not written to" in response.json()["note"]
    assert len(client.get("/v1/orders").json()["items"]) == before - 1


def test_an_approved_order_cannot_be_deleted_out_from_under_its_lease():
    client.post("/v1/orders/1/approve", json={"by": "Nok"})
    leases = client.get("/v1/loan-book").json()["counts"]["total"]
    response = client.delete("/v1/orders/1")
    assert response.status_code == 409
    assert response.json()["code"] == "order_in_loan_book"
    # And the book is untouched by the attempt.
    assert client.get("/v1/loan-book").json()["counts"]["total"] == leases


# --- per-tester isolation ------------------------------------------------------
# The defect this guards: two testers sharing a deployment saw each other's
# approvals, and neither could tell whose work they were looking at.

def _tester():
    """A client with its own cookie jar — one browser, one sandbox."""
    return TestClient(app)


def test_two_testers_do_not_see_each_other_s_approvals():
    a, b = _tester(), _tester()
    # Each first request mints a session cookie, so the two are separate from here.
    assert a.get("/v1/orders").json()["counts"]["done"] == 0
    assert b.get("/v1/orders").json()["counts"]["done"] == 0

    assert a.post("/v1/orders/1/approve", json={"by": "Nok"}).status_code == 200

    assert a.get("/v1/orders").json()["counts"]["done"] == 1
    assert b.get("/v1/orders").json()["counts"]["done"] == 0, "tester B saw tester A's approval"
    # And B can still approve the same order, because in B's sandbox it is untouched.
    assert b.post("/v1/orders/1/approve", json={"by": "Whan"}).status_code == 200


def test_a_lease_written_by_one_tester_stays_out_of_another_s_book():
    a, b = _tester(), _tester()
    before = b.get("/v1/loan-book").json()["counts"]["total"]
    a.post("/v1/orders/1/approve", json={"by": "Nok"})
    assert a.get("/v1/loan-book").json()["counts"]["approved_here"] == 1
    assert b.get("/v1/loan-book").json()["counts"]["approved_here"] == 0
    assert b.get("/v1/loan-book").json()["counts"]["total"] == before


def test_a_record_added_or_removed_by_one_tester_is_invisible_to_another():
    a, b = _tester(), _tester()
    baseline = len(b.get("/v1/orders").json()["items"])

    a.post("/v1/orders", json={"first_name": "A", "last_name": "B", "crm_id": "28009999501"})
    a.delete("/v1/orders/2")

    assert len(b.get("/v1/orders").json()["items"]) == baseline
    assert any(o["crm_id"] == "28009999501" for o in a.get("/v1/orders").json()["items"])
    assert not any(o["crm_id"] == "28009999501" for o in b.get("/v1/orders").json()["items"])
    # B still sees the row A hid.
    assert any(o["no"] == 2 for o in b.get("/v1/orders").json()["items"])


def test_one_reviewer_s_saved_default_never_becomes_another_s():
    a, b = _tester(), _tester()
    a.put("/v1/criteria/default", json={"by": "Whan", "population": "approved_this_run"})
    assert a.get("/v1/criteria/default").json()["default"]["set_by"] == "Whan"
    # This is the whole point of the "no implicit default" rule: B must still be told
    # nobody has chosen one.
    assert b.get("/v1/criteria/default").json()["default"] is None
    assert b.get("/v1/overview").json()["criteria_source"] == "fallback"


def test_a_session_persists_across_requests_from_the_same_browser():
    a = _tester()
    first = a.get("/v1/orders")
    cookie = first.cookies.get("volt_session")
    assert cookie
    a.post("/v1/orders/1/approve", json={"by": "Nok"})
    assert a.get("/v1/orders").json()["counts"]["done"] == 1
