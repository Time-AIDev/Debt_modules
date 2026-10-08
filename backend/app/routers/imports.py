"""Ruling 71 — POST /v1/imports, GET /v1/imports, GET /v1/imports/{uid}.

The obvious shape — an `UploadFile` / `File(...)` parameter — cannot be built:
`python-multipart` is not installed, and FastAPI raises `RuntimeError` for that
parameter AT ROUTE-DECORATION TIME, i.e. inside `import app.main`. The whole app
would fail to start and every test would error at collection (demonstrated in
docs/design/round-5/data-flow/F-api.md §4.1). So this is a RAW request body, sent
by the browser as a plain `fetch(...)` body — never `FormData`, never multipart.

The handler is `async def` because the size cap has to be enforced WHILE the body
is being read (a `Content-Length` pre-check catches a declared-oversize body before
a byte is read; a running counter over the stream catches a chunked body that
omits or lies about its length) — that needs `await request.stream()`, which a
sync `def` handler cannot use. The actual parsing (XML for `.xlsx`, `csv` for
`.csv`) is CPU-bound and could block the event loop for a large file, so it runs in
the starlette threadpool via `run_in_threadpool` rather than inline on the loop —
satisfying the same concern leg F raised ("declare it def, not async def") without
giving up the streaming cap, which a plain `def` handler cannot enforce at all.
"""
import csv
import contextvars
import io
import re
import threading
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import audit
from .. import db
from .. import errors
from .. import imports as imports_domain
from ..pipelines import runs

router = APIRouter()

# The whole 47-block Drive render of the entire book is 1,281,402 bytes — 5 MB is
# ~4x the whole book and ~40x any single tab (F-api.md §4.1's own arithmetic).
MAX_BYTES = imports_domain.MAX_BYTES
MAX_MB = imports_domain.MAX_MB


def _refused(exc):
    return errors.validation_failed([{
        "pointer": exc.pointer, "code": "validation_failed",
        "message": exc.message, "message_th": exc.message_th, **exc.extensions}])


def upload_from_parts(request: Request):
    """The file named by `X-Volt-Upload` (sent earlier in parts), or None when the
    request carries its body the ordinary way. Shared with routers/pipelines.py."""
    upload_id = request.headers.get("x-volt-upload")
    if not upload_id:
        return None
    try:
        return imports_domain.take_upload(upload_id, request.headers.get("x-volt-officer"))
    except imports_domain.UploadRefused as exc:
        raise _refused(exc)


@router.post("/v1/imports/parts/{upload_id}/{index}")
async def put_upload_part(upload_id: str, index: int, of: int, request: Request):
    """One part of a file too big for one request (Cloud Run's 32 MiB body limit).
    The upload itself then names the parts with `X-Volt-Upload: <upload_id>`."""
    audit.describe(act="IMPORT_PART_RECEIVED", subject=("upload", upload_id), detail={"part": index, "of": of})
    try:
        imports_domain.check_part(upload_id, index, of)
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > imports_domain.PART_BYTES:
                break                     # put_part refuses it; nothing past the cap is read
        held = imports_domain.put_part(upload_id, index, of, bytes(data), request.headers.get("x-volt-officer"))
    except imports_domain.UploadRefused as exc:
        raise _refused(exc)
    return {"upload_id": upload_id, "received": held, "of": of}


@router.delete("/v1/imports/parts/{upload_id}")
def discard_upload_parts(upload_id: str, x_volt_officer: str = Header(default=None)):
    audit.describe(act="IMPORT_UPLOAD_ABORTED", subject=("upload", upload_id))
    return {"upload_id": upload_id,
            "discarded": imports_domain.discard_upload(upload_id, x_volt_officer)}


async def _read_raw(request: Request, run_uid=None):
    """The raw body under the size cap — create_import's own two-stage check, shared
    with the assignment upload (feedback-r2 TASK-117). Returns bytes; the caller
    refuses an empty body in its own words. A file sent in parts arrives whole."""
    joined = upload_from_parts(request)
    if joined is not None:
        if run_uid:
            runs.progress(run_uid, phase="uploading", uploaded_bytes=len(joined),
                          total_bytes=len(joined))
        return joined
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_BYTES:
                raise errors.validation_failed([{
                    "pointer": "/file", "code": "payload_too_large",
                    "message": "The file is %.1f MB; the cap is %d MB." % (
                        int(declared_length) / 1024 / 1024, MAX_MB),
                    "message_th": "ไฟล์ใหญ่เกิน %d MB — แยกแท็บแล้วอัปโหลดทีละไฟล์" % MAX_MB,
                    "cap_bytes": MAX_BYTES, "declared_bytes": int(declared_length)}])
        except ValueError:
            pass
    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BYTES:
            # A chunked body can omit or lie about Content-Length — this is the
            # running cap that catches it regardless of what the header said.
            raise errors.validation_failed([{
                "pointer": "/file", "code": "payload_too_large",
                "message": "The stream exceeded the %d MB cap while being read." % MAX_MB,
                "message_th": "ไฟล์ใหญ่เกิน %d MB — แยกแท็บแล้วอัปโหลดทีละไฟล์" % MAX_MB,
                "cap_bytes": MAX_BYTES}])
        chunks.append(chunk)
        if run_uid:
            runs.progress(run_uid, phase="uploading", uploaded_bytes=total,
                          total_bytes=int(declared_length) if declared_length and declared_length.isdigit() else None)
    return b"".join(chunks)


def _filename(header):
    """Sanitised and echoed back only — never used to open, write or route to a
    path (ruling 71's own line on this)."""
    if not header:
        return None
    return re.sub(r"[^\w\u0E00-\u0E7F.\- ()]", "", Path(urllib.parse.unquote(header)).name)[:120] or None


def _problem_payload(exc):
    if isinstance(exc, errors.Problem):
        return {"code": exc.code, "status": exc.status, "title": exc.title,
                "detail": exc.detail, "message_th": exc.message_th,
                "error_id": exc.error_id, "errors": exc.errors,
                "extensions": exc.extensions}
    if isinstance(exc, imports_domain.UploadRefused):
        return {"code": "validation_failed", "status": 422,
                "detail": exc.message, "message_th": exc.message_th,
                "errors": [{"pointer": exc.pointer, **exc.extensions}]}
    return {"code": "operation_failed", "status": 500,
            "detail": exc.__class__.__name__, "message_th": "ดำเนินการไม่สำเร็จ"}


def _validate_install_payload(payload):
    if payload.get("done_tabs_unread"):
        tabs = "; ".join("%s (missing: %s)" % (u["sheet"], ", ".join(u["missing"]) or "no customer rows")
                         for u in payload["done_tabs_unread"])
        raise errors.Problem(code="done_tab_unread", status=422, title="A Done tab was not read",
                             detail="The file carries %s but the importer could not read it; an older tab "
                                    "would stand in for it. Fix the header and upload again." % tabs,
                             message_th="อ่านแท็บ %s ไม่ได้ (หัวคอลัมน์เปลี่ยน) — ไม่นำเข้า เพื่อไม่ให้แท็บเก่ามาแทน "
                                        "แก้หัวคอลัมน์แล้ว upload ใหม่" % tabs,
                             error_id="DEBT-IMP-0423")
    if not imports_domain.can_install(payload):
        raise errors.Problem(code="sheet_incomplete", status=422, title="Not the book",
                             detail="No leasing tab with a customer on it — the book's contracts "
                                    "come from the leasing tabs",
                             message_th="ไม่พบแท็บสัญญาเช่าที่มีลูกค้า — นำเข้าไฟล์นี้เป็นสมุดงานไม่ได้",
                             error_id="DEBT-IMP-0422")
    if not db.configured():
        raise errors.Problem(code="database_required", status=503, title="No database configured",
                             detail="Installing the sheet lands it in the landing schema; set DATABASE_URL",
                             message_th="ต้องตั้งค่าฐานข้อมูลก่อนนำเข้า", error_id="DEBT-IMP-0503")


def _process_import(raw, filename, officer, role, install, confirm_retire, run_uid=None, profile=None):
    parsed_run_uid = None
    try:
        if profile:
            from .. import debt_imports
            if run_uid:
                runs.progress(run_uid, phase='parsing')
            if install:
                raise debt_imports.problem("profile_apply", "ตรวจตัวอย่างก่อน แล้วใช้คำสั่งยืนยันแถวที่เลือก")
            preview = debt_imports.stage(raw, filename, profile, officer or "officer")
            result = {"preview": preview, "counts": preview["counts"], "installed": False}
            if run_uid:
                runs.mark_committed(run_uid)
            return result
        if run_uid:
            runs.progress(run_uid, phase="parsing", processed=0, phase_total=None)
        run, payload = imports_domain.parse_upload(
            raw, filename, officer, role, True,
            on_progress=(lambda processed, phase_total: runs.progress(
                run_uid, phase="parsing", processed=processed, phase_total=phase_total)) if run_uid else None,
            checkpoint=(lambda: runs.checkpoint(run_uid)) if run_uid else None)
        parsed_run_uid = (run.get("run") or {}).get("uid")
        if db.configured():
            if run_uid:
                runs.checkpoint(run_uid)
                runs.progress(run_uid, phase="scanning", processed=0, phase_total=None)
            run["retire"] = imports_domain.retire_preview(payload)
        if not install:
            if run_uid:
                runs.mark_committed(run_uid)
            return run
        _validate_install_payload(payload)
        if run_uid:
            runs.checkpoint(run_uid)
            runs.progress(run_uid, phase="applying", processed=0, phase_total=None)
        try:
            installed = imports_domain.install(
                payload, confirm_retire,
                before_commit=(lambda: (runs.checkpoint(run_uid), runs.mark_committed(run_uid)))
                if run_uid else None)
        except imports_domain.InstallWouldRetire as exc:
            p = exc.preview
            tabs = ", ".join(p["dropped_tabs"])
            raise errors.Problem(
                code="install_would_retire", status=422, title="Would retire part of the book",
                detail="Installing this file retires %d of %d sheet customers%s; send confirm_retire=%d "
                       "to install it" % (p["customers"], p["live"],
                                          " and drops the %s tab(s)" % tabs if tabs else "",
                                          p["customers"]),
                message_th="ไฟล์นี้จะนำลูกค้า %d จาก %d รายออกจากสมุดงาน%s — ยืนยันจำนวนนี้ก่อนนำเข้า"
                           % (p["customers"], p["live"], " และไม่มีแท็บ %s" % tabs if tabs else ""),
                error_id="DEBT-IMP-0422", extensions={"retire": p})
        audit.describe(subject=("import", filename or run["run"]["uid"]),
                       detail={k: installed[k] for k in ("run_id", "customers", "contracts", "tracked", "retired")})
        run.update(installed=True, install=installed,
                   installed_note_th="นำเข้าเป็นสมุดงานแล้ว — สมุดงานใช้ไฟล์นี้ตั้งแต่ตอนนี้",
                   installed_note_en="Installed as the book — the book is served from this file now")
        return run
    except runs.RunCancelled:
        # parse_upload stages a preview in the user's durable state. Cancellation
        # after parsing but before commit must not leave that partial run behind.
        if parsed_run_uid:
            imports_domain.for_current().runs.pop(parsed_run_uid, None)
        raise


async def _run_background(uid, context, work, preview_only=False):
    def inside():
        result = work()
        # The request already returned, so tester_session's normal end-of-request
        # flush happened before this background mutation. Persist under the copied
        # authenticated principal before the run reports done.
        if not preview_only:
            from .. import import_sync, session
            with import_sync.session_lock():
                session.flush_current()
        return result

    def target():
        try:
            result = context.run(inside)
            runs.finish(uid, {"result": result})
        except runs.RunCancelled as exc:
            runs.fail(uid, exc)
        except Exception as exc:
            runs.fail(uid, _problem_payload(exc))
    from ..durable_runs import WORKER_RUN
    if WORKER_RUN.get():
        await run_in_threadpool(target)
    else:
        threading.Thread(target=target, name="volt-operation-%s" % uid, daemon=True).start()


@router.post("/v1/imports")
async def create_import(request: Request, install: bool = False, confirm_retire: int = None, profile: str = None,
                        x_volt_role: str = Header(default="OFFICER"),
                        x_volt_officer: str = Header(default=None),
                        x_volt_filename: str = Header(default=None)):
    """The check (every role) — and, with `?install=true`, the New Order Master
    installed as the book (MANAGER/OWNER; Arina 2026-09-24, reversing ruling 73). With a
    database, both say what installing would take out of the live book (`retire`); an
    install that retires more than a tenth of it, or a whole tab kind, needs that count
    echoed back as `confirm_retire`."""
    audit.describe(act="SHEET_INSTALLED" if install else "IMPORT_UPLOADED")
    if install:
        from .settings import require_manager
        require_manager(x_volt_role, "Installing the sheet as the book is a manager's act",
                        "เฉพาะผู้จัดการขึ้นไปนำเข้าชีตเป็นสมุดงานได้")
    raw = await _read_raw(request)

    if not raw:
        raise errors.validation_failed([{
            "pointer": "/file", "code": "required",
            "message": "The request body is empty.",
            "message_th": "ไฟล์ว่าง ไม่มีข้อมูลให้อ่าน"}])

    filename = _filename(x_volt_filename)

    try:
        return await run_in_threadpool(_process_import, raw, filename, x_volt_officer,
                                       x_volt_role, install, confirm_retire, None, profile)
    except imports_domain.UploadRefused as exc:
        raise _refused(exc)


@router.post("/v1/imports:start", status_code=202)
async def start_import(request: Request, install: bool = False, confirm_retire: int = None, profile: str = None,
                       x_volt_role: str = Header(default="OFFICER"),
                       x_volt_officer: str = Header(default=None),
                       x_volt_filename: str = Header(default=None)):
    """Start a cancellable New Order Master check/install and return immediately."""
    if install:
        from .settings import require_manager
        require_manager(x_volt_role, "Installing the sheet as the book is a manager's act",
                        "เฉพาะผู้จัดการขึ้นไปนำเข้าชีตเป็นสมุดงานได้")
    uid = runs.start("master-sheet")
    runs.progress(uid, phase="uploading")
    try:
        raw = await _read_raw(request, uid)
    except Exception as exc:
        runs.fail(uid, _problem_payload(exc))
        raise
    if not raw:
        problem = errors.validation_failed([{"pointer": "/file", "code": "required",
                                             "message": "The request body is empty.",
                                             "message_th": "ไฟล์ว่าง ไม่มีข้อมูลให้อ่าน"}])
        runs.fail(uid, _problem_payload(problem))
        raise problem
    filename = _filename(x_volt_filename)
    audit.describe(act="SHEET_INSTALLED" if install else "IMPORT_UPLOADED",
                   subject=("operation_run", uid), detail={"filename": filename})
    from ..production_unit import enabled
    from ..durable_runs import WORKER_RUN
    if enabled() and not WORKER_RUN.get():
        from ..task_outbox import enqueue_request
        await run_in_threadpool(enqueue_request, request, uid, raw)
        return JSONResponse(status_code=202, content=runs.get(uid))
    await _run_background(uid, contextvars.copy_context(), lambda: _process_import(
        raw, filename, x_volt_officer, x_volt_role, install, confirm_retire, uid, profile),
        preview_only=profile in ("debt_status", "contract_supplement") and not install)
    return JSONResponse(status_code=202, content=runs.get(uid))


@router.get("/v1/imports")
def list_imports():
    runs = imports_domain.list_current()
    return {"runs": runs, "meta": {"total": len(runs)}}


@router.get("/v1/imports/sheet/disagreements")
def sheet_disagreements():
    """Every served customer whose PEAK answer and "done collection" answer differ, by
    month (`month: null` is the current status) — the sheet panel's review list.
    Reading it changes nothing: PEAK keeps serving, the sheet keeps its word."""
    from .. import cases as cases_domain, journey
    rows = [{"customer_uid": c.uid, "name": c.display_name, "customer_no": c.customer_no, **d}
            for c in list(journey.book_customers()) + list(journey.identity_customers())
            for d in cases_domain.status_disagreements(c)]
    return {"rows": rows, "meta": {"total": len(rows), "customers": len({r["customer_uid"] for r in rows})}}


# --- feedback round 2: the assignment template (TASK-117, R-D default) --------------
# Declared BEFORE GET /v1/imports/{uid} below, or the literal path would be captured
# as a uid (FastAPI matches in declaration order).

ASSIGN_TEMPLATE_HEADER = ("volt_id", "customer_no", "officer")


def _assignment_rows(raw):
    """The template's rows, read through the SAME reader the import door uses —
    `sniff_kind` decides from the bytes, `read_xlsx` / `decode_csv` do the work
    (ruling 36: never a second parser)."""
    kind = imports_domain.sniff_kind(raw)
    if kind == "XLSX":
        sheets = imports_domain.read_xlsx(raw)
        return sheets[0]["rows"] if sheets else []
    if kind == "MAYBE_CSV":
        _encoding, text = imports_domain.decode_csv(raw)
        return [list(row) for row in csv.reader(io.StringIO(text))]
    raise imports_domain.UploadRefused(
        "/file", "Legacy .xls (OLE) files are not supported; save as .xlsx or .csv.",
        "รองรับเฉพาะไฟล์ .csv และ .xlsx")


def _template_indexes():
    """(customers by volt_id stem, customers by customer_no, officers by uid or
    display name) — built once from the served book, never per row."""
    from .. import journey, officers
    from ..pipelines import crm_lead as crm_lead_pipeline
    by_stem, by_no = {}, {}
    for customer in list(journey.book_customers()) + list(journey.identity_customers()):
        volt_id = getattr(customer, "volt_id", None)
        no = getattr(customer, "customer_no", None)
        if volt_id:
            by_stem.setdefault(crm_lead_pipeline.volt_stem(volt_id), customer.uid)
        if no:
            by_no.setdefault(str(no).strip(), customer.uid)
    officer_lookup = {}
    for row in officers.registry():
        officer_lookup[row["uid"]] = row["uid"]
        for name in (row.get("display_name_th"), row.get("display_name_en")):
            if name:
                officer_lookup.setdefault(str(name).strip(), row["uid"])
    return by_stem, by_no, officer_lookup


def _process_assignment(raw, filename, run_uid=None):
    if run_uid:
        runs.progress(run_uid, phase="parsing", processed=0, phase_total=None)
        runs.checkpoint(run_uid)
    rows = _assignment_rows(raw)
    data = [row for row in rows if any(str(cell).strip() for cell in row)]
    header = [str(cell).strip().lstrip("\ufeff").lower() for cell in (data[0][:3] if data else [])]
    if header != list(ASSIGN_TEMPLATE_HEADER):
        raise errors.validation_failed([{
            "pointer": "/header", "code": "header_invalid",
            "message": "The first row must be the header %s." % ", ".join(ASSIGN_TEMPLATE_HEADER),
            "message_th": "แถวแรกต้องเป็นหัวตาราง volt_id, customer_no, officer"}])

    from ..pipelines import crm_lead as crm_lead_pipeline
    by_stem, by_no, officer_lookup = _template_indexes()
    failures, assigned = [], []
    total = max(0, len(data) - 1)
    for n, row in enumerate(data[1:], start=2):
        if run_uid:
            runs.checkpoint(run_uid)
            runs.progress(run_uid, phase="parsing", processed=n - 1, phase_total=total)
        cells = [str(cell).strip() for cell in (list(row) + ["", "", ""])[:3]]
        volt_id, customer_no, officer = cells
        pointer = "/rows/%d" % n
        if not volt_id and not customer_no:
            failures.append({"pointer": pointer, "code": "customer_required",
                             "message": "Row %d names no customer (volt_id or customer_no)." % n,
                             "message_th": "แถวที่ %d ไม่ได้ระบุลูกค้า (volt_id หรือ customer_no)" % n})
            continue
        uid = (by_stem.get(crm_lead_pipeline.volt_stem(volt_id)) if volt_id else None) \
            or (by_no.get(customer_no) if customer_no else None)
        if uid is None:
            failures.append({"pointer": pointer, "code": "customer_unknown",
                             "message": "Row %d names a customer this system does not serve." % n,
                             "message_th": "แถวที่ %d ไม่พบลูกค้ารายนี้ในระบบ" % n})
            continue
        if any(a["uid"] == uid for a in assigned):
            failures.append({"pointer": pointer, "code": "duplicate",
                             "message": "Row %d repeats a customer already in this file." % n,
                             "message_th": "แถวที่ %d ซ้ำกับลูกค้าที่ระบุไปแล้วในไฟล์นี้" % n})
            continue
        officer_uid = officer_lookup.get(officer)
        if officer_uid is None:
            failures.append({"pointer": pointer, "code": "officer_unknown",
                             "message": "Row %d names an officer the registry does not serve." % n,
                             "message_th": "แถวที่ %d ไม่รู้จักเจ้าหน้าที่ที่ระบุ" % n})
            continue
        assigned.append({"uid": uid, "officer_uid": officer_uid})
    if failures:
        raise errors.validation_failed(failures)

    by_officer = {}
    for row in assigned:
        by_officer.setdefault(row["officer_uid"], []).append(row["uid"])
    audit.describe(act="CUSTOMERS_ASSIGNED", subject=("import", filename or "assignments"),
                   detail={"mode": "template", "count": len(assigned),
                           "officer_uids": sorted(by_officer)})

    def apply():
        from .settings import _assign_many
        for officer_uid, uids in by_officer.items():
            _assign_many(uids, officer_uid)

    if run_uid:
        runs.progress(run_uid, phase="applying", processed=0, phase_total=len(assigned))
        runs.commit(run_uid, apply)
    else:
        apply()
    return {"count": len(assigned), "officer_uids": sorted(by_officer),
            "assigned": [row["uid"] for row in assigned]}


@router.get("/v1/imports/assignments:template")
def assignment_template(x_volt_role: str = Header(default="OFFICER")):
    """R-D: the downloadable template — the header row and one example. Audited as a
    download because it leaves the system."""
    from .settings import require_manager
    require_manager(x_volt_role, "The assignment template is a manager's act",
                    "เฉพาะผู้จัดการขึ้นไปดาวน์โหลดเทมเพลตแบ่งงานได้")
    audit.describe(act="TEMPLATE_DOWNLOADED", subject=("template", "assignments"))
    rows = [list(ASSIGN_TEMPLATE_HEADER),
            ["28001000001_Example_Customer_VOLT", "28001000001", "nantapol"]]
    text = "\n".join(",".join(cell for cell in row) for row in rows) + "\n"
    return Response(content=text, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="assignments-template.csv"'})


@router.post("/v1/imports/assignments")
async def assignment_upload(request: Request, x_volt_role: str = Header(default="OFFICER"),
                            x_volt_filename: str = Header(default=None)):
    """R-D / R-C: read a filled template and assign every row, or refuse the whole
    file with every bad row named — all-or-nothing, like Q5's bulk assign."""
    from .settings import require_manager
    require_manager(x_volt_role, "The portfolio split is a manager's act",
                    "เฉพาะผู้จัดการขึ้นไปแบ่งพอร์ตได้")
    raw = await _read_raw(request)
    if not raw:
        raise errors.validation_failed([{
            "pointer": "/file", "code": "required",
            "message": "The request body is empty.",
            "message_th": "ไฟล์ว่าง ไม่มีข้อมูลให้อ่าน"}])
    filename = _filename(x_volt_filename)
    try:
        return await run_in_threadpool(_process_assignment, raw, filename)
    except imports_domain.UploadRefused as exc:
        raise _refused(exc)


@router.post("/v1/imports/assignments:start", status_code=202)
async def start_assignment_upload(request: Request, x_volt_role: str = Header(default="OFFICER"),
                                  x_volt_filename: str = Header(default=None)):
    from .settings import require_manager
    require_manager(x_volt_role, "The portfolio split is a manager's act",
                    "เฉพาะผู้จัดการขึ้นไปแบ่งพอร์ตได้")
    uid = runs.start("assignment")
    runs.progress(uid, phase="uploading")
    try:
        raw = await _read_raw(request, uid)
    except Exception as exc:
        runs.fail(uid, _problem_payload(exc))
        raise
    if not raw:
        problem = errors.validation_failed([{"pointer": "/file", "code": "required",
                                             "message": "The request body is empty.",
                                             "message_th": "ไฟล์ว่าง ไม่มีข้อมูลให้อ่าน"}])
        runs.fail(uid, _problem_payload(problem))
        raise problem
    filename = _filename(x_volt_filename)
    audit.describe(act="CUSTOMERS_ASSIGNED", subject=("operation_run", uid),
                   detail={"filename": filename})
    from ..production_unit import enabled
    from ..durable_runs import WORKER_RUN
    if enabled() and not WORKER_RUN.get():
        from ..task_outbox import enqueue_request
        await run_in_threadpool(enqueue_request, request, uid, raw)
        return JSONResponse(status_code=202, content=runs.get(uid))
    await _run_background(uid, contextvars.copy_context(),
                    lambda: _process_assignment(raw, filename, uid))
    return JSONResponse(status_code=202, content=runs.get(uid))


@router.get("/v1/imports/{uid}")
def get_import(uid: str):
    run = imports_domain.get_current(uid)
    if run is None:
        raise errors.not_found("import run")
    return run
