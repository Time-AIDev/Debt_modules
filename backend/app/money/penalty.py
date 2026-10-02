"""REQ-MNY-017 / REQ-MNY-018 — penalty accrual.

    overdue_base_amount = outstanding_amount - GREATEST(fee_amount - paid_fee, 0)
    days_past_due       = (accrual_date - due_date) - frozen_days - reset_days
    chargeable_days     = GREATEST(days_past_due - grace_days, 0)
    amount              = ROUND(base * rate, 2)                    -- per day
    cumulative_amount   = ROUND(base * rate * chargeable_days, 2)

Simple, never compounding: no day computes on a base that includes prior penalty.
The fee portion is stripped so penalty never accrues on penalty.

CF1 IS DECIDED (ruling 87, Arina 2026-09-09): 0.03 %/day, and penalty invoicing to PEAK
is live. The evidence read 0.3 %/day — agreement VL0010399 §13.1 and three late-fee
lines on IVT-20260700089 — and she ruled 0.03 %/day, which is 10.95 %/yr and inside
§13.2's own ceiling. No rate is hard-coded here; the rate is Owner-tunable and every
row snapshots the rate it used, so a later change never restates history.

NOTE: PEAK still bills 0.3 %/day. Our figures are one tenth of the customer's own tax
invoice until AR moves PEAK's setting.
"""
from bisect import bisect_left
from dataclasses import dataclass
from decimal import Decimal

from .schedule import round_half_up

ZERO = Decimal("0.00")


@dataclass
class PenaltyRow:
    """One row per (instalment, accrual_date). UNIQUE on that pair with
    ON CONFLICT DO NOTHING, so the 03:00 job is idempotent by construction."""

    days_past_due: int
    chargeable_days: int
    overdue_base_amount: Decimal
    amount: Decimal
    cumulative_amount: Decimal
    rate: Decimal
    grace_days: int
    # Snapshotted onto every row so a later rate change never silently restates history.
    rate_resolution_level: str = "SYSTEM_DEFAULT"
    is_indicative: bool = True


def accrue(instalment, accrual_date, rate, grace_days, frozen_days=0, reset_days=0,
           rate_resolution_level="SYSTEM_DEFAULT", is_indicative=False) -> PenaltyRow:
    base = instalment.outstanding_amount - instalment.outstanding_fee
    if base < ZERO:
        base = ZERO

    days_past_due = max((accrual_date - instalment.due_date).days - frozen_days - reset_days, 0)
    chargeable_days = max(days_past_due - grace_days, 0)

    # A zero row is still written inside grace "so the zero is explainable" (TC-MNY-054).
    per_day = round_half_up(base * rate) if chargeable_days > 0 else ZERO
    cumulative = round_half_up(base * rate * Decimal(chargeable_days))

    return PenaltyRow(
        days_past_due=days_past_due,
        chargeable_days=chargeable_days,
        overdue_base_amount=base,
        amount=per_day,
        cumulative_amount=cumulative,
        rate=rate,
        grace_days=grace_days,
        rate_resolution_level=rate_resolution_level,
        is_indicative=is_indicative,
    )


# ---------------------------------------------------------------------------
# REQ-MNY-017 as AMENDED by G2 (Amendment v2.4 §1).
#
#   "The fee shall accrue on arrears only ... Where arrears change during the
#    period of lateness, the fee for each day is computed on the arrears as they
#    stood on that day, so a fee cannot be recomputed by multiplying a final
#    arrears figure by a total number of days."
#
# `accrue()` above is the v1.0 shape and is kept only because its acceptance
# examples are still cited. It is correct ONLY on a constant-arrears window. Use
# accrue_range() for anything real: the moment a second instalment falls due or a
# partial payment lands mid-window, the multiplication and the rule diverge.
# ---------------------------------------------------------------------------

from datetime import timedelta  # noqa: E402

from .fee_states import stops_fee  # noqa: E402


@dataclass
class DayAccrual:
    accrual_date: object
    arrears: Decimal
    amount: Decimal
    paused_by_state: str = None
    # What this day WOULD have accrued but for the pause. REQ-MNY-032 item 6 needs
    # it to decompose a fee total into accrued / not-accrued-by-state / reversed.
    would_have_accrued: Decimal = ZERO


@dataclass
class AccrualPeriod:
    days: list
    cumulative_amount: Decimal
    rate: Decimal
    grace_days: int
    reversed_amount: Decimal = ZERO
    is_indicative: bool = True

    def decomposition(self):
        """A single net number fails REQ-MNY-032 item 6."""
        by_state = {}
        for day in self.days:
            if day.paused_by_state:
                by_state[day.paused_by_state] = (
                    by_state.get(day.paused_by_state, ZERO) + day.would_have_accrued
                )
        return {
            "accrued": self.cumulative_amount,
            "not_accrued_by_state": by_state,
            "reversed": self.reversed_amount,
        }


def accrue_range(due_date, arrears_on, through, rate, grace_days,
                 state_on=None, reversed_amount=ZERO, is_indicative=True) -> AccrualPeriod:
    """Walk one calendar day at a time from the first chargeable day to `through`.

    arrears_on(day) -> Decimal: the arrears as they stood on that day.
    state_on(day)   -> str|None: the governed fee state in force on that day.
    """
    first_chargeable = due_date + timedelta(days=grace_days + 1)
    days = []
    cumulative = ZERO

    day = first_chargeable
    while day <= through:
        arrears = arrears_on(day)
        would_accrue = round_half_up(arrears * rate) if arrears > ZERO else ZERO

        state = state_on(day) if state_on else None
        # Read the governed table. Never derive this from a hold type.
        paused = bool(state) and stops_fee(state)

        if paused:
            # "The fee shall not be recomputed for a paused day at any later time,
            # whatever the eventual outcome of the state."
            days.append(DayAccrual(day, arrears, ZERO, state, would_accrue))
        else:
            days.append(DayAccrual(day, arrears, would_accrue, None, would_accrue))
            cumulative += would_accrue

        day += timedelta(days=1)

    return AccrualPeriod(
        days=days,
        cumulative_amount=cumulative,
        rate=rate,
        grace_days=grace_days,
        reversed_amount=reversed_amount,
        is_indicative=is_indicative,
    )


def chargeable_arrears_on(instalments, day, grace_days):
    """The fee base for one day.

    The fee accrues on "the sum of instalments that are overdue on that day" — but
    grace is a property of EACH INSTALMENT, 14 calendar days from ITS OWN due date.
    So an instalment that fell due yesterday is in arrears and is not yet chargeable,
    and this function is the only place that distinction is made.

    Ignoring it is invisible on a single-instalment fixture and overcharges every real
    contract: on FX-ARR-2 it bills an extra 368.28 by charging the second instalment
    through its own grace period.

    Only REGULAR lines count. Penalty never accrues on penalty.
    """
    first_chargeable_offset = timedelta(days=grace_days)
    return sum(
        (
            i.outstanding_amount
            for i in instalments
            if i.is_active_regular
            and i.due_date + first_chargeable_offset < day
            and i.outstanding_amount > ZERO
        ),
        ZERO,
    )


def chargeable_arrears_by_day(instalments, grace_days):
    """chargeable_arrears_on for every day of one accrual walk, reading the schedule once.

    Each chargeable instalment joins the fee base on the first day after its own grace,
    so the base is a step function of the day: sort those days once, then a day's base
    is a prefix sum found by bisect. Same Decimal total as chargeable_arrears_on — the
    sum is exact at these magnitudes, so its order does not matter — without rescanning
    the whole schedule for every day (measured at 10x: half of /v1/today's time).
    """
    offset = timedelta(days=grace_days)
    steps = sorted((i.due_date + offset, i.outstanding_amount) for i in instalments
                   if i.is_active_regular and i.outstanding_amount > ZERO)
    starts = [start for start, _ in steps]
    totals = [ZERO]
    for _, amount in steps:
        totals.append(totals[-1] + amount)
    return lambda day: totals[bisect_left(starts, day)]
