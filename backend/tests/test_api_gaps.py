"""Gaps found by building the screens against this API.

Each one is a case where the interface could not honour a rule because the wire did
not carry what the rule needs. That is an API defect, not a UI problem: "no arithmetic
in the interface" only works if the API sends the figures.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_the_contact_lock_names_the_officer_not_the_customers_identity_hash(client):
    """An officer reading "held by identity:hash:C-001067" learns nothing.

    The lock is KEYED on the customer's identity — that part is right — but the field
    an officer reads has to say WHO holds today's slot and WHEN they took it.
    """
    item = client.get("/v1/today-list").json()["items"][0]
    client.post("/v1/contacts", json={
        "customer_uid": item["customer"]["uid"], "channel": "PHONE", "direction": "OUTBOUND",
        "disposition": "ANS_DISCUSSED", "at": "2026-10-23T09:10:00+07:00", "officer": "noon",
    })

    refreshed = next(
        i for i in client.get("/v1/today-list").json()["items"]
        if i["customer"]["uid"] == item["customer"]["uid"]
    )
    lock = refreshed["contact_lock"]

    assert lock["state"] == "LOCKED"
    assert lock["locked_by"] == "noon"
    assert "identity:hash" not in str(lock["locked_by"])
    assert lock["locked_at"]
    assert lock["result"] == "ANS_DISCUSSED"


def test_every_today_list_item_says_which_board_column_the_run_placed_it_in(client):
    """REQ-COL-054: a column's identity is its id, never its name.

    If the item does not carry a column id, the only way to place a card is to match
    the column's NAME against something — exactly the derivation the requirement
    forbids, and it breaks on the next Owner rename.
    """
    body = client.get("/v1/today-list").json()
    valid = {c["column_id"] for c in client.get("/v1/board/columns").json()["columns"]}

    for item in body["items"]:
        assert "board_column_id" in item, item["customer"]["customer_no"]
        assert item["board_column_id"] in valid


def test_every_today_list_item_carries_the_outstanding_balance_beside_the_arrears(client):
    """The standing money rule is arrears large, balance small BENEATH IT. A wire that
    carries only arrears makes the rule unimplementable without inventing a figure."""
    from decimal import Decimal

    for item in client.get("/v1/today-list").json()["items"]:
        assert "aggregate_outstanding" in item
        contracts = client.get(
            "/v1/customers/%s/contracts" % item["customer"]["uid"]
        ).json()["contracts"]
        expected = sum(Decimal(c["outstanding_balance"]) for c in contracts)
        assert Decimal(item["aggregate_outstanding"]) == expected


def test_the_instalment_rows_of_a_contract_are_reachable(client):
    """The schedule table cannot be built from contract-level totals, and deriving the
    rows in the browser is banned."""
    contracts = client.get(
        "/v1/customers/%s/contracts" % client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    ).json()["contracts"]
    body = client.get("/v1/contracts/%s/instalments" % contracts[0]["uid"]).json()

    assert body["instalments"]
    row = body["instalments"][0]
    for field in ("no", "due_date", "amount", "paid", "outstanding", "status", "category"):
        assert field in row, field


def test_the_instalment_rows_reconcile_to_the_contract_totals(client):
    """The reconciliation that catches a schedule drifting from its header."""
    from decimal import Decimal

    contracts = client.get(
        "/v1/customers/%s/contracts" % client.get("/v1/today-list").json()["items"][0]["customer"]["uid"]
    ).json()["contracts"]
    contract = contracts[0]
    body = client.get("/v1/contracts/%s/instalments" % contract["uid"]).json()

    outstanding = sum(Decimal(r["outstanding"]) for r in body["instalments"] if r["category"] == "REGULAR")
    assert outstanding == Decimal(contract["outstanding_balance"])
    assert body["total_amount"] == str(sum(Decimal(r["amount"]) for r in body["instalments"]))


def test_the_instalment_list_says_the_final_row_may_differ(client):
    """REQ-MNY-003: the final instalment is the balancing figure. Accounting must be
    told before the first customer statement — so the schedule header states it."""
    contracts = client.get(
        "/v1/customers/%s/contracts" % client.get("/v1/today-list").json()["items"][1]["customer"]["uid"]
    ).json()["contracts"]
    body = client.get("/v1/contracts/%s/instalments" % contracts[0]["uid"]).json()

    assert body["final_installment_amount"]
    assert body["installment_amount"]
