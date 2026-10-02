"""The executive overview: KPIs, progress against targets, and what to do next.

Two rules shape everything here.

1. **A KPI without a target shows no progress.** There are no targets anywhere in
   the source data, so a progress bar drawn without one would be inventing the
   denominator — the same defect the discount-rate decision (OQ-31) is open about.
   `target` is None until a person saves one, and `progress_pct` is None with it.

2. **"What to do next" is derived from state, never authored.** Every item below
   is produced because a real count is non-zero, and each carries the route that
   acts on it. A hint nobody can act on is decoration.
"""
from decimal import Decimal


def _sum(rows, field):
    total = Decimal("0.00")
    seen = False
    for row in rows:
        value = row.get(field)
        if value in (None, ""):
            continue
        try:
            total += Decimal(str(value))
            seen = True
        except Exception:
            continue
    return total if seen else None


def apply_criteria(orders, criteria):
    """Narrow the order population. Unknown values narrow to nothing rather than
    silently widening to everything."""
    rows = list(orders)
    population = getattr(criteria, "population", "all_orders")
    if population == "awaiting_approval":
        rows = [r for r in rows if r["order_status"] != "Order - Done"]
    elif population == "approved_this_run":
        rows = [r for r in rows if r["order_status"] == "Order - Done"]
    province = getattr(criteria, "province", None)
    if province:
        rows = [r for r in rows if (r.get("province") or "").lower() == province.lower()]
    order_type = getattr(criteria, "order_type", None)
    if order_type:
        rows = [r for r in rows if (r.get("order_type") or "").lower() == order_type.lower()]
    return rows


# R6-C08, closed round 7. Some KPIs are better SMALLER — arrears at risk, orders
# stuck awaiting approval. `progress_pct` is value/target for every key alike, so
# 79 customers at 30+ days against a target of 50 arrives as `progress_pct: 100`:
# a full bar for a target missed by 58%, which is exactly the confident wrong value
# contract §1a grades ABOVE a visible blank.
#
# The screen had already caught this and kept its own `LOWER_IS_BETTER` set to draw
# those two as a pair with an over/under mark instead of a bar — the right render
# from the wrong place. A direction the interface infers is a rule the interface
# invented; it belongs beside the target, on the wire, where /reports and any later
# client read the same answer. That is what `direction` is.
#
# `progress_pct` itself is unchanged and still capped. It is not the field that was
# wrong — it was never meaningful for these keys in either direction, and `direction`
# is now what says so.
# `arrears_thb` joins the two the screen already knew about. It carries no target
# today, so nothing renders differently — but a field that says "more arrears is
# better progress" is false whether or not anything reads it this week, and the next
# client to read it will not have the screen's constant to protect it.
LOWER_IS_BETTER = ("orders_awaiting", "at_risk_30", "arrears_thb")


def _kpi(key, label, value, unit, group, targets, basis):
    target = targets.get(key)
    progress = None
    if target is not None:
        if target == 0:
            # "Zero customers at risk" is a real target, and it divides by zero.
            # It is met or it is not; there is no partial progress toward none.
            progress = 100 if float(value) == 0 else 0
        else:
            # Capped at 100: a bar past its own track reads as a rendering bug, and
            # the raw value is printed beside it anyway.
            progress = min(100, int(round((float(value) / float(target)) * 100)))
    return {
        "key": key, "label": label, "group": group,
        "value": value, "unit": unit,
        "target": target, "progress_pct": progress,
        # Which way is good. LOWER_IS_BETTER keys must not be drawn as a progress bar:
        # see the note above LOWER_IS_BETTER.
        "direction": "LOWER_IS_BETTER" if key in LOWER_IS_BETTER else "HIGHER_IS_BETTER",
        "basis": basis,
    }


def build(orders, loan_book, collections, criteria):
    targets = dict(getattr(criteria, "targets", {}) or {})
    scoped = apply_criteria(orders, criteria)

    awaiting = [r for r in scoped if r["order_status"] != "Order - Done"]
    approved = [r for r in scoped if r["order_status"] == "Order - Done"]
    leasing_awaiting = [r for r in awaiting
                        if (r.get("order_type") or "").lower() == "leasing"]

    from_sheet = [e for e in loan_book if e.get("origin") == "sheet"]
    approved_here = [e for e in loan_book if e.get("origin") == "approved"]

    kpis = [
        _kpi("orders_awaiting", "Orders awaiting approval", len(awaiting), "count",
             "origination", targets, "Orders in the selected population still at EPC Installation."),
        _kpi("orders_approved", "Approved in this run", len(approved), "count",
             "origination", targets, "Orders a person moved to Order - Done in this run."),
        _kpi("pipeline_monthly_thb", "Monthly value awaiting approval",
             str(_sum(leasing_awaiting, "monthly_rate_incl_vat") or Decimal("0.00")), "thb",
             "origination", targets,
             "Sum of the monthly rate on LEASING orders awaiting approval. Cash orders "
             "are excluded: their figure is a one-off price, not a monthly one."),
        _kpi("leases", "Leases in the book", len(loan_book), "count",
             "book", targets, "Every lease the book holds, both cohorts."),
        _kpi("monthly_revenue_thb", "Monthly lease revenue",
             str(_sum(loan_book, "monthly_incl_vat_thb") or Decimal("0.00")), "thb",
             "book", targets, "Sum of the monthly lease payment incl VAT across the book."),
        _kpi("book_value_usd", "Book value",
             str(_sum(from_sheet, "book_value_usd") or Decimal("0.00")), "usd",
             "book", targets,
             "Sum of current book value across the sheet cohort only. Leases approved "
             "in this run carry no book value, so including them would understate it."),
        _kpi("capacity_kwp", "Installed capacity",
             str(_sum(loan_book, "system_size_kwp") or Decimal("0.00")), "kwp",
             "book", targets, "Sum of system size across the book."),
        _kpi("accounts_in_list", "Accounts on the today list",
             collections["accounts"], "count",
             "collections", targets, "Customers the overnight run put in front of an officer."),
        _kpi("arrears_thb", "Arrears outstanding", collections["arrears"], "thb",
             "collections", targets, "Cumulative arrears across those customers."),
        _kpi("at_risk_30", "Portfolio at risk, 30+ days", collections["at_risk_30"], "count",
             "collections", targets,
             "Customers whose worst DPD is 30 or more. Counted per customer, not per "
             "contract, so one customer with three late contracts counts once."),
    ]

    return {
        "criteria": criteria.to_dict() if hasattr(criteria, "to_dict") else {},
        "scope": {
            "orders_in_scope": len(scoped),
            "orders_total": len(orders),
            "loan_book_from_sheet": len(from_sheet),
            "loan_book_approved_here": len(approved_here),
        },
        "kpis": kpis,
        "next_actions": next_actions(awaiting, collections, criteria),
    }


def next_actions(awaiting, collections, criteria):
    """What a person should do next, in the order it costs to leave undone."""
    actions = []
    if collections["at_risk_30"]:
        actions.append({
            "key": "at_risk", "count": collections["at_risk_30"], "route": "/",
            "label": "customers at 30 or more days past due",
            "why": "These are the accounts a delay costs most on.",
            "tone": "overdue",
        })
    if awaiting:
        actions.append({
            "key": "approve", "count": len(awaiting), "route": "/orders",
            "label": "orders waiting for approval",
            "why": "Each one is an installation that cannot enter the lease book yet.",
            "tone": "pending",
        })
    # REMOVED 2026-09-11, Arina: "remove decision still open from overview."
    # It was served whenever config.PENDING was non-empty — five entries, so on every
    # load — and it linked to `/pending`, a route the 2026-09-02 realignment retired:
    # App.jsx redirects it to /settings. The card named an act, carried a count, and
    # took the reader somewhere that is not a list of open decisions. The decisions
    # themselves are not lost; PENDING still feeds the settings screen that owns them.
    # `open_decisions` went with it — this block was its only reader.
    if not getattr(criteria, "set_by", None):
        # Not an error — the system deliberately has no implicit default. It is an
        # action because only a person can close it.
        actions.append({
            "key": "no_default", "count": None, "route": None,
            "label": "No default view saved",
            "why": "Set the criteria you want and save them, so this screen opens on your population.",
            "tone": "neutral",
        })
    return actions
