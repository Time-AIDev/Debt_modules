"""Accounting NPL assessment from Amendment v2.6.

Classification is deliberately separate from NPL type and recovery strategy.  The
former is mechanical; the latter two remain Manager/Owner decisions.
"""
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, Optional

from .money.dpd import compute_dpd


ASSESSMENT_HOLD_STATES = frozenset({"SERVICE_HOLD_FAULT_CONFIRMED"})


@dataclass(frozen=True)
class Assessment:
    actual_dpd: int
    missed_instalments: int
    restructured: bool
    automatic_npl: bool
    needs_review: bool
    assessment_hold: bool
    reason: Optional[str]
    label_th: Optional[str] = None
    label_en: Optional[str] = None


def assess(
    contracts: Iterable,
    *,
    as_of: date,
    contacts: Iterable[dict] = (),
    field_of: Optional[Callable] = None,
) -> Assessment:
    """Assess a customer's active schedules without mutating any workflow state.

    ``actual_dpd`` intentionally ignores clock-freezing holds.  A qualifying hold
    suppresses NPL assessment but never hides how late the debt really is.
    """
    field_of = field_of or (lambda contract, field: getattr(contract, field, None))
    max_dpd = 0
    max_missed = 0
    restructured = False
    assessment_hold = False

    for contract in contracts:
        lines = list(field_of(contract, "instalments") or ())
        max_dpd = max(max_dpd, compute_dpd(lines, as_of=as_of, frozen_days=0) or 0)
        missed = sum(
            1 for line in lines
            if line.is_active_regular and line.due_date < as_of and line.outstanding_amount > 0
        )
        max_missed = max(max_missed, missed)
        restructured = restructured or any(
            getattr(line, "schedule_status", None) == "SUPERSEDED" for line in lines
        )
        assessment_hold = assessment_hold or (
            field_of(contract, "fee_state") in ASSESSMENT_HOLD_STATES
        )

    two_restructured_misses = restructured and max_missed >= 2
    threshold_met = max_dpd >= 90 or two_restructured_misses
    counted_contact = any(bool(row.get("counted")) for row in contacts)
    automatic_npl = threshold_met and not assessment_hold
    needs_review = (
        (max_dpd >= 60 or max_missed >= 2)
        and not counted_contact
        and not assessment_hold
    )
    reason = None
    if automatic_npl:
        reason = "RESTRUCTURED_TWO_MISSES" if two_restructured_misses else "DPD_90_PLUS"

    return Assessment(
        actual_dpd=max_dpd,
        missed_instalments=max_missed,
        restructured=restructured,
        automatic_npl=automatic_npl,
        needs_review=needs_review,
        assessment_hold=assessment_hold,
        reason=reason,
        label_th="พักประเมิน NPL" if assessment_hold else None,
        label_en="NPL assessment paused" if assessment_hold else None,
    )
