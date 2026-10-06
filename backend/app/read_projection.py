"""Indexed collection reads, derived by the existing business engine.

The writer's transaction publishes source facts and projections together. A full
rebuild creates another generation and swaps one pointer only after every row is
complete. Projections contain business facts, never authentication/capabilities.
"""
import hashlib
import json
import os
import secrets
from decimal import Decimal

from sqlalchemy import text

from . import errors

BUILD_LOCK = 0x564F4C5450524A
FIELDS = ("entity", "product", "payment_status", "dc_status", "officer", "tier", "ladder_indicative")
SORTS = {"aggregate_overdue": "overdue", "aggregate_outstanding": "outstanding", "oldest_dpd": "dpd",
         "display_name": "display_name", "next_action_on": "next_action_on", "tier": "tier_rank",
         "oldest_unpaid": "oldest_unpaid_on"}


def _unit():
    from .production_unit import CURRENT
    return CURRENT.get()


def enabled():
    unit = _unit()
    return bool(unit and unit.get("capacity") and os.environ.get("VOLT_INDEXED_READS_ENABLED", "true") == "true")


def invalidate_customers(conn, customer_uids, reason="domain"):
    unit = _unit()
    if unit and unit.get("capacity"):
        unit.setdefault("projection_customers", set()).update(str(uid) for uid in customer_uids if uid)


def invalidate_all(conn, reason="landing"):
    unit = _unit()
    if unit and unit.get("capacity"):
        unit["projection_all"] = True
    # Outside a durable unit (startup/maintenance) the pointer stays dirty until
    # rebuild(), so no new source epoch can masquerade as a complete projection.
    available = bool(unit and unit.get("capacity"))
    if unit is None:
        available = bool(conn.execute(text("select to_regclass('app.projection_current') is not null and "
            "coalesce((select version from app.schema_version where singleton),0)>=3")).scalar_one())
    if available:
        conn.execute(text("update app.projection_current set dirty=true where singleton"))


def _decimal(value):
    return Decimal(str(value or 0))


def _row(customer_uid, workbook, today, cs, business_date):
    case = (workbook or {}).get("case") or {}
    customer = workbook.get("customer") or {}
    pp = workbook.get("payment_position") or {}
    contacts = [row for row in cs.contact_log if row.get("customer_uid") == customer_uid
                and str(row.get("occurred_at") or "")[:10] == business_date]
    from . import cases
    promises = [cs.ptps.get(row.get("ptp_uid")) for row in contacts if row.get("ptp_uid")]
    promises = [row for row in promises if row]
    return {
        "customer_uid": customer_uid, "workbook": json.dumps(workbook, ensure_ascii=False),
        "today": json.dumps(today, ensure_ascii=False) if today is not None else None,
        "entity": workbook.get("entity"), "product": ("LEASE" if workbook.get("entity") == "SPV" else "CASH")
        if case.get("sheet") else None,
        "payment_status": case.get("payment_status"), "dc_status": case.get("dc_status"),
        "officer": case.get("officer_uid"), "tier": (today or workbook).get("tier"),
        "tier_rank": (today or workbook).get("tier_rank"),
        "ladder_indicative": (workbook.get("ladder") or {}).get("indicative"),
        "search_text": "\n".join(str(value or "").lower() for value in
                                   (customer.get("display_name"), case.get("volt_id"), customer.get("customer_no"))),
        "display_name": customer.get("display_name") or "", "overdue": _decimal(workbook.get("aggregate_overdue")),
        "outstanding": _decimal(workbook.get("aggregate_outstanding")), "dpd": workbook.get("oldest_dpd"),
        "next_action_on": case.get("next_action_on") or "", "oldest_unpaid_on": (pp.get("oldest_unpaid") or {}).get("due_date"),
        "identity_only": bool(workbook.get("identity_only")), "has_sheet": bool(case.get("sheet")),
        "unpaid": bool(pp.get("open_count")), "stale": pp.get("stale") is True,
        "worked": bool((today or {}).get("worked_today")), "answers_waiting": len((today or {}).get("waiting") or []),
        "contact_open": (workbook.get("contact_lock") or {}).get("state") == "OPEN",
        "promise_history": bool(case.get("broken_ptp_count") or case.get("open_ptp")),
        "kept_ptps": int(case.get("kept_ptp_count") or 0), "ptp_today": len(promises),
        "ptp_amount": sum((_decimal(row.get("promised_amount")) for row in promises), Decimal(0)),
        "unreachable_today": sum(row.get("result") in cases.UNREACHABLE_RESULTS for row in contacts),
    }


def _save_rows(conn, generation, rows):
    if not rows:
        return
    columns = list(rows[0])
    sql = "insert into app.customer_projection(generation,%s) values(:generation,%s) " % (
        ",".join(columns), ",".join("cast(:%s as jsonb)" % col if col in ("workbook", "today") else ":" + col for col in columns))
    sql += "on conflict(generation,customer_uid) do update set " + ",".join(
        col + "=excluded." + col for col in columns if col != "customer_uid")
    conn.execute(text(sql), [dict(row, generation=generation) for row in rows])


def rebuild(conn):
    """Use fresh bounded reads after source writes, then restore caller caches.

    Global mutations deliberately avoid request-wide financial memoization. Their
    projection publication is read-only derivation within the same transaction,
    so it can safely share metadata and contract calculations for this build.
    """
    from . import main, request_context
    memo_token = main._VIEW_MEMO.set({})
    read_token = request_context.begin_read()
    try:
        return _rebuild(conn)
    finally:
        request_context.end_read(read_token)
        main._VIEW_MEMO.reset(memo_token)


def _rebuild(conn):
    """Build one complete shadow generation with legacy financial functions."""
    from . import cases, data_epoch, journey, session, today as domain
    from .config import settings
    from .routers.today import _legacy_workbook
    unit = _unit()
    old_scope = unit.pop("customer_uid", None)
    unit["seeding"] = True
    # A global writer or cold-read build holds this transaction lock. Other readers
    # use the previous committed pointer, not this uncommitted generation.
    conn.execute(text("select pg_advisory_xact_lock(:k)"), {"k": BUILD_LOCK})
    try:
        from .production_runtime import prepare_book
        prepare_book(exclusive=True)
        source_epoch = int(conn.execute(text("select coalesce(max(id),0) from app.data_epoch")).scalar_one())
        cs = cases.for_current()
        cases.open_collection_cases(cs)
        cs = cases.for_current()
        today = domain.build()
        domain.annotate_worked(today["items"], settings.business_date)
        today["meta"]["worked_today_count"] = sum(bool(row["worked_today"]) for row in today["items"])
        today["meta"]["daily_summary"] = domain.daily_summary(today["items"], cs, settings.business_date)
        workbook = _legacy_workbook(identities="1", _projection_all=True)
        generation = conn.execute(text(
            "insert into app.projection_generation(source_epoch,business_date,metadata) "
            "values(:epoch,:day,cast(:metadata as jsonb)) returning id"), {
                "epoch": source_epoch, "day": settings.business_date,
                "metadata": json.dumps({"today": {"run": today["run"], "meta": today["meta"]},
                                        "workbook": {"meta": workbook["meta"]}}, ensure_ascii=False)}).scalar_one()
        today_rows = {row["customer"]["uid"]: row for row in today["items"]}
        rows = [_row(row["customer"]["uid"], row, today_rows.get(row["customer"]["uid"]), cs,
                     str(settings.business_date)) for row in workbook["rows"]]
        _save_rows(conn, generation, rows)
        conn.execute(text("insert into app.customer_version(customer_uid) "
                          "select customer_uid from app.customer_projection where generation=:g "
                          "on conflict do nothing"), {"g": generation})
        # Pre-install cases live outside the collection/book projection but still
        # expose case ETags. Register them so a later global edit invalidates all
        # previously opened case files, including those without a money row.
        if cs.cases:
            conn.execute(text("insert into app.customer_version(customer_uid) "
                              "select unnest(cast(:uids as text[])) on conflict do nothing"), {"uids": list(cs.cases)})
        # Publish seeded stores once. Scoped requests restore indexed rows thereafter.
        from .production_unit import flush
        flush()
        conn.execute(text("update app.projection_current set generation=:g,ordering_version=ordering_version+1,"
                          "dirty=false where singleton"), {"g": generation})
        unit.pop("projection_all", None)
        unit.pop("projection_customers", None)
        return generation
    finally:
        unit.pop("seeding", None)
        if old_scope is not None:
            unit["customer_uid"] = old_scope


def current(conn):
    from .config import settings
    row = conn.execute(text(
        "select c.generation,c.ordering_version,c.dirty,g.source_epoch,g.business_date,g.metadata "
        "from app.projection_current c left join app.projection_generation g on g.id=c.generation where singleton"
    )).mappings().one()
    epoch = int(conn.execute(text("select coalesce(max(id),0) from app.data_epoch")).scalar_one())
    if row["dirty"] or row["generation"] is None or row["source_epoch"] != epoch or row["business_date"] != settings.business_date:
        if _unit().get("book_exclusive") is False:
            from .production_runtime import BookRefreshRequired
            raise BookRefreshRequired()
        # Cold start/import publication: rebuild under the legacy writer barrier.
        # A request that already owns a customer lock must first finish its write;
        # the middleware invokes refresh before commit.
        rebuild(conn)
        row = conn.execute(text(
            "select c.generation,c.ordering_version,c.dirty,g.source_epoch,g.business_date,g.metadata "
            "from app.projection_current c join app.projection_generation g on g.id=c.generation where singleton"
        )).mappings().one()
    return dict(row)


def refresh_customers(conn, customer_uids):
    """Refresh the affected customer's projection in its source transaction."""
    from . import cases, journey, today as domain
    from .config import settings
    from .routers.today import _legacy_workbook, _identity_row
    unit = _unit()
    if not unit or not unit.get("capacity"):
        return
    pointer = conn.execute(text("select generation,dirty from app.projection_current where singleton")).one()
    if pointer.generation is None or pointer.dirty or unit.get("projection_all"):
        rebuild(conn)
        return
    cs = cases.for_current()
    today = domain.build()
    domain.annotate_worked(today["items"], settings.business_date)
    today_rows = {row["customer"]["uid"]: row for row in today["items"]}
    workbook = _legacy_workbook()
    workbook_rows = {row["customer"]["uid"]: row for row in workbook["rows"]}
    wanted = set(customer_uids)
    rows = []
    removed = False
    previous = {row["customer_uid"]: row for row in conn.execute(text(
        "select * from app.customer_projection where generation=:g and customer_uid=any(:uids)"),
        {"g": pointer.generation, "uids": list(wanted)}).mappings()}
    for uid in wanted:
        row = workbook_rows.get(uid)
        customer = journey.customer_by_uid(uid)
        if row is None and customer is not None and not customer.contracts:
            row = _identity_row(customer, cs)
        if row is not None:
            rows.append(_row(uid, row, today_rows.get(uid), cs, str(settings.business_date)))
        else:
            removed = bool(conn.execute(text("delete from app.customer_projection where generation=:g and customer_uid=:u"),
                                       {"g": pointer.generation, "u": uid}).rowcount) or removed
    changed = [row for row in rows if row["customer_uid"] not in previous or any(
        previous[row["customer_uid"]].get(key) != (json.loads(value) if key in ("workbook", "today") and value is not None else value)
        for key, value in row.items())]
    _save_rows(conn, pointer.generation, changed)
    if changed or removed:
        conn.execute(text("update app.projection_current set ordering_version=ordering_version+1 where singleton"))


def finish_write(conn):
    unit = _unit()
    if not unit or not unit.get("capacity"):
        return
    if unit.get("projection_all") or not unit.get("customer_uid"):
        # An unaudited/global action may change any customer's case. Invalidate
        # every scoped token conservatively; the exclusive legacy barrier makes
        # this one atomic publication with the source/projection transaction.
        conn.execute(text("update app.customer_version set version=version+1"))
        invalidate_all(conn)
        rebuild(conn)
    else:
        refresh_customers(conn, unit.get("projection_customers", set()) | {unit["customer_uid"]})


def _filters(generation, filters, kind, *, omit_tier=False):
    where = ["generation=:generation"]
    params = {"generation": generation}
    if kind == "today":
        where.append("today is not null")
    elif not filters.get("identities"):
        where.append("not identity_only")
    for field in FIELDS:
        value = filters.get(field)
        if value and not (field == "tier" and omit_tier):
            where.append(field + "=:" + field)
            params[field] = value
    if filters.get("unassigned"):
        where.append("coalesce(officer,'')=''")
    if filters.get("q"):
        where.append("strpos(search_text,:q)>0")
        params["q"] = str(filters["q"]).strip().lower()
    if filters.get("position") in ("unpaid", "stale"):
        where.append("unpaid" if filters["position"] == "unpaid" else "stale")
    return " and ".join(where), params


def _problem(kind, stale=False):
    return errors.Problem(kind + ("_cursor_stale" if stale else "_cursor_invalid"), 409 if stale else 422,
                          "Reload the list", "The cursor is stale or belongs to another query.",
                          "รายการเปลี่ยนแล้ว กรุณาโหลดรายการใหม่", "DEBT-PAGE-001")


def _anchor(conn, token, identity, kind):
    if not isinstance(token, str) or len(token) != 43:
        raise _problem(kind, stale=True)
    row = conn.execute(text("select payload,subject from app.projection_cursor where token_hash=:t "
                            "and expires_at>now()"), {"t": hashlib.sha256(token.encode()).hexdigest()}).first()
    if not row or row.subject != (_unit().get("subject") or "anonymous"):
        raise _problem(kind)
    if row.payload.get("identity") != identity:
        raise _problem(kind, stale=True)
    return row.payload["anchor"]


def _cursor(conn, identity, anchor):
    token = secrets.token_urlsafe(32)
    conn.execute(text("insert into app.projection_cursor(token_hash,subject,payload) "
                      "values(:t,:s,cast(:p as jsonb))"), {
        "t": hashlib.sha256(token.encode()).hexdigest(), "s": _unit().get("subject") or "anonymous",
        "p": json.dumps({"identity": identity, "anchor": anchor}, default=str)})
    return token


def _rows(conn, pointer, filters, kind, limit, cursor, sort, direction):
    where, params = _filters(pointer["generation"], filters, kind)
    column = SORTS.get(sort, "overdue")
    descending = direction == "desc"
    # UID is the existing stable tie-breaker. NULL/undated rows remain last in
    # both directions, including the oldest-unpaid sort.
    expression = "coalesce(dpd,0)" if column == "dpd" else column
    if column in ("display_name", "next_action_on", "oldest_unpaid_on"):
        expression += ' collate "C"'
    order = expression + (" desc" if descending else " asc") + ' nulls last,customer_uid collate "C" asc'
    if kind == "today":
        money_order = "overdue desc,coalesce(dpd,0) desc" if sort == "arrears" else "coalesce(dpd,0) desc,overdue desc"
        order = 'tier_rank asc,' + money_order + ',display_name collate "C" asc,customer_uid collate "C" asc'
    identity = [kind, pointer["generation"], pointer["ordering_version"], str(pointer["business_date"]),
                filters, sort, direction]
    if cursor:
        anchor = _anchor(conn, cursor, identity, kind)
        if kind == "today":
            money_keys = "-overdue,-coalesce(dpd,0)" if sort == "arrears" else "-coalesce(dpd,0),-overdue"
            where += ' and (tier_rank,' + money_keys + ',display_name collate "C",customer_uid collate "C") > '
            where += "(:a_tier,cast(:a_first as numeric),cast(:a_second as numeric),:a_name,:a_uid)"
            params.update(a_tier=anchor[0], a_first=anchor[1], a_second=anchor[2], a_name=anchor[3], a_uid=anchor[4])
        else:
            params.update(a_value=anchor[0], a_uid=anchor[1])
            cast = "cast(:a_value as numeric)" if column in ("overdue", "outstanding", "dpd", "tier_rank") else ":a_value"
            if anchor[0] is None:
                where += " and " + expression + ' is null and customer_uid collate "C">:a_uid'
            else:
                where += " and (" + expression + " is null or " + expression + ("<" if descending else ">") + cast
                where += " or (" + expression + "=" + cast + ' and customer_uid collate "C">:a_uid))'
    params["limit"] = limit + 1 if limit else 2147483647
    rows = conn.execute(text("select customer_uid," + kind + " as payload," + expression + " as sort_value,"
                             "tier_rank,dpd,overdue,display_name from app.customer_projection where " + where +
                             " order by " + order + " limit :limit"), params).mappings().all()
    has_more = bool(limit and len(rows) > limit)
    kept = rows[:limit] if limit else rows
    next_cursor = None
    if has_more:
        last = kept[-1]
        anchor = [last["tier_rank"], -(last["dpd"] or 0), str(-last["overdue"]), last["display_name"], last["customer_uid"]]
        if kind == "today" and sort == "arrears":
            anchor[1], anchor[2] = anchor[2], anchor[1]
        if kind != "today":
            anchor = [str(last["sort_value"]) if last["sort_value"] is not None else None, last["customer_uid"]]
        next_cursor = _cursor(conn, identity, anchor)
    return [row["payload"] for row in kept], {"limit": limit, "returned": len(kept), "has_more": has_more,
                                               "next_cursor": next_cursor}


def workbook(filters, sort="aggregate_overdue", direction="desc", limit=None, cursor=None):
    conn = _unit()["conn"]
    pointer = current(conn)
    where, params = _filters(pointer["generation"], filters, "workbook")
    total, identities = conn.execute(text("select count(*),count(*) filter(where identity_only) "
                                          "from app.customer_projection where " + where), params).one()
    rows, page = _rows(conn, pointer, filters, "workbook", limit, cursor, sort, direction)
    meta = dict(pointer["metadata"]["workbook"]["meta"])
    shown = sum(bool(row.get("identity_only")) for row in rows)
    if not limit and identities:
        cap = 200 if filters.get("q") else 50
        rows = [row for row in rows if not row.get("identity_only")] + [row for row in rows if row.get("identity_only")][:cap]
        shown = min(identities, cap)
        total = len(rows)
    meta.update(total=total, identities_total=identities, identities_shown=shown,
                ladder_indicative=filters.get("ladder_indicative"))
    meta["identities_note_th"] = "รายชื่อ Odoo แสดง %d จาก %d · พิมพ์ในช่องค้นหาเพื่อดูรายอื่น" % (shown, identities) if identities else None
    meta["identities_note_en"] = "Odoo names: %d of %d shown · type in the search box for the rest" % (shown, identities) if identities else None
    result = {"rows": rows, "meta": meta}
    if limit:
        result["page"] = page
    return result


def today(filters, limit=None, cursor=None, sort="priority"):
    from . import today as domain
    conn = _unit()["conn"]
    pointer = current(conn)
    where, params = _filters(pointer["generation"], filters, "today")
    rows, page = _rows(conn, pointer, filters, "today", limit, cursor, sort, "asc")
    tiers = {tier: 0 for tier in domain.TIERS}
    counts = conn.execute(text("select tier,count(*),count(*) filter(where not worked and payment_status<>'PENDING') "
                                "from app.customer_projection where " + where + " group by tier"), params).all()
    unworked = dict(tiers)
    for tier, count, not_worked in counts:
        tiers[tier] = count
        unworked[tier] = not_worked
    all_tiers_where, all_tiers_params = _filters(pointer["generation"], filters, "today", omit_tier=True)
    tier_options = {tier: 0 for tier in domain.TIERS}
    for tier, count in conn.execute(text("select tier,count(*) from app.customer_projection where " + all_tiers_where + " group by tier"), all_tiers_params):
        tier_options[tier] = count
    aggregate = conn.execute(text(
        "select count(*),count(*) filter(where worked),count(*) filter(where not worked and payment_status='PENDING'),"
        "count(*) filter(where answers_waiting>0),bool_or(promise_history),coalesce(sum(kept_ptps),0) "
        "from app.customer_projection where " + where), params).one()
    meta = dict(pointer["metadata"]["today"]["meta"])
    meta.update(total=aggregate[0], worked_today_count=aggregate[1], pending_unworked_count=aggregate[2],
                unworked_tier_counts=unworked, counts_by_tier=tiers, tier_partition=tiers, tier_counts=tier_options,
                answers_waiting=aggregate[3], answers_waiting_elsewhere=aggregate[3]-tiers["ANSWER_WAITING"],
                filters={**filters, "q": str(filters.get("q") or "").strip().lower() or None},
                ladder_indicative=filters.get("ladder_indicative"), sort=sort)
    from . import main
    meta["board_counts"] = dict.fromkeys((column["column_id"] for column in main.BOARD_COLUMNS), 0)
    for column, count in conn.execute(text("select today->>'board_column_id',count(*) from app.customer_projection "
                                           "where " + where + " group by today->>'board_column_id'"), params):
        if column:
            meta["board_counts"][column] = count
    entity_where = "generation=:generation and today is not null" + (" and entity=:entity" if filters.get("entity") else "")
    meta["officer_totals"] = dict.fromkeys(meta.get("officer_totals", {}), 0)
    for officer, count in conn.execute(text("select officer,count(*) from app.customer_projection where " + entity_where + " group by officer"), params):
        if officer:
            meta["officer_totals"][officer] = count
    meta["unassigned_total"] = conn.execute(text("select count(*) from app.customer_projection where " + entity_where + " and coalesce(officer,'')=''"), params).scalar_one()
    summaries = {}
    officer_stats = {row[0]: row[1:] for row in conn.execute(text(
        "select coalesce(officer,'*'),coalesce(sum(ptp_today),0),coalesce(sum(ptp_amount),0),"
        "coalesce(sum(unreachable_today),0) from app.customer_projection where generation=:generation group by officer"),
        {"generation": pointer["generation"]})}
    for officer, count, worked in conn.execute(text("select coalesce(officer,'*'),count(*),count(*) filter(where worked) "
                                                   "from app.customer_projection where " + where + " group by officer"), params):
        stats = officer_stats.get(officer, (0, Decimal(0), 0))
        summaries[officer] = {"total": count, "worked": worked, "not_yet": count-worked,
                              "ptp_count": int(stats[0]), "ptp_amount": str(stats[1].quantize(Decimal('.01'))),
                              "unreachable": int(stats[2])}
    stats = conn.execute(text("select coalesce(sum(ptp_today),0),coalesce(sum(ptp_amount),0),coalesce(sum(unreachable_today),0) "
                              "from app.customer_projection where generation=:generation"), {"generation": pointer["generation"]}).one()
    summaries["*"] = {"total": aggregate[0], "worked": aggregate[1], "not_yet": aggregate[0]-aggregate[1],
                       "ptp_count": int(stats[0]), "ptp_amount": str(stats[1].quantize(Decimal('.01'))), "unreachable": int(stats[2])}
    meta["daily_summary"] = summaries
    money_order = "overdue desc,coalesce(dpd,0) desc" if sort == "arrears" else "coalesce(dpd,0) desc,overdue desc"
    next_up = conn.execute(text("select customer_uid from app.customer_projection where " + where +
                               " and contact_open order by (tier='ROUTINE'),tier_rank," + money_order +
                               ',display_name collate "C",customer_uid collate "C" limit 1'), params).scalar()
    meta["next_up"] = next_up
    # Reminder delivery remains a governed batch action. Match the full selected
    # desk without forcing the browser to hydrate every row.
    matching_uids = set(conn.execute(text("select customer_uid from app.customer_projection where " + where), params).scalars())
    meta["reminder_batch"] = [entry for entry in pointer["metadata"]["today"]["meta"].get("reminder_batch", [])
                             if entry["customer_uid"] in matching_uids]
    note = bool(aggregate[4]) and not aggregate[5]
    meta["ptp_history_note_th"] = domain.PTP_HISTORY_NOTE_TH if note else None
    meta["ptp_history_note_en"] = domain.PTP_HISTORY_NOTE_EN if note else None
    meta["answers_waiting_elsewhere_note_th"] = "รวมอยู่ในขั้นอื่น %d" % meta["answers_waiting_elsewhere"] if meta["answers_waiting_elsewhere"] else None
    meta["answers_waiting_elsewhere_note_en"] = "%d counted in other tiers" % meta["answers_waiting_elsewhere"] if meta["answers_waiting_elsewhere"] else None
    result = {"run": {**pointer["metadata"]["today"]["run"], "officer": filters.get("officer")}, "items": rows, "meta": meta}
    if limit:
        result["page"] = page
    return result
