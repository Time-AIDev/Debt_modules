"""History navigation reads exact immutable findings and exact case identifiers."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app import journey, main
from app.routers import service_deferrals, terminated


@pytest.fixture
def history(monkeypatch):
    customer = main.CUSTOMERS[0]
    row = {
        "uid": "sdef-history", "customer_uid": customer.uid,
        "customer_no": str(customer.customer_no), "contract_uid": "contract-history",
        "status": "REVERSED", "moves": [{"n": 1, "new_due_date": "2027-01-01"}],
        "accounting": {
            "status": "PENDING_REVIEW", "note": "latest value must not replace findings",
            "history": [
                {"at": "2026-10-07T08:00:00+07:00", "by": "accounting-one", "role": "OPS",
                 "status": "REVIEWED", "note": "first finding", "document_refs": ["IV-SYNTHETIC"]},
                {"at": "2026-10-07T02:00:00Z", "by": "accounting-two", "role": "OPS",
                 "status": "PENDING_REVIEW", "note": "second finding", "document_refs": []},
            ],
        },
    }
    historical = {
        **deepcopy(row), "uid": "sdef-archived", "customer_uid": "archived-customer",
        "contract_uid": "archived-contract", "customer_name": "Archived synthetic customer",
    }
    monkeypatch.setattr(service_deferrals.domain, "records", lambda: [row, historical])
    client = TestClient(main.app)
    client.cookies.set("volt_session", "history-test")
    return client, row, historical


def test_history_filters_exact_customer_contract_and_deferral_with_full_total(history):
    client, row, _ = history
    response = client.get("/v1/service-deferrals/history", params={
        "customer_uid": row["customer_uid"], "contract_uid": row["contract_uid"],
        "deferral_uid": row["uid"], "page_size": 1,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["meta"] == {"total": 2, "page": 1, "page_size": 1}
    assert result["entries"][0]["note"] == "second finding"
    assert result["entries"][0]["deferral_status"] == "REVERSED"
    second = client.get("/v1/service-deferrals/history", params={
        "customer_uid": row["customer_uid"], "page": 2, "page_size": 1,
    }).json()
    assert second["entries"][0]["note"] == "first finding"
    assert second["entries"][0]["document_refs"] == ["IV-SYNTHETIC"]
    assert second["entries"][0]["uid"] != result["entries"][0]["uid"]
    assert client.get("/v1/service-deferrals/history", params={
        "customer_uid": row["customer_uid"], "contract_uid": "archived-contract",
    }).json()["meta"]["total"] == 0


def test_history_keeps_archived_customer_and_does_not_mutate_stored_evidence(history):
    client, row, historical = history
    before = deepcopy([row, historical])
    response = client.get("/v1/service-deferrals/history", params={
        "customer_uid": "archived-customer",
    })
    assert response.status_code == 200
    assert response.json()["entries"][0]["customer_name"] == "Archived synthetic customer"
    assert [row, historical] == before
    returned = service_deferrals.accounting_history(
        customer_uid=row["customer_uid"], contract_uid=None, deferral_uid=None, page=1, page_size=50)
    returned["entries"][0]["moves"][0]["n"] = 99
    returned["entries"][1]["document_refs"].clear()
    assert [row, historical] == before


def test_naive_history_time_is_legacy_bangkok_time_not_utc(history):
    client, row, _ = history
    row["accounting"]["history"][0]["at"] = "2026-10-07T08:00:00"
    result = client.get("/v1/service-deferrals/history", params={"customer_uid": row["customer_uid"]}).json()
    assert [entry["note"] for entry in result["entries"]] == ["second finding", "first finding"]


@pytest.mark.parametrize("query", [{"page": 0}, {"page_size": 0}, {"page_size": 201},
                                    {"customer_uid": ""}, {"contract_uid": "x" * 201}])
def test_history_rejects_invalid_pagination_and_identifiers(history, query):
    client, _, _ = history
    assert client.get("/v1/service-deferrals/history", params=query).status_code == 422


def test_termination_history_uses_exact_customer_uid_not_name_search(monkeypatch):
    records = [{
        "archive_uid": "archive-" + uid, "customer_uid": uid, "customer_name": "Same name",
        "customer_no": "Same number", "volt_id": "Same display code", "captured_at": "2026-10-07T12:00:00Z",
        "terminated_on": "2026-10-07", "causes": ["DEFAULT"], "actor": "synthetic-officer",
        "source": "PERSON", "snapshot": {"immutable": True},
    } for uid in ("customer-one", "customer-one-extra")]
    monkeypatch.setattr(terminated.archive, "records", lambda: records)
    monkeypatch.setattr(journey, "customer_by_uid", lambda uid: None)
    client = TestClient(main.app)
    response = client.get("/v1/terminated-customers", params={"customer_uid": "customer-one"})
    assert response.status_code == 200
    assert response.json()["meta"]["total"] == 1
    assert response.json()["entries"][0]["customer_uid"] == "customer-one"
    assert "snapshot" not in response.json()["entries"][0]
    assert client.get("/v1/terminated-customers", params={"customer_uid": "customer"}).json()["meta"]["total"] == 0


def test_history_keeps_repeated_archives_when_customer_has_new_active_contract(monkeypatch):
    from types import SimpleNamespace
    rows = [{"archive_uid": "archive-%d" % n, "customer_uid": "same-customer",
             "customer_name": "Synthetic", "captured_at": "2026-10-0%dT00:00:00Z" % n,
             "terminated_on": "2026-10-0%d" % n, "causes": ["DEFAULT"],
             "actor": "synthetic", "source": "PERSON", "snapshot": {"immutable": n}}
            for n in (1, 2)]
    monkeypatch.setattr(terminated.archive, "records", lambda: rows)
    monkeypatch.setattr(journey, "customer_by_uid", lambda uid: SimpleNamespace(
        contracts=[SimpleNamespace(status="ACTIVE")]))
    monkeypatch.setattr(terminated.cases, "contract_field_of", lambda item, field: getattr(item, field))
    client = TestClient(main.app)
    assert client.get("/v1/terminated-customers", params={"customer_uid": "same-customer"}).json()["meta"]["total"] == 0
    result = client.get("/v1/terminated-customers", params={"customer_uid": "same-customer", "history": True}).json()
    assert result["meta"]["total"] == 2
    assert [row["archive_uid"] for row in result["entries"]] == ["archive-2", "archive-1"]
    assert all("snapshot" not in row for row in result["entries"])
