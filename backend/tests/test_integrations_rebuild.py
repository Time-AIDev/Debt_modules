"""R13–R16 — the integration seams, tested without any network.

Secrets discipline is load-bearing here: every assertion about credentials is about
their NAMES. No test sets or reads a real value.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.integrations import peak as peak_client


@pytest.fixture()
def client():
    return TestClient(app)


def test_status_names_env_vars_and_never_values(client):
    body = client.get("/v1/integrations/status").json()
    assert body["odoo"]["fallback_chain"] == ["ODOO", "SHEET_FIXTURES"]    # no snapshot rung since 2026-09-25
    for name in body["odoo"]["missing_env"] + body["peak"]["missing_env"]:
        assert name.isupper() and ("ODOO" in name or "PEAK" in name)


def test_unconfigured_odoo_refuses_with_the_variable_names(client, monkeypatch):
    monkeypatch.setattr("app.integrations.odoo.env", lambda k, d=None: None)
    response = client.get("/v1/integrations/odoo/discovery")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "integration_not_configured"
    assert set(body["extensions"]["missing_env"]) == {
        "ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY"}


def test_a_status_override_carries_full_provenance(client):
    order_no = client.get("/v1/orders").json()["items"][0]["no"]
    # No reason → refused; nothing stored.
    refused = client.post("/v1/orders/%d/status-override" % order_no,
                          json={"adjusted_value": "Declined"})
    assert refused.status_code == 422
    created = client.post("/v1/orders/%d/status-override" % order_no, json={
        "adjusted_value": "Declined", "reason": "customer withdrew, Odoo lags",
        "by": "noon"})
    assert created.status_code == 201
    override = created.json()["override"]
    assert override["source_value"] is not None
    assert override["adjusted_value"] == "Declined"
    assert override["by"] == "noon"
    assert override["source_changed_since_override"] is False
    # Adjusting to the same value is refused — an audit row that changes nothing.
    same = client.post("/v1/orders/%d/status-override" % order_no, json={
        "adjusted_value": override["source_value"], "reason": "noop", "by": "noon"})
    assert same.status_code == 422
    assert same.json()["code"] == "override_source_unchanged"


def test_peak_failure_degrades_to_unsent_and_success_creates_a_draft(client, monkeypatch):
    """INT-004 as amended by PKD-001..005 (C3): the route creates a DRAFT and a
    draft carries no QR; approval and the QR come from PEAK itself."""
    from app import peak_documents as pkd
    invoices = client.get("/v1/ar/pipeline").json()["invoices"]
    # Round-5 T5-02 reordered this list so the oldest unpaid invoice comes first, and
    # the migrated sheet invoices at the top are already recorded in PEAK. This test
    # needs one that is NOT, so it says so rather than trusting the order.
    invoice = next(i for i in invoices
                   if i["state"] in ("SENT", "ISSUED", "OVERDUE")
                   and i.get("peak_state") not in ("DRAFT_CREATED", "APPROVED_IN_PEAK"))

    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport(fail_create=True)
    failed = client.post("/v1/invoices/%s:issue-peak" % invoice["uid"])
    assert failed.status_code == 502
    body = failed.json()
    assert body["code"] == "peak_unsent"
    assert body["extensions"]["peak_state"] == "UNSENT"
    # The invoice is NOT lost — it stays local, marked UNSENT, re-sendable.
    after = client.get("/v1/contracts/%s/invoices" % invoice["contract_uid"]).json()
    row = next(i for i in after["invoices"] if i["uid"] == invoice["uid"])
    assert row["peak_state"] == "UNSENT"

    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    sent = client.post("/v1/invoices/%s:issue-peak" % invoice["uid"])
    assert sent.status_code == 201
    assert sent.json()["invoice"]["peak_state"] == "DRAFT_CREATED"
    assert sent.json()["invoice"]["peak_ref"]
    assert sent.json()["invoice"]["qr_payload"] is None      # no QR on a draft (PC3)
    assert sent.json()["peak_document"]["idempotency_key"].startswith("debt-")
    # Re-issuing a document PEAK already holds is a duplicate create — refused.
    again = client.post("/v1/invoices/%s:issue-peak" % invoice["uid"])
    assert again.status_code == 409
