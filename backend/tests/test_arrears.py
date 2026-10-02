"""REQ-COL-027 — the arrears block.

`closing_balance` and `cumulative_arrears` are defined precisely and ONLY by the
daily-ledger query (Data_Model.md:3980-4058). These tests mirror that SQL.
"""
from datetime import date
from decimal import Decimal

from app.money.arrears import ArrearsBlock, arrears_block
from app.money.models import Instalment

LEDGER_DATE = date(2026, 10, 23)


def regular(due_date, paid=Decimal("0")):
    return Instalment(
        due_date=due_date,
        category="REGULAR",
        principal_amount=Decimal("4000.00"),
        interest_amount=Decimal("1580.00"),
        fee_amount=Decimal("0.00"),
        paid_principal=paid,
    )


def fx_arr_1():
    """One overdue instalment (2026-10-01) and one not yet due (2026-11-01)."""
    return [regular(date(2026, 10, 1)), regular(date(2026, 11, 1))]


def test_outstanding_balance_counts_every_regular_line_due_or_not():
    block = arrears_block(fx_arr_1(), ledger_date=LEDGER_DATE)
    assert block.closing_balance == Decimal("11160.00")


def test_arrears_counts_only_the_past_due_slice():
    block = arrears_block(fx_arr_1(), ledger_date=LEDGER_DATE)
    assert block.cumulative_arrears == Decimal("5580.00")
    assert block.overdue_instalment_count == 1


def test_a_past_due_penalty_line_is_in_arrears_but_not_in_the_balance():
    """The asymmetry in the ledger SQL, pinned deliberately.

    The `bal` CTE filters category = 'REGULAR'. The `arr` CTE does NOT. So a billed
    PENALTY line past due IS counted in cumulative_arrears and is NOT counted in
    closing_balance — which means arrears is not a subset of the balance. That is
    defensible (an officer collecting 'arrears payable today' wants the billed
    penalty in the figure) but it is stated nowhere in prose, so this test is the
    only place the intent is recorded.
    """
    lines = fx_arr_1() + [
        Instalment(
            due_date=date(2026, 10, 5),
            category="PENALTY",
            principal_amount=Decimal("0.00"),
            interest_amount=Decimal("0.00"),
            fee_amount=Decimal("133.92"),
        )
    ]
    block = arrears_block(lines, ledger_date=LEDGER_DATE)

    assert block.cumulative_arrears == Decimal("5713.92")
    assert block.closing_balance == Decimal("11160.00")


def test_arrears_decomposes_into_principal_interest_and_fee():
    block = arrears_block(fx_arr_1(), ledger_date=LEDGER_DATE)
    assert block.arrears_principal == Decimal("4000.00")
    assert block.arrears_interest == Decimal("1580.00")
    assert block.arrears_fee == Decimal("0.00")


def test_full_payoff_is_the_balance_plus_unbilled_penalty():
    """full_payoff_amount = closing_balance + penalty_accrued_unbilled (Data_Model.md:4003).

    This simple sum is the FALLBACK, live only because early_settlement_method is
    unset (OD-03). It is not the early-settlement quote.
    """
    block = arrears_block(fx_arr_1(), ledger_date=LEDGER_DATE, penalty_accrued_unbilled=Decimal("133.92"))
    assert block.full_payoff_amount == Decimal("11293.92")


def test_the_field_order_is_fixed_and_leads_with_arrears_payable_today():
    """REQ-COL-027 / TC-COL-052: 'a response that leads with the next instalment FAILS the test'.

    The order is: total arrears payable today; DPD and bucket; accrued penalty with
    composition; next due date; next instalment; full payoff.
    """
    block = arrears_block(fx_arr_1(), ledger_date=LEDGER_DATE)
    keys = list(block.to_ordered_dict().keys())

    assert keys[0] == "total_arrears_payable_today"
    assert keys.index("days_past_due") < keys.index("next_installment_amount")
    assert keys.index("accrued_penalty") < keys.index("next_due_date")
    assert keys.index("next_due_date") < keys.index("next_installment_amount")
    assert keys.index("next_installment_amount") < keys.index("full_payoff_amount")


def test_the_next_due_date_is_the_earliest_line_not_yet_due():
    block = arrears_block(fx_arr_1(), ledger_date=LEDGER_DATE)
    assert block.next_due_date == date(2026, 11, 1)
    assert block.next_installment_amount == Decimal("5580.00")


def test_penalty_accrued_billed_paid_and_waived_are_never_netted_into_one():
    """TC-COL-053: four separate figures."""
    block = arrears_block(
        fx_arr_1(),
        ledger_date=LEDGER_DATE,
        penalty_accrued_unbilled=Decimal("133.92"),
        penalty_billed=Decimal("50.00"),
        penalty_paid=Decimal("20.00"),
        penalty_waived=Decimal("10.00"),
    )
    penalty = block.to_ordered_dict()["accrued_penalty"]

    assert penalty["accrued_unbilled"] == Decimal("133.92")
    assert penalty["billed"] == Decimal("50.00")
    assert penalty["paid"] == Decimal("20.00")
    assert penalty["waived"] == Decimal("10.00")
    assert "net" not in penalty


def test_the_block_carries_the_ledger_date_it_was_computed_from():
    """The endpoint reads yesterday's closed row plus today's provisional row, so the
    basis date must travel with the numbers or header and drill-down can disagree."""
    block = arrears_block(fx_arr_1(), ledger_date=LEDGER_DATE)
    assert block.basis_ledger_date == LEDGER_DATE
    assert isinstance(block, ArrearsBlock)


def test_the_arrears_block_carries_the_band_set_beside_the_bucket():
    """API Surface v2.1 §2.2 — the block renders aging_bucket, so it must render
    band_set_code too or a client cannot tell which set answered."""
    from app.money.band_sets import assert_band_pair_present

    block = arrears_block(
        fx_arr_1(), ledger_date=LEDGER_DATE, days_past_due=22,
        aging_bucket="MID_OVERDUE", band_set_code="OPERATIONAL",
    )
    payload = block.to_ordered_dict()

    assert payload["band_set_code"] == "OPERATIONAL"
    assert_band_pair_present(payload)
