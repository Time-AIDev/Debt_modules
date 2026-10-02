"""The 2026-09-26 data-quality test of staging against the New Order Master found the
importer at fault in five places (report F01-F03, F06, F10, F14). Synthetic rows only."""
from datetime import date

from app import book, imports

IMS = imports._IMS
VID = "28000000021_Test_ทดสอบ_IPW"
X_HDR = ["No", "Order Type", "Order Status", "Volt ID", "EPC Start Date"]


def _read(name, rows):
    """(kind, records) for one uploaded tab."""
    kind, _hi, _hdr, got, _refused, _extra = imports._classify_sheet([], rows, name, [], list(range(1, len(rows) + 1)))
    return kind, got


def _payload(leasing=(), cash=(), orders=()):
    return IMS.assemble_payload(list(leasing), list(cash), [], [], [], [], list(orders), [], [], {}, [], [])


def test_f01_tab_x_is_read_without_a_phone_column_and_beats_its_old_copy():
    kind, x = _read("x", [X_HDR, ["1", "Cash", "Order - Done", VID, "2026-01-05"]])
    assert kind == "ORDER_MASTER"
    _k, copy = _read("Copy of x", [X_HDR + ["Phone"], ["1", "Leasing", "Order - Lost", VID, "2025-01-05", "081-234-5678"]])
    for orders in (x + copy, copy + x):
        c = _payload(orders=orders)["customers"][0]
        assert c["order"]["order_status"] == "Order - Done"
        assert c["phone_e164"] == "+66812345678"          # x has no Phone: the copy's stays
    # 'Licensing VOLT' shares the three order names, but no Order Type: not an order tab
    assert _read("Licensing VOLT", [X_HDR[2:], ["Order - Done", VID, "2026-01-05"]])[0] is None


def test_f02_x_order_type_decides_the_product_and_epc_collection_is_no_lease_book():
    lease_hdr = ["VOLT ID", "Order Type", "Payment Status", "Term, Original", "Rate, \ninc VAT"]
    assert _read("EPC - Collection", [lease_hdr, [VID, "Cash", "Not Installed", "1", ""]]) == (None, [])
    _k, lease = _read("Absolete collection", [lease_hdr, [VID, "Leasing", "Current", "96", "3199"]])
    _k, x = _read("x", [X_HDR, ["1", "Cash", "Order - Done", VID, "2026-01-05"]])
    assert _payload(leasing=lease, orders=x)["customers"][0]["product"] == "CASH"


def test_f02_an_order_x_says_awaits_installation_keeps_its_pipeline_card(monkeypatch):
    """'EPC - Collection' fed the pre-install pipeline its Not Installed rows; tab x's
    Order Status says the same thing at the source."""
    from app import invoice_pipeline
    _k, x = _read("x", [X_HDR, ["1", "Cash", "Order - EPC Installation", VID, ""]])
    payload = _payload(orders=x)
    monkeypatch.setattr(book, "load_sheet", lambda: payload)
    book.invalidate()
    invoice_pipeline.reset()
    items = invoice_pipeline.for_current().items.values()
    assert [(i["volt_id"], i["product"]) for i in items] == [(VID, "CASH")]


CASH_HDR = ["Status", "VOLT ID", "Price", "DP \nincl VAT", "OUTSTANDING AMOUNT", "Invoices Overdue", "DC Status",
            "Deposit Paid", "Due Date", "M1", "Status", "Due Date M2", "M2", "Status", "Due Date M3", "M3", "Status"]


def test_f06_each_instalment_status_says_what_is_paid_and_when_the_next_is_due():
    """'Done - Cash' fills Mn's amount even when it is unpaid, and writes 'Closed'
    where the schedule ends, on an open account too."""
    row = ["Late", VID, "100000", "20000", "40000", "1", "", "Paid",
           "10/08/2026", "40000", "Paid", "02/09/2026", "40000", "Late", "02/10/2026", "", "Closed"]
    rec = IMS.read_cash_tab(0, [], [CASH_HDR, row])[0]
    assert [m and m["kind"] for m in rec["months"]] == ["PAID", "LATE", None]
    assert rec["next_due_date"] == "2026-09-02"
    k, _ = book._cash_contract("K", "u", rec, [], date(2026, 9, 26))
    assert (k.status, k.instalments[1].due_date, k.instalments[1].paid_principal) == ("PAST_DUE", date(2026, 9, 2), 0)


def test_f14_dd_mm_yyyy_reads_day_first_where_the_tab_writes_it():
    assert IMS.parse_date("01/09/2024", day_first=True) == "2024-09-01"
    assert IMS.parse_date("7/31/2026", day_first=True) == "2026-07-31"   # cannot be day first
    assert IMS.parse_date("01/09/2024") == "2024-01-09"                   # the leasing tabs' PTP Date


def test_f10_a_first_due_taken_from_the_signing_month_is_labelled_derived():
    row = {"pmt_inc_vat": "3199", "term_original": 96, "months": [], "payment_status": "Current",
           "contract_signed": "2026-03-15", "first_payment_date": None}
    k, _ = book._lease_contract("K", "u", row, date(2026, 9, 26))
    assert k.first_due == date(2026, 4, 10)
    assert k.derivation["first_due"].startswith("derived")
