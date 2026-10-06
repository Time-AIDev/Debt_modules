"""Compact list-row review amounts must equal the complete case cycle projection."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
import random

import pytest

from app import payment_summary, request_context
from app.fixtures import ContractFixture
from app.money.models import Instalment

FIELDS = ("review_amount", "review_count", "schedule_verified", "unplaced_peak_details")


def _contract(strict=True):
    contract = ContractFixture("compact-review", "compact-customer", "LEASE", Decimal("9600"), 96,
                               date(2024, 1, 1))
    contract.instalments = [Instalment(date(2024 + n // 12, n % 12 + 1, 1), "REGULAR",
        Decimal("100.005"), Decimal("1.005"), paid_principal=Decimal("100") if n % 3 == 0 else Decimal("0"))
        for n in range(96)]
    contract.requires_schedule_confirmation = strict
    contract.schedule_confirmation = {"first_due": "2024-01-01"} if strict else None
    contract.sheet_row = {"first_payment_date": "2024-01-01"}
    return contract


def _hit(paid="10.01", verified=True, due="2024-01-20"):
    return {"status": "OVERDUE", "paid": paid, "outstanding": "91.00", "amount": "101.01",
            "due_date": due, "due_dates": [due], "open_due_date": due,
            "invoices": [{"uid": "proof", "matching_method": "SERVICE_MONTH"}],
            "matching_method": "SERVICE_MONTH", "liability_verified": verified}


def _equivalent(contract, business_date, cycles):
    full = payment_summary.for_contract(contract, business_date, Decimal("0"), peak_cycles=cycles)
    compact = payment_summary.review_summary(contract, business_date, cycles)
    assert compact == {key: full[key] for key in FIELDS}


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("business_date", [date(2023, 12, 31), date(2024, 1, 1), date(2026, 10, 23), date(2033, 1, 1)])
def test_review_summary_matches_all_schedule_dates_and_rounding(strict, business_date):
    contract = _contract(strict)
    for rounding in (None, ROUND_HALF_UP):
        with localcontext() as context:
            if rounding:
                context.rounding = rounding
            _equivalent(contract, business_date, None)


def test_review_summary_matches_confirmed_receipt_only_future_rejected_and_unplaced_evidence():
    contract = _contract()
    cycles = payment_summary.PeakCycles([{"uid": "unplaced", "contract_resolved": False,
                                         "amount": "90.00", "outstanding": "90.00"}])
    cycles.update({1: _hit(), 2: _hit(verified=False, due="2024-02-20"),
                   90: _hit(verified=False, due="2024-03-20")})
    cycles.rejected = {3: [{"uid": "rejected"}]}
    _equivalent(contract, date(2026, 10, 23), cycles)


def test_review_summary_matches_unconfirmed_schedule_and_service_deferred_dates():
    contract = _contract()
    contract.schedule_confirmation = None
    original = contract.instalments[0]
    original.service_original_due_date = original.due_date
    original.due_date = date(2030, 1, 1)
    original.service_deferral = {"uid": "synthetic-deferral"}
    _equivalent(contract, date(2026, 10, 23), None)


def test_review_summary_matches_seeded_evidence_combinations_without_cross_request_state():
    randomizer = random.Random(20261006)
    token = request_context.begin_read()
    try:
        for scenario in range(40):
            contract = _contract()
            contract.uid += "-%d" % scenario
            cycles = payment_summary.PeakCycles([])
            cycles.rejected = {}
            for n in range(1, 97):
                choice = randomizer.randrange(5)
                due = str(contract.instalments[n - 1].due_date)
                if choice in (1, 2):
                    cycles[n] = _hit(paid="0.00" if n % 2 else "102.01", verified=choice == 1, due=due)
                elif choice == 3:
                    cycles.rejected[n] = [{"uid": "rejected-%d" % n}]
            _equivalent(contract, date(2026, 10, 23), cycles)
    finally:
        request_context.end_read(token)
