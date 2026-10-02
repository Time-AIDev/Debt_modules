"""The New Order Master read from an uploaded .xlsx (2026-09-25).

1. Header cells keep their in-cell line breaks in an .xlsx ('Rate, \\ninc VAT'); the
   Drive render the readers were written against turns them into spaces. Every such
   column (PMT, DP, cost, system size, NPV) read as empty from an upload.
2. 'Done - Cash' states each instalment as an amount under Mn (paid) or a word in the
   Status beside it (Late / Link sent), and counts the overdue ones in Overdue. The
   cash contract ignored all of it: 503 of 571 customers read PAST_DUE with the
   sheet's own Overdue at 0."""
from datetime import date

from app import book, imports

IMS = imports._IMS
VID = "28000000002_Test_ทดสอบ_IPW"

LEASE_HDR = ["Sales Lead", "VOLT ID", "Payment Status", "Term, Original", "Rate, \ninc VAT",
             "DP \nincl VAT", "System Size\n(kWp)", "M1"]
CASH_HDR = ["Status", "VOLT ID", "Price", "DP \nincl VAT", "DC Status", "DC Comment", "Comment",
            "Overdue", "Deposit Paid", "Due Date", "M1", "Status", "Due Date M2", "M2", "Status"]


def _cash_rec(**cells):
    row = dict(zip(CASH_HDR, [""] * len(CASH_HDR)))
    row.update({"VOLT ID": VID, "Price": "100000", "DP \nincl VAT": "5000", "Overdue": "0",
                "Deposit Paid": "Paid"})
    values = [row[h] for h in CASH_HDR]
    for (i, value) in cells.items():   # positional overrides: {"i11": "Late"}
        values[int(i[1:])] = value
    return IMS.read_cash_tab(0, [], [CASH_HDR, values])[0]


def test_line_broken_headers_read_from_an_upload():
    rec = IMS.read_leasing_block(0, [], [LEASE_HDR, ["", VID, "Current", "96", "3,199", "0", "5", "3199"]], [])[0]
    assert (rec["pmt_inc_vat"], rec["dp_inc_vat"], rec["system_kwp"]) == ("3199.00", "0.00", "5.00")


def test_status_word_fills_an_unpaid_instalment_cell():
    rec = _cash_rec(i10="50000", i11="Paid", i13="", i14="Late", i12="2026-08-10")
    assert [m and m["kind"] for m in rec["months"]] == ["PAID", "LATE"]
    assert rec["next_due_date"] == "2026-08-10"


def _status(rec, as_of=date(2026, 9, 8)):
    k, _ = book._cash_contract("K", "u", rec, [], as_of)
    return k.status


def test_fully_paid_cash_is_not_past_due():
    assert _status(_cash_rec(i10="95000", i11="Paid")) == "ACTIVE"


def test_close_in_comment_closes():
    assert _status(_cash_rec(i6="Close", i10="95000", i11="Paid")) == "CLOSED"


def test_sheet_overdue_count_makes_it_past_due():
    assert _status(_cash_rec(i7="1", i10="50000", i11="Paid", i12="2026-08-10", i14="Late")) == "PAST_DUE"


def test_balance_not_yet_due_stays_active():
    assert _status(_cash_rec(i10="50000", i11="Paid", i12="2026-10-10")) == "ACTIVE"


def test_a_first_due_on_the_31st_builds_a_schedule():
    """A Done - Collection row due on the 31st crashed the whole install once its PMT
    was read (day is out of range for month): a short month takes its last day."""
    from app.fixtures import _add_months
    assert _add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert _add_months(date(2025, 1, 31), 2) == date(2025, 3, 31)


def test_nan_in_a_money_cell_is_no_money():
    assert IMS.money("NaN") is None and IMS.money("inf") is None and IMS.money("1,200") == "1200.00"


def test_an_instalment_due_on_the_31st_counts_on_its_own_day():
    """instalments_due_by capped the day at 28 while the schedule falls on the 31st."""
    assert book.instalments_due_by(date(2026, 1, 31), 12, date(2026, 3, 29)) == 2
    assert book.instalments_due_by(date(2026, 1, 31), 12, date(2026, 3, 31)) == 3
