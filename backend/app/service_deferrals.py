"""Invoice accounting remains intact; a durable overlay moves collection due dates.

Cycle identity follows the original schedule, never the newly sorted due dates.
Money is reconciled by invoice cycle, so a payment on M3 cannot become cash on M1.
"""
import calendar
import hashlib
import json
import uuid
from contextvars import ContextVar
from dataclasses import replace
from datetime import date
from decimal import Decimal

from . import clock, errors, service_deferral_store as store
from .config import settings

ZERO = Decimal("0.00")
_ROWS = ContextVar("service_deferral_projection", default=None)


def problem(code, message, status=422):
    return errors.Problem("service_deferral_" + code, status, "Service deferral refused",
                          message, message, "DEBT-DEF-%04d" % status)


def records():
    projected = _ROWS.get()
    return projected if projected is not None else store.read()


def list_for_contract(uid):
    return sorted((r for r in records() if r["contract_uid"] == uid),
                  key=lambda r: (r["created_at"], r["uid"]), reverse=True)


def has_history(contract_uid):
    return any(r["contract_uid"] == contract_uid for r in records())


def customer_has_history(customer_uid):
    return any(r["customer_uid"] == customer_uid for r in records())


def scopes_service_hold(contract, opened_on, issue_uid=None):
    """An approved per-cycle remedy replaces its own contract-wide fault hold."""
    for row in list_for_contract(contract.uid):
        if row["status"] != "ACTIVE":
            continue
        inputs = row["inputs"]
        if issue_uid and inputs.get("issue_uid") == issue_uid:
            return True
        if opened_on and inputs["service_from"] <= str(opened_on)[:10] <= inputs["service_until"]:
            return True
    return False


def effective_hold_field(contract, field, value, slot):
    raw = lambda key: slot[key] if key in slot else getattr(contract, key, None)
    scoped = raw("fee_state") == "SERVICE_HOLD_FAULT_CONFIRMED" and scopes_service_hold(
        contract, raw("fee_state_from"), raw("service_hold_issue_uid"))
    if field == "fee_state_history":
        return [h for h in value or [] if h.get("state") != "SERVICE_HOLD_FAULT_CONFIRMED"
                or not scopes_service_hold(contract, h.get("from"), h.get("issue_uid"))]
    if not scoped:
        return value
    if field == "fee_state":
        return raw("fee_state_before_hold")
    if field == "fee_state_from":
        return raw("fee_state_from_before_hold")
    if field == "fee_state_until":
        return None
    return value


def decorate_issue(issue, contracts):
    if not any(scopes_service_hold(k, issue.get("opened_on"), issue.get("uid")) for k in contracts):
        return issue
    return dict(issue,
        fee_clock_note_th="งวดที่เลื่อนใช้วันครบกำหนดใหม่ในการนับ DPD และค่าปรับ; งวดอื่นยังนับตามปกติ ตั๋วบริการยังดำเนินการแยกกัน",
        fee_clock_note_en="Deferred cycles use their new due dates for DPD and penalties; other cycles continue normally. The service ticket is handled separately.")


def active_moves(contract_uid):
    return {m["n"]: dict(m, deferral_uid=r["uid"], reason=r["reason"])
            for r in list_for_contract(contract_uid) if r["status"] == "ACTIVE"
            for m in r["moves"]}


def raw_lines(contract):
    from . import cases
    slot = cases._fee_overlay().get(contract.uid) or {}
    return slot.get("instalments", contract.instalments)


def ordered_regular(lines):
    from . import request_context
    cache = request_context.reads()
    key = ("service_deferrals.ordered", id(lines), len(lines))
    hit = cache.get(key) if cache is not None else None
    if hit is not None and hit[0] is lines:
        return hit[1]
    ordered = sorted((l for l in lines if l.is_active_regular),
                     key=lambda l: getattr(l, "service_original_due_date", l.due_date))
    if cache is not None: cache[key] = (lines, ordered)
    return ordered


def invoices_for(contract_uid):
    from . import journey, main
    return main.rows_for(journey.for_current().invoices, "contract_uid", {contract_uid})


def cycle_invoices(contract_uid):
    from . import instalment_evidence, journey
    grouped = {}
    found = journey.contract_by_uid(contract_uid)
    lines = ordered_regular(raw_lines(found[1])) if found else []
    for inv in invoices_for(contract_uid):
        n = instalment_evidence.match_invoice(found[1], inv, lines)[0] if found else None
        if n and inv.get("state") not in ("CANCELLED", "DRAFT", "VOID", "AR_REVIEW"):
            grouped.setdefault(n, []).append(inv)
    return grouped


def outstanding(inv):
    if inv.get("confirmed_outstanding") is not None:
        return Decimal(str(inv["confirmed_outstanding"]))
    if inv.get("outstanding") is not None:
        return Decimal(str(inv["outstanding"]))
    return ZERO if inv.get("state") == "PAID" else Decimal(str(inv["amount"]))


def winner(invs):
    return max(invs, key=lambda i: (i.get("issued_on") or "", i.get("peak_number") or i["uid"]))


def apply_schedule(contract, lines):
    if not has_history(contract.uid) and not customer_has_history(getattr(contract, "customer_uid", None)):
        return lines
    mapped = cycle_invoices(contract.uid)
    moved = active_moves(contract.uid)
    numbers = {id(line): n for n, line in enumerate(ordered_regular(lines), 1)}
    result = []
    for original in lines:
        n = numbers.get(id(original))
        if n is None:
            result.append(original)
            continue
        line = replace(original)
        line.service_original_due_date = original.due_date
        line.service_cycle_n = n
        invs = mapped.get(n)
        if invs:
            inv = winner(invs)
            # Confirmed invoice balances replace sheet's inferred paid-through only
            # when this contract has a service adjustment; pending claims are not cash.
            if Decimal(str(inv["amount"])) == line.total_amount:
                paid = max(ZERO, line.total_amount - outstanding(inv))
                line.paid_principal = min(paid, line.principal_amount)
                paid -= line.paid_principal
                line.paid_interest = min(paid, line.interest_amount)
                line.paid_fee = min(max(ZERO, paid - line.paid_interest), line.fee_amount)
        move = moved.get(n)
        if move:
            if move.get("invoice_doc_no") and not any(
                    (i.get("peak_number") or i["uid"]) == move["invoice_doc_no"] for i in (invs or [])):
                raise problem("invoice_missing", "ไม่พบใบแจ้งหนี้เดิมของงวดที่เลื่อน ต้องตรวจสอบการจับคู่ PEAK", 409)
            if str(original.due_date) != move["old_due_date"] or str(line.total_amount.quantize(Decimal('.01'))) != move["amount"]:
                raise problem("schedule_conflict", "ตารางสัญญาเปลี่ยนหลังเลื่อนงวด ต้องตรวจสอบก่อนคำนวณ", 409)
            line.due_date = date.fromisoformat(move["new_due_date"])
            line.service_deferral = move
        result.append(line)
    return result


def decorate_invoice(inv):
    from . import journey
    found = journey.contract_by_uid(inv.get("contract_uid"))
    if found and customer_has_history(found[0].uid):
        inv = dict(inv, service_adjusted=True)
    moves = active_moves(inv.get("contract_uid"))
    if not moves:
        return inv
    n = inv.get("contract_cycle")
    if n is None and found:
        from . import instalment_evidence
        n = instalment_evidence.match_invoice(found[1], inv, ordered_regular(raw_lines(found[1])))[0]
    move = moves.get(n)
    if not move:
        return inv
    return dict(inv, collection_due_date=move["new_due_date"], service_deferral=move,
                collection_status="DEFERRED" if move["new_due_date"] >= str(settings.business_date)
                else "OVERDUE", collection_followup_closed=move["new_due_date"] >= str(settings.business_date))


def _fmt(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


def _contract(uid, active=True):
    from . import journey, cases
    found = journey.contract_by_uid(uid)
    if not found:
        raise problem("not_found", "ไม่พบสัญญา", 404)
    customer, contract = found
    if active and (contract.product != "LEASE" or cases.contract_field_of(contract, "status") in cases.ENDED_CONTRACT_STATUSES):
        raise problem("contract_invalid", "เลื่อนได้เฉพาะสัญญาผ่อนชำระที่ยังไม่สิ้นสุด", 409)
    return customer, contract


def _inputs(customer, body, validate=True):
    from . import cases
    result = {k: str(body.get(k) or "").strip() for k in (
        "reason", "service_from", "service_until", "issue_uid", "confirmation_note", "confirmed_by", "evidence_uid")}
    cycles = body.get("cycles")
    if not isinstance(cycles, list) or not cycles or any(type(n) is not int or n < 1 for n in cycles) or len(set(cycles)) != len(cycles):
        raise problem("cycles_invalid", "เลือกงวดที่ต้องการเลื่อนโดยไม่ซ้ำกัน")
    result["cycles"] = sorted(cycles)
    if not validate:
        return result
    if not result["reason"]:
        raise problem("reason_required", "ต้องระบุเหตุผล")
    try:
        start, end = (date.fromisoformat(result[k]) for k in ("service_from", "service_until"))
        if start > end or end > settings.business_date:
            raise ValueError()
    except ValueError:
        raise problem("date_invalid", "ระบุช่วงที่ใช้งานไม่ได้ให้ถูกต้อง และไม่เกินวันทำการปัจจุบัน") from None
    issue = cases.for_current().issues.get(result["issue_uid"]) if result["issue_uid"] else None
    if result["issue_uid"] and (not issue or issue.get("customer_uid") != customer.uid):
        raise problem("issue_invalid", "ตั๋วปัญหาต้องอยู่ในเคสลูกค้ารายนี้")
    confirmed_ticket = issue and (issue.get("status") == "RESOLVED" or issue.get("fault_confirmed") is True)
    if not confirmed_ticket and not (result["confirmation_note"] and result["confirmed_by"]):
        raise problem("confirmation_required", "ต้องมีตั๋วที่ยืนยันปัญหาแล้ว หรือบันทึกยืนยันปัญหาพร้อมผู้ยืนยัน")
    if result["evidence_uid"]:
        from .attachments import store as attachments
        attachment = attachments.get(result["evidence_uid"])
        if not attachment or attachment[0].get("attached_to") != "case:%s" % customer.uid:
            raise problem("evidence_invalid", "ไฟล์หลักฐานต้องอยู่ในเคสลูกค้ารายนี้")
    return result


def _no_payment(customer, contract, cycles, reversing=False):
    from . import journey, payment_claims
    lines = ordered_regular(raw_lines(contract))
    mapped = cycle_invoices(contract.uid)
    moves = active_moves(contract.uid)
    claims = payment_claims.active_for_customer(customer.uid)
    for n in cycles:
        if n > len(lines):
            raise problem("cycles_invalid", "ไม่พบงวดที่เลือก")
        if not reversing and n in moves:
            raise problem("already_deferred", "งวดนี้ถูกเลื่อนไปแล้ว", 409)
        if not reversing and not (date.fromisoformat(str(lines[n - 1].due_date)) < settings.business_date):
            raise problem("cycle_not_due", "เลื่อนได้เฉพาะงวดที่ครบกำหนดแล้ว", 409)
        invs = mapped.get(n, [])
        if len(invs) > 1:
            raise problem("invoice_ambiguous", "มีหลายใบแจ้งหนี้สำหรับงวดนี้ ต้องตรวจสอบการจับคู่ก่อน", 409)
        if invs and Decimal(str(invs[0]["amount"])) != lines[n - 1].total_amount:
            raise problem("amount_mismatch", "ยอดใบแจ้งหนี้ไม่ตรงกับยอดงวด ต้องตรวจสอบก่อน", 409)
        paid = (outstanding(invs[0]) < Decimal(str(invs[0]["amount"]))) if invs else lines[n - 1].outstanding_amount < lines[n - 1].total_amount
        refs = {i.get("peak_number") or i["uid"] for i in invs}
        ids = {i["uid"] for i in invs}
        received = any(Decimal(str(r.get("amount") or "0")) > ZERO for inv in invs
                       for r in journey.invoice_receipts(journey.for_current(), inv))
        pending = any(Decimal(str(i.get("pending_amount") or "0")) > ZERO for i in invs) or any(
            t.get("invoice_doc_no") in refs for c in claims for t in c.get("targets", []))
        if paid or received or pending or lines[n - 1].total_amount <= ZERO:
            raise problem("payment_conflict", "งวดที่จ่ายแล้ว จ่ายบางส่วน หรือรอยืนยันรับเงิน ไม่สามารถเลื่อนหรือย้อนรายการได้", 409)
    return lines, mapped


def invoice_eligibility(inv):
    """Use the authoritative form validation for the row's disabled reason."""
    try:
        customer, contract = _contract(inv.get("contract_uid"))
        if inv.get("review_status") == "REJECTED":
            raise problem("invoice_rejected", "ต้องรับรองใบแจ้งหนี้กลับก่อนเลื่อนงวด", 409)
        n = inv.get("contract_cycle")
        if not n:
            raise problem("invoice_unmatched", "ต้องแก้ข้อมูลจับคู่สัญญาและเดือนบริการก่อน", 409)
        _no_payment(customer, contract, [n])
        return dict(inv, deferral_eligible=True, deferral_reason=None, deferral_reason_code=None)
    except errors.Problem as exc:
        return dict(inv, deferral_eligible=False, deferral_reason=exc.message_th,
                    deferral_reason_code=exc.code)


def _version(contract, inputs, impact):
    from . import journey, payment_claims
    lines = raw_lines(contract)
    customer, _ = _contract(contract.uid)
    payload = {"contract": contract.uid, "date": str(settings.business_date), "inputs": inputs, "impact": impact,
               "rows": list_for_contract(contract.uid),
               "schedule": [(str(l.due_date), l.schedule_status, str(l.total_amount), str(l.outstanding_amount)) for l in lines],
               "invoices": invoices_for(contract.uid),
               "receipts": [r for r in journey.for_current().receipts.values() if r.get("contract_uid") == contract.uid],
               "claims": payment_claims.active_for_customer(customer.uid)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _impact(contract, projected):
    from . import main
    customer, _ = _contract(contract.uid)
    before = [main._work_out_contract(k)[3] for k in customer.contracts]
    token = _ROWS.set(projected)
    try:
        after = [main._work_out_contract(k)[3] for k in customer.contracts]
        dates = [l.due_date for l in apply_schedule(contract, raw_lines(contract)) if l.is_active_regular]
    finally:
        _ROWS.reset(token)
    return {"collection_overdue_before": _fmt(sum((b.cumulative_arrears for b in before), ZERO)),
            "collection_overdue_after": _fmt(sum((b.cumulative_arrears for b in after), ZERO)),
            "penalty_after": _fmt(sum((b.penalty_accrued_unbilled for b in after), ZERO)),
            "contract_end_after": str(max(dates)), "outstanding_after": _fmt(sum((b.closing_balance for b in after), ZERO))}


def preview(contract_uid, body):
    customer, contract = _contract(contract_uid)
    inputs = _inputs(customer, body)
    lines, mapped = _no_payment(customer, contract, inputs["cycles"])
    existing = active_moves(contract_uid)
    anchor = max([l.due_date for l in lines] + [date.fromisoformat(m["new_due_date"]) for m in existing.values()])
    # Preserve the original billing day across February and 30-day months.
    billing_day = contract.first_due.day
    moves = []
    for offset, n in enumerate(inputs["cycles"], 1):
        month = anchor.month - 1 + offset
        year, month = anchor.year + month // 12, month % 12 + 1
        new_date = date(year, month, min(billing_day, calendar.monthrange(year, month)[1]))
        inv = mapped[n][0] if mapped.get(n) else None
        moves.append({"n": n, "old_due_date": str(lines[n - 1].due_date), "new_due_date": str(new_date),
                      "amount": _fmt(lines[n - 1].total_amount),
                      "invoice_uid": inv["uid"] if inv else None,
                      "invoice_doc_no": (inv.get("peak_number") or inv["uid"]) if inv else None})
    projected = {"uid": "preview", "contract_uid": contract_uid, "customer_uid": customer.uid,
                 "inputs": inputs, "status": "ACTIVE",
                 "moves": moves, "reason": inputs["reason"], "created_at": "preview"}
    impact = _impact(contract, records() + [projected])
    return dict(impact, version=_version(contract, inputs, impact), moves=moves,
                contract_uid=contract_uid, contract_end_before=str(max(
                    l.due_date for l in apply_schedule(contract, raw_lines(contract)) if l.is_active_regular)))


def confirm(contract_uid, body, by, role):
    key = str(body.get("idempotency_key") or "").strip()
    if not key or len(key) > 200:
        raise problem("idempotency_required", "ต้องมีรหัสคำสั่งสำหรับป้องกันการบันทึกซ้ำ")
    with store.transaction() as (rows, save):
        token = _ROWS.set(rows)
        try:
            duplicate = next((r for r in rows if r["contract_uid"] == contract_uid and r["idempotency_key"] == key), None)
            if duplicate:
                if duplicate["inputs"] != _inputs(None, body, validate=False) or duplicate["created_by"] != by:
                    raise problem("idempotency_conflict", "รหัสคำสั่งนี้ถูกใช้กับรายการอื่นแล้ว", 409)
                return duplicate
            customer, contract = _contract(contract_uid)
            inputs = _inputs(customer, body)
            current = preview(contract_uid, body)
            if current["version"] != body.get("preview_version"):
                raise problem("preview_stale", "ข้อมูลเปลี่ยนแล้ว กรุณาดูตัวอย่างใหม่ก่อนยืนยัน", 409)
            stamp = clock.business_now().isoformat()
            row = {"uid": "sdef-" + uuid.uuid4().hex, "contract_uid": contract_uid,
                   "customer_uid": customer.uid, "customer_no": str(customer.customer_no),
                   "status": "ACTIVE", "inputs": inputs,
                   "reason": inputs["reason"], "moves": current["moves"], "created_at": stamp,
                   "contract_end_before": current["contract_end_before"], "contract_end_after": current["contract_end_after"],
                   "created_by": by, "created_role": role, "idempotency_key": key,
                   "accounting": {"status": "PENDING_REVIEW", "document_refs": [], "history": []},
                   "history": [{"act": "CONFIRMED", "by": by, "role": role, "at": stamp}]}
            if inputs.get("issue_uid"):
                from . import cases
                issue = cases.for_current().issues[inputs["issue_uid"]]
                row["ticket_evidence"] = {k: issue.get(k) for k in (
                    "uid", "ticket_ref", "ticket_url", "ticket_status", "status", "fault_confirmed", "summary", "opened_by",
                    "opened_on", "resolved_on", "closed_by", "resolution_note", "responsible_team")}
            save(row)
            return row
        finally:
            _ROWS.reset(token)


def reverse_preview(contract_uid, uid, reason):
    customer, contract = _contract(contract_uid)
    row = next((r for r in list_for_contract(contract_uid) if r["uid"] == uid), None)
    if not row:
        raise problem("not_found", "ไม่พบรายการเลื่อนงวด", 404)
    if row["status"] != "ACTIVE":
        raise problem("already_reversed", "รายการนี้ถูกย้อนแล้ว", 409)
    reason = str(reason or "").strip()
    if not reason:
        raise problem("reason_required", "ต้องระบุเหตุผลที่ย้อนรายการ")
    _no_payment(customer, contract, [m["n"] for m in row["moves"]], reversing=True)
    projected = [dict(r, status="REVERSED") if r["uid"] == uid else r for r in records()]
    impact = _impact(contract, projected)
    return dict(impact, moves=row["moves"],
                version=_version(contract, {"reverse_uid": uid, "reason": reason}, impact))


def reverse(contract_uid, uid, body, by, role):
    with store.transaction() as (rows, save):
        token = _ROWS.set(rows)
        try:
            current = reverse_preview(contract_uid, uid, body.get("reason"))
            if current["version"] != body.get("preview_version"):
                raise problem("preview_stale", "ข้อมูลเปลี่ยนแล้ว กรุณาดูตัวอย่างใหม่ก่อนย้อนรายการ", 409)
            row = next(r for r in rows if r["uid"] == uid)
            stamp = clock.business_now().isoformat()
            row = dict(row, status="REVERSED", reversed_at=stamp, reversed_by=by,
                       reversal_reason=body["reason"], history=row["history"] + [{
                           "act": "REVERSED", "by": by, "role": role, "at": stamp, "reason": body["reason"]}])
            row["accounting"] = dict(row["accounting"], status="PENDING_REVIEW")
            save(row)
            return row
        finally:
            _ROWS.reset(token)


def accounting_update(contract_uid, uid, body, by, role):
    _contract(contract_uid, active=False)
    refs = body.get("document_refs")
    note = str(body.get("note") or "").strip()
    if body.get("status") not in ("PENDING_REVIEW", "REVIEWED") or not note or not isinstance(refs, list) or any(not isinstance(r, str) or not r.strip() for r in refs):
        raise problem("accounting_invalid", "ต้องระบุสถานะ ผลตรวจสอบ และเลขเอกสารที่เกี่ยวข้อง (ถ้ามี)")
    with store.transaction() as (rows, save):
        row = next((r for r in rows if r["uid"] == uid and r["contract_uid"] == contract_uid), None)
        if not row:
            raise problem("not_found", "ไม่พบรายการเลื่อนงวด", 404)
        history = row["accounting"]["history"] + [{"by": by, "role": role, "at": clock.business_now().isoformat(),
                                                   "status": body["status"], "document_refs": refs, "note": note}]
        row = dict(row, accounting={"status": body["status"], "document_refs": refs, "note": note, "history": history})
        save(row)
        return row


def sync_followup(state, case, customer):
    """Retire stale debt tasks, while preserving callbacks, PTP and ticket tasks."""
    from . import main, cases
    active = [r for r in records() if r["customer_uid"] == customer.uid and r["status"] == "ACTIVE"]
    previous = case.get("service_deferral_followup")
    if not active:
        if previous and case.get("next_action_set_by") == "SERVICE_DEFERRAL":
            for key in ("next_action", "next_action_on", "next_action_set_by"):
                case[key] = previous[key]
        case.pop("service_deferral_followup", None)
        return
    if main._customer_aggregate(customer)[0] > ZERO:
        return
    if case.get("open_ptp_uid") or case.get("next_action") not in (
            "CALL", "SEND_REMINDER", "SEND_INVOICE_LINK", "LINE_FOLLOW_UP"):
        return
    if case.get("next_action_on") and case["next_action_on"] > str(settings.business_date):
        return
    future = [l.due_date for k in customer.contracts for l in cases.contract_field_of(k, "instalments")
              if l.is_active_regular and l.outstanding_amount > ZERO and l.due_date >= settings.business_date]
    if not future:
        return
    old = {k: case.get(k) for k in ("next_action", "next_action_on", "next_action_set_by")}
    case.setdefault("service_deferral_followup_history", []).append(dict(
        old, closed_by="SERVICE_DEFERRAL", on=str(settings.business_date), deferral_uids=[r["uid"] for r in active]))
    case["service_deferral_followup"] = old
    cases.set_next_action(state, case, case["next_action"], min(future), by="SERVICE_DEFERRAL",
                          note="จบงานติดตามงวดที่เลื่อนเพราะปัญหาบริการ และติดตามงวดที่ครบกำหนดถัดไป")
