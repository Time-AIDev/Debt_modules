"""The calendar's read model — vault note 10 §3 WP6 (F16).

One dated list drawn from the stores that already hold dates. Nothing here is a new
fact: each serializer reads ONE store, names it in `source`, and places the item on the
store's own date. A store that holds no date for an open record (a journey service
issue) is counted in not_dated, never given a date.

Two registers of promises and reviews exist (cases.CaseState and journey.JourneyState,
design §7). Both are read and every item names which. A journey promise the case store
already mirrors (cases._seed, source "JOURNEY") is served once, from the case store.
"""
from datetime import date, datetime, timedelta

from . import journey
from .config import settings

# The largest range one request may serve. 2026-09-21: 42 -> 366 so the screen's
# year view (Jan 1 - Dec 31, twelve months) is ONE request; the default grid the
# screen opens on stays six weeks (`default_range` below). 366 covers every year,
# leap included.
MAX_SPAN_DAYS = 366
# The grid the screen opens on when no range is asked for: six weeks around the
# business date. Separate from the cap above since 2026-09-21 — the cap grew for the
# year view, the opening grid did not.
DEFAULT_GRID_DAYS = 42
KINDS = ("PTP_DUE", "NEXT_ACTION", "REVIEW_SLA", "ISSUE_DEADLINE", "NPL_BUYBACK",
         "RESTRUCTURE", "SETTLEMENT", "REMINDER_BATCH", "NOTICE")
KIND_RANK = {kind: rank for rank, kind in enumerate(KINDS)}
# SEND_REMINDER is served as a REMINDER_BATCH; NONE_CLOSED is not an action at all.
NEXT_ACTION_EXCLUDED = ("SEND_REMINDER", "NONE_CLOSED")
# Kinds the officer filter does not scope: a batch is scoped by the reminders call
# itself, and a notice belongs to its owner, not to a case's officer.
UNSCOPED_KINDS = ("REMINDER_BATCH", "NOTICE")
NOBODY = {"customer_uid": None, "display_name": None, "volt_id": None, "officer_uid": None}


def _day(value):
    """A store's own date as yyyy-mm-dd, or None when it is not a date this can read."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _within(on, start, end):
    return bool(on) and start.isoformat() <= on <= end.isoformat()


def _who(customer_uid, cs):
    if not customer_uid:
        return dict(NOBODY)
    customer = journey.customer_by_uid(customer_uid)
    case = cs.cases.get(customer_uid)
    return {"customer_uid": customer_uid,
            "display_name": getattr(customer, "display_name", None),
            "volt_id": getattr(customer, "volt_id", None),
            "officer_uid": case["officer_uid"] if case else None}


def _item(uid, kind, source, on, who, overdue, time=None, movable=False, facts=None, moved_from=None):
    row = {"uid": uid, "kind": kind, "source": source, "on": on, "time": time,
           "overdue": bool(overdue), "movable": movable, "facts": facts or {},
           # F07 / feedback-r2 TASK-103: the item's own urgency rank, from KIND_RANK.
           # PTP_DUE is 0, so the served order and the screen's colour agree.
           "priority": KIND_RANK[kind],
           "moved": bool(moved_from), "moved_from": moved_from}
    row.update(who)
    return row


def default_range(bd):
    first = bd.replace(day=1)
    start = first - timedelta(days=first.weekday())
    return start, start + timedelta(days=DEFAULT_GRID_DAYS - 1)


def next_actions(cs, start, end, bd):
    """cases.CaseState.cases — the one next action every case carries (REQ-COL-070)."""
    out = []
    for customer_uid, case in cs.cases.items():
        on = _day(case.get("next_action_on"))
        if case.get("next_action") in (None,) + NEXT_ACTION_EXCLUDED or not _within(on, start, end):
            continue
        out.append(_item("na:%s" % customer_uid, "NEXT_ACTION", "cases.next_action", on, _who(customer_uid, cs),
                         on < str(bd), movable=True,
                         facts={"action": case["next_action"], "set_by": case.get("next_action_set_by")},
                         moved_from=case.get("next_action_moved_from")))
    return out


def case_ptps(cs, start, end, bd):
    """cases.CaseState.ptps — open promises, on their promise date. Also collects the
    JOURNEY-sourced promise dates journey_ptps needs to skip a promise this store
    already mirrors, so cs.ptps is walked once for both jobs (fold-in, C2b)."""
    out, mirrored = [], set()
    for ptp in cs.ptps.values():
        if ptp.get("source") == "JOURNEY":
            mirrored.add((ptp["customer_uid"], ptp.get("promise_date")))
        on = _day(ptp.get("promise_date"))
        if ptp.get("status") != "OPEN" or not _within(on, start, end):
            continue
        out.append(_item("ptp:%s" % ptp["uid"], "PTP_DUE", "cases.ptp", on, _who(ptp["customer_uid"], cs),
                         on < str(bd), facts={"ptp_uid": ptp["uid"], "amount": ptp.get("promised_amount"),
                                              "origin": ptp.get("source")}))
    return out, mirrored


def journey_ptps(js, cs, start, end, bd, mirrored):
    """journey.JourneyState.ptps — the second register. A promise the case store mirrors
    (same customer, same date, source JOURNEY) is skipped; the count of those comes
    back. `mirrored` is case_ptps' own walk of cs.ptps, computed once and passed in
    rather than re-walked here (fold-in, C2b)."""
    out, skipped = [], 0
    for ptp in js.ptps.values():
        on = _day(ptp.get("promise_date"))
        if ptp.get("status") != "OPEN" or not _within(on, start, end):
            continue
        if (ptp["customer_uid"], on) in mirrored:
            skipped += 1
            continue
        out.append(_item("jptp:%s" % ptp["uid"], "PTP_DUE", "journey.ptp", on, _who(ptp["customer_uid"], cs),
                         on < str(bd), facts={"ptp_uid": ptp["uid"], "amount": ptp.get("promised_amount"),
                                              "origin": ptp.get("kind")}))
    return out, skipped


def reminder_batches(rows, start, end, bd, batch_label):
    """GET /v1/today/reminders' own rows (the block WP7 moved off Today), grouped into one
    batch per day and label. The label is that endpoint's own, never re-derived here."""
    groups = {}
    for r in rows:
        on = _day(r.get("due_on"))
        if not _within(on, start, end):
            continue
        groups.setdefault((on, r["kind"]), []).append(
            {"customer_uid": r["customer_uid"], "display_name": r.get("display_name"), "volt_id": r.get("volt_id"),
             "officer_uid": r.get("officer_uid"), "overdue": bool(r.get("overdue"))})
    return [_item("rb:%s:%s" % (on, label), "REMINDER_BATCH", "today.reminders", on, dict(NOBODY), on < str(bd),
                  facts={"label": label, "count": len(customers), "customers": customers, "batch_label": batch_label})
            for (on, label), customers in sorted(groups.items())]


def _sla_days():
    return -(-int(settings.review_sla_hours) // 24)       # whole days, rounded up


def case_reviews(cs, start, end, bd):
    """cases.CaseState.reviews — an open review is due review_sla_hours after
    raised_at_time, the clock GET /v1/reviews measures age_hours by. A review with no
    readable time falls back to its raised_at day, and says precision "day"."""
    hours = int(settings.review_sla_hours)
    out = []
    for review in cs.reviews.values():
        if review.get("status") != "OPEN":
            continue
        try:
            due_at = datetime.fromisoformat(review["raised_at_time"]) + timedelta(hours=hours)
            on, time, precision = due_at.date().isoformat(), due_at.strftime("%H:%M"), "hour"
        except (KeyError, TypeError, ValueError):
            raised = _day(review.get("raised_at"))
            if raised is None:
                continue
            on = (date.fromisoformat(raised) + timedelta(days=_sla_days())).isoformat()
            time, precision = None, "day"
        if not _within(on, start, end):
            continue
        out.append(_item("rv:%s" % review["uid"], "REVIEW_SLA", "cases.review", on, _who(review["customer_uid"], cs),
                         on < str(bd), time=time,
                         facts={"review_uid": review["uid"], "reason": review.get("reason"),
                                "raised_at": review.get("raised_at"), "sla_hours": hours, "precision": precision}))
    return out


def journey_reviews(js, cs, start, end, bd):
    """journey.JourneyState.reviews — the manager-review queue stores a day, not a time,
    so the same review_sla_hours lands on a day: opened_on + the SLA in whole days."""
    out = []
    for review in js.reviews.values():
        opened = _day(review.get("opened_on"))
        if review.get("status") != "OPEN" or opened is None:
            continue
        on = (date.fromisoformat(opened) + timedelta(days=_sla_days())).isoformat()
        if not _within(on, start, end):
            continue
        out.append(_item("mrv:%s" % review["uid"], "REVIEW_SLA", "journey.review", on,
                         _who(review["customer_uid"], cs), on < str(bd),
                         facts={"review_uid": review["uid"], "reason": review.get("reason"), "raised_at": opened,
                                "sla_hours": int(settings.review_sla_hours), "precision": "day"}))
    return out


def case_issues(cs, start, end, bd):
    """cases.CaseState.issues — an open ticket on its OWN deadline (J4-07's field). Also
    counts the open issues with no dated deadline — not_dated's own job for this store —
    so cs.issues is walked once for both (fold-in, C2b)."""
    out, undated = [], 0
    for issue in cs.issues.values():
        if issue.get("status") != "OPEN":
            continue
        on = _day(issue.get("deadline"))
        if on is None:
            undated += 1
            continue
        if not _within(on, start, end):
            continue
        out.append(_item("iss:%s" % issue["uid"], "ISSUE_DEADLINE", "cases.issue", on, _who(issue["customer_uid"], cs),
                         on < str(bd), facts={"issue_uid": issue["uid"], "responsible_team": issue.get("responsible_team"),
                                              "ticket_ref": issue.get("ticket_ref"), "ticket_url": issue.get("ticket_url"),
                                              "summary": issue.get("summary")}))
    return out, undated


def restructures(js, cs, start, end, bd):
    """journey.JourneyState.restructures — a proposal on the day it was proposed (while it
    is still PROPOSED), and the first due date of the new schedule it names."""
    out = []
    for rst in js.restructures.values():
        who = _who((js.cases.get(rst.get("case_uid")) or {}).get("customer_uid"), cs)
        facts = {"restructure_uid": rst["uid"], "status": rst.get("status"), "new_term_months": rst.get("new_term_months")}
        proposed = _day(rst.get("proposed_on"))
        if rst.get("status") == "PROPOSED" and _within(proposed, start, end):
            out.append(_item("rst:%s:proposed" % rst["uid"], "RESTRUCTURE", "journey.restructure", proposed, who, False,
                             facts=dict(facts, phase="PROPOSED")))
        first_due = _day(rst.get("new_first_due"))
        if rst.get("status") in ("PROPOSED", "ACTIVE") and _within(first_due, start, end):
            out.append(_item("rst:%s:first-due" % rst["uid"], "RESTRUCTURE", "journey.restructure", first_due, who, False,
                             facts=dict(facts, phase="FIRST_DUE")))
    return out


def settlements(js, cs, start, end, bd):
    """journey.JourneyState — a cash settlement plan on the day its ladder recorded the
    offer (stage SETTLEMENT_PLAN_60), and an ACTIVE repayment arrangement on the day it
    opened. Planner's mapping (brief): "settlement" reads the cash-ladder settlement
    stage plus active arrangements — no third store invents a settlement date."""
    out = []
    for cash in js.cash_cases.values():
        if cash.get("stage") != "SETTLEMENT_PLAN_60":
            continue
        entry = next((h for h in reversed(cash.get("stage_history") or []) if h.get("stage") == "SETTLEMENT_PLAN_60"), None)
        on = _day(entry.get("on")) if entry else None
        if not _within(on, start, end):
            continue
        out.append(_item("cash:%s:settlement" % cash["uid"], "SETTLEMENT", "journey.cash_case", on,
                         _who(cash["customer_uid"], cs), False,
                         facts={"phase": "PLAN_OFFERED", "ref_uid": cash["uid"], "by": entry.get("by")}))
    for arrangement in js.arrangements.values():
        on = _day(arrangement.get("opened_on"))
        if arrangement.get("status") != "ACTIVE" or not _within(on, start, end):
            continue
        out.append(_item("arr:%s" % arrangement["uid"], "SETTLEMENT", "journey.arrangement", on,
                         _who(arrangement["customer_uid"], cs), False,
                         facts={"phase": "ARRANGEMENT_OPENED", "ref_uid": arrangement["uid"], "by": None}))
    return out


def npl_buybacks(js, cs, start, end, bd):
    """journey.JourneyState.npl_cases — the executed deed and buy-back payment (day 120,
    journey.execute_assignment). No store holds a buy-back date before it is executed,
    so none is invented. Planner's mapping (brief): "buy-back" reads executed deeds
    only. The amount is 100% of remaining NPV at an undecided discount rate (OQ-31):
    indicative, and served as such."""
    out = []
    for npl in js.npl_cases.values():
        deed = npl.get("assignment") or {}
        on = _day(deed.get("executed_on"))
        if not _within(on, start, end):
            continue
        out.append(_item("npl:%s:buyback" % npl["uid"], "NPL_BUYBACK", "journey.npl_case", on,
                         _who((js.cases.get(npl.get("case_uid")) or {}).get("customer_uid"), cs), False,
                         facts={"npl_uid": npl["uid"], "amount": deed.get("remaining_npv"),
                                "indicative": bool(deed.get("is_indicative", True)), "by": deed.get("by")}))
    return out


def not_dated(cases_undated, js):
    """Open records a store holds with no date the calendar can place — counted, never
    dated. `cases_undated` is case_issues' own walk of cs.issues, computed once and
    passed in rather than re-walked here (fold-in, C2b)."""
    return {
        "cases.issue": cases_undated,
        "journey.issue": sum(1 for i in js.issues.values() if i.get("status") in ("OPEN", "IN_PROGRESS")),
    }


def ordered(items):
    return sorted(items, key=lambda r: (r["on"], r["time"] or "", KIND_RANK[r["kind"]], r["display_name"] or "", r["uid"]))


def count_by(items, key):
    out = {}
    for row in items:
        out[row[key]] = out.get(row[key], 0) + 1
    return out


def count_by_month(items, start, end):
    """Every month the range touches, with its own totals — zero months included, the
    same rule `day_totals` follows so the year view never has to decide that an absent
    month means none. `month` is "YYYY-MM"; `by_kind` answers the per-kind chips."""
    counts = count_by(items, "on")
    kinds = {}
    for row in items:
        bucket = kinds.setdefault(row["on"][:7], {})
        bucket[row["kind"]] = bucket.get(row["kind"], 0) + 1
    out, month = [], start.replace(day=1)
    while month <= end:
        key = month.isoformat()[:7]
        out.append({"month": key, "total": sum(n for on, n in counts.items() if on[:7] == key),
                    "by_kind": kinds.get(key, {})})
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def day_totals(items, start, end):
    """Every day in the range with its served total — zero days included, so the screen
    never has to decide that an absent day means none."""
    counts = count_by(items, "on")
    out, day = [], start
    while day <= end:
        out.append({"on": day.isoformat(), "total": counts.get(day.isoformat(), 0)})
        day += timedelta(days=1)
    return out


def notices(rows, cs, bd):
    """records.notice — the caller's own notices (notices.list_for), never anyone else's."""
    return [_item("ntc:%s" % n["uid"], "NOTICE", "records.notice", n["on"], _who(n.get("customer_uid"), cs), False,
                  time=n.get("time"),
                  facts={"notice_uid": n["uid"], "title": n["title"], "text": n.get("text"),
                         "done": n["done"], "durable": n["durable"]})
            for n in rows]
