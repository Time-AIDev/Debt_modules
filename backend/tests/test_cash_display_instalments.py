"""The CASH case display counts invoice obligations without rewriting contract debt."""
from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import journey, main, payment_display, session


CASH_UID = "sheet-99999000297"


def _case_with_peak_invoices(rows):
    client = TestClient(main.app)
    session_id = "cash-display-" + "-".join(row[0] for row in rows)
    client.cookies.set(session.COOKIE, session_id)
    token = session.CURRENT.set(session_id)
    try:
        contract = next(customer for customer in main.CUSTOMERS if customer.uid == CASH_UID).contracts[0]
        state = journey.for_current()
        for uid, inv in list(state.invoices.items()):
            if inv["contract_uid"] == contract.uid:
                del state.invoices[uid]
        for number, kind, status, amount, outstanding, due in rows:
            inv = journey.make_invoice(state, contract.uid, "EPC", kind, amount, due, status)
            inv.update(source="PEAK_REPORT", peak_number=number, outstanding=outstanding,
                       contract_resolved=True, report_as_of="2026-10-05")
    finally:
        session.CURRENT.reset(token)
    response = client.get(f"/v1/cases/by-customer/{CASH_UID}")
    assert response.status_code == 200, response.json()
    return response.json()


def test_two_cash_invoices_show_one_paid_of_two_and_keep_the_contract_balance():
    data = _case_with_peak_invoices([
        ("IV-PAID", "HANDOVER_BALANCE", "PAID", "160000.00", "0.00", "2026-07-20"),
        ("IV-OPEN", "HANDOVER_BALANCE", "OVERDUE", "165000.00", "165000.00", "2026-08-23"),
    ])
    display = data["payment_summary"]["display_instalments"]
    assert (display["paid_count"], display["total_count"], display["remaining_count"],
            display["overdue_count"]) == (1, 2, 1, 1)
    assert [(row["n"], row["status"], row["doc_no"]) for row in display["contracts"][0]["cycles"]] == [
        (1, "PAID", "IV-PAID"), (2, "OVERDUE", "IV-OPEN")]
    assert display["peak_outstanding"] == "165000.00"
    assert display["contract_outstanding"] == data["work_item"]["contract_outstanding"]
    assert data["work_item"]["aggregate_outstanding"] == display["peak_outstanding"]
    assert display["contract_outstanding"] != display["peak_outstanding"]
    assert "PEAK" in display["provenance_th"]
    assert "PEAK" in display["provenance_en"]


def test_deposit_cancelled_and_duplicate_documents_do_not_create_extra_cash_instalments():
    data = _case_with_peak_invoices([
        ("DP", "DEPOSIT", "PAID", "5000.00", "0.00", "2026-06-20"),
        ("IV-PAID", "HANDOVER_BALANCE", "PAID", "160000.00", "0.00", "2026-07-20"),
        ("IV-PAID", "HANDOVER_BALANCE", "PAID", "160000.00", "0.00", "2026-07-20"),
        ("IV-VOID", "HANDOVER_BALANCE", "CANCELLED", "30000.00", "30000.00", "2026-08-01"),
        ("IV-OPEN", "HANDOVER_BALANCE", "OVERDUE", "165000.00", "165000.00", "2026-08-23"),
    ])
    display = data["payment_summary"]["display_instalments"]
    assert (display["paid_count"], display["total_count"], display["peak_outstanding"]) == (1, 2, "165000.00")


def test_partial_peak_evidence_does_not_mark_unmatched_sheet_months_paid():
    contract = SimpleNamespace(uid="cash-partial", product="CASH", month_cells=[
        {"kind": "PAID", "amount": "160000.00"}, {"kind": "PAID", "amount": "165000.00"}],
        sheet_row={})
    entry = {"cycles": [{"n": 1, "kind": "DEPOSIT", "status": "PAID"},
                        {"n": 2, "kind": "BALANCE", "status": "PAID"}], "source": "SHEET_DERIVED"}
    invoice = {"uid": "one-open", "contract_uid": contract.uid, "kind": "HANDOVER_BALANCE",
               "source": "PEAK_REPORT", "peak_number": "IV-OPEN", "amount": "165000.00",
               "outstanding": "165000.00", "state": "OVERDUE", "due_date": "2026-08-23",
               "month_index": None, "contract_resolved": True}
    result = payment_display.build([contract], [entry], SimpleNamespace(invoices={"i": invoice}, receipts={}),
                                   date(2026, 10, 5), "325000.00")
    assert result["total_count"] == 2
    assert result["paid_count"] == 0
    assert result["unconfirmed_count"] == 2
    assert result["peak_outstanding"] == "165000.00"


def test_sheet_paid_month_without_peak_evidence_remains_unconfirmed():
    contract = SimpleNamespace(uid="cash-sheet-only", product="CASH",
                               month_cells=[{"kind": "PAID", "amount": "160000.00"}], sheet_row={})
    result = payment_display.build([contract], [{"cycles": [], "source": "SHEET_DERIVED"}],
                                   SimpleNamespace(invoices={}, receipts={}), date(2026, 10, 5), "160000.00")
    assert result["paid_count"] == 0
    assert result["unconfirmed_count"] == 1
    assert result["contracts"][0]["cycles"][0]["status"] == "UNCONFIRMED"


def test_cash_schedule_paid_without_peak_evidence_remains_unconfirmed():
    contract = SimpleNamespace(uid="cash-schedule-only", product="CASH", month_cells=[], sheet_row={})
    entry = {"cycles": [{"n": 1, "kind": "BALANCE", "status": "INFERRED_PAID",
                         "source": "SHEET_DERIVED"}], "source": "SHEET_DERIVED"}
    result = payment_display.build([contract], [entry], SimpleNamespace(invoices={}, receipts={}),
                                   date(2026, 10, 5), "160000.00")
    assert result["paid_count"] == 0
    assert result["unconfirmed_count"] == 1


def test_a_peak_handover_document_matching_the_sheet_deposit_is_not_an_instalment():
    contract = SimpleNamespace(uid="cash-dp", product="CASH", month_cells=[
        {"kind": "PAID", "amount": "160000.00"}, {"kind": "LATE", "amount": "165000.00"}],
        sheet_row={"dp_inc_vat": "5000.00"})
    entry = {"cycles": [], "source": "SHEET_DERIVED"}
    rows = [
        ("dp", "DP", "5000.00", "0.00", "PAID", "2026-06-01"),
        ("paid", "IV-PAID", "160000.00", "0.00", "PAID", "2026-07-20"),
        ("open", "IV-OPEN", "165000.00", "165000.00", "OVERDUE", "2026-08-23"),
    ]
    invoices = {uid: {"uid": uid, "contract_uid": contract.uid, "kind": "HANDOVER_BALANCE",
                      "source": "PEAK_REPORT", "peak_number": number, "amount": amount,
                      "outstanding": outstanding, "state": state, "due_date": due,
                      "contract_resolved": True}
                for uid, number, amount, outstanding, state, due in rows}
    result = payment_display.build([contract], [entry], SimpleNamespace(invoices=invoices, receipts={}),
                                   date(2026, 10, 5), "325000.00")
    assert result["total_count"] == 2
    assert [row["doc_no"] for row in result["contracts"][0]["cycles"]] == ["IV-PAID", "IV-OPEN"]


def test_mixed_contracts_do_not_claim_the_partial_peak_balance_covers_the_case():
    cash = SimpleNamespace(uid="cash", product="CASH", month_cells=[], sheet_row={})
    lease = SimpleNamespace(uid="lease", product="LEASE")
    invoice = {"uid": "cash-open", "contract_uid": cash.uid, "kind": "HANDOVER_BALANCE",
               "source": "PEAK_REPORT", "peak_number": "IV-CASH", "amount": "165000.00",
               "outstanding": "165000.00", "state": "OVERDUE", "due_date": "2026-08-23",
               "contract_resolved": True}
    entries = [{"cycles": [], "source": "CONTRACT"}, {"cycles": [], "source": "CONTRACT"}]
    result = payment_display.build([cash, lease], entries,
                                   SimpleNamespace(invoices={"cash-open": invoice}, receipts={}),
                                   date(2026, 10, 5), "325000.00")
    assert result["peak_outstanding"] == "165000.00"
    assert result["peak_balance_complete"] is False


def test_bad_sheet_deposit_amount_does_not_break_the_case_display():
    cash = SimpleNamespace(uid="cash", product="CASH", month_cells=[{"kind": "LATE", "amount": "100"}],
                           sheet_row={"dp_inc_vat": "unknown"})
    invoices = {uid: {"uid": uid, "contract_uid": cash.uid, "kind": "HANDOVER_BALANCE",
                      "source": "PEAK_REPORT", "peak_number": uid, "amount": amount,
                      "outstanding": outstanding, "state": status, "due_date": due,
                      "contract_resolved": True}
                for uid, amount, outstanding, status, due in [
                    ("dp", "20.00", "0.00", "PAID", "2026-06-01"),
                    ("open", "100.00", "100.00", "OVERDUE", "2026-08-23")]}
    result = payment_display.build([cash], [{"cycles": [], "source": "SHEET"}],
                                   SimpleNamespace(invoices=invoices, receipts={}),
                                   date(2026, 10, 5), "100.00")
    assert result["total_count"] == 1
    assert result["unconfirmed_count"] == 0


def test_missing_contract_balance_stays_unknown():
    result = payment_display.build([], [], SimpleNamespace(invoices={}, receipts={}),
                                   date(2026, 10, 5), None)
    assert result["contract_outstanding"] is None
    assert result["peak_outstanding"] is None
