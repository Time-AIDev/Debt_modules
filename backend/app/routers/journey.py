from .. import termination_archive
"""The journey endpoints — everything the rebuilt screens call that the pre-rebuild
API did not serve. All additive under /v1; every refusal is an errors.py factory.

The handlers read the fixture book through app.main's module attributes AT CALL TIME
(lazy import) so the conftest monkeypatch seam keeps working, and read/write journey
state through app.journey's per-session store.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Header, Query

from .. import audit
from .. import clock
from .. import customer_contact
from .. import errors
from .. import journey
from .. import payment_position
from .. import session as session_domain
from .. import sop
from ..config import PENDING, settings
from ..entities import EPC, SPV, entity_fields
from ..ladder import LADDER_MODES, LADDERS, stage_depth
from ..money import band_sets as _band_sets      # J4-13: the band's own Thai label

router = APIRouter()


def _main():
    from .. import main
    return main


def _cases():
    from .. import cases
    return cases


def _board():
    from .. import board
    return board


def _aggregate(customer):
    return _main()._customer_aggregate(customer)


def _customer_or_404(uid):
    customer = journey.customer_by_uid(uid)
    if customer is None:
        raise errors.not_found("customer")
    return customer


def _contract_or_404(uid):
    found = journey.contract_by_uid(uid)
    if found is None:
        raise errors.not_found("contract")
    return found


def _positive_amount(raw, pointer):
    """One money-input gate. Decimal('Infinity') passes a naive `<= 0` and
    Decimal('NaN') CRASHES one (comparisons raise) — the adversarial round
    recorded an Infinity receipt. is_finite() first, always."""
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError):
        raise errors.validation_failed([{
            "pointer": pointer, "code": "not_a_number",
            "message": "amount is not a number", "message_th": "จำนวนเงินไม่ถูกต้อง"}])
    if not amount.is_finite() or amount <= 0:
        raise errors.validation_failed([{
            "pointer": pointer, "code": "amount_not_positive",
            "message": "amount must be a finite number greater than zero",
            "message_th": "จำนวนเงินต้องเป็นค่าจำกัดและมากกว่าศูนย์"}])
    return amount


# --- scenarios and mode -----------------------------------------------------------

SCENARIOS = [
    {"code": "S01", "name": "Cash order", "owner": "EPC only"},
    {"code": "S02", "name": "Lease order", "owner": "SPV lease · EPC service"},
    {"code": "S03", "name": "Cancel before install — cause: customer", "owner": "Money forfeited"},
    {"code": "S04", "name": "Cancellation after installation", "owner": "Settle or NPL"},
    {"code": "S05", "name": "Cancel before install — cause: VOLT", "owner": "Full refund"},
    {"code": "S06", "name": "Cannot install — re-quote & re-sign", "owner": "Two parallel tracks"},
    {"code": "S07", "name": "NPL — contract assigned back to EPC", "owner": "EPC executes everything"},
    {"code": "S08", "name": "Lease restructure", "owner": "SPV, with an NPL exit"},
    {"code": "S09", "name": "Service order flow", "owner": "EPC only"},
    {"code": "S10", "name": "Invoice & money flow", "owner": "EPC ⇄ SPV ⇄ customer"},
    {"code": "S11", "name": "Cash default — balance not paid", "owner": "EPC only"},
    {"code": "S12", "name": "Repossession & redeployment", "owner": "EPC only"},
]


@router.get("/v1/scenarios")
def scenarios():
    demo = {}
    for customer in journey.book_customers():
        for code in customer.scenario_codes:
            demo.setdefault(code, []).append(customer.customer_no)
    return {
        "source": "VOLT ERP — SPV/EPC Scenario Workflows v20.0",
        "scenarios": [{**s, "demo_customers": demo.get(s["code"], [])} for s in SCENARIOS],
    }


@router.get("/v1/ladder-mode")
def get_ladder_mode():
    state = journey.for_current()
    return {"ladder_mode": state.ladder_mode, "modes": list(LADDER_MODES),
            "note": "MANUAL suppresses the indicative rung entirely (R6); stages always move only by human action."}


@router.put("/v1/ladder-mode")
def put_ladder_mode(body: dict = Body(...)):
    audit.describe(act="LADDER_MODE_SET", detail={"mode": (body or {}).get("mode")})
    mode = (body or {}).get("ladder_mode")
    if mode not in LADDER_MODES:
        raise errors.validation_failed([{
            "pointer": "/ladder_mode", "code": "unknown_mode",
            "message": "ladder_mode must be one of %s" % (LADDER_MODES,),
            "message_th": "โหมดบันไดไม่ถูกต้อง"}])
    state = journey.for_current()
    state.ladder_mode = mode
    return {"ladder_mode": mode}


# --- the working list (R9–R11) ----------------------------------------------------

def money_position(customer, total=None):
    """Judge J-07 / J-31: one figure the customer is asked for, and where the rest
    comes from. aggregate_overdue = instalments overdue + penalty the engine accrued
    at the decided rate (ruling 87); the penalty IS now invoiced to PEAK as a draft, and
    the sheet's own late-fee cell is shown beside it so the officer sees both books."""
    from ..config import settings
    main = _main()
    instalments = Decimal("0.00")
    penalty = Decimal("0.00")
    per_contract = []
    for k in customer.contracts:
        _c, dpd, _band, block, _period = main._contract_view(k)
        from .. import invoice_reviews
        imported = invoice_reviews.contract_arrears(customer, k, journey.for_current(), settings.business_date)
        arrears = block.cumulative_arrears
        if imported is not None:
            arrears, dpd = imported
        # cumulative_arrears is the overdue instalment lines only (arrears.py `arr`);
        # the penalty is accrued beside it, never inside it. Round-2 thip T2-01 caught
        # the earlier subtraction, which invented a 371,932 "instalment" figure.
        penalty += block.penalty_accrued_unbilled
        instalments += arrears
        per_contract.append({"uid": k.uid, "product": k.product, "instalments_overdue": str(arrears),
                             "penalty": str(block.penalty_accrued_unbilled), "oldest_dpd": dpd,
                             "pmt": str(getattr(k, "pmt", None)) if getattr(k, "pmt", None) is not None else None,
                             # Ruling 43 / R4-F01: session-scoped read.
                             "fee_state": _cases().fee_state_of(k)})
    sheet = getattr(customer, "sheet", None) or {}
    row = sheet.get("leasing") or sheet.get("cash") or {}
    sheet_fee = row.get("late_fees")
    rate_pct_day = str((settings.late_payment_daily_rate * 100).normalize())
    # Round-3 J3-28: the sentence named only the rate, so the figure never reconciled on
    # sight — วิชัย 25,000.00 × 0.3% × (339 − 14) = 24,375.00 exactly. The 14-day grace
    # (late_payment_grace_days, OD-31) is the missing term; it goes IN the sentence.
    grace = settings.late_payment_grace_days
    if penalty > 0:
        note_en = ("The amount to ask the customer for is the overdue instalments, %s baht (the arrears on screen); the app accrues "
                   "a separate penalty of %s baht at the decided rate of %s%%/day, counted after the %d-day grace period — "
                   "on (days overdue − %d). It is not in the arrears but has been sent to PEAK as a draft invoice"
                   % (instalments, penalty, rate_pct_day, grace, grace))
        note_th = ("ยอดที่ขอให้ลูกค้าชำระคือค่างวดค้าง %s บาท (ยอดค้างบนหน้าจอ); แอปคำนวณค่าปรับไว้ต่างหากอีก %s บาทในอัตราที่ตัดสินแล้ว %s%%/วัน "
                   "โดยเริ่มนับหลังพ้นระยะผ่อนผัน %d วัน — คิดจาก (จำนวนวันค้าง − %d) "
                   "ซึ่งยังไม่รวมในยอดค้างแต่ถูกส่งเป็นใบแจ้งหนี้ไปยัง PEAK แล้วในรูปแบบร่าง"
                   % (instalments, penalty, rate_pct_day, grace, grace))
    else:
        note_en = ("All the arrears are instalments; no penalty in the app yet — the penalty starts after the %d-day "
                   "grace period at the decided rate" % grace)
        note_th = ("ยอดค้างทั้งหมดเป็นค่างวด ยังไม่มีค่าปรับในแอป — ค่าปรับเริ่มนับหลังพ้นระยะผ่อนผัน %d วัน "
                   "ในอัตราที่ตัดสินแล้ว" % grace)
    if sheet_fee:
        note_th += " · ชีตบันทึกค่าปรับ %s บาท (ค้าง %s วัน) ซึ่งแอปยังไม่คิด" % (sheet_fee, row.get("days_late"))
        note_en += " · the sheet records a late fee of %s baht (%s days late), which the app does not charge" % (sheet_fee, row.get("days_late"))
    if len(per_contract) > 1:
        # N2-03: the header is the SUM across the customer's contracts, and says so.
        _sum = " + ".join("%s %s" % (c["uid"], c["instalments_overdue"]) for c in per_contract)
        note_th += " · ยอดค้างรวมจาก %d สัญญา (%s)" % (len(per_contract), _sum)
        note_en += " · arrears summed across %d contracts (%s)" % (len(per_contract), _sum)
    from .. import payment_summary, instalment_evidence
    review_entries = []
    for contract in customer.contracts:
        if instalment_evidence.required(contract):
            peak_cycles, _, _ = payment_summary.peak_cycles_for(contract.uid, journey.for_current())
            review_entries.append(payment_summary.for_contract(contract, settings.business_date, Decimal("0"),
                                                               peak_cycles=peak_cycles))
    review_amount = sum((Decimal(entry["review_amount"]) for entry in review_entries), Decimal("0"))
    review_required = any(not entry["schedule_verified"] or entry["review_count"]
                          or entry["unplaced_peak_details"] for entry in review_entries)
    return {
        "review_amount": str(review_amount), "review_required": bool(review_required),
        "collection_basis": "CONFIRMED_EVIDENCE" if review_entries else "LEDGER",
        "amount_to_ask": str(instalments),
        "instalments_overdue": str(instalments),
        "penalty_accrued_unbilled": str(penalty),
        "per_contract": per_contract,
        "contract_count": len(per_contract),
        "summed_across_contracts": len(per_contract) > 1,
        "penalty_invoicing_enabled": settings.penalty_invoicing_enabled,
        "penalty_rate_pct_per_day": rate_pct_day,
        "penalty_rule_owner": "CF1 / OD-31",
        "penalty_grace_days": grace,                              # J3-28
        "penalty_formula_th": "ยอดค้าง × %s%%/วัน × (จำนวนวันค้าง − %d)" % (rate_pct_day, grace),
        "penalty_formula_en": "arrears × %s%%/day × (days overdue − %d)" % (rate_pct_day, grace),
        "sheet_late_fees": sheet_fee,
        "sheet_days_late": row.get("days_late"),
        "reconciles": (total is None) or (instalments == total),
        "aggregate_overdue_includes_penalty": False,
        "note_th": note_th,
        "note_en": note_en,
    }


def _work_item(state, customer, business_date, case_state=None):
    main = _main()
    total, oldest, band, outstanding = _aggregate(customer)
    position = payment_position.build(customer, state, business_date)
    from .. import invoice_reviews
    contract_outstanding = invoice_reviews.contract_outstanding(customer, state)
    outstanding = Decimal(position["due_outstanding_amount"])
    # Delta-100 D2a: the row's own 0..100 risk score, from the aggregate just
    # computed (the same snapshot the row serves) and the case's own broken-PTP
    # and last-contact record. One computation, served on the row and its nested
    # customer alike, so /v1/today, /v1/workbook, /v1/working-list and the case's
    # work_item all read the same number. Unknown history counts as stale
    # (app.risk.score's own rule).
    cs = case_state or _cases().for_current()
    case = cs.cases.get(customer.uid) or {}
    risk_score = journey.risk_score_for_customer(
        customer, business_date, aggregate=(total, oldest, band, outstanding))
    lock = main.contact_log.locks_for(customer.identity_key, business_date, level="PERSON")
    missed = max((journey.missed_count(k) for k in customer.contracts), default=0)
    ptp = journey.open_ptp_for(state, customer.uid)
    issues = journey.open_issue_for(state, customer.uid)
    reviews = journey.open_review_for(state, customer.uid)
    service = [state.service_accounts.get(k.uid)
               for k in customer.contracts]
    service = [s for s in service if s]
    entity = customer.contracts[0].entity if customer.contracts else None
    return {
        "customer": {
            "uid": customer.uid,
            "customer_no": customer.customer_no,
            # F12 / feedback-r2 TASK-104: the identity line prints the Volt ID first, and
            # every place that builds this customer block reads it from here.
            "volt_id": getattr(customer, "volt_id", None),
            "display_name": customer.display_name,
            # R5-F01: phone_masked alone cannot say whether this is a real mask or the
            # "no number on file" placeholder — 159 of 212 rows serve the literal
            # string "xxx-xxx-xxxx" for both. This is the one shared place that builds
            # the customer object for /v1/today, /v1/workbook, /v1/working-list and
            # /v1/cases/by-customer/{uid} alike, so one field here reaches all four.
            # Feedback Round 1 / WP9 (F9 (a)): a number a person entered wins
            # phone_e164 and makes phone_on_file true; phone_masked is untouched and
            # phone_on_sheet keeps the import's own answer (customer_contact.py).
            **customer_contact.phone_fields(customer.uid, customer),
            "line_id": customer.line_id,
            "meta_id": getattr(customer, "meta_id", None),
            "contract_count": len(customer.contracts),
            # Ruling 40: reassignment lands in the per-session overlay, never on the
            # shared Customer fixture (mirrors recovery_overlay below).
            "officer": state.officer_overlay.get(customer.uid, customer.officer),
            # Delta-100 D2a: the same figure the row serves, beside the identity.
            "risk_score": risk_score,
        },
        **(entity_fields(entity) if entity else {"entity": None, "company_id": None}),
        "data_source": customer.data_source,
        "order_ref": customer.order_ref,
        "scenario_codes": list(customer.scenario_codes),
        # Delta-100 D2a: the record and the rows read the served score — never a
        # re-derivation on the screen.
        "risk_score": risk_score,
        "aggregate_overdue": str(total),
        "aggregate_outstanding": str(outstanding),
        "contract_outstanding": str(contract_outstanding),
        "oldest_dpd": oldest,
        "aging_bucket": band.code,
        "band_set_code": band.band_set_code,
        # Round-4 J4-13: the ช่วงอายุหนี้ column reads THIS, so a set authored in the app
        # can never print a bare S4_MID at an officer's desk.
        "aging_bucket_label_th": _band_sets.label_for(band.band_set_code, band.code),
        "aging_bucket_label_en": _band_sets.label_for(band.band_set_code, band.code, "en"),
        # Ruling 43 / R4-F01: session-scoped read.
        "fee_state": _cases().fee_state_of(customer.contracts[0]) if customer.contracts else None,
        "money_position": money_position(customer, total),
        # Feedback Round 1 / Task 10, plan 2026-09-11 §1.4: the position rides beside
        # the money. Covers /v1/today items and (via case_detail's shared call) the
        # case's own work_item in one place — do not add it a second time there.
        "payment_position": position,
        **_board().serve(customer, oldest, case_state=cs, journey_state=state),
        "recovery_stage": state.recovery_overlay.get(customer.uid, customer.recovery_stage),
        "ladder": journey.ladder_payload_for(state, customer, oldest, missed),
        "priority_reason": journey.priority_reason(state, customer, total, business_date),
        "open_ptp": {"uid": ptp["uid"], "promised_amount": ptp["promised_amount"],
                     "promise_date": ptp["promise_date"],
                     # D05 / TASK-221: set when a receipt landed before the promise date.
                     "paid_before_due": ptp.get("paid_before_due")} if ptp else None,
        # Round-4 R4-F31/R4-F54: ruling 7's class, second instance. The cases store is
        # BOTH the write model (every PTP endpoint) and the read model (tier_for, all
        # screen sites, both exports). Recomputing the count off the journey store gave
        # a second answer on 15/151 rows and made /v1/working-list?bucket=BROKEN_PTP
        # find 1 of 14. Read the owner.
        "broken_ptp_count": case.get("broken_ptp_count", 0),
        "open_service_issues": len(issues),
        # Judge J-12b: a review opened on the case (cases.py) counts too, not only the
        # journey's own review store.
        "manager_review_open": len(reviews) + _case_reviews_open(customer.uid, cs),
        "service_billing": service[0] if service else None,
        "contact_lock": {
            "state": "LOCKED" if lock else "OPEN",
            "locked_by": lock[0].officer if lock else None,
            "locked_at": str(lock[0].taken_at) if lock else None,
            # Round-3 J3-15: what the officer reads is the business day in local time.
            "locked_at_local_th": clock.local_stamp_th(lock[0].taken_at) if lock else None,
            "locked_at_local_en": clock.local_stamp_en(lock[0].taken_at) if lock else None,
            "result": lock[0].result if lock else None,
        },
        # Round-4 ruling 62 (closes R4-F55, the fifteenth and last authorised test
        # edit): renamed from "last_contact". This is main.contact_log.attempts —
        # THIS SESSION's own dialling, empty at seed and filled only by
        # POST /v1/contacts — a different fact from case.last_contact_at (the
        # imported history, set on 8/151) one level down at item["case"]. The two
        # no longer share a name. Read item.case.* for the imported history; this
        # key is deliberately not it. Moves test_round4.py:78, the J4-01
        # business-clock guard, cited there.
        "session_last_contact": _last_contact(main, customer),
    }


def _case_reviews_open(customer_uid, case_state=None):
    from .. import cases as cases_domain
    cs = case_state or cases_domain.for_current()
    return sum(1 for r in cs.reviews.values() if r["customer_uid"] == customer_uid and r["status"] == "OPEN")


def _last_contact(main, customer):
    attempts = [a for a in main.contact_log.attempts
                if a.customer_key == customer.identity_key]
    if not attempts:
        return None
    last = attempts[-1]
    return {"at": str(last.at), "channel": last.channel,
            "disposition": last.disposition, "officer": last.officer}


def _bucket_match(state, item, bucket, business_date):
    if bucket == "DUE_TODAY":
        return item["open_ptp"] is not None and item["open_ptp"]["promise_date"] == str(business_date)
    if bucket == "OVERDUE":
        return Decimal(item["aggregate_overdue"]) > 0
    if bucket == "PTP_DUE":
        return item["open_ptp"] is not None
    if bucket == "BROKEN_PTP":
        return item["broken_ptp_count"] > 0
    if bucket == "SERVICE_ISSUE":
        return item["open_service_issues"] > 0
    if bucket == "UNREACHABLE":
        # Round-4 F3 BE-4: "UNREACHABLE" is not a member of PRIORITY_REASONS (it
        # belongs to REVIEW_REASONS) — this bucket found nothing, ever, on any book.
        # unreachable_run is the count that already exists for exactly this question.
        return _cases().unreachable_run(_cases().for_current(),
                                        item["customer"]["uid"])["unreachable_since_last_reach"] > 0
    if bucket == "ARRANGEMENT":
        return any(a["customer_uid"] == item["customer"]["uid"]
                   for a in state.arrangements.values())
    if bucket == "NPL_RECOVERY":
        return stage_depth(item["ladder"]["stage"]) >= 3
    return False


@router.get("/v1/working-list")
def working_list(bucket: str = Query(default=None), entity: str = Query(default=None)):
    """The tier-sorted queue (R11: PTP due today → biggest arrears → deepest ladder
    → broken PTP, applied sequentially). Grouped per customer, never per contract."""
    state = journey.for_current()
    business_date = settings.business_date
    if bucket and bucket not in journey.WORKING_BUCKETS:
        raise errors.working_list_bucket_unknown(bucket, journey.WORKING_BUCKETS)
    if entity and entity not in (EPC, SPV):
        raise errors.validation_failed([{
            "pointer": "/entity", "code": "unknown_entity",
            "message": "entity must be EPC or SPV", "message_th": "ระบุบริษัทไม่ถูกต้อง"}])

    ranked = []
    for customer in journey.book_customers():
        total, _oldest, _band, _outstanding = _aggregate(customer)
        ranked.append((journey.priority_key(state, customer, total, business_date), customer))
    ranked.sort(key=lambda pair: pair[0])

    items = [_work_item(state, customer, business_date) for _key, customer in ranked]
    if entity:
        items = [i for i in items if i["entity"] == entity]
    if bucket:
        items = [i for i in items if _bucket_match(state, i, bucket, business_date)]

    unlocked = [i for i in items if i["contact_lock"]["state"] == "OPEN"
                and Decimal(i["aggregate_overdue"]) > 0]
    tiers = {reason: sum(1 for i in items if i["priority_reason"] == reason)
             for reason in journey.PRIORITY_REASONS}
    return {
        "run": {"business_date": str(business_date), "job": "working-list",
                "ordering": "PTP_DUE_TODAY, then largest arrears, then deepest ladder, then broken PTP (R11)",
                # Round-4 §4.12: not a fix — the two next_up rules can diverge by design
                # (different populations, different orders) and both are pinned. This
                # names which route REQ-COL-071 (Amendment v2.6 §3.2) makes authoritative.
                "superseded_by": "GET /v1/today — REQ-COL-071 (Amendment v2.6 §3.2) supersedes R11's order"},
        "items": items,
        "meta": {
            "total": len(items),
            "counts_by_reason": tiers,
            "next_up": unlocked[0]["customer"]["uid"] if unlocked else None,
            "buckets": list(journey.WORKING_BUCKETS),
            "ladder_mode": state.ladder_mode,
        },
    }


# --- PTPs -------------------------------------------------------------------------

@router.post("/v1/ptps", status_code=201)
def create_ptp(body: dict = Body(...)):
    audit.describe(act="PTP_CREATED")
    customer = _customer_or_404(body.get("customer_uid"))
    state = journey.for_current()
    existing = journey.open_ptp_for(state, customer.uid)
    if existing:
        raise errors.ptp_already_open(customer.uid, existing["uid"])
    amount = _positive_amount(body.get("promised_amount"), "/promised_amount")
    try:
        promise = date.fromisoformat(str(body.get("promise_date")))
    except (TypeError, ValueError):
        raise errors.validation_failed([{
            "pointer": "/promise_date", "code": "not_a_date",
            "message": "promise_date must be YYYY-MM-DD", "message_th": "รูปแบบวันที่ไม่ถูกต้อง"}])
    if promise < settings.business_date:
        raise errors.ptp_date_in_past(promise, settings.business_date)
    ptp = journey.make_ptp(state, customer.uid, amount, promise,
                           body.get("by") or "Nok",
                           contract_uids=[k.uid for k in customer.contracts],
                           source_contact_id=body.get("source_contact_id"),
                           kind=body.get("kind") or "LEASE")
    return {"ptp": ptp}


@router.get("/v1/ptps")
def list_ptps(customer_uid: str = Query(default=None), status: str = Query(default=None)):
    state = journey.for_current()
    rows = list(state.ptps.values())
    if customer_uid:
        rows = [p for p in rows if p["customer_uid"] == customer_uid]
    if status:
        if status not in journey.PTP_STATUSES:
            raise errors.validation_failed([{
                "pointer": "/status", "code": "unknown_status",
                "message": "status must be one of %s" % (journey.PTP_STATUSES,),
                "message_th": "สถานะไม่ถูกต้อง"}])
        rows = [p for p in rows if p["status"] == status]
    return {"ptps": rows, "counts": {s: sum(1 for p in state.ptps.values() if p["status"] == s)
                                     for s in journey.PTP_STATUSES}}


@router.post("/v1/ptps/{uid}:close")
def close_ptp(uid: str, body: dict = Body(...)):
    audit.describe(act="PTP_CLOSED", subject=("ptp", uid), detail={"outcome": (body or {}).get("outcome")})
    state = journey.for_current()
    ptp = state.ptps.get(uid)
    if ptp is None:
        raise errors.not_found("ptp")
    if ptp["status"] != "OPEN":
        raise errors.ptp_already_closed(uid, ptp["status"])
    outcome = (body or {}).get("outcome")
    if outcome not in ("KEPT", "KEPT_PARTIAL", "BROKEN"):
        raise errors.validation_failed([{
            "pointer": "/outcome", "code": "unknown_outcome",
            "message": "outcome must be KEPT, KEPT_PARTIAL or BROKEN",
            "message_th": "ผลนัดชำระไม่ถูกต้อง"}])
    ptp["status"] = outcome
    ptp["closed_on"] = str(settings.business_date)
    ptp["receipt_uid"] = body.get("receipt_uid")
    review_uid = None
    if outcome == "BROKEN":
        # The flow (part 3): a broken PTP is logged AND routed to Manager Review.
        review = journey.make_review(state, ptp["customer_uid"], "BROKEN_PTP",
                                     source_ref=uid, opened_by=body.get("by") or "system",
                                     snapshot=_review_snapshot(state, ptp["customer_uid"]))
        ptp["broken_review_uid"] = review["uid"]
        review_uid = review["uid"]
    return {"ptp": ptp, "manager_review_uid": review_uid}


@router.post("/v1/ptps/{uid}:cancel")
def cancel_ptp(uid: str, body: dict = Body(...)):
    audit.describe(act="PTP_CANCELLED", subject=("ptp", uid))
    state = journey.for_current()
    ptp = state.ptps.get(uid)
    if ptp is None:
        raise errors.not_found("ptp")
    if ptp["status"] != "OPEN":
        raise errors.ptp_already_closed(uid, ptp["status"])
    reason = (body or {}).get("reason")
    if not reason or not str(reason).strip():
        raise errors.validation_failed([{
            "pointer": "/reason", "code": "required",
            "message": "Cancelling a promise requires a logged reason.",
            "message_th": "การยกเลิกนัดชำระต้องระบุเหตุผล"}])
    ptp["status"] = "CANCELLED"
    ptp["closed_on"] = str(settings.business_date)
    ptp["cancel_reason"] = str(reason).strip()
    return {"ptp": ptp}


# --- service issues ---------------------------------------------------------------

@router.get("/v1/service-issues")
def list_issues(customer_uid: str = Query(default=None)):
    state = journey.for_current()
    rows = list(state.issues.values())
    if customer_uid:
        rows = [i for i in rows if i["customer_uid"] == customer_uid]
    return {"issues": rows}


@router.post("/v1/service-issues", status_code=201)
def create_issue(body: dict = Body(...)):
    audit.describe(act="SERVICE_ISSUE_CREATED")
    customer = _customer_or_404(body.get("customer_uid"))
    routed_to = (body or {}).get("routed_to")
    if routed_to not in ("CS", "O_AND_M", "OPS"):
        raise errors.validation_failed([{
            "pointer": "/routed_to", "code": "unknown_route",
            "message": "routed_to must be CS, O_AND_M or OPS",
            "message_th": "หน่วยงานปลายทางไม่ถูกต้อง"}])
    owners = {"CS": "Fah (CS)", "O_AND_M": "Krit (O&M)", "OPS": "Beam (Ops)"}
    issue = journey.make_issue(journey.for_current(), customer.uid, routed_to,
                               (body.get("summary") or "").strip() or "(no summary)",
                               owner=owners[routed_to])
    return {"issue": issue}


@router.post("/v1/service-issues/{uid}:resolve")
def resolve_issue(uid: str, body: dict = Body(default={})):
    audit.describe(act="SERVICE_ISSUE_RESOLVED", subject=("service_issue", uid))
    state = journey.for_current()
    issue = state.issues.get(uid)
    if issue is None:
        raise errors.not_found("service issue")
    issue["status"] = "RESOLVED"
    issue["resolved_on"] = str(settings.business_date)
    issue["resolution"] = (body or {}).get("note")
    return {"issue": issue, "note": "Customer returns to the follow-up loop (flow part 3)."}


# --- board persistence ------------------------------------------------------------

@router.post("/v1/board/moves", status_code=201)
def board_move(body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """No longer a move. The column is derived (app/board.py), so asking for a
    different one is a claim that the case data is wrong.

    Toward higher severity the officer knows something the data has not caught up to,
    and it applies with a reason. Toward lower severity — or onto a column outside the
    derived four — it is a claim the case is healthier than the record says, which is
    the move that makes a desk look better than it is. Nothing moves; a Manager decides.
    """
    audit.describe(act="BOARD_MOVED")
    from .. import board as board_mod
    main = _main()
    customer = _customer_or_404(body.get("customer_uid"))
    destination = (body or {}).get("to_column_id")
    known = {c["column_id"] for c in main.BOARD_COLUMNS}
    if destination not in known:
        raise errors.destination_column_unknown(destination)

    reason = (body.get("reason") or "").strip()
    if not reason:
        raise errors.board_move_reason_required(customer.uid, destination)

    cs = _cases().for_current()
    case = cs.cases.get(customer.uid)
    # Spec §9a is written against the REQUEST, not against one direction. One review at
    # a time per case, so a case that already has one open refuses a board move
    # whichever way it points — and this is checked before the direction is decided,
    # because the direction is not what makes it wrong.
    #
    # It sat inside the BACKWARD branch and a forward move applied straight over a card
    # that was waiting for a Manager. The card then carried board_override AND
    # board_pending_review_uid at once, which the model has no meaning for: the screen
    # renders only the pending chip, so the officer read "waiting for a Manager" on a
    # card that had already moved, and the Manager's later answer replaced the forward
    # override with no event and no marker.
    open_uid = case.get("review_uid") if case else None
    if open_uid and cs.reviews[open_uid]["status"] == "OPEN":
        raise errors.board_move_review_open(customer.uid, open_uid,
                                            cs.reviews[open_uid]["reason"])

    _total, oldest, _band, _out = main._customer_aggregate(customer)
    # TWO different questions, and they stop agreeing the moment an override is live.
    #
    # `served` is what the officer is looking at — `column_for` returns the live
    # override's column when there is one — so FORWARD/BACKWARD is judged against it,
    # and so is `from_column_id` on the way out. `derived` is what the case data says
    # on its own, and THAT is the pin `board.column_for` compares against on every read
    # to decide whether the grant has been outlived (spec §6).
    #
    # Pinning against `served` pins a new override against the previous override, so
    # the pin can never equal `derive()` and §6 deletes the grant on the very next
    # read — a Manager's approved decision included. Do not collapse these into one
    # call; the values look interchangeable and are not.
    served = board_mod.column_for(customer, oldest)
    derived = board_mod.derive(**board_mod.facts_for(customer, oldest))
    try:
        direction = board_mod.direction_of(destination, served)
    except board_mod.BoardError as exc:
        if exc.code == "board_move_same_column":
            raise errors.board_move_same_column(served)
        raise

    state = journey.for_current()
    who = body.get("by") or x_volt_officer or "unknown"
    record = {
        "customer_uid": customer.uid, "to_column_id": destination,
        "derived_at_grant": derived, "direction": direction, "reason": reason,
        "requested_by": who, "requested_on": str(settings.business_date),
        "review_uid": None, "approved_by": None, "approved_on": None,
    }

    if direction == "FORWARD":
        state.board_overrides[customer.uid] = record
        return {"customer_uid": customer.uid, "from_column_id": served,
                "to_column_id": destination, "direction": direction,
                "applied": True, "review_uid": None,
                "moved_on": str(settings.business_date)}

    if case is None:
        raise errors.not_found("case")
    # Identity by id, display by name: a column id is how the record points at a
    # column, never how a human is asked about one. `main.BOARD_COLUMNS` is the served
    # column list and already carries the name, so this reads the same source the
    # `known` check above reads — no second vocabulary, no new import. It has no Thai
    # name yet (leg F change request E2), so the Thai sentence names the columns in
    # English rather than inventing a second Thai label set beside the client's
    # `board.col.*`.
    names = {c["column_id"]: c["name"] for c in main.BOARD_COLUMNS}
    from_name, to_name = names.get(served, served), names.get(destination, destination)
    # `question` is the ENGLISH text and `question_th` its twin — the idiom of the
    # POWER_CUTOFF_ASK call at cases.py:1292. Passing the Thai positionally made
    # `question_en` Thai, so the next reader of the English field got Thai.
    question_en = "Approve moving %s from %s to %s — %s" % (
        customer.display_name, from_name, to_name, reason)
    question_th = "ขออนุมัติย้าย %s จาก %s ไป %s — %s" % (
        customer.display_name, from_name, to_name, reason)
    review = _cases().request_review(cs, case, "BOARD_MOVE_ASK", question_en,
                                     by=who, question_th=question_th)
    record["review_uid"] = review["uid"]
    # Held, not applied. `board.column_for` never reads a record whose review is open,
    # so the card stays where the data put it until a Manager answers.
    #
    # There is deliberately no clear of this on the applied path above. A pending record
    # exists only while its BOARD_MOVE_ASK review is OPEN — `cases.answer_review` pops it
    # on the way to granting or refusing, and nothing else closes a board review — and
    # the guard at the top of this function refuses any move while that review is open.
    # So the two records cannot coexist, and a clear that can never run would imply they
    # can.
    state.board_pending[customer.uid] = record
    return {"customer_uid": customer.uid, "from_column_id": served,
            "to_column_id": destination, "direction": direction,
            "applied": False, "review_uid": review["uid"],
            "moved_on": None}


@router.post("/v1/recovery-board/moves", status_code=201)
def recovery_board_move(body: dict = Body(...)):
    customer = _customer_or_404(body.get("customer_uid"))
    to_stage = (body or {}).get("to_stage")
    if to_stage not in journey.RECOVERY_BOARD_STAGES:
        raise errors.recovery_stage_unknown(to_stage, journey.RECOVERY_BOARD_STAGES)
    state = journey.for_current()
    previous = state.recovery_overlay.get(customer.uid, customer.recovery_stage)
    reason = (body or {}).get("reason")
    backwards = (journey.RECOVERY_BOARD_STAGES.index(to_stage)
                 < journey.RECOVERY_BOARD_STAGES.index(previous))
    if backwards and (not reason or not str(reason).strip()):
        raise errors.validation_failed([{
            "pointer": "/reason", "code": "reversal_reason_required",
            "message": "A leftward move is a reversal and requires a logged reason.",
            "message_th": "การย้อนขั้นต้องระบุเหตุผล"}])
    state.recovery_overlay[customer.uid] = to_stage
    # A reversal is the move a supervisor asks about first; the trail names both
    # ends and, when it went backwards, why.
    from .. import audit
    audit.describe(act="RECOVERY_STAGE_MOVED", subject=("customer", customer.uid),
                   detail={"from": previous, "to": to_stage,
                           "reversal": backwards, "reason": reason})
    return {"customer_uid": customer.uid, "from_stage": previous, "to_stage": to_stage,
            "reversal": backwards, "reason": reason,
            "moved_on": str(settings.business_date)}


# --- lease ladder cases -----------------------------------------------------------

# Round 7 / R7-D01. `propose_restructure` below holds the rule for whether a case may
# be offered a restructure. Until now that rule lived ONLY inside the POST, so a screen
# wanting to know "may this case be proposed?" had two options: call the endpoint and
# read the 422, or re-implement the predicate. The second is a workflow rule invented by
# the interface, which contract §3 forbids; the first makes a refusal out of a question.
#
# So the rule is extracted, the endpoint calls it, and the case payload carries its
# answer. One predicate, two readers, and it cannot drift.
def restructure_eligibility(state, case):
    """(eligible, code, message_th) — SOP step 15's gate, as the POST enforces it."""
    offered = (stage_depth(case["stage"]) >= 2
               or any(h["stage"] == "RESTRUCTURE_OFFER_60" for h in case["stage_history"]))
    if not offered:
        return False, "restructure_not_offered", "เคสนี้ยังไม่ถึงขั้นเสนอปรับโครงสร้างหนี้"
    if case.get("restructured"):
        return False, "second_restructure_forbidden", "สัญญานี้ปรับโครงสร้างไปแล้วครั้งหนึ่ง ทำซ้ำไม่ได้"
    existing = state.restructures.get(case.get("restructure_uid"))
    if existing and existing["status"] in ("PROPOSED", "APPROVED", "ACTIVE"):
        return False, "restructure_in_flight", "มีข้อเสนอปรับโครงสร้างที่ยังดำเนินอยู่"
    return True, None, None


RESTRUCTURE_REFUSED_EN = {
    "restructure_not_offered": "This case has not yet reached the restructure-offer step",
    "second_restructure_forbidden": "This contract has already been restructured once and cannot be again",
    "restructure_in_flight": "A restructure proposal is still in progress",
}


def _restructure_view(state, case):
    eligible, code, why_th = restructure_eligibility(state, case)
    rst = state.restructures.get(case.get("restructure_uid"))
    return {
        "eligible": eligible, "refused_code": code, "refused_th": why_th,
        "refused_en": RESTRUCTURE_REFUSED_EN.get(code),
        "current": rst,
        "may_approve_roles": ["MANAGER", "OWNER"],
    }


def _case_payload(state, case):
    found = journey.contract_by_uid(case["contract_uid"])
    dpd = missed = None
    band_pair = {}
    risk_score = None
    if found:
        main = _main()
        _customer, contract = found
        _c, dpd, band, block, _p = main._contract_view(contract)
        missed = journey.missed_count(contract)
        # Delta-100 D2a: the lease/cash case list carries the same 0..100 score the
        # record reads. A case whose customer does not resolve serves None.
        risk_score = journey.risk_score_for_customer(_customer, settings.business_date)
        from ..money.band_sets import resolve_band
        # Ruling 43 / R4-F03: session-scoped read — never contract.status directly.
        legacy = resolve_band(_cases().contract_field_of(contract, "status"), dpd, "LEGACY_LDR")
        band_pair = {
            "aging_bucket": band.code, "band_set_code": band.band_set_code,
            "legacy_band": {"aging_bucket": legacy.code, "band_set_code": legacy.band_set_code},
            "arrears": str(block.cumulative_arrears),
            "outstanding_balance": str(block.closing_balance),
        }
    kind = case.get("ladder", "LEASE")
    return {
        **case,
        **band_pair,
        "days_past_due": dpd,
        # Delta-100 D2a: served beside the money it is derived from.
        "risk_score": risk_score,
        # R7-D01: SOP step 15's gate, answered on the read so the screen never has to
        # POST to find out, and never has to guess.
        "restructure": _restructure_view(state, case),
        "missed_instalments": missed,
        "ladder_detail": (
            __import__("app.ladder", fromlist=["ladder_payload"]).ladder_payload(
                kind, case["stage"], dpd, missed, mode=state.ladder_mode)
        ),
    }


@router.get("/v1/cases")
def list_cases(stage: str = Query(default=None)):
    state = journey.for_current()
    rows = [_case_payload(state, c) for c in state.cases.values()]
    if stage:
        rows = [r for r in rows if r["stage"] == stage]
    return {"cases": rows}


@router.get("/v1/cases/{uid}")
def get_case(uid: str):
    state = journey.for_current()
    case = state.cases.get(uid)
    if case is None:
        raise errors.not_found("case")
    payload = _case_payload(state, case)
    payload["restructure"] = state.restructures.get(case.get("restructure_uid"))
    payload["npl"] = state.npl_cases.get(case.get("npl_uid"))
    return payload


LEASE_STAGES = ("NORMAL",) + tuple(r["stage"] for r in LADDERS["LEASE"])
CASH_STAGES = ("BALANCE_DUE",) + tuple(r["stage"] for r in LADDERS["CASH"])


@router.post("/v1/cases/{uid}:advance")
def advance_case(uid: str, body: dict = Body(...)):
    audit.describe(act="CASE_ADVANCED", subject=("case", uid))
    state = journey.for_current()
    case = state.cases.get(uid)
    if case is None:
        raise errors.not_found("case")
    to_stage = (body or {}).get("to_stage")
    by = (body or {}).get("by") or "Nok"
    role = (body or {}).get("role") or "OFFICER"
    note = (body or {}).get("note")
    if to_stage not in LEASE_STAGES or to_stage == "NORMAL":
        raise errors.ladder_stage_unknown(to_stage, [s for s in LEASE_STAGES if s != "NORMAL"])

    current_idx = LEASE_STAGES.index(case["stage"])
    target_idx = LEASE_STAGES.index(to_stage)
    # The adversarial round's finding: a backwards move re-declared NPL and paid the
    # buyback twice. The ladder only advances — no role, no note, no exception.
    if target_idx <= current_idx:
        raise errors.ladder_move_not_forward(case["stage"], to_stage)
    if target_idx != current_idx + 1:
        # Skipping FORWARD needs an OWNER with a logged reason.
        if role != "OWNER" or not note:
            raise errors.ladder_stage_skip(case["stage"], to_stage)

    found = journey.contract_by_uid(case["contract_uid"])
    _customer, contract = found
    missed = journey.missed_count(contract)
    rung = next(r for r in LADDERS["LEASE"] if r["stage"] == to_stage)
    if missed < rung["min_missed"]:
        raise errors.stage_requires_missed_count(to_stage, rung["min_missed"], missed)

    if to_stage == "NPL_DECLARED_90":
        # The human flag (OD-04). Role-gated; DEBT_MANAGER is vacant, OWNER absorbs.
        if role not in ("OWNER", "MANAGER"):
            raise errors.authority_gap_blocks_approval(role or "OFFICER", "declare NPL")
        # One declaration per case, ever — a second would orphan the npl_case that
        # may carry the executed deed (the double-buyback finding).
        if case.get("npl_uid"):
            raise errors.npl_already_declared(uid, case["npl_uid"])
        npl = journey.make_npl_case(state, case["uid"], contract.uid,
                                    settings.business_date, by)
        case["npl_uid"] = npl["uid"]
        # Ruling 43 / R4-F03: session-scoped write — never contract.status = ... onto
        # the shared Contract fixture (same overlay as R4-F01's fee_state).
        _cases()._set_contract_fields(contract, status="NON_PERFORMING")

    if to_stage == "ASSIGNED_120":
        if not case.get("npl_uid"):
            raise errors.assignment_before_npl(uid)
        npl = state.npl_cases[case["npl_uid"]]
        if npl.get("assignment"):
            raise errors.assignment_already_executed(uid)
        journey.execute_assignment(state, case, contract, settings.business_date, by)

    case["stage"] = to_stage
    case["stage_history"].append({"stage": to_stage, "on": str(settings.business_date),
                                  "by": by, "note": note})
    payload = _case_payload(state, case)
    payload["extensions"] = {"pending_decision": "OD-04",
                             "threshold_source": "deck v20.0 — indicative only, a human flags"}
    return payload


# --- cash ladder ------------------------------------------------------------------

@router.get("/v1/cash-cases")
def list_cash_cases():
    state = journey.for_current()
    return {"cases": [_case_payload(state, c) for c in state.cash_cases.values()]}


@router.post("/v1/cash-cases/{uid}:advance")
def advance_cash_case(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="CASH_CASE_ADVANCED", subject=("cash_case", uid))
    state = journey.for_current()
    case = state.cash_cases.get(uid)
    if case is None:
        raise errors.not_found("case")
    to_stage = (body or {}).get("to_stage")
    by = (body or {}).get("by") or "Nok"
    note = (body or {}).get("note")
    # The header, never the body: this path is not on auth.ACTOR_ROLE_BODY (as _set_stage).
    role = (x_volt_role or "OFFICER").upper()
    if to_stage not in CASH_STAGES or to_stage == "BALANCE_DUE":
        raise errors.ladder_stage_unknown(to_stage, [s for s in CASH_STAGES if s != "BALANCE_DUE"])
    # The lease :advance's own rule: the ladder only advances, one rung at a time, and
    # skipping forward needs the OWNER with a logged note. A move back is a Manager's
    # set-stage, with a reason (fix-all Leg R audit).
    current_idx, target_idx = CASH_STAGES.index(case["stage"]), CASH_STAGES.index(to_stage)
    if target_idx <= current_idx:
        raise errors.ladder_move_not_forward(case["stage"], to_stage)
    if target_idx != current_idx + 1 and (role != "OWNER" or not note):
        raise errors.ladder_stage_skip(case["stage"], to_stage)
    if to_stage == "DEFAULT_CONFIRMED_90":
        # Confirming the default chooses the recovery path and opens it: the Manager's
        # act open_recovery and set-stage already gate. Never a second recovery.
        _manager_only(role, "Only a Manager or the Owner confirms a cash default and its recovery path",
                      "เฉพาะผู้จัดการขึ้นไปยืนยันการผิดนัดและเลือกแนวทางเรียกคืนได้")
    if to_stage == "DEFAULT_CONFIRMED_90" and not case.get("recovery_uid"):
        path = (body or {}).get("path")
        if path not in ("LEGAL_CLAIM", "REMOVAL"):
            raise errors.validation_failed([{
                "pointer": "/path", "code": "path_required",
                "message": "Confirming a cash default requires a path: LEGAL_CLAIM or REMOVAL.",
                "message_th": "ต้องเลือกแนวทาง: ฟ้องร้อง หรือ ถอดระบบ"}])
        case["path"] = path
        strategy = "LEGAL" if path == "LEGAL_CLAIM" else "REPOSSESSION"
        rec = journey.make_recovery(state, uid, case["contract_uid"], strategy, EPC)
        case["recovery_uid"] = rec["uid"]
        if strategy == "REPOSSESSION":
            found = journey.contract_by_uid(case["contract_uid"])
            journey.make_lot(state, rec["uid"], case["contract_uid"],
                             "RP-%s" % case["contract_uid"], expected_count=10, watt=5000)
    case["stage"] = to_stage
    case["stage_history"].append({"stage": to_stage, "on": str(settings.business_date),
                                  "by": by, "note": note})
    return _case_payload(state, case)


# --- Q1 / F05: the ladder stage by hand (TASK-110) ---------------------------------
#
# `:advance` stays the officer's one-step forward move with its own contract. This is
# the manager's separate act: either direction, a mandatory reason, every move logged
# on the case and in the audit log. NPL keeps its own gate and a back-then-forward
# move never re-declares it. Ruling Q1; edit 41 keeps the pinned refusal of `:advance`
# for a backward move for everyone (that route is untouched).

def _manager_only(role, detail, th):
    """Q1/Q2's own gate (TASK-110/112): a 403, matching the assignment routes'
    shape. `errors.authority_gap_blocks_approval` is 422 and means a vacant post,
    not a role that may not act — the plan cites it, the tasks require 403."""
    if role not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager or above",
                             detail=detail, message_th=th, error_id="DEBT-IAM-0403")


def _set_stage(kind, uid, body, x_volt_role):
    state = journey.for_current()
    store = state.cases if kind == "LEASE" else state.cash_cases
    case = store.get(uid)
    if case is None:
        raise errors.not_found("case")
    body = body or {}
    to_stage = body.get("to_stage")
    by = body.get("by") or "Nok"
    # The header, never the body: the auth middleware rewrites X-Volt-Role from the
    # session, and this path is not on auth.ACTOR_ROLE_BODY (fix-all Leg R).
    role = (x_volt_role or "OFFICER").upper()
    reason = str(body.get("reason") or "").strip()
    stages = LEASE_STAGES if kind == "LEASE" else CASH_STAGES
    base = "NORMAL" if kind == "LEASE" else "BALANCE_DUE"
    _manager_only(role, "Only a Manager or the Owner moves a ladder stage by hand",
                  "เฉพาะผู้จัดการขึ้นไปปรับขั้นด้วยมือได้")
    if not reason:
        raise errors.validation_failed([{
            "pointer": "/reason", "code": "reason_required",
            "message": "A hand-moved stage needs a reason",
            "message_th": "ปรับขั้นด้วยมือต้องระบุเหตุผล"}])
    if to_stage not in stages or to_stage == base:
        raise errors.ladder_stage_unknown(to_stage, [s for s in stages if s != base])
    previous = case["stage"]
    if to_stage == previous:
        raise errors.stage_unchanged(to_stage)
    direction = "forward" if stages.index(to_stage) > stages.index(previous) else "back"

    if direction == "forward" and kind == "LEASE":
        found = journey.contract_by_uid(case["contract_uid"])
        _customer, contract = found
        missed = journey.missed_count(contract)
        rung = next(r for r in LADDERS["LEASE"] if r["stage"] == to_stage)
        # The min_missed gate stays (the one-step and OWNER-skip rules do not: a
        # manager with a reason may skip).
        if missed < rung["min_missed"]:
            raise errors.stage_requires_missed_count(to_stage, rung["min_missed"], missed)
        if to_stage == "NPL_DECLARED_90" and not case.get("npl_uid"):
            # The human flag (OD-04), declared once. A case that went back below NPL
            # and comes forward again keeps its npl_uid and creates nothing (the
            # double-buyback guard).
            npl = journey.make_npl_case(state, case["uid"], contract.uid,
                                        settings.business_date, by)
            case["npl_uid"] = npl["uid"]
            _cases()._set_contract_fields(contract, status="NON_PERFORMING")
        if to_stage == "ASSIGNED_120":
            if not case.get("npl_uid"):
                raise errors.assignment_before_npl(uid)
            npl = state.npl_cases[case["npl_uid"]]
            if npl.get("assignment"):
                raise errors.assignment_already_executed(uid)
            journey.execute_assignment(state, case, contract, settings.business_date, by)
    if direction == "forward" and kind == "CASH" and to_stage == "DEFAULT_CONFIRMED_90" \
            and not case.get("recovery_uid"):
        path = body.get("path")
        if path not in ("LEGAL_CLAIM", "REMOVAL"):
            raise errors.validation_failed([{
                "pointer": "/path", "code": "path_required",
                "message": "Confirming a cash default requires a path: LEGAL_CLAIM or REMOVAL.",
                "message_th": "ต้องเลือกแนวทาง: ฟ้องร้อง หรือ ถอดระบบ"}])
        case["path"] = path
        strategy = "LEGAL" if path == "LEGAL_CLAIM" else "REPOSSESSION"
        rec = journey.make_recovery(state, uid, case["contract_uid"], strategy, EPC)
        case["recovery_uid"] = rec["uid"]
        if strategy == "REPOSSESSION":
            journey.make_lot(state, rec["uid"], case["contract_uid"],
                             "RP-%s" % case["contract_uid"], expected_count=10, watt=5000)

    # A backward move changes the stage and nothing else: never npl_uid, never the
    # npl_case store, never contract status or service accounts.
    case["stage"] = to_stage
    case["stage_history"].append({"stage": to_stage, "from": previous,
                                  "on": str(settings.business_date), "by": by,
                                  "role": role, "reason": reason, "manual": True})
    audit.describe(act="LADDER_STAGE_SET",
                   subject=("case" if kind == "LEASE" else "cash_case", uid),
                   detail={"from": previous, "to": to_stage, "direction": direction,
                           "reason": reason, "role": role})
    payload = _case_payload(state, case)
    payload["extensions"] = {"direction": direction, "manual": True,
                             # RISK-102's sibling: the payload says which case it is.
                             "case_uid": uid, "kind": kind}
    return payload


@router.post("/v1/cases/{uid}:set-stage")
def set_case_stage(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="LADDER_STAGE_SET", subject=("case", uid))
    return _set_stage("LEASE", uid, body, x_volt_role)


@router.post("/v1/cash-cases/{uid}:set-stage")
def set_cash_case_stage(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="LADDER_STAGE_SET", subject=("cash_case", uid))
    return _set_stage("CASH", uid, body, x_volt_role)


# --- restructures (S08) -----------------------------------------------------------

@router.post("/v1/cases/{uid}/restructures", status_code=201)
def propose_restructure(uid: str, body: dict = Body(...)):
    audit.describe(act="RESTRUCTURE_PROPOSED", subject=("case", uid))
    state = journey.for_current()
    case = state.cases.get(uid)
    if case is None:
        raise errors.not_found("case")
    # R7-D01: one predicate, shared with the read (see restructure_eligibility above).
    # The refusals themselves stay exactly as they were — same codes, same messages.
    eligible, code, _why = restructure_eligibility(state, case)
    if not eligible:
        if code == "restructure_not_offered":
            raise errors.restructure_not_offered(uid, case["stage"])
        raise errors.second_restructure_forbidden(case["contract_uid"])
    rst = state.uid("rst")
    state.restructures[rst] = {
        "uid": rst, "case_uid": uid, "contract_uid": case["contract_uid"],
        "status": "PROPOSED", "proposed_by": (body or {}).get("by") or "Nok",
        "proposed_on": str(settings.business_date),
        "new_term_months": int((body or {}).get("new_term_months") or 60),
        "new_first_due": (body or {}).get("new_first_due"),
        "approved_by": None, "missed_on_new_schedule": 0,
        "note": (body or {}).get("note"),
    }
    case["restructure_uid"] = rst
    return {"restructure": state.restructures[rst]}


@router.get("/v1/restructures/{uid}")
def get_restructure(uid: str):
    state = journey.for_current()
    rst = state.restructures.get(uid)
    if rst is None:
        raise errors.not_found("restructure")
    return {"restructure": rst}


@router.post("/v1/restructures/{uid}:approve")
def approve_restructure(uid: str, body: dict = Body(default={})):
    audit.describe(act="RESTRUCTURE_APPROVED", subject=("restructure", uid))
    state = journey.for_current()
    rst = state.restructures.get(uid)
    if rst is None:
        raise errors.not_found("restructure")
    role = (body or {}).get("role") or "OFFICER"
    if role not in ("OWNER", "MANAGER"):
        raise errors.authority_gap_blocks_approval(role, "approve restructure")
    if rst["status"] != "PROPOSED":
        raise errors.invoice_state_conflict(uid, rst["status"], "approve")
    import dataclasses
    from ..fixtures import ContractFixture, _add_months
    from .. import cases as cases_domain
    found = journey.contract_by_uid(rst["contract_uid"])
    _customer, contract = found
    # Ruling 47: the CONTRACT is the shared fixture book — two sessions each holding
    # a PROPOSED copy must not both apply an addendum (the 96→240-line corruption
    # finding). This used to be enforced by ACCIDENT: reading `line.schedule_status`
    # straight off the shared `contract.instalments` happened to double as a
    # cross-session guard, only because that list was never isolated. The guard is
    # now explicit and deliberate — `journey.restructure_lock`, a process-wide,
    # write-once record keyed by contract uid (journey.py, beside `_IDEMPOTENCY`'s
    # own reasoning) — so the refusal below no longer depends on the schedule's
    # storage shape.
    #
    # Ruling 49: the schedule DATA is now isolated too, onto cases.py's own
    # per-session overlay (contract_field_of / _set_contract_fields — the same
    # mechanism fee_state and status already use, generalised a third time, not a
    # new one). Neither `contract.instalments` nor any `line.schedule_status` is
    # written on the shared fixture objects again: superseded lines are REPLACED
    # by a per-session copy (`dataclasses.replace`, never a mutation of the shared
    # Instalment), and the whole new list lands in the acting session's overlay
    # slot. A session that has not restructured this contract keeps reading the
    # pre-restructure schedule off the raw attribute, which is never written by a
    # request again — same guarantee as fee_state/status.
    if journey.restructure_lock(contract.uid) is not None:
        raise errors.second_restructure_forbidden(contract.uid)
    from .. import service_deferrals
    if service_deferrals.active_moves(contract.uid):
        raise service_deferrals.problem("schedule_locked", "ต้องย้อนการเลื่อนงวดก่อนปรับโครงสร้างสัญญา", 409)
    journey.lock_restructure(contract.uid, restructure_uid=uid,
                             session_id=session_domain.current(),
                             approved_by=(body or {}).get("by") or "Owner",
                             on=str(settings.business_date))
    # The addendum's schedule SUPERSEDES the old lines; the money engine follows
    # is_active_regular with zero engine edits. New principal = outstanding PRINCIPAL
    # plus interest already EARNED (lines due by today, unpaid) — never the future
    # flat interest of the old schedule, which the 7.9% would then compound
    # (the interest-on-interest finding).
    current_lines = list(cases_domain.contract_field_of(contract, "instalments"))
    outstanding = Decimal("0.00")
    for l in current_lines:
        if not l.is_active_regular:
            continue
        outstanding += l.outstanding_principal
        if l.due_date <= settings.business_date:
            outstanding += l.outstanding_interest
    superseded_lines = [
        dataclasses.replace(line, schedule_status="SUPERSEDED") if line.is_active_regular else line
        for line in current_lines
    ]
    first_due = rst.get("new_first_due")
    first_due = date.fromisoformat(first_due) if first_due else _add_months(settings.business_date, 1)
    addendum = ContractFixture(contract.uid, _customer.uid, "LEASE",
                               outstanding.quantize(Decimal("0.01")),
                               rst["new_term_months"], first_due).build()
    cases_domain._set_contract_fields(contract, instalments=superseded_lines + addendum.instalments)
    rst["status"] = "ACTIVE"
    rst["approved_by"] = (body or {}).get("by") or "Owner"
    case = state.cases.get(rst["case_uid"])
    if case:
        case["restructured"] = True
        case["stage"] = "NORMAL"
        case["stage_history"].append({
            "stage": "NORMAL", "on": str(settings.business_date),
            "by": rst["approved_by"],
            "note": "Restructure ACTIVE — new schedule supersedes old; performing again"})
    return {"restructure": rst,
            "note": "Two missed instalments on the NEW schedule declares NPL immediately — no second restructure."}


@router.post("/v1/restructures/{uid}:record-miss")
def record_restructure_miss(uid: str, body: dict = Body(default={})):
    """Demo lever: the re-default trigger. Two missed on the new schedule locks the
    case to CONFIRM_NPL and opens a mandatory review."""
    audit.describe(act="RESTRUCTURE_MISS_RECORDED", subject=("restructure", uid))
    state = journey.for_current()
    rst = state.restructures.get(uid)
    if rst is None:
        raise errors.not_found("restructure")
    if rst["status"] != "ACTIVE":
        raise errors.invoice_state_conflict(uid, rst["status"], "record-miss")
    rst["missed_on_new_schedule"] += 1
    review_uid = None
    if rst["missed_on_new_schedule"] >= 2:
        rst["status"] = "FAILED_TO_NPL"
        case = state.cases.get(rst["case_uid"])
        review = journey.make_review(state, case["customer_uid"], "RESTRUCTURE_FAILED",
                                     source_ref=uid, opened_by="system",
                                     snapshot=_review_snapshot(state, case["customer_uid"]))
        review_uid = review["uid"]
    return {"restructure": rst, "manager_review_uid": review_uid,
            "note": "No second restructure (deck S08)." if rst["status"] == "FAILED_TO_NPL" else None}


# --- manager review + arrangements ------------------------------------------------

def _review_snapshot(state, customer_uid):
    customer = journey.customer_by_uid(customer_uid)
    if customer is None:
        return {}
    total, oldest, band, _out = _aggregate(customer)
    ptps = [p for p in state.ptps.values() if p["customer_uid"] == customer_uid]
    return {
        "days_past_due": oldest,
        "aging_bucket": band.code,
        "band_set_code": band.band_set_code,
        "arrears": str(total),
        "ptp_history": {
            "made": len(ptps),
            "kept": sum(1 for p in ptps if p["status"] in ("KEPT", "KEPT_PARTIAL")),
            "broken": sum(1 for p in ptps if p["status"] == "BROKEN"),
        },
        "open_service_issues": len(journey.open_issue_for(state, customer_uid)),
    }


def _available_decisions(customer):
    """One helper used by BOTH the queue and the decide endpoint, so the advertised
    list and the enforcement can never diverge (the cash-bypass finding): a CASH
    account's remedies are S11's — restructure and lease-NPL do not exist for it."""
    is_cash = bool(customer and customer.contracts
                   and customer.contracts[0].product == "CASH")
    return [d for d in journey.REVIEW_DECISIONS
            if not (is_cash and d in ("RESTRUCTURE", "CONFIRM_NPL"))]


@router.get("/v1/manager-review")
def review_queue(status: str = Query(default=None)):
    state = journey.for_current()
    rows = list(state.reviews.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    for row in rows:
        if not row["snapshot"]:
            row["snapshot"] = _review_snapshot(state, row["customer_uid"])
        customer = journey.customer_by_uid(row["customer_uid"])
        row["customer"] = {
            "uid": customer.uid, "customer_no": customer.customer_no,
            "display_name": customer.display_name,
        } if customer else None
        # CASH accounts cannot be restructured — the 12-scenario matrix, visible.
        row["available_decisions"] = _available_decisions(customer)
        is_cash = len(row["available_decisions"]) < len(journey.REVIEW_DECISIONS)
        if is_cash:
            row["cash_note"] = ("บัญชีเงินสด EPC ใช้บันได 30/60/90 → กฎหมาย/ถอดระบบ "
                                "(S11) — restructure and lease-NPL do not apply")
    return {"reviews": rows}


@router.post("/v1/manager-review/{uid}:decide")
def decide_review(uid: str, body: dict = Body(...)):
    audit.describe(act="MANAGER_REVIEW_DECIDED", subject=("manager_review", uid), detail={"decision": (body or {}).get("decision")})
    state = journey.for_current()
    review = state.reviews.get(uid)
    if review is None:
        raise errors.not_found("review")
    if review["status"] == "DECIDED":
        raise errors.review_already_decided(uid, review["decision"])
    decision = (body or {}).get("decision")
    customer = journey.customer_by_uid(review["customer_uid"])
    # Enforced HERE, not only advertised in the queue — the adversarial round
    # forced a CASH contract into the lease NPL ladder through this gap.
    available = _available_decisions(customer)
    if decision not in available:
        raise errors.decision_unknown(decision, available)
    role = (body or {}).get("role") or "OFFICER"
    if role not in ("MANAGER", "OWNER"):
        raise errors.authority_gap_blocks_approval(role, "decide review")
    by = (body or {}).get("by") or "Owner"
    effect = {}
    if decision == "REPAYMENT_ARRANGEMENT":
        arr = state.uid("arr")
        state.arrangements[arr] = {
            "uid": arr, "customer_uid": review["customer_uid"], "review_uid": uid,
            "status": "ACTIVE", "lines": (body or {}).get("lines") or [],
            "opened_on": str(settings.business_date),
            "note": "Broken plan reopens a review (flow part 4).",
        }
        effect = {"arrangement_uid": arr}
    elif decision == "RESTRUCTURE":
        case = journey.case_for_customer(state, review["customer_uid"])
        if case is None and customer:
            case = journey.make_case(state, customer.uid, customer.contracts[0].uid,
                                     "RESTRUCTURE_OFFER_60",
                                     history=[{"stage": "RESTRUCTURE_OFFER_60",
                                               "on": str(settings.business_date),
                                               "by": by, "note": "Offered via review"}])
        effect = {"case_uid": case["uid"] if case else None,
                  "next": "POST /v1/cases/{uid}/restructures"}
    elif decision == "CONFIRM_NPL":
        case = journey.case_for_customer(state, review["customer_uid"])
        if case is None and customer:
            case = journey.make_case(state, customer.uid, customer.contracts[0].uid, "NORMAL")
        if not case.get("npl_uid"):
            found = journey.contract_by_uid(case["contract_uid"])
            _cust, contract = found
            npl = journey.make_npl_case(state, case["uid"], contract.uid,
                                        settings.business_date, by)
            case["npl_uid"] = npl["uid"]
            case["stage"] = "NPL_DECLARED_90"
            case["stage_history"].append({"stage": "NPL_DECLARED_90",
                                          "on": str(settings.business_date),
                                          "by": by, "note": "Confirmed via manager review"})
            # Ruling 43 / R4-F03: session-scoped write, same overlay as R4-F01.
            _cases()._set_contract_fields(contract, status="NON_PERFORMING")
        effect = {"npl_uid": case["npl_uid"]}

    review["status"] = "DECIDED"
    review["decision"] = decision
    review["decided_by"] = by
    review["decided_on"] = str(settings.business_date)
    review["note"] = (body or {}).get("note")
    return {"review": review, "effect": effect}


@router.post("/v1/arrangements/{uid}:break")
def break_arrangement(uid: str, body: dict = Body(default={})):
    audit.describe(act="ARRANGEMENT_BROKEN", subject=("arrangement", uid))
    state = journey.for_current()
    arr = state.arrangements.get(uid)
    if arr is None:
        raise errors.not_found("arrangement")
    arr["status"] = "BROKEN"
    review = journey.make_review(state, arr["customer_uid"], "ARRANGEMENT_BROKEN",
                                 source_ref=uid, opened_by=(body or {}).get("by") or "system",
                                 snapshot=_review_snapshot(state, arr["customer_uid"]))
    return {"arrangement": arr, "manager_review_uid": review["uid"]}


# --- NPL / recovery / repossession ------------------------------------------------

@router.get("/v1/npl-cases")
def list_npl_cases():
    """Judge J-47: every case whose payment_status is NPL — the sheet-derived ones too —
    not only the demo declarations. The demo rows keep their shape; every row gains
    npl_type, npl_type_label, display_name, volt_id, aggregate_overdue and source."""
    from .. import cases as cases_domain
    from .. import dictionaries
    state = journey.for_current()
    cs = cases_domain.for_current()
    d = dictionaries.for_current()

    def decorate(row, customer, case):
        npl_type = case["npl_type"] if case else None
        total = _aggregate(customer)[0] if customer else Decimal("0")
        ds = (getattr(customer, "data_source", None) or {}) if customer else {}
        # Delta-100 REC-6/9/11/16: the row's remaining NPV, the declared path
        # estimates for the not-yet-chosen cards, and the risk edge. All null when
        # no contract resolves — never an invented figure.
        contract_uid = (customer.contracts[0].uid if customer and customer.contracts
                        else row.get("contract_uid"))
        found = journey.contract_by_uid(contract_uid) if contract_uid else None
        contract = found[1] if found else None
        npv = journey.remaining_npv(contract) if contract else None
        rec = state.recovery_cases.get(row.get("recovery_uid"))
        status_label_th, status_label_en = (recovery_status_label(state, rec) if rec
                                            else ("ยังไม่เลือกแนวทาง", "No path chosen yet"))
        row.update({
            "npl_type": npl_type,
            "npl_type_label": d.label("NPL_TYPE", npl_type) if npl_type else None,
            "display_name": customer.display_name if customer else None,
            "volt_id": getattr(customer, "volt_id", None) if customer else None,
            "aggregate_overdue": str(total),
            "remaining_npv": str(npv) if npv is not None else None,
            "risk_score": journey.risk_score_for_customer(customer),
            "recovery_paths": _recovery_paths_for(contract) if contract else None,
            # F08 / TASK-113: the row's column on the strategy board — the OPEN
            # recovery's strategy, never a superseded one's.
            "strategy": rec["strategy"] if rec and rec.get("status") == "IN_PROGRESS" else None,
            "status_label_th": status_label_th, "status_label_en": status_label_en,
            "payment_status": case["payment_status"] if case else None,
            "source": "SHEET" if ds.get("history") == "SHEET" else "DEMO",
        })
        return row

    rows = []
    for npl in state.npl_cases.values():
        jcase = state.cases.get(npl["case_uid"])
        customer_uid = jcase["customer_uid"] if jcase else None
        customer = journey.customer_by_uid(customer_uid) if customer_uid else None
        rows.append(decorate(dict(npl, customer_uid=customer_uid), customer, cs.cases.get(customer_uid)))
    for case in _undeclared_npl_cases(state, cs):
        customer = journey.customer_by_uid(case["customer_uid"])
        rows.append(decorate({
            "uid": case["uid"], "case_uid": case["uid"], "customer_uid": case["customer_uid"],
            "contract_uid": _first_contract_uid(customer),
            "declared_on": None, "declared_by": None,
            "recovery_uid": _recovery_opened_from(state, case["uid"]), "pending_decision": "OD-04",
            "origin": "PAYMENT_STATUS",
        }, customer, case))
    # Declared (journey) rows keep their place first; the payment-status rows follow, arrears descending.
    rows.sort(key=lambda r: (r.get("origin") == "PAYMENT_STATUS", -Decimal(r["aggregate_overdue"]), r["display_name"] or ""))
    customers = len({r["customer_uid"] for r in rows})
    return {"npl_cases": rows, "meta": {"total": len(rows), "customers": customers,
                                        # F08 / TASK-113: the board's columns, served
                                        # with their availability (EXTERNAL_COLLECTION
                                        # stays visible and disabled, D27).
                                        "strategies": strategy_meta(),
                                        "by_source": {k: sum(1 for r in rows if r["source"] == k) for k in ("SHEET", "DEMO")},
                                        "without_type": sum(1 for r in rows if not r["npl_type"]),
                                        # S2-07: the tab badge is THIS number — one row per NPL customer, the
                                        # same head-count the weekly report's "NPL" shows.
                                        "badge": customers,
                                        "note_th": "หนึ่งแถวต่อลูกค้า NPL หนึ่งราย เท่ากับจำนวน NPL ในรายงานประจำสัปดาห์"}}


def _undeclared_npl_cases(state, cs):
    """The customer-level cases whose payment_status is NPL and that no declaration
    already stands for — the PAYMENT_STATUS rows of GET /v1/npl-cases. One predicate
    for the list and for opening a recovery, so the Recovery tab can never offer an act
    on a row the API cannot find (the 404s J-47's wider list left behind)."""
    declared = {state.cases[n["case_uid"]]["customer_uid"]
                for n in state.npl_cases.values() if n["case_uid"] in state.cases}
    return [c for c in cs.cases.values()
            if c["payment_status"] == "NPL" and c["customer_uid"] not in declared]


def _first_contract_uid(customer):
    return customer.contracts[0].uid if customer and customer.contracts else None


def _recovery_opened_from(state, source_ref):
    """The newest recovery on this row that nothing superseded — after a strategy
    change the row serves the new record, not the first one it opened."""
    return next((r["uid"] for r in reversed(state.recovery_cases.values())
                 if r["source_ref"] == source_ref and not r.get("superseded_by")), None)


# --- Delta-100 REC-6/7/9/11/16: what a recovery/case row serves --------------------

RECOVERY_STATUS_LABELS = {
    "FULL": ("ปิดครบ", "Closed — full recovery"),
    "PARTIAL": ("ปิดบางส่วน", "Closed — partial recovery"),
    "NO_CONCLUSION": ("ปิดโดยไม่มีข้อยุติ", "Closed — no conclusion"),
    "CLOSED_WRITE_OFF": ("ตัดจำหน่าย", "Written off"),
}
LOT_STATUS_LABELS = {
    "PLANNED": ("รอถอดระบบ", "Awaiting removal"),
    "UNINSTALLED": ("ถอดระบบแล้ว รอตรวจนับ", "Removed, awaiting count"),
    "COUNTED": ("ตรวจนับแล้ว รอเกรด", "Counted, awaiting grading"),
    "GRADED": ("เกรดแล้ว รอตั้งราคา", "Graded, awaiting pricing"),
    "PRICED": ("ตั้งราคาแล้ว รอขาย", "Priced, awaiting sale"),
    "SOLD": ("ขายแล้ว", "Sold"),
}


def recovery_status_label(state, rec):
    """The row's status chip text, from the served state machine: the lot's own
    status where the strategy has one, the outcome once resolved, the supersede word
    once replaced, else in progress. Never a prototype sample word — a real state's
    own label."""
    if rec.get("status") == "SUPERSEDED":
        return ("ถูกแทนที่", "Superseded")
    if rec.get("status") == "RESOLVED":
        return RECOVERY_STATUS_LABELS.get(rec.get("outcome"), ("ปิดเคส", "Closed"))
    lot = next((l for l in state.lots.values() if l["recovery_uid"] == rec["uid"]), None)
    if lot:
        return LOT_STATUS_LABELS.get(lot["status"], ("กำลังดำเนินการ", "In progress"))
    return ("กำลังดำเนินการ", "In progress")


def _recovery_payload(state, rec):
    """One recovery case as every route serves it: the SOP's steps (REC-14), the
    case's remaining NPV, the declared commercial rate and its estimate (REC-9/11),
    the status chip (REC-7) and the risk edge (REC-16). Nothing here decides
    anything: rate_pct is the declared assumption in journey.RECOVERY_RATE_PCT and
    every figure says so in rate_basis_*."""
    found = journey.contract_by_uid(rec["contract_uid"])
    contract = found[1] if found else None
    npv = journey.remaining_npv(contract) if contract else None
    rate = journey.RECOVERY_RATE_PCT.get(rec["strategy"])
    expected = (npv * rate / Decimal("100")).quantize(Decimal("0.01")) \
        if npv is not None and rate is not None else None
    if rate is not None:
        basis_th, basis_en = journey.RECOVERY_RATE_BASIS_TH, journey.RECOVERY_RATE_BASIS_EN
    else:
        basis_th, basis_en = journey.RECOVERY_RATE_REFUSED_TH, journey.RECOVERY_RATE_REFUSED_EN
    label_th, label_en = recovery_status_label(state, rec)
    note_th, note_en = sop.RECOVERY_NEXT_STEPS_NOTES.get(rec["strategy"], (None, None))
    customer = journey.customer_by_uid(contract.customer_uid) if contract else None
    pct_note_th = ("NPV คงเหลือคือยอดตามสัญญาหักส่วนที่ชำระแล้ว คิดลดด้วยอัตราที่ประกาศไว้ "
                   "และใช้ %s%% ของ NPV" % settings.acquisition_pct_of_npv) if npv is not None else None
    pct_note_en = ("Remaining NPV is the balance still owed, discounted at the declared rate, "
                   "at %s%% of NPV" % settings.acquisition_pct_of_npv) if npv is not None else None
    return {
        **rec,
        "next_steps": sop.RECOVERY_NEXT_STEPS.get(rec["strategy"], []),
        "next_steps_note_th": note_th, "next_steps_note_en": note_en,
        "remaining_npv": str(npv) if npv is not None else None,
        "remaining_npv_basis_th": pct_note_th,
        "remaining_npv_basis_en": pct_note_en,
        "remaining_npv_pending_decision": "OQ-31" if npv is not None else None,
        "rate_pct": str(rate) if rate is not None else None,
        "expected_recovery": str(expected) if expected is not None else None,
        "rate_basis_th": basis_th, "rate_basis_en": basis_en,
        "rate_is_assumption": rate is not None,
        "status_label_th": label_th, "status_label_en": label_en,
        "risk_score": journey.risk_score_for_customer(customer),
    }


def _recovery_paths_for(contract):
    """The path cards before one is chosen: each strategy with the same declared
    rate and its estimate against THIS case's remaining NPV. The interface never
    multiplies — the server owns the number (api.js's own rule)."""
    npv = journey.remaining_npv(contract) if contract else None
    paths = []
    for strategy in journey.RECOVERY_STRATEGIES:
        rate = journey.RECOVERY_RATE_PCT.get(strategy)
        expected = (npv * rate / Decimal("100")).quantize(Decimal("0.01")) \
            if npv is not None and rate is not None else None
        if rate is not None:
            basis_th, basis_en = journey.RECOVERY_RATE_BASIS_TH, journey.RECOVERY_RATE_BASIS_EN
        else:
            basis_th, basis_en = journey.RECOVERY_RATE_REFUSED_TH, journey.RECOVERY_RATE_REFUSED_EN
        note_th, note_en = sop.RECOVERY_NEXT_STEPS_NOTES.get(strategy, (None, None))
        paths.append({
            "strategy": strategy, "rate_pct": str(rate) if rate is not None else None,
            "expected_recovery": str(expected) if expected is not None else None,
            "rate_basis_th": basis_th, "rate_basis_en": basis_en,
            "rate_is_assumption": rate is not None,
            "available": strategy != "EXTERNAL_COLLECTION",
            "pending_decision": "D27" if strategy == "EXTERNAL_COLLECTION" else None,
            "next_steps": sop.RECOVERY_NEXT_STEPS.get(strategy, []),
            "next_steps_note_th": note_th, "next_steps_note_en": note_en,
        })
    return {"remaining_npv": str(npv) if npv is not None else None, "paths": paths}


@router.post("/v1/npl-cases/{uid}/recovery", status_code=201)
def open_recovery(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
                  x_volt_officer: str = Header(default=None)):
    audit.describe(act="RECOVERY_OPENED", subject=("npl_case", uid))
    from .. import cases as cases_domain
    state = journey.for_current()
    npl = state.npl_cases.get(uid)
    if npl is not None:
        contract_uid, already = npl["contract_uid"], npl.get("recovery_uid")
    else:
        # A PAYMENT_STATUS row: its uid is the customer-level case's. The recovery keeps
        # that uid as its source_ref and nothing else is written — no journey case, no
        # declaration, no contract status. Declaring stays a person's separate act.
        case = next((c for c in _undeclared_npl_cases(state, cases_domain.for_current())
                     if c["uid"] == uid), None)
        if case is None:
            raise errors.not_found("npl case")
        contract_uid = _first_contract_uid(journey.customer_by_uid(case["customer_uid"]))
        already = _recovery_opened_from(state, uid)
    # A 404 stays a 404 for anyone; then the role, from the header the auth middleware
    # rewrites (this path is not on auth.ACTOR_ROLE_BODY) — the path choice is MANAGER+.
    role = (x_volt_role or "OFFICER").upper()
    _manager_only(role, "Only a Manager or the Owner opens a recovery case",
                  "เฉพาะผู้จัดการขึ้นไปเปิดการเรียกคืนได้")
    body = body or {}
    strategy = body.get("strategy")
    if strategy not in journey.RECOVERY_STRATEGIES:
        raise errors.recovery_strategy_unknown(strategy, journey.RECOVERY_STRATEGIES)
    if already:
        raise errors.review_already_decided(uid, "recovery already open")
    reason = str(body.get("reason") or "").strip() or None
    rec = journey.make_recovery(state, uid, contract_uid, strategy, EPC,
                                opened_by=body.get("by") or x_volt_officer,
                                opened_on=str(settings.business_date), opened_reason=reason)
    if npl is not None:
        npl["recovery_uid"] = rec["uid"]
    lot = None
    if strategy == "REPOSSESSION":
        lot = journey.make_lot(state, rec["uid"], contract_uid,
                               "RP-%s" % contract_uid, expected_count=10, watt=5000)
    audit.describe(act="RECOVERY_OPENED", subject=("npl_case", uid),
                   detail={"strategy": strategy, "reason": reason, "role": role,
                           "recovery_uid": rec["uid"]})
    return {"recovery": _recovery_payload(state, rec), "lot": lot}


# --- Q2 / F08: change the recovery strategy (TASK-112) ------------------------------
# A strategy change is a supersede, never an edit: the old record keeps the money it
# earned and closes as SUPERSEDED, the new one opens under the chosen strategy. The
# NPL row / cash case follows the new uid.

def strategy_meta():
    """The four strategies with their SOP labels, declared rate and availability —
    the board's columns, served once (TASK-113)."""
    out = []
    for strategy in journey.RECOVERY_STRATEGIES:
        steps = sop.RECOVERY_NEXT_STEPS.get(strategy) or [{}]
        rate = journey.RECOVERY_RATE_PCT.get(strategy)
        out.append({
            "strategy": strategy,
            "label_th": steps[0].get("label_th") or strategy,
            "label_en": steps[0].get("label_en") or strategy,
            "available": strategy != "EXTERNAL_COLLECTION",
            "pending_decision": "D27" if strategy == "EXTERNAL_COLLECTION" else None,
            "rate_pct": str(rate) if rate is not None else None,
        })
    return out


@router.post("/v1/recovery-cases/{uid}:change-strategy")
def change_recovery_strategy(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="RECOVERY_STRATEGY_CHANGED", subject=("recovery", uid))
    state = journey.for_current()
    rec = state.recovery_cases.get(uid)
    if rec is None:
        raise errors.not_found("recovery case")
    body = body or {}
    role = (x_volt_role or "OFFICER").upper()     # the header, never the body (as _set_stage)
    _manager_only(role, "Only a Manager or the Owner changes the recovery strategy",
                  "เฉพาะผู้จัดการขึ้นไปเปลี่ยนแนวทางได้")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise errors.validation_failed([{
            "pointer": "/reason", "code": "reason_required",
            "message": "A strategy change needs a reason",
            "message_th": "เปลี่ยนแนวทางต้องระบุเหตุผล"}])
    strategy = body.get("strategy")
    if strategy not in journey.RECOVERY_STRATEGIES:
        raise errors.recovery_strategy_unknown(strategy, journey.RECOVERY_STRATEGIES)
    if strategy == rec["strategy"]:
        raise errors.strategy_unchanged(strategy)
    if rec.get("status") != "IN_PROGRESS":
        raise errors.recovery_not_open(rec.get("status"))
    # The same availability rule the path cards carry (D27 stays open).
    if strategy == "EXTERNAL_COLLECTION":
        raise errors.recovery_strategy_unavailable(strategy, "D27")

    by = body.get("by") or "Nok"
    old = rec
    old["status"] = "SUPERSEDED"
    old["superseded_on"] = str(settings.business_date)
    old["superseded_reason"] = reason
    new = journey.make_recovery(state, old["source_ref"], old["contract_uid"], strategy, EPC)
    new["supersedes"] = old["uid"]
    old["superseded_by"] = new["uid"]
    npl = state.npl_cases.get(old["source_ref"])
    if npl is not None:
        npl["recovery_uid"] = new["uid"]
    cash = state.cash_cases.get(old["source_ref"])
    if cash is not None:
        cash["recovery_uid"] = new["uid"]
    lot = None
    if strategy == "REPOSSESSION":
        lot = journey.make_lot(state, new["uid"], new["contract_uid"],
                               "RP-%s" % new["contract_uid"], expected_count=10, watt=5000)
    audit.describe(act="RECOVERY_STRATEGY_CHANGED", subject=("recovery", uid),
                   detail={"from": old["strategy"], "to": strategy, "reason": reason,
                           "new_uid": new["uid"], "role": role})
    return {
        "superseded": _recovery_payload(state, old),
        "recovery": _recovery_payload(state, new),
        "lot": lot,
        # RISK-104: the old record's lot rows stay where they are — they belong to
        # the strategy that earned them — and the response says so.
        "note_th": "ระเบียนเดิมถูกแทนที่ (SUPERSEDED) เงินที่เรียกคืนได้และล็อตเดิมยังอยู่กับระเบียนเดิม",
        "note_en": "The old record is superseded; its recoveries and lots stay with it",
        "by": by,
    }


@router.get("/v1/recovery-cases")
def list_recovery_cases():
    state = journey.for_current()
    rows = []
    for rec in state.recovery_cases.values():
        rows.append({**_recovery_payload(state, rec),
                     "lots": [l for l in state.lots.values()
                              if l["recovery_uid"] == rec["uid"]]})
    return {"recovery_cases": rows}


@router.post("/v1/recovery-cases/{uid}/recoveries", status_code=201)
def record_recovery(uid: str, body: dict = Body(...)):
    audit.describe(act="RECOVERY_RECORDED", subject=("recovery_case", uid))
    state = journey.for_current()
    rec = state.recovery_cases.get(uid)
    if rec is None:
        raise errors.not_found("recovery case")
    amount = _positive_amount((body or {}).get("amount"), "/amount")
    rec["recoveries"].append({"amount": str(amount),
                              "on": str(settings.business_date),
                              "source": (body or {}).get("source") or "UNSPECIFIED",
                              "by": (body or {}).get("by") or "Nok"})
    # The server sums; the interface never does.
    rec["recovered_total"] = str(sum((Decimal(r["amount"]) for r in rec["recoveries"]),
                                     Decimal("0.00")))
    return {"recovery": rec}


@router.post("/v1/recovery-cases/{uid}:resolve")
@termination_archive.operation
def resolve_recovery(uid: str, body: dict = Body(...)):
    audit.describe(act="RECOVERY_RESOLVED", subject=("recovery_case", uid))
    state = journey.for_current()
    rec = state.recovery_cases.get(uid)
    if rec is None:
        raise errors.not_found("recovery case")
    outcome = (body or {}).get("outcome")
    if outcome not in journey.RECOVERY_OUTCOMES:
        raise errors.decision_unknown(outcome, journey.RECOVERY_OUTCOMES)
    role = (body or {}).get("role") or "OFFICER"
    if outcome == "CLOSED_WRITE_OFF":
        # Write-off is an approval; DEBT_MANAGER is vacant, the OWNER absorbs.
        if role != "OWNER":
            raise errors.authority_gap_blocks_approval(role, "approve write-off")
        found = journey.contract_by_uid(rec["contract_uid"])
        if found:
            _customer, contract = found
            # Ruling 43 / R4-F03: session-scoped write, same overlay as R4-F01.
            # 2026-09-20: the write-off IS the instrument that ends the contract on
            # default, so the termination record travels with it (status stays
            # WRITTEN_OFF — the books keep saying how the loss closed — and the case
            # derives TERMINATED with cause DEFAULT).
            _cases().record_termination(
                contract, cause="DEFAULT", by=(body or {}).get("by") or role,
                reason=(body or {}).get("reason") or "ตัดจำหน่ายโดยเจ้าของ (OWNER)",
                instrument="WRITE_OFF", status="WRITTEN_OFF")
    elif rec.get("strategy") in ("REPOSSESSION", "COOP_DECOMMISSION") and outcome in ("FULL", "PARTIAL"):
        # 2026-09-20: resolving a repossession (asset came back) or a cooperative
        # decommission (both sides agreed to dismantle) ends the contract. The cause
        # is the honest one for each strategy: the customer asked for the decommission;
        # a repossession is the default path. LEGAL is deliberately NOT here — money
        # recovered under legal pressure does not by itself end the contract, which
        # takes its own terminate act.
        found = journey.contract_by_uid(rec["contract_uid"])
        if found:
            _customer, contract = found
            cause = "CUSTOMER_REQUEST" if rec.get("strategy") == "COOP_DECOMMISSION" else "DEFAULT"
            _cases().record_termination(
                contract, cause=cause, by=(body or {}).get("by") or role,
                reason=(body or {}).get("reason") or "ปิดเคสเรียกคืนด้วยผล %s" % outcome,
                instrument="RECOVERY_%s" % outcome)
    rec["outcome"] = outcome
    rec["status"] = "RESOLVED"
    rec["resolved_by"] = (body or {}).get("by") or role
    rec["resolved_on"] = str(settings.business_date)
    return {"recovery": rec}


@router.get("/v1/repossession-lots")
def list_lots():
    state = journey.for_current()
    return {"lots": list(state.lots.values())}


def _lot_or_404(state, uid):
    lot = state.lots.get(uid)
    if lot is None:
        raise errors.not_found("lot")
    return lot


@router.post("/v1/repossession-lots/{uid}:count")
def count_lot(uid: str, body: dict = Body(...)):
    audit.describe(act="LOT_COUNTED", subject=("repossession_lot", uid))
    state = journey.for_current()
    lot = _lot_or_404(state, uid)
    if lot["status"] not in ("PLANNED", "UNINSTALLED"):
        raise errors.lot_state_conflict(uid, "PLANNED or UNINSTALLED", lot["status"])
    actual = (body or {}).get("actual_count")
    if not isinstance(actual, int) or actual < 0:
        raise errors.validation_failed([{
            "pointer": "/actual_count", "code": "not_a_count",
            "message": "actual_count must be a non-negative integer",
            "message_th": "จำนวนที่นับได้ไม่ถูกต้อง"}])
    lot["actual_count"] = actual
    lot["count_variance"] = actual - lot["expected_count"]
    if lot["count_variance"] != 0:
        note = (body or {}).get("variance_note")
        if not note:
            raise errors.validation_failed([{
                "pointer": "/variance_note", "code": "variance_needs_reason",
                "message": "EXPECTED %d vs ACTUAL %d — a variance needs a reason and a photo."
                           % (lot["expected_count"], actual),
                "message_th": "จำนวนไม่ตรงกับที่คาดไว้ ต้องระบุเหตุผลและรูปถ่าย"}])
        lot["variance_note"] = note
    lot["status"] = "COUNTED"
    return {"lot": lot}


@router.post("/v1/repossession-lots/{uid}:grade")
def grade_lot(uid: str, body: dict = Body(...)):
    audit.describe(act="LOT_GRADED", subject=("repossession_lot", uid))
    state = journey.for_current()
    lot = _lot_or_404(state, uid)
    if lot["status"] != "COUNTED":
        raise errors.lot_state_conflict(uid, "COUNTED", lot["status"])
    grades = (body or {}).get("grades") or {}
    if set(grades) - {"A", "B", "C"} or not grades:
        raise errors.validation_failed([{
            "pointer": "/grades", "code": "unknown_grade",
            "message": "grades must be counts keyed A, B, C",
            "message_th": "เกรดต้องเป็น A, B หรือ C เท่านั้น"}])
    graded = sum(int(v) for v in grades.values())
    if graded != lot["actual_count"]:
        raise errors.grade_count_mismatch(uid, graded, lot["actual_count"])
    lot["grades"] = {k: int(v) for k, v in grades.items()}
    lot["status"] = "GRADED"
    return {"lot": lot,
            "note": "Grade C is scrapped and written off — it never returns to sellable stock."}


# Deck S12 made the resale price Dan's manual call, and this route used to compare the
# signer to the literal name "Dan". Once login decides who signs, no session is ever
# "Dan", so nobody could price a lot. Arina, 2026-09-14: a ROLE decides — Operations
# (Dan's seat) or the Owner — refused as 403 like every other role refusal.
PRICE_LOT_ROLES = ("OPS", "OWNER")


@router.post("/v1/repossession-lots/{uid}:price")
def price_lot(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="LOT_PRICED", subject=("repossession_lot", uid))
    state = journey.for_current()
    lot = _lot_or_404(state, uid)
    if lot["status"] != "GRADED":
        raise errors.lot_state_conflict(uid, "GRADED", lot["status"])
    # A zero or negative "price" would unblock the stock and drive the recovery
    # total below zero on sale — the negative-recovery finding. Checked before the
    # role, so a malformed price is named as such whoever sends it.
    price = _positive_amount((body or {}).get("resale_price"), "/resale_price")
    role = (x_volt_role or "OFFICER").upper()
    if role not in PRICE_LOT_ROLES:
        raise errors.Problem(code="forbidden", status=403, title="Operations or Owner only",
                             detail="The resale price is Operations' manual call; the Owner may also set it.",
                             message_th="เฉพาะทีมปฏิบัติการหรือเจ้าของกำหนดราคาขายต่อได้",
                             error_id="DEBT-IAM-0403", extensions={"allowed_roles": list(PRICE_LOT_ROLES)})
    by = (body or {}).get("by")
    lot["resale_price"] = str(price)
    lot["priced_by"] = by
    lot["priced_by_role"] = role
    lot["stock_blocked"] = False   # saving a price is what unblocks the stock
    lot["status"] = "PRICED"
    return {"lot": lot}


@router.post("/v1/repossession-lots/{uid}:sell")
def sell_lot(uid: str, body: dict = Body(default={})):
    audit.describe(act="LOT_SOLD", subject=("repossession_lot", uid))
    state = journey.for_current()
    lot = _lot_or_404(state, uid)
    if lot["stock_blocked"] or lot["resale_price"] is None:
        raise errors.resale_price_unset(uid)
    if lot["status"] != "PRICED":
        raise errors.lot_state_conflict(uid, "PRICED", lot["status"])
    lot["status"] = "SOLD"
    lot["sold_amount"] = lot["resale_price"]
    rec = state.recovery_cases.get(lot["recovery_uid"])
    if rec:
        rec["recoveries"].append({"amount": lot["resale_price"],
                                  "on": str(settings.business_date),
                                  "source": "REFURB_RESALE", "by": "system"})
        rec["recovered_total"] = str(sum((Decimal(r["amount"]) for r in rec["recoveries"]),
                                         Decimal("0.00")))
    return {"lot": lot,
            "note": "Quote must SAY refurbished, own shorter warranty — rejoins S01 as an EPC cash sale."}


# --- service billing (S09) --------------------------------------------------------

@router.get("/v1/service-billing")
def service_billing():
    state = journey.for_current()
    rows = []
    for account in state.service_accounts.values():
        found = journey.contract_by_uid(account["contract_uid"])
        customer = found[0] if found else None
        invoices = [i for i in state.invoices.values()
                    if i["contract_uid"] == account["contract_uid"]
                    and i["kind"] == "SERVICE_MONTHLY"]
        rows.append({
            **account,
            "customer": {"uid": customer.uid, "customer_no": customer.customer_no,
                         "display_name": customer.display_name} if customer else None,
            "service_invoices": invoices,
        })
    return {
        "accounts": rows,
        "meta": {
            "monthly_floor_thb": str(settings.service_monthly_floor_thb),
            "billing_window": {"from_day": settings.service_billing_window[0],
                               "to_day": settings.service_billing_window[1]},
            "prepaid_months": settings.service_prepaid_months,
            "decline_pending_decision": "SVC-37",
            "decline_owner": PENDING["service_month37_decline_allowed"].owner,
            "isolation_rule": "Service arrears NEVER feed the lease NPL ladder (deck S09).",
        },
    }


@router.post("/v1/contracts/{contract_uid}/service-billing:bill", status_code=201)
def bill_service(contract_uid: str):
    audit.describe(act="SERVICE_BILLED", subject=("contract", contract_uid))
    _contract_or_404(contract_uid)
    state = journey.for_current()
    account = state.service_accounts.get(contract_uid)
    if account is None:
        raise errors.not_found("service account")
    if account["status"] == "CANCELLED":
        raise errors.service_cancelled_by_assignment(contract_uid)
    if account["month_index"] <= settings.service_prepaid_months:
        raise errors.service_before_month_37(account["month_index"])
    day = settings.business_date.day
    lo, hi = settings.service_billing_window
    if not (lo <= day <= hi):
        # The live demonstration of the window law: the fixture clock is the 23rd.
        raise errors.billing_window_closed(day, settings.service_billing_window)
    invoice = journey.make_invoice(state, contract_uid, EPC, "SERVICE_MONTHLY",
                                   settings.service_monthly_floor_thb,
                                   settings.business_date, "ISSUED", scenario="S09",
                                   issued_on=settings.business_date)
    return {"invoice": invoice}


@router.post("/v1/contracts/{contract_uid}/service-billing:decline", status_code=202)
def decline_service(contract_uid: str, body: dict = Body(default={})):
    audit.describe(act="SERVICE_BILLING_DECLINED", subject=("contract", contract_uid))
    _contract_or_404(contract_uid)
    state = journey.for_current()
    account = state.service_accounts.get(contract_uid)
    if account is None:
        raise errors.not_found("service account")
    account["decline_requested"] = True
    account["decline_requested_by"] = (body or {}).get("by")
    return {
        "recorded": True,
        "billing_continues": True,
        "pending_decision": "SVC-37",
        "owner": PENDING["service_month37_decline_allowed"].owner,
        "note": ("The decline REQUEST is recorded. Whether a customer may decline is "
                 "the one open item in deck v20.0 — Jo to settle. Billing runs either "
                 "way meanwhile (R1)."),
    }


# --- AR pipeline, invoices, receipts, timeline ------------------------------------

OPEN_INVOICE_STATES = ("ISSUED", "SENT", "PARTIALLY_PAID", "OVERDUE")


@router.get("/v1/ar/pipeline")
def ar_pipeline(q: str = Query(default=None), customer_uid: str = Query(default=None),
                state: str = Query(default=None), open_only: bool = Query(default=False)):
    """Every invoice — no cap (round-2 thip T2-04). `q` matches the name, the VOLT id,
    the customer no. or the invoice uid; `customer_uid` narrows to one customer;
    `open_only` keeps the states a slip can be recorded against."""
    jstate = journey.for_current()
    rows = []
    needle = (q or "").strip().lower()
    for invoice in jstate.invoices.values():
        found = journey.contract_by_uid(invoice["contract_uid"])
        customer = found[0] if found else None
        if customer:
            who = {"uid": customer.uid, "customer_no": customer.customer_no,
                   "display_name": customer.display_name, "volt_id": getattr(customer, "volt_id", None)}
        elif invoice.get("customer_uid"):
            # a pre-install (pipeline) customer without a contract yet
            who = {"uid": invoice["customer_uid"], "customer_no": None,
                   "display_name": invoice.get("display_name"), "volt_id": invoice.get("volt_id")}
        else:
            who = None
        if customer_uid and (who is None or who["uid"] != customer_uid):
            continue
        if state and invoice["state"] != state:
            continue
        if open_only and invoice["state"] not in OPEN_INVOICE_STATES:
            continue
        if needle and not any(needle in (v or "").lower() for v in (
                invoice["uid"], who["display_name"] if who else None, who["volt_id"] if who else None,
                who["customer_no"] if who else None, invoice.get("peak_number"))):
            continue
        rows.append({**invoice, "customer": who})
    # Round-5 T5-02: the list was ordered by the state tuple, in which SENT sits above
    # OVERDUE, so a customer's not-yet-due invoice was offered before the overdue one
    # and a slip could be posted to the wrong month without a word. A slip is money the
    # customer has already paid, so the oldest unpaid invoice comes first.
    def _rank(row):
        return journey.invoice_collection_sort_key(row)[0]
    rows.sort(key=journey.invoice_collection_sort_key)
    oldest_seen = set()
    for row in rows:
        row["collection_rank"] = _rank(row)
        who = (row.get("customer") or {}).get("uid")
        if row["state"] == "OVERDUE" and who and who not in oldest_seen:
            oldest_seen.add(who)
            row["oldest_unpaid"] = True
            row["slip_hint_th"] = "ใบที่ค้างนานที่สุดของลูกค้ารายนี้ — ปกติสลิปจะตรงกับใบนี้"
    return {"invoices": rows,
            "states": list(journey.INVOICE_STATES),
            "counts": {s: sum(1 for r in rows if r["state"] == s)
                       for s in journey.INVOICE_STATES},
            "meta": {"total": len(rows), "cap": None, "q": q, "customer_uid": customer_uid,
                     "open_states": list(OPEN_INVOICE_STATES)}}


_INVOICE_ACTS = {
    "issue": {"from": ("DRAFT", "AR_REVIEW", "REVIEW_ORIGINAL"), "to": "ISSUED"},
    "send": {"from": ("ISSUED",), "to": "SENT"},
    "review-original": {"from": ("ISSUED", "SENT", "OVERDUE"), "to": "REVIEW_ORIGINAL"},
}


@router.post("/v1/invoices/{uid}:issue")
def issue_invoice(uid: str):
    audit.describe(act="INVOICE_ISSUED", subject=("invoice", uid))
    return _invoice_act(uid, "issue")


@router.post("/v1/invoices/{uid}:send")
def send_invoice(uid: str):
    audit.describe(act="INVOICE_SENT", subject=("invoice", uid))
    return _invoice_act(uid, "send")


@router.post("/v1/invoices/{uid}:review-original")
def review_original(uid: str):
    audit.describe(act="INVOICE_ORIGINAL_REVIEWED", subject=("invoice", uid))
    return _invoice_act(uid, "review-original")


@router.post("/v1/invoices/{uid}:link-sent")
def record_link_sent(uid: str, body: dict = Body(default=None),
                     x_volt_officer: str = Header(default=None)):
    """Round-2 judge J2-03: the sheet records that a link was sent but never when,
    so an overdue month reads "ยังไม่ส่งลิงก์" until a person says otherwise. This
    records that the officer sent it today, with their name. It does not create or
    approve anything in PEAK."""
    audit.describe(act="INVOICE_LINK_SENT", subject=("invoice", uid))
    state = journey.for_current()
    invoice = state.invoices.get(uid)
    if invoice is None:
        raise errors.not_found("invoice")
    if invoice["state"] in ("PAID", "CANCELLED"):
        raise errors.invoice_state_conflict(uid, invoice["state"], "link-sent")
    body = body or {}
    by = (body.get("by") or x_volt_officer or "").strip() or None
    if by is None:
        raise errors.Problem(code="officer_required", status=422,
                             title="The acting officer is required",
                             detail="Recording a sent link needs the officer's name",
                             message_th="ต้องระบุชื่อเจ้าหน้าที่ที่ส่งลิงก์",
                             error_id="DEBT-INV-0422")
    on = str(settings.business_date)
    invoice["link_sent"] = True
    invoice["link_sent_on"] = on
    invoice["link_sent_by"] = by
    invoice["link_sent_source"] = "APP"
    invoice["link_sent_note_th"] = "ส่งลิงก์เมื่อ %s โดย %s" % (on, by)
    invoice["link_sent_note_en"] = "Link sent on %s by %s" % (on, by)
    if invoice["state"] == "ISSUED":
        invoice["state"] = "SENT"
    return {"invoice": invoice}


def _invoice_act(uid, act):
    state = journey.for_current()
    invoice = state.invoices.get(uid)
    if invoice is None:
        raise errors.not_found("invoice")
    rule = _INVOICE_ACTS[act]
    if invoice["state"] not in rule["from"]:
        raise errors.invoice_state_conflict(uid, invoice["state"], act)
    invoice["state"] = rule["to"]
    if act == "issue":
        invoice["issued_on"] = str(settings.business_date)
    return {"invoice": invoice}


@router.get("/v1/contracts/{contract_uid}/invoices")
def contract_invoices(contract_uid: str):
    _contract_or_404(contract_uid)
    state = journey.for_current()
    return {"invoices": [i for i in state.invoices.values()
                         if i["contract_uid"] == contract_uid]}


@router.get("/v1/contracts/{contract_uid}/receipts")
def contract_receipts(contract_uid: str):
    _contract_or_404(contract_uid)
    state = journey.for_current()
    return {"receipts": [r for r in state.receipts.values()
                         if r["contract_uid"] == contract_uid]}


# Only these invoice states can receive money. A receipt against a PAID, CANCELLED
# or in-review invoice rewrote its state in the adversarial round — refused now.
_MATCHABLE_INVOICE_STATES = ("ISSUED", "SENT", "PARTIALLY_PAID", "OVERDUE")


@router.post("/v1/receipts", status_code=201)
def record_receipt(body: dict = Body(...)):
    audit.describe(act="RECEIPT_RECORDED")
    contract_uid = (body or {}).get("contract_uid")
    found = _contract_or_404(contract_uid)
    _customer, contract = found
    amount = _positive_amount((body or {}).get("amount"), "/amount")
    state = journey.for_current()
    invoice_uid = (body or {}).get("invoice_uid")
    matched = "UNMATCHED"
    entity = contract.entity or EPC
    overpayment = None
    if invoice_uid:
        invoice = state.invoices.get(invoice_uid)
        if invoice is None:
            raise errors.not_found("invoice")
        # Task 25c fix round 1, finding 2: a link a Manager confirms can move a
        # PEAK invoice to a different customer at the next reseed — the contract
        # this receipt is posted against must be the invoice's OWN customer, or
        # nothing is written. Checked before the state-conflict guard: whose
        # invoice it is comes before what state it is in.
        invoice_owner = journey.contract_by_uid(invoice["contract_uid"])
        if invoice_owner is None or invoice_owner[0].uid != _customer.uid:
            # Fix round 2, finding (c): name the invoice uid and the POSTING
            # contract only -- never the owner's customer id/number. An invoice
            # uid is guessable (inv-pk-<doc_no>); naming the owning customer here
            # would map a PEAK document number straight to a customer identity.
            raise errors.Problem(
                code="invoice_other_customer", status=422,
                title="The invoice belongs to another customer",
                detail="Invoice %s belongs to a different customer than contract %s. "
                       "Nothing was written." % (invoice_uid, contract_uid),
                message_th="ใบแจ้งหนี้นี้เป็นของลูกค้ารายอื่น — เลือกใบแจ้งหนี้ของลูกค้ารายนี้",
                error_id="DEBT-AR-0422",
                extensions={"invoice_uid": invoice_uid, "contract_uid": contract_uid},
                errors=[{
                    "pointer": "/invoice_uid",
                    "code": "invoice_other_customer",
                    "message": "This invoice belongs to another customer",
                    "message_th": "ใบแจ้งหนี้นี้เป็นของลูกค้ารายอื่น — เลือกใบแจ้งหนี้ของลูกค้ารายนี้",
                }],
            )
        if invoice["state"] not in _MATCHABLE_INVOICE_STATES:
            raise errors.invoice_state_conflict(invoice_uid, invoice["state"], "receipt")
        # The receipt books where the INVOICE books — an EPC service payment on an
        # SPV lease is EPC money (the entity-stamp finding).
        entity = invoice["entity"]
        due = Decimal(invoice["amount"])
        # CUMULATIVE matching: two honest partials must eventually mark PAID, and
        # an overpayment must say so rather than quietly widening FULL.
        # Task 25c: scoped to the invoice's OWN customer (journey.invoice_receipts) —
        # a link a Manager confirms can move a PEAK invoice to a different customer
        # at the next reseed, and a receipt someone else recorded against the OLD
        # owner of this uid must never inflate how much THIS invoice is paid.
        paid_before = sum(
            (Decimal(r["amount"]) for r in journey.invoice_receipts(state, invoice)),
            Decimal("0.00"))
        cumulative = paid_before + amount
        matched = "FULL" if cumulative >= due else "PARTIAL"
        invoice["state"] = "PAID" if matched == "FULL" else "PARTIALLY_PAID"
        if cumulative > due:
            overpayment = str(cumulative - due)
    receipt = journey.make_receipt(state, contract_uid, entity,
                                   amount, settings.business_date,
                                   invoice_uid=invoice_uid, matched=matched)
    if overpayment is not None:
        receipt["overpayment_unallocated"] = overpayment
    return {"receipt": receipt,
            "note": ("Recorded and matched at invoice level, cumulatively. Instalment "
                     "components are NOT written while the allocation order is undecided — the exception is "
                     "raised instead, the same asymmetry as the PEAK webhook.")}


@router.get("/v1/customers/{customer_uid}/timeline")
def customer_timeline(customer_uid: str):
    customer = _customer_or_404(customer_uid)
    state = journey.for_current()
    main = _main()
    contract_uids = {k.uid for k in customer.contracts}
    events = []

    for invoice in state.invoices.values():
        if invoice["contract_uid"] in contract_uids:
            events.append({"type": "INVOICE", "on": invoice["issued_on"] or invoice["due_date"],
                           "entity": invoice["entity"], "company_id": invoice["company_id"],
                           "ref": invoice["uid"],
                           "summary": "%s %s — %s" % (invoice["kind"], invoice["amount"],
                                                      invoice["state"])})
    for receipt in state.receipts.values():
        if receipt["contract_uid"] in contract_uids:
            events.append({"type": "RECEIPT", "on": receipt["received_on"],
                           "entity": receipt["entity"], "company_id": receipt["company_id"],
                           "ref": receipt["uid"],
                           "summary": "Receipt %s (%s) — allocation pending"
                                      % (receipt["amount"], receipt["matched"])})
    for ptp in state.ptps.values():
        if ptp["customer_uid"] == customer_uid:
            events.append({"type": "PTP", "on": ptp["promise_date"], "ref": ptp["uid"],
                           "summary": "PTP %s due %s — %s" % (ptp["promised_amount"],
                                                              ptp["promise_date"], ptp["status"])})
    for attempt in main.contact_log.attempts:
        if attempt.customer_key == customer.identity_key:
            events.append({"type": "CONTACT", "on": str(attempt.at)[:10], "ref": str(attempt.contact_id),
                           "summary": "%s %s — %s%s" % (attempt.channel, attempt.direction,
                                                        attempt.disposition,
                                                        " (retracted)" if attempt.retracted else "")})
    case = journey.case_for_customer(state, customer_uid)
    cash = journey.cash_case_for_customer(state, customer_uid)
    for c in (case, cash):
        if c:
            for step in c["stage_history"]:
                events.append({"type": "LADDER", "on": step["on"], "ref": c["uid"],
                               "summary": "%s — %s (%s)" % (step["stage"],
                                                            step.get("note") or "", step["by"])})
    for doc in state.intercompany:
        if doc.get("contract_uid") in contract_uids:
            events.append({"type": "INTERCOMPANY", "on": doc["occurred_on"], "ref": doc["uid"],
                           "entity": doc["entity"], "company_id": doc["company_id"],
                           "summary": "%s %s → %s%s" % (doc["doc_type"], doc["from_entity"],
                                                        doc["to_entity"],
                                                        " " + doc["amount"] if doc["amount"] else "")})
    events.sort(key=lambda e: (e["on"] or ""), reverse=True)
    return {"customer_uid": customer_uid, "events": events,
            "meta": {"types": ["INVOICE", "RECEIPT", "PTP", "CONTACT", "LADDER", "INTERCOMPANY"]}}


# --- inter-company docs (S10) -----------------------------------------------------

@router.get("/v1/intercompany/docs")
def intercompany_docs(contract_uid: str = Query(default=None)):
    state = journey.for_current()
    rows = state.intercompany
    if contract_uid:
        rows = [d for d in rows if d.get("contract_uid") == contract_uid]
    return {"documents": rows,
            "note": ("DIRECTION is the DOCUMENT direction — who issues to whom; money "
                     "moves the other way on every invoice (deck S10).")}


@router.post("/v1/intercompany/docs", status_code=201)
def post_intercompany(body: dict = Body(...)):
    audit.describe(act="INTERCOMPANY_DOC_POSTED")
    doc_type = (body or {}).get("doc_type")
    if doc_type in ("ACCOUNTING_FEE_50000", "SERVICE_BULK_INVOICE"):
        raise errors.manual_outside_erp(doc_type)
    raise errors.validation_failed([{
        "pointer": "/doc_type", "code": "not_posted_here",
        "message": ("Inter-company documents are created by their flows (acquisition, "
                    "deed, buyback), never posted free-form."),
        "message_th": "เอกสารระหว่างบริษัทถูกสร้างโดยขั้นตอนงานเท่านั้น"}])


# --- cancellations (S03/S05/S06) --------------------------------------------------

@router.get("/v1/cancellations")
def list_cancellations():
    state = journey.for_current()
    return {"cancellations": list(state.cancellations.values())}


_CXL_VALID = {
    ("PRE_INSTALL", "CUSTOMER", "FORFEIT_DEPOSIT"),
    ("PRE_INSTALL", "VOLT", "FULL_REFUND_WEEKLY_BATCH"),
    ("PRE_INSTALL", "SITE", "REQUOTE_RESIGN"),
    ("POST_INSTALL", "CUSTOMER", "SETTLE_CLOSED"),
    ("POST_INSTALL", "CUSTOMER", "TO_NPL"),
}


@router.post("/v1/cancellations", status_code=201)
def create_cancellation(body: dict = Body(...)):
    audit.describe(act="CANCELLATION_CREATED")
    phase = (body or {}).get("phase")
    cause = (body or {}).get("cause")
    outcome = (body or {}).get("outcome")
    if (phase, cause, outcome) not in _CXL_VALID:
        raise errors.cancellation_combo_invalid(phase, cause, outcome)
    state = journey.for_current()
    from datetime import timedelta
    uid = state.uid("cxl")
    state.cancellations[uid] = {
        "uid": uid, "phase": phase, "cause": cause, "outcome": outcome,
        "order_no": (body or {}).get("order_no"),
        "contract_uid": (body or {}).get("contract_uid"),
        "note": (body or {}).get("note"),
        "refund_batch_date": str(settings.business_date + timedelta(days=7))
        if outcome == "FULL_REFUND_WEEKLY_BATCH" else None,
        "opened_on": str(settings.business_date),
    }
    return {"cancellation": state.cancellations[uid]}
