"""Reports — API Surface v2.3 §9."""
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Body, Header, Query
from fastapi.responses import Response

from .. import audit, cases as cases_domain, collection_kpi, errors, monthly_history, reports, team_performance, weekly_export, xlsx_writer
from .. import officers as officer_registry   # the GET /v1/reports/officers handler shadows the module name

router = APIRouter()

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/v1/reports/weekly")
def weekly():
    # The edition block rides beside the report, not inside it: `reports.weekly()` is
    # also what a snapshot and an edition freeze, and a stored copy must never carry
    # a "DRAFT" stamp that was only true at the moment it was taken.
    payload = reports.weekly()
    return {**payload, "edition": reports.edition_state(payload["period"]["label"])}


def _manager_only(x_volt_role, detail, th):
    if (x_volt_role or "").upper() not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail=detail,
                             message_th=th, error_id="DEBT-IAM-0403")


@router.post("/v1/reports/weekly:publish", status_code=201)
def publish_weekly(body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER"),
                   x_volt_officer: str = Header(default=None)):
    """Publish the live draft as the next edition of its week (Manager/Owner)."""
    _manager_only(x_volt_role, "A weekly edition is published by a Manager or the Owner",
                  "เฉพาะผู้จัดการหรือ Owner เผยแพร่รายงานประจำสัปดาห์ได้")
    by, by_role = officer_registry.sign(body or {}, x_volt_officer, x_volt_role, fallback="manager")
    # The act is named BEFORE the work, not after it (the house rule customer_contact.py:554
    # records: audit.describe runs before the first store read, field-shape refusals excepted).
    # publish_edition computes the whole weekly report and mutates the edition store; when it
    # raises, the row the middleware writes used to carry verb, route and actor but a blank
    # act — a reader of the log could not see that a publish was what failed.
    audit.describe(act="WEEKLY_EDITION_PUBLISHED")
    edition = reports.publish_edition(by, published_by_role=by_role)
    # The uid only exists once the edition does, so the subject is named on the way out.
    audit.describe(act="WEEKLY_EDITION_PUBLISHED", subject=("weekly_edition", edition["edition_uid"]),
                   detail={"period": edition["period"], "number": edition["number"]})
    return {"edition": edition}


def _edition_figures(edition, cs):
    """Delta-100 D2i: the figures the editions list shows beside each edition.

    The contacts count is read from cases.contact_log over the edition's OWN frozen
    period (the same store and date rule reports.officers() counts by), so a new
    edition and its period's rows cannot disagree; `counted_contacts` is the subset
    the counted flag marks. The kept/total PTP pair comes from the edition's frozen
    payload.promises (kept, kept+broken) — the same pair the Overview's team strip
    serves. The cash total comes from the frozen management_summary.cash_in.total.
    Every one of them is None, not 0, when the edition genuinely carries no figure
    (an edition frozen by an older payload, or an unreadable period) — and
    `cash_sort` is the numeric mirror of cash_total for a sort toggle to use, never
    a figure to print.
    """
    payload = edition.get("payload") or {}
    period = payload.get("period") or {}
    start, end = period.get("start"), period.get("end")
    contacts = counted = None
    if start and end:
        rows = [r for r in cs.contact_log
                if start <= str(r.get("occurred_at") or "")[:10] <= end]
        contacts = len(rows)
        counted = sum(1 for r in rows if r.get("counted"))
    promises = payload.get("promises") or {}
    kept, broken = promises.get("kept"), promises.get("broken")
    ptp_kept = kept if isinstance(kept, int) else None
    ptp_total = (kept + broken) if isinstance(kept, int) and isinstance(broken, int) else None
    cash = ((payload.get("management_summary") or {}).get("cash_in") or {}).get("total")
    try:
        cash_total = str(Decimal(str(cash)).quantize(Decimal("0.01"))) if cash not in (None, "") else None
    except (InvalidOperation, ValueError):
        cash_total = None          # a stored payload with a non-number total is no figure, not a crash
    return {
        **reports._edition_summary(edition),
        "contacts": contacts, "counted_contacts": counted,
        "ptp_kept": ptp_kept, "ptp_total": ptp_total,
        "cash_total": cash_total,
        "cash_sort": float(Decimal(cash_total)) if cash_total is not None else None,
    }


@router.get("/v1/reports/weekly/editions")
def weekly_editions():
    cs = cases_domain.for_current()
    rows = [_edition_figures(e, cs) for e in reports.editions()]
    return {"editions": rows, "meta": {"total": len(rows), "order": "newest first",
                                       "payload_note_th": "เปิดฉบับเต็มได้ที่ /v1/reports/weekly/editions/{edition_uid}"}}


@router.get("/v1/reports/weekly/editions/{edition_uid}")
def weekly_edition(edition_uid: str):
    edition = reports.edition(edition_uid)
    if edition is None:
        raise errors.not_found("edition")
    return {"edition": edition}


@router.post("/v1/reports/weekly:export")
def export_weekly(body: dict = Body(default={})):
    """The weekly report as .xlsx — the live draft, or one edition by `edition_uid`.

    A POST, not a GET, so every file that leaves is in the action log with who took it
    (the audit middleware logs every non-GET; ruling 74 closed the workbook's ungoverned
    GET export for the same reason). The report names customers in its NPL list."""
    body = body or {}
    # str() first: a non-string edition_uid (a number, a list, an object) used to reach
    # .strip() and 500 instead of taking the ordinary 404 refusal below.
    edition_uid = str(body.get("edition_uid") or "").strip() or None
    lang = "en" if body.get("lang") == "en" else "th"
    # Named before the report is computed, for the reason given in publish_weekly above.
    # Everything the body already settles goes in now; the period is known only after
    # the payload is, and describe merges detail, so it is added on the way out.
    audit.describe(act="WEEKLY_REPORT_EXPORTED",
                   subject=("weekly_edition", edition_uid) if edition_uid else None,
                   detail={"edition_uid": edition_uid, "format": "xlsx", "lang": lang})
    # Redesign v2 ruling R16: a report leaves only with a stated reason, kept in the log.
    reason = body.get("reason")
    reason = reason.strip()[:500] if isinstance(reason, str) else ""
    if not reason:
        raise errors.validation_failed([{
            "pointer": "/reason", "code": "required",
            "message": "Say why the report is being exported.",
            "message_th": "ต้องระบุเหตุผลในการส่งออกรายงาน"}])
    audit.describe(act="WEEKLY_REPORT_EXPORTED", detail={"reason": reason[:200]})
    if edition_uid:
        edition = reports.edition(edition_uid)
        if edition is None:
            raise errors.not_found("edition")
        payload = edition["payload"]
    else:
        edition, payload = None, reports.weekly()
    name = weekly_export.filename(payload, edition)
    audit.describe(act="WEEKLY_REPORT_EXPORTED",
                   subject=("weekly_edition", edition_uid) if edition_uid else ("weekly_report", payload["period"]["label"]),
                   detail={"period": payload["period"]["label"]})
    return Response(content=weekly_export.build(payload, edition, lang=lang), media_type=XLSX_MEDIA,
                    headers={"Content-Disposition": "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (name, quote(name))})


@router.get("/v1/reports/monthly")
def monthly(months: int = Query(default=12, ge=1, le=60)):
    """Monthly history (2026-09-25): per month, customers and money by payment status,
    NPL in/out against the month before and the change on it — from records.customer_month."""
    return {"months": monthly_history.report(months), "current_month": monthly_history.current_month()}


_MONTHLY_HEAD = ["VOLT ID", "เลขลูกค้า", "ผลิตภัณฑ์", "สถานะการชำระ", "ที่มาของสถานะ", "ยอดค้าง",
                 "ยอดคงเหลือ", "DPD", "Officer", "บันทึกเมื่อ"]


@router.post("/v1/reports/monthly:export")
def export_monthly(body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER")):
    """One month's history as .xlsx (Manager/Owner, with a stated reason, in the action
    log — the rows name customers). Sheet 1 per customer, sheet 2 by status."""
    body = body or {}
    month = str(body.get("month") or "").strip()
    audit.describe(act="MONTHLY_HISTORY_EXPORTED", subject=("monthly_history", month or None),
                   detail={"month": month, "format": "xlsx"})
    _manager_only(x_volt_role, "A month's history is exported by a Manager or the Owner",
                  "เฉพาะผู้จัดการหรือ Owner ส่งออกประวัติรายเดือนได้")
    try:
        collection_kpi.parse_month(month)
    except ValueError:
        raise errors.validation_failed([{"pointer": "/month", "code": "invalid",
                                         "message": "month is YYYY-MM", "message_th": "เดือนต้องเป็นรูปแบบ YYYY-MM"}])
    reason = body.get("reason")
    reason = reason.strip()[:500] if isinstance(reason, str) else ""
    if not reason:
        raise errors.validation_failed([{
            "pointer": "/reason", "code": "required",
            "message": "Say why the month is being exported.",
            "message_th": "ต้องระบุเหตุผลในการส่งออก"}])
    audit.describe(act="MONTHLY_HISTORY_EXPORTED", detail={"reason": reason[:200]})
    rows = monthly_history.month_rows(month)
    detail = [[xlsx_writer.Bold(h) for h in _MONTHLY_HEAD]] + [
        [r["volt_id"], r["customer_no"], r["product"], r["payment_status"], r["status_source"],
         r["overdue"], r["outstanding"], r["oldest_dpd"], r["officer"],
         r["taken_at"].strftime("%Y-%m-%d %H:%M") if r["taken_at"] else None] for r in rows]
    summary = [[xlsx_writer.Bold(h) for h in ("สถานะการชำระ", "จำนวนลูกค้า", "ยอดค้าง", "ยอดคงเหลือ")]]
    by = {}
    for r in rows:
        s = by.setdefault(r["payment_status"], [0, Decimal(0), Decimal(0)])
        s[0] += 1
        s[1] += r["overdue"] or 0
        s[2] += r["outstanding"] or 0
    summary += [[k, n, o, b] for k, (n, o, b) in sorted(by.items())]
    summary += [[xlsx_writer.Bold("รวม"), len(rows), sum((v[1] for v in by.values()), Decimal(0)),
                 sum((v[2] for v in by.values()), Decimal(0))]]
    name = "volt-monthly-history-%s.xlsx" % month
    content = xlsx_writer.workbook([{"name": "ลูกค้า %s" % month, "rows": detail},
                                    {"name": "สรุป %s" % month, "rows": summary}])
    return Response(content=content, media_type=XLSX_MEDIA,
                    headers={"Content-Disposition": "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (name, quote(name))})


@router.post("/v1/reports/weekly:snapshot", status_code=201)
def weekly_snapshot(body: dict = Body(default={}), x_volt_role: str = Header(default="OFFICER"),
                    x_volt_officer: str = Header(default=None)):
    """Judge J-52: freeze the weekly report as it stands (Manager/Owner)."""
    audit.describe(act="WEEKLY_SNAPSHOT_TAKEN")
    _manager_only(x_volt_role, "A weekly snapshot is taken by a Manager", "เฉพาะผู้จัดการบันทึกรายงานประจำสัปดาห์ได้")
    taken_by, by_role = officer_registry.sign(body or {}, x_volt_officer, x_volt_role, fallback="manager")   # S2-04
    # Round-4 J4-19: a person may name what they just froze.
    return {"snapshot": reports.take_snapshot(taken_by, taken_by_role=by_role, name=(body or {}).get("name"))}


@router.get("/v1/reports/weekly/snapshots")
def weekly_snapshots():
    rows = reports.snapshots()
    return {"snapshots": rows, "meta": {"total": len(rows), "order": "newest first",
                                        # J4-19: the stored report is on the wire; each row
                                        # can be opened on its own address.
                                        "payload_note_th": "แต่ละรายการเก็บรายงานฉบับเต็มไว้ใน payload เปิดดูได้ที่ /v1/reports/weekly/snapshots/{snapshot_uid}"}}


@router.get("/v1/reports/weekly/snapshots/{snapshot_uid}")
def weekly_snapshot(snapshot_uid: str):
    """Round-4 J4-19: the frozen report, opened by its own uid — the screen held the
    whole payload and rendered three fields of it into a bare list item."""
    snap = reports.snapshot(snapshot_uid)
    if snap is None:
        raise errors.not_found("snapshot")
    return {"snapshot": snap}


@router.post("/v1/reports/weekly/snapshots/{snapshot_uid}:rename")
def rename_weekly_snapshot(snapshot_uid: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="WEEKLY_SNAPSHOT_RENAMED", subject=("weekly_snapshot", snapshot_uid))
    _manager_only(x_volt_role, "A snapshot is named by a Manager", "เฉพาะผู้จัดการตั้งชื่อรายงานที่บันทึกไว้ได้")
    snap = reports.rename_snapshot(snapshot_uid, body.get("name"))
    if snap is None:
        raise errors.not_found("snapshot")
    return {"snapshot": {k: v for k, v in snap.items() if k != "payload"}}


@router.put("/v1/reports/weekly/{period}/targets")
def put_targets(period: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="WEEKLY_TARGETS_SET", subject=("weekly_period", period))
    if (x_volt_role or "").upper() not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only", detail="Targets are saved by a Manager",
                             message_th="เฉพาะผู้จัดการตั้งเป้าได้", error_id="DEBT-IAM-0403")
    reports.TARGETS[period] = {k: str(v) for k, v in body.items()}
    return {"period": period, "targets": reports.TARGETS[period]}


@router.put("/v1/reports/weekly/{period}/focus")
def put_focus(period: str, body: dict = Body(...)):
    audit.describe(act="WEEKLY_FOCUS_SET", subject=("weekly_period", period))
    reports.FOCUS[period] = body.get("text", "")
    return {"period": period, "next_week_focus": reports.FOCUS[period]}


@router.get("/v1/reports/officers")
def officers():
    rows = reports.officers()
    rec = reports.reconciliation()
    period = rows[0]["period"] if rows else None
    return {"officers": rows, "meta": {"unit": rec["unit_officers"], "total_caseload": sum(o["caseload"] for o in rows),
                                       # Round-3 J3-12: the period stamp now MEANS the period.
                                       "period": period,
                                       "period_scope": "IN_PERIOD",
                                       "period_basis": dict(reports.OFFICER_PERIOD_BASIS),
                                       "period_note_th": "คอลัมน์การติดต่อและนัดชำระ นับเฉพาะในช่วง %s เท่านั้น; คอลัมน์ที่ลงท้าย _all_time คือ \"ตลอดอายุ\"" % (period or "-"),
                                       "caseload_note_th": "จำนวนเคส/ค้างชำระ/NPL เป็นยอด ณ วันทำการ ไม่ใช่ยอดสะสมในช่วง",
                                       "reconciliation": rec}}


@router.get("/v1/reports/team")
def team():
    """Redesign v2 PR 8: the Overview's team performance — every signed role reads it."""
    return team_performance.build()


@router.get("/v1/reports/officers/{officer_uid}")
def officer_one(officer_uid: str):
    """F09 / feedback-r2 TASK-105: the same row `team()` serves for one officer, for
    the case overview's scoreboard. An unknown uid is a 404 named `officer`."""
    payload = team_performance.officer(officer_uid)
    if payload is None:
        raise errors.not_found("officer")
    return payload


# --- feedback round 2: the PTP report (F16, TASK-114/115) ---------------------------

def _ptp_statuses():
    from .. import journey
    return tuple(dict.fromkeys(cases_domain.PTP_STATUSES + journey.PTP_STATUSES))


def _iso_day(value, pointer):
    from datetime import date
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise errors.validation_failed([{
            "pointer": pointer, "code": "not_a_date",
            "message": "%s must be a YYYY-MM-DD date." % pointer,
            "message_th": "รูปแบบวันที่ไม่ถูกต้อง ใช้ YYYY-MM-DD"}])


def _business_month(bd):
    import calendar as _calendar
    return bd.replace(day=1), bd.replace(day=_calendar.monthrange(bd.year, bd.month)[1])


def _ptp_rows(start, end, officer=None, status=None):
    """The union the calendar feed already makes: the case store's promises and the
    journey store's, each filtered by its own promise_date, then officer and status.
    Nothing is recomputed — the row is the stored record with its customer named."""
    from .. import journey
    cs = cases_domain.for_current()
    js = journey.for_current()
    rows = []
    for source, store in (("case", cs.ptps), ("journey", js.ptps)):
        for ptp in store.values():
            on = _iso_day_quiet(ptp.get("promise_date"))
            if on is None or not (start <= on <= end):
                continue
            if officer and ptp.get("created_by") != officer:
                continue
            if status and ptp.get("status") != status:
                continue
            customer = journey.customer_by_uid(ptp.get("customer_uid"))
            rows.append({
                "uid": ptp["uid"], "source": source,
                "customer_uid": ptp.get("customer_uid"),
                "display_name": getattr(customer, "display_name", None),
                "volt_id": getattr(customer, "volt_id", None),
                "officer_uid": ptp.get("created_by"),
                "promise_date": str(on), "promised_amount": ptp.get("promised_amount"),
                "status": ptp.get("status"), "closed_on": ptp.get("closed_on"),
                # F01b: a postponed promise shows what it continues.
                "renegotiation_count": ptp.get("renegotiation_count", 0) or 0,
                "lineage_from_uid": ptp.get("lineage_from_uid"),
                "lineage_from_closed_on": ptp.get("lineage_from_closed_on"),
            })
    rows.sort(key=lambda r: (r["promise_date"], r["display_name"] or "", r["uid"]))
    return rows


def _iso_day_quiet(value):
    from datetime import date
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _ptp_totals(rows):
    total = sum((Decimal(r["promised_amount"] or "0") for r in rows), Decimal("0"))
    by_status = {}
    for r in rows:
        slot = by_status.setdefault(r["status"], {"count": 0, "promised_amount": Decimal("0")})
        slot["count"] += 1
        slot["promised_amount"] += Decimal(r["promised_amount"] or "0")
    return {
        "count": len(rows),
        "promised_amount": str(total.quantize(Decimal("0.01"))),
        "by_status": {k: {"count": v["count"],
                          "promised_amount": str(v["promised_amount"].quantize(Decimal("0.01")))}
                      for k, v in by_status.items()},
    }


@router.get("/v1/reports/ptps")
def ptp_report(from_: str = Query(default=None, alias="from"), to: str = Query(default=None),
               officer: str = Query(default=None), status: str = Query(default=None)):
    from ..config import settings
    bd = settings.business_date
    default_from, default_to = _business_month(bd)
    start = _iso_day(from_, "/from") if from_ else default_from
    end = _iso_day(to, "/to") if to else default_to
    if end < start:
        raise errors.validation_failed([{
            "pointer": "/to", "code": "range_inverted",
            "message": "The end of the range is before its start.",
            "message_th": "วันที่สิ้นสุดก่อนวันที่เริ่มต้น"}])
    if status and status not in _ptp_statuses():
        raise errors.validation_failed([{
            "pointer": "/status", "code": "value_unknown", "known": list(_ptp_statuses()),
            "message": "%r is not a promise status this system knows." % status,
            "message_th": "ไม่รู้จักสถานะนัดชำระที่ระบุ"}])
    rows = _ptp_rows(start, end, officer=officer, status=status)
    return {
        "rows": rows,
        "totals": _ptp_totals(rows),
        "meta": {
            "from": str(start), "to": str(end), "business_date": str(bd),
            "officer": officer, "status": status,
            "statuses": list(_ptp_statuses()),
            "note_th": "รวมนัดชำระทุกสถานะจากเคสและจากเส้นทางในช่วงวันที่ที่เลือก — ยอดรวมเสิร์ฟจาก API",
            "note_en": "Every promise of every status, case and journey stores alike, inside the range — the totals are served by the API",
        },
    }


@router.post("/v1/reports/ptps:export")
def ptp_report_export(body: dict = Body(default={})):
    """The same rows as CSV. Governed like every export: the act is named before the
    file is built (audit.describe), and the filename carries the range."""
    import csv
    import io

    from fastapi.responses import PlainTextResponse

    body = body or {}
    payload = ptp_report(from_=body.get("from"), to=body.get("to"),
                         officer=body.get("officer"), status=body.get("status"))
    rows = payload["rows"]
    audit.describe(act="PTP_REPORT_EXPORTED", subject=("report", "ptps"),
                   detail={"from": payload["meta"]["from"], "to": payload["meta"]["to"],
                           "officer": payload["meta"]["officer"], "status": payload["meta"]["status"],
                           "rows": len(rows)})
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["customer", "volt_id", "officer", "source", "promise_date",
                     "promised_amount", "status", "closed_on", "renegotiation_count",
                     "lineage_from_uid"])
    for r in rows:
        writer.writerow([r["display_name"] or "", r["volt_id"] or "", r["officer_uid"] or "",
                         r["source"], r["promise_date"], r["promised_amount"], r["status"],
                         r["closed_on"] or "", r["renegotiation_count"], r["lineage_from_uid"] or ""])
    filename = "ptp-report_%s_%s.csv" % (payload["meta"]["from"], payload["meta"]["to"])
    return PlainTextResponse("\ufeff" + out.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="%s"' % filename})


@router.get("/v1/reports/bucket-flow")
def bucket_flow(band_set: str = Query(default=None)):
    return reports.bucket_flow(band_set)


# --- REQ-KPI-017, round 5 rulings 78-83 -------------------------------------------
#
# Two indicators, not one function with a `measure` parameter (R79-D) — see
# collection_kpi.py's module docstring for why the shape refuses itself here.
#
# The trap this route must NOT walk into: declaring `measure` as a required
# `Query(...)` sends an omission through FastAPI's own RequestValidationError
# handler (main.py:222-240), whose per-field message_th is the hardcoded generic
# "ข้อมูลในฟิลด์นี้ไม่ถูกต้อง" — a specified refusal would reach the manager's screen
# as a typo report. `measure` is declared optional and raised BY HAND, the same
# idiom `/v1/dashboards/exceptions` already uses for `population_filter`
# (main.py:967-968).
@router.get("/v1/reports/collection")
def collection_indicator(measure: str = Query(default=None), month: str = Query(default=None),
                         officer: str = Query(default=None)):
    if not measure or not measure.strip():
        raise errors.collection_measure_unset()
    measure = measure.strip()
    if measure not in collection_kpi.MEASURES:
        raise errors.validation_failed([{
            "pointer": "/measure", "code": "unknown",
            "message": "%r is not a measure this system knows (cash_received, due_month)." % measure,
            "message_th": "ไม่รู้จักวิธีนับนี้ กรุณาเลือก cash_received หรือ due_month",
        }])
    month = (month or "").strip() or None
    if month is not None:
        try:
            collection_kpi.parse_month(month)
        except ValueError:
            raise errors.validation_failed([{
                "pointer": "/month", "code": "invalid",
                "message": "%r is not a YYYY-MM month." % month,
                "message_th": "รูปแบบเดือนไม่ถูกต้อง ใช้ YYYY-MM",
            }])
    officer = (officer or "").strip() or None
    return collection_kpi.FUNCTIONS[measure](month=month, officer=officer)


@router.put("/v1/reports/collection/{month}/targets")
def put_collection_targets(month: str, body: dict = Body(...), x_volt_role: str = Header(default="OFFICER")):
    """Ruling 78: the manager sets the target VALUES, per portfolio and per
    officer (ruling 82 — no team). A separate month-keyed namespace inside the
    SAME already-session-isolated store `PUT …/weekly/{period}/targets` uses
    (`reports.TARGETS`, ruling 43) — no new mechanism, and no collision: weekly
    periods are `"YYYY-MM-DD..YYYY-MM-DD"` strings, this is `"YYYY-MM"`, and the
    inner keys here always carry a `:` the weekly keys never do.

    Every key is validated before anything is written — an unknown key, a team
    key or contact_rate (a denominator concept, never a target — REQ-KPI-017) is
    refused by name (R5-F09's class: the sibling weekly route accepts ANY key
    with 200 and silently never produces a figure for it). **The value is
    validated too** (C-4, BLOCKER-class, found live by a concurrent design leg
    driving this exact route and reproduced independently before this fix):
    `{"due_month:portfolio": null}` used to store the literal string `"None"`,
    and the next `GET` raised `decimal.InvalidOperation` — a 500 that PERSISTS
    in the session store because the bad value was already saved. A
    comma-formatted string (`"400,000"`, what a manager actually types) did the
    same. **An empty string (`""`) is the CLEAR transition, not a value** — it
    removes the key rather than being parsed as a number, so REQ-KPI-020's "no
    target means no achievement figure" keeps working after a clear."""
    audit.describe(act="COLLECTION_TARGETS_SET", subject=("collection_month", month))
    if (x_volt_role or "").upper() not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only",
                             detail="Targets are saved by a Manager",
                             message_th="เฉพาะผู้จัดการตั้งเป้าได้", error_id="DEBT-IAM-0403")
    try:
        collection_kpi.parse_month(month)
    except ValueError:
        raise errors.validation_failed([{
            "pointer": "/month", "code": "invalid",
            "message": "%r is not a YYYY-MM month." % month,
            "message_th": "รูปแบบเดือนไม่ถูกต้อง ใช้ YYYY-MM",
        }])
    field_errors = []
    to_set = {}
    to_clear = []
    for k, v in (body or {}).items():
        ok, code, message = collection_kpi.validate_target_key(k)
        if not ok:
            field_errors.append({"pointer": "/%s" % k, "code": code,
                                 "message": message[1], "message_th": message[0]})
            continue
        if v == "":
            to_clear.append(k)          # the clear transition — a removal, not a value
            continue
        ok, normalized, message = collection_kpi.validate_target_value(v)
        if not ok:
            field_errors.append({"pointer": "/%s" % k, "code": "not_a_number",
                                 "message": message[1], "message_th": message[0]})
            continue
        to_set[k] = normalized
    if field_errors:
        raise errors.validation_failed(field_errors)
    current = dict(reports.TARGETS.get(month) or {})
    for k in to_clear:
        current.pop(k, None)
    current.update(to_set)
    reports.TARGETS[month] = current
    return {"month": month, "targets": reports.TARGETS[month]}
