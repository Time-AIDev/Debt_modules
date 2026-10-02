"""Amount-led, auditable payment claims.

A claim is the collection officer's provisional observation that money arrived.  It
never changes confirmed receivables.  PEAK receipt reconciliation resolves it later;
until then the customer reads PENDING and the case exposes both confirmed and
projected balances.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import re
import threading
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from . import clock, db, errors

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
ACTIVE_STATES = ("PENDING",)
STATES = ("PENDING", "CONFIRMED", "PARTIALLY_CONFIRMED", "NEEDS_REVIEW", "CANCELLED")
GOVERNED_PAYMENT_STATUSES = ("NPL", "CLOSED", "TERMINATED", "NOT_INSTALLED")

_LOCK = threading.RLock()
_MEMORY = {}              # uid -> claim
_REMINDERS = {}           # (customer_uid, YYYY-MM) -> reminder
_COUNTER = 0
_VERSION = 0

# One read per request, not one per row: a book build asks for the pending claims
# once per case (cases._apply_payment_claims runs on every cases.for_current(), and
# today.build/board.facts_for call that per item). On 2026-09-29 the local book paid
# ~5,900 identical `list_all(PENDING)` reads on a single /v1/today. The memo lives in
# a ContextVar, so it is scoped to the request's own context and dies with it; the
# _VERSION guard drops it when a write in this process lands mid-request. A write
# from another process mid-request is seen on the next request, the same window every
# request-scoped read has.
_READ_CACHE: contextvars.ContextVar = contextvars.ContextVar("payment_claims_read_cache", default=None)


def _read_cache():
    cache = _READ_CACHE.get()
    if cache is None:
        cache = {}
        _READ_CACHE.set(cache)
    return cache


def _money(value, pointer="/amount"):
    try:
        amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise errors.Problem(
            code="payment_claim_amount_invalid", status=422, title="Invalid payment amount",
            detail="amount must be a decimal number greater than zero",
            message_th="ยอดรับชำระไม่ถูกต้อง กรุณาระบุจำนวนที่มากกว่าศูนย์",
            error_id="DEBT-PAY-0422", errors=[{"pointer": pointer, "code": "invalid"}])
    if amount <= ZERO:
        raise errors.Problem(
            code="payment_claim_amount_invalid", status=422, title="Invalid payment amount",
            detail="amount must be greater than zero",
            message_th="ยอดรับชำระต้องมากกว่าศูนย์", error_id="DEBT-PAY-0422",
            errors=[{"pointer": pointer, "code": "minimum"}])
    return amount


def _iso_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        raise errors.Problem(
            code="payment_claim_date_invalid", status=422, title="Invalid payment date",
            detail="paid_on must be an ISO calendar date",
            message_th="วันที่รับชำระไม่ถูกต้อง", error_id="DEBT-PAY-0423",
            errors=[{"pointer": "/paid_on", "code": "invalid"}])


def _fmt(value):
    return str(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def _doc_no(invoice):
    return invoice.get("peak_number") or invoice.get("doc_no") or invoice.get("uid")


def _outstanding(invoice):
    if invoice.get("confirmed_outstanding") is not None:
        return max(ZERO, Decimal(str(invoice["confirmed_outstanding"])))
    if invoice.get("outstanding") is not None:
        return max(ZERO, Decimal(str(invoice["outstanding"])))
    if invoice.get("state") == "PAID":
        return ZERO
    return max(ZERO, Decimal(str(invoice.get("amount") or invoice.get("amount_due") or "0")))


def allocate_preview(invoices, amount, reference=None, existing_pending=None):
    """Invoice-level allocation: named invoice, then oldest due, then customer credit.

    This deliberately does not allocate principal/interest/fee; OD-02 remains intact.
    """
    amount = Decimal(amount).quantize(CENT)
    existing_pending = existing_pending or {}
    confirmed_total = sum((_outstanding(inv) for inv in invoices), ZERO)
    remaining = amount

    ordered = sorted(
        invoices,
        key=lambda inv: (
            0 if reference and _doc_no(inv) == reference else 1,
            str(inv.get("collection_due_date") or inv.get("due_date") or "9999-12-31"),
            str(inv.get("issued_on") or "9999-12-31"),
            str(_doc_no(inv) or ""),
        ),
    )
    allocations = []
    for inv in ordered:
        if remaining <= ZERO:
            break
        doc = _doc_no(inv)
        before = _outstanding(inv)
        pending = max(ZERO, Decimal(str(existing_pending.get(doc, ZERO))))
        available = max(ZERO, before - pending)
        take = min(remaining, available)
        if take <= ZERO:
            continue
        remaining -= take
        allocations.append({
            "invoice_doc_no": doc,
            "invoice_uid": inv.get("uid"),
            "before": _fmt(before),
            "already_pending": _fmt(pending),
            "amount": _fmt(take),
            "after": _fmt(available - take),
            "order": len(allocations) + 1,
        })
    pending_allocated = amount - remaining
    return {
        "allocations": allocations,
        "confirmed_outstanding": _fmt(confirmed_total),
        "pending_allocated": _fmt(pending_allocated),
        "projected_outstanding": _fmt(max(ZERO, confirmed_total - sum(existing_pending.values(), ZERO) - pending_allocated)),
        "credit": _fmt(remaining),
    }


def _identity_of(row):
    return (row.get("customer_uid") or row.get("customer_no")
            or row.get("contact_code"))


def reconcile_receipts(invoices, receipt_observations):
    """Pure amount-led reconciliation across every receipt observation.

    The latest observation of a receipt number wins, making repeated exports
    idempotent and allowing a later CANCELLED observation to reverse its cash.
    A receipt can allocate only when both its invoice reference and customer
    identity agree. Excess then rolls to the customer's other invoices FIFO and
    finally becomes customer credit.
    """
    latest = {}
    for index, raw in enumerate(receipt_observations):
        receipt = dict(raw)
        doc_no = str(receipt.get("doc_no") or "").strip()
        if not doc_no:
            continue
        key = (str(receipt.get("observed_at") or receipt.get("exported_at") or ""),
               int(receipt.get("run_id") or receipt.get("source_run_id") or 0), index)
        if doc_no not in latest or key > latest[doc_no][0]:
            latest[doc_no] = (key, receipt)

    invoice_rows = {str(_doc_no(inv)): dict(inv) for inv in invoices}
    remaining = {doc: _outstanding(inv) for doc, inv in invoice_rows.items()}
    received = {doc: ZERO for doc in invoice_rows}
    after_snapshot = {doc: ZERO for doc in invoice_rows}
    allocations, exceptions, credit_by_customer = [], [], {}

    active = [value[1] for value in latest.values()
              if str(value[1].get("status") or "").upper() not in ("DRAFT", "CANCELLED")]
    active.sort(key=lambda row: (str(row.get("paid_on") or ""), str(row.get("doc_no") or "")))
    for receipt in active:
        status = str(receipt.get("status") or "").upper()
        if status != "PAID":
            exceptions.append({"receipt_doc_no": receipt.get("doc_no"),
                               "reason": "STATUS_UNKNOWN", "status": status or None})
            continue
        ref = str(receipt.get("invoice_ref") or "").strip()
        invoice = invoice_rows.get(ref)
        if not ref or invoice is None:
            exceptions.append({"receipt_doc_no": receipt.get("doc_no"),
                               "reason": "MISSING_INVOICE" if ref else "MISSING_INVOICE_REFERENCE",
                               "invoice_ref": ref or None})
            continue
        receipt_customer, invoice_customer = _identity_of(receipt), _identity_of(invoice)
        if not receipt_customer or not invoice_customer or str(receipt_customer) != str(invoice_customer):
            exceptions.append({"receipt_doc_no": receipt.get("doc_no"),
                               "reason": "CUSTOMER_MISMATCH", "invoice_ref": ref,
                               "receipt_customer": receipt_customer,
                               "invoice_customer": invoice_customer})
            continue
        try:
            amount = _money(receipt.get("paid_amount"), pointer="/paid_amount")
        except errors.Problem:
            exceptions.append({"receipt_doc_no": receipt.get("doc_no"),
                               "reason": "AMOUNT_INVALID", "invoice_ref": ref})
            continue
        customer_invoices = [inv for inv in invoice_rows.values()
                             if str(_identity_of(inv)) == str(invoice_customer)]
        ordered = sorted(customer_invoices, key=lambda inv: (
            0 if _doc_no(inv) == ref else 1,
            str(inv.get("collection_due_date") or inv.get("due_date") or inv.get("due_on") or "9999-12-31"),
            str(inv.get("issued_on") or "9999-12-31"), str(_doc_no(inv))))
        left = amount
        if invoice.get("service_adjusted"):
            # Reconstruct this receipt's named invoice from its face amount. The
            # latest PEAK balance may already include the historical receipt; its
            # zero balance must not make M3 cash spill into a deferred M1.
            remaining[ref] = max(remaining[ref], Decimal(str(invoice["amount"])) - received[ref])
        for inv in ordered:
            if left <= ZERO:
                break
            doc = str(_doc_no(inv))
            take = min(left, remaining[doc])
            if take <= ZERO:
                continue
            before = remaining[doc]
            remaining[doc] -= take
            received[doc] += take
            cutoff = inv.get("snapshot_as_of")
            if inv.get("service_adjusted") and cutoff and str(receipt.get("paid_on") or "")[:10] > str(cutoff)[:10]:
                after_snapshot[doc] += take
            left -= take
            allocations.append({
                "receipt_doc_no": receipt["doc_no"], "invoice_doc_no": doc,
                "customer_uid": invoice.get("customer_uid") or receipt.get("customer_uid"),
                "customer_no": invoice.get("customer_no") or receipt.get("customer_no"),
                "amount": _fmt(take), "before": _fmt(before), "after": _fmt(remaining[doc]),
                "order": len([a for a in allocations if a["receipt_doc_no"] == receipt["doc_no"]]) + 1,
                "source_run_id": receipt.get("run_id") or receipt.get("source_run_id"),
            })
        if left > ZERO:
            customer_key = str(invoice.get("customer_uid") or invoice_customer)
            credit_by_customer[customer_key] = credit_by_customer.get(customer_key, ZERO) + left
            allocations.append({
                "receipt_doc_no": receipt["doc_no"], "invoice_doc_no": None,
                "customer_uid": invoice.get("customer_uid") or receipt.get("customer_uid"),
                "customer_no": invoice.get("customer_no") or receipt.get("customer_no"),
                "amount": _fmt(left), "before": "0.00", "after": _fmt(left),
                "order": len([a for a in allocations if a["receipt_doc_no"] == receipt["doc_no"]]) + 1,
                "source_run_id": receipt.get("run_id") or receipt.get("source_run_id"),
            })

    reconciled_invoices = {}
    for doc, inv in invoice_rows.items():
        left = remaining[doc]
        if inv.get("service_adjusted"):
            total = Decimal(str(inv["amount"]))
            snapshot_paid = total - _outstanding(inv)
            left = max(ZERO, total - max(received[doc], snapshot_paid + after_snapshot[doc]))
        state = "PAID" if left == ZERO else ("PARTIALLY_PAID" if received[doc] > ZERO
                                                else inv.get("state") or inv.get("status") or "OVERDUE")
        paid = Decimal(str(inv["amount"])) - left if inv.get("service_adjusted") else received[doc]
        reconciled_invoices[doc] = dict(inv, confirmed_paid=_fmt(paid),
                                        confirmed_outstanding=_fmt(left), state=state, status=state)
    return {
        "allocations": allocations, "invoices": reconciled_invoices,
        "credit_by_customer": {key: _fmt(value) for key, value in credit_by_customer.items()},
        "exceptions": exceptions, "active_receipts": len(active),
    }


def _customer_invoices(customer_uid):
    from . import journey, service_deferrals
    customer = journey.customer_by_uid(customer_uid)
    if customer is None:
        raise errors.Problem(code="not_found", status=404, title="Customer not found",
                             detail="no customer %s" % customer_uid,
                             message_th="ไม่พบลูกค้า", error_id="DEBT-PLT-0404")
    contracts = {k.uid for k in getattr(customer, "contracts", ())}
    return [dict(service_deferrals.decorate_invoice(inv)) for inv in journey.for_current().invoices.values()
            if inv.get("contract_uid") in contracts]


def _case(customer_uid):
    from . import cases
    case = cases.for_current().cases.get(customer_uid)
    if case is None:
        raise errors.Problem(code="not_found", status=404, title="Case not found",
                             detail="no case for customer %s" % customer_uid,
                             message_th="ไม่พบเคสของลูกค้า", error_id="DEBT-PLT-0404")
    return case


def _assert_allowed(case):
    confirmed = case.get("payment_status_confirmed") or case.get("payment_status_system") or case.get("payment_status")
    if confirmed in GOVERNED_PAYMENT_STATUSES:
        raise errors.Problem(
            code="payment_claim_status_governed", status=409,
            title="This governed status cannot enter payment pending",
            detail="payment claims are unavailable while the customer is %s" % confirmed,
            message_th="สถานะของลูกค้ารายนี้ไม่อนุญาตให้บันทึกรอการยืนยันชำระ",
            error_id="DEBT-PAY-0409", extensions={"payment_status": confirmed})


def _memory_claims(customer_uid=None):
    with _LOCK:
        rows = [dict(row) for row in _MEMORY.values()
                if customer_uid is None or row["customer_uid"] == customer_uid]
    return sorted(rows, key=lambda r: (r["created_at"], r["uid"]), reverse=True)


def list_for_customer(customer_uid):
    # The in-memory store is the local/test path. DB persistence is added below by
    # the same public contract; callers do not know which one serves them.
    if not db.configured():
        return _memory_claims(customer_uid)
    from sqlalchemy import text
    conn = db.connect()
    try:
        rows = conn.execute(text(
            "select * from records.payment_claim where customer_uid = :c "
            "order by created_at desc, uid desc"), {"c": customer_uid}).mappings().all()
        targets = conn.execute(text(
            "select * from records.payment_claim_target where claim_uid = any(:ids) order by claim_uid, allocation_order"),
            {"ids": [r["uid"] for r in rows] or ["-"]}).mappings().all()
    finally:
        conn.close()
    by = {}
    for target in targets:
        by.setdefault(target["claim_uid"], []).append(dict(target))
    return [_serialise(dict(row), by.get(row["uid"], [])) for row in rows]


def list_all(state=None):
    if state and state not in STATES:
        raise errors.Problem(code="payment_claim_state_invalid", status=422,
                             title="Invalid payment claim state", detail="unknown claim state",
                             message_th="สถานะรายการรับชำระไม่ถูกต้อง", error_id="DEBT-PAY-0426")
    cache = _read_cache()
    key = (_VERSION, state)
    if key in cache:
        return cache[key]
    if not db.configured():
        rows = _memory_claims()
        result = [row for row in rows if not state or row["state"] == state]
    else:
        from sqlalchemy import text
        conn = db.connect()
        try:
            where = "where state=:state" if state else ""
            rows = conn.execute(text(
                "select * from records.payment_claim %s order by created_at desc, uid desc" % where),
                {"state": state} if state else {}).mappings().all()
            ids = [row["uid"] for row in rows]
            targets = conn.execute(text(
                "select * from records.payment_claim_target where claim_uid = any(:ids) "
                "order by claim_uid, allocation_order"), {"ids": ids or ["-"]}).mappings().all()
        finally:
            conn.close()
        by = {}
        for target in targets:
            by.setdefault(target["claim_uid"], []).append(dict(target))
        result = [_serialise(dict(row), by.get(row["uid"], [])) for row in rows]
    cache[key] = result
    return result


def pending_by_customer():
    """PENDING claims grouped by customer_uid — the read `cases._apply_payment_claims`
    repeats per case. Built once per request on top of the memoised `list_all`."""
    cache = _read_cache()
    key = (_VERSION, "PENDING_BY_CUSTOMER")
    if key in cache:
        return cache[key]
    grouped = {}
    for row in list_all(state="PENDING"):
        grouped.setdefault(row["customer_uid"], []).append(row)
    cache[key] = grouped
    return grouped


def active_for_customer(customer_uid):
    return [row for row in list_for_customer(customer_uid) if row["state"] in ACTIVE_STATES]


def _pending_by_invoice(customer_uid):
    out = {}
    for claim in active_for_customer(customer_uid):
        for target in claim.get("targets") or []:
            doc = target.get("invoice_doc_no")
            out[doc] = out.get(doc, ZERO) + Decimal(str(target.get("amount") or "0"))
    return out


def _version(customer_uid, invoices=None):
    invoices = invoices if invoices is not None else _customer_invoices(customer_uid)
    payload = {
        "invoices": [(_doc_no(i), _fmt(_outstanding(i)), i.get("collection_due_date") or i.get("due_date")) for i in invoices],
        "claims": [(r["uid"], r["state"], r["amount"]) for r in active_for_customer(customer_uid)],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def preview(customer_uid, amount, paid_on, reference=None, evidence_uid=None):
    case = _case(customer_uid)
    _assert_allowed(case)
    amount = _money(amount)
    paid_on = _iso_date(paid_on)
    invoices = _customer_invoices(customer_uid)
    result = allocate_preview(invoices, amount, reference=reference,
                              existing_pending=_pending_by_invoice(customer_uid))
    duplicates = [row["uid"] for row in active_for_customer(customer_uid)
                  if Decimal(str(row["amount"])) == amount
                  and str(row["paid_on"]) == paid_on
                  and (row.get("evidence_uid") or None) == (evidence_uid or None)]
    return dict(result, customer_uid=customer_uid, amount=_fmt(amount), paid_on=paid_on,
                reference=reference, version=_version(customer_uid, invoices),
                duplicate_warning=bool(duplicates), duplicate_claim_uids=duplicates)


def _serialise(row, targets=None):
    out = dict(row)
    for key in ("amount", "confirmed_amount", "credit_amount"):
        if key in out and out[key] is not None:
            out[key] = _fmt(out[key])
    for key in ("paid_on",):
        if out.get(key) is not None:
            out[key] = str(out[key])
    for key in ("created_at", "resolved_at", "cancelled_at"):
        if out.get(key) is not None:
            out[key] = out[key].isoformat() if hasattr(out[key], "isoformat") else str(out[key])
    if targets is not None:
        out["targets"] = [{**dict(t), "amount": _fmt(t["amount"])} for t in targets]
    return out


def create(customer_uid, amount, paid_on, by, role, idempotency_key,
           preview_version, note=None, evidence_uid=None, reference=None):
    global _COUNTER, _VERSION
    case = _case(customer_uid)
    _assert_allowed(case)
    clean_note = str(note or "").strip()
    if not clean_note:
        raise errors.validation_failed([{
            "pointer": "/note", "code": "required", "message": "note is required",
            "message_th": "กรุณาระบุหมายเหตุ",
        }])
    key = str(idempotency_key or "").strip()
    if not key:
        raise errors.Problem(code="idempotency_key_required", status=422,
                             title="Idempotency key required", detail="payment claims require idempotency_key",
                             message_th="ไม่พบรหัสป้องกันการบันทึกซ้ำ", error_id="DEBT-PAY-0424")
    existing = next((r for r in list_for_customer(customer_uid) if r.get("idempotency_key") == key), None)
    if existing:
        return existing, False
    if evidence_uid:
        from .attachments import store as attachment_store
        found = attachment_store.get(evidence_uid)
        if found is None or found[0].get("attached_to") != "case:%s" % customer_uid:
            raise errors.Problem(
                code="payment_claim_evidence_invalid", status=422,
                title="Payment evidence is unavailable",
                detail="evidence must be an active attachment on this customer case",
                message_th="หลักฐานต้องเป็นไฟล์ที่แนบอยู่กับเคสลูกค้ารายนี้",
                error_id="DEBT-PAY-0427",
                errors=[{"pointer": "/evidence_uid", "code": "invalid"}])
    current = preview(customer_uid, amount, paid_on, reference=reference,
                      evidence_uid=evidence_uid)
    if preview_version != current["version"]:
        raise errors.Problem(code="payment_claim_preview_stale", status=409,
                             title="Payment preview changed", detail="invoice or pending balances changed after preview",
                             message_th="ยอดเปลี่ยนหลังจากแสดงตัวอย่าง กรุณาตรวจสอบใหม่",
                             error_id="DEBT-PAY-0410", retryable=True,
                             extensions={"current_version": current["version"]})
    now = clock.business_now().replace(tzinfo=clock.BANGKOK)
    if not db.configured():
        with _LOCK:
            replay = next((row for row in _MEMORY.values()
                           if row["customer_uid"] == customer_uid
                           and row["idempotency_key"] == key), None)
            if replay is not None:
                return dict(replay), False
            _COUNTER += 1
            uid = "pcl-%06d" % _COUNTER
            row = {
                "uid": uid, "customer_uid": customer_uid, "amount": current["amount"],
                "paid_on": current["paid_on"], "reference": reference,
                "evidence_uid": evidence_uid, "note": clean_note,
                "created_by": by, "created_role": role, "created_at": now.isoformat(),
                "idempotency_key": key, "state": "PENDING", "confirmed_amount": "0.00",
                "credit_amount": current["credit"], "resolution_run_id": None,
                "resolved_at": None, "resolution_note": None,
                "targets": [dict(t) for t in current["allocations"]],
            }
            _MEMORY[uid] = row
            _VERSION += 1
        return dict(row), True
    return _create_db(current, by, role, key, clean_note, evidence_uid, reference)


def _create_db(current, by, role, key, note, evidence_uid, reference):
    global _VERSION
    from sqlalchemy import text
    import uuid
    uid = "pcl-" + uuid.uuid4().hex
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text(
                "insert into records.payment_claim "
                "(uid, customer_uid, amount, paid_on, reference, evidence_uid, note, created_by, created_role, "
                "idempotency_key, state, confirmed_amount, credit_amount) "
                "values (:uid,:customer,:amount,:paid_on,:reference,:evidence,:note,:by,:role,:key,'PENDING',0,:credit) "
                "on conflict (customer_uid,idempotency_key) do nothing returning *"),
                {"uid": uid, "customer": current["customer_uid"], "amount": current["amount"],
                 "paid_on": current["paid_on"], "reference": reference, "evidence": evidence_uid,
                 "note": (str(note).strip() or None) if note else None, "by": by, "role": role,
                 "key": key, "credit": current["credit"]}).mappings().first()
            created = row is not None
            if created:
                for target in current["allocations"]:
                    conn.execute(text(
                        "insert into records.payment_claim_target "
                        "(claim_uid, invoice_doc_no, invoice_uid, amount, allocation_order, before_amount, after_amount) "
                        "values (:claim,:doc,:invoice_uid,:amount,:ord,:before,:after)"),
                        {"claim": uid, "doc": target["invoice_doc_no"], "invoice_uid": target.get("invoice_uid"),
                         "amount": target["amount"], "ord": target["order"],
                         "before": target["before"], "after": target["after"]})
                targets = current["allocations"]
            else:
                row = conn.execute(text(
                    "select * from records.payment_claim "
                    "where customer_uid=:customer and idempotency_key=:key"),
                    {"customer": current["customer_uid"], "key": key}).mappings().one()
                targets = conn.execute(text(
                    "select * from records.payment_claim_target where claim_uid=:claim "
                    "order by allocation_order"), {"claim": row["uid"]}).mappings().all()
    finally:
        conn.close()
    if created:
        _VERSION += 1
    return _serialise(dict(row), [dict(target) for target in targets]), created


def cancel(uid, by, role):
    global _VERSION
    if not db.configured():
        with _LOCK:
            row = _MEMORY.get(uid)
            if row is None:
                raise errors.Problem(code="not_found", status=404, title="Claim not found", detail="no payment claim %s" % uid,
                                     message_th="ไม่พบรายการรอยืนยัน", error_id="DEBT-PLT-0404")
            if row["state"] != "PENDING":
                raise errors.Problem(code="payment_claim_not_pending", status=409, title="Claim is not pending",
                                     detail="only a pending claim can be cancelled",
                                     message_th="ยกเลิกได้เฉพาะรายการที่ยังรอยืนยัน",
                                     error_id="DEBT-PAY-0411")
            if by != row["created_by"] and role not in ("MANAGER", "OWNER"):
                raise errors.Problem(code="forbidden", status=403, title="Not allowed", detail="only creator or manager may cancel",
                                     message_th="เฉพาะผู้บันทึกหรือผู้จัดการเท่านั้นที่ยกเลิกได้",
                                     error_id="DEBT-IAM-0403")
            row["state"], row["cancelled_by"] = "CANCELLED", by
            row["cancelled_at"] = clock.stamp()
            _VERSION += 1
            return dict(row)
    from sqlalchemy import text
    conn = db.connect()
    try:
        with conn.begin():
            row = conn.execute(text("select * from records.payment_claim where uid=:uid for update"), {"uid": uid}).mappings().first()
            if row is None:
                raise errors.Problem(code="not_found", status=404, title="Claim not found", detail="no payment claim",
                                     message_th="ไม่พบรายการรอยืนยัน", error_id="DEBT-PLT-0404")
            if row["state"] != "PENDING":
                raise errors.Problem(code="payment_claim_not_pending", status=409, title="Claim is not pending",
                                     detail="only pending claims can be cancelled", message_th="ยกเลิกได้เฉพาะรายการที่ยังรอยืนยัน",
                                     error_id="DEBT-PAY-0411")
            if by != row["created_by"] and role not in ("MANAGER", "OWNER"):
                raise errors.Problem(code="forbidden", status=403, title="Not allowed", detail="only creator or manager may cancel",
                                     message_th="เฉพาะผู้บันทึกหรือผู้จัดการเท่านั้นที่ยกเลิกได้", error_id="DEBT-IAM-0403")
            updated = conn.execute(text(
                "update records.payment_claim set state='CANCELLED', cancelled_by=:by, cancelled_at=now() "
                "where uid=:uid returning *"), {"uid": uid, "by": by}).mappings().one()
    finally:
        conn.close()
    _VERSION += 1
    return _serialise(dict(updated))


def _confirmed_allocations(customer_uid):
    if not db.configured():
        return [], ZERO
    from sqlalchemy import text
    conn = db.connect()
    try:
        rows = conn.execute(text(
            "select receipt_doc_no, invoice_doc_no, amount, allocation_order, source_run_id, "
            "before_amount, after_amount from records.payment_allocation "
            "where customer_uid=:uid and active order by receipt_doc_no, allocation_order"),
            {"uid": customer_uid}).mappings().all()
    finally:
        conn.close()
    credit = sum((Decimal(row["amount"]) for row in rows if row["invoice_doc_no"] is None), ZERO)
    return [dict(row) for row in rows], credit


def decorate(customer_uid, case, invoices):
    claims = list_for_customer(customer_uid)
    active = [r for r in claims if r["state"] == "PENDING"]
    pending_by = {}
    for claim in active:
        for target in claim.get("targets") or []:
            doc = target["invoice_doc_no"]
            pending_by[doc] = pending_by.get(doc, ZERO) + Decimal(str(target["amount"]))
    confirmed_allocations, confirmed_credit = _confirmed_allocations(customer_uid)
    allocation_by_invoice = {}
    for allocation in confirmed_allocations:
        if allocation.get("invoice_doc_no"):
            allocation_by_invoice.setdefault(allocation["invoice_doc_no"], []).append(allocation)
    annotated = []
    confirmed = ZERO
    for inv in invoices:
        before = _outstanding(inv)
        pending = min(before, pending_by.get(_doc_no(inv), ZERO))
        confirmed += before
        amount = Decimal(str(inv.get("amount") or inv.get("amount_due") or "0"))
        confirmed_paid = max(ZERO, amount - before)
        if before == ZERO:
            amount_state = "PAID"
        elif confirmed_paid > ZERO:
            amount_state = "PARTIALLY_PAID"
        else:
            amount_state = inv.get("state") or inv.get("status") or "OVERDUE"
        invoice_allocations = allocation_by_invoice.get(_doc_no(inv), [])
        annotated.append(dict(inv,
                              state=amount_state,
                              confirmed_paid=_fmt(confirmed_paid),
                              pending_amount=_fmt(pending),
                              confirmed_outstanding=_fmt(before),
                              projected_outstanding=_fmt(before - pending),
                              payment_allocations=[{**row, "amount": _fmt(row["amount"]),
                                                    "before_amount": _fmt(row["before_amount"]),
                                                    "after_amount": _fmt(row["after_amount"])}
                                                   for row in invoice_allocations],
                              receipt_references=[row["receipt_doc_no"] for row in invoice_allocations]))
    pending_amount = sum((Decimal(str(r["amount"])) for r in active), ZERO)
    pending_credit = sum((Decimal(str(r.get("credit_amount") or "0")) for r in active), ZERO)
    case_view = dict(case)
    base = case.get("payment_status_confirmed") or case.get("payment_status_system") or case.get("payment_status")
    case_view["payment_status_confirmed"] = base
    if active and base not in GOVERNED_PAYMENT_STATUSES:
        case_view["payment_status"] = "PENDING"
        case_view["payment_pending_since"] = min(r["created_at"] for r in active)
    position = {
        "confirmed_outstanding": _fmt(confirmed),
        "pending_amount": _fmt(pending_amount),
        "projected_outstanding": _fmt(max(ZERO, confirmed - pending_amount)),
        "credit_balance": _fmt(confirmed_credit),
        "pending_credit": _fmt(pending_credit),
        "active_claims": len(active),
    }
    return case_view, annotated, claims, position


def reconciliation_exceptions():
    if not db.configured():
        return [row for row in _memory_claims() if row["state"] == "NEEDS_REVIEW"]
    from sqlalchemy import text
    conn = db.connect()
    try:
        claims = conn.execute(text(
            "select * from records.payment_claim where state='NEEDS_REVIEW' "
            "order by resolved_at desc nulls last, created_at desc")).mappings().all()
        receipts = conn.execute(text(
            "select * from records.payment_reconciliation_exception where active "
            "order by last_seen_at desc, exception_key")).mappings().all()
    finally:
        conn.close()
    out = []
    for row in receipts:
        item = dict(row)
        for key in ("first_seen_at", "last_seen_at", "resolved_at"):
            if item.get(key) is not None:
                item[key] = item[key].isoformat()
        out.append(item)
    out.extend(dict(_serialise(dict(row)), kind="CLAIM",
                    reason=row.get("resolution_note") or "RECEIPT_NOT_FOUND")
               for row in claims)
    return out


def _month(value=None):
    value = str(value or clock.business_now().strftime("%Y-%m"))
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise errors.Problem(code="reminder_month_invalid", status=422,
                             title="Invalid reminder month", detail="month must be YYYY-MM",
                             message_th="เดือนแจ้งเตือนไม่ถูกต้อง", error_id="DEBT-PAY-0425")
    return value


def _existing_reminder(customer_uid, month):
    if not db.configured():
        with _LOCK:
            row = _REMINDERS.get((customer_uid, month))
            return dict(row) if row else None
    from sqlalchemy import text
    conn = db.connect()
    try:
        row = conn.execute(text(
            "select * from records.payment_reminder where customer_uid=:uid and month=:month"),
            {"uid": customer_uid, "month": month}).mappings().first()
    finally:
        conn.close()
    if not row:
        return None
    out = dict(row)
    if out.get("sent_at") is not None:
        out["sent_at"] = out["sent_at"].isoformat()
    return out


def reminder_preview(customer_uid, month=None):
    from .config import settings
    month = _month(month)
    _case(customer_uid)  # validates the customer/case exists
    invoices = []
    total = ZERO
    for inv in _customer_invoices(customer_uid):
        if inv.get("service_deferral") and inv.get("collection_due_date", "") >= str(settings.business_date):
            continue
        outstanding = _outstanding(inv)
        if outstanding <= ZERO:
            continue
        total += outstanding
        invoices.append({
            "invoice_uid": inv.get("uid"), "invoice_ref": _doc_no(inv),
            "cycle": inv.get("month_index") or inv.get("cycle") or inv.get("cycle_n"),
            "due_on": inv.get("collection_due_date") or inv.get("due_date") or inv.get("due_on"),
            "outstanding": _fmt(outstanding),
        })
    active = active_for_customer(customer_uid)
    sent = _existing_reminder(customer_uid, month)
    blocked_reason = "PAYMENT_PENDING" if active else ("ALREADY_SENT" if sent else None)
    from . import service_deferrals
    if not invoices and service_deferrals.customer_has_history(customer_uid):
        blocked_reason = blocked_reason or "SERVICE_DEFERRED"
    refs = ", ".join(row["invoice_ref"] for row in invoices if row["invoice_ref"])
    return {
        "customer_uid": customer_uid, "month": month, "eligible": blocked_reason is None,
        "blocked_reason": blocked_reason, "invoice_count": len(invoices), "invoices": invoices,
        "total_outstanding": _fmt(total), "already_sent": sent,
        "message_th": ("แจ้งยอดค้าง %d งวด รวม %s บาท%s" %
                       (len(invoices), _fmt(total), (" · %s" % refs) if refs else "")),
    }


def send_reminder(customer_uid, month, by, channel=None):
    global _VERSION
    month = _month(month)
    existing = _existing_reminder(customer_uid, month)
    if existing:
        return existing, False
    preview_row = reminder_preview(customer_uid, month)
    if preview_row["blocked_reason"] == "SERVICE_DEFERRED":
        from . import service_deferrals
        raise service_deferrals.problem("reminder_closed", "ไม่มีงวดที่ต้องแจ้งเตือน งวดปัญหาบริการเลื่อนไปแล้ว", 409)
    if preview_row["blocked_reason"] == "PAYMENT_PENDING":
        raise errors.Problem(code="payment_reminder_pending", status=409,
                             title="Payment confirmation is pending",
                             detail="reminders are paused for the whole customer while a payment claim is pending",
                             message_th="พักการแจ้งเตือนทั้งลูกค้าระหว่างรอยืนยันยอดชำระ",
                             error_id="DEBT-PAY-0412")
    now = clock.business_now().replace(tzinfo=clock.BANGKOK)
    row = {"customer_uid": customer_uid, "month": month, "payload": preview_row,
           "sent_by": by, "sent_at": now.isoformat(), "channel": channel}
    if not db.configured():
        with _LOCK:
            existing = _REMINDERS.get((customer_uid, month))
            if existing:
                return dict(existing), False
            _REMINDERS[(customer_uid, month)] = row
            _VERSION += 1
        return dict(row), True
    from sqlalchemy import text
    conn = db.connect()
    try:
        with conn.begin():
            inserted = conn.execute(text(
                "insert into records.payment_reminder (customer_uid,month,payload,sent_by,channel) "
                "values (:uid,:month,cast(:payload as jsonb),:by,:channel) "
                "on conflict (customer_uid,month) do nothing returning *"),
                {"uid": customer_uid, "month": month,
                 "payload": json.dumps(preview_row, ensure_ascii=False), "by": by,
                 "channel": channel}).mappings().first()
    finally:
        conn.close()
    if inserted:
        _VERSION += 1
        out = dict(inserted)
        out["sent_at"] = out["sent_at"].isoformat()
        return out, True
    return _existing_reminder(customer_uid, month), False


def reconcile_applied(conn, run_id):
    """Rebuild confirmed allocation truth from all applied receipt observations.

    It runs inside the receipt-apply transaction. Rebuilding (instead of adding a
    delta) is what makes re-uploads idempotent and a later CANCELLED observation a
    reversible event.
    """
    global _VERSION
    from sqlalchemy import text
    from . import journey, service_deferrals

    invoice_run = conn.execute(text(
        "select id from landing.import_run where source_system='PEAK' and status='OK' "
        "and meta ? 'applied' order by cast(meta->'applied'->>'at' as timestamptz) desc nulls last, id desc limit 1"
    )).scalar()
    invoice_rows = []
    if invoice_run:
        invoice_rows = conn.execute(text(
            "select doc_no, issued_on, due_on, amount_due, amount_awaiting, "
            "coalesce(customer_no, ladder_customer_no) as customer_no "
            "from landing.peak_invoice where import_run_id=:r and "
            "coalesce(customer_no, ladder_customer_no) is not null"), {"r": invoice_run}).mappings().all()

    receipt_rows = conn.execute(text(
        "select distinct on (p.doc_no) p.doc_no, p.invoice_ref, p.status, p.paid_on, p.paid_amount, "
        "p.customer_no, p.invoice_doc_no, p.verdict, r.id as run_id, r.meta->>'exported_at' as exported_at "
        "from landing.peak_receipt p join landing.import_run r on r.id=p.import_run_id "
        "where r.source_system='PEAK_RECEIPT' and r.status='OK' and r.meta ? 'applied' "
        "order by p.doc_no, cast(r.meta->'applied'->>'at' as timestamptz) desc nulls last, r.id desc"
    )).mappings().all()

    uid_by_no = {str(customer.customer_no): customer.uid for customer in journey.book_customers()
                 if getattr(customer, "customer_no", None)}
    invoices = []
    adjusted = {r["customer_uid"] for r in service_deferrals.records()}
    collection_dates = {m["invoice_doc_no"]: m["new_due_date"] for r in service_deferrals.records()
                        if r["status"] == "ACTIVE" for m in r["moves"] if m.get("invoice_doc_no")}
    invoice_as_of = conn.execute(text("select meta->>'report_as_of' from landing.import_run where id=:r"),
                                 {"r": invoice_run}).scalar() if invoice_run else None
    for row in invoice_rows:
        no = str(row["customer_no"])
        invoices.append({
            "uid": "inv-pk-" + row["doc_no"], "doc_no": row["doc_no"],
            "customer_no": no, "customer_uid": uid_by_no.get(no),
            "issued_on": _iso_date(row["issued_on"]) if row["issued_on"] else None,
            "due_on": _iso_date(row["due_on"]) if row["due_on"] else None,
            "amount": _fmt(row["amount_due"] or ZERO),
            "outstanding": _fmt(row["amount_awaiting"] if row["amount_awaiting"] is not None
                                 else row["amount_due"] or ZERO),
            "service_adjusted": uid_by_no.get(no) in adjusted,
            "collection_due_date": collection_dates.get(row["doc_no"]),
            "snapshot_as_of": invoice_as_of,
        })
    receipts = []
    for row in receipt_rows:
        no = str(row["customer_no"]) if row["customer_no"] is not None else None
        receipts.append({
            "doc_no": row["doc_no"], "invoice_ref": row["invoice_doc_no"] or row["invoice_ref"],
            # Financial status only gates Draft/Cancelled/unknown. Strict matching
            # below independently checks both invoice reference and customer.
            "status": row["status"],
            "paid_on": str(row["paid_on"]) if row["paid_on"] else None,
            "paid_amount": row["paid_amount"], "customer_no": no,
            "customer_uid": uid_by_no.get(no), "run_id": row["run_id"],
            "exported_at": row["exported_at"],
        })
    result = reconcile_receipts(invoices, receipts)

    # Keep the strict-match exception queue durable. Repeated applies reactivate
    # the same stable row; exceptions that disappear remain as resolved audit.
    conn.execute(text(
        "update records.payment_reconciliation_exception "
        "set active=false, resolved_at=now() where active"))
    receipt_by_doc = {row["doc_no"]: row for row in receipts}
    for exception in result["exceptions"]:
        receipt_doc = str(exception.get("receipt_doc_no") or "")
        observed = receipt_by_doc.get(receipt_doc, {})
        reason = exception["reason"]
        exception_key = hashlib.sha256(
            ("receipt\0%s\0%s" % (receipt_doc, reason)).encode()).hexdigest()
        conn.execute(text(
            "insert into records.payment_reconciliation_exception "
            "(exception_key,kind,receipt_doc_no,customer_uid,invoice_doc_no,reason,source_run_id,detail) "
            "values (:key,'RECEIPT',:receipt,:customer,:invoice,:reason,:run,cast(:detail as jsonb)) "
            "on conflict (exception_key) do update set "
            "customer_uid=excluded.customer_uid, invoice_doc_no=excluded.invoice_doc_no, "
            "reason=excluded.reason, source_run_id=excluded.source_run_id, detail=excluded.detail, "
            "active=true, last_seen_at=now(), resolved_at=null"), {
                "key": exception_key, "receipt": receipt_doc or None,
                "customer": observed.get("customer_uid"),
                "invoice": observed.get("invoice_ref"), "reason": reason,
                "run": observed.get("run_id") or run_id,
                "detail": json.dumps(exception, ensure_ascii=False, default=str),
            })

    # Keep prior allocation rows as reversal evidence; only the current rebuild is active.
    conn.execute(text("update records.payment_allocation set active=false where active"))
    for allocation in result["allocations"]:
        key = allocation["invoice_doc_no"] or "CREDIT"
        conn.execute(text(
            "insert into records.payment_allocation "
            "(receipt_doc_no,allocation_key,customer_uid,customer_no,invoice_doc_no,amount,allocation_order,"
            "source_run_id,before_amount,after_amount,active,reconciled_at) "
            "values (:receipt,:key,:uid,:no,:invoice,:amount,:ord,:source,:before,:after,true,now()) "
            "on conflict (receipt_doc_no,allocation_key) do update set "
            "customer_uid=excluded.customer_uid, customer_no=excluded.customer_no, "
            "invoice_doc_no=excluded.invoice_doc_no, amount=excluded.amount, allocation_order=excluded.allocation_order, "
            "source_run_id=excluded.source_run_id, before_amount=excluded.before_amount, "
            "after_amount=excluded.after_amount, active=true, reconciled_at=now()"), {
                "receipt": allocation["receipt_doc_no"], "key": key,
                "uid": allocation.get("customer_uid") or "unknown", "no": allocation.get("customer_no"),
                "invoice": allocation["invoice_doc_no"], "amount": allocation["amount"],
                "ord": allocation["order"], "source": allocation.get("source_run_id") or run_id,
                "before": allocation["before"], "after": allocation["after"],
            })

    # Re-resolve claims from current receipt truth. This also reverses claims whose
    # receipt was later cancelled without deleting the historical allocation row.
    conn.execute(text("delete from records.payment_claim_receipt"))
    conn.execute(text(
        "update records.payment_claim set state='PENDING', confirmed_amount=0, resolution_run_id=null, "
        "resolved_at=null, resolution_note=null where state <> 'CANCELLED'"))
    allocation_by_receipt = {}
    for allocation in result["allocations"]:
        allocation_by_receipt.setdefault(allocation["receipt_doc_no"], []).append(allocation)
    active_receipts = {row["doc_no"]: row for row in receipts if row["status"] == "PAID"}
    for receipt_doc, allocations in allocation_by_receipt.items():
        receipt = active_receipts.get(receipt_doc)
        if not receipt:
            continue
        customer_uid = next((a.get("customer_uid") for a in allocations if a.get("customer_uid")), None)
        invoice_docs = {a["invoice_doc_no"] for a in allocations if a["invoice_doc_no"]}
        claims = conn.execute(text(
            "select distinct c.* from records.payment_claim c "
            "left join records.payment_claim_target t on t.claim_uid=c.uid "
            "where c.customer_uid=:uid and c.state in ('PENDING','PARTIALLY_CONFIRMED') "
            "and (t.invoice_doc_no = any(:docs) or c.reference = any(:docs)) "
            "order by c.created_at, c.uid"), {"uid": customer_uid, "docs": list(invoice_docs) or ["-"]}).mappings().all()
        available = sum((Decimal(a["amount"]) for a in allocations), ZERO)
        for claim in claims:
            if available <= ZERO:
                break
            claim_remaining = max(
                ZERO, Decimal(claim["amount"]) - Decimal(claim["confirmed_amount"]))
            matched = min(available, claim_remaining)
            if matched <= ZERO:
                continue
            available -= matched
            confirmed_amount = Decimal(claim["confirmed_amount"]) + matched
            state = ("CONFIRMED" if confirmed_amount >= Decimal(claim["amount"])
                     else "PARTIALLY_CONFIRMED")
            conn.execute(text(
                "update records.payment_claim set state=:state, confirmed_amount=:amount, "
                "resolution_run_id=:run, resolved_at=now(), resolution_note=:note where uid=:uid"),
                {"state": state, "amount": confirmed_amount, "run": run_id,
                 "note": "matched receipt %s" % receipt_doc, "uid": claim["uid"]})
            conn.execute(text(
                "insert into records.payment_claim_receipt (claim_uid,receipt_doc_no,amount,source_run_id) "
                "values (:claim,:receipt,:amount,:run)"),
                {"claim": claim["uid"], "receipt": receipt_doc, "amount": matched,
                 "run": receipt.get("run_id") or run_id})

    final_claim_counts = conn.execute(text(
        "select count(*) filter (where state='CONFIRMED') as confirmed, "
        "count(*) filter (where state='PARTIALLY_CONFIRMED') as partial "
        "from records.payment_claim where resolution_run_id=:run"),
        {"run": run_id}).mappings().one()
    confirmed = int(final_claim_counts["confirmed"] or 0)
    partially = int(final_claim_counts["partial"] or 0)

    applied = conn.execute(text("select meta from landing.import_run where id=:r"), {"r": run_id}).scalar() or {}
    covers_from, covers_to = applied.get("covers_from"), applied.get("covers_to")
    needs_review = 0
    if covers_from and covers_to:
        changed = conn.execute(text(
            "update records.payment_claim set state='NEEDS_REVIEW', resolved_at=now(), "
            "resolution_run_id=:run, resolution_note='receipt coverage passed without a strict match' "
            "where state='PENDING' and paid_on between cast(:start as date) and cast(:finish as date)"),
            {"run": run_id, "start": covers_from, "finish": covers_to})
        needs_review = changed.rowcount or 0
    allocated = sum((Decimal(a["amount"]) for a in result["allocations"] if a["invoice_doc_no"]), ZERO)
    credit = sum((Decimal(value) for value in result["credit_by_customer"].values()), ZERO)
    _VERSION += 1
    return {
        "claims_confirmed": confirmed, "claims_partially_confirmed": partially,
        "claims_needs_review": needs_review, "allocated_to_invoices": _fmt(allocated),
        "customer_credit": _fmt(credit), "exceptions": len(result["exceptions"]),
        "receipts_active": result["active_receipts"],
    }


def version():
    if not db.configured():
        return _VERSION
    from sqlalchemy import text
    conn = db.connect()
    try:
        return tuple(conn.execute(text(
            "select count(*), count(*) filter (where state='PENDING') from records.payment_claim")).one())
    finally:
        conn.close()


def reset():
    global _COUNTER, _VERSION
    with _LOCK:
        _MEMORY.clear()
        _REMINDERS.clear()
        _COUNTER = 0
        _VERSION = 0
