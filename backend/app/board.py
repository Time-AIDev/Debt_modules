"""Which board column a case belongs in, and what a request to change it means.

Spec: docs/archive/superpowers/specs/2026-09-09-board-derived-columns-design.md

One rule, one place. `fixtures.py` used to own a seed-time copy of this and wrote
the answer onto the customer; that pass is gone and the column is computed where it
is served. `docs/design/round-4/board/B-system.md` §1.7 forbade exactly this and is
superseded — see spec §9f for the three reasons and how each is answered.
"""
from datetime import date

CALL_TODAY = "col_01H8X"
AWAITING_PAYMENT = "col_01H8Y"
PROMISE_MADE = "col_01H8Z"
ESCALATE = "col_01H90"

DERIVED_COLUMNS = (CALL_TODAY, AWAITING_PAYMENT, PROMISE_MADE, ESCALATE)

# How bad the case is — NOT the column's served `order` (1..4), which is the desk's
# reading order and stays as it is. Under the rule below `Awaiting payment` is the
# HEALTHY column (nothing overdue) and `Call today` the overdue one, so ranking on
# `order` would make a move into health look like progress. That is precisely the
# move this ranking exists to send to a Manager.
SEVERITY = {AWAITING_PAYMENT: 0, PROMISE_MADE: 1, CALL_TODAY: 2, ESCALATE: 3}


class BoardError(Exception):
    """Carries a `code` the router turns into an RFC 9457 problem."""

    def __init__(self, code, **extensions):
        super().__init__(code)
        self.code = code
        self.extensions = extensions


def derive(*, npl_confirmed, npl_type, recovery_stage, dc_status,
           open_ptp_promise_date, dpd, business_date):
    """The column a case's own data implies. First match wins, so the branches are
    exhaustive and exclusive and Σ columns == row count holds by construction.

    Two inputs are excluded BY NAME and must stay excluded:

    * `manager_review_open` — spec §9g. It is circular here: a backward move raises a
      review, the review would push the card to Escalate, the derived value would
      change, and §6 would expire the override the Manager had just approved. The card
      would refuse to hold the placement it was granted.
    * `aging_bucket` — spec §9f. Its codes are defined by the active band set and
      `PUT /v1/config {band_set_code}` rewrites five of them into seven different ones,
      so a tester switching band sets would reshuffle the whole board. The NPL fact is
      read from the contract's own status instead, which does not move.
    """
    if (npl_confirmed or npl_type
            or recovery_stage in ("ESCALATE", "RECOVERY")
            or dc_status == "RETRIEVE_ASSET"):
        return ESCALATE
    # A promise holds the card only while it is still live. The day after the promised
    # date this comparison fails and the card leaves on the next read — no job runs.
    if open_ptp_promise_date is not None and open_ptp_promise_date >= business_date:
        return PROMISE_MADE
    # `dpd` is the money engine's own answer, computed from the schedule's due dates.
    # `None` means the engine could not price the contract: not a licence to call.
    if dpd is not None and dpd > 0:
        return CALL_TODAY
    return AWAITING_PAYMENT


def direction_of(requested, current):
    """FORWARD only when the officer asks for a column the data ranks as WORSE than
    where the case already sits — they know something the data has not caught up to.
    Everything else is a claim that the case is better than the record says, which is
    a Manager's call."""
    if requested == current:
        raise BoardError("board_move_same_column", column_id=current)
    # An Owner may add a column beyond the derived four. It has no rank to compare, so
    # it is the largest claim an officer can make and a Manager signs for it. Indexing
    # SEVERITY here instead would raise KeyError on a live request.
    if requested not in SEVERITY or current not in SEVERITY:
        return "BACKWARD"
    return "FORWARD" if SEVERITY[requested] > SEVERITY[current] else "BACKWARD"


def cause_of(previous, current, *, open_ptp_promise_date, business_date):
    """Why a card moved on its own. A function of the transition and the CURRENT facts
    — the previous inputs are not stored, so nothing here is inferred from them."""
    if (previous == PROMISE_MADE and current != PROMISE_MADE
            and open_ptp_promise_date is not None
            and open_ptp_promise_date < business_date):
        return "PTP_DATE_PASSED"
    if previous == AWAITING_PAYMENT and current == CALL_TODAY:
        return "ARREARS_OPENED"
    if previous == CALL_TODAY and current == AWAITING_PAYMENT:
        return "ARREARS_CLEARED"
    # An NPL confirmation, a DC status, a recovery move. A real value, not a fallback
    # standing in for a branch nobody wrote.
    return "CASE_CHANGED"


def facts_for(customer, dpd, case_state=None, journey_state=None):
    """Gather `derive`'s inputs from the live per-session stores.

    `dpd` is passed in rather than computed: both call sites already have it from
    `_customer_aggregate`, and taking it as an argument keeps this module free of an
    import back into `main`.
    """
    from . import cases as cases_domain
    from . import journey as journey_domain
    from .config import settings

    cs = case_state or cases_domain.for_current()
    js = journey_state or journey_domain.for_current()
    case = cs.cases.get(customer.uid) or {}
    ptp_uid = case.get("open_ptp_uid")
    ptp = cs.ptps.get(ptp_uid) if ptp_uid else None
    promise = None
    if ptp and ptp.get("promise_date"):
        promise = date.fromisoformat(ptp["promise_date"])
    # Ruling 43: the session-scoped read. Never `contract.status` directly — a session's
    # NPL classification must not be visible to a session that never made it.
    statuses = {cases_domain.contract_field_of(k, "status") for k in customer.contracts}
    return {
        "npl_confirmed": "NON_PERFORMING" in statuses,
        "npl_type": case.get("npl_type"),
        # Overlay-aware. `main.py` serves the raw `customer.recovery_stage` on its own
        # separate line of the payload (spec §9c, left as found), but the DERIVATION
        # must see a session's recovery move or the board would ignore it on one of the
        # two paths and not the other.
        "recovery_stage": js.recovery_overlay.get(customer.uid, customer.recovery_stage),
        "dc_status": case.get("dc_status"),
        "open_ptp_promise_date": promise,
        "dpd": dpd,
        "business_date": settings.business_date,
    }


def serve(customer, dpd, case_state=None, journey_state=None):
    """Everything the payload needs about this card's placement, in one call.

    `column_for` below answers only "which column" and is what the router uses for the
    direction check. This is what the two serving endpoints spread into the item: the
    column PLUS the three facts that explain it, because a card that moved on its own
    or is held pending a Manager has to say so on the card itself.
    """
    from . import cases as cases_domain
    from . import journey as journey_domain

    js = journey_state or journey_domain.for_current()
    cs = case_state or cases_domain.for_current()
    # Only the move THIS call produced is news. Scanning the whole event list for the
    # customer's most recent BOARD_AUTO_MOVED would re-announce an old move whenever its
    # destination happened to match today's column — so the window is the events this
    # call appended, and nothing else.
    before = len(cs.events)
    column = column_for(customer, dpd, case_state=cs, journey_state=js)
    fresh = next((e for e in cs.events[before:]
                  if e["kind"] == "BOARD_AUTO_MOVED" and e["customer_uid"] == customer.uid),
                 None)
    override = js.board_overrides.get(customer.uid)
    pending = js.board_pending.get(customer.uid)
    return {
        "board_column_id": column,
        "auto_moved": fresh is not None,
        "auto_moved_cause": fresh["cause"] if fresh else None,
        "board_override": bool(override),
        "board_pending_review_uid": pending["review_uid"] if pending else None,
    }


def column_for(customer, dpd, case_state=None, journey_state=None):
    """The column to serve, and the only place that answers the question.

    An approved override wins over the derivation, but only while the derivation it
    departed from still holds. The moment the data moves — a payment clears, a promise
    lapses, an NPL is confirmed — the override is void and the data wins. Without that
    clause one approved override would pin a card against reality for ever.
    """
    from . import cases as cases_domain
    from . import journey as journey_domain
    from .config import settings

    js = journey_state or journey_domain.for_current()
    # BOARD_AUTO_MOVED and BOARD_OVERRIDE_EXPIRED land in THE audit trail — the one
    # PTP_BROKEN, CASE_OPENED, NPL_TYPE_SET and POWER_APPROVED already use. A second
    # event log for the same case would be the second pattern for the same job, in the
    # very change that deletes a duplicate placement store for that reason.
    cs = case_state or cases_domain.for_current()
    facts = facts_for(customer, dpd, case_state=cs, journey_state=js)
    derived = derive(**facts)

    override = js.board_overrides.get(customer.uid)
    if override is not None and override["derived_at_grant"] != derived:
        del js.board_overrides[customer.uid]
        cs.events.append({
            "kind": "BOARD_OVERRIDE_EXPIRED", "customer_uid": customer.uid,
            "was_column_id": override["to_column_id"], "now_column_id": derived,
            "granted_against": override["derived_at_grant"],
            "on": str(settings.business_date),
        })
        override = None

    served = override["to_column_id"] if override else derived

    previous = js.board_last_served.get(customer.uid)
    if previous is not None and previous != served and override is None:
        cs.events.append({
            "kind": "BOARD_AUTO_MOVED", "customer_uid": customer.uid,
            "from_column_id": previous, "to_column_id": served,
            "cause": cause_of(previous, served,
                              open_ptp_promise_date=facts["open_ptp_promise_date"],
                              business_date=settings.business_date),
            "on": str(settings.business_date),
        })
    js.board_last_served[customer.uid] = served
    return served
