"""The payment position — plan 2026-09-11 §1.1, built in Feedback Round 1 (WP1/WP3).

Four questions in one server-owned block: did they pay, how much is left, when did
money last come in, and WHO SAYS SO. The manager's own words: "each case shows how
many invoices are paid and how many unpaid remain".

Every figure is produced here, once, as a string (api.js:1-4). When the as-of date
is unknowable the block refuses — as_of, as_of_days and stale are None and note_th
says so — rather than printing today's date as if it knew.

Feedback Round 1 controller ruling (task-10): `_sheet_captured_on()` used to call
`book_source.load()` — which re-reads the whole book, the 1.3 MB fixture JSON or a
re-query of the landing schema — on every `build()` call, i.e. once per work item,
212 times on a single `/v1/today` or `/v1/workbook` request. The book only changes
at process start and on `main.reload_book()`, so the capture date is memoised at
module level: `_UNSET` distinguishes "never asked" from a legitimately cached
`None` (an older fixture with no capture date at all). `forget_capture_date()`
resets the cache; `main.reload_book()` calls it, because that is the one place the
underlying book actually changes.

Feedback Round 1, task 25b (controller ruling): `as_of` precedence when the newest
receipt is PEAK_REPORT-sourced. A receipt's own date says when THAT payment landed;
the PEAK report's own `report_as_of` says how current the WHOLE PICTURE is, and the
report states nothing more was paid up to that day — which is routinely later than
the last payment it carries (measured on the real export: last payment 2026-09-03,
report as of 2026-09-14). So a PEAK_REPORT receipt takes `as_of` (and therefore the
note, `as_of_days` and `stale`) from `customer.sheet["peak"]["report_as_of"]` when
the block carries one; `last_money_in` still keeps the receipt's own date and
amount, unchanged. A SLIP or PEAK_DOC receipt, or a PEAK_REPORT receipt whose block
carries no `report_as_of`, keeps its own date as `as_of` — unchanged.
"""
from datetime import date
from decimal import Decimal

from . import book_source
from .config import settings

OPEN_STATES = ("ISSUED", "SENT", "PARTIALLY_PAID", "OVERDUE")
SETTLED_STATES = ("PAID",)
SOURCES = ("SHEET", "SLIP", "PEAK_DOC", "PEAK_REPORT", "PEAK_RECEIPT")
# Fix-all P1 (M3): receipt-run money was served as an officer's slip. Both PEAK
# reports take `as_of` from the served block's report_as_of (task 25b's rule).
REPORT_SOURCES = ("PEAK_REPORT", "PEAK_RECEIPT")

NOTE_UNKNOWN_TH = ("ไม่ทราบว่าข้อมูลการชำระนี้เป็นข้อมูล ณ วันใด — ชีตที่นำเข้าไม่ได้บันทึกวันที่ดึงข้อมูล "
                   "จึงบอกไม่ได้ว่าเก่าแค่ไหน")
NOTE_SHEET_TH = "ข้อมูลการชำระมาจากชีต ณ วันที่ %s"
NOTE_RECEIPT_TH = {
    "SLIP": "ข้อมูลล่าสุดมาจากสลิปที่เจ้าหน้าที่ยืนยัน เมื่อ %s",
    "PEAK_DOC": "ข้อมูลล่าสุดมาจากเอกสาร PEAK ที่อัปโหลด เมื่อ %s",
    "PEAK_REPORT": "ข้อมูลล่าสุดมาจากรายงานใบแจ้งหนี้ PEAK ณ %s",
    "PEAK_RECEIPT": "ข้อมูลล่าสุดมาจากใบเสร็จจากรายงานรับชำระ PEAK ณ %s",
}
NOTE_STALE_TH = " · เก่ากว่า %d วัน ควรตรวจสอบกับ PEAK"
NOTE_UNKNOWN_EN = ("It is not known what date this payment data is from — the imported sheet did not record "
                   "when it was pulled, so its age cannot be told")
NOTE_SHEET_EN = "Payment data from the sheet as of %s"
NOTE_RECEIPT_EN = {
    "SLIP": "Latest data from a slip an officer confirmed, on %s",
    "PEAK_DOC": "Latest data from an uploaded PEAK document, on %s",
    "PEAK_REPORT": "Latest data from the PEAK invoice report as of %s",
    "PEAK_RECEIPT": "Latest data from the PEAK receipt report as of %s",
}
NOTE_STALE_EN = " · older than %d days, check against PEAK"

# Feedback Round 1 controller ruling (task-10): a sentinel distinct from any real
# captured_on value (including None), so the module can tell "never loaded" from
# "loaded, and the sheet legitimately carries no date" apart.
_UNSET = object()
_CAPTURED = _UNSET


def _sheet_captured_on():
    global _CAPTURED
    if _CAPTURED is _UNSET:
        _CAPTURED = (book_source.load().get("source") or {}).get("captured_on")
    return _CAPTURED


def forget_capture_date():
    """Reset the memoised capture date. Called from `main.reload_book()` — the one
    place the served book actually changes after process start."""
    global _CAPTURED
    _CAPTURED = _UNSET


def _money(raw):
    return str(Decimal(str(raw)).quantize(Decimal("0.01")))


def _date(raw):
    y, m, d = (int(p) for p in str(raw)[:10].split("-"))
    return date(y, m, d)


def _mine(customer, rows):
    from .main import rows_for          # indexed within a GET (main.rows_for)
    return rows_for(rows, "contract_uid", {k.uid for k in customer.contracts})


def _oldest_unpaid(invoices):
    open_rows = [i for i in invoices if i["state"] in OPEN_STATES]
    if not open_rows:
        return None
    oldest = min(open_rows, key=lambda i: (i["due_date"] is None, i["due_date"] or "", i["uid"]))
    outstanding = oldest.get("outstanding")
    if outstanding in (None, ""):
        outstanding = oldest["amount"]
    return {"uid": oldest["uid"], "peak_number": oldest.get("peak_number"),
            "due_date": oldest["due_date"], "outstanding": _money(outstanding)}


def _last_money_in(receipts):
    dated = [r for r in receipts if r.get("received_on")]
    if not dated:
        return None
    newest = max(dated, key=lambda r: (str(r["received_on"]), r["uid"]))
    source = newest.get("source") or "SLIP"
    return {"amount": _money(newest["amount"]), "on": str(newest["received_on"])[:10],
            "source": source if source in SOURCES else "SLIP", "ref": newest.get("ref") or newest["uid"]}


def build(customer, jstate, business_date):
    invoices = _mine(customer, jstate.invoices)
    receipts = _mine(customer, jstate.receipts)
    last_in = _last_money_in(receipts)
    peak = (getattr(customer, "sheet", {}) or {}).get("peak") or {}
    if last_in is not None:
        source = last_in["source"]
        # Task 25b: a PEAK_REPORT receipt's own date is when THAT payment landed,
        # not how current the report itself is. When the block carries its own
        # report_as_of, as_of (and staleness) follow the report, not the receipt —
        # last_money_in below keeps the receipt's own date and amount either way.
        if source in REPORT_SOURCES and peak.get("report_as_of"):
            as_of = peak["report_as_of"]
        else:
            as_of = last_in["on"]
        note = NOTE_RECEIPT_TH.get(source, NOTE_RECEIPT_TH["SLIP"]) % as_of
        note_en = NOTE_RECEIPT_EN.get(source, NOTE_RECEIPT_EN["SLIP"]) % as_of
    elif any(i.get("source") == "PEAK_REPORT" for i in invoices) and peak.get("report_as_of"):
        source, as_of = "PEAK_REPORT", peak["report_as_of"]
        note = NOTE_RECEIPT_TH["PEAK_REPORT"] % as_of
        note_en = NOTE_RECEIPT_EN["PEAK_REPORT"] % as_of
    else:
        source, as_of = "SHEET", _sheet_captured_on()
        note = NOTE_SHEET_TH % as_of if as_of else NOTE_UNKNOWN_TH
        note_en = NOTE_SHEET_EN % as_of if as_of else NOTE_UNKNOWN_EN
    if as_of:
        as_of_days = (business_date - _date(as_of)).days
        stale = as_of_days > settings.payment_position_stale_days
        if stale:
            note += NOTE_STALE_TH % settings.payment_position_stale_days
            note_en += NOTE_STALE_EN % settings.payment_position_stale_days
    else:
        as_of_days, stale = None, None
    from . import service_deferrals, main
    adjustment = {}
    if any(service_deferrals.has_history(k.uid) for k in customer.contracts):
        deferred = [line for k in customer.contracts for line in service_deferrals.apply_schedule(
            k, service_deferrals.raw_lines(k)) if getattr(line, "service_deferral", None)
            and line.due_date >= business_date]
        adjustment = {
            "peak_outstanding": _money(sum((service_deferrals.outstanding(i) for i in invoices
                                             if i.get("source") == "PEAK_REPORT"), Decimal("0"))),
            "collection_overdue": _money(main._customer_aggregate(customer)[0]),
            "deferred_amount": _money(sum((max(line.outstanding_amount, Decimal("0"))
                                            for line in deferred), Decimal("0"))),
            "deferred_count": len(deferred),
            "adjustment_note_th": "ยอดติดตามใช้วันครบกำหนดใหม่ของงวดที่เลื่อนเพราะปัญหาบริการ; ยอด PEAK เป็นข้อมูลใบแจ้งหนี้เดิม",
            "adjustment_note_en": "Collection uses service-adjusted due dates; PEAK retains the original invoice balances.",
        }
    return {
        **adjustment,
        "paid_count": sum(1 for i in invoices if i["state"] in SETTLED_STATES),
        "open_count": sum(1 for i in invoices if i["state"] in OPEN_STATES),
        "total_count": len(invoices),
        "oldest_unpaid": _oldest_unpaid(invoices),
        "last_money_in": last_in,
        "source": source, "as_of": as_of, "as_of_days": as_of_days, "stale": stale, "note_th": note, "note_en": note_en,
    }
