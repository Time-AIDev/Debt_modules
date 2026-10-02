"""Do the fixtures obey the rules the engine states?

Every defect the 25-08 cross-artefact audit found was in illustrative data, never in a
rule. This file is the standing guard against that: it asserts the SEED DATA obeys the
same requirements the engine enforces, so a rule cannot be correct in code and wrong on
screen at the same time.
"""
import json
from decimal import Decimal
from pathlib import Path

from app.fixtures import seed
from app.money.fee_states import FEE_STATES
from app.money.schedule import build_schedule

CUSTOMERS = seed()
CONTRACTS = [(c, k) for c in CUSTOMERS for k in c.contracts]
ORDER_FIXTURE = Path(__file__).resolve().parent.parent / "app" / "fixtures_orders.json"
SHEET_FIXTURE = Path(__file__).resolve().parent.parent / "app" / "fixtures_sheet.json"


def test_published_order_fixture_contains_only_synthetic_identities():
    """A committed demo fixture must never contain a customer's exported identity."""
    data = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    assert data["source"]["data_classification"] == "synthetic"
    assert data["orders"]
    assert all(row["crm_id"].startswith("SYN-ORDER-") for row in data["orders"])
    assert all(row["first_name"].startswith("Demo") for row in data["orders"])
    assert all(row["thai_name"].startswith("ลูกค้าทดสอบ") for row in data["orders"])
    assert all(row["customer_id"].startswith("SYN-LOAN-") for row in data["loan_book"])


def test_published_sheet_fixture_contains_only_synthetic_identities():
    """The demo book may preserve scenarios, but never exported customer identities."""
    data = json.loads(SHEET_FIXTURE.read_text(encoding="utf-8"))
    assert data["source"]["data_classification"] == "synthetic"
    assert data["customers"]
    assert all(row["customer_no"].startswith("99999") for row in data["customers"])
    assert all(row["name_roman"].startswith("Demo Customer") for row in data["customers"])
    assert all(row["name_th"].startswith("ลูกค้าทดสอบ") for row in data["customers"])


def _is_cash_format(contract):
    """Deck v20.0 cash one-format: exactly two zero-interest lines — the deposit,
    then the WHOLE remaining balance. A third line would resurrect Cash 2/Cash 3."""
    return contract.product == "CASH" and len(contract.instalments) == 2 and all(
        line.interest_amount == Decimal("0.00") for line in contract.instalments
    )


def _active_lines(contract):
    return [line for line in contract.instalments if line.schedule_status == "ACTIVE"]


def test_every_schedule_sums_to_its_total_with_no_residue():
    """REQ-MNY-003 / TC-MNY-003: the final instalment is the balancing figure so the
    sum of scheduled instalments equals total_amount EXACTLY.

    FX-C2 (210,000 over 36) is the case that catches it: 35 lines at 7,215.83 plus a
    final line of 7,215.95. A fixture that repeats 7,215.83 on the last line leaves a
    0.12 residue and quietly contradicts the requirement it is meant to illustrate.

    The deck-v20 shapes carry their own versions of the same law: a cash-format
    contract's two lines sum to the PRICE exactly, and a restructured contract's
    ACTIVE lines sum to the addendum schedule's total.
    """
    for customer, contract in CONTRACTS:
        active = _active_lines(contract)
        if _is_cash_format(contract):
            drawn = sum((line.total_amount for line in active), Decimal("0.00"))
            assert drawn == contract.principal, (
                "%s cash format leaves a residue of %s" % (contract.uid, drawn - contract.principal)
            )
            continue
        if len(active) != contract.term_months:
            # A restructured contract: the ACTIVE lines are the addendum's schedule,
            # whose own term differs from the fixture's original term.
            term = len(active)
            principal = sum((line.principal_amount for line in active), Decimal("0.00"))
        else:
            term, principal = contract.term_months, contract.principal
        schedule = build_schedule(principal, Decimal("7.9"), term)
        drawn = sum((line.total_amount for line in active), Decimal("0.00"))
        assert drawn == schedule.total_amount, (
            "%s leaves a residue of %s" % (contract.uid, drawn - schedule.total_amount)
        )


def test_the_final_line_carries_the_balancing_figure():
    for customer, contract in CONTRACTS:
        if _is_cash_format(contract):
            # The balancing figure of the cash format IS the whole remaining balance.
            deposit, balance = contract.instalments
            assert balance.total_amount == contract.principal - deposit.total_amount, contract.uid
            continue
        active = _active_lines(contract)
        term = len(active)
        principal = sum((line.principal_amount for line in active), Decimal("0.00"))
        schedule = build_schedule(principal, Decimal("7.9"), term)
        assert active[-1].total_amount == schedule.final_installment_amount, contract.uid


def test_cash_contracts_obey_the_one_format_rule():
    """Deck v20.0 (Win, 26 Aug): deposit from THB 5,000 scaling with system size,
    then instalment 2 for the WHOLE remaining balance. Cash 2 and Cash 3 retired."""
    cash = [k for _c, k in CONTRACTS if _is_cash_format(k)]
    assert cash, "no cash-format contract — S01/S11 become untestable"
    for contract in cash:
        deposit, balance = contract.instalments
        derivation = getattr(contract, "derivation", None) or {}
        if str(derivation.get("deposit", "")).startswith("paid so far"):
            # Round-2 thip T2-01: a migrated cash row whose sheet invoice is fully
            # outstanding has paid nothing yet; the one-format rule describes the
            # contract shape, not what the customer has done so far.
            assert balance.total_amount == contract.principal - deposit.total_amount, contract.uid
            continue
        assert deposit.total_amount >= Decimal("5000"), contract.uid
        assert deposit.outstanding_amount == Decimal("0.00"), (
            "%s — the deposit is what triggers the work; an unpaid deposit is not an order" % contract.uid
        )
        assert balance.total_amount == contract.principal - deposit.total_amount, contract.uid


def test_every_contract_routes_on_an_entity():
    """Deck v20.0 — CASH→EPC, LEASE→SPV. SPV never appears on a cash order."""
    for _customer, contract in CONTRACTS:
        assert contract.entity in ("EPC", "SPV"), contract.uid
        if contract.product == "CASH":
            assert contract.entity == "EPC", contract.uid
        if contract.product == "LEASE":
            assert contract.entity == "SPV", contract.uid


def test_the_scenario_book_covers_the_ladder_rungs():
    """S07's four rungs, S08 active, S09 month-37+, S11, S12 all have a live example —
    a rung with no demo customer is a rule nobody can see."""
    codes = set()
    for customer in CUSTOMERS:
        codes.update(customer.scenario_codes)
    for required in ("S01", "S02", "S07", "S08", "S09", "S11", "S12"):
        assert required in codes, "no demo customer carries %s" % required


def test_sheet_derived_identities_are_marked_and_bridged():
    """R5 — every sheet-derived identity is marked, carries the fixture-authored
    order_ref, and its order row actually exists in fixtures_orders.json."""
    data = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    order_nos = {o["no"] for o in data["orders"]}
    for customer in CUSTOMERS:
        source = customer.data_source
        assert set(source) == {"identity", "history"}, customer.customer_no
        if source["identity"] == "SHEET" and source["history"] == "SYNTHETIC":
            assert customer.order_ref, customer.customer_no
            assert customer.order_ref["no"] in order_nos, customer.customer_no
            assert "bridge_note" in customer.order_ref, customer.customer_no
            # The import masked the real number; inventing one could dial a stranger.
            assert customer.phone_e164 is None, customer.customer_no
        elif source["identity"] == "SHEET":
            # 2026-09-02: the migrated book (REQ-INT-030) — every row names its
            # sheet block and row, and still carries no invented number.
            assert customer.order_ref and customer.order_ref.get("source_refs"), customer.customer_no
            assert customer.phone_e164 is None, customer.customer_no
        else:
            assert customer.order_ref is None, customer.customer_no


def test_every_fee_state_in_the_fixtures_is_in_the_governed_table():
    """A state absent from the table would make every consumer derive its own answer."""
    for customer, contract in CONTRACTS:
        if contract.fee_state:
            assert contract.fee_state in FEE_STATES, contract.uid


def test_a_fee_state_that_pauses_the_fee_has_a_start_date():
    """Without one the pause applies retroactively and erases fee that was earned."""
    for customer, contract in CONTRACTS:
        if contract.fee_state and FEE_STATES[contract.fee_state].stops_fee:
            assert contract.fee_state_from is not None, contract.uid


def test_the_fixture_set_still_contains_the_cases_the_rules_need_to_be_visible():
    """These are not decoration. Remove any of them and a rule stops being observable."""
    states = {k.fee_state for _c, k in CONTRACTS}
    assert "PERMIT_HOLD" in states, "no permit-held contract — D13 becomes untestable"
    assert "DISPUTE_UNDER_REVIEW" in states, "no disputed contract — REQ-MNY-033 becomes untestable"
    assert any(len(c.contracts) > 1 for c in CUSTOMERS), "no multi-contract customer"
    assert any(
        k.part_payment > 0 for _c, k in CONTRACTS
    ), "no part-paid contract — 'sufficient payment' becomes untestable"
    assert len({k.term_months for _c, k in CONTRACTS}) > 1 or any(
        k.term_months == 36 for _c, k in CONTRACTS
    ), "no non-dividing term — the balancing final instalment becomes untestable"
