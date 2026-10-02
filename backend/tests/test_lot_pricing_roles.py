"""Who may price a repossession lot — a role, not the name "Dan" (Arina, 2026-09-14).

Deck S12 gives the resale price to Operations; the Owner may also set it. Any other
role is refused 403, like every other role refusal. A malformed price is still named
as a price problem first, whoever sends it.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _graded_lot():
    lots = client.get("/v1/repossession-lots").json()["lots"]
    return next(l for l in lots if l["status"] == "GRADED")


def _price(lot, role, price="50000", by="someone"):
    return client.post("/v1/repossession-lots/%s:price" % lot["uid"],
                       json={"by": by, "resale_price": price}, headers={"X-Volt-Role": role})


@pytest.mark.parametrize("role", ["OPS", "OWNER"])
def test_operations_and_the_owner_may_price(role):
    lot = _graded_lot()
    r = _price(lot, role)
    assert r.status_code == 200
    assert r.json()["lot"]["status"] == "PRICED"
    assert r.json()["lot"]["priced_by_role"] == role
    assert r.json()["lot"]["stock_blocked"] is False


@pytest.mark.parametrize("role", ["OFFICER", "SUPERVISOR", "MANAGER"])
def test_every_other_role_is_refused_403(role):
    lot = _graded_lot()
    r = _price(lot, role, by="Dan")
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "forbidden"
    assert body["extensions"]["allowed_roles"] == ["OPS", "OWNER"]
    assert body["message_th"]
    # refused means nothing was saved: the lot is still unpriced and blocked
    again = next(l for l in client.get("/v1/repossession-lots").json()["lots"] if l["uid"] == lot["uid"])
    assert again["status"] == "GRADED" and again["resale_price"] is None


def test_a_bad_price_is_a_price_problem_even_from_a_role_that_may_not_price():
    lot = _graded_lot()
    r = _price(lot, "OFFICER", price="0")
    assert r.status_code == 422
    assert r.json()["code"] == "validation_failed"


def test_the_blocked_stock_problem_names_roles_not_a_person():
    lot = _graded_lot()
    r = client.post("/v1/repossession-lots/%s:sell" % lot["uid"], json={})
    assert r.json()["code"] == "resale_price_unset"
    assert r.json()["extensions"]["priced_by_roles"] == ["OPS", "OWNER"]
    assert "Dan" not in r.json()["message_th"]
