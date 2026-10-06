"""Review changes collection eligibility; source balances and receipts stay intact."""
import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal

from . import errors, invoice_review_store as store, request_context
from .config import settings

ZERO = Decimal("0")


def problem(code, message, status=422):
    return errors.Problem("invoice_review_" + code, status, "Invoice review refused",
                          message, message, "DEBT-IVR-%04d" % status)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def identity(inv):
    fields = (inv.get("company_uid") or inv.get("company_id") or inv.get("entity"),
              inv.get("peak_number") or inv.get("peak_ref") or inv["uid"])
    cache = request_context.reads()
    key = ("invoice_reviews.identity", fields)
    try:
        if cache is not None and key in cache: return cache[key]
        value = digest(list(fields))
        if cache is not None: cache[key] = value
        return value
    except TypeError:
        # Malformed source fields retain the existing JSON validation behavior.
        return digest(list(fields))


def source_version(inv):
    return digest({k: inv.get(k) for k in ("customer_uid", "contract_uid", "amount", "due_date",
                                          "service_month", "service_month_conflict", "contract_resolved", "kind", "lines")})


def decisions(rows=None):
    cache = request_context.reads() if rows is None else None
    if cache is not None and "invoice_reviews.decisions" in cache:
        return cache["invoice_reviews.decisions"]
    result = {}
    for event in store.read() if rows is None else rows:
        for item in event["decisions"]:
            result[item["identity"]] = dict(item, actor=event["actor"], role=event["role"],
                                           reason=event["reason"], reviewed_at=event["created_at"])
    if cache is not None:
        cache["invoice_reviews.decisions"] = result
    return result


def decorate(inv, reviewed=None):
    reviewed = decisions() if reviewed is None else reviewed
    decision = reviewed.get(identity(inv)) if reviewed else None
    status = "AUTO_MATCHED" if inv.get("contract_cycle") else "UNMATCHED"
    changed = bool(decision and decision["source_version"] != source_version(inv))
    if decision:
        status = "REJECTED" if decision["action"] == "REJECT" else "PENDING_REVIEW" if changed else "ACCEPTED"
    return dict(inv, review_status=status, review=decision, review_source_changed=changed)


def project(customer, state, invoices=None, reviewed=None, business_date=None):
    """The common due projection used by cases, counts, previews and review impact."""
    from . import instalment_evidence, service_deferrals
    own = invoices if invoices is not None else [i for i in state.invoices.values()
        if i.get("contract_uid") in {k.uid for k in customer.contracts}]
    matched = instalment_evidence.annotate_invoices(customer, state, own)
    business_date = business_date or settings.business_date
    reviewed = decisions() if reviewed is None else reviewed
    result, seen = [], set()
    for inv in matched:
        row = decorate(service_deferrals.decorate_invoice(inv), reviewed)
        due = row.get("collection_due_date") or row.get("amended_due_date") or row.get("due_date")
        try:
            due_day = date.fromisoformat(str(due)[:10])
        except ValueError:
            due_day = None
        valid = row.get("state") not in ("DRAFT", "VOID", "CANCELLED", "AR_REVIEW")
        duplicate = identity(row) in seen
        if valid:
            seen.add(identity(row))
        liability = row.get("liability_verified") is not False and row.get("payment_evidence") != "UNCONFIRMED"
        matched_ok = bool(row.get("contract_cycle")) or row.get("kind") != "INSTALMENT"
        included = valid and not duplicate and liability and matched_ok and row["review_status"] != "REJECTED"
        original_due = row.get("amended_due_date") or row.get("due_date")
        try:
            visible = date.fromisoformat(str(original_due)[:10]) <= business_date
        except ValueError:
            visible = False
        result.append(dict(row, collection_due_date=str(due_day) if due_day else None,
                           invoice_visible=visible or bool(due_day and due_day <= business_date),
                           is_due=bool(due_day and due_day <= business_date),
                           is_overdue=bool(due_day and due_day < business_date),
                           collection_included=included,
                           collection_state="PAID" if Decimal(row.get("outstanding") or "0") <= ZERO else
                           "OVERDUE" if due_day and due_day < business_date else "ISSUED",
                           collection_exclusion_reason="DUPLICATE_DOCUMENT" if duplicate else
                           "REJECTED" if row["review_status"] == "REJECTED" else
                           row.get("unmatched_reason") if not matched_ok else None))
    return result


def totals(rows):
    from .instalment_evidence import invoice_outstanding as balance
    due = [i for i in rows if i["is_due"] and i["collection_included"]]
    future = [i for i in rows if not i["is_due"] and i["collection_included"]]
    money = lambda values: str(sum(values, ZERO).quantize(Decimal(".01")))
    return {"due_outstanding_amount": money(balance(i) for i in due),
            "source_outstanding_amount": money(balance(i) for i in rows
                if i.get("state") not in ("DRAFT", "CANCELLED", "VOID", "AR_REVIEW")
                and i.get("collection_exclusion_reason") != "DUPLICATE_DOCUMENT"
                and i.get("liability_verified") is not False and i.get("payment_evidence") != "UNCONFIRMED"),
            "future_outstanding_amount": money(balance(i) for i in future),
            "due_paid_amount": money(max(ZERO, Decimal(i["amount"]) - balance(i)) for i in due),
            "due_invoice_count": len(due),
            "due_cycle_count": len({(i["contract_uid"], i.get("contract_cycle")) for i in due if i.get("contract_cycle")}),
            "due_open_invoice_count": sum(balance(i) > ZERO for i in due),
            "due_open_cycle_count": len({(i["contract_uid"], i.get("contract_cycle")) for i in due
                                          if i.get("contract_cycle") and balance(i) > ZERO})}


def contract_outstanding(customer, state):
    """Unreviewed whole-contract balance, kept beside the collection projection."""
    from . import instalment_evidence, main
    amount = ZERO
    for contract in customer.contracts:
        if not instalment_evidence.required(contract):
            amount += main._contract_view(contract)[3].closing_balance
            continue
        seen = set()
        for inv in instalment_evidence.evidence_invoices(contract.uid, state):
            key = identity(inv)
            if key in seen or inv.get("receipt_only") or inv.get("state") in ("DRAFT", "VOID", "CANCELLED"):
                continue
            seen.add(key)
            amount += instalment_evidence.invoice_outstanding(inv)
    return amount


def contract_arrears(customer, contract, state, business_date):
    """Imported liabilities use the same included invoices for every arrears view."""
    from . import main
    cache = request_context.reads()
    key = ("invoice_reviews.arrears", id(customer), contract.uid, business_date)
    if cache is not None and key in cache:
        return cache[key]
    own = main.rows_for(state.invoices, "contract_uid", {contract.uid})
    if not any(i.get("source") == "PEAK_REPORT" for i in own):
        if cache is not None:
            cache[key] = None
        return None
    from .instalment_evidence import invoice_outstanding
    overdue = [i for i in project(customer, state, own, business_date=business_date)
               if i["collection_included"] and i["is_overdue"] and invoice_outstanding(i) > ZERO]
    amount = sum((invoice_outstanding(i) for i in overdue), ZERO)
    dpd = max(((business_date - date.fromisoformat(i["collection_due_date"])).days for i in overdue), default=0)
    result = amount, dpd
    if cache is not None:
        cache[key] = result
    return result


def authorize(customer_uid, role, officer):
    from . import cases, journey, officers
    if role not in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER"):
        raise problem("forbidden", "เฉพาะเจ้าหน้าที่ Debt ขึ้นไปจึงรับรองใบแจ้งหนี้ได้", 403)
    if not any(r["uid"] == officer and role in r["roles"] for r in officers.registry()):
        raise problem("actor_invalid", "ไม่พบผู้ทำรายการที่มีสิทธิ์นี้", 403)
    customer = journey.customer_by_uid(customer_uid)
    if customer is None:
        raise problem("not_found", "ไม่พบลูกค้า", 404)
    case = cases.for_current().cases.get(customer_uid)
    if role == "OFFICER" and (not case or case.get("officer_uid") != officer):
        raise problem("assignment", "ทำรายการได้เฉพาะเคสที่ได้รับมอบหมาย", 403)
    return customer


def inputs(body):
    ids, action = body.get("invoice_uids"), body.get("action")
    if not isinstance(ids, list) or not ids or len(ids) > 1000 or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise problem("ids_invalid", "เลือกใบแจ้งหนี้โดยไม่ซ้ำกัน (ไม่เกิน 1,000 ใบ)")
    if action not in ("ACCEPT", "REJECT"):
        raise problem("action_invalid", "เลือกการรับรองหรือปฏิเสธใบแจ้งหนี้")
    reason = body.get("reason") or ""
    if not isinstance(reason, str) or len(reason) > 2000:
        raise problem("reason_invalid", "เหตุผลต้องเป็นข้อความไม่เกิน 2,000 ตัวอักษร")
    reason = reason.strip()
    try:
        reason.encode("utf-8")
        if "\x00" in reason:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise problem("reason_invalid", "เหตุผลมีอักขระที่บันทึกไม่ได้") from None
    if action == "REJECT" and not reason:
        raise problem("reason_required", "ต้องระบุเหตุผลที่ปฏิเสธ")
    return {"invoice_uids": sorted(ids), "action": action, "reason": reason}


def preview(customer, body, events=None):
    from . import journey
    data = inputs(body)
    state = journey.for_current()
    for uid in data["invoice_uids"]:
        inv = state.invoices.get(uid)
        if inv is None:
            raise problem("not_found", "ไม่พบใบแจ้งหนี้ที่เลือก กรุณาโหลดข้อมูลใหม่", 404)
        if inv.get("customer_uid") not in (None, customer.uid) or inv.get("contract_uid") not in {k.uid for k in customer.contracts}:
            raise problem("ownership", "ใบแจ้งหนี้ทุกใบต้องเป็นของลูกค้ารายนี้", 403)
    current = decisions(events)
    rows = project(customer, state, reviewed=current)
    selected = [r for r in rows if r["uid"] in data["invoice_uids"]]
    if len(selected) != len(data["invoice_uids"]):
        raise problem("not_found", "ไม่พบใบแจ้งหนี้", 404)
    for row in selected:
        if not row["is_due"] or row.get("state") in ("DRAFT", "VOID", "CANCELLED", "AR_REVIEW") or row.get("collection_exclusion_reason") == "DUPLICATE_DOCUMENT":
            raise problem("ineligible", "เลือกได้เฉพาะใบแจ้งหนี้ที่ถึงกำหนดและยังมีผล", 409)
        if data["action"] == "ACCEPT" and (row.get("unmatched_reason") or row.get("liability_verified") is False):
            raise problem("unmatched", "ข้อมูลกำกวม ต้องแก้สัญญาและเดือนบริการก่อนรับรอง", 409)
    projected = dict(current)
    for row in selected:
        projected[identity(row)] = {"identity": identity(row), "source_version": source_version(row), "action": data["action"]}
    after = project(customer, state, reviewed=projected)
    version = digest({"customer_uid": customer.uid, "date": str(settings.business_date), "inputs": data,
                      "invoices": rows, "contracts": [(k.uid, str(k.first_due),
                          [(str(l.due_date), str(l.total_amount)) for l in k.instalments]) for k in customer.contracts]})
    return {"version": version, "action": data["action"], "items": selected,
            "before": totals(rows), "after": totals(after), "invoice_count": len(selected),
            "amount": str(sum((Decimal(r["amount"]) for r in selected), ZERO).quantize(Decimal(".01")))}


def confirm(customer, body, actor, role):
    from . import audit, clock
    data = inputs(body)
    key = body.get("idempotency_key")
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise problem("idempotency_required", "ต้องมีรหัสรายการเพื่อป้องกันการบันทึกซ้ำ")
    fingerprint = digest({"customer_uid": customer.uid, "actor": actor, "role": role, "inputs": data,
                          "preview_version": body.get("preview_version")})
    with store.transaction() as (events, save):
        previous = next((e for e in events if e["key"] == key), None)
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise problem("idempotency_conflict", "รหัสรายการนี้ถูกใช้กับข้อมูลอื่นแล้ว", 409)
            return previous["response"]
        try:
            result = preview(customer, body, events)
        except errors.Problem as exc:
            if exc.status == 404 and body.get("preview_version"):
                raise problem("stale", "ข้อมูลเปลี่ยนแล้ว กรุณาดูผลกระทบใหม่ก่อนยืนยัน", 409) from None
            raise
        if body.get("preview_version") != result["version"]:
            raise problem("stale", "ข้อมูลเปลี่ยนแล้ว กรุณาดูผลกระทบใหม่ก่อนยืนยัน", 409)
        uid = str(uuid.uuid4())
        response = {"uid": uid, "action": data["action"], "invoice_uids": data["invoice_uids"],
                    "before": result["before"], "after": result["after"]}
        event = {"uid": uid, "customer_uid": customer.uid, "actor": actor, "role": role,
                 "reason": data["reason"], "created_at": clock.stamp(), "key": key,
                 "fingerprint": fingerprint, "response": response, "decisions": [
                     {"identity": identity(r), "source_version": source_version(r), "invoice_uid": r["uid"],
                      "source_document": r.get("peak_number") or r["uid"], "action": data["action"],
                      "before_status": r["review_status"], "before": {k: r.get(k) for k in
                          ("contract_uid", "amount", "outstanding", "due_date", "collection_due_date",
                           "contract_cycle", "matching_method", "review_status", "collection_included")}}
                     for r in result["items"]]}
        save(event)
        audit.describe(act="INVOICE_REVIEW_" + data["action"], subject=("customer", customer.uid),
                       detail={"actor": actor, "reason": data["reason"], **response})
    return response
