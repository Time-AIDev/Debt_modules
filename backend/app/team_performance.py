"""GET /v1/reports/team — the Overview's team performance (redesign v2 PR 8).

Nothing here is a new money rule. Every figure is read from a computation that
already serves it: arrears from the customer aggregate (main._customer_aggregate,
what aggregate_overdue is), receipts from weekly_figures.counted_receipts (each
payment once) through collection_kpi.cash_received, promise and contact counts
from reports.officers(), NPL roll from weekly_figures.npl_movement, the queue
from today.officer_totals, bands from band_sets.resolve_band. This module only
groups and divides what those serve, so the screen does no arithmetic.
"""
import calendar
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import cases as cases_domain
from . import collection_kpi, journey, officers as officer_registry, reports, today, weekly_figures
from .config import settings
from .money import band_sets

ZERO = Decimal("0")
BAND_SET = "SOP_30_60_90"          # the set GET /v1/reports/bucket-flow reports on by default
DSO_WINDOW_DAYS = 90
MONTHS_TH = ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม",
             "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม")
STATUS_BAND_EN = {"NPL_CONFIRMED": "NPL confirmed", "RESOLVED": "Resolved", "CLOSED": "Closed"}
NOT_APPROVED = ("DRAFT_CREATED", "PENDING", "UNSENT", "REJECTED")

NOTES = {
    "no_target": ("ยังไม่มีเป้าที่ผู้จัดการตั้งไว้ จึงยังไม่มีตัวเลขผลสำเร็จ",
                  "No target has been saved, so there is no achievement figure"),
    "no_split_target": ("ยังตั้งเป้าแยกตามประเภทรายรับไม่ได้ จึงยังไม่มีตัวเลขผลสำเร็จแยกประเภท",
                        "Targets are not saved per receipt type, so there is no achievement figure for it"),
    "no_contacts": ("ยังไม่มีการติดต่อที่บันทึกไว้", "No contact is on record yet"),
    "no_promises": ("ยังไม่มีนัดชำระที่ครบกำหนดแล้ว (รักษาหรือผิดนัด)", "No promise has been kept or broken yet"),
    "rates": ("อัตราการติดต่อและอัตรารักษานัด นับจากที่บันทึกไว้ทั้งหมดในระบบ ไม่ใช่เฉพาะเดือนนี้",
              "Contact and promise rates count everything on record, not this month only"),
    "dso_incomplete": ("บางใบแจ้งหนี้ไม่มียอดเงินหรือวันที่ออก จึงคำนวณจำนวนวันเก็บหนี้ไม่ได้",
                       "Some invoices carry no amount or issue date, so days sales outstanding cannot be served"),
    "dso_no_billing": ("ไม่มีการออกใบแจ้งหนี้ใน 90 วันที่ผ่านมา จึงคำนวณจำนวนวันเก็บหนี้ไม่ได้",
                       "Nothing was billed in the last 90 days, so days sales outstanding cannot be served"),
    "dso_short_receipts": ("ข้อมูลรับเงินในระบบยังไม่ครอบคลุม 90 วันที่ผ่านมา จึงคำนวณจำนวนวันเก็บหนี้ไม่ได้",
                           "Receipts on record do not cover the last 90 days, so days sales outstanding cannot be served"),
}


def _note(key):
    th, en = NOTES[key]
    return th, en


def _money(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def _rate(num, den):
    """(served "62.4%", Decimal) or (None, None) when there is nothing to divide by."""
    if not den:
        return None, None
    pct = (Decimal(num) / Decimal(den) * 100).quantize(Decimal("0.1"))
    return "%s%%" % pct, pct


def _shown_target(value):
    """A Settings target as served: None stays None; a number reads as its plain
    string, the same shape the config rows serve. Never a zero in None's place."""
    return None if value is None else str(value)


def _target_attainment(actual_pct, target):
    """(attainment "9.1%", bar_pct, note_th, note_en) for a rate against its target.

    No target (None): attainment None with the shared no-target note — never a bar.
    A target with no computable rate yet: both None with no note, because the rate's
    own note already says why. Otherwise the same capped bar `collection_kpi._attainment`
    serves the collection screens, carrying its own note when the target is zero."""
    if target is None:
        th, en = _note("no_target")
        return None, None, th, en
    if actual_pct is None:
        return None, None, None, None
    att, th, en, bar = collection_kpi._attainment(actual_pct, target)
    return ("%s%%" % att) if att else None, bar, th, en


def _vs(mine, team):
    if mine is None or team is None:
        return None
    return "above" if mine > team else "below" if mine < team else "equal"


def scope_counts(cs):
    """(cases_total, in_scope) — the two counts the Overview strip and the shell's
    workload read.

    in_scope is the collection unit `reports.reconciliation()` states in words:
    "customers in collection (closed, terminated and not-installed contracts excluded)"
    (reports.py:198, its own unit_weekly). A case is in scope when its payment_status
    is neither CLOSED, TERMINATED nor NOT_INSTALLED; cases_total is every case on the
    work book, the denominator the strip's note prints beside it. This is deliberately
    NOT the bare `!= "CLOSED"` gate arrears uses: a customer the contracts still mark
    PRE_COLLECTION (NOT_INSTALLED) is reading the book, not being collected from.
    Since 2026-09-20 a terminated contract is off the collection population exactly
    like a closed one — nobody is being collected from — while the two stay apart in
    every report that names the status.
    """
    book_cases = book_cases_of(cs)
    return (len(book_cases),
            sum(1 for c in book_cases
                if c["payment_status"] not in ("CLOSED", "TERMINATED", "NOT_INSTALLED")))


def book_cases_of(cs):
    """Cases that count on the work book. A pre-install card opened from 2026-09-20
    carries a case before its invoice is released; it is pipeline work until then and
    must not inflate the book badge, the caseload or any management figure. Stated
    here once so every count agrees."""
    return [c for c in cs.cases.values() if cases_domain.is_book_case(c)]


def queue_done_totals(cs, known, business_date=None):
    """Per-officer count of Today-queue cases already worked on the business date.

    Delta-100 D2b. The predicate, stated once here: a case is `done` when it is in
    the officer's Today queue by the same gates `today.officer_totals` applies (a
    case on a book customer, not CLOSED, with an officer) AND at least one row on
    cases.contact_log for that customer carries `counted: true` with `occurred_at`
    on the business date. `counted` is the flag `reports.officers()` counts and
    `cases.log_contact` writes (cases.py:1212); a call that only sent a LINE or
    reached nobody is logged and is NOT done. The contact row's own officer_uid is
    not consulted: the queue's current owner gets the credit for work on their case.
    """
    bd = str(business_date or settings.business_date)
    counted_today = {r["customer_uid"] for r in cs.contact_log
                     if r.get("counted") and str(r.get("occurred_at") or "")[:10] == bd}
    totals = {uid: 0 for uid in known}
    for customer in journey.book_customers():
        case = cs.cases.get(customer.uid)
        if case is None or case["payment_status"] in ("CLOSED", "TERMINATED") or not case["officer_uid"]:
            continue
        if customer.uid in counted_today:
            uid = case["officer_uid"]
            totals[uid] = totals.get(uid, 0) + 1
    return totals


def workload(cs=None):
    """The rail footer's workload: the work-book caseload against a cap, and the
    contact-rate denominator.

    `cap` is `settings.caseload_cap`, None until somebody sets one — the percentage
    is then None and the screen says so, never a made-up figure. The denominator is
    the same in-scope count the Overview strip serves (scope_counts), the head-count
    contacts and promises are measured over. `bar_pct` is the same percentage
    clamped to 0..100 for a progress bar; `percentage` stays the true figure.
    """
    cs = cs or cases_domain.for_current()
    cases_total, in_scope = scope_counts(cs)
    cap = settings.caseload_cap
    pct = None
    if cap:
        pct = (Decimal(cases_total) / Decimal(cap) * 100).quantize(Decimal("0.1"))
    return {
        "caseload": cases_total,
        "cap": cap,
        "contact_denominator": in_scope,
        "percentage": str(pct) if pct is not None else None,
        "bar_pct": str(max(Decimal("0.0"), min(Decimal("100.0"), pct))) if pct is not None else None,
        "cap_note_th": None if cap else "ยังไม่ได้ตั้งเพดานงานในระบบ จึงยังไม่มีสัดส่วนเทียบเพดาน",
        "cap_note_en": None if cap else "No caseload cap has been set, so there is no ratio to a cap",
    }


def _week_ptp(rows):
    """The whole book's PTP outcome inside one report week, from reports.officers():
    kept / (kept + broken). The pair is None-rate when nothing was decided."""
    kept = sum(r["ptps_kept"] for r in rows)
    broken = sum(r["ptps_broken"] for r in rows)
    decided = kept + broken
    pct = (Decimal(kept) / Decimal(decided) * 100).quantize(Decimal("0.1")) if decided else None
    return {"kept": kept, "decided": decided, "pct": pct,
            "rate": ("%s%%" % pct) if pct is not None else None}


def dso_delta(current, prior):
    """(signed days, direction) of a later DSO against an earlier one, or (None, None)
    when either is absent — never a delta against a figure that was not served."""
    if current is None or prior is None:
        return None, None
    if current == prior:
        return 0, "same"
    return current - prior, ("slower" if current > prior else "faster")


def month_span(bd, back):
    """The month `back` months before bd's, from its 1st to the same day number as bd
    (clipped to that month's last day) — so every month compares like with like."""
    y, m = bd.year, bd.month - back
    while m < 1:
        y, m = y - 1, m + 12
    first = bd.replace(year=y, month=m, day=1)
    return first, first.replace(day=min(bd.day, calendar.monthrange(y, m)[1]))


def dso_days(invoices, units, overdue_total, bd):
    """Days sales outstanding, or (None, note) when the book cannot honestly serve it.

    Formula (redesign v2 ruling): DSO = outstanding overdue receivables
    ÷ (amount billed in the last 90 days ÷ 90), rounded to whole days.
    Served only when every invoice carries an amount and an issue date, something was
    billed inside the window, and the receipts on record reach back to its first day."""
    start = bd - timedelta(days=DSO_WINDOW_DAYS - 1)
    invoices = list(invoices)
    if not invoices or any(inv.get("amount") in (None, "") or not inv.get("issued_on") for inv in invoices):
        return None, _note("dso_incomplete")
    billed = sum((Decimal(str(inv["amount"])) for inv in invoices
                  if str(start) <= str(inv["issued_on"])[:10] <= str(bd)), ZERO)
    if billed <= 0:
        return None, _note("dso_no_billing")
    dated = [u["received_on"] for u in units if u["received_on"]]
    if not dated or min(dated) > str(start):
        return None, _note("dso_short_receipts")
    days = (Decimal(overdue_total) / (billed / DSO_WINDOW_DAYS)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(days), None


def aging_bands(customers):
    """[(customer, status, oldest_dpd, arrears)] → bands in severity order."""
    rows = {}
    for _customer, status, oldest, arrears in customers:
        code = band_sets.resolve_band(status, oldest, BAND_SET).code or "NONE"
        row = rows.setdefault(code, [0, ZERO])
        row[0] += 1
        row[1] += arrears
    out = []
    for lo, hi, code in band_sets.BAND_SETS[BAND_SET]:
        n, amount = rows.pop(code, [0, ZERO])
        out.append({"code": code, "label_th": band_sets.band_label_th(BAND_SET, code, lo, hi),
                    "label_en": band_sets.band_label_en(BAND_SET, code, lo, hi), "customers": n, "arrears": _money(amount)})
    for code in ("NPL_CONFIRMED", "RESOLVED", "CLOSED", "NONE"):
        if code in rows:
            n, amount = rows[code]
            out.append({"code": code,
                        "label_th": band_sets.STATUS_LABEL_TH.get(code, "ยังไม่เข้าช่วงอายุหนี้"),
                        "label_en": STATUS_BAND_EN.get(code, "Not yet banded"),
                        "customers": n, "arrears": _money(amount)})
    return out


def queues(cs):
    """The four queue counts the Overview and the shell rail both read."""
    from . import invoice_pipeline, peak_documents
    from .routers.journey import list_npl_cases
    docs = peak_documents.for_current()
    return {"reviews_open": sum(1 for r in cs.reviews.values() if r["status"] == "OPEN"),
            "pipeline": len(invoice_pipeline.lookahead(invoice_pipeline.for_current())),
            "peak_not_approved": sum(1 for d in docs.documents.values() if d["state"] in NOT_APPROVED),
            "npl_cases": list_npl_cases()["meta"]["badge"]}


def _officer_row(uid, name, queue, done, cases, arrears, receipts, contacts, reached, kept, decided, npl):
    contact_rate, contact_pct = _rate(reached, contacts)
    kept_rate, kept_pct = _rate(kept, decided)
    return {"officer_uid": uid, "display_name": name, "display_name_en": name,
            "queue_today": queue, "queue_done": done, "cases": cases,
            "arrears": _money(arrears), "receipts_month": _money(receipts), "receipts_share": None,
            "contact_rate": contact_rate, "contacts": contacts, "reached_contacts": reached,
            "ptp_kept_rate": kept_rate, "ptps_kept": kept, "ptps_decided": decided, "npl_count": npl,
            "_contact_pct": contact_pct, "_kept_pct": kept_pct}


def build(business_date=None):
    bd = business_date or settings.business_date
    month = collection_kpi.business_month(bd)
    cs = cases_domain.for_current()
    jstate = journey.for_current()
    from . import main

    # Arrears — the customer aggregate, over customers in collection (not CLOSED).
    arrears_of, book, arrears_by_officer = {}, [], {}
    for customer in journey.book_customers():
        total, oldest, _band, _out = main._customer_aggregate(customer)
        arrears_of[customer.uid] = total
        status = cases_domain.contract_field_of(customer.contracts[0], "status") if customer.contracts else "PRE_COLLECTION"
        book.append((customer, status, oldest, total))
        case = cs.cases.get(customer.uid)
        if case is None or case["payment_status"] in ("CLOSED", "TERMINATED"):
            continue
        uid = case["officer_uid"]
        arrears_by_officer[uid] = arrears_by_officer.get(uid, ZERO) + total
    in_collection = [c for c, _s, _o, _t in book
                     if c.uid in cs.cases and cs.cases[c.uid]["payment_status"] not in ("CLOSED", "TERMINATED")]
    arrears_total = sum((arrears_of[c.uid] for c in in_collection), ZERO)
    debtors = sum(1 for c in in_collection if arrears_of[c.uid] > 0)
    # The strip's two scope counts, computed in one place so the shell serves the
    # same numbers (scope_counts, whose docstring carries the predicate).
    cases_total, in_scope = scope_counts(cs)

    # Receipts — each payment once; the month and the four before it, to the same day.
    units = weekly_figures.counted_receipts(jstate)
    portfolio = collection_kpi.cash_received(month=month)["indicator"]
    month_start = bd.replace(day=1)
    month_end = bd.replace(day=calendar.monthrange(bd.year, bd.month)[1])
    split = weekly_figures._money_span(units, month_start, month_end)
    stored_target = portfolio["target"]
    # Delta-100 D2e: the receipts target is the month's saved target when a manager
    # saved one; otherwise the config fallback, and only then None. The fallback is
    # named on the payload so a reader can see which of the two is in force.
    config_target = settings.receipts_monthly_target
    target = stored_target or (_money(config_target) if config_target is not None else None)
    target_source = "SAVED_MONTHLY_TARGET" if stored_target else ("CONFIG_DEFAULT" if config_target is not None else None)
    attainment, _note_th, _note_en, _bar = collection_kpi._attainment(portfolio["actual"], target)
    no_target_th, no_target_en = _note("no_target")
    no_split_th, no_split_en = _note("no_split_target")
    by_month = []
    for back in range(4, -1, -1):
        start, end = month_span(bd, back)
        span = weekly_figures._money_span(units, start, end)
        month_key = "%04d-%02d" % (start.year, start.month)
        # Delta-100 D2e: the monthly bar's target, from the same collection targets
        # store the current month's target lives in; a month nobody set one for
        # serves None and the no-target note, never a zero. The CURRENT month also
        # accepts the config fallback, so the bar and the KPI card read one target.
        month_target = collection_kpi.month_target(month_key)
        if back == 0 and not month_target and config_target is not None:
            month_target = config_target
        month_att, month_att_th, month_att_en, month_att_bar = collection_kpi._attainment(span["total"], month_target)
        by_month.append({"month": month_key,
                         "label_th": "%s %d" % (MONTHS_TH[start.month - 1], start.year),
                         "label_en": "%s %d" % (calendar.month_name[start.month], start.year),
                         "start": span["start"], "end": span["end"], "total": span["total"],
                         "target": _money(month_target) if month_target else None,
                         "attainment": ("%s%%" % month_att) if month_att else None,
                         "attainment_bar_pct": month_att_bar,
                         "attainment_note_th": month_att_th, "attainment_note_en": month_att_en,
                         "current": back == 0})

    # Officers — reports.officers() for counts, today.officer_totals for the queue.
    counted = {o["officer_uid"]: o for o in reports.officers(bd)}
    registry = {r["uid"]: r for r in officer_registry.registry()}
    uids = sorted({c["officer_uid"] for c in cs.cases.values() if c["officer_uid"]}
                  | {u for u, r in registry.items() if r["role"] == "OFFICER"})
    queue = today.officer_totals(cs, uids)
    done = queue_done_totals(cs, uids, bd)
    rows = []
    # An officer missing from the registry (or with a blank name) is served by its uid, the
    # handle role.jsx's roster and the identity menu already show for such an officer.
    for uid in uids:
        o = counted.get(uid) or reports._blank_officer(uid, "", "")
        rows.append(_officer_row(
            uid, (registry.get(uid) or {}).get("display_name_th") or uid, queue.get(uid, 0), done.get(uid, 0),
            o["caseload"],
            arrears_by_officer.get(uid, ZERO), Decimal(collection_kpi.cash_received(month=month, officer=uid)["indicator"]["actual"]),
            o["contacts_all_time"], o["counted_contacts_all_time"], o["ptps_kept_all_time"],
            o["ptps_kept_all_time"] + o["ptps_broken_all_time"], o["npl"]))
    total = _officer_row(None, None, sum(r["queue_today"] for r in rows), sum(r["queue_done"] for r in rows),
                         sum(r["cases"] for r in rows),
                         sum((Decimal(r["arrears"]) for r in rows), ZERO),
                         sum((Decimal(r["receipts_month"]) for r in rows), ZERO),
                         sum(r["contacts"] for r in rows), sum(r["reached_contacts"] for r in rows),
                         sum(r["ptps_kept"] for r in rows), sum(r["ptps_decided"] for r in rows),
                         sum(r["npl_count"] for r in rows))
    total["display_name"] = "ทั้งทีม"
    total["display_name_en"] = "Team total"
    largest = max((Decimal(r["receipts_month"]) for r in rows), default=ZERO)
    for r in rows:
        # The bar's width: this officer's receipts as a share of the largest officer's.
        r["receipts_share"] = float((Decimal(r["receipts_month"]) / largest).quantize(Decimal("0.001"))) if largest > 0 else 0.0
        r["contact_rate_vs_team"] = _vs(r.pop("_contact_pct"), total["_contact_pct"])
        r["ptp_kept_vs_team"] = _vs(r.pop("_kept_pct"), total["_kept_pct"])
    del total["_contact_pct"], total["_kept_pct"]
    total["contact_rate_vs_team"] = total["ptp_kept_vs_team"] = None

    # NPL roll inside the current month window.
    movement = weekly_figures.npl_movement(month_start, bd, cs, jstate)
    rolled_in = {r["customer_uid"] for r in movement["rows"] if r["direction"] == "ENTERED"}
    rolled_out = {r["customer_uid"] for r in movement["rows"] if r["direction"] == "LEFT"}
    still = {c["customer_uid"] for c in cs.cases.values()
             if c["payment_status"] == "NPL" and c["customer_uid"] not in rolled_in}

    def roll(uids_):
        return {"customers": len(uids_), "amount": _money(sum((arrears_of.get(u, ZERO) for u in uids_), ZERO))}

    dso, dso_note = dso_days(jstate.invoices.values(), units, arrears_total, bd)
    # Delta-100 D2e: the prior month's DSO at the same day of the month — the same
    # formula, the same invoice and receipt list, with that day's arrears read from
    # the money engine. The engine refuses (None + its note) when the book cannot
    # honestly carry the window, so the delta is then None too.
    prior_month_day = month_span(bd, 1)[1]
    prior_arrears = ZERO
    for customer in in_collection:
        for contract in customer.contracts:
            _c, _d, _b, block, _p = main._contract_view(contract, as_of=prior_month_day)
            prior_arrears += block.cumulative_arrears
    dso_prior, dso_prior_note = dso_days(jstate.invoices.values(), units, prior_arrears, prior_month_day)
    dso_change, dso_vs_prior = dso_delta(dso, dso_prior)

    # Delta-100 D2e: prior-week PTP kept rate, from the same reports.officers() rows
    # the officer table reads, over the 7 days ending one week before the business
    # date. None (and therefore a None delta) when that week decided no promise.
    week_ptp = _week_ptp(counted.values())
    prior_week_ptp = _week_ptp(reports.officers(bd - timedelta(days=7)))
    if week_ptp["pct"] is not None and prior_week_ptp["pct"] is not None:
        ptp_delta = week_ptp["pct"] - prior_week_ptp["pct"]
        ptp_delta_pts, ptp_vs_prior = str(ptp_delta), _vs(week_ptp["pct"], prior_week_ptp["pct"])
    else:
        ptp_delta_pts = ptp_vs_prior = None

    # Delta-100 D2e: the weekly edition currently out, read from the same edition
    # store and summary GET /v1/reports/weekly serves (reports._edition_summary) —
    # newest first, so editions[0] is the latest published edition. None when
    # nothing has been published; the live week label is served beside it.
    latest_edition = reports._edition_summary(reports.editions()[0]) if reports.editions() else None
    week_year, week_no, _ = bd.isocalendar()
    period_start, period_end = reports._period(bd)

    # Delta-100 D2e: the four KPI bars' targets. Two of the four are rates, so the
    # attainment is the rate over its target; DSO is lower-is-better and carries a
    # comparison instead of a bar. No target means None + the no-target note.
    _kept_rate, kept_pct = _rate(total["ptps_kept"], total["ptps_decided"])
    _contact_rate, contact_pct = _rate(total["reached_contacts"], total["contacts"])
    ptp_att, ptp_att_bar, ptp_att_th, ptp_att_en = _target_attainment(kept_pct, settings.ptp_kept_target_pct)
    contact_att, contact_att_bar, contact_att_th, contact_att_en = _target_attainment(contact_pct, settings.contact_target_pct)
    dso_target = settings.dso_target_days
    if dso is None or dso_target is None:
        dso_vs_target = None
    else:
        dso_vs_target = "within" if dso <= dso_target else "over"

    contacts_th, contacts_en = _note("no_contacts")
    promises_th, promises_en = _note("no_promises")
    rates_th, rates_en = _note("rates")
    team = {
        "arrears_total": _money(arrears_total), "debtors": debtors,
        "queue_today": sum(queue.values()),
        "queue_done": sum(done.values()),
        "in_scope": in_scope, "cases_total": cases_total,
        "contact_scope": in_scope,
        "contact_scope_note_th": "วัดจากลูกหนี้ที่อยู่ในการติดตาม %d ราย (ไม่รวมปิดบัญชีและยังไม่ติดตั้ง)" % in_scope,
        "contact_scope_note_en": "Measured over the %d customers in collection (closed and not-installed excluded)" % in_scope,
        "ptp_kept_rate": total["ptp_kept_rate"], "ptps_kept": total["ptps_kept"], "ptps_decided": total["ptps_decided"],
        "ptp_kept_rate_note_th": None if total["ptp_kept_rate"] else promises_th,
        "ptp_kept_rate_note_en": None if total["ptp_kept_rate"] else promises_en,
        "npl_count": total["npl_count"],
        "contact_success_rate": total["contact_rate"], "reached_contacts": total["reached_contacts"],
        "contacts": total["contacts"],
        "contact_success_rate_note_th": None if total["contact_rate"] else contacts_th,
        "contact_success_rate_note_en": None if total["contact_rate"] else contacts_en,
        "rates_note_th": rates_th, "rates_note_en": rates_en,
        "receipts_month": portfolio["actual"], "target_month": target, "target_month_source": target_source,
        "attainment": ("%s%%" % attainment) if attainment else None,
        "attainment_note_th": None if attainment else no_target_th,
        "attainment_note_en": None if attainment else no_target_en,
        "receipts": {line: {"amount": split[line], "target": None, "attainment": None,
                            "attainment_note_th": no_split_th, "attainment_note_en": no_split_en}
                     for line in weekly_figures.RECEIPT_LINES},
        "dso_days": dso,
        "dso_note_th": dso_note[0] if dso_note else None,
        "dso_note_en": dso_note[1] if dso_note else None,
        # Delta-100 D2e comparison figures — prior week / prior month / scope / edition.
        "ptp_kept_rate_week": week_ptp["rate"], "ptps_kept_week": week_ptp["kept"],
        "ptps_decided_week": week_ptp["decided"],
        "ptp_kept_rate_prior_week": prior_week_ptp["rate"], "ptps_kept_prior_week": prior_week_ptp["kept"],
        "ptps_decided_prior_week": prior_week_ptp["decided"],
        "ptp_kept_rate_delta_pts": ptp_delta_pts, "ptp_kept_rate_vs_prior_week": ptp_vs_prior,
        "dso_prior_month_days": dso_prior, "dso_delta_days": dso_change, "dso_vs_prior_month": dso_vs_prior,
        "dso_prior_month_note_th": dso_prior_note[0] if dso_prior_note else None,
        "dso_prior_month_note_en": dso_prior_note[1] if dso_prior_note else None,
        "weekly_edition": {"period": "%s..%s" % (period_start, period_end),
                           "week_label": "WK-%02d/%d" % (week_no, week_year),
                           "edition": latest_edition,
                           "edition_label": ("WK-%02d/%d" % (latest_edition["week"], latest_edition["week_year"]))
                                             if latest_edition else None},
        # Delta-100 D2e: the four KPI bars' targets. `receipts` above is the first
        # bar and already carries target/attainment; the other three follow.
        "receipts_monthly_target": _money(config_target) if config_target is not None else None,
        "ptp_kept_target_pct": _shown_target(settings.ptp_kept_target_pct),
        "ptp_kept_attainment": ptp_att, "ptp_kept_attainment_bar_pct": ptp_att_bar,
        "ptp_kept_attainment_note_th": ptp_att_th, "ptp_kept_attainment_note_en": ptp_att_en,
        "contact_target_pct": _shown_target(settings.contact_target_pct),
        "contact_attainment": contact_att, "contact_attainment_bar_pct": contact_att_bar,
        "contact_attainment_note_th": contact_att_th, "contact_attainment_note_en": contact_att_en,
        "dso_target_days": dso_target, "dso_vs_target": dso_vs_target,
    }
    team["receipts"]["total"] = {"amount": split["total"], "target": target, "attainment": team["attainment"],
                                 "attainment_note_th": team["attainment_note_th"],
                                 "attainment_note_en": team["attainment_note_en"]}
    return {
        "period": {"business_date": str(bd), "month": month,
                   "month_label_th": "%s %d" % (MONTHS_TH[bd.month - 1], bd.year),
                   "month_label_en": "%s %d" % (calendar.month_name[bd.month], bd.year),
                   "officers": len(rows)},
        "team": team,
        "receipts_by_month": by_month,
        "npl_roll": {"start": str(month_start), "end": str(bd), "rolled_in": roll(rolled_in),
                     "rolled_out": roll(rolled_out), "still_npl": roll(still)},
        "aging_bands": aging_bands(book),
        "band_set_code": BAND_SET,
        "officers": rows,
        "officers_total": total,
        "queues": queues(cs),
    }


def _receipts_by_officer(cs, month, uids):
    """Each officer's cash received this month, in one pass.

    The same number `collection_kpi.cash_received(month=month, officer=uid)["actual"]`
    serves — that function's own read of `weekly_figures.counted_receipts`, filtered
    to the contracts on the officer's desk — but computed for every officer from one
    receipt list instead of one whole read per officer. Only the receipts actual is
    needed: the row's receipts_month and the share's max. Targets and the portfolio
    figure are not part of the one-officer payload.
    """
    contract_officer = {}
    for customer in journey.book_customers():
        case = cs.cases.get(customer.uid)
        if case is None:
            continue
        officer = case["officer_uid"]
        for contract in customer.contracts:
            contract_officer[contract.uid] = officer
    units = weekly_figures.counted_receipts(journey.for_current())
    totals = {}
    for unit in units:
        if (unit["received_on"] or "")[:7] != month:
            continue
        officer = contract_officer.get(unit["contract_uid"])
        if officer in uids:
            totals[officer] = totals.get(officer, ZERO) + unit["amount"]
    return {uid: Decimal(collection_kpi._money(totals.get(uid, ZERO))) for uid in uids}


def officer(officer_uid):
    """F09 / feedback-r2 TASK-105: one officer's row from the same computation
    `build()` serves the team payload, plus the note that explains a rate which is
    not computable yet. None when the uid is not an officer in this book.

    Computed narrowly (2026-09-29): the row's own arrears, queue and receipts, and
    only the team sums its two comparator fields divide by — instead of `build()`,
    which also paid DSO's prior-month contract views, aging bands, the weekly
    editions and a second reports.officers() pass for every case a screen opened.
    """
    bd = settings.business_date
    month = collection_kpi.business_month(bd)
    cs = cases_domain.for_current()
    from . import main

    counted = {o["officer_uid"]: o for o in reports.officers(bd)}
    registry = {r["uid"]: r for r in officer_registry.registry()}
    uids = sorted({c["officer_uid"] for c in cs.cases.values() if c["officer_uid"]}
                  | {u for u, r in registry.items() if r["role"] == "OFFICER"})
    if officer_uid not in uids:
        return None

    def counted_row(uid):
        return counted.get(uid) or reports._blank_officer(uid, "", "")

    # The row's arrears: the officer's own cases, under build()'s own gate.
    arrears = ZERO
    for customer in journey.book_customers():
        case = cs.cases.get(customer.uid)
        if case is None or case["payment_status"] in ("CLOSED", "TERMINATED"):
            continue
        if case["officer_uid"] != officer_uid:
            continue
        total, _oldest, _band, _out = main._customer_aggregate(customer)
        arrears += total

    queue = today.officer_totals(cs, [officer_uid]).get(officer_uid, 0)
    done = queue_done_totals(cs, [officer_uid], bd).get(officer_uid, 0)
    receipts = _receipts_by_officer(cs, month, uids)
    own = counted_row(officer_uid)
    row = _officer_row(
        officer_uid, (registry.get(officer_uid) or {}).get("display_name_th") or officer_uid,
        queue, done, own["caseload"], arrears, receipts.get(officer_uid, ZERO),
        own["contacts_all_time"], own["counted_contacts_all_time"], own["ptps_kept_all_time"],
        own["ptps_kept_all_time"] + own["ptps_broken_all_time"], own["npl"])

    # The two team comparators build() takes over its rows: the same sums over the
    # same uid set (a counted officer outside it is not a row and never was).
    team_reached = sum(counted_row(u)["counted_contacts_all_time"] for u in uids)
    team_contacts = sum(counted_row(u)["contacts_all_time"] for u in uids)
    team_kept = sum(counted_row(u)["ptps_kept_all_time"] for u in uids)
    team_decided = sum(counted_row(u)["ptps_kept_all_time"] + counted_row(u)["ptps_broken_all_time"] for u in uids)
    _team_rate, team_contact_pct = _rate(team_reached, team_contacts)
    _team_kept_rate, team_kept_pct = _rate(team_kept, team_decided)
    largest = max((receipts.get(u, ZERO) for u in uids), default=ZERO)
    row["receipts_share"] = float((Decimal(row["receipts_month"]) / largest).quantize(Decimal("0.001"))) if largest > 0 else 0.0
    row["contact_rate_vs_team"] = _vs(row.pop("_contact_pct"), team_contact_pct)
    row["ptp_kept_vs_team"] = _vs(row.pop("_kept_pct"), team_kept_pct)
    notes_th, notes_en = [], []
    if row["contact_rate"] is None:
        notes_th.append(NOTES["no_contacts"][0])
        notes_en.append(NOTES["no_contacts"][1])
    if row["ptp_kept_rate"] is None:
        notes_th.append(NOTES["no_promises"][0])
        notes_en.append(NOTES["no_promises"][1])
    if not notes_th:
        notes_th.append(NOTES["rates"][0])
        notes_en.append(NOTES["rates"][1])
    return {"officer": row, "note_th": " · ".join(notes_th), "note_en": " · ".join(notes_en)}
