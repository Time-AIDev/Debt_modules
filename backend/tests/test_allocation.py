"""REQ-MNY-011 / REQ-MNY-009 — allocation.

Oldest due instalment first is SETTLED. The component order WITHIN an instalment is
OPEN (OD-02, rank HIGH, owner Accounting with Legal). The engine must REFUSE, not guess.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.money.allocation import AllocationRulePending, allocate
from app.money.models import Instalment


def regular(due_date):
    return Instalment(
        due_date=due_date,
        category="REGULAR",
        principal_amount=Decimal("4000.00"),
        interest_amount=Decimal("1580.00"),
        fee_amount=Decimal("0.00"),
    )


def fx_arr_1():
    return [regular(date(2026, 10, 1)), regular(date(2026, 11, 1))]


def test_allocation_refuses_when_the_component_order_is_unset():
    """TC-MNY-026: with allocation_component_order unset the manual path returns
    HTTP 422 allocation_rule_pending and WRITES NOTHING.

    This is the single most important behaviour in this module. Guessing an order
    changes which instalment escalates, and OD-02 is owned by Accounting with Legal.
    """
    with pytest.raises(AllocationRulePending) as exc:
        allocate(Decimal("6000.00"), fx_arr_1(), effective_date=date(2026, 10, 23), component_order=None)

    assert exc.value.code == "allocation_rule_pending"
    # The refusal must name the pending decision AND its owner.
    assert "OD-02" in str(exc.value)
    assert "Accounting" in str(exc.value)


def test_oldest_instalment_first_under_the_default_component_order():
    """TC-MNY-019: FX-ARR-1 with a confirmed 6,000.00 receipt.

    overdue principal 4,000.00 / interest 1,580.00 / fee 0.00; current principal 420.00.
    Instalment 1 becomes PAID, instalment 2 PARTIALLY_PAID.
    """
    result = allocate(
        Decimal("6000.00"),
        fx_arr_1(),
        effective_date=date(2026, 10, 23),
        component_order=("PRINCIPAL", "INTEREST", "FEE"),
    )

    assert result.total_allocated == Decimal("6000.00")
    assert result.by_bucket[("PRINCIPAL", "OVERDUE")] == Decimal("4000.00")
    assert result.by_bucket[("INTEREST", "OVERDUE")] == Decimal("1580.00")
    assert result.by_bucket[("PRINCIPAL", "CURRENT")] == Decimal("420.00")
    assert result.instalment_status[0] == "PAID"
    assert result.instalment_status[1] == "PARTIALLY_PAID"


def test_no_amount_may_be_untyped():
    """REQ-MNY-009: every amount lands in exactly one of six reportable figures."""
    result = allocate(
        Decimal("6000.00"),
        fx_arr_1(),
        effective_date=date(2026, 10, 23),
        component_order=("PRINCIPAL", "INTEREST", "FEE"),
    )

    assert sum(result.by_bucket.values()) == Decimal("6000.00")
    for bucket, aging in result.by_bucket:
        assert bucket in ("PRINCIPAL", "INTEREST", "FEE")
        assert aging in ("CURRENT", "OVERDUE")


def test_aging_is_overdue_when_the_due_date_precedes_the_effective_date():
    """Data_Model.md:1638 — aging is a function of the transaction's effective date,
    not of today. Back-dating a receipt moves money between the two aging columns."""
    result = allocate(
        Decimal("5580.00"),
        fx_arr_1(),
        effective_date=date(2026, 9, 15),  # before the first due date
        component_order=("PRINCIPAL", "INTEREST", "FEE"),
    )

    assert result.by_bucket[("PRINCIPAL", "CURRENT")] == Decimal("4000.00")
    assert ("PRINCIPAL", "OVERDUE") not in result.by_bucket


def test_a_different_component_order_is_reachable_by_configuration_with_no_code_branch():
    """TC-MNY-021: under FEE,PRINCIPAL,INTEREST the fee settles first.

    Both orders must be reachable by configuration. The assertion that matters is that
    the SAME function produces both — no branch on the order value.
    """
    lines = [
        Instalment(
            due_date=date(2026, 10, 1),
            category="REGULAR",
            principal_amount=Decimal("4000.00"),
            interest_amount=Decimal("1580.00"),
            fee_amount=Decimal("267.84"),
        )
    ]
    result = allocate(
        Decimal("1000.00"),
        lines,
        effective_date=date(2026, 10, 23),
        component_order=("FEE", "PRINCIPAL", "INTEREST"),
    )

    assert result.by_bucket[("FEE", "OVERDUE")] == Decimal("267.84")
    assert result.by_bucket[("PRINCIPAL", "OVERDUE")] == Decimal("732.16")


def test_every_allocation_row_records_the_rule_version_and_step():
    """Data_Model.md:1642 — rule_step is 'position in the order applied, for the
    explanation screen'. Historical transactions keep the version they were allocated
    under and are never re-allocated (TC-MNY-021)."""
    result = allocate(
        Decimal("6000.00"),
        fx_arr_1(),
        effective_date=date(2026, 10, 23),
        component_order=("PRINCIPAL", "INTEREST", "FEE"),
        rule_version="v1",
    )

    assert all(row.rule_version == "v1" for row in result.rows)
    assert result.rows[0].rule_step == 1


def test_an_overpayment_is_not_silently_absorbed():
    """Nothing may be untyped, so an amount with no line left to land on must surface
    rather than vanish into a rounding difference."""
    result = allocate(
        Decimal("99999.00"),
        fx_arr_1(),
        effective_date=date(2026, 10, 23),
        component_order=("PRINCIPAL", "INTEREST", "FEE"),
    )

    assert result.total_allocated == Decimal("11160.00")
    assert result.unallocated == Decimal("88839.00")
