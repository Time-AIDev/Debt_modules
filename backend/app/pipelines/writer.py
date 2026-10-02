"""One import_run of source ODOO, written in batches, with a ledger of what it
replaced.

The ledger exists because of a decision taken on 2026-09-11: ODOO wins over SHEET,
which is landing._PRECEDENCE as it already stands. That was harmless while Odoo
contributed five rows that touched no sheet customer; with 34,401 it overlaps — 58 of
58 sheet rows matched a lead by phone — so a blank or zero in Odoo now replaces a real
sheet value. The rule stands as chosen and its cost is written down instead: per
volt_id, per field, both values kept, so §6 of the rules file can be changed on
evidence rather than on argument.
"""
import collections
import hashlib
import json
import re

from sqlalchemy import text

from .. import landing
from .crm_lead import mask_phone, phone_key      # the same mask the customer object serves
from .peak_match import normalise_code, _digits as _phone_digits   # one normaliser, not two

LEDGER_FIELDS = ("name_th", "name_roman", "epc", "product", "sales_lead",
                 "phone_e164", "email_masked", "customer_no", "line_id", "meta_id")

# 2026-09-20: the full number must not land in a run's meta. `overwrite_ledger` and
# `proposals` are served (the receipt's sample, the paginated landing-run route), and
# since the phone stopped being masked at import the ledger would otherwise carry the
# sheet's real number on both sides. The ledger still records THAT the phone changed —
# both sides on the same mask the customer object serves. The case's audited
# phone:reveal route is the only door that answers the number itself.
_PHONE_LEDGER_FIELDS = ("phone_e164",)


def _ledger_value(field, value):
    if field in _PHONE_LEDGER_FIELDS:
        # The mask the reader/serving layer would show: a +66 number is masked on
        # its national form ("08x-xxx-3333"), not on "66x-xxx-3333".
        text = str(value or "").strip()
        if text.startswith("+66"):
            text = "0" + text[3:]
        return mask_phone(text)
    return value

def _differs(field, old, new):
    """A filled old value the new one does not repeat. Phones compare on their last
    nine digits: "+66899999999" and "089-999-9999" are one number, not a proposal."""
    if old in (None, ""):
        return False
    if field in _PHONE_LEDGER_FIELDS:
        return phone_key(old) != phone_key(new)
    return old != new


def _digest(record):
    """sha256 of the normalised lead: the same lead pulled twice digests the same, so
    NEW_ONLY can tell an unchanged lead from a changed one without comparing fields."""
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()


def _odoo_digests(conn):
    """{volt_id: row_digest} for every live ODOO row (OK run, not retired). A row
    landed before digests existed maps to None, so it reads as changed once; a
    retired row is absent, so a lead that comes back lands as new."""
    return dict(conn.execute(text(
        "select t.volt_id, t.row_digest from landing.\"order\" t %s "
        "where t.data_source = 'ODOO'" % landing._ok_runs_clause())).all())


# A NEW_ONLY pull may retire at most this share of the live Odoo rows that an earlier
# pull of this code landed (they carry a digest) and that the book serves (not a
# lead-/phone- placeholder). A complete-but-wrong pull (the integration user's
# record rules narrowed, a lost field_map row turning every lead into a placeholder)
# would otherwise empty the Odoo part of the book. Legacy rows — the sale.order
# sync's, phone- keys, anything landed before digests — are outside the count: the
# first pull after 2026-09-25 retires them by design. An OVERWRITE run (a manager's
# own act) is not limited.
MAX_RETIRE_SHARE = 0.2


class TooMuchToRetire(Exception):
    code = "pull_would_retire_too_much"


class PreviewCountMismatch(Exception):
    code = "eligibility_preview_mismatch"


_VID = re.compile(r"^(V[A-Z]{1,2}\d{7})")

MODES = ("NEW_ONLY", "OVERWRITE")


def retirement_preview(conn, records):
    """Count the exact live Odoo customers a NEW_ONLY apply would soft-retire.

    This deliberately uses the writer's match and digest rules. The preview token
    is useful only when it predicts the same set the eventual transaction sees.
    """
    unique = {}
    for record in records:
        unique[record["volt_id"]] = record
    records = list(unique.values())
    index = _sheet_index(conn)
    landed_before = _odoo_digests(conn)
    # Eligibility is a source-level decision. An eligible Odoo row remains in the
    # keep set even when a SHEET row wins serving precedence for that customer.
    seen, held_by_sheet = set(unique), set()
    for record in records:
        sheet, matched_by, _shared_by = _resolve_existing(index, record)
        if sheet is not None:
            if matched_by != "PHONE":
                held_by_sheet.add(record["volt_id"])
    live = set(conn.execute(text(
        "select volt_id from landing.customer where data_source='ODOO' and retired_at is null"
    )).scalars().all())
    would_retire = len(live - seen) if seen else 0
    served = {key for key, digest in landed_before.items()
              if digest and not key.startswith(landing.PLACEHOLDER_PREFIXES)}
    guarded_retire = len({key for key in served if key not in seen and key not in held_by_sheet})
    return {"eligible_unique": len(records), "live_odoo": len(live),
            "would_retire": would_retire, "guarded_retire": guarded_retire,
            "held_by_sheet": len(held_by_sheet)}


def _sheet_rows(conn):
    """What SHEET holds today, newest run first, keyed by volt_id.

    This used to bind every ODOO record's volt_id to `= any(:ids)` — 350,000
    elements at the 2026-09-20 bench, built and shipped on every pull to compare
    against a table holding the sheet's own few hundred rows. The sheet side is the
    small side: read it whole and index it here.
    """
    rows = conn.execute(text(
        "select t.* from landing.customer t "
        "join landing.import_run r on r.id = t.import_run_id and r.status = 'OK' "
        "where t.data_source = 'SHEET' and t.retired_at is null "
        "order by t.import_run_id desc, t.volt_id")).mappings().all()
    out = {}
    for row in rows:
        out.setdefault(row["volt_id"], dict(row))
    return out


def _sheet_index(conn):
    """Every SHEET customer from an OK run, indexed three ways. This is §1 of the rules
    file finally applied (rows 1–3: customer number, phone, V-id prefix), the keys the
    2026-09-11 comparison measured at 58/58, 58/58 and 0/58-exact.

    Rows are read newest run first, and for by_no/by_vid the first row seen for a key
    wins — deterministic, and it is always the newest import. by_phone maps a phone to
    the list of distinct customers (distinct by customer_no) who carry it, because a
    phone is not always one customer: a family or a company can share it, and treating
    the last row an unordered scan happened to see as *the* owner would silently
    swallow whichever other customer holds the same number.
    """
    rows = conn.execute(text(
        "select t.* from landing.customer t "
        "join landing.import_run r on r.id = t.import_run_id and r.status = 'OK' "
        "where t.data_source = 'SHEET' and t.retired_at is null "
        "order by t.import_run_id desc, t.volt_id")).mappings().all()
    by_no, by_phone, by_vid = {}, {}, {}
    for r in rows:
        r = dict(r)
        no = str(r["customer_no"]) if r.get("customer_no") else None
        if no and no not in by_no:
            by_no[no] = r
        ph = _phone_digits(r.get("phone_e164"))
        if ph:
            bucket = by_phone.setdefault(ph, [])
            if not any(b.get("customer_no") == r.get("customer_no") for b in bucket):
                bucket.append(r)
        m = _VID.match(normalise_code(r.get("volt_id")))
        if m and m.group(1) not in by_vid:
            by_vid[m.group(1)] = r
    return by_no, by_phone, by_vid


def _resolve_existing(index, record):
    """(sheet_row, matched_by, shared_by) for a lead the book already holds — sheet
    and matched_by are None when nothing resolves. shared_by is None unless the only
    near-match is a phone two or more SHEET customers carry; then it lists their
    customer numbers and the lead is left unresolved (never silently attached to
    whichever one a dict happened to keep)."""
    by_no, by_phone, by_vid = index
    no = str(record.get("customer_no") or "")
    if no and no in by_no:
        return by_no[no], "CUSTOMER_NO", None
    vid = normalise_code(record.get("volt_id"))
    m = _VID.match(vid)
    if m and m.group(1) in by_vid:
        return by_vid[m.group(1)], "VOLT_ID", None
    ph = _phone_digits(record.get("phone_e164"))
    if ph and ph in by_phone:
        bucket = by_phone[ph]
        if len(bucket) == 1:
            return bucket[0], "PHONE", None
        return None, None, [b.get("customer_no") for b in bucket]
    return None, None, None


def _proposal(sheet, record, matched_by):
    fields = []
    for field in LEDGER_FIELDS:
        old, new = sheet.get(field), record.get(field)
        if _differs(field, old, new):
            fields.append({"field": field, "sheet": _ledger_value(field, old),
                           "odoo": _ledger_value(field, new),
                           "odoo_blank": new in (None, "")})
    sheet_vid = _VID.match(normalise_code(sheet.get("volt_id")))
    odoo_vid = _VID.match(normalise_code(record.get("volt_id")))
    kind = "FIELDS_DIFFER"
    if odoo_vid and matched_by != "VOLT_ID" and (not sheet_vid or sheet_vid.group(1) != odoo_vid.group(1)):
        kind = "NEW_CONTRACT_FOR_EXISTING"       # the package-change trace, reported not applied
    return {"kind": kind, "customer_no": sheet.get("customer_no"), "sheet_volt_id": sheet.get("volt_id"),
            "odoo_volt_id": record.get("volt_id"), "matched_by": matched_by, "fields": fields}


def write(conn, records, verdicts, batch=1000, on_progress=None, read=None, door=None,
          mode="OVERWRITE", run_id=None, retire=False, exclusion_counts=None,
          expected_retire=None, preserve_identity_links=False,
          refresh_source_rows=False):
    """Land one crm.lead run. `run_id` continues a RUNNING row the caller committed
    before the fetch (service.run_odoo); without it a run is started here.

    NEW_ONLY lands only what changed: a lead the sheet already holds is skipped (and
    proposed), a lead whose digest matches its live ODOO row is `unchanged` and not
    rewritten, the rest are `new` (no live row) or `changed`. `retire=True` says the
    pull was complete: every live ODOO row it did not see — landed, unchanged, or
    skipped for a sheet row that shares only its phone — is retired; a lead the sheet
    holds by customer number or V-id is not seen, so its old ODOO row retires unless
    `refresh_source_rows` keeps the eligible Odoo source row current behind the
    served Sheet row. A
    NEW_ONLY pull that would retire more than MAX_RETIRE_SHARE of the served Odoo
    rows — not counting the ones the sheet now holds — raises TooMuchToRetire before
    anything is written."""
    if mode not in MODES:
        raise ValueError("mode is NEW_ONLY or OVERWRITE, not %r" % mode)
    run = run_id or landing.start_run(conn, "ODOO")

    # A payload may hold two leads for one volt_id — Odoo's crm.lead does, since the
    # same customer number can sit on more than one lead. The landing upsert is ONE
    # `insert ... on conflict (volt_id, data_source) do update`, and Postgres refuses
    # a command that would touch one row twice ("ON CONFLICT DO UPDATE command cannot
    # affect row a second time"). Staging's first fresh pull hit exactly that
    # (2026-09-21) while the long-lived local landing had never seen the two rows in
    # one batch. The pull is ordered by Odoo id, so the LAST row is the newest lead
    # and wins; the dropped ones are counted, never silent.
    unique, position, duplicates = [], {}, 0
    for record in records:
        key = record["volt_id"]
        if key in position:
            unique[position[key]] = record
            duplicates += 1
        else:
            position[key] = len(unique)
            unique.append(record)
    records = unique
    digests = {r["volt_id"]: _digest(r) for r in records}

    proposals, skipped, unchanged, held_by_phone, held_by_sheet = [], 0, [], [], set()
    sheet_links = {}
    new_count = changed_count = None
    if mode == "NEW_ONLY":
        index = _sheet_index(conn)
        landed_before = _odoo_digests(conn)
        kept, new_count, changed_count = [], 0, 0
        for record in records:
            sheet, matched_by, shared_by = _resolve_existing(index, record)
            if sheet is not None:
                skipped += 1
                prop = _proposal(sheet, record, matched_by)
                if prop["fields"] or prop["kind"] == "NEW_CONTRACT_FOR_EXISTING":
                    proposals.append(prop)
                # Only a sheet row that IS this lead (same customer number or V-id)
                # gets an identity link. A shared phone is another contract and must
                # never be linked automatically.
                if matched_by == "PHONE":
                    held_by_phone.append(record["volt_id"])
                else:
                    held_by_sheet.add(record["volt_id"])
                    # 2026-10-01: before the old ODOO landing row retires, keep the
                    # cross-system fact it carried — this crm.lead id is this customer.
                    # The served row is the SHEET one and its `crm_id` is the Freshworks
                    # deal id, so without this the case has no Odoo link at all.
                    lead_id = (record.get("order") or {}).get("crm_id")
                    # The SHEET customer number: that is the row the book serves, so
                    # that is the key the serving read must find (a V-id match can
                    # carry a different Odoo customer_no than the sheet's).
                    no = sheet.get("customer_no") or record.get("customer_no")
                    if lead_id and no:
                        sheet_links[record["volt_id"]] = (no, lead_id)
                if not refresh_source_rows:
                    continue
            if shared_by:
                proposals.append({"kind": "SHARED_PHONE", "customer_no": None,
                                  "sheet_volt_id": None, "odoo_volt_id": record.get("volt_id"),
                                  "matched_by": "PHONE", "shared_by": shared_by, "fields": []})
            key = record["volt_id"]
            if key not in landed_before:
                new_count += 1
            elif landed_before[key] == digests[key]:
                unchanged.append(key)
                continue
            else:
                changed_count += 1
            kept.append(record)
        records = kept
        if retire:
            seen = {r["volt_id"] for r in records} | set(unchanged) | set(held_by_phone)
            served = [k for k, digest in landed_before.items()
                      if digest and not k.startswith(landing.PLACEHOLDER_PREFIXES)]
            # A row the sheet now holds (same customer number or V-id) retires by
            # design — the sheet taking over is not a lead gone from Odoo, so only a
            # lead truly missing from the pull counts against the cap (2026-09-25:
            # runs 325-334 refused after the sheet took over 1,667 of 2,630 rows).
            gone = sum(1 for k in served if k not in seen and k not in held_by_sheet)
            live = set(conn.execute(text(
                "select volt_id from landing.customer "
                "where data_source='ODOO' and retired_at is null"
            )).scalars().all())
            projected_retire = len(live - seen) if seen else 0
            if expected_retire is not None and projected_retire != expected_retire:
                raise PreviewCountMismatch(
                    "preview expected %d retirements but current data would retire %d"
                    % (expected_retire, projected_retire))
            if expected_retire is None and gone > MAX_RETIRE_SHARE * len(served):
                raise TooMuchToRetire(
                    "this pull would retire %d of the %d served Odoo rows (the limit is %d%%)"
                    % (gone, len(served), MAX_RETIRE_SHARE * 100))

    before = _sheet_rows(conn)

    ledger = []
    for record in records:
        sheet = before.get(record["volt_id"])
        if not sheet:
            continue
        for field in LEDGER_FIELDS:
            old, new = sheet.get(field), record.get(field)
            if _differs(field, old, new):
                ledger.append({"volt_id": record["volt_id"], "field": field,
                               "sheet": _ledger_value(field, old),
                               "odoo": _ledger_value(field, new)})

    orders = []
    for record in records:
        order = dict(record.get("order") or {})
        order.setdefault("reason", record["reason"])
        order["row_digest"] = digests[record["volt_id"]]      # its own column, never served
        orders.append((record["volt_id"], order))
    landing.write_customers(conn, run, "ODOO", records)
    landing.write_orders(conn, run, "ODOO", orders, batch=batch,
                         on_progress=(lambda written: on_progress(landed=written)) if on_progress else None)
    landed = len(records)
    written = {r["volt_id"] for r in records}
    seen = written | set(unchanged) | set(held_by_phone)
    retired = 0
    if retire and seen:
        retired = landing.retire_unseen(conn, "ODOO", seen)
    if expected_retire is not None and retired != expected_retire:
        raise PreviewCountMismatch(
            "preview expected %d retirements but apply retired %d"
            % (expected_retire, retired))
    # The Odoo-lead links the merge resolved (see odoo_links). A complete pull also
    # closes a link whose lead it no longer returned. Never for OVERWRITE: that mode
    # performs no sheet match, so an empty `desired` would retire the whole register.
    links_added = links_retired = 0
    if mode == "NEW_ONLY":
        from . import odoo_links
        links_added, links_retired = odoo_links.reconcile(
            conn, sheet_links, retire=retire and not preserve_identity_links)

    rejected = collections.Counter(v["rule"] for v in verdicts
                                   if v["verdict"] == "rejected" and v["rule"])
    # Unmapped values go to their own table — and only for the leads this run wrote:
    # an unchanged lead's values are already there under the run that landed it.
    # On meta they were one entry per lead: 700k at the 350k bench, ~400 MB of Python
    # decoded on every read of the run. The receipt keeps a sample and a total.
    unmapped_rows, unmapped_sample, unmapped_total = [], [], 0
    for v in verdicts:
        volt_id = v.get("volt_id")
        if volt_id not in written:
            continue
        for item in v.get("unmapped") or []:
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                continue
            unmapped_total += 1
            if len(unmapped_sample) < 20:
                unmapped_sample.append([item[0], item[1]])
            unmapped_rows.append((volt_id, str(item[0]), str(item[1])))
    landing.write_unmapped(conn, run, unmapped_rows)
    # `read` is what the door handed normalise(); when the caller does not say
    # (older tests, direct writer use) it is landed + rejected — never invented
    # from anything else.
    effective_read = read if read is not None else landed + sum(rejected.values())
    unchanged_count = len(unchanged) if mode == "NEW_ONLY" else None
    conn.execute(text("update landing.import_run set meta = cast(:m as jsonb) where id = :i"),
                 {"m": json.dumps({"rejected": dict(rejected),
                                   "duplicates": duplicates,
                                   "unmapped_sample": unmapped_sample,
                                   "unmapped_total": unmapped_total,
                                   "overwrite_ledger": ledger,
                                   "reason": "no money row in Odoo",
                                   "eligibility_exclusions": exclusion_counts or {},
                                   "door": door, "read": effective_read,
                                   "mode": mode, "new": new_count, "changed": changed_count,
                                   "unchanged": unchanged_count, "retired": retired,
                                   "links_added": links_added, "links_retired": links_retired,
                                   "skipped": skipped, "proposals": proposals},
                                  ensure_ascii=False, default=str), "i": run})
    landing.finish_run(conn, run, "OK",
                       row_counts={"landed": landed, "rejected": sum(rejected.values()),
                                   "overwrote": len(ledger), "read": effective_read,
                                   "skipped": skipped, "duplicates": duplicates})
    return {"run_id": run, "import_run_id": run, "landed": landed, "duplicates": duplicates,
            "rejected": sum(rejected.values()), "overwrote": len(ledger),
            "read": effective_read, "door": door, "ledger": ledger,
            "mode": mode, "new": new_count, "changed": changed_count,
            "unchanged": unchanged_count, "retired": retired,
            "links_added": links_added, "links_retired": links_retired,
            "skipped": skipped, "proposals": proposals}
