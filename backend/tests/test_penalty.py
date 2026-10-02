"""REQ-MNY-017 / REQ-MNY-018 — penalty accrual.

Simple, never compounding, accrued PER INSTALMENT per calendar day.

CF1 IS DECIDED (ruling 87): 0.03 %/day. The two spec rates below — 0.3 %/day (Debt
spec, CRM v6.7) and 0.1 %/day (PAY v1.2), both citing agreement VL0010399 §13.1 — stay
as fixture rates: nothing here hard-codes a rate, every test passes one in, and these
two are what the acceptance examples below were written against.
"""
from datetime import date
from decimal import Decimal

from app.money.models import Instalment
from app.money.penalty import accrue, accrue_range

RATE_DEBT_SPEC = Decimal("0.003")  # CF1 side A — the live book uses this today
RATE_PAY_SPEC = Decimal("0.001")   # CF1 side B
GRACE = 14

FIRST_DUE = date(2026, 10, 1)


def fx_c1_line(paid=Decimal("0")):
    return Instalment(
        due_date=FIRST_DUE,
        category="REGULAR",
        principal_amount=Decimal("4000.00"),
        interest_amount=Decimal("1580.00"),
        fee_amount=Decimal("0.00"),
        paid_principal=paid,
    )


def test_the_acceptance_example_of_req_mny_018():
    """5,580 at 22 days late, grace 14, gives 8 chargeable days and 133.92."""
    row = accrue(fx_c1_line(), accrual_date=date(2026, 10, 23), rate=RATE_DEBT_SPEC, grace_days=GRACE)

    assert row.days_past_due == 22
    assert row.chargeable_days == 8
    assert row.overdue_base_amount == Decimal("5580.00")
    assert row.cumulative_amount == Decimal("133.92")
    assert row.amount == Decimal("16.74")


def test_day_fourteen_is_inside_grace_and_still_writes_an_explainable_zero_row():
    """TC-MNY-054: 2026-10-15 is day 14 — chargeable 0, amount 0.00, row still written."""
    row = accrue(fx_c1_line(), accrual_date=date(2026, 10, 15), rate=RATE_DEBT_SPEC, grace_days=GRACE)

    assert row.days_past_due == 14
    assert row.chargeable_days == 0
    assert row.amount == Decimal("0.00")
    assert row.cumulative_amount == Decimal("0.00")


def test_day_fifteen_is_the_first_chargeable_day():
    """TC-MNY-054: 2026-10-16 is day 15 — chargeable 1, amount 16.74."""
    row = accrue(fx_c1_line(), accrual_date=date(2026, 10, 16), rate=RATE_DEBT_SPEC, grace_days=GRACE)

    assert row.chargeable_days == 1
    assert row.amount == Decimal("16.74")


def test_r6_88_the_spec_150_baht_worked_example_is_now_implemented():
    """Spec §15.2 ex.1: 5,000 x rate x 10 days, counting from day 1. §15.3 said penalty
    started on day 15 and the two contradicted; REQ-MNY-018 noted the 150 figure 'is not
    implemented'. Ruling 88 (Arina, 2026-09-09) closed that contradiction in §15.2's
    favour — grace is 0 and the count starts at the due date.

    At the ruled rate of 0.0003 the same ten days give 15.00, not 150.00: the shape of
    §15.2 is now implemented, at ruling 87's rate rather than the spec's.
    """
    line = Instalment(
        due_date=FIRST_DUE,
        category="REGULAR",
        principal_amount=Decimal("5000.00"),
        interest_amount=Decimal("0.00"),
        fee_amount=Decimal("0.00"),
    )
    row = accrue(line, accrual_date=date(2026, 10, 11), rate=Decimal("0.0003"), grace_days=0)

    assert row.days_past_due == 10
    assert row.chargeable_days == 10
    assert row.cumulative_amount == Decimal("15.00")
    # And at the rate the spec itself wrote, the example reproduces exactly.
    legacy = accrue(line, accrual_date=date(2026, 10, 11), rate=Decimal("0.003"), grace_days=0)
    assert legacy.cumulative_amount == Decimal("150.00")


def test_penalty_is_simple_and_never_compounds():
    """TC-MNY-055: 30 chargeable days on 5,580 is 502.20, each daily row 16.74.

    No day may compute on a base that includes prior penalty.
    """
    # due 2026-10-01 + 44 days = 2026-11-14, so 44 - 14 grace = 30 chargeable days
    row = accrue(fx_c1_line(), accrual_date=date(2026, 11, 14), rate=RATE_DEBT_SPEC, grace_days=GRACE)

    assert row.chargeable_days == 30
    assert row.cumulative_amount == Decimal("502.20")
    assert row.amount == Decimal("16.74")


def test_penalty_never_accrues_on_penalty():
    """The fee portion is stripped from the base (Data_Model.md:4074).

    TC-MNY-053: overdue_base_amount 5,580.00 excludes penalty itself.
    """
    line = Instalment(
        due_date=FIRST_DUE,
        category="REGULAR",
        principal_amount=Decimal("4000.00"),
        interest_amount=Decimal("1580.00"),
        fee_amount=Decimal("133.92"),  # a billed penalty riding on the line
    )
    row = accrue(line, accrual_date=date(2026, 10, 23), rate=RATE_DEBT_SPEC, grace_days=GRACE)

    assert row.overdue_base_amount == Decimal("5580.00")


def test_frozen_days_reduce_penalty_using_the_same_count_as_dpd():
    """TC-COL-067: DPD and penalty use the same frozen day count so they cannot diverge."""
    row = accrue(fx_c1_line(), accrual_date=date(2026, 10, 23), rate=RATE_DEBT_SPEC, grace_days=GRACE, frozen_days=10)

    assert row.days_past_due == 12
    assert row.chargeable_days == 0


def test_cf1_impact_figure_both_sides():
    """REQ-MNY-019 / TC-MNY-058: 100,000 at 30 days past due, grace 14 (16 chargeable).

    0.003 gives 4,800.00 and 0.001 gives 1,600.00 — a 3,200 baht difference on ONE
    instalment. This is the whole reason invoicing stays feature-flagged off.
    """
    line = Instalment(
        due_date=FIRST_DUE,
        category="REGULAR",
        principal_amount=Decimal("100000.00"),
        interest_amount=Decimal("0.00"),
        fee_amount=Decimal("0.00"),
    )
    as_of = date(2026, 10, 31)  # 30 days past due

    assert accrue(line, as_of, RATE_DEBT_SPEC, GRACE).cumulative_amount == Decimal("4800.00")
    assert accrue(line, as_of, RATE_PAY_SPEC, GRACE).cumulative_amount == Decimal("1600.00")


def test_a_settled_line_accrues_nothing():
    """TC-MNY-049: payment in full — 'no further penalty accrues'."""
    line = fx_c1_line(paid=Decimal("5580.00"))
    assert line.outstanding_amount == Decimal("0.00")

    row = accrue(line, accrual_date=date(2026, 10, 23), rate=RATE_DEBT_SPEC, grace_days=GRACE)
    assert row.cumulative_amount == Decimal("0.00")


def test_every_row_snapshots_the_rate_and_carries_the_pending_flag():
    """REQ-MNY-020: the resolved value and the level that answered are both returned.

    Ruling 87 flipped the default to not-indicative (see the r6_87 test below), but
    the flag is not retired — forcing it True at the call site is still honoured, for
    whatever later decision needs to mark a row indicative again.
    """
    row = accrue(fx_c1_line(), accrual_date=date(2026, 10, 23), rate=RATE_DEBT_SPEC,
                 grace_days=GRACE, is_indicative=True)

    assert row.rate == RATE_DEBT_SPEC
    assert row.grace_days == GRACE
    assert row.is_indicative is True


def test_r6_87_penalty_rows_are_no_longer_indicative_but_still_snapshot_their_rate():
    """Ruling 87 closed CF1, and penalty.py's own docstring conditioned `indicative` on
    'until Legal rules'. Legal ruled. The rate snapshot stays — it is what makes an
    Owner-tunable rate safe, because yesterday's rows keep yesterday's rate."""
    row = accrue(fx_c1_line(), accrual_date=date(2026, 10, 23),
                 rate=Decimal("0.0003"), grace_days=0)
    assert row.is_indicative is False
    assert row.rate == Decimal("0.0003")
    assert row.rate_resolution_level == "SYSTEM_DEFAULT"


# --- REQ-MNY-017 as AMENDED by G2 (Amendment v2.4 §1) ---------------------------
# "Where arrears change during the period of lateness, the fee for each day is
# computed on the arrears as they stood on that day, so a fee cannot be recomputed
# by multiplying a final arrears figure by a total number of days."

def test_the_fee_is_a_day_loop_not_one_multiplication():
    """The case where the v1.0 arithmetic and the current rule diverge.

    A 5,580.00 instalment falls due 2026-10-01. Grace 14, so day 15 (2026-10-16) is
    the first chargeable day. On 2026-10-22 a partial payment of 2,580.00 lands and
    arrears drop to 3,000.00.

        2026-10-16 .. 2026-10-21   6 days on 5,580.00  ->  6 x 16.74 = 100.44
        2026-10-22 .. 2026-10-23   2 days on 3,000.00  ->  2 x  9.00 =  18.00
                                                                       ------
                                                                       118.44

    Neither v1.0 shortcut reaches it: final arrears x 8 days = 72.00, and original
    arrears x 8 days = 133.92. Both are wrong the moment arrears move.
    """
    def arrears_on(day):
        return Decimal("3000.00") if day >= date(2026, 10, 22) else Decimal("5580.00")

    total = accrue_range(
        due_date=FIRST_DUE,
        arrears_on=arrears_on,
        through=date(2026, 10, 23),
        rate=RATE_DEBT_SPEC,
        grace_days=GRACE,
    )

    assert total.cumulative_amount == Decimal("118.44")
    assert total.cumulative_amount != Decimal("133.92")  # the v1.0 multiplication
    assert total.cumulative_amount != Decimal("72.00")   # final-arrears x days
    assert len(total.days) == 8


def test_the_day_loop_still_reproduces_the_v1_worked_example_on_constant_arrears():
    """133.92 is still right when arrears do not move across the window — which is
    why the fixture agreeing proves nothing about the implementation."""
    total = accrue_range(
        due_date=FIRST_DUE,
        arrears_on=lambda day: Decimal("5580.00"),
        through=date(2026, 10, 23),
        rate=RATE_DEBT_SPEC,
        grace_days=GRACE,
    )
    assert total.cumulative_amount == Decimal("133.92")


def test_a_day_under_a_fee_pausing_state_accrues_nothing_and_records_why():
    """REQ-MNY-032 item 4: mark a paused day with THE STATE that paused it, in a
    column distinct from the frozen-day marker. The fee for a paused day is never
    recomputed later, whatever the eventual outcome of the state."""
    total = accrue_range(
        due_date=FIRST_DUE,
        arrears_on=lambda day: Decimal("5580.00"),
        through=date(2026, 10, 23),
        rate=RATE_DEBT_SPEC,
        grace_days=GRACE,
        state_on=lambda day: "PERMIT_HOLD" if day >= date(2026, 10, 20) else None,
    )

    # 2026-10-16..10-19 accrue (4 days), 10-20..10-23 are paused.
    assert total.cumulative_amount == Decimal("66.96")
    paused = [d for d in total.days if d.paused_by_state]
    assert len(paused) == 4
    assert paused[0].paused_by_state == "PERMIT_HOLD"
    assert paused[0].amount == Decimal("0.00")


def test_a_dispute_does_not_pause_the_day_loop():
    """REQ-MNY-033 — the fee continues to accrue during a complaint review."""
    total = accrue_range(
        due_date=FIRST_DUE,
        arrears_on=lambda day: Decimal("5580.00"),
        through=date(2026, 10, 23),
        rate=RATE_DEBT_SPEC,
        grace_days=GRACE,
        state_on=lambda day: "DISPUTE_UNDER_REVIEW",
    )
    assert total.cumulative_amount == Decimal("133.92")


def test_every_fee_total_decomposes_into_accrued_paused_and_reversed():
    """REQ-MNY-032 item 6: a fee total on any screen must break down into fee
    accrued, fee not accrued by reason of a pausing state broken down BY STATE, and
    fee reversed by reason. A single net number fails this."""
    total = accrue_range(
        due_date=FIRST_DUE,
        arrears_on=lambda day: Decimal("5580.00"),
        through=date(2026, 10, 23),
        rate=RATE_DEBT_SPEC,
        grace_days=GRACE,
        state_on=lambda day: "PERMIT_HOLD" if day >= date(2026, 10, 20) else None,
    )
    breakdown = total.decomposition()

    assert breakdown["accrued"] == Decimal("66.96")
    assert breakdown["not_accrued_by_state"]["PERMIT_HOLD"] == Decimal("66.96")
    assert breakdown["reversed"] == Decimal("0.00")
