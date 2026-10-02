"""Payments and PEAK documents — API Surface v2.3 §6.

A confirmed slip creates a DRAFT receipt at invoice level (REQ-ACC-034); the queue
lists every document with its state; resend, refresh and fix-and-resubmit (PAY-12)
are the only acts. There is no approve route — a test asserts the router table never
gains one.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Header, Query

from .. import audit
from .. import cases as cases_domain
from .. import errors, journey
from .. import officers
from .. import peak_documents as pkd
from ..config import PENDING, settings

router = APIRouter()


def problem(exc: pkd.PeakDocumentError):
    mapping = {
        "peak_draft_only": (403, "DEBT-ACC-0403", "Debt never approves a PEAK document", "ระบบ Debt ไม่อนุมัติเอกสารใน PEAK การอนุมัติทำใน PEAK เท่านั้น"),
        "document_state_conflict": (409, "DEBT-ACC-0409", "The document state does not allow this", "สถานะเอกสารไม่ตรงกับคำสั่ง"),
        "not_found": (404, "DEBT-PLT-0404", "Not found", "ไม่พบเอกสาร"),
        "manual_outside_erp": (422, "DEBT-ICO-0422", "Manual outside the ERP", "เอกสารนี้ทำนอกระบบ"),
        "entity_unresolved": (422, "DEBT-ENT-0422", "No company resolves", "ระบุบริษัทไม่ได้ ระบบไม่สร้างเอกสาร"),
        "feature_disabled": (422, "DEBT-CFG-0423", "Feature disabled", "ฟีเจอร์นี้ปิดอยู่"),
        "intent_unknown": (422, "DEBT-ACC-0422", "Unknown intent", "ประเภทเอกสารไม่ถูกต้อง"),
        "receipt_unapplied": (422, "DEBT-ACC-0424", "Cannot be matched", "จับคู่เงินเข้ากับลูกค้าไม่ได้ อยู่ในคิวข้อยกเว้นของการเงิน"),
        # PAY-12: a resubmit that cannot reach PEAK is refused with the transport's
        # OWN reason — never a 200 claiming a draft that no PEAK ever saw.
        "resubmit_transport_unavailable": (503, "DEBT-ACC-0503", "PEAK is not configured", "ยังเชื่อมต่อ PEAK ไม่ได้ — ส่งใหม่ไม่ได้ในขณะนี้"),
        "resubmit_transport_failed": (502, "DEBT-ACC-0502", "PEAK refused the resubmission", "PEAK ปฏิเสธการส่งเอกสารใหม่ — ตรวจสอบแล้วลองอีกครั้ง"),
    }
    status, error_id, title, th = mapping.get(exc.code, (422, "DEBT-ACC-0499", "Refused", "ระบบปฏิเสธคำสั่ง"))
    return errors.Problem(code=exc.code, status=status, title=title, detail=exc.detail, message_th=th,
                          error_id=error_id, extensions=exc.extra, retryable=(status == 503))


def _waiting_days(created_at, business_date):
    """Prototype 2038: every document is stamped on the business clock, so its honest
    age is the business date minus that stamp's date, clipped at zero. A missing or
    unparseable stamp serves None rather than an invented age."""
    if not created_at:
        return None
    try:
        return max(0, (business_date - date.fromisoformat(str(created_at)[:10])).days)
    except (TypeError, ValueError):
        return None


# --- Delta-100 PAY-10/11: the allocation block -------------------------------------
#
# OD-02 (allocation_component_order) is unset, so the allocation engine REFUSES
# (money/allocation.py): a slip receipt is recorded with is_allocated false and
# pending_decision OD-02, and nothing is guessed. The one allocation record that
# exists is PEAK's own — a receipt seeded from an applied PEAK report whose payment
# names its invoice, marked is_allocated true while settings.peak_report_allocates
# holds (journey.py:_seed_peak_invoices). The three lines the prototype draws are
# served from exactly those stored records; no line is ever synthesised.
ALLOCATION_STATES = ("ALLOCATED", "NOT_ALLOCATED", "AWAITING_RULING")
ALLOCATION_LABELS = {
    "ALLOCATED": ("จัดสรรแล้ว", "Allocated"),
    "NOT_ALLOCATED": ("ยังไม่จัดสรร", "Not allocated yet"),
    "AWAITING_RULING": ("รอคำตัดสิน", "Awaiting the ruling"),
}
ALLOCATION_TONES = {"ALLOCATED": "current", "NOT_ALLOCATED": "pending", "AWAITING_RULING": "held"}


def _allocation_state(receipt):
    """Which line one stored money record stands on. ALLOCATED only where an
    allocation actually happened (is_allocated true); AWAITING_RULING where the
    engine refused on the open OD-02; NOT_ALLOCATED otherwise (nothing attempted)."""
    if receipt.get("is_allocated"):
        return "ALLOCATED"
    if receipt.get("pending_decision") == "OD-02":
        return "AWAITING_RULING"
    return "NOT_ALLOCATED"


def _money(raw):
    try:
        return Decimal(str(raw or "0"))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _allocation_meta(receipts):
    """The three lines, with counts and amounts, computed from the stored rows the
    way reports.py's OD-02 hold reads them — a record is allocated only when its own
    is_allocated flag says so."""
    lines = []
    for state in ALLOCATION_STATES:
        rows = [r for r in receipts if _allocation_state(r) == state]
        label_th, label_en = ALLOCATION_LABELS[state]
        lines.append({
            "state": state, "label_th": label_th, "label_en": label_en,
            "tone": ALLOCATION_TONES[state], "count": len(rows),
            "amount": str(sum((_money(r.get("amount")) for r in rows), Decimal("0.00"))) if rows else None,
            "pending_decision": "OD-02" if state == "AWAITING_RULING" else None,
        })
    return {
        "lines": lines,
        "total_count": len(receipts),
        "component_order_set": settings.allocation_component_order is not None,
        "pending_decision": "OD-02" if settings.allocation_component_order is None else None,
        "owner": PENDING["allocation_component_order"].owner if settings.allocation_component_order is None else None,
        # Prototype 625's own sentence, served so the block and the gate footnote
        # cannot drift apart.
        "note_th": "เงินที่ยังไม่จัดสรรไม่ลดยอดค้างบนหน้าจอ — ยังไม่ตัดสินลำดับการจัดสรร",
        "note_en": "Unallocated money does not reduce the arrears on screen — the allocation order is not decided yet",
    }


def _document_allocation(record, receipts):
    """The same classification for ONE document's own money. A document with no
    linked receipt has nothing to allocate yet, so it reads NOT_ALLOCATED with no
    amount — never an invented figure."""
    linked = [r for r in receipts if r.get("peak_document_uid") == record["uid"]]
    if not linked:
        state, amount = "NOT_ALLOCATED", None
    else:
        states = {_allocation_state(r) for r in linked}
        state = ("ALLOCATED" if states == {"ALLOCATED"}
                 else "AWAITING_RULING" if "AWAITING_RULING" in states
                 else "NOT_ALLOCATED")
        amount = str(sum((_money(r.get("amount")) for r in linked), Decimal("0.00")))
    label_th, label_en = ALLOCATION_LABELS[state]
    return {
        "state": state, "label_th": label_th, "label_en": label_en,
        "tone": ALLOCATION_TONES[state], "amount": amount,
        "receipt_uids": [r["uid"] for r in linked],
        "pending_decision": "OD-02" if state == "AWAITING_RULING" else None,
    }


def _document_customer(record):
    """The customer a document belongs to, from what its OWN record or source ref
    already names. Never guessed: anything that does not resolve serves no score."""
    uid = record.get("customer_uid")
    if uid:
        customer = journey.customer_by_uid(uid)
        if customer is not None:
            return customer
    source_ref = record.get("source_ref")
    if not source_ref:
        return None
    jstate = journey.for_current()
    receipt = jstate.receipts.get(source_ref)
    if receipt is not None:
        contract_uid = receipt["contract_uid"]
    else:
        invoice = jstate.invoices.get(source_ref)
        contract_uid = invoice["contract_uid"] if invoice is not None else None
    found = journey.contract_by_uid(contract_uid) if contract_uid else None
    return found[0] if found else None


def _document_risk(record):
    """Delta-100 PAY-15: the per-item risk edge. Null where no customer resolves —
    an unknown is never rendered as a clean zero."""
    return journey.risk_score_for_customer(_document_customer(record))


@router.get("/v1/peak-documents")
def list_documents(state: str = Query(default=None), source_ref: str = Query(default=None)):
    docs = pkd.for_current()
    rows = pkd.list_documents(docs, doc_state=state, source_ref=source_ref)
    bd = settings.business_date
    receipts = list(journey.for_current().receipts.values())
    # Round-6: the row's own age, computed here because the client has no business
    # date to compute it against — the meta carries that date too.
    for r in rows:
        r["waiting_days"] = _waiting_days(r.get("created_at"), bd)
        # PAY-10/11 and PAY-15: the document's own allocation line and risk edge.
        r["allocation"] = _document_allocation(r, receipts)
        r["risk_score"] = _document_risk(r)
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    counts = {s: sum(1 for r in docs.documents.values() if r["state"] == s) for s in pkd.STATES}
    stub = pkd.transport_for(docs) is not pkd.peak_client
    # Judge J-37: every role sees which PEAK it is talking to. Read-only — the switch
    # itself stays an Owner's act (POST /v1/peak-documents/stub).
    return {"documents": rows, "meta": {"counts": counts, "write_mode": settings.peak_write_mode,
                                        "stub": stub, "intents": list(pkd.INTENTS),
                                        "business_date": str(bd),
                                        "allocation": _allocation_meta(receipts),
                                        "transport": "STUB" if stub else "LIVE",
                                        # Round-4 J4-27: the stub approves ON READ — nothing runs on a
                                        # timer. The old sentence promised seconds, which is why one
                                        # press of อ่านสถานะกลับ looked like it approved three documents.
                                        "transport_note_th": ("จำลอง: อนุมัติเมื่อกดอ่านสถานะกลับ ไม่ใช่ PEAK จริง" if stub
                                                              else "PEAK UAT จริง: สร้างร่างเอกสารเท่านั้น การอนุมัติทำใน PEAK"),
                                        "transport_note_en": ("Simulated: a document is approved when its state is read back, not real PEAK"
                                                              if stub else "Real PEAK UAT: creates drafts only; approval happens in PEAK")}}


@router.post("/v1/peak-documents/{uid}:resend")
def resend(uid: str):
    audit.describe(act="PEAK_DOCUMENT_RESENT", subject=("peak_document", uid))
    docs = pkd.for_current()
    try:
        record = pkd.resend(docs, uid)
    except pkd.PeakDocumentError as exc:
        raise problem(exc)
    _propagate(record)      # T2-02: the invoice's peak_state mirrors the document after a resend too
    return {"document": record}


@router.post("/v1/peak-documents/{uid}:refresh")
def refresh(uid: str):
    audit.describe(act="PEAK_DOCUMENT_REFRESHED", subject=("peak_document", uid))
    docs = pkd.for_current()
    try:
        record = pkd.refresh(docs, uid)
    except pkd.PeakDocumentError as exc:
        raise problem(exc)
    _propagate(record)
    return {"document": record}


@router.post("/v1/peak-documents/{uid}/resubmit")
def resubmit(uid: str, body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER"),
             x_volt_officer: str = Header(default=None)):
    """PAY-12 / prototype 597: fix and resubmit a REFUSED document.

    Manager+ as the design shows; advances the document to DRAFT_CREATED and mirrors
    the new state onto its invoice/receipt. When the transport cannot create the
    draft the router refuses with the transport's own reason (503/502) and the record
    stays REJECTED — never a silent fix. The act is audited as PEAK_DOCUMENT_RESUBMITTED."""
    audit.describe(act="PEAK_DOCUMENT_RESUBMITTED", subject=("peak_document", uid))
    role = (x_volt_role or "OFFICER").upper()
    if role not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only",
                             detail="Fixing and resubmitting a refused PEAK document is a Manager's act",
                             message_th="เฉพาะผู้จัดการขึ้นไปแก้เอกสารที่ถูกปฏิเสธแล้วส่งใหม่ได้",
                             error_id="DEBT-IAM-0403", extensions={"allowed_roles": ["MANAGER", "OWNER"]})
    by = (body or {}).get("by") or x_volt_officer or role
    docs = pkd.for_current()
    try:
        record = pkd.resubmit(docs, uid, by=by)
    except pkd.PeakDocumentError as exc:
        raise problem(exc)
    _propagate(record)
    return {"document": record}


@router.post("/v1/peak-documents:refresh-all")
def refresh_all():
    """The 02:30 read-back, on demand."""
    audit.describe(act="PEAK_DOCUMENTS_REFRESHED")
    docs = pkd.for_current()
    touched = []
    for record in list(docs.documents.values()):
        if record["state"] == "DRAFT_CREATED" and record.get("peak_ref"):
            try:
                pkd.refresh(docs, record["uid"])
                _propagate(record)
                touched.append(record["uid"])
            except pkd.PeakDocumentError:
                continue
    return {"refreshed": touched}


def _propagate(record):
    """An approved invoice carries its QR onto the local invoice; a rejection raises
    a tier-6 item for whoever raised it (REQ-ACC-033)."""
    jstate = journey.for_current()
    for inv in jstate.invoices.values():
        if inv.get("peak_document_uid") == record["uid"]:
            inv["peak_state"] = record["state"]
            inv["peak_state_note_th"] = record.get("state_note_th")
            inv["peak_ref"] = record.get("peak_ref")
            inv["peak_number"] = record.get("peak_number")
            inv["qr_payload"] = record.get("qr_payload") if record["state"] == "APPROVED_IN_PEAK" else None
    # Round-3 J3-09: the RECEIPT reads its document back too — the queue said
    # "APPROVED_IN_PEAK IV-…" while the customer's own case still printed "ร่างใน PEAK".
    for rcp in jstate.receipts.values():
        if rcp.get("peak_document_uid") == record["uid"]:
            rcp["peak_state"] = record["state"]
            rcp["peak_state_note_th"] = record.get("state_note_th")
            rcp["peak_ref"] = record.get("peak_ref")
            rcp["peak_number"] = record.get("peak_number")
            rcp["peak_state_read_at"] = record.get("state_read_at")
    if record["state"] == "REJECTED" and record.get("customer_uid"):
        cs = cases_domain.for_current()
        case = cs.cases.get(record["customer_uid"])
        if case:
            cs.today_items.append({"uid": cs.uid("ti"), "kind": "PEAK_REJECTED", "case_uid": case["uid"],
                                   "customer_uid": case["customer_uid"], "officer_uid": case["officer_uid"],
                                   "text": record.get("rejection_reason"), "ref": record["uid"],
                                   "on": str(settings.business_date), "done": False})


@router.post("/v1/peak-documents/stub")
def set_stub(body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER")):
    """Demo and test seam: answer PEAK without a network. Off = the real client.
    OWNER only (round-1 UAT: an officer could see and change it)."""
    audit.describe(act="PEAK_STUB_SET")
    if (x_volt_role or "").upper() != "OWNER":
        raise errors.Problem(code="forbidden", status=403, title="Owner only", detail="The PEAK stub is an Owner's switch",
                             message_th="เฉพาะเจ้าของระบบเปลี่ยนโหมดจำลอง PEAK ได้", error_id="DEBT-IAM-0403")
    # Ruling 43 / R4-F05: this used to write pkd.TRANSPORT_OVERRIDE, a process-wide
    # module global — one Owner's stub toggle answered every other session's PEAK
    # calls, and a session created afterwards. pkd.transport_for() already prefers a
    # PER-SESSION state.transport over TRANSPORT_OVERRIDE (peak_documents.py:52-53) —
    # the route just never used it (ruling 39's "a second pattern for the same job").
    # TRANSPORT_OVERRIDE itself is untouched: it stays the documented process-wide
    # seam for tests and the no-credential demo (peak_documents.py:47-48), which
    # several test modules set directly and deliberately share across fixtures.
    state = pkd.for_current()
    if body.get("enabled", True):
        state.transport = pkd.StubTransport(fail_create=bool(body.get("fail_create")),
                                            approve_on_read=body.get("approve_on_read", True),
                                            reject_reason=body.get("reject_reason"),
                                            read_unknown=bool(body.get("read_unknown")))
    else:
        state.transport = None
    return {"stub": state.transport is not None}


@router.post("/v1/slips", status_code=201)
def confirm_slip(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    """A confirmed slip -> a DRAFT receipt against the invoice, at invoice level.
    Allocation to instalment components still refuses while OD-02 is open."""
    audit.describe(act="SLIP_CONFIRMED")
    by, by_role = officers.sign(body, x_volt_officer, x_volt_role)     # S2-04
    body = dict(body, by=by)
    jstate = journey.for_current()
    invoice_uid = body.get("invoice_uid")
    invoice = jstate.invoices.get(invoice_uid) if invoice_uid else None
    customer_uid = body.get("customer_uid")
    try:
        amount = Decimal(str(body.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        raise errors.validation_failed([{"pointer": "/amount", "code": "invalid", "message": "amount required", "message_th": "ระบุจำนวนเงิน"}])
    if invoice is None and not customer_uid:
        raise errors.validation_failed([{"pointer": "/invoice_uid", "code": "required", "message": "an invoice or a customer is required", "message_th": "ระบุใบแจ้งหนี้หรือลูกค้า"}])
    if invoice is None:
        # RECEIPT_UNAPPLIED — the money sits in the Finance exception queue (S07)
        docs = pkd.for_current()
        try:
            pkd.raise_document(docs, "RECEIPT_UNAPPLIED", "slip:%s" % body.get("slip_ref"), None, {"amount": str(amount)}, by=body.get("by", "officer"))
        except pkd.PeakDocumentError as exc:
            raise problem(exc)
        return {"receipt": None, "peak_document": None}
    entity = invoice.get("entity")
    intent = "RECEIPT_FULL" if amount >= Decimal(str(invoice["amount"])) else "RECEIPT_PARTIAL"
    receipt = journey.make_receipt(jstate, invoice["contract_uid"], entity, str(amount),
                                   date.fromisoformat(body.get("received_on", str(settings.business_date))),
                                   invoice_uid=invoice["uid"], matched="FULL" if intent == "RECEIPT_FULL" else "PARTIAL")
    receipt["slip_ref"] = body.get("slip_ref")
    receipt["confirmed_by"], receipt["by_role"] = by, by_role
    docs = pkd.for_current()
    found = journey.contract_by_uid(invoice["contract_uid"])
    customer = found[0] if found else None
    try:
        [record] = pkd.raise_document(docs, intent, receipt["uid"], entity, {"amount": str(amount), "invoice_uid": invoice["uid"],
                                                                             "received_on": receipt["received_on"]},
                                      by=body.get("by", "officer"), customer_name=customer.display_name if customer else None)
    except pkd.PeakDocumentError as exc:
        raise problem(exc)
    record["customer_uid"] = customer.uid if customer else None
    receipt["peak_document_uid"], receipt["peak_state"] = record["uid"], record["state"]
    if customer:
        cs = cases_domain.for_current()
        case = cs.cases.get(customer.uid)
        if case:
            cases_domain.payment_confirmed(cs, case, receipt["received_on"])
            if case["open_ptp_uid"] and intent == "RECEIPT_FULL":
                cases_domain.close_ptp(cs, case, case["open_ptp_uid"], "KEPT", receipt["received_on"], by=body.get("by", "officer"))
            elif case["open_ptp_uid"]:
                cases_domain.close_ptp(cs, case, case["open_ptp_uid"], "KEPT_PARTIAL", receipt["received_on"], by=body.get("by", "officer"))
    return {"receipt": receipt, "peak_document": record}


@router.post("/v1/credit-notes", status_code=201)
def credit_note(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    audit.describe(act="CREDIT_NOTE_RAISED")
    if (x_volt_role or "").upper() not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail="A standalone credit note is a Manager's act",
                             message_th="เฉพาะผู้จัดการออกใบลดหนี้ได้", error_id="DEBT-IAM-0403")
    by, by_role = officers.sign(body, x_volt_officer, x_volt_role, fallback="manager")     # S2-04
    body = dict(body, by=by)
    jstate = journey.for_current()
    invoice = jstate.invoices.get(body.get("invoice_uid"))
    if invoice is None:
        raise errors.not_found("invoice")
    if not body.get("reason"):
        raise errors.validation_failed([{"pointer": "/reason", "code": "required", "message": "reason required", "message_th": "ระบุเหตุผล"}])
    docs = pkd.for_current()
    try:
        [record] = pkd.raise_document(docs, "CREDIT_NOTE_STANDALONE", invoice["uid"], invoice.get("entity"),
                                      {"amount": body.get("amount", invoice["amount"]), "reason": body["reason"]}, by=body.get("by", "manager"))
    except pkd.PeakDocumentError as exc:
        raise problem(exc)
    record["by_role"] = by_role
    return {"peak_document": record}
