"""The PEAK report run sequence, once (the same shape as service.py for crm.lead).

Every exit goes through the registry. The indexes the ladder needs are built here,
from the book as it is served right now and from the ODOO rows in landing, so the
matcher itself stays pure.
"""
import hashlib
import logging
import time
import traceback
from pathlib import Path

from sqlalchemy import text

from .. import db, journey, landing
from ..integrations import peak_reports
from . import peak_candidates, peak_links, peak_match, peak_report, peak_writer, runs

KIND = "peak-report"
KIND_RECEIPT = "peak-receipt"
log = logging.getLogger(__name__)
_APP_ROOT = Path(__file__).resolve().parents[1]

# One PEAK run at a time: the write takes peak_writer's lock at session level on its
# own connection (the applies take it per transaction).
PEAK_LOCK_KEY = peak_writer.PEAK_LOCK_KEY
RUN_IN_PROGRESS_TH = peak_writer.RUN_IN_PROGRESS_TH
DUPLICATE_TH = ("ไฟล์นี้อยู่ในรอบที่ยังไม่ได้ใช้แล้ว (รอบ %s) — เปิดรายการรอบล่าสุดแล้วกด "
                "'ใช้รายงานนี้' ได้เลย ไม่ต้องอัปโหลดซ้ำ")

# Final review I4: an unexpected failure's own message can carry what the report
# carried — a customer's name, a 13-digit id. The run view (and so :run's 500 and the
# polled run) says which exception class failed and nothing more; so does the log.
FAILED_DETAIL = "The PEAK report run failed (%s)"
FAILED_DETAIL_TH = "การประมวลผลรายงาน PEAK ล้มเหลว — ลองใหม่อีกครั้ง หรือแจ้งผู้ดูแลระบบ"


def _failure_location(exc):
    """Return the final application frame without values from the exception."""
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        try:
            relative = Path(frame.filename).resolve().relative_to(_APP_ROOT)
        except ValueError:
            continue
        module = "app." + relative.with_suffix("").as_posix().replace("/", ".")
        return "%s:%s:%d" % (module, frame.name, frame.lineno)
    return "unavailable"


def _log_unexpected(uid, exc):
    run = runs.get(uid) or {}
    log.error(
        "PEAK receipt run failed run_uid=%s phase=%s exception_class=%s failure_location=%s",
        uid, run.get("phase") or "unknown", exc.__class__.__name__, _failure_location(exc))


class PipelineRefused(Exception):
    def __init__(self, problem):
        super().__init__(problem.get("detail") or problem.get("code"))
        self.problem = problem


def _end_read_tx(conn):
    """A plain SELECT on this connection may have begun a transaction (SQLAlchemy
    autobegin), and `with conn.begin()` refuses when one is already open. Reads are
    done with by the time this is called, so rolling back costs nothing; it is also
    what keeps the function honest under a test harness that hands every db.connect()
    the SAME connection."""
    if conn.in_transaction():
        conn.rollback()


def _duplicate_staged(fingerprint, source=None):
    """The id of an OK, NOT-applied run carrying the same file bytes, or None.

    Refusing the re-upload of a staged file is the honest answer — its rows are
    already waiting to be applied. A file whose run was ALREADY APPLIED is not a
    duplicate: the `already_applied` refusal itself tells the caller to upload the
    report again to re-apply it, and this check must not close that path."""
    if not fingerprint or not db.configured():
        return None
    conn = db.connect()
    try:
        _end_read_tx(conn)
        with conn.begin():
            row = conn.execute(text(
                "select id from landing.import_run "
                "where source_system = :s and status = 'OK' and not (meta ? 'applied') "
                "and meta->>'fingerprint' = :f order by id desc limit 1"),
                {"s": source or peak_writer.SOURCE, "f": fingerprint}).first()
            return row[0] if row else None
    finally:
        conn.close()


def _open_durable_run(filename, fingerprint, source=None):
    """A RUNNING run row committed BEFORE the write, so a failure later has a
    durable record. The write's own transaction commits it to OK or rolls back to
    this state, which _fail_durable then marks FAILED (sync audit, 2026-09-20)."""
    if not db.configured():
        return None
    conn = db.connect()
    try:
        _end_read_tx(conn)
        with conn.begin():
            return landing.start_run(conn, source or peak_writer.SOURCE, meta={
                "door": "upload", "filename": filename, "fingerprint": fingerprint})
    finally:
        conn.close()


def _fail_durable(run_id, problem):
    if run_id is None:
        return
    try:
        conn = db.connect()
        try:
            _end_read_tx(conn)
            with conn.begin():
                landing.finish_run(conn, run_id, "FAILED",
                                   note="%s: %s" % (problem.get("code"),
                                                    problem.get("detail") or ""))
        finally:
            conn.close()
    except Exception as exc:                      # noqa: BLE001 — the run's own view still fails
        log.error("PEAK run %s could not be marked failed (%s)", run_id, exc.__class__.__name__)


def _identities(customers):
    """D02 / TASK-208: the Odoo side of the conflict compare, per customer_no — the
    served identity's own fields, read once from the same list the index was built
    from. Never a second read of the book."""
    out = {}
    for c in customers:
        no = getattr(c, "customer_no", None)
        if not no:
            continue
        sheet = getattr(c, "sheet", None)
        sheet = sheet if isinstance(sheet, dict) else {}
        out[str(no)] = {
            "name_th": sheet.get("name_th") or getattr(c, "display_name", None),
            "name_roman": getattr(c, "name_roman", None),
            "volt_id": getattr(c, "volt_id", None),
            "customer_no": no,
            "product": getattr(c, "product", None),
            "order": sheet.get("order") or {},
        }
    return out


def receipt_match_verdict(receipt, invoice, identity):
    """Require both the referenced invoice and independently matched customer.

    A reference is not proof of ownership: a typo can point at somebody else's
    invoice.  Conversely, a customer match without an invoice is reviewable cash,
    not an allocation target.
    """
    ref = (receipt.get("invoice_ref") or "").strip()
    if invoice is None:
        if identity.get("verdict") == "EXACT":
            return {"verdict": "CANDIDATE",
                    "rule": "INVOICE_NOT_FOUND" if ref else "INVOICE_REF_REQUIRED",
                    "customer_no": identity.get("customer_no"), "invoice_doc_no": None,
                    "candidates": peak_candidates.merge(peak_candidates.make(
                        identity.get("customer_no"), identity.get("rule"), receipt.get("contact_code")))}
        return dict(identity, invoice_doc_no=None,
                    candidates=peak_candidates.merge(identity.get("candidates") or []))
    invoice_customer = invoice.get("customer_no") or invoice.get("ladder_customer_no")
    identity_customer = identity.get("customer_no") if identity.get("verdict") == "EXACT" else None
    if not invoice_customer or not identity_customer or str(invoice_customer) != str(identity_customer):
        invoice_candidate = peak_candidates.make(invoice_customer, "INVOICE_REF_CUSTOMER", ref)
        identity_candidate = peak_candidates.make(
            identity_customer, identity.get("rule"), receipt.get("contact_code"))
        return {"verdict": "CANDIDATE", "rule": "INVOICE_CUSTOMER_MISMATCH",
                "customer_no": identity_customer, "invoice_doc_no": None,
                "candidates": peak_candidates.merge(invoice_candidate, identity_candidate,
                                                     identity.get("candidates") or [])}
    return {"verdict": "EXACT", "rule": "INVOICE_REF_AND_CUSTOMER",
            "customer_no": invoice_customer, "invoice_doc_no": ref, "candidates": []}


def _receipt_verdicts(conn, parsed, on_progress=None):
    """Q6 (TASK-203): the receipt's own matching order, in one place.

    1. `invoice_ref` equals a doc_no of the last APPLIED invoice run → EXACT by
       INVOICE_REF; the customer is that invoice's served customer (its stored
       customer_no, else the ladder's own without links — the register is read again
       by invoices_for_book at read time).
    2. else the identity ladder on the contact code (with the link register), the
       same `match_one` the invoice run uses.
    3. else UNMATCHED — landed and reviewable, never dropped.
    """
    applied = peak_writer.last_run(conn, applied=True)
    invoices = {}
    if applied is not None:
        rows = conn.execute(text(
            "select doc_no, customer_no, ladder_customer_no from landing.peak_invoice "
            "where import_run_id = :r"), {"r": applied["id"]}).mappings().all()
        invoices = {r["doc_no"]: r for r in rows}
    book = peak_match.build_book_index(
        list(journey.book_customers()) + list(journey.identity_customers()))
    odoo = peak_match.build_odoo_index(peak_writer.odoo_phone_rows(conn))
    links = peak_links.load(conn)
    verdicts = []
    total = len(parsed["receipts"])
    if on_progress and total == 0:
        on_progress(0, 0)
    for processed, rec in enumerate(parsed["receipts"], start=1):
        ref = (rec.get("invoice_ref") or "").strip()
        hit = invoices.get(ref) if ref else None
        own = peak_match.match_one({"contact_code": rec.get("contact_code"), "reference": None,
                                    "customer_name": rec.get("customer_name")}, book, odoo, links)
        verdicts.append(receipt_match_verdict(rec, hit, own))
        if on_progress and (processed % 500 == 0 or processed == total):
            on_progress(processed, total)
    return verdicts


def _land(uid, parsed, filename, fingerprint=None, kind="report", stage_timings=None):
    if not db.configured():
        raise PipelineRefused({"code": "database_required",
                               "detail": "The PEAK report lands in the landing schema; set DATABASE_URL"})
    source = peak_writer.SOURCE if kind == "report" else peak_writer.RECEIPT_SOURCE
    staged = _duplicate_staged(fingerprint, source=source)
    if staged:
        raise PipelineRefused({"code": "peak_duplicate_report",
                               "detail": "the same file is already staged as run %s" % staged,
                               "detail_th": DUPLICATE_TH % staged,
                               "run_id": staged})
    # A RUNNING run row committed before the write: a failure later leaves a durable
    # FAILED row instead of dying with the process (sync audit, 2026-09-20).
    run_id = _open_durable_run(filename, fingerprint, source=source)
    conn = db.connect()
    locked = False
    try:
        _end_read_tx(conn)
        locked = bool(conn.execute(text("select pg_try_advisory_lock(%d)" % PEAK_LOCK_KEY)).scalar())
        # end the implicit transaction the lock read opened; the lock itself is
        # session-level and survives the commit, and the write wants conn.begin().
        conn.commit()
        if not locked:
            # the outer handler marks the durable row FAILED before re-raising
            raise PipelineRefused({"code": "peak_run_in_progress",
                                   "detail": "another PEAK report run is in progress",
                                   "detail_th": RUN_IN_PROGRESS_TH})
        # Fix-all P9 (M7): a run whose process died mid-write stayed RUNNING for ever.
        # Holding the lock, no other PEAK write is running, so an old RUNNING row is dead.
        _end_read_tx(conn)
        with conn.begin():
            for source_system in (peak_writer.SOURCE, peak_writer.RECEIPT_SOURCE):
                landing.sweep_running(conn, source_system, 30)
        with conn.begin():
            runs.checkpoint(uid)
            if kind == "receipt":
                matching_started = time.perf_counter()
                verdicts = _receipt_verdicts(
                    conn, parsed,
                    on_progress=lambda processed, total: (
                        runs.checkpoint(uid),
                        runs.progress(uid, phase="parsing", processed=processed,
                                      phase_total=total),
                    )[-1])
                if stage_timings is not None:
                    stage_timings["matching_ms"] = round((time.perf_counter() - matching_started) * 1000)
                runs.progress(uid, phase="writing", processed=0,
                              phase_total=len(parsed["receipts"]))
                writing_started = time.perf_counter()
                result = peak_writer.write_receipts(
                    conn, parsed, verdicts, door="upload", filename=filename,
                    on_progress=lambda **kw: (
                        runs.checkpoint(uid), runs.progress(uid, **kw))[1],
                    run_id=run_id, fingerprint=fingerprint)
                if stage_timings is not None:
                    stage_timings["writing_ms"] = round((time.perf_counter() - writing_started) * 1000)
            else:
                # The served book's identities ride beside the contract holders (the
                # 2026-09-19 ruling made crm.lead the served book, and most PEAK contact
                # codes are its 11-digit CRM ids or V-ids). Matching them is what makes
                # the reconciliation real on that mode; attaching money still needs a
                # contract an identity does not have, so an identity match lands the
                # facts and leaves the engine invoices untouched.
                customers = list(journey.book_customers()) + list(journey.identity_customers())
                book = peak_match.build_book_index(customers)
                odoo = peak_match.build_odoo_index(peak_writer.odoo_phone_rows(conn))
                links = peak_links.load(conn)
                verdicts = peak_match.match(parsed["invoices"], book, odoo, links)
                runs.checkpoint(uid)
                # Final review C1: the same ladder WITHOUT the register, stored per row, so
                # the book's read lets an active link decide at read time and falls back to
                # this when the link is retired. Same pure inputs; no id is added to them.
                ladder = peak_match.match(parsed["invoices"], book, odoo, {})
                result = peak_writer.write(
                    conn, parsed, verdicts, door="upload", filename=filename,
                    on_progress=lambda **kw: (
                        runs.checkpoint(uid), runs.progress(uid, **kw))[1],
                    ladder=ladder, run_id=run_id, fingerprint=fingerprint,
                    identities=_identities(customers))
            runs.checkpoint(uid)
            runs.mark_committed(uid)
        return result
    except Exception as exc:                      # noqa: BLE001 — the durable row must say FAILED
        if run_id is not None:
            # Fix-all P6 (K5): the note is served on last-run; an exception's own text can
            # quote a name, a 13-digit id or SQL. A refusal says its code, anything else
            # says which class failed and nothing more.
            _fail_durable(run_id, exc.problem if isinstance(exc, PipelineRefused)
                          else {"code": "pipeline_failed", "detail": FAILED_DETAIL % exc.__class__.__name__})
        raise
    finally:
        if locked:
            try:
                conn.execute(text("select pg_advisory_unlock(%d)" % PEAK_LOCK_KEY))
                conn.commit()
            except Exception:                     # noqa: BLE001 — closing the connection releases it
                pass
        conn.close()


def run_upload(raw, filename, uid=None):
    uid = uid or runs.start(KIND)
    fingerprint = hashlib.sha256(raw).hexdigest()
    try:
        runs.progress(uid, phase="reading", processed=0, phase_total=None)
        runs.checkpoint(uid)
        parsed = peak_report.parse(raw, filename)
        # invoices for both read and total: 7,998 lines against 7,638 invoices
        # would show the progress bar past 100% (RunProgress.jsx does read / total).
        runs.progress(uid, read=len(parsed["invoices"]), total=len(parsed["invoices"]))
        runs.checkpoint(uid)
        result = _land(uid, parsed, filename, fingerprint=fingerprint)
    except peak_report.ReportError as exc:
        runs.fail(uid, {"code": exc.code, "detail": exc.detail, "detail_th": exc.detail_th,
                        "schema": exc.schema})
    except PipelineRefused as exc:
        runs.fail(uid, exc.problem)
    except Exception as exc:                      # noqa: BLE001 — recorded, never swallowed
        name = exc.__class__.__name__
        log.error("PEAK report run failed (%s)", name)
        runs.fail(uid, {"code": "pipeline_failed", "detail": FAILED_DETAIL % name, "detail_th": FAILED_DETAIL_TH})
    else:
        # "landed" is the invoices actually written, so the bar's own landed
        # number matches what runs.progress already reported as read/total.
        runs.finish(uid, dict(result, landed=result["invoices"]))
    return runs.get(uid)


def run_receipt_upload(raw, filename, uid=None):
    """Q6 (TASK-203): the receipt report's own run — same shape as run_upload, its
    own parser, its own landing table and its own last-applied."""
    from . import peak_receipt
    uid = uid or runs.start(KIND_RECEIPT)
    fingerprint = hashlib.sha256(raw).hexdigest()
    stage_timings = {}
    try:
        runs.progress(uid, phase="reading", processed=0, phase_total=None)
        runs.checkpoint(uid)
        reading_started = time.perf_counter()
        parsed = peak_receipt.parse(raw, filename)
        runs.checkpoint(uid)
        stage_timings["reading_ms"] = round((time.perf_counter() - reading_started) * 1000)
        receipts = len(parsed["receipts"])
        runs.progress(uid, phase="matching", processed=0, phase_total=receipts,
                      read=receipts, total=receipts)
        result = _land(uid, parsed, filename, fingerprint=fingerprint, kind="receipt",
                       stage_timings=stage_timings)
    except peak_report.ReportError as exc:
        runs.fail(uid, {"code": exc.code, "detail": exc.detail, "detail_th": exc.detail_th,
                        "schema": exc.schema})
    except PipelineRefused as exc:
        runs.fail(uid, exc.problem)
    except Exception as exc:                      # noqa: BLE001 — recorded, never swallowed
        name = exc.__class__.__name__
        _log_unexpected(uid, exc)
        runs.fail(uid, {"code": "pipeline_failed", "detail": FAILED_DETAIL % name, "detail_th": FAILED_DETAIL_TH})
    else:
        runs.finish(uid, dict(result, landed=result["receipts"]))
        log.info(
            "PEAK receipt run completed run_uid=%s receipts=%d reading_ms=%d matching_ms=%d writing_ms=%d",
            uid, receipts, stage_timings.get("reading_ms", 0),
            stage_timings.get("matching_ms", 0), stage_timings.get("writing_ms", 0))
    return runs.get(uid)


ADAPTER_MISSING_TH = ("PEAK API ตอบข้อมูลมา แต่ยังไม่มีตัวแปลงข้อมูลที่ตรวจกับเอกสารของ PEAK "
                      "ระบบจึงไม่นำเข้า — ใช้การอัปโหลดไฟล์รายงานไปก่อน")


def run_api(since=None, instance="EPC"):
    """Door 2 (WP5, F19). Asks the port and REFUSES before any run starts — no registry
    entry, no import_run, no landing row — because nothing verified can be pulled yet.

    If the port ever answers (an endpoint verified and an adapter written in
    integrations/peak_reports.py), this still refuses with adapter_missing until the
    mapping from PEAK's documented payload onto peak_report's invoice record is written
    and tested here. Never a pretend run."""
    try:
        peak_reports.list_invoices(since, instance)
    except peak_reports.PeakReportApiError as exc:
        raise PipelineRefused(exc.problem())
    raise PipelineRefused({"code": "adapter_missing",
                           "detail": "The PEAK report API answered, but no adapter maps its payload onto the report record",
                           "detail_th": ADAPTER_MISSING_TH})
