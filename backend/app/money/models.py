"""The money row.

`total_amount` and `outstanding_amount` are GENERATED STORED columns in the real
schema (Data_Model.md:1570, 1575) — "neither can drift". They are properties here for
the same reason: nothing may set them independently of their components.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")

# ADR-006: money is append-only. A correction is a new reversing row, never an edit.
CATEGORIES = ("REGULAR", "PENALTY", "ADJUSTMENT")


@dataclass
class Instalment:
    due_date: date
    category: str
    principal_amount: Decimal
    interest_amount: Decimal
    fee_amount: Decimal = ZERO
    paid_principal: Decimal = ZERO
    paid_interest: Decimal = ZERO
    paid_fee: Decimal = ZERO
    schedule_status: str = "ACTIVE"
    # Stamped on every money row because the SPV is expected to move accounting
    # systems while EPC stays (Spec §19.2) — even though PEAK is SPV-only today.
    legal_entity: str = "SPV"

    def __post_init__(self):
        if self.category not in CATEGORIES:
            raise ValueError("category must be one of %s, got %r" % (CATEGORIES, self.category))

    @property
    def total_amount(self) -> Decimal:
        return self.principal_amount + self.interest_amount + self.fee_amount

    @property
    def outstanding_amount(self) -> Decimal:
        return self.total_amount - self.paid_principal - self.paid_interest - self.paid_fee

    @property
    def outstanding_principal(self) -> Decimal:
        return max(self.principal_amount - self.paid_principal, ZERO)

    @property
    def outstanding_interest(self) -> Decimal:
        return max(self.interest_amount - self.paid_interest, ZERO)

    @property
    def outstanding_fee(self) -> Decimal:
        return max(self.fee_amount - self.paid_fee, ZERO)

    @property
    def is_active_regular(self) -> bool:
        return self.schedule_status == "ACTIVE" and self.category == "REGULAR"


@dataclass
class Hold:
    """REQ-COL-039. What a hold freezes depends on its type, and the two effects are
    SEPARATE rules — a permit hold pauses the fee but NOT the clock."""

    hold_type: str
    opened_on: date
    closed_on: date = None
    reason: str = ""
    approved_by: str = None  # the 18 backfilled power restrictions legitimately have none


@dataclass
class Contract:
    uid: str
    status: str
    instalments: list = field(default_factory=list)
    holds: list = field(default_factory=list)
    frozen_days: int = 0
    reset_days: int = 0
