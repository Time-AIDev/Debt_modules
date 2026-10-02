"""Round-two blind findings, adjudicated REAL and pinned here.

Three of these are bypasses: a control that can be walked around is worse than no
control, because it is documented as protection.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.money.band_sets import BAND_SETS, resolve_band


@pytest.fixture
def client():
    return TestClient(app)


def a_customer(client, index=0):
    return client.get("/v1/today-list").json()["items"][index]["customer"]["uid"]


class TestTheRetractionWindowIsNotSigned:
    """REQ-COL-055 BYPASS. The window was `now - start > 90s`, which is a SIGNED
    comparison: a retraction stamped EARLIER than the contact always passes it.

    An officer could spend the customer's daily slot, then hand back a retraction dated
    an hour before the call and get the slot returned every time — an unlimited-contact
    hole in the one rule the Thai Debt Collection Act actually fixes.
    """

    def _log(self, client, customer_uid, at="2026-10-23T12:00:00+07:00", amount_stated=False):
        return client.post("/v1/contacts", json={
            "customer_uid": customer_uid, "channel": "PHONE", "direction": "OUTBOUND",
            "disposition": "ANS_DISCUSSED", "at": at, "officer": "noon",
            "amount_stated": amount_stated,
        }).json()

    def test_a_retraction_dated_before_the_contact_is_refused(self, client):
        created = self._log(client, a_customer(client, 0))
        response = client.post("/v1/contacts/%s:retract" % created["contact_id"],
                               json={"at": "2026-10-23T11:40:00+07:00"})

        assert response.status_code == 422
        assert response.json()["code"] == "retraction_window_closed"

    def test_a_retraction_inside_the_window_still_works(self, client):
        created = self._log(client, a_customer(client, 1))
        response = client.post("/v1/contacts/%s:retract" % created["contact_id"],
                               json={"at": "2026-10-23T12:01:00+07:00"})
        assert response.status_code == 200
        assert response.json()["slot_restored"] is True

    def test_the_boundary_is_ninety_seconds(self, client):
        created = self._log(client, a_customer(client, 2))
        assert client.post("/v1/contacts/%s:retract" % created["contact_id"],
                           json={"at": "2026-10-23T12:01:29+07:00"}).status_code == 200

        created = self._log(client, a_customer(client, 3))
        assert client.post("/v1/contacts/%s:retract" % created["contact_id"],
                           json={"at": "2026-10-23T12:01:31+07:00"}).status_code == 422


class TestTheVacancyGuardCannotBeSpelledAround:
    """REQ-IAM-015 BYPASS. The guard matched one exact byte string, so `debt_manager`,
    `Debt_Manager` and a padded `" DEBT_MANAGER "` all seeded a route to a post nobody
    holds — an escalation to nobody, silently, which is the exact failure the
    requirement exists to prevent."""

    @pytest.mark.parametrize("spelling", [
        "debt_manager", "Debt_Manager", "  DEBT_MANAGER  ", "debt manager", "DEBT-MANAGER",
    ])
    def test_every_spelling_of_a_vacant_role_is_refused(self, client, spelling):
        response = client.post("/v1/config/approval-paths",
                               json={"action": "mod.write_off.approve", "role": spelling})
        assert response.status_code == 422, spelling
        assert response.json()["code"] == "authority_gap_blocks_approval"

    def test_a_list_of_roles_containing_a_vacant_one_is_refused(self, client):
        response = client.post("/v1/config/approval-paths",
                               json={"action": "mod.write_off.approve",
                                     "role": ["OWNER", "debt_manager"]})
        assert response.status_code == 422

    def test_a_filled_role_is_still_accepted(self, client):
        assert client.post("/v1/config/approval-paths",
                           json={"action": "mod.write_off.approve", "role": "OWNER"}
                           ).status_code == 201


class TestTheLockRefusalCarriesTrueEvidence:
    def test_locked_at_is_when_the_slot_was_taken_not_when_it_was_refused(self, client):
        """A 409 that reports the REFUSED attempt's own timestamp tells the officer the
        customer was contacted at a time they were not. It is the sentence that goes in
        front of a customer during a complaint."""
        uid = a_customer(client, 4)
        # Round-4 J4-01: the row is stamped from the BUSINESS clock, so the evidence in
        # the refusal is the first contact's own business stamp — never the client's
        # wall clock, and never the refused attempt's moment.
        first = client.post("/v1/contacts", json={
            "customer_uid": uid, "channel": "PHONE", "direction": "OUTBOUND",
            "disposition": "ANS_DISCUSSED", "at": "2026-10-23T08:00:00+07:00", "officer": "noon"}).json()

        refused = client.post("/v1/contacts", json={
            "customer_uid": uid, "channel": "PHONE", "direction": "OUTBOUND",
            "disposition": "ANS_DISCUSSED", "at": "2026-10-23T21:45:00+07:00", "officer": "ploy"})

        assert refused.status_code == 409
        extensions = refused.json()["extensions"]
        assert first["at"][11:19] in str(extensions["locked_at"])
        assert "21:45" not in str(extensions["locked_at"])
        assert extensions["locked_by"] == "noon"


class TestTheBandSetsAreTheSeededOnes:
    """The seeded sets are OPERATIONAL (the queue's design bands) and LEGACY_LDR (the
    boundaries the existing reporting uses at 30/45/60/75/90). A name invented here
    would not join to ref.aging_band_set."""

    def test_both_seeded_sets_exist_under_their_real_names(self):
        assert "OPERATIONAL" in BAND_SETS
        assert "LEGACY_LDR" in BAND_SETS

    def test_the_two_sets_overlap_by_construction(self):
        """They overlap on purpose — which is why the non-overlap constraint has to be
        scoped WITHIN a set. At DPD 45 the two sets give different answers."""
        assert resolve_band("PAST_DUE", 45, "OPERATIONAL").code == "RISK_REVIEW"
        assert resolve_band("PAST_DUE", 45, "LEGACY_LDR").code != "RISK_REVIEW"

    def test_the_api_stamps_the_collection_status_set(self, client):
        for item in client.get("/v1/today-list").json()["items"]:
            assert item["band_set_code"] == "COLLECTION_STATUS_V1"


def test_a_report_names_its_population_its_band_set_and_its_discount_rate(client):
    """RB-KPI-01, verbatim: "Read the report's own face: population filter, band set,
    discount rate version. If any is absent the run is void." """
    meta = client.get("/v1/dashboards/exceptions",
                      params={"population_filter": "ALL_OPEN"}).json()["meta"]

    assert meta["population_filter"] == "ALL_OPEN"
    assert meta["band_set_code"] == "COLLECTION_STATUS_V1"
    # Unset is a legitimate value here — OQ-31 is open — but it must be STATED, because
    # a run that does not name it is void whether or not the value exists.
    assert "discount_rate_version" in meta


def test_error_ids_match_the_catalogue(client):
    """error_id is what a support ticket quotes. A wrong one sends someone to the wrong
    requirement; a COLLIDING one sends two different failures to the same place."""
    uid = a_customer(client, 0)
    contract = client.get("/v1/customers/%s/contracts" % uid).json()["contracts"][0]["uid"]

    allocation = client.post("/v1/contracts/%s/transactions" % contract,
                             json={"amount": "100.00", "effective_date": "2026-10-23"})
    assert allocation.json()["error_id"] == "DEBT-MNY-0423"

    columns = client.get("/v1/board/columns").json()["columns"]
    deletion = client.request("DELETE", "/v1/board/columns/%s" % columns[0]["column_id"], json={})
    # DEBT-COL-0424 already belongs to next_contact_required.
    assert deletion.json()["error_id"] != "DEBT-COL-0424"


class TestPlatformConventions:
    def test_a_request_id_is_echoed_and_becomes_the_problem_instance(self, client):
        """X-Request-Id is generated when absent and ALWAYS echoed, and it is the
        `instance` of every problem response. A constant instance means a refused
        contact cannot be tied to its audit row."""
        response = client.get("/v1/dashboards/exceptions", headers={"X-Request-Id": "req-abc-123"})
        assert response.headers.get("x-request-id") == "req-abc-123"
        assert response.json()["instance"] == "urn:request:req-abc-123"

    def test_a_request_id_is_generated_when_absent(self, client):
        first = client.get("/v1/today-list").headers.get("x-request-id")
        second = client.get("/v1/today-list").headers.get("x-request-id")
        assert first and second and first != second

    def test_personal_data_is_not_cacheable(self, client):
        """The today list carries display names and masked phone numbers."""
        assert client.get("/v1/today-list").headers.get("cache-control") == "no-store"

    def test_a_dictionary_endpoint_may_be_cached(self, client):
        assert client.get("/v1/board/columns").headers.get("cache-control") != "no-store"
