"""One PEAK import_run: the invoices with their verdicts, the receipt on the run,
the apply step, and the one read the book makes.

A run is STAGED when written and APPLIED when a person says so (design F1). Applied
is a mark on import_run.meta, never a status of its own: status stays the landing
schema's RUNNING/OK/FAILED, and book_source keeps reading only OK runs.

The 13-digit id is dropped here, before anything is written (F5).
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from .. import landing
from . import field_decisions, peak_candidates, peak_conflicts
from .peak_match import normalise_code
from .peak_report import report_range

SOURCE = "PEAK"
CENT = Decimal("0.01")
# One PEAK run at a time, across instances: a write holds this advisory lock for its
# session, an apply for its transaction (fix-all P9). Two reports applied at once is
# a race the book cannot resolve (sync audit, 2026-09-20).
PEAK_LOCK_KEY = 0x5045414B  # "PEAK"
RUN_IN_PROGRESS_TH = "มีรายงาน PEAK กำลังนำเข้าอยู่ — รอให้รอบปัจจุบันจบก่อนแล้วลองใหม่"
STORED = ("doc_no", "doc_kind", "issued_on", "due_on", "reference", "system_reference", "contact_code",
          "customer_name", "status", "product_group", "amount_total", "amount_due", "amount_awaiting", "note")

# The insert's column order, named once. The batch builder and the casts below read
# it, so adding a column to the table means adding it here and nowhere else.
_PEAK_COLUMNS = ("import_run_id", "doc_no", "doc_kind", "issued_on", "due_on", "reference",
                 "system_reference", "contact_code", "customer_name", "status", "cycle_n",
                 "cycle_of", "product_group", "amount_total", "amount_due", "amount_awaiting",
                 "paid_on", "paid_channel", "paid_amount", "receipt_no", "note", "lines",
                 "verdict", "rule", "customer_no", "candidates", "ladder_verdict",
                 "ladder_customer_no", "ladder_rule", "conflicts")


def _write_rows(conn, rows, batch=500, on_written=None):
    """Stream the invoices in over COPY, then upsert them in one statement.

    Same measured reason as landing.write_customers: 500 rows x 29 columns is 14,500
    bindings if they travel as VALUES, and none if they travel over COPY. `on_written`
    is called with the running count as rows stream, so the pipeline's progress bar
    keeps reporting real landed invoices.
    """
    if not rows:
        return 0
    columns = ", ".join(_PEAK_COLUMNS)
    cur = landing.stage_table(conn, "volt_stage_peak", "landing.peak_invoice")
    try:
        with cur.copy("copy volt_stage_peak (%s) from stdin" % columns) as copy:
            for i, row in enumerate(rows, start=1):
                copy.write_row(tuple(row.get(column) for column in _PEAK_COLUMNS))
                if on_written and i % batch == 0:
                    on_written(i)
        cur.execute(
            "insert into landing.peak_invoice (%s) select %s from volt_stage_peak "
            "on conflict (import_run_id, doc_no) do nothing" % (columns, columns))
    finally:
        cur.close()
    if on_written:
        on_written(len(rows))
    return len(rows)


class WriterRefused(Exception):
    def __init__(self, code, detail, detail_th):
        super().__init__(detail)
        self.code, self.detail, self.detail_th = code, detail, detail_th


def _hold_the_lock(conn):
    """Fix-all P9 (M6): an apply holds the PEAK lock until its transaction ends, so two
    applies (or an apply beside a write) never both check against the same run."""
    if not conn.execute(text("select pg_try_advisory_xact_lock(:k)"), {"k": PEAK_LOCK_KEY}).scalar():
        raise WriterRefused("peak_run_in_progress", "another PEAK report run is in progress", RUN_IN_PROGRESS_TH)


def _iso(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10] if isinstance(value, date) and not isinstance(value, datetime) else value.isoformat()
    return value


def write(conn, parsed, verdicts, door="upload", filename=None, on_progress=None, ladder=None,
          run_id=None, fingerprint=None, identities=None):
    """`verdicts` is the ladder WITH the link register (what the run reports and the
    lists show); `ladder` is the same ladder WITHOUT it, one per invoice (final review
    C1), stored as ladder_verdict / ladder_customer_no / ladder_rule so the book's
    read can let the register decide at read time. Only those three fields of it are
    stored — never its candidates, and never anything of the invoice's 13-digit id.
    A caller that passes no `ladder` lands NULLs, which the read treats as a legacy
    row.

    `run_id` continues a RUNNING run row opened before the parse (sync audit,
    2026-09-20) so a failed run leaves a durable FAILED row instead of dying with
    the process; `fingerprint` names the exact bytes, so the same file cannot be
    staged twice."""
    covers_from, covers_to = report_range(filename)
    meta = {"report_as_of": parsed.get("report_as_of"),
            "exported_at": parsed.get("exported_at"),
            "covers_from": covers_from, "covers_to": covers_to,
            "door": door, "filename": filename, "fingerprint": fingerprint,
            "schema": parsed.get("schema")}
    if run_id:
        run = int(run_id)
        conn.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                     {"m": json.dumps(meta, ensure_ascii=False), "i": run})
    else:
        run = landing.start_run(conn, SOURCE, meta=meta)
    counts = {"EXACT": 0, "CANDIDATE": 0, "UNMATCHED": 0}
    ladder = list(ladder) if ladder is not None else [None] * len(parsed["invoices"])
    if len(ladder) != len(parsed["invoices"]):
        # zip() would silently drop the invoices past the shorter list
        raise ValueError("the ladder carries %d verdicts for %d invoices" % (len(ladder), len(parsed["invoices"])))
    rows = []
    for inv, verdict, own in zip(parsed["invoices"], verdicts, ladder):
        params = {k: inv.get(k) for k in STORED}
        pay = inv.get("payment") or {}
        cycle = inv.get("cycle") or {}
        own = own or {}
        params.update(import_run_id=run, cycle_n=cycle.get("n"), cycle_of=cycle.get("of"),
                      paid_on=pay.get("on"), paid_channel=pay.get("channel"), paid_amount=pay.get("amount"),
                      receipt_no=pay.get("receipt_no"), lines=json.dumps(inv.get("lines") or [], ensure_ascii=False),
                      verdict=verdict["verdict"], rule=verdict.get("rule"), customer_no=verdict.get("customer_no"),
                      candidates=json.dumps(verdict.get("candidates") or [], ensure_ascii=False),
                      ladder_verdict=own.get("verdict"), ladder_customer_no=own.get("customer_no"),
                      ladder_rule=own.get("rule"))
        # D02 / TASK-208: a matched invoice carries the fields where PEAK and the
        # Odoo record disagree — only the differing ones; nothing to review, no row.
        conflicts = None
        if identities and verdict["verdict"] == "EXACT":
            identity = identities.get(str(verdict.get("customer_no") or ""))
            if identity:
                conflicts = [c for c in peak_conflicts.compare(inv, identity) if not c["same"]] or None
        params["conflicts"] = json.dumps(conflicts, ensure_ascii=False) if conflicts else None
        rows.append(params)
        counts[verdict["verdict"]] += 1
    _write_rows(conn, rows,
                on_written=(lambda written: on_progress(landed=written)) if on_progress else None)
    rejected = len(parsed.get("rejected") or [])
    # The rejected rows are a fact of the run, not a counter: the rows endpoint's
    # verdict=REJECTED filter was always empty because nothing wrote them (sync
    # audit, 2026-09-20). They land in the unmapped table — the same place an
    # unmapped vocabulary value goes for crm.lead, keyed to the sheet row.
    landing.write_unmapped(conn, run, [
        ("row-%s" % (r.get("row") or "?"), str(r.get("code") or "rejected"),
         str(r.get("value") if r.get("value") is not None else "—"))
        for r in (parsed.get("rejected") or [])])
    conn.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                 {"m": json.dumps({"rejected": parsed.get("rejected") or [], "matched": counts["EXACT"],
                                   "candidates": counts["CANDIDATE"], "unmatched": counts["UNMATCHED"]},
                                  ensure_ascii=False), "i": run})
    landing.finish_run(conn, run, "OK", row_counts={"read": len(parsed.get("lines") or []),
                                                    "landed": len(parsed["invoices"]), "rejected": rejected})
    return {"run_id": run, "invoices": len(parsed["invoices"]), "matched": counts["EXACT"],
            "candidates": counts["CANDIDATE"], "unmatched": counts["UNMATCHED"], "rejected": rejected,
            "report_as_of": parsed.get("report_as_of"), "door": door}


def last_run(conn, applied=None, source=None):
    """The newest OK PEAK run. `applied=True` means the run applied LAST — ordered by
    the moment apply_run stamped it (meta.applied.at), then id — never the run
    uploaded last: applying an earlier upload over a later one (allow_older) must make
    the earlier one the served run (final review I2).

    Feedback round 2 (TASK-203): `source` names which door — the receipt run's own
    last_applied is independent of the invoice run's (a receipt run newer than the
    applied invoice run is the normal case)."""
    clause, order = "", "id desc"
    if applied is True:
        clause = "and meta ? 'applied'"
        order = "cast(meta->'applied'->>'at' as timestamptz) desc nulls last, id desc"
    elif applied is False:
        clause = "and not (meta ? 'applied')"
    row = conn.execute(text(
        "select * from landing.import_run where source_system = :s and status = 'OK' %s "
        "order by %s limit 1" % (clause, order)), {"s": source or SOURCE}).mappings().first()
    return landing.serialize_run(row) if row else None


def last_failed(conn, source=None):
    """The newest FAILED PEAK run, or None.

    A failed run now leaves a durable row (sync audit, 2026-09-20); the screen has
    to be able to show it, or the last OK receipt keeps looking like the whole
    story and the person waits for a run that already died."""
    row = conn.execute(text(
        "select * from landing.import_run where source_system = :s and status = 'FAILED' "
        "order by id desc limit 1"), {"s": source or SOURCE}).mappings().first()
    return landing.serialize_run(row) if row else None


def check_range(mine, applied, allow_older, receipts=False):
    """Applying a report that reaches back less far deletes invoice history nobody
    asked to lose (journey.py:1094 clears every PEAK row before reseeding). For the
    receipt report (`receipts`), the overlay reads the applied run alone, so the invoices
    paid in between would read unpaid again; the way out is a new export from the same
    start date, not the older-report tick (fix-all P4, audit)."""
    if allow_older or not applied:
        return
    theirs, ours = applied.get("covers_from"), mine.get("covers_from")
    if not theirs or not ours or ours <= theirs:
        return
    if receipts:
        raise WriterRefused(
            "receipt_range_narrower",
            "this receipt report starts %s; the one in use reaches back to %s, so the invoices paid in "
            "between would read unpaid again — export the receipt report again from %s" % (ours, theirs, theirs),
            "รายงานใบเสร็จนี้เริ่ม %s แต่รายงานที่ใช้อยู่ย้อนถึง %s — ใบแจ้งหนี้ที่ชำระในช่วงนั้นจะกลับเป็นค้างชำระ "
            "ให้ส่งออกรายงานใบเสร็จใหม่ตั้งแต่วันที่ %s" % (ours, theirs, theirs))
    raise WriterRefused(
        "report_range_narrower",
        "this report starts %s; the applied one reaches back to %s, so applying it "
        "drops the invoices in between" % (ours, theirs),
        "รายงานนี้เริ่ม %s แต่รายงานที่ใช้อยู่ย้อนถึง %s — ใช้รายงานนี้จะทำให้ใบแจ้งหนี้ช่วงก่อนหน้าหายไป "
        "ติ๊ก 'ใช้รายงานเก่ากว่า' หากตั้งใจ" % (ours, theirs))


def apply_run(conn, run_id, by, allow_older=False, force=False):
    _hold_the_lock(conn)
    run = landing.get_run(conn, run_id)
    if run is None or run.get("source_system") != SOURCE:
        raise WriterRefused("not_found", "no PEAK run %s" % run_id, "ไม่พบรอบนำเข้า PEAK นี้")
    stamped = (run.get("meta") or {}).get("applied")
    if stamped:
        # Final review I2: re-stamping an applied run would silently re-order what the
        # book serves. Refused by name instead; upload the report again to re-apply it.
        raise WriterRefused("already_applied",
                            "PEAK run %s was already applied at %s by %s" % (run_id, stamped.get("at"), stamped.get("by")),
                            "รอบนำเข้านี้ถูกใช้ไปแล้ว — หากต้องการใช้อีกครั้ง ให้นำเข้ารายงานนี้ใหม่")
    current = last_run(conn, applied=True)
    mine_meta, theirs_meta = run.get("meta") or {}, (current or {}).get("meta") or {}
    if current and not force and mine_meta.get("report_as_of"):
        # The same report uploaded twice makes two independent runs; per-run
        # `already_applied` never stopped the second from being applied, silently
        # re-stamping the book (sync audit, 2026-09-20). Same date AND same range is
        # the same report; a Manager's explicit force is the only way through.
        same = all((mine_meta.get(k) or None) == (theirs_meta.get(k) or None)
                   for k in ("report_as_of", "covers_from", "covers_to"))
        if same:
            raise WriterRefused(
                "report_already_applied",
                "the same report (as of %s) is already applied as run %s" % (mine_meta.get("report_as_of"),
                                                                             (current or {}).get("id")),
                "รายงานชุดเดียวกันนี้ (ณ %s) ถูกใช้อยู่แล้วในรอบ %s — ใช้เฉพาะเมื่อตั้งใจประมวลผลซ้ำ"
                % (mine_meta.get("report_as_of"), (current or {}).get("id")))
    if current and not allow_older:
        newer = (current.get("meta") or {}).get("report_as_of")
        mine = (run.get("meta") or {}).get("report_as_of")
        # An undated report can never be SHOWN newer than a dated (or another
        # undated) applied one — refuse rather than let the short-circuit on
        # `mine` silently let it through. A DATED report replacing an UNDATED
        # applied one is fine: `newer` is falsy so the next check never fires.
        if not mine:
            newer_or_unknown = newer or "unknown"
            raise WriterRefused("report_as_of_unknown",
                                "the report's date is unknown, so it cannot be shown to be newer than "
                                "the applied report of %s" % newer_or_unknown,
                                "ไม่ทราบวันที่ของรายงานนี้ จึงบอกไม่ได้ว่าใหม่กว่ารายงานที่ใช้อยู่ — "
                                "ติ๊ก 'ใช้รายงานเก่ากว่า' หากตั้งใจ")
        if newer and mine < newer:
            raise WriterRefused("report_older_than_applied",
                                "report as of %s is older than the applied %s" % (mine, newer),
                                "รายงานนี้ (ณ %s) เก่ากว่ารายงานที่ใช้อยู่ (ณ %s) — ติ๊ก 'ใช้รายงานเก่ากว่า' หากตั้งใจ" % (mine, newer))
        check_range(run.get("meta") or {}, current.get("meta") or {}, allow_older)
    conn.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                 {"m": json.dumps({"applied": {"by": by, "at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"}}),
                  "i": int(run_id)})
    # Q7 / TASK-208: every conflict this run carries and a person has not decided
    # takes PEAK as the default, with the applier's name on the provenance.
    defaulted = field_decisions.default_all(conn, run_id, by)
    run = landing.serialize_run(landing.get_run(conn, run_id))
    run["defaulted_fields"] = defaulted
    return run


AMOUNTS = ("amount_total", "amount_due", "amount_awaiting", "paid_amount")


def _row_value(k, v):
    if k in AMOUNTS:
        return str(v) if v is not None else None
    return _iso(v)


def rows(conn, run_id, verdict=None, limit=100, offset=0):
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    if verdict == "REJECTED":
        # Rejected lines never reach landing.peak_invoice (no invoice exists for a
        # status the report's own vocabulary does not carry); they are written to
        # landing.import_unmapped so the screen can show WHAT was skipped and why.
        total = conn.execute(text(
            "select count(*) from landing.import_unmapped where import_run_id = :r"),
            {"r": int(run_id)}).scalar() or 0
        found = conn.execute(text(
            "select volt_id, field, value from landing.import_unmapped "
            "where import_run_id = :r order by volt_id limit :lim offset :off"),
            {"r": int(run_id), "lim": limit, "off": offset}).mappings().all()
        return {"rows": [{"verdict": "REJECTED", "row": dict(r)["volt_id"],
                          "code": dict(r)["field"], "value": dict(r)["value"]} for r in found],
                "total": total, "limit": limit, "offset": offset}
    clause = "and verdict = :v" if verdict else ""
    params = {"r": int(run_id), "lim": limit, "off": offset}
    if verdict:
        params["v"] = verdict
    total = conn.execute(text("select count(*) from landing.peak_invoice where import_run_id = :r %s" % clause),
                         {k: v for k, v in params.items() if k in ("r", "v")}).scalar() or 0
    # The register is authoritative at read time (final review C1), so a row whose
    # code a person has since linked must say so: the reconciliation list uses
    # `linked_no` to stop showing a resolved row as still waiting for a decision.
    # Same normaliser and priority as invoices_for_book: the contact code's link wins
    # over the reference's, and DISTINCT ON keeps one row per invoice.
    norm = "upper(regexp_replace(coalesce(%s, ''), '[[:space:]]+', '', 'g'))"
    found = conn.execute(text(
        "select * from ("
        "select distinct on (p.doc_no) p.*, l.customer_no as linked_no "
        "from landing.peak_invoice p "
        "left join records.identity_link l on l.retired_at is null and l.source = 'PEAK_LINK' and "
        "(l.contact_code = %s or l.contact_code = %s) "
        "where p.import_run_id = :r %s "
        "order by p.doc_no, case when l.contact_code = %s then 0 when l.uid is not null then 1 else 2 end"
        ") q order by q.due_on desc nulls last, q.doc_no limit :lim offset :off"
        % (norm % "p.contact_code", norm % "p.reference", clause, norm % "p.contact_code")),
        params).mappings().all()
    # amount_total/amount_due/amount_awaiting/paid_amount come back as Decimal from
    # psycopg; a FastAPI route (Task 8) returns this dict straight through, and a
    # Decimal does not survive JSON encoding the way a plain string does.
    return {"rows": [{k: _row_value(k, v) for k, v in dict(r).items()} for r in found],
            "total": total, "limit": limit, "offset": offset}


def odoo_phone_rows(conn):
    found = conn.execute(text(
        "select t.volt_id, t.phone_e164 from landing.customer t "
        "join landing.import_run r on r.id = t.import_run_id and r.status = 'OK' "
        "where t.data_source = 'ODOO' and t.retired_at is null "
        "and t.phone_e164 is not null and t.phone_e164 <> ''")).mappings().all()
    return [dict(r) for r in found]


def _payment(r, receipt_no):
    return {"on": _iso(r["paid_on"]), "channel": r["paid_channel"],
            "amount": str(r["paid_amount"]) if r["paid_amount"] is not None else None,
            "receipt_no": receipt_no}


# The register's normaliser: peak_match.normalise_code (all whitespace, upper case) in SQL.
_NORM = "upper(regexp_replace(coalesce(%s, ''), '[[:space:]]+', '', 'g'))"


def _linked_rows(conn, run_id, columns, where="", params=None):
    """One row per invoice of `run_id` (narrowed by `where`), with its active link as
    `linked_no`. An invoice's contact_code and reference can each carry their own active
    link to a DIFFERENT customer; DISTINCT ON keeps one row per invoice, and the ORDER BY
    picks the contact_code's link over the reference's (and either over no link) — the
    same priority rung 0 uses in peak_match.match_one (contact_code checked before
    reference). The normaliser matches peak_match.normalise_code (all whitespace
    stripped, not just spaces), or a link confirmed against a tab-bearing code never
    joins."""
    return conn.execute(text(
        "select distinct on (p.doc_no) %s, l.customer_no as linked_no "
        "from landing.peak_invoice p "
        "left join records.identity_link l on l.retired_at is null and l.source = 'PEAK_LINK' and "
        "(l.contact_code = %s or l.contact_code = %s) "
        "where p.import_run_id = :r %s "
        "order by p.doc_no, case when l.contact_code = %s then 0 when l.uid is not null then 1 else 2 end"
        % (", ".join("p.%s" % c for c in columns), _NORM % "p.contact_code", _NORM % "p.reference",
           where, _NORM % "p.contact_code")),
        dict(params or {}, r=int(run_id))).mappings().all()


def _served(row, rule=None):
    r = dict(row)
    payment = _payment(r, r["receipt_no"]) if r["paid_on"] or r["receipt_no"] else None
    return {"doc_no": r["doc_no"], "doc_kind": r["doc_kind"], "issued_on": _iso(r["issued_on"]),
            "due_on": _iso(r["due_on"]), "status": r["status"],
            "cycle": {"n": r["cycle_n"], "of": r["cycle_of"]} if r["cycle_n"] else None,
            "product_group": r["product_group"], "amount_total": str(r["amount_total"]) if r["amount_total"] is not None else None,
            "amount_due": str(r["amount_due"]) if r["amount_due"] is not None else None,
            "amount_awaiting": str(r["amount_awaiting"] or "0.00"),
            # `payments` is every payment the book serves for this invoice (fix-all P2):
            # the report's own one here, the receipt run's receipts once they overlay it.
            "payment": payment, "payments": [payment] if payment else [],
            "contact_code": r["contact_code"], "rule": rule or r["rule"]}


def _serves(r):
    """Which customer one row of the applied run is served to, and by which rule —
    or (None, None). The link register is authoritative at READ time (final review
    C1): an active link wins over anything stored; with no active link, the ladder's
    own verdict WITHOUT links decides; a legacy row (no ladder columns) is served by
    its stored verdict only when that was EXACT by a rule other than LINK, since a
    stored LINK verdict with no active link behind it is a link since retired."""
    if r["linked_no"]:
        return r["linked_no"], "LINK"
    if r["ladder_verdict"] is not None:
        if r["ladder_verdict"] == "EXACT" and r["ladder_customer_no"]:
            return r["ladder_customer_no"], r["ladder_rule"]
        return None, None
    if r["verdict"] == "EXACT" and r["rule"] != "LINK" and r["customer_no"]:
        return r["customer_no"], r["rule"]
    return None, None


# The columns `_serves` and `_served` actually read. `p.*` used to travel: lines,
# candidates and a name a book row never shows, multiplied by every invoice of the
# applied run. The filter below proves which rows can be served before they are read.
_BOOK_COLUMNS = ("doc_no", "doc_kind", "issued_on", "due_on", "status", "cycle_n", "cycle_of",
                 "product_group", "amount_total", "amount_due", "amount_awaiting",
                 "paid_on", "paid_channel", "paid_amount", "receipt_no",
                 "contact_code", "rule", "verdict", "customer_no",
                 "ladder_verdict", "ladder_customer_no", "ladder_rule")


def invoices_for_book(conn, served_nos=None):
    """Every row of the last APPLIED run, read once with its active link (if any), and
    served to the customer `_serves` names — rung 0 applied at read time, for EXACT
    rows too, so confirming or retiring a link moves an invoice without a re-run.

    `served_nos` is the exact set of customer numbers the book will look up. Passing
    it lets the DATABASE drop rows that could never be attached to a served customer;
    omitting it (tests, callers that need the whole run) keeps the old read.
    """
    run = last_run(conn, applied=True)
    if run is None:
        # Q6 (TASK-204): with no applied invoice report there are no invoices to
        # serve, but an applied receipt run can still carry money — receipt_only rows.
        return _overlay_receipts(conn, {}, None)
    as_of = (run.get("meta") or {}).get("report_as_of")
    out = {}
    params, restrict = {}, ""
    if served_nos is not None:
        nos = [str(no) for no in served_nos if no]
        if not nos:
            return {}
        restrict = ("and (p.customer_no = any(:nos) or p.ladder_customer_no = any(:nos) "
                    "or l.customer_no = any(:nos))")
        params["nos"] = nos
    active = "and p.status not in ('DRAFT','CANCELLED') " + restrict
    for r in _linked_rows(conn, run["id"], _BOOK_COLUMNS, active, params):
        no, rule = _serves(r)
        if not no:
            continue
        out.setdefault(no, {"report_as_of": as_of, "run_id": run["id"], "invoices": []})["invoices"].append(_served(r, rule=rule))
    for block in out.values():
        block["invoices"].sort(key=lambda i: (i["due_on"] or "", i["doc_no"]))
    # Q6 (TASK-204): the last applied receipt run overlays what it settles.
    return _overlay_receipts(conn, out, as_of)


# --- feedback round 2 / Q6: the receipt run (TASK-203/204) --------------------------
#
# Same landing shape as the invoice report, its own source and its own tables. One
# row per receipt; its lines folded into jsonb. The 13-digit id is parsed in-run and
# never stored (F5).

RECEIPT_SOURCE = "PEAK_RECEIPT"

_RECEIPT_STORED = ("doc_no", "doc_kind", "issued_on", "invoice_ref", "contact_code", "customer_name",
                   "status", "cycle_n", "cycle_of", "amount_total", "amount_due", "paid_on",
                   "paid_channel", "paid_amount", "note")

_RECEIPT_COLUMNS = ("import_run_id",) + _RECEIPT_STORED + (
    "lines", "verdict", "rule", "customer_no", "invoice_doc_no", "candidates")

RECEIPT_ONLY_TH = "ใบเสร็จนี้ไม่มีใบแจ้งหนี้ในรายงานที่ใช้อยู่"
RECEIPT_ONLY_EN = "This receipt's invoice is not in the applied invoice report"


def _write_receipt_rows(conn, rows, batch=500, on_written=None):
    if not rows:
        return 0
    columns = ", ".join(_RECEIPT_COLUMNS)
    cur = landing.stage_table(conn, "volt_stage_peak_receipt", "landing.peak_receipt")
    try:
        with cur.copy("copy volt_stage_peak_receipt (%s) from stdin" % columns) as copy:
            for i, row in enumerate(rows, start=1):
                copy.write_row(tuple(row.get(column) for column in _RECEIPT_COLUMNS))
                if on_written and i % batch == 0:
                    on_written(i)
        cur.execute(
            "insert into landing.peak_receipt (%s) select %s from volt_stage_peak_receipt "
            "on conflict (import_run_id, doc_no) do nothing" % (columns, columns))
    finally:
        cur.close()
    if on_written:
        on_written(len(rows))
    return len(rows)


def write_receipts(conn, parsed, verdicts, door="upload", filename=None, on_progress=None,
                   run_id=None, fingerprint=None):
    """The receipt run's write — the same contract as write(): verdicts are the ladder
    WITH the link register, one per receipt, in parse order."""
    covers_from, covers_to = report_range(filename)
    meta = {"report_as_of": (parsed.get("meta") or {}).get("report_as_of"),
            "exported_at": (parsed.get("meta") or {}).get("exported_at"),
            "covers_from": covers_from, "covers_to": covers_to,
            "door": door, "filename": filename, "fingerprint": fingerprint,
            "schema": (parsed.get("meta") or {}).get("schema")}
    if run_id:
        run = int(run_id)
        conn.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                     {"m": json.dumps(meta, ensure_ascii=False), "i": run})
    else:
        run = landing.start_run(conn, RECEIPT_SOURCE, meta=meta)
    counts = {"EXACT": 0, "CANDIDATE": 0, "UNMATCHED": 0}
    rows = []
    for rec, verdict in zip(parsed["receipts"], verdicts):
        params = {k: rec.get(k) for k in _RECEIPT_STORED}
        params.update(import_run_id=run,
                      lines=json.dumps(rec.get("lines") or [], ensure_ascii=False),
                      verdict=verdict["verdict"], rule=verdict.get("rule"),
                      customer_no=verdict.get("customer_no"),
                      invoice_doc_no=verdict.get("invoice_doc_no"),
                      candidates=json.dumps(verdict.get("candidates") or [], ensure_ascii=False))
        rows.append(params)
        counts[verdict["verdict"]] += 1
    _write_receipt_rows(conn, rows,
                        on_written=(lambda written: on_progress(landed=written)) if on_progress else None)
    rejected = list((parsed.get("meta") or {}).get("rejected") or [])
    receipt_only = sum(1 for v in verdicts if v["verdict"] == "EXACT" and not v.get("invoice_doc_no"))
    landing.write_unmapped(conn, run, [
        ("row-%s" % (r.get("row") or "?"), str(r.get("code") or "rejected"),
         str(r.get("value") if r.get("value") is not None else "—"))
        for r in rejected])
    conn.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                 {"m": json.dumps({"rejected": rejected, "matched": counts["EXACT"],
                                   "candidates": counts["CANDIDATE"], "unmatched": counts["UNMATCHED"]},
                                  ensure_ascii=False), "i": run})
    landing.finish_run(conn, run, "OK", row_counts={"read": (parsed.get("meta") or {}).get("read", 0),
                                                    "landed": len(parsed["receipts"]), "rejected": len(rejected)})
    return {"run_id": run, "receipts": len(parsed["receipts"]), "matched": counts["EXACT"],
            "candidates": counts["CANDIDATE"], "unmatched": counts["UNMATCHED"], "rejected": len(rejected),
            "receipt_only": receipt_only,
            "report_as_of": (parsed.get("meta") or {}).get("report_as_of"), "door": door}


def apply_receipt_run(conn, run_id, by, allow_older=False):
    """Q6 (TASK-204): a receipt run is compared against the last APPLIED RECEIPT run
    only — a receipt run newer than the applied invoice run is the normal case, so
    the invoice run's own date never gates this one."""
    _hold_the_lock(conn)
    run = landing.get_run(conn, run_id)
    if run is None or run.get("source_system") != RECEIPT_SOURCE:
        raise WriterRefused("not_found", "no PEAK receipt run %s" % run_id, "ไม่พบรอบนำเข้าใบเสร็จนี้")
    stamped = (run.get("meta") or {}).get("applied")
    if stamped:
        raise WriterRefused("already_applied",
                            "PEAK receipt run %s was already applied at %s by %s" % (run_id, stamped.get("at"), stamped.get("by")),
                            "รอบนำเข้านี้ถูกใช้ไปแล้ว — หากต้องการใช้อีกครั้ง ให้นำเข้าไฟล์นี้ใหม่")
    current = last_run(conn, applied=True, source=RECEIPT_SOURCE)
    mine_meta = run.get("meta") or {}
    if current and mine_meta.get("report_as_of"):
        theirs_meta = current.get("meta") or {}
        # fix-all P4 (F9): the file's own bytes are part of "the same report" — a
        # same-day re-export carrying new receipts applies; the identical file does not.
        same = all((mine_meta.get(k) or None) == (theirs_meta.get(k) or None)
                   for k in ("report_as_of", "covers_from", "covers_to", "fingerprint"))
        if same:
            raise WriterRefused(
                "report_already_applied",
                "the same receipt report (as of %s) is already applied as run %s" % (
                    mine_meta.get("report_as_of"), current.get("id")),
                "รายงานชุดเดียวกันนี้ (ณ %s) ถูกใช้อยู่แล้วในรอบ %s" % (mine_meta.get("report_as_of"), current.get("id")))
    if current and not allow_older:
        newer = (current.get("meta") or {}).get("report_as_of")
        mine = mine_meta.get("report_as_of")
        if not mine:
            raise WriterRefused("report_as_of_unknown",
                                "the receipt report's date is unknown, so it cannot be shown to be newer",
                                "ไม่ทราบวันที่ของรายงานนี้ จึงบอกไม่ได้ว่าใหม่กว่ารายงานที่ใช้อยู่")
        if newer and mine < newer:
            raise WriterRefused("report_older_than_applied",
                                "receipt report as of %s is older than the applied %s" % (mine, newer),
                                "รายงานนี้ (ณ %s) เก่ากว่ารายงานที่ใช้อยู่ (ณ %s)" % (mine, newer))
        # fix-all P4 (F5): the overlay reads only the last applied receipt run, so a
        # report reaching back less far un-pays the invoices in between.
        check_range(mine_meta, current.get("meta") or {}, allow_older, receipts=True)
    conn.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                 {"m": json.dumps({"applied": {"by": by, "at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"}}),
                  "i": int(run_id)})
    return landing.serialize_run(landing.get_run(conn, run_id))


def _overlay_receipts(conn, out, invoice_as_of):
    """All APPLIED receipt observations overlay the served invoices they settle.

    The latest observation per receipt number wins. This makes a re-upload
    idempotent and lets a later CANCELLED row reverse an earlier PAID row. Fix-all
    P2: every active PAID receipt naming an invoice counts, summed in Decimal. What is
    left is what the invoice asked less what came in — never below zero, never above
    the report's own awaiting — and the invoice reads PAID only when nothing is left;
    a part payment keeps the report's own status. `payments` carries those receipts in
    date order, each with its own source, plus the report's own payment when the run
    does not carry that receipt (a run starting later than the report must not drop
    money the report saw); `payment`, `paid_on` and `receipt_no` name the latest,
    `paid_amount` is the sum. A receipt whose invoice is not served rides as a
    `receipt_only` row to the customer the register names at READ time (`_serves`, as
    for invoices), so confirming, retiring or re-pointing a link moves it without a
    re-run — and a receipt the invoice step used is never served a second time."""
    run = last_run(conn, applied=True, source=RECEIPT_SOURCE)
    if run is None:
        return out
    receipt_as_of = (run.get("meta") or {}).get("report_as_of")
    # Dedupe *before* filtering status; otherwise a latest CANCELLED observation
    # would expose an older PAID observation again.
    rows = conn.execute(text(
        "select p.doc_no, p.doc_kind, p.issued_on, p.invoice_ref, p.contact_code, p.cycle_n, p.cycle_of, "
        "p.amount_total, p.amount_due, p.paid_on, p.paid_channel, p.paid_amount, p.verdict, p.rule, "
        "p.customer_no, p.invoice_doc_no, null as ladder_verdict, l.customer_no as linked_no "
        "from (select distinct on (pr.doc_no) pr.* from landing.peak_receipt pr "
        "join landing.import_run ir on ir.id=pr.import_run_id "
        "where ir.status='OK' and ir.source_system=:source and ir.meta ? 'applied' "
        "order by pr.doc_no, cast(ir.meta->'applied'->>'at' as timestamptz) desc nulls last, ir.id desc) p "
        "left join records.identity_link l "
        "on l.retired_at is null and l.source = 'PEAK_LINK' and l.contact_code = %s "
        "where p.status = 'PAID' order by p.paid_on, p.doc_no" % (_NORM % "p.contact_code")),
        {"source": RECEIPT_SOURCE}).mappings().all()
    # When the amount-led ledger exists it is authoritative, including FIFO carry
    # to invoices other than the reference. Direct writer-level tests that do not
    # run reconciliation retain the legacy reference overlay as a compatibility seam.
    # The served book is built while the application module imports, before the
    # startup migration hook runs. A database upgraded from an older revision does
    # not have this table yet, so the first boot must use the legacy overlay until
    # migration creates it instead of failing the whole API process.
    ledger_table = conn.execute(text(
        "select to_regclass('records.payment_allocation')")).scalar()
    ledger = []
    if ledger_table:
        ledger = conn.execute(text(
            "select receipt_doc_no, invoice_doc_no, amount from records.payment_allocation "
            "where active and invoice_doc_no is not null order by receipt_doc_no, allocation_order"
        )).mappings().all()
    if ledger:
        receipt_by_doc = {row["doc_no"]: row for row in rows}
        allocated_rows = []
        for allocation in ledger:
            receipt = receipt_by_doc.get(allocation["receipt_doc_no"])
            if receipt is None:
                continue
            allocated_rows.append(dict(receipt, invoice_doc_no=allocation["invoice_doc_no"],
                                       paid_amount=allocation["amount"]))
        rows = allocated_rows
    by_invoice = {}
    for r in rows:
        ref = (r["invoice_doc_no"] or r["invoice_ref"] or "").strip()
        if ref and r["paid_on"]:
            by_invoice.setdefault(ref, []).append(r)
    used = set()
    # This read runs during book startup, before app-level fixtures are available.
    # Identify adjusted customers by their durable invoice references instead.
    adjusted_docs = set()
    adjusted_customers = set()
    if conn.execute(text("select to_regclass('records.service_deferral')")).scalar():
        for payload in conn.execute(text("select payload from records.service_deferral")).scalars():
            adjusted_docs.update(m.get("invoice_doc_no") for m in payload.get("moves", []))
            if payload.get("customer_no"):
                adjusted_customers.add(str(payload["customer_no"]))
    for customer_no, block in out.items():
        adjusted = str(customer_no) in adjusted_customers or any(i["doc_no"] in adjusted_docs for i in block["invoices"])
        for inv in block["invoices"]:
            paid = by_invoice.get(inv["doc_no"])
            if not paid:
                continue
            used.update(r["doc_no"] for r in paid)
            payments = [dict(_payment(r, r["doc_no"]), source=RECEIPT_SOURCE) for r in paid]
            own = inv["payment"]            # the report's own; without a number it cannot be told apart
            if own and own["receipt_no"] and own["receipt_no"] not in {p["receipt_no"] for p in payments}:
                payments = sorted(payments + [dict(own, source="PEAK_REPORT")],
                                  key=lambda p: (p["on"] or "", p["receipt_no"]))
            total = sum((Decimal(p["amount"]) for p in payments if p["amount"]), Decimal(0))
            asked = Decimal(inv.get("amount_due") or inv.get("amount_total") or "0")
            left = min(max(Decimal(0), asked - total), Decimal(inv["amount_awaiting"]))
            if adjusted and invoice_as_of:
                newer = sum((Decimal(str(r["paid_amount"] or 0)) for r in paid
                             if str(r["paid_on"])[:10] > str(invoice_as_of)[:10]), Decimal(0))
                left = min(left, max(Decimal(0), Decimal(inv["amount_awaiting"]) - newer))
                total = asked - left
            inv.update({
                "status": "PAID" if left == 0 else inv["status"],
                "paid_on": payments[-1]["on"],
                "paid_amount": str(total.quantize(CENT)),
                "receipt_no": payments[-1]["receipt_no"],
                "payment_source": RECEIPT_SOURCE,
                "amount_awaiting": str(left.quantize(CENT)),
                "payment": payments[-1],
                "payments": payments,
            })
    served = {inv["doc_no"] for block in out.values() for inv in block["invoices"]}
    for r in rows:
        if r["doc_no"] in used or r["invoice_doc_no"] in served:
            continue                          # served on its invoice (rule 1's included)
        no, rule = _serves(r)
        if not no:
            continue
        block = out.setdefault(no, {"report_as_of": receipt_as_of, "run_id": run["id"], "invoices": []})
        cycle = {"n": r["cycle_n"], "of": r["cycle_of"]} if r["cycle_n"] else None
        payment = _payment(r, r["doc_no"])
        block["invoices"].append({
            "doc_no": r["doc_no"], "doc_kind": r["doc_kind"], "status": "PAID",
            "receipt_only": True, "issued_on": _iso(r["issued_on"]), "due_on": None,
            "cycle": cycle,
            "amount_total": str(r["amount_total"]) if r["amount_total"] is not None else None,
            "amount_due": str(r["amount_due"]) if r["amount_due"] is not None else None,
            "amount_awaiting": "0.00",
            "payment": payment, "payments": [payment],
            "contact_code": r["contact_code"], "rule": rule,
            "note_th": RECEIPT_ONLY_TH, "note_en": RECEIPT_ONLY_EN,
        })
    for key, block in out.items():
        if invoice_as_of or receipt_as_of:
            block["report_as_of"] = max(x for x in (invoice_as_of, receipt_as_of) if x)
        block["invoices"].sort(key=lambda i: (i.get("due_on") or "", i["doc_no"]))
    return out


def receipt_rows(conn, run_id, verdict=None, limit=100, offset=0):
    """The receipt run's review list — the same shape as `rows()` above."""
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    if verdict == "REJECTED":
        total = conn.execute(text(
            "select count(*) from landing.import_unmapped where import_run_id = :r"),
            {"r": int(run_id)}).scalar() or 0
        found = conn.execute(text(
            "select volt_id, field, value from landing.import_unmapped "
            "where import_run_id = :r order by volt_id limit :lim offset :off"),
            {"r": int(run_id), "lim": limit, "off": offset}).mappings().all()
        return {"rows": [{"verdict": "REJECTED", "row": dict(r)["volt_id"],
                          "code": dict(r)["field"], "value": dict(r)["value"]} for r in found],
                "total": total, "limit": limit, "offset": offset}
    clause = "and verdict = :v" if verdict else ""
    params = {"r": int(run_id), "lim": limit, "off": offset}
    if verdict:
        params["v"] = verdict
    total = conn.execute(text("select count(*) from landing.peak_receipt where import_run_id = :r %s" % clause),
                         {k: v for k, v in params.items() if k in ("r", "v")}).scalar() or 0
    # The register is read at READ time (fix-all P10a): `linked_no` names the customer a
    # receipt's code is linked to now, so the review list stops showing a linked receipt
    # as waiting — the same field rows() serves for invoices.
    found = conn.execute(text(
        "select p.*, l.customer_no as linked_no from landing.peak_receipt p "
        "left join records.identity_link l on l.retired_at is null and l.source = 'PEAK_LINK' and l.contact_code = %s "
        "where p.import_run_id = :r %s "
        "order by p.paid_on desc nulls last, p.doc_no limit :lim offset :off" % (_NORM % "p.contact_code", clause)),
        params).mappings().all()
    rows = [{k: _row_value(k, v) for k, v in dict(r).items()} for r in found]
    for row in rows:
        row["candidates"] = peak_candidates.merge(row.get("candidates") or [])
    return {"rows": rows,
            "total": total, "limit": limit, "offset": offset}


def conflict_rows(conn, run_id):
    """D02 / TASK-208: every differing field the run carries, raw and ordered by customer
    and doc_no — the router groups them per customer and joins the active decision.

    Fix-all P5 (audit): only rows the book serves to that same customer NOW (`_serves`,
    the register read as the book reads it). A row whose link was retired or re-pointed
    is not that customer's invoice any more, and its conflicts were measured against
    them: the page, a person's decision and the apply's defaults all leave it out."""
    rows = _linked_rows(conn, run_id, ("doc_no", "customer_no", "conflicts", "verdict", "rule", "ladder_verdict",
                                       "ladder_customer_no", "ladder_rule"),
                        "and p.verdict = 'EXACT' and p.conflicts is not null")
    return sorted(({"doc_no": r["doc_no"], "customer_no": r["customer_no"], "conflicts": r["conflicts"]}
                   for r in rows if r["customer_no"] and _serves(r)[0] == r["customer_no"]),
                  key=lambda r: (r["customer_no"], r["doc_no"]))
