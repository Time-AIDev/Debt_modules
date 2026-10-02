"""The invoice pipeline — API Surface v2.3 §5."""
from datetime import date

from fastapi import APIRouter, Body, Header, Query

from .. import audit
from .. import errors
from .. import invoice_pipeline as pipeline
from ..attachments import store as attachment_store
from ..invoice_pipeline import PipelineError
from ..config import settings

router = APIRouter()

PROBLEMS = {
    "gate_not_passed": (422, "DEBT-INV-0422", "A release gate is open", "ยังผ่านเงื่อนไขไม่ครบ ปล่อยใบแจ้งหนี้ไม่ได้"),
    "gate_evidence_required": (422, "DEBT-INV-0423", "The gate needs evidence", "ต้องมีหลักฐานก่อนผ่านเงื่อนไข"),
    "already_released": (409, "DEBT-INV-0409", "Already released", "ปล่อยใบแจ้งหนี้ไปแล้ว"),
    "entity_unresolved": (422, "DEBT-ENT-0422", "No company resolves", "ระบุบริษัทผู้ออกเอกสารไม่ได้ ระบบไม่สร้างเอกสาร"),
    "invoice_not_approved": (422, "DEBT-INV-0424", "Not yet approved in PEAK", "AR ยังไม่อนุมัติใน PEAK จึงยังไม่มีลิงก์"),
    "decision_unknown": (422, "DEBT-INV-0425", "Unknown decision", "ตัวเลือกไม่ถูกต้อง"),
    "reason_required": (422, "DEBT-INV-0426", "A reason is required", "ต้องระบุเหตุผล"),
    "nothing_to_reschedule": (409, "DEBT-INV-0427", "No invoice released", "ยังไม่มีใบแจ้งหนี้ให้เลื่อน"),
    "forbidden": (403, "DEBT-IAM-0403", "Not permitted for this role", "สิทธิ์ของคุณไม่พอ"),
    "amount_required": (422, "DEBT-INV-0428", "No amount to invoice", "ไม่มียอดสำหรับใบแจ้งหนี้ กรอกยอดเงินดาวน์จากสัญญาที่เงื่อนไข 1 ก่อน"),
    "feature_disabled": (422, "DEBT-CFG-0423", "Feature disabled", "ฟีเจอร์นี้ปิดอยู่"),
    "new_due_required": (422, "DEBT-INV-0429", "The new due date is required", "ต้องระบุวันครบกำหนดใหม่เมื่อเลือกเลื่อนวันครบกำหนด"),
    "reply_required": (422, "DEBT-INV-0430", "The reply is empty", "ต้องระบุข้อความตอบกลับของลูกค้า"),
    "not_delivered": (409, "DEBT-INV-0431", "Nothing was delivered yet", "ยังไม่ได้ส่งใบแจ้งหนี้ จึงยังบันทึกการตอบกลับไม่ได้"),
    "new_install_on_required": (422, "DEBT-INV-0432", "The new installation date is required", "ต้องระบุวันติดตั้งใหม่เมื่อเลื่อนการติดตั้ง"),
    # Round-3 J3-30: an invoice must not be issued already late.
    "due_date_invalid": (422, "DEBT-INV-0433", "The due date is not a valid date", "วันครบกำหนดไม่ถูกต้อง ใช้รูปแบบ ปี-เดือน-วัน"),
    "due_date_in_past": (422, "DEBT-INV-0434", "The due date is already past", "วันครบกำหนดผ่านมาแล้ว เลือกวันตั้งแต่วันทำการนี้เป็นต้นไป"),
    # Delta-100 D2h: the evidence drawer's own refusals.
    "gate_key_unknown": (422, "DEBT-INV-0435", "Unknown release condition", "ไม่รู้จักเงื่อนไขการปล่อยที่ระบุ"),
    "evidence_not_found": (404, "DEBT-INV-0436", "Evidence not found", "ไม่พบหลักฐานนี้ในเงื่อนไขที่ระบุ"),
    "attachment_unknown": (422, "DEBT-INV-0437", "Attachment not available", "ไม่พบไฟล์แนบนี้ หรือถูกลบไปแล้ว"),
    "attachment_in_use": (422, "DEBT-INV-0438", "Attachment is already attached elsewhere", "ไฟล์นี้ถูกแนบไว้กับรายการอื่นแล้ว"),
}


def problem(exc: PipelineError):
    status, error_id, title, th = PROBLEMS.get(exc.code, (422, "DEBT-INV-0499", "Refused", "ระบบปฏิเสธคำสั่ง"))
    return errors.Problem(code=exc.code, status=status, title=title, detail=exc.detail, message_th=th,
                          error_id=error_id, extensions=exc.extra)


def _item(uid):
    state = pipeline.for_current()
    item = state.items.get(uid)
    if item is None:
        raise errors.not_found("pipeline_item")
    # Every response built on the item carries the three conditions and their
    # evidence lists (Delta-100 D2h) — one annotate() call, no second shape.
    return state, pipeline.annotate(item)


def _days_since(bd, stamp):
    if not stamp:
        return None
    try:
        return max(0, (bd - date.fromisoformat(str(stamp)[:10])).days)
    except (TypeError, ValueError):
        return None


def _row_risk(customer, case, business_date):
    """Delta-100 D2a: the same score every other screen shows, from the same signals —
    the customer's worst DPD and arrears, the case's broken promises, and days since
    the last contact. A row with no customer at all serves None rather than a score
    built on nothing."""
    if customer is None:
        return None
    from .. import main as main_module
    from .. import risk
    arrears, dpd, _band, outstanding = main_module._customer_aggregate(customer)
    return risk.score(dpd=dpd, arrears=arrears, outstanding=outstanding,
                      broken_ptps=(case or {}).get("broken_ptp_count") or 0,
                      days_since_contact=_days_since(business_date, (case or {}).get("last_contact_at")))


def _waiting_days(planned_on, business_date):
    """Prototype 2038: how long this row has waited for its install — the business
    date minus the planned install date, clipped at zero so a future plan is 0, not a
    negative age. A row with no usable planned date serves None; nothing is guessed."""
    if not planned_on:
        return None
    try:
        return max(0, (business_date - date.fromisoformat(str(planned_on)[:10])).days)
    except (TypeError, ValueError):
        return None


def pipeline_payload(days=None, include_all=False):
    """Pure route payload shared by the queue and selected-row export."""
    from .. import cases as cases_domain
    from .. import journey as journey_domain
    from .. import main as main_module
    state = pipeline.for_current()
    rows = list(state.items.values()) if include_all else pipeline.lookahead(state, days=days)
    known = cases_domain.for_current().cases
    bd = str(settings.business_date)
    # One aggregate per customer per request: the loop below asked for the same
    # customer's arrears/DPD/band once per card (two cards on one contract walked the
    # contract views twice). Request-local on purpose — a cross-request cache would
    # have to be invalidated with the import epoch.
    aggregates = {}
    for i in rows:
        i["has_case"] = i["customer_uid"] in known
        # Prototype 2038: the row's own age, and the case's served DPD when this
        # customer already has a case. Both are read, never computed on the screen;
        # a row with no case keeps case_dpd None rather than a made-up figure.
        i["waiting_days"] = _waiting_days(i.get("planned_install_on"), settings.business_date)
        i["case_dpd"] = None
        customer = journey_domain.customer_by_uid(i["customer_uid"])
        if i["has_case"] and customer is not None:
            if i["customer_uid"] not in aggregates:
                aggregates[i["customer_uid"]] = main_module._customer_aggregate(customer)
            i["case_dpd"] = aggregates[i["customer_uid"]][1]
        # Delta-100 D2a / P7: the row's risk score, the same formula the record serves.
        i["risk_score"] = _row_risk(customer, known.get(i["customer_uid"]), settings.business_date)
        # Delta-100 D2h: the three conditions plus each one's evidence list.
        pipeline.annotate(i)
        i.setdefault("late_install", (i["planned_install_on"] or "") < bd and i["install_outcome"] != "INSTALLED")
        i.setdefault("moved_out_of_window", False)
        i.setdefault("moved_note_th", None)
        i.setdefault("moved_note_en", None)
        i.setdefault("installed_uninvoiced", False)   # R4-F63
        i.setdefault("installed_uninvoiced_note_th", None)
        i.setdefault("installed_uninvoiced_note_en", None)
    window = days or settings.pipeline_lookahead_days
    return {"items": rows, "meta": {"total": len(rows), "lookahead_days": window,
                                    "invoice_owner_role": settings.invoice_owner_role,
                                    "business_date": str(settings.business_date),
                                    "book_total": len(state.items),
                                    "moved_out_of_window": sum(1 for i in rows if i.get("moved_out_of_window")),
                                    # J-18, J2-26; round-3 J3-10: `beyond` over the whole book.
                                    "counts": pipeline.counts(rows, window_days=window,
                                                              book=list(state.items.values()))}}


@router.get("/v1/pipeline")
def list_pipeline(days: int = Query(default=None), all: bool = Query(default=False)):
    return pipeline_payload(days=days, include_all=all)


@router.post("/v1/pipeline/{uid}/gates/down-payment")
def gate_down_payment(uid: str, body: dict = Body(...)):
    audit.describe(act="GATE_DOWN_PAYMENT_PASSED", subject=("pipeline_item", uid))
    state, item = _item(uid)
    try:
        pipeline.pass_gate_down_payment(state, item, body.get("receipt_ref") or body.get("slip_ref"), by=body.get("by", "officer"), amount=body.get("amount"))
    except PipelineError as exc:
        raise problem(exc)
    # Annotate AFTER the write: passing the gate flips down_payment to PASSED.
    return {"item": pipeline.annotate(item)}


@router.post("/v1/pipeline/{uid}/gates/epc-confirmed")
def gate_epc(uid: str, body: dict = Body(...)):
    audit.describe(act="GATE_EPC_CONFIRMED", subject=("pipeline_item", uid))
    state, item = _item(uid)
    try:
        pipeline.pass_gate_epc(state, item, body.get("confirmed_on"), by=body.get("by", "epc"),
                               source=body.get("source", "ODOO"), reason=body.get("reason"))
    except PipelineError as exc:
        raise problem(exc)
    return {"item": pipeline.annotate(item)}


def _attachment_for_scope(file_uid, scope):
    """A stored file may back condition evidence only if it exists and is not already
    attached somewhere else — the attachments store holds one `attached_to` per file,
    and silently stealing one from a note would make two records lie."""
    found = attachment_store.get(file_uid)
    if found is None:
        raise problem(PipelineError("attachment_unknown", "No attachment %s" % file_uid))
    record = found[0]
    if record.get("attached_to") and record["attached_to"] != scope:
        raise problem(PipelineError("attachment_in_use", "Attachment %s is attached to %s"
                                    % (file_uid, record["attached_to"])))
    return attachment_store.attach(file_uid, scope)


@router.post("/v1/pipeline/{uid}/conditions/{key}/evidence", status_code=201)
def attach_condition_evidence(uid: str, key: str, body: dict = Body(default={}),
                              x_volt_officer: str = Header(default=None)):
    """Delta-100 D2h / prototype 1199-1209 (DR5): the Attach-evidence drawer. One
    record per attachment — {condition, note, file_uid, uploaded_by, uploaded_at,
    scope} — on the item; attaching flips the condition it belongs to (and for
    contract_signed, attaching is the ONLY way it can pass: no source document
    exists upstream). The optional stored file is one already uploaded through
    POST /v1/attachments; the record points at it and the scope is stamped on it."""
    audit.describe(act="CONDITION_EVIDENCE_ATTACHED", subject=("pipeline_item", uid),
                   detail={"condition": key, "file_uid": (body or {}).get("file_uid")})
    state, item = _item(uid)
    try:
        pipeline.condition_spec(key)          # an unknown key refuses before anything is written
        file_uid = (body or {}).get("file_uid")
        if file_uid:
            _attachment_for_scope(file_uid, pipeline.evidence_scope(item, key))
        evidence = pipeline.attach_evidence(
            state, item, key, (body or {}).get("note"), file_uid=file_uid,
            by=(body or {}).get("by") or (x_volt_officer or "").strip() or "officer",
            amount=(body or {}).get("amount"))
    except PipelineError as exc:
        raise problem(exc)
    # Annotate AFTER the write: `conditions` was computed before the evidence landed.
    return {"item": pipeline.annotate(item), "evidence": evidence,
            "conditions": pipeline.conditions_for(item)}


@router.post("/v1/pipeline/{uid}/conditions/{key}/evidence/{evidence_uid}:remove")
def remove_condition_evidence(uid: str, key: str, evidence_uid: str, body: dict = Body(default={}),
                              x_volt_officer: str = Header(default=None)):
    """The drawer's other half: removing the last evidence flips its condition back to
    open. The act is audited like every other write on this router."""
    audit.describe(act="CONDITION_EVIDENCE_REMOVED", subject=("pipeline_item", uid),
                   detail={"condition": key, "evidence_uid": evidence_uid})
    state, item = _item(uid)
    try:
        evidence = pipeline.remove_evidence(
            state, item, key, evidence_uid,
            by=(body or {}).get("by") or (x_volt_officer or "").strip() or "officer")
    except PipelineError as exc:
        raise problem(exc)
    # The file is released with the record it backed. Left stamped, it could never
    # back another condition (attachment_in_use) even though nothing references it.
    if evidence.get("file_uid"):
        attachment_store.attach(evidence["file_uid"], None)
    # Annotate AFTER the write: removing the last evidence reopens the condition.
    return {"item": pipeline.annotate(item), "evidence": evidence,
            "conditions": pipeline.conditions_for(item)}


@router.post("/v1/pipeline/{uid}:release", status_code=201)
def release(uid: str, body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="INVOICE_RELEASED", subject=("pipeline_item", uid))
    state, item = _item(uid)
    try:
        item, invoice, record = pipeline.release(state, item, by=body.get("by", "officer"),
                                                 role=(x_volt_role or "OFFICER").upper(),
                                                 due_date=body.get("due_date"))   # J3-30
    except PipelineError as exc:
        raise problem(exc)
    return {"item": pipeline.annotate(item), "invoice": invoice, "peak_document": record}


@router.post("/v1/pipeline/{uid}/delivery")
def deliver(uid: str, body: dict = Body(...)):
    audit.describe(act="INVOICE_DELIVERED", subject=("pipeline_item", uid))
    state, item = _item(uid)
    try:
        pipeline.deliver(state, item, body.get("channel", "LINE"), by=body.get("by", "officer"))
    except PipelineError as exc:
        raise problem(exc)
    return {"item": pipeline.annotate(item)}


@router.post("/v1/pipeline/{uid}/delivery/reply")
def delivery_reply(uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """Judge J-26: the customer's reply to the delivered link."""
    audit.describe(act="DELIVERY_REPLY_RECORDED", subject=("pipeline_item", uid))
    state, item = _item(uid)
    try:
        pipeline.record_reply(state, item, body.get("reply"), by=body.get("by") or (x_volt_officer or "").strip() or "officer")
    except PipelineError as exc:
        raise problem(exc)
    return {"item": pipeline.annotate(item)}


@router.post("/v1/pipeline/{uid}/install-outcome")
def install_outcome(uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    audit.describe(act="INSTALL_OUTCOME_SET", subject=("pipeline_item", uid), detail={"outcome": (body or {}).get("outcome")})
    state, item = _item(uid)
    try:
        pipeline.install_outcome(state, item, body.get("outcome"), on=body.get("on"),
                                 new_install_on=body.get("new_install_on"),
                                 by=body.get("by") or (x_volt_officer or "").strip() or "officer")
    except PipelineError as exc:
        raise problem(exc)
    return {"item": pipeline.annotate(item)}


@router.post("/v1/pipeline/{uid}/reschedule")
def reschedule(uid: str, body: dict = Body(...)):
    audit.describe(act="INVOICE_RESCHEDULED", subject=("pipeline_item", uid), detail={"decision": (body or {}).get("decision")})
    state, item = _item(uid)
    try:
        item, docs = pipeline.reschedule(state, item, body.get("decision"), body.get("reason"), by=body.get("by", "officer"), new_due=body.get("new_due"))
    except PipelineError as exc:
        raise problem(exc)
    return {"item": pipeline.annotate(item), "peak_documents": docs}
