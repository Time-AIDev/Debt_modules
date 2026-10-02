"""Amount-led payment claims: pending first, PEAK receipt confirmation later."""
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cases, errors, payment_claims
from app.main import app


def test_payment_ledgers_are_part_of_the_repeatable_database_schema():
    schema = (Path(__file__).parents[1] / "app" / "schema.sql").read_text()
    for table in ("payment_claim", "payment_claim_target", "payment_allocation",
                  "payment_claim_receipt", "payment_reconciliation_exception",
                  "payment_reminder"):
        assert "records.%s" % table in schema


def _invoice(doc_no, amount, outstanding, due_on, issued_on="2026-09-01"):
    return {
        "uid": "inv-pk-" + doc_no,
        "peak_number": doc_no,
        "amount": str(amount),
        "outstanding": str(outstanding),
        "due_date": due_on,
        "issued_on": issued_on,
        "state": "OVERDUE",
    }


def test_preview_applies_the_reference_first_then_fifo_and_surfaces_credit():
    """Changing allocation order or dropping excess customer credit breaks this."""
    invoices = [
        _invoice("IV-OLD", "100.00", "100.00", "2026-07-01"),
        _invoice("IV-REF", "80.00", "80.00", "2026-08-01"),
        _invoice("IV-NEXT", "50.00", "50.00", "2026-09-01"),
    ]

    preview = payment_claims.allocate_preview(
        invoices, Decimal("250.00"), reference="IV-REF")

    assert [(row["invoice_doc_no"], row["amount"]) for row in preview["allocations"]] == [
        ("IV-REF", "80.00"),
        ("IV-OLD", "100.00"),
        ("IV-NEXT", "50.00"),
    ]
    assert preview["confirmed_outstanding"] == "230.00"
    assert preview["projected_outstanding"] == "0.00"
    assert preview["credit"] == "20.00"


def test_existing_pending_amount_is_not_offered_to_a_second_claim():
    """Two users must not provisionally spend the same invoice balance."""
    invoices = [_invoice("IV-1", "100.00", "100.00", "2026-07-01")]
    preview = payment_claims.allocate_preview(
        invoices,
        Decimal("80.00"),
        existing_pending={"IV-1": Decimal("60.00")},
    )
    assert preview["allocations"] == [{
        "invoice_doc_no": "IV-1", "invoice_uid": "inv-pk-IV-1",
        "before": "100.00", "already_pending": "60.00",
        "amount": "40.00", "after": "0.00", "order": 1,
    }]
    assert preview["credit"] == "40.00"


def test_receipts_are_deduplicated_reversible_and_allocate_reference_then_fifo():
    invoices = [
        dict(_invoice("IV-1", "100", "100", "2026-07-01"), customer_uid="cus-1", customer_no="C1"),
        dict(_invoice("IV-2", "80", "80", "2026-08-01"), customer_uid="cus-1", customer_no="C1"),
    ]
    receipts = [
        {"doc_no": "RE-1", "invoice_ref": "IV-2", "customer_uid": "cus-1", "customer_no": "C1",
         "paid_on": "2026-09-01", "paid_amount": "200", "status": "PAID", "run_id": 10},
        # The latest observation for RE-1 wins; re-uploading it never doubles cash.
        {"doc_no": "RE-1", "invoice_ref": "IV-2", "customer_uid": "cus-1", "customer_no": "C1",
         "paid_on": "2026-09-01", "paid_amount": "200", "status": "PAID", "run_id": 11},
    ]
    result = payment_claims.reconcile_receipts(invoices, receipts)
    assert [(a["invoice_doc_no"], a["amount"]) for a in result["allocations"]] == [
        ("IV-2", "80.00"), ("IV-1", "100.00"), (None, "20.00")]
    assert result["invoices"]["IV-1"]["state"] == "PAID"
    assert result["invoices"]["IV-2"]["state"] == "PAID"
    assert result["credit_by_customer"] == {"cus-1": "20.00"}

    cancelled = receipts + [dict(receipts[-1], status="CANCELLED", run_id=12)]
    reversed_result = payment_claims.reconcile_receipts(invoices, cancelled)
    assert reversed_result["allocations"] == []
    assert reversed_result["invoices"]["IV-1"]["confirmed_outstanding"] == "100.00"


def test_receipt_requires_both_invoice_reference_and_same_customer():
    invoices = [dict(_invoice("IV-1", "100", "100", "2026-07-01"),
                     customer_uid="cus-1", customer_no="C1")]
    result = payment_claims.reconcile_receipts(invoices, [{
        "doc_no": "RE-WRONG", "invoice_ref": "IV-1", "customer_uid": "cus-2",
        "customer_no": "C2", "paid_on": "2026-09-01", "paid_amount": "100",
        "status": "PAID", "run_id": 1,
    }])
    assert result["allocations"] == []
    assert result["exceptions"][0]["reason"] == "CUSTOMER_MISMATCH"


def _late_customer_with_invoice(client):
    for row in client.get("/v1/workbook").json()["rows"]:
        if row["case"]["payment_status"] != "LATE":
            continue
        uid = row["customer"]["uid"]
        detail = client.get("/v1/cases/by-customer/%s" % uid).json()
        if detail.get("invoices"):
            return uid, detail
    raise AssertionError("the seeded book has no late customer with an invoice")


@pytest.mark.parametrize("role", ["OFFICER", "MANAGER", "OWNER"])
def test_every_operational_role_can_create_a_pending_claim(role):
    client = TestClient(app)
    uid, _detail = _late_customer_with_invoice(client)
    response = client.post(
        "/v1/customers/%s/payment-claims:preview" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23"},
        headers={"X-Volt-Role": role, "X-Volt-Officer": role.lower()},
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    created = client.post(
        "/v1/customers/%s/payment-claims" % uid,
        json={
            "amount": "1.00", "paid_on": "2026-10-23", "note": "โอนแล้ว",
            "idempotency_key": "claim-%s" % role,
            "preview_version": preview["version"],
        },
        headers={"X-Volt-Role": role, "X-Volt-Officer": role.lower()},
    )
    assert created.status_code == 201, created.text
    claim = created.json()["claim"]
    assert claim["state"] == "PENDING" and claim["created_by"] == role.lower()

    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    assert detail["case"]["payment_status"] == "PENDING"
    assert detail["case"]["payment_status_confirmed"] == "LATE"
    assert detail["payment_claim_position"]["pending_amount"] == "1.00"
    want = max(
        Decimal("0.00"),
        Decimal(detail["payment_claim_position"]["confirmed_outstanding"]) - Decimal("1.00"),
    )
    assert Decimal(detail["payment_claim_position"]["projected_outstanding"]) == want
    queued = next(row for row in client.get("/v1/workbook").json()["rows"]
                  if row["customer"]["uid"] == uid)
    assert queued["case"]["payment_status"] == "PENDING"
    assert queued["case"]["payment_status_confirmed"] == "LATE"


def test_create_is_idempotent_and_cancel_restores_the_confirmed_status():
    client = TestClient(app)
    uid, _detail = _late_customer_with_invoice(client)
    headers = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nok"}
    preview = client.post(
        "/v1/customers/%s/payment-claims:preview" % uid,
        json={"amount": "25.00", "paid_on": "2026-10-23"}, headers=headers,
    ).json()
    payload = {
        "amount": "25.00", "paid_on": "2026-10-23", "note": "หลักฐานแนบแล้ว",
        "idempotency_key": "same-transfer", "preview_version": preview["version"],
    }
    first = client.post("/v1/customers/%s/payment-claims" % uid, json=payload, headers=headers)
    second = client.post("/v1/customers/%s/payment-claims" % uid, json=payload, headers=headers)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["claim"]["uid"] == second.json()["claim"]["uid"]

    claim_uid = first.json()["claim"]["uid"]
    cancelled = client.post("/v1/payment-claims/%s:cancel" % claim_uid, json={}, headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["claim"]["state"] == "CANCELLED"
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "LATE"
    queued = next(row for row in client.get("/v1/workbook").json()["rows"]
                  if row["customer"]["uid"] == uid)
    assert queued["case"]["payment_status"] == "LATE"


@pytest.mark.parametrize("note", [None, "", "   \n\t"])
def test_create_requires_a_non_whitespace_note_but_preview_does_not(note):
    client = TestClient(app)
    uid, _detail = _late_customer_with_invoice(client)
    headers = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nok"}
    preview = client.post(
        "/v1/customers/%s/payment-claims:preview" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23"}, headers=headers,
    )
    assert preview.status_code == 200

    response = client.post(
        "/v1/customers/%s/payment-claims" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23", "note": note,
              "idempotency_key": "missing-note", "preview_version": preview.json()["version"]},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["errors"] == [{"pointer": "/note", "code": "required",
                                           "message": "note is required",
                                           "message_th": "กรุณาระบุหมายเหตุ"}]


def test_create_trims_the_required_note_before_storing_it():
    client = TestClient(app)
    uid, _detail = _late_customer_with_invoice(client)
    headers = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nok"}
    preview = client.post(
        "/v1/customers/%s/payment-claims:preview" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23"}, headers=headers,
    ).json()
    response = client.post(
        "/v1/customers/%s/payment-claims" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23", "note": "  โอนผ่านธนาคาร  ",
              "idempotency_key": "trim-note", "preview_version": preview["version"]},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["claim"]["note"] == "โอนผ่านธนาคาร"


def test_governed_payment_status_cannot_create_pending():
    client = TestClient(app)
    uid, _detail = _late_customer_with_invoice(client)
    case = cases.for_current().cases[uid]
    case["payment_status"] = case["payment_status_system"] = "NPL"
    # This test mutates the current in-memory session directly, so exercise the
    # domain boundary in that same session (TestClient requests intentionally
    # get isolated sessions in the test harness).
    with pytest.raises(errors.Problem) as caught:
        payment_claims.preview(uid, "10.00", "2026-10-23")
    assert caught.value.status == 409
    assert caught.value.code == "payment_claim_status_governed"


def test_non_collection_role_and_foreign_evidence_are_refused():
    client = TestClient(app)
    uid, _detail = _late_customer_with_invoice(client)
    ops = {"X-Volt-Role": "OPS", "X-Volt-Officer": "ops"}
    refused_role = client.post(
        "/v1/customers/%s/payment-claims:preview" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23"}, headers=ops)
    assert refused_role.status_code == 403

    headers = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nok"}
    preview = client.post(
        "/v1/customers/%s/payment-claims:preview" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23"}, headers=headers).json()
    refused_evidence = client.post(
        "/v1/customers/%s/payment-claims" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23", "note": "แนบหลักฐานการโอน",
              "idempotency_key": "foreign-evidence", "preview_version": preview["version"],
              "evidence_uid": "att-from-another-case"}, headers=headers)
    assert refused_evidence.status_code == 422
    assert refused_evidence.json()["code"] == "payment_claim_evidence_invalid"


def test_monthly_reminder_is_consolidated_guarded_and_blocked_by_pending():
    client = TestClient(app)
    uid, detail = _late_customer_with_invoice(client)
    headers = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nok"}
    preview = client.get(
        "/v1/customers/%s/payment-reminders:preview?month=2026-10" % uid,
        headers=headers).json()
    assert preview["eligible"] is True
    assert preview["invoice_count"] == len([i for i in detail["invoices"]
                                             if Decimal(i["outstanding"]) > 0])
    assert Decimal(preview["total_outstanding"]) > 0
    first = client.post("/v1/customers/%s/payment-reminders" % uid,
                        json={"month": "2026-10", "channel": "LINE"}, headers=headers)
    second = client.post("/v1/customers/%s/payment-reminders" % uid,
                         json={"month": "2026-10", "channel": "LINE"}, headers=headers)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["reminder"]["customer_uid"] == uid
    assert second.json()["already_sent"] is True

    claim_preview = client.post(
        "/v1/customers/%s/payment-claims:preview" % uid,
        json={"amount": "1.00", "paid_on": "2026-10-23"}, headers=headers).json()
    client.post("/v1/customers/%s/payment-claims" % uid, json={
        "amount": "1.00", "paid_on": "2026-10-23", "note": "แจ้งชำระแล้ว",
        "idempotency_key": "reminder-block",
        "preview_version": claim_preview["version"]}, headers=headers)
    blocked = client.get(
        "/v1/customers/%s/payment-reminders:preview?month=2026-11" % uid,
        headers=headers).json()
    assert blocked["eligible"] is False and blocked["blocked_reason"] == "PAYMENT_PENDING"
