"""REQ-MNY-001/002/003 — the flat-rate repayment schedule.

Flat rate, not declining balance: interest is calculated on the full loan amount
for the full term. ADR-006 §Decision 2 requires Decimal throughout — never float.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

SATANG = Decimal("0.01")


def round_half_up(value: Decimal) -> Decimal:
    """`rounding_rule` defaults to HALF_UP_SATANG (Data_Model.md:1531)."""
    return value.quantize(SATANG, rounding=ROUND_HALF_UP)


@dataclass
class Schedule:
    total_interest: Decimal
    total_amount: Decimal
    installment_amount: Decimal
    # Stored, never recomputed — money.repayment_schedule carries installment_amount
    # and final_installment_amount as separate NOT NULL columns (Data_Model.md:1527).
    final_installment_amount: Decimal


def build_schedule(principal: Decimal, annual_rate_percent: Decimal, term_months: int) -> Schedule:
    # The rate is stored as a PERCENT PER YEAR, not a fraction (Data_Model.md:4500).
    years = Decimal(term_months) / Decimal(12)
    total_interest = round_half_up(principal * (annual_rate_percent / Decimal(100)) * years)
    total_amount = round_half_up(principal + total_interest)
    installment_amount = round_half_up(total_amount / Decimal(term_months))
    # The final line is the balancing figure, so the schedule sums to total_amount
    # exactly with no residue. Accounting must be told it can differ (TEST-CASES-MNY.md:207).
    final_installment_amount = total_amount - installment_amount * Decimal(term_months - 1)

    return Schedule(
        total_interest=total_interest,
        total_amount=total_amount,
        installment_amount=installment_amount,
        final_installment_amount=final_installment_amount,
    )
