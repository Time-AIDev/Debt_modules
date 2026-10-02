"""R-B / Q6 (feedback-r2 TASK-220): payment status follows the receipts — the
automatic half. A LATE case whose only open invoice is settled by an applied receipt
reads CURRENT without a person touching it; NPL stays a human declaration (OD-04).

The manual route's own gate is NOT built here: adding it would refuse the OFFICER
posts in test_payment_status_adjust.py (4 functions), test_termination.py:144,
test_weekly_editions.py:170, test_weekly_figures.py:196/270 and
test_auth_middleware_audit.py:126 — none of which any numbered edit authorises.
Quoted and priced in the PR, per the kickoff's escalation rule.

Every test here is an ADDITION.
"""
import pytest
from sqlalchemy import text

from app import cases, db, journey, migrate
from app.book import SHEET
from app.pipelines import peak_writer

MISSING = object()


def _book_customer():
    return next(c for c in journey.book_customers() if c.data_source == SHEET and c.contracts)


def _open_invoice(no):
    return {"doc_no": "IVT-90060", "doc_kind": "IVT", "issued_on": "2026-07-11", "due_on": "2026-07-18",
            "status": "AWAITING", "cycle": {"n": 16, "of": 84}, "product_group": "Solar Leasing",
            "amount_total": "8399.00", "amount_due": "8399.00", "amount_awaiting": "8399.00",
            "payment": None, "contact_code": no, "rule": "CUSTOMER_NO"}


def _receipt(doc, ref):
    return {"doc_no": doc, "doc_kind": doc.split("-")[0], "issued_on": "2026-09-16",
            "invoice_ref": ref, "journal_ref": None, "contact_code": None,
            "customer_name": "Somchai Tamdee", "tax_id_13": "123", "status": "PAID",
            "cycle_n": 16, "cycle_of": 84, "amount_total": "8399.00", "amount_due": "8399.00",
            "paid_on": "2026-09-16", "channel_code": None, "paid_channel": "Beam 0001",
            "paid_amount": "8399.00", "note": None, "lines": []}


@pytest.fixture
def db_env(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        yield pg_conn
    finally:
        pg_conn.execute(text("delete from records.identity_link"))
        pg_conn.commit()


def _apply_a_settling_receipt(conn, no, ref, paid="8399.00"):
    written = peak_writer.write_receipts(
        conn, {"receipts": [dict(_receipt("RE-20260900090", ref), paid_amount=paid)],
               "meta": {"report_as_of": "2026-09-16", "covers_from": "2024-01-01",
                        "covers_to": "2026-09-16", "read": 1, "rejected": []}},
        [{"verdict": "EXACT", "rule": "INVOICE_REF", "customer_no": no,
          "invoice_doc_no": ref, "candidates": []}],
        door="upload", filename="receipt_export_as_of_20240101_20260916.xlsx")
    conn.commit()
    peak_writer.apply_receipt_run(conn, written["run_id"], by="test")
    conn.commit()


def _serve_overlay(conn, customer, no, out):
    """The served book's own overlay path, then the seed's own status follow."""
    overlaid = peak_writer._overlay_receipts(conn, out, "2026-09-14")
    customer.sheet["peak"] = {"report_as_of": overlaid[no]["report_as_of"],
                              "invoices": overlaid[no]["invoices"]}
    return overlaid


def test_a_late_case_reads_current_once_a_receipt_settles_its_only_invoice(db_env):
    conn = db_env
    customer = _book_customer()
    no = customer.customer_no
    case = cases.for_current().cases[customer.uid]
    contract = customer.contracts[0]
    assert cases._peak_says(customer) is None

    # the invoice report's own served block: one open, overdue instalment
    out = {no: {"report_as_of": "2026-09-14", "run_id": None, "invoices": [_open_invoice(no)]}}
    customer.sheet["peak"] = {"report_as_of": "2026-09-14", "invoices": [_open_invoice(no)]}
    cases._set_contract_fields(contract, status="PAST_DUE")
    assert case["payment_status"] == "LATE" and cases._peak_says(customer) == "LATE"

    _apply_a_settling_receipt(conn, no, "IVT-90060")
    overlaid = _serve_overlay(conn, customer, no, out)
    served = overlaid[no]["invoices"][0]
    assert served["status"] == "PAID" and served["amount_awaiting"] == "0.00"
    assert cases._peak_says(customer) == "CURRENT"

    summary = cases.follow_import_for_all()
    assert summary["moved"] >= 1
    assert case["payment_status"] == "CURRENT"
    events = [e for e in cases.for_current().events
              if e["case_uid"] == case["uid"] and e["kind"] == "PAYMENT_STATUS_SET"]
    assert events[-1]["code"] == "CURRENT" and events[-1]["by"] == "SYSTEM"


def test_a_case_declared_npl_stays_npl_after_the_same_receipt_applies(db_env):
    conn = db_env
    customer = _book_customer()
    no = customer.customer_no
    case = cases.for_current().cases[customer.uid]
    contract = customer.contracts[0]

    out = {no: {"report_as_of": "2026-09-14", "run_id": None, "invoices": [_open_invoice(no)]}}
    customer.sheet["peak"] = {"report_as_of": "2026-09-14", "invoices": [_open_invoice(no)]}
    # the human declaration (OD-04): NON_PERFORMING on the contract is NPL and wins
    cases._set_contract_fields(contract, status="NON_PERFORMING")
    assert case["payment_status"] == "NPL"

    _apply_a_settling_receipt(conn, no, "IVT-90060")
    _serve_overlay(conn, customer, no, out)
    cases.follow_import_for_all()
    assert case["payment_status"] == "NPL", "NPL is a human declaration, never the money's"


def test_a_part_payment_leaves_the_rest_owed_and_the_case_late(db_env):
    """Fix-all P2 (F3): any PAID receipt marked its invoice fully paid, so 300 paid on a
    1,000 invoice read CURRENT with 700 still owed. The rest stays owed, and LATE."""
    conn = db_env
    customer = _book_customer()
    no = customer.customer_no
    invoice = dict(_open_invoice(no), amount_total="1000.00", amount_due="1000.00", amount_awaiting="1000.00")
    out = {no: {"report_as_of": "2026-09-14", "run_id": None, "invoices": [invoice]}}
    customer.sheet["peak"] = {"report_as_of": "2026-09-14", "invoices": [dict(invoice)]}

    _apply_a_settling_receipt(conn, no, "IVT-90060", paid="300.00")
    overlaid = _serve_overlay(conn, customer, no, out)
    served = overlaid[no]["invoices"][0]
    assert served["status"] == "AWAITING", "300 of 1,000 is not paid"
    assert (served["amount_awaiting"], served["paid_amount"]) == ("700.00", "300.00")
    assert [p["amount"] for p in served["payments"]] == ["300.00"]
    assert cases._peak_says(customer) == "LATE"
