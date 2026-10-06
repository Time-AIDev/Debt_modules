"""Batch read optimizations retain every cycle, invoice UID and recorded payment."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from types import SimpleNamespace

from app import journey, payment_summary
from app.book import SHEET
from app.fixtures import ContractFixture
from app.money.models import Instalment


def test_cycle_summary_keeps_exact_96_cycle_totals_and_status_partition():
    contract = ContractFixture("perf-96", "perf-customer", "LEASE", Decimal("9600"), 96, date(2020, 1, 1))
    contract.instalments = [Instalment(
        due_date=date(2020 + n // 12, n % 12 + 1, 1), category="REGULAR",
        principal_amount=Decimal("100.01"), interest_amount=Decimal("1.11"), fee_amount=Decimal("0.01"),
        paid_principal=Decimal("100.01") if n < 12 else Decimal("33.33") if n == 12 else Decimal("0"),
        paid_interest=Decimal("1.11") if n < 12 else Decimal("0"),
        paid_fee=Decimal("0.01") if n < 12 else Decimal("0")) for n in range(96)]
    entry = payment_summary.for_contract(contract, date(2026, 10, 23), Decimal("1234.56"))
    assert len(entry["cycles"]) == entry["cycle_count"] == sum(entry["counts"].values()) == 96
    assert entry["paid_count"] == 12 and entry["partly_paid_count"] == 1
    assert entry["contract_amount"] == "9708.48"
    assert entry["paid_amount"] == "1246.89"
    assert entry["outstanding_amount"] == "8461.59"
    assert entry["paid_amount"] == str(sum((Decimal(row["paid"]) for row in entry["cycles"]), Decimal("0.00")))
    assert entry["outstanding_amount"] == str(sum((Decimal(row["outstanding"]) for row in entry["cycles"]), Decimal("0.00")))
    assert entry["overdue_amount"] == "1234.56"


def test_decimal_formatting_keeps_the_existing_context_rounding():
    values = (Decimal("1.005"), Decimal("100.01"), Decimal("-0.00"), "2.675", 10)
    with localcontext() as context:
        context.rounding = ROUND_HALF_UP
        for value in values:
            assert payment_summary._money(value) == str(Decimal(str(value)).quantize(Decimal("0.01")))


def test_batch_reseed_keeps_manual_cash_and_new_rows_visible_to_repeated_contract(monkeypatch):
    lines = [Instalment(date(2026, 9, 1), "REGULAR", Decimal("100"), Decimal("0")),
             Instalment(date(2026, 10, 1), "REGULAR", Decimal("100"), Decimal("0"),
                        paid_principal=Decimal("40"))]
    contract = ContractFixture("perf-reseed", "perf-customer", "LEASE", Decimal("200"), 2,
                               date(2026, 9, 1), instalments=lines)
    customer = SimpleNamespace(data_source=dict(SHEET), contracts=[contract], sheet={})
    # A repeated source reference must observe rows added earlier in the same refresh.
    monkeypatch.setattr(journey, "book_customers", lambda: [customer, customer])
    state = journey.JourneyState()
    first = journey.make_invoice(state, contract.uid, "SPV", "INSTALMENT", "100", date(2026, 9, 1), "OVERDUE")
    first["month_index"], first["outstanding"] = 1, "17.00"
    receipt = journey.make_receipt(state, contract.uid, "SPV", "83", date(2026, 9, 15),
                                   invoice_uid=first["uid"], matched="PARTIAL")
    receipt["source"] = "SLIP"
    original_uid = first["uid"]
    result = journey.reseed_migrated_invoices(state, date(2026, 10, 23))
    assert result == {"updated": 0, "added": 1, "flagged": 0}
    assert len(state.invoices) == 2 and first["uid"] == original_uid and first["outstanding"] == "17.00"
    second = next(row for row in state.invoices.values() if row["uid"] != original_uid)
    assert second["month_index"] == 2 and second["outstanding"] == "60.00" and second["state"] == "PARTIALLY_PAID"
    assert state.receipts[receipt["uid"]]["amount"] == "83"
