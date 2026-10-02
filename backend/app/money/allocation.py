"""REQ-MNY-011 / REQ-MNY-009 — one central allocation rule.

Oldest due instalment first is SETTLED. The component order WITHIN an instalment is
NOT: OD-02 is rank HIGH, owned by Accounting with Legal, from agreement VL0010399.

So this module REFUSES rather than guessing. The illustration in the requirement is
the reason: two instalments of 5,580 plus 268 penalty against a payment of 6,000
produce different escalation answers depending on the order. Guessing would silently
decide which customer escalates.

Both orders are reachable by configuration and there is NO code branch on the order
value — TC-MNY-021 asserts exactly that.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Tuple

ZERO = Decimal("0.00")

COMPONENTS = ("PRINCIPAL", "INTEREST", "FEE")


class AllocationRulePending(Exception):
    """HTTP 422 allocation_rule_pending. The manual path writes NOTHING.

    The PEAK webhook path behaves differently on purpose: it records the transaction
    with is_allocated false and raises an ACC exception, so the payment is never lost.
    That asymmetry is an engineering rule, not a spec rule (VERIFY, owner Arina with
    Accounting) — callers choose the path, this exception only serves the manual one.
    """

    code = "allocation_rule_pending"

    def __init__(self, message=None):
        super().__init__(
            message
            or (
                "allocation_component_order is not set, so allocation cannot proceed. "
                "Pending decision OD-02 (rank HIGH), owner Accounting with Legal, from "
                "agreement VL0010399 §6.6. The engine refuses rather than guessing "
                "because the component order changes which instalment escalates."
            )
        )


@dataclass
class AllocationRow:
    instalment_index: int
    bucket: str
    aging: str
    amount: Decimal
    rule_step: int
    rule_version: str


@dataclass
class AllocationResult:
    rows: List[AllocationRow] = field(default_factory=list)
    by_bucket: Dict[Tuple[str, str], Decimal] = field(default_factory=dict)
    instalment_status: Dict[int, str] = field(default_factory=dict)
    total_allocated: Decimal = ZERO
    unallocated: Decimal = ZERO
    rule_version: str = "v1"


def allocate(amount, instalments, effective_date, component_order, rule_version="v1") -> AllocationResult:
    if not component_order:
        raise AllocationRulePending()

    unknown = [c for c in component_order if c not in COMPONENTS]
    if unknown:
        raise ValueError("unknown allocation component(s): %s" % unknown)

    result = AllocationResult(rule_version=rule_version)
    remaining = amount

    # Oldest due instalment first — the settled half of REQ-MNY-011.
    order = sorted(range(len(instalments)), key=lambda idx: instalments[idx].due_date)

    outstanding = {
        idx: {
            "PRINCIPAL": instalments[idx].outstanding_principal,
            "INTEREST": instalments[idx].outstanding_interest,
            "FEE": instalments[idx].outstanding_fee,
        }
        for idx in order
    }

    for idx in order:
        line = instalments[idx]
        # Aging follows the transaction's EFFECTIVE date, not today — back-dating a
        # receipt legitimately moves money between the current and overdue columns.
        aging = "OVERDUE" if line.due_date < effective_date else "CURRENT"

        for step, component in enumerate(component_order, start=1):
            if remaining <= ZERO:
                break
            take = min(remaining, outstanding[idx][component])
            if take <= ZERO:
                continue

            outstanding[idx][component] -= take
            remaining -= take
            result.rows.append(
                AllocationRow(
                    instalment_index=idx,
                    bucket=component,
                    aging=aging,
                    amount=take,
                    rule_step=step,
                    rule_version=rule_version,
                )
            )
            key = (component, aging)
            result.by_bucket[key] = result.by_bucket.get(key, ZERO) + take

    for idx in order:
        left = sum(outstanding[idx].values())
        if left <= ZERO:
            result.instalment_status[idx] = "PAID"
        elif left < instalments[idx].outstanding_amount:
            result.instalment_status[idx] = "PARTIALLY_PAID"
        else:
            result.instalment_status[idx] = "UNPAID"

    result.total_allocated = amount - remaining
    # An overpayment surfaces rather than vanishing: no amount may be untyped.
    result.unallocated = remaining
    return result
