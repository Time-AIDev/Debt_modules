"""The record's risk score (Delta-100 D2a).

The Final v2 prototype shows a 0-100 "คะแนนความเสี่ยง" on the customer record and
draws severity edges from a per-row score. The backend never modelled one; this
computes it from signals the system already holds, so every screen can serve the
same number:

  dpd        the worst days-past-due under the customer (0..120 caps the weight)
  arrears    overdue amount vs outstanding, as a share
  broken     broken promises to pay (0..3 caps the weight)
  recency    days since the last contact (14+ caps the weight; unknown = 14+)

The four weights live in Settings (risk_weight_*), so the score can be tuned
without a release. The result is clipped to 0..100.
"""
from decimal import Decimal

from .config import settings

DPD_CAP = 120
BROKEN_CAP = 3
RECENCY_CAP = 14


def score(*, dpd=None, arrears=None, outstanding=None, broken_ptps=0, days_since_contact=None):
    """Return the 0..100 risk score for one case/customer."""
    total = Decimal("0")

    if dpd is not None and dpd > 0:
        total += Decimal(min(dpd, DPD_CAP)) / DPD_CAP * settings.risk_weight_dpd

    if arrears is not None and outstanding is not None and outstanding > 0:
        share = min(Decimal(arrears) / Decimal(outstanding), Decimal("1"))
        total += share * settings.risk_weight_arrears

    if broken_ptps and broken_ptps > 0:
        total += Decimal(min(broken_ptps, BROKEN_CAP)) / BROKEN_CAP * settings.risk_weight_broken_ptp

    days = RECENCY_CAP if days_since_contact is None else min(max(int(days_since_contact), 0), RECENCY_CAP)
    total += Decimal(days) / RECENCY_CAP * settings.risk_weight_recency

    return int(max(Decimal("0"), min(total, Decimal("100"))).to_integral_value())
