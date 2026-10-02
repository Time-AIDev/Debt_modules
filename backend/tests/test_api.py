"""The HTTP surface.

The doc version is 2.x and the URL version deliberately does NOT move:
"This document is version 2.1. The addresses still begin with slash v1."
Every v2.x change is additive under v1.0's own rule. Do not let anyone "fix" this
by minting /v2 — that would be a breaking change needing a plan, not a patch.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.money.band_sets import assert_band_pair_present


@pytest.fixture
def client():
    return TestClient(app)


# --- platform ----------------------------------------------------------------

def test_healthz_is_the_cloud_run_probe_target(client):
    assert client.get("/healthz").status_code == 200


def test_readyz_is_separate_from_healthz(client):
    """Cloud Run has startup and liveness probes only; readiness in the Kubernetes
    sense does not exist. /readyz is for the LB uptime check and the deploy smoke
    test, never for Cloud Run."""
    assert client.get("/readyz").status_code == 200


def test_the_surface_is_v1_even_though_the_documents_are_v2(client):
    body = client.get("/v1/meta/version").json()
    assert body["url_version"] == "v1"
    assert body["document_version"].startswith("2.")


def test_the_interface_prefix_reaches_the_same_route(client):
    """api.js talks to /api; this API serves /v1. Only the vite dev proxy ever
    stripped that prefix (vite.config.js), so a deployed build called
    /api/v1/... and got a 404 problem document for every screen. Six UAT rounds
    missed it: e2e_check.py hits :8000 with no prefix and the unit tests stub
    fetch. One origin has to work without a proxy in front of it.
    """
    bare = client.get("/v1/board/columns")
    prefixed = client.get("/api/v1/board/columns")
    assert bare.status_code == 200
    assert prefixed.status_code == 200
    assert prefixed.json() == bare.json()


def test_an_unknown_prefixed_route_is_still_a_problem_document(client):
    """Stripping the prefix must not turn a typo into the HTML shell."""
    assert client.get("/api/v1/nope").status_code == 404
    assert client.get("/api/nonsense").status_code == 404


def test_only_a_real_api_segment_has_its_prefix_stripped(client):
    """The prefix match must be a BOUNDARY. `startswith("/api/v1")` also matched
    `/api/v1board/columns`, which was rewritten to `/v1board/columns` — a path the
    spa() guard tests for `v1/` and `api/` and matches neither, so it came back as the
    HTML shell with a 200. api.js's `get()` reads that as success, fails the `.json()`
    parse into null and renders an empty state with no error: the exact failure the
    prefix middleware was written to remove.
    """
    table = [
        ("/api/v1/board/columns", 200, "application/json"),
        ("/api/v1/nope", 404, "application/problem+json"),
        ("/api/nonsense", 404, "application/problem+json"),
        ("/api/v1board/columns", 404, "application/problem+json"),
        ("/api/v1", 404, "application/problem+json"),
    ]
    for path, status, media in table:
        response = client.get(path)
        assert response.status_code == status, (path, response.text[:200])
        assert response.headers["content-type"].startswith(media), \
            (path, response.headers["content-type"])


# --- error envelope, RFC 9457 -------------------------------------------------

def test_every_error_carries_the_full_envelope(client):
    """`message_th` is ALWAYS present; `errors` is an empty array, never absent;
    `extensions` is an empty object when not applicable. `code` is the only field
    clients branch on."""
    response = client.get("/v1/dashboards/exceptions")
    body = response.json()

    for field in ("type", "title", "status", "code", "error_id", "message_th", "retryable", "errors", "extensions"):
        assert field in body, field
    assert isinstance(body["errors"], list)
    assert isinstance(body["extensions"], dict)
    assert body["message_th"]


def test_a_problem_response_uses_the_problem_json_media_type(client):
    response = client.get("/v1/dashboards/exceptions")
    assert response.headers["content-type"].startswith("application/problem+json")


# --- exception dashboard, screen 03 -------------------------------------------

def test_a_dashboard_without_a_population_filter_is_422_not_a_guessed_number(client):
    """422 population_filter_unset, DEBT-KPI-0422.

    "There is no implicit whole-book default, deliberately." A dashboard that renders
    an undefined number is worse than one that refuses.
    """
    response = client.get("/v1/dashboards/exceptions")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "population_filter_unset"
    assert body["error_id"] == "DEBT-KPI-0422"
    # "Extensions name the configuration key to set."
    assert "config_key" in body["extensions"]


def test_a_dashboard_with_a_population_filter_renders(client):
    response = client.get("/v1/dashboards/exceptions", params={"population_filter": "ALL_OPEN"})

    assert response.status_code == 200
    assert_band_pair_present(response.json())


# --- today list, screen 01 ----------------------------------------------------

def test_the_today_list_is_grouped_by_customer_never_by_contract(client):
    """Spec §7.1: "A customer holding several contracts has one officer and receives
    one contact covering all of them." A list keyed on contracts would let one
    customer be called twice in a day, which is the thing the Act forbids."""
    body = client.get("/v1/today-list").json()

    assert body["items"]
    for item in body["items"]:
        assert "customer" in item
        assert item["customer"]["contract_count"] >= 1
    keys = [item["customer"]["uid"] for item in body["items"]]
    assert len(keys) == len(set(keys)), "a customer appears twice — the list is keyed on contracts"


def test_every_today_list_item_carries_the_band_set_beside_the_bucket(client):
    assert_band_pair_present(client.get("/v1/today-list").json())


def test_the_today_list_reports_counts_by_priority(client):
    body = client.get("/v1/today-list").json()
    assert "counts_by_priority" in body["meta"]


def test_aggregate_overdue_reconciles_to_the_contracts_beneath_it(client):
    """The standing money rule: a fully-drawn column must reconcile exactly to its
    cards. This is the audit that found three downstream totals hanging off an
    impossible figure."""
    from decimal import Decimal

    body = client.get("/v1/today-list").json()
    for item in body["items"]:
        detail = client.get("/v1/customers/%s/contracts" % item["customer"]["uid"]).json()
        total = sum(Decimal(c["arrears"]) for c in detail["contracts"])
        assert Decimal(item["aggregate_overdue"]) == total, item["customer"]["uid"]


# --- contract card, screen 02 -------------------------------------------------

def test_the_contract_summary_leads_with_arrears_payable_today(client):
    """TC-COL-052: a response that leads with the next instalment FAILS the test."""
    uid = client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    contracts = client.get("/v1/customers/%s/contracts" % uid).json()["contracts"]
    body = client.get("/v1/contracts/%s/summary" % contracts[0]["uid"]).json()

    assert list(body.keys())[0] == "total_arrears_payable_today"


def test_every_penalty_figure_is_no_longer_indicative_now_that_cf1_is_decided(client):
    """Ruling 87 (Arina, 2026-09-09) closed CF1 and moved it into config.DECIDED — the
    rate is Owner-tunable, not a number still awaiting Legal, so the summary must
    stop calling it indicative and name the ruling that settled it instead."""
    uid = client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    contracts = client.get("/v1/customers/%s/contracts" % uid).json()["contracts"]
    body = client.get("/v1/contracts/%s/summary" % contracts[0]["uid"]).json()

    assert body["accrued_penalty"]["is_indicative"] is False
    assert body["accrued_penalty"]["decided_by_ruling"] == 87


def test_the_fee_total_decomposes_rather_than_netting(client):
    """REQ-MNY-032 item 6 — accrued, not-accrued-by-state broken down BY STATE, reversed."""
    uid = client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    contracts = client.get("/v1/customers/%s/contracts" % uid).json()["contracts"]
    penalty = client.get("/v1/contracts/%s/summary" % contracts[0]["uid"]).json()["accrued_penalty"]

    assert "accrued" in penalty
    assert "not_accrued_by_state" in penalty
    assert "reversed" in penalty


def test_raising_a_penalty_invoice_is_refused_while_the_flag_is_off(client, monkeypatch):
    """The spec forbids building the penalty engine's INVOICING until CF1 closes. The
    calculation ships as indicative; the write to PEAK does not ship at all."""
    # Ruling 87 flipped the default to True, so this test must turn it off itself to
    # keep exercising the disabled path. The patch lands in the SHARED session slot
    # (`monkeypatch.setattr` runs outside any request, so `session.CURRENT` reads its
    # ContextVar default — see session.py). This client's own first call would
    # otherwise be handed its own fresh, unpatched session by the `tester_session`
    # middleware (main.py) and never see the patch — the same hazard test_round4.py's
    # `client` fixture already documents — so it is pinned to `shared` too, here only,
    # rather than widening the fixture for all 25 other tests in this file.
    client.cookies.set("volt_session", "shared")
    monkeypatch.setattr(settings, "penalty_invoicing_enabled", False)
    uid = client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    contracts = client.get("/v1/customers/%s/contracts" % uid).json()["contracts"]
    response = client.post("/v1/contracts/%s/penalty-invoices" % contracts[0]["uid"], json={})

    assert response.status_code == 422
    assert response.json()["code"] == "feature_disabled"


# --- payments -----------------------------------------------------------------

def test_a_manual_payment_is_refused_while_the_allocation_order_is_unset(client):
    """TC-MNY-026: the manual path returns 422 allocation_rule_pending and WRITES
    NOTHING. The webhook path behaves differently on purpose so a real payment is
    never lost — that asymmetry is an engineering rule, not a spec rule."""
    uid = client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    contracts = client.get("/v1/customers/%s/contracts" % uid).json()["contracts"]
    response = client.post(
        "/v1/contracts/%s/transactions" % contracts[0]["uid"],
        json={"amount": "6000.00", "effective_date": "2026-10-23"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "allocation_rule_pending"
    assert "OD-02" in response.json()["extensions"]["pending_decision"]
    assert response.json()["extensions"]["owner"]


# --- contacts, the daily slot -------------------------------------------------

def test_a_second_counting_contact_the_same_day_is_409_contact_locked(client):
    uid = client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    payload = {
        "customer_uid": uid, "channel": "PHONE", "direction": "OUTBOUND",
        "disposition": "ANS_DISCUSSED", "at": "2026-10-23T09:10:00+07:00",
    }
    assert client.post("/v1/contacts", json=payload).status_code == 201

    second = client.post("/v1/contacts", json={**payload, "at": "2026-10-23T15:00:00+07:00"})
    assert second.status_code == 409
    assert second.json()["code"] == "contact_locked"
    assert second.json()["error_id"] == "DEBT-COL-0409"
    assert second.json()["retryable"] is False


def test_an_inbound_call_is_accepted_without_limit(client):
    uid = client.get("/v1/today-list").json()["items"][1]["customer"]["uid"]
    for hour in (9, 10, 11):
        response = client.post("/v1/contacts", json={
            "customer_uid": uid, "channel": "PHONE", "direction": "INBOUND",
            "disposition": "INBOUND_CALLED", "at": "2026-10-23T%02d:00:00+07:00" % hour,
        })
        assert response.status_code == 201
        assert response.json()["counted"] is False


# --- REQ-COL-055, the retraction window ---------------------------------------

def test_the_daily_slot_can_be_retracted_within_ninety_seconds(client):
    """REQ-COL-055. The slot is spent at amount-stated or 90 s, whichever is first."""
    uid = client.get("/v1/today-list").json()["items"][2]["customer"]["uid"]
    created = client.post("/v1/contacts", json={
        "customer_uid": uid, "channel": "PHONE", "direction": "OUTBOUND",
        "disposition": "ANS_DISCUSSED", "at": "2026-10-23T09:10:00+07:00",
    }).json()

    response = client.post("/v1/contacts/%s:retract" % created["contact_id"],
                           json={"at": "2026-10-23T09:11:00+07:00"})
    assert response.status_code == 200
    assert response.json()["slot_restored"] is True


def test_retraction_is_impossible_once_the_amount_has_been_stated(client):
    """"Retraction is impossible once the amount is stated, so the loophole closes
    itself." Ninety seconds is the ceiling, not the rule."""
    uid = client.get("/v1/today-list").json()["items"][3]["customer"]["uid"]
    created = client.post("/v1/contacts", json={
        "customer_uid": uid, "channel": "PHONE", "direction": "OUTBOUND",
        "disposition": "ANS_DISCUSSED", "at": "2026-10-23T09:10:00+07:00",
        "amount_stated": True,
    }).json()

    response = client.post("/v1/contacts/%s:retract" % created["contact_id"],
                           json={"at": "2026-10-23T09:10:30+07:00"})
    assert response.status_code == 422
    assert response.json()["code"] == "retraction_window_closed"


def test_retraction_after_ninety_seconds_is_refused(client):
    uid = client.get("/v1/today-list").json()["items"][4]["customer"]["uid"]
    created = client.post("/v1/contacts", json={
        "customer_uid": uid, "channel": "PHONE", "direction": "OUTBOUND",
        "disposition": "ANS_DISCUSSED", "at": "2026-10-23T09:10:00+07:00",
    }).json()

    response = client.post("/v1/contacts/%s:retract" % created["contact_id"],
                           json={"at": "2026-10-23T09:12:00+07:00"})
    assert response.status_code == 422
    assert response.json()["code"] == "retraction_window_closed"


# --- REQ-COL-054, board columns ------------------------------------------------

def test_a_board_column_is_identified_by_a_stable_id_not_by_its_name(client):
    """REQ-COL-054, closing RA-01. A rename is a non-event."""
    columns = client.get("/v1/board/columns").json()["columns"]

    for column in columns:
        assert column["column_id"]
        assert column["name"]
        assert column["column_id"] != column["name"]


def test_deleting_a_column_requires_a_nominated_destination(client):
    """The hazard none of the three original options named: customers standing on the
    deleted column have to go somewhere, and the Owner must say where, logged per
    customer."""
    columns = client.get("/v1/board/columns").json()["columns"]
    response = client.request("DELETE", "/v1/board/columns/%s" % columns[0]["column_id"], json={})

    assert response.status_code == 422
    assert response.json()["code"] == "destination_column_required"


# --- REQ-IAM-015, the vacant post ---------------------------------------------

def test_an_approval_path_naming_a_vacant_role_is_refused(client):
    """REQ-IAM-015. There is no Debt Manager in post, and the role held most approvals
    plus the sole authority to flag NPL. An escalation to a vacant post is an
    escalation to nobody, silently."""
    response = client.post("/v1/config/approval-paths",
                           json={"action": "mod.write_off.approve", "role": "DEBT_MANAGER"})

    assert response.status_code == 422
    assert response.json()["code"] == "authority_gap_blocks_approval"
    assert response.json()["extensions"]["vacant_role"] == "DEBT_MANAGER"


def test_the_owner_absorbs_the_vacant_roles_routes(client):
    response = client.post("/v1/config/approval-paths",
                           json={"action": "mod.write_off.approve", "role": "OWNER"})
    assert response.status_code == 201


def test_livez_is_the_alias_a_deployed_estate_must_use(client):
    """/healthz is reserved by Google's front end on *.run.app — it answers 404
    before the container sees it. /livez is the same handler, and the smoke tools
    point at it (2026-09-21, found while smoke-testing staging)."""
    live = client.get("/livez")
    assert live.status_code == 200
    assert live.json().get("status") == "ok"
    assert live.json() == client.get("/healthz").json()
