"""REQ-MNY-015 / REQ-MNY-016 — DPD and the aging bucket.

Calendar days only. `day_count_basis` is seeded CALENDAR and business days never
touch DPD or penalty — they exist only for SLA columns (Data_Model.md:4506).
"""
from datetime import date
from decimal import Decimal

from app.money.dpd import aging_bucket, compute_dpd
from app.money.models import Instalment

FIRST_DUE = date(2026, 10, 1)


def regular(due_date, paid=Decimal("0")):
    """One FX-C1 line: 4,000.00 principal + 1,580.00 interest = 5,580.00."""
    return Instalment(
        due_date=due_date,
        category="REGULAR",
        principal_amount=Decimal("4000.00"),
        interest_amount=Decimal("1580.00"),
        fee_amount=Decimal("0.00"),
        paid_principal=paid,
    )


def test_dpd_is_today_minus_the_due_date_of_the_oldest_unpaid_instalment():
    """FX-ARR-1: due 2026-10-01, as of 2026-10-23, is DPD 22."""
    assert compute_dpd([regular(FIRST_DUE)], as_of=date(2026, 10, 23)) == 22


def test_dpd_is_none_not_zero_when_the_status_does_not_apply_dpd():
    """REQ-MNY-013: 'zero is a valid value distinct from null'.

    TC-MNY-043 makes this a failing test — a report that renders NULL as 0 fails.
    """
    assert compute_dpd([regular(FIRST_DUE)], as_of=date(2026, 10, 23), dpd_applies=False) is None


def test_a_part_paid_instalment_still_drives_dpd():
    """TC-MNY-045: 5,000.00 against a 5,580.00 line leaves DPD 22, because 580.00 remains.

    'Sufficient payment' means outstanding_amount on the REGULAR line is zero.
    """
    line = regular(FIRST_DUE, paid=Decimal("5000.00"))
    assert line.outstanding_amount == Decimal("580.00")
    assert compute_dpd([line], as_of=date(2026, 10, 23)) == 22


def test_only_a_regular_line_drives_dpd():
    """TC-MNY-050: an unpaid billed PENALTY line leaves DPD 0 and the bucket Current."""
    penalty_line = Instalment(
        due_date=FIRST_DUE,
        category="PENALTY",
        principal_amount=Decimal("0.00"),
        interest_amount=Decimal("0.00"),
        fee_amount=Decimal("133.92"),
    )
    assert compute_dpd([penalty_line], as_of=date(2026, 10, 23)) == 0


def test_frozen_days_are_subtracted_from_dpd():
    """REQ-MNY-023: a pending service issue freezes the clock."""
    assert compute_dpd([regular(FIRST_DUE)], as_of=date(2026, 10, 23), frozen_days=10) == 12


def test_a_full_reset_is_expressed_as_reset_days_so_there_is_one_subtraction_path():
    """TC-MNY-047: a FULL reset records dpd_reset_days equal to the days accrued."""
    assert compute_dpd([regular(FIRST_DUE)], as_of=date(2026, 10, 23), reset_days=22) == 0


def test_dpd_never_goes_negative():
    assert compute_dpd([regular(FIRST_DUE)], as_of=date(2026, 10, 23), reset_days=99) == 0


# --- aging buckets, REQ-MNY-016 -------------------------------------------------

def test_bucket_boundaries_leave_no_dpd_between_two_buckets_or_in_none():
    """TC-MNY-051 asserts exactly these seven values."""
    assert aging_bucket("PAST_DUE", 0) == "CURRENT"
    assert aging_bucket("PAST_DUE", 1) == "EARLY_OVERDUE"
    assert aging_bucket("PAST_DUE", 7) == "EARLY_OVERDUE"
    assert aging_bucket("PAST_DUE", 8) == "MID_OVERDUE"
    assert aging_bucket("PAST_DUE", 29) == "MID_OVERDUE"
    assert aging_bucket("PAST_DUE", 30) == "RISK_REVIEW"
    assert aging_bucket("PAST_DUE", 31) == "RISK_REVIEW"


def test_status_overrides_the_number():
    """TC-MNY-052: fn_aging_bucket reads the status override FIRST."""
    assert aging_bucket("NON_PERFORMING", 45) == "NPL_CONFIRMED"
    assert aging_bucket("WRITTEN_OFF", 120) == "CLOSED"
    assert aging_bucket("SETTLED", 0) == "RESOLVED"


def test_pre_collection_has_a_null_bucket_not_current():
    """TC-MNY-052 again — the trap this test exists to catch."""
    assert aging_bucket("PRE_COLLECTION", None) is None
