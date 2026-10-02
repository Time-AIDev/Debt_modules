"""REQ-COL-012 / 013 / 014 — the daily contact slot.

`daily_contact_limit_per_customer` = 1 per customer per day, outbound with the amount
discussed, keyed on the CUSTOMER's identity, never on the contract. LOCKED law.

The day is the Asia/Bangkok calendar day, not the server's.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.collections.contact import (
    ContactLocked,
    ContactLog,
    ContactOnHold,
    OverrideForbidden,
    OverrideReasonRequired,
)

BKK = ZoneInfo("Asia/Bangkok")
CUSTOMER = "identity:hash:C-000871"


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=BKK)


@pytest.fixture
def log():
    return ContactLog()


def test_outbound_answered_with_the_amount_discussed_counts_and_consumes_the_slot(log):
    result = log.log_contact(
        customer_key=CUSTOMER,
        contract_uids=["K-1"],
        channel="PHONE",
        direction="OUTBOUND",
        disposition="ANS_DISCUSSED",
        at=at(2026, 10, 23, 9, 10),
        officer="noon",
        role="OFFICER",
    )
    assert result.counted is True
    assert result.lock_consumed is True


def test_answered_but_not_discussed_does_not_count_and_the_officer_may_retry(log):
    first = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_NOT_DISC", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    assert first.counted is False

    retry = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 11, 5), officer="noon", role="OFFICER",
    )
    assert retry.counted is True


def test_an_inbound_call_never_counts_and_is_unlimited(log):
    """`inbound_call_does_not_count` is LOCKED LAW — no override, no Manager action
    and no configuration edit can make an inbound call count."""
    for hour in (9, 10, 11, 12):
        result = log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="INBOUND",
            disposition="INBOUND_CALLED", at=at(2026, 10, 23, hour, 0), officer="noon", role="OFFICER",
        )
        assert result.counted is False
        assert result.lock_consumed is False


def test_a_second_counting_contact_the_same_day_is_refused(log):
    log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    with pytest.raises(ContactLocked) as exc:
        log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
            disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 15, 0), officer="ploy", role="OFFICER",
        )
    assert exc.value.code == "contact_locked"


def test_one_channel_is_not_a_way_around_another(log):
    """TC-COL-031: a phone call at 09:10 blocks a LINE message at 11:05."""
    log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    with pytest.raises(ContactLocked):
        log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="LINE", direction="OUTBOUND",
            disposition="LINE_READ", at=at(2026, 10, 23, 11, 5), officer="noon", role="OFFICER",
        )


def test_an_unsuccessful_attempt_is_still_logged_and_does_not_extend_the_lock(log):
    first = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    try:
        log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
            disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 15, 0), officer="ploy", role="OFFICER",
        )
    except ContactLocked as exc:
        assert exc.blocked_by_lock_id == first.lock_id

    blocked = [a for a in log.attempts if a.blocked_by_lock_id]
    assert len(blocked) == 1
    assert len(log.locks_for(CUSTOMER, at(2026, 10, 23, 9, 10).date(), level="PERSON")) == 1


def test_a_counting_contact_writes_both_a_person_and_a_contract_lock(log):
    """`contact_lock_levels` is LOCKED pending Legal: 'the two levels must not be
    optimised away'. Both rows are always stored even when only PERSON is enforced."""
    log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1", "K-2"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    day = at(2026, 10, 23, 9, 10).date()

    assert len(log.locks_for(CUSTOMER, day, level="PERSON")) == 1
    assert len(log.locks_for(CUSTOMER, day, level="CONTRACT")) == 2


def test_the_day_boundary_is_bangkok_not_utc(log):
    """TC-COL-037: 23:50 on the 23rd and 00:10 on the 24th are BOTH allowed, even
    though both fall on 2026-10-23 in UTC."""
    log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 23, 50), officer="noon", role="OFFICER",
    )
    second = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 24, 0, 10), officer="noon", role="OFFICER",
    )
    assert second.counted is True


def test_line_counts_at_read_time_not_at_send_time(log):
    """§8.5: the row is created with counted false; the READ callback flips it to true
    and takes the lock AT THE MOMENT OF THE READ.

    TC-COL-027: sent 10:00, read 14:20 — a call at 12:00 is allowed, one at 15:00 is not.
    """
    sent = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="LINE", direction="OUTBOUND",
        disposition="LINE_SENT_UNREAD", at=at(2026, 10, 23, 10, 0), officer="noon", role="OFFICER",
    )
    assert sent.counted is False

    midday_call = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_NOT_DISC", at=at(2026, 10, 23, 12, 0), officer="noon", role="OFFICER",
    )
    assert midday_call.counted is False

    log.mark_line_read(sent.contact_id, read_at=at(2026, 10, 23, 14, 20))

    with pytest.raises(ContactLocked):
        log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
            disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 15, 0), officer="noon", role="OFFICER",
        )


def test_a_blocked_line_message_raises_a_flag_on_the_customer(log):
    result = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="LINE", direction="OUTBOUND",
        disposition="LINE_BLOCKED", at=at(2026, 10, 23, 10, 0), officer="noon", role="OFFICER",
    )
    assert result.counted is False
    assert result.raises_flag is True


def test_sms_and_email_never_count_because_the_rule_is_a_channel_property(log):
    for channel in ("SMS", "EMAIL"):
        result = log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel=channel, direction="OUTBOUND",
            disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 10, 0), officer="noon", role="OFFICER",
        )
        assert result.counted is False, channel


def test_a_manager_override_without_a_reason_writes_nothing(log):
    log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    before = len(log.attempts)

    with pytest.raises(OverrideReasonRequired):
        log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
            disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 15, 0), officer="mana", role="MANAGER",
            override=True,
        )
    assert len(log.attempts) == before


def test_a_manager_override_with_a_reason_creates_no_second_lock_row(log):
    log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    result = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 15, 0), officer="mana", role="MANAGER",
        override=True, override_reason="Customer called back asking for a settlement figure",
    )
    day = at(2026, 10, 23, 9, 10).date()

    assert result.override is True
    assert len(log.locks_for(CUSTOMER, day, level="PERSON")) == 1


def test_a_supervisor_may_not_override(log):
    """'The daily limit is not a soft guideline that a persuasive officer can pass.'
    Manager and Owner only — Officer AND Supervisor both get 403."""
    log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    with pytest.raises(OverrideForbidden):
        log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
            disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 15, 0), officer="sup", role="SUPERVISOR",
            override=True, override_reason="I would like to try again",
        )


def test_a_contact_hold_is_distinct_from_a_lock_and_leaves_the_slot_intact(log):
    """'When the hold expires the customer's daily slot is intact and unused, so the
    hold has not silently spent it.'"""
    log.open_contact_hold(CUSTOMER)

    with pytest.raises(ContactOnHold) as exc:
        log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
            disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
        )
    assert exc.value.code == "contact_on_hold"

    log.close_contact_hold(CUSTOMER)
    result = log.log_contact(
        customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
        disposition="ANS_DISCUSSED", at=at(2026, 10, 23, 10, 0), officer="noon", role="OFFICER",
    )
    assert result.lock_consumed is True


def test_mark_as_contacted_covers_every_contract_but_spends_exactly_one_slot(log):
    result = log.mark_contacted(
        customer_key=CUSTOMER, contract_uids=["K-1", "K-2", "K-3"],
        at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
    )
    day = at(2026, 10, 23, 9, 10).date()

    assert result.counted is True
    assert len(log.locks_for(CUSTOMER, day, level="PERSON")) == 1
    assert len(log.locks_for(CUSTOMER, day, level="CONTRACT")) == 3


def test_an_unknown_disposition_is_refused_rather_than_treated_as_not_counting(log):
    """`contact_result` is a CLOSED dictionary. Silently treating an unknown value as
    'does not count' would let a typo uncount a real contact."""
    with pytest.raises(ValueError):
        log.log_contact(
            customer_key=CUSTOMER, contract_uids=["K-1"], channel="PHONE", direction="OUTBOUND",
            disposition="TALKED_TO_HIM", at=at(2026, 10, 23, 9, 10), officer="noon", role="OFFICER",
        )
