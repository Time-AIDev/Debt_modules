"""The contract-level fee: which arrears are chargeable on a given day.

The amendment says the fee accrues on "the sum of instalments that are overdue on
that day". Grace, though, is a property of EACH INSTALMENT — "14 calendar days from
the due date". So an instalment that fell due yesterday is in arrears and is NOT yet
chargeable, and the day's base must exclude it.

Getting this wrong is invisible on a single-instalment fixture and wrong on every
real contract, which is exactly the kind of defect that survives a demo.
"""
from datetime import date
from decimal import Decimal

from app.money.models import Instalment
from app.money.penalty import accrue, accrue_range, chargeable_arrears_by_day, chargeable_arrears_on

RATE = Decimal("0.003")
GRACE = 14


def line(due_date):
    return Instalment(
        due_date=due_date,
        category="REGULAR",
        principal_amount=Decimal("4000.00"),
        interest_amount=Decimal("1580.00"),
        fee_amount=Decimal("0.00"),
    )


def fx_arr_2():
    """Two 5,580.00 instalments, due 2026-10-01 and 2026-11-01."""
    return [line(date(2026, 10, 1)), line(date(2026, 11, 1))]


def test_an_instalment_inside_its_own_grace_is_in_arrears_but_not_chargeable():
    lines = fx_arr_2()

    # 2026-11-02: instalment 2 is one day past due, so it is in ARREARS...
    in_arrears = sum(i.outstanding_amount for i in lines if i.due_date < date(2026, 11, 2))
    assert in_arrears == Decimal("11160.00")

    # ...but only instalment 1 has cleared its own 14-day grace.
    assert chargeable_arrears_on(lines, date(2026, 11, 2), GRACE) == Decimal("5580.00")


def test_the_second_instalment_becomes_chargeable_on_its_own_day_fifteen():
    lines = fx_arr_2()

    # 2026-11-15 is day 14 for instalment 2 — still inside grace.
    assert chargeable_arrears_on(lines, date(2026, 11, 15), GRACE) == Decimal("5580.00")
    # 2026-11-16 is its day 15.
    assert chargeable_arrears_on(lines, date(2026, 11, 16), GRACE) == Decimal("11160.00")


def test_the_contract_day_loop_agrees_with_the_per_instalment_engine_to_the_satang():
    """FX-ARR-2 at 2026-11-23. The per-instalment engine gives 652.86 + 133.92 = 786.78
    (TC-MNY-056). The contract-level day loop must reach the same figure, or the two
    presentations of one calculation disagree — which REQ-MNY-011 forbids.

        2026-10-16 .. 2026-11-15   31 days on  5,580.00  ->  518.94
        2026-11-16 .. 2026-11-23    8 days on 11,160.00  ->  267.84
                                                             ------
                                                             786.78
    """
    lines = fx_arr_2()
    as_of = date(2026, 11, 23)

    per_instalment = sum(
        accrue(i, as_of, RATE, GRACE).cumulative_amount for i in lines
    )
    assert per_instalment == Decimal("786.78")

    period = accrue_range(
        due_date=date(2026, 10, 1),
        arrears_on=lambda day: chargeable_arrears_on(lines, day, GRACE),
        through=as_of,
        rate=RATE,
        grace_days=GRACE,
    )
    assert period.cumulative_amount == per_instalment


def test_a_naive_base_that_ignores_per_instalment_grace_overcharges():
    """The bug this module exists to prevent, pinned so it cannot come back.

    Charging on every past-due instalment from the OLDEST instalment's day 15 bills
    the customer for days when the newer instalment was still inside its own grace.
    """
    lines = fx_arr_2()
    as_of = date(2026, 11, 23)

    naive = accrue_range(
        due_date=date(2026, 10, 1),
        arrears_on=lambda day: sum(
            (i.outstanding_amount for i in lines if i.due_date < day), Decimal("0.00")
        ),
        through=as_of,
        rate=RATE,
        grace_days=GRACE,
    )

    assert naive.cumulative_amount == Decimal("1021.14")
    # The second instalment gets charged from 2026-11-02 instead of 2026-11-16 —
    # 14 extra days at 16.74, so the customer is overbilled by 234.36 on one contract.
    assert naive.cumulative_amount - Decimal("786.78") == Decimal("234.36")


def test_a_paid_instalment_drops_out_of_the_chargeable_base():
    lines = fx_arr_2()
    lines[0].paid_principal = Decimal("4000.00")
    lines[0].paid_interest = Decimal("1580.00")

    assert chargeable_arrears_on(lines, date(2026, 11, 16), GRACE) == Decimal("5580.00")


def test_only_regular_lines_drive_the_fee_base():
    """Penalty never accrues on penalty — a billed PENALTY line past due must not
    enlarge the base the fee is charged on."""
    lines = fx_arr_2() + [
        Instalment(
            due_date=date(2026, 10, 5),
            category="PENALTY",
            principal_amount=Decimal("0.00"),
            interest_amount=Decimal("0.00"),
            fee_amount=Decimal("133.92"),
        )
    ]
    assert chargeable_arrears_on(lines, date(2026, 11, 2), GRACE) == Decimal("5580.00")


def test_the_by_day_base_is_the_per_day_sum_on_every_day_to_the_satang():
    """The accrual walk's fast base must equal the one-day sum on EVERY day — same
    value and same exponent — across paid, part-paid, penalty, inactive and same-day
    lines, including the days either side of each instalment's grace edge."""
    import random
    from datetime import timedelta
    rnd = random.Random(20260924)
    for _ in range(200):
        lines = []
        for _ in range(rnd.randint(0, 40)):
            principal = Decimal(rnd.randint(0, 900000)) / 100
            lines.append(Instalment(
                due_date=date(2026, 1, 1) + timedelta(days=rnd.choice([0, 0, 31, 59, 90]) + rnd.randint(0, 400)),
                category=rnd.choice(["REGULAR", "REGULAR", "REGULAR", "PENALTY", "ADJUSTMENT"]),
                principal_amount=principal,
                interest_amount=Decimal(rnd.randint(0, 200000)) / 100,
                paid_principal=rnd.choice([Decimal("0.00"), principal, principal / 2]),
                schedule_status=rnd.choice(["ACTIVE", "ACTIVE", "ACTIVE", "SUPERSEDED"]),
            ))
        grace = rnd.choice([0, 14])
        base = chargeable_arrears_by_day(lines, grace)
        day = date(2025, 12, 1)
        while day <= date(2027, 4, 1):
            expected = chargeable_arrears_on(lines, day, grace)
            got = base(day)
            assert got == expected and str(got) == str(expected), (day, got, expected)
            day += timedelta(days=1)
