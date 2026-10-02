"""REQ-MNY-032 / REQ-MNY-033 — the fee and the lateness clock are SEPARATE rules.

v1.0 moved them together: PENALTY_SERVICE_HOLD "suspends penalty accrual and DPD
counting", one boolean. Amendment v2.4 splits them, because "they are different
columns because they are different facts".

Every screen and every job must READ this table. Nothing may derive pause behaviour
from a hold type — that is the entire point of REQ-MNY-032.
"""
import pytest

from app.money.fee_states import FEE_STATES, stops_clock, stops_fee


def test_a_permit_hold_pauses_the_fee_but_not_the_clock():
    """G7, amending D13: 'A permit hold pauses the fee and does not pause the clock.
    D13 becomes two rules.'

    The consequence is the sharp one: a customer can drift toward NPL on an MEA/PEA
    delay while no fee accrues and no officer is measured on it.
    """
    assert stops_fee("PERMIT_HOLD") is True
    assert stops_clock("PERMIT_HOLD") is False


def test_a_confirmed_service_fault_stops_both():
    assert stops_fee("SERVICE_HOLD_FAULT_CONFIRMED") is True
    assert stops_clock("SERVICE_HOLD_FAULT_CONFIRMED") is True


def test_a_dispute_does_not_pause_the_fee():
    """REQ-MNY-033. G9 originally paused it; G13 reversed that.

    'A pause on complaint makes a complaint worth money, and word of that travels
    faster than any collections letter.'
    """
    assert stops_fee("DISPUTE_UNDER_REVIEW") is False
    assert stops_clock("DISPUTE_UNDER_REVIEW") is False


def test_a_pending_claim_pauses_nothing():
    assert stops_fee("CLAIM_PENDING") is False
    assert stops_clock("CLAIM_PENDING") is False


def test_exactly_five_states_stop_the_fee_and_exactly_one_stops_the_clock():
    """§3.1 of the delta brief: 'Six states pause the fee' is wrong — it is five."""
    assert sum(1 for s in FEE_STATES.values() if s.stops_fee) == 5
    assert sum(1 for s in FEE_STATES.values() if s.stops_clock) == 1


def test_the_other_three_fee_pausing_states_are_present():
    for state in ("DECEASED", "PROPERTY_SOLD_NOVATION_UNRESOLVED", "JURISTIC_DISSOLVED"):
        assert stops_fee(state) is True
        assert stops_clock(state) is False


def test_an_unknown_state_is_refused_rather_than_defaulted():
    """A state that is not in the governed table must not silently pause nothing —
    that would be a consumer deriving behaviour, which REQ-MNY-032 forbids."""
    with pytest.raises(KeyError):
        stops_fee("SOME_HOLD_SOMEONE_INVENTED")
