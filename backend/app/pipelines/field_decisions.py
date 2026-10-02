"""D02 / Q7 (feedback-r2 TASK-207): a person's per-field decision on the served record.

The row is the provenance: PEAK says X · Odoo says Y · chosen by whom, when, why.
Nothing is written back to Odoo (CON-201); the served record overlays the active PEAK
decisions at read time, and retiring one restores the Odoo value.
"""
from sqlalchemy import text

FIELDS = ("customer_name", "volt_id", "product", "system_size_kwp")


def load(conn, customer_nos=None):
    """{customer_no: {field: row}} of the ACTIVE decisions, optionally narrowed. A PEAK
    decision with no PEAK value is skipped: overlaying it would blank the field
    (fix-all P3 backstop)."""
    clause, params = "", {}
    if customer_nos is not None:
        nos = [str(no) for no in customer_nos if no]
        if not nos:
            return {}
        clause = "and customer_no = any(:nos)"
        params["nos"] = nos
    rows = conn.execute(text(
        "select * from records.field_decision where retired_at is null "
        "and not (chosen_source = 'PEAK' and peak_value is null) %s order by uid" % clause),
        params).mappings().all()
    out = {}
    for r in rows:
        out.setdefault(r["customer_no"], {})[r["field"]] = dict(r)
    return out


def decide(conn, customer_no, field, source, by, reason=None, run_id=None,
           peak_value=None, odoo_value=None):
    """One decision; the previously active row for the same field is retired first
    (peak_links.confirm's own shape)."""
    conn.execute(text(
        "update records.field_decision set retired_at = now(), retired_by = :by "
        "where customer_no = :n and field = :f and retired_at is null"),
        {"n": str(customer_no), "f": field, "by": by})
    row = conn.execute(text(
        "insert into records.field_decision (customer_no, field, chosen_source, peak_value, odoo_value, "
        "decided_by, reason, run_id) values (:n, :f, :s, :p, :o, :by, :why, :run) returning *"),
        {"n": str(customer_no), "f": field, "s": source, "p": peak_value, "o": odoo_value,
         "by": by, "why": reason, "run": run_id}).mappings().one()
    return dict(row)


def retire(conn, uid, by):
    row = conn.execute(text(
        "update records.field_decision set retired_at = now(), retired_by = :by "
        "where uid = :u and retired_at is null returning *"),
        {"u": int(uid), "by": by}).mappings().first()
    return dict(row) if row else None


def default_all(conn, run_id, by):
    """Q7: on apply, every conflict of the run with no active decision takes PEAK,
    recorded as a system default with the applier's name. Returns how many were
    inserted — the apply response serves it as `defaulted_fields`.

    Fix-all P5 (audit): the rows are peak_writer.conflict_rows — only those the book
    serves to their customer now, so a link retired or re-pointed before the apply
    defaults nothing onto the customer it used to name. The reason names the invoice a
    default came from, so retiring a link takes back only what its own rows defaulted."""
    from .peak_writer import conflict_rows          # peak_writer imports this module
    rows = conflict_rows(conn, run_id)
    active = load(conn, [r["customer_no"] for r in rows])
    inserted, seen = 0, set()
    for r in rows:
        no = r["customer_no"]
        if not no:
            continue
        for c in (r["conflicts"] or []):
            # fix-all P5 (F8): volt_id's PEAK side is the matched contact code's head;
            # defaulting it replaced the customer's own id. Only a person decides it.
            if c.get("same") or c.get("field") == "volt_id":
                continue
            key = (no, c.get("field"))
            if key in seen or active.get(no, {}).get(c.get("field")):
                continue
            seen.add(key)
            decide(conn, no, c["field"], "PEAK", by=by,
                   reason="default PEAK on apply by %s from %s" % (by, r["doc_no"]), run_id=run_id,
                   peak_value=c.get("peak_value"), odoo_value=c.get("odoo_value"))
            inserted += 1
    return inserted


# peak_writer's normaliser, which matches peak_match.normalise_code (all whitespace, upper case).
_NORM = "upper(regexp_replace(coalesce(%s, ''), '[[:space:]]+', '', 'g'))"


def retire_link_defaults(conn, customer_no, code, by):
    """Fix-all P5 (F8): the fields an apply defaulted onto a customer through a link on
    `code` (already normalised, as the register stores it) leave with that link, so a
    retired or re-pointed link never leaves another contact's name on this customer.
    Only a default whose own invoice (named in its reason) is a LINK row on that code;
    one from the customer's own invoice, and a person's own decision, stay. A default
    written before its invoice was named keeps the broader rule it was written under.
    Returns the retired uids."""
    return conn.execute(text(
        "update records.field_decision d set retired_at = now(), retired_by = :by "
        "where d.customer_no = :n and d.retired_at is null "
        "and exists (select 1 from landing.peak_invoice p where p.import_run_id = d.run_id "
        "and p.customer_no = d.customer_no and p.rule = 'LINK' and (%s = :c or %s = :c) "
        "and d.reason in ('default PEAK on apply by ' || d.decided_by || ' from ' || p.doc_no, "
        "'default PEAK on apply by ' || d.decided_by)) "
        "returning d.uid" % (_NORM % "p.contact_code", _NORM % "p.reference")),
        {"n": str(customer_no), "c": code, "by": by}).scalars().all()
