"""The action audit log — one append-only, hash-chained record of every act.

Design: docs/archive/superpowers/specs/2026-09-11-action-audit-log-design.md

Two things this module refuses to pretend:

  - It records `actor_claimed`, never `actor`. The acting name arrives as a
    header or a body field the CLIENT chooses (tester_session, main.py:177:
    "the cookie identifies a BROWSER, not a person"). `actor_source` says which,
    so a reader knows exactly how much the name is worth.
  - The chain is tamper-EVIDENT, not tamper-proof. We hold the credentials.
    What it buys is that no alteration can be silent.

INTACT and COMPLETE are separate claims. A chain whose hashes all agree is
intact. A chain that also lost no writes is complete. verify() answers both,
because "nothing was edited" and "nothing is missing" fail in different ways.
"""
import hashlib
import json
from contextvars import ContextVar

from .config import settings

# The hashed fields, in a fixed order. Adding a field here changes every hash
# after the change, which is correct — but it means an existing chain verifies
# only up to the schema it was written under. Append, never reorder.
FIELDS = (
    "seq", "at", "business_date",
    "actor_claimed", "actor_source",
    "session_id", "request_id",
    "verb", "route_template",
    "act", "subject_type", "subject_uid", "detail",
    "outcome", "status", "error_code",
    "actor_role",
)

# Fields added after rows already existed. A None value is left OUT of the hashed
# payload, so a row written before the field existed hashes exactly as it did then.
# A set value is hashed like any other field.
LATE_FIELDS = ("actor_role",)

# The signing role (R13). Same set as auth.ROLES; not imported to keep this module leaf.
ROLES = ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS")

GENESIS = "0" * 64


def canonical(entry):
    """One string per entry, stable under key order and Unicode.

    ensure_ascii=False so Thai reasons hash as the characters they are rather
    than as escape sequences; separators pinned so no whitespace change can
    alter a hash.
    """
    return json.dumps(entry, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def hash_entry(entry, prev_hash):
    payload = canonical({k: entry.get(k) for k in FIELDS
                         if k not in LATE_FIELDS or entry.get(k) is not None}) + prev_hash
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Chain:
    """In-memory chain. The Postgres-backed one (store.py) reuses every rule here."""

    def __init__(self):
        self._entries = []
        self._gaps = []

    def entries(self):
        return self._entries

    def head_hash(self):
        return self._entries[-1]["hash"] if self._entries else GENESIS

    def append(self, *, at=None, **fields):
        # An unhashed field is an unprotected field. A key the chain cannot hash
        # must be a loud error, not a silent omission. Missing keys stay legal —
        # seq, at and business_date are computed, so absence is normal.
        unknown = set(fields) - set(FIELDS)
        if unknown:
            raise ValueError("audit entry has fields the chain does not hash: %s"
                             % ", ".join(sorted(unknown)))
        entry = {k: fields.get(k) for k in FIELDS}
        entry["seq"] = len(self._entries) + 1
        entry["at"] = at or _now()
        entry["business_date"] = str(settings.business_date)
        entry["detail"] = fields.get("detail") or {}
        entry["prev_hash"] = self.head_hash()
        entry["hash"] = hash_entry(entry, entry["prev_hash"])
        self._entries.append(entry)
        return entry

    def gaps(self):
        return list(self._gaps)

    def record_gap(self, why):
        """An act happened and could not be recorded.

        The act is already done; refusing the response would not undo it, only
        hide it. So the miss is counted and surfaced, because a log that
        silently drops rows is worse than one that admits it dropped them.
        """
        self._gaps.append({"why": str(why), "at": _now()})

    def verify(self):
        prev = GENESIS
        for index, entry in enumerate(self._entries, start=1):
            if entry["prev_hash"] != prev or entry["hash"] != hash_entry(entry, prev):
                return {"ok": False, "broken_at": entry["seq"], "verified": index - 1,
                        "gaps": len(self._gaps), "complete": False}
            prev = entry["hash"]
        return {"ok": True, "broken_at": None, "verified": len(self._entries),
                "gaps": len(self._gaps), "complete": not self._gaps}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# The entry being built for the request in flight. A ContextVar for the same reason
# REQUEST_ID is one (main.py:163): it is per-request state that domain code must be
# able to reach without every function growing a parameter for it.
CURRENT = ContextVar("audit_entry", default=None)

# D3: the ONE read in scope. Opening a customer's file is the act a data-subject
# complaint asks about; list and report views are navigation and are not logged.
# A tuple, and the coverage test in Task 7 asserts nothing else GET is recorded, so
# this cannot widen by accident.
LOGGED_READS = ("/v1/cases/by-customer/{customer_uid}",
                "/v1/terminated-customers/{archive_uid}")


def is_logged(method, route_template):
    """The one definition of what this log records: every act, plus the reads in
    LOGGED_READS. It lives here rather than inline in the middleware so the coverage
    test can exercise the REAL rule instead of restating it — a guard that only
    restates the thing it guards cannot fail, which is how this was found."""
    if route_template is None:
        return False
    return method != "GET" or route_template in LOGGED_READS


def describe(act=None, subject=None, detail=None):
    """Attach business meaning to the entry for the request in flight.

    A no-op outside a request, so every domain function stays callable from a test
    or a job with no HTTP anywhere near it.
    """
    entry = CURRENT.get()
    if entry is None:
        return
    if act and entry.get("act") and act != entry["act"]:
        # Detail belongs to an act. execute_power calls set_dc_status, which describes
        # itself first (act=DC_STATUS_SET, detail={from, to, reason} for the POWER_CUTOFF
        # transition); execute_power's own describe(act=POWER_EXECUTED) then ran with no
        # detail of its own, and the merge below let the inner act's detail survive under
        # the outer act's name — a POWER_EXECUTED row explaining a status change it never
        # made. A confident wrong value outranks a blank (contract §1a), so a nested act
        # that changes the act name resets detail rather than inheriting a stranger's.
        # Final-review Fix 8: subject belongs to an act for exactly the same reason —
        # an inner act's subject (an order, a document) surviving under an outer act's
        # name is the same class of confident wrong value as the borrowed detail was,
        # just on a different pair of columns. Reset both.
        entry["detail"] = {}
        entry["subject_type"], entry["subject_uid"] = None, None
    if act:
        entry["act"] = act
    if subject:
        entry["subject_type"], entry["subject_uid"] = subject
    if detail:
        entry["detail"] = {**(entry.get("detail") or {}), **detail}


def note_error(code):
    entry = CURRENT.get()
    if entry is not None:
        entry["error_code"] = code
