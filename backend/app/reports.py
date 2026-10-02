"""Reports — REQ-KPI-020 (the weekly report in Jo's shape) and REQ-KPI-021 (officer
indicators). Every ratio carries its period; every figure is computed here, never in
the interface. Targets come from a person (saved), never a literal."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import cases as cases_domain
from . import clock
from . import journey
from . import today as today_domain
from . import weekly_figures
from .config import settings
from .session import Store

# Ruling 43, R4-F04 (MINOR): TARGETS/FOCUS were process-wide module dicts — one
# tester's saved weekly targets and next-week focus text appeared in every other
# tester's report, and in a session created afterwards. Same defect class as R4-F02
# (a module-wide mutable dict, not a per-object field), fixed the same way: a
# `session.Store` per dict, wrapped in a thin dict-shaped proxy so every read/write
# site below keeps the same name (`TARGETS`, `FOCUS`) and the same call shape.
_targets_store = Store(dict, key="reports.targets")      # period -> {category: target}; saved by a person
_focus_store = Store(dict, key="reports.focus")        # period -> next-week focus text


class _StoreDict:
    """dict-shaped stand-in for a module-level dict now held per session."""

    def __init__(self, store):
        self._store = store

    def _d(self):
        return self._store.for_current()

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def __contains__(self, k):
        return k in self._d()

    def __iter__(self):
        return iter(self._d())

    def __len__(self):
        return len(self._d())

    def get(self, k, default=None):
        return self._d().get(k, default)

    def clear(self):
        self._d().clear()


TARGETS = _StoreDict(_targets_store)
FOCUS = _StoreDict(_focus_store)

# Judge J-52: frozen copies of the weekly report, per tester session, newest first.
_snapshots = Store(list, key="reports.snapshots")

# Editions: the weekly report as the team PUBLISHED it. A snapshot is a private
# bookmark a manager can name; an edition is the copy that went out. The live report
# is always the draft — its figures move with the book — and publishing freezes it as
# edition N of its week. A later edition of the same week supersedes the earlier one;
# nothing is ever deleted. Per tester session, newest first, like the snapshots.
_editions = Store(list, key="reports.editions")


def snapshots():
    return _snapshots.for_current()


def editions():
    return _editions.for_current()


def reset():
    """Test seam: clears EVERY session's snapshots, editions and saved targets/focus,
    not just the current one — matching the sibling domains' `Store.reset()` idiom."""
    _snapshots.reset()
    _editions.reset()
    _targets_store.reset()
    _focus_store.reset()


def _snapshot_name(name):
    """Round-4 J4-19's name: trimmed, None when empty — and (B13b fix round 1) with any
    typed number cut by customer_contact._without_numbers BEFORE it is stored. The name
    is served on take, list, read and rename, and the Reports screen builds the download
    filename from it, so cutting it here covers every one of them."""
    text = (str(name).strip() or None) if name else None
    return weekly_figures.without_typed_numbers(text)


def take_snapshot(taken_by, taken_by_role=None, name=None):
    """Round-4 J4-19: `label` is the period and is generated; a person may also NAME the
    snapshot ("ก่อนประชุมทีม") so a list of six identical periods can be told apart."""
    rows = snapshots()
    payload = weekly()
    snap = {
        "snapshot_uid": "wks-%05d" % (len(rows) + 1),
        "taken_at": clock.stamp(),           # J3-19: one clock
        "taken_by": taken_by,
        "taken_by_role": taken_by_role,      # S2-04
        "label": payload["period"]["label"],
        "name": _snapshot_name(name),
        "payload": payload,
    }
    rows.insert(0, snap)
    return snap


def snapshot(snapshot_uid):
    return next((s for s in snapshots() if s["snapshot_uid"] == snapshot_uid), None)


def rename_snapshot(snapshot_uid, name):
    snap = snapshot(snapshot_uid)
    if snap is None:
        return None
    snap["name"] = _snapshot_name(name)
    return snap


def _edition_summary(e):
    return {k: v for k, v in e.items() if k != "payload"}


def publish_edition(published_by, published_by_role=None):
    """Freeze the live report as the next edition of its week. The earlier PUBLISHED
    edition of the same week, if any, becomes SUPERSEDED and names its successor."""
    rows = editions()
    payload = weekly()
    period = payload["period"]
    number = 1 + sum(1 for e in rows if e["period"] == period["label"])
    edition = {
        "edition_uid": "wke-%05d" % (len(rows) + 1),
        "period": period["label"],
        "week": period["week"],
        "week_year": period["week_year"],
        "number": number,
        "status": "PUBLISHED",
        "published_at": clock.stamp(),
        "published_by": published_by,
        "published_by_role": published_by_role,
        "superseded_by": None,
        "payload": payload,
    }
    for e in rows:
        if e["period"] == period["label"] and e["status"] == "PUBLISHED":
            e["status"] = "SUPERSEDED"
            e["superseded_by"] = edition["edition_uid"]
    rows.insert(0, edition)
    return edition


def edition(edition_uid):
    return next((e for e in editions() if e["edition_uid"] == edition_uid), None)


def edition_state(period_label):
    """What the live report is, in edition terms: always the DRAFT, plus the edition
    of this week that is currently out (if one is)."""
    this_week = [e for e in editions() if e["period"] == period_label]
    current = next((e for e in this_week if e["status"] == "PUBLISHED"), None)
    return {
        "status": "DRAFT",
        "period": period_label,
        "published_count": len(this_week),
        "latest": _edition_summary(current) if current else None,
        "note": "The draft is the live report; its figures move until an edition is published.",
        "note_th": "ฉบับร่างคือรายงานสด ตัวเลขยังเปลี่ยนได้จนกว่าจะเผยแพร่เป็นฉบับ",
        "note_en": "The draft is the live report; its figures can change until an edition is published.",
    }


def _period(business_date):
    end = business_date
    start = end - timedelta(days=6)
    return str(start), str(end)


def reconciliation(data=None):
    """Judge J-43: the three tabs count different things. Say so with numbers that add up.

    `data` is an unfiltered build() the caller already paid for (weekly); omitted, it
    builds its own — each build is a full pass over the book."""
    cs = cases_domain.for_current()
    data = data if data is not None else today_domain.build()
    # A pre-install card's case (2026-09-20) counts only once its invoice is released;
    # the three tabs must add up over the same book `team_performance.book_cases_of` names.
    book_cases = [c for c in cs.cases.values() if cases_domain.is_book_case(c)]
    by_status = {}
    for case in book_cases:
        by_status[case["payment_status"]] = by_status.get(case["payment_status"], 0) + 1
    in_collection = len(data["items"])
    total = len(book_cases)
    return {
        "book_rows": total,
        "in_collection": in_collection,
        "excluded_from_collection": total - in_collection,
        "by_payment_status": by_status,
        "unit_weekly": "customers in collection (closed, terminated and not-installed contracts excluded)",
        "unit_officers": "work-book rows per officer (every case, including closed and not installed)",
        "unit_buckets": "customers in the book by aging band",
        # R6-C15, closed round 7: `bucket-flow` served `unit` in English and nothing
        # else, alone among its siblings — every other unit on this payload has a Thai
        # twin. The working language is Thai (L5), so the one report whose unit an
        # officer could not read was the one counting her own book.
        "unit_buckets_th": "นับหัวลูกค้าในสมุดงาน แยกตามช่วงอายุหนี้",
        "unit_buckets_en": "Customers in the work book, by aging band",
        "note_th": "รายงานประจำสัปดาห์นับลูกค้าที่อยู่ในการติดตาม %d ราย; ตารางเจ้าหน้าที่และกระแสบัคเก็ตนับทุกแถวในสมุดงาน %d แถว (รวมปิดบัญชี/ยังไม่ติดตั้ง %d แถว)"
                   % (in_collection, total, total - in_collection),
        "note_en": "The weekly report counts %d customers in collection; the officer table and the band flow count "
                   "every work-book row, %d rows (including %d closed or not-installed rows)"
                   % (in_collection, total, total - in_collection),
    }


ALLOCATION_HOLD_PENDING_DECISION = "OD-02"


def _allocation_hold_in_period(cs, jstate, units):
    """Round-4 J4-06: the customers whose money is in and whose arrears have not moved.

    A receipt is recorded and drafted in PEAK but never allocated to instalment
    components while OD-02 is open, so the case still reads LATE (or NPL) and still
    counts in the late ratio. Returns (customer_uids, receipt_uids).

    B13 fix round 2, finding (c): reads the period's counted units
    (weekly_figures.units_in over counted_receipts, the list cash_in reads), not the
    raw receipts. A slip folded into a PEAK payment is allocated when PEAK's side is
    (weekly_figures.unit_is_allocated), so it holds nobody PEAK alone would not hold,
    and a folded payment that does hold counts as ONE receipt."""
    customers, rows = set(), []
    for u in units:
        if weekly_figures.unit_is_allocated(u):
            continue
        found = journey.contract_by_uid(u["contract_uid"])
        customer = found[0] if found else None
        case = cs.cases.get(customer.uid) if customer else None
        if case and case["payment_status"] in ("LATE", "NPL"):
            customers.add(customer.uid)
            rows.append(u["uid"])
    return customers, rows


def weekly(business_date=None, data=None):
    bd = business_date or settings.business_date
    start, end = _period(bd)
    period = "%s..%s" % (start, end)
    # `data` is a build() the caller already paid for (routers/shell.py); omitting it
    # keeps every other caller exactly as before.
    data = data if data is not None else today_domain.build()
    items = data["items"]
    cs = cases_domain.for_current()
    jstate = journey.for_current()
    by_entity = {"SPV": Decimal("0"), "EPC": Decimal("0")}
    late = npl = current = 0
    for it in items:
        ps = it["case"]["payment_status"]
        late += ps == "LATE"; npl += ps == "NPL"; current += ps == "CURRENT"
    # B13 fix round 1, finding (1): cash_in counts each payment once. A payment on record
    # twice — a PEAK report receipt and a receipt a person recorded against the same
    # invoice — is one unit from weekly_figures.counted_receipts, the helper mom and
    # paying_customers share, and the figure then says so and is indicative.
    # Fix round 2: the OD-02 hold below reads the same period units, and a flagged
    # receipt counted in the period is named and badges cash_in too.
    units = weekly_figures.counted_receipts(jstate)
    period_units = weekly_figures.units_in(units, start, end)
    for u in period_units:
        by_entity[u["entity"] or "EPC"] += u["amount"]
    span = {"start": start, "end": end}
    cash_in_notes = [n for n in (weekly_figures.overlap_note(units, (span,)),
                                 weekly_figures.flagged_note(units, span)) if n]
    # Final fix F-R2: this session's own receipts may lag the book's newest applied
    # PEAK report (an apply is reseeded only for the session that made it) — see
    # weekly_figures.peak_session_gap. cash_in serves its own peak_report_as_of the
    # same way mom and paying_customers do.
    peak_report_as_of, peak_gap_note = weekly_figures.peak_session_gap(jstate)
    if peak_gap_note:
        cash_in_notes.append(peak_gap_note)
    # Round-4 J4-06: the ratio and the cash figure disagree on purpose while OD-02 is
    # open — the money arrived, the arrears did not move, so the customer is still
    # counted late. The report says so beside the number instead of leaving the one
    # figure that goes upstairs unaccompanied.
    hold_customers, hold_receipts = _allocation_hold_in_period(cs, jstate, period_units)
    cash_in = {"instalment": str(by_entity["SPV"]), "cash_or_project": str(by_entity["EPC"]),
               "total": str(by_entity["SPV"] + by_entity["EPC"])}
    targets = TARGETS.get(period)
    achievement = None
    if targets:
        achievement = {k: (str((Decimal(cash_in[k]) / Decimal(str(v)) * 100).quantize(Decimal("0.1"))) + "%" if Decimal(str(v)) else None)
                       for k, v in targets.items() if k in cash_in}
    npl_changes = []
    for e in cs.events:
        if e["kind"] == "NPL_TYPE_SET":
            case = next((c for c in cs.cases.values() if c["uid"] == e["case_uid"]), None)
            customer = journey.customer_by_uid(case["customer_uid"]) if case else None
            # B13b: the NPL type's typed reason is cut of any number before it is copied.
            npl_changes.append({**weekly_figures.event_without_typed_numbers(e),
                                "display_name": customer.display_name if customer else None,
                                "volt_id": case["volt_id"] if case else None, "on": e.get("on") or str(bd)})
    # Round-2 settasak S2-08: the power and NPL acts of the period, with the case's power
    # line as it stands now — APPROVED/RESTRICTED after an approval, never "รออนุมัติ".
    power_actions = []
    for e in cs.events:
        if e["kind"] not in ("POWER_REQUESTED", "POWER_APPROVED", "POWER_EXECUTED", "POWER_RESTORED"):
            continue
        if not (start <= (e.get("on") or "") <= end):
            continue
        case = next((c for c in cs.cases.values() if c["uid"] == e["case_uid"]), None)
        customer = journey.customer_by_uid(case["customer_uid"]) if case else None
        # B13b: a power request's typed reason, the same way.
        power_actions.append({**weekly_figures.event_without_typed_numbers(e),
                              "display_name": customer.display_name if customer else None,
                              "volt_id": case["volt_id"] if case else None,
                              "power_state": case["power_state"] if case else None,
                              "power_state_label_th": cases_domain.POWER_STATE_LABEL_TH.get(case["power_state"], case["power_state"]) if case else None})
    issues_open = sum(1 for i in cs.issues.values() if i["status"] == "OPEN")
    ptps = list(cs.ptps.values())
    kept = sum(1 for p in ptps if p["status"] in ("KEPT", "KEPT_PARTIAL"))
    broken = sum(1 for p in ptps if p["status"] == "BROKEN")
    # J4-06: one sentence, carried beside both the cash figure and the ratio.
    allocation_note_th = ("รับเงินแล้ว %d ราย ยังนับเป็นล่าช้า — ยอดค้างยังไม่เปลี่ยนจนกว่าบัญชีจะตัดสินลำดับการจัดสรร"
                          % len(hold_customers)) if hold_customers else None
    allocation_note_en = ("%d customer(s) have paid but still count as late — their arrears do not change until "
                          "accounting decides the allocation order" % len(hold_customers)) if hold_customers else None
    # The week is named by its END date — the business date the report is run on —
    # using the ISO calendar (weeks start Monday), so "week 43" means one thing.
    week_year, week_no, _ = bd.isocalendar()
    return {
        "period": {"start": start, "end": end, "label": period, "generated_at": str(bd),
                   "week": week_no, "week_year": week_year,
                   "week_basis": "ISO 8601 week of the period's end date"},
        "management_summary": {
            "cash_in": cash_in, "targets": targets, "achievement": achievement,
            # B13 fix round 1, finding (1): additive, beside cash_in (not inside it).
            "cash_in_indicative": bool(cash_in_notes),
            "cash_in_notes": cash_in_notes,
            # Final fix F-R2: this session's own date, same key mom/paying_customers serve.
            "peak_report_as_of": peak_report_as_of,
            # Ruling 79's stamp: named as `cash_received` (R79-C) so a report read
            # next month says which of the two collected-amount indicators `cash_in`
            # has always been. A literal here, not a call into collection_kpi —
            # this module has no reason to import that one.
            "measure": "cash_received",
            "measure_label_th": "เงินสดรับตามเดือนที่เงินเข้า",
            "measure_label_en": "Cash received, by the month the money came in",
            "note": "Targets are saved by a person; no target means no achievement figure",
            # Round-4 J4-18: the sentences on the page a lead sends out are in Thai.
            "note_th": "เป้าหมายต้องมีคนตั้งไว้ก่อน ถ้ายังไม่มีเป้า จะไม่มีตัวเลขผลสำเร็จ",
            "note_en": "A person has to set a target first; with no target there is no achievement figure.",
            "allocation_hold_note_th": allocation_note_th,                          # J4-06
            "allocation_hold_note_en": allocation_note_en,
            "allocation_hold_customers": len(hold_customers),
        },
        "portfolio": {"current": current, "late": late, "npl": npl, "in_collection": len(items),
                      "unit": "customers in collection (closed contracts excluded), counted on the business date",
                      "unit_th": "นับหัวลูกค้าที่อยู่ในการติดตาม ณ วันทำการ (ไม่รวมสัญญาที่ปิดแล้ว)",
                      "unit_en": "Customers in collection on the business date (closed contracts excluded)",
                      "ratio_late_pct": str((Decimal(late) / Decimal(len(items) or 1) * 100).quantize(Decimal("0.1"))),
                      "ratio_definition": "late customers ÷ customers in collection on the business date (a head-count, not a period ratio)",
                      "ratio_definition_th": "ลูกค้าล่าช้า ÷ ลูกค้าที่อยู่ในการติดตาม ณ วันทำการ (นับหัว ไม่ใช่สัดส่วนตลอดช่วง)",
                      "ratio_definition_en": "Late customers ÷ customers in collection on the business date (a head-count, not a ratio over the period)",
                      # Round-4 J4-06: the caveat sits with the ratio it qualifies.
                      "allocation_hold_customers": len(hold_customers),
                      "allocation_hold_receipts": len(hold_receipts),
                      "allocation_hold_pending_decision": ALLOCATION_HOLD_PENDING_DECISION,
                      "allocation_hold_note_th": allocation_note_th,
                      "allocation_hold_note_en": allocation_note_en,
                      "period_of_ratio": "as of %s" % bd,
                      "period_of_ratio_th": "ณ วันที่ %02d/%02d/%d" % (bd.day, bd.month, bd.year),
                      "period_of_ratio_en": "as of %02d/%02d/%d" % (bd.day, bd.month, bd.year)},
        "promises": {"kept": kept, "broken": broken, "open": sum(1 for p in ptps if p["status"] == "OPEN"),
                     "kept_rate_pct": str((Decimal(kept) / Decimal(kept + broken or 1) * 100).quantize(Decimal("0.1"))),
                     "period_of_ratio": "all promises on record",
                     "period_of_ratio_th": "นับจากนัดชำระทั้งหมดที่มีในระบบ ไม่ใช่เฉพาะในสัปดาห์นี้",
                     "period_of_ratio_en": "counted over every promise on record, not only this week"},
        "npl_changes": npl_changes[-10:],
        "power_actions": power_actions[-10:],
        "service_issues_open": issues_open,
        "reviews_open": sum(1 for r in cs.reviews.values() if r["status"] == "OPEN"),
        # B13b: the focus is text a person typed; a number in it stops here too.
        "next_week_focus": weekly_figures.without_typed_numbers(FOCUS.get(period)),
        "counts_by_tier": data["meta"]["counts_by_tier"],
        "reconciliation": reconciliation(data),
        # Feedback Round 1, WP12 (design F15): five figures this payload never served —
        # additive keys, each with its definition line and its notes. `hold_customers`
        # is passed, not recomputed, so arrears_split's OD-02 hold names the same
        # customers as portfolio.allocation_hold_customers.
        **weekly_figures.build(bd, date.fromisoformat(start), date.fromisoformat(end),
                               items, cs, jstate, hold_customers, units=units),
    }


OFFICER_PERIOD_BASIS = {
    "contacts": "contact_log.occurred_at",
    "counted_contacts": "contact_log.occurred_at",
    "ptps_taken": "ptp.promise_date",
    "ptps_kept": "ptp.closed_on",
    "ptps_broken": "ptp.broken_detected_at or ptp.closed_on",
}


def _blank_officer(uid, start, end):
    return {"officer_uid": uid, "caseload": 0, "late": 0, "npl": 0,
            "contacts": 0, "counted_contacts": 0, "ptps_taken": 0, "ptps_kept": 0, "ptps_broken": 0,
            "contacts_all_time": 0, "counted_contacts_all_time": 0,
            "ptps_taken_all_time": 0, "ptps_kept_all_time": 0, "ptps_broken_all_time": 0,
            "period": "%s..%s" % (start, end)}


def officers(business_date=None):
    """Round-3 J3-12: every row carried `period` while nothing was filtered by it — a
    lead pasting the table reported 14 broken promises "this week" against promises
    dated July. The five activity columns are now counted INSIDE `period`; the all-time
    figures stay beside them under an explicit "ตลอดอายุ" name, and meta says which
    date each column was filtered on. caseload/late/npl remain a head-count as of the
    business date, the way the weekly tab states its own unit."""
    bd = business_date or settings.business_date
    start, end = _period(bd)
    inside = lambda stamp: bool(stamp) and start <= str(stamp)[:10] <= end
    cs = cases_domain.for_current()
    rows = {}
    for case in [c for c in cs.cases.values() if cases_domain.is_book_case(c)]:
        o = rows.setdefault(case["officer_uid"], _blank_officer(case["officer_uid"], start, end))
        o["caseload"] += 1
        o["late"] += case["payment_status"] == "LATE"
        o["npl"] += case["payment_status"] == "NPL"
    for r in cs.contact_log:
        o = rows.setdefault(r["officer_uid"], _blank_officer(r["officer_uid"], start, end))
        o["contacts_all_time"] += 1
        o["counted_contacts_all_time"] += bool(r.get("counted"))
        if inside(r.get("occurred_at")):
            o["contacts"] += 1
            o["counted_contacts"] += bool(r.get("counted"))
    for p in cs.ptps.values():
        o = rows.get(p["created_by"]) or rows.get(cs.cases[p["customer_uid"]]["officer_uid"])
        if o is None:
            continue
        kept = p["status"] in ("KEPT", "KEPT_PARTIAL")
        broken = p["status"] == "BROKEN"
        o["ptps_taken_all_time"] += 1
        o["ptps_kept_all_time"] += kept
        o["ptps_broken_all_time"] += broken
        o["ptps_taken"] += inside(p.get("promise_date"))
        o["ptps_kept"] += kept and inside(p.get("closed_on"))
        o["ptps_broken"] += broken and inside(p.get("broken_detected_at") or p.get("closed_on"))
    for o in rows.values():
        decided = o["ptps_kept"] + o["ptps_broken"]
        o["ptp_kept_rate_pct"] = str((Decimal(o["ptps_kept"]) / Decimal(decided or 1) * 100).quantize(Decimal("0.1"))) if decided else None
        decided_all = o["ptps_kept_all_time"] + o["ptps_broken_all_time"]
        o["ptp_kept_rate_all_time_pct"] = str((Decimal(o["ptps_kept_all_time"]) / Decimal(decided_all or 1) * 100).quantize(Decimal("0.1"))) if decided_all else None
    return sorted(rows.values(), key=lambda o: o["officer_uid"])


def bucket_flow(band_set_code=None):
    from .money.band_sets import resolve_band
    from .routers.journey import _aggregate
    band_set_code = band_set_code or "SOP_30_60_90"
    counts = {}
    for customer in journey.book_customers():
        _total, oldest, _band, _out = _aggregate(customer)
        # Ruling 43 / R4-F03: session-scoped read.
        status = cases_domain.contract_field_of(customer.contracts[0], "status") if customer.contracts else "PRE_COLLECTION"
        band = resolve_band(status, oldest, band_set_code)
        counts[band.code or "NONE"] = counts.get(band.code or "NONE", 0) + 1
    from .money import band_sets as _bs
    described = {r["code"]: r for r in _bs.describe()}
    row = described.get(band_set_code) or {"active": True}
    rec = reconciliation()
    return {"band_set_code": band_set_code,
            # Round-3 J3-11: a report run on a retired set says so on the report itself.
            "band_set_active": bool(row["active"]),
            "band_set_note_th": None if row["active"] else "ชุดช่วงอายุหนี้นี้ถูกปิดใช้งานแล้ว — ตัวเลขนี้อ้างอิงชุดที่เลิกใช้",
            "band_set_note_en": None if row["active"] else "This aging band set is deactivated — these figures use a retired set",
            "counts": counts, "as_of": str(settings.business_date),
            "total": sum(counts.values()), "unit": rec["unit_buckets"],
            "unit_th": rec["unit_buckets_th"], "unit_en": rec["unit_buckets_en"],
            "reconciliation": rec}
