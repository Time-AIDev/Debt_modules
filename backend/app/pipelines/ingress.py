"""The Odoo door: crm.lead rows keyed by FIELD NAME, as normalise() takes them.

The crm.lead file door went on 2026-09-25 (fix-all): the New Order Master sheet lands
through POST /v1/imports, and this pipeline reads Odoo only.
"""
from ..integrations import odoo
from ..crm_policy import won_only

PAGE = 500
ELIGIBILITY_DOMAIN = [
    ("stage_name", "=", "Won"),
    ("epc_start_date", "!=", False),
    ("epc_end_date", "!=", False),
]
EXCLUSION_DOMAINS = {
    "not_won": [("stage_name", "!=", "Won")],
    "install_start_missing": [("stage_name", "=", "Won"),
                              ("epc_start_date", "=", False)],
    "install_end_missing": [("stage_name", "=", "Won"),
                            ("epc_start_date", "!=", False),
                            ("epc_end_date", "=", False)],
}


def eligibility_domain():
    return ELIGIBILITY_DOMAIN[:1] if won_only() else ELIGIBILITY_DOMAIN


def _fields(rules):
    """Exactly what §2 of the rules file maps, plus the source id and title. Adding a row to that table
    adds the field to the pull; there is no constant here to keep in step with it."""
    named = [r["crm.lead field"] for r in rules.field_map
             if r["crm.lead field"] not in ("—", "")]
    return sorted(set(named) | {"id", "name"})


def from_odoo(rules, execute=None, on_progress=None, on_exclusions=None):
    """`on_progress(read=, total=)` after each page — reported by the code doing the
    work, so the bar can never claim progress the pull did not make.

    Keyset paging (id > the last id seen, ordered by id), not offsets: a lead Odoo
    deletes mid-pull would shift every later offset and skip a live lead, which a
    complete pull then retires. A pull that comes back shorter than Odoo's own count
    still fails — a short page must never retire the tail. Odoo counts before and
    after the read and the smaller count is the bar: a lead deleted mid-read lowers the
    second, and must not fail a pull that read every lead still there."""
    execute = execute or odoo._execute
    config = odoo._config()
    uid = odoo._login(config)
    fields = _fields(rules)
    domain = eligibility_domain()
    exclusions = {"not_won": EXCLUSION_DOMAINS["not_won"]} if won_only() else EXCLUSION_DOMAINS
    if on_exclusions:
        on_exclusions({name: execute(config, uid, "crm.lead", "search_count", [domain])
                       for name, domain in exclusions.items()})
    total = execute(config, uid, "crm.lead", "search_count", [domain])
    rows, last_id = [], 0
    while True:
        page = execute(config, uid, "crm.lead", "search_read", [domain + [("id", ">", last_id)]],
                       {"fields": fields, "limit": PAGE, "order": "id"})
        if not page:
            break
        rows.extend(page)
        last_id = page[-1]["id"]
        if on_progress:
            on_progress(read=len(rows), total=total)
    counted = min(total, execute(config, uid, "crm.lead", "search_count", [domain]))
    if len(rows) < counted:
        raise odoo.OdooError("Odoo returned %d of the %d leads it counted" % (len(rows), counted))
    return rows
