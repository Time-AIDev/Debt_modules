"""The PEAK invoice report door — vault note 10 §3 WP1.

Same shape as routers/pipelines.py (raw body, X-Volt-Filename, Manager-only writes,
202 + uid to watch) so the officer meets one intake desk with three source cards.
"""
import json
import re
import threading
import urllib.parse
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import audit, db, errors, journey, landing, payment_claims
from ..integrations import peak_reports
from ..pipelines import field_decisions, peak_links, peak_receipt, peak_report, peak_service, peak_writer, runs
from .pipelines import _body, _manager_only, _officer_or_above, _require_db

router = APIRouter()
PREFIX = "/v1/pipelines/peak-report"
# Feedback round 2 / Q6 (TASK-205): the receipt door — its own prefix, its own
# tables, its own last-applied (a receipt run is nearly always newer than the
# applied invoice run). Same doors, roles, watchable run, review list and apply.
PREFIX_RECEIPT = "/v1/pipelines/peak-receipt"


def _filename(header):
    # Task 25a: the browser sends X-Volt-Filename: encodeURIComponent(file.name), so
    # the header arrives percent-encoded and MUST be decoded before sanitising — the
    # old sanitise-only code kept the hex of a stripped "%" and truncated PEAK's own
    # "…export_as_of_<from>_<to>_…" tail out of the 120-char cap, so report_as_of()
    # (peak_report.py) returned None. Decode exactly once, then sanitise (still via
    # Path(...).name, so a decoded "..%2F..%2Fetc%2Fpasswd" still ends as "passwd",
    # never a path); the character class widens past \w to the Thai block
    # (U+0E00-U+0E7F) because Thai vowel/tone marks are category Mn and \w alone
    # would still mangle a decoded Thai name.
    name = urllib.parse.unquote(header or "")
    return re.sub(r"[^\w฀-๿.\- ]", "", Path(name).name)[:120] or None


def _require_body(raw):
    if not raw:
        raise errors.validation_failed([{"pointer": "/file", "code": "required",
                                         "message": "The request body is empty.",
                                         "message_th": "ไฟล์ว่าง ไม่มีข้อมูลให้อ่าน"}])


@contextmanager
def _write_tx(conn):
    """A write transaction, tolerant of a connection a read left mid-transaction.

    In production `db.connect()` hands out a fresh pooled connection; a test harness
    hands every call the SAME connection, and a read (the epoch check, a book reload)
    leaves SQLAlchemy's implicit transaction open, which makes `conn.begin()` raise.
    Reads are done by then, so rolling back first costs nothing."""
    if conn.in_transaction():
        conn.rollback()
    with conn.begin():
        yield


# I1 (fix round 1): peak_service.run_upload swallows every failure — a parse error,
# a database refusal, anything unexpected — into runs.fail, so the run's own view
# never raises on its own. Left unhandled here, a synchronous :run that failed for
# any reason other than "no database" came back as HTTP 200 with {state: failed,
# problem}, unlike the crm.lead :run this router mirrors, which answers a problem.
# unreadable/header_not_found/missing_required_columns are the caller's own file — 422;
# database_required stays the existing 503; anything else is unexpected — 500,
# never silently 200.
_RUN_FAILURE_VALIDATION_CODES = ("unreadable", "header_not_found", "missing_required_columns",
                                 "schema_ambiguous_header", "wrong_report")
# A refused upload is not an internal error: the run is already in progress, or the
# same file is already staged. Both are 409s with the run the caller should use.
_RUN_FAILURE_CONFLICT_CODES = ("peak_run_in_progress", "peak_duplicate_report")

# WP5 (F19): door 2. Content-Type decides the door, as routers/pipelines.py:1-6 does for
# crm.lead: application/json carries {"source": "api"}; anything else is the file.
_DOOR_POINTERS = {"since_invalid": "/since", "instance_unknown": "/instance"}


def _is_json(request):
    return "application/json" in (request.headers.get("content-type") or "")


def _door_problem(problem):
    code = problem.get("code")
    if code == "feature_disabled":
        return errors.feature_disabled(feature="peak_api", reason="Production uses PEAK file imports only.")
    if code == "integration_not_configured":
        refusal = errors.integration_not_configured("PEAK report API", problem.get("missing_env") or [])
        refusal.message_th = problem.get("detail_th") or refusal.message_th
        return refusal
    if code in _DOOR_POINTERS:
        return errors.validation_failed([{"pointer": _DOOR_POINTERS[code], "code": code,
                                          "message": problem.get("detail"), "message_th": problem.get("detail_th")}])
    # integration_untested / adapter_missing: the door exists and is not open. 501 — never
    # a 200 that pretends a pull happened, never a 502 that blames PEAK for our gap.
    return errors.Problem(code=code or "integration_untested", status=501,
                          title="The PEAK report API door is not open yet",
                          detail=problem.get("detail"),
                          message_th=problem.get("detail_th") or peak_reports.UNTESTED_TH,
                          error_id="DEBT-INT-0501",
                          extensions={"integration": "PEAK report API", "state": peak_reports.state()["state"]})


def _api_door(raw):
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("source") != "api":
        raise errors.validation_failed([{"pointer": "/source", "code": "invalid",
                                         "message": 'source must be "api", or send the report file as the body',
                                         "message_th": "ต้องระบุ source เป็น api หรือส่งไฟล์รายงานมาใน body"}])
    try:
        return peak_service.run_api(since=body.get("since"), instance=body.get("instance") or "EPC")
    except peak_service.PipelineRefused as exc:
        raise _door_problem(exc.problem)


@router.post(PREFIX + ":run")
async def run_report(request: Request, x_volt_role: str = Header(default="OFFICER"),
                     x_volt_filename: str = Header(default=None)):
    audit.describe(act="PEAK_REPORT_RUN")
    _officer_or_above(x_volt_role)
    raw = await _body(request)
    if _is_json(request):
        _manager_only(x_volt_role)
        return _api_door(raw)
    _require_body(raw)
    run = peak_service.run_upload(raw, _filename(x_volt_filename))
    if run["state"] == "failed":
        problem = run.get("problem") or {}
        code = problem.get("code")
        if code in _RUN_FAILURE_VALIDATION_CODES:
            refusal = errors.validation_failed([{"pointer": "/file", "code": code,
                                                  "message": problem.get("detail"),
                                                  "message_th": problem.get("detail_th")}])
            refusal.extensions["schema"] = problem.get("schema") or {}
            raise refusal
        if code in _RUN_FAILURE_CONFLICT_CODES:
            raise errors.Problem(code=code, status=409, title="The PEAK report was refused",
                                 detail=problem.get("detail"),
                                 message_th=problem.get("detail_th") or "รายงาน PEAK นี้ถูกปฏิเสธ",
                                 error_id="DEBT-PEAK-0409",
                                 extensions={"run_id": problem.get("run_id")} if problem.get("run_id") else None)
        if code == "database_required":
            _require_db()
        raise errors.Problem(code=code, status=500, title="The PEAK report run failed",
                             detail=problem.get("detail"),
                             message_th=problem.get("detail_th") or "การประมวลผลรายงาน PEAK ล้มเหลว",
                             error_id="DEBT-PEAK-0500")
    return run


@router.get(PREFIX + "/schemas")
def schemas():
    """Upload checklist owned by the backend parser, not duplicated in the UI."""
    return {"invoice": peak_report.public_schema(), "receipt": peak_receipt.public_schema()}


@router.post(PREFIX + ":start", status_code=202)
async def start_report(request: Request, x_volt_role: str = Header(default="OFFICER"),
                       x_volt_filename: str = Header(default=None)):
    audit.describe(act="PEAK_REPORT_RUN")
    _officer_or_above(x_volt_role)
    raw = await _body(request)
    if _is_json(request):
        # Door 2 refuses before any run starts (peak_service.run_api), so there is no
        # uid to hand back and nothing to thread: the refusal is the answer.
        _manager_only(x_volt_role)
        return _api_door(raw)
    _require_body(raw)
    uid = runs.start(peak_service.KIND)
    from ..production_unit import enabled
    from ..durable_runs import WORKER_RUN
    if enabled():
        if not WORKER_RUN.get():
            from ..task_outbox import enqueue_request
            await run_in_threadpool(enqueue_request, request, uid, raw)
        else:
            await run_in_threadpool(peak_service.run_upload, raw, _filename(x_volt_filename), uid)
        return JSONResponse(status_code=202, content=runs.get(uid))
    threading.Thread(target=peak_service.run_upload, args=(raw, _filename(x_volt_filename), uid),
                     daemon=True).start()
    return JSONResponse(status_code=202, content=runs.get(uid))


@router.get(PREFIX + "/runs/{uid}")
def get_run(uid: str):
    run = runs.get(uid)
    if run is None:
        raise errors.not_found("pipeline run")
    return run


@router.get(PREFIX + "/last-run")
def last_run():
    watch = runs.latest(kind=peak_service.KIND)
    if not db.configured():
        return {"staged": None, "applied": None, "watch": watch}
    conn = db.connect()
    try:
        return {"staged": peak_writer.last_run(conn, applied=False),
                "applied": peak_writer.last_run(conn, applied=True),
                "failed": peak_writer.last_failed(conn), "watch": watch}
    finally:
        conn.close()


@router.get(PREFIX + "/doors")
def doors():
    """WP5 (F19): both doors and their state, in codes the card turns into words."""
    return {"doors": [
        {"door": "upload", "state": "ready", "formats": ["xlsx", "csv"], "roles": ["OFFICER", "MANAGER", "OWNER"]},
        dict(peak_reports.state(), door="api", roles=["MANAGER", "OWNER"]),
    ]}


@router.get(PREFIX + "/landing-runs/{run_id}/rows")
def run_rows(run_id: int, verdict: str = Query(default=None),
             limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    if verdict not in (None, "", "EXACT", "CANDIDATE", "UNMATCHED", "REJECTED"):
        raise errors.validation_failed([{"pointer": "/verdict", "code": "invalid",
                                         "message": "verdict is EXACT, CANDIDATE, UNMATCHED or REJECTED",
                                         "message_th": "verdict ต้องเป็น EXACT, CANDIDATE, UNMATCHED หรือ REJECTED"}])
    _require_db()
    conn = db.connect()
    try:
        return peak_writer.rows(conn, run_id, verdict=verdict or None, limit=limit, offset=offset)
    finally:
        conn.close()


_TICK = " — tick 'Apply even if older than the applied report' if you mean to"
_REFUSED_TITLE = {
    "not_found": "This PEAK import run was not found",
    "already_applied": "This import run was already applied — upload the report again to apply it again",
    "report_as_of_unknown": "This report's date is unknown, so it cannot be shown to be newer than the report in use" + _TICK,
    "report_older_than_applied": "This report is older than the report in use" + _TICK,
    "report_range_narrower": "This report starts later than the report in use, so earlier invoices would drop out" + _TICK,
    "receipt_range_narrower": "This receipt report starts later than the one in use — export the receipts again "
                              "from the same start date",
    "report_already_applied": "The same report is already applied — force only to process it again",
    "peak_run_in_progress": "Another PEAK report run is in progress — try again when it finishes",
}


def _refused(exc):
    # Ruling 2 (Task 4's fix): apply_run now raises three codes — not_found,
    # report_older_than_applied, report_as_of_unknown. not_found is a 404; the other
    # two are both a 409 (the request was well formed, the report is simply refused
    # against the one already applied) — the else branch below already covers the
    # new code without naming it, so no branch was added for it. Final review I2 adds a
    # fourth, already_applied — also a 409 through the same else branch.
    status = 404 if exc.code == "not_found" else 409
    # Language pass: the title is the one English sentence the screen reads.
    return errors.Problem(code=exc.code, status=status, title=_REFUSED_TITLE.get(exc.code, "PEAK report refused"),
                          detail=exc.detail, message_th=exc.detail_th, error_id="DEBT-PEAK-%04d" % status)


def _after_apply(kind="peak", run_id=None):
    """The served book rebuilt, then THIS session healed, in one sequence.

    The acting session runs the same `import_sync.heal_session()` every other session
    runs on its next request — PEAK invoices, migrated invoices, pipeline cards, case
    snapshots and documents — and then stamps `seen`, so the next request does not
    repeat it (sync audit, 2026-09-20: the bespoke reseed here plus the lazy heal on
    the next request ran the work twice). `served: false` still means the reload
    failed and `:refresh-served` is the repair."""
    from .. import import_sync, refresh
    served = refresh.after_landing(kind, run_id)
    if not served["served"]:
        raise RuntimeError((served.get("problem") or {}).get("detail") or "reload failed")
    with import_sync.session_lock():
        # This session's own 30 s poll may have healed it for this epoch while the
        # book rebuilt: heal once (fix-all F audit).
        if int(served["epoch"] or 0) > 0 and import_sync.seen_epoch() >= int(served["epoch"]):
            return {}
        summary = import_sync.heal_session()
        import_sync.mark_seen(served["epoch"])
    return summary


_AFTER_APPLY_FAILED_TH = "บันทึกแล้ว แต่ระบบยังโหลดข้อมูลชุดใหม่ไม่สำเร็จ — ลองรีเฟรช หรือแจ้งผู้ดูแลระบบ"
_AFTER_APPLY_FAILED_EN = "Saved, but the new data has not loaded yet — refresh, or tell the administrator"


def _served(payload, kind="peak", run_id=None):
    """I2 (fix round 1): the write this payload reports on has ALREADY COMMITTED and
    ALREADY BEEN AUDITED by the time this runs — callers audit.describe() the act
    before calling this, never after. _after_apply() only reloads what the rest of
    this process sees (the book, this session's invoices, every case's status); if
    THAT fails, the write itself is not undone and must not be misreported as one —
    the response still carries the committed result, with served=False and a Thai
    note telling the caller to refresh, and the failure is folded into the SAME
    audit row (never a second act, never the act name itself, which would misdescribe
    a write that succeeded)."""
    try:
        summary = _after_apply(kind, run_id)
        payload["served"] = True
        payload["moved_cases"] = summary.get("cases_moved", 0)
        payload["refreshed_cases"] = summary.get("cases_refreshed", 0)
    except Exception as exc:                      # noqa: BLE001 — recorded, never swallowed
        payload["served"] = False
        payload["note_th"] = _AFTER_APPLY_FAILED_TH
        payload["note_en"] = _AFTER_APPLY_FAILED_EN
        audit.describe(detail={"after_apply_failed": exc.__class__.__name__})
    return payload


@router.post(PREFIX + "/landing-runs/{run_id}:apply")
def apply_run(run_id: int, body: dict = Body(default=None), x_volt_role: str = Header(default="OFFICER"),
              x_volt_officer: str = Header(default=None)):
    _officer_or_above(x_volt_role)
    body = body or {}
    if body.get("allow_older") or body.get("force"):
        _manager_only(x_volt_role)
    _require_db()
    conn = db.connect()
    try:
        with _write_tx(conn):
            try:
                run = peak_writer.apply_run(conn, run_id, by=x_volt_officer or x_volt_role.upper(),
                                            allow_older=bool(body.get("allow_older")),
                                            force=bool(body.get("force")))
            except peak_writer.WriterRefused as exc:
                raise _refused(exc)
    finally:
        conn.close()
    # I2: audit the act THE MOMENT the transaction above has committed — before
    # _after_apply() gets any chance to raise and cost the audit row for a write
    # that already happened.
    meta = run.get("meta") or {}
    audit.describe(act="PEAK_REPORT_APPLIED", subject=("import_run", str(run_id)),
                   detail={"report_as_of": meta.get("report_as_of"), "matched": meta.get("matched"),
                           "candidates": meta.get("candidates"), "unmatched": meta.get("unmatched"),
                           "allow_older": bool(body.get("allow_older"))})
    return _served({"run": run, "note_th": "ใช้รายงานนี้แล้ว — เซสชันนี้เห็นข้อมูลใหม่ทันที เซสชันอื่นอัปเดตอัตโนมัติเมื่อเปิดหน้าถัดไป",
                    "note_en": "This report is now in use — this session sees the new data at once; other sessions catch up automatically on their next request"},
                   "peak", run_id)


@router.post(PREFIX + "/landing-runs/{run_id}:refresh-served")
def refresh_served(run_id: int, x_volt_role: str = Header(default="OFFICER"),
                   x_volt_officer: str = Header(default=None)):
    """Repairs a committed apply whose served refresh failed (`served: false`).

    The apply is committed and audited before the reload runs; when the reload
    failed, the refusal path had no way back — re-applying is 409 already_applied,
    and re-uploading was the only advice (sync audit, 2026-09-20). This re-runs the
    same idempotent after-apply step: the served book is rebuilt, this session's
    PEAK invoices reseed onto their stable uids, and case payment statuses follow.
    Same role bar as the apply itself."""
    _officer_or_above(x_volt_role)
    _require_db()
    conn = db.connect()
    try:
        run = landing.get_run(conn, run_id)
    finally:
        conn.close()
    if run is None or run.get("source_system") != peak_writer.SOURCE:
        raise errors.not_found("PEAK run %s" % run_id)
    if not (run.get("meta") or {}).get("applied"):
        raise errors.Problem(
            code="run_not_applied", status=409, title="This import run has not been applied",
            detail="nothing to refresh; apply the run first",
            message_th="รอบนำเข้านี้ยังไม่ได้ถูกใช้ — กด 'ใช้รายงานนี้' ก่อน", error_id="DEBT-PEAK-0409")
    audit.describe(detail={"refresh_served": {"run_id": run_id}})
    return _served({"run": landing.serialize_run(run)}, "peak", run_id)


@router.get(PREFIX + "/links")
def links(include_retired: bool = Query(default=False), customer_no: str = Query(default=None)):
    """Q7/TASK-210: the register, optionally the links of ONE customer (the case page's
    own list)."""
    _require_db()
    conn = db.connect()
    try:
        rows = peak_links.list_links(conn, include_retired=include_retired)
    finally:
        conn.close()
    if customer_no:
        rows = [r for r in rows if str(r.get("customer_no")) == str(customer_no)]
    return {"links": rows}


@router.post(PREFIX + "/links", status_code=201)
def confirm_link(body: dict = Body(...), x_volt_role: str = Header(default="OFFICER"),
                 x_volt_officer: str = Header(default=None)):
    _officer_or_above(x_volt_role)
    code, no = (body.get("contact_code") or "").strip(), str(body.get("customer_no") or "").strip()
    problems = []
    if not code:
        problems.append({"pointer": "/contact_code", "code": "required", "message": "contact_code is required",
                         "message_th": "ต้องระบุรหัสผู้ติดต่อ PEAK"})
    if not no:
        problems.append({"pointer": "/customer_no", "code": "required", "message": "customer_no is required",
                         "message_th": "ต้องระบุเลขลูกค้า"})
    if problems:
        raise errors.validation_failed(problems)
    _require_db()
    if not any(c.customer_no == no for c in journey.book_customers()):
        raise errors.not_found("customer %s" % no)
    conn = db.connect()
    try:
        with _write_tx(conn):
            link = peak_links.confirm(conn, code, no, by=x_volt_officer or x_volt_role.upper(), reason=body.get("reason"),
                                      contract_uid=body.get("contract_uid"))
    finally:
        conn.close()
    # I2: audit before _after_apply() — see apply_run's own note above.
    audit.describe(act="PEAK_LINK_CONFIRMED", subject=("customer", "sheet-%s" % no),
                   detail={"contact_code": link["contact_code"], "reason": body.get("reason")})
    return _served({"link": link}, "peak-link")


@router.post(PREFIX + "/links/{uid}:retire")
def retire_link(uid: int, body: dict = Body(default=None), x_volt_role: str = Header(default="OFFICER"),
                x_volt_officer: str = Header(default=None)):
    _officer_or_above(x_volt_role)
    _require_db()
    conn = db.connect()
    try:
        with _write_tx(conn):
            link = peak_links.retire(conn, uid, by=x_volt_officer or x_volt_role.upper())
    finally:
        conn.close()
    if link is None:
        raise errors.not_found("active link %s" % uid)
    # I2: audit before _after_apply() — see apply_run's own note above.
    audit.describe(act="PEAK_LINK_RETIRED", subject=("customer", "sheet-%s" % link["customer_no"]),
                   detail={"contact_code": link["contact_code"], "reason": (body or {}).get("reason")})
    return _served({"link": link}, "peak-link")


# --- feedback round 2 / Q6: the receipt report door (TASK-205) ----------------------
#
# The frequent upload: the same doors, roles, watchable run, review list and apply
# step as the invoice report, over its own table and its own last-applied.

@router.post(PREFIX_RECEIPT + ":start", status_code=202)
async def start_receipt(request: Request, x_volt_role: str = Header(default="OFFICER"),
                        x_volt_filename: str = Header(default=None)):
    audit.describe(act="PEAK_RECEIPT_RUN")
    _officer_or_above(x_volt_role)
    raw = await _body(request)
    _require_body(raw)
    uid = runs.start(peak_service.KIND_RECEIPT)
    from ..production_unit import enabled
    from ..durable_runs import WORKER_RUN
    if enabled():
        if not WORKER_RUN.get():
            from ..task_outbox import enqueue_request
            await run_in_threadpool(enqueue_request, request, uid, raw)
        else:
            await run_in_threadpool(peak_service.run_receipt_upload, raw, _filename(x_volt_filename), uid)
        return JSONResponse(status_code=202, content=runs.get(uid))
    threading.Thread(target=peak_service.run_receipt_upload, args=(raw, _filename(x_volt_filename), uid),
                     daemon=True).start()
    return JSONResponse(status_code=202, content=runs.get(uid))


@router.get(PREFIX_RECEIPT + "/runs/{uid}")
def get_receipt_run(uid: str):
    run = runs.get(uid)
    if run is None:
        raise errors.not_found("pipeline run")
    return run


@router.get(PREFIX_RECEIPT + "/last-run")
def receipt_last_run():
    watch = runs.latest(kind=peak_service.KIND_RECEIPT)
    if not db.configured():
        return {"staged": None, "applied": None, "watch": watch}
    conn = db.connect()
    try:
        return {"staged": peak_writer.last_run(conn, applied=False, source=peak_writer.RECEIPT_SOURCE),
                "applied": peak_writer.last_run(conn, applied=True, source=peak_writer.RECEIPT_SOURCE),
                "failed": peak_writer.last_failed(conn, source=peak_writer.RECEIPT_SOURCE),
                "watch": watch}
    finally:
        conn.close()


@router.get(PREFIX_RECEIPT + "/landing-runs/{run_id}/rows")
def receipt_run_rows(run_id: int, verdict: str = Query(default=None),
                     limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    if verdict not in (None, "", "EXACT", "CANDIDATE", "UNMATCHED", "REJECTED"):
        raise errors.validation_failed([{"pointer": "/verdict", "code": "invalid",
                                         "message": "verdict is EXACT, CANDIDATE, UNMATCHED or REJECTED",
                                         "message_th": "verdict ต้องเป็น EXACT, CANDIDATE, UNMATCHED หรือ REJECTED"}])
    _require_db()
    conn = db.connect()
    try:
        return peak_writer.receipt_rows(conn, run_id, verdict=verdict or None, limit=limit, offset=offset)
    finally:
        conn.close()


@router.post(PREFIX_RECEIPT + "/landing-runs/{run_id}:apply")
def apply_receipt_run(run_id: int, body: dict = Body(default=None), x_volt_role: str = Header(default="OFFICER"),
                      x_volt_officer: str = Header(default=None)):
    _officer_or_above(x_volt_role)
    body = body or {}
    if body.get("allow_older"):
        _manager_only(x_volt_role)
    _require_db()
    conn = db.connect()
    try:
        with _write_tx(conn):
            try:
                run = peak_writer.apply_receipt_run(conn, run_id, by=x_volt_officer or x_volt_role.upper(),
                                                    allow_older=bool(body.get("allow_older")))
                reconciliation = payment_claims.reconcile_applied(conn, run_id)
            except peak_writer.WriterRefused as exc:
                raise _refused(exc)
    finally:
        conn.close()
    meta = run.get("meta") or {}
    audit.describe(act="PEAK_RECEIPT_APPLIED", subject=("import_run", str(run_id)),
                   detail={"report_as_of": meta.get("report_as_of"), "matched": meta.get("matched"),
                           "unmatched": meta.get("unmatched"), "allow_older": bool(body.get("allow_older")),
                           "reconciliation": reconciliation})
    return _served({"run": run, "reconciliation": reconciliation,
                    "note_th": "ใช้รายงานใบเสร็จนี้แล้ว — สถานะการชำระรายงวดอัปเดตทันที",
                    "note_en": "This receipt report is now in use — per-instalment payment status updates at once"},
                   "peak-receipt", run_id)


@router.post(PREFIX_RECEIPT + "/landing-runs/{run_id}:refresh-served")
def refresh_receipt_served(run_id: int, x_volt_role: str = Header(default="OFFICER"),
                           x_volt_officer: str = Header(default=None)):
    _officer_or_above(x_volt_role)
    _require_db()
    conn = db.connect()
    try:
        run = landing.get_run(conn, run_id)
    finally:
        conn.close()
    if run is None or run.get("source_system") != peak_writer.RECEIPT_SOURCE:
        raise errors.not_found("PEAK receipt run %s" % run_id)
    if not (run.get("meta") or {}).get("applied"):
        raise errors.Problem(
            code="run_not_applied", status=409, title="This import run has not been applied",
            detail="nothing to refresh; apply the run first",
            message_th="รอบนำเข้านี้ยังไม่ได้ถูกใช้ — กด 'ใช้รายงานนี้' ก่อน", error_id="DEBT-PEAK-0409")
    audit.describe(detail={"refresh_served": {"run_id": run_id}})
    return _served({"run": landing.serialize_run(run)}, "peak-receipt", run_id)


# --- feedback round 2 / Q7: the conflict review (TASK-208/209) -----------------------

def _conflicts_page(conn, run_id, offset=0, limit=50):
    limit = max(1, min(int(limit or 50), 100))
    offset = max(0, int(offset or 0))
    by_no = {str(c.customer_no): c for c in
             list(journey.book_customers()) + list(journey.identity_customers())}
    groups, order = {}, []
    for row in peak_writer.conflict_rows(conn, run_id):
        no = row["customer_no"]
        if no not in groups:
            order.append(no)
            groups[no] = {"customer_no": no, "display_name": None, "volt_id": None,
                          "invoice_count": 0, "conflicts": [], "decided": False}
        slot = groups[no]
        slot["invoice_count"] += 1
        for c in row["conflicts"] or []:
            if not any(existing["field"] == c["field"] for existing in slot["conflicts"]):
                slot["conflicts"].append(c)
    active = field_decisions.load(conn, order)
    for no, slot in groups.items():
        customer = by_no.get(str(no))
        slot["display_name"] = getattr(customer, "display_name", None)
        slot["volt_id"] = getattr(customer, "volt_id", None)
        decisions = active.get(no, {})
        for c in slot["conflicts"]:
            decision = decisions.get(c["field"])
            c["decision"] = ({"source": decision["chosen_source"], "by": decision["decided_by"],
                              "at": str(decision["decided_at"]), "reason": decision.get("reason"),
                              "uid": decision["uid"]} if decision else None)
        slot["decided"] = all(c.get("decision") for c in slot["conflicts"])
    paged = [groups[no] for no in order[offset:offset + limit]]
    # the fields that take PEAK on apply; volt_id never does (fix-all P5)
    undecided = sum(1 for no in order for c in groups[no]["conflicts"]
                    if not c.get("decision") and c["field"] != "volt_id")
    return {"rows": paged, "total": len(order), "limit": limit, "offset": offset,
            "undecided_fields": undecided}


@router.get(PREFIX + "/landing-runs/{run_id}/conflicts")
def run_conflicts(run_id: int, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100)):
    _require_db()
    conn = db.connect()
    try:
        return _conflicts_page(conn, run_id, offset=offset, limit=limit)
    finally:
        conn.close()


def _decision_problem(problems):
    raise errors.validation_failed(problems)


@router.post(PREFIX + "/landing-runs/{run_id}/conflicts:decide")
def decide_conflicts(run_id: int, body: dict = Body(default=None), x_volt_role: str = Header(default="OFFICER"),
                     x_volt_officer: str = Header(default=None)):
    _officer_or_above(x_volt_role)
    body = body or {}
    no = str(body.get("customer_no") or "").strip()
    decisions = body.get("decisions") or []
    problems = []
    if not no:
        problems.append({"pointer": "/customer_no", "code": "required", "message": "customer_no is required",
                         "message_th": "ต้องระบุลูกค้า"})
    if not isinstance(decisions, list) or not decisions:
        problems.append({"pointer": "/decisions", "code": "required", "message": "at least one decision is required",
                         "message_th": "ต้องมีการตัดสินอย่างน้อยหนึ่งฟิลด์"})
    for i, d in enumerate(decisions):
        if d.get("field") not in field_decisions.FIELDS:
            problems.append({"pointer": "/decisions/%d/field" % i, "code": "unknown",
                             "message": "%r is not a comparable field" % d.get("field"),
                             "message_th": "ไม่รู้จักฟิลด์ที่ตัดสิน"})
        if d.get("source") not in ("PEAK", "ODOO"):
            problems.append({"pointer": "/decisions/%d/source" % i, "code": "unknown",
                             "message": "source must be PEAK or ODOO",
                             "message_th": "แหล่งข้อมูลต้องเป็น PEAK หรือ ODOO"})
    if problems:
        _decision_problem(problems)
    _require_db()
    by = x_volt_officer or x_volt_role.upper()
    conn = db.connect()
    try:
        # Fix-all P3 (F4): the decision stores what each side said — the run's own
        # conflict, first per field as the page shows it — or the served field is
        # overwritten with NULL. A field the run never disagreed on is refused.
        said = {}
        for row in peak_writer.conflict_rows(conn, run_id):
            if row["customer_no"] == no:
                for c in row["conflicts"] or []:
                    said.setdefault(c["field"], c)
        missing = [{"pointer": "/decisions/%d/field" % i, "code": "no_such_conflict",
                    "message": "run %s has no %s conflict for this customer" % (run_id, d["field"]),
                    "message_th": "รอบนำเข้านี้ไม่มีข้อมูลที่ขัดกันในฟิลด์นี้ของลูกค้ารายนี้"}
                   for i, d in enumerate(decisions) if d["field"] not in said]
        if missing:
            _decision_problem(missing)
        with _write_tx(conn):
            for d in decisions:
                field_decisions.decide(conn, no, d["field"], d["source"], by=by,
                                       reason=d.get("reason"), run_id=run_id,
                                       peak_value=said[d["field"]].get("peak_value"),
                                       odoo_value=said[d["field"]].get("odoo_value"))
    finally:
        conn.close()
    audit.describe(act="PEAK_FIELD_DECIDED", subject=("customer", "sheet-%s" % no),
                   detail={"run_id": run_id,
                           "decisions": [{"field": d["field"], "source": d["source"]} for d in decisions]})
    return _served({"customer_no": no, "decisions": len(decisions)}, "peak-field", run_id)


@router.post(PREFIX + "/field-decisions/{uid}:retire")
def retire_field_decision(uid: int, body: dict = Body(default=None), x_volt_role: str = Header(default="OFFICER"),
                          x_volt_officer: str = Header(default=None)):
    _officer_or_above(x_volt_role)
    _require_db()
    conn = db.connect()
    try:
        with _write_tx(conn):
            row = field_decisions.retire(conn, uid, by=x_volt_officer or x_volt_role.upper())
    finally:
        conn.close()
    if row is None:
        raise errors.not_found("active field decision %s" % uid)
    audit.describe(act="PEAK_FIELD_DECISION_RETIRED", subject=("customer", "sheet-%s" % row["customer_no"]),
                   detail={"field": row["field"], "uid": uid})
    return _served({"decision": row}, "peak-field")


def conflicts_undecided(conn, run_id):
    """Served count for the apply confirmation: how many differing fields of the run
    no person has decided (they take PEAK on apply)."""
    page = _conflicts_page(conn, run_id, offset=0, limit=100)
    return page["undecided_fields"]
