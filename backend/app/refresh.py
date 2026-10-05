"""One seam between "rows landed" and "the process serves them".

Before this module, only a PEAK apply rebuilt the served book (main.reload_book);
a crm.lead pull invalidated the book cache and nothing else, so the landing rows
were read by the migration report and a new session's pipeline seed while Today,
the workbook and every case/journey loop kept the pre-pull `main.CUSTOMERS` in
the same process (sync audit, 2026-09-20). Every door that writes landing now
lands here instead: crm.lead run/start/schedule/job and a PEAK apply.

The call never raises into the import path. The landing commit is the fact; a
failed reload is reported as `served: false` with the problem, the old book keeps
serving, and the session heal still runs from the live landing reads. The epoch
is bumped even then, deliberately: sessions must not keep seeding from the old
facts just because this process could not rebind.
"""
from . import book as book_module
from . import data_epoch

_LAST = {"kind": None, "run_id": None, "served": False, "problem": None}


def _landing_has_a_run():
    """Whether the landing schema holds a run the book would be served from.

    A database can be configured for other reasons (session persistence) while the
    book is served from the fixtures — and a test harness runs exactly that way.
    Reloading from an empty landing would replace a working book with nothing, so
    the reload is skipped until landing actually carries a SHEET or crm.lead run.
    """
    from . import db, landing
    if not db.configured():
        return False
    from sqlalchemy import text
    try:
        conn = db.connect()
        try:
            # A read on a connection a test harness shares must not leave its
            # implicit transaction open: the next `with conn.begin()` (audit,
            # session flush, the write) would raise.
            if conn.in_transaction():
                conn.rollback()
            with conn.begin():
                if landing.last_run(conn, "SHEET") or landing.last_lead_run(conn):
                    return True
                # A PEAK apply changes what the book serves just as a landing does.
                applied = conn.execute(text(
                    "select 1 from landing.import_run where source_system = 'PEAK' "
                    "and status = 'OK' and meta ? 'applied' limit 1")).first()
                return bool(applied)
        finally:
            conn.close()
    except Exception:                                  # noqa: BLE001 — no landing, no reload
        return False


def after_landing(kind, run_id=None, changed=True):
    """Rebind the served book, bump the epoch, and say what happened.

    Returns {"served": bool, "epoch": int, "problem": {...}|None, "changed": bool}.
    `kind` names the door for the epoch row; `run_id` is the landing run when the
    caller has one. `changed=False` — a pull that landed and retired nothing — skips
    both the rebuild and the bump: every session would otherwise heal, and the book
    rebuild, for a pull that changed no fact (2026-09-25).
    """
    if not changed:
        # Nothing moved in the book, but DPD and overdue move with the day: the month's
        # row still follows (review, 2026-09-25).
        from . import monthly_history
        monthly_history.safe_snapshot(kind)
        return {"served": True, "epoch": data_epoch.current(), "problem": _archive_import(), "changed": False}
    from . import main
    result = {"served": False, "epoch": data_epoch.current(), "problem": None, "changed": True}
    landed = _landing_has_a_run()
    # The epoch BEFORE the rebuild (fix-all F): main.reload_book builds only for an
    # epoch this process does not serve yet, and book_source re-reads the non-PEAK
    # landing only when the last non-PEAK epoch moved — both need this landing's epoch.
    try:
        result["epoch"] = data_epoch.bump(kind, run_id)
    except Exception as exc:                           # noqa: BLE001 — sessions keep their old epoch
        result["problem"] = {
            "code": "epoch_write_failed",
            "detail": exc.__class__.__name__,        # the class only, never the driver's text
            "message_th": "บันทึกจุดอัปเดตข้อมูลไม่สำเร็จ เซสชันอื่นจะยังไม่เห็นข้อมูลใหม่",
            "message_en": "Could not record the import epoch; other sessions will not heal",
        }
    if result["problem"]:
        pass            # nothing records the change, so nothing rebuilds for it: the old book serves
    elif landed:
        try:
            main.reload_book()
        except Exception as exc:                       # noqa: BLE001 — the import already committed
            book_module.invalidate()
            result["problem"] = {
                "code": "serve_refresh_failed",
                # The class only: a driver's text can quote the row that failed.
                "detail": exc.__class__.__name__,
                "message_th": "ข้อมูลนำเข้าแล้ว แต่ยังสลับสมุดงานที่ให้บริการไม่สำเร็จ",
                "message_en": "The import landed, but the served book could not be switched",
            }
        else:
            result["served"] = True
    else:
        # Nothing landed to serve (fixtures mode / an empty landing): the book in
        # memory is already the served one.
        result["served"] = True
    if result["served"]:
        # This process just rebuilt the book for that epoch. Saying so stops
        # import_sync.ensure_current from rebuilding it AGAIN on the next request —
        # measured 2026-09-20: two full book builds per import per instance (473 ms
        # each here, ~1.4 s warm at the 350k bench). A failed reload is deliberately
        # NOT noted, so the lazy rebuild on the next request stays the recovery path.
        # (The early-payment scan that ran here for the acting session only is in
        # import_sync.heal_session since fix-all F2 — every session runs it.)
        from . import import_sync, monthly_history
        import_sync.note_book_epoch(result["epoch"])
        # The current month's history row follows every landing (2026-09-25).
        monthly_history.safe_snapshot(kind)
        archive_problem = _archive_import()
        if archive_problem:
            result["problem"] = archive_problem
    _LAST.update(kind=kind, run_id=run_id, served=result["served"], problem=result["problem"])
    return result


def last():
    """The last landing refresh, for the data-state endpoint."""
    return dict(_LAST)


def reset():
    """Test seam."""
    _LAST.update(kind=None, run_id=None, served=False, problem=None)


def _archive_import():
    # The landing is already committed. Report an archive failure explicitly;
    # the next import heal retries the idempotent capture.
    from . import termination_archive
    try:
        termination_archive.backfill_current(capture_kind="IMPORT")
    except Exception as exc:
        return {"code": "termination_archive_unavailable", "detail": exc.__class__.__name__,
                "message_th": "นำเข้าข้อมูลแล้ว แต่ทะเบียนการยุติยังไม่พร้อม กรุณารีเฟรชข้อมูลอีกครั้ง"}
    return None
