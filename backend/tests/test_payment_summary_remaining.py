"""F03/F14 — `remaining_count` and `paid_count` on `payment_summary` (feedback-r2 TASK-102).

The case header prints "paid / total" and the remaining count; the client never
subtracts, so both figures are served per contract and in the totals. Every test
here is an ADDITION to the suite.
"""
from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)

LEASE_WITH_LATE = "sheet-99999000027"   # 96 cycles, 22 inferred paid per test_payment_summary.py
CASH_OVERDUE = "sheet-99999000297"        # the cash case the overview screenshots use
PAT1 = "sheet-99999000140"              # the customer the round-2 header test reads


def _summary(uid):
    response = client.get("/v1/cases/by-customer/%s" % uid)
    assert response.status_code == 200, response.text
    return response.json()["payment_summary"]


def test_a_lease_contract_serves_paid_count_and_remaining_count():
    summary = _summary(LEASE_WITH_LATE)
    (contract,) = summary["contracts"]
    assert contract["cycle_count"] == 96
    assert contract["counts"]["PAID"] == 0
    assert contract["counts"]["INFERRED_PAID"] == 22
    assert contract["paid_count"] == 0
    assert contract["remaining_count"] == 96
    assert contract["paid_count"] + contract["remaining_count"] == contract["cycle_count"]
    assert summary["totals"]["paid_count"] == 0
    assert summary["totals"]["remaining_count"] == 96


def test_the_totals_sum_the_per_contract_counts_never_recompute():
    for uid in (LEASE_WITH_LATE, CASH_OVERDUE, PAT1):
        summary = _summary(uid)
        assert summary["totals"]["paid_count"] == sum(c["paid_count"] for c in summary["contracts"])
        assert summary["totals"]["remaining_count"] == sum(c["remaining_count"] for c in summary["contracts"])
        assert summary["totals"]["paid_count"] + summary["totals"]["remaining_count"] == summary["totals"]["cycle_count"]


def test_customer_scorecard_counts_inferred_paid_without_confirming_payment():
    summary = _summary(LEASE_WITH_LATE)
    instalments = summary['totals']['breakdown']['instalment']
    assert instalments['display_paid_count'] == 22
    assert instalments['unverified_paid_count'] == 22
    assert instalments['display_remaining_count'] == 74
    assert summary['totals']['paid_count'] == 0
    assert summary['totals']['paid_amount'] == '0.00'


def test_scorecard_counts_only_paid_reports_and_excludes_deposit():
    from app import payment_summary
    cycles = [{'kind': kind, 'status': status, 'payment_evidence': 'UNCONFIRMED'}
              for kind, status in [('DEPOSIT', 'PAID'), ('INSTALMENT', 'PAID'),
                                   ('INSTALMENT', 'INFERRED_PAID'), ('INSTALMENT', 'SHEET_REPORTED_PAID'),
                                   ('INSTALMENT', 'UNCONFIRMED'), ('INSTALMENT', 'OVERDUE'),
                                   ('INSTALMENT', 'UPCOMING')]]
    counts = payment_summary._breakdown(cycles)['instalment']
    assert counts['count'] == 6
    assert counts['display_paid_count'] == 3
    assert counts['unverified_paid_count'] == 2
    assert counts['display_remaining_count'] == 3
    assert counts['counts']['PAID'] == 1


def test_paid_cash_balance_from_sheet_is_still_pending_evidence_in_scorecard():
    from app import payment_summary
    rows = [{'kind': 'BALANCE', 'status': 'PAID', 'source': 'SHEET_DERIVED'}]
    count = payment_summary._breakdown(rows)['instalment']
    assert count['display_paid_count'] == 1
    assert count['unverified_paid_count'] == 1
    assert count['display_remaining_count'] == 0
