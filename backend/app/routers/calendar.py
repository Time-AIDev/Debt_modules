"""The calendar — vault note 10 §3 WP6, ruling F16.

GET /v1/calendar serves one dated list from the stores that already hold dates
(calendar_feed.py names the store on every item). The screen reads it, moves a next
action with a reason (C2c), and keeps personal notices (C2b). No recurrence, no
sharing, no e-mail.

GET /v1/calendar itself is read-only: reading dated work is not an act, the same as
GET /v1/today, so that route is not audited. The routes below ARE acts — each is
audited (NOTICE_CREATED / NOTICE_UPDATED / NOTICE_DELETED / NEXT_ACTION_MOVED), never
with the notice's own words or a phone number typed into a reason (fix round 1 / M5:
this docstring used to say nothing here is audited, which stopped being true the
moment those routes were added; C2c added the fourth).
"""
import re
from datetime import date

from fastapi import APIRouter, Body, Header, Query

from .. import audit, calendar_feed, cases as cases_domain, db, dictionaries, errors, journey, notices, officers, today as today_domain
from ..cases import CaseError
from ..config import settings
from ..customer_contact import _without_numbers
from . import today as today_router

router = APIRouter()


def _date_param(raw, pointer):
    try:
        if len(raw) != 10:
            raise ValueError(raw)
        return date.fromisoformat(raw)
    except ValueError:
        raise errors.validation_failed([{
            "pointer": pointer, "code": "date_invalid",
            "message": "%s must be a date (yyyy-mm-dd); got %r" % (pointer[1:], raw),
            "message_th": "วันที่ไม่ถูกต้อง ใช้รูปแบบ ปี-เดือน-วัน"}])


def _range(start_raw, end_raw, bd):
    """Both or neither. Neither is the six-week grid around the business date, and the
    answer says so (meta.defaulted) — never a silent choice."""
    if start_raw is None and end_raw is None:
        start, end = calendar_feed.default_range(bd)
        return start, end, True
    missing = [pointer for pointer, value in (("/from", start_raw), ("/to", end_raw)) if value is None]
    if missing:
        raise errors.validation_failed([{
            "pointer": pointer, "code": "required",
            "message": "from and to are given together, or neither",
            "message_th": "ต้องระบุวันเริ่ม (from) และวันสิ้นสุด (to) คู่กัน หรือไม่ระบุทั้งคู่"} for pointer in missing])
    start, end = _date_param(start_raw, "/from"), _date_param(end_raw, "/to")
    if end < start:
        raise errors.validation_failed([{
            "pointer": "/to", "code": "range_reversed",
            "message": "to (%s) is before from (%s)" % (end, start),
            "message_th": "วันสิ้นสุดอยู่ก่อนวันเริ่ม"}])
    span = (end - start).days + 1
    if span > calendar_feed.MAX_SPAN_DAYS:
        raise errors.validation_failed([{
            "pointer": "/to", "code": "range_too_long", "max_days": calendar_feed.MAX_SPAN_DAYS,
            "message": "the range is %d days; the calendar serves at most %d" % (span, calendar_feed.MAX_SPAN_DAYS),
            "message_th": "ช่วงวันที่ยาว %d วัน เกินที่ปฏิทินแสดงได้ (%d วัน)" % (span, calendar_feed.MAX_SPAN_DAYS)}])
    return start, end, False


def _officer(raw, cs, acting_header):
    """F9 (controller ruling): validated against Task B2a's known_officers(cs, acting=x)
    — registry ∪ case-assigned uids ∪ the acting identity — NOT officers.registry()
    alone, so an officer given work through assignment is filterable here exactly as
    on Today (routers/today.py's own `_valid_choice("officer", ...)` call)."""
    if not raw:
        return None
    known = today_domain.known_officers(cs, acting=(acting_header or "").strip() or None)
    if raw not in known:
        raise errors.validation_failed([{
            "pointer": "/officer", "code": "value_unknown", "known": sorted(known),
            "message": "officer %r is not known" % raw,
            "message_th": "ไม่รู้จักเจ้าหน้าที่ที่ระบุ"}])
    return raw


@router.get("/v1/calendar")
def calendar_view(start: str = Query(default=None, alias="from"), end: str = Query(default=None, alias="to"),
                  officer: str = Query(default=None), x_volt_officer: str = Header(default=None)):
    bd = settings.business_date
    start_d, end_d, defaulted = _range(start or None, end or None, bd)
    cs = cases_domain.for_current()
    officer = _officer(officer, cs, x_volt_officer)
    cases_domain.detect_broken_ptps(cs, bd)          # the same first step GET /v1/today takes
    js = journey.for_current()
    reminders = today_router.reminders(days=(end_d - bd).days, officer=officer)
    # cs.ptps and cs.issues each hold two jobs (an item list plus a count another
    # serializer needs), so each is walked once: case_ptps also collects the JOURNEY-
    # sourced dates journey_ptps skips, and case_issues also counts the undated ones
    # not_dated reports (fold-in, C2b).
    case_ptp_items, mirrored = calendar_feed.case_ptps(cs, start_d, end_d, bd)
    journey_ptp_items, skipped = calendar_feed.journey_ptps(js, cs, start_d, end_d, bd, mirrored)
    case_issue_items, cases_undated = calendar_feed.case_issues(cs, start_d, end_d, bd)
    # F16: a notice is its owner's alone — X-Volt-Officer, which the login middleware
    # rewrites to the session's own identity when AUTH_MODE is on. No header, no notices.
    owner = (x_volt_officer or "").strip() or None
    notice_rows = notices.list_for(owner, start_d, end_d)
    items = (calendar_feed.next_actions(cs, start_d, end_d, bd)
             + case_ptp_items
             + journey_ptp_items
             + calendar_feed.reminder_batches(reminders["reminders"], start_d, end_d, bd,
                                              reminders["meta"].get("batch_label"))
             + calendar_feed.case_reviews(cs, start_d, end_d, bd)
             + calendar_feed.journey_reviews(js, cs, start_d, end_d, bd)
             + case_issue_items
             + calendar_feed.restructures(js, cs, start_d, end_d, bd)
             + calendar_feed.settlements(js, cs, start_d, end_d, bd)
             + calendar_feed.npl_buybacks(js, cs, start_d, end_d, bd)
             + calendar_feed.notices(notice_rows, cs, bd))
    if officer:
        items = [row for row in items if row["kind"] in calendar_feed.UNSCOPED_KINDS or row["officer_uid"] == officer]
    items = calendar_feed.ordered(items)
    return {
        "items": items,
        "days": calendar_feed.day_totals(items, start_d, end_d),
        "meta": {
            "from": start_d.isoformat(), "to": end_d.isoformat(), "defaulted": defaulted,
            "business_date": str(bd), "max_span_days": calendar_feed.MAX_SPAN_DAYS,
            "officer": officer, "total": len(items),
            "by_kind": calendar_feed.count_by(items, "kind"),
            # F07 / feedback-r2 TASK-103: the served urgency order the legend reads —
            # the same order `ordered` sorts a day by. PTP first.
            "kind_order": list(calendar_feed.KINDS),
            # 2026-09-21: the year view's 12-month summary — every month in the range,
            # zero-filled, so the screen renders what it is served and computes nothing.
            "by_month": calendar_feed.count_by_month(items, start_d, end_d),
            "by_source": calendar_feed.count_by(items, "source"),
            "officers": [{"uid": row["uid"], "display_name_th": row["display_name_th"],
                          "display_name_en": row.get("display_name_en")}
                         for row in officers.registry() if row["role"] == "OFFICER"],
            "not_dated": calendar_feed.not_dated(cases_undated, js),
            "journey_ptps_mirrored": skipped,
            "next_action_excluded": list(calendar_feed.NEXT_ACTION_EXCLUDED),
            "review_sla_hours": settings.review_sla_hours,
            # The header strip's reminder cell prints the batch's own label and, when
            # the configured offsets and the SOP still disagree, that open conflict.
            # This is the meta of the SAME today.reminders call the item list above
            # already built (line 93) — never a second computation or a re-derived
            # label (J3-13: batch_label is authoritative).
            "reminders": {
                "batch_label": reminders["meta"].get("batch_label"),
                "offsets": reminders["meta"].get("offsets"),
                "offsets_conflict": reminders["meta"].get("offsets_conflict"),
                "note_th": reminders["meta"].get("note_th"),
                "note_en": reminders["meta"].get("note_en"),
            },
            "notices": {"owner": owner, "scope": "OWNER_ONLY", "durable": db.configured(),
                        "total": len(notice_rows)},
        },
    }


# --- personal notices (F16) ---------------------------------------------------------

def _owner(header):
    owner = (header or "").strip()
    if not owner:
        raise errors.Problem(code="owner_required", status=422, title="A notice needs an owner",
                             detail="X-Volt-Officer names the person a notice belongs to; it was empty",
                             message_th="ไม่ทราบว่าโน้ตนี้เป็นของใคร — เลือกชื่อผู้ใช้งานก่อน",
                             error_id="DEBT-CAL-0422")
    return owner


def _clean(body, partial):
    try:
        fields = notices.clean(body, partial)
    except notices.NoticeRefused as exc:
        raise errors.validation_failed([exc.error()])
    if partial and not fields:
        raise errors.validation_failed([{"pointer": "", "code": "nothing_to_change",
                                         "message": "the body changes nothing", "message_th": "ไม่มีข้อมูลที่เปลี่ยน"}])
    return fields


def _shaped(uid):
    """Fix round 1 / M3: a uid that does not even look like one this module could have
    generated is never a real notice, so it is refused BEFORE `audit.describe` — a
    malformed path segment (someone's phone number, typed into the URL by mistake or
    on purpose) must never be written into the append-only audit log as subject_uid.
    A well-formed but unknown uid still reaches the store and is audited as before."""
    if not notices.looks_like_uid(uid):
        raise errors.not_found("notice")
    return uid


@router.post("/v1/calendar/notices", status_code=201)
def create_notice(body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    owner = _owner(x_volt_officer)
    fields = _clean(body, partial=False)
    uid = notices.new_uid()
    # Audited before the write that can raise; never the title or the text.
    audit.describe(act="NOTICE_CREATED", subject=("notice", uid),
                   detail={"on": fields["on"], "customer_uid": fields.get("customer_uid"), "durable": db.configured()})
    return {"notice": notices.create(owner, fields, uid)}


@router.put("/v1/calendar/notices/{uid}")
def update_notice(uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    owner = _owner(x_volt_officer)
    uid = _shaped(uid)                # M3: refused, unaudited, before the uid is quoted anywhere
    fields = _clean(body, partial=True)
    detail = {"fields": sorted(fields)}
    if "done" in fields:
        detail["done"] = fields["done"]
    audit.describe(act="NOTICE_UPDATED", subject=("notice", uid), detail=detail)
    notice = notices.update(owner, uid, fields)
    if notice is None:
        raise errors.not_found("notice")        # someone else's is "not found" too — never leaked
    return {"notice": notice}


@router.delete("/v1/calendar/notices/{uid}")
def delete_notice(uid: str, x_volt_officer: str = Header(default=None)):
    owner = _owner(x_volt_officer)
    uid = _shaped(uid)                # M3: refused, unaudited, before the uid is quoted anywhere
    audit.describe(act="NOTICE_DELETED", subject=("notice", uid))
    notice = notices.delete(owner, uid)
    if notice is None:
        raise errors.not_found("notice")
    return {"notice": notice}


# --- moving a next action (F16) -----------------------------------------------------

# B6/C2b rulings, applied up front here rather than repeated: a NUL or a lone
# surrogate (U+D800-U+DFFF — what a string cut mid-emoji decodes to from JSON, since
# json.loads does not require surrogates to pair) in ANY string field of the body is
# refused with 422 text_invalid before audit.describe or set_next_action ever see it.
# Not a literal string, so \x00 and \ud800-\udfff are Python escapes decoded once
# here, the same DANGEROUS_RE every other write route in this file (customer_contact.py,
# notices.py) already carries.
_DANGEROUS_RE = re.compile("[\x00\ud800-\udfff]")
TEXT_INVALID_TH = "มีอักขระที่บันทึกไม่ได้ในช่องนี้"


def _field_pointer(key):
    """RFC 6901, matching this module's own _pointer-shaped escaping elsewhere in the
    codebase (notices.py): '~' before '/', so a key carrying either is never misread
    as a path separator."""
    return "/" + str(key).replace("~", "~0").replace("/", "~1")


def _refuse_dangerous(body):
    """Every string value the body carries — reason and on named first for a
    deterministic pointer when more than one is bad, then any other field in a
    stable order — is checked before anything else runs."""
    ordered = [k for k in ("reason", "on", "by") if k in body]
    ordered += [k for k in sorted(body) if k not in ("reason", "on", "by")]
    for key in ordered:
        value = body.get(key)
        if isinstance(value, str) and _DANGEROUS_RE.search(value):
            raise errors.validation_failed([{
                "pointer": _field_pointer(key), "code": "text_invalid",
                "message": "this field carries a character that cannot be stored",
                "message_th": TEXT_INVALID_TH}])


@router.post("/v1/calendar/next-actions/{customer_uid}:move")
def move_next_action(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """A next action moved to another day, with a reason, through cases.set_next_action —
    the function, the checks and the NEXT_ACTION_SET event every next-action write uses,
    so each refusal it makes (a blank action, a bad date, AWAIT_REVIEW with no review) is
    this route's refusal too. Only the day changes; the action code stays what it was.

    C2c rulings: the case is resolved first (_case_or_404), so an arbitrary or unknown
    customer_uid path segment never reaches audit.describe as subject_uid — a 404 on
    it is refused before any audit row names it, the uid this route then describes
    with is the case's own resolved customer_uid, the same shape M3 gives notices'
    uid. `reason` and `on` are refused (never coerced with str()) when they are not
    real, non-blank strings. F18: a phone number or 13-digit id typed into the reason
    is cut out via customer_contact._without_numbers before it reaches EITHER the
    audit detail or the case's own trail (next_action_note, the NEXT_ACTION_SET
    event) — the same redacted copy goes to both, so scrubbing the audit log while
    leaving the number sitting in the case (and in this very response's `case`
    object) would not have been a fix at all.

    Fix round 1: audit.describe now runs before the same-day (next_action_unchanged)
    check too, not only before set_next_action — a same-day move is a refusal about
    the case's OWN current state, not a store read, but it is still a refusal, and it
    must still name what was asked. Mirrors customer_contact.py's own M7 ordering for
    `phone_unchanged`: describe runs before the FIRST thing that can conclude a
    refusal, not only before the write.
    """
    cs = cases_domain.for_current()
    case = today_router._case_or_404(cs, customer_uid)
    _refuse_dangerous(body)
    reason_raw = body.get("reason")
    to_raw = body.get("on")
    problems = []
    if not isinstance(reason_raw, str) or not reason_raw.strip():
        problems.append({"pointer": "/reason", "code": "reason_required",
                         "message": "moving a next action needs a reason",
                         "message_th": "ต้องระบุเหตุผลที่ย้ายวัน"})
    if not isinstance(to_raw, str) or not to_raw.strip():
        problems.append({"pointer": "/on", "code": "required",
                         "message": "on names the day to move to",
                         "message_th": "ต้องระบุวันที่จะย้ายไป"})
    if problems:
        raise errors.validation_failed(problems)
    reason = _without_numbers(reason_raw.strip())
    from_on = case.get("next_action_on")
    # Described before ANYTHING that can raise a refusal, including the same-day
    # check right below — not only before set_next_action (fix round 1). The reason
    # in the detail is the redacted copy — never the raw digits.
    audit.describe(act="NEXT_ACTION_MOVED", subject=("customer", case["customer_uid"]),
                   detail={"action": case.get("next_action"), "from": from_on, "to": to_raw[:10],
                           "reason": reason})
    if to_raw[:10] == from_on:
        raise errors.Problem(code="next_action_unchanged", status=409,
                             title="The next action is already on that day",
                             detail="%s is already due on %s" % (case.get("next_action"), from_on),
                             message_th="งานถัดไปอยู่วันนี้อยู่แล้ว", error_id="DEBT-CAL-0409")
    try:
        cases_domain.set_next_action(cs, case, case.get("next_action"), to_raw,
                                     by=today_router.who(body, x_volt_officer), note=reason)
    except CaseError as exc:
        raise today_router.problem_from(exc)
    except dictionaries.DictionaryError as exc:
        raise today_router.dictionary_problem(exc)
    case["next_action_moved_from"] = from_on      # PR 9: the calendar shows where it came from
    return {"case": case, "moved": {"action": case["next_action"], "from": from_on, "to": case["next_action_on"]}}
