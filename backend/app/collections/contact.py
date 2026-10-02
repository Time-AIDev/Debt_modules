"""REQ-COL-012/013/014/016 — contact logging and the daily slot.

Three properties of this module are LOCKED law and must not be softened:

1. `daily_contact_limit_per_customer` is 1 per customer per day.
2. `inbound_call_does_not_count` — no override, no Manager action and no configuration
   edit can make an inbound call count.
3. Manager and Owner may override with a logged reason. Officer AND Supervisor may not:
   "the daily limit is not a soft guideline that a persuasive officer can pass."

The lock is keyed on the CUSTOMER's identity, never on the contract. A customer holding
several contracts has one officer and receives one contact covering all of them.

⚠ There is no customer identity key in any live Volt data — the join key today is a
composite Volt ID and no citizen or juristic id exists anywhere upstream. `customer_key`
is that identity hash. Until Odoo supplies a real id this rule is unenforceable on real
data, which is why the prototype takes the key as an explicit argument rather than
deriving one.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

BANGKOK = ZoneInfo("Asia/Bangkok")

# Channels that can never consume the slot. The rule is a CHANNEL property, not a
# result property — an SMS with any disposition still counts for nothing.
COUNTING_CHANNELS = ("PHONE", "LINE")
CHANNELS = ("PHONE", "LINE", "SMS", "EMAIL", "VISIT", "LETTER")
DIRECTIONS = ("INBOUND", "OUTBOUND")


@dataclass(frozen=True)
class Disposition:
    code: str
    counts: bool
    raises_flag: bool = False
    # LINE_SENT_UNREAD becomes counting only when a READ callback arrives.
    counts_on_read: bool = False


# The closed dictionary of `contact_result`. Short codes, because the dictionary caps
# at 16 characters — the API worked examples use longer ones that do not fit (§12.2).
DISPOSITIONS = {
    d.code: d
    for d in (
        Disposition("ANS_DISCUSSED", counts=True),
        Disposition("ANS_NOT_DISC", counts=False),
        Disposition("VOICEMAIL", counts=False),
        Disposition("NO_ANSWER", counts=False),
        Disposition("BUSY", counts=False),
        Disposition("DISCONNECTED", counts=False),
        Disposition("WRONG_NUMBER", counts=False),
        Disposition("LINE_READ", counts=True),
        Disposition("LINE_SENT_UNREAD", counts=False, counts_on_read=True),
        Disposition("LINE_BLOCKED", counts=False, raises_flag=True),
        Disposition("INBOUND_CALLED", counts=False),
        # 2026-08-30 rebuild, additive: the flow's refuse-to-pay branch. The customer
        # was reached and the amount discussed (counts), and the refusal routes to
        # Manager Review (raises_flag) — flow part 3.
        Disposition("REFUSED_PAY", counts=True, raises_flag=True),
    )
}

OVERRIDE_ROLES = ("MANAGER", "OWNER")


class ContactLocked(Exception):
    code = "contact_locked"

    def __init__(self, blocked_by_lock_id):
        super().__init__("A counting contact already exists for this customer today.")
        self.blocked_by_lock_id = blocked_by_lock_id


class ContactOnHold(Exception):
    """Distinct from contact_locked on purpose. No lock row is created or consumed, so
    when the hold expires the customer's daily slot is intact and unused."""

    code = "contact_on_hold"


class OverrideReasonRequired(Exception):
    code = "override_reason_required"


class OverrideForbidden(Exception):
    code = "forbidden"


@dataclass
class Lock:
    lock_id: int
    customer_key: str
    lock_date: object
    level: str  # PERSON or CONTRACT
    ref: str
    # The lock is KEYED on the customer's identity, but an officer reading the board
    # needs to know WHO holds today's slot. Showing them the identity hash tells them
    # nothing they can act on.
    officer: str = None
    taken_at: object = None
    result: str = None


@dataclass
class ContactAttempt:
    contact_id: int
    customer_key: str
    contract_uids: list
    channel: str
    direction: str
    disposition: str
    at: datetime
    officer: str
    counted: bool
    lock_consumed: bool = False
    lock_id: Optional[int] = None
    blocked_by_lock_id: Optional[int] = None
    raises_flag: bool = False
    override: bool = False
    override_reason: Optional[str] = None
    retracted: bool = False
    # Round-4 J4-02: the officer declared this second contact of the day as not counted
    # — an honest audit row instead of "the customer called me".
    not_counted_declared: bool = False


def parse_timestamp(raw):
    """RFC 3339 with an explicit offset — and `Z` IS an explicit offset (§5.6), exactly
    +00:00. Python 3.9's `fromisoformat` does not accept it; that is a limitation of the
    runtime, not of the contract, so it is absorbed here. Rejecting `Z` would lock out
    every JavaScript client, since `Date.toISOString()` emits it by default.
    """
    if not isinstance(raw, str):
        raise ValueError("timestamp must be a string")
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError("timestamp must carry an explicit offset")
    return moment


def bangkok_day(moment: datetime):
    """Every lock query resolves the date in Asia/Bangkok, never the server default.
    A contact at 23:50 on the 23rd and one at 00:10 on the 24th are different days,
    even though both are 2026-10-23 in UTC."""
    return moment.astimezone(BANGKOK).date()


class ContactLog:
    def __init__(self):
        self.attempts = []
        self._locks = []
        self._holds = set()
        self._next_id = 1

    # -- queries ---------------------------------------------------------------

    def locks_for(self, customer_key, day, level=None):
        return [
            l
            for l in self._locks
            if l.customer_key == customer_key and l.lock_date == day and (level is None or l.level == level)
        ]

    def _person_lock(self, customer_key, day):
        found = self.locks_for(customer_key, day, level="PERSON")
        return found[0] if found else None

    # -- holds -----------------------------------------------------------------

    def open_contact_hold(self, customer_key):
        self._holds.add(customer_key)

    def close_contact_hold(self, customer_key):
        self._holds.discard(customer_key)

    # -- writes ----------------------------------------------------------------

    def _take_id(self):
        value = self._next_id
        self._next_id += 1
        return value

    def _create_locks(self, customer_key, contract_uids, day, officer=None,
                      taken_at=None, result=None):
        """Two stored levels, always. `contact_lock_levels` is LOCKED pending Legal and
        the two levels must not be optimised away, even though only PERSON is enforced."""
        lock_id = self._take_id()
        self._locks.append(
            Lock(lock_id, customer_key, day, "PERSON", customer_key, officer, taken_at, result)
        )
        for uid in contract_uids:
            self._locks.append(
                Lock(self._take_id(), customer_key, day, "CONTRACT", uid, officer, taken_at, result)
            )
        return lock_id

    def log_contact(self, customer_key, contract_uids, channel, direction, disposition,
                    at, officer, role, override=False, override_reason=None,
                    not_counted=False):
        if disposition not in DISPOSITIONS:
            raise ValueError(
                "unknown contact_result %r — the dictionary is closed; a typo must not "
                "silently uncount a real contact" % disposition
            )
        if channel not in CHANNELS:
            raise ValueError("unknown channel %r" % channel)
        if direction not in DIRECTIONS:
            raise ValueError("unknown direction %r" % direction)

        if customer_key in self._holds:
            raise ContactOnHold("Contact is on hold for this customer.")

        rule = DISPOSITIONS[disposition]
        # Counting needs all three to agree: an outbound direction, a counting channel
        # and a counting result. Inbound can never reach True by any route.
        would_count = rule.counts and direction == "OUTBOUND" and channel in COUNTING_CHANNELS
        # Round-4 J4-02: an officer may DECLARE a second contact today as not counted,
        # rather than mislabelling their own call as inbound to get it recorded. This
        # softens none of the three locked laws: no lock is taken, none is released,
        # and the day's slot stays spent by whoever spent it. It can only ever make a
        # row count LESS, and the declaration is written on the attempt.
        if not_counted:
            would_count = False

        day = bangkok_day(at)
        existing = self._person_lock(customer_key, day) if would_count else None

        if existing is not None:
            if override:
                if role not in OVERRIDE_ROLES:
                    raise OverrideForbidden(
                        "Only Manager and Owner may override the daily contact limit; %s may not." % role
                    )
                if not override_reason or not str(override_reason).strip():
                    # Nothing is written at all — not even the attempt row.
                    raise OverrideReasonRequired("An override requires a logged reason.")
                attempt = ContactAttempt(
                    contact_id=self._take_id(), customer_key=customer_key, contract_uids=list(contract_uids),
                    channel=channel, direction=direction, disposition=disposition, at=at, officer=officer,
                    counted=True, lock_consumed=False, blocked_by_lock_id=existing.lock_id,
                    override=True, override_reason=override_reason,
                )
                # No second lock row. The override is audited instead.
                self.attempts.append(attempt)
                return attempt

            # The attempt is still logged; the lock is not extended, duplicated or released.
            self.attempts.append(
                ContactAttempt(
                    contact_id=self._take_id(), customer_key=customer_key, contract_uids=list(contract_uids),
                    channel=channel, direction=direction, disposition=disposition, at=at, officer=officer,
                    counted=False, blocked_by_lock_id=existing.lock_id,
                )
            )
            raise ContactLocked(blocked_by_lock_id=existing.lock_id)

        lock_id = (
            self._create_locks(customer_key, contract_uids, day, officer, at, disposition)
            if would_count else None
        )
        attempt = ContactAttempt(
            contact_id=self._take_id(), customer_key=customer_key, contract_uids=list(contract_uids),
            channel=channel, direction=direction, disposition=disposition, at=at, officer=officer,
            counted=would_count, lock_consumed=would_count, lock_id=lock_id,
            raises_flag=rule.raises_flag, not_counted_declared=bool(not_counted),
        )
        self.attempts.append(attempt)
        return attempt

    def mark_line_read(self, contact_id, read_at):
        """The READ callback flips `counted` to true and takes the lock AT THE MOMENT
        OF THE READ, not at the moment of the send. A message sent at 10:00 and read at
        14:20 leaves a 12:00 call allowed and blocks one at 15:00."""
        attempt = next(a for a in self.attempts if a.contact_id == contact_id)
        day = bangkok_day(read_at)
        if self._person_lock(attempt.customer_key, day) is not None:
            return attempt  # the slot was already spent; the read does not take a second

        attempt.counted = True
        attempt.lock_consumed = True
        attempt.lock_id = self._create_locks(
            attempt.customer_key, attempt.contract_uids, day,
            attempt.officer, read_at, attempt.disposition,
        )
        return attempt

    def mark_contacted(self, customer_key, contract_uids, at, officer, role):
        """One activity covering every contract, one PERSON lock and one CONTRACT lock
        per contract, and exactly ONE slot spent."""
        return self.log_contact(
            customer_key=customer_key, contract_uids=contract_uids, channel="PHONE",
            direction="OUTBOUND", disposition="ANS_DISCUSSED", at=at, officer=officer, role=role,
        )


    def retract(self, customer_key, day):
        """REQ-COL-055 — give the slot back.

        The locks go; the ATTEMPT ROW STAYS, marked retracted. Erasing the attempt would
        lose the fact that a call was made, which is the opposite of an audit trail.
        """
        self._locks = [
            l for l in self._locks
            if not (l.customer_key == customer_key and l.lock_date == day)
        ]
        for attempt in self.attempts:
            if attempt.customer_key == customer_key and bangkok_day(attempt.at) == day:
                attempt.counted = False
                attempt.lock_consumed = False
                attempt.retracted = True


class SessionContactLog:
    """Judge J-12c: the daily lock was process-wide, so a second browser profile saw
    the first tester's locks. One ContactLog per `volt_session`, through the same
    session.Store the cases and journey stores use. Attribute access falls through
    to the current session's log, so `main.contact_log.locks_for(...)` reads as before."""

    def __init__(self):
        from ..session import Store
        self._store = Store(ContactLog, key="collections.contact.log")

    def for_current(self) -> ContactLog:
        return self._store.for_current()

    def reset(self):
        """Clears EVERY session. Test seam only."""
        self._store.reset()

    def __getattr__(self, name):
        return getattr(self._store.for_current(), name)
