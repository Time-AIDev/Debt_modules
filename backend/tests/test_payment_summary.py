"""The case's payment overview — `payment_summary` on GET /v1/cases/by-customer/{uid}.

Arina, 2026-09-14: the case page shows how much a customer has paid across every
cycle, and where each cycle stands, as a picture. The interface adds nothing up, so
every count and total the picture draws is served, and tied out here against the
engine figures the rest of the page already prints.

Expectations distinguish imported assumptions from confirmed payment evidence.
"""
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app import main, payment_summary
from app.fixtures import ContractFixture
from app.money.models import Instalment

client = TestClient(main.app)

LEASE_WITH_LATE = "sheet-99999000027"   # 96 cycles, one LATE sheet cell, 11,649.00 overdue
CASH_OVERDUE = "sheet-99999000297"        # the screenshot's customer: deposit 0.00, balance 588,500.00 overdue


def _case(uid):
    response = client.get("/v1/cases/by-customer/%s" % uid)
    assert response.status_code == 200
    return response.json()


def _d(value):
    return Decimal(value)


def test_a_lease_case_serves_every_cycle_with_its_status():
    summary = _case(LEASE_WITH_LATE)["payment_summary"]
    assert summary["indicative"] is True, "cycle paid figures are the sheet walked back, never cash"
    assert summary["provenance_th"]
    (contract,) = summary["contracts"]
    assert contract["contract_uid"] == "K-99999000027-L"
    assert contract["cycle_count"] == 96
    assert len(contract["cycles"]) == 96
    assert [c["n"] for c in contract["cycles"]] == list(range(1, 97))
    # The four statuses partition the cycles — nothing is counted twice or dropped.
    assert sum(contract["counts"].values()) == 96
    assert contract["counts"] == {"PAID": 0, "OVERDUE": 0, "UPCOMING": 73, "NO_AMOUNT": 0,
                                   "INFERRED_PAID": 22, "SHEET_REPORTED_PAID": 0, "UNCONFIRMED": 1, "REJECTED": 0}
    assert contract["schedule_verified"] is False
    assert contract["review_count"] == 23


def test_the_lease_totals_tie_out_to_the_engine_figures_on_the_same_page():
    data = _case(LEASE_WITH_LATE)
    (contract,) = data["payment_summary"]["contracts"]
    (k,) = data["contracts"]
    assert contract["overdue_amount"] == k["instalments_overdue"] == "0.00"
    cycles = contract["cycles"]
    assert _d(contract["paid_amount"]) == sum(_d(c["paid"]) for c in cycles) == Decimal("0.00")
    assert _d(contract["contract_amount"]) == sum(_d(c["amount"]) for c in cycles)
    assert _d(contract["outstanding_amount"]) == sum(_d(c["outstanding"]) for c in cycles)
    assert contract["next_due"] == {"n": 24, "due_date": "2026-11-10", "amount": "11649.00"}


def test_the_sheet_count_is_served_beside_the_engine_count_never_blended():
    """The engine says 22 cycles paid (due by the business date, minus the one LATE
    cell); the sheet's own grid has 19 PAID cells, because it starts recording six
    months in. Both are served so the page can say "sheet says 19" beside "22"."""
    (contract,) = _case(LEASE_WITH_LATE)["payment_summary"]["contracts"]
    assert contract["counts"]["PAID"] == 0
    assert contract["counts"]["INFERRED_PAID"] == 22
    assert contract["sheet"] == {"paid_cells": 19, "paid_amount": "221331.00", "late_cells": 1, "cells": 30}


def test_a_cash_case_serves_its_deposit_and_balance_as_two_cycles():
    data = _case(CASH_OVERDUE)
    summary = data["payment_summary"]
    (contract,) = summary["contracts"]
    assert contract["product"] == "CASH"
    assert [c["kind"] for c in contract["cycles"]] == ["DEPOSIT", "BALANCE"]
    deposit, balance = contract["cycles"]
    # The sheet's invoices say nothing was paid, so the deposit line carries no amount.
    # It is not "paid": a zero cycle is its own status, not a green block.
    assert deposit["status"] == "NO_AMOUNT"
    assert balance["status"] == "OVERDUE"
    assert balance["amount"] == balance["outstanding"] == "588500.00"
    assert contract["paid_amount"] == "0.00"
    assert contract["overdue_amount"] == "588500.00"
    assert contract["next_due"] is None
    # A cash row with no month cells has no sheet count to compare against.
    assert contract["sheet"] is None


def test_a_paid_cash_deposit_is_not_counted_as_a_paid_instalment():
    k = ContractFixture("K-DP", "cu-dp", "CASH", Decimal("3000"), 2, date(2026, 9, 1))
    k.instalments = [
        Instalment(due_date=date(2026, 9, 1), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0"), paid_principal=Decimal("1000")),
        Instalment(due_date=date(2026, 11, 1), category="REGULAR", principal_amount=Decimal("2000"),
                   interest_amount=Decimal("0")),
    ]

    entry = payment_summary.for_contract(k, date(2026, 10, 23), overdue_amount=Decimal("0.00"))
    summary = payment_summary.build([entry], date(2026, 10, 23))

    assert [(c["kind"], c["instalment_n"], c["status"]) for c in entry["cycles"]] == [
        ("DEPOSIT", None, "PAID"), ("BALANCE", 1, "UPCOMING"),
    ]
    assert entry["breakdown"] == {
        "deposit": {"count": 1, "counts": {"PAID": 1, "OVERDUE": 0, "UPCOMING": 0, "NO_AMOUNT": 0},
                    "remaining_count": 0, "display_paid_count": 1, "unverified_paid_count": 1, "display_remaining_count": 0},
        "instalment": {"count": 1, "counts": {"PAID": 0, "OVERDUE": 0, "UPCOMING": 1, "NO_AMOUNT": 0},
                       "remaining_count": 1, "display_paid_count": 0, "unverified_paid_count": 0, "display_remaining_count": 1},
    }
    assert summary["totals"]["breakdown"] == entry["breakdown"]


def test_lease_cycle_numbers_remain_instalment_numbers():
    k = ContractFixture("K-I", "cu-i", "LEASE", Decimal("2000"), 2, date(2026, 9, 1))
    k.instalments = [
        Instalment(due_date=date(2026, 9, 1), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0"), paid_principal=Decimal("1000")),
        Instalment(due_date=date(2026, 11, 1), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0")),
    ]

    entry = payment_summary.for_contract(k, date(2026, 10, 23), overdue_amount=Decimal("0.00"))

    assert [c["instalment_n"] for c in entry["cycles"]] == [1, 2]
    assert entry["breakdown"]["deposit"]["count"] == 0
    assert entry["breakdown"]["instalment"] == {
        "count": 2, "counts": entry["counts"], "remaining_count": 1,
        "display_paid_count": 1, "unverified_paid_count": 1, "display_remaining_count": 1,
    }


def test_every_case_in_the_book_ties_out():
    """All 212: the statuses partition the cycles, and the totals are the sums of the
    contracts and match the arrears figure the header prints."""
    for customer in main.CUSTOMERS:
        data = _case(customer.uid)
        summary = data["payment_summary"]
        contracts = summary["contracts"]
        assert len(contracts) == len(data["contracts"]), customer.uid
        for contract in contracts:
            assert sum(contract["counts"].values()) == contract["cycle_count"] == len(contract["cycles"]), customer.uid
            assert contract["partly_paid_count"] == sum(1 for c in contract["cycles"] if c["partly_paid"]), customer.uid
        totals = summary["totals"]
        assert _d(totals["paid_amount"]) == sum(_d(c["paid_amount"]) for c in contracts), customer.uid
        assert _d(totals["contract_amount"]) == sum(_d(c["contract_amount"]) for c in contracts), customer.uid
        assert _d(totals["overdue_amount"]) == sum(_d(c["overdue_amount"]) for c in contracts), customer.uid
        assert totals["cycle_count"] == sum(c["cycle_count"] for c in contracts), customer.uid
        assert totals["overdue_amount"] == data["work_item"]["money_position"]["instalments_overdue"], customer.uid
        assert summary["summed_across_contracts"] is (len(contracts) > 1), customer.uid


def test_a_superseded_line_is_not_a_cycle():
    """A restructure supersedes the old schedule (deck S08). The engine follows
    is_active_regular; so does the overview, or a restructured customer would show
    two schedules' worth of cycles."""
    k = ContractFixture("K-T", "cu-t", "LEASE", Decimal("3000"), 3, date(2026, 8, 10))
    k.instalments = [
        Instalment(due_date=date(2026, 8, 10), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0"), paid_principal=Decimal("1000")),
        Instalment(due_date=date(2026, 9, 10), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0"), paid_principal=Decimal("400")),
        Instalment(due_date=date(2026, 10, 10), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0"), schedule_status="SUPERSEDED"),
        Instalment(due_date=date(2026, 11, 10), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0")),
    ]
    entry = payment_summary.for_contract(k, date(2026, 10, 23), overdue_amount=Decimal("600.00"))
    assert entry["cycle_count"] == 3
    assert [c["due_date"] for c in entry["cycles"]] == ["2026-08-10", "2026-09-10", "2026-11-10"]
    assert [c["status"] for c in entry["cycles"]] == ["PAID", "OVERDUE", "UPCOMING"]
    assert [c["partly_paid"] for c in entry["cycles"]] == [False, True, False]
    assert entry["paid_amount"] == "1400.00"
    assert entry["outstanding_amount"] == "1600.00"


def test_a_cycle_due_on_the_business_date_is_not_yet_overdue():
    """The engine's own rule (arrears_block): overdue means due BEFORE the ledger date."""
    k = ContractFixture("K-U", "cu-u", "LEASE", Decimal("1000"), 1, date(2026, 10, 23))
    k.instalments = [Instalment(due_date=date(2026, 10, 23), category="REGULAR",
                                principal_amount=Decimal("1000"), interest_amount=Decimal("0"))]
    entry = payment_summary.for_contract(k, date(2026, 10, 23), overdue_amount=Decimal("0.00"))
    assert entry["cycles"][0]["status"] == "UPCOMING"


def test_a_peak_cycle_overlays_the_engines_status_and_says_so():
    import datetime
    from app import journey
    customer = next(c for c in journey.book_customers() if c.contracts and c.contracts[0].product == "LEASE")
    contract = customer.contracts[0]
    peak = {2: {"status": "PAID", "paid": "8399.00", "outstanding": "0.00", "doc_no": "IVT-2"},
            3: {"status": "OVERDUE", "paid": "0.00", "outstanding": "8399.00", "doc_no": "IVT-3"}}
    out = payment_summary.for_contract(contract, datetime.date(2026, 10, 23), "0.00", peak_cycles=peak)
    by_n = {c["n"]: c for c in out["cycles"]}
    assert by_n[2]["status"] == "PAID" and by_n[2]["source"] == "PEAK" and by_n[2]["doc_no"] == "IVT-2"
    assert by_n[3]["status"] == "OVERDUE" and by_n[3]["source"] == "PEAK"
    assert by_n[1]["source"] == "SHEET_DERIVED"
    assert out["source"] == "PEAK" and out["peak"]["invoices"] == 2


def test_without_peak_the_contract_is_sheet_derived_as_before():
    import datetime
    from app import journey
    customer = next(c for c in journey.book_customers() if c.contracts)
    out = payment_summary.for_contract(customer.contracts[0], datetime.date(2026, 10, 23), "0.00")
    assert out["source"] == "SHEET_DERIVED" and out["peak"] is None
    assert all(c["source"] == "SHEET_DERIVED" for c in out["cycles"])


def test_the_summary_is_indicative_unless_every_due_cycle_is_peaks():
    import datetime
    from app import cases as cases_domain, journey
    bd = datetime.date(2026, 10, 23)

    def _due_count(k):
        # The first LEASE-first customer in the book has only one cycle due by bd — covering
        # it with a single PEAK slot would make "partial" indistinguishable from "full". Pick
        # the first LEASE contract with at least two, so partial coverage stays partial.
        lines = cases_domain.contract_field_of(k, "instalments") or []
        return sum(1 for ln in lines if ln.is_active_regular and ln.due_date <= bd)

    customer = next(c for c in journey.book_customers()
                    if c.contracts and c.contracts[0].product == "LEASE" and _due_count(c.contracts[0]) >= 2)
    contract = customer.contracts[0]
    partial = payment_summary.build([payment_summary.for_contract(contract, bd, "0.00",
                                                                 peak_cycles={1: {"status": "PAID", "paid": "1", "outstanding": "0", "doc_no": "x"}})], bd)
    assert partial["indicative"] is True
    due = [c["n"] for c in payment_summary.for_contract(contract, bd, "0.00")["cycles"] if c["due_date"] <= str(bd)]
    every = {n: {"status": "PAID", "paid": "1", "outstanding": "0", "doc_no": "x"} for n in due}
    full = payment_summary.build([payment_summary.for_contract(contract, bd, "0.00", peak_cycles=every)], bd)
    assert full["indicative"] is False and "PEAK" in full["provenance_th"]


def test_peak_cycles_for_reads_this_sessions_peak_invoices():
    from app import journey
    from tests.test_peak_book import _with_peak, PAID, LATE
    customer, state = _with_peak([PAID, LATE, dict(LATE, doc_no="IVT-9", cycle=None)])
    contract = customer.contracts[0]
    contract.first_due = date(2026, 4, 12)
    contract.build()
    contract.schedule_confirmation = {"first_due": "2026-04-12", "document_ref": "test signed contract"}
    cycles, unplaced, as_of = payment_summary.peak_cycles_for(contract.uid, state)
    assert set(cycles) == {3, 4} and cycles[4]["status"] == "OVERDUE" and cycles[3]["doc_no"] == "IVT-1"
    assert unplaced == 0 and as_of == "2026-09-14"
    assert len(cycles[4]["invoices"]) == 2


def test_the_contract_totals_follow_a_peak_overlay_not_just_the_engine():
    """I1: contract paid_amount/outstanding_amount must not disagree with the cycle
    table they sit above — a PEAK-overlaid cycle's figures must be reflected in the
    contract totals, not just the engine's own (pre-overlay) numbers."""
    k = ContractFixture("K-P", "cu-p", "LEASE", Decimal("2000"), 2, date(2026, 8, 10))
    k.instalments = [
        Instalment(due_date=date(2026, 8, 10), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0"), paid_principal=Decimal("1000")),
        Instalment(due_date=date(2026, 9, 10), category="REGULAR", principal_amount=Decimal("1000"),
                   interest_amount=Decimal("0")),
    ]
    # The engine says cycle 2 is untouched (unpaid); PEAK says it was paid in full.
    peak = {2: {"status": "PAID", "paid": "1000.00", "outstanding": "0.00", "doc_no": "IVT-1"}}
    entry = payment_summary.for_contract(k, date(2026, 10, 23), overdue_amount=Decimal("0.00"), peak_cycles=peak)
    assert entry["cycles"][0]["paid"] == "1000.00" and entry["cycles"][1]["paid"] == "1000.00"
    assert entry["paid_amount"] == "2000.00"            # not the engine's 1000.00
    assert entry["outstanding_amount"] == "0.00"         # not the engine's 1000.00
    assert Decimal(entry["paid_amount"]) == sum(Decimal(c["paid"]) for c in entry["cycles"])
    assert Decimal(entry["outstanding_amount"]) == sum(Decimal(c["outstanding"]) for c in entry["cycles"])


def test_two_peak_invoices_on_one_cycle_are_both_retained():
    """Both effective invoices are evidence, not a latest-document contest."""
    from tests.test_peak_book import _with_peak, PAID
    customer, state = _with_peak([PAID, dict(PAID, doc_no="IVT-9", issued_on="2026-06-20")])
    contract = customer.contracts[0]
    contract.first_due = date(2026, 4, 12)
    contract.build()
    contract.schedule_confirmation = {"first_due": "2026-04-12", "document_ref": "test signed contract"}
    cycles, unplaced, as_of = payment_summary.peak_cycles_for(contract.uid, state)
    assert set(cycles) == {3} and unplaced == 0
    assert len(cycles[3]["invoices"]) == 2
    assert cycles[3]["paid"] == "16798.00"
    entry = payment_summary.for_contract(contract, date(2026, 10, 23), "0.00", peak_cycles=cycles)
    assert entry["peak"]["invoices"] == 2
    assert entry["peak"]["superseded_invoices"] == 0


def test_a_month_index_beyond_the_schedule_counts_as_unplaced():
    """I2: a month_index below 1 or past the contract's own last cycle lands on no
    cycle — it must not sit in the overlay dict inflating peak['invoices']; it counts
    toward unplaced_peak_invoices instead."""
    from tests.test_peak_book import _with_peak, PAID
    customer, state = _with_peak([dict(PAID, doc_no="IVT-77", cycle={"n": 9999, "of": 48})])
    contract = customer.contracts[0]
    contract.first_due = date(2026, 4, 12)
    contract.build()
    contract.schedule_confirmation = {"first_due": "2026-04-12", "document_ref": "test signed contract"}
    cycles, unplaced, as_of = payment_summary.peak_cycles_for(contract.uid, state)
    assert cycles == {} and unplaced == 1
