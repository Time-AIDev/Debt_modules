"""REQ-MNY-001/002/003 — the flat-rate schedule.

REQ-MNY-002's worked example is a *permanent acceptance test*, not a unit test
(Traceability_Matrix.md:153). It is the first test in this suite for that reason.
"""
from decimal import Decimal

from app.money.schedule import build_schedule


def test_worked_example_of_spec_6_2_produces_5580_per_month():
    """REQ-MNY-002: 240,000 at 7.9% flat over 60 months is 5,580.00 a month."""
    schedule = build_schedule(principal=Decimal("240000"), annual_rate_percent=Decimal("7.9"), term_months=60)

    assert schedule.total_interest == Decimal("94800.00")
    assert schedule.total_amount == Decimal("334800.00")
    assert schedule.installment_amount == Decimal("5580.00")


def test_final_instalment_absorbs_rounding_so_the_sum_is_exact():
    """REQ-MNY-003 / FX-C2: 259,770.00 over 36 does not divide.

    Lines 1-35 at 7,215.83 give 252,554.05; line 36 must be 7,215.95 so the
    schedule sums to 259,770.00 'with no residue' (TC-MNY-003).
    """
    schedule = build_schedule(principal=Decimal("210000"), annual_rate_percent=Decimal("7.9"), term_months=36)

    assert schedule.total_amount == Decimal("259770.00")
    assert schedule.installment_amount == Decimal("7215.83")
    assert schedule.final_installment_amount == Decimal("7215.95")
