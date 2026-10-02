from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.money.models import Instalment
from app.npl_assessment import assess
from app import cases


AS_OF = date(2026, 10, 23)


def _line(days, *, status="ACTIVE"):
    return Instalment(
        due_date=AS_OF - timedelta(days=days),
        category="REGULAR",
        principal_amount=Decimal("100.00"),
        interest_amount=Decimal("0.00"),
        schedule_status=status,
    )


def _contract(*lines, fee_state=None):
    return SimpleNamespace(uid="k-1", instalments=list(lines), fee_state=fee_state)


@pytest.mark.parametrize(("dpd", "automatic", "review"), [
    (0, False, False),
    (1, False, False),
    (30, False, False),
    (31, False, False),
    (60, False, True),
    (61, False, True),
    (89, False, True),
    (90, True, True),
])
def test_v26_dpd_boundaries(dpd, automatic, review):
    lines = [] if dpd == 0 else [_line(dpd)]

    result = assess([_contract(*lines)], as_of=AS_OF, contacts=[])

    assert result.actual_dpd == dpd
    assert result.automatic_npl is automatic
    assert result.needs_review is review


def test_two_misses_only_trigger_automatic_npl_on_a_restructured_schedule():
    ordinary = assess([_contract(_line(10), _line(5))], as_of=AS_OF, contacts=[])
    restructured = assess([
        _contract(_line(100, status="SUPERSEDED"), _line(10), _line(5))
    ], as_of=AS_OF, contacts=[])

    assert ordinary.automatic_npl is False
    assert ordinary.needs_review is True
    assert restructured.automatic_npl is True
    assert restructured.reason == "RESTRUCTURED_TWO_MISSES"


def test_counted_contact_clears_the_60_day_review_but_not_automatic_npl():
    result = assess(
        [_contract(_line(70))],
        as_of=AS_OF,
        contacts=[{"counted": True, "occurred_at": "2026-10-20T09:00:00+07:00"}],
    )

    assert result.needs_review is False
    assert result.automatic_npl is False


def test_assessment_hold_keeps_actual_dpd_visible_and_suppresses_npl():
    result = assess(
        [_contract(_line(120), fee_state="SERVICE_HOLD_FAULT_CONFIRMED")],
        as_of=AS_OF,
        contacts=[],
    )

    assert result.actual_dpd == 120
    assert result.automatic_npl is False
    assert result.needs_review is False
    assert result.assessment_hold is True
    assert result.label_th == "พักประเมิน NPL"


def test_automatic_accounting_npl_wins_over_peak_status():
    contract = _contract(_line(90))
    contract.status = "PAST_DUE"
    customer = SimpleNamespace(
        contracts=[contract],
        sheet={"peak": {"invoices": [{
            "status": "PAID", "amount_awaiting": "0", "due_on": "2026-09-01"
        }]}},
    )

    assert cases.payment_status_with_source(customer) == ("NPL", "CONTRACT")


def test_threshold_review_is_queued_without_consuming_the_case_workflow_slot():
    state = cases.for_current()
    review = next(row for row in state.reviews.values() if row["reason"] == "NPL_REVIEW")
    case = state.cases[review["customer_uid"]]

    assert review["blocking"] is False
    assert case["npl_review_uid"] == review["uid"]
    assert case["review_uid"] != review["uid"]
