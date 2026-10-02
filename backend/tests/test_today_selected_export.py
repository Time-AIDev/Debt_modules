import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import audit_store
from app.main import app
from app.routers import today as today_router


@pytest.fixture
def client():
    value = TestClient(app)
    value.cookies.set("volt_session", "shared")
    return value


def _csv(response):
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_officer_exports_only_selected_today_rows_in_api_order_with_safe_fields(client):
    items = client.get("/v1/today").json()["items"]
    selected = [items[2]["customer"]["uid"], items[0]["customer"]["uid"]]
    response = client.post(
        "/v1/today:export",
        json={"workstream": "collection", "customer_uids": selected,
              "reason": "ติดตามรายการที่เลือก"},
        headers={"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nok"},
    )
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "attachment" in response.headers["content-disposition"]
    rows = _csv(response)
    assert [row["customer_uid"] for row in rows] == [items[0]["customer"]["uid"], items[2]["customer"]["uid"]]
    assert {row["customer_uid"] for row in rows} == set(selected)
    assert rows[0]["total_outstanding"] == items[0]["aggregate_outstanding"]
    assert rows[0]["overdue"] == items[0]["aggregate_overdue"]
    assert not ({"phone", "email", "tax_id", "note", "evidence_url"} & set(rows[0]))

    audit = audit_store.read({}, limit=1, before_seq=None)[0]
    assert audit["act"] == "TODAY_SELECTION_EXPORTED"
    assert audit["detail"] == {"workstream": "collection", "count": 2,
                               "reason": "ติดตามรายการที่เลือก"}
    assert not any(uid in str(audit["detail"]) for uid in selected)


@pytest.mark.parametrize("body,pointer,code", [
    ({"workstream": "collection", "customer_uids": [], "reason": "เหตุผลยาวพอแล้ว"},
     "/customer_uids", "required"),
    ({"workstream": "collection", "customer_uids": ["x", "x"], "reason": "เหตุผลยาวพอแล้ว"},
     "/customer_uids", "duplicate"),
    ({"workstream": "collection", "customer_uids": [""], "reason": "เหตุผลยาวพอแล้ว"},
     "/customer_uids/0", "required"),
    ({"workstream": "collection", "customer_uids": ["not-a-customer"], "reason": "เหตุผลยาวพอแล้ว"},
     "/customer_uids/0", "unknown"),
    ({"workstream": "collection", "customer_uids": ["x"], "reason": "สั้น"},
     "/reason", "required"),
    ({"workstream": "collection", "customer_uids": ["x"], "reason": "x" * 501},
     "/reason", "max_length"),
    ({"workstream": "wrong", "customer_uids": ["x"], "reason": "เหตุผลยาวพอแล้ว"},
     "/workstream", "invalid"),
])
def test_selected_export_validates_its_governed_request(client, body, pointer, code):
    response = client.post("/v1/today:export", json=body,
                           headers={"X-Volt-Role": "OFFICER"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["pointer"] == pointer
    assert response.json()["errors"][0]["code"] == code


def test_ops_cannot_export_selected_customers(client):
    uid = client.get("/v1/today").json()["items"][0]["customer"]["uid"]
    response = client.post(
        "/v1/today:export",
        json={"workstream": "collection", "customer_uids": [uid],
              "reason": "เหตุผลยาวพอแล้ว"},
        headers={"X-Volt-Role": "OPS"},
    )
    assert response.status_code == 403


def test_collection_export_rejects_a_known_customer_outside_the_today_queue(client):
    queue = {row["customer"]["uid"] for row in client.get("/v1/today").json()["items"]}
    all_customers = {row["customer"]["uid"] for row in client.get("/v1/workbook").json()["rows"]}
    outside = next(iter(all_customers - queue))
    response = client.post(
        "/v1/today:export",
        json={"workstream": "collection", "customer_uids": [outside],
              "reason": "ตรวจเฉพาะคิววันนี้"},
        headers={"X-Volt-Role": "OFFICER"},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "out_of_scope"


def test_pending_claim_projection_uses_confirmed_and_projected_amounts_without_frontend_math():
    row = today_router._project_collection_export({
        "customer": {"uid": "c-1", "volt_id": "V-1", "customer_no": "N-1", "display_name": "Test"},
        "case": {"payment_status": "PENDING", "payment_pending_amount": "125.50",
                 "payment_pending_count": 2, "payment_pending_uids": ["pc-1", "pc-2"]},
        "aggregate_outstanding": "500.00", "aggregate_overdue": "200.00", "oldest_dpd": 10,
    })
    assert row["payment_confirmed"] == "false"
    assert row["pending_claim_count"] == 2
    assert row["pending_claim_uids"] == "pc-1;pc-2"
    assert row["confirmed_outstanding"] == "500.00"
    assert row["projected_outstanding"] == "374.50"


def test_pre_install_export_uses_the_same_rows_as_the_pipeline_api(client):
    items = client.get("/v1/pipeline").json()["items"]
    selected = [items[0]["customer_uid"]]
    response = client.post(
        "/v1/today:export",
        json={"workstream": "pre_install", "customer_uids": selected,
              "reason": "ส่งให้ทีมติดตั้งตรวจ"},
        headers={"X-Volt-Role": "SUPERVISOR"},
    )
    assert response.status_code == 200, response.text
    row = _csv(response)[0]
    assert row["customer_uid"] == selected[0]
    assert row["workstream"] == "pre_install"
    assert row["down_payment_status"] == items[0]["gate_down_payment"]["state"]
    assert row["business_date"] == str(client.get("/v1/pipeline").json()["meta"]["business_date"])


def test_odoo_crm_link_requires_a_numeric_id_and_safe_http_configuration(monkeypatch):
    monkeypatch.setattr(today_router, "integration_env", lambda key, default=None: "https://odoo.example.com/")
    assert today_router._odoo_crm(74482) == {
        "model": "crm.lead", "record_id": 74482,
        "url": "https://odoo.example.com/web#id=74482&model=crm.lead&view_type=form",
    }
    assert today_router._odoo_crm("SYN-12") is None
    monkeypatch.setattr(today_router, "integration_env", lambda key, default=None: "javascript:alert(1)")
    assert today_router._odoo_crm("74482") is None


def test_case_customer_dto_always_carries_the_nullable_odoo_link(client, monkeypatch):
    served = {"model": "crm.lead", "record_id": 74482,
              "url": "https://odoo.example.com/web#id=74482&model=crm.lead&view_type=form"}
    monkeypatch.setattr(today_router, "_customer_odoo_crm", lambda *args, **kwargs: served)
    uid = client.get("/v1/today").json()["items"][0]["customer"]["uid"]
    response = client.get("/v1/cases/by-customer/%s" % uid)
    assert response.status_code == 200
    assert response.json()["customer"]["odoo_crm"] == served
