"""Monthly history (Arina, 2026-09-25): one row per customer per month in
records.customer_month — payment status, its source, overdue, outstanding, DPD,
officer. `snapshot` writes only the CURRENT month's key, so the row of a month that
has turned is final by construction. It runs after every landing (refresh.after_landing),
after a manual status (cases.set_payment_status) and at boot.

Read from the shared served book plus the shared overrides: a status a person set
only in their own session (a ladder NPL, a reassignment) is not in it."""
from decimal import Decimal

from sqlalchemy import text

from . import db
from .config import settings

_UPSERT = text("""
insert into records.customer_month (month, customer_uid, volt_id, customer_no, product, payment_status,
    status_source, overdue, outstanding, oldest_dpd, officer, taken_at, taken_by_kind)
values (:month, :customer_uid, :volt_id, :customer_no, :product, :payment_status,
    :status_source, :overdue, :outstanding, :oldest_dpd, :officer, now(), :kind)
on conflict (month, customer_uid) do update set
    volt_id = excluded.volt_id, customer_no = excluded.customer_no, product = excluded.product,
    payment_status = excluded.payment_status, status_source = excluded.status_source,
    overdue = excluded.overdue, outstanding = excluded.outstanding, oldest_dpd = excluded.oldest_dpd,
    officer = excluded.officer, taken_at = now(), taken_by_kind = excluded.taken_by_kind, in_book = true""")
_LEFT = text("update records.customer_month set in_book = false "
             "where month = :month and in_book and not (customer_uid = any(:uids))")


def current_month():
    return settings.business_date.strftime("%Y-%m")


def _row(customer, month, kind, overrides):
    from . import cases, main
    code, source = cases.payment_status_with_source(customer)
    row = (overrides or {}).get(customer.uid)
    if row is not None and row.get("system_code_at_set") == code:
        code, source = row["code"], "OVERRIDE"
    arrears, dpd, _band, outstanding = main._customer_aggregate(customer)
    return {"month": month, "customer_uid": customer.uid, "volt_id": getattr(customer, "volt_id", None),
            "customer_no": customer.customer_no,
            "product": customer.contracts[0].product if customer.contracts else None,
            "payment_status": code, "status_source": source, "overdue": arrears, "outstanding": outstanding,
            "oldest_dpd": dpd, "officer": main._officer_overlay().get(customer.uid, customer.officer),
            "kind": kind}


def snapshot(kind, uids=None):
    """Upsert the current month's row for every book customer (or `uids`). Returns the
    number written; 0 with no database, or when the business date sits in a month
    older than one already held (a pin moved back must not rewrite a finished month).

    Read in the SHARED session whatever request triggered it: a landing started by one
    person must not write that person's session-only changes (a ladder NPL, a
    reassignment) into everyone's history (review, 2026-09-25)."""
    if not db.configured():
        return 0
    from . import main, payment_overrides, session, request_context
    month = current_month()
    newest = _read("select max(month) as m from records.customer_month", {})[0]["m"]
    if newest and month < newest:
        return 0
    token = session.CURRENT.set(session.SHARED)
    # One consistent read scope for the batch, also outside HTTP requests at boot.
    # Keep it separate from the caller's session-specific cached domain reads.
    read_token = request_context.begin_read()
    try:
        overrides = payment_overrides.active()
        wanted = set(uids) if uids else None
        rows = [_row(c, month, kind, overrides) for c in main.CUSTOMERS
                if getattr(c, "volt_id", None) and (wanted is None or c.uid in wanted)]
    finally:
        request_context.end_read(read_token)
        session.CURRENT.reset(token)
    if rows:
        conn = db.connect()
        try:
            conn.execute(_UPSERT, rows)
            if wanted is None:          # a full snapshot: whoever is not in the book left it
                conn.execute(_LEFT, {"month": month, "uids": [r["customer_uid"] for r in rows]})
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return len(rows)


def safe_snapshot(kind, uids=None):
    """`snapshot` for the callers that must not fail: a landing already committed, a
    status already set, a boot must proceed."""
    import sys
    try:
        return snapshot(kind, uids)
    except Exception as exc:                        # noqa: BLE001 — history is never the thing that fails
        print("monthly history not written: %s" % exc.__class__.__name__, file=sys.stderr)
        return 0


def _read(sql, params):
    """A read on its own connection, its transaction ended either way."""
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]
    finally:
        conn.rollback()
        conn.close()


def _money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def for_customer(uid):
    """The customer's months, newest first; [] with no database."""
    if not db.configured():
        return []
    rows = _read("select month, payment_status, status_source, overdue, outstanding, oldest_dpd, officer, taken_at "
                 "from records.customer_month where customer_uid = :u order by month desc", {"u": uid})
    return [{**dict(r), "overdue": _money(r["overdue"]), "outstanding": _money(r["outstanding"]),
             "taken_at": r["taken_at"].isoformat() if r["taken_at"] else None} for r in rows]


def report(months=12):
    """Per month, newest first: customers and money by status, NPL in/out against the
    month before (None for the first month held) and the change on that month (mom)."""
    if not db.configured():
        return []
    held = [r["month"] for r in _read("select distinct month from records.customer_month where in_book "
                                        "order by month desc limit :n", {"n": max(1, min(int(months), 60)) + 1})]
    rows = _read("select month, customer_uid, payment_status, overdue, outstanding from records.customer_month "
                 "where in_book and month = any(:m)", {"m": held}) if held else []
    by_month = {}
    for r in rows:
        by_month.setdefault(r["month"], []).append(r)
    out = []
    for i, month in enumerate(held):
        this = by_month.get(month, [])
        # The CALENDAR month before, not the previous month held: a missing month
        # compares against nothing rather than reading as "vs last month".
        prev_month = _month_before(month) if _month_before(month) in by_month else None
        prev = {r["customer_uid"]: r["payment_status"] for r in by_month.get(prev_month, [])}
        now = {r["customer_uid"]: r["payment_status"] for r in this}
        statuses = {}
        for r in this:
            s = statuses.setdefault(r["payment_status"], {"count": 0, "outstanding": Decimal(0), "overdue": Decimal(0)})
            s["count"] += 1
            s["outstanding"] += r["outstanding"] or 0
            s["overdue"] += r["overdue"] or 0
        total = {"customers": len(this), "outstanding": sum((r["outstanding"] or 0 for r in this), Decimal(0)),
                 "overdue": sum((r["overdue"] or 0 for r in this), Decimal(0))}
        out.append({"month": month, "customers": total["customers"],
                    "outstanding": _money(total["outstanding"]), "overdue": _money(total["overdue"]),
                    "by_status": {k: {"count": v["count"], "outstanding": _money(v["outstanding"]),
                                      "overdue": _money(v["overdue"])} for k, v in statuses.items()},
                    "npl_in": sum(1 for u, s in now.items() if s == "NPL" and prev.get(u) != "NPL") if prev_month else None,
                    "npl_out": sum(1 for u, s in prev.items() if s == "NPL" and now.get(u) != "NPL") if prev_month else None,
                    "_total": total})
    totals = {m["month"]: m["_total"] for m in out}
    for m in out:
        before = totals.get(_month_before(m["month"]))
        t = m.pop("_total")
        m["mom"] = None if before is None else {
            "customers": t["customers"] - before["customers"],
            "outstanding": _money(t["outstanding"] - before["outstanding"]),
            "overdue": _money(t["overdue"] - before["overdue"])}
    return out[:max(1, min(int(months), 60))]


def _month_before(month):
    y, m = (int(x) for x in month.split("-"))
    return "%04d-%02d" % ((y, m - 1) if m > 1 else (y - 1, 12))


def month_rows(month):
    """Every customer counted in one month, for the export."""
    if not db.configured():
        return []
    return _read("select * from records.customer_month where month = :m and in_book order by volt_id", {"m": month})
