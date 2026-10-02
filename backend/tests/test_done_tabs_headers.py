"""The 2026-09-25 New Order Master renamed its Done tabs' columns (Arina's check of
'New Order Master-6.xlsx'):

- 'Done - Collection' calls its payment status "Status", not "Payment Status" — the
  leasing tab went unrecognised and the old Absolete / backup tabs silently stood in.
- 'Done - Cash' calls "Overdue" "Invoices Overdue", and states each customer's status
  in its first "Status" column and the balance in "OUTSTANDING AMOUNT".
- A Done tab present in the file but not read must stop the install, not be skipped."""
from datetime import date

from fastapi.testclient import TestClient

from app import book, imports
from app.main import app
from tests.test_round5_data_flow import _xlsx_bytes_multi

IMS = imports._IMS
VID = "28000000003_Test_ทดสอบ_IPW"
AS_OF = date(2026, 9, 8)

LEASE_HDR = ["Sales Lead", "VOLT ID", "Term, Original", "Rate, \ninc VAT", "First Payment Date",
             "PTP Amount", "Status", "M1"]
CASH_HDR = ["Status", "VOLT ID", "Price", "DP \nincl VAT", "OUTSTANDING AMOUNT", "DC Status", "Comment",
            "Invoices Overdue", "Deposit Paid", "Due Date", "M1", "Status", "Due Date M2", "M2", "Status"]


def test_a_leasing_tab_that_calls_its_payment_status_status_is_read():
    rows = [LEASE_HDR, ["", VID, "96", "3,199", "2024-06-10", "", "Late", "3199"]]
    kind, _hi, _hdr, got, _ref, _x = imports._classify_sheet([], rows, "Done - Collection", [], list(range(1, 3)))
    assert kind == "LEASING_BOOK" and got[0]["payment_status"] == "Late"


def _cash(word, outstanding="0", overdue="0", comment=""):
    row = [word, VID, "100000", "5000", outstanding, "", comment, overdue, "Paid", "", "95000", "Paid", "", "", ""]
    return IMS.read_cash_tab(0, [], [CASH_HDR, row])[0]


def test_done_cash_reads_invoices_overdue_its_status_word_and_outstanding():
    rec = _cash("Late", outstanding="50,000", overdue="1")
    assert (rec["overdue"], rec["status_word"], rec["outstanding_amount"]) == ("1.00", "Late", "50000.00")


def _status(rec):
    return book._cash_contract("K", "u", rec, [], AS_OF)[0].status


def test_done_cash_status_word_decides_the_contract_status():
    assert _status(_cash("Closed")) == "CLOSED"
    assert _status(_cash("Late", outstanding="50000", overdue="1")) == "PAST_DUE"
    assert _status(_cash("Link sent", outstanding="50000")) == "PAST_DUE"
    assert _status(_cash("Not Due", outstanding="50000")) == "ACTIVE"
    assert _status(_cash("Not issued", outstanding="50000")) == "ACTIVE"
    assert _status(_cash("Terminated", outstanding="50000")) == "TERMINATED"


def test_a_done_tab_the_importer_cannot_read_stops_the_install():
    """'Done - Collection' with neither "Payment Status" nor "Status": the check names
    it, and the install refuses instead of letting an old tab stand in."""
    broken = ["Sales Lead", "VOLT ID", "Term, Original", "Rate, \ninc VAT", "M1"]
    ok = ["VOLT ID", "Payment Status", "Term, Original", "Rate,  inc VAT", "First Payment Date"]
    body = _xlsx_bytes_multi([
        ("Done - Collection", [broken, ["", VID, "96", "3199", "3199"]]),
        ("Absolete collection", [ok, [VID, "Current", "96", "3199", "2024-06-10"]]),
    ])
    run = imports.parse_upload(body, "nom.xlsx", "t", "MANAGER")
    assert [u["sheet"] for u in run["done_tabs_unread"]] == ["Done - Collection"]
    assert "Payment Status" in run["done_tabs_unread"][0]["missing"]
    r = TestClient(app).post("/v1/imports?install=true", content=body,
                             headers={"X-Volt-Filename": "nom.xlsx", "X-Volt-Role": "MANAGER",
                                      "Content-Type": "application/octet-stream"})
    assert r.status_code == 422 and r.json()["code"] == "done_tab_unread"
