"""F10 / Q5 — POST /v1/customers:assign (feedback-r2 TASK-107).

One request assigns a set of customers to one officer, all-or-nothing, SUPERVISOR
and above, with one audit entry naming every uid. Every test here is an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app import journey, officers
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
SUPERVISOR = {"X-Volt-Role": "SUPERVISOR", "X-Volt-Officer": "thip"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _officer_uid():
    return next(r["uid"] for r in officers.registry() if r["role"] == "OFFICER")


def _three_uids(client):
    rows = client.get("/v1/workbook").json()["rows"]
    return [r["customer"]["uid"] for r in rows[:3]]


def _assert_unassigned_to(client, uids, officer_uid):
    cs = cases_domain.for_current()
    for uid in uids:
        assert cs.cases[uid]["officer_uid"] == officer_uid or journey.for_current().officer_overlay.get(uid) == officer_uid


def test_an_officer_may_not_bulk_assign(client):
    response = client.post("/v1/customers:assign", headers=OFFICER,
                           json={"customer_uids": _three_uids(client), "officer_uid": _officer_uid()})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_an_unknown_officer_is_refused_before_anything_is_written(client):
    uids = _three_uids(client)
    cs = cases_domain.for_current()
    before = {uid: cs.cases[uid]["officer_uid"] for uid in uids}
    response = client.post("/v1/customers:assign", headers=MANAGER,
                           json={"customer_uids": uids, "officer_uid": "nobody-at-all"})
    assert response.status_code == 422 and response.json()["code"] == "officer_unknown"
    assert {uid: cs.cases[uid]["officer_uid"] for uid in uids} == before


def test_an_unknown_customer_is_refused_by_name_and_nothing_is_written(client):
    uids = _three_uids(client)
    cs = cases_domain.for_current()
    before = {uid: cs.cases[uid]["officer_uid"] for uid in uids}
    response = client.post("/v1/customers:assign", headers=MANAGER,
                           json={"customer_uids": uids + ["no-such-customer"], "officer_uid": _officer_uid()})
    assert response.status_code == 422 and response.json()["code"] == "customer_unknown"
    assert response.json()["extensions"]["customer_uids"] == ["no-such-customer"]
    assert {uid: cs.cases[uid]["officer_uid"] for uid in uids} == before


def test_three_uids_are_assigned_in_one_request_and_the_audit_names_them(client):
    uids = _three_uids(client)
    target = next(r["uid"] for r in officers.registry() if r["role"] == "OFFICER" and r["uid"] != "nantapol")
    response = client.post("/v1/customers:assign", headers=SUPERVISOR,
                           json={"customer_uids": uids, "officer_uid": target, "reason": "แบ่งพอร์ตต้นเดือน"})
    assert response.status_code == 200, response.text
    assert response.json() == {"officer_uid": target, "assigned": uids, "count": 3}
    _assert_unassigned_to(client, uids, target)
    # The Today rows now carry the officer — the assignment is served, not just stored.
    items = client.get("/v1/today").json()["items"]
    for uid in uids:
        row = next(i for i in items if i["customer"]["uid"] == uid)
        assert row["case"]["officer_uid"] == target
    # One audit entry, naming every uid (one row per request by design).
    entry = next(e for e in client.get("/v1/audit").json()["entries"] if e["act"] == "CUSTOMERS_ASSIGNED")
    assert entry["subject_uid"] == target
    assert entry["detail"]["count"] == 3 and set(entry["detail"]["customer_uids"]) == set(uids)
    assert entry["detail"]["reason"] == "แบ่งพอร์ตต้นเดือน"


def test_a_duplicate_uid_in_the_set_is_refused(client):
    uids = _three_uids(client)
    response = client.post("/v1/customers:assign", headers=MANAGER,
                           json={"customer_uids": [uids[0], uids[0]], "officer_uid": _officer_uid()})
    assert response.status_code == 422
    assert response.json()["errors"][0]["pointer"] == "/customer_uids"
