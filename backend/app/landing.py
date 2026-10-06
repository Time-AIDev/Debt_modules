"""The landing schema — writes, and reads with precedence applied by SQL.

This module knows tables. app/book_source.py knows what the rows mean. Keeping
those apart is what lets the precedence rule be stated once, in one ORDER BY,
instead of being re-implemented by every reader.
"""
import json

from sqlalchemy import text
from .crm_policy import won_only

BLOCKS = ("leasing", "tracking", "cash", "cash_invoices", "asset", "contact_log")

# The precedence chain, as one clause. DISTINCT ON takes the first row per volt_id.
# Arina, 2026-09-24: the New Order Master sheet IS the book, so a SHEET row wins over
# an ODOO row for the same volt_id (before that, ODOO won — the 2026-09-19 ruling).
# With no SHEET run landed this changes nothing: there is no SHEET row to prefer.
# Newer runs beat older ones within a source; the join (`_ok_runs_clause`) makes a
# FAILED run and a RETIRED row invisible to every rung.
_SOURCE_RANK = "case t.data_source when 'SHEET' then 0 else 1 end"
_PRECEDENCE = """
    order by t.volt_id, %s, t.import_run_id desc
""" % _SOURCE_RANK

CUSTOMER_COLUMNS = ("volt_id", "customer_no", "name_roman", "name_th", "epc", "product",
                    "sales_lead", "phone_masked", "phone_e164", "email_masked",
                    "line_id", "meta_id")

ORDER_COLUMNS = ("no", "crm_id", "order_type", "order_status", "loan_status",
                 "submit_date", "contract_signed_date", "epc_start_date",
                 "epc_end_date", "amount_total")


def start_run(conn, source_system, spreadsheet_id=None, meta=None):
    """`meta` carries pivots, flow_stages and warnings — properties of the import
    rather than of any row, which is why they hang on the run and not on a table."""
    return conn.execute(text(
        "insert into landing.import_run (source_system, spreadsheet_id, meta) "
        "values (:s, :g, cast(:m as jsonb)) returning id"),
        {"s": source_system, "g": spreadsheet_id,
         "m": json.dumps(meta or {}, ensure_ascii=False)}).scalar()


def finish_run(conn, run_id, status, row_counts=None, reconciled=None,
               truncated_blocks=None, note=None):
    conn.execute(text(
        "update landing.import_run set status=:st, finished_at=now(), "
        "row_counts=cast(:rc as jsonb), reconciled=:rec, "
        "truncated_blocks=cast(:tb as jsonb), note=:n where id=:i"),
        {"st": status, "rc": json.dumps(row_counts or {}), "rec": reconciled,
         "tb": json.dumps(truncated_blocks or []), "n": note, "i": run_id})


def stage_table(conn, name, like):
    """A session temp table shaped like `like`, empty, ready for COPY.

    Reused and truncated per call: a fresh CREATE would run DDL in the middle of
    every import, and `on commit drop` needs a transaction these functions should
    not assume (a caller may be in autocommit). Dropping is left to the session,
    where a temp table is already private.
    """
    cur = conn.connection.driver_connection.cursor()
    cur.execute("create temp table if not exists %s (like %s including defaults)" % (name, like))
    cur.execute("truncate %s" % name)
    return cur


def write_customers(conn, run_id, data_source, recs, batch=1000, on_progress=None):
    """Stream the rows in over COPY, then upsert them in one statement.

    The 2026-09-20 bench, 50k customer+order rows: 26.6s one row at a time, 16.9s
    through multi-row VALUES at batch 100, 5.2s through psycopg's executemany, and
    2.6s this way. COPY is the only one where the per-row work stays inside
    Postgres instead of crossing the driver one binding at a time.

    `batch` paces the progress callback only; nothing here is chunked.
    """
    if not recs:
        return 0
    columns = list(CUSTOMER_COLUMNS) + ["data_source", "source_refs", "import_run_id"]
    cur = stage_table(conn, "volt_stage_customer", "landing.customer")
    try:
        with cur.copy("copy volt_stage_customer (%s) from stdin" % ", ".join(columns)) as copy:
            for i, rec in enumerate(recs, start=1):
                copy.write_row(tuple([rec.get(c) for c in CUSTOMER_COLUMNS]
                                     + [data_source, json.dumps(rec.get("source_refs") or []), run_id]))
                if on_progress and i % batch == 0:
                    on_progress(i)
        cur.execute(
            "insert into landing.customer (%s) select %s from volt_stage_customer "
            "on conflict (volt_id, data_source) do update set %s"
            % (", ".join(columns), ", ".join(columns),
               ", ".join("%s = excluded.%s" % (c, c)
                         for c in list(CUSTOMER_COLUMNS) if c != "volt_id")
               + ", source_refs = excluded.source_refs, import_run_id = excluded.import_run_id"
               + ", retired_at = null"))
    finally:
        cur.close()
    if on_progress:
        on_progress(len(recs))
    return len(recs)


def write_customer(conn, run_id, data_source, rec):
    write_customers(conn, run_id, data_source, [rec], batch=1)


# Keys that live in their own column or are handled separately; everything else in
# the sheet's order block goes to `extra` rather than being silently dropped.
# `row_digest` is the crm.lead pull's change detector: its own column, never served.
ORDER_HANDLED = set(ORDER_COLUMNS) | {"volt_id", "source_ref", "row_digest"}


def write_orders(conn, run_id, data_source, items, batch=1000, on_progress=None):
    """`items` is (volt_id, rec) pairs. Same COPY path as write_customers; the natural
    key stays (volt_id, data_source) and `extra` is rebuilt per row exactly as the
    single-row path did. `batch` paces the progress callback only."""
    if not items:
        return 0
    columns = ["volt_id"] + list(ORDER_COLUMNS) + ["data_source", "source_ref", "extra", "import_run_id",
                                                   "row_digest"]
    cur = stage_table(conn, "volt_stage_order", 'landing."order"')
    try:
        with cur.copy("copy volt_stage_order (%s) from stdin" % ", ".join(
                '"%s"' % c if c in ORDER_COLUMNS + ("no",) else c for c in columns)) as copy:
            for i, (volt_id, rec) in enumerate(items, start=1):
                copy.write_row(tuple([volt_id]
                                     + [rec.get(c) for c in ORDER_COLUMNS]
                                     + [data_source, json.dumps(rec.get("source_ref") or []),
                                        json.dumps({k: v for k, v in rec.items()
                                                    if k not in ORDER_HANDLED},
                                                   ensure_ascii=False), run_id, rec.get("row_digest")]))
                if on_progress and i % batch == 0:
                    on_progress(i)
        quoted = ['"%s"' % c if c in ORDER_COLUMNS else c for c in columns]
        cur.execute(
            'insert into landing."order" (%s) select %s from volt_stage_order '
            "on conflict (volt_id, data_source) do update set %s, "
            "source_ref = excluded.source_ref, extra = excluded.extra, "
            "import_run_id = excluded.import_run_id, row_digest = excluded.row_digest, retired_at = null"
            % (", ".join(quoted), ", ".join(quoted),
               ", ".join('"%s" = excluded."%s"' % (c, c) for c in ORDER_COLUMNS)))
    finally:
        cur.close()
    if on_progress:
        on_progress(len(items))
    return len(items)


def write_order(conn, run_id, data_source, volt_id, rec):
    write_orders(conn, run_id, data_source, [(volt_id, rec)], batch=1)


def write_block(conn, run_id, data_source, volt_id, block, payload):
    if block not in BLOCKS:
        raise ValueError("unknown block %r" % block)
    conn.execute(text(
        "insert into landing.customer_block (volt_id, block, data_source, payload, import_run_id) "
        "values (:v, :b, :ds, cast(:p as jsonb), :run) "
        "on conflict (volt_id, block, data_source) do update set "
        "payload = excluded.payload, import_run_id = excluded.import_run_id, retired_at = null"),
        {"v": volt_id, "b": block, "ds": data_source,
         "p": json.dumps(payload, ensure_ascii=False), "run": run_id})


def write_unmapped(conn, run_id, rows):
    """One COPY for the unmapped vocabulary values of a run.

    `rows` is (volt_id, field, value) triples. Same stage-and-upsert shape as the
    customer write; `do nothing` because the primary key already makes two identical
    unmapped values on one lead a single fact.
    """
    if not rows:
        return 0
    cur = stage_table(conn, "volt_stage_unmapped", "landing.import_unmapped")
    try:
        with cur.copy("copy volt_stage_unmapped (import_run_id, volt_id, field, value) "
                      "from stdin") as copy:
            for volt_id, field, value in rows:
                copy.write_row((run_id, volt_id, field, value))
        cur.execute("insert into landing.import_unmapped (import_run_id, volt_id, field, value) "
                    "select import_run_id, volt_id, field, value from volt_stage_unmapped "
                    "on conflict (import_run_id, volt_id, field, value) do nothing")
    finally:
        cur.close()
    return len(rows)


def unmapped_for_volt(conn, run_ids, volt_id):
    """This lead's unmapped values, from the table rather than from a 700k-entry
    JSON blob stored beside every run."""
    if not run_ids:
        return []
    rows = conn.execute(text(
        "select field, value from landing.import_unmapped "
        "where import_run_id = any(:ids) and volt_id = :v "
        "order by field, value"), {"ids": list(run_ids), "v": volt_id}).mappings().all()
    return [{"volt_id": volt_id, "field": r["field"], "value": r["value"]} for r in rows]


def _ok_runs_clause():
    return ("join landing.import_run r on r.id = t.import_run_id and r.status = 'OK' "
            "and t.retired_at is null")


# A lead with no VOLT id lands under a placeholder key (`lead-<crm id>`; `phone-…` on
# rows landed before 2026-09-25) and is counted, never served. Stated once: the count
# and the served read must agree on the slice.
SHAPED_ONLY = "and t.volt_id not like 'phone-%%' and t.volt_id not like 'lead-%%'"
PLACEHOLDER_PREFIXES = ("phone-", "lead-")


def _served_filter(shaped_only):
    if not shaped_only:
        return ""
    if not won_only():
        return SHAPED_ONLY
    # Only successful, live Odoo snapshots prove CRM eligibility. A verified link
    # takes precedence over a shared VOLT stem, so another lead cannot admit a
    # customer whose own linked lead has left Won. Phone matches are insufficient.
    return SHAPED_ONLY + """
    and exists (
      select 1 from landing.customer w
      join landing.import_run wr on wr.id=w.import_run_id and wr.status='OK'
      join landing."order" wo on wo.volt_id=w.volt_id and wo.data_source='ODOO'
      join landing.import_run wor on wor.id=wo.import_run_id and wor.status='OK'
      where w.data_source='ODOO' and w.retired_at is null and wo.retired_at is null
      and (wo.extra->>'crm_status'='Won' or
           (not (wo.extra ? 'crm_status') and wo.order_status='Order - Done'))
      and ((t.data_source='ODOO' and w.volt_id=t.volt_id) or
           (t.data_source='SHEET' and case when exists (
              select 1 from records.identity_link l where l.source='ODOO_CRM_LEAD'
              and l.retired_at is null and l.customer_no=t.customer_no
           ) then wo.crm_id::text = (
              select l.odoo_lead_id::text from records.identity_link l
              where l.source='ODOO_CRM_LEAD' and l.retired_at is null
              and l.customer_no=t.customer_no order by l.uid desc limit 1
           ) else (
              upper(w.customer_no)=upper(t.customer_no) or
              split_part(upper(w.volt_id),'_',1)=split_part(upper(t.volt_id),'_',1)
           ) end))
    )"""


def resolved_customers(conn, shaped_only=False):
    """The precedence-resolved rows. `shaped_only` asks the DATABASE for the served
    slice instead of filtering 350k rows in Python afterwards (bench 2026-09-20: a
    book load shaped every landed row, served or not, and paid 17s for it)."""
    rows = conn.execute(text(
        "select distinct on (t.volt_id) t.* "
        "from landing.customer t %s where true %s %s"
        % (_ok_runs_clause(), _served_filter(shaped_only), _PRECEDENCE))).mappings().all()
    return [dict(r) for r in rows]


def count_customers(conn, shaped_only=False):
    """Resolved customers, counted in SQL. A header label must not build 33k fixture
    rows to print one number (that cost ~1.4 s on every workbook request)."""
    extra = " " + _served_filter(shaped_only)
    return conn.execute(text(
        "select count(distinct t.volt_id) from landing.customer t %s%s"
        % (_ok_runs_clause(), extra))).scalar() or 0


def resolved_orders(conn, volt_ids=None):
    """Every resolved order, or only those for `volt_ids` when the caller names the
    served slice — the order table is as long as the landing one, and a book that
    serves 25k of 350k rows has no use for the other 325k, rebuilt as Python dicts."""
    if volt_ids is not None and not len(volt_ids):
        return {}
    where, params = "", {}
    if volt_ids is not None:
        where, params["ids"] = "where t.volt_id = any(:ids)", list(volt_ids)
    rows = conn.execute(text(
        'select distinct on (t.volt_id) t.* from landing."order" t %s %s %s'
        % (_ok_runs_clause(), where, _PRECEDENCE)), params).mappings().all()
    return {r["volt_id"]: dict(r) for r in rows}


def blocks_for(conn, volt_ids):
    if not volt_ids:
        return {}
    rows = conn.execute(text(
        "select distinct on (t.volt_id, t.block) t.volt_id, t.block, t.payload "
        "from landing.customer_block t %s where t.volt_id = any(:ids) "
        "order by t.volt_id, t.block, %s, t.import_run_id desc"
        % (_ok_runs_clause(), _SOURCE_RANK)), {"ids": list(volt_ids)}).mappings().all()
    out = {}
    for row in rows:
        out.setdefault(row["volt_id"], {})[row["block"]] = row["payload"]
    return out


def last_run(conn, source_system):
    row = conn.execute(text(
        "select * from landing.import_run where source_system=:s and status='OK' "
        "order by id desc limit 1"), {"s": source_system}).mappings().first()
    return dict(row) if row else None


def last_lead_run(conn):
    """The last crm.lead pull (or upload of its shape), not the sale.order sync.

    Both write source ODOO, and the sync runs at every boot — so `last_run(conn,
    "ODOO")` usually answers with the five-order snapshot and every 'as of' date,
    freshness check and receipt on the crm.lead screens would name the wrong run.
    Only the pipeline writer stamps meta.door; the sync writes no meta at all.
    """
    row = conn.execute(text(
        "select * from landing.import_run where source_system='ODOO' and status='OK' "
        "and meta ? 'door' order by id desc limit 1")).mappings().first()
    return dict(row) if row else None



def retire_unseen(conn, data_source, seen_volt_ids):
    """Retire every live `data_source` row whose volt_id this complete pull or sheet
    install did not carry — customer, order and block rows alike. Nothing is deleted:
    a retired row is invisible to every book read, and landing it again brings it back.
    Returns the number of customers retired.

    Refuses an empty `seen` set: a pull that read nothing is a failed pull, and
    retiring on it would empty the book."""
    seen = {v for v in seen_volt_ids if v}
    if not seen:
        raise ValueError("an empty %s run never retires the book" % data_source)
    cur = conn.connection.driver_connection.cursor()
    try:
        cur.execute("create temp table if not exists volt_seen (volt_id text primary key)")
        cur.execute("truncate volt_seen")
        with cur.copy("copy volt_seen (volt_id) from stdin") as copy:
            for volt_id in seen:
                copy.write_row((volt_id,))
        retired = 0
        for table in ("landing.customer", 'landing."order"', "landing.customer_block"):
            cur.execute(
                "update %s t set retired_at = now() where t.data_source = %%s "
                "and t.retired_at is null "
                "and not exists (select 1 from volt_seen s where s.volt_id = t.volt_id)" % table,
                (data_source,))
            if table == "landing.customer":
                retired = cur.rowcount
    finally:
        cur.close()
    return retired


def sweep_running(conn, source_system, older_than_minutes=30):
    """Mark `source_system` runs still RUNNING after `older_than_minutes` as FAILED.
    A process that died mid-run leaves its row RUNNING for ever, and nothing else
    finishes it. Call it while holding that source's run lock: the lock covers the
    LANDING only, not the fetch before it, so a run still fetching after
    `older_than_minutes` is swept too (its own landing then finishes it OK — the
    crm.lead pull's 8 s page timeout keeps a whole fetch far below 30 minutes).
    Returns the swept run ids."""
    rows = conn.execute(text(
        "update landing.import_run set status = 'FAILED', finished_at = now(), "
        "note = 'pipeline_failed: the process stopped before this run finished' "
        "where source_system = :s and status = 'RUNNING' "
        "and started_at < now() - make_interval(mins => :m) returning id"),
        {"s": source_system, "m": int(older_than_minutes)}).scalars().all()
    return list(rows)

# A run row as the screens read it: the big meta lists — the ledger, the proposals,
# the old unmapped lists, each naming OTHER leads' keys — dropped IN THE DATABASE, and
# their sizes carried as totals. One select list for every slim reader.
_SLIM_RUN = (
    "id, source_system, spreadsheet_id, status, started_at, finished_at, "
    "row_counts, truncated_blocks, note, reconciled, "
    "(meta - 'unmapped' - 'unmapped_by_volt' - 'overwrite_ledger' - 'proposals') "
    "|| jsonb_build_object("
    "  'unmapped_total', greatest("
    "      case when (meta->>'unmapped_total') ~ '^[0-9]+$' then (meta->>'unmapped_total')::int else 0 end,"
    "      coalesce(case when jsonb_typeof(meta->'unmapped') = 'array' "
    "                    then jsonb_array_length(meta->'unmapped') end, 0)),"
    "  'ledger_total', greatest("
    "      case when (meta->>'ledger_total') ~ '^[0-9]+$' then (meta->>'ledger_total')::int else 0 end,"
    "      coalesce(case when jsonb_typeof(meta->'overwrite_ledger') = 'array' "
    "                    then jsonb_array_length(meta->'overwrite_ledger') end, 0)),"
    "  'proposals_total', coalesce(case when jsonb_typeof(meta->'proposals') = 'array' "
    "                                   then jsonb_array_length(meta->'proposals') end, 0)"
    ") as meta")


def lead_run_slim(conn, status="OK"):
    """`last_lead_run`, slim (_SLIM_RUN) — or the newest run of another status. A run
    refused because another pull held the landing lock is not the latest failure:
    the pull that held it is the news (it stays in `lead_runs`).

    Older runs kept the whole unmapped list on meta: one 2026-09-20 pull left 3.5 MB
    of it, and every Data sources mount decoded all of it (274 ms) and shipped it
    (1.8 MB) for six counters. The paginated `/landing-runs/{id}` endpoint remains
    the way to read the lists; `rejected` (counts by rule) stays on the slim row.
    """
    row = conn.execute(text(
        "select %s from landing.import_run where source_system='ODOO' and status=:st "
        "and meta ? 'door' and coalesce(note, '') not like 'crm_lead_run_in_progress:%%' "
        "order by id desc limit 1" % _SLIM_RUN), {"st": status}).mappings().first()
    return dict(row) if row else None


def lead_runs(conn, limit=20):
    """The last `limit` crm.lead runs, any status (RUNNING, OK, FAILED), newest
    first — slim, as lead_run_slim."""
    rows = conn.execute(text(
        "select %s from landing.import_run where source_system='ODOO' and meta ? 'door' "
        "order by id desc limit :n" % _SLIM_RUN), {"n": int(limit)}).mappings().all()
    return [serialize_run(dict(r)) for r in rows]


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def serialize_run(row):
    """An import_run row as JSON-safe dict. Datetimes to ISO, jsonb passthrough."""
    if row is None:
        return None
    out = dict(row)
    for key in ("started_at", "finished_at"):
        out[key] = _iso(out.get(key))
    out["row_counts"] = out.get("row_counts") or {}
    out["meta"] = out.get("meta") or {}
    out["truncated_blocks"] = out.get("truncated_blocks") or []
    return out


def get_run(conn, run_id):
    """One import_run by id, any status. None when missing — never invented."""
    row = conn.execute(text(
        "select * from landing.import_run where id=:i"), {"i": run_id}).mappings().first()
    return serialize_run(dict(row)) if row else None


def rows_for_volt(conn, volt_id):
    """Every landing row for one volt_id, plus which rung wins and why.

    The point is the question an officer asks after an Odoo import: "did MY
    row go in, and which value does the book serve now?" Both SHEET and ODOO
    rows are returned side by side; `winner` names the data_source the
    precedence rule picks among OK runs, and `ledger` carries the overwrite
    entries for this volt_id from the latest OK ODOO run.
    """
    # A placeholder key (lead-<crm id>, and the legacy phone-<digits>, which IS a phone
    # number) answers only while its row is live: a retired one is nobody's lead.
    live_only = "and t.retired_at is null" if volt_id.startswith(PLACEHOLDER_PREFIXES) else ""
    customers = conn.execute(text(
        "select t.*, r.status as run_status from landing.customer t "
        "join landing.import_run r on r.id = t.import_run_id "
        "where t.volt_id=:v %s order by %s, t.import_run_id desc" % (live_only, _SOURCE_RANK)),
        {"v": volt_id}).mappings().all()
    orders = conn.execute(text(
        'select t.*, r.status as run_status from landing."order" t '
        "join landing.import_run r on r.id = t.import_run_id "
        "where t.volt_id=:v %s order by %s, t.import_run_id desc" % (live_only, _SOURCE_RANK)),
        {"v": volt_id}).mappings().all()
    run_ids = {r["import_run_id"] for r in list(customers) + list(orders)}
    runs = []
    if run_ids:
        # Slim: a run's full meta names every other lead it touched.
        runs = conn.execute(text(
            "select %s from landing.import_run where id = any(:ids) order by id" % _SLIM_RUN),
            {"ids": list(run_ids)}).mappings().all()
    runs = [serialize_run(dict(r)) for r in runs]

    winner = None
    ok_customers = [dict(r) for r in customers
                    if r.get("run_status") == "OK" and not r.get("retired_at")]
    if ok_customers:
        winner = ok_customers[0].get("data_source")

    ledger = []
    if conn.execute(text(
            "select 1 from landing.import_run where source_system='ODOO' and status='OK' limit 1")).first():
        latest = conn.execute(text(
            "select meta from landing.import_run where source_system='ODOO' and status='OK' "
            "order by id desc limit 1")).scalar()
        if isinstance(latest, dict):
            for entry in latest.get("overwrite_ledger") or []:
                if isinstance(entry, dict) and entry.get("volt_id") == volt_id:
                    ledger.append(entry)
    unmapped = unmapped_for_volt(conn, run_ids, volt_id)

    def _clean(row):
        # The full number is answered only by the case's audited phone:reveal route
        # (customer_contact.py); a provenance read serves the mask beside it — and
        # never the pull's row_digest, a hash of the whole lead the number is in.
        d = dict(row)
        for key in ("phone_e164", "row_digest"):
            d.pop(key, None)
        if isinstance(d.get("extra"), dict):
            d["extra"] = {k: v for k, v in d["extra"].items() if k not in ("phone_e164", "row_digest")}
        return d

    return {"volt_id": volt_id,
            "customers": [_clean(r) for r in customers],
            "orders": [_clean(r) for r in orders],
            "runs": runs,
            "winner": winner,
            "ledger": ledger,
            "unmapped": unmapped}


def list_landing_customers(conn, data_source=None, q=None, limit=50, offset=0):
    """Paginated landing.customer rows from OK runs, for the registry filter.

    data_source is SHEET, ODOO or None (both). q matches volt_id, customer_no,
    name_th or sales_lead case-insensitively. Newest run first so a repeated
    import surfaces its own rows, not a stale run's.
    """
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    clauses = ["r.status='OK'", "t.retired_at is null"]
    params = {"lim": limit, "off": offset}
    if data_source in ("SHEET", "ODOO"):
        clauses.append("t.data_source=:ds")
        params["ds"] = data_source
    if q:
        clauses.append("(t.volt_id ilike :q or t.customer_no ilike :q "
                       "or t.name_th ilike :q or t.sales_lead ilike :q)")
        params["q"] = "%%%s%%" % q.strip()
    where = "where " + " and ".join(clauses)
    total = conn.execute(text(
        "select count(*) from landing.customer t "
        "join landing.import_run r on r.id=t.import_run_id %s" % where),
        {k: v for k, v in params.items() if k not in ("lim", "off")}).scalar() or 0
    rows = conn.execute(text(
        "select t.volt_id, t.data_source, t.customer_no, t.name_th, t.name_roman, "
        "t.epc, t.product, t.sales_lead, t.phone_masked, t.email_masked, "
        "t.import_run_id from landing.customer t "
        "join landing.import_run r on r.id=t.import_run_id %s "
        "order by t.import_run_id desc, t.volt_id limit :lim offset :off" % where),
        params).mappings().all()
    return {"rows": [dict(r) for r in rows], "total": total,
            "limit": limit, "offset": offset}
