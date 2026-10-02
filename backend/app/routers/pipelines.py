"""The crm.lead pipeline endpoint. Manager-only; it reads Odoo and nothing else.

The body is JSON: {"source": "odoo", "mode": "NEW_ONLY"|"OVERWRITE"}. The crm.lead
file door closed on 2026-09-25 (fix-all): a raw file gets 422 use_sheet_upload,
pointing at POST /v1/imports, where the New Order Master sheet lands.

Design: docs/archive/superpowers/specs/2026-09-11-odoo-crm-lead-pipeline-design.md
"""
import json
import threading

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import audit
from .. import db, errors, session as session_domain
from ..imports import MAX_BYTES, MAX_MB
from .imports import upload_from_parts
from ..pipelines import runs, schedule as schedule_mod, service, writer

router = APIRouter()

REASON = "no money row in Odoo"

def _manager_only(role):
    if (role or "OFFICER").upper() not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Manager only",
                             detail="Running an import is a Manager's act",
                             message_th="เฉพาะผู้จัดการนำเข้าข้อมูลได้",
                             error_id="DEBT-IAM-0403")


def _officer_or_above(role):
    """Staging, linking and applying a newer report are an officer's work. Only
    allow_older, which overrides the date and range refusals, stays a Manager's."""
    if (role or "").upper() not in ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Not this role's act",
                             detail="Bringing in a PEAK report is not this role's act",
                             message_th="บทบาทนี้ไม่มีสิทธิ์นำเข้ารายงาน PEAK",
                             error_id="DEBT-IAM-0403")


async def _body(request):
    """The request body, with the same running cap routers/imports.py applies — a
    chunked body can omit or lie about Content-Length, so the cap is enforced while
    reading rather than from the header alone. A file sent in parts arrives whole."""
    joined = upload_from_parts(request)
    if joined is not None:
        return joined
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BYTES:
            raise errors.validation_failed([{
                "pointer": "/file", "code": "payload_too_large",
                "message": "The stream exceeded the %d MB cap while being read." % MAX_MB,
                "message_th": "ข้อมูลใหญ่เกิน %d MB" % MAX_MB,
                "cap_bytes": MAX_BYTES}])
        chunks.append(chunk)
    return b"".join(chunks)


# --- the watchable run (2026-09-11) ------------------------------------------------

def _read_mode(raw, is_json):
    """The run's mode, from the JSON body. Shared by :run and :start so the two can
    never disagree about what a request asks for."""
    if raw and not is_json:
        raise errors.Problem(
            code="use_sheet_upload", status=422,
            title="Upload the sheet at /v1/imports",
            detail="The crm.lead pipeline reads Odoo only; the New Order Master file "
                   "lands through POST /v1/imports.",
            message_th="ไปอัปโหลดไฟล์ชีตที่หน้านำเข้าไฟล์ (/v1/imports) — การดึง Odoo crm.lead ไม่รับไฟล์",
            error_id="DEBT-PIP-0422", extensions={"use": "/v1/imports"})
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {}
    if (body or {}).get("source") != "odoo":
        raise errors.validation_failed([{
            "pointer": "/source", "code": "invalid",
            "message": 'source must be "odoo"',
            "message_th": "ต้องระบุ source เป็น odoo"}])
    mode = body.get("mode") or "NEW_ONLY"
    if mode not in writer.MODES:
        raise errors.validation_failed([{
            "pointer": "/mode", "code": "invalid",
            "message": "mode is NEW_ONLY or OVERWRITE",
            "message_th": "mode ต้องเป็น NEW_ONLY หรือ OVERWRITE"}])
    return mode


def _database_required(detail):
    return errors.Problem(code="database_required", status=503,
                          title="No database configured", detail=detail,
                          message_th="ต้องตั้งค่าฐานข้อมูลก่อนนำเข้า",
                          error_id="DEBT-PIP-0503")


def _run_problem(problem):
    """A failed run's registry problem as the HTTP answer :run gives."""
    code = problem.get("code")
    if code == "integration_not_configured":
        return errors.integration_not_configured("Odoo", problem.get("missing") or [])
    if code == "integration_unavailable":
        return errors.integration_unavailable("Odoo", problem.get("detail"))
    if code == "database_required":
        return _database_required(problem.get("detail"))
    if code in ("crm_lead_run_in_progress", "pull_would_retire_too_much",
                "eligibility_preview_invalid", "eligibility_preview_used",
                "eligibility_preview_expired", "eligibility_preview_mismatch"):
        return errors.Problem(code=code, status=409, title="The crm.lead pull was refused",
                              detail=problem.get("detail"),
                              message_th=problem.get("detail_th") or "ข้อมูลเปลี่ยนจากตอนตรวจสอบ กรุณาตรวจสอบจำนวนใหม่",
                              error_id="DEBT-PIP-0409", retryable=code == "crm_lead_run_in_progress")
    # Never a built-in default for rules_unreadable: a pipeline running on rules
    # nobody can see is exactly what the rules file exists to prevent.
    return errors.Problem(code=code or "pipeline_failed", status=500,
                          title="The crm.lead pull failed", detail=problem.get("detail"),
                          message_th="การดึง Odoo crm.lead ล้มเหลว",
                          error_id="DEBT-PIP-0500")


@router.post("/v1/pipelines/crm-lead/eligibility:preview")
async def preview_crm_eligibility(x_volt_role: str = Header(default="OFFICER")):
    """Create the one-time count token required for eligibility soft-retirement."""
    audit.describe(act="CRM_ELIGIBILITY_PREVIEW")
    _manager_only(x_volt_role)
    try:
        result = await run_in_threadpool(service.preview_eligibility, session_domain.current())
    except Exception as exc:
        problem, _code = service._failure(exc)
        raise _run_problem(problem)
    audit.describe(subject=("eligibility_preview", result["token"]),
                   detail=result["expected"])
    return result


@router.post("/v1/pipelines/crm-lead/eligibility:apply")
async def apply_crm_eligibility(body: dict = Body(default=None),
                                x_volt_role: str = Header(default="OFFICER")):
    """Re-fetch, verify the preview counts, then atomically apply and consume it."""
    audit.describe(act="CRM_ELIGIBILITY_APPLY")
    _manager_only(x_volt_role)
    token = str((body or {}).get("token") or "").strip()
    if not token:
        raise errors.validation_failed([{"pointer": "/token", "code": "required",
                                         "message": "preview token is required",
                                         "message_th": "ต้องระบุ token จากขั้น preview"}])
    view = await run_in_threadpool(service.apply_eligibility, token,
                                   session_domain.current())
    if view["state"] != "done":
        raise _run_problem(view.get("problem") or {})
    audit.describe(subject=("eligibility_preview", token),
                   detail={"run_id": view.get("run_id"), "retired": view.get("retired")})
    return view


@router.post("/v1/pipelines/crm-lead:run")
async def run_crm_lead(request: Request, x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="CRM_LEAD_PIPELINE_RUN")
    _manager_only(x_volt_role)
    raw = await _body(request)
    mode = _read_mode(raw, "application/json" in (request.headers.get("content-type") or ""))
    # The same run sequence :start, the timer and the job use (service.run_odoo) —
    # durable run row, lock, landing, rebuild — off the event loop: a 34k-lead pull
    # inline would stall every other request for its minute and a half.
    view = await run_in_threadpool(service.run_odoo, None, mode)
    if view["state"] != "done":
        raise _run_problem(view.get("problem") or {})
    return {**view, "source": "odoo", "reason": REASON}


def _require_db():
    if not db.configured():
        raise _database_required("The pipeline lands rows in the landing schema; set DATABASE_URL")


def _receipt_summary(run):
    """The durable receipt in one screenful: counts plus samples, never the
    whole ledger. The full ledger is one paginated call away."""
    if run is None:
        return None
    meta = run.get("meta") or {}
    counts = run.get("row_counts") or {}
    ledger = meta.get("overwrite_ledger") or []
    # last-run is served from a slim row: the list itself is dropped in SQL and its
    # size travels as `ledger_total` (the paginated endpoint serves the entries).
    ledger_total = meta.get("ledger_total")
    if ledger_total is None:
        ledger_total = len(ledger)
    # Runs since 2026-09-20 keep a bounded sample and the true total on meta; older
    # runs kept the whole list. Both must render the same receipt.
    unmapped = meta.get("unmapped") or []
    unmapped_total = meta.get("unmapped_total")
    if unmapped_total is None:
        unmapped_total = len(unmapped)
    unmapped_sample = meta.get("unmapped_sample") or unmapped[:20]
    return {
        "id": run.get("id"),
        "source_system": run.get("source_system"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "door": meta.get("door"),
        "reason": meta.get("reason") or REASON,
        "counts": counts,
        "read": counts.get("read", meta.get("read")),
        "landed": counts.get("landed", 0),
        "rejected": counts.get("rejected", 0),
        "overwrote": counts.get("overwrote", 0),
        "rejected_by_rule": meta.get("rejected") or {},
        "unmapped_sample": unmapped_sample,
        "unmapped_total": unmapped_total,
        "ledger_sample": ledger[:20],
        "ledger_total": ledger_total,
        # An empty ledger is NO MEASUREMENT while §1 stays unwired
        # (odoo_compare.md §1/§6): the two systems share no volt_id string,
        # so nothing was compared. Never render it as "no harm".
        "ledger_measured": bool(counts.get("landed")),
        "note": run.get("note"),
        "mode": meta.get("mode") or "OVERWRITE",
        "new": meta.get("new"), "skipped": meta.get("skipped"),
        "changed": meta.get("changed"), "unchanged": meta.get("unchanged"),
        "retired": meta.get("retired"),
        # last-run's slim row carries the total and drops the list (landing._SLIM_RUN).
        "proposals_total": meta.get("proposals_total", len(meta.get("proposals") or [])),
        "proposals_sample": (meta.get("proposals") or [])[:20],
    }


@router.get("/v1/pipelines/crm-lead/last-run")
def last_run():
    from .. import landing
    # The registry is shared with the PEAK runs: only a crm.lead pull is watched here.
    watch = runs.latest(kind="odoo")
    if not db.configured():
        return {"run": None, "watch": watch, "receipt": None, "failed": None}
    conn = db.connect()
    try:
        run = landing.serialize_run(landing.lead_run_slim(conn))
        failed = landing.serialize_run(landing.lead_run_slim(conn, status="FAILED"))
    finally:
        conn.close()
    # The newest durable failure, while no later pull has succeeded — once one has,
    # the failure is history, not news.
    if failed and run and failed["id"] < run["id"]:
        failed = None
    return {"run": run, "watch": watch, "receipt": _receipt_summary(run), "failed": failed}


def recent_runs(limit=20):
    """The last crm.lead runs, any status, for the Data sources screen's
    "รอบที่ผ่านมา" (composed into the overview). Empty without a database."""
    from .. import landing
    if not db.configured():
        return []
    conn = db.connect()
    try:
        return landing.lead_runs(conn, limit)
    finally:
        conn.close()


@router.get("/v1/pipelines/crm-lead/landing-runs/{run_id}")
def landing_run(run_id: int, ledger_limit: int = Query(default=100, ge=1, le=500),
                ledger_offset: int = Query(default=0, ge=0)):
    """The durable receipt for one import_run: what landed, what it refused,
    and the paginated slice of the overwrite ledger the screen asked for."""
    from .. import landing
    _require_db()
    conn = db.connect()
    try:
        run = landing.get_run(conn, run_id)
    finally:
        conn.close()
    if run is None or run.get("source_system") != "ODOO":
        raise errors.not_found("import run")
    full = run.get("meta") or {}
    ledger = full.get("overwrite_ledger") or []
    # Slim, as every other run read: the proposal list and the old per-lead unmapped
    # list name other leads' keys — on runs before 2026-09-25, phone-<digits> keys.
    meta = {k: v for k, v in full.items() if k not in ("proposals", "unmapped_by_volt")}
    meta["proposals_total"] = len(full.get("proposals") or [])
    total = len(ledger)
    run["meta"] = dict(meta, overwrite_ledger=ledger[ledger_offset:ledger_offset + ledger_limit])
    run["ledger_total"] = total
    run["ledger_limit"] = ledger_limit
    run["ledger_offset"] = ledger_offset
    run["receipt"] = _receipt_summary({**run, "meta": {**meta, "overwrite_ledger": ledger}})
    return {"run": run}


@router.get("/v1/pipelines/crm-lead/provenance")
def provenance(volt_id: str = Query(...)):
    """Did THIS volt_id go in, and which rung does the book serve now?

    Read-only for every role: telling real from invented (R5) is an
    officer's daily need, not a manager's privilege. 404 names the id
    rather than inventing an empty answer.
    """
    from .. import landing
    _require_db()
    volt = (volt_id or "").strip()
    if not volt:
        raise errors.validation_failed([{
            "pointer": "/volt_id", "code": "required",
            "message": "volt_id is required",
            "message_th": "ต้องระบุ volt_id"}])
    conn = db.connect()
    try:
        found = landing.rows_for_volt(conn, volt)
    finally:
        conn.close()
    if not found["customers"] and not found["orders"]:
        raise errors.not_found("volt_id %s" % volt)
    return found


@router.get("/v1/pipelines/crm-lead/customers")
def landing_customers(data_source: str = Query(default=None),
                      q: str = Query(default=None),
                      limit: int = Query(default=50, ge=1, le=200),
                      offset: int = Query(default=0, ge=0)):
    """The registry filter §6 asked for: landed identities with no deliberate
    way to view them. Odoo rows carry no money by design, so they never reach
    /v1/cases — this is where they can be read."""
    from .. import landing
    if data_source not in (None, "", "SHEET", "ODOO"):
        raise errors.validation_failed([{
            "pointer": "/data_source", "code": "invalid",
            "message": 'data_source must be "SHEET" or "ODOO"',
            "message_th": "data_source ต้องเป็น SHEET หรือ ODOO"}])
    _require_db()
    conn = db.connect()
    try:
        page = landing.list_landing_customers(
            conn, data_source=data_source or None, q=q, limit=limit, offset=offset)
    finally:
        conn.close()
    return page


@router.post("/v1/pipelines/crm-lead:start", status_code=202)
async def start_crm_lead(request: Request, x_volt_role: str = Header(default="OFFICER")):
    """Answer at once with a uid to watch, and do the work on a thread.

    A 34k-row pull takes a minute and a half. Holding the request open for it gives
    the officer a spinner that cannot say whether anything is happening — which is
    the question they actually ask at eighty seconds.
    """
    audit.describe(act="CRM_LEAD_PIPELINE_RUN")
    _manager_only(x_volt_role)
    raw = await _body(request)
    mode = _read_mode(raw, "application/json" in (request.headers.get("content-type") or ""))
    uid = runs.start("odoo")
    from ..production_unit import enabled
    from ..durable_runs import WORKER_RUN
    if enabled():
        if not WORKER_RUN.get():
            from ..task_outbox import enqueue_request
            await run_in_threadpool(enqueue_request, request, uid, raw)
        else:
            await run_in_threadpool(service.run_odoo, uid, mode=mode)
        return JSONResponse(status_code=202, content={**runs.get(uid), "mode": mode})
    threading.Thread(target=service.run_odoo, args=(uid,),
                     kwargs={"mode": mode}, daemon=True).start()
    return JSONResponse(status_code=202, content={**runs.get(uid), "mode": mode})


@router.get("/v1/pipelines/crm-lead/runs/{uid}")
def get_run(uid: str):
    run = runs.get(uid)
    if run is None:
        raise errors.not_found("pipeline run")
    return run


@router.get("/v1/pipelines/crm-lead/schedule")
def get_schedule():
    from ..production_unit import enabled
    if enabled():
        from ..durable_schedule import state
        return state()
    return schedule_mod.state()


@router.put("/v1/pipelines/crm-lead/schedule")
def put_schedule(request: Request, body: dict = Body(default=None),
                 x_volt_role: str = Header(default="OFFICER")):
    audit.describe(act="CRM_LEAD_SCHEDULE_SET")
    _manager_only(x_volt_role)
    body = body or {}
    from ..production_unit import enabled
    if enabled():
        from .. import auth
        from ..durable_schedule import configure
        try: return configure(auth.resolve_session(request.scope), bool(body.get("enabled")), body.get("interval_minutes", 120))
        except (TypeError, ValueError):
            raise errors.validation_failed([{"pointer": "/interval_minutes", "code": "invalid_interval",
                                             "message": "Use 15–1440 minutes", "message_th": "กำหนดรอบ 15–1440 นาที"}])
    if body.get("enabled"):
        return schedule_mod.enable(body.get("interval_minutes",
                                            schedule_mod.INTERVAL_DEFAULT))
    return schedule_mod.disable()
