"""The identity-link register: what a person confirmed about which PEAK contact code
is which customer. records.identity_link (vault note 10 §3 WP1, F4).

Rung 0 of the ladder reads it at match time AND the book reads it at load time
(peak_writer.invoices_for_book, and the receipt overlay for receipts), so confirming,
retiring or re-pointing a link moves the invoices and receipts at once — no re-run,
no re-upload. Retiring keeps the row as history; only retired_at moves.
"""
from sqlalchemy import text

from . import field_decisions
from .peak_match import normalise_code


def _row(r):
    d = dict(r)
    for k in ("confirmed_at", "retired_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


# 2026-10-01: records.identity_link carries two registers. This module reads and
# writes only the PEAK one; the Odoo-lead links (source 'ODOO_CRM_LEAD') belong to
# pipelines/odoo_links.py and must stay invisible here — an Odoo volt_id can equal a
# PEAK contact code, and treating the one as the other moves money between people.
SOURCE = "PEAK_LINK"


def load(conn):
    rows = conn.execute(text(
        "select uid, contact_code, customer_no, contract_uid, rule from records.identity_link "
        "where source = :s and retired_at is null"), {"s": SOURCE}).mappings().all()
    return {r["contact_code"]: dict(r) for r in rows}


def list_links(conn, include_retired=False):
    where = "where source = :s" + ("" if include_retired else " and retired_at is null")
    rows = conn.execute(text("select * from records.identity_link %s order by uid" % where),
                        {"s": SOURCE}).mappings().all()
    return [_row(r) for r in rows]


def confirm(conn, contact_code, customer_no, by, reason=None, rule="PERSON", contract_uid=None):
    code = normalise_code(contact_code)
    if not code or not customer_no:
        raise ValueError("a link needs a contact code and a customer number")
    before = conn.execute(text(
        "update records.identity_link set retired_at = now(), retired_by = :by "
        "where source = :s and contact_code = :c and retired_at is null returning customer_no"),
        {"s": SOURCE, "c": code, "by": by}).scalars().all()
    for old in set(before) - {str(customer_no)}:         # re-pointed: fix-all P5
        field_decisions.retire_link_defaults(conn, old, code, by)
    row = conn.execute(text(
        "insert into records.identity_link (source, contact_code, customer_no, contract_uid, rule, confirmed_by, reason) "
        "values (:s, :c, :n, :k, :r, :by, :why) returning *"),
        {"s": SOURCE, "c": code, "n": str(customer_no), "k": contract_uid, "r": rule,
         "by": by, "why": reason}).mappings().one()
    return _row(row)


def retire(conn, uid, by):
    row = conn.execute(text(
        "update records.identity_link set retired_at = now(), retired_by = :by "
        "where source = :s and uid = :u and retired_at is null returning *"),
        {"s": SOURCE, "u": int(uid), "by": by}).mappings().first()
    if row:
        field_decisions.retire_link_defaults(conn, row["customer_no"], row["contact_code"], by)   # fix-all P5
    return _row(row) if row else None
