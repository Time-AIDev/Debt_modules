"""RFC 9457 problem details, in the envelope §2.4 fixes.

Field rules that are load-bearing:
  code       — the ONLY field clients branch on.
  error_id   — DEBT-<MOD>-<status or serial>, for support tickets and test references.
  message_th — a Thai sentence for end users; ALWAYS present.
  retryable  — true only for 429, 503 and 409 states resolved by refetching, including
               optimistic_lock_conflict and a stale workbook cursor.
  errors     — an empty array when not applicable, NEVER absent.
  extensions — an empty object when not applicable.
  detail     — explicitly OUTSIDE the compatibility contract. Clients that parse it
               will break without notice.
"""
from fastapi.responses import JSONResponse

BASE = "https://debt.volt.co.th/errors/"


class Problem(Exception):
    def __init__(self, code, status, title, detail, message_th, error_id,
                 extensions=None, errors=None, retryable=False):
        super().__init__(detail)
        self.code = code
        self.status = status
        self.title = title
        self.detail = detail
        self.message_th = message_th
        self.error_id = error_id
        self.extensions = extensions or {}
        self.errors = errors or []
        self.retryable = retryable

    def response(self, instance="urn:request:unknown"):
        return JSONResponse(
            status_code=self.status,
            media_type="application/problem+json",
            content={
                "type": BASE + self.code,
                "title": self.title,
                "status": self.status,
                "detail": self.detail,
                "instance": instance,
                "code": self.code,
                "error_id": self.error_id,
                "message_th": self.message_th,
                "retryable": self.retryable,
                "trace_id": instance.rsplit(":", 1)[-1],
                "errors": self.errors,
                "extensions": self.extensions,
            },
        )


def population_filter_unset(config_key="kpi_default_population_filter"):
    return Problem(
        code="population_filter_unset",
        status=422,
        title="No population filter given and no default configured",
        detail=(
            "This dashboard has no population filter and no default is configured. "
            "There is no implicit whole-book default, deliberately — rendering an "
            "undefined number is worse than refusing."
        ),
        message_th="แดชบอร์ดนี้ยังไม่ได้กำหนดกลุ่มข้อมูล และระบบไม่ได้ตั้งค่าเริ่มต้นไว้ กรุณาเลือกกลุ่มข้อมูลก่อน",
        error_id="DEBT-KPI-0422",
        extensions={"config_key": config_key},
    )


def workbook_cursor_invalid(detail):
    return Problem(
        code="workbook_cursor_invalid",
        status=422,
        title="Workbook cursor is invalid",
        detail=detail,
        message_th="หน้ารายชื่อลูกค้าไม่ตรงกับตัวกรองปัจจุบัน กรุณาเริ่มโหลดจากหน้าแรก",
        error_id="DEBT-COL-0462",
    )


def workbook_cursor_stale(cursor_epoch, current_epoch):
    return Problem(
        code="workbook_cursor_stale",
        status=409,
        title="Workbook cursor is stale",
        detail="The customer book changed after this cursor was issued",
        message_th="ข้อมูลลูกค้ามีการเปลี่ยนแปลง กรุณาเริ่มโหลดจากหน้าแรก",
        error_id="DEBT-COL-0463",
        retryable=True,
        extensions={"cursor_epoch": cursor_epoch, "current_epoch": current_epoch},
    )


CONTACT_LOCKED_ALTERNATIVES = {
    "INBOUND_NOT_COUNTED": "บันทึกเป็นลูกค้าติดต่อเข้า (ไม่นับครั้ง) พร้อมกล่อง PTP",
    "RENEGOTIATE_OPEN_PTP": "ใช้ปุ่มเจรจาใหม่บน PTP ที่เปิดอยู่",
    # Round-4 J4-02: a route out that does not require writing "the customer called me"
    # about a call the officer made.
    "SECOND_CONTACT_NOT_COUNTED": "บันทึกการติดต่อครั้งที่สอง (ไม่นับ)",
}


def _business_date():
    from .config import settings
    return settings.business_date


def contact_locked(locked_by, locked_at, result, lock_id, override_allowed=False, alternatives=None):
    """Judge J-04: a refusal that names the way through. `alternatives` lists the acts
    that are still open (inbound never counts; an open PTP can be renegotiated).

    Round-3 J3-15 (regression of J2-12): the sentence quoted the server's raw UTC wall
    clock — "2026-09-02 17:42:30+00:00" — to an officer working the business day
    23/10/2026, while the same contact appeared in the history as 23/10/2026. The
    officer reads the BUSINESS day in Bangkok local time; the raw stamp stays in the
    extensions for the record."""
    from . import clock
    alternatives = alternatives if alternatives is not None else [
        {"code": "INBOUND_NOT_COUNTED", "label_th": CONTACT_LOCKED_ALTERNATIVES["INBOUND_NOT_COUNTED"]}]
    way_through = " หรือ ".join(a["label_th"] for a in alternatives)
    locked_at_local_th = clock.local_stamp_th(locked_at)
    local = clock.to_local(locked_at)
    locked_at_local = local.isoformat(timespec="seconds") if local else None
    return Problem(
        code="contact_locked",
        status=409,
        title="Customer already contacted today",
        detail=(
            "A counting contact was logged for this customer on the business day %s by %s (result %s). "
            "The Thai Debt Collection Act limit is one contact per customer per day."
            % (locked_at_local_th, locked_by, result)
        ),
        message_th=(
            "ลูกค้ารายนี้ถูกติดต่อแล้ววันนี้ %s โดย %s "
            "ตามกฎหมายติดตามทวงถามหนี้ติดต่อได้วันละ 1 ครั้ง" % (locked_at_local_th, locked_by)
            + (" ทางเลือกที่ยังทำได้: %s" % way_through if way_through else "")
        ),
        error_id="DEBT-COL-0409",
        extensions={
            "lock_level": "PERSON",
            "locked_by": locked_by,
            "locked_at": locked_at_local or locked_at,
            "locked_at_local_th": locked_at_local_th,
            "locked_at_raw": locked_at,
            "business_date": str(_business_date()),
            "result": result,
            "blocked_by_lock_id": lock_id,
            "override_allowed": override_allowed,
            "alternatives": alternatives,
        },
    )


def contact_on_hold():
    return Problem(
        code="contact_on_hold",
        status=409,
        title="Contact is on hold for this customer",
        detail=(
            "A CONTACT_HOLD is open. No lock row is created or consumed, so when the "
            "hold expires the customer's daily slot is intact and unused."
        ),
        message_th="ลูกค้ารายนี้อยู่ระหว่างระงับการติดต่อ ยังไม่ได้ใช้สิทธิ์ติดต่อประจำวัน",
        error_id="DEBT-COL-0410",
    )


def allocation_rule_pending():
    return Problem(
        code="allocation_rule_pending",
        status=422,
        title="Allocation component order is not set",
        detail=(
            "Oldest-instalment-first is settled; the component order within an "
            "instalment is not. Nothing has been written. Guessing the order would "
            "change which instalment escalates."
        ),
        message_th="ยังไม่ได้กำหนดลำดับการตัดชำระภายในงวด ระบบจึงไม่บันทึกรายการนี้",
        error_id="DEBT-MNY-0423",
        extensions={
            "pending_decision": "OD-02",
            "owner": "Accounting with Legal",
            "source": "agreement VL0010399 §6.6",
            "config_key": "allocation_component_order",
        },
    )


def feature_disabled(feature, reason, pending_decision=None, owner=None):
    return Problem(
        code="feature_disabled",
        status=422,
        title="Feature flag off",
        detail=reason,
        message_th="ฟังก์ชันนี้ยังไม่เปิดใช้งาน",
        error_id="DEBT-CFG-0423",
        extensions={
            "feature": feature,
            "pending_decision": pending_decision,
            "owner": owner,
        },
    )


def retraction_window_closed(reason):
    return Problem(
        code="retraction_window_closed",
        status=422,
        title="The daily slot can no longer be retracted",
        detail=reason,
        message_th="ไม่สามารถยกเลิกการใช้สิทธิ์ติดต่อประจำวันได้แล้ว",
        # DEBT-COL-0423 is assigned to override_reason_required; two conditions behind
        # one error_id sends two different investigations to the same place.
        error_id="DEBT-COL-0429",
    )


def destination_column_required(column_id, affected):
    return Problem(
        code="destination_column_required",
        status=422,
        title="Deleting a column needs a destination for the customers on it",
        detail=(
            "%d customer(s) stand on this column. The Owner must nominate where each "
            "one goes, and the move is logged per customer." % affected
        ),
        message_th="มีลูกค้าอยู่ในคอลัมน์นี้ กรุณาระบุคอลัมน์ปลายทางก่อนลบ",
        error_id="DEBT-COL-0427",
        extensions={"column_id": column_id, "affected_customers": affected},
    )


def authority_gap_blocks_approval(role, action):
    return Problem(
        code="authority_gap_blocks_approval",
        status=422,
        title="That approval path names a vacant role",
        detail=(
            "The role %s holds no person. An escalation to a vacant post is an "
            "escalation to nobody, silently. The Owner absorbs these routes as one "
            "time-boxed reassignment with a review date." % role
        ),
        message_th="ไม่สามารถกำหนดผู้อนุมัติเป็นตำแหน่งที่ว่างอยู่ได้",
        error_id="DEBT-IAM-0422",
        extensions={"vacant_role": role, "action": action, "absorbed_by": "OWNER"},
    )


def closure_voids_pending(lines_pending, amount_pending):
    """409 DEBT-MOD-0438. A closing transition while mirrored invoices are undecided."""
    return Problem(
        code="closure_voids_pending",
        status=409,
        title="Closing this contract would leave undecided invoice lines",
        detail=(
            "%d line(s) carrying %s are still undecided. Every leftover invoice must be "
            "decided before a closing transition." % (lines_pending, amount_pending)
        ),
        message_th="ยังมีรายการใบแจ้งหนี้ค้างตัดสินใจ ไม่สามารถปิดสัญญาได้",
        error_id="DEBT-MOD-0438",
        extensions={"lines_pending": lines_pending, "amount_pending": str(amount_pending)},
    )


def validation_failed(errors):
    return Problem(
        code="validation_failed",
        status=422,
        title="Validation failed",
        detail="One or more fields are invalid.",
        message_th="ข้อมูลไม่ถูกต้อง",
        error_id="DEBT-PLT-0422",
        errors=errors,
    )


def not_found(what="record"):
    return Problem(
        code="not_found",
        status=404,
        title="Not found",
        # 404 is used instead of 403 for documents, customers and contracts so
        # existence is never leaked (Spec §21.2).
        detail="No such %s within scope." % what,
        message_th="ไม่พบข้อมูลที่ร้องขอ",
        error_id="DEBT-PLT-0404",
    )


def population_filter_unknown(given, known):
    return Problem(
        code="population_filter_unknown",
        status=422,
        title="Unknown population filter",
        detail=(
            "%r is not a population this system knows. It is refused rather than widened "
            "to the whole book, because a dashboard that prints a population it did not "
            "apply is worse than one that refuses." % given
        ),
        message_th="ไม่รู้จักกลุ่มข้อมูลที่ระบุ กรุณาเลือกจากรายการที่กำหนด",
        error_id="DEBT-KPI-0423",
        extensions={"given": given, "known_filters": list(known)},
    )


# Round 5, rulings 79/81, escalation E-2 (leg F), decided by leg C: REQ-KPI-017 says
# "neither shall be the default when a caller omits the measure" — omitting the
# measure is not invalid input, it is a deliberate refusal to pick, the same shape
# population_filter_unset already carries for the same reason. Ruling 51 permits a
# *declared* code; a leg's earlier brief forbade one outright, which was the
# over-tightening leg F flagged and this declares instead of repeating.
def collection_measure_unset():
    return Problem(
        code="collection_measure_unset",
        status=422,
        title="No collected-amount measure given",
        detail=(
            "A collected-amount figure has no default measure. Name cash_received or "
            "due_month; rendering an unnamed figure is worse than refusing."
        ),
        message_th="ต้องเลือกวิธีนับก่อน — เงินสดรับตามเดือนที่เงินเข้า หรือ ยอดชำระตามเดือนที่ครบกำหนด (ไม่มีค่าเริ่มต้น)",
        error_id="DEBT-KPI-0425",
        errors=[{
            "pointer": "/measure",
            "code": "required",
            "message": "A collected-amount figure has no default measure. Name cash_received "
                       "or due_month; rendering an unnamed figure is worse than refusing.",
            "message_th": "ต้องเลือกวิธีนับก่อน — เงินสดรับตามเดือนที่เงินเข้า หรือ ยอดชำระตามเดือนที่ครบกำหนด (ไม่มีค่าเริ่มต้น)",
        }],
    )


def destination_column_unknown(destination):
    return Problem(
        code="destination_column_unknown",
        status=422,
        title="The nominated destination column does not exist",
        detail="Moving customers to %r would strand them." % destination,
        message_th="ไม่พบคอลัมน์ปลายทางที่ระบุ",
        error_id="DEBT-COL-0428",
        extensions={"destination_column_id": destination},
    )


def business_date_unavailable(given, available):
    return Problem(
        code="business_date_unavailable",
        status=422,
        title="No run exists for that business date",
        detail=(
            "This prototype holds one run, for %s. Accepting %r and answering with a "
            "different date would let a caller believe a question was answered that "
            "never was." % (available, given)
        ),
        message_th="ไม่มีข้อมูลรอบการทำงานของวันที่ระบุ",
        error_id="DEBT-COL-0426",
        extensions={"requested": given, "available": [str(available)]},
    )


def malformed_request(detail="Body is not valid JSON or violates the schema."):
    return Problem(
        code="malformed_request",
        status=400,
        title="Malformed request",
        detail=detail,
        message_th="รูปแบบคำขอไม่ถูกต้อง",
        error_id="DEBT-PLT-0400",
    )


def method_not_allowed(method, path):
    return Problem(
        code="method_not_allowed",
        status=405,
        title="Method not allowed",
        detail="%s is not allowed on %s." % (method, path),
        message_th="ไม่อนุญาตให้ใช้วิธีการนี้กับปลายทางนี้",
        error_id="DEBT-PLT-0405",
    )


def internal_error():
    # Never with detail — an unexpected error is reported to Error Reporting, and a
    # stack trace on the wire is a disclosure, not a diagnostic.
    return Problem(
        code="internal_error",
        status=500,
        title="Unexpected error",
        detail="The request could not be completed.",
        message_th="เกิดข้อผิดพลาดภายในระบบ",
        error_id="DEBT-PLT-0500",
    )


def idempotency_key_reused(key):
    """PEAK counts every POST create as billable, so a replay must never become a second
    create. The key is stored BEFORE the call, never after — a key written afterwards
    protects nothing if the call succeeds and the write does not."""
    return Problem(
        code="idempotency_key_reused",
        status=409,
        title="Idempotency key reused with a different body",
        detail="Key %r was already used for a different request within the retention window." % key,
        message_th="คีย์ป้องกันการทำซ้ำนี้ถูกใช้กับคำขออื่นแล้ว",
        error_id="DEBT-PLT-0409",
        extensions={"idempotency_key": key},
    )


# --- origination: orders and the loan book --------------------------------------

def order_status_unknown(given, known):
    return Problem(
        code="order_status_unknown",
        status=422,
        title="Unknown order status",
        detail=(
            "%r is not a status this system knows. It is refused rather than widened "
            "to every order, because a queue that silently shows more than was asked "
            "for is a queue nobody can work from." % given
        ),
        message_th="ไม่รู้จักสถานะคำสั่งซื้อที่ระบุ กรุณาเลือกจากรายการที่กำหนด",
        error_id="DEBT-ORD-0423",
        extensions={"given": given, "known_statuses": list(known)},
    )


def order_already_approved(no, status):
    """409, not 422: the request was well formed, the order has simply moved on."""
    return Problem(
        code="order_already_approved",
        status=409,
        title="That order is already approved",
        detail=(
            "Order %d has already moved to %s. Approving it twice would write a second "
            "lease into the book for one installation." % (no, status)
        ),
        message_th="คำสั่งซื้อนี้ได้รับการอนุมัติแล้ว",
        error_id="DEBT-ORD-0409",
        extensions={"order_no": no},
    )


def loan_not_approved(no, loan_status):
    return Problem(
        code="loan_not_approved",
        status=422,
        title="The loan on this order is not approved",
        detail=(
            "Order %d carries loan status %r. An order whose loan is not approved "
            "cannot enter the lease book, and the loan decision is not made on this "
            "screen." % (no, loan_status)
        ),
        message_th="สินเชื่อของคำสั่งซื้อนี้ยังไม่ได้รับอนุมัติ",
        error_id="DEBT-ORD-0422",
        extensions={"order_no": no, "loan_status": loan_status},
    )


def order_in_loan_book(no):
    """409. The lease exists; deleting the order under it orphans the lease."""
    return Problem(
        code="order_in_loan_book",
        status=409,
        title="That order is already in the loan book",
        detail=(
            "Order %d has been approved and a lease was written from it. Deleting the "
            "order would leave a lease in the book whose origin cannot be traced, which "
            "is worse than refusing." % no
        ),
        message_th="คำสั่งซื้อนี้ถูกอนุมัติและบันทึกเข้าทะเบียนสัญญาเช่าแล้ว ไม่สามารถลบได้",
        error_id="DEBT-ORD-0410",
        extensions={"order_no": no},
    )


def order_invalid(field_errors):
    return Problem(
        code="validation_failed",
        status=422,
        title="The order cannot be created",
        detail="One or more required fields are missing or invalid.",
        message_th="ข้อมูลคำสั่งซื้อไม่ครบถ้วนหรือไม่ถูกต้อง",
        error_id="DEBT-ORD-0424",
        errors=field_errors,
    )


def crm_id_taken(crm_id):
    return Problem(
        code="crm_id_taken",
        status=409,
        title="That CRM id is already on an order",
        detail=(
            "CRM id %r is already carried by an order in this run. Two orders sharing a "
            "CRM id would produce two leases for one customer record." % crm_id
        ),
        message_th="รหัส CRM นี้มีอยู่ในคำสั่งซื้ออื่นแล้ว",
        error_id="DEBT-ORD-0411",
        extensions={"crm_id": crm_id},
    )


def criteria_invalid(reason):
    """A target on a figure nobody controls reads as a forecast, and this screen
    does not forecast — so the refusal names the field rather than dropping it."""
    kind, _, detail = reason.partition(":")
    messages = {
        "population_unknown": "That population is not one this system knows.",
        "target_not_targetable": "%r cannot carry a target: it is a measured total, "
                                 "not something a person sets." % detail,
        "target_not_a_number": "The target for %r is not a whole number." % detail,
        "target_negative": "The target for %r is negative." % detail,
    }
    return Problem(
        code="criteria_invalid",
        status=422,
        title="Those criteria cannot be saved",
        detail=messages.get(kind, "The criteria payload is not valid."),
        message_th="ไม่สามารถบันทึกเงื่อนไขนี้ได้ กรุณาตรวจสอบข้อมูล",
        error_id="DEBT-KPI-0424",
        extensions={"reason": kind, "field": detail or None},
    )


def feedback_empty():
    return Problem(
        code="feedback_empty",
        status=422,
        title="There is nothing in that feedback",
        detail="Give it a rating, a comment, or both. An entry with neither carries "
               "no information and would dilute the round.",
        message_th="กรุณาให้คะแนนหรือเขียนความคิดเห็นอย่างน้อยหนึ่งอย่าง",
        error_id="DEBT-UAT-0422",
    )


def feedback_rating_unknown(given, known):
    return Problem(
        code="feedback_rating_unknown",
        status=422,
        title="That is not a rating this round uses",
        detail="%r is not one of the ratings. It is refused rather than stored as free "
               "text, because a rating nobody can count is not a rating." % given,
        message_th="ไม่รู้จักระดับความคิดเห็นที่ระบุ",
        error_id="DEBT-UAT-0423",
        extensions={"given": given, "known_ratings": list(known)},
    )


def feedback_too_long(limit):
    return Problem(
        code="feedback_too_long",
        status=422,
        title="That comment is too long to store",
        detail="Comments are capped at %d characters." % limit,
        message_th="ความคิดเห็นยาวเกินกำหนด",
        error_id="DEBT-UAT-0424",
        extensions={"max_characters": limit},
    )


# --- the 2026-08-30 rebuild: journey, ladders, integrations ----------------------
# Same envelope, same discipline: every refusal names what was refused and why the
# alternative (guessing, widening, silently deciding) is worse.

def working_list_bucket_unknown(given, known):
    return Problem(
        code="working_list_bucket_unknown", status=422,
        title="Unknown working-list bucket",
        detail="%r is not a bucket this system knows. Refused rather than widened to "
               "the whole book." % given,
        message_th="ไม่รู้จักกลุ่มงานที่ระบุ กรุณาเลือกจากรายการที่กำหนด",
        error_id="DEBT-COL-0430",
        extensions={"given": given, "known_buckets": list(known)},
    )


# --- feedback round 2: the assignment routes (TASK-107, TASK-116, TASK-117) --------

def customer_unknown(uids):
    """One uid or a list — the misses are named so the upload's row list is exact."""
    if isinstance(uids, str):
        uids = [uids]
    uids = [str(u) for u in uids]
    return Problem(
        code="customer_unknown", status=422,
        title="Unknown customer",
        detail="%s is not a customer this system serves." % ", ".join(uids),
        message_th="ไม่พบลูกค้ารายนี้ในระบบ",
        error_id="DEBT-COL-0477",
        extensions={"customer_uids": uids},
    )


def officer_unknown(uids):
    """One uid or a list — an assignment to a name no desk has is refused by name."""
    if isinstance(uids, str):
        uids = [uids]
    uids = [str(u) for u in uids]
    return Problem(
        code="officer_unknown", status=422,
        title="Unknown officer",
        detail="%s is not an officer the registry serves." % ", ".join(uids),
        message_th="ไม่รู้จักเจ้าหน้าที่ที่ระบุ กรุณาเลือกจากรายชื่อทีม",
        error_id="DEBT-COL-0478",
        extensions={"officer_uids": uids},
    )


def ptp_already_open(customer_uid, ptp_uid):
    return Problem(
        code="ptp_already_open", status=409,
        title="An open promise already exists for this customer",
        detail="A customer holds at most one OPEN promise. Close or cancel %s first — "
               "two live promises make 'kept' unanswerable." % ptp_uid,
        message_th="ลูกค้ารายนี้มีนัดชำระที่ยังเปิดอยู่แล้ว",
        error_id="DEBT-COL-0431",
        extensions={"customer_uid": customer_uid, "open_ptp_uid": ptp_uid},
    )


def ptp_already_closed(ptp_uid, status):
    return Problem(
        code="ptp_already_closed", status=409,
        title="That promise is already closed",
        detail="Promise %s is %s. A closed promise never reopens; a new promise is a "
               "new row." % (ptp_uid, status),
        message_th="นัดชำระนี้ถูกปิดไปแล้ว",
        error_id="DEBT-COL-0432",
        extensions={"ptp_uid": ptp_uid, "status": status},
    )


def ptp_date_in_past(given, business_date):
    return Problem(
        code="ptp_date_in_past", status=422,
        title="A promise cannot be dated before today",
        detail="%s is before the business date %s. A promise to have paid already is "
               "a payment claim, not a PTP." % (given, business_date),
        message_th="วันที่นัดชำระต้องไม่ย้อนหลัง",
        error_id="DEBT-COL-0433",
        extensions={"given": str(given), "business_date": str(business_date)},
    )


def recovery_stage_unknown(given, known):
    return Problem(
        code="recovery_stage_unknown", status=422,
        title="Unknown recovery-board stage",
        detail="%r is not a stage of the fixed ladder." % given,
        message_th="ไม่รู้จักขั้นติดตามที่ระบุ",
        error_id="DEBT-COL-0434",
        extensions={"given": given, "known_stages": list(known)},
    )


def ladder_stage_unknown(given, known):
    return Problem(
        code="ladder_stage_unknown", status=422,
        title="Unknown ladder stage",
        detail="%r is not a rung of this case's ladder (deck v20.0)." % given,
        message_th="ไม่รู้จักขั้นบันไดที่ระบุ",
        error_id="DEBT-NPL-0422",
        extensions={"given": given, "known_stages": list(known)},
    )


def ladder_stage_skip(from_stage, to_stage):
    return Problem(
        code="ladder_stage_skip", status=422,
        title="That move skips a rung of the ladder",
        detail="%s to %s skips the ladder's order. An OWNER may override with a logged "
               "reason; nobody else may." % (from_stage, to_stage),
        message_th="ไม่สามารถข้ามขั้นบันไดได้ ต้องให้ Owner อนุมัติพร้อมเหตุผล",
        error_id="DEBT-NPL-0423",
        extensions={"from_stage": from_stage, "to_stage": to_stage,
                    "override_roles": ["OWNER"]},
    )


def stage_requires_missed_count(stage, required, actual):
    return Problem(
        code="stage_requires_missed_count", status=422,
        title="The ladder rung's own wording is not met",
        detail="%s is worded on %d missed instalment(s); this contract has %d. The "
               "deck's rung is an act with a precondition, not a label." % (stage, required, actual),
        message_th="ยังไม่เข้าเงื่อนไขจำนวนงวดค้างชำระของขั้นนี้",
        error_id="DEBT-NPL-0424",
        extensions={"stage": stage, "required_missed": required, "actual_missed": actual},
    )


def assignment_before_npl(case_uid):
    return Problem(
        code="assignment_before_npl", status=422,
        title="Assignment requires a declared NPL",
        detail="The deed at 120 days executes only after NPL was declared at 90. "
               "Case %s has no declaration." % case_uid,
        message_th="ต้องประกาศ NPL ก่อนจึงจะโอนสัญญากลับ EPC ได้",
        error_id="DEBT-NPL-0425",
        extensions={"case_uid": case_uid},
    )


def assignment_already_executed(case_uid):
    return Problem(
        code="assignment_already_executed", status=409,
        title="The assignment deed was already executed",
        detail="Case %s was assigned to EPC once; a second deed would pay SPV twice." % case_uid,
        message_th="สัญญานี้ถูกโอนกลับ EPC ไปแล้ว",
        error_id="DEBT-NPL-0409",
        extensions={"case_uid": case_uid},
    )


def restructure_not_offered(case_uid, stage):
    return Problem(
        code="restructure_not_offered", status=422,
        title="A restructure has not been offered on this case",
        detail="The offer is the 60-day rung (deck S08); case %s stands at %s." % (case_uid, stage),
        message_th="เคสนี้ยังไม่ถึงขั้นเสนอปรับโครงสร้างหนี้",
        error_id="DEBT-NPL-0426",
        extensions={"case_uid": case_uid, "stage": stage},
    )


def second_restructure_forbidden(contract_uid):
    return Problem(
        code="second_restructure_forbidden", status=422,
        title="No second restructure",
        detail="Contract %s was restructured once. Two missed instalments on the new "
               "schedule declare NPL — there is no second restructure (deck S08)." % contract_uid,
        message_th="ปรับโครงสร้างหนี้ได้เพียงครั้งเดียว",
        error_id="DEBT-NPL-0427",
        extensions={"contract_uid": contract_uid},
    )


def review_already_decided(review_uid, decision):
    return Problem(
        code="review_already_decided", status=409,
        title="That review is already decided",
        detail="Review %s was decided (%s). A second decision would silently overwrite "
               "the first; open a new review instead." % (review_uid, decision),
        message_th="เคสนี้ได้รับการตัดสินใจแล้ว",
        error_id="DEBT-COL-0435",
        extensions={"review_uid": review_uid, "decision": decision},
    )


def decision_unknown(given, known):
    return Problem(
        code="decision_unknown", status=422,
        title="Unknown review decision",
        detail="%r is not one of the four Part-4 paths." % given,
        message_th="ไม่รู้จักแนวทางการตัดสินใจที่ระบุ",
        error_id="DEBT-COL-0436",
        extensions={"given": given, "known_decisions": list(known)},
    )


def recovery_strategy_unknown(given, known):
    return Problem(
        code="recovery_strategy_unknown", status=422,
        title="Unknown recovery strategy",
        detail="%r is not a strategy the flow knows." % given,
        message_th="ไม่รู้จักกลยุทธ์การเรียกคืนที่ระบุ",
        error_id="DEBT-RCV-0422",
        extensions={"given": given, "known_strategies": list(known)},
    )


def lot_state_conflict(lot_uid, expected, actual):
    return Problem(
        code="lot_state_conflict", status=409,
        title="The lot is not in the state that act requires",
        detail="Lot %s must be %s for this act; it is %s. Count before grade, grade "
               "before price, price before sale." % (lot_uid, expected, actual),
        message_th="สถานะล็อตไม่ถูกต้องสำหรับขั้นตอนนี้",
        error_id="DEBT-RCV-0409",
        extensions={"lot_uid": lot_uid, "required_status": expected, "status": actual},
    )


def grade_count_mismatch(lot_uid, graded, actual):
    return Problem(
        code="grade_count_mismatch", status=422,
        title="Grades must cover exactly the counted units",
        detail="Lot %s counted %d unit(s); the grades cover %d. A graded unit nobody "
               "counted, or a counted unit nobody graded, is how variance hides." % (lot_uid, actual, graded),
        message_th="จำนวนเกรดต้องเท่ากับจำนวนที่นับได้",
        error_id="DEBT-RCV-0423",
        extensions={"lot_uid": lot_uid, "graded_units": graded, "counted_units": actual},
    )


def resale_price_unset(lot_uid):
    return Problem(
        code="resale_price_unset", status=422,
        title="The stock is blocked until Operations prices it",
        detail="Lot %s carries no resale price. Saving a price is what unblocks the "
               "stock — this is what stops Sales quoting an unpriced system." % lot_uid,
        message_th="ยังไม่มีราคาขายต่อ สต๊อกถูกบล็อกจนกว่าทีมปฏิบัติการหรือเจ้าของจะกำหนดราคา",
        error_id="DEBT-RCV-0424",
        # Who may price, by role (Arina, 2026-09-14) — was the literal name "Dan".
        extensions={"lot_uid": lot_uid, "priced_by_roles": ["OPS", "OWNER"]},
    )


def billing_window_closed(day, window):
    return Problem(
        code="billing_window_closed", status=422,
        title="Service billing runs on the 25th to 30th only",
        detail="The business date is day %d; ALL service billing, customer and "
               "inter-company alike, is raised on days %d–%d of the month (deck S09)." % (day, window[0], window[1]),
        message_th="ออกบิลค่าบริการได้เฉพาะวันที่ 25-30 ของเดือนเท่านั้น",
        error_id="DEBT-SVC-0422",
        extensions={"business_day_of_month": day,
                    "window": {"from_day": window[0], "to_day": window[1]}},
    )


def service_before_month_37(month_index):
    return Problem(
        code="service_before_month_37", status=422,
        title="Months 1 to 36 are prepaid — nobody is invoiced",
        detail="This system is in month %d. The 36 months of O&M are priced into the "
               "sale before the quote; billing in the prepaid window would charge the "
               "customer twice (deck S09)." % month_index,
        message_th="ค่าบริการ 36 เดือนแรกรวมอยู่ในราคาขายแล้ว จะไม่มีการเรียกเก็บซ้ำ",
        error_id="DEBT-SVC-0423",
        extensions={"month_index": month_index, "prepaid_through_month": 36},
    )


def service_cancelled_by_assignment(contract_uid):
    return Problem(
        code="service_cancelled_by_assignment", status=409,
        title="The service account was cancelled with the lease",
        detail="Any month-37 service contract is cancelled when the lease is assigned "
               "back to EPC (deck S07). Contract %s was assigned." % contract_uid,
        message_th="สัญญาบริการถูกยกเลิกพร้อมการโอนสัญญาเช่ากลับ EPC แล้ว",
        error_id="DEBT-SVC-0409",
        extensions={"contract_uid": contract_uid},
    )


def invoice_state_conflict(invoice_uid, from_state, act):
    return Problem(
        code="invoice_state_conflict", status=409,
        title="That act does not apply to the invoice's state",
        detail="Invoice %s is %s; %r does not apply. The AR pipeline moves one step "
               "at a time (flow part 1)." % (invoice_uid, from_state, act),
        message_th="สถานะใบแจ้งหนี้ไม่ถูกต้องสำหรับขั้นตอนนี้",
        error_id="DEBT-AR-0409",
        extensions={"invoice_uid": invoice_uid, "state": from_state, "act": act},
    )


def manual_outside_erp(doc_type):
    return Problem(
        code="manual_outside_erp", status=422,
        title="That document is raised manually, outside the ERP",
        detail="%s is a manual document by rule (deck S10) — the THB 50,000 accounting "
               "fee and the monthly bulk service invoice are never auto-generated. "
               "Recording that it EXISTS is allowed; posting it is not." % doc_type,
        message_th="เอกสารนี้จัดทำด้วยตนเองนอกระบบ ERP เท่านั้น",
        error_id="DEBT-ICO-0422",
        extensions={"doc_type": doc_type},
    )


def cancellation_combo_invalid(phase, cause, outcome):
    return Problem(
        code="cancellation_combo_invalid", status=422,
        title="That cancellation combination does not exist in the flows",
        detail="phase=%r cause=%r outcome=%r matches none of S03/S04/S05/S06. The "
               "cause test decides who keeps the money; it cannot be skipped." % (phase, cause, outcome),
        message_th="รูปแบบการยกเลิกไม่ตรงกับขั้นตอนที่กำหนด",
        error_id="DEBT-CXL-0422",
        extensions={"phase": phase, "cause": cause, "outcome": outcome},
    )


def integration_not_configured(name, missing):
    return Problem(
        code="integration_not_configured", status=422,
        title="%s credentials are not configured" % name,
        detail="Set %s in the runtime environment for both API and worker. "
               "Credential values are never committed or returned." % ", ".join(missing),
        message_th="ยังไม่ได้ตั้งค่าการเชื่อมต่อระบบภายนอก",
        error_id="DEBT-INT-0422",
        extensions={"integration": name, "missing_env": list(missing)},
    )


def integration_unavailable(name, reason):
    return Problem(
        code="integration_unavailable", status=502,
        title="%s did not answer" % name,
        detail=reason,
        message_th="ไม่สามารถเชื่อมต่อระบบภายนอกได้ในขณะนี้",
        error_id="DEBT-INT-0502",
        retryable=True,
        extensions={"integration": name},
    )


def peak_unsent(invoice_uid, reason):
    return Problem(
        code="peak_unsent", status=502,
        title="PEAK did not accept the invoice — it stays local, marked UNSENT",
        detail="The invoice was NOT lost: it is recorded locally with peak_state "
               "UNSENT and can be re-issued. PEAK said: %s" % reason,
        message_th="ส่งใบแจ้งหนี้เข้า PEAK ไม่สำเร็จ ระบบบันทึกไว้ในสถานะ UNSENT",
        error_id="DEBT-INT-0503",
        retryable=True,
        extensions={"invoice_uid": invoice_uid, "peak_state": "UNSENT"},
    )


def override_source_unchanged(ref, value):
    return Problem(
        code="override_source_unchanged", status=422,
        title="The adjusted value equals the source value",
        detail="%s already reads %r. An override that changes nothing still leaves an "
               "audit row claiming someone changed something." % (ref, value),
        message_th="ค่าที่ปรับต้องแตกต่างจากค่าเดิม",
        error_id="DEBT-INT-0423",
        extensions={"ref": ref, "value": value},
    )


def ladder_move_not_forward(from_stage, to_stage):
    """The endpoint is named :advance. The adversarial round proved a backwards move
    could re-declare NPL and pay the buyback twice — so no non-forward move exists,
    for anyone. An unwind, if it is ever needed, is its own designed flow."""
    return Problem(
        code="ladder_move_not_forward", status=422,
        title="The ladder only advances",
        detail="%s to %s is not a forward move. Stage entry runs side effects (an NPL "
               "case, the assignment deed) that must never re-fire; there is no unwind "
               "on this endpoint, for any role." % (from_stage, to_stage),
        message_th="บันไดเดินหน้าเท่านั้น ไม่สามารถย้อนหรือทำซ้ำขั้นเดิมได้",
        error_id="DEBT-NPL-0428",
        extensions={"from_stage": from_stage, "to_stage": to_stage},
    )


def npl_already_declared(case_uid, npl_uid):
    return Problem(
        code="npl_already_declared", status=409,
        title="NPL is already declared on this case",
        detail="Case %s already carries NPL case %s. A second declaration would orphan "
               "the first — and the first may carry the executed deed." % (case_uid, npl_uid),
        message_th="เคสนี้ประกาศ NPL ไปแล้ว",
        error_id="DEBT-NPL-0429",
        extensions={"case_uid": case_uid, "npl_uid": npl_uid},
    )


# --- feedback round 2: the hand-moved stage and the strategy change (Q1/Q2) ---------

def stage_unchanged(stage):
    return Problem(
        code="stage_unchanged", status=409,
        title="The stage already reads that",
        detail="The case already stands on %s; a move to the stage it is on changes nothing." % stage,
        message_th="ขั้นนี้เป็นขั้นปัจจุบันอยู่แล้ว",
        error_id="DEBT-NPL-0430",
        extensions={"stage": stage},
    )


def strategy_unchanged(strategy):
    return Problem(
        code="strategy_unchanged", status=409,
        title="The recovery already runs that strategy",
        detail="The open recovery already carries %s; superseding it with itself would "
               "orphan a record for no change." % strategy,
        message_th="แนวทางนี้เป็นแนวทางปัจจุบันอยู่แล้ว",
        error_id="DEBT-NPL-0431",
        extensions={"strategy": strategy},
    )


def recovery_strategy_unavailable(strategy, decision=None):
    return Problem(
        code="recovery_strategy_unavailable", status=422,
        title="That recovery strategy is not available",
        detail="%s cannot be opened until the open decision is ruled on." % strategy,
        message_th="แนวทางนี้ยังใช้ไม่ได้จนกว่าจะมีคำตัดสิน",
        error_id="DEBT-NPL-0432",
        extensions={"strategy": strategy, "pending_decision": decision},
    )


def recovery_not_open(status, *, action="change_strategy"):
    detail = "A recovery in status %s cannot change strategy; open a new one instead." % status
    message_th = "การเรียกคืนนี้ไม่อยู่ในสถานะเปิดอยู่ จึงเปลี่ยนแนวทางไม่ได้"
    if action == "record_money":
        detail = "A recovery in status %s cannot accept a manual payment; payments require IN_PROGRESS." % status
        message_th = "บันทึกยอดรับคืนได้เฉพาะรายการที่อยู่ระหว่างดำเนินการ กรุณาตรวจสอบสถานะล่าสุด"
    elif action == "resolve":
        detail = "A recovery in status %s cannot be resolved again; confirmation requires IN_PROGRESS." % status
        message_th = "ยืนยันผลการเรียกคืนได้เฉพาะรายการที่อยู่ระหว่างดำเนินการ กรุณาตรวจสอบประวัติรายการนี้"
    return Problem(
        code="recovery_not_open", status=409,
        title="That recovery is no longer open",
        detail=detail,
        message_th=message_th,
        error_id="DEBT-NPL-0433",
        extensions={"status": status},
    )


# --- the 2026-09-09 spec: the board column is derived, so a move is a request -----
# The error_ids continue the one global sequence (the prefix names the domain, the
# numeral is never reused). DEBT-COL-0429..0432 were already taken — by
# retraction_window_closed, working_list_bucket_unknown, ptp_already_open and
# ptp_already_closed — and a colliding error_id sends two different investigations to
# the same support entry, so these take the next four free numbers.

def board_move_reason_required(customer_uid, to_column_id):
    return Problem(
        code="board_move_reason_required",
        status=422,
        title="A board move must say why",
        detail="The board column is computed from the case. Moving a card away from it "
               "is a claim that the data is wrong, and a claim carries a reason.",
        message_th="การย้ายคอลัมน์ต้องระบุเหตุผล",
        error_id="DEBT-COL-0453",
        extensions={"customer_uid": customer_uid, "to_column_id": to_column_id},
    )


def board_move_same_column(column_id):
    return Problem(
        code="board_move_same_column",
        status=422,
        title="The card is already in that column",
        detail="Nothing would change.",
        message_th="การ์ดอยู่ในคอลัมน์นี้อยู่แล้ว",
        error_id="DEBT-COL-0454",
        extensions={"column_id": column_id},
    )


def board_move_review_open(customer_uid, blocking_review_uid, blocking_reason):
    return Problem(
        code="board_move_review_open",
        status=409,
        title="A review is already open on this case",
        detail="One review at a time per case. Answer %s (%s) first — a board move is "
               "the least urgent of the two." % (blocking_review_uid, blocking_reason),
        message_th="เคสนี้มีคำขอตรวจที่ยังไม่ได้ตอบอยู่แล้ว — ตอบคำขอนั้นก่อน",
        error_id="DEBT-COL-0455",
        extensions={"customer_uid": customer_uid,
                    "blocking_review_uid": blocking_review_uid,
                    "blocking_reason": blocking_reason},
    )


def board_column_derived(column_id, derived):
    return Problem(
        code="board_column_derived",
        status=422,
        title="This column is computed, not arranged",
        detail="The board rule can place a card in %r, so deleting it would leave the "
               "rule naming a column that does not exist." % column_id,
        message_th="คอลัมน์นี้ระบบคำนวณเอง ลบไม่ได้",
        error_id="DEBT-COL-0456",
        extensions={"column_id": column_id, "derived_columns": list(derived)},
    )
