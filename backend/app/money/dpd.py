"""REQ-MNY-015 — days past due, and REQ-MNY-016 — the aging bucket.

Mirrors money.fn_dpd (Data_Model.md:3906) exactly:

    dpd = GREATEST(0, (as_of - oldest_due) - frozen_days - reset_days)

There is exactly ONE subtraction path. A FULL reset is recorded as reset_days equal
to the days accrued rather than as a separate branch, "so the arithmetic stays uniform".
"""
from typing import Optional

# ref.aging_bucket, seeded reference data. A change to these boundaries is a
# MIGRATION, not a panel edit — Spec §22 does not mark them configurable.
# The ranges cannot overlap; the database enforces that with a gist EXCLUDE constraint.
BANDS = (
    (0, 0, "CURRENT"),
    (1, 7, "EARLY_OVERDUE"),
    (8, 29, "MID_OVERDUE"),
    (30, None, "RISK_REVIEW"),
)

# ref.contract_status.aging_bucket_override — read FIRST, before the numeric band.
# Status wins over the number: NON_PERFORMING at DPD 45 is NPL Confirmed, not Risk Review.
STATUS_OVERRIDE = {
    "NON_PERFORMING": "NPL_CONFIRMED",
    "SETTLED": "RESOLVED",
    "RESTRUCTURED": "RESOLVED",
    "WRITTEN_OFF": "CLOSED",
    "CANCELLED": "CLOSED",
    # 2026-09-20: an ended contract is off the collection bands like the others. The
    # CASE-level status keeps CLOSED and TERMINATED apart (`cases.py`); this band is
    # only about which rung of the ladder the DPD no longer climbs.
    "TERMINATED": "CLOSED",
}

# Statuses where DPD does not apply at all. The result is NULL, not 0 — REQ-MNY-013
# calls zero "a valid value distinct from null", and TC-MNY-043 fails any report that
# renders NULL as 0.
DPD_DOES_NOT_APPLY = ("PENDING_ACTIVATION", "PRE_COLLECTION")


def compute_dpd(instalments, as_of, dpd_applies=True, frozen_days=0, reset_days=0) -> Optional[int]:
    if not dpd_applies:
        return None

    # Only a REGULAR line on the ACTIVE schedule drives DPD. A billed PENALTY line
    # left unpaid does not (TC-MNY-050) — the arrears block shows it separately so
    # the officer is not misled.
    overdue = [
        i.due_date
        for i in instalments
        if i.is_active_regular and i.due_date < as_of and i.outstanding_amount > 0
    ]
    if not overdue:
        return 0

    elapsed = (as_of - min(overdue)).days
    return max(0, elapsed - frozen_days - reset_days)


def aging_bucket(status, dpd) -> Optional[str]:
    if status in STATUS_OVERRIDE:
        return STATUS_OVERRIDE[status]
    if dpd is None:
        return None
    for low, high, code in BANDS:
        if dpd >= low and (high is None or dpd <= high):
            return code
    return None
