from datetime import date
from decimal import Decimal

import pytest

from app import confirmed_cash, errors, journey
from app.fixtures import ContractFixture
from app.money.models import Instalment


def line(due):
    return Instalment(due_date=due, category="REGULAR", principal_amount=Decimal("1000"),
                     interest_amount=Decimal("100"))


def evidence(outstanding):
    return {"amount": "1100", "outstanding": outstanding, "liability_verified": True}


def test_fully_paid_historical_cycle_is_excluded_but_future_obligation_survives():
    past, future = line(date(2026, 9, 10)), line(date(2026, 11, 10))
    balances = confirmed_cash.outstanding_by_cycle([past, future], {1: evidence("0")},
                                                   as_of=date(2026, 10, 7))
    assert balances == {1: Decimal("0"), 2: Decimal("1100")}
    assert past.paid_principal == 0  # projection never changes raw schedule/money


def test_partial_payment_uses_existing_allocation_policy_gate():
    with pytest.raises(errors.Problem) as failure:
        confirmed_cash.outstanding_by_cycle([line(date(2026, 9, 10))], {1: evidence("550")},
                                            as_of=date(2026, 10, 7))
    assert failure.value.code == "allocation_rule_pending"
    assert confirmed_cash.outstanding_by_cycle([line(date(2026, 9, 10))], {1: evidence("550")},
        as_of=date(2026, 10, 7), allocation_order=("INTEREST", "PRINCIPAL", "FEE"))[1] == Decimal("550")


def test_historical_missing_or_unplaced_evidence_cannot_be_quoted_as_unpaid():
    for cycles, unresolved in [({}, 0), ({1: evidence("0")}, 1)]:
        with pytest.raises(errors.Problem) as failure:
            confirmed_cash.outstanding_by_cycle([line(date(2026, 9, 10))], cycles,
                as_of=date(2026, 10, 7), unresolved=unresolved)
        assert failure.value.code == "npv_payment_evidence_unconfirmed"


def test_existing_native_fixture_npv_remains_unchanged():
    contract = ContractFixture("native-proof", "native-customer", "LEASE", Decimal("12000"),
                               12, date(2024, 1, 10), paid_through=2).build()
    face = sum(line.outstanding_amount for line in contract.instalments)
    assert journey.remaining_npv(contract, as_of=date(2026, 10, 7)) == face.quantize(Decimal("0.01"))


def test_quote_hook_uses_verified_snapshot_outstanding_without_subtracting_cash_twice(monkeypatch):
    from app import payment_summary
    contract = ContractFixture("supplement-proof", "source-customer", "LEASE", Decimal("1000"),
                               1, date(2026, 9, 10)).build()
    contract.financial_evidence_only = True
    contract.schedule_confirmation = {"document_ref": "SIGNED-CONTRACT"}
    total = str(contract.instalments[0].total_amount)
    monkeypatch.setattr(payment_summary, "peak_cycles_for", lambda *_args: ({1: {
        "amount": total, "outstanding": "0", "liability_verified": True}}, 0, "2026-09-30"))
    assert journey.remaining_npv(contract, as_of=date(2026, 10, 7)) == Decimal("0.00")


def test_supplement_without_independent_contract_schedule_proof_refuses_quote():
    contract = ContractFixture("unconfirmed-proof", "source-customer", "LEASE", Decimal("1000"),
                               1, date(2026, 9, 10)).build()
    contract.financial_evidence_only = True
    with pytest.raises(errors.Problem) as failure:
        journey.remaining_npv(contract, as_of=date(2026, 10, 7))
    assert failure.value.code == "npv_payment_evidence_unconfirmed"


def test_deferral_copies_keep_stable_cycle_mapping_in_the_quote(monkeypatch):
    import copy
    from app import cases, payment_summary
    contract = ContractFixture("deferred-proof", "source-customer", "LEASE", Decimal("1000"),
                               2, date(2026, 9, 10)).build()
    contract.financial_evidence_only = True
    contract.schedule_confirmation = {"document_ref": "SIGNED-CONTRACT"}
    def projected(_contract, _field):
        lines = [copy.copy(line) for line in contract.instalments]
        lines[0].service_original_due_date = lines[0].due_date
        lines[0].due_date = date(2026, 12, 10)
        return lines
    monkeypatch.setattr(cases, "contract_field_of", projected)
    monkeypatch.setattr(payment_summary, "peak_cycles_for", lambda *_args: ({1: {
        "amount": str(contract.instalments[0].total_amount), "outstanding": "0", "liability_verified": True}}, 0, None))
    assert journey.remaining_npv(contract, as_of=date(2026, 10, 7)) == contract.instalments[1].outstanding_amount
