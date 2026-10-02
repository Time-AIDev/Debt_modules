"""The record of who took the workbook out, and why — ruling 72 (the governed `POST`)
and ruling 74 (closing the ungoverned `GET`, authorised edit 17).

Before this module, `GET /v1/workbook:export` returned 200 to OFFICER, MANAGER and
OWNER alike, with no reason and no record — "a documented hole with a URL, beside a
governed POST that asks for a reason" (round-5 ledger, ruling 74). Every export that
leaves through either verb is signed and appended here; `GET /v1/workbook/exports`
reads it back. Per session, like every other per-tester mutable in this backend —
see session.py and ruling 43's remedy.
"""
from .session import Store


class ExportLog:
    def __init__(self):
        self.entries = []
        self._counter = 0

    def uid(self, prefix):
        self._counter += 1
        return "%s-%05d" % (prefix, self._counter)


_store = Store(ExportLog, key="workbook_exports.log")


def for_current() -> ExportLog:
    return _store.for_current()


def reset():
    _store.reset()


def record(*, verb, by, by_role, reason, on, taken_at, row_count, total, filters, columns_hash):
    """Appends one export to the current session's log and returns it. `reason` is
    None for a pre-ruling-74-style call is never possible any more — the caller
    always has one by the time it reaches here, both verbs refuse first."""
    log = for_current()
    entry = {
        "uid": log.uid("exp"),
        "verb": verb,
        "by": by,
        "by_role": by_role,
        "reason": reason,
        "on": on,
        "taken_at": taken_at,
        "row_count": row_count,
        "total": total,
        "filters": filters,
        "columns_hash": columns_hash,
    }
    log.entries.append(entry)
    return entry


def list_for_current():
    return list(for_current().entries)
