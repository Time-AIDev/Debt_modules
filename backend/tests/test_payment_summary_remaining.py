"""F03/F14 — `remaining_count` and `paid_count` on `payment_summary` (feedback-r2 TASK-102).

The case header prints "paid / total" and the remaining count; the client never
subtracts, so both figures are served per contract and in the totals. Every test
here is an ADDITION to the suite.
"""
from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)

LEASE_WITH_LATE = "sheet-99999000027"   # 96 cycles, 22 PAID per test_payment_summary.py
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
    assert contract["counts"]["PAID"] == 22
    assert contract["paid_count"] == 22
    assert contract["remaining_count"] == 74
    assert contract["paid_count"] + contract["remaining_count"] == contract["cycle_count"]
    assert summary["totals"]["paid_count"] == 22
    assert summary["totals"]["remaining_count"] == 74


def test_the_totals_sum_the_per_contract_counts_never_recompute():
    for uid in (LEASE_WITH_LATE, CASH_OVERDUE, PAT1):
        summary = _summary(uid)
        assert summary["totals"]["paid_count"] == sum(c["paid_count"] for c in summary["contracts"])
        assert summary["totals"]["remaining_count"] == sum(c["remaining_count"] for c in summary["contracts"])
        assert summary["totals"]["paid_count"] + summary["totals"]["remaining_count"] == summary["totals"]["cycle_count"]
