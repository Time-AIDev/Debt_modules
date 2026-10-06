"""Audited customer-only transaction plans; unknown side effects stay global.

The middleware supplies bounded, parsed JSON before choosing its book/SQL lease.
This module never reads mutable process books or trusts a body-supplied owner.
"""
from dataclasses import dataclass
import re

from sqlalchemy import text

from . import business_records, errors

DIRECT = re.compile(r"/v1/cases/by-customer/([^/]+)(?:/([^/]+))?")
PTP_CLOSE = re.compile(r"/v1/case-ptps/([^/]+):close")
READ_ACTIONS = frozenset({None, "invoices", "peak-codes"})
WRITE_ACTIONS = frozenset({"notes", "next-action", "dc-status", "contacts"})


@dataclass(frozen=True)
class CustomerScope:
    customer_uid: str
    action: str
    child_record_key: str | None = None


def captures_json(scope):
    """Exact requests whose body affects safe scoping (before the outer gate)."""
    if scope.get("method") != "POST":
        return False
    path = scope.get("path", "")
    direct = DIRECT.fullmatch(path)
    return bool(direct and direct[2] in WRITE_ACTIONS or PTP_CLOSE.fullmatch(path))


def _attachments(value):
    if isinstance(value, dict):
        return any((key in ("attachment_uids", "attachments") and bool(child)) or _attachments(child)
                   for key, child in value.items())
    if isinstance(value, list):
        return any(_attachments(child) for child in value)
    return False


def plan(scope, body=None, conn=None):
    """Return customer plan or None for the existing globally exclusive path.

    Unsafe contacts use cases.fee_state; attachment preflight/attach lacks a CAS;
    renegotiation consumes a person-wide shared ContactLog. None means these
    handlers retain their original exclusion and workflow, not that they refuse.
    """
    path, method = scope.get("path", ""), scope.get("method")
    direct = DIRECT.fullmatch(path)
    if direct:
        if method in ("GET", "HEAD") and direct[2] in READ_ACTIONS:
            return CustomerScope(direct[1], "read")
        if method != "POST" or direct[2] not in WRITE_ACTIONS or not isinstance(body, dict):
            return None
        if _attachments(body):
            return None
        if direct[2] == "contacts" and any(body.get(key) for key in ("issue", "service_issue", "service_ticket")):
            return None
        return CustomerScope(direct[1], direct[2])
    child = PTP_CLOSE.fullmatch(path)
    if method == "POST" and child and isinstance(body, dict) and conn is not None and not _attachments(body):
        key = "ptps/" + business_records.canonical(child[1])
        owner = conn.execute(text("select customer_uid from app.business_record "
                                  "where store_key='cases.state' and record_key=:key and schema_version=1"),
                             {"key": key}).scalar()
        if owner:
            return CustomerScope(owner, "ptp-close", key)
    return None


def revalidate(conn, planned):
    """After customer lock, require the child still belongs to that customer."""
    if planned is None or planned.child_record_key is None:
        return
    owner = conn.execute(text("select customer_uid from app.business_record "
                              "where store_key='cases.state' and record_key=:key and schema_version=1"),
                         {"key": planned.child_record_key}).scalar()
    if owner != planned.customer_uid:
        raise errors.Problem("case_ownership_changed", 409, "Reload the case",
                             "The committed child owner changed before the customer transaction.",
                             "ข้อมูลเคสเปลี่ยนแล้ว กรุณาโหลดเคสใหม่ก่อนบันทึก", "DEBT-CASE-409")
