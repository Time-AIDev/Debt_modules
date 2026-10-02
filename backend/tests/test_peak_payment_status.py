"""Measured on the 2026-09-14 export: 37 lines carry a partial payment, 29 carry a
status that disagrees with their own outstanding balance. The money decides."""
import types
from app import cases


def _customer(rows):
    return types.SimpleNamespace(sheet={"peak": {"invoices": rows}})


def _row(**over):
    return {"status": "PAID", "due_on": "2026-01-31", "amount_awaiting": "0.00", **over}


def test_fully_paid_is_current():
    assert cases._peak_says(_customer([_row()])) == "CURRENT"


def test_a_partial_payment_is_late_because_money_is_still_owed():
    assert cases._peak_says(_customer([_row(status="OVERDUE", amount_awaiting="6,791.05")])) == "LATE"


def test_overdue_with_nothing_owed_is_not_late():
    assert cases._peak_says(_customer([_row(status="OVERDUE")])) == "CURRENT"


def test_money_owed_past_the_due_date_is_late_whatever_the_word_says():
    assert cases._peak_says(_customer([_row(status="AWAITING", due_on="2020-01-01",
                                            amount_awaiting="1000.00")])) == "LATE"


def test_money_owed_before_the_due_date_is_not_late_yet():
    assert cases._peak_says(_customer([_row(status="AWAITING", due_on="2099-01-01",
                                            amount_awaiting="1000.00")])) == "CURRENT"


def test_a_draft_is_ignored():
    assert cases._peak_says(_customer([_row(status="DRAFT", amount_awaiting="999")])) is None


def test_no_invoices_means_no_opinion():
    assert cases._peak_says(_customer([])) is None


def test_a_nan_amount_reads_as_nothing_owed_instead_of_throwing():
    """Decimal("nan") parses fine but raises on comparison. A Postgres numeric can
    hold NaN, and this is the payment-status decision path."""
    assert cases._peak_says(_customer([_row(status="OVERDUE", due_on="2020-01-01",
                                            amount_awaiting="NaN")])) == "CURRENT"


def test_an_infinite_amount_reads_as_nothing_owed():
    assert cases._peak_says(_customer([_row(status="OVERDUE", due_on="2020-01-01",
                                            amount_awaiting="Infinity")])) == "CURRENT"


def test_overdue_with_money_owed_and_no_due_date_is_late():
    """Finding 2 regression guard: PEAK's own OVERDUE word is the fallback when
    there is no due_on to compare against a missing due_on must not read as
    'never late'."""
    row = _row(status="OVERDUE", amount_awaiting="1000.00")
    del row["due_on"]
    assert cases._peak_says(_customer([row])) == "LATE"


def test_awaiting_with_money_owed_and_no_due_date_is_still_current():
    """The guard on the fix above: AWAITING (not OVERDUE) with no due_on stays
    CURRENT — only OVERDUE's own word is the fallback."""
    row = _row(status="AWAITING", amount_awaiting="1000.00")
    del row["due_on"]
    assert cases._peak_says(_customer([row])) == "CURRENT"


# --- fix-all leg S: PEAK first where it has invoices, the sheet fills every gap -------
# Synthetic customers only: a contract status, a "done collection" row, PEAK invoices.

def _person(category=None, contract="ACTIVE", invoices=(), months=()):
    tracking = {"category": category, "months": list(months)} if category is not None else None
    return types.SimpleNamespace(
        contracts=[types.SimpleNamespace(uid="K-SYN-%s-%s" % (category, contract), status=contract)],
        sheet={"tracking": tracking, "peak": {"invoices": list(invoices)} if invoices else None})


def test_a_receipt_only_row_has_no_say_on_lateness():
    receipt = _row(receipt_only=True, due_on=None)
    assert cases._peak_says(_customer([receipt])) is None
    assert cases._payment_status(_person("Late", invoices=[receipt])) == "LATE"   # the sheet's LATE shows


def test_a_customer_only_the_sheet_knows_takes_the_done_collection_status():
    assert cases._payment_status(_person("Late")) == "LATE"               # contracts say CURRENT
    assert cases._payment_status(_person("Active", contract="PAST_DUE")) == "CURRENT"
    assert cases._payment_status(_person("NPL - Restructure")) == "NPL"
    assert cases._payment_status(_person("Delayed Installation")) == "NOT_INSTALLED"
    assert cases._payment_status(_person()) == "CURRENT"                  # no row: the contracts'


def test_an_unknown_word_keeps_the_contract_answer_and_is_flagged():
    person = _person("Service Issue", contract="PAST_DUE")
    assert cases.sheet_says(person) == (None, "Service Issue")
    assert cases._payment_status(person) == "LATE"


def test_what_the_contracts_decide_still_wins_over_peak_and_the_sheet():
    assert cases._payment_status(_person("Active", contract="NON_PERFORMING", invoices=[_row()])) == "NPL"
    assert cases._payment_status(_person("Late", contract="CLOSED")) == "CLOSED"


def test_peak_overrides_the_sheet_and_the_disagreement_is_listed_not_overwritten():
    months = [{"month": "Jan 2026", "cell": {"kind": "LATE"}}, {"month": "Feb 2026", "cell": {"kind": "PAID"}}]
    person = _person("Late", invoices=[_row(due_on="2026-01-15")], months=months)
    assert cases._payment_status(person) == "CURRENT"                     # PEAK: January is paid
    assert cases.status_disagreements(person) == [
        {"month": None, "peak": "CURRENT", "sheet": "LATE", "peak_off": False},
        {"month": "Jan 2026", "peak": "PAID", "sheet": "LATE"}]
    assert cases.sheet_status(person) == {"code": "LATE", "word": "Late", "unknown": False, "month": "Feb 2026"}
    # the month grid: PEAK's month where it billed one, else the sheet's cell
    assert [(m["month"], m["status"], m["source"]) for m in cases.month_status(person)] == [
        ("Jan 2026", "PAID", "PEAK"), ("Feb 2026", "PAID", "SHEET")]
    assert person.sheet["tracking"]["category"] == "Late" and months[0]["cell"] == {"kind": "LATE"}


def test_a_month_peak_has_not_judged_yet_is_no_disagreement():
    months = [{"month": "Dec 2099", "cell": {"kind": "LATE"}}]
    person = _person("Late", invoices=[_row(due_on="2099-12-15", status="AWAITING", amount_awaiting="10.00")],
                     months=months)
    # PEAK has not judged December yet (not due), so no month is listed; its current
    # answer (nothing past due) against the sheet's Late still is.
    assert [d["month"] for d in cases.status_disagreements(person)] == [None]


def test_with_peak_switched_off_the_status_follows_the_sheet_and_the_row_says_so(monkeypatch):
    from app.config import settings
    person = _person("Late", invoices=[_row(due_on="2026-01-15")])
    monkeypatch.setattr(settings, "peak_report_drives_status", False)
    assert cases._payment_status(person) == "LATE"
    assert cases.status_disagreements(person) == [
        {"month": None, "peak": "CURRENT", "sheet": "LATE", "peak_off": True}]
