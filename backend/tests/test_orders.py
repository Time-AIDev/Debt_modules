"""Orders and the loan book.

The facts under test are the two that the sheet itself makes easy to get wrong:
the imported status is not the queue's status, and approving APPENDS to the loan
book rather than updating a row in it.
"""
import pytest
from fastapi.testclient import TestClient

from app import orders as orders_domain
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    orders_domain.reset()
    yield
    orders_domain.reset()


def test_queue_seeds_every_order_as_pending_not_as_the_sheet_says():
    body = client.get("/v1/orders").json()
    assert body["counts"]["pending"] == len(body["items"])
    assert body["counts"]["done"] == 0
    # Every row in tab 'x' already reads Done. The queue must not inherit that,
    # and must not hide it either.
    assert {r["order_status"] for r in body["items"]} == {orders_domain.STATUS_PENDING}
    assert "Order - Done" in {r["sheet_order_status"] for r in body["items"]}


def test_approving_moves_the_order_and_appends_one_lease():
    before = client.get("/v1/loan-book").json()["counts"]
    approved = client.post("/v1/orders/1/approve", json={"by": "Nok"})
    assert approved.status_code == 200
    assert approved.json()["order"]["order_status"] == orders_domain.STATUS_DONE

    after = client.get("/v1/loan-book").json()
    assert after["counts"]["total"] == before["total"] + 1
    assert after["counts"]["from_sheet"] == before["from_sheet"]
    assert after["counts"]["approved_here"] == 1
    # Appended, not merged: the sheet's own cohort is untouched.
    assert after["entries"][-1]["origin"] == "approved"
    assert after["entries"][-1]["customer_id"] == "SYN-ORDER-001"


def test_approving_twice_is_refused_so_one_install_is_never_two_leases():
    client.post("/v1/orders/1/approve", json={"by": "Nok"})
    again = client.post("/v1/orders/1/approve", json={"by": "Nok"})
    assert again.status_code == 409
    assert again.json()["code"] == "order_already_approved"
    assert client.get("/v1/loan-book").json()["counts"]["approved_here"] == 1


def test_a_new_lease_leaves_unsupplied_fields_absent_rather_than_zero():
    client.post("/v1/orders/1/approve", json={"by": "Nok"})
    entry = client.get("/v1/loan-book").json()["entries"][-1]
    # Tab 'x' carries none of these. A zero here is a number somebody can lend against.
    for field in ("original_cost_thb", "book_value_usd", "commencement_date", "age_years"):
        assert entry[field] is None
    # What it CAN carry, it carries.
    assert entry["monthly_incl_vat_thb"] == "3199.00"
    assert entry["system_size_kwp"] == "5.00"
    assert entry["total_lease_incl_vat_thb"] == "307104.00"


def test_an_unknown_status_filter_is_refused_not_widened():
    response = client.get("/v1/orders", params={"order_status": "Order - Whatever"})
    assert response.status_code == 422
    assert response.json()["code"] == "order_status_unknown"


def test_the_filter_and_search_narrow_the_same_population():
    pending = client.get(
        "/v1/orders", params={"order_status": orders_domain.STATUS_PENDING}
    ).json()
    assert len(pending["items"]) == pending["counts"]["pending"]
    found = client.get("/v1/orders", params={"q": "SYN-ORDER-001"}).json()
    assert [r["no"] for r in found["items"]] == [1]


def test_contact_details_never_leave_the_importer_unmasked():
    items = client.get("/v1/orders").json()["items"]
    for row in items:
        assert "phone" not in row, "the raw phone column must not be served"
        # 2026-09-20: the Odoo sync row carries phone_e164, and `{**order}` spread it
        # onto this list. The full number is served only by the case's audited
        # phone:reveal route now.
        assert "phone_e164" not in row, "the full number must not be served on a list"
        if row["phone_masked"]:
            assert "x-xxx-" in row["phone_masked"]
        if row["email_masked"]:
            assert "•••@" in row["email_masked"]


# --- 2026-09-20 sync audit: overlays follow the ORDER, not its position ---------------
# The Odoo sale.order rows (and the switch/reorder tests that fed them) went on
# 2026-09-25; the sheet rows are the only orders rung, and legacy positional refs
# still resolve against them.

def _bound(sid, call):
    """A direct store call bound to one session id — the same slot a browser with that
    cookie reads."""
    from app import session as session_domain

    token = session_domain.CURRENT.set(sid)
    try:
        return call()
    finally:
        session_domain.CURRENT.reset(token)


def test_an_override_keyed_by_position_still_resolves_after_the_key_change():
    from app import journey

    sid = "sess-orders-legacy-override"

    def write_and_reconcile():
        rows = orders_domain.orders()
        first = rows[0]
        ref = "order:%s:loan_status" % first["no"]          # the legacy positional ref
        state = journey.for_current()
        state.overrides[ref] = {
            "ref": ref, "field": "loan_status",
            "source_value": "Pending review", "adjusted_value": "Declined",
            "by": "noon", "reason": "lagging", "on": "2026-09-14",
            "source_system": "SHEET", "source_changed_since_override": False,
        }
        lookup = {orders_domain._key(o): o for o in rows} | {str(o["no"]): o for o in rows}
        moved = journey.reconcile_overrides(lookup)
        return ref, first["loan_status"], state.overrides[ref], moved

    ref, live, record, moved = _bound(sid, call=write_and_reconcile)
    assert live != "Pending review"
    # the live source no longer reads what the override saw, so it is marked source-moved
    assert record["source_changed_since_override"] is True
    assert moved["changed"] == [ref]
    assert record["source_missing"] is False


def test_an_override_for_a_vanished_order_is_flagged_not_deleted():
    from app import journey

    sid = "sess-orders-vanished-override"

    def write_and_reconcile():
        state = journey.for_current()
        state.overrides["order:SO-OLD_ODOO:loan_status"] = {
            "ref": "order:SO-OLD_ODOO:loan_status", "field": "loan_status",
            "source_value": "Approved", "adjusted_value": "Declined",
            "by": "noon", "reason": "lagging", "on": "2026-09-14",
            "source_system": "ODOO", "source_changed_since_override": False,
        }
        return journey.reconcile_overrides({}), state.overrides["order:SO-OLD_ODOO:loan_status"]

    out, record = _bound(sid, call=write_and_reconcile)
    assert out["missing"] == ["order:SO-OLD_ODOO:loan_status"]
    assert record["source_missing"] is True
