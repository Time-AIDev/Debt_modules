"""The five weekly figures the report did not serve — Feedback Round 1, WP12 (design F15).

`reports.weekly()` spreads `build(...)` into its payload, beside the keys it already
served; nothing it served before changes. Each figure is computed once, here:

  mom               this calendar month's receipts vs the same span of last month
  paying_customers  distinct customers with a receipt, this 7-day period vs the 7 before
  npl_movement      into / out of NPL in the period: status changes AND declarations
  arrears_split     arrears held on the company side (OD-02 hold, open service issue)
                    vs true arrears, per instalment / cash line
  status_changes    every PAYMENT_STATUS_SET in the period (from -> to, by, reason)

House rules carried here:
  - Money is Decimal, served as strings quantised to 0.01. The client never adds
    (api.js:1-4) — every total and every change is on the wire.
  - Every figure carries `definition` / `definition_th` (the F15 sentence) and
    `source` (the stores it reads).
  - `notes` is a list of {code, en, th}. A zero whose source is empty says so, and a
    figure known to be partial says so and sets `indicative` — never a silent 0 that
    reads as "nobody paid".
  - Read-only: nothing here writes to any store.

B13 fix round 1: `mom` and `paying_customers` (and `reports.weekly()`'s `cash_in`)
are whole-book / per-customer totals. They read `jstate.receipts` directly — every
receipt on record, not the receipts of one invoice — so they are NOT built on
`journey.invoice_receipts()` the way a per-invoice paid-so-far check is. What they
share is `counted_receipts()`, the one place a payment on record twice (a PEAK report
receipt and receipts a person recorded against the same invoice) is folded into one;
`journey.invoice_receipts()` is called there only to match those receipts to the
invoice's own customer.

B13 fix round 2: the same units are read by `reports._allocation_hold_in_period` (the
OD-02 hold, via `unit_is_allocated`) and by `collection_kpi.cash_received`, the monthly
figure that carries the same `cash_received` label as `mom`.
"""
from datetime import timedelta
from decimal import Decimal

from . import journey
# B13b: import the redaction only. customer_contact.py is B6's; its name and behaviour
# (a run of nine or more digits -> "[ตัดเบอร์ออก]") are the contract relied on here.
from .customer_contact import _without_numbers

CENT = Decimal("0.01")
# The one routing rule (entities.py): SPV carries the lease instalments, EPC the cash
# and project receivables AND every service fee. The same two keys `cash_in` already
# serves, so the new figures and the old one name their lines alike.
LINE_OF_ENTITY = {"SPV": "instalment", "EPC": "cash_or_project"}
RECEIPT_LINES = ("instalment", "cash_or_project")
# A contract whose product has no entity stays unrouted, visibly (fixtures.py) —
# its arrears land here, never in a guessed line.
ARREARS_LINES = ("instalment", "cash_or_project", "unrouted")
PEAK_SOURCE = "PEAK_REPORT"
# Fix-all P1: the receipt run's money is PEAK's too — it folds against a person's
# receipt exactly as the report's own paid columns do. A folded unit keeps PEAK_SOURCE.
PEAK_SOURCES = journey.PEAK_SOURCES
# The flags journey.reseed_peak stamps on a person's receipt whose invoice uid now
# names another customer's invoice, or an invoice whose owner cannot be resolved.
# Read with .get: a receipt that was never through a reseed carries neither.
RECEIPT_FLAGS = ("invoice_moved_to_other_customer", "invoice_owner_unknown")

DEFINITIONS = {
    "mom": (
        "Receipts this calendar month (day 1 to the business date) against the same span of "
        "last month, split instalment (SPV) and cash/project (EPC, service fees included). "
        "Counted from the receipts on record, including an applied PEAK report's receipts; a payment "
        "on record both in a PEAK report and as a receipt recorded here for the same invoice is counted once.",
        "ยอดรับเงินเดือนนี้ (วันที่ 1 ถึงวันทำการ) เทียบช่วงวันเดียวกันของเดือนก่อน แยกค่างวด (SPV) "
        "และเงินสด/โครงการ (EPC รวมค่าบริการ) นับจากใบเสร็จในระบบ รวมใบเสร็จจากรายงาน PEAK ที่ใช้งานแล้ว "
        "การชำระที่มีทั้งในรายงาน PEAK และใบเสร็จที่บันทึกในระบบนี้กับใบแจ้งหนี้เดียวกันนับครั้งเดียว",
    ),
    "paying_customers": (
        "Distinct customers with at least one receipt in this 7-day period, against the 7 days before it. "
        "A payment on record both in a PEAK report and as a receipt recorded here counts as one receipt.",
        "จำนวนลูกค้าที่มีใบเสร็จอย่างน้อย 1 ใบในช่วง 7 วันนี้ (นับหัวไม่ซ้ำ) เทียบกับ 7 วันก่อนหน้า "
        "การชำระที่มีทั้งในรายงาน PEAK และใบเสร็จที่บันทึกในระบบนี้นับเป็นใบเดียว",
    ),
    "npl_movement": (
        "Into NPL: payment-status changes to NPL in the period, and NPL declarations opened in the "
        "period; both are counted, and `customers` counts each customer once. Out of NPL: "
        "payment-status changes from NPL to any other status in the period.",
        "เข้า NPL: การเปลี่ยนสถานะการชำระเป็น NPL ในช่วงนี้ และการประกาศ NPL ที่เปิดในช่วงนี้ "
        "นับทั้งสองแบบ และช่องลูกค้านับหัวไม่ซ้ำ · ออกจาก NPL: การเปลี่ยนสถานะจาก NPL เป็นค่าอื่นในช่วงนี้",
    ),
    # B13 fix round 1, finding (3): the OD-02 receipt hold is a 7-day window
    # (reports._allocation_hold_in_period reads the period's counted units only), so the
    # sentence says so — on day 8 a customer whose money is in moves back to true.
    "arrears_split": (
        "Arrears of the customers in collection on the business date, per instalment and cash line. "
        "Held on the company side: the customer has a receipt dated inside this report's 7-day period "
        "that is not allocated while the allocation order is undecided, a case put on allocation hold, or an open "
        "service issue. True arrears: every other customer. The receipt test looks back 7 days only: "
        "from the 8th day, a customer whose money is in but still unallocated counts as true arrears again.",
        "ยอดค้างของลูกค้าที่อยู่ในการติดตาม ณ วันทำการ แยกค่างวดและเงินสด · พักไว้ฝั่งบริษัท = ลูกค้าที่มีใบเสร็จ "
        "ลงวันที่ภายในช่วง 7 วันของรายงานนี้ที่ยังไม่จัดสรร (รอบัญชีตัดสินลำดับการจัดสรร) หรือเคสที่ตั้งพักการจัดสรร "
        "หรือมีตั๋วปัญหาบริการเปิดอยู่ · ค้างจริง = ลูกค้าที่เหลือทั้งหมด · ใบเสร็จดูย้อนหลังแค่ 7 วัน "
        "ตั้งแต่วันที่ 8 ลูกค้าที่รับเงินแล้วแต่ยังไม่จัดสรรจะกลับไปนับเป็นค้างจริง",
    ),
    "status_changes": (
        "Every payment-status change in the period — from, to, who and why — whether a person "
        "made it or the system followed the data.",
        "ทุกการเปลี่ยนสถานะการชำระในช่วงนี้ (จาก → เป็น ใครเปลี่ยน เหตุผล) ทั้งที่คนเปลี่ยนเองและที่ระบบปรับตามข้อมูล",
    ),
}

SOURCES = {
    "mom": "journey.receipts, every receipt on record (slips, recorded receipts, PEAK report receipts: "
           "source PEAK_REPORT), each payment once (counted_receipts; owners matched by journey.invoice_receipts)",
    "paying_customers": "journey.receipts, every receipt on record, each payment once (counted_receipts); "
                        "customer by the receipt's contract",
    "npl_movement": "cases.events PAYMENT_STATUS_SET; journey.npl_cases declared_on",
    "arrears_split": "money engine per contract; allocation hold (unallocated counted_receipts units in the 7-day period "
                     "+ case allocation_hold); "
                     "open service issues in cases.issues and journey.issues",
    "status_changes": "cases.events PAYMENT_STATUS_SET; journey.npl_cases declared_on",
}

NOTES = {
    "NO_RECEIPTS_ON_RECORD": (
        "No receipt is on record at all: 0 means nothing was recorded, not that nobody paid.",
        "ยังไม่มีใบเสร็จในระบบเลย — 0 คือไม่มีบันทึกการรับเงิน ไม่ใช่ยืนยันว่าไม่มีใครจ่าย",
    ),
    "NO_RECEIPTS_IN_SPAN": (
        "No receipt from {start} to {end}: 0 means nothing was recorded, not that nobody paid. "
        "The latest receipt counted is dated {latest}.",
        "ไม่มีใบเสร็จช่วง {start} ถึง {end} — 0 คือไม่มีบันทึกการรับเงิน ไม่ใช่ยืนยันว่าไม่มีใครจ่าย "
        "(ใบเสร็จล่าสุดที่นับลงวันที่ {latest})",
    ),
    # Fix round 2 (minor): a span whose only receipts belong to a payment PEAK dates in
    # another span is not "nothing recorded" — the slip is there, counted on PEAK's date.
    "FOLDED_RECEIPTS_COUNTED_ELSEWHERE": (
        "Nothing is counted from {start} to {end}, but {n} receipt(s) recorded here in this span are the same "
        "payment(s) as a PEAK report receipt; each payment is counted once, on the PEAK report's payment date "
        "({dates}).",
        "ไม่มียอดที่นับในช่วง {start} ถึง {end} แต่มีใบเสร็จ {n} ใบที่บันทึกในช่วงนี้เป็นการชำระเดียวกับใบเสร็จในรายงาน PEAK "
        "จึงนับครั้งเดียวตามวันที่ชำระในรายงาน PEAK ({dates})",
    ),
    "NO_PEAK_REPORT": (
        "No PEAK report is applied, so only receipts recorded in this system are counted.",
        "ยังไม่มีรายงาน PEAK ที่ใช้งาน จึงนับเฉพาะใบเสร็จที่บันทึกในระบบนี้",
    ),
    "PEAK_REPORT_OLDER_THAN_SPAN": (
        "The applied PEAK report is as of {as_of}; its receipts after that date up to {end} are not in yet, "
        "so the span {start} to {end} is incomplete.",
        "รายงาน PEAK ที่ใช้อยู่เป็นข้อมูล ณ {as_of} ใบเสร็จหลังวันนั้นถึง {end} ยังไม่เข้า "
        "ตัวเลขช่วง {start} ถึง {end} จึงยังไม่ครบ",
    ),
    # Final fix F-R2: an apply is reseeded only for the session that made it, so a
    # different session's own receipts can lag a newer report indefinitely, and would
    # otherwise read as a complete, non-indicative 0 — the "silent 0" house rule forbids.
    "PEAK_REPORT_NOT_IN_SESSION": (
        "The PEAK report dated {as_of} was applied after this session loaded; its payments are not counted "
        "here. Reloading the book counts them.",
        "รายงาน PEAK ลงวันที่ {as_of} ถูกใช้งานหลังจากเซสชันนี้โหลดข้อมูลไปแล้ว ยอดชำระของรายงานนี้จึงยังไม่ถูกนับที่นี่ "
        "โหลดสมุดงานใหม่จึงจะนับยอดนี้",
    ),
    "SPANS_DIFFER_IN_LENGTH": (
        "This month's span has {this_days} day(s) ({this_start} to {this_end}); last month's stops on its "
        "last day and has {last_days} day(s) ({last_start} to {last_end}), so the two spans are not the same length.",
        "ช่วงเดือนนี้มี {this_days} วัน ({this_start} ถึง {this_end}) ช่วงเดือนก่อนสิ้นสุดที่วันสุดท้ายของเดือน "
        "จึงมี {last_days} วัน ({last_start} ถึง {last_end}) สองช่วงจึงยาวไม่เท่ากัน",
    ),
    "PEAK_AND_SLIP_OVERLAP": (
        "{n} payment(s) are on record twice — in a PEAK report and as receipt(s) recorded here against the "
        "same invoice, {on_record} on record in all. Each is counted once, at the larger of the two amounts "
        "(counted {counted}), on the PEAK report's payment date: {dated}. This figure is indicative until they "
        "are reconciled.",
        "การชำระ {n} รายการมีบันทึกซ้ำ ทั้งในรายงาน PEAK และใบเสร็จที่บันทึกในระบบนี้กับใบแจ้งหนี้เดียวกัน "
        "รวมที่บันทึกไว้ {on_record} · นับครั้งเดียวด้วยยอดที่มากกว่า (นับ {counted}) ตามวันที่ชำระในรายงาน PEAK: "
        "{dated_th} · ตัวเลขนี้จึงเป็นค่าประมาณจนกว่าจะกระทบยอดแล้ว",
    ),
    "FLAGGED_RECEIPTS_IN_SPAN": (
        "{n} receipt(s) from {start} to {end}, {amount} in all, name an invoice that now belongs to another "
        "customer or whose owner cannot be resolved. They are counted as recorded, on their own contract; "
        "check them against the invoice.",
        "ใบเสร็จ {n} ใบช่วง {start} ถึง {end} รวม {amount} อ้างใบแจ้งหนี้ที่ตอนนี้เป็นของลูกค้ารายอื่น "
        "หรือระบุเจ้าของไม่ได้ ยังนับตามที่บันทึกไว้กับสัญญาของใบเสร็จเอง ควรตรวจสอบกับใบแจ้งหนี้",
    ),
    "NO_BASE_FOR_PERCENT": (
        "Where the earlier span is 0, no percentage change can be given.",
        "ช่องที่ช่วงก่อนหน้าเป็น 0 คิดเป็นร้อยละการเปลี่ยนแปลงไม่ได้",
    ),
    "UNRESOLVED_RECEIPTS": (
        "{n} receipt(s) name a contract the book does not hold, so they are not counted as a customer.",
        "ใบเสร็จ {n} ใบอ้างสัญญาที่ไม่อยู่ในสมุดงาน จึงไม่นับเป็นลูกค้า",
    ),
    "EVENT_LOG_FROM_SYSTEM_START": (
        "Counted from the status changes recorded in this system; a change made before it (on the sheet) has no record.",
        "นับจากบันทึกการเปลี่ยนสถานะที่เกิดในระบบนี้ การเปลี่ยนก่อนเริ่มใช้ระบบ (ในชีต) ไม่มีบันทึก",
    ),
    "DECLARATION_ALSO_STATUS_CHANGE": (
        "{n} customer(s) entered NPL by a declaration that also changed the payment status; both rows are "
        "listed, and `customers` counts each customer once.",
        "ลูกค้า {n} รายเข้า NPL จากการประกาศที่ทำให้สถานะการชำระเปลี่ยนด้วย จึงแสดงทั้งสองแถว แต่ช่องลูกค้านับหัวไม่ซ้ำ",
    ),
    "ENTERED_AND_LEFT": (
        "{n} customer(s) both entered and left NPL in the period, so they are counted under entered and under left.",
        "ลูกค้า {n} รายทั้งเข้าและออกจาก NPL ในช่วงนี้ จึงนับทั้งในช่องเข้าและช่องออก",
    ),
    "NPL_ROWS_UNRESOLVED": (
        "{n} NPL row(s) in the period name a case whose customer is not in the book; they are left out of every count here.",
        "รายการ NPL {n} รายการในช่วงนี้อ้างเคสที่หาลูกค้าในสมุดงานไม่พบ จึงไม่นับรวมในตัวเลขนี้",
    ),
    "NO_NPL_EXIT_RECORD": (
        "Leaving NPL is counted from status changes only; the system has no record that closes a declaration.",
        "การออกจาก NPL นับจากการเปลี่ยนสถานะเท่านั้น ระบบยังไม่มีบันทึกการปิดการประกาศ NPL",
    ),
    "NO_NPL_MOVEMENT_IN_PERIOD": (
        "No customer entered or left NPL in the period.",
        "ไม่มีลูกค้าเข้าหรือออกจาก NPL ในช่วงนี้",
    ),
    "NO_STATUS_CHANGES_IN_PERIOD": (
        "No payment status changed in the period.",
        "ไม่มีการเปลี่ยนสถานะการชำระในช่วงนี้",
    ),
    "DECLARATION_WITHOUT_EVENT": (
        "{n} NPL declaration(s) in the period have no matching status change by the system, so this list "
        "does not show them; NPL in / out counts them.",
        "การประกาศ NPL {n} รายการในช่วงนี้ไม่มีบันทึกการเปลี่ยนสถานะโดยระบบที่ตรงกัน จึงไม่อยู่ในรายการนี้ "
        "ดูได้ที่ตัวเลขเข้า/ออก NPL",
    ),
    "NO_ARREARS": (
        "No customer in collection has arrears on the business date.",
        "ไม่มีลูกค้าในการติดตามที่มียอดค้าง ณ วันทำการ",
    ),
    "OD02_OPEN": (
        "Held arrears include {n} customer(s) whose money is in but not allocated while the allocation order is undecided — a receipt "
        "dated {start} to {end} (this 7-day period) or a case on allocation hold — so their arrears have not "
        "moved. A receipt older than the 7-day period no longer holds its customer.",
        "ยอดพักไว้รวมลูกค้า {n} รายที่รับเงินแล้วแต่ยังไม่จัดสรร (รอบัญชีตัดสินลำดับการจัดสรร) คือมีใบเสร็จลงวันที่ {start} ถึง {end} "
        "(ช่วง 7 วันนี้) หรือเคสที่ตั้งพักการจัดสรร ยอดค้างของลูกค้ากลุ่มนี้จึงยังไม่ลด "
        "ใบเสร็จที่เก่ากว่าช่วง 7 วันจะไม่ทำให้ลูกค้าถูกนับเป็นยอดพักอีก",
    ),
    "TWO_ISSUE_REGISTERS": (
        "Open service issues are read from both registers: the case's ticket and the service-issue desk.",
        "ตั๋วปัญหาบริการนับจากทั้งสองทะเบียน คือตั๋วบนเคส และงานปัญหาบริการ",
    ),
}


# B13b (the F18 pattern): the free-text fields a figure copies from an event into the
# payload. Counts, Decimal amounts, uids, codes and dates are computed, not typed, and
# are never passed through the redaction.
FREE_TEXT_KEYS = ("reason", "note", "comment")


def without_typed_numbers(text):
    """A typed free-text string as it may leave the report: every run of nine or more
    digits (a phone number, a 13-digit id) cut out by customer_contact._without_numbers.
    None and non-strings pass through unchanged."""
    return _without_numbers(text) if isinstance(text, str) else text


def event_without_typed_numbers(event):
    """A copy of an event whose free-text fields (FREE_TEXT_KEYS, and the same fields of
    a nested `ended` record) are redacted; every other field is copied as it is. The
    store's own event is never changed."""
    out = dict(event)
    for key in FREE_TEXT_KEYS:
        if key in out:
            out[key] = without_typed_numbers(out[key])
    if isinstance(out.get("ended"), dict):
        out["ended"] = event_without_typed_numbers(out["ended"])
    return out


def _note(code, **values):
    en, th = NOTES[code]
    return {"code": code, "en": en.format(**values), "th": th.format(**values)}


def _definition(key):
    en, th = DEFINITIONS[key]
    return {"definition": en, "definition_th": th, "definition_en": en, "source": SOURCES[key]}


def _money(value):
    return str(Decimal(value).quantize(CENT))


def _pct(now, before):
    """Percentage change, one decimal, as a string; None when there is no base."""
    now, before = Decimal(now), Decimal(before)
    if before == 0:
        return None
    return str(((now - before) / before * 100).quantize(Decimal("0.1")))


def _day(value):
    return str(value)[:10] if value else None


def _inside(value, start, end):
    day = _day(value)
    return bool(day) and str(start) <= day <= str(end)


def _amount(receipt):
    return Decimal(str(receipt["amount"]))


def _total(receipts):
    return sum((_amount(r) for r in receipts), Decimal("0"))


# --- receipts, each payment once (shared by mom, paying_customers and cash_in) ------------

def _named_by_invoice(jstate):
    """The receipts that name an invoice, grouped by `invoice_uid`, in store order — one pass."""
    named = {}
    for r in jstate.receipts.values():
        if r.get("invoice_uid"):
            named.setdefault(r["invoice_uid"], []).append(r)
    return named


def _owned(invoice, named):
    """B13b: `journey.invoice_receipts(state, invoice)`, computed from the receipts that
    already name this invoice instead of a scan of the whole store.

    `journey.invoice_receipts` stays the documented source of the rule, and
    `receipts_by_invoice_owner` is tested equal to it for every invoice: a receipt
    counts toward an invoice only when its customer (by its own contract) is the
    invoice's customer, and never when the invoice's own customer does not resolve
    (None == None is not "the same customer"). The owner lookup is the one that rule
    uses, `journey._customer_uid_for_contract`, so the two cannot drift apart."""
    owner = journey._customer_uid_for_contract(invoice["contract_uid"])
    if owner is None:
        return []
    return [r for r in named if journey._customer_uid_for_contract(r["contract_uid"]) == owner]


def receipts_by_invoice_owner(jstate):
    """{invoice_uid: receipts booked against that invoice by its OWN customer}, for every
    invoice on record that a receipt names — equal to `journey.invoice_receipts` per
    invoice (an invoice no receipt names is absent: its list would be empty), in time
    linear in the store."""
    grouped = {}
    for invoice_uid, named in _named_by_invoice(jstate).items():
        invoice = jstate.invoices.get(invoice_uid)
        if invoice is not None:
            grouped[invoice_uid] = _owned(invoice, named)
    return grouped


def counted_receipts(jstate):
    """Every receipt on record as the money it stands for, each payment counted once.

    B13 fix round 1, finding (1): an officer records a receipt against a PEAK invoice
    (POST /v1/receipts), and a PEAK report applied later shows the same invoice paid.
    The store then holds both rows, and every whole-book total added the one payment
    twice. So, per invoice, when PEAK_REPORT receipts AND receipts a person recorded
    both name it, they become ONE unit: the larger of the PEAK amount and the sum of
    the person's receipts, dated on the PEAK receipt (PEAK's own payment date; a
    receipt recorded here is stamped the day it was recorded). The receipts folded in
    are the invoice's own customer's only — `journey.invoice_receipts()` — so a receipt
    whose invoice now belongs to someone else is never folded in: it counts as itself,
    as does every receipt with no `invoice_uid`.

    Returns units in the order their first receipt is on record, each
    {uid, contract_uid, entity, amount (Decimal), received_on, source, members,
    overlap}; `overlap` is None, or {peak, recorded} (Decimal) for a folded payment.

    B13b: linear. Calling `journey.invoice_receipts()` once per overlapping invoice
    scanned the whole store each time (4,000 overlaps took seconds, on the per-request
    KPI too). The receipts are grouped by `invoice_uid` once, and each group is
    filtered by its invoice's own customer (`_owned`, the same rule).
    """
    by_invoice = _named_by_invoice(jstate)
    folded = {}
    for invoice_uid, named in by_invoice.items():
        invoice = jstate.invoices.get(invoice_uid)
        # Cheap first: only an invoice named by both kinds of receipt can overlap.
        if invoice is None or {r.get("source") in PEAK_SOURCES for r in named} != {True, False}:
            continue
        own = _owned(invoice, named)
        peak = [r for r in own if r.get("source") in PEAK_SOURCES]
        recorded = [r for r in own if r.get("source") not in PEAK_SOURCES]
        if not (peak and recorded):
            continue
        dated = max(peak, key=lambda r: (_day(r.get("received_on")) or "", r["uid"]))
        peak_amount, recorded_amount = _total(peak), _total(recorded)
        # Fix-all P6 (audit): an invoice paid in parts carries several PEAK receipts. Each
        # earlier one counts as itself, on its own date; the person's receipts fold into
        # the latest, which also carries what they recorded beyond PEAK — the invoice
        # still counts max(PEAK, recorded) once, and no part payment moves to a later week.
        unit = {"uid": dated["uid"], "contract_uid": dated["contract_uid"], "entity": dated.get("entity"),
                "amount": max(peak_amount, recorded_amount) - (peak_amount - _amount(dated)),
                "received_on": _day(dated.get("received_on")),
                "source": PEAK_SOURCE, "members": [dated] + recorded,
                "overlap": {"peak": peak_amount, "recorded": recorded_amount}}
        for r in unit["members"]:
            folded[r["uid"]] = unit
    units, placed = [], set()
    for r in jstate.receipts.values():
        unit = folded.get(r["uid"])
        if unit is None:
            units.append({"uid": r["uid"], "contract_uid": r["contract_uid"], "entity": r.get("entity"),
                          "amount": _amount(r), "received_on": _day(r.get("received_on")),
                          "source": r.get("source"), "members": [r], "overlap": None})
        elif unit["uid"] not in placed:
            placed.add(unit["uid"])
            units.append(unit)
    return units


def units_in(units, start, end):
    """The units counted inside [start, end], by the date each is counted on."""
    return [u for u in units if _inside(u["received_on"], start, end)]


def unit_is_allocated(unit):
    """Fix round 2, finding (c): whether the money a unit stands for is allocated. A
    folded payment is allocated when its PEAK side is (PEAK's receipt is the one the
    books carry; allocated when settings.peak_report_allocates). A single receipt keeps
    its own flag. The OD-02 hold and the monthly KPI's unallocated count read this."""
    side = [r for r in unit["members"] if r.get("source") in PEAK_SOURCES] if unit["overlap"] else unit["members"]
    return all(r.get("is_allocated") for r in side)


def _placed(unit, spans):
    """Fix round 2 (minor): where a folded payment is counted — its date, and which of
    the figure's spans holds it, or that none does. (en, th)."""
    day, amount = unit["received_on"], _money(unit["amount"])
    home = next((s for s in spans if _inside(day, s["start"], s["end"])), None)
    if home:
        return ("%s counted on %s, inside %s to %s" % (amount, day, home["start"], home["end"]),
                "%s นับวันที่ %s อยู่ในช่วง %s ถึง %s" % (amount, day, home["start"], home["end"]))
    return ("%s counted on %s, outside %s" % (amount, day, " and ".join("%s to %s" % (s["start"], s["end"]) for s in spans)),
            "%s นับวันที่ %s อยู่นอกช่วง %s" % (amount, day, " และ ".join("%s ถึง %s" % (s["start"], s["end"]) for s in spans)))


def overlap_note(units, spans):
    """PEAK_AND_SLIP_OVERLAP for the folded payments that touch any span — by the date
    they are counted on or by any receipt folded into them — or None when there are
    none. `spans` are {start, end} mappings. The note names the date each payment is
    counted on and whether that date falls in one of the spans. A figure carrying it is
    indicative."""
    touching = [u for u in units if u["overlap"] and any(
        _inside(r.get("received_on"), span["start"], span["end"]) for r in u["members"] for span in spans)]
    if not touching:
        return None
    on_record = sum((u["overlap"]["peak"] + u["overlap"]["recorded"] for u in touching), Decimal("0"))
    # the whole payment: a part-paid invoice's earlier PEAK receipts count as themselves
    counted = sum((max(u["overlap"]["peak"], u["overlap"]["recorded"]) for u in touching), Decimal("0"))
    placed = [_placed(u, spans) for u in touching]
    return _note("PEAK_AND_SLIP_OVERLAP", n=len(touching), on_record=_money(on_record), counted=_money(counted),
                 dated="; ".join(en for en, _th in placed), dated_th="; ".join(th for _en, th in placed))


def flagged_note(units, span):
    """FLAGGED_RECEIPTS_IN_SPAN (fix round 1, finding 2): the flagged receipts counted in
    the span — still counted, named, and (fix round 2) badging the figure indicative,
    since one may be the same money as another customer's PEAK receipt. Or None."""
    rows = [r for u in units_in(units, span["start"], span["end"]) for r in u["members"]
            if any(r.get(flag) for flag in RECEIPT_FLAGS)]
    if not rows:
        return None
    return _note("FLAGGED_RECEIPTS_IN_SPAN", n=len(rows), amount=_money(_total(rows)),
                 start=span["start"], end=span["end"])


def _latest_receipt_on(units):
    """The latest date a unit is counted on (fix round 2: not a folded slip's own date)."""
    days = [u["received_on"] for u in units if u["received_on"]]
    return max(days) if days else None


def _empty_span_notes(units, spans, latest):
    if latest is None:
        return [_note("NO_RECEIPTS_ON_RECORD")]
    notes = []
    for span in spans:
        if span["receipts"]:
            continue
        # A span with nothing counted can still hold a person's receipt folded into a
        # payment PEAK dates elsewhere: say that, never "nothing was recorded".
        elsewhere = [(u, [r for r in u["members"] if r.get("source") not in PEAK_SOURCES
                          and _inside(r.get("received_on"), span["start"], span["end"])])
                     for u in units if u["overlap"]]
        elsewhere = [(u, rows) for u, rows in elsewhere if rows]
        if elsewhere:
            notes.append(_note("FOLDED_RECEIPTS_COUNTED_ELSEWHERE", start=span["start"], end=span["end"],
                               n=sum(len(rows) for _u, rows in elsewhere),
                               dates=", ".join(sorted({u["received_on"] for u, _rows in elsewhere}))))
        else:
            notes.append(_note("NO_RECEIPTS_IN_SPAN", start=span["start"], end=span["end"], latest=latest))
    return notes


def _badge_notes(units, spans):
    """The notes both receipt figures carry after their own: the PEAK badge checked for
    EVERY span (finding 4, and the minor 'both spans'), the folded payments (finding 1)
    and the flagged receipts per span (finding 2). Each of the three makes the figure
    indicative. Returns (notes, peak_report_as_of, indicative).

    Final fix F-R2: also folds in peak_session_gap — this reading session's own PEAK
    report date against the book's current one. When they differ, `as_of` served back
    is the SESSION's own date, not the book's newer one; see that function's docstring."""
    as_of = peak_report_as_of()
    notes = [_note("NO_PEAK_REPORT")] if as_of is None else []
    partial = as_of is None
    for span in spans:
        # A span is known to be partial whenever PEAK's receipts do not reach its last day.
        if as_of is not None and as_of < span["end"]:
            notes.append(_note("PEAK_REPORT_OLDER_THAN_SPAN", as_of=as_of, start=span["start"], end=span["end"]))
            partial = True
    overlap = overlap_note(units, spans)
    if overlap:
        notes.append(overlap)
    flagged = [n for n in (flagged_note(units, span) for span in spans) if n]
    notes.extend(flagged)
    session_as_of, gap_note = peak_session_gap(journey.for_current())
    if gap_note:
        notes.append(gap_note)
        as_of = session_as_of
    return notes, as_of, partial or overlap is not None or bool(flagged) or gap_note is not None


def month_spans(business_date):
    """((this_start, this_end), (last_start, last_end)) as dates. Last month's span stops
    on the same day number, clipped to that month's last day (31 Mar -> 1-28 Feb)."""
    this_start = business_date.replace(day=1)
    last_month_end = this_start - timedelta(days=1)
    last_start = last_month_end.replace(day=1)
    last_end = last_start.replace(day=min(business_date.day, last_month_end.day))
    return (this_start, business_date), (last_start, last_end)


def peak_report_as_of():
    """The applied PEAK report's date, from the one seam the book carries it on
    (customer.sheet["peak"]["report_as_of"], as payment_position reads it); None when
    no report is applied."""
    dates = []
    for customer in journey.book_customers():
        peak = (getattr(customer, "sheet", None) or {}).get("peak") or {}
        if peak.get("report_as_of"):
            dates.append(str(peak["report_as_of"]))
    return max(dates) if dates else None


def peak_session_gap(jstate):
    """Final fix F-R2. `jstate.peak_as_of` is the PEAK report date THIS session's own
    receipts were seeded from (set at seed and at journey.reseed_peak — never by a
    GET). `peak_report_as_of()` above is the book's own date, right now, across every
    session. An apply is reseeded only for the session that made it
    (routers/peak_pipeline.py's `_after_apply`); every other session keeps counting its
    old report until it resets or reseeds, so the two dates can differ for as long as
    that session lives — and, unfixed, a reader of that session sees a complete-looking
    0 that reads as nobody paid.

    Returns (session_as_of, note_or_None): the note is PEAK_REPORT_NOT_IN_SESSION,
    naming the book's date, when the two differ; None when they agree (including
    "neither has a report", None == None). A caller that gets a note back marks its
    figure indicative and serves `session_as_of` as its own `peak_report_as_of`, not
    the book's — the book's date names receipts this session does not hold."""
    book_as_of = peak_report_as_of()
    session_as_of = jstate.peak_as_of
    if session_as_of == book_as_of:
        return session_as_of, None
    return session_as_of, _note("PEAK_REPORT_NOT_IN_SESSION", as_of=book_as_of)


# `mom` and `paying_customers` below are whole-book / per-customer totals: they read
# every receipt in `jstate.receipts` directly (as `counted_receipts` units), never one
# invoice's receipts through `journey.invoice_receipts()`.

def _money_span(units, start, end):
    rows = units_in(units, start, end)
    sums = {line: Decimal("0") for line in RECEIPT_LINES}
    for u in rows:
        sums[LINE_OF_ENTITY[u["entity"]]] += u["amount"]
    out = {"start": str(start), "end": str(end)}
    out.update({line: _money(sums[line]) for line in RECEIPT_LINES})
    out["total"] = _money(sum(sums.values(), Decimal("0")))
    out["receipts"] = len(rows)
    out["peak_receipts"] = sum(1 for u in rows if u["source"] in PEAK_SOURCES)
    return out


def mom(business_date, units):
    """`units` is `counted_receipts(jstate)`: the whole book's receipts, each payment once."""
    (this_start, this_end), (last_start, last_end) = month_spans(business_date)
    this = _money_span(units, this_start, this_end)
    last = _money_span(units, last_start, last_end)
    keys = RECEIPT_LINES + ("total",)
    change = {k: _money(Decimal(this[k]) - Decimal(last[k])) for k in keys}
    change_pct = {k: _pct(this[k], last[k]) for k in keys}
    latest = _latest_receipt_on(units)
    notes = _empty_span_notes(units, (this, last), latest)
    if any(v is None for v in change_pct.values()):
        notes.append(_note("NO_BASE_FOR_PERCENT"))
    this_days, last_days = (this_end - this_start).days + 1, (last_end - last_start).days + 1
    if this_days != last_days:
        # Fix round 1 (minor): 31 Oct against 1-30 Sep compares 31 days with 30.
        notes.append(_note("SPANS_DIFFER_IN_LENGTH", this_days=this_days, last_days=last_days,
                           this_start=this["start"], this_end=this["end"],
                           last_start=last["start"], last_end=last["end"]))
    badges, as_of, indicative = _badge_notes(units, (this, last))
    notes.extend(badges)
    return dict(_definition("mom"), this_month=this, last_month=last, change=change, change_pct=change_pct,
                measure="cash_received", peak_report_as_of=as_of, latest_receipt_on=latest,
                indicative=indicative, empty=this["receipts"] == 0 and last["receipts"] == 0, notes=notes)


def _paying_span(units, start, end):
    rows = units_in(units, start, end)
    customers, unresolved = set(), 0
    for u in rows:
        found = journey.contract_by_uid(u["contract_uid"])
        if found:
            customers.add(found[0].uid)
        else:
            unresolved += 1
    return {"start": str(start), "end": str(end), "customers": len(customers), "receipts": len(rows),
            "unresolved_receipts": unresolved}


def paying_customers(period_start, period_end, units):
    """`units` is `counted_receipts(jstate)`; a folded payment is one receipt here."""
    prior_end = period_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=6)
    this = _paying_span(units, period_start, period_end)
    prior = _paying_span(units, prior_start, prior_end)
    latest = _latest_receipt_on(units)
    notes = _empty_span_notes(units, (this, prior), latest)
    change_pct = _pct(this["customers"], prior["customers"])
    if change_pct is None:
        notes.append(_note("NO_BASE_FOR_PERCENT"))
    unresolved = this["unresolved_receipts"] + prior["unresolved_receipts"]
    if unresolved:
        notes.append(_note("UNRESOLVED_RECEIPTS", n=unresolved))
    # Finding 4: the same partial receipts mom badges, so the same badge.
    badges, as_of, indicative = _badge_notes(units, (this, prior))
    notes.extend(badges)
    return dict(_definition("paying_customers"), this_period=this, prior_period=prior,
                change=this["customers"] - prior["customers"], change_pct=change_pct,
                latest_receipt_on=latest, peak_report_as_of=as_of, indicative=indicative,
                empty=this["receipts"] == 0 and prior["receipts"] == 0, notes=notes)


def _who(customer_uid, cs):
    customer = journey.customer_by_uid(customer_uid) if customer_uid else None
    case = cs.cases.get(customer_uid) if customer_uid else None
    return {"customer_uid": customer_uid,
            "display_name": customer.display_name if customer else None,
            "volt_id": case.get("volt_id") if case else None}


def _resolved(customer_uid):
    """The one customer key NPL rows are counted by: the journey customer uid, when it
    resolves in the book; else None. Never a case uid in its place (fix round 1, minor)."""
    return customer_uid if customer_uid and journey.customer_by_uid(customer_uid) is not None else None


def _status_events_in(cs, start, end):
    """PAYMENT_STATUS_SET events in the period, with the customer they belong to."""
    by_case_uid = {c["uid"]: c for c in cs.cases.values()}
    out = []
    for e in cs.events:
        if e.get("kind") != "PAYMENT_STATUS_SET" or not _inside(e.get("on"), start, end):
            continue
        case = by_case_uid.get(e.get("case_uid"))
        out.append((e, case["customer_uid"] if case else None))
    return out


def _declarations_in(jstate, start, end):
    """NPL declarations opened in the period, each with its resolved customer uid (or None)."""
    out = []
    for npl in jstate.npl_cases.values():
        if not _inside(npl.get("declared_on"), start, end):
            continue
        jcase = jstate.cases.get(npl.get("case_uid"))
        out.append((npl, _resolved(jcase.get("customer_uid") if jcase else None)))
    return out


def npl_movement(period_start, period_end, cs, jstate):
    rows = []
    entered, left, declared, changed_in = set(), set(), set(), set()
    by_change_in = by_change_out = by_declaration = unresolved = 0
    for e, customer_uid in _status_events_in(cs, period_start, period_end):
        into = e.get("code") == "NPL" and e.get("from") != "NPL"
        out = e.get("from") == "NPL" and e.get("code") != "NPL"
        if not (into or out):
            continue
        key = _resolved(customer_uid)
        if key is None:
            unresolved += 1
            continue
        if into:
            by_change_in += 1
            entered.add(key)
            changed_in.add(key)
        else:
            by_change_out += 1
            left.add(key)
        rows.append(dict(_who(key, cs), direction="ENTERED" if into else "LEFT", basis="STATUS_CHANGE",
                         on=_day(e.get("on")), **{"from": e.get("from")}, to=e.get("code"), by=e.get("by"),
                         reason=without_typed_numbers(e.get("reason")), npl_uid=None))
    for npl, key in _declarations_in(jstate, period_start, period_end):
        if key is None:
            unresolved += 1
            continue
        by_declaration += 1
        entered.add(key)
        declared.add(key)
        rows.append(dict(_who(key, cs), direction="ENTERED", basis="DECLARATION",
                         on=_day(npl.get("declared_on")), **{"from": None}, to="NPL", by=npl.get("declared_by"),
                         reason=None, npl_uid=npl.get("uid")))
    notes = [_note("EVENT_LOG_FROM_SYSTEM_START"), _note("NO_NPL_EXIT_RECORD")]
    both = len(declared & changed_in)
    if both:
        notes.append(_note("DECLARATION_ALSO_STATUS_CHANGE", n=both))
    in_and_out = len(entered & left)
    if in_and_out:
        notes.append(_note("ENTERED_AND_LEFT", n=in_and_out))
    if unresolved:
        notes.append(_note("NPL_ROWS_UNRESOLVED", n=unresolved))
    if not rows:
        notes.append(_note("NO_NPL_MOVEMENT_IN_PERIOD"))
    return dict(_definition("npl_movement"),
                period={"start": str(period_start), "end": str(period_end)},
                entered={"by_status_change": by_change_in, "by_declaration": by_declaration, "customers": len(entered)},
                left={"by_status_change": by_change_out, "customers": len(left)},
                rows=rows, empty=not rows, notes=notes)


def _blank_lines():
    return {line: Decimal("0") for line in ARREARS_LINES}


def _served_lines(sums, customers):
    out = {line: _money(sums[line]) for line in ARREARS_LINES}
    out["total"] = _money(sum(sums.values(), Decimal("0")))
    out["customers"] = customers
    return out


def arrears_split(business_date, period_start, period_end, items, cs, jstate, od02_receipt_customers):
    """True arrears vs arrears held on the company side, per line, over the customers in
    collection (the portfolio's own unit). Only customers with arrears above zero are
    counted; `total` equals the sum of the items' aggregate_overdue.

    `od02_receipt_customers` comes from reports._allocation_hold_in_period over the
    counted units of the 7-day period only (fix round 2: the same `units_in` cash_in
    reads, so a slip folded into an allocated PEAK payment holds nobody) — the window
    the definition, the unit line and the OD02_OPEN note name (fix round 1, finding 3)."""
    from . import main
    open_case_issue = {i["customer_uid"] for i in cs.issues.values() if i.get("status") == "OPEN"}
    sums = {"true": _blank_lines(), "held": _blank_lines()}
    counts = {"true": 0, "held": 0}
    held_by = {"od02_allocation": 0, "service_issue": 0}
    held_rows = []
    for item in items:
        customer = journey.customer_by_uid(item["customer"]["uid"])
        if customer is None:
            continue
        lines = _blank_lines()
        for contract in customer.contracts:
            lines[LINE_OF_ENTITY.get(contract.entity, "unrouted")] += main._contract_view(contract)[3].cumulative_arrears
        if sum(lines.values(), Decimal("0")) <= 0:
            continue
        case = cs.cases.get(customer.uid) or {}
        reasons = []
        if customer.uid in od02_receipt_customers:
            reasons.append("OD02_RECEIPT_IN_PERIOD")
        if case.get("allocation_hold"):
            reasons.append("OD02_CASE_HOLD")
        if customer.uid in open_case_issue:
            reasons.append("SERVICE_ISSUE_CASE")
        if journey.open_issue_for(jstate, customer.uid):
            reasons.append("SERVICE_ISSUE_JOURNEY")
        side = "held" if reasons else "true"
        counts[side] += 1
        for line in ARREARS_LINES:
            sums[side][line] += lines[line]
        if reasons:
            held_by["od02_allocation"] += any(r.startswith("OD02_") for r in reasons)
            held_by["service_issue"] += any(r.startswith("SERVICE_ISSUE_") for r in reasons)
            row = dict(_who(customer.uid, cs), reasons=reasons)
            row.update({line: _money(lines[line]) for line in ARREARS_LINES})
            row["total"] = _money(sum(lines.values(), Decimal("0")))
            held_rows.append(row)
    held_rows.sort(key=lambda r: (-Decimal(r["total"]), r["customer_uid"]))
    total = {line: sums["true"][line] + sums["held"][line] for line in ARREARS_LINES}
    start, end = str(period_start), str(period_end)
    notes = []
    if not (counts["true"] or counts["held"]):
        notes.append(_note("NO_ARREARS"))
    if held_by["od02_allocation"]:
        notes.append(_note("OD02_OPEN", n=held_by["od02_allocation"], start=start, end=end))
    if held_by["service_issue"]:
        notes.append(_note("TWO_ISSUE_REGISTERS"))
    return dict(_definition("arrears_split"), as_of=str(business_date),
                unit="customers in collection with arrears above zero, on the business date; an unallocated receipt "
                     "holds its customer only when dated %s to %s (the 7-day period)" % (start, end),
                unit_en="Customers in collection with arrears above zero on the business date; an unallocated receipt "
                        "holds its customer only when dated %s to %s (the 7-day period)" % (start, end),
                unit_th="นับลูกค้าที่อยู่ในการติดตามและมียอดค้างมากกว่า 0 ณ วันทำการ · ใบเสร็จที่ยังไม่จัดสรร "
                        "ทำให้นับเป็นยอดพักเฉพาะใบที่ลงวันที่ %s ถึง %s (ช่วง 7 วัน)" % (start, end),
                true=_served_lines(sums["true"], counts["true"]),
                held=_served_lines(sums["held"], counts["held"]),
                total=_served_lines(total, counts["true"] + counts["held"]),
                held_by=held_by, held_rows=held_rows, pending_decision="OD-02",
                # Held arrears under OD-02 still carry money already received.
                indicative=bool(held_by["od02_allocation"]),
                empty=not (counts["true"] or counts["held"]), notes=notes)


def status_changes(period_start, period_end, cs, jstate):
    events = _status_events_in(cs, period_start, period_end)
    rows = []
    for raw, customer_uid in reversed(events):
        e = event_without_typed_numbers(raw)          # B13b: reason and ended.reason are typed
        rows.append(dict(_who(customer_uid, cs), case_uid=e.get("case_uid"), on=_day(e.get("on")),
                         **{"from": e.get("from")}, to=e.get("code"), system=e.get("system"), by=e.get("by"),
                         by_system=e.get("by") == "SYSTEM", reason=e.get("reason"), ended=e.get("ended")))
    by_system = sum(1 for r in rows if r["by_system"])
    # Fix round 1 (minor): a declaration in the period that the system did not follow
    # with its own PAYMENT_STATUS_SET to NPL (e.g. a case already NPL when first seen)
    # is not on this list; say how many, so the list is not read as complete.
    followed = [(_resolved(customer_uid), _day(e.get("on"))) for e, customer_uid in events
                if e.get("by") == "SYSTEM" and e.get("code") == "NPL"]
    without_event = sum(
        1 for npl, key in _declarations_in(jstate, period_start, period_end)
        if key is not None and not any(who == key and on >= _day(npl.get("declared_on")) for who, on in followed))
    notes = [_note("EVENT_LOG_FROM_SYSTEM_START")]
    if without_event:
        notes.append(_note("DECLARATION_WITHOUT_EVENT", n=without_event))
    if not rows:
        notes.append(_note("NO_STATUS_CHANGES_IN_PERIOD"))
    return dict(_definition("status_changes"),
                period={"start": str(period_start), "end": str(period_end)},
                rows=rows, order="newest first", count=len(rows), by_system=by_system,
                by_person=len(rows) - by_system, empty=not rows, notes=notes)


def build(business_date, period_start, period_end, items, cs, jstate, od02_receipt_customers, units=None):
    """The five blocks, keyed as reports.weekly() serves them. `units` lets
    reports.weekly() hand in the `counted_receipts(jstate)` its `cash_in` already used,
    so the three receipt figures read one list."""
    units = counted_receipts(jstate) if units is None else units
    return {
        "mom": mom(business_date, units),
        "paying_customers": paying_customers(period_start, period_end, units),
        "npl_movement": npl_movement(period_start, period_end, cs, jstate),
        "arrears_split": arrears_split(business_date, period_start, period_end, items, cs, jstate,
                                       od02_receipt_customers),
        "status_changes": status_changes(period_start, period_end, cs, jstate),
    }
