"""Where the book comes from — and nothing else in the domain needs to know.

load() returns exactly the dict shape backend/app/fixtures_sheet.json has, which
is exactly what book.build() already consumes. That is the whole trick: the 32
domain modules and the 158 endpoints are untouched because the shape they receive
never changes, only its origin does.

Three states (spec §5.2.1):
  DATABASE_URL unset   read the fixture, exactly as before there was a database
  set and reachable    read the landing schema
  set but unreachable  raise. Never fall back — that would look like success.
"""
import json
import threading
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from datetime import date as _date, datetime as _datetime
from decimal import Decimal as _Decimal
from pathlib import Path

from sqlalchemy import text

from . import clock, db, landing

FIXTURE_PATH = Path(__file__).with_name("fixtures_sheet.json")

# The source block is served by two hot readers (the workbook header, /v1/data-state)
# and its counts are `count(distinct volt_id)` over the whole landing table — measured
# 111 ms per call on 34k rows, 1.1 s at the 350k bench. It can only change when an
# import lands, which is exactly what the epoch records, so it is cached per epoch.
# `forget_summary()` is called from book.invalidate() so tests that swap the landing
# without an epoch see fresh counts.
class _SummaryCache:
    """Bounded per-key singleflight; unrelated databases/snapshots never wait."""
    def __init__(self):
        self.lock = threading.RLock()
        self.entries = OrderedDict()
        self.building = {}
        self.version = 0

    def clear(self):
        with self.lock:
            self.version += 1
            self.entries.clear()

    def value(self, key, build):
        with self.lock:
            key = (self.version, *key)
        while True:
            with self.lock:
                saved = self.entries.pop(key, None)
                if saved is not None:
                    self.entries[key] = saved
                    return deepcopy(saved)
                flight = self.building.get(key)
                if flight is None:
                    if len(self.building) >= 8:
                        break
                    flight = threading.Event()
                    self.building[key] = flight
                    break
            flight.wait()
        if flight is None:
            return build()
        try:
            value = build()
            with self.lock:
                self.entries[key] = deepcopy(value)
                while len(self.entries) > 8:
                    self.entries.popitem(last=False)
            return value
        finally:
            with self.lock:
                self.building.pop(key, None)
                flight.set()


_SUMMARY = _SummaryCache()


def forget_summary():
    _SUMMARY.clear()


# Fix-all F3: a PEAK apply rebuilds the book, and every rebuild re-read the whole served
# slice of landing (~3 s at the 10x bench) though only PEAK data had moved. All of it
# but the PEAK invoices and the field decisions changes only when a non-PEAK landing
# bumps the epoch — refresh.after_landing bumps before it rebuilds — so it is kept per
# the last non-PEAK epoch. book.invalidate() drops it; main.reload_book keeps it.
# One (key, reads) tuple, swapped in whole, so two builds racing across a bump can
# never pair one epoch's key with another's rows.
# ponytail: one more copy of the served slice's rows in memory; key it per table if
# that ever matters.
_READS = {"entry": None}


def forget_reads():
    _READS["entry"] = None


def _non_peak_reads(conn):
    from sqlalchemy import text
    # Read BEFORE the rows: a landing commits before its bump, so the rows read after
    # this key hold at least everything the key names.
    key = conn.execute(text("select coalesce(max(id), 0) from app.data_epoch "
                            "where kind not like 'peak%'")).scalar()
    entry = _READS["entry"]
    if entry is None or entry[0] != key:
        sheet_run = landing.last_run(conn, "SHEET")
        customers = landing.resolved_customers(conn, shaped_only=True)
        merged = _merged(customers) if sheet_run else {}
        customers = [c for c in customers if c["volt_id"] not in merged]
        volt_ids = [c["volt_id"] for c in customers]
        entry = _READS["entry"] = (key, {
            "sheet_run": sheet_run, "odoo_run": landing.last_lead_run(conn),
            "customers": customers, "merged": len(merged),
            "merged_pairs": list(merged.values()),
            "landed": landing.count_customers(conn),
            "orders": landing.resolved_orders(conn, volt_ids=volt_ids),
            "blocks": landing.blocks_for(conn, volt_ids),
        })
    return entry[1]

# The block names, and the empty value each takes when the landing schema holds no
# row for it. An Odoo-only customer has none of them, which is the point.
BLOCK_DEFAULTS = {"leasing": None, "tracking": None, "cash": None,
                  "cash_invoices": [], "asset": None, "contact_log": [], "peak": None}


def _as_fixture_scalar(value):
    """Postgres types back into the shapes fixtures_sheet.json uses.

    The seam's whole contract is that the payload is INDISTINGUISHABLE from the
    fixture, and types are part of a shape. A date column returns datetime.date
    where the sheet had an ISO string, and the domain compares those against
    strings — which surfaced as
    "TypeError: '<' not supported between instances of 'datetime.date' and 'str'"
    inside the invoice pipeline's seed, i.e. a 500 on every pipeline request.
    Numerics come back as Decimal where the sheet had a string, the same trap one
    step behind.
    """
    if isinstance(value, (_date, _datetime)):
        return value.isoformat()
    if isinstance(value, _Decimal):
        return str(value)
    return value


def _as_fixture(mapping):
    return {k: _as_fixture_scalar(v) for k, v in mapping.items()}


def load():
    """The payload, or None when there is nothing to read at all."""
    if not db.configured():
        # Plan 2026-09-11 §1.3: a held fixture predates the capture date and will
        # never have one. It gets the KEY, set to None — "unknown", which the
        # payment position then refuses on, rather than a date nobody recorded.
        return _with_captured_on(_from_fixture())
    conn = db.connect()
    try:
        return _from_landing(conn)
    finally:
        conn.close()


def _iso_date(value):
    """A landing timestamp as a plain date string, or None. `finished_at` arrives
    as a datetime from the driver and as a string from a cached snapshot; both are
    accepted and neither is guessed at when absent. The day is Bangkok's: a run that
    finished at 18:30 UTC was captured on the NEXT Thai day."""
    if value in (None, ""):
        return None
    local = clock.to_local(value)
    if local is None:
        return (value.isoformat() if hasattr(value, "isoformat") else str(value))[:10]
    return local.date().isoformat()


def _iso_stamp(value):
    """A landing timestamp as its full ISO value, or None.

    Feedback Round 1 / final v2 (prototype 2363): the registry's note names the
    instant the book was imported, and `finished_at` already carries it. Truncating
    it to the day (as `captured_on` must, for the payment position's staleness
    check) would throw the time away and leave the note unable to say it.
    """
    if value in (None, ""):
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _with_captured_on(payload, captured_on=None, imported_at=None, import_started_at=None):
    """One place that guarantees the key exists on every load path.

    `setdefault`, not assignment: a payload that already carries its own capture
    date keeps it. Without this the fixture path and the landing path disagreed
    about whether the field exists at all, and every consumer would have had to
    guard for it separately."""
    if not payload:
        return payload
    source = payload.setdefault("source", {})
    source.setdefault("captured_on", captured_on)
    # The held fixture predates every import run, so it carries the KEY with None,
    # never a date nobody recorded. The migration report renders nothing for None.
    source.setdefault("imported_at", imported_at)
    source.setdefault("import_started_at", import_started_at)
    # Delta-100 DS1: the fixture IS the sheet render, so the rung serving the book
    # is named by the book's own source name, never a hardcoded label.
    source.setdefault("serving_code", "SHEET")
    source.setdefault("origin", "FIXTURE")
    source.setdefault("serving_name", source.get("spreadsheet") or "New Order Master")
    for rec in payload.get("customers") or []:
        rec.setdefault("peak", None)
    return payload


def _from_fixture():
    if not FIXTURE_PATH.exists():
        return None
    with open(FIXTURE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def source_summary():
    """The source block alone — no customer fixtures.

    The workbook header reads this on every request, and building the whole payload
    to print one label cost ~1.4 s on a 33k-row landing. The counts are the same
    numbers `load()` serves: the shaped slice counted in SQL, less the Odoo
    identities a sheet customer already is (read only when a SHEET run exists).

    The epoch is read from the SAME snapshot as the source rows, never the
    process epoch cache. Source publication changes it atomically under the
    global barrier. Mutations derive their own value and cannot publish an
    uncommitted summary to another request, including after rollback.
    """
    if not db.configured():
        return _SUMMARY.value(("fixtures", FIXTURE_PATH),
                              lambda: (_with_captured_on(_from_fixture()) or {}).get("source") or {})
    from .production_unit import CURRENT
    unit = CURRENT.get()
    with _summary_connection(unit) as conn:
        if unit and unit.get("mutation"):
            return _source_summary(conn)
        epoch = int(conn.execute(text("select coalesce(max(id),0) from app.data_epoch")).scalar_one())
        key = (conn.engine, epoch, landing.won_only())
        return _SUMMARY.value(key, lambda: _source_summary(conn))


@contextmanager
def _summary_connection(unit):
    if unit:
        yield unit["conn"]
    else:
        # Standalone readers also bind the epoch and counts to one committed
        # snapshot; a separate epoch checkout could race an import commit.
        with db.connect() as conn, conn.begin():
            conn.execute(text("set transaction isolation level repeatable read, read only"))
            yield conn


def _source_summary(conn):
    sheet_run = landing.last_run(conn, "SHEET")
    odoo_run = landing.last_lead_run(conn)
    landed = landing.count_customers(conn)
    merged = len(_merged(landing.resolved_customers(conn, shaped_only=True))) if sheet_run else 0
    served = landing.count_customers(conn, shaped_only=True) - merged
    return _source_block(sheet_run, odoo_run, served, landed, merged)


def _merged(rows):
    """{Odoo volt_id: (its customer_no, the SHEET customer_no it is)} — the Odoo
    identities a SHEET customer already is under another volt_id (Arina, 2026-09-24:
    the sheet is the book): the same customer number, or the same phone when exactly
    one sheet customer and one Odoo row hold it (a shared number — an agent's, a
    family's — never merges, as PEAK's matcher never matches one). The sheet's row
    serves the person and carries what was found under the Odoo number (PEAK
    invoices, links, field decisions — _landing_rows); these are counted as merged,
    never served twice. Same volt_id needs nothing here: landing serves SHEET."""
    from collections import Counter
    from .pipelines.crm_lead import phone_key

    def no(r):
        return str(r.get("customer_no") or "").strip().upper()

    def phone(r):
        return phone_key(r.get("phone_e164") or "")

    sheet = [r for r in rows if r["data_source"] == "SHEET"]
    odoo = [r for r in rows if r["data_source"] != "SHEET"]
    by_no = {no(r): r["customer_no"] for r in sheet if no(r)}
    held = Counter((r["data_source"] == "SHEET", phone(r)) for r in rows if phone(r))
    by_phone = {phone(r): r["customer_no"] for r in sheet
                if phone(r) and held[(True, phone(r))] == 1 and held[(False, phone(r))] == 1}
    out = {}
    for r in odoo:
        target = by_no.get(no(r)) or by_phone.get(phone(r))
        if target:
            out[r["volt_id"]] = (r.get("customer_no"), target)
    return out


def _source_block(sheet_run, odoo_run, served, landed, merged=0):
    run = sheet_run or odoo_run or {}
    meta = (sheet_run or {}).get("meta") or {}
    # Delta-100 DS1: which rung the served book is actually built from. The sheet is
    # the base whenever a SHEET run exists; an ODOO-only landing (no sheet run) is
    # served by the Odoo rung; with neither, the book is the stale system data.
    if sheet_run:
        serving_code, serving_name = "SHEET", "New Order Master"
    elif odoo_run:
        serving_code, serving_name = "ODOO", "Odoo crm.lead"
    else:
        serving_code, serving_name = "STALE_SYSTEM", None
    served_note_th = served_note_en = None
    if not sheet_run and odoo_run and landed > served:
        hidden = landed - served
        served_note_th = ("แสดง %d จาก %d รายที่นำเข้าจาก Odoo · อีก %d รายยังไม่มี VOLT ID"
                          " จึงยังไม่ปรากฏในสมุดงาน" % (served, landed, hidden))
        served_note_en = ("Serving %d of %d rows pulled from Odoo · %d have no VOLT id yet"
                          " and stay out of the book" % (served, landed, hidden))
    return {
        "spreadsheet": "New Order Master",
        "spreadsheet_id": run.get("spreadsheet_id"),
        "render": "landing schema (PostgreSQL)",
        # Which store the book was read from: the seed and the journey's demo rows
        # only exist beside the held fixture (fixtures.seed, journey._seed).
        "origin": "LANDING",
        "serving_code": serving_code,
        "serving_name": serving_name,
        # The served slice, stated on the wire so the chain and the workbook can
        # print it: rows the book serves, rows the last run landed, and the Odoo
        # identities served once as the sheet customer they already are.
        "served_customers": served,
        "landed_customers": landed,
        "merged_customers": merged,
        "served_note_th": served_note_th,
        "served_note_en": served_note_en,
        # Plan 2026-09-11 §1.3. The import run's own finish time is the only
        # honest answer to "as of when?" — not now(), which would make every
        # book look freshly captured the moment it is read.
        "captured_on": _iso_date(run.get("finished_at")),
        # Final v2 (prototype 2363): the registry note says when the import ran,
        # to the minute. Same source, kept whole — started_at is carried beside
        # it so a run still in flight can be told from a finished one.
        "imported_at": _iso_stamp(run.get("finished_at")),
        "import_started_at": _iso_stamp(run.get("started_at")),
        "pii": "phone kept whole for the dial actions (hidden at the serving layer, audited reveal); email masked; names, VOLT IDs, amounts, statuses and notes kept",
        "blocks": run.get("truncated_blocks") or [],
    }


def _from_landing(conn):
    # Odoo crm.lead is a 34k-row sign-up list of which most rows carry no VOLT id at
    # all; the workable slice is the rows the app can act on — the ones with a real
    # VOLT id. The rest are counted, never dropped silently, and the screens print
    # "served N of M". Arina, 2026-09-24: the slice holds whether or not a SHEET run
    # exists (the sheet no longer switches it off), and an Odoo identity the sheet
    # already holds under another volt_id is served once, as the sheet's row.
    #
    # The slice is applied by the DATABASE (the bench measured 17s shaping every
    # landed row in Python before throwing 93% of them away, and 2GB of transient
    # dicts with it). Which rows are shaped is therefore decided before the read —
    # in _non_peak_reads, which keeps them per non-PEAK epoch (fix-all F3).
    reads = _non_peak_reads(conn)
    sheet_run, odoo_run, customers = reads["sheet_run"], reads["odoo_run"], reads["customers"]
    # Pivots, flow stages and warnings are properties of the IMPORT, not of any
    # row, so they travel on import_run.meta. Returning empty ones instead cost
    # three e2e checks: the migration report could not reconcile CURRENT and
    # could not say why, which is exactly the dishonesty REQ-INT-032 forbids.
    meta = (sheet_run or {}).get("meta") or {}
    return {
        "source": _source_block(sheet_run, odoo_run, len(customers),
                                reads["landed"], reads["merged"]),
        "pivots": meta.get("pivots") or {"payment_status": [], "collection_tracking": [],
                                         "cash_invoices": []},
        "flow_stages": meta.get("flow_stages") or {"stages": [], "late_fee_logic": []},
        "counts": ((sheet_run or odoo_run or {}).get("row_counts") or {}),
        "warnings": meta.get("warnings") or [],
        "customers": _landing_rows(conn, customers, reads["orders"], reads["blocks"],
                                   reads["merged_pairs"]),
    }


def _fold_peak(blocks):
    """One PEAK block out of a sheet customer's own and its merged Odoo numbers'."""
    blocks = [b for b in blocks if b]
    if len(blocks) < 2:
        return blocks[0] if blocks else None
    return dict(blocks[0], report_as_of=max(b.get("report_as_of") or "" for b in blocks) or None,
                invoices=sorted((i for b in blocks for i in b["invoices"]),
                                key=lambda i: (i.get("due_on") or "", i["doc_no"])))


def _landing_rows(conn, customers, orders, blocks, merged=()):
    """The book's rows, resolved against orders, blocks and the applied PEAK run.

    Every read is restricted to the customers actually in the book. The previous
    shape loaded all 350k orders and every applied-run invoice as Python dicts, then
    attached the handful that belonged to a served customer. `orders` and `blocks`
    come from _non_peak_reads; the PEAK invoices and field decisions below are read
    on every build. `merged` is (odoo customer_no, sheet customer_no) pairs: what PEAK
    filed under a merged Odoo number — invoices, a person's links and field decisions
    — rides on the sheet row.
    """
    folded = {}
    for odoo_no, sheet_no in merged:
        group = folded.setdefault(str(sheet_no), [])
        if odoo_no and str(odoo_no) != str(sheet_no) and str(odoo_no) not in group:
            group.append(str(odoo_no))       # the sheet's own number is read once, as its own
    nos = [str(c["customer_no"]) for c in customers if c.get("customer_no")] + \
        [no for group in folded.values() for no in group]
    # Feedback Round 1 / WP1 (vault note 10 §3): the last APPLIED PEAK run, keyed by
    # customer_no — the same seam as the sheet's blocks, so the domain never learns a
    # second data path. An unapplied run is invisible here on purpose.
    from .pipelines import peak_writer
    peak_blocks = peak_writer.invoices_for_book(conn, served_nos=nos)

    rows = []
    from . import debt_imports
    supplements = debt_imports.supplements(conn)
    supplements_by_customer = {value["customer_uid"]: value for value in supplements.values()}
    statuses = debt_imports.observation_map(conn, ["sheet-" + str(customer.get("customer_no") or "")
                                                 for customer in customers])
    for customer in customers:
        volt_id = customer["volt_id"]
        record = _as_fixture({key: customer.get(key) for key in landing.CUSTOMER_COLUMNS})
        record["source_refs"] = customer.get("source_refs") or []
        record["data_source"] = customer.get("data_source")
        for block, empty in BLOCK_DEFAULTS.items():
            record[block] = blocks.get(volt_id, {}).get(block, empty)
        own = str(customer.get("customer_no") or "")
        record["peak"] = _fold_peak([peak_blocks.get(no) for no in [own] + folded.get(own, [])])
        order = orders.get(volt_id)
        if order:
            # `extra` first, so a normalised column always wins over its own copy.
            merged = dict(order.get("extra") or {})
            merged.update(_as_fixture({k: order.get(k) for k in landing.ORDER_COLUMNS}))
            merged["volt_id"] = volt_id
            merged["source_ref"] = order.get("source_ref") or []
            record["order"] = merged
        else:
            record["order"] = None
        customer_uid = "sheet-" + str(customer.get("customer_no") or "")
        supplement = supplements_by_customer.get(customer_uid)
        if supplement:
            block = "leasing" if supplement["product"] == "LEASE" else "cash"
            # Preserve any existing authoritative contractual book, never replace it.
            if not record.get(block):
                record[block] = supplement["record"]
                record["contract_supplement"] = supplement
        record["debt_status_observations"] = statuses.get(customer_uid) or []
        rows.append(record)
    # 2026-10-01: the Odoo lead each merged sheet customer is, recorded by the crm.lead
    # pull before its ODOO landing row retired (pipelines/odoo_links). The served row
    # is the sheet's, whose `crm_id` is the Freshworks deal id — this is the only
    # honest source for the case's Odoo deep link.
    from .pipelines import odoo_links
    odoo_lead_ids = odoo_links.active_for_customers(conn, nos)
    odoo_names = odoo_links.names_for_customers(conn, nos)
    odoo_social = odoo_links.social_for_customers(conn, nos)
    for record in rows:
        customer_no = str(record.get("customer_no") or "")
        lead_id = odoo_lead_ids.get(customer_no)
        if lead_id is not None:
            record["odoo_lead_id"] = lead_id
            record["odoo_lead_name"] = odoo_names.get(customer_no)
        social = odoo_social.get(customer_no)
        if social is not None:
            record.update(social)
    # Q7 / TASK-209: a person's active PEAK decision replaces the served field, with
    # its provenance beside it. Retiring the decision restores the Odoo value because
    # this overlay simply stops applying.
    from .pipelines import field_decisions
    decisions = field_decisions.load(conn, nos)
    for record in rows:
        own = str(record.get("customer_no") or "")
        mine = {}
        for no in folded.get(own, []):
            # the sheet names the person: an Odoo identity's volt_id decision stays its own
            mine.update({f: d for f, d in (decisions.get(no) or {}).items() if f != "volt_id"})
        mine.update(decisions.get(own) or {})           # the sheet number's own decision wins
        _apply_field_decisions(record, mine)
    return rows


def _apply_field_decisions(record, decisions):
    if not decisions:
        return
    sources, notes_th, notes_en = {}, {}, {}
    for field, decision in decisions.items():
        if decision.get("chosen_source") != "PEAK":
            continue
        peak = decision.get("peak_value")
        odoo = decision.get("odoo_value")
        when = str(decision.get("decided_at") or "")[:10]
        by = decision.get("decided_by")
        if field == "customer_name":
            record["name_th"] = peak
            record["display_name"] = peak
        elif field == "volt_id":
            record["volt_id"] = peak
        elif field == "product":
            record["product"] = peak
        elif field == "system_size_kwp":
            if not isinstance(record.get("order"), dict):
                continue                      # no order to carry the size on
            try:
                record["order"]["watt"] = str(int(_Decimal(str(peak)) * 1000))
            except (ArithmeticError, TypeError, ValueError):
                continue
        else:
            continue
        sources[field] = "PEAK"
        notes_th[field] = "PEAK ว่า %s · Odoo ว่า %s · เลือก PEAK โดย %s เมื่อ %s" % (peak, odoo, by, when)
        notes_en[field] = "PEAK says %s · Odoo says %s · chosen as PEAK by %s on %s" % (peak, odoo, by, when)
    if sources:
        record["field_sources"] = sources
        record["field_notes_th"] = notes_th
        record["field_notes_en"] = notes_en
