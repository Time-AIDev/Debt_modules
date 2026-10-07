"""Payment position — the block, its provenance, and its refusal.

Plan `docs/archive/superpowers/plans/2026-09-11-peak-upload-payment-position.md`.

Every test here is an ADDITION. Nothing in this file edits an existing assertion.

Feedback Round 1, Task 10: the `payment_position` block itself, served on the work
item (`/v1/today` items and the case's `work_item`), the Work Book row, and the
per-customer invoices payload. Controller ruling (task-10): `_sheet_captured_on()`
memoises held fixture metadata; `forget_capture_date()` resets the cache and is
called from every fixture below that touches the capture date, so no test leaks
a cached value into the next. Database dates belong to the current SQL snapshot.
"""
import datetime

import pytest
from fastapi.testclient import TestClient

from app import book_source, journey, payment_position
from app.main import app

client = TestClient(app)


def test_the_source_block_carries_a_capture_date_or_says_it_cannot():
    """Plan §1.3 / §0's measured gap.

    `book_source` built the source block with spreadsheet, id, render, pii and
    blocks — and no date. So no caller could tell how stale a payment status was;
    not "hard to tell", impossible. The key must EXIST on both load paths. An older
    fixture legitimately carries None: what is forbidden is the key being absent,
    because then nothing downstream can tell "unknown" from "never asked".
    """
    payload = book_source.load()
    assert payload is not None, "the fixture book must load for this suite to mean anything"
    source = payload["source"]
    assert "captured_on" in source, "the source block must say when the sheet was captured"
    assert source["captured_on"] is None or isinstance(source["captured_on"], str)


# --- payment_position.build() — the block itself ----------------------------------

@pytest.fixture
def jstate():
    payment_position.forget_capture_date()
    journey.reset()
    yield journey.for_current()
    journey.reset()
    payment_position.forget_capture_date()


def _customer_with(jstate, invoices, receipts=()):
    customer = next(c for c in journey.book_customers() if c.contracts)
    contract_uid = customer.contracts[0].uid
    for uid in [u for u, i in jstate.invoices.items() if i["contract_uid"] == contract_uid]:
        del jstate.invoices[uid]
    for uid in [u for u, r in jstate.receipts.items() if r["contract_uid"] == contract_uid]:
        del jstate.receipts[uid]
    for amount, due, state, peak_number in invoices:
        inv = journey.make_invoice(jstate, contract_uid, "SPV", "INSTALMENT", amount, due, state)
        inv["peak_number"] = peak_number
    # Author an explicit calendar for this focused position test.
    from app.money.models import Instalment
    from decimal import Decimal
    customer.contracts[0].instalments = [Instalment(due_date=row[1], category='REGULAR',
        principal_amount=Decimal(row[0]), interest_amount=Decimal('0')) for row in invoices]
    for amount, on, source, ref in receipts:
        rcp = journey.make_receipt(jstate, contract_uid, "SPV", amount, on)
        rcp["source"], rcp["ref"] = source, ref
    return customer


def test_it_counts_paid_and_open_and_names_the_oldest_unpaid(jstate):
    customer = _customer_with(jstate, [
        ("8399.00", datetime.date(2026, 4, 12), "PAID", "IVT-20260400091"),
        ("8399.00", datetime.date(2026, 5, 12), "OVERDUE", "IVT-20260500090"),
        ("8399.00", datetime.date(2026, 6, 18), "OVERDUE", "IVT-20260600090")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert (block["paid_count"], block["open_count"], block["total_count"]) == (1, 2, 3)
    assert block["oldest_unpaid"]["peak_number"] == "IVT-20260500090"
    assert block["oldest_unpaid"]["due_date"] == "2026-05-12"
    assert isinstance(block["oldest_unpaid"]["outstanding"], str)


def test_with_no_receipt_the_source_is_the_sheet_and_the_capture_date_or_unknown(jstate):
    customer = _customer_with(jstate, [("8399.00", datetime.date(2026, 5, 12), "OVERDUE", None)])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["source"] == "SHEET" and block["last_money_in"] is None
    assert block["as_of"] is None and block["stale"] is None and "ไม่ทราบ" in block["note_th"]


def test_the_newest_receipt_moves_the_source_and_the_as_of(jstate):
    customer = _customer_with(jstate, [("8399.00", datetime.date(2026, 5, 12), "PAID", None)],
                              [("38257.45", "2026-07-16", "PEAK_REPORT", "RE-20260700272"),
                               ("8399.00", "2026-03-02", "SLIP", "slip-0001")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["source"] == "PEAK_REPORT" and block["as_of"] == "2026-07-16"
    assert block["last_money_in"] == {"amount": "38257.45", "on": "2026-07-16", "source": "PEAK_REPORT", "ref": "RE-20260700272"}
    assert block["as_of_days"] == 57 and block["stale"] is True


def test_a_peak_customer_with_no_receipt_is_as_of_the_report(jstate):
    from tests.test_peak_book import _with_peak, LATE
    customer, state = _with_peak([dict(LATE, cycle=None)])
    block = payment_position.build(customer, state, datetime.date(2026, 9, 21))
    assert block["source"] == "PEAK_REPORT" and block["as_of"] == "2026-09-14" and block["open_count"] == 1


def test_the_four_surfaces_serve_the_position():
    payment_position.forget_capture_date()
    item = client.get("/v1/today").json()["items"][0]
    assert item["payment_position"]["source"] in ("SHEET", "SLIP", "PEAK_DOC", "PEAK_REPORT")
    uid = item["customer"]["uid"]
    assert "payment_position" in client.get("/v1/cases/by-customer/%s/invoices" % uid).json()
    assert "payment_position" in client.get("/v1/cases/by-customer/%s" % uid).json()["work_item"]
    book = client.get("/v1/workbook").json()
    assert "payment_position" in book["rows"][0] and "payment_position" in book["meta"]["columns"]


# --- controller ruling (task-10): memoise the capture date, forget it on reload ---

def test_the_capture_date_is_read_once_and_forgotten_on_reload(jstate, monkeypatch):
    """Held fixture metadata, including null, is read once until book reload."""
    customer = _customer_with(jstate, [("8399.00", datetime.date(2026, 5, 12), "OVERDUE", None)])
    real_load = book_source.capture_date
    calls = {"n": 0}

    def counting_load():
        calls["n"] += 1
        return real_load()

    monkeypatch.setattr(book_source, "capture_date", counting_load)
    payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert calls["n"] == 1, "a second build() must not re-load the book"

    payment_position.forget_capture_date()
    payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert calls["n"] == 2, "forget_capture_date() must force the next build() to reload"


# --- fix round 1 (Important I1): the CSV cell is worded, never a fraction, never "None" ---

def test_the_csv_cell_is_worded_not_a_fraction_and_never_none():
    """`"%s/%s" % (paid, open)` read as a date in Excel/Google Sheets ("1/2"), and
    printed the literal string "None/None" for a row with no served block. The cell
    is worded ("paid N · open M") and blank — never "None" — when payment_position
    is absent or null. Uses `/v1/workbook:export`, the same route
    test_ux_round1.py's own CSV tests use."""
    import csv
    import io
    import re

    from app.routers.today import _write_rows

    data = client.get("/v1/workbook").json()
    columns = data["meta"]["columns"]
    idx = columns.index("payment_position")
    body = client.get("/v1/workbook:export").text.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(body)))
    served = [r for r in rows if r["payment_position"]]
    assert served, "at least one row must carry a served payment_position for this test to mean anything"
    for row in rows:
        assert "/" not in row["payment_position"], row["payment_position"]
        assert "None" not in row["payment_position"], row["payment_position"]
    for row in served:
        assert re.match(r"^paid \d+ · open \d+$", row["payment_position"]), row["payment_position"]

    # The absent/null branch, against a real row's own shape (never a hand-built
    # fake): _write_rows must leave the cell blank, not print "None".
    out = io.StringIO()
    writer = csv.writer(out)
    row = dict(data["rows"][0])
    row["payment_position"] = None
    _write_rows(writer, [row])
    cell = next(csv.reader(io.StringIO(out.getvalue())))[idx]
    assert cell == ""


# --- task 25b (controller ruling): as_of follows the PEAK report, not the payment date ---

def test_a_peak_report_receipt_takes_as_of_from_the_report_not_the_payment_date(jstate):
    """Measured on the real export: a customer's last PEAK-reported payment landed
    2026-09-03, but the report itself is true as of 2026-09-14 — the report says
    nothing more was paid up to that day, which is routinely later than the last
    payment it carries. as_of, the note and staleness follow report_as_of;
    last_money_in keeps the receipt's own date and amount, unchanged."""
    from tests.test_peak_book import PAID, _with_peak
    row = dict(PAID, payment=dict(PAID["payment"], on="2026-09-03"))
    customer, state = _with_peak([row], report_as_of="2026-09-14")
    block = payment_position.build(customer, state, datetime.date(2026, 9, 21))
    assert block["source"] == "PEAK_REPORT"
    assert block["as_of"] == "2026-09-14"
    assert block["last_money_in"]["on"] == "2026-09-03"
    assert block["last_money_in"]["amount"] == "8399.00"
    assert "2026-09-14" in block["note_th"]
    assert block["as_of_days"] == 7  # 2026-09-21 - 2026-09-14, not - 2026-09-03


def test_a_peak_report_receipt_with_no_report_as_of_keeps_the_payment_date(jstate):
    """The other half of the ruling: a PEAK_REPORT receipt whose block carries no
    report_as_of keeps today's behaviour — the receipt's own date."""
    from tests.test_peak_book import PAID, _with_peak
    row = dict(PAID, payment=dict(PAID["payment"], on="2026-09-03"))
    customer, state = _with_peak([row], report_as_of=None)
    block = payment_position.build(customer, state, datetime.date(2026, 9, 21))
    assert block["source"] == "PEAK_REPORT"
    assert block["as_of"] == "2026-09-03"


def test_a_receipt_run_payment_is_named_as_the_receipt_report_and_dated_by_it(jstate):
    """Fix-all P1 (M3): receipt-run money was served as "a slip an officer confirmed".
    It names the PEAK receipt report, and as_of follows the served block's own date."""
    from tests.test_peak_book import PAID, _with_peak
    row = dict(PAID, payment_source="PEAK_RECEIPT", payment=dict(PAID["payment"], on="2026-09-03"))
    customer, state = _with_peak([row], report_as_of="2026-09-16")
    block = payment_position.build(customer, state, datetime.date(2026, 9, 21))
    assert block["source"] == "PEAK_RECEIPT" and block["last_money_in"]["source"] == "PEAK_RECEIPT"
    assert block["as_of"] == "2026-09-16" and block["last_money_in"]["on"] == "2026-09-03"
    assert block["note_th"] == "ข้อมูลล่าสุดมาจากใบเสร็จจากรายงานรับชำระ PEAK ณ 2026-09-16"
    assert block["note_en"] == "Latest data from the PEAK receipt report as of 2026-09-16"


def test_a_slip_receipt_keeps_its_own_date_as_of(jstate):
    """SLIP (and PEAK_DOC) receipts are untouched by the ruling — their own date is
    already the truth about when that money came in."""
    customer = _customer_with(jstate, [("8399.00", datetime.date(2026, 5, 12), "PAID", None)],
                              [("8399.00", "2026-08-20", "SLIP", "slip-0002")])
    block = payment_position.build(customer, jstate, datetime.date(2026, 9, 11))
    assert block["source"] == "SLIP" and block["as_of"] == "2026-08-20"


# --- Task 14 (Feedback Round 1): position=unpaid|stale, and the oldest_unpaid sort ---
# Controller ruling (task-14): `position` is a parameter of `_workbook` and all three
# routes; it is validated first (422, not silently ignored on a typo) and then
# filtered in the SAME block as `payment_status`, so CLOSED rows (appended before
# that block) and meta.total agree with both CSV exports by construction.

def test_the_book_filters_to_the_unpaid_and_to_the_stale():
    everyone = client.get("/v1/workbook").json()["rows"]
    unpaid = client.get("/v1/workbook?position=unpaid").json()["rows"]
    assert 0 < len(unpaid) <= len(everyone)
    assert all(r["payment_position"]["open_count"] > 0 for r in unpaid)
    stale = client.get("/v1/workbook?position=stale").json()["rows"]
    assert 0 < len(stale) < len(everyone)
    assert all(r["payment_position"]["stale"] is True for r in stale)
    # meta.total must agree with the filtered row count — the same rule that
    # keeps the CLOSED-row path from silently disagreeing (test_round4.py:765).
    assert client.get("/v1/workbook?position=unpaid").json()["meta"]["total"] == len(unpaid)


def test_an_unknown_position_filter_is_refused_not_ignored():
    response = client.get("/v1/workbook?position=banana")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["errors"][0]["pointer"] == "/position"
    assert body["errors"][0]["message_th"] == "ตัวกรองสถานะการชำระรับเฉพาะ unpaid หรือ stale"


def test_the_csv_export_honours_the_position_filter_too():
    """Ruling (a): the export shares `_workbook`, so the row count and a bad value's
    422 must agree with the JSON route — find the existing export tests first
    (test_round4.py's own `test_f2_the_export_honours_the_ladder_filter` is the
    model this follows)."""
    import csv
    import io

    filtered_meta = client.get("/v1/workbook?position=stale").json()["meta"]
    assert filtered_meta["total"] > 0
    body = client.get("/v1/workbook:export?position=stale").text.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(body)))
    assert len(rows) == filtered_meta["total"]
    assert client.get("/v1/workbook:export?position=banana").status_code == 422


def test_the_book_sorts_oldest_unpaid_first_dated_then_undated_ascending():
    rows = client.get("/v1/workbook?sort=oldest_unpaid&dir=asc").json()["rows"]
    dues = [((r.get("payment_position") or {}).get("oldest_unpaid") or {}).get("due_date") for r in rows]
    dated = [d for d in dues if d]
    assert dated, "the live book must carry at least one oldest_unpaid date for this test to mean anything"
    assert dues[:len(dated)] == dated
    assert all(d is None for d in dues[len(dated):])
    assert dated == sorted(dated)


def test_the_book_sorts_oldest_unpaid_descending_with_undated_still_last():
    rows = client.get("/v1/workbook?sort=oldest_unpaid&dir=desc").json()["rows"]
    dues = [((r.get("payment_position") or {}).get("oldest_unpaid") or {}).get("due_date") for r in rows]
    dated = [d for d in dues if d]
    assert dues[:len(dated)] == dated
    assert all(d is None for d in dues[len(dated):])
    assert dated == sorted(dated, reverse=True)


# --- Task 14 fix round 1 (I1): the position filter names itself in the export ---
# Controller ruling (I1): `_filters_note` fed both the governed export's own
# "# ตัวกรอง: …" banner and the durable workbook_exports.record() audit entry —
# and never received `position`. A position-filtered export was describing,
# and recording, itself as unfiltered. Same call shape as
# test_round5_data_flow.py's own ruling-72 tests (a reason in the body, the
# recorded entry read back from GET /v1/workbook/exports).

def test_the_position_filter_names_itself_in_the_export_banner_and_the_record():
    resp = client.post("/v1/workbook:export", params={"position": "unpaid"},
                       json={"reason": "ตรวจสอบใบค้างชำระก่อนปิดรอบ"})
    assert resp.status_code == 200
    uid = resp.headers["X-Volt-Export-Uid"]
    body = resp.text.lstrip("﻿")
    lines = body.splitlines()
    banner = lines[2]
    assert banner.startswith("# ตัวกรอง")
    assert "position=unpaid" in banner

    exports = client.get("/v1/workbook/exports").json()["exports"]
    entry = next(e for e in exports if e["uid"] == uid)
    assert "position=unpaid" in entry["filters"]
