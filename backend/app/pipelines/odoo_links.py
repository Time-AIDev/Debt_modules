"""The automatic Odoo-lead link a crm.lead pull leaves behind.

records.identity_link rows with source 'ODOO_CRM_LEAD'. When a complete crm.lead
pull finds a lead the SHEET book already holds (matched by customer number or V-id),
the sheet wins serving precedence while the eligible ODOO source row can stay live.
The link is still required because the served SHEET row's `crm_id` is the Freshworks
deal id; it routes both the Odoo deep link and Odoo-owned contact handles to the
served customer (found 2026-10-01, Jessada Nonmaha).

`reconcile` records the link at merge time, before the landing row can retire, and
retires a link the pull no longer sees. PHONE-only matches never link: a shared
number is another contract (or another person) until a person confirms otherwise,
which is exactly why the writer already refuses to attach one.
"""
from sqlalchemy import text

SOURCE = "ODOO_CRM_LEAD"
# confirmed_by is NOT NULL and this is not a person's confirmation: the sync did it.
BY = "system:odoo-sync"


def active(conn):
    """{contact_code: {customer_no, odoo_lead_id}} — active Odoo links, keyed by the
    lead's volt_id (the contact_code of an ODOO_CRM_LEAD row)."""
    rows = conn.execute(text(
        "select contact_code, customer_no, odoo_lead_id from records.identity_link "
        "where source = :s and retired_at is null"), {"s": SOURCE}).mappings().all()
    return {r["contact_code"]: dict(r) for r in rows}


def active_for_customers(conn, customer_nos):
    """{customer_no: odoo_lead_id} for the book's read. A customer with more than one
    linked lead serves the newest link (highest uid)."""
    nos = [str(n) for n in customer_nos if n]
    if not nos:
        return {}
    rows = conn.execute(text(
        "select customer_no, odoo_lead_id from records.identity_link "
        "where source = :s and retired_at is null and customer_no = any(:nos) "
        "order by uid"), {"s": SOURCE, "nos": nos}).mappings().all()
    out = {}
    for row in rows:
        out[str(row["customer_no"])] = row["odoo_lead_id"]   # ascending uid: last wins
    return out


def social_for_customers(conn, customer_nos):
    """{customer_no: {line_id, meta_id}} from each linked live Odoo source row.

    Sheet remains the served/customer-owned row; these two contact handles are Odoo
    source fields and therefore follow the active Odoo identity link instead of being
    copied into (and later going stale on) the Sheet landing row.
    """
    nos = [str(n) for n in customer_nos if n]
    if not nos:
        return {}
    rows = conn.execute(text(
        "select l.customer_no, c.line_id, c.meta_id "
        "from records.identity_link l "
        "join landing.customer c on c.volt_id = l.contact_code "
        "and c.data_source = 'ODOO' and c.retired_at is null "
        "join landing.import_run r on r.id = c.import_run_id and r.status = 'OK' "
        "where l.source = :s and l.retired_at is null and l.customer_no = any(:nos) "
        "order by l.uid"), {"s": SOURCE, "nos": nos}).mappings().all()
    out = {}
    for row in rows:
        out[str(row["customer_no"])] = {
            "line_id": row["line_id"], "meta_id": row["meta_id"],
        }
    return out


def reconcile(conn, desired, retire=False, by=BY):
    """Write the links a NEW_ONLY pull resolved, and (complete pull) retire the rest.

    `desired` is {odoo volt_id: (customer_no, odoo_lead_id)}. A changed pair re-points
    the link: the old row retires, a new one is written, history stays. With
    `retire=True` every active link the pull did not see is retired — a lead deleted
    or archived in Odoo stops claiming a book customer.

    Returns (added, retired) so the run can say what moved and the caller can rebuild
    the book when only the link changed.
    """
    existing = conn.execute(text(
        "select uid, contact_code, customer_no, odoo_lead_id from records.identity_link "
        "where source = :s and retired_at is null"), {"s": SOURCE}).mappings().all()
    by_code = {r["contact_code"]: dict(r) for r in existing}
    added = retired = 0
    for code, pair in desired.items():
        customer_no, lead_id = pair
        if customer_no in (None, "") or lead_id in (None, ""):
            continue
        row = by_code.get(code)
        if row and str(row["customer_no"]) == str(customer_no) and row["odoo_lead_id"] == int(lead_id):
            continue
        if row:
            conn.execute(text(
                "update records.identity_link set retired_at = now(), retired_by = :by "
                "where uid = :u and retired_at is null"), {"u": row["uid"], "by": by})
            retired += 1
        conn.execute(text(
            "insert into records.identity_link "
            "(source, contact_code, customer_no, odoo_lead_id, rule, confirmed_by, reason) "
            "values (:s, :c, :n, :l, :r, :by, :why)"),
            {"s": SOURCE, "c": code, "n": str(customer_no), "l": int(lead_id),
             "r": SOURCE, "by": by,
             "why": "auto: crm.lead pull matched the sheet customer"})
        added += 1
    if retire:
        for code, row in by_code.items():
            if code in desired:
                continue
            conn.execute(text(
                "update records.identity_link set retired_at = now(), retired_by = :by "
                "where uid = :u and retired_at is null"), {"u": row["uid"], "by": by})
            retired += 1
    return added, retired
