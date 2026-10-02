"""Evidence files on a contact or a note (vault note 10 §3 WP4).

Design F7/F8: guard first (format rules), then scan (a virus scanner port), then
store — an infected file is never stored, and a configured-but-unreachable scanner
refuses rather than passing silently. Raw-body upload, same shape as
`routers/imports.py`: `X-Volt-Filename` beside the body, a `Content-Length`
pre-check plus a running cap over `request.stream()` — no `UploadFile`, because
`python-multipart` is not installed and that parameter stops the app booting.

Controller ruling (2026-09-15, ledgered): the brief's own snippet signed with
`officers.sign(body, officer, role)`, but that returns a TUPLE (by, by_role) —
storing `uploaded_by` as a tuple would make the uploader unable to delete their own
file. This signs with the case router's `who(body, header)`
(`backend/app/routers/today.py:27-36`), which returns the acting officer as a
plain string, for both the upload (`uploaded_by`) and the delete (uploader check).
`officers` is never imported here for signing.
"""
import contextvars
import threading
from urllib.parse import quote, unquote

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import audit, errors
from ..attachments import guard, scanner, store
from ..config import settings
from ..pipelines import runs
from .imports import upload_from_parts
from .today import who

router = APIRouter()


async def _body(request, run_uid=None):
    """Content-Length pre-check, then a running cap over the stream itself — the
    same two-layer shape as `routers/imports.py`'s own upload: the header catches a
    declared-oversize body before a byte is read, the running counter catches a
    chunked body that omits or lies about its length."""
    joined = upload_from_parts(request)
    if joined is not None:
        if len(joined) > settings.attachment_max_bytes:
            raise errors.validation_failed([{
                "pointer": "/file", "code": "too_large",
                "message": "the joined upload exceeded the attachment cap",
                "message_th": "ไฟล์ใหญ่เกิน %d MB" % (settings.attachment_max_bytes // (1024 * 1024))}])
        if run_uid:
            runs.progress(run_uid, phase="uploading", uploaded_bytes=len(joined),
                          total_bytes=len(joined))
        return joined
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > settings.attachment_max_bytes:
                raise errors.validation_failed([{
                    "pointer": "/file", "code": "too_large",
                    "message": "%d bytes; the cap is %d" % (int(declared), settings.attachment_max_bytes),
                    "message_th": "ไฟล์ใหญ่เกิน %d MB" % (settings.attachment_max_bytes // (1024 * 1024))}])
        except ValueError:
            pass
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > settings.attachment_max_bytes:
            raise errors.validation_failed([{
                "pointer": "/file", "code": "too_large",
                "message": "the stream exceeded the attachment cap",
                "message_th": "ไฟล์ใหญ่เกิน %d MB" % (settings.attachment_max_bytes // (1024 * 1024))}])
        chunks.append(chunk)
        if run_uid:
            runs.progress(run_uid, phase="uploading", uploaded_bytes=total,
                          total_bytes=int(declared) if declared and declared.isdigit() else None)
    return b"".join(chunks)


def _problem(exc):
    if isinstance(exc, errors.Problem):
        return {"code": exc.code, "status": exc.status, "detail": exc.detail,
                "message_th": exc.message_th, "error_id": exc.error_id,
                "errors": exc.errors, "extensions": exc.extensions}
    if isinstance(exc, guard.Refused):
        return {"code": exc.code, "status": 422, "detail": exc.detail,
                "message_th": exc.detail_th}
    if isinstance(exc, scanner.Infected):
        return {"code": "file_infected", "status": 422,
                "detail": "the scanner found %s" % exc.signature,
                "message_th": "โปรแกรมสแกนพบไวรัส (%s) — ไฟล์ไม่ถูกเก็บ" % exc.signature}
    if isinstance(exc, scanner.ScannerUnavailable):
        return {"code": "scanner_unavailable", "status": 503,
                "detail": str(exc), "message_th": "โปรแกรมสแกนไวรัสไม่พร้อมใช้งาน"}
    return {"code": "operation_failed", "status": 500,
            "detail": exc.__class__.__name__,
            "message_th": "ดำเนินการไม่สำเร็จ"}


def _process_upload(uid, raw, filename, attach_to, by):
    try:
        runs.progress(uid, phase="parsing", processed=0, phase_total=1)
        runs.checkpoint(uid)
        meta = guard.check(raw, unquote(filename or ""))
        runs.progress(uid, phase="parsing", processed=1, phase_total=1)
        runs.checkpoint(uid)
        runs.progress(uid, phase="scanning", processed=0, phase_total=1)
        scanned = scanner.scan(raw)
        runs.progress(uid, phase="scanning", processed=1, phase_total=1)
        runs.checkpoint(uid)
        runs.progress(uid, phase="applying", processed=0, phase_total=1)

        def apply():
            record = store.put(meta, raw, by, scanned)
            if attach_to:
                record = store.attach(record["uid"], attach_to.strip()[:80]) or record
            return record

        record = runs.commit(uid, apply)
        from .. import import_sync, session
        with import_sync.session_lock():
            session.flush_current()
        runs.finish(uid, {"result": {"attachment": record}})
    except runs.RunCancelled as exc:
        runs.fail(uid, exc)
    except Exception as exc:
        runs.fail(uid, _problem(exc))


@router.post("/v1/attachments", status_code=201)
async def upload(request: Request, x_volt_role: str = Header(default="OFFICER"),
                 x_volt_officer: str = Header(default=None), x_volt_filename: str = Header(default=None),
                 x_volt_attach_to: str = Header(default=None)):
    raw = await _body(request)
    # Task 25a: the browser sends X-Volt-Filename: encodeURIComponent(file.name), so
    # it arrives percent-encoded — decode it exactly once, here, before it reaches
    # guard.check (which still sanitises, keeping the Thai block) so a Thai file
    # name is stored and served back decoded, not as hex.
    try:
        meta = guard.check(raw, unquote(x_volt_filename or ""))
    except guard.Refused as exc:
        raise errors.validation_failed([{"pointer": "/file", "code": exc.code, "message": exc.detail,
                                         "message_th": exc.detail_th, "rule": exc.rule}])
    try:
        scanned = scanner.scan(raw)
    except scanner.Infected as exc:
        raise errors.validation_failed([{"pointer": "/file", "code": "file_infected",
                                         "message": "the scanner found %s" % exc.signature,
                                         "message_th": "โปรแกรมสแกนพบไวรัส (%s) — ไฟล์ไม่ถูกเก็บ" % exc.signature}])
    except scanner.ScannerUnavailable as exc:
        raise errors.Problem(code="scanner_unavailable", status=503, title="Virus scanner unavailable",
                             detail=str(exc),
                             message_th="โปรแกรมสแกนไวรัสตั้งค่าไว้แต่ติดต่อไม่ได้ — ไม่รับไฟล์จนกว่าจะกลับมา",
                             error_id="DEBT-ATT-0503", retryable=True)
    by = who({}, x_volt_officer)
    record = store.put(meta, raw, by, scanned)
    if x_volt_attach_to:
        record = store.attach(record["uid"], x_volt_attach_to.strip()[:80]) or record
    audit.describe(act="ATTACHMENT_UPLOADED", subject=("attachment", record["uid"]),
                   detail={"kind": meta["kind"], "size": meta["size"], "sha256": meta["sha256"],
                           "scan": scanned["state"], "attached_to": record.get("attached_to")})
    return {"attachment": record}


@router.post("/v1/attachments:start", status_code=202)
async def start_upload(request: Request, x_volt_role: str = Header(default="OFFICER"),
                       x_volt_officer: str = Header(default=None),
                       x_volt_filename: str = Header(default=None),
                       x_volt_attach_to: str = Header(default=None)):
    uid = runs.start("attachment")
    runs.progress(uid, phase="uploading")
    try:
        raw = await _body(request, uid)
    except Exception as exc:
        runs.fail(uid, _problem(exc))
        raise
    by = who({}, x_volt_officer)
    audit.describe(act="ATTACHMENT_UPLOADED", subject=("operation_run", uid),
                   detail={"filename": unquote(x_volt_filename or ""),
                           "attached_to": x_volt_attach_to})
    context = contextvars.copy_context()
    from ..production_unit import enabled
    from ..durable_runs import WORKER_RUN
    if enabled():
        if not WORKER_RUN.get():
            from ..task_outbox import enqueue_request
            await run_in_threadpool(enqueue_request, request, uid, raw)
        else:
            await run_in_threadpool(_process_upload, uid, raw, x_volt_filename, x_volt_attach_to, by)
        return JSONResponse(status_code=202, content=runs.get(uid))
    threading.Thread(
        target=lambda: context.run(_process_upload, uid, raw, x_volt_filename,
                                   x_volt_attach_to, by),
        name="volt-operation-%s" % uid, daemon=True).start()
    return JSONResponse(status_code=202, content=runs.get(uid))


@router.post("/v1/attachments/{uid}:download")
def download(uid: str):
    found = store.get(uid)
    if found is None:
        raise errors.not_found("attachment")
    record, raw = found
    audit.describe(act="ATTACHMENT_DOWNLOADED", subject=("attachment", uid), detail={"filename": record["filename"]})
    return Response(content=raw, media_type=record["content_type"], headers={
        "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(record["filename"]),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "Cache-Control": "private, no-store",
    })


@router.post("/v1/attachments/{uid}:delete")
def delete(uid: str, x_volt_role: str = Header(default="OFFICER"), x_volt_officer: str = Header(default=None)):
    found = store.get(uid)
    if found is None:
        raise errors.not_found("attachment")
    record = found[0]
    by = who({}, x_volt_officer)
    if record["uploaded_by"] != by and (x_volt_role or "").upper() not in ("MANAGER", "OWNER"):
        raise errors.Problem(code="forbidden", status=403, title="Not yours to delete",
                             detail="only the uploader or a Manager may delete an attachment",
                             message_th="ลบได้เฉพาะผู้อัปโหลดหรือผู้จัดการ", error_id="DEBT-IAM-0403")
    gone = store.delete(uid, by)
    audit.describe(act="ATTACHMENT_DELETED", subject=("attachment", uid), detail={"filename": record["filename"]})
    return {"attachment": gone}


@router.get("/v1/attachments")
def list_attachments(attached_to: str = Query(...)):
    return {"attachments": store.list_for(attached_to)}
