"""REQ-COL-027 — the arrears block, in the fixed order the tests enforce.

The field order is not cosmetic. TC-COL-052: "a response that leads with the next
instalment FAILS the test." An officer must see what is payable today first.

No arithmetic is performed in the API layer or the interface — everything is computed
here, from the daily ledger, so header and drill-down agree to the satang.
"""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

ZERO = Decimal("0.00")


@dataclass
class ArrearsBlock:
    total_arrears_payable_today: Decimal
    cumulative_arrears: Decimal
    closing_balance: Decimal
    arrears_principal: Decimal
    arrears_interest: Decimal
    arrears_fee: Decimal
    overdue_instalment_count: int
    days_past_due: Optional[int]
    aging_bucket: Optional[str]
    # API Surface v2.1 §2.2 — the bucket code alone no longer identifies a band.
    band_set_code: str
    penalty_accrued_unbilled: Decimal
    penalty_billed: Decimal
    penalty_paid: Decimal
    penalty_waived: Decimal
    next_due_date: Optional[date]
    next_installment_amount: Optional[Decimal]
    full_payoff_amount: Decimal
    basis_ledger_date: date

    def to_ordered_dict(self):
        """REQ-COL-027's order, literally."""
        return OrderedDict(
            [
                ("total_arrears_payable_today", self.total_arrears_payable_today),
                ("days_past_due", self.days_past_due),
                ("aging_bucket", self.aging_bucket),
                ("band_set_code", self.band_set_code),
                (
                    "accrued_penalty",
                    OrderedDict(
                        [
                            # Four separate figures, never netted into one (TC-COL-053).
                            ("accrued_unbilled", self.penalty_accrued_unbilled),
                            ("billed", self.penalty_billed),
                            ("paid", self.penalty_paid),
                            ("waived", self.penalty_waived),
                            (
                                "composition",
                                OrderedDict(
                                    [
                                        ("principal", self.arrears_principal),
                                        ("interest", self.arrears_interest),
                                        ("fee", self.arrears_fee),
                                    ]
                                ),
                            ),
                        ]
                    ),
                ),
                ("next_due_date", self.next_due_date),
                ("next_installment_amount", self.next_installment_amount),
                ("full_payoff_amount", self.full_payoff_amount),
                ("outstanding_balance", self.closing_balance),
                ("basis_ledger_date", self.basis_ledger_date),
            ]
        )


def arrears_block(
    instalments,
    ledger_date,
    penalty_accrued_unbilled=ZERO,
    penalty_billed=ZERO,
    penalty_paid=ZERO,
    penalty_waived=ZERO,
    days_past_due=None,
    aging_bucket=None,
    band_set_code="OPERATIONAL",
):
    # closing_balance — the `bal` CTE. REGULAR lines on the ACTIVE schedule,
    # due or not yet due.
    closing_balance = sum(
        (i.outstanding_amount for i in instalments if i.is_active_regular), ZERO
    )

    # cumulative_arrears — the `arr` CTE. Note there is NO category filter here.
    # That is deliberate and mirrors the SQL: a billed PENALTY or ADJUSTMENT line
    # past due IS counted in arrears while NOT being counted in the balance, so
    # arrears is not a subset of the balance. See test_a_past_due_penalty_line_...
    overdue = [
        i
        for i in instalments
        if i.schedule_status == "ACTIVE" and i.due_date < ledger_date and i.outstanding_amount > 0
    ]
    cumulative_arrears = sum((i.outstanding_amount for i in overdue), ZERO)

    upcoming = sorted(
        (i for i in instalments if i.is_active_regular and i.due_date >= ledger_date),
        key=lambda i: i.due_date,
    )
    next_line = upcoming[0] if upcoming else None

    return ArrearsBlock(
        total_arrears_payable_today=cumulative_arrears,
        cumulative_arrears=cumulative_arrears,
        closing_balance=closing_balance,
        arrears_principal=sum((i.outstanding_principal for i in overdue), ZERO),
        arrears_interest=sum((i.outstanding_interest for i in overdue), ZERO),
        arrears_fee=sum((i.outstanding_fee for i in overdue), ZERO),
        overdue_instalment_count=len(overdue),
        days_past_due=days_past_due,
        aging_bucket=aging_bucket,
        band_set_code=band_set_code,
        penalty_accrued_unbilled=penalty_accrued_unbilled,
        penalty_billed=penalty_billed,
        penalty_paid=penalty_paid,
        penalty_waived=penalty_waived,
        next_due_date=next_line.due_date if next_line else None,
        next_installment_amount=next_line.total_amount if next_line else None,
        # The FALLBACK payoff, live only because early_settlement_method is unset (OD-03).
        # This is not an early-settlement quote and must not be presented as one.
        full_payoff_amount=closing_balance + penalty_accrued_unbilled,
        basis_ledger_date=ledger_date,
    )
