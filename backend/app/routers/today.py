from .. import termination_archive
"""Today, the work book and the case — API Surface v2.3 §1–§4."""
import csv
import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Body, Header, Query, Response
from fastapi.encoders import jsonable_encoder
from urllib.parse import urlsplit

from .. import audit
from .. import csv_safety
from .. import cases as cases_domain
from .. import clock
from .. import customer_contact, monthly_history
from .. import data_epoch, dictionaries, errors, journey, officers, payment_claims, payment_display, payment_position, payment_summary, sop, today as today_domain
from .. import workbook_cursor
from .. import workbook_index
from .. import perf
from ..cases import CaseError
from ..config import settings
from ..integrations import env as integration_env
from .. import ladder as ladder_mod

router = APIRouter()

# Round-3 J3-07: OPS (the O&M team) joins the roles the API accepts — the domain named
# it as the role that cuts and restores the power, but no header could ever carry it.
ROLES = ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS")


def role_of(header):
    role = (header or "OFFICER").upper()
    return role if role in ROLES else "OFFICER"


# crm.lead.id is the model's int4 primary key. A value outside it is not an Odoo id:
# the sheet's 11-digit Freshworks deal ids (28,005,118,095) passed the old digits-only
# check and produced deep links to records that never existed (found 2026-10-01).
_MAX_ODOO_ID = 2 ** 31 - 1


def _odoo_crm(record_id):
    """A safe, nullable deep link. Configuration and ids are never guessed."""
    raw_id = str(record_id or "").strip()
    if not raw_id.isdigit():
        return None
    value = int(raw_id)
    if not 0 < value <= _MAX_ODOO_ID:
        return None
    base = str(integration_env("ODOO_URL") or "").strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    # Credentials/fragments in a configured base are not propagated into a link.
    if parsed.username or parsed.password or parsed.fragment:
        return None
    clean_base = "%s://%s%s" % (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"))
    return {"model": "crm.lead", "record_id": value,
            "url": "%s/web#id=%d&model=crm.lead&view_type=form" % (clean_base, value)}


def _customer_odoo_crm(customer, fallback=None):
    """The case's Odoo crm.lead deep link, only ever from a real Odoo id.

    2026-10-01 (Jessada Nonmaha): a SHEET order's `crm_id` is the Freshworks deal id,
    not an Odoo lead id — the merge records the true one in records.identity_link
    (pipelines/odoo_links) and the book serves it as `odoo_lead_id`. Only an
    ODOO-sourced landing row may read `order.crm_id` as a crm.lead id.
    """
    sheet = (getattr(customer, "sheet", {}) or {}) if customer is not None else {}
    order = sheet.get("order") or {}
    data_source = getattr(customer, "data_source", None) or {}
    identity = data_source.get("identity") if isinstance(data_source, dict) else data_source
    if identity == "ODOO":
        crm = _odoo_crm(order.get("crm_id") or fallback)
        name = order.get("odoo_lead_name")
    else:
        crm = _odoo_crm(getattr(customer, "odoo_lead_id", None))
        name = getattr(customer, "odoo_lead_name", None)
    if crm and name:
        crm["name"] = name
    return crm


def _json(data):
    """The bytes FastAPI would send for `data`, without its pure-Python encoder pass.

    2026-09-27: /v1/today and /v1/workbook serve 7–10 MB of JSON on the real book, and
    jsonable_encoder took as long as building it (0.7–1.1 s a call on one CPU). These
    are Starlette JSONResponse's own dumps arguments; a value JSON cannot hold (a
    Decimal, a date) still goes through jsonable_encoder, and a key it cannot hold
    falls back to the old path whole.
    """
    args = dict(ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":"))
    with perf.phase("json"):
        try:
            body = json.dumps(data, default=jsonable_encoder, **args)
        except TypeError:
            body = json.dumps(jsonable_encoder(data), **args)
    return Response(body.encode("utf-8"), media_type="application/json")


def who(body, header, fallback="officer", role=None):
    """The acting person: the body's `by`, else the X-Volt-Officer header the interface
    sends from its identity switch, else a role word. Round-1: a contact was signed
    "noon" because the screen defaulted to a demo name. Round-2 settasak S2-04: pass
    `role` (X-Volt-Role) for a governed act — when the identity does not hold a
    MANAGER/OWNER role the role's default identity signs (officers.sign)."""
    if role is not None:
        by, _by_role = officers.sign(body, header, role, fallback=fallback)
        return by
    return body.get("by") or (header or "").strip() or fallback


def signer(body, header, role, fallback="officer"):
    """(by, by_role) for a governed act — see officers.sign."""
    return officers.sign(body, header, role, fallback=fallback)


def problem_from(exc: CaseError):
    mapping = {
        "next_action_required": (422, "DEBT-COL-0440", "Say what happens next before closing the contact", "กรุณาระบุงานถัดไปและวันที่ก่อนปิดการติดต่อ"),
        "next_action_date_invalid": (422, "DEBT-COL-0444", "The next-action date is not a valid date", "วันที่งานถัดไปไม่ถูกต้อง ใช้รูปแบบ วัน/เดือน/ปี ภายในสองปี"),
        "ptp_date_invalid": (422, "DEBT-COL-0445", "The promise date is not a valid date", "วันนัดชำระไม่ถูกต้อง"),
        "npl_type_required": (422, "DEBT-COL-0446", "Name the NPL type with this decision", "ต้องระบุประเภท NPL พร้อมคำตอบนี้"),
        # Round-4 J4-12: the type is gated on the customer actually being NPL.
        "npl_type_not_applicable": (409, "DEBT-COL-0452", "This customer is not NPL",
                                    "กำหนดประเภท NPL ได้เฉพาะลูกค้าที่สถานะเป็น NPL"),
        "review_pending": (409, "DEBT-COL-0441", "A review is already open on this case", "เคสนี้มีคำขอตรวจที่ยังเปิดอยู่"),
        "review_already_decided": (409, "DEBT-COL-0435", "This review was already answered", "คำขอตรวจนี้ตอบแล้ว"),
        "ptp_already_open": (409, "DEBT-COL-0431", "One open promise per customer", "ลูกค้ามีนัดชำระที่เปิดอยู่แล้ว"),
        "ptp_already_closed": (409, "DEBT-COL-0432", "This promise is already closed", "นัดชำระนี้ปิดแล้ว"),
        "power_restriction_preconditions": (422, "DEBT-MOD-0442", "Power restriction preconditions not met", "ยังไม่เข้าเงื่อนไขการตัดระบบไฟ"),
        "power_state_conflict": (409, "DEBT-MOD-0443", "Power state does not allow this act", "สถานะไฟไม่ตรงกับคำสั่งนี้"),
        # Round-3 J3-06: a cut-off request is decided, not answered.
        "power_decision_required": (422, "DEBT-MOD-0451", "A power cut-off request is decided, not answered",
                                    "คำขอตัดระบบไฟต้องอนุมัติหรือปฏิเสธเท่านั้น"),
        # 2026-09-09 spec §5: the board mirror of power_state_conflict — a board
        # decision answers a board-move request and nothing else.
        "board_decision_not_applicable": (409, "DEBT-COL-0457", "This review is not a board-move request",
                                          "คำขอตรวจนี้ไม่ใช่คำขอย้ายคอลัมน์"),
        "forbidden": (403, "DEBT-IAM-0403", "This role may not do that", "สิทธิ์ของคุณไม่พอสำหรับคำสั่งนี้"),
        "not_found": (404, "DEBT-PLT-0404", "Not found", "ไม่พบข้อมูล"),
        "decision_unknown": (422, "DEBT-COL-0436", "Unknown decision", "ตัวเลือกไม่ถูกต้อง"),
        "feature_disabled": (422, "DEBT-CFG-0423", "Feature disabled", "ฟีเจอร์นี้ปิดอยู่"),
        # Round-1 P3: J-46 (NPL type) and J-48 (power restriction) both need a reason;
        # the domain supplies the act-specific Thai sentence on the CaseError.
        "reason_required": (422, "DEBT-COL-0447", "A reason is required", "ต้องระบุเหตุผล"),
        # Arina, 2026-09-11: the follow-up status is a person's, so it carries a reason
        # and it may not be "changed" to the value it already holds — R14's rule
        # (errors.override_source_unchanged), applied to a case field rather than to
        # an Odoo one. reason_required above already covers the missing-reason half.
        "status_unchanged": (409, "DEBT-COL-0458", "The status already reads that value",
                             "สถานะเป็นค่านี้อยู่แล้ว"),
        # Arina, 2026-09-14: a person's payment status is one of the five names
        # REQ-COL-075 gives (cases.PAYMENT_STATUSES).
        "payment_status_unknown": (422, "DEBT-COL-0459", "Unknown payment status",
                                   "ไม่รู้จักสถานะการชำระนี้"),
        "resolution_note_required": (422, "DEBT-COL-0448", "A resolution note is required to close the ticket", "ต้องระบุผลการแก้ไขก่อนปิดตั๋ว"),
        "issue_already_closed": (409, "DEBT-COL-0449", "This ticket is already closed", "ตั๋วนี้ปิดแล้ว"),
        # Round-2 nantapol N2-05: a renegotiation refused while the third is under review names the rule.
        "renegotiation_awaiting_review": (409, "DEBT-COL-0450", "A third renegotiation is awaiting the Manager's answer", cases_domain.THIRD_RENEGOTIATION_TH),
        # Feedback F7/F8: several notes per contact, and a note that is not a contact,
        # each with its own evidence files (Task 23).
        "note_text_required": (422, "DEBT-COL-0460", "A note needs text", "ต้องพิมพ์ข้อความในบันทึก"),
        "too_many_attachments": (422, "DEBT-COL-0461", "Too many files on one note", "แนบไฟล์เกินจำนวนที่กำหนดต่อบันทึก"),
        "attachment_unknown": (422, "DEBT-COL-0462", "Attachment not available",
                               "ไม่พบไฟล์แนบนี้ หรือไฟล์ถูกลบหรือแนบกับบันทึกอื่นแล้ว"),
        # Feedback Round 1 / WP9 (F9 (a)): a person-entered phone number.
        "phone_invalid": (422, "DEBT-COL-0463", "Not a Thai phone number", customer_contact.INVALID_TH),
        "phone_unchanged": (409, "DEBT-COL-0464", "The number already reads that", "เบอร์ของลูกค้าเป็นแบบนี้อยู่แล้ว"),
        # Reveal (2026-09-20): the one audited read of the full number. Nothing on
        # file is a plain 404 — there is no number to open, and the screen shows the
        # masked/absent state instead.
        "phone_not_on_file": (404, "DEBT-COL-0472", "No full number is on file",
                              "ยังไม่มีเบอร์เต็มในระบบสำหรับลูกค้ารายนี้"),
        # B6 fix round 2 / R1: a NUL or a lone surrogate in phone/reason/by.
        "text_invalid": (422, "DEBT-COL-0466", "This field carries a character that cannot be stored", customer_contact.TEXT_INVALID_TH),
        # B6 fix round 3 / Critical (3): a write-side cap, independent of the reason
        # scanner in customer_contact.py.
        "reason_too_long": (422, "DEBT-COL-0468", "A reason is at most 500 characters", customer_contact.REASON_TOO_LONG_TH),
        # B6 fix round 4 / item 5: the phone route's `by` — it used to fall through to DEBT-PLT-0422.
        "phone_actor_invalid": (422, "DEBT-COL-0469", "The acting person is required", customer_contact.ACTOR_REQUIRED_TH),
        # Language pass: both used to fall through to the bare "Refused" title.
        "review_required": (422, "DEBT-COL-0470", "Send the case to the Manager for review first",
                            "ต้องส่งให้ผู้จัดการตรวจก่อน"),
        "board_decision_required": (422, "DEBT-COL-0471", "A board move is approved or rejected, not answered",
                                    "คำขอย้ายคอลัมน์ต้องอนุมัติหรือปฏิเสธเท่านั้น"),
        # 2026-09-20 (Closed/Terminated ruling): the terminate act's own refusals.
        "termination_cause_unknown": (422, "DEBT-COL-0473", "Unknown termination cause",
                                      "ไม่รู้จักสาเหตุการยุติสัญญา ต้องเป็น Default หรือ Customer request"),
        "payment_status_terminate_via_route": (422, "DEBT-COL-0475",
                                               "TERMINATED is set by the terminate act, with a cause",
                                               "สถานะยุติสัญญาตั้งได้จากคำสั่งยุติสัญญาเท่านั้น (ต้องระบุสาเหตุและเหตุผล)"),
        # feedback-r2 / R-E (F01c): a promise result needs its amount and date, server-side.
        "ptp_required_for_promise": (422, "DEBT-COL-0476", "A promise needs an amount and a date",
                                     "ผลการติดต่อเป็นนัดชำระ ต้องระบุจำนวนเงินและวันที่นัดก่อนบันทึก"),
    }
    status, error_id, title, th = mapping.get(exc.code, (422, "DEBT-PLT-0422", "Refused", "ระบบปฏิเสธคำสั่ง"))
    message_th = getattr(exc, "message_th", None) or th
    pointer = exc.extra.get("pointer") if exc.extra else None
    errs = [{"pointer": pointer, "code": exc.code, "message": exc.detail, "message_th": message_th}] if pointer else None
    return errors.Problem(code=exc.code, status=status, title=title, detail=exc.detail,
                          message_th=message_th, error_id=error_id, extensions=exc.extra, errors=errs)


def dictionary_problem(exc):
    return errors.Problem(code="dictionary_value_unknown", status=422, title="Value not in the dictionary",
                          detail="%s has no value %r" % (exc.dictionary, exc.code),
                          message_th="ค่าที่เลือกไม่อยู่ในรายการที่กำหนด", error_id="DEBT-CFG-0424",
                          extensions={"dictionary": exc.dictionary, "value": exc.code})


def _unknown_rung_error(known):
    return {
        "pointer": "/ladder_indicative", "code": "unknown_ladder_rung",
        "message": "ladder_indicative must be one of %s" % ", ".join(known),
        "message_th": "ไม่รู้จักขั้นบันไดที่ระบุ กรุณาเลือกจากรายการที่กำหนด",
        "known": known}


def _valid_rung(code):
    """Round-4 F2-CR-1. Ruling 51: no new error code — an unknown rung is a
    validation failure with the known list riding INSIDE the error item (there is no
    known=/extensions= parameter on errors.validation_failed), and the same list is
    on meta.ladder_rungs so a client never has to guess. Empty/absent means
    unfiltered, never a refusal."""
    if not code:
        return None
    known = [r["stage"] for r in ladder_mod.ladder_rungs()]
    if code not in known:
        raise errors.validation_failed([_unknown_rung_error(known)])
    return code


def _valid_position(value):
    """Feedback Round 1 / Task 14, controller ruling (a): validated first, same
    idiom as `_valid_rung` above — a filter that matched everything on a typo
    would be worse than an error. Empty/absent means unfiltered, never a refusal."""
    if not value:
        return None
    if value not in ("unpaid", "stale"):
        raise errors.validation_failed([{
            "pointer": "/position", "code": "value_unknown",
            "message": "position is 'unpaid' or 'stale'; %r is neither." % value,
            "message_th": "ตัวกรองสถานะการชำระรับเฉพาะ unpaid หรือ stale"}])
    return value


def _valid_choice(field, value, known, message_th):
    """Feedback Round 1 / B2: one refusal for every /v1/today filter — `_valid_position`'s
    idiom (pointer, code value_unknown, message_th) with `_unknown_rung_error`'s known
    list riding inside the error item, so a client never has to guess what is allowed.
    Empty/absent means unfiltered, never a refusal."""
    if not value:
        return None
    if value not in known:
        raise errors.validation_failed([{
            "pointer": "/%s" % field, "code": "value_unknown",
            "message": "%s must be one of %s; %r is not." % (field, ", ".join(known), value),
            "message_th": message_th, "known": list(known)}])
    return value


# --- Today --------------------------------------------------------------------------

@router.get("/v1/today")
def today(officer: str = Query(default=None), ladder_indicative: str = Query(default=None),
          tier: str = Query(default=None), payment_status: str = Query(default=None),
          dc_status: str = Query(default=None), product: str = Query(default=None),
          entity: str = Query(default=None),
          q: str = Query(default=None), unassigned: str = Query(default=None),
          limit: int = Query(default=None, ge=1, le=200), cursor: str = Query(default=None),
          sort: str = Query(default="priority"),
          x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    from .. import read_projection
    sort = _valid_choice("sort", sort, ("priority", "arrears"), "เลือกเรียงตามลำดับงานหรือยอดค้างชำระ")
    if read_projection.enabled():
        rung = _valid_rung(ladder_indicative)
        tier = _valid_choice("tier", tier, today_domain.TIERS, "ไม่รู้จักลำดับความสำคัญที่ระบุ")
        payment_status = _valid_choice("payment_status", payment_status, cases_domain.PAYMENT_STATUSES, "ไม่รู้จักสถานะการชำระ")
        product = _valid_choice("product", product, today_domain.PRODUCTS, "รับเฉพาะ LEASE หรือ CASH")
        entity = _valid_choice("entity", entity, ("EPC", "SPV"), "รับเฉพาะ EPC หรือ SPV")
        if unassigned and officer:
            raise errors.validation_failed([{"pointer": "/unassigned", "code": "filter_conflict",
                                             "message": "Unassigned cannot be combined with an officer",
                                             "message_th": "เลือกงานที่ยังไม่มอบหมายพร้อมเจ้าหน้าที่ไม่ได้"}])
        if cursor and limit is None:
            raise read_projection._problem("today")
        # Validate vocabularies without restoring a whole CaseState graph.
        conn = read_projection._unit()["conn"]
        pointer = read_projection.current(conn)
        from sqlalchemy import text
        known = [row[0] for row in conn.execute(text("select distinct officer from app.customer_projection "
                                                   "where generation=:g and officer is not null"), {"g": pointer["generation"]})]
        known += [row["uid"] for row in officers.registry()]
        if x_volt_officer:
            known.append(x_volt_officer)
        officer = _valid_choice("officer", officer, known, "ไม่รู้จักเจ้าหน้าที่ที่ระบุ")
        dc_status = _valid_choice("dc_status", dc_status, [row["code"] for row in dictionaries.for_current().list("DC_STATUS")],
                                  "ไม่รู้จักสถานะติดตามที่ระบุ")
        return _json(read_projection.today({"officer": officer, "ladder_indicative": rung, "tier": tier,
            "payment_status": payment_status, "dc_status": dc_status, "product": product, "entity": entity,
            "q": q, "unassigned": bool(unassigned)}, limit, cursor, sort))
    cs = cases_domain.for_current()
    # Feedback Round 1 / B2: every filter is validated BEFORE the broken-PTP sweep or any
    # row is built. A filter that matched everything — or nothing — on a typo would be
    # worse than an error (Task 14's ruling on `position`, applied to all six).
    rung = _valid_rung(ladder_indicative)
    officer = _valid_choice("officer", officer, today_domain.known_officers(cs, acting=(x_volt_officer or "").strip() or None),
                            "ไม่รู้จักเจ้าหน้าที่ที่ระบุ กรุณาเลือกจากรายชื่อทีม")
    # feedback-r2 TASK-108: the unassigned desk is its own filter and never composes
    # with an officer — "assigned to nobody, and to X" answers nothing.
    if unassigned and officer:
        raise errors.validation_failed([{
            "pointer": "/unassigned", "code": "filter_conflict",
            "message": "unassigned=1 and officer=… cannot be combined.",
            "message_th": "เลือกดูงานที่ยังไม่มอบหมายพร้อมกับกรองเจ้าหน้าที่ไม่ได้"}])
    unassigned_desk = bool(unassigned)
    tier = _valid_choice("tier", tier, today_domain.TIERS,
                         "ไม่รู้จักลำดับความสำคัญที่ระบุ กรุณาเลือกจากเจ็ดขั้นที่กำหนด")
    payment_status = _valid_choice("payment_status", payment_status, cases_domain.PAYMENT_STATUSES,
                                   "ไม่รู้จักสถานะการชำระที่ระบุ กรุณาเลือกจากห้าสถานะที่กำหนด")
    dc_status = _valid_choice("dc_status", dc_status,
                              [v["code"] for v in dictionaries.for_current().list("DC_STATUS")],
                              "ไม่รู้จักสถานะติดตามที่ระบุ กรุณาเลือกจากรายการสถานะ DC")
    product = _valid_choice("product", product, today_domain.PRODUCTS,
                            "ไม่รู้จักผลิตภัณฑ์ที่ระบุ รับเฉพาะ LEASE หรือ CASH")
    entity = _valid_choice("entity", entity, ("EPC", "SPV"),
                           "ไม่รู้จักบริษัทที่ระบุ รับเฉพาะ EPC หรือ SPV")
    cases_domain.detect_broken_ptps(cs, settings.business_date)
    data = today_domain.build(officer=officer, ladder_indicative=rung, only_tier=tier,
                              payment_status=payment_status, dc_status=dc_status, product=product,
                              entity=entity, q=q,
                              unassigned=unassigned_desk)
    # F17 / TASK-118 (R-A): only this desk carries the worked flags and the daily
    # summary — build()'s rows are shared with the workbook's pinned key set.
    today_domain.annotate_worked(data["items"], settings.business_date)
    data["meta"]["worked_today_count"] = sum(1 for i in data["items"] if i["worked_today"])
    data["meta"]["daily_summary"] = today_domain.daily_summary(data["items"], cs, settings.business_date)
    data["meta"]["sort"] = sort
    if sort == "arrears":
        data["items"].sort(key=lambda item: (item["tier_rank"], -Decimal(item["aggregate_overdue"]),
            -(item["oldest_dpd"] or 0), item["customer"]["display_name"], item["customer"]["uid"]))
        unlocked = [row for row in data["items"] if row["contact_lock"]["state"] == "OPEN" and row["tier"] != "ROUTINE"] or [
            row for row in data["items"] if row["contact_lock"]["state"] == "OPEN"]
        data["meta"]["next_up"] = unlocked[0]["customer"]["uid"] if unlocked else None
    from .. import main
    data["meta"]["board_counts"] = dict.fromkeys((column["column_id"] for column in main.BOARD_COLUMNS), 0)
    for row in data["items"]:
        column = row.get("board_column_id")
        if column:
            data["meta"]["board_counts"][column] = data["meta"]["board_counts"].get(column, 0) + 1
    return _json(data)


TODAY_EXPORT_COLUMNS = (
    "customer_uid", "volt_id", "customer_number", "display_name", "workstream", "officer",
    "priority", "tier", "payment_status", "payment_confirmed", "payment_pending_since",
    "pending_claim_count", "pending_claim_amount", "pending_claim_uids",
    "confirmed_outstanding", "projected_outstanding", "overdue", "total_outstanding", "dpd",
    "dc_status", "next_action", "next_action_date", "down_payment_status",
    "invoice_release_status", "business_date", "data_source",
)


def _export_error(pointer, code, message, message_th):
    raise errors.validation_failed([{"pointer": pointer, "code": code,
                                     "message": message, "message_th": message_th}])


def _source_code(value):
    if isinstance(value, dict):
        return value.get("identity") or value.get("history") or ""
    return value or ""


def _project_collection_export(item):
    customer, case = item.get("customer") or {}, item.get("case") or {}
    confirmed = Decimal(str(item.get("aggregate_outstanding") or "0"))
    pending = Decimal(str(case.get("payment_pending_amount") or "0"))
    return {
        "customer_uid": customer.get("uid"), "volt_id": customer.get("volt_id") or case.get("volt_id"),
        "customer_number": customer.get("customer_no"), "display_name": customer.get("display_name"),
        "workstream": "collection", "officer": case.get("officer_uid") or customer.get("officer"),
        "priority": item.get("priority_reason"), "tier": item.get("tier"),
        "payment_status": case.get("payment_status"),
        "payment_confirmed": "false" if case.get("payment_status") == "PENDING" else "true",
        "payment_pending_since": case.get("payment_pending_since"),
        "pending_claim_count": case.get("payment_pending_count") or 0,
        "pending_claim_amount": case.get("payment_pending_amount") or "0.00",
        "pending_claim_uids": ";".join(case.get("payment_pending_uids") or []),
        "confirmed_outstanding": str(confirmed),
        "projected_outstanding": str(max(Decimal("0.00"), confirmed - pending)),
        "overdue": item.get("aggregate_overdue"), "total_outstanding": item.get("aggregate_outstanding"),
        "dpd": item.get("oldest_dpd"), "dc_status": case.get("dc_status"),
        "next_action": case.get("next_action"), "next_action_date": case.get("next_action_on"),
        "down_payment_status": None, "invoice_release_status": None,
        "business_date": str(settings.business_date), "data_source": _source_code(item.get("data_source")),
    }


def _project_pre_install_export(item):
    gate = item.get("gate_down_payment") or {}
    return {
        "customer_uid": item.get("customer_uid"), "volt_id": item.get("volt_id"),
        "customer_number": item.get("customer_no"), "display_name": item.get("display_name"),
        "workstream": "pre_install", "officer": item.get("sales_lead"),
        "priority": item.get("risk_score"), "tier": None,
        "payment_status": None, "payment_confirmed": None, "payment_pending_since": None,
        "pending_claim_count": 0, "pending_claim_amount": "0.00", "pending_claim_uids": "",
        # A pre-install quote is not a confirmed receivable; do not turn it into debt in an export.
        "confirmed_outstanding": None, "projected_outstanding": None, "overdue": None,
        "total_outstanding": None, "dpd": item.get("case_dpd"), "dc_status": None,
        "next_action": None, "next_action_date": None,
        "down_payment_status": gate.get("state"),
        "invoice_release_status": "RELEASED" if item.get("released_at") else "NOT_RELEASED",
        "business_date": str(settings.business_date), "data_source": _source_code(item.get("data_source")),
    }


@router.post("/v1/today:export")
def today_selected_export(body: dict = Body(default={}),
                          x_volt_role: str = Header(default="OFFICER")):
    """Governed, selected-only CSV for either Today workstream."""
    raw_role = (x_volt_role or "").upper()
    if raw_role not in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Not permitted for this role",
                             detail="selected Today export requires Officer or above",
                             message_th="บทบาทนี้ไม่มีสิทธิ์ส่งออกรายการที่เลือก",
                             error_id="DEBT-IAM-0403")
    workstream = str((body or {}).get("workstream") or "").strip()
    if workstream not in ("collection", "pre_install"):
        _export_error("/workstream", "invalid", "workstream must be collection or pre_install",
                      "workstream ต้องเป็น collection หรือ pre_install")
    raw_ids = (body or {}).get("customer_uids")
    if not isinstance(raw_ids, list) or not raw_ids:
        _export_error("/customer_uids", "required", "select at least one customer",
                      "กรุณาเลือกลูกค้าอย่างน้อยหนึ่งราย")
    selected = [str(uid or "").strip() for uid in raw_ids]
    if any(not uid for uid in selected):
        index = next(i for i, uid in enumerate(selected) if not uid)
        _export_error("/customer_uids/%d" % index, "required", "customer uid is required",
                      "รหัสลูกค้าห้ามว่าง")
    if len(set(selected)) != len(selected):
        _export_error("/customer_uids", "duplicate", "customer_uids must be unique",
                      "รายการลูกค้าต้องไม่ซ้ำกัน")
    reason = str((body or {}).get("reason") or "").strip()
    if len(reason) < 8:
        _export_error("/reason", "required", "reason must be 8 to 500 characters",
                      "กรุณาระบุเหตุผลอย่างน้อย 8 ตัวอักษร")
    if len(reason) > 500:
        _export_error("/reason", "max_length", "reason must be at most 500 characters",
                      "เหตุผลยาวได้ไม่เกิน 500 ตัวอักษร")

    if workstream == "collection":
        payload = today_domain.build()
        rows = payload["items"]
        known = set(cases_domain.for_current().cases)
        projector = _project_collection_export
    else:
        from .pipeline import pipeline_payload
        payload = pipeline_payload()
        rows = payload["items"]
        known = {row.get("customer_uid") for row in pipeline_payload(include_all=True)["items"]}
        projector = _project_pre_install_export
    in_scope = {((row.get("customer") or {}).get("uid") if workstream == "collection"
                 else row.get("customer_uid")) for row in rows}
    for index, uid in enumerate(selected):
        if uid not in known:
            _export_error("/customer_uids/%d" % index, "unknown", "unknown customer uid",
                          "ไม่พบรหัสลูกค้าที่ระบุ")
        if uid not in in_scope:
            _export_error("/customer_uids/%d" % index, "out_of_scope", "customer is outside this workstream",
                          "ลูกค้าอยู่นอกขอบเขตงานนี้")

    selected_set = set(selected)
    projected, emitted = [], set()
    for row in rows:
        uid = ((row.get("customer") or {}).get("uid") if workstream == "collection"
               else row.get("customer_uid"))
        if uid in selected_set and uid not in emitted:
            projected.append(projector(row))
            emitted.add(uid)
    audit.describe(act="TODAY_SELECTION_EXPORTED",
                   detail={"workstream": workstream, "count": len(projected), "reason": reason})
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=TODAY_EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(csv_safety.mapping(row) for row in projected)
    filename = "volt-debt-%s-selected-%s.csv" % (workstream.replace("_", "-"), settings.business_date)
    return Response(("\ufeff" + out.getvalue()).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % filename})


@router.get("/v1/today/reminders")
def reminders(days: int = Query(default=21), officer: str = Query(default=None)):
    from datetime import timedelta
    cs = cases_domain.for_current()
    bd = settings.business_date
    horizon = str(bd + timedelta(days=days))
    offsets = cases_domain.reminder_offsets()          # N2-13: a config key, not a literal
    rows = []
    for case in cs.cases.values():
        # Judge's round-4 observation: the parameter was accepted and ignored, so every
        # desk saw the whole book's batch.
        if officer and case["officer_uid"] != officer:
            continue
        if (case["payment_status"] != "PENDING" and case["next_action"] == "SEND_REMINDER"
                and (case["next_action_on"] or "") <= horizon):
            customer = journey.customer_by_uid(case["customer_uid"])
            rows.append({"customer_uid": case["customer_uid"], "display_name": customer.display_name if customer else None,
                         "volt_id": case["volt_id"], "due_on": case["next_action_on"],
                         "kind": ("D-%d" % offsets[0]) if (case["next_action_on"] or "") > str(bd) else "D0",
                         "overdue": (case["next_action_on"] or "") < str(bd), "officer_uid": case["officer_uid"]})
    rows.sort(key=lambda r: (r["due_on"] or "", r["display_name"] or ""))
    return {"reminders": rows, "meta": {"total": len(rows), "horizon": horizon,
                                        "officer": officer,
                                        "offsets": list(offsets),
                                        # J4-21: the batch is not the only way to send one.
                                        "on_demand_route": "POST /v1/today/reminders:send",
                                        "on_demand_note_th": "ส่งแจ้งเตือนรายลูกค้าหรือรายใบแจ้งหนี้ได้ทันทีจากหน้าเคส (customer_uid หรือ invoice_uid)",
                                        "on_demand_note_en": "A reminder for one customer or one invoice can be sent straight from the case page",
                                        # Round-3 J3-13: batch_label is AUTHORITATIVE — the screen prints it
                                        # verbatim and never re-derives an offset (the build read "D+3").
                                        "batch_label": " / ".join("D-%d" % o if o else "D0" for o in offsets),
                                        "batch_label_authoritative": True,
                                        "batch_label_note_th": "ป้ายชุดนี้มาจากค่าที่ตั้งไว้ ให้แสดงตามนี้ ห้ามคำนวณใหม่",
                                        "batch_label_note_en": "This batch label comes from the setting; show it as served, never recompute it",
                                        "offsets_config_key": "reminder_offsets_days",
                                        # Round-3 J3-13 (regression of J2-21): config and SOP disagree and
                                        # nobody has decided. The app says so instead of picking one quietly.
                                        "offsets_conflict": {
                                            "app": ",".join(str(o) for o in offsets),
                                            "sop": "1,0",
                                            "open_question": "CF1",
                                            "note_th": "ค่าที่ตั้งไว้ในระบบคือ D-%d/D0 แต่ SOP ระบุ D-1/D0 — ข้อขัดแย้งนี้ยังไม่มีผู้ตัดสิน ระบบใช้ค่าที่ตั้งไว้และแจ้งไว้ตรงนี้" % offsets[0],
                                            "note_en": "The setting is D-%d/D0 but the SOP says D-1/D0 — nobody has decided this yet, so the app uses the setting and says so here" % offsets[0],
                                        },
                                        "template_th": "เรียนคุณ {name} ค่างวดเดือนนี้ {amount} บาท ครบกำหนดวันที่ {due} ชำระผ่าน QR ในใบแจ้งหนี้ได้เลยค่ะ",
                                        "note_th": "แจ้งเตือนเป็นการแจ้งข้อมูล ไม่ใช่การติดต่อทวงถาม จึงไม่ใช้สิทธิ์ติดต่อรายวัน",
                                        "note_en": "A reminder is information, not a collection contact, so it does not use the daily contact",
                                        "note": "a reminder is a notification, not a collection contact — it never spends the daily slot"}}


@router.get("/v1/officers")
def list_officers():
    """Round-2 settasak S2-04: who can sign what. Governed acts (Manager/Owner) are
    signed by an identity that holds the role; officers.sign applies it."""
    rows = officers.registry()
    return {"officers": rows, "meta": {"total": len(rows), "defaults_by_role": dict(officers.ROLE_DEFAULTS),
                                        "note_th": "การกระทำระดับผู้จัดการ/เจ้าของจะลงชื่อด้วยผู้ที่ถือบทบาทนั้น หากชื่อในแถบบนไม่ใช่ จะลงชื่อด้วยชื่อประจำบทบาทและบันทึก by_role",
                                        "note_en": "Manager and Owner acts are signed by someone who holds that role; if the name in the top bar does not, the role's default name signs and the role is recorded"}}


@router.get("/v1/sop/steps")
def sop_steps():
    """The seventeen steps as a reference list — the team's own SOP, rank 2.

    Round 7 / WP2. The case page gets its step from `sop_step` on the case payload;
    the screens that own a STEP rather than a CASE — the invoice pipeline, the review
    queue, recovery — need the catalogue instead, so they can name the step an officer
    is standing in without the client hard-coding seventeen Thai strings of workflow
    content it does not own.

    It carries no customer, so unlike the case read it is not an audited read. Steps
    the prototype can never place a case on (7, 9, 17) are included, marked
    `placeable: false` with the reason, because an officer who can see only fourteen
    of seventeen would reasonably think the other three were missing.
    """
    return {
        "steps": [dict(s, screens=list(s["screens"]),
                       operated_by=("TEAM" if s["step"] in sop.D26_STEPS else "SYSTEM"),
                       lane_th=sop.LANE_TH[s["lane"]], lane_en=sop.LANE_EN[s["lane"]])
                  for s in sop.STEPS],
        "meta": {"total": len(sop.STEPS), "source": dict(sop.SOURCE),
                 "open_decision": dict(sop.D26)},
    }


@router.post("/v1/today/reminders:send")
def send_reminder(body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """Round-4 J4-21: send a reminder on demand, for a CASE or for one INVOICE.

    The batch is a list of what is due; an officer looking at a customer or at an
    overdue invoice must be able to send the reminder from where they are standing. A
    reminder is a notification, never a collection contact, so it spends no daily slot.
    """
    audit.describe(act="REMINDER_SENT")
    from datetime import timedelta
    cs = cases_domain.for_current()
    jstate = journey.for_current()
    invoice_uid = body.get("invoice_uid")
    invoice = jstate.invoices.get(invoice_uid) if invoice_uid else None
    if invoice_uid and invoice is None:
        raise errors.not_found("invoice")
    customer_uid = body.get("customer_uid")
    if invoice is not None and not customer_uid:
        found = journey.contract_by_uid(invoice["contract_uid"])
        customer_uid = invoice.get("customer_uid") or (found[0].uid if found else None)
    case = _case_or_404(cs, customer_uid)
    from .. import payment_claims
    signed_by = who(body, x_volt_officer)
    reminder, created = payment_claims.send_reminder(
        customer_uid, str(settings.business_date)[:7], by=signed_by,
        channel=body.get("channel", "LINE"))
    if not created:
        return {"contact": None, "case": case,
                "reminder": {**reminder, "invoice_uid": None, "counted": False,
                             "consolidated": True},
                "already_sent": True}
    about_th = ("แจ้งเตือนใบแจ้งหนี้ %s ครบกำหนด %s" % (invoice["uid"], invoice.get("due_date"))) if invoice \
        else "แจ้งเตือนค่างวดของลูกค้า"
    row = cases_domain._append_contact(cs, case, {
        "occurred_at": cases_domain.business_stamp(),        # J3-19 / J4-01: one clock
        "officer_uid": signed_by, "channel": body.get("channel", "LINE"), "direction": "OUTBOUND",
        "result": "LINE_SENT_UNREAD", "amount_stated": False, "counted": False,
        "note": body.get("note") or about_th,
        "source": "APP", "kind": "REMINDER", "invoice_uid": invoice["uid"] if invoice else None,
    })
    due = date(settings.business_date.year, settings.business_date.month, 10)
    if due <= settings.business_date:
        due = date(settings.business_date.year + (settings.business_date.month // 12), settings.business_date.month % 12 + 1, 10)
    # A follow-up the officer set themselves is not overwritten by a reminder (J4-07's rule).
    if case.get("next_action_set_by") in cases_domain.SYSTEM_SETTERS:
        cases_domain.set_next_action(cs, case, "CALL", due + timedelta(days=1), by="SYSTEM", note="follow up the day after the due date if unpaid")
    return {"contact": row, "case": case,
            "reminder": {**reminder, "invoice_uid": None, "sent_on": str(settings.business_date),
                         "counted": False, "consolidated": True,
                         "note_th": "แจ้งเตือนเป็นการแจ้งข้อมูล ไม่ใช่การทวงถาม จึงไม่ใช้สิทธิ์ติดต่อรายวัน",
                         "note_en": "A reminder is information, not a collection contact, so it does not use the daily contact"}}


@router.post("/v1/today/items/{uid}:done")
def today_item_done(uid: str):
    audit.describe(act="TODAY_ITEM_DONE", subject=("today_item", uid))
    cs = cases_domain.for_current()
    try:
        return {"item": cases_domain.mark_today_item_done(cs, uid)}
    except CaseError as exc:
        raise problem_from(exc)


# --- the work book ------------------------------------------------------------------

@router.get("/v1/workbook")
def workbook(product: str = Query(default=None), payment_status: str = Query(default=None),
             dc_status: str = Query(default=None), officer: str = Query(default=None),
             tier: str = Query(default=None), q: str = Query(default=None),
             sort: str = Query(default="aggregate_overdue"), dir: str = Query(default="desc"),
             ladder_indicative: str = Query(default=None), position: str = Query(default=None),
             identities: str = Query(default=None), entity: str = Query(default=None),
             limit: int = Query(default=None, ge=1, le=200), cursor: str = Query(default=None)):
    with perf.phase("workbook_build"):
        result = _workbook(product, payment_status, dc_status, officer, tier, q, sort, dir,
                           ladder_indicative, position, identities, limit, cursor, entity=entity)
    return _json(result)


IDENTITY_FIRST = 50      # directory rows before a query
IDENTITY_PAGE = 200      # and with one — the payload cap is 1 MiB


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _workbook_source():
    """Delta-100 B-01/D2f: the registry the workbook's rows are served from.

    The same book_source block the Data sources chain reads (migration._source_chain
    names the serving rung from `serving_code`/`serving_name` with the same
    fallbacks), so the workbook sub line and the chain can never print two
    different names for one source. Returns (source_name, source_label, note) — the
    screen prints the label, which already carries the rung's "(SHEET)" tag, and the
    note, which carries the served slice when one applies.
    """
    from .. import book_source
    # source_summary, not load(): the header needs the block, not 33k customer
    # fixtures (that read alone cost ~1.4 s on every workbook request).
    source = book_source.source_summary() or {}
    code = source.get("serving_code") or "SHEET"
    name = source.get("serving_name") or source.get("spreadsheet") or "New Order Master"
    note = (source.get("served_note_th"), source.get("served_note_en"))
    if code == "SHEET":
        return name, "%s (SHEET)" % name, note
    if code == "ODOO":
        return name or "Odoo crm.lead", "Odoo crm.lead", note
    if code == "STALE_SYSTEM":
        # The chain names this rung in Thai; there is no registry name to carry.
        return source.get("serving_name"), "ข้อมูลที่ค้างในระบบ", note
    return name, name, note


def _workbook(product=None, payment_status=None, dc_status=None, officer=None, tier=None, q=None,
              sort="aggregate_overdue", dir="desc", ladder_indicative=None, position=None,
              identities=None, limit=None, cursor=None, entity=None):
    from .. import read_projection
    entity = _valid_choice("entity", entity, ("EPC", "SPV"), "รับเฉพาะ EPC หรือ SPV")
    if read_projection.enabled():
        ladder_indicative = _valid_rung(ladder_indicative)
        position = _valid_position(position)
        if cursor and limit is None:
            raise errors.workbook_cursor_invalid("A cursor requires a page limit")
        return read_projection.workbook({"product": product, "payment_status": payment_status, "dc_status": dc_status,
            "officer": officer, "tier": tier, "q": (q or "").strip() or None, "ladder_indicative": ladder_indicative,
            "position": position, "identities": _truthy(identities), "entity": entity}, sort, dir, limit, cursor)
    return _legacy_workbook(product, payment_status, dc_status, officer, tier, q, sort, dir,
                            ladder_indicative, position, identities, limit, cursor, entity=entity)


def _legacy_workbook(product=None, payment_status=None, dc_status=None, officer=None, tier=None, q=None,
                     sort="aggregate_overdue", dir="desc", ladder_indicative=None, position=None,
                     identities=None, limit=None, cursor=None, entity=None, _projection_all=False):
    """Plain function behind /v1/workbook so the CSV export can share the filters.
    Round-1 UAT (judge J-16): the export called the route and received Query objects."""
    ladder_indicative = _valid_rung(ladder_indicative)
    # Task 14, ruling (a): validated first, before any row is built or filtered.
    position = _valid_position(position)
    q = (q or "").strip() or None
    if cursor and limit is None:
        raise errors.workbook_cursor_invalid("A cursor requires a page limit")
    paged = limit is not None
    epoch = data_epoch.current() if paged else None
    cursor_query = {
        "product": product, "payment_status": payment_status, "dc_status": dc_status,
        "officer": officer, "tier": tier, "q": q or "",
        "sort": sort, "dir": dir, "ladder_indicative": ladder_indicative,
        "position": position, "identities": _truthy(identities),
        "entity": entity,
    }
    offset = workbook_cursor.decode(cursor, epoch, cursor_query) if cursor else 0
    data = today_domain.build(ladder_indicative=ladder_indicative)
    rows = data["items"]
    # closed cases are in the book even if not on Today. 2026-09-20: terminated ones
    # too — an ended contract is still a row the book must show, for the same reason.
    cs = cases_domain.for_current()
    from ..routers.journey import _work_item
    jstate = journey.for_current()
    for customer in journey.book_customers():
        case = cs.cases.get(customer.uid)
        if case and case["payment_status"] in ("CLOSED", "TERMINATED"):
            item = _work_item(jstate, customer, settings.business_date, case_state=cs)
            # Round-4 F2-CR-1 correction 3: this loop builds its rows OUTSIDE
            # today_domain.build(), so the filter above never sees them — applied
            # again here or a CLOSED case could carry a filtered-out rung and still
            # show up, disagreeing with meta.total and the CSV (R4-F58's class).
            if ladder_indicative and (item.get("ladder") or {}).get("indicative") != ladder_indicative:
                continue
            item["tier"], item["tier_rank"], item["priority_reason"] = "ROUTINE", 7, "ROUTINE"
            item["case"] = today_domain._case_summary(case, cs)
            item["waiting"], item["missed_count"] = [], 0
            # Round-4 F3 BE-1: without this, the key is absent on every CLOSED row —
            # the same 7-key omission class as R4-F58.
            item["unreachable_run"] = cases_domain.unreachable_run(cs, customer.uid)
            rows.append(item)
    # The 2026-09-19 ruling: crm.lead identities are the Book's list, served only
    # when the caller asks for the customer directory (`identities=1`). The engine
    # reads (queues, KPIs, exports by default) stay contract-only, because an
    # identity has no contract to collect on and every money figure beside it is a
    # None/0 that would drag totals off.
    if _truthy(identities):
        identity_customers = journey.identity_customers()
        identity_epoch = epoch if epoch is not None else data_epoch.current()
        rows.extend(workbook_index.rows_for(
            identity_customers, identity_epoch,
            lambda customer: _identity_row(customer, cs),
        ))
    if product:
        rows = [r for r in rows if r["case"]["sheet"] and (("LEASE" if r["entity"] == "SPV" else "CASH") == product)]
    if entity:
        rows = [row for row in rows if row.get("entity") == entity]
    if payment_status:
        rows = [r for r in rows if r["case"]["payment_status"] == payment_status]
    if position:
        # Ruling (a): CLOSED rows are already appended above (they bypass
        # today_domain.build() and its own filters), so this one block is the
        # only place `position` needs to filter — meta.total and both CSV
        # exports agree with the JSON route by construction, no second path.
        if position == "unpaid":
            rows = [r for r in rows if (r.get("payment_position") or {}).get("open_count")]
        else:
            rows = [r for r in rows if (r.get("payment_position") or {}).get("stale") is True]
    if dc_status:
        rows = [r for r in rows if r["case"]["dc_status"] == dc_status]
    if officer:
        rows = [r for r in rows if r["case"]["officer_uid"] == officer]
    if tier:
        rows = [r for r in rows if r["tier"] == tier]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in (r["customer"]["display_name"] or "").lower()
                or needle in (r["case"]["volt_id"] or "").lower() or needle in (r["customer"]["customer_no"] or "").lower()]
    # The identity directory is search-first. 2,600 rows in one payload is several
    # megabytes and an unusable list, so: the first 50 before a query, up to 200
    # once one is typed — and the count is served so the note can say "N of M".
    identities_total = sum(1 for r in rows if r.get("identity_only"))
    identities_shown = 0
    if identities_total and not paged and not _projection_all:
        identities_shown = min(identities_total, IDENTITY_PAGE if q else IDENTITY_FIRST)
        kept, seen = [], 0
        for r in rows:
            if not r.get("identity_only"):
                kept.append(r)
                continue
            if seen < identities_shown:
                kept.append(r)
                seen += 1
        rows = kept
    if sort == "oldest_unpaid":
        # Ruling (b): undated rows (no open invoice) belong after every dated row
        # in BOTH directions — a single Decimal/str keyfn cannot express that,
        # since reverse= would flip the "undated last" placement along with the
        # date ordering. Partition and append instead.
        def _oldest_unpaid_due(r):
            return ((r.get("payment_position") or {}).get("oldest_unpaid") or {}).get("due_date")
        dated = [r for r in rows if _oldest_unpaid_due(r)]
        undated = [r for r in rows if not _oldest_unpaid_due(r)]
        dated.sort(key=lambda r: r["customer"]["uid"])
        dated.sort(key=_oldest_unpaid_due, reverse=(dir == "desc"))
        undated.sort(key=lambda r: r["customer"]["uid"])
        rows = dated + undated
    else:
        # The pre-existing silent fallback for an unknown sort key is untouched.
        keyfn = {
            "aggregate_overdue": lambda r: Decimal(r["aggregate_overdue"]),
            "aggregate_outstanding": lambda r: Decimal(r["aggregate_outstanding"]),
            "oldest_dpd": lambda r: r["oldest_dpd"] or 0,
            "display_name": lambda r: r["customer"]["display_name"] or "",
            "next_action_on": lambda r: r["case"]["next_action_on"] or "",
            "tier": lambda r: r["tier_rank"],
        }.get(sort, lambda r: Decimal(r["aggregate_overdue"]))
        rows.sort(key=lambda r: r["customer"]["uid"])
        rows.sort(key=keyfn, reverse=(dir == "desc"))
    matched_total = len(rows)
    page = None
    if paged:
        page_rows = rows[offset:offset + limit]
        next_offset = offset + len(page_rows)
        has_more = next_offset < matched_total
        rows = page_rows
        identities_shown = sum(1 for row in rows if row.get("identity_only"))
        page = {
            "limit": limit,
            "returned": len(rows),
            "has_more": has_more,
            "next_cursor": workbook_cursor.encode(next_offset, epoch, cursor_query) if has_more else None,
        }
    # Cached identity templates are process-shared. Only copy those entering this
    # response before adding request-specific enrichment below.
    rows = [dict(row) if row.get("identity_only") else row for row in rows]
    d = dictionaries.for_current()
    open_by_contract = _open_invoices_by_contract(jstate)
    for r in rows:
        r["invoice_state"] = _invoice_state(open_by_contract, r)    # J4-23
    # Delta-100 B-01/D2f: the pane's sub line names its source from the wire, not
    # from a literal on the screen.
    source_name, source_label, source_note = _workbook_source()
    result = {
        "rows": rows,
        "meta": {"total": matched_total, "business_date": str(settings.business_date),
                 "source_name": source_name, "source_label": source_label,
                 "source_note_th": source_note[0], "source_note_en": source_note[1],
                 "identities_total": identities_total, "identities_shown": identities_shown,
                 "identities_note_th": (("รายชื่อ Odoo แสดง %d จาก %d · พิมพ์ในช่องค้นหาเพื่อดูรายอื่น"
                                         % (identities_shown, identities_total)) if identities_total else None),
                 "identities_note_en": (("Odoo names: %d of %d shown · type in the search box for the rest"
                                         % (identities_shown, identities_total)) if identities_total else None),
                 # Round-4 J4-23: the sheet the team hands round could not be rebuilt from
                 # the old 16 columns — the penalty, the sheet's own late-fee and days-late
                 # cells and the invoice's state were all computed and all left behind.
                 # UX round 1 (cut 12): customer_no, entity and amount_to_ask join them.
                 # They existed only in the SCREEN's own client-side CSV, so the two files
                 # the team could produce were each missing three columns the other had.
                 # This projection is now a superset of both, and the client-side second
                 # export goes away — one export, and "every column" is true.
                 "columns": ["volt_id", "display_name", "customer_no", "product", "entity",
                             # R5-F05: entity travels with company_id everywhere else in
                             # this backend (entities.assert_entity_present asserts the
                             # pair on every JSON response) — the CSV writer emitted a
                             # flat list of scalars, which the dict-walking guard never
                             # sees, so the pair broke only here. One more column closes
                             # it; the guard's own reason is in entities.py:53-63.
                             "company_id",
                             "payment_status", "dc_status", "aggregate_overdue",
                             "aggregate_outstanding", "penalty_accrued_unbilled", "amount_to_ask",
                             "oldest_dpd", "aging_bucket",
                             "aging_bucket_label_th", "band_set_code", "open_ptp",
                             "next_action", "next_action_on", "last_contact_at", "officer", "tier",
                             "sheet_days_late", "sheet_late_fees", "fee_state", "invoice_state",
                             "invoice_peak_state",
                             # Feedback Round 1 / Task 10: paid count, open count, oldest
                             # unpaid, last money in and its source — already on every row
                             # via _work_item; named here so the column picker and the CSV
                             # export carry it too. Inserted here, beside the invoice-state
                             # columns, rather than appended at the tail: test_round4.py:758
                             # pins the LAST FOUR column names (kept_ptp_count onward) and
                             # must not be edited.
                             "payment_position",
                             "missed_basis_th", "tier_reason_th",
                             "open_service_issues", "manager_review_open", "data_source", "order_ref",
                             # Round-4 F1-BE1: the promise record, off the case (the owning
                             # store) — never the row-level twin (R4-F31/F54).
                             "kept_ptp_count", "broken_ptp_count",
                             # Round-4 F2-CR-2: NORMAL + null is the honest pair on 133/212
                             # rows — no rung reached, nobody has moved this case.
                             "ladder_stage", "ladder_indicative"],
                 "columns_note_th": "คอลัมน์ค่าปรับ ตัวเลขจากชีต สถานะใบแจ้งหนี้ เลขที่ลูกค้า บริษัทที่บันทึก และยอดที่ขอชำระ อยู่ในไฟล์ส่งออกทั้งหมด (J4-23 · UX-1)",
                 "columns_note_en": "The penalty, sheet figures, invoice state, customer number, company and amount to ask columns are all in the export",
                 "dictionaries": {"DC_STATUS": d.list("DC_STATUS"), "NEXT_ACTION": d.list("NEXT_ACTION")},
                 # Round-4 F2-CR-1 correction 2: /v1/today and /v1/workbook build their
                 # OWN meta dicts and share not one key — copied from the same build()
                 # call this request already ran, so the two endpoints never disagree.
                 "ladder_rungs": data["meta"]["ladder_rungs"],
                 "ladder_indicative": data["meta"]["ladder_indicative"]},
    }
    if page is not None:
        result["page"] = page
    return result


def _open_invoices_by_contract(jstate):
    """Open invoices grouped by contract, each bucket due-date ordered.

    `_invoice_state` used to scan EVERY invoice in the session once per row, so the
    workbook cost O(rows x invoices) — the 350k/500-contract bench made that 4s at
    25k rows. One pass here makes each row a lookup.
    """
    from ..routers.journey import OPEN_INVOICE_STATES
    index = {}
    for invoice in jstate.invoices.values():
        if invoice["state"] in OPEN_INVOICE_STATES:
            index.setdefault(invoice["contract_uid"], []).append(invoice)
    for bucket in index.values():
        bucket.sort(key=lambda i: (i["due_date"] or "", i["uid"]))
    return index


def _invoice_state(open_by_contract, row):
    """J4-23: the oldest OPEN invoice's state and its PEAK state, for the export.
    Nothing is computed here that the case page does not already show."""
    customer = journey.customer_by_uid(row["customer"]["uid"])
    uids = {k.uid for k in customer.contracts} if customer else set()
    oldest = [open_by_contract[uid][0] for uid in uids if uid in open_by_contract]
    if not oldest:
        return {"uid": None, "state": None, "peak_state": None, "due_date": None}
    oldest = min(oldest, key=lambda i: (i["due_date"] or "", i["uid"]))
    oldest = _with_peak_state(oldest)
    return {"uid": oldest["uid"], "state": oldest["state"],
            "peak_state": oldest.get("peak_state"), "due_date": oldest.get("due_date")}


def _order_ref_cell(order_ref):
    """R5-F02 / the backend half of R5-F03: `order_ref` used to reach the CSV as a
    Python dict repr — up to 224 characters, single-quoted, unparseable by any CSV
    reader, and printing the customer's name a third time. The one column carrying
    ruling 71's sheet-cell trace was the one column no reader could use. Emits
    "block:row" pairs (semicolon-joined on the rare multi-ref row) — the same
    (block, row) pair `import_master_sheet.py:8-10` already promises on every row,
    just written where a spreadsheet can read it. A customer with no sheet origin
    (SYNTHETIC/ODOO) still renders empty, not a repr of `None`."""
    if not order_ref:
        return None
    refs = order_ref.get("source_refs") or []
    cell = ";".join("%s:%s" % (b, r) for b, r in refs)
    return cell or None


def _write_rows(writer, rows):
    """The header<->row lockstep test_ux_round1.py:46-58 guards, extracted once
    (ruling 72) so `POST /v1/workbook:export` writes exactly what `GET` writes -
    one writer, not a second copy to drift out of step with the first."""
    for r in rows:
        c = r["case"]
        money = r.get("money_position") or {}
        pp = r.get("payment_position")
        inv = r.get("invoice_state") or {}
        sheet = c.get("sheet") or {}
        writer.writerow(csv_safety.row([c["volt_id"], r["customer"]["display_name"], r["customer"].get("customer_no"),
                         "LEASE" if r["entity"] == "SPV" else "CASH", r.get("entity"),
                         r.get("company_id"),
                         c["payment_status"], c["dc_status"], r["aggregate_overdue"], r["aggregate_outstanding"],
                         money.get("penalty_accrued_unbilled"), money.get("amount_to_ask"),
                         r["oldest_dpd"], r["aging_bucket"], r.get("aging_bucket_label_th"), r["band_set_code"],
                         (c["open_ptp"] or {}).get("promise_date"), c["next_action"], c["next_action_on"],
                         c["last_contact_at"], c["officer_uid"], r["tier"],
                         sheet.get("days_late"), sheet.get("late_fees"), r.get("fee_state"),
                         inv.get("state"), inv.get("peak_state"),
                         # Feedback Round 1 / Task 10: the header lockstep test
                         # (test_ux_round1.py:46-58) needs one CSV cell for the
                         # column, so the full block rides on the JSON row only, not
                         # the CSV. Fix round 1 (Important I1): "%s/%s" % (paid,
                         # open) read as a date in Excel/Sheets ("1/2"), and printed
                         # the literal string "None/None" when there was no block —
                         # worded instead, and left blank rather than "None" when
                         # payment_position is absent or null. Placed here, matching
                         # the "columns" list above, not appended at the tail:
                         # test_round4.py:758 pins the last four column names.
                         ("paid %d · open %d" % (pp["paid_count"], pp["open_count"])) if pp else "",
                         r.get("missed_basis_th"), r.get("tier_reason_th"),
                         r.get("open_service_issues"), r.get("manager_review_open"),
                         r.get("data_source"), _order_ref_cell(r.get("order_ref")),
                         # Round-4 F1-BE1: off c (r["case"]), the owning store — never
                         # r["broken_ptp_count"], the row-level twin (R4-F31/F54).
                         c["kept_ptp_count"], c["broken_ptp_count"],
                         # Round-4 F2-CR-2.
                         (r.get("ladder") or {}).get("stage"), (r.get("ladder") or {}).get("indicative")]))


def _filters_note(product, payment_status, dc_status, officer, tier, q, ladder_indicative, position=None, entity=None):
    """Feedback Round 1 / Task 14 fix (I1): `position` prints the same way every
    other filter here does. This note feeds BOTH the governed export's own
    "# ตัวกรอง: …" banner and the durable workbook_exports.record() audit entry
    — a position-filtered export was describing and recording itself as
    unfiltered before this parameter existed."""
    parts = []
    for key, value in (("product", product), ("payment_status", payment_status), ("dc_status", dc_status),
                       ("officer", officer), ("tier", tier), ("q", q), ("ladder_indicative", ladder_indicative),
                       ("position", position), ("entity", entity)):
        if value:
            parts.append("%s=%s" % (key, value))
    return ", ".join(parts) if parts else "ทั้งหมด"


def _csv_body(data):
    import csv
    import io
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(data["meta"]["columns"])
    _write_rows(writer, data["rows"])
    return out.getvalue()


@router.get("/v1/workbook:export")
def workbook_export(product: str = Query(default=None), payment_status: str = Query(default=None),
                    dc_status: str = Query(default=None), officer: str = Query(default=None),
                    tier: str = Query(default=None), q: str = Query(default=None),
                    sort: str = Query(default="aggregate_overdue"), dir: str = Query(default="desc"),
                    ladder_indicative: str = Query(default=None), position: str = Query(default=None),
                    identities: str = Query(default=None), entity: str = Query(default=None)):
    """Ruling 74 was SPECIFIED to close this verb here — a mandatory reason, a role
    capture and a record, the same shape as the governed `POST` below — and is
    ESCALATED INSTEAD, not built. Leg F's own blast-radius table (F-api.md section
    7.1) named six test functions across seven call sites; actually building the
    change and running the suite (not just reading it, as leg F's artifact says it
    did not) found TWO MORE, pre-existing and untouched this round:
    `test_ux_round1.py::test_the_added_columns_carry_the_values_the_screen_shows`
    (:66) and `::test_entity_and_product_are_two_columns_because_they_answer_two_
    questions` (:88) — both bare `client.get("/v1/workbook:export")` with no
    `reason`. The true cost is EIGHT test functions across TEN call sites, not the
    six across seven this leg was authorised to spend on ruling 74. "If a seventh
    assertion moves, stop and escalate" is this leg's own standing instruction, and
    an eighth and a ninth did too. Reverted to its exact original, ungoverned shape;
    the finding is recorded in C-backend.md and the ledger, not silently absorbed
    into edit 17's budget. Ruling 72's `POST`, below, needed no test edit and is NOT
    reverted — it is a second verb, not an edit to this one, and it already gives
    the officer one governed way to take the book out with a reason on the record."""
    from fastapi.responses import PlainTextResponse
    # _workbook validates and filters \u2014 the export shares it, so the CSV honours the
    # ladder filter by construction (WorkBook.jsx's whole reason for server-side filters).
    data = _workbook(product, payment_status, dc_status, officer, tier, q, sort, dir, ladder_indicative, position, entity=entity)
    filename = "volt-debt-workbook-%s.csv" % settings.business_date
    return PlainTextResponse("\ufeff" + _csv_body(data), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % filename})


@router.post("/v1/workbook:export")
def workbook_export_governed(body: dict = Body(default={}), product: str = Query(default=None),
                             payment_status: str = Query(default=None), dc_status: str = Query(default=None),
                             officer: str = Query(default=None), tier: str = Query(default=None),
                             q: str = Query(default=None), sort: str = Query(default="aggregate_overdue"),
                             dir: str = Query(default="desc"), ladder_indicative: str = Query(default=None),
                             position: str = Query(default=None), identities: str = Query(default=None),
                             entity: str = Query(default=None),
                             x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    """Ruling 72 — the governed export. Same resource, second verb (para 5.3 of
    docs/design/round-5/data-flow/F-api.md): one column list, one writer
    (`_write_rows`), so `test_ux_round1.py:46-58`'s lockstep guards both files by
    construction rather than by two people remembering to keep them in step — which
    is exactly the defect R5-F03 found between this export and WorkBook.jsx's own.

    Reason: free text, 8-500 characters — SOP paragraph 5 requires a STATED reason, and
    shorter than 8 characters is not a reason (a single character is not a reason).
    Refused the same shape `POST /v1/orders/{no}/status-override` already uses
    (integrations.py:102-106) — pointer "/reason", 422 validation_failed — so a
    blank reason from a stripped client is refused server-side, not merely by a
    browser's `required` attribute a refresh removes.

    Masked exactly as ruling 72 asks: leg F traced all 36 columns and found no
    phone, email or identity number among them (F-api.md section 3a) — there is
    nothing left to mask. The unhonoured half of ruling 72 was never masking; it was
    the absence of a reason, a signer and a record, which this verb supplies. The
    2FA and seven-day-expiry halves of rank 2 SOP paragraph 5 are NOT buildable in
    this prototype (session.py:8-11 — the cookie is not authentication, there is no
    SSO for a second factor to attach to; expiry needs a server-held, token-fetched
    resource, which this build's in-memory, no-database shape does not have) — named
    on the file's own face below, not silently dropped."""
    audit.describe(act="WORKBOOK_EXPORTED")
    reason = (body or {}).get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < 8:
        raise errors.validation_failed([{
            "pointer": "/reason", "code": "required",
            "message": "A workbook export requires a logged reason of at least 8 characters (SOP paragraph 5).",
            "message_th": "การส่งออกข้อมูลลูกค้าต้องระบุเหตุผล (SOP §5)"}])
    reason = str(reason).strip()[:500]
    data = _workbook(product, payment_status, dc_status, officer, tier, q, sort, dir, ladder_indicative, position, entity=entity)
    by, by_role = signer(body, x_volt_officer, x_volt_role, fallback="officer")
    unfiltered_total = _workbook()["meta"]["total"]
    import hashlib
    columns_hash = hashlib.sha1(",".join(data["meta"]["columns"]).encode()).hexdigest()[:12]
    taken_at = clock.stamp()
    filters_note = _filters_note(product, payment_status, dc_status, officer, tier, q, ladder_indicative, position, entity)
    from .. import workbook_exports
    entry = workbook_exports.record(
        verb="POST", by=by, by_role=by_role, reason=reason, on=str(settings.business_date),
        taken_at=taken_at, row_count=len(data["rows"]), total=unfiltered_total,
        filters=filters_note, columns_hash=columns_hash)

    provenance = (
        "# Volt Debt — สมุดงานติดตามหนี้ · ส่งออกเมื่อ %s (วันที่ทำงาน %s)\n"
        "# ผู้ส่งออก: %s (%s) · เหตุผล: %s\n"
        "# ตัวกรอง: %s · %d แถว จากทั้งหมด %d\n"
        "# ข้อมูลส่วนบุคคล: ปกปิดเบอร์โทรและอีเมลตั้งแต่นำเข้า · ไฟล์นี้ไม่มีคอลัมน์เบอร์โทรหรืออีเมล · "
        "ยังไม่มีการตรวจสอบสองชั้น (2FA) และยังไม่มีวันหมดอายุของไฟล์ในต้นแบบนี้ (SOP paragraph 5)\n"
    ) % (clock.local_stamp_th(taken_at), settings.business_date, by, by_role or x_volt_role.upper(), reason,
        filters_note, len(data["rows"]), unfiltered_total)

    from fastapi.responses import PlainTextResponse
    filename = "volt-debt-workbook-%s.csv" % settings.business_date
    return PlainTextResponse("\ufeff" + provenance + _csv_body(data), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % filename,
                                      "X-Volt-Export-Uid": entry["uid"]})


@router.get("/v1/workbook/exports")
def workbook_exports_list():
    """Ruling 72/74 — the record: who took the book out, when, and why. Per session,
    like every other per-tester log in this backend (session.py)."""
    from .. import workbook_exports
    entries = workbook_exports.list_for_current()
    return {"exports": entries, "meta": {"total": len(entries)}}



# --- the case ------------------------------------------------------------------------

def _case_or_404(cs, customer_uid):
    try:
        return cases_domain.get_case(cs, customer_uid)
    except CaseError as exc:
        raise problem_from(exc)


def _system_size_fields(sheet):
    """F04 / feedback-r2 TASK-101: the system's size in kWp from the Odoo order the
    customer's sheet carries. `orders.kwp` is the unit change, computed once on the
    backend; no order or no watt serves None with the reason, never a zero."""
    from .. import orders as orders_domain
    kwp = orders_domain.kwp((sheet.get("order") or {}).get("watt"))
    if kwp:
        return {"system_size_kwp": kwp,
                "system_size_note_th": "จากใบสั่งซื้อ Odoo",
                "system_size_note_en": "From the Odoo order"}
    return {"system_size_kwp": None,
            "system_size_note_th": "ไม่มีข้อมูลขนาดระบบในใบสั่งซื้อ",
            "system_size_note_en": "No system size on the Odoo order"}


def _month_grid(months, row, contract_uid=None):
    """Judge J-03: a month cell whose amount is not the instalment carries the
    difference and says the sheet does not name it."""
    pmt = row.get("pmt_inc_vat") or row.get("pmt")
    if not pmt:
        # the same rule the migration uses (book.usual_instalment): the instalment is the
        # amount the customer most often paid — N2-03 had the two disagree.
        from ..book import usual_instalment
        pmt = usual_instalment(months)[0]
    out = []
    for i, m in enumerate(months):
        cell = {"index": i + 1, **(m or {"kind": None}), "contract_uid": contract_uid}
        amount = cell.get("amount")
        if pmt and amount:
            try:
                diff = Decimal(str(amount)) - Decimal(str(pmt))
            except Exception:
                diff = Decimal("0")
            if diff != 0:
                cell["diff_from_pmt"] = str(diff)
                cell["note_th"] = ("%s บาท %s ยอดงวด %s บาท อยู่ %s บาท — ชีตไม่ระบุว่าเป็นอะไร (อาจเป็นค่าปรับหรือชำระเกิน)"
                                   % (amount, "มากกว่า" if diff > 0 else "น้อยกว่า", pmt, abs(diff)))
                cell["note_en"] = ("%s baht is %s baht %s the instalment of %s baht — the sheet does not say what it is (maybe a penalty or an overpayment)"
                                   % (amount, abs(diff), "more than" if diff > 0 else "less than", pmt))
        out.append(cell)
    return out


def _occurred_on(row):
    """The day a contact row happened, or None when the stamp cannot be read —
    never a guessed date."""
    try:
        return date.fromisoformat(str(row.get("occurred_at") or "")[:10])
    except ValueError:
        return None


def _contact_allowance(cs, customer_uid):
    """Delta-100 T-15/D2b: the weekly contact allowance, both numbers served.

    `cap` is the Settings limit (daily_contact_limit_per_customer); `used` is the
    customer's own COUNTED contact rows since Monday of the business week. The
    business date is already the Bangkok working day, so Monday is plain date
    arithmetic on it — no second clock. The screen words the sentence; this only
    serves the two figures it is made of.
    """
    bd = settings.business_date
    monday = bd - timedelta(days=bd.weekday())
    used = 0
    for row in cs.contact_log:
        if row.get("customer_uid") != customer_uid or not row.get("counted"):
            continue
        on = _occurred_on(row)
        if on is not None and monday <= on <= bd:
            used += 1
    return {"cap": settings.daily_contact_limit_per_customer, "used": used}


def _pre_install_case_detail(cs, case, customer_uid):
    """Round-3 J3-34: everything done to a pre-install customer used to live only on the
    pipeline card. The case exists from the moment an invoice is released; it carries the
    invoices and the timeline, and says plainly that the contract has not started."""
    from .. import invoice_pipeline as pipeline
    jstate = journey.for_current()
    d = dictionaries.for_current()
    book_customer = journey.customer_by_uid(customer_uid)   # TASK-209: the served provenance
    item = next((i for i in pipeline.for_current().items.values() if i["customer_uid"] == customer_uid), None)
    if item is not None:
        # The case page's card reads the same annotated shape the Pipeline screen
        # does — conditions, their evidence and the attach labels — so one component
        # can serve both without a second computation.
        pipeline.annotate(item)
    invoices = [_resolve_amended_due(_with_payment_link(_with_peak_state(inv)))
                for inv in jstate.invoices.values() if inv.get("customer_uid") == customer_uid]
    allowance = _contact_allowance(cs, customer_uid)
    claim_case, invoices, claims, claim_position = payment_claims.decorate(customer_uid, case, invoices)
    return {
        "case": {**claim_case, "dc_status_label": d.label("DC_STATUS", case["dc_status"]) if case["dc_status"] else None,
                 "next_action_label": d.label("NEXT_ACTION", case["next_action"]) if case["next_action"] else None,
                 "power_state_label_th": cases_domain.POWER_STATE_LABEL_TH.get(case["power_state"], case["power_state"]),
                 "power_state_label_en": cases_domain.POWER_STATE_LABEL_EN.get(case["power_state"], case["power_state"]),
                 "power_state_labels_th": dict(cases_domain.POWER_STATE_LABEL_TH),
                 "power_next_act": cases_domain.power_next_act(case),
                 "power_approver_role": settings.power_restriction_approver,
                 # Delta-100 D2a: no contract in the book yet, so no aggregate to
                 # score — served as None, never an invented zero.
                 "risk_score": None},
        "work_item": None,
        # Delta-100 D2a/T-15: same shape as the started contract's payload, so one
        # screen needs no second branch.
        "risk_score": None,
        "contact_allowance": allowance,
        # WP2 / round 7: the SOP step this case stands on. A pre-install customer is on
        # one of the D26 eight, so the object marks the step the TEAM's and carries the
        # open decision rather than minting a gate the Owner has not ruled on.
        "sop_step": sop.walkthrough(case, pipeline_item=item, in_book=False),
        "related_cases": [],
        "customer": {"uid": customer_uid, "customer_no": case["customer_no"],
                     "display_name": case.get("display_name"), "volt_id": case.get("volt_id"),
                     "odoo_crm": _customer_odoo_crm(book_customer, (item or {}).get("odoo_ref")),
                     **customer_contact.phone_fields(customer_uid), "line_id": None, "meta_id": None,
                     "officer": case["officer_uid"], "data_source": case["data_source"], "order_ref": None,
                     "risk_score": None, "contact_allowance": allowance,
                     # Q7 / TASK-209 (dry-run find 2026-09-23): a pre-install row is an
                     # identity in the served book too, so its decisions' provenance is
                     # served here the same way.
                     "field_sources": getattr(book_customer, "field_sources", None),
                     "field_notes_th": getattr(book_customer, "field_notes_th", None),
                     "field_notes_en": getattr(book_customer, "field_notes_en", None)},
        # No contract has started, so there is no cycle to draw (payment_summary.py).
        "contracts": [], "contract_count": 0, "month_grid": [], "payment_summary": None,
        "contact_log": [r for r in cs.contact_log if r["customer_uid"] == customer_uid][::-1],
        "ptps": [p for p in cs.ptps.values() if p["customer_uid"] == customer_uid],
        "issues": [i for i in cs.issues.values() if i["customer_uid"] == customer_uid],
        "reviews": [r for r in cs.reviews.values() if r["customer_uid"] == customer_uid],
        "power": [p for p in cs.power.values() if p["customer_uid"] == customer_uid],
        "sheet_row": {},
        "invoices": invoices,
        "payment_claims": claims,
        "payment_claim_position": claim_position,
        "receipts": [_with_peak_state(r) for r in jstate.receipts.values() if r.get("customer_uid") == customer_uid],
        # Round-5 T5-01: a pre-install customer is exactly the one whose amendment draft
        # went missing — the case must list what was sent to Accounting.
        "peak_documents": _case_peak_documents(
            customer_uid, {inv.get("contract_uid") for inv in invoices}, jstate),
        "events": [e for e in cs.events if e.get("case_uid") == case["uid"]],
        "pipeline_item": item,
        "pipeline_meta": {"invoice_owner_role": settings.invoice_owner_role},
        "unreachable_run": cases_domain.unreachable_run(cs, customer_uid),   # J4-32
        "pre_install": True,
        "pre_install_note_th": "ลูกค้ารายนี้ยังไม่ติดตั้ง จึงยังไม่มีสัญญาและยอดค้าง — เคสเปิดตั้งแต่เข้ากระบวนการก่อนติดตั้ง งานเงื่อนไข หลักฐาน และการปล่อยใบแจ้งหนี้ทำจบที่เคสนี้",
        "pre_install_note_en": "This customer is not installed yet, so there is no contract or arrears — the case opened when they entered the pre-installation process, and the conditions, evidence and release all finish here",
        "allocation_note": None,
        "allocation_hold_note_th": case.get("allocation_hold_note_th"),
        "allocation_hold_note_en": case.get("allocation_hold_note_en"),
        "sheet_reconciliation": None,
    }


def _identity_row(customer, case_state=None):
    order = (getattr(customer, "sheet", {}) or {}).get("order") or {}
    return {
        "customer": {"uid": customer.uid, "customer_no": customer.customer_no,
                     "display_name": customer.display_name,
                     "volt_id": getattr(customer, "volt_id", None),
                     "officer": getattr(customer, "officer", None),
                     "data_source": (getattr(customer, "data_source", {}) or {}).get("identity") or "ODOO"},
        "entity": None, "product": getattr(customer, "product", None),
        "aggregate_overdue": "0.00", "aggregate_outstanding": "0.00",
        "oldest_dpd": None, "risk_score": None,
        "aging_bucket": "IDENTITY", "aging_bucket_label_th": "ยังไม่มียอดเงิน",
        "aging_bucket_label_en": "No money row",
        "band_set_code": None, "board_column_id": None, "board_override": None,
        "board_pending_review_uid": None, "auto_moved": False, "auto_moved_cause": None,
        "answers_waiting": 0, "tier": None, "tier_rank": 9, "identity_only": True,
        "order_stage": order.get("order_status"),
        "order_ref": getattr(customer, "order_ref", None),
        "case": _identity_case_summary(customer, case_state),
    }


def _identity_case_summary(customer, case_state=None):
    """The exact shape today_domain._case_summary serves, with no case behind it.

    The CSV writer and the panels read these keys directly, so an identity row must
    carry the whole shape. Every counter is 0 and payment_status is None because no
    case exists — never a zero that could read as "nothing owed"."""
    return today_domain._case_summary({
        "uid": None, "payment_status": None, "dc_status": None, "npl_type": None,
        "next_action": None, "next_action_on": None, "next_action_set_by": None,
        "last_contact_at": None, "last_contact_by": None, "last_result": None,
        "broken_ptp_count": 0, "kept_ptp_count": 0, "renegotiation_count": 0,
        "power_state": None, "review_uid": None, "open_ptp_uid": None, "open_issue_uid": None,
        "sheet": {}, "volt_id": getattr(customer, "volt_id", None),
        "officer_uid": getattr(customer, "officer", None),
    }, case_state or cases_domain.for_current())


def _identity_only_case_detail(cs, customer, customer_uid):
    """A crm.lead customer the book serves as an identity: no contract, no invoice,
    no case. The 2026-09-19 ruling made these the served book, so the screen opens
    them with the served reason and every money figure absent — None, never zero,
    because nothing is owed on a row that carries no money."""
    from .. import customer_contact
    from .. import financial_evidence
    evidence = financial_evidence.for_customer(customer_uid)
    sheet = getattr(customer, "sheet", {}) or {}
    order = sheet.get("order") or {}
    allowance = _contact_allowance(cs, customer_uid)
    return {
        "identity_only": True,
        "financial_evidence": evidence,
        "reason": order.get("reason") or "no money row in Odoo",
        "case": None, "work_item": None, "risk_score": None,
        "contact_allowance": allowance,
        "sop_step": None, "related_cases": [],
        "customer": {"uid": customer_uid, "customer_no": getattr(customer, "customer_no", None),
                     "display_name": customer.display_name, "volt_id": getattr(customer, "volt_id", None),
                     "odoo_crm": _customer_odoo_crm(customer, order.get("crm_id")),
                     **customer_contact.phone_fields(customer_uid), "line_id": None, "meta_id": None,
                     "officer": order.get("sales_lead") or None, "data_source": "ODOO",
                     "order_ref": order.get("crm_id"), "risk_score": None,
                     "contact_allowance": allowance,
                     # Q7 / TASK-209: an identity-only row serves its field decisions'
                     # provenance exactly as the started case's block does.
                     "field_sources": getattr(customer, "field_sources", None),
                     "field_notes_th": getattr(customer, "field_notes_th", None),
                     "field_notes_en": getattr(customer, "field_notes_en", None),
                     # F04 / feedback-r2 TASK-101: symmetry with the started case's customer
                     # block — an identity-only row serves its order's size the same way.
                     **_system_size_fields(sheet)},
        "order": order,
        "contracts": [], "contract_count": 0, "month_grid": [], "payment_summary": None,
        "contact_log": [], "ptps": [], "issues": [], "reviews": [], "power": [],
        "sheet_row": {}, "invoices": [], "receipts": [], "peak_documents": [], "events": [],
        "pipeline_item": None, "unreachable_run": None,
        "identity_note_th": "ลูกค้ารายนี้มาจาก Odoo crm.lead — ยังไม่มียอดเงินหรือสัญญาในระบบ จึงยังไม่มีเคสติดตาม · Odoo ไม่เก็บยอดหรือสถานะการชำระ ยอดจะมาเมื่อ VOLT ID นี้อยู่ในแท็บ Done - Collection / Done - Cash หรือในไฟล์ PEAK",
        "identity_note_en": "This customer comes from Odoo crm.lead — no money row or contract exists yet, so there is no collection case · Odoo holds no amounts or payment status; they arrive once this VOLT ID is on the Done - Collection / Done - Cash tab or in a PEAK export",
        "allocation_note": None, "allocation_hold_note_th": None, "allocation_hold_note_en": None,
        "sheet_reconciliation": None,
    }


def _with_peak_state(row):
    """Round-3 J3-09: the case READS the PEAK document back. The queue and the case are
    two views of one record, so the document store is the authority for peak_state,
    peak_number and the Thai note on every load — never a stale copy."""
    from .. import peak_documents as pkd
    uid = row.get("peak_document_uid")
    if not uid:
        return row
    record = pkd.for_current().documents.get(uid)
    if record is None:
        return row
    record = pkd.annotate(record)
    return dict(row, peak_state=record["state"], peak_number=record.get("peak_number"),
                peak_ref=record.get("peak_ref"),
                peak_state_note_th=record.get("state_note_th"),
                peak_state_note_en=record.get("state_note_en"),
                peak_state_read_at=record.get("state_read_at"),
                peak_document_uid=uid)


def _resolve_amended_due(row):
    """Round-5 T5-01: an amendment raised on the pipeline is a REQUEST until AR
    approves it in PEAK (C3, draft-only). Until then the case shows the original due
    date with the request beside it; once the document is approved the date moves and
    the case says when and by which document."""
    from .. import peak_documents as pkd
    requested = row.get("amended_due_date")
    if not requested:
        return row
    uid = row.get("amended_due_document_uid")
    record = pkd.for_current().documents.get(uid) if uid else None
    state = record["state"] if record else None
    if state == "APPROVED_IN_PEAK":
        return dict(row, due_date=requested, amended_due_state="APPROVED_IN_PEAK",
                    amended_due_note_th=("เลื่อนวันครบกำหนดเป็น %s แล้ว (AR อนุมัติใน PEAK)" % requested),
                    amended_due_note_en="Due date moved to %s (approved by AR in PEAK)" % requested)
    if row.get("amended_due_note_th"):
        return dict(row, amended_due_state="PENDING_PEAK_APPROVAL")
    return dict(row, amended_due_state="PENDING_PEAK_APPROVAL",
                amended_due_note_th="ขอเลื่อนวันครบกำหนดเป็น %s — ยังไม่มีผลจนกว่า AR จะอนุมัติ" % requested,
                amended_due_note_en="Asked to move the due date to %s — no effect until AR approves it" % requested)



def _case_events(state, case, customer):
    terms = {k.uid: cases_domain.contract_field_of(k, "termination") for k in customer.contracts
             if cases_domain.contract_field_of(k, "termination")}
    result = []
    for event in state.events:
        if event.get("case_uid") != case["uid"]:
            continue
        row = dict(event)
        if row.get("kind") == "CONTRACT_TERMINATED":
            uid = row.get("contract_uid")
            if not uid and len(terms) == 1:
                uid = next(iter(terms))
            term = terms.get(uid)
            if term:
                row.update({k: term.get(k) for k in ("on", "by", "cause", "instrument", "origin")})
                row.update(contract_uid=uid, reason=term.get("reason") or term.get("reason_th") or term.get("reason_en"))
        result.append(row)
    return result

@router.get("/v1/cases/by-customer/{customer_uid}")
def case_detail(customer_uid: str):
    from .. import service_deferrals
    from ..routers.journey import _work_item
    cs = cases_domain.for_current()
    customer = journey.customer_by_uid(customer_uid)
    # D3: this is the one logged read — "who opened this customer's file" — and it
    # can only answer that question if the row names the customer. route_template
    # deliberately masks the uid (it groups rows by shape, not by which customer),
    # so the subject has to be attached here explicitly. Every branch below shares
    # this one call.
    try:
        case = cases_domain.get_case(cs, customer_uid)
    except CaseError as exc:
        # The 2026-09-19 ruling makes crm.lead the served book, so a lead the book
        # holds opens even with no case behind it — as an identity, never a
        # fabricated case. A uid the book does not hold at all still 404s.
        if customer is not None:
            audit.describe(subject=("customer", customer_uid))
            if getattr(customer, "contracts", None):
                raise errors.Problem("collection_case_not_ready", 503, "Reload the customer case",
                                     "The contract is available but its collection case has not been published.",
                                     "มีข้อมูลสัญญาแล้ว แต่เคสติดตามหนี้ยังไม่พร้อม กรุณาโหลดเคสใหม่",
                                     "DEBT-CASE-503", retryable=True)
            return _identity_only_case_detail(cs, customer, customer_uid)
        raise problem_from(exc)
    audit.describe(subject=("customer", customer_uid))
    if customer is None or not getattr(customer, "contracts", None):
        # Round-3 J3-34: a pre-install case has an invoice and a pipeline card but no
        # contract in the book yet. It still opens as a case rather than 404-ing —
        # and the invoice is what tells it apart from a crm.lead identity, which the
        # session also seeds a bare case for.
        jstate = journey.for_current()
        has_invoice = any(inv.get("customer_uid") == customer_uid for inv in jstate.invoices.values())
        # `pipeline_uid` is the seed-opened pre-install case (2026-09-20): the card
        # exists before any invoice, and the case page is where it finishes.
        if has_invoice or customer is None or case.get("pipeline_uid"):
            return _pre_install_case_detail(cs, case, customer_uid)
        return _identity_only_case_detail(cs, customer, customer_uid)
    jstate = journey.for_current()
    item = _work_item(jstate, customer, settings.business_date, case_state=cs)
    contract_uids = {k.uid for k in customer.contracts}
    sheet = getattr(customer, "sheet", None) or {}
    row = sheet.get("leasing") or sheet.get("cash") or {}
    months = row.get("months") or []
    d = dictionaries.for_current()
    # Round-2 nantapol N2-03: every contract carries ITS sheet row, grid, PMT and note; the
    # top-level month_grid / sheet_row stay the FIRST contract's for the old screen.
    contracts = []
    summaries = []
    for k in customer.contracts:
        k_row = getattr(k, "sheet_row", None)
        k_row = k_row if k_row is not None else (row if len(customer.contracts) == 1 else {})
        k_months = getattr(k, "month_cells", None)
        k_months = k_months if k_months is not None else (k_row.get("months") or [])
        _c, k_dpd, _band, block, _period = main_module()._contract_view(k)
        from .. import invoice_reviews
        imported = invoice_reviews.contract_arrears(customer, k, jstate, settings.business_date)
        arrears = block.cumulative_arrears
        if imported is not None:
            arrears, k_dpd = imported
        # Arina, 2026-09-14: the payment overview, on the same date and the same arrears
        # figure the block above was computed with.
        peak_cycles, unplaced, peak_as_of = payment_summary.peak_cycles_for(k.uid, journey.for_current())
        entry = payment_summary.for_contract(k, settings.business_date, arrears,
                                             month_cells=k_months, peak_cycles=peak_cycles)
        if entry["peak"]:
            entry["peak"]["report_as_of"] = peak_as_of
        entry["unplaced_peak_invoices"] = unplaced
        summaries.append(entry)
        contracts.append({
            # Ruling 43 / R4-F03: session-scoped read — never k.status directly.
            "uid": k.uid, "product": k.product, "entity": k.entity, "status": cases_domain.contract_field_of(k, "status"), "principal": str(k.principal),
            "term_months": k.term_months, "first_due": str(k.first_due), "paid_through": k.paid_through,
            "schedule_confirmation": getattr(k, "schedule_confirmation", None),
            "schedule_verified": entry["schedule_verified"], "schedule_conflict": entry["schedule_conflict"],
            "source_first_due": entry["source_first_due"],
            "sheet_calendar_months": getattr(k, "calendar_months", []),
            "contract_end": entry["contract_end"],
            # Ruling 43 / R4-F01: session-scoped read — never k.fee_state directly.
            "derivation": getattr(k, "derivation", None), "fee_state": cases_domain.fee_state_of(k),
            "fee_state_from": str(cases_domain.fee_state_of(k, "fee_state_from")) if cases_domain.fee_state_of(k, "fee_state_from") else None,
            "fee_state_until": str(cases_domain.fee_state_of(k, "fee_state_until")) if cases_domain.fee_state_of(k, "fee_state_until") else None,
            "pmt": str(getattr(k, "pmt", None)) if getattr(k, "pmt", None) is not None else (k_row.get("pmt_inc_vat") or k_row.get("pmt")),
            "sheet_row": k_row, "month_grid": _month_grid(k_months, k_row, contract_uid=k.uid),
            "comment_th": getattr(k, "comment_th", None) if getattr(k, "comment_th", None) is not None else (k_row.get("comment_th") or k_row.get("comment")),
            "late_cells": list(getattr(k, "late_cells", None) or []), "link_sent_cells": list(getattr(k, "link_sent_cells", None) or []),
            "instalments_overdue": str(arrears), "penalty_accrued_unbilled": str(block.penalty_accrued_unbilled),
            "oldest_dpd": k_dpd,
        })
    first = contracts[0] if contracts else None
    # Delta-100 D2a/T-15: the two figures the record header and its history footer
    # read. The score is the work item's own (computed from this case's snapshot);
    # the allowance is the cap plus the counted contacts since Monday.
    allowance = _contact_allowance(cs, customer_uid)
    risk_score = item.get("risk_score")
    from ..book import sheet_captured_on
    captured = sheet_captured_on()
    served_invoices = [service_deferrals.decorate_invoice(_resolve_amended_due(_with_payment_link(_with_peak_state(inv))))
                       for inv in jstate.invoices.values() if inv["contract_uid"] in contract_uids]
    from .. import invoice_reviews
    served_invoices = invoice_reviews.project(customer, jstate, served_invoices)
    due_totals = invoice_reviews.totals(served_invoices)
    claim_case, served_invoices, claims, claim_position = payment_claims.decorate(
        customer_uid, case, served_invoices)
    served_invoices = [service_deferrals.invoice_eligibility(inv) for inv in served_invoices if inv["invoice_visible"]]
    served_invoices.sort(key=journey.invoice_collection_sort_key)
    return {
        "service_deferrals": [r for k in customer.contracts for r in service_deferrals.list_for_contract(k.uid)],
        "case": {**claim_case, "dc_status_label": d.label("DC_STATUS", case["dc_status"]) if case["dc_status"] else None,
                 "next_action_label": d.label("NEXT_ACTION", case["next_action"]) if case["next_action"] else None,
                 "power_state_label_th": cases_domain.POWER_STATE_LABEL_TH.get(case["power_state"], case["power_state"]),
                 "power_state_label_en": cases_domain.POWER_STATE_LABEL_EN.get(case["power_state"], case["power_state"]),
                 "power_state_labels_th": dict(cases_domain.POWER_STATE_LABEL_TH),
                 "power_next_act": cases_domain.power_next_act(case),
                  "power_approver_role": settings.power_restriction_approver,
                  # R-B / TASK-222: the sentence beside the Manager's manual exception.
                  "payment_status_note_th": ("สถานะตามระบบคือ %s · ปรับด้วยมือโดยผู้จัดการ"
                                             % (case.get("payment_status_system") or "—")),
                  # Delta-100 D2a: the same served number, on the case object too.
                  "risk_score": risk_score,
                  # Arina, 2026-09-24: the "done collection" tab's own answer (a word the
                  # system does not know is flagged, not guessed), the month grid PEAK-
                  # first, and every place PEAK and the sheet disagree — nothing overwritten.
                  "sheet_status": cases_domain.sheet_status(customer),
                  "month_status": cases_domain.month_status(customer),
                  "status_disagreements": cases_domain.status_disagreements(customer),
                  # 2026-09-25: one row per month, newest first (records.customer_month).
                  "monthly_history": monthly_history.for_customer(customer.uid),
                  # The day the landed sheet's payments are known to (its contracts are
                  # derived as of it); None on the held fixture book.
                  "sheet_captured_on": str(captured) if captured else None},
        "work_item": item,
        # Delta-100 D2a/T-15: served top-level for a client that reads data first.
        "risk_score": risk_score,
        "contact_allowance": allowance,
        # WP2 / round 7: the SOP step this case stands on, the one act that moves it and
        # the branches the flowcharts draw. Deliberately NOT on _work_item or the workbook
        # row — test_round4.py:775 pins that exactly seven keys differ between a normal and
        # a CLOSED workbook row, and a key added there makes the septet an eight.
        "sop_step": sop.walkthrough(case, item=item),
        "related_cases": _related_cases(customer, cs),
        "customer": {"uid": customer.uid, "customer_no": customer.customer_no, "display_name": customer.display_name,
                     "name_roman": getattr(customer, "name_roman", None), "volt_id": getattr(customer, "volt_id", None),
                     "odoo_crm": _customer_odoo_crm(customer),
                     "epc": getattr(customer, "epc", None), "sales_lead": getattr(customer, "sales_lead", None),
                     # WP9: the same phone keys the work item's customer serves (R5-F01's
                     # escalation — the two objects used to disagree on phone_on_file).
                     **customer_contact.phone_fields(customer.uid, customer), "line_id": customer.line_id,
                     "meta_id": getattr(customer, "meta_id", None),
                     # Ruling 40: overlay-aware, same pattern as board_column_id/recovery_stage —
                     # never the shared Customer fixture's `.officer` directly.
                     "officer": jstate.officer_overlay.get(customer.uid, customer.officer),
                     "data_source": customer.data_source, "order_ref": customer.order_ref,
                     # F04 / feedback-r2 TASK-101: the system size, served with the reason
                     # it is absent when the order carries no watt.
                     **_system_size_fields(sheet),
                     # Q7 / TASK-209: the provenance of any field a person decided.
                     "field_sources": getattr(customer, "field_sources", None),
                     "field_notes_th": getattr(customer, "field_notes_th", None),
                     "field_notes_en": getattr(customer, "field_notes_en", None),
                     # Delta-100 D2a/T-15: the record's own figures ride the
                     # customer object too, so one screen has one read path.
                     "risk_score": risk_score, "contact_allowance": allowance},
        "contracts": contracts,
        "contract_count": len(contracts),
        # Every cycle of every contract and what it adds up to (payment_summary.py).
        "payment_summary": {
            **payment_summary.build(summaries, settings.business_date),
            "totals": {**payment_summary.build(summaries, settings.business_date)["totals"], **due_totals},
            "display_instalments": payment_display.build(customer.contracts, summaries, jstate,
                settings.business_date, item["contract_outstanding"]),
        },
        "month_grid": first["month_grid"] if first else _month_grid(months, row),
        "contact_log": [r for r in cs.contact_log if r["customer_uid"] == customer_uid][::-1],
        "ptps": [p for p in cs.ptps.values() if p["customer_uid"] == customer_uid],
        "issues": [service_deferrals.decorate_issue(i, customer.contracts)
                   for i in cs.issues.values() if i["customer_uid"] == customer_uid],
        "reviews": [r for r in cs.reviews.values() if r["customer_uid"] == customer_uid],
        "power": [p for p in cs.power.values() if p["customer_uid"] == customer_uid],
        "sheet_row": first["sheet_row"] if first else row,
        "invoices": served_invoices,
        "payment_claims": claims,
        "payment_claim_position": claim_position,
        "receipts": [_with_peak_state(r) for r in jstate.receipts.values() if r["contract_uid"] in contract_uids],
        # Round-5 T5-01: the case is where an officer looks for what was sent to
        # Accounting, and the amendment draft raised on the pipeline was nowhere on it.
        # Every PEAK document this customer has, annotated, on the same load.
        "peak_documents": _case_peak_documents(customer_uid, contract_uids, jstate),
        "events": _case_events(cs, case, customer),
        # Round-3, ruling 8 (Arina, 2026-09-04): this key is an English developer note
        # only — no client is contracted to branch on it (errors.py:1-13's "code is the
        # only field clients branch on" applies here by the same logic). It used to
        # assert receipts were "recorded and drafted in PEAK" unconditionally, which was
        # false on 210/212 cases (zero receipts). Reworded to the standing fact only.
        "allocation_note": "instalment allocation waits on the allocation-order decision, so arrears do not move until Accounting settles it",
        # Round-4 J4-27: the caption follows the document's STATE, not the intent that
        # raised it — an approved receipt no longer reads "รอ AR อนุมัติใน PEAK".
        "allocation_note_th": _allocation_note_th(case, jstate, contract_uids),
        "allocation_note_en": _allocation_note_th(case, jstate, contract_uids, lang="en"),
        # Round-3, ruling 8: the standing OD-02 refusal, true on every case regardless of
        # receipts (contract §3 — the refusal stays on 212/212 and, unlike the sentence it
        # replaces on the default view, is never false). Shares its wording with
        # `_allocation_note_th`'s own tail so the two sentences can never drift.
        "allocation_note_standing_th": ALLOCATION_NOTE_STANDING_TH,
        "allocation_note_standing_en": ALLOCATION_NOTE_STANDING_EN,
        "allocation_hold_note_th": case.get("allocation_hold_note_th"),      # J3-08: beside the money
        "allocation_hold_note_en": case.get("allocation_hold_note_en"),
        "sheet_reconciliation": _sheet_reconciliation(case, contracts),      # J3-17
        "unreachable_run": cases_domain.unreachable_run(cs, customer_uid),   # J4-32
    }


# Round-4 J4-31: there is no customer-facing invoice URL anywhere in the domain — the
# sheet records that a link was sent, never an address. The app says so plainly instead
# of leaving step 4 as "record that you sent a link the app cannot give you". The one
# real payable artefact is the QR on an APPROVED PEAK document.
_ROLE_EN = {"OFFICER": "Officer", "SUPERVISOR": "Supervisor", "MANAGER": "Manager", "OWNER": "Owner", "OPS": "Operations"}

PAYMENT_LINK_NONE_TH = ("แอปยังไม่มีลิงก์ชำระเงินสำหรับลูกค้า — ระบบไม่ได้เก็บที่อยู่ลิงก์ไว้เลย "
                        "ให้ส่งจากช่องทางเดิม (เอกสาร PEAK หรือ QR) แล้วบันทึกว่าส่งแล้ว")
PAYMENT_LINK_QR_TH = "ใช้ QR จากเอกสาร PEAK ที่อนุมัติแล้ว (%s) — แอปไม่มีลิงก์หน้าเว็บให้ลูกค้า"
PAYMENT_LINK_NONE_EN = ("The app has no payment link for the customer — no link address is stored at all. "
                        "Send it the usual way (the PEAK document or QR), then record that it was sent")
PAYMENT_LINK_QR_EN = "Use the QR on the approved PEAK document (%s) — the app has no web link for the customer"


def _with_payment_link(row):
    qr = row.get("qr_payload")
    return dict(row,
                payment_link=None,
                payment_link_state="PEAK_QR" if qr else "NOT_AVAILABLE",
                payment_qr_payload=qr,
                payment_link_note_th=(PAYMENT_LINK_QR_TH % qr) if qr else PAYMENT_LINK_NONE_TH,
                payment_link_note_en=(PAYMENT_LINK_QR_EN % qr) if qr else PAYMENT_LINK_NONE_EN)


# Round-3, ruling 8 (Arina, 2026-09-04): the tail every receipts-state sentence below
# already shared, now also served standing (no receipts head) so a case with none can
# still carry a TRUE OD-02 refusal instead of the removed, unconditional false premise.
# One string, two callers — `_allocation_note_th` and `case_detail`'s
# `allocation_note_standing_th` — so they can never drift apart.
ALLOCATION_NOTE_STANDING_TH = "การจัดสรรเข้างวดรอบัญชีตัดสินลำดับการจัดสรร ยอดค้างจึงยังไม่เปลี่ยนจนกว่าบัญชีจะตัดสิน"
ALLOCATION_NOTE_STANDING_EN = ("Placing payments into instalments waits for Accounts to decide the order, "
                               "so the arrears do not change until Accounts decides")


def _allocation_note_th(case, jstate, contract_uids, lang="th"):
    """J4-27: one caption, driven by what PEAK actually answered. `lang="en"` composes
    the English twin from the same branch."""
    rows = [_with_peak_state(r) for r in jstate.receipts.values() if r["contract_uid"] in contract_uids]
    if not rows:
        return None
    en = lang == "en"
    approved = [r for r in rows if r.get("peak_state") == "APPROVED_IN_PEAK"]
    if approved:
        ref = approved[-1].get("peak_number") or approved[-1]["uid"]
        head = ("Receipt approved in PEAK (%s)" if en else "ใบเสร็จอนุมัติใน PEAK แล้ว (%s)") % ref
    elif any(r.get("peak_state") == "DRAFT_CREATED" for r in rows):
        head = "Receipt drafted in PEAK, waiting for AR to approve it" if en \
            else "ใบเสร็จสร้างร่างใน PEAK แล้ว รอ AR อนุมัติใน PEAK"
    else:
        head = "Receipt recorded, not yet sent to PEAK" if en else "ใบเสร็จถูกบันทึกไว้แล้ว ยังไม่ได้ส่งไป PEAK"
    return head + " — " + (ALLOCATION_NOTE_STANDING_EN if en else ALLOCATION_NOTE_STANDING_TH)


def _sheet_reconciliation(case, contracts):
    """Round-3 J3-17: the fee gap was explained, the DAYS gap was not — sheet 54 days
    against the app's 13. Two different as-of dates, and a 14-day grace (OD-31) that is
    why this customer's app penalty is 0.00 while another's is 774.01. One sentence
    names both."""
    from ..book import snapshot_date
    sheet = case.get("sheet") or {}
    sheet_days = sheet.get("days_late")
    dpds = [c["oldest_dpd"] for c in contracts if c["oldest_dpd"] is not None]
    dpd = max(dpds) if dpds else None
    grace = settings.late_payment_grace_days
    penalty = sum(Decimal(c["penalty_accrued_unbilled"]) for c in contracts) if contracts else Decimal("0")
    snap = snapshot_date()
    days = (sheet_days if sheet_days is not None else "-", snap.day, snap.month, snap.year,
            dpd if dpd is not None else "-",
            settings.business_date.day, settings.business_date.month, settings.business_date.year)
    lines = ["ชีตนับ %s วัน ณ วันที่ดึงข้อมูล %02d/%02d/%d — แอปนับ %s วัน ณ วันทำการ %02d/%02d/%d จึงไม่เท่ากันโดยธรรมชาติ" % days]
    lines_en = ["The sheet counts %s days as of its pull on %02d/%02d/%d — the app counts %s days as of business day "
                "%02d/%02d/%d, so the two differ by design" % days]
    if dpd is not None and dpd <= grace:
        lines.append("ค่าปรับของแอปยังเป็น 0.00 เพราะค้าง %d วัน ยังไม่พ้นระยะผ่อนผัน %d วัน" % (dpd, grace))
        lines_en.append("The app's penalty is still 0.00: %d days late is within the %d-day grace period" % (dpd, grace))
    elif dpd is None:
        lines.append("ยังไม่ยืนยัน DPD จากหลักฐาน — ยอดรอตรวจสอบ; ระยะผ่อนผัน %d วันจะใช้เมื่อยืนยันฐานหนี้ได้" % grace)
        lines_en.append("Evidence DPD is unconfirmed — balances await review; the %d-day grace applies after the debt basis is verified" % grace)
    elif dpd is not None:
        lines.append("ค่าปรับของแอปเริ่มนับหลังพ้นระยะผ่อนผัน %d วัน จึงคิดจาก %d วัน" % (grace, dpd - grace))
        lines_en.append("The app's penalty starts after the %d-day grace period, so it is charged on %d days" % (grace, dpd - grace))
    return {
        "sheet_days_late": sheet_days,
        "sheet_snapshot_date": str(snap),
        "app_oldest_dpd": dpd,
        "business_date": str(settings.business_date),
        "late_payment_grace_days": grace,
        "app_penalty_accrued_unbilled": str(penalty),
        "note_th": " · ".join(lines),
        "note_en": " · ".join(lines_en),
    }


def main_module():
    from .. import main
    return main


def _related_cases(customer, cs):
    """Other rows of the same person in the book (one VOLT id each — ปัทมวรรณ (1) and (2))."""
    name = (customer.display_name or "").strip()
    if not name:
        return []
    rows = []
    for other in journey.book_customers():
        if other.uid == customer.uid or (other.display_name or "").strip() != name:
            continue
        case = cs.cases.get(other.uid)
        payment_status = case["payment_status"] if case else None
        from .. import read_projection
        if case is None and read_projection.enabled():
            from sqlalchemy import text
            payment_status = read_projection._unit()["conn"].execute(text(
                "select p.payment_status from app.customer_projection p join app.projection_current c "
                "on c.generation=p.generation where c.singleton and p.customer_uid=:u"), {"u": other.uid}).scalar()
        rows.append({"customer_uid": other.uid, "customer_no": other.customer_no, "volt_id": getattr(other, "volt_id", None),
                     "display_name": other.display_name, "payment_status": payment_status,
                     "note_th": "อีกสัญญาหนึ่งของลูกค้ารายเดียวกัน (VOLT id %s) — เงินและตารางเดือนแยกกัน" % getattr(other, "volt_id", other.customer_no),
                     "note_en": "Another contract of the same customer (VOLT id %s) — money and months are kept separately" % getattr(other, "volt_id", other.customer_no)})
    return rows


@router.get("/v1/cases/by-customer/{customer_uid}/invoices")
def customer_open_invoices(customer_uid: str):
    """Round-2 thip T2-04: the slip form offers this customer's open invoices with the
    amount to ask pre-filled (the invoice's outstanding — never computed on the screen)."""
    from ..routers.journey import money_position, OPEN_INVOICE_STATES
    cs = cases_domain.for_current()
    _case_or_404(cs, customer_uid)
    customer = journey.customer_by_uid(customer_uid)
    jstate = journey.for_current()
    contract_uids = {k.uid for k in customer.contracts}
    position = money_position(customer)
    rows = []
    for inv in jstate.invoices.values():
        if inv["contract_uid"] not in contract_uids or inv["state"] not in OPEN_INVOICE_STATES:
            continue
        outstanding = inv.get("outstanding") if inv.get("outstanding") not in (None, "") else inv["amount"]
        inv = _resolve_amended_due(_with_payment_link(_with_peak_state(inv)))   # J4-31, T5-01
        rows.append({**inv, "amount_to_ask": str(Decimal(str(outstanding)).quantize(Decimal("0.01"))),
                     "customer": {"uid": customer.uid, "customer_no": customer.customer_no, "display_name": customer.display_name,
                                  "volt_id": getattr(customer, "volt_id", None)}})
    from .. import invoice_reviews
    rows = invoice_reviews.project(customer, jstate, rows)
    rows = [inv for inv in rows if inv["invoice_visible"]]
    rows = [dict(inv, amount_to_ask=None, review_required=True)
            if not inv["is_due"] or not inv["collection_included"] else
            dict(inv, amount_to_ask=str(Decimal(str(inv["outstanding"])).quantize(Decimal("0.01"))))
            if inv.get("liability_verified") is True else inv for inv in rows]
    rows.sort(key=lambda i: (i["due_date"] or "", i["uid"]))
    # Feedback Round 1 / Task 10: the same block the work item carries, on the
    # per-customer invoices payload — the slip form reads it beside money_position.
    position_block = payment_position.build(customer, jstate, settings.business_date)
    return {"invoices": rows, "customer_uid": customer_uid, "money_position": position,
            "payment_position": position_block,
            "meta": {"total": len(rows), "states": list(OPEN_INVOICE_STATES),
                     "note_th": "ยอดที่ขอชำระของแต่ละใบคือยอดคงค้างของใบนั้น; ยอดรวมทั้งลูกค้าอยู่ใน money_position.amount_to_ask",
                     "note_en": "Each invoice's amount to ask is what is still owed on it; the customer's total is in the money position"}}


@router.post("/v1/cases/by-customer/{customer_uid}/next-action")
def set_next_action(customer_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    audit.describe(act="NEXT_ACTION_SET", subject=("customer", customer_uid))
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    try:
        cases_domain.set_next_action(cs, case, body.get("next_action"), body.get("next_action_on"),
                                     by=who(body, x_volt_officer), note=body.get("note"))
    except CaseError as exc:
        raise problem_from(exc)
    except dictionaries.DictionaryError as exc:
        raise dictionary_problem(exc)
    return {"case": case}


@router.post("/v1/cases/by-customer/{customer_uid}/dc-status")
def set_dc_status(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """A person's status; kept until the next logged contact changes it, or for good when governed (N2-09).

    `reason` is the name every other act in this API uses for the same thing
    (set_npl_type, the power request, R14's override). `note` is still accepted so an
    older caller keeps working, but the two are one field, not two."""
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    reason = body.get("reason") or body.get("note")
    try:
        cases_domain.set_dc_status(cs, case, body.get("code"), by=who(body, x_volt_officer), note=reason)
    # Ruling 11: d704a2c taught cases.set_dc_status to refuse a missing/unchanged
    # reason with CaseError, but never taught this route to catch it — the domain
    # rule and the HTTP contract were verified separately, and neither test saw the
    # gap between them (test_cases.py calls set_dc_status directly and sees the
    # CaseError; the frontend mocks the API). So the suite stayed green while the
    # route itself answered a reason-less request with an unhandled 500. problem_from
    # already carries both codes this raises (reason_required, status_unchanged) —
    # the route just never reached the table.
    except CaseError as exc:
        raise problem_from(exc)
    except dictionaries.DictionaryError as exc:
        raise dictionary_problem(exc)
    return {"case": case}


@router.get("/v1/contracts/{contract_uid}/schedule-confirmation")
def get_schedule_confirmation(contract_uid: str):
    from .. import schedule_confirmation
    if journey.contract_by_uid(contract_uid) is None:
        raise errors.not_found("contract")
    rows = schedule_confirmation.history(contract_uid)
    return {"confirmation": rows[-1] if rows else None, "history": rows}


@router.post("/v1/contracts/{contract_uid}/schedule-confirmation", status_code=201)
def confirm_contract_schedule(contract_uid: str, body: dict = Body(...),
                              x_volt_role: str = Header(default="OFFICER"),
                              x_volt_officer: str = Header(default=None)):
    from .. import schedule_confirmation
    found = journey.contract_by_uid(contract_uid)
    if found is None:
        raise errors.not_found("contract")
    if role_of(x_volt_role) not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager or above",
                             detail="Contract review requires Manager or Owner",
                             message_th="เฉพาะผู้จัดการหรือเจ้าของยืนยันวันเริ่มงวดได้",
                             error_id="DEBT-IAM-0403")
    from .. import instalment_evidence
    if not instalment_evidence.required(found[1]):
        raise errors.Problem(code="schedule_format_unsupported", status=422,
                             title="Reviewed schedule dates unsupported for this format",
                             detail="This contract format cannot apply a reviewed first due date",
                             message_th="รูปแบบสัญญานี้ยังไม่รองรับการยืนยันวันเริ่มงวด",
                             error_id="DEBT-SCHEDULE-0422")
    audit.describe(act="CONTRACT_SCHEDULE_CONFIRMED", subject=("contract", contract_uid))
    row = schedule_confirmation.confirm(found[1], body, who({}, x_volt_officer))
    main_module().reload_book()
    return {"confirmation": row}


@router.post("/v1/cases/by-customer/{customer_uid}/payment-status")
def set_payment_status(customer_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
                       x_volt_officer: str = Header(default=None)):
    """The manual payment status, with a reason — a Manager's audited exception.

    R-B / feedback-r2 TASK-220 (Q7 ruling): the manager's line is that the system
    owns this status, never the user. The automatic answer follows every apply
    (`cases.follow_system_payment_status`); this route stays for the one case where
    a person must overrule a wrong PEAK row, MANAGER and above. The case resolves
    FIRST, so an unknown uid is still a 404 rather than a role refusal. The served
    `note_th` names the system's own answer.
    Spec: docs/archive/superpowers/specs/2026-09-14-payment-status-adjustment-design.md

    `note` is accepted as another name for `reason`, as on dc-status."""
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    role = (x_volt_role or "OFFICER").upper()
    if role not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager or above",
                             detail="A manual payment status is a Manager's audited exception",
                             message_th="เฉพาะผู้จัดการขึ้นไปปรับสถานะการชำระด้วยมือได้",
                             error_id="DEBT-IAM-0403")
    reason = body.get("reason") or body.get("note")
    try:
        cases_domain.set_payment_status(cs, case, body.get("code"), by=who(body, x_volt_officer),
                                        reason=reason)
    except CaseError as exc:
        raise problem_from(exc)
    return {"case": case,
            # R-B / TASK-220: the sentence beside the exception names the system's own answer.
            "note_th": "สถานะตามระบบคือ %s · ปรับด้วยมือโดยผู้จัดการ" % (case.get("payment_status_system") or "—")}


@router.post("/v1/cases/by-customer/{customer_uid}:terminate")
@termination_archive.operation
def terminate_contract(customer_uid: str, body: dict = Body(default=None),
                       x_volt_role: str = Header(default="OFFICER"),
                       x_volt_officer: str = Header(default=None)):
    """End this customer's live contracts with a cause and a reason.

    2026-09-20 (Closed/Terminated ruling): CLOSED means paid per the terms and nothing
    else; every other way a contract ends — VOLT on default, or the customer's own
    request — is TERMINATED and must carry its cause. Outstanding balances remain
    in the ledger; this act does not pay or write off a debt. OFFICER, SUPERVISOR,
    MANAGER and OWNER may use it, while OPS may not. Body {"cause", "reason"} —
    cause from TERMINATION_CAUSE.
    """
    body = body or {}
    audit.describe(act="CONTRACT_TERMINATED", subject=("customer", customer_uid))
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    role = role_of(x_volt_role)
    if role not in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER"):
        raise problem_from(CaseError("forbidden", "Operations cannot terminate a contract",
                                     message_th="บทบาททีมปฏิบัติการไม่มีสิทธิ์ยุติสัญญา"))
    customer = journey.customer_by_uid(customer_uid)
    if customer is None:
        raise errors.not_found("customer")
    by = who(body, x_volt_officer, role=role)
    try:
        reason = cases_domain.validate_termination_inputs(body.get("cause"),
                                                          body.get("reason") or body.get("note"))
    except CaseError as exc:
        raise problem_from(exc)
    ended = []
    try:
        for contract in customer.contracts:
            if cases_domain.contract_field_of(contract, "status") in cases_domain.ENDED_CONTRACT_STATUSES:
                continue
            ended.append(cases_domain.record_termination(
                contract, cause=body.get("cause"), by=by, reason=reason,
                instrument="TERMINATE_ACT", on=body.get("effective_on")))
    except CaseError as exc:
        raise problem_from(exc)
    if not ended:
        raise problem_from(CaseError("status_unchanged", "Every contract on this case has already ended",
                                     message_th="สัญญาทุกฉบับของเคสนี้สิ้นสุดอยู่แล้ว"))
    return {"case": case, "termination": ended[0], "contracts": [
        {"contract_uid": contract.uid, "status": cases_domain.contract_field_of(contract, "status")}
        for contract in customer.contracts]}


@router.post("/v1/cases/by-customer/{customer_uid}/phone")
def set_customer_phone(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """Feedback Round 1 / WP9 (design F9 (a)): a real phone number for the customer,
    entered by any role with a reason, audited PHONE_SET ("set"/"cleared", never the
    number). Body {"phone": "081-234-5678" | null, "reason": "..."}; a null or blank
    phone clears it. Answers the customer's phone keys exactly as every read serves
    them, so the screen shows the server's own formatting."""
    cs = cases_domain.for_current()
    _case_or_404(cs, customer_uid)
    try:
        customer_contact.set_phone(customer_uid, body.get("phone"), by=who(body, x_volt_officer),
                                   reason=body.get("reason"))
    except CaseError as exc:
        raise problem_from(exc)
    fields = customer_contact.phone_fields(customer_uid, journey.customer_by_uid(customer_uid))
    return {"customer": {"uid": customer_uid, **fields}}


@router.post("/v1/cases/by-customer/{customer_uid}/phone:reveal")
def reveal_customer_phone(customer_uid: str):
    """The one read that answers a full phone number (2026-09-20). The case's own
    response serves masked phone keys plus `phone_revealable`; this route is the
    audited door — PHONE_REVEALED with source and kind, never the digits. A person's
    override wins over the imported number; nothing on file is DEBT-COL-0472."""
    cs = cases_domain.for_current()
    _case_or_404(cs, customer_uid)
    try:
        revealed = customer_contact.reveal_phone(customer_uid, journey.customer_by_uid(customer_uid))
    except CaseError as exc:
        raise problem_from(exc)
    return {"customer": {"uid": customer_uid, **revealed}}


@router.post("/v1/cases/by-customer/{customer_uid}/npl-type")
def set_npl_type(customer_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    try:
        by, by_role = signer(body, x_volt_officer, x_volt_role, "manager")   # S2-04
        cases_domain.set_npl_type(cs, case, body.get("code"), by=by, role=role_of(x_volt_role),
                                  reason=body.get("reason"), by_role=by_role)   # J-46
    except CaseError as exc:
        raise problem_from(exc)
    except dictionaries.DictionaryError as exc:
        raise dictionary_problem(exc)
    return {"case": case}


@router.post("/v1/cases/by-customer/{customer_uid}/contacts", status_code=201)
def log_case_contact(customer_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    """The contact log row (REQ-COL-072). The Act's daily slot is enforced by the
    existing POST /v1/contacts; the interface calls that first for a counting
    result and then this with counted=true. Both are recorded here."""
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    try:
        row, ptp, issue = cases_domain.log_contact(cs, case, body, by=who(body, x_volt_officer))
    except CaseError as exc:
        raise problem_from(exc)
    except dictionaries.DictionaryError as exc:
        raise dictionary_problem(exc)
    # Round-4 R4-F32/BE-2: non-null only when THIS call created one — never a
    # pre-existing review, which would make the drawer print "review sent" for a
    # call that sent nothing. The arity of log_contact's own return stays a 3-tuple
    # (ten sites unpack three); the review travels on the row and is looked up here.
    return {"contact": row, "ptp": ptp, "issue": issue, "case": case,
            "review": cs.reviews.get(row.get("review_uid"))}


@router.post("/v1/contacts/{uid}/notes", status_code=201)
def add_contact_note(uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """F7/F8: a note added to a contact already on the log, each with its own
    evidence files. Never counted, never a slot — the contact spent that already."""
    cs = cases_domain.for_current()
    try:
        note = cases_domain.add_contact_note(cs, uid, body.get("text"), who(body, x_volt_officer),
                                             body.get("attachment_uids") or [])
    except CaseError as exc:
        raise problem_from(exc)
    return {"note": note}


@router.post("/v1/cases/by-customer/{customer_uid}/notes", status_code=201)
def add_case_note(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """F7/F8: a note that is not a contact at all — an event on the case, never a
    row on the contact log, so it never spends the daily contact slot."""
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    try:
        event = cases_domain.add_case_note(cs, case, body.get("text"), who(body, x_volt_officer),
                                           body.get("attachment_uids") or [])
    except CaseError as exc:
        raise problem_from(exc)
    return {"event": event, "case": case}


@router.post("/v1/contacts/{uid}:correct", status_code=201)
def correct_contact(uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    audit.describe(act="CONTACT_CORRECTED", subject=("contact", uid))
    cs = cases_domain.for_current()
    old = next((r for r in cs.contact_log if r["uid"] == uid), None)
    if old is None:
        raise errors.not_found("contact")
    case = cs.cases[old["customer_uid"]]
    try:
        row = cases_domain.correct_contact(cs, case, uid, {k: v for k, v in body.items() if k in ("result", "note", "channel")}, by=who(body, x_volt_officer))
    except CaseError as exc:
        raise problem_from(exc)
    return {"contact": row}


@router.post("/v1/case-ptps/{uid}:close")
def close_case_ptp(uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    audit.describe(act="PTP_CLOSED", subject=("ptp", uid), detail={"outcome": (body or {}).get("outcome")})
    cs = cases_domain.for_current()
    ptp = cs.ptps.get(uid)
    if ptp is None:
        raise errors.not_found("ptp")
    case = cs.cases[ptp["customer_uid"]]
    try:
        cases_domain.close_ptp(cs, case, uid, body.get("outcome"), body.get("on", str(settings.business_date)), by=who(body, x_volt_officer),
                               reason=body.get("reason"))   # N2-16
        if body.get("outcome") in ("KEPT", "KEPT_PARTIAL"):
            cases_domain.payment_confirmed(cs, case, body.get("on", str(settings.business_date)))
    except CaseError as exc:
        raise problem_from(exc)
    # Round-4 J4-04: an early break is recorded WITH its warning rather than in silence.
    return {"ptp": ptp, "case": case,
            "warning": {"code": "ptp_broken_before_due",
                        "message_th": ptp["broken_before_due_note_th"],
                        "days_early": ptp["broken_before_due_days"],
                        "promise_date": ptp["promise_date"]} if ptp.get("broken_before_due") else None,
            "warning_th": ptp.get("broken_before_due_note_th")}


@router.post("/v1/case-ptps/{uid}:renegotiate", status_code=201)
def renegotiate_case_ptp(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
                         x_volt_officer: str = Header(default=None)):
    """Round-4 J4-02 — one rule for one act.

    Renegotiating a promise IS a conversation with the customer, but this route took no
    lock and wrote no contact row: three renegotiations left `contact_log` unchanged
    while the drawer refused a second call on the same customer. It now spends the same
    daily slot, through the same ContactLog the drawer uses, and writes the same row.
    An officer who has already used today's slot may still record the call — as an
    explicit `not_counted` second contact, never as "the customer called me".
    """
    audit.describe(act="PTP_RENEGOTIATED", subject=("ptp", uid))
    cs = cases_domain.for_current()
    ptp = cs.ptps.get(uid)
    if ptp is None:
        raise errors.not_found("ptp")
    case = cs.cases[ptp["customer_uid"]]
    by = who(body, x_volt_officer)
    not_counted = bool(body.get("not_counted"))
    # The domain's own refusals first (N2-05: nothing moves until everything is checked),
    # so a refused renegotiation never spends the customer's daily slot.
    try:
        cases_domain.check_renegotiable(cs, case, uid, body.get("amount"), body.get("date"))
    except CaseError as exc:
        raise problem_from(exc)
    attempt = _spend_the_daily_slot(case, by, role_of(x_volt_role), not_counted=not_counted)
    try:
        new, review = cases_domain.renegotiate_ptp(cs, case, uid, body.get("amount"), body.get("date"), by=by)
    except CaseError as exc:
        raise problem_from(exc)
    contact = cases_domain._append_contact(cs, case, {
        "occurred_at": cases_domain.business_stamp(),          # J4-01: the business clock
        "officer_uid": by, "channel": body.get("channel", "PHONE"), "direction": "OUTBOUND",
        "result": "REACHED_PTP", "amount_stated": True,
        "counted": bool(attempt.counted) if attempt else False,
        "not_counted_declared": not_counted,
        "note": body.get("note") or "เจรจานัดชำระใหม่ %s → %s" % (ptp["uid"], new["uid"]),
        "source": "APP", "ptp_uid": new["uid"], "kind": "RENEGOTIATION",
        "next_action": case["next_action"], "next_action_on": case["next_action_on"],
    })
    # N2-05: the new promise (still OPEN), the review it opened (or None), and the old one — nothing vanishes.
    return {"ptp": new, "review": review, "previous_ptp": ptp, "case": case,
            "escalated": bool(review), "renegotiation_count": new["renegotiation_count"],
            "contact": contact,
            "counted": bool(attempt.counted) if attempt else False,
            "lock_consumed": bool(attempt.lock_consumed) if attempt else False,
            "message_th": new.get("escalation_note_th") or new.get("renegotiation_note_th")}


def _spend_the_daily_slot(case, by, role, not_counted=False):
    """J4-02: the drawer's own check, applied to the renegotiation route.

    Returns the ContactLog attempt, or None when the customer is not in the fixture book
    (a pre-install case has no identity key to lock). Raises the SAME 409 the drawer
    raises, with the same alternatives — including the honest second-contact route."""
    from .. import main as main_module_ref
    from ..collections.contact import ContactLocked, ContactOnHold
    customer = journey.customer_by_uid(case["customer_uid"])
    if customer is None:
        return None
    try:
        return main_module_ref.contact_log.log_contact(
            customer_key=customer.identity_key,
            contract_uids=[k.uid for k in customer.contracts],
            channel="PHONE", direction="OUTBOUND", disposition="ANS_DISCUSSED",
            at=clock.business_now().replace(tzinfo=clock.BANGKOK),
            officer=by, role=role, not_counted=not_counted)
    except ContactOnHold:
        raise errors.contact_on_hold()
    except ContactLocked as exc:
        held = main_module_ref.contact_log.locks_for(customer.identity_key, settings.business_date, level="PERSON")
        lock = held[0] if held else None
        raise errors.contact_locked(
            alternatives=[{"code": "SECOND_CONTACT_NOT_COUNTED",
                           "label_th": errors.CONTACT_LOCKED_ALTERNATIVES["SECOND_CONTACT_NOT_COUNTED"],
                           "field": "not_counted",
                           "how_th": "ส่งคำขอเจรจาใหม่อีกครั้งพร้อม not_counted: true — บันทึกการเจรจาไว้เป็นประวัติ ไม่นับเป็นการทวงถามของวันนี้",
                           "how_en": "Send the renegotiation again as not counted — it is kept as history and does not count as today's contact"},
                          {"code": "INBOUND_NOT_COUNTED",
                           "label_th": errors.CONTACT_LOCKED_ALTERNATIVES["INBOUND_NOT_COUNTED"]}],
            locked_by=lock.officer if lock else None,
            locked_at=str(lock.taken_at) if lock else None,
            result=lock.result if lock else None,
            lock_id=exc.blocked_by_lock_id,
            override_allowed=role in ("MANAGER", "OWNER"))


# --- reviews -------------------------------------------------------------------------

@router.post("/v1/cases/by-customer/{customer_uid}/review-requests", status_code=201)
def request_review(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    audit.describe(act="REVIEW_REQUESTED", subject=("customer", customer_uid))
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    try:
        review = cases_domain.request_review(cs, case, body.get("reason"), body.get("question", ""), by=who(body, x_volt_officer),
                                             question_th=body.get("question_th"))
    except CaseError as exc:
        raise problem_from(exc)
    except dictionaries.DictionaryError as exc:
        raise dictionary_problem(exc)
    return {"review": review, "case": case}


@router.get("/v1/reviews")
def list_reviews(status: str = Query(default=None), x_volt_role: str = Header(default="OFFICER")):
    cs = cases_domain.for_current()
    rows = list(cs.reviews.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["status"] != "OPEN", r["raised_at"]))
    d = dictionaries.for_current()
    bd = settings.business_date
    role = role_of(x_volt_role)
    for r in rows:
        r["reason_label"] = d.label("REVIEW_REASON", r["reason"])
        r["reason_label_en"] = d.label("REVIEW_REASON", r["reason"], "en")
        customer = journey.customer_by_uid(r["customer_uid"])
        r["display_name"] = customer.display_name if customer else None
        r["volt_id"] = getattr(customer, "volt_id", None) if customer else None
        r["age_hours"] = _review_age_hours(r, bd)
        # Delta-100 D2g / prototype 530-539 (R1): the side card's arrears and DPD
        # joined from the same customer aggregate every case screen reads. A review
        # whose customer is not in the book serves None, never a made-up figure.
        case = cs.cases.get(r["customer_uid"])
        aggregate = _customer_money(customer) if customer is not None else None
        if aggregate is None:
            r["aggregate_overdue"], r["aggregate_outstanding"] = None, None
            r["oldest_dpd"], r["aging_bucket"], r["band_set_code"] = None, None, None
        else:
            total, oldest, band, outstanding = aggregate
            r["aggregate_overdue"], r["aggregate_outstanding"] = str(total), str(outstanding)
            r["oldest_dpd"], r["aging_bucket"], r["band_set_code"] = oldest, band.code, band.band_set_code
        # Delta-100 D2a: the same 0..100 score the record and the pipeline serve.
        r["risk_score"] = _record_risk(customer, case, bd, aggregate)
        # Round-4 J4-32: the supervisor reading this can see whether it was the third
        # failure to reach the customer or the first.
        r["unreachable_run"] = cases_domain.unreachable_run(cs, r["customer_uid"])
        # Prototype 519-529: the work panel's evidence list. Every fact is read off
        # records that already exist — the case's own contact log, the counts the
        # review snapshotted, and the requester's reason and note. A case with no
        # contact log serves an empty list, never an invented row.
        r["evidence"] = _review_evidence(cs, r, d)
        r["sla_breached"] = r["status"] == "OPEN" and (r["age_hours"] or 0) > settings.review_sla_hours
        # Delta-100 R4/R12: the row's own age in whole days, and the per-request need
        # sentence derived from the state/SLA/reason just computed.
        r["age_days"] = (r["age_hours"] // 24) if r["age_hours"] is not None else None
        r["need_basis"], r["need_th"], r["need_en"] = _review_need(r)
        # Round-3 J3-06: a cut-off card offers only อนุมัติ / ปฏิเสธ, and only to the approver.
        if r["reason"] == "POWER_CUTOFF_ASK":
            approver = settings.power_restriction_approver
            r["approver_role"] = approver
            r["approver_role_label_th"] = cases_domain.ROLE_LABEL_TH.get(approver, approver)
            r["approver_role_label_en"] = _ROLE_EN.get(approver, approver)
            r["decisions"] = [x for x in d.list("REVIEW_DECISION") if x["code"] in cases_domain.POWER_DECISIONS] \
                if role in (approver, "OWNER") else []
            r["decision_note_th"] = "คำขอตัดระบบไฟตัดสินโดย%s เท่านั้น" % cases_domain.ROLE_LABEL_TH.get(approver, approver)
            r["decision_note_en"] = "Only the %s decides a power cut-off request" % _ROLE_EN.get(approver, approver)
        else:
            r["approver_role"] = None
            r["decisions"] = [x for x in d.list("REVIEW_DECISION") if x["code"] not in cases_domain.POWER_DECISIONS]
            r["decision_note_th"] = None
            r["decision_note_en"] = None
    decisions = d.list("REVIEW_DECISION")
    if role != settings.power_restriction_approver and role != "OWNER":
        decisions = [x for x in decisions if x["code"] not in cases_domain.POWER_DECISIONS]
    return {"reviews": rows, "meta": {"open": sum(1 for r in rows if r["status"] == "OPEN"),
                                      "decisions": decisions, "reasons": d.list("REVIEW_REASON"),
                                      "npl_types": d.list("NPL_TYPE"),
                                      "sla_hours": settings.review_sla_hours, "business_date": str(bd),
                                      "power_approver": settings.power_restriction_approver,
                                      # Delta-100 D2g / R5: the list's money figure is the
                                      # customer's arrears; the API serves the raw amount and
                                      # the screen sorts. The stored order (open first, oldest
                                      # first) is unchanged — the SLA runs from the oldest.
                                      "row_sort_key": "aggregate_overdue",
                                      "row_sort_note_th": "ตัวเลขดิบต่อแถวคือ aggregate_overdue (ยอดค้าง) — หน้าจอเรียงเองได้ ส่วนลำดับที่ระบบส่งยังเป็นเปิดก่อน-เก่าก่อนเพราะ SLA นับจากรายการที่เก่าสุด",
                                      "row_sort_note_en": "The row's raw money figure is aggregate_overdue; the screen sorts. The served order stays open-first, oldest-first because the SLA runs from the oldest"}}


def _customer_money(customer):
    """The one aggregate every screen reads (main._customer_aggregate): arrears,
    worst DPD, band, outstanding. Imported inside the call because main.py imports
    this router's app at module load."""
    from .. import main as main_module
    return main_module._customer_aggregate(customer)


def _record_risk(customer, case, bd, aggregate=None):
    """Delta-100 D2a: the 0..100 risk score from app.risk, fed by the customer
    aggregate and the case's own promise/contact record. Unknown history counts as
    stale (risk.score's own rule), exactly as on the record."""
    from .. import risk
    if customer is None:
        return None
    arrears, dpd, _band, outstanding = aggregate or _customer_money(customer)
    last = (case or {}).get("last_contact_at")
    days_since = None
    if last:
        try:
            days_since = max(0, (bd - date.fromisoformat(str(last)[:10])).days)
        except (TypeError, ValueError):
            days_since = None
    return risk.score(dpd=dpd, arrears=arrears, outstanding=outstanding,
                      broken_ptps=(case or {}).get("broken_ptp_count") or 0,
                      days_since_contact=days_since)


# The per-request need sentence (prototype 500 / R12). Prototype Thai verbatim where
# the prototype has the sentence; the answered twin is this API's own, for a review
# the prototype never shows. Twins are written, never composed then translated.
_REVIEW_NEED = {
    "ANSWERED": ("ตอบแล้ว — ไม่มีงานค้าง", "Answered — nothing is waiting"),
    "POWER_CUTOFF_ASK": ("O&M รอคำสั่ง", "O&M is waiting on the order"),
    "SLA_BREACHED": ("ตัดสินภายในวันนี้", "Decide today"),
    "BOARD_MOVE_ASK": ("อ่านเหตุผลก่อนตัดสิน", "Read the reason before deciding"),
    "OPEN": ("ตัดสินภายใน 2 วันทำการ", "Decide within 2 business days"),
}


def _review_need(review):
    """Derived from the review's own state, SLA and reason. A cut-off request is
    waiting on O&M before the SLA clock means anything; a breached SLA asks for
    today; a board move asks for the reason first; the rest get the two-day rule."""
    if review["status"] != "OPEN":
        basis = "ANSWERED"
    elif review["reason"] == "POWER_CUTOFF_ASK":
        basis = "POWER_CUTOFF_ASK"
    elif review["sla_breached"]:
        basis = "SLA_BREACHED"
    elif review["reason"] == "BOARD_MOVE_ASK":
        basis = "BOARD_MOVE_ASK"
    else:
        basis = "OPEN"
    th, en = _REVIEW_NEED[basis]
    return basis, th, en


def _review_age_hours(review, bd):
    """Judge J-15: never negative. The clock runs from `raised_at_time` (business date +
    wall clock at the moment of raising) to the business date + wall clock now; a row
    without that stamp counts whole days from `raised_at`, floored at zero."""
    now = clock.peek(bd)                     # J3-19: one clock, and it never runs backwards
    try:
        raised = datetime.fromisoformat(review["raised_at_time"]) if review.get("raised_at_time") else None
    except (TypeError, ValueError):
        raised = None
    if raised is not None:
        return max(0, int((now - raised).total_seconds() // 3600))
    try:
        return max(0, (bd - date.fromisoformat(review["raised_at"][:10])).days * 24)
    except (TypeError, ValueError):
        return None


EVIDENCE_CONTACTS = 3


def _review_evidence(state, review, d):
    """The evidence panel's facts (prototype 519-529), each one already on record.

    `last_contacts` is the case's own append-only contact log, the newest
    EVIDENCE_CONTACTS rows, newest first, narrowed to small explicit fields the panel
    can print. The promise counts ride the review's snapshot; the reason and the note
    are the requester's own words. Nothing is synthesised for a review whose case has
    no contacts — the list is simply empty and the screen says so.
    """
    rows = [c for c in state.contact_log if c["customer_uid"] == review["customer_uid"]]
    last_contacts = [{
        "uid": c.get("uid"),
        "occurred_at": c.get("occurred_at"),
        "officer_uid": c.get("officer_uid"),
        "channel": c.get("channel"),
        "direction": c.get("direction"),
        "result": c.get("result"),
        "result_label_th": d.label("CONTACT_RESULT", c.get("result")),
        "result_label_en": d.label("CONTACT_RESULT", c.get("result"), "en"),
        "note": c.get("note"),
        "kind": c.get("kind"),
        "counted": bool(c.get("counted")),
    } for c in reversed(rows[-EVIDENCE_CONTACTS:])]
    snap = review.get("snapshot") or {}
    return {
        "last_contacts": last_contacts,
        "kept_ptp_count": snap.get("kept_ptp_count"),
        "broken_ptp_count": snap.get("broken_ptp_count"),
        "reason": review.get("reason"),
        "reason_label_th": review.get("reason_label"),
        "reason_label_en": review.get("reason_label_en"),
        "note_th": review.get("question_th"),
        "note_en": review.get("question_en"),
    }


@router.post("/v1/reviews/{uid}:answer")
def answer_review(uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    audit.describe(act="REVIEW_ANSWERED", subject=("review", uid), detail={"decision": (body or {}).get("decision")})
    cs = cases_domain.for_current()
    try:
        by, by_role = signer(body, x_volt_officer, x_volt_role, "manager")   # S2-04
        review = cases_domain.answer_review(cs, uid, body.get("decision"), body.get("comment", ""),
                                            by=by, role=role_of(x_volt_role),
                                            npl_type=body.get("npl_type"), by_role=by_role,
                                            # Round-4 J4-16: the answer may name the case's next step.
                                            next_action=body.get("next_action"),
                                            next_action_on=body.get("next_action_on"))
    except CaseError as exc:
        raise problem_from(exc)
    except dictionaries.DictionaryError as exc:
        raise dictionary_problem(exc)
    return {"review": review, "case": cs.cases[review["customer_uid"]]}


# --- service issues (ticket) and power ---------------------------------------------

@router.post("/v1/case-issues/{uid}:close")
def close_case_issue(uid: str, body: dict = Body(default={}), x_volt_officer: str = Header(default=None)):
    audit.describe(act="ISSUE_CLOSED", subject=("issue", uid))
    cs = cases_domain.for_current()
    issue = cs.issues.get(uid)
    if issue is None:
        raise errors.not_found("issue")
    case = cs.cases[issue["customer_uid"]]
    try:
        # J-13: the officer may close, but says how it was resolved; closed_by is the header identity.
        cases_domain.close_issue(cs, case, uid, by=who(body, x_volt_officer, "cx"), note=body.get("note"),
                                 resolution_note=body.get("resolution_note"))
    except CaseError as exc:
        raise problem_from(exc)
    return {"issue": issue, "case": case}


@router.post("/v1/cases/by-customer/{customer_uid}/power-restriction", status_code=201)
def request_power(customer_uid: str, body: dict = Body(default={}), x_volt_officer: str = Header(default=None)):
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    customer = journey.customer_by_uid(customer_uid)
    missed = max((journey.missed_count(k) for k in customer.contracts), default=0)
    try:
        rec = cases_domain.request_power(cs, case, by=who(body, x_volt_officer), missed_count=missed,
                                         reason=body.get("reason"))   # J-48
    except CaseError as exc:
        raise problem_from(exc)
    return {"power": rec, "case": case}


@router.post("/v1/power-restrictions/{uid}:{act}")
def power_act(uid: str, act: str, body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    cs = cases_domain.for_current()
    rec = cs.power.get(uid)
    if rec is None:
        raise errors.not_found("power_restriction")
    case = cs.cases[rec["customer_uid"]]
    try:
        if act == "approve":
            by, by_role = signer(body, x_volt_officer, x_volt_role, "owner")   # S2-04
            cases_domain.approve_power(cs, case, by=by, role=role_of(x_volt_role), by_role=by_role)
        elif act == "execute":
            cases_domain.execute_power(cs, case, by=who(body, x_volt_officer, "om"),
                                       notified_om=body.get("notified_om", True), role=role_of(x_volt_role))
        elif act == "reject":
            by, by_role = signer(body, x_volt_officer, x_volt_role, "owner")   # J3-06
            cases_domain.reject_power(cs, case, by=by, role=role_of(x_volt_role),
                                      reason=body.get("reason") or body.get("comment"), by_role=by_role)
        elif act == "restore":
            cases_domain.restore_power(cs, case, by=who(body, x_volt_officer, "om", role=x_volt_role), role=role_of(x_volt_role))
        else:
            raise errors.not_found("act")
    except CaseError as exc:
        raise problem_from(exc)
    return {"power": rec, "case": case}


@router.get("/v1/power-restrictions")
def list_power():
    cs = cases_domain.for_current()
    return {"power_restrictions": list(cs.power.values())}


def _case_peak_documents(customer_uid, contract_uids, jstate):
    """Every PEAK document raised for this customer, however it was raised."""
    from .. import peak_documents as pkd
    own = set()
    for inv in jstate.invoices.values():
        if inv["contract_uid"] in contract_uids:
            own.add(inv["uid"])
    for rcp in jstate.receipts.values():
        if rcp["contract_uid"] in contract_uids:
            own.add(rcp["uid"])
    rows = []
    for record in pkd.for_current().documents.values():
        if record.get("customer_uid") == customer_uid or record.get("source_ref") in own:
            rows.append(pkd.annotate(record))
    rows.sort(key=lambda r: r["uid"])
    return rows


# --- feedback round 2 / Q7 (TASK-210): pairing from the case side -------------------

@router.get("/v1/cases/by-customer/{customer_uid}/peak-codes")
def case_peak_codes(customer_uid: str, q: str = Query(default=None)):
    """The PEAK contact codes the last applied invoice run carries, searched from the
    case page. A code linked to another customer is shown with `linked_to`, never
    hidden — a person can see why it cannot be linked."""
    from sqlalchemy import text
    from .. import db
    from ..pipelines import peak_match, peak_links, peak_writer
    if not db.configured():
        return {"codes": [], "meta": {"total": 0, "database": False}}
    needle = (q or "").strip()
    if len(needle) < 2:
        return {"codes": [], "meta": {"total": 0, "min_chars": 2}}
    _case_or_404(cases_domain.for_current(), customer_uid)
    conn = db.connect()
    try:
        run = peak_writer.last_run(conn, applied=True)
        if run is None:
            return {"codes": [], "meta": {"total": 0}}
        rows = conn.execute(text(
            "select contact_code, customer_name, count(*) as invoices, max(due_on) as last_due_on "
            "from landing.peak_invoice where import_run_id = :r and contact_code is not null "
            "and (contact_code ilike :q or customer_name ilike :q) "
            "group by contact_code, customer_name order by invoices desc, contact_code limit 10"),
            {"r": run["id"], "q": "%" + needle + "%"}).mappings().all()
        links = peak_links.load(conn)
    finally:
        conn.close()
    out = []
    for row in rows:
        code = row["contact_code"]
        link = links.get(peak_match.normalise_code(code)) or links.get(code)
        out.append({"contact_code": code, "customer_name": row["customer_name"],
                    "invoices": row["invoices"], "last_due_on": _iso_or(row["last_due_on"]),
                    "linked_to": (link or {}).get("customer_no")})
    return {"codes": out, "meta": {"total": len(out)}}


def _iso_or(value):
    return str(value)[:10] if value else None


@router.post("/v1/cases/by-customer/{customer_uid}/peak-link", status_code=201)
def link_case_peak_code(customer_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
                        x_volt_officer: str = Header(default=None)):
    """Bind a PEAK contact code to this case's customer; the served book reloads at
    once so the invoices appear on the case (TASK-210). OFFICER and above."""
    from .. import db
    from ..pipelines import peak_links
    from .peak_pipeline import _served, _write_tx
    from .pipelines import _require_db
    audit.describe(act="PEAK_LINK_CONFIRMED", subject=("customer", customer_uid),
                   detail={"contact_code": (body or {}).get("contact_code")})
    case = _case_or_404(cases_domain.for_current(), customer_uid)
    code = str((body or {}).get("contact_code") or "").strip()
    if not code:
        raise errors.validation_failed([{"pointer": "/contact_code", "code": "required",
                                         "message": "contact_code is required",
                                         "message_th": "ต้องระบุรหัสผู้ติดต่อ PEAK"}])
    _require_db()
    by = who(body, x_volt_officer)
    conn = db.connect()
    try:
        with _write_tx(conn):
            link = peak_links.confirm(conn, code, case["customer_no"], by=by,
                                      reason=(body or {}).get("reason"), rule="PERSON_CASE")
    finally:
        conn.close()
    return _served({"link": link, "customer_uid": customer_uid}, "peak-link")
