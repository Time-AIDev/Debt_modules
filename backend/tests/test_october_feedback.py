"""Regression coverage for the 1 October debt-team feedback."""
import csv
import io
from datetime import date

from fastapi.testclient import TestClient

from app import data_epoch, journey, main


client = TestClient(main.app)
client.cookies.set("volt_session", "shared")


def test_customer_search_accepts_one_character_and_returns_only_safe_identity_fields(monkeypatch):
    target = main.CUSTOMERS[0]
    monkeypatch.setattr(target, "email_masked", "s•••@volt.test", raising=False)
    monkeypatch.setattr(data_epoch, "current", lambda: 101)

    response = client.get("/v1/customers/search", params={"q": target.display_name[0], "limit": 10})

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["customer_uid"] == target.uid)
    assert item["display_name"] == target.display_name
    assert item["phone_masked"] == target.phone_masked
    assert item["email_masked"] == "s•••@volt.test"
    assert item["matched_on"] == "display_name"
    assert "phone_e164" not in item
    assert "email" not in item
    assert "line_id" not in item and "meta_id" not in item


def test_case_detail_serves_social_ids_for_the_composer(monkeypatch):
    target = main.CUSTOMERS[0]
    monkeypatch.setattr(target, "line_id", "line-123")
    monkeypatch.setattr(target, "meta_id", "meta-456", raising=False)
    response = client.get("/v1/cases/by-customer/%s" % target.uid)
    assert response.status_code == 200
    assert response.json()["customer"]["line_id"] == "line-123"
    assert response.json()["customer"]["meta_id"] == "meta-456"


def test_customer_search_covers_english_name_volt_id_customer_number_and_masked_contact(monkeypatch):
    target = next(c for c in main.CUSTOMERS
                  if getattr(c, "name_roman", None) and getattr(c, "volt_id", None) and c.phone_masked)
    monkeypatch.setattr(target, "phone_masked", "08x-xxx-4321")
    monkeypatch.setattr(target, "email_masked", "d•••@example.invalid", raising=False)
    monkeypatch.setattr(data_epoch, "current", lambda: 102)
    queries = [
        (getattr(target, "name_roman"), "name_roman"),
        (getattr(target, "volt_id"), "volt_id"),
        (target.customer_no, "customer_no"),
        (target.phone_masked[-4:], "phone_masked"),
        ("example.invalid", "email_masked"),
    ]

    for query, matched_on in queries:
        body = client.get("/v1/customers/search", params={"q": query}).json()
        assert body["items"][0]["customer_uid"] == target.uid, (query, body)
        assert body["items"][0]["matched_on"] == matched_on


def test_customer_search_ranks_exact_identifiers_then_prefixes_then_substrings(monkeypatch):
    exact, prefix, substring = main.CUSTOMERS[:3]
    monkeypatch.setattr(exact, "customer_no", "RANK-900")
    monkeypatch.setattr(prefix, "customer_no", "RANK-900-TAIL")
    monkeypatch.setattr(substring, "display_name", "ลูกค้า RANK-900 ปลายคำ")
    monkeypatch.setattr(data_epoch, "current", lambda: 103)

    body = client.get("/v1/customers/search", params={"q": "rank-900", "limit": 10}).json()

    assert [item["customer_uid"] for item in body["items"][:3]] == [exact.uid, prefix.uid, substring.uid]
    assert [item["matched_on"] for item in body["items"][:3]] == [
        "customer_no", "customer_no", "display_name",
    ]


def test_masked_contact_prefix_does_not_outrank_a_name_substring(monkeypatch):
    masked, named = main.CUSTOMERS[3:5]
    monkeypatch.setattr(masked, "phone_masked", "MASK-777-xxxx")
    monkeypatch.setattr(named, "display_name", "ลูกค้า MASK-777 ปลายคำ")
    monkeypatch.setattr(data_epoch, "current", lambda: 104)

    body = client.get("/v1/customers/search", params={"q": "mask-777", "limit": 10}).json()

    assert [item["customer_uid"] for item in body["items"][:2]] == [named.uid, masked.uid]


def test_customer_search_does_not_build_the_workbook(monkeypatch):
    from app import today as today_domain

    monkeypatch.setattr(today_domain, "build", lambda: (_ for _ in ()).throw(AssertionError("slow desk build")))
    response = client.get("/v1/customers/search", params={"q": "ส"})

    assert response.status_code == 200
    assert response.json()["items"]


def test_customer_search_does_not_restore_the_full_journey_state(monkeypatch):
    monkeypatch.setattr(
        journey, "for_current",
        lambda: (_ for _ in ()).throw(AssertionError("slow journey restore")),
    )

    response = client.get("/v1/customers/search", params={"q": "ส"})

    assert response.status_code == 200
    assert response.json()["items"]


def test_customer_search_keeps_assignment_overlays_without_restoring_journey(monkeypatch):
    target = main.CUSTOMERS[0]
    assigned = client.post(
        "/v1/customers/%s/assign" % target.uid,
        json={"officer_uid": "thip"},
        headers={"X-Volt-Role": "MANAGER"},
    )
    assert assigned.status_code == 200
    monkeypatch.setattr(
        journey, "for_current",
        lambda: (_ for _ in ()).throw(AssertionError("slow journey restore")),
    )

    response = client.get("/v1/customers/search", params={"q": target.customer_no})

    assert response.status_code == 200
    assert response.json()["items"][0]["officer"] == "thip"


def test_customer_search_rebuilds_cached_documents_when_the_data_epoch_changes(monkeypatch):
    target = main.CUSTOMERS[0]
    monkeypatch.setattr(data_epoch, "current", lambda: 201)
    assert client.get("/v1/customers/search", params={"q": target.display_name}).json()["items"]

    monkeypatch.setattr(target, "display_name", "ชื่อหลังนำเข้ารอบใหม่")
    monkeypatch.setattr(data_epoch, "current", lambda: 202)
    body = client.get("/v1/customers/search", params={"q": "หลังนำเข้า"}).json()

    assert body["items"][0]["customer_uid"] == target.uid
    assert body["items"][0]["display_name"] == "ชื่อหลังนำเข้ารอบใหม่"


def test_customer_search_validates_blank_queries_and_limits():
    blank = client.get("/v1/customers/search", params={"q": "   "})
    too_many = client.get("/v1/customers/search", params={"q": "ส", "limit": 11})

    assert blank.status_code == 422
    assert too_many.status_code == 422


def test_invoice_status_preview_returns_actionable_invoices_first_and_caps_the_page(monkeypatch):
    from app.routers import today as today_router

    customer = main.IDENTITIES[0]
    state = journey.for_current()
    paid = journey.make_invoice(state, "K-PREVIEW", "EPC", "BALANCE", "2000", date(2026, 9, 1), "PAID")
    paid.update(customer_uid=customer.uid, peak_number="IV-PAID", outstanding="0.00")
    overdue = journey.make_invoice(state, "K-PREVIEW", "EPC", "BALANCE", "3000", date(2026, 10, 1), "OVERDUE")
    overdue.update(customer_uid=customer.uid, peak_number="IV-LATE", outstanding="3000.00", month_index=1)
    monkeypatch.setattr(today_router, "_with_peak_state",
                        lambda invoice: dict(invoice, peak_state="APPROVED_IN_PEAK"))

    response = client.get("/v1/customers/%s/invoice-statuses" % customer.uid, params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["customer_uid"] == customer.uid
    assert body["meta"] == {"total": 2, "limit": 1, "has_more": True, "remaining": 1}
    assert body["items"] == [{
        "uid": overdue["uid"], "reference": "IV-LATE", "kind": "BALANCE", "month_index": 1,
        "due_date": "2026-10-01", "state": "OVERDUE", "peak_state": "APPROVED_IN_PEAK",
        "amount": "3000", "outstanding": "3000.00",
        "collection_due_date": "2026-10-01", "review_status": "UNMATCHED", "collection_included": True,
    }]


def test_invoice_status_preview_rejects_unknown_customers():
    response = client.get("/v1/customers/not-a-customer/invoice-statuses")

    assert response.status_code == 404


def test_invoice_status_preview_can_return_every_invoice_with_decimal_payment_totals():
    customer = main.IDENTITIES[0]
    state = journey.for_current()
    for i in range(25):
        invoice = journey.make_invoice(state, "K-ALL", "EPC", "BALANCE", "100.01", date(2026, 10, 1), "SENT")
        invoice.update(customer_uid=customer.uid, peak_number="IV-%s" % i, outstanding="100.01")
    partial = journey.make_invoice(state, "K-ALL", "EPC", "BALANCE", "200.50", date(2026, 10, 1), "PARTIALLY_PAID")
    partial.update(customer_uid=customer.uid, outstanding="50.25")
    paid = journey.make_invoice(state, "K-ALL", "EPC", "BALANCE", "300.10", date(2026, 10, 1), "PAID")
    paid.update(customer_uid=customer.uid)
    for status in ("CANCELLED", "DRAFT"):
        excluded = journey.make_invoice(state, "K-ALL", "EPC", "BALANCE", "999.99", date(2026, 10, 1), status)
        excluded.update(customer_uid=customer.uid)

    body = client.get("/v1/customers/%s/invoice-statuses" % customer.uid, params={"include_all": True}).json()

    assert len(body["items"]) == 29
    assert body["meta"]["has_more"] is False
    assert body["meta"]["remaining"] == 0
    assert body["summary"]["paid"] == "450.35"
    assert body["summary"]["outstanding"] == body["summary"]["due_outstanding_amount"] == "2550.50"
    assert body["summary"]["due_invoice_count"] == 27
    limited = client.get("/v1/customers/%s/invoice-statuses" % customer.uid, params={"limit": 1}).json()
    assert len(limited["items"]) == 1
    assert limited["summary"] == body["summary"]


def test_collection_invoice_sort_rule_prioritises_actionable_state_then_due_date():
    invoices = [
        {"uid": "paid", "state": "PAID", "due_date": "2026-01-01"},
        {"uid": "sent", "state": "SENT", "due_date": "2026-10-03"},
        {"uid": "overdue-new", "state": "OVERDUE", "due_date": "2026-10-02"},
        {"uid": "overdue-old", "state": "OVERDUE", "due_date": "2026-09-02"},
        {"uid": "partial", "state": "PARTIALLY_PAID", "due_date": "2026-08-02"},
    ]

    ordered = sorted(invoices, key=journey.invoice_collection_sort_key)

    assert [row["uid"] for row in ordered] == [
        "overdue-old", "overdue-new", "partial", "sent", "paid",
    ]


def test_workbook_csv_has_one_bom_and_round_trips_the_reported_thai_fields():
    payload = client.get("/v1/workbook", params={"sort": "display_name", "dir": "asc"}).json()
    response = client.get("/v1/workbook:export", params={"sort": "display_name", "dir": "asc"})

    assert response.content.startswith(b"\xef\xbb\xbf")
    assert not response.content.startswith(b"\xef\xbb\xbf\xef\xbb\xbf")
    exported = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    by_customer_no = {row["customer_no"]: row for row in exported}
    for source in payload["rows"]:
        row = by_customer_no[source["customer"]["customer_no"]]
        assert row["display_name"] == (source["customer"]["display_name"] or "")
        assert row["aging_bucket_label_th"] == (source.get("aging_bucket_label_th") or "")
        assert row["next_action_on"] == (source["case"].get("next_action_on") or "")
        assert row["missed_basis_th"] == (source.get("missed_basis_th") or "")
        assert row["tier_reason_th"] == (source.get("tier_reason_th") or "")
