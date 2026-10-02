"""REQ-KPI-017 — two collected-amount indicators, and the shortfall bands.

Round 5, rulings 78-83. Leg F built and drove both indicators and all four bands
in a scratch copy before this file existed (docs/design/round-5/kpi/F-api.md); this
module is leg C's build of it, adjusted by rulings 81-83, which were recorded
after leg F reported and changed three things it specified:

  ruling 81 — cash_received is served (store, receipt count, amount) but nothing
              here decides whether a caller draws it as a bar; that is a screen
              decision outside this module's job.
  ruling 82 — portfolio and officer only. There is no team, and `product`
              (LEASE/CASH) is refused as a stand-in for one — "a fixture
              coincidence dressed as an org chart" (leg F, ledger :729-731).
              `team` is carried on the face of every response (meta), not
              silently accepted and not silently dropped.
  ruling 83 — band 2 (closing / pending cancellation) is `amount: null` with its
              reason, never `0` and never the badged proxy leg F specified —
              "a number nobody can tie out is worse than a stated gap."

REQ-KPI-017 refuses one function with a `measure` parameter by name. In this
codebase the shape refuses itself anyway: the two indicators read different
collections (`journey.receipts` vs `contract.instalments`), filter on different
date fields (`received_on` vs `due_date`), and produce different key sets. There
is no shared body to factor out, so there are two functions, not one with a flag.

Every contract read below goes through `cases.contract_field_of` — never a bare
`contract.<field>` — because `status`, `fee_state` and `instalments` are all
session-scoped overlays (ruling 43's class; ruling 49 added `instalments` for a
restructure). Reading the raw attribute would let one tester's restructure or
fee-state change leak into another tester's KPI figure.
"""
import calendar
import re
from decimal import Decimal, InvalidOperation

from . import cases as cases_domain
from . import journey
from . import weekly_figures
from .config import settings

ZERO = Decimal("0.00")

# R79-D: two functions, no shared body — see the module docstring.
MEASURES = ("cash_received", "due_month")

MEASURE_LABEL_TH = {
    "cash_received": "เงินสดรับตามเดือนที่เงินเข้า",
    "due_month": "ยอดชำระตามเดือนที่ครบกำหนด",
}
MEASURE_LABEL_EN = {
    "cash_received": "Cash received, by the month the money came in",
    "due_month": "Payments due, by the month they fell due",
}

MEASURE_BASIS = {
    "cash_received": "journey.receipts.received_on",
    "due_month": "contract.instalments.due_date",
}

# REQ-KPI-007 / D7 (spec-deltas-v21-v24.md:230-236), not cited in the round brief
# and not optional: the collection denominator excludes contracts that cannot be
# worked — service-held, permit-held, already closed. They stay visible: a held
# contract reappears as band 1; a closed one is simply out of collection, the same
# population `today.py:214` and `reports.officers()` already draw from.
HELD_FEE_STATES = ("SERVICE_HOLD_FAULT_CONFIRMED", "PERMIT_HOLD")
CLOSED_STATUS = "CLOSED"
# 2026-09-20 (Closed/Terminated ruling): an ended contract leaves the denominator for
# the same reason a closed one does — nobody is collecting on it — while the two keep
# their own names in every report that lists statuses.
TERMINATED_STATUS = "TERMINATED"
EXCLUDED_STATUSES = (CLOSED_STATUS, TERMINATED_STATUS)

SCOPES = ("portfolio", "officer")

# Ruling 82: named on the face of every response rather than silently accepted
# (R5-F09 drove `{"team:lease": "300000"}` to a 200 with no figure, ever) or
# silently dropped. `officers.registry()` returns {uid, display_name_th, role,
# roles} — no team field exists anywhere in this product, and none is invented.
TEAM_NOTE_TH = ("ระบบนี้ไม่มีข้อมูลทีมของเจ้าหน้าที่ "
                "จึงยังไม่มีสรุปผลระดับทีม — มีเฉพาะพอร์ตทั้งหมดและรายเจ้าหน้าที่")
TEAM_NOTE_EN = ("This system holds no officer team data, so there is no team-level summary — "
                "only the whole portfolio and each officer")

# Ruling 83: the reason lives beside the null, not merely a "0" that would fold
# silently into band 4.
CLOSING_UNCOMPUTABLE_NOTE_TH = (
    "ไม่สามารถวัดได้ — รายการยกเลิก (cancellations) ที่มีอยู่ไม่มีการเชื่อมกับสัญญา (contract_uid) "
    "จึงระบุแยกเป็นสัญญาไม่ได้ในตอนนี้"
)
CLOSING_UNCOMPUTABLE_NOTE_EN = (
    "Cannot be measured — the cancellations on record are not linked to a contract, "
    "so they cannot be told apart by contract yet"
)

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def business_month(business_date=None):
    bd = business_date or settings.business_date
    return "%04d-%02d" % (bd.year, bd.month)


def parse_month(month):
    """Raises ValueError on anything that is not YYYY-MM — a caller passing a
    weekly label ("2026-10-17..2026-10-23") by mistake must be refused, not
    silently misread."""
    if not month or not _MONTH_RE.match(month):
        raise ValueError(month)
    y, m = month.split("-")
    return int(y), int(m)


def _money(x):
    if x is None:
        return None
    return str(Decimal(str(x)).quantize(Decimal("0.01")))


def _status_of(contract):
    return cases_domain.contract_field_of(contract, "status")


def _fee_state_of(contract):
    return cases_domain.contract_field_of(contract, "fee_state")


def _lines_of(contract):
    return cases_domain.contract_field_of(contract, "instalments")


def _month_lines(contract, year, month):
    return [ln for ln in _lines_of(contract)
            if ln.is_active_regular and ln.due_date.year == year and ln.due_date.month == month]


def _line_paid(line):
    return line.paid_principal + line.paid_interest + line.paid_fee


def _line_shortfall(line):
    return max(line.outstanding_amount, ZERO)


def _population(officer=None):
    """Every (customer, case, contract) in the book, optionally narrowed to one
    officer's desk — read through the SAME session-scoped case store
    `today.build()` and `reports.officers()` already use (`case["officer_uid"]`,
    reassignment-aware since ruling 40's overlay), never `customer.officer`
    directly."""
    cs = cases_domain.for_current()
    for customer in journey.book_customers():
        case = cs.cases.get(customer.uid)
        if case is None:
            continue
        if officer and case["officer_uid"] != officer:
            continue
        for contract in customer.contracts:
            yield customer, case, contract


def target_key(measure, scope, officer_uid):
    if scope == "officer":
        return "%s:officer:%s" % (measure, officer_uid)
    return "%s:portfolio" % measure


def validate_target_key(key):
    """<measure>:portfolio or <measure>:officer:<uid>. Anything else is refused
    BY NAME where the reason is worth stating — contact rate is a denominator
    concept only (REQ-KPI-017), never a target; team does not exist (ruling 82)
    and must not be accepted the way `PUT …/weekly/{period}/targets` accepts any
    key today (R5-F09). Returns (ok, code, (message_th, message_en) or None)."""
    parts = (key or "").split(":")
    measure = parts[0] if parts else ""
    if measure == "contact_rate":
        return False, "not_targetable", ("อัตราการติดต่อเป็นตัวหารเพื่อดูภาพรวม ไม่ใช่ตัวเลขที่ตั้งเป้าได้",
                                         "The contact rate is a denominator for the overall picture, not a figure a target can be set on")
    if len(parts) >= 2 and parts[1] == "team":
        return False, "team_not_supported", (TEAM_NOTE_TH, TEAM_NOTE_EN)
    if measure not in MEASURES:
        return False, "unknown_measure", ("ไม่รู้จักตัวชี้วัดนี้ ใช้ cash_received หรือ due_month",
                                          "This indicator is not known; use cash received or payments due")
    if len(parts) == 2 and parts[1] == "portfolio":
        return True, None, None
    if len(parts) == 3 and parts[1] == "officer" and parts[2]:
        return True, None, None
    return False, "invalid_key", ("รูปแบบคีย์เป้าหมายไม่ถูกต้อง ใช้ <measure>:portfolio หรือ <measure>:officer:<uid>",
                                  "The target key is not in a known format; use <measure>:portfolio or <measure>:officer:<uid>")


def validate_target_value(raw):
    """Found live by a concurrent design leg driving this route (C-4,
    BLOCKER-class), reproduced independently before this fix: the write
    validated the KEY and not the VALUE. `PUT {"due_month:portfolio": null}`
    stored the literal string `"None"`; a comma-formatted string (`"400,000"` —
    what a manager actually types) does the same. Both crash the NEXT `GET` with
    `decimal.InvalidOperation` — a 500 that PERSISTS in the session store,
    because the bad value is already saved by the time anyone reads it back.

    Returns `(ok, normalized_value_or_None, (message_th, message_en) or None)`. **The clear
    transition (`""`) is NOT handled here** — it is not a value at all, it is an
    instruction to remove the key, and the caller (the PUT route) handles it one
    level up, before this function is ever called, so REQ-KPI-020's "no target
    means no achievement figure" keeps working."""
    if raw is None:
        return False, None, ("ต้องระบุตัวเลข หรือส่งค่าว่าง (\"\") เพื่อล้างเป้า",
                             "Enter a number, or leave it empty to clear the target")
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return False, None, ("ต้องเป็นตัวเลข เช่น 400000 (ห้ามมีเครื่องหมายจุลภาคหรือตัวอักษร)",
                             "Must be a number such as 400000 (no commas or letters)")
    if not d.is_finite():
        return False, None, ("ต้องเป็นตัวเลขที่จำกัด", "Must be a finite number")
    return True, str(d.quantize(Decimal("0.01"))), None


def _target_for(month, key):
    # Lazy import: reports.py never needs to import this module (weekly()'s own
    # stamp is a two-line literal, not a call in here), so this is the only edge
    # and it stays one-directional.
    from . import reports as reports_domain
    stored = reports_domain.TARGETS.get(month) or {}
    return stored.get(key)


def month_target(month, officer=None):
    """The cash_received target a manager saved for a calendar month, at the
    portfolio scope (or one officer's), or None when nobody saved one.

    Delta-100 D2e: the Overview's five monthly bars each carry this target so the
    screen can draw attainment; it reads the same `reports.TARGETS` namespace the
    collection targets route writes and `cash_received` itself reads, so the trend
    and the indicator can never disagree. None is the honest state — never 0."""
    return _target_for(month, target_key("cash_received", "officer" if officer else "portfolio", officer))


def _attainment(actual, target):
    """Returns `(attainment_pct, attainment_note_th, attainment_note_en, attainment_bar_pct)`.
    `attainment_pct` is the true figure, unbounded (a manager overshooting a
    target should still read the real number). `attainment_bar_pct` is the same
    figure clamped to [0, 100] — a concurrent design leg drove `attainment_pct`
    to `"280498.0"` at a token `target=100` and found the uncapped figure would
    render a fill 2,805 tracks wide (C-1); serving the clamp here means the
    screen draws a bar without doing arithmetic (`api.js:1-4`)."""
    if not target:
        return (None, "ยังไม่มีเป้าที่ผู้จัดการตั้งไว้ จึงยังไม่มีตัวเลขผลสำเร็จ",
                "No target has been set by a manager yet, so there is no achievement figure", None)
    t = Decimal(str(target))
    if t == ZERO:
        return (None, "เป้าที่ตั้งไว้เป็นศูนย์ จึงยังไม่มีตัวเลขผลสำเร็จที่มีความหมาย",
                "The target set is zero, so there is no meaningful achievement figure", None)
    pct = (Decimal(str(actual)) / t * 100).quantize(Decimal("0.1"))
    bar_pct = str(max(Decimal("0.0"), min(Decimal("100.0"), pct)))
    return str(pct), None, None, bar_pct


def _orphan_cancellations():
    jstate = journey.for_current()
    return sum(1 for c in jstate.cancellations.values() if not c.get("contract_uid"))


def _band_bar_pct(amount, largest):
    """C-1: a band's fill width as a percentage of the LARGEST band amount in
    the list — never of the shortfall, because band 1 sits outside the
    denominator (D7) and a share of the shortfall would compare two different
    populations. `None` when `amount` is `None` (band 2 — a bar with no width is
    not the same claim as a bar the client had to compute as zero)."""
    if amount is None:
        return None
    if largest <= ZERO:
        return "0.0"
    return str((amount / largest * 100).quantize(Decimal("0.1")))


def _month_progress_note_th(year, month, bd):
    """Part of C-3: `business_date` (2026-10-23) sitting inside a queried month
    (2026-10) says nothing about whether that month is still running — a figure
    read from a month with 8 days left can still move, and nothing on the
    payload said so. Computed here, not in the client (`api.js:1-4`)."""
    last_day = calendar.monthrange(year, month)[1]
    if (bd.year, bd.month) == (year, month):
        remaining = last_day - bd.day
        if remaining > 0:
            return "เดือนนี้ยังไม่ปิด เหลืออีก %d วัน ตัวเลขนี้ยังเปลี่ยนได้จนกว่าจะครบเดือน" % remaining
        return "วันนี้เป็นวันสุดท้ายของเดือนนี้ ตัวเลขยังเปลี่ยนได้จนกว่าจะสิ้นสุดวัน"
    if (year, month) < (bd.year, bd.month):
        return "เดือนนี้ปิดแล้ว ตัวเลขนี้ไม่เปลี่ยนอีก"
    return "เดือนนี้ยังไม่เริ่ม ตัวเลขที่แสดงคือศูนย์ตามข้อมูลที่มีอยู่ในขณะนี้"


def _month_progress_note_en(year, month, bd):
    last_day = calendar.monthrange(year, month)[1]
    if (bd.year, bd.month) == (year, month):
        remaining = last_day - bd.day
        if remaining > 0:
            return "This month is still open, %d day(s) left; the figure can change until the month ends" % remaining
        return "Today is the last day of this month; the figure can change until the day ends"
    if (year, month) < (bd.year, bd.month):
        return "This month is closed; the figure will not change"
    return "This month has not started; the figure shows zero from the data on record now"


# ESC-3 / the coordinator's correction: ruling 83's own illustrative "฿525,437.00
# across 74 contracts" pairs indicator.contracts (the DESK's whole population —
# every contract this officer carries) with a band amount that in fact sits on
# only 5 of those 74. The two counts are different denominators and must never
# be read as one number's own count. Stated on the face so nobody repeats the
# pairing the way this leg's own first C-backend.md draft did.
CONTRACTS_NOTE_TH = (
    "จำนวนสัญญาใน indicator.contracts คือสัญญาทั้งหมดของเจ้าหน้าที่คนนี้ (หรือทั้งพอร์ต) "
    "ส่วนจำนวนสัญญาใน bands[].contracts คือเฉพาะสัญญาที่อยู่ในแถบนั้นแถบเดียว "
    "ตัวเลขทั้งสองนับคนละฐาน ห้ามนำมาคู่กันเป็นตัวเลขเดียว"
)
CONTRACTS_NOTE_EN = (
    "The contract count on the indicator is every contract this officer (or the portfolio) carries; "
    "the contract count on a band is only the contracts in that one band. "
    "The two count different bases and must never be read as one number"
)


def _meta(measure, month, scope, officer_uid):
    bd = settings.business_date
    year, mon = parse_month(month)
    return {
        "measure": measure,
        "measures_available": list(MEASURES),
        "scopes_available": list(SCOPES),           # ruling 82
        "team_note_th": TEAM_NOTE_TH,                # ruling 82 — carried, not silent
        "team_note_en": TEAM_NOTE_EN,
        "business_date": str(bd),
        "month": month,
        "month_progress_note_th": _month_progress_note_th(year, mon, bd),
        "month_progress_note_en": _month_progress_note_en(year, mon, bd),
        "scope": scope,
        "officer_uid": officer_uid,
        "denominator_excludes": list(HELD_FEE_STATES) + list(EXCLUDED_STATUSES),
        "population_note_th": "ไม่รวมสัญญาที่ปิดแล้วหรือถูกยุติสัญญา และไม่รวมสัญญาที่ติดปัญหาบริการหรือรออนุญาต",
        "population_note_en": "Closed and terminated contracts, and contracts held for a service issue or a permit, are excluded",
        "contracts_note_th": CONTRACTS_NOTE_TH,
        "contracts_note_en": CONTRACTS_NOTE_EN,
    }


def cash_received(month=None, officer=None):
    """R79-C: `reports.py:177-181`'s `cash_in` resembles this and is not it — weekly
    not monthly, split by legal entity not by scope, stamped with nothing. This
    reads the same store (`journey.receipts`) on the actual timing rule REQ-KPI-017
    asks for (received_on inside the month), scoped to portfolio or one officer's
    contracts, and states its own smallness rather than implying a bar's worth of
    data (ruling 81)."""
    bd = settings.business_date
    month = month or business_month(bd)
    year, mon = parse_month(month)
    scope = "officer" if officer else "portfolio"

    allowed_uids = None
    if officer:
        allowed_uids = {contract.uid for _c, _k, contract in _population(officer=officer)}

    # B13 fix round 2 (controller ruling): this figure and the weekly report's `mom` are
    # both labelled cash_received, so they read ONE list — weekly_figures.counted_receipts,
    # where a payment on record twice (a receipt recorded here and the PEAK report receipt
    # for the same invoice) is one unit. Before, the same October read 16,798.00 on 2
    # receipts here and 8,399.00 on 1 in `mom`. A folded payment's allocation is its
    # PEAK side's (weekly_figures.unit_is_allocated), the same rule the OD-02 hold reads.
    jstate = journey.for_current()
    all_receipts = weekly_figures.counted_receipts(jstate)
    if allowed_uids is not None:
        all_receipts = [u for u in all_receipts if u["contract_uid"] in allowed_uids]
    month_receipts = [u for u in all_receipts if (u["received_on"] or "")[:7] == month]

    actual = sum((u["amount"] for u in month_receipts), ZERO)
    all_time_amount = sum((u["amount"] for u in all_receipts), ZERO)
    unallocated = [u for u in month_receipts if not weekly_figures.unit_is_allocated(u)]
    month_span = {"start": "%s-01" % month, "end": "%s-%02d" % (month, calendar.monthrange(year, mon)[1])}
    overlap = weekly_figures.overlap_note(all_receipts, (month_span,))
    # B13b: a receipt flagged invoice_moved_to_other_customer / invoice_owner_unknown
    # counted in the month may be the same money as another customer's PEAK receipt;
    # named and badged exactly as weekly mom does (weekly_figures.flagged_note).
    flagged = weekly_figures.flagged_note(all_receipts, month_span)
    # Final fix F-R2: this session's own receipts may lag the book's newest applied
    # PEAK report (an apply is reseeded only for the session that made it) — see
    # weekly_figures.peak_session_gap.
    peak_report_as_of, peak_gap_note = weekly_figures.peak_session_gap(jstate)

    key = target_key("cash_received", scope, officer)
    target = _target_for(month, key)
    attainment_pct, attainment_note, attainment_note_en, attainment_bar_pct = _attainment(actual, target)

    return {
        "indicator": {
            "measure": "cash_received",
            "measure_label_th": MEASURE_LABEL_TH["cash_received"],
            "measure_label_en": MEASURE_LABEL_EN["cash_received"],
            "month": month,
            "scope": scope,
            "officer_uid": officer,
            "actual": _money(actual),
            "receipts": len(month_receipts),
            "receipts_all_time": len(all_receipts),
            "receipts_all_time_amount": _money(all_time_amount),
            "unallocated_receipts": len(unallocated),
            # OD-02 stated, not swallowed — reports.py:208-209's own idiom.
            "unallocated_pending_decision": "OD-02" if unallocated else None,
            "basis": MEASURE_BASIS["cash_received"],
            # OD-02 qualifies allocation, not provenance, so this stays False — except
            # when a payment on record twice touches the month (fix round 2), a flagged
            # receipt is counted in it (B13b), or this session's own PEAK report lags
            # the book's (final fix F-R2): then the figure is indicative and says why.
            "indicative": overlap is not None or flagged is not None or peak_gap_note is not None,
            "overlap_note": overlap["en"] if overlap else None,
            "overlap_note_th": overlap["th"] if overlap else None,
            "overlap_note_en": overlap["en"] if overlap else None,
            "flagged_note": flagged["en"] if flagged else None,
            "flagged_note_th": flagged["th"] if flagged else None,
            "flagged_note_en": flagged["en"] if flagged else None,
            "peak_report_as_of": peak_report_as_of,
            "peak_report_not_in_session_note": peak_gap_note["en"] if peak_gap_note else None,
            "peak_report_not_in_session_note_th": peak_gap_note["th"] if peak_gap_note else None,
            "peak_report_not_in_session_note_en": peak_gap_note["en"] if peak_gap_note else None,
            "bank_reconciled": None,           # R5-F14 — no bank feed exists anywhere in this product
            "bank_reconciliation_note_th": "ยังไม่มีการกระทบยอดกับธนาคารหรือฝ่ายบัญชีในระบบนี้",
            "bank_reconciliation_note_en": "Nothing here has been reconciled with the bank or accounting yet",
            "target": _money(target) if target else None,
            "target_key": key,
            "attainment_pct": attainment_pct,
            "attainment_bar_pct": attainment_bar_pct,     # C-1 — capped [0,100], never client-computed
            "attainment_note_th": attainment_note,
            "attainment_note_en": attainment_note_en,
        },
        "shortfall": None,          # R79-D: no scheduled amount, nothing to decompose
        "meta": _meta("cash_received", month, scope, officer),
    }


def due_month(month=None, officer=None):
    """R79-A/B: the attribution REQ-KPI-017 asks for is intrinsic to the schedule
    row (due_date, principal/interest/fee, paid_principal/interest/fee) — it does
    not need an allocation and is not blocked by OD-02. This is the performance
    figure (D14) and the only one of the two that decomposes into the shortfall
    bands (ruling 80), because only it has a scheduled amount to fall short of.

    `indicative: true` always (R5-F16): `book.py:145` derives `paid_through` as
    `due_by − missed`, where `missed` counts LATE cells in the SHEET's own grid —
    the sheet's statement walked back, not a record of cash. L4 requires that
    badged wherever this figure renders."""
    bd = settings.business_date
    month = month or business_month(bd)
    year, mon = parse_month(month)
    scope = "officer" if officer else "portfolio"

    cs = cases_domain.for_current()
    promised_customers = {p["customer_uid"] for p in cs.ptps.values() if p["status"] == "OPEN"}

    contracts_total = 0
    lines_n = 0
    held_amount = ZERO
    held_uids = set()
    denom_scheduled = denom_paid = denom_shortfall = ZERO
    promised_amount = ZERO
    promised_uids = set()
    unworked_uids = set()

    for customer, _case, contract in _population(officer=officer):
        if _status_of(contract) in EXCLUDED_STATUSES:
            continue
        contracts_total += 1
        lines = _month_lines(contract, year, mon)
        if not lines:
            continue
        scheduled = sum((ln.total_amount for ln in lines), ZERO)
        paid = sum((_line_paid(ln) for ln in lines), ZERO)
        shortfall = sum((_line_shortfall(ln) for ln in lines), ZERO)
        lines_n += len(lines)

        if _fee_state_of(contract) in HELD_FEE_STATES:
            # Band 1 (ruling 80/R80-A): out of the denominator entirely — D7's
            # "excludes but does not hide" — so this contract's money is NOT part
            # of denom_shortfall below; it is reported only on its own line.
            held_amount += shortfall
            if shortfall > ZERO:
                held_uids.add(contract.uid)
            continue

        denom_scheduled += scheduled
        denom_paid += paid
        denom_shortfall += shortfall
        if shortfall <= ZERO:
            continue
        if customer.uid in promised_customers:
            promised_amount += shortfall
            promised_uids.add(contract.uid)
        else:
            unworked_uids.add(contract.uid)

    # Ruling 83 / band 2: NOT computed — no contract state exists for "closing or
    # pending cancellation", and 3 of 3 cancellations carry contract_uid: null with
    # no join key (F-api.md §5.2). The badged proxy leg F specified is refused by
    # name in ruling 83 ("a number nobody can tie out is worse than a stated gap"),
    # so nothing here estimates it. Band 4 is therefore the residual of ONLY the
    # bands that ARE computed (band 3), never band 2 — its own note says so, so a
    # reviewer knows it may include contracts that are actually closing.
    unworked_amount = denom_shortfall - promised_amount

    key = target_key("due_month", scope, officer)
    target = _target_for(month, key)
    attainment_pct, attainment_note, attainment_note_en, attainment_bar_pct = _attainment(denom_paid, target)

    # C-1: bar widths are a share of the LARGEST band amount, never of the
    # shortfall (band 1 sits outside the denominator — see _band_bar_pct).
    largest_band_amount = max((a for a in (held_amount, promised_amount, unworked_amount)), default=ZERO)

    return {
        "indicator": {
            "measure": "due_month",
            "measure_label_th": MEASURE_LABEL_TH["due_month"],
            "measure_label_en": MEASURE_LABEL_EN["due_month"],
            "month": month,
            "scope": scope,
            "officer_uid": officer,
            "actual": _money(denom_paid),
            "scheduled": _money(denom_scheduled),
            "shortfall": _money(denom_shortfall),
            "lines": lines_n,
            "contracts": contracts_total,
            "basis": MEASURE_BASIS["due_month"],
            "indicative": True,                     # L4 / R5-F16 — always, not conditionally
            "provenance_th": "คำนวณจากตารางผ่อนชำระ (paid_through เทียบกับงวดที่ครบกำหนด) "
                             "ไม่ใช่จากใบเสร็จรับเงินโดยตรง",
            "provenance_en": "Worked out from the instalment schedule (paid through against the instalments due), "
                             "not from receipts directly",
            "target": _money(target) if target else None,
            "target_key": key,
            "attainment_pct": attainment_pct,
            "attainment_bar_pct": attainment_bar_pct,     # C-1 — capped [0,100], never client-computed
            "attainment_note_th": attainment_note,
            "attainment_note_en": attainment_note_en,
        },
        "shortfall": {
            "bands": [
                {
                    "code": "held", "label_th": "ติดปัญหาบริการหรือรออนุญาต",
                    "label_en": "Held for a service issue or a permit",
                    "amount": _money(held_amount), "contracts": len(held_uids),
                    "bar_pct": _band_bar_pct(held_amount, largest_band_amount),
                    "basis": "contract.fee_state in (SERVICE_HOLD_FAULT_CONFIRMED, PERMIT_HOLD); "
                            "excluded from the denominator",
                    # Part of C-3: band 1's out-of-denominator status, in Thai on its own row.
                    "note_th": "อยู่นอกฐานคำนวณส่วนต่าง (shortfall) เพราะติดปัญหาบริการหรือรออนุญาตอยู่ "
                              "จึงไม่ถูกนับรวมกับสามแถบด้านล่าง",
                    "note_en": "Outside the shortfall base because it is held for a service issue or a permit, "
                               "so it is not added to the three bands below",
                },
                {
                    # Ruling 83 build law #1: null WITH ITS REASON, never 0.
                    "code": "closing", "label_th": "สัญญากำลังปิดหรือรอยกเลิก",
                    "label_en": "Contract closing or awaiting cancellation",
                    "amount": None, "contracts": None, "bar_pct": None, "basis": None,
                    "note_th": CLOSING_UNCOMPUTABLE_NOTE_TH,
                    "note_en": CLOSING_UNCOMPUTABLE_NOTE_EN,
                },
                {
                    "code": "promised", "label_th": "อยู่ระหว่างนัดชำระ", "label_en": "Promise to pay open",
                    "amount": _money(promised_amount), "contracts": len(promised_uids),
                    "bar_pct": _band_bar_pct(promised_amount, largest_band_amount),
                    "basis": "customer holds an OPEN promise-to-pay (cases.ptps)",
                    "note_th": None,
                },
                {
                    # Ruling 83 build law #2: contracts always travels beside amount.
                    "code": "unworked", "label_th": "ยังไม่ได้ติดตาม", "label_en": "Not yet worked",
                    "amount": _money(unworked_amount), "contracts": len(unworked_uids),
                    "bar_pct": _band_bar_pct(unworked_amount, largest_band_amount),
                    "basis": "the residual after held (out of denominator) and promised; "
                            "closing is not computed and may be included here",
                    # C-2, MAJOR (found live by a concurrent design leg): this basis was
                    # English-only. The most consequential figure on the screen needs its
                    # caveat in the language the reader works in, not only in the audit trail.
                    "note_th": "ตัวเลขนี้อาจรวมสัญญาที่กำลังปิดหรือรอยกเลิกอยู่ด้วย เพราะยังแยกรายการนั้นไม่ได้ "
                              "(ดูแถบ \"สัญญากำลังปิดหรือรอยกเลิก\" ด้านบน)",
                    "note_en": "This figure may include contracts that are closing or awaiting cancellation, because "
                               "those cannot be separated yet (see the \"Contract closing or awaiting cancellation\" band above)",
                },
            ],
            "orphan_cancellations": _orphan_cancellations(),
        },
        "meta": _meta("due_month", month, scope, officer),
    }


FUNCTIONS = {"cash_received": cash_received, "due_month": due_month}
