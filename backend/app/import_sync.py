"""Catching a session up to imported facts, on the session's own next request.

A session seeds its journey invoices, cases and pipeline cards from the book once,
on first touch. Until 2026-09-20 only the session that pressed Apply reseeded (and
only its PEAK invoices); every other tester kept the old facts indefinitely, and
`main.reload_book`'s own docstring said they would "see the facts at their next
reset" (sync audit, 2026-09-20). Now every landing/apply bumps app.data_epoch, and
this module compares that with what the session last saw. When it is behind, the
import-derived parts of its stores are refreshed IN PLACE — amounts, dates, names,
imported statuses — while everything a person did (slips, PTPs, contacts, evidence,
gates, released invoices, overrides) is left alone.

It also keeps the PROCESS's book fresh on a multi-instance deploy: instance B only
learns the epoch moved when a request arrives, so the first request after another
instance's import rebuilds this instance's served book.
"""
import sys
import threading

from . import data_epoch, db
from .session import Store

# The epoch a session last healed to — and, since fix-all F1, the business date it
# healed on: the live date turns at Bangkok midnight, and a session seeded yesterday
# would keep yesterday's derived dates until the next import.
_seen = Store(lambda: {"epoch": 0}, key="import.seen_epoch")

# The epoch this PROCESS last rebuilt main.CUSTOMERS from. A module value (not the
# session store): the served book is process-wide, the seen epoch is per session.
_book_epoch = {"value": 0}

# One heal (and one flush, main.tester_session) per session at a time (fix-all F1). The
# middleware runs both in the threadpool now, off the event loop, so two requests of
# one session can reach them together: the second waits, then finds the first's stamp.
# ponytail: one RLock per session id, never evicted — like the stores' own slots.
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def session_lock():
    """The current session's heal lock (re-entrant: ensure_current holds it around
    heal_session, which takes it again for its other callers)."""
    from . import session as session_domain
    session_id = session_domain.current()
    with _LOCKS_GUARD:
        lock = _LOCKS.get(session_id)
        if lock is None:
            lock = _LOCKS[session_id] = threading.RLock()
    return lock


def seen_epoch():
    return int(_seen.for_current().get("epoch") or 0)


def note_book_epoch(value):
    """Called by refresh.after_landing when THIS process already reloaded."""
    _book_epoch["value"] = max(_book_epoch["value"], int(value or 0))


def mark_seen(epoch=None):
    """Stamp the session as caught up to `epoch` (default: the current one).

    The acting session's own heal (a PEAK apply, a link confirm) runs inside the
    request; without this stamp its NEXT request would run heal_session again for
    the same epoch — measured 2026-09-20, a full duplicate heal per apply."""
    epoch = int(epoch if epoch is not None else data_epoch.current())
    if epoch > 0:
        from .config import settings
        _seen.for_current().update(epoch=epoch, date=str(settings.business_date))
    return epoch


def reset():
    """Test seam."""
    _seen.reset()
    _book_epoch["value"] = 0


def heal_session():
    """Refresh this session's import-derived state, in place. Returns counts.

    Under the session's heal lock, so every caller is covered: the per-request hook,
    an apply's own heal (routers/peak_pipeline._after_apply) and the stale banner's
    button (routers/data_state.refresh_imports)."""
    from . import cases, invoice_pipeline, journey, peak_documents
    from .config import settings
    with session_lock():
        bd = settings.business_date
        jstate = journey.for_current()
        # PEAK first: it deletes and re-mints its own rows, and the sheet refresh below
        # must not touch what it owns.
        journey.reseed_peak(jstate, bd)
        sheet = journey.reseed_migrated_invoices(jstate, bd)
        cards = invoice_pipeline.reseed_from_book()
        # New cards open their cases (the cases factory's job) before the case snapshot
        # refresh walks them, so a card added by this import is caught up in the same pass.
        case_state = cases.for_current()
        collection_cases_added = cases.open_collection_cases(case_state)
        cases._open_pipeline_cases(case_state)
        summary = cases.follow_import_for_all()
        docs = peak_documents.reconcile(peak_documents.for_current(), jstate)
        from . import termination_archive
        termination_archive.backfill_current(capture_kind="IMPORT")
        # D05 / TASK-221, fix-all F2: money in before an open promise's date, for EVERY
        # session's own promises — it ran for the acting session only (refresh.py). The
        # notice uid is derived from owner, customer and receipt, so the many sessions
        # that heal on one import write one notice. Never fails the heal. The hook runs
        # it outside audit_trail, so only an apply's own heal records the act.
        try:
            from . import audit
            from .ptp_watch import notice_early_payments
            # The heal runs inside whatever request caught this session up — an apply, a
            # link confirm — and the scan's describe() would rename THAT request's audit
            # act (fix-all F audit). The notice and its case event are the record.
            token = audit.CURRENT.set(None)
            try:
                notice_early_payments(jstate, cases.for_current(), bd, by="SYSTEM")
            finally:
                audit.CURRENT.reset(token)
        except Exception as exc:                       # noqa: BLE001 — the heal already happened
            print("early-payment scan failed: %s" % exc.__class__.__name__, file=sys.stderr)
        return {
            "invoices_updated": sheet.get("updated", 0),
            "invoices_added": sheet.get("added", 0),
            "invoices_flagged": sheet.get("flagged", 0),
            "cards_updated": cards.get("updated", 0),
            "cards_added": cards.get("added", 0),
            "cases_moved": summary.get("moved", 0),
            "cases_refreshed": summary.get("refreshed", 0),
            "collection_cases_added": collection_cases_added,
            "documents_flagged": docs.get("flagged", 0),
        }


def ensure_current(force=False):
    """A summary when this session was healed (or stamped fresh), else None. `force`
    re-runs it (the screen's button).

    No database — the fixtures never change and the date is pinned — so nothing to
    catch up to, and the function is a no-op. The heal runs when the epoch moved or,
    once there is an epoch, when the business date did (fix-all F1). A heal failure
    is reported and the session's seen epoch is NOT stamped, so the next request tries
    again instead of skipping for ever.
    """
    if not db.configured():
        return None
    epoch = data_epoch.current()
    if epoch <= 0:
        # Nothing ever imported: no store is read, so a request that touches none still
        # flushes nothing (and a dead database stays quiet here).
        return None
    from . import main
    from . import session as session_domain
    from .config import settings
    with session_lock():
        # Checked BEFORE _seen.for_current() and settings (a per-session store too):
        # reading either would itself touch a store and make every session look "touched".
        fresh_session = not force and not session_domain.touched_current()
        today = str(settings.business_date)
        stored = _seen.for_current()
        seen = int(stored.get("epoch") or 0)
        if not force and seen >= epoch and stored.get("date") == today:
            return None
        book_reloaded = False
        if _book_epoch["value"] < epoch:
            try:
                main.reload_book()
            except Exception as exc:                   # noqa: BLE001 — the session heal still runs
                import os
                if os.environ.get("ENV") == "prd": raise
                print("served book refresh failed: %s" % exc.__class__.__name__, file=sys.stderr)
            else:
                note_book_epoch(epoch)
                book_reloaded = True
        if fresh_session and not seen:
            # Nothing seeded yet: the first touch of each store reads the CURRENT book,
            # so healing now would seed twice (measured 646 ms for that first heal).
            # No slot in memory is not "new" by itself: a cold start keeps K_REVISION and
            # restores every store from app.session_state as it was at the epoch this
            # session last saw, so a session that ever stamped one heals (2026-09-27).
            stored.update(epoch=epoch, date=today)
            return {"epoch": epoch, "book_reloaded": book_reloaded,
                    "seen_before": False, "fresh_session": True}
        summary = heal_session()
        stored.update(epoch=epoch, date=today)
        summary.update({"epoch": epoch, "book_reloaded": book_reloaded,
                        "seen_before": seen > 0})
        return summary
