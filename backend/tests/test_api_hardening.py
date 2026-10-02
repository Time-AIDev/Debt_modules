"""Findings from the blind adversarial pass, pinned as tests.

Each of these was found by an agent that could see the HTTP surface and the spec but
NOT the source. That is the point: a bug you can only see in the implementation is one
the unit tests already cover.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

PROBLEM = "application/problem+json"


@pytest.fixture
def client():
    return TestClient(app)


class TestEveryErrorIsProblemJson:
    """§2.4 fixes ONE envelope. A client that branches on `code` cannot do so when the
    framework answers with its own shape, and `message_th` is specified as ALWAYS
    present — a Thai-speaking officer gets nothing from FastAPI's default body."""

    REQUIRED = ("type", "title", "status", "code", "error_id", "message_th",
                "retryable", "errors", "extensions")

    def test_an_unknown_route_is_problem_json(self, client):
        response = client.get("/v1/no-such-thing")
        assert response.headers["content-type"].startswith(PROBLEM)
        for field in self.REQUIRED:
            assert field in response.json(), field

    def test_a_wrong_method_is_problem_json(self, client):
        response = client.delete("/v1/today-list")
        assert response.status_code == 405
        assert response.headers["content-type"].startswith(PROBLEM)
        assert response.json()["message_th"]

    def test_a_malformed_body_is_problem_json_with_field_errors(self, client):
        response = client.post("/v1/contacts", content=b"{not json",
                               headers={"Content-Type": "application/json"})
        assert response.headers["content-type"].startswith(PROBLEM)
        body = response.json()
        assert body["code"] in ("malformed_request", "validation_failed")
        assert isinstance(body["errors"], list)

    def test_a_missing_required_field_reports_a_pointer(self, client):
        response = client.post("/v1/contacts", json={"customer_uid": "nope"})
        assert response.headers["content-type"].startswith(PROBLEM)
        assert response.json()["errors"]
        assert response.json()["errors"][0]["pointer"].startswith("/")


class TestARefusalNeverStampsAFabricatedAnswer:
    def test_the_dashboard_actually_applies_the_population_it_prints(self, client):
        """The sharpest finding of the blind pass: the endpoint echoed whatever
        population it was given onto its own face while returning the whole book.

        A dashboard that prints a population it did not apply is worse than one that
        refuses — the refusal is honest and the echo is not.
        """
        everything = client.get("/v1/dashboards/exceptions",
                                params={"population_filter": "ALL_OPEN"}).json()
        held = client.get("/v1/dashboards/exceptions",
                          params={"population_filter": "PERMIT_HELD"}).json()

        assert held["population_filter"] == "PERMIT_HELD"
        assert len(held["rows"]) < len(everything["rows"])
        assert all(r["fee_state"] == "PERMIT_HOLD" for r in held["rows"])

    def test_an_unknown_population_is_refused_rather_than_silently_widened(self, client):
        response = client.get("/v1/dashboards/exceptions",
                              params={"population_filter": "SOMETHING_MADE_UP"})
        assert response.status_code == 422
        assert response.json()["code"] == "population_filter_unknown"
        assert response.json()["extensions"]["known_filters"]

    def test_a_whitespace_population_is_treated_as_unset_not_as_a_value(self, client):
        response = client.get("/v1/dashboards/exceptions", params={"population_filter": "   "})
        assert response.status_code == 422
        assert response.json()["code"] == "population_filter_unset"


class TestExistenceIsCheckedBeforeBusinessRules:
    """Answering a business-rule 422 for a contract that does not exist tells an
    integrator their payload was wrong when their id was wrong."""

    def test_a_transaction_on_an_unknown_contract_is_404(self, client):
        response = client.post("/v1/contracts/K-DOES-NOT-EXIST/transactions",
                               json={"amount": "100.00", "effective_date": "2026-10-23"})
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    def test_a_penalty_invoice_on_an_unknown_contract_is_404(self, client):
        assert client.post("/v1/contracts/K-NOPE/penalty-invoices", json={}).status_code == 404

    def test_deleting_an_unknown_column_is_404_not_an_invented_customer_count(self, client):
        response = client.request("DELETE", "/v1/board/columns/col_NOT_REAL", json={})
        assert response.status_code == 404

    def test_deleting_into_a_destination_that_does_not_exist_is_refused(self, client):
        columns = client.get("/v1/board/columns").json()["columns"]
        response = client.request(
            "DELETE", "/v1/board/columns/%s" % columns[0]["column_id"],
            json={"destination_column_id": "col_IMAGINARY"},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "destination_column_unknown"


class TestParametersAreAppliedOrRefused:
    def test_an_unsupported_business_date_is_refused_rather_than_ignored(self, client):
        """The prototype runs on one business date. Accepting `date` and ignoring it
        lets a caller believe they asked a question the server never answered."""
        response = client.get("/v1/today-list", params={"date": "2025-01-01"})
        assert response.status_code == 422
        assert response.json()["code"] == "business_date_unavailable"

    def test_the_current_business_date_is_accepted(self, client):
        from app.config import settings
        response = client.get("/v1/today-list", params={"date": str(settings.business_date)})
        assert response.status_code == 200


def test_the_early_settlement_decision_is_labelled_od_03(client):
    """The blind pass caught this: the register said OD-04, which is the NPL threshold.
    OD-03 is early settlement, owned by Owner with Accounting and Legal."""
    pending = {p["key"]: p for p in client.get("/v1/config/pending").json()["pending"]}
    assert pending["early_settlement_method"]["decision"] == "OD-03"
    assert pending["npl_dpd_threshold_days"]["decision"] != "OD-03"
