"""The run sequence, once. The button (:run, :start), the 2-hour timer, the Cloud
Run job and the boot refresh all call run_odoo — a second copy for any of them would
be ruling 36's second-pattern MAJOR on the one sequence that matters.

Every exit goes through the registry AND the durable run row: a RUNNING
landing.import_run is committed before the fetch, the landing finishes it OK, and
any failure finishes it FAILED with a code. A run that ends without saying which of
the two it was is the dishonesty the whole pipeline is built against.
"""
import logging
import json
import uuid

import httpx
from sqlalchemy import text

from .. import db, landing
from ..integrations import odoo as odoo_client
from . import crm_lead, ingress, rules as rules_mod, runs, writer

log = logging.getLogger(__name__)

# One crm.lead landing at a time, across processes and instances: the in-process
# timer, the Cloud Run job and a Manager's pull could otherwise land the same 34k
# leads twice over (2026-09-24 review, finding 2).
CRM_LEAD_LOCK_KEY = 0x43524D4C  # "CRML"
RUN_IN_PROGRESS_TH = "มีการดึง Odoo crm.lead กำลังนำเข้าอยู่ — รอให้รอบปัจจุบันจบก่อนแล้วลองใหม่"
TOO_MUCH_TO_RETIRE_TH = ("การดึงรอบนี้จะเลิกใช้ลูกค้าจาก Odoo เกิน 20% ของที่ให้บริการอยู่ — ระบบจึงไม่นำเข้า "
                         "ตรวจข้อมูลใน Odoo ก่อน หรือให้ผู้จัดการดึงแบบ OVERWRITE")
STALE_RUNNING_MINUTES = 30


class PipelineRefused(Exception):
    def __init__(self, problem):
        super().__init__(problem.get("detail") or problem.get("code"))
        self.problem = problem


def _for_memory(result, keep=100):
    """The volatile watch-registry keeps a preview, never the whole ledger.

    The full ledger lives on import_run.meta (the durable receipt). Keeping
    34k entries times KEEP=20 runs in process memory is how a laptop session
    quietly grows to tens of megabytes; the poll response would also breach
    the 1 MiB body cap the API surface fixes.
    """
    trimmed = dict(result)
    ledger = result.get("ledger") or []
    if len(ledger) > keep:
        trimmed["ledger"] = ledger[:keep]
        trimmed["ledger_truncated"] = True
        trimmed["ledger_total"] = len(ledger)
    return trimmed


def _fresh(conn):
    """A plain read on this connection may have begun a transaction (autobegin), and
    `with conn.begin()` refuses when one is open; a harness that hands every
    db.connect() the same connection needs the same courtesy."""
    if conn.in_transaction():
        conn.rollback()
    return conn


def _land(uid, raw_rows, rules, door=None, mode="NEW_ONLY", run_id=None,
          exclusion_counts=None, eligibility_token=None, preview_owner=None):
    runs.checkpoint(uid)
    runs.progress(uid, phase="parsing")
    records, verdicts = crm_lead.normalise(raw_rows, rules)
    runs.checkpoint(uid)
    if not db.configured():
        raise PipelineRefused({"code": "database_required",
                               "detail": "The pipeline lands rows in the landing "
                                         "schema; set DATABASE_URL"})
    conn = db.connect()
    try:
        with conn.begin():
            # First statement of the transaction; released when it ends.
            if not conn.execute(text("select pg_try_advisory_xact_lock(:k)"),
                                {"k": CRM_LEAD_LOCK_KEY}).scalar():
                raise PipelineRefused({"code": "crm_lead_run_in_progress",
                                       "detail": "another crm.lead pull is landing",
                                       "detail_th": RUN_IN_PROGRESS_TH})
            # Holding the lock, a RUNNING row this old is a process that died mid-run.
            landing.sweep_running(conn, "ODOO", STALE_RUNNING_MINUTES)
            expected_retire = None
            # crm.lead eligibility can change without changing the customer's
            # identity. Retire the Odoo-owned row, never its durable identity link.
            preserve_identity_links = True
            if eligibility_token:
                preview = conn.execute(text(
                    "select expected, expires_at, applied_at from app.crm_eligibility_preview "
                    "where token=:t and principal_key=:p for update"),
                    {"t": eligibility_token, "p": preview_owner}).mappings().first()
                if preview is None:
                    raise PipelineRefused({"code": "eligibility_preview_invalid",
                                           "detail": "preview token was not found for this account"})
                if preview["applied_at"] is not None:
                    raise PipelineRefused({"code": "eligibility_preview_used",
                                           "detail": "preview token was already applied"})
                expired = conn.execute(text("select :expires < now()"),
                                       {"expires": preview["expires_at"]}).scalar()
                if expired:
                    raise PipelineRefused({"code": "eligibility_preview_expired",
                                           "detail": "preview token expired"})
                expected = preview["expected"] or {}
                current_counts = {
                    "eligible_source": len(raw_rows),
                    "normalised": len(records),
                    "eligibility_exclusions": exclusion_counts or {},
                }
                for key, value in current_counts.items():
                    if expected.get(key) != value:
                        raise PipelineRefused({
                            "code": "eligibility_preview_mismatch",
                            "detail": "current %s count differs from the preview" % key,
                            "expected": expected.get(key), "actual": value})
                expected_retire = int(expected.get("would_retire", 0))
            runs.progress(uid, phase="applying", processed=0, phase_total=len(records))
            result = writer.write(conn, records, verdicts,
                                  on_progress=lambda **kw: (
                                      runs.checkpoint(uid), runs.progress(uid, **kw))[1],
                                  read=len(raw_rows), door=door, mode=mode,
                                  run_id=run_id, retire=True,
                                  exclusion_counts=exclusion_counts,
                                  expected_retire=expected_retire,
                                  preserve_identity_links=preserve_identity_links,
                                  refresh_source_rows=True)
            if eligibility_token:
                conn.execute(text(
                    "update app.crm_eligibility_preview set applied_at=now(), apply_run_id=:r "
                    "where token=:t"), {"r": result["run_id"], "t": eligibility_token})
            runs.checkpoint(uid)
            # Make cancellation impossible immediately before the transaction is
            # committed. A request observed earlier raises inside this block and
            # SQLAlchemy rolls the whole write back.
            runs.mark_committed(uid)
    finally:
        conn.close()
    # Landed rows are only half the act: the served book has to be rebuilt from them
    # or every screen keeps the pre-pull book in this process (sync audit, 2026-09-20).
    # A pull that landed and retired nothing changes no fact, so it rebuilds nothing
    # and bumps no epoch. after_landing never raises — the landing commit is the fact.
    from .. import refresh
    # A pull that only moved an Odoo-lead link (all its leads are held by sheet rows,
    # so nothing lands and nothing retires) still changes what the case can show: the
    # served row gains or loses its Odoo deep link.
    changed = bool(result["landed"] or result["retired"]
                   or result.get("links_added") or result.get("links_retired"))
    served = refresh.after_landing(door or "pipeline", result.get("run_id"), changed=changed)
    return {**result, "new_data": changed, "served": served["served"],
            "serve_problem": served.get("problem"),
            "data_epoch": served["epoch"]}


def preview_eligibility(principal_key):
    """Fetch eligible crm.lead rows and persist the exact retirement expectation."""
    if not db.configured():
        raise PipelineRefused({"code": "database_required",
                               "detail": "eligibility preview requires DATABASE_URL"})
    rules = rules_mod.load()
    exclusions = {}
    raw_rows = ingress.from_odoo(rules, on_exclusions=lambda counts: exclusions.update(counts))
    records, verdicts = crm_lead.normalise(raw_rows, rules)
    conn = _fresh(db.connect())
    try:
        with conn.begin():
            retire = writer.retirement_preview(conn, records)
            expected = {**retire, "eligible_source": len(raw_rows),
                        "normalised": len(records),
                        "rejected": sum(1 for item in verdicts if item.get("verdict") == "rejected"),
                        "eligibility_exclusions": exclusions}
            token = "elig-" + uuid.uuid4().hex
            conn.execute(text(
                "insert into app.crm_eligibility_preview (token, principal_key, expected) "
                "values (:t, :p, cast(:e as jsonb))"),
                {"t": token, "p": principal_key,
                 "e": json.dumps(expected, ensure_ascii=False, default=str)})
    finally:
        conn.close()
    return {"token": token, "expected": expected, "expires_in_hours": 24}


def apply_eligibility(token, principal_key, uid=None):
    """Re-fetch and apply only if every previewed count still agrees."""
    uid = uid or runs.start("odoo-eligibility")
    run_id = None
    try:
        runs.checkpoint(uid)
        run_id = _open_durable_run("NEW_ONLY")
        rules = rules_mod.load()
        exclusions = {}
        raw_rows = ingress.from_odoo(
            rules, on_progress=lambda **kw: (
                runs.checkpoint(uid), runs.progress(uid, **kw))[1],
            on_exclusions=lambda counts: exclusions.update(counts))
        result = _land(uid, raw_rows, rules, door="odoo-eligibility", mode="NEW_ONLY",
                       run_id=run_id, exclusion_counts=exclusions,
                       eligibility_token=token, preview_owner=principal_key)
    except Exception as exc:
        problem, code = _failure(exc)
        _fail_durable(run_id, code, exc)
        runs.fail(uid, problem)
    else:
        runs.finish(uid, _for_memory(result))
    return runs.get(uid)


def _open_durable_run(mode):
    """A RUNNING run row committed BEFORE the fetch, so a pull that dies later leaves
    a durable FAILED row, not only an in-memory registry entry (peak_service.py's
    pattern). None without a database."""
    if not db.configured():
        return None
    conn = _fresh(db.connect())
    try:
        with conn.begin():
            return landing.start_run(conn, "ODOO", meta={"door": "odoo", "mode": mode})
    finally:
        conn.close()


def _fail_durable(run_id, code, exc):
    """FAILED as "<code>: <exception class>" — never the exception's text, which can
    quote a lead's own values or a statement. Only a row still RUNNING: a landing
    whose commit reached the server before the client saw an error stays OK."""
    if run_id is None:
        return
    try:
        conn = _fresh(db.connect())
        try:
            with conn.begin():
                conn.execute(text(
                    "update landing.import_run set status = 'FAILED', finished_at = now(), note = :n "
                    "where id = :i and status = 'RUNNING'"),
                    {"n": "%s: %s" % (code, exc.__class__.__name__), "i": run_id})
        finally:
            conn.close()
    except Exception as err:                      # noqa: BLE001 — the registry still says failed
        log.error("crm.lead run %s could not be marked failed (%s)", run_id, err.__class__.__name__)


def _failure(exc):
    """(the registry's problem, the durable row's code) for what stopped a run."""
    name = exc.__class__.__name__
    if isinstance(exc, runs.RunCancelled):
        return {"code": "cancelled", "detail": "operation cancelled"}, "cancelled"
    if isinstance(exc, PipelineRefused):
        problem = dict(exc.problem)
        if problem.get("code") == "crm_lead_run_in_progress":
            problem.update(status=503, retryable=True)
        return problem, problem.get("code") or "pipeline_failed"
    if isinstance(exc, writer.TooMuchToRetire):
        return {"code": exc.code, "detail": str(exc), "detail_th": TOO_MUCH_TO_RETIRE_TH}, exc.code
    if isinstance(exc, writer.PreviewCountMismatch):
        return {"code": exc.code, "detail": str(exc)}, exc.code
    if isinstance(exc, rules_mod.RulesError):
        return {"code": "rules_unreadable", "detail": str(exc)}, "rules_unreadable"
    if isinstance(exc, odoo_client.NotConfigured):
        return ({"code": "integration_not_configured", "missing": exc.missing,
                 "status": 422, "retryable": False,
                 "message_th": "ยังไม่ได้ตั้งค่าการเชื่อมต่อ Odoo",
                 "detail": "missing " + ", ".join(exc.missing)}, "integration_not_configured")
    if isinstance(exc, odoo_client.OdooError):
        return {"code": "integration_unavailable", "detail": str(exc)}, "odoo_refused"
    if isinstance(exc, httpx.HTTPError):
        transient = not isinstance(exc, httpx.HTTPStatusError) or (
            exc.response.status_code >= 500 or exc.response.status_code in (408, 425, 429))
        return {"code": "integration_unavailable", "detail": name,
                "status": 503 if transient else 422, "retryable": transient}, "odoo_unreachable"
    return {"code": "pipeline_failed", "detail": name}, "pipeline_failed"


def run_odoo(uid=None, mode="NEW_ONLY"):
    uid = uid or runs.start("odoo")
    runs.progress(uid, mode=mode)
    run_id = None
    try:
        runs.checkpoint(uid)
        run_id = _open_durable_run(mode)
        rules = rules_mod.load()
        eligibility_exclusions = {}
        raw_rows = ingress.from_odoo(
            rules, on_progress=lambda **kw: (
                runs.checkpoint(uid), runs.progress(uid, **kw))[1],
            on_exclusions=lambda counts: eligibility_exclusions.update(counts))
        runs.checkpoint(uid)
        result = _land(uid, raw_rows, rules, door="odoo", mode=mode, run_id=run_id,
                       exclusion_counts=eligibility_exclusions)
    except Exception as exc:                      # noqa: BLE001 — recorded, never swallowed
        # A background thread has nowhere to raise to. Swallowing would leave the run
        # "running" for ever; this records what happened, twice over, and ends it.
        problem, code = _failure(exc)
        _fail_durable(run_id, code, exc)
        runs.fail(uid, problem)
    else:
        runs.finish(uid, _for_memory(result))
    return runs.get(uid)


STALE_AFTER_HOURS = 6


def refresh_if_stale(max_age_hours=STALE_AFTER_HOURS):
    """Start a background crm.lead pull when the last ODOO run is older than the
    window (the 2026-09-19 ruling: crm.lead is the served book, so it must not sit
    stale behind a running server). Never blocks boot; no database — or no run yet —
    is simply a no-op, and a failure to read the registry never stops start-up.
    No Odoo credentials is a no-op too, as for the timer (schedule._loop): a pull
    that cannot run would only leave a durable FAILED row per boot.
    """
    import threading
    from datetime import datetime, timedelta, timezone

    from . import schedule

    if not db.configured() or not schedule.odoo_ready():
        return False
    try:
        conn = db.connect()
        try:
            run = landing.lead_run_slim(conn)
        finally:
            conn.close()
    except Exception:                                  # noqa: BLE001 — boot must proceed
        return False
    finished = (run or {}).get("finished_at")
    if finished is not None:
        try:
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - finished < timedelta(hours=max_age_hours):
                return False
        except Exception:                              # noqa: BLE001 — an odd stamp means refresh
            pass
    threading.Thread(target=run_odoo, kwargs={"mode": "NEW_ONLY"}, daemon=True).start()
    return True
