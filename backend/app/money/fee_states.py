"""REQ-MNY-032 — the governed state table.

The single most important property of this module: it is a TABLE, not logic. Every
screen and every job reads pause behaviour from here. Nothing anywhere may derive it
from a hold type, because `stops_clock` and `stops_fee` "are different columns because
they are different facts" (Amendment v2.4 §3).

v1.0 had one boolean and three hold types, and moved the fee and the clock together.
That is now wrong in a way that matters: an unreleased PERMIT hold freezes nothing —
it suppresses collection on an account that keeps accruing DPD. An engineer reading
the old v1.0 line during a hold-expiry failure would look for a frozen clock, not
find one, and wrongly conclude the job was fine.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FeeState:
    code: str
    label: str
    stops_clock: bool
    stops_fee: bool


FEE_STATES = {
    s.code: s
    for s in (
        FeeState("SERVICE_HOLD_FAULT_CONFIRMED", "Service hold, fault confirmed", True, True),
        # The fourth hold type. v1.0 locks the list at three; the amendment adds this one.
        FeeState("PERMIT_HOLD", "Permit hold, authority awaited", False, True),
        FeeState("DECEASED", "Deceased flag set", False, True),
        FeeState("PROPERTY_SOLD_NOVATION_UNRESOLVED", "Property sold, novation unresolved", False, True),
        FeeState("JURISTIC_DISSOLVED", "Juristic customer dissolved", False, True),
        # REQ-MNY-033. G9 paused the fee on a dispute; G13 reversed it, because
        # "a pause on complaint makes a complaint worth money, and word of that
        # travels faster than any collections letter."
        FeeState("DISPUTE_UNDER_REVIEW", "Dispute or complaint under review", False, False),
        FeeState("CLAIM_PENDING", "Claim pending", False, False),
    )
}


def stops_fee(state_code: str) -> bool:
    """KeyError on an unknown state, deliberately. A state absent from the table must
    not silently resolve to 'pauses nothing' — that is a consumer deriving behaviour."""
    return FEE_STATES[state_code].stops_fee


def stops_clock(state_code: str) -> bool:
    return FEE_STATES[state_code].stops_clock
