"""Cases — the officer's unit of work (Requirements Amendment v2.6 §3.1–3.8).

One case per customer in collection. It carries the two statuses (payment_status
computed, dc_status human), the mandatory next action, the promise counts, the
holds, the power state and the review pointer. State is per tester session
(session.Store) and is seeded from the migrated book, so the sheet's own PTP
dates, DC statuses, NPL types and MapLog rows appear on day one.

Rules encoded here:
  REQ-COL-070  no case without a next action — set_next_action refuses blanks;
               a PTP, an issue or a review sets one automatically.
  REQ-COL-073  broken/kept/renegotiation counts are computed, never typed.
  REQ-COL-075  payment_status and dc_status are two fields; neither derives the other.
  REQ-MOD-040  power restriction is requested, approved, executed, restored — logged.
  REQ-COL-076  a service issue carries its ticket and its closure returns to Today.
"""
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from . import termination_archive
from . import clock
from . import dictionaries
from . import errors
from . import payment_overrides
from .config import settings
from .session import Store

NEXT_ACTION_AUTO = {
    "PTP": "FOLLOW_PTP", "ISSUE": "AWAIT_TICKET", "REVIEW": "AWAIT_REVIEW", "PEAK": "AWAIT_PEAK",
}
POWER_STATES = ("ON", "RESTRICTION_REQUESTED", "RESTRICTION_APPROVED", "RESTRICTED", "RESTORE_DUE")
# Round-3 J3-06: the only two answers a POWER_CUTOFF_ASK review takes.
POWER_DECISIONS = ("POWER_CUTOFF_APPROVE", "POWER_CUTOFF_REJECT")
# Spec 2026-09-09: the only two answers a BOARD_MOVE_ASK review takes. Deliberately not
# POWER_DECISIONS — cutting a customer's power is not an answer to a board request.
BOARD_DECISIONS = ("BOARD_MOVE_APPROVE", "BOARD_MOVE_REJECT")
ROLE_LABEL_TH = {"OFFICER": "เจ้าหน้าที่", "SUPERVISOR": "หัวหน้างาน", "MANAGER": "ผู้จัดการ",
                 "OWNER": "เจ้าของ", "OPS": "ทีมปฏิบัติการ (O&M)"}
# Round-2 settasak S2-08: the case's power line read "รออนุมัติ" after the Owner approved.
POWER_STATE_LABEL_TH = {
    "ON": "จ่ายไฟปกติ", "RESTRICTION_REQUESTED": "ขอตัดไฟแล้ว รออนุมัติ",
    "RESTRICTION_APPROVED": "อนุมัติตัดไฟแล้ว รอดำเนินการ", "RESTRICTED": "ตัดไฟแล้ว",
    "RESTORE_DUE": "มีเงินเข้า ถึงกำหนดคืนไฟ",
}
POWER_STATE_LABEL_EN = {
    "ON": "Power on", "RESTRICTION_REQUESTED": "Cut-off requested, awaiting approval",
    "RESTRICTION_APPROVED": "Cut-off approved, awaiting execution", "RESTRICTED": "Power cut off",
    "RESTORE_DUE": "Payment received, power due to be restored",
}
# Round-2 nantapol N2-09 / thip T2-15: DC statuses a PERSON sets that no contact result
# may overwrite; every other status follows what is logged (derive_dc_status).
GOVERNED_DC_STATUSES = ("POWER_CUTOFF", "LEGAL_LETTER", "RESTRUCTURE_LOAN", "RETRIEVE_ASSET",
                        "TERMINATE_CONTRACT", "VISIT_CUSTOMER")
# Arina, 2026-09-14 (spec 2026-09-14-payment-status-adjustment-design.md): the five
# values REQ-COL-075 names. A person may now choose one, with a reason.
# 2026-09-20 (Closed/Terminated ruling): "five" became six — TERMINATED is its own
# status, because CLOSED must mean paid per the terms and nothing else. The five
# still work exactly as before; TERMINATED is set by the terminate act, not by the
# generic payment-status route (set_payment_status refuses it), so the cause can
# never be bypassed.
MANUAL_PAYMENT_STATUSES = ("CURRENT", "LATE", "NPL", "CLOSED", "TERMINATED", "NOT_INSTALLED")
PAYMENT_STATUSES = MANUAL_PAYMENT_STATUSES + ("PENDING",)
# Contract statuses that mean nothing is left to collect. CLOSED is paid-off; every
# other member is an ENDED contract (a written-off default, a repossession, a
# customer's requested termination). `_payment_status_from_contracts` keeps the two
# apart: a customer whose contracts all read CLOSED is "ปิด", anyone else here is
# "ยุติสัญญา". Before this, WRITTEN_OFF was served as CLOSED and every default
# termination hid behind "ปิด".
ENDED_CONTRACT_STATUSES = ("CLOSED", "WRITTEN_OFF", "TERMINATED", "CANCELLED")
TERMINATION_CAUSES = ("DEFAULT", "CUSTOMER_REQUEST")
# The sheet's OWN tracking vocabulary (collection_tracking pivot) names the two
# termination scenarios the business runs. Repossessed = VOLT ended it on default;
# the cooperative decommission rows are the customers who asked to end it (their own
# notes say "ลูกค้าแจ้งขอยกเลิก" / "รอรื้อถอน").
TERMINATION_BY_TRACKING_CATEGORY = {
    "Repossessed - Ready Resell": "DEFAULT",
    "Repossessed - Sold": "DEFAULT",
    "NPL - Cooperative - Decommission": "CUSTOMER_REQUEST",
}
SERVICE_HOLD = "SERVICE_HOLD_FAULT_CONFIRMED"
PTP_STATUSES = ("OPEN", "KEPT", "KEPT_PARTIAL", "BROKEN", "CANCELLED", "RENEGOTIATED")


class CaseError(Exception):
    def __init__(self, code, detail, message_th=None, **extra):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        # Round-1 P3 (J-46/J-48): one code can need a different Thai sentence per act.
        self.message_th = message_th
        self.extra = extra


def _now_on_business_date():
    """Round-3 J3-19: ONE clock — app/clock.py. The machine's live time of day used to
    ride on the business date, so a row written at 00:36 real time read 2026-10-23T00:36
    and the history sorted wrong against everything stamped from the business day."""
    return clock.stamp()


class CaseState:
    def __init__(self):
        self.cases = {}            # customer_uid -> case dict
        self.contact_log = []      # append-only rows
        self.ptps = {}             # uid -> ptp
        self.reviews = {}          # uid -> review request / system review
        self.issues = {}           # uid -> service issue
        self.power = {}            # uid -> power restriction record
        self.today_items = []      # tier-6 answers/closures waiting for an officer
        self.events = []           # audit trail
        self._counter = 0

    def uid(self, prefix):
        self._counter += 1
        return "%s-%05d" % (prefix, self._counter)


def _factory():
    state = CaseState()
    _seed(state)
    _open_pipeline_cases(state)
    return state


def _open_pipeline_cases(state):
    """One case for every pre-install card (2026-09-20).

    The team asked for the customer case to be the place pre-install work finishes,
    so a card comes with its case. The import is local and one-directional: this
    module never gets imported by invoice_pipeline at factory time, so the two
    Store.for_current() factories cannot re-enter each other (a set() of the slot
    only happens after the factory returns, so a cycle would recurse forever).
    """
    from . import invoice_pipeline
    for item in invoice_pipeline.for_current().items.values():
        open_pipeline_case(state, item)


_store = Store(_factory, key="cases.state")


def for_current() -> CaseState:
    state = _store.for_current()
    from . import request_context
    reads = request_context.reads()
    key = ("cases.overlays", id(state))
    if reads is not None and reads.get(key) is state:
        return state
    from . import perf
    with perf.phase("case_overlays"):
        from . import service_deferrals
        affected = {r["customer_uid"] for r in service_deferrals.records()}
        for uid in affected:
            customer = customer_by_uid(uid)
            case = state.cases.get(uid)
            if customer and case:
                _follow(state, case, customer)
                service_deferrals.sync_followup(state, case, customer)
        _apply_shared_overrides(state)
        _apply_payment_claims(state)
        termination_archive.project(state)
    if reads is not None:
        reads[key] = state
    return state


def _apply_payment_claims(state):
    """Overlay provisional cash without mutating the confirmed case answer.

    This is intentionally applied on every read.  A shared manual override can move
    independently of a claim, so a version-only shortcut could briefly expose LATE
    while a claim is still active. The overlay itself is not memoised — only the
    read behind it: `pending_by_customer()` fetches and groups the pending rows once
    per request (2026-09-29: /v1/today asked 5,926 times, each its own two queries),
    and a claim written in this process drops that read for the rest of the request.
    """
    from . import payment_claims
    active_by_customer = payment_claims.pending_by_customer()
    for case in state.cases.values():
        active = active_by_customer.get(case["customer_uid"], [])
        if active:
            if case.get("payment_status") != "PENDING":
                case["payment_status_confirmed"] = case.get("payment_status")
            case["payment_status"] = "PENDING"
            case["payment_pending_since"] = min(row["created_at"] for row in active)
            case["payment_pending_count"] = len(active)
            case["payment_pending_amount"] = str(sum(
                (Decimal(str(row.get("amount") or "0")) for row in active), Decimal("0.00")))
            case["payment_pending_uids"] = [row["uid"] for row in active]
            continue
        if case.get("payment_status") == "PENDING":
            case["payment_status"] = (case.get("payment_status_confirmed")
                                      or case.get("payment_status_system"))
        case.pop("payment_status_confirmed", None)
        case.pop("payment_pending_since", None)
        case.pop("payment_pending_count", None)
        case.pop("payment_pending_amount", None)
        case.pop("payment_pending_uids", None)


def _apply_shared_overrides(state):
    """The manual payment status is shared for everyone (Arina, 2026-09-24). When
    payment_overrides.version() moved since this session last looked (or _follow asked
    again), every active row whose system answer at set time is still this case's own is
    applied; a person's change whose row was retired goes back to the system's answer.
    Either move is written as the case's PAYMENT_STATUS_SET event, so the weekly figures
    count it in every session. No data-epoch bump, so no import heal runs.

    A row whose system answer is no longer this case's is moot and is retired here —
    not only where a session sees the answer move (_follow): a book that moved while no
    session holding the row healed (every session fresh after a deploy) would otherwise
    bring the months-old change back when the answer returned. Only a session caught up
    with the imports judges that; one behind reads an old answer, and asks again."""
    version = payment_overrides.version()
    if getattr(state, "overrides_seen", None) == version:
        return
    rows = payment_overrides.active()
    if rows is None:
        return                          # a failed read; the next call asks again
    settled = True
    for case in state.cases.values():
        row = rows.get(case["customer_uid"])
        if row is not None:
            _payment_status_fields(case)
            if row["system_code_at_set"] == case["payment_status_system"]:
                _show_shared(state, case, row)
                continue
            if not (_caught_up() and _retire_shared(case["customer_uid"])):
                settled = False
        if case.get("payment_status_set_by"):
            _end_shared(state, case)
    if settled:
        state.overrides_seen = version


def _caught_up():
    """Whether this session has healed to the newest import (always, with no database)."""
    # ponytail: another instance's import is seen through data_epoch's 1 s cache, so in
    # that second a session here can still judge with the old book; a per-row book check
    # on the apply side (refresh.py) closes it if multi-instance deploys ever matter.
    from . import data_epoch, import_sync
    return import_sync.seen_epoch() >= data_epoch.current()


def _retire_shared(customer_uid):
    """The system ends the customer's shared change. A store that does not answer is
    reported and False comes back; the next apply retires the moot row instead."""
    try:
        payment_overrides.retire(customer_uid, "SYSTEM")
    except errors.Problem as exc:
        print("payment status override not retired: %s" % exc.code, file=sys.stderr)
        return False
    return True


def _show_shared(state, case, row):
    shown = (row["code"], row["set_by"], row["reason"])
    if (case["payment_status"], case["payment_status_set_by"], case["payment_status_reason"]) == shown:
        return                          # already showing it (the setter's own session)
    previous = case["payment_status"]
    case["payment_status"], case["payment_status_set_by"], case["payment_status_reason"] = shown
    set_at = row.get("set_at")
    state.events.append({"kind": "PAYMENT_STATUS_SET", "case_uid": case["uid"],
                         "from": previous, "code": row["code"], "system": case["payment_status_system"],
                         "by": row["set_by"], "reason": row["reason"],
                         "on": str(set_at.astimezone(clock.BANGKOK).date() if set_at else settings.business_date),
                         "ended": None})


def _end_shared(state, case):
    _payment_status_fields(case)
    previous = case["payment_status"]
    ended = {"by": case["payment_status_set_by"], "code": previous, "reason": case.get("payment_status_reason")}
    case["payment_status"] = case["payment_status_system"]
    case["payment_status_set_by"], case["payment_status_reason"] = None, None
    state.events.append({"kind": "PAYMENT_STATUS_SET", "case_uid": case["uid"],
                         "from": previous, "code": case["payment_status"], "system": case["payment_status"],
                         "by": "SYSTEM", "reason": None, "on": str(settings.business_date), "ended": ended})


def reset():
    _store.reset()
    _fee_state_store.reset()
    payment_overrides.reset()           # the shared manual statuses (memory; test seam)


# --- shared-Contract-field overlay (ruling 43, R4-F01 BLOCKER + R4-F03 MAJOR) ------
#
# _apply_service_hold / _release_service_hold used to write fee_state and its four
# sibling fields straight onto the shared Contract fixture object reached through
# customer_by_uid() -> main.BY_CUSTOMER -- the exact shape ruling 39 named for
# board_column_id and ruling 40 named for officer. One officer logging a single
# service-fault contact flipped every other session's read of the fee state, and
# every session created afterwards, because SERVICE_HOLD_FAULT_CONFIRMED stops both
# the penalty accrual AND the DPD clock (money/fee_states.py). This overlay is the
# fourth instance of the established per-session-projection pattern (journey.py's
# officer_overlay / recovery_overlay): a session's service-hold state
# never touches the fixture, only this per-session dict, keyed by contract uid.
#
# The same overlay carries R4-F03's `contract.status` writes (NPL declaration,
# write-off) — one dict-of-dicts, keyed by contract uid, generic over field name.
#
# Ruling 49: `contract.instalments` (routers/journey.py:approve_restructure) rides
# the same overlay now, as a THIRD field, not a second mechanism. The concurrency
# guard (journey.py's `_RESTRUCTURE_LOCKS`, deliberately NOT per-session — see its
# own comment) is unchanged and still what stops a second session from succeeding;
# this overlay only carries the SCHEDULE DATA once the lock has already decided who
# won. approve_restructure never mutates a shared `Instalment` line's
# `schedule_status` in place any more -- a superseded line is replaced with a
# `dataclasses.replace(...)` copy, and the whole new list (superseded originals +
# addendum) lands in the acting session's overlay slot via _set_contract_fields.
# A session that has not restructured this contract keeps reading the pre-
# restructure schedule off the raw attribute, which -- like fee_state and status --
# is never written by a request again.
#
# Every site that used to read k.fee_state / k.fee_state_from / k.fee_state_until /
# k.fee_state_history / k.fee_state_before_hold / k.fee_state_from_before_hold /
# k.status / k.instalments directly now reads through contract_field_of(contract,
# field). The only write path is _set_contract_fields below -- never
# `k.<field> = ...` again, and never `line.schedule_status = ...` on a line taken
# from the raw shared list.
_fee_state_store = Store(dict, key="cases.fee_state")


def _fee_overlay():
    return _fee_state_store.for_current()


def contract_field_of(contract, field="fee_state"):
    """Session-aware read for any of the shared-Contract fields this overlay covers
    (fee_state and its five siblings, plus `status`). Falls back to the fixture's
    seeded value on the object itself -- that attribute is never written by a
    request any more, so it stays the seed for the life of the process."""
    if field in ("status", "termination"):
        pending = termination_archive._PENDING.get() or {}
        fact = pending.get(contract.uid) or termination_archive.facts().get(contract.uid)
        if fact:
            return fact[field]
    slot = _fee_overlay().get(contract.uid)
    value = slot[field] if slot and field in slot else getattr(contract, field, None)
    if field == "instalments":
        from . import service_deferrals
        return service_deferrals.apply_schedule(contract, value or [])
    if field in ("fee_state", "fee_state_from", "fee_state_until", "fee_state_history"):
        from . import service_deferrals
        return service_deferrals.effective_hold_field(contract, field, value, slot or {})
    return value


def _set_contract_fields(contract, **fields):
    """The only write path for the fields this overlay covers. Lands in the current
    session's overlay, never on the shared Contract object."""
    if "instalments" in fields:
        from . import service_deferrals
        if service_deferrals.active_moves(contract.uid):
            raise service_deferrals.problem("schedule_locked", "ต้องย้อนการเลื่อนงวดก่อนเปลี่ยนตารางสัญญา", 409)
    slot = _fee_overlay().setdefault(contract.uid, {})
    slot.update(fields)
    if "status" in fields:
        # Spec 2026-09-14 §3.3: a contract's status changes only through here, so this
        # is the one place the case's payment status can follow the system.
        follow_system_payment_status(contract)


def _payment_status_fields(case):
    """A case saved before 2026-09-14 has no system answer beside its status. Its
    status was the system's then, so that is the answer to start from (final review M2)."""
    case.setdefault("payment_status_system", case["payment_status"])
    case.setdefault("payment_status_set_by", None)
    case.setdefault("payment_status_reason", None)


def _follow(state, case, customer):
    """The shared step behind follow_system_payment_status (one contract's status
    changed) and follow_system_for_all (a PEAK report applied — every case is
    re-checked the same way). Re-works the system's answer for one case; if it moved,
    ends a person's standing change and writes the event and the audit detail.
    Returns the case when it moved, else None.
    """
    _payment_status_fields(case)
    new = _payment_status(customer)
    if new == case.get("payment_status_system"):
        return None
    previous = case["payment_status"]
    ended = None
    if case.get("payment_status_set_by"):
        ended = {"by": case["payment_status_set_by"], "code": previous,
                 "reason": case.get("payment_status_reason")}
        # The change is shared, so its end is too: every session goes back to its own
        # system answer. A store that does not answer must not half-finish the act that
        # moved the status; the next apply retires the row, moot by then.
        _retire_shared(case["customer_uid"])
    # The shared rows are read again on the next for_current: one set against the new
    # answer may apply now, and one set against the old answer is moot.
    state.overrides_seen = None
    case["payment_status_system"] = new
    case["payment_status"] = new
    case["payment_status_set_by"], case["payment_status_reason"] = None, None
    state.events.append({"kind": "PAYMENT_STATUS_SET", "case_uid": case["uid"],
                         "from": previous, "code": new, "system": new, "by": "SYSTEM",
                         "reason": None, "on": str(settings.business_date), "ended": ended})
    from . import audit
    # Detail only, never an act name. This runs inside another act's request (the NPL
    # declaration, the review decision, the write-off), and that act owns the row.
    # audit.describe resets detail only when an act NAME changes, so this survives.
    audit.describe(detail={"payment_status_followed_system": {"from": previous, "to": new, "ended": ended}})
    return case


def follow_system_payment_status(contract):
    """The system wins (Arina, 2026-09-14: decision 3, for every case: decision 5).

    Before this, nothing re-worked `payment_status` after the seed: declaring NPL on
    C-002032 left the case reading LATE. Now, when a contract's status changes, the
    owning customer's answer is worked out again. If it moved, the case shows it, and
    a person's change that stood ends. The history and the audit row say whose.
    """
    from . import main
    found = main.BY_CONTRACT.get(contract.uid)
    if not found:
        return None
    customer = found[0]
    state = for_current()
    case = state.cases.get(customer.uid)
    if case is None:
        return None
    return _follow(state, case, customer)


# Back-compat names — the fee-state call sites (main.py, routers/today.py,
# routers/journey.py) were written against these first; kept as plain aliases
# rather than touched a second time for a rename with no behaviour change.
fee_state_of = contract_field_of
_set_fee_state = _set_contract_fields


# --- book access ------------------------------------------------------------------

def book_customers():
    from . import main
    return main.CUSTOMERS


def customer_by_uid(uid):
    from . import main
    return main.BY_CUSTOMER.get(uid)


# --- seeding from the migrated book ----------------------------------------------

def _blank_case(uid, customer_uid, customer_no, volt_id, product, officer_uid,
                payment_status, data_source, sheet=None, termination=None):
    """One shape for a case, wherever it is opened. Round-3 J3-34 opens a case for a
    pre-install customer at release, so the seed's dict literal became a function
    instead of being copied — a second copy would drift on the next field added."""
    return {
        "uid": uid,
        "customer_uid": customer_uid,
        "customer_no": customer_no,
        "volt_id": volt_id,
        "product": product,
        "officer_uid": officer_uid,
        "payment_status": payment_status,
        # The system's own answer, kept beside the value every screen reads, and who
        # overruled it and why while a person's change stands (spec §3.1).
        "payment_status_system": payment_status,
        "payment_status_set_by": None,
        "payment_status_reason": None,
        "dc_status": None,
        "dc_status_note": None,
        "dc_status_set_by": None,
        "dc_status_reason_th": None,
        "dc_status_reason_en": None,
        "dc_status_before_issue": None,
        "npl_type": None,
        # Round-4 J4-12: who classified this customer, as which role, why and when.
        "npl_type_set_by": None,
        "npl_type_set_by_role": None,
        "npl_type_reason": None,
        "npl_type_set_on": None,
        # Amendment v2.6: mechanical accounting status stays separate from the
        # Manager-owned NPL type and recovery/legal decisions.
        "npl_assessment": None,
        # Round-4 J4-07: a ticket's deadline is the TICKET's date, kept beside the
        # officer's own next action instead of silently replacing it.
        "ticket_deadline": None,
        "ticket_deadline_note_th": None,
        "ticket_deadline_note_en": None,
        "next_action": None,
        "next_action_on": None,
        "next_action_set_by": None,
        "next_action_note": None,
        # Redesign v2 PR 9: the day a calendar move took the action from (None = not moved).
        "next_action_moved_from": None,
        "last_contact_at": None,
        "last_contact_by": None,
        "last_result": None,
        "open_ptp_uid": None,
        "broken_ptp_count": 0,
        "kept_ptp_count": 0,
        "renegotiation_count": 0,
        "open_issue_uid": None,
        "power_state": "ON",
        "allocation_hold": False, "allocation_hold_note_th": None, "allocation_hold_note_en": None,
        "allocation_hold_since": None, "allocation_hold_arrears": None,
        "power_uid": None,
        "review_uid": None,
        # The v2.6 threshold queue is visible to Managers without occupying the
        # case's single blocking workflow-review slot.
        "npl_review_uid": None,
        "delay_cause": None,
        # 2026-09-20: the termination record — {cause, on, by, reason_th, reason_en,
        # instrument, origin} — on the case too, beside `payment_status=TERMINATED`,
        # so the header, the history tab and the workbook can say WHY the contract
        # ended. None on every case that never terminated.
        "termination": termination,
        "sheet": sheet or {},
        "data_source": data_source,
    }


def _seed(state: CaseState):
    d = dictionaries.for_current()
    bd = settings.business_date
    for customer in book_customers():
        sheet = getattr(customer, "sheet", None)
        product = getattr(customer, "product", None) or (customer.contracts[0].product if customer.contracts else None)
        row = (sheet or {}).get("leasing") or (sheet or {}).get("cash") or {}
        tracking = (sheet or {}).get("tracking") or {}
        # 2026-09-20: an ended contract comes from the sheet too, and its record was
        # baked onto the contract at BOOK BUILD time (`book.build` — the Store factory
        # may not re-enter `for_current`, so the seed reads it here instead of writing
        # an overlay mid-factory). A runtime termination is a different thing and goes
        # through cases.record_termination's overlay; this is the import's own fact,
        # the same way the fixture rows already carry NPL statuses.
        termination = next((contract_field_of(k, "termination") for k in customer.contracts
                            if contract_field_of(k, "termination")), None)
        case = _blank_case(
            uid="case-%s" % customer.customer_no, customer_uid=customer.uid,
            customer_no=customer.customer_no, volt_id=getattr(customer, "volt_id", None),
            product=product, officer_uid=customer.officer,
            payment_status=_payment_status(customer), data_source=customer.data_source,
            sheet={
                "days_late": row.get("days_late"),
                "late_fees": row.get("late_fees"),
                "overdue": row.get("overdue"),
                "bucket": row.get("bucket"),
                "payment_status": row.get("payment_status") or tracking.get("category"),
                "dc_status_raw": row.get("dc_status"),
                "npl_type_raw": row.get("npl_type"),
                "comment_th": row.get("comment_th") or row.get("comment") or tracking.get("note"),
                "comment_en": row.get("comment_en"),
                "source_refs": (sheet or {}).get("source_refs"),
                **_comment_provenance(row.get("comment_th") or row.get("comment") or tracking.get("note"), customer.customer_no),
            }, termination=termination)
        # dc_status and NPL type from the sheet, through the dictionary (aliases accepted)
        try:
            # An empty DC Status cell on the sheet means nothing was done yet — the
            # sheet's own first value. An unknown spelling is kept as a note, not guessed.
            case["dc_status"] = d.resolve("DC_STATUS", row.get("dc_status")) or "NO_ACTION"
            case["dc_status_set_by"] = "SHEET" if row.get("dc_status") else "SYSTEM"
            case["dc_status_reason_th"] = "ค่าจากชีต" if row.get("dc_status") else "ชีตไม่มีค่า ระบบตั้งเป็นยังไม่ดำเนินการ"
            case["dc_status_reason_en"] = "Value from the sheet" if row.get("dc_status") \
                else "The sheet has no value, so the system set No action yet"
        except dictionaries.DictionaryError:
            case["dc_status"] = None
            case["dc_status_note"] = "sheet value not in the dictionary: %s" % row.get("dc_status")
        try:
            case["npl_type"] = d.resolve("NPL_TYPE", row.get("npl_type") or (tracking.get("category") if str(tracking.get("category", "")).startswith("NPL") else None))
        except dictionaries.DictionaryError:
            case["npl_type"] = None
        if case["dc_status"] == "POWER_CUTOFF":
            case["power_state"] = "RESTRICTED"
            rec = _power_record(state, case, requested_by="sheet", backfilled=True)
            rec["executed_at"] = None
            case["power_uid"] = rec["uid"]
        # the MapLog rows -> contact log
        for entry in (sheet or {}).get("contact_log") or []:
            _append_contact(state, case, {
                "occurred_at": entry.get("occurred_at"),
                "officer_uid": _officer_alias(entry.get("officer")) or customer.officer,
                "channel": "LINE",
                "direction": "OUTBOUND",
                "result": entry.get("result") or "REACHED_ANSWERED",
                "amount_stated": bool(entry.get("ptp_amount")),
                "counted": bool(entry.get("result") in ("REACHED_ANSWERED", "REACHED_PTP")),
                "note": entry.get("note"),
                "source": "MAPLOG_IMPORT",
                "source_ref": entry.get("source_ref"),
            })
            if entry.get("next_call") and not case["next_action_on"]:
                case["next_action"], case["next_action_on"], case["next_action_set_by"] = "CALLBACK", entry["next_call"], "MAPLOG_IMPORT"
        # the sheet's PTP -> an OPEN promise (or BROKEN if the date has passed)
        ptp_date, ptp_amount = row.get("ptp_date") or tracking.get("ptp_date"), row.get("ptp_amount") or tracking.get("ptp_amount")
        if ptp_date and ptp_amount:
            ptp = _make_ptp(state, case, ptp_amount, ptp_date, created_by="sheet", source="SHEET")
            if date.fromisoformat(ptp_date) < bd:
                _break_ptp(state, case, ptp, on=bd)
        # Ruling 7, round 3 (Arina, 2026-09-04): "one PTP concept, one store." A promise
        # can also be seeded straight into the JOURNEY store (`journey.py`'s own `_seed`,
        # not the sheet), with nothing written here — this case's `open_ptp_uid` then
        # stayed null while the journey store's own row-level projection served the
        # promise under a different key at a different nesting level. This store is
        # both the write model (every PTP endpoint) and the read model (`tier_for`
        # above, all five screen call sites, both CSV exports), so a promise that lived
        # only in the journey store was invisible everywhere an officer looks and never
        # reached the tier engine either. Mirror it in, once, only when the sheet did
        # not already open one — never two open promises on the same case.
        if not case["open_ptp_uid"]:
            from . import journey as journey_domain
            jptp = journey_domain.open_ptp_for(journey_domain.for_current(), customer.uid)
            if jptp:
                _make_ptp(state, case, jptp["promised_amount"], jptp["promise_date"],
                          created_by=jptp.get("created_by") or "journey", source="JOURNEY")
        # a ticket block -> an open service issue with its link
        ticket = row.get("ticket") or {}
        if ticket.get("ticket_link") or (row.get("dc_status") in ("Tech Issue", "Technical Issue")):
            issue = _make_issue(state, case, {
                "summary": ticket.get("remark") or row.get("dc_comment") or "Tech issue on the sheet",
                "responsible_team": _team(ticket.get("responsible_team")),
                "ticket_url": ticket.get("ticket_link"),
                "deadline": ticket.get("deadline"),
                "ticket_status": ticket.get("case_status") or "OPEN",
                "opened_by": "sheet",
            })
            case["open_issue_uid"] = issue["uid"]
            case["delay_cause"] = "VOLT_SERVICE_ISSUE"
            if case["dc_status"] != "TECH_ISSUE":
                case["dc_status_before_issue"] = case["dc_status"]
                _set_dc(case, "TECH_ISSUE", "SYSTEM", "ชีตมีตั๋วปัญหาระบบเปิดอยู่",
                        "The sheet has an open system-issue ticket")
        if case["next_action"] is None:
            _default_next_action(case, bd)
        assessment = npl_assessment_for(
            customer,
            contacts=(r for r in state.contact_log if r["customer_uid"] == customer.uid),
        )
        case["npl_assessment"] = _assessment_payload(assessment)
        state.cases[customer.uid] = case
        # 2026-09-20: an imported termination is a fact on the case's own timeline too,
        # not only in the served `termination` record — the History tab reads events.
        if termination:
            add_event(state, case, "CONTRACT_TERMINATED", cause=termination["cause"],
                      instrument="SHEET_CATEGORY", by="SHEET",
                      note=termination.get("reason_th"))
        # An NPL case with no type yet is a decision waiting for the Manager (REQ-COL-075):
        # it opens a system review so the lead sees it in the queue, not the officer in a tier.
        if case["payment_status"] == "NPL" and not case["npl_type"] and not case["review_uid"]:
            request_review(state, case, "NPL_TYPE_ASK", "NPL ยังไม่มีประเภท — ผู้จัดการต้องกำหนด", by="SYSTEM",
                           question_en="NPL without a type yet — the Manager must set one")
        elif assessment.needs_review and not case.get("npl_review_uid"):
            review = request_review(
                state, case, "NPL_REVIEW",
                "DPD ถึงเกณฑ์ทบทวนและยังไม่มีการติดต่อที่นับได้",
                by="SYSTEM",
                question_en="The NPL review threshold was reached without a counted contact",
                blocking=False,
            )
            case["npl_review_uid"] = review["uid"]


def open_pre_install_case(state, customer_uid, customer_no, display_name, volt_id,
                          officer_uid, product="CASH", by="SYSTEM", reason_th=None, reason_en=None):
    """Round-3 J3-34: a pre-install customer had NO case, so everything done to them —
    release, delivery, a postponement, an amend — lived only on the pipeline card, and
    that card is exactly the one that can leave the look-ahead. A case is opened as
    soon as an invoice is released; the collection work has a home from that moment.

    Since 2026-09-20 the case usually already exists — `open_pipeline_case` opens it
    when the pre-install card is seeded — so this returns it and release marks it.
    """
    existing = state.cases.get(customer_uid)
    if existing is not None:
        return existing
    case = _blank_case(uid="case-%s" % customer_no, customer_uid=customer_uid,
                       customer_no=customer_no, volt_id=volt_id, product=product,
                       officer_uid=officer_uid, payment_status="CURRENT",
                       data_source={"identity": "PIPELINE", "history": "PIPELINE"},
                       sheet={})
    case["display_name"] = display_name
    case["pre_install"] = True
    case["opened_from"] = "INVOICE_RELEASED"
    case["opened_on"] = str(settings.business_date)
    case["opened_reason_th"] = reason_th or "เปิดเคสอัตโนมัติเมื่อปล่อยใบแจ้งหนี้ก่อนติดตั้ง"
    case["opened_reason_en"] = reason_en or "Case opened automatically when a pre-install invoice was released"
    _set_dc(case, "NO_ACTION", "SYSTEM", case["opened_reason_th"], case["opened_reason_en"])
    case["next_action"], case["next_action_on"], case["next_action_set_by"] = \
        "SEND_INVOICE_LINK", str(settings.business_date), "SYSTEM"
    state.cases[customer_uid] = case
    add_event(state, case, "CASE_OPENED", customer_uid=customer_uid,
              by=by, reason=case["opened_reason_th"])
    return case


def open_pipeline_case(state, item, officer_uid=None, by="SYSTEM"):
    """Open the customer's case when their pre-install card is seeded (2026-09-20).

    The team asked for one place to finish pre-install work: the customer's own case.
    A card therefore comes with its case from day one, `pipeline_released` False and
    no next action — an un-released card is pipeline work, not book work, and the
    counts say so (`is_book_case`). Releasing the invoice marks it released.
    """
    existing = state.cases.get(item["customer_uid"])
    if existing is not None:
        return existing
    case = _blank_case(uid="case-%s" % item["customer_no"], customer_uid=item["customer_uid"],
                       customer_no=item["customer_no"], volt_id=item.get("volt_id"),
                       product=item.get("product") or "CASH",
                       officer_uid=officer_uid or item.get("officer_uid"),
                       payment_status="CURRENT",
                       data_source={"identity": "PIPELINE", "history": "PIPELINE"},
                       sheet={})
    case["display_name"] = item["display_name"]
    case["pre_install"] = True
    case["opened_from"] = "PRE_INSTALL_CARD"
    case["pipeline_uid"] = item["uid"]
    case["pipeline_released"] = False
    case["opened_on"] = str(settings.business_date)
    case["opened_reason_th"] = "เปิดเคสเมื่อลูกค้าเข้ากระบวนการก่อนติดตั้ง"
    case["opened_reason_en"] = "Case opened when the customer entered the pre-installation process"
    _set_dc(case, "NO_ACTION", "SYSTEM", case["opened_reason_th"], case["opened_reason_en"])
    state.cases[item["customer_uid"]] = case
    add_event(state, case, "CASE_OPENED", customer_uid=item["customer_uid"],
              by=by, reason=case["opened_reason_th"])
    return case


def add_event(state, case, kind, **fields):
    """One entry on the case's own timeline. The case page renders these beside the
    contact log, so an act that is not a contact (an evidence attach, a gate, a
    release) is still visible where the work happens."""
    row = {"kind": kind, "case_uid": case["uid"], "on": str(settings.business_date)}
    row.update(fields)
    state.events.append(row)
    return row


def is_book_case(case):
    """Whether this case counts on the work book.

    A pre-install case is pipeline work until its invoice is released; before that it
    exists for the customer's own page and the pipeline card, but it is not a book row
    and must not inflate the book badge, a caseload or a management figure.
    """
    return case.get("opened_from") != "PRE_INSTALL_CARD" or bool(case.get("pipeline_released"))


OFFICER_ALIASES = {"nantapol": "nantapol", "ทิพย์อักษร": "thip", "thiphakson": "thip", "thip": "thip"}


def _officer_alias(raw):
    key = (raw or "").strip().lower()
    return OFFICER_ALIASES.get(key, key or None)


def _comment_provenance(comment, customer_no):
    """Round-2 nantapol N2-03: the note on ปัทมวรรณ (1) opens with the MapLog of her other
    contract 99999000146. Name where the note came from instead of letting it pass as this row's."""
    import re
    m = re.match(r"\s*\[MapLog:(\d+)_", comment or "")
    ref = m.group(1) if m else None
    if ref and ref != str(customer_no):
        return {"comment_ref_no": ref,
                "comment_note_th": "หมายเหตุนี้มาจาก MapLog ของสัญญา %s (อีกสัญญาหนึ่งของลูกค้ารายเดียวกัน) ไม่ใช่ของสัญญานี้" % ref}
    return {"comment_ref_no": ref, "comment_note_th": None}


def _set_dc(case, code, by, reason_th, reason_en=None):
    """reason_en defaults to reason_th: a reason a person typed is their own text."""
    case["dc_status"], case["dc_status_set_by"], case["dc_status_reason_th"] = code, by, reason_th
    case["dc_status_reason_en"] = reason_en or reason_th


def _contracts_of(case):
    customer = customer_by_uid(case["customer_uid"])
    return list(customer.contracts) if customer else []


def _apply_service_hold(case, on):
    """Round-2 N2-07 / T2-08: while a service issue is open the fee AND the DPD clock stop
    (money/fee_states.py: SERVICE_HOLD_FAULT_CONFIRMED stops both). The hold starts on
    the day the ticket opens; main._contract_view reads fee_state_from and the history.
    Ruling 43 / R4-F01: writes go through _set_fee_state, into the per-session overlay
    — never `k.fee_state = ...` onto the shared Contract fixture."""
    for k in _contracts_of(case):
        if fee_state_of(k) == SERVICE_HOLD:
            continue
        _set_fee_state(k,
                        fee_state_before_hold=fee_state_of(k),
                        fee_state_from_before_hold=fee_state_of(k, "fee_state_from"),
                        fee_state=SERVICE_HOLD, fee_state_from=on, fee_state_until=None)


def _release_service_hold(case, on):
    for k in _contracts_of(case):
        slot = _fee_overlay().get(k.uid) or {}
        raw = lambda field: slot[field] if field in slot else getattr(k, field, None)
        # A per-cycle remedy scopes the effective hold without closing its ticket.
        # Closing that ticket still releases the stored hold, including on reversal.
        if raw("fee_state") != SERVICE_HOLD:
            continue
        history = list(raw("fee_state_history") or [])
        # A paused day is never recomputed: the closed hold stays on the record.
        history.append({"state": SERVICE_HOLD, "from": raw("fee_state_from"), "until": on,
                        "issue_uid": raw("service_hold_issue_uid")})
        _set_fee_state(k,
                        fee_state_history=history,
                        fee_state=fee_state_of(k, "fee_state_before_hold"),
                        fee_state_from=fee_state_of(k, "fee_state_from_before_hold"),
                        fee_state_until=on)


ALLOCATION_HOLD_TH = "ยอดค้างยังไม่เปลี่ยน — รอบัญชีตัดสินลำดับการจัดสรร"
ALLOCATION_HOLD_EN = "arrears unchanged — awaiting allocation by Accounting"


def case_arrears(case):
    """The case's arrears straight from the money engine — never a number this module
    computes (house rule). Decimal, 0.00 when the customer has gone."""
    from .main import _customer_aggregate
    customer = customer_by_uid(case["customer_uid"])
    if customer is None:
        return Decimal("0.00")
    return _customer_aggregate(customer)[0]


# --- ending a contract (2026-09-20, the Closed/Terminated ruling) --------------------

def termination_gate(customer):
    """The money rule for ending a contract: every contract is either already ended or
    owes nothing. Returns `(blocking, checks)` — an empty `blocking` means the way is
    open, and `checks` is the served evidence for the ones that passed.

    A contract's `closing_balance` is the engine's own figure (money/arrears.py) and it
    does NOT move because a status changed, so the gate is "the balance was closed by
    an instrument", not "the engine reads zero afterwards": a contract already
    WRITTEN_OFF passes because the OWNER-approved write-off IS the instrument. A live
    contract with a balance blocks, and the refusal carries `payoff_amount`
    (`block.full_payoff_amount`) so the officer can quote the number that settles it.
    """
    from . import main
    blocking, checks = [], []
    for contract in customer.contracts:
        status = contract_field_of(contract, "status")
        if status in ENDED_CONTRACT_STATUSES:
            checks.append({"contract_uid": contract.uid, "status": status, "closed_by": "status"})
            continue
        block = main._contract_view(contract)[3]
        if block.closing_balance > 0:
            blocking.append({"contract_uid": contract.uid,
                             "outstanding": str(block.closing_balance),
                             "payoff_amount": str(block.full_payoff_amount)})
        else:
            checks.append({"contract_uid": contract.uid, "status": status, "closed_by": "paid"})
    return blocking, checks


def validate_termination_inputs(cause, reason):
    """The cheap checks first — a malformed request must not hide behind the money
    gate (the same order set_dc_status/set_payment_status keep). Returns the reason.
    Raises CaseError `termination_cause_unknown` / `reason_required`."""
    if cause not in TERMINATION_CAUSES:
        raise CaseError("termination_cause_unknown",
                        "%r is not a termination cause; use one of %s" % (cause, ", ".join(TERMINATION_CAUSES)),
                        message_th="ไม่รู้จักสาเหตุการยุติสัญญา", known=list(TERMINATION_CAUSES),
                        pointer="/cause")
    if not reason or not str(reason).strip():
        raise CaseError("reason_required", "Terminating a contract needs a reason",
                        message_th="ต้องระบุเหตุผลในการยุติสัญญา", pointer="/reason")
    return str(reason).strip()


@termination_archive.operation
def record_termination(contract, cause, by, reason, instrument, status="TERMINATED", on=None):
    """The ONE writer of an ended contract (2026-09-20).

    Both terminal paths go through here: the terminate act (status TERMINATED, any
    instrument that closed the balance) and the OWNER write-off (status WRITTEN_OFF —
    its own contract status, because the books must keep saying the loss was written
    off, while the case derives TERMINATED all the same).

    Writes the contract through `_set_contract_fields` — the only write path for
    status, which re-works the case's payment status (follow_system_payment_status) —
    and mirrors the record on the case so the header, the history tab and the workbook
    can say WHY it ended. The audit detail carries the cause and the instrument, never
    the reason's own digits-free text twice.
    """
    reason = validate_termination_inputs(cause, reason)
    record = {"cause": cause, "on": str(on or settings.business_date), "by": by,
              "instrument": instrument, "origin": "PERSON", "reason": reason}
    termination_archive.observe(contract, record, status)
    _set_contract_fields(contract, status=status, termination=record)
    state = for_current()
    case = None
    from . import main
    found = main.BY_CONTRACT.get(contract.uid)
    if found:
        case = state.cases.get(found[0].uid)
    if case is not None:
        case["termination"] = record
        add_event(state, case, "CONTRACT_TERMINATED", cause=cause, instrument=instrument,
                  contract_uid=contract.uid, by=by, on=record["on"],
                  reason=reason, origin=record["origin"])
    # The act name belongs to whichever route is running: the terminate route names
    # CONTRACT_TERMINATED itself before calling, and a write-off inside recovery:resolve
    # is part of RECOVERY_RESOLVED — renaming the act mid-request would reset the outer
    # detail (audit.describe's nested-act rule) and lose what the route already said.
    # Detail only here; the act is added when there is none yet (a direct call).
    from . import audit
    detail = {"cause": cause, "instrument": instrument, "contract_uid": contract.uid,
              "status": status}
    if audit.CURRENT.get() is None or audit.CURRENT.get().get("act"):
        audit.describe(detail={"contract_terminated": detail})
    else:
        audit.describe(act="CONTRACT_TERMINATED",
                       subject=("customer", case["customer_uid"] if case else contract.customer_uid),
                       detail={"contract_terminated": detail})
    return record


def set_allocation_hold(case, arrears):
    """Round-3 J3-08: the OD-02 hold sits beside the money. The header prints
    allocation_hold_note_th next to ยอดค้าง."""
    case["allocation_hold"] = True
    case["allocation_hold_note_th"] = ALLOCATION_HOLD_TH
    case["allocation_hold_note_en"] = ALLOCATION_HOLD_EN
    case["allocation_hold_since"] = str(settings.business_date)
    case["allocation_hold_arrears"] = str(arrears)
    return case


def clear_allocation_hold(case):
    case["allocation_hold"] = False
    case["allocation_hold_note_th"] = None
    case["allocation_hold_note_en"] = None
    case["allocation_hold_since"] = None
    case["allocation_hold_arrears"] = None
    return case


def derive_dc_status(state, case, trigger, result=None, next_action=None, by="SYSTEM"):
    """Round-2 nantapol N2-09 / thip T2-15: the sheet's DC status followed what the officer
    logged; the app left it on NO_ACTION. After every contact the status follows the
    result through the dictionary — unless a person set one of the governed statuses,
    which only a person changes back."""
    d = dictionaries.for_current()
    if case["dc_status"] in GOVERNED_DC_STATUSES and case.get("dc_status_set_by") not in (None, "SYSTEM", "SHEET"):
        return None
    code = reason = reason_en = None
    if trigger == "ISSUE_OPENED":
        if case["dc_status"] != "TECH_ISSUE":
            case["dc_status_before_issue"] = case["dc_status"]
        code, reason, reason_en = "TECH_ISSUE", "เปิดตั๋วปัญหาระบบ", "A system-issue ticket was opened"
    elif trigger == "ISSUE_CLOSED":
        code = case.get("dc_status_before_issue") or "NO_ACTION"
        reason = "ปิดตั๋วแล้ว กลับไปสถานะก่อนเปิดตั๋ว"
        reason_en = "Ticket closed, back to the status before it opened"
        case["dc_status_before_issue"] = None
    elif trigger == "PAYMENT_CONFIRMED":
        # Round-3 J3-08: a receipt is recorded and drafted in PEAK, but instalment
        # allocation waits on OD-02, so the arrears do not move. "ชำระแล้ว" beside a
        # ยอดค้าง of 8,798.00 is the app disagreeing with itself: the status stays
        # where it was and the hold is carried on the case, beside the money.
        arrears = case_arrears(case)
        if arrears > 0:
            set_allocation_hold(case, arrears)
            return None
        clear_allocation_hold(case)
        code, reason = ("PAID" if d.get("DC_STATUS", "PAID") else "NO_ACTION"), "ยืนยันเงินเข้าแล้ว"
        reason_en = "Payment received and confirmed"
    elif trigger == "PTP":
        cash = (case.get("product") == "CASH")
        code = "PTP" if (cash and d.get("DC_STATUS", "PTP")) else "EXTEND_PAYMENT_TO"
        reason, reason_en = "ลูกค้านัดชำระ", "The customer promised to pay"
    elif trigger == "CONTACT":
        if result and result.startswith("UNREACHABLE_"):
            code, reason = "UNREACHABLE", "ผลการติดต่อ: %s" % (d.label("CONTACT_RESULT", result) or result)
            reason_en = "Contact result: %s" % (d.label("CONTACT_RESULT", result, "en") or result)
        elif result == "CALLBACK_REQUESTED" or next_action == "CALLBACK":
            code, reason, reason_en = "CONTACT_BACK", "ลูกค้าขอให้ติดต่อกลับ", "The customer asked to be contacted back"
        elif result in ("PROMISED", "REACHED_PTP"):
            cash = (case.get("product") == "CASH")
            code = "PTP" if (cash and d.get("DC_STATUS", "PTP")) else "EXTEND_PAYMENT_TO"
            reason = "ผลการติดต่อ: %s" % (d.label("CONTACT_RESULT", result) or result)
            reason_en = "Contact result: %s" % (d.label("CONTACT_RESULT", result, "en") or result)
        elif result == "SERVICE_ISSUE":
            if case["dc_status"] != "TECH_ISSUE":
                case["dc_status_before_issue"] = case["dc_status"]
            code, reason, reason_en = "TECH_ISSUE", "ลูกค้าแจ้งปัญหาระบบ", "The customer reported a system issue"
    if code is None or d.get("DC_STATUS", code) is None:
        return None
    if code != case["dc_status"]:
        state.events.append({"kind": "DC_STATUS_SET", "case_uid": case["uid"], "code": code, "by": "SYSTEM",
                             "reason_th": reason, "on": str(settings.business_date)})
    _set_dc(case, code, "SYSTEM", reason, reason_en)
    return code


def _payment_status_from_contracts(customer):
    if not customer.contracts:
        return "NOT_INSTALLED"
    # Ruling 43 / R4-F03: session-scoped read — never k.status directly.
    statuses = {contract_field_of(k, "status") for k in customer.contracts}
    active = statuses - set(ENDED_CONTRACT_STATUSES)
    if not active:
        # 2026-09-20: nothing left to collect. Paid per the terms is CLOSED; any other
        # way the contract ended (write-off, repossession, a customer's requested
        # termination) is TERMINATED. The two must not merge, or the write-off book
        # reads as if those customers paid.
        return "CLOSED" if statuses <= {"CLOSED"} else "TERMINATED"
    if npl_assessment_for(customer).automatic_npl:
        return "NPL"
    if "NON_PERFORMING" in active:
        return "NPL"
    if "PAST_DUE" in active:
        return "LATE"
    if "PRE_COLLECTION" in active:
        return "NOT_INSTALLED"
    return "CURRENT"


def npl_assessment_for(customer, contacts=()):
    from .npl_assessment import assess
    return assess(
        customer.contracts,
        as_of=settings.business_date,
        contacts=contacts,
        field_of=contract_field_of,
    )


def _assessment_payload(result):
    return {
        "actual_dpd": result.actual_dpd,
        "missed_instalments": result.missed_instalments,
        "restructured": result.restructured,
        "automatic_npl": result.automatic_npl,
        "needs_review": result.needs_review,
        "assessment_hold": result.assessment_hold,
        "reason": result.reason,
        "label_th": result.label_th,
        "label_en": result.label_en,
    }


def _owed(row):
    """Money still owed on one PEAK row. PEAK writes it with comma separators; an
    unreadable or non-finite value reads as nothing owed, because inventing a debt
    is worse than missing one."""
    try:
        owed = Decimal(str(row.get("amount_awaiting") or "0").replace(",", "").strip() or "0")
    except InvalidOperation:
        return Decimal("0")
    return owed if owed.is_finite() else Decimal("0")


def _late(r, bd):
    """Money first, status word only as the fallback for when PEAK did not say —
    a row PEAK already marked OVERDUE must not read as never-late just because
    due_on is missing."""
    if _owed(r) <= 0:
        return False
    due = r.get("due_on")
    return due < bd if due else r.get("status") == "OVERDUE"


def termination_from_tracking(tracking):
    """The termination record the sheet's own tracking category states, or None.

    2026-09-20 (Closed/Terminated ruling): the sheet names both scenarios in its own
    vocabulary — `Repossessed - *` are the contracts VOLT ended on default,
    `NPL - Cooperative - Decommission` are the customers who asked to end it. The
    category carries no date, so `on` stays None rather than inventing one; the row's
    own source_ref points at the cell, and the category travels verbatim."""
    category = (tracking or {}).get("category")
    cause = TERMINATION_BY_TRACKING_CATEGORY.get((category or "").strip())
    if not cause:
        return None
    return {"cause": cause, "on": None, "by": "SHEET", "origin": "SHEET",
            "instrument": "SHEET_CATEGORY", "category": category,
            "reason_th": "ชีตระบุหมวด %s" % category,
            "reason_en": "The sheet's tracking category reads %s" % category}


def _peak_rows(customer):
    """The PEAK invoices that can judge lateness. DRAFT is not a judgement at all, and
    a receipt_only row is money with no invoice behind it — it says nothing about a
    due date, and read as CURRENT it hid the sheet's LATE."""
    peak = (getattr(customer, "sheet", {}) or {}).get("peak") or {}
    return [r for r in peak.get("invoices") or []
            if r.get("status") not in ("DRAFT", "CANCELLED") and not r.get("receipt_only")]


def _peak_says(customer):
    """LATE / CURRENT from the PEAK invoices, or None when this customer has none.

    The money decides, not the status word: 37 lines in the 2026-09-14 export are
    marked overdue with most of the amount already in, and 29 are marked unpaid
    with nothing outstanding. Late = money still owed AND the due date passed."""
    rows = _peak_rows(customer)
    if not rows:
        return None
    bd = str(settings.business_date)
    return "LATE" if any(_late(r, bd) for r in rows) else "CURRENT"


# Arina, 2026-09-24: the New Order Master's "done collection" tab is the debt team's
# monthly payment-status source. Its Category, in the app's codes; every "NPL - …"
# category is NPL. Any other word keeps the contract answer and is flagged on the case.
SHEET_CATEGORY_STATUS = {"Active": "CURRENT", "Late": "LATE", "Delayed Installation": "NOT_INSTALLED"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def sheet_says(customer):
    """(code, word) — the "done collection" tab's status for its latest month. `code`
    is None when the tab holds no row for this customer or a word the map does not
    know; `word` is the sheet's own Category, verbatim."""
    sheet = getattr(customer, "sheet", None) or {}
    from .imports import _IMS
    leasing = sheet.get("leasing") or {}
    if _IMS._done(leasing) and leasing.get("payment_status"):
        # Arina, 2026-09-25: Done - Collection's own Payment Status wins over any
        # other tab's word for the same customer.
        from .book import payment_status_code
        word = str(leasing["payment_status"]).strip()
        return ("NPL" if word.startswith("NPL") else payment_status_code(word)), word
    cash = sheet.get("cash") or {}
    if _IMS._done(cash) and cash.get("status_word"):
        word = cash["status_word"]
        return {"closed": "CLOSED", "late": "LATE", "link sent": "LATE", "not due": "CURRENT",
                "not issued": "CURRENT", "terminated": "TERMINATED"}.get(word.lower()), word
    word = str((sheet.get("tracking") or {}).get("category") or "").strip()
    if not word:
        return None, None
    return ("NPL" if word.startswith("NPL") else SHEET_CATEGORY_STATUS.get(word)), word


def sheet_status(customer):
    """What the case page prints as "สถานะตามชีต": the Category word, its code (None
    for a word the map does not know — flagged, not guessed) and the tab's latest
    month; None when the "done collection" tab holds no row for this customer."""
    code, word = sheet_says(customer)
    if not word:
        return None
    tracking = (getattr(customer, "sheet", None) or {}).get("tracking") or {}
    months = [m["month"] for m in tracking.get("months") or []]
    return {"code": code, "word": word, "unknown": code is None,
            "month": max(months, key=_month_key) if months else None}


def _payment_status(customer):
    """Arina, 2026-09-24 (supersedes design F2's two tiers): the contract statuses
    that mean NPL, CLOSED, TERMINATED or NOT_INSTALLED still win (a person or the
    ladder set them); then PEAK where it has invoices (the switch on); then the
    sheet's "done collection" status; then the contract-derived answer. Where PEAK
    and the sheet differ, `status_disagreements` lists it — neither is overwritten."""
    return payment_status_with_source(customer)[0]


def payment_status_with_source(customer):
    """(code, source) — `_payment_status`'s answer and which rung gave it: CONTRACT
    (an ended/NPL/not-installed contract, or nothing else answered), PEAK or SHEET.
    The monthly history keeps the source beside the status (2026-09-25)."""
    from_contracts = _payment_status_from_contracts(customer)
    if from_contracts in ("NPL", "CLOSED", "TERMINATED", "NOT_INSTALLED"):
        return from_contracts, "CONTRACT"
    from . import service_deferrals, main
    if any(service_deferrals.has_history(k.uid) for k in customer.contracts):
        overdue = main._customer_aggregate(customer)[0]
        return ("LATE" if overdue > 0 else "CURRENT"), "SERVICE_ADJUSTED_SCHEDULE"
    peak = _peak_says(customer) if settings.peak_report_drives_status else None
    if peak:
        return peak, "PEAK"
    sheet = sheet_says(customer)[0]
    return (sheet, "SHEET") if sheet else (from_contracts, "CONTRACT")


def _month_key(label):
    mon, _, year = label.partition(" ")
    return year, _MONTHS.index(mon) if mon in _MONTHS else 12


def month_status(customer):
    """The case's month grid: per calendar month, PEAK's answer where PEAK billed that
    month (LATE when money due then is still owed past its date, PAID when every
    invoice due then is settled), else the "done collection" tab's own cell."""
    bd = str(settings.business_date)
    by_month = {}
    for r in _peak_rows(customer):
        if r.get("due_on"):
            month = "%s %s" % (_MONTHS[int(r["due_on"][5:7]) - 1], r["due_on"][:4])
            by_month.setdefault(month, []).append(
                "LATE" if _late(r, bd) else ("PAID" if _owed(r) <= 0 else None))
    peak = {m: "LATE" if "LATE" in codes else ("PAID" if all(codes) else None)
            for m, codes in by_month.items()}
    tracking = (getattr(customer, "sheet", None) or {}).get("tracking") or {}
    sheet = {m["month"]: (m.get("cell") or {}).get("kind") for m in tracking.get("months") or []}
    return [{"month": m, "status": peak.get(m) or sheet.get(m),
             "source": "PEAK" if peak.get(m) else ("SHEET" if sheet.get(m) else None),
             "peak": peak.get(m), "sheet": sheet.get(m)}
            for m in sorted(set(sheet) | {m for m, code in peak.items() if code}, key=_month_key)]


def status_disagreements(customer):
    """Every month (and the current status, `month: None`) where PEAK and the sheet
    both answer and differ. Listed for a person to review — the served status keeps
    PEAK's answer and the sheet keeps its own; nothing is overwritten. The current row
    says when PEAK is switched off (`peak_off`): the status then follows the sheet."""
    out = [{"month": m["month"], "peak": m["peak"], "sheet": m["sheet"]} for m in month_status(customer)
           if m["peak"] and m["sheet"] in ("PAID", "LATE") and m["peak"] != m["sheet"]]
    peak, (sheet, _word) = _peak_says(customer), sheet_says(customer)
    if peak and sheet and peak != sheet:
        out.insert(0, {"month": None, "peak": peak, "sheet": sheet,
                       "peak_off": not settings.peak_report_drives_status})
    return out


def _team(raw):
    return {
        "Installation (EPC)": "INSTALLATION_EPC", "O&M": "O_AND_M", "Permit": "PERMIT",
        "Installation (EPC), O&M": "INSTALLATION_EPC", "O&M, Installation (EPC)": "O_AND_M",
    }.get(raw or "", "CS")


def _default_next_action(case, bd):
    """REQ-COL-070: the seed leaves nobody without a next action. The choice is the
    SOP ladder's own: a promise is followed, a late case is called, a current case
    gets its reminder, a closed case is closed."""
    if case["open_ptp_uid"]:
        return
    ps = case["payment_status"]
    if ps == "LATE" or ps == "NPL":
        case["next_action"], case["next_action_on"] = "CALL", str(bd)
    elif ps == "CURRENT":
        case["next_action"], case["next_action_on"] = "SEND_REMINDER", str(_next_due_minus(bd, reminder_offsets()[0]))
    elif ps == "NOT_INSTALLED":
        case["next_action"], case["next_action_on"] = "SEND_INVOICE_LINK", str(bd)
    else:
        case["next_action"], case["next_action_on"] = "NONE_CLOSED", str(bd)
    case["next_action_set_by"] = "SEED"


def reminder_offsets():
    """Round-2 nantapol N2-13: the reminder batch offsets are a config key, not a literal."""
    raw = getattr(settings, "reminder_offsets_days", None) or [3, 0]
    return [int(x) for x in raw]


def _next_due_minus(bd, days):
    from datetime import timedelta
    due = date(bd.year, bd.month, 10)
    if due <= bd:
        due = date(bd.year + (bd.month // 12), bd.month % 12 + 1, 10)
    return due - timedelta(days=days)


# --- primitives -------------------------------------------------------------------

def business_stamp(occurred_at=None):
    """Round-4 J4-01: every contact write is stamped from the BUSINESS clock.

    A caller may hand in its own `occurred_at`, but only a stamp that falls on the
    business date is honoured — the drawer's `new Date()` (2026-09-03) landed the row
    on a day /v1/today never looks at, so the customer stayed รายต่อไป while the desk
    was already locked out of them.
    """
    if occurred_at and str(occurred_at)[:10] == str(settings.business_date):
        return occurred_at
    return clock.stamp()


def _append_contact(state, case, row):
    entry = dict(row)
    entry["uid"] = state.uid("ct")
    entry["case_uid"] = case["uid"]
    entry["customer_uid"] = case["customer_uid"]
    entry.setdefault("ptp_uid", None)
    entry.setdefault("issue_uid", None)
    entry.setdefault("next_action", None)
    entry.setdefault("next_action_on", None)
    entry.setdefault("corrects_uid", None)
    entry.setdefault("notes", [])
    state.contact_log.append(entry)
    if entry.get("occurred_at") and (case["last_contact_at"] is None or entry["occurred_at"] >= case["last_contact_at"]):
        case["last_contact_at"] = entry["occurred_at"]
        case["last_contact_by"] = entry.get("officer_uid")
        case["last_result"] = entry.get("result")
    return entry


# --- notes (F7/F8): several notes per contact, and a note that is not a contact ----
#
# Controller ruling 2026-09-15: an unknown or already-attached-elsewhere uid must
# refuse the WHOLE note before anything is written — store.attach() has no guard of
# its own and would silently re-target a file already attached to someone else's
# record. So every uid is checked here, in a pre-flight, before `_note_record` ever
# calls store.attach. `_note_record` then attaches, knowing each uid is valid.
#
# Amendment (2026-09-15, ledgered): Task 24's "add a note to a saved contact" dialog
# uploads its files with X-Volt-Attach-To already set to this note's own target
# (contact:<uid>) — routers/attachments.py:81 attaches on upload. Those files must
# not be refused for being "already attached": a uid is accepted when it exists, is
# not deleted, and its attached_to is either None or ALREADY EQUAL to `target`.
# `target` is None for `log_contact` (the contact row does not exist yet at
# pre-flight time), so in practice only unattached files pass there.
def _check_note(text_value, attachment_uids, target=None, pointer_base=""):
    from .attachments import store
    if not text_value or not str(text_value).strip():
        raise CaseError("note_text_required", "A note needs text", message_th="ต้องพิมพ์ข้อความในบันทึก",
                        pointer=pointer_base + "/text")
    uids = list(attachment_uids or ())
    if len(uids) > settings.attachments_per_note:
        raise CaseError("too_many_attachments", "at most %d files per note" % settings.attachments_per_note,
                        message_th="แนบได้ไม่เกิน %d ไฟล์ต่อบันทึก" % settings.attachments_per_note,
                        pointer=pointer_base + "/attachment_uids")
    for att_uid in uids:
        found = store.get(att_uid)
        attached_to = found[0]["attached_to"] if found else None
        if found is None or (attached_to is not None and attached_to != target):
            raise CaseError("attachment_unknown", "unknown, deleted or already attached",
                            message_th="ไม่พบไฟล์แนบนี้ หรือไฟล์ถูกลบหรือแนบกับบันทึกอื่นแล้ว",
                            pointer=pointer_base + "/attachment_uids")


def _note_record(state, text_value, by, attachment_uids, target):
    from .attachments import store
    note = {"uid": state.uid("nt"), "text": str(text_value).strip(), "by": by, "at": clock.stamp(), "attachments": []}
    for att_uid in attachment_uids or ():
        note["attachments"].append(store.attach(att_uid, target))
    return note


def add_contact_note(state, contact_uid, text_value, by, attachment_uids=()):
    row = next((r for r in state.contact_log if r["uid"] == contact_uid), None)
    if row is None:
        raise CaseError("not_found", "no contact %s" % contact_uid, message_th="ไม่พบการติดต่อนี้")
    target = "contact:%s" % contact_uid
    _check_note(text_value, attachment_uids, target=target)
    note = _note_record(state, text_value, by, attachment_uids, target)
    row.setdefault("notes", []).append(note)
    if not row.get("note"):
        row["note"] = note["text"]
    from . import audit
    audit.describe(act="NOTE_ADDED", subject=("customer", row["customer_uid"]),
                   detail={"contact_uid": contact_uid, "attachments": len(note["attachments"])})
    return note


def add_case_note(state, case, text_value, by, attachment_uids=()):
    """A note that is not a contact at all: never counted, never spends the daily
    contact slot. It lives on state.events, not state.contact_log."""
    uid = state.uid("ev")
    target = "note:%s" % uid
    _check_note(text_value, attachment_uids, target=target)
    note = _note_record(state, text_value, by, attachment_uids, target)
    event = {"kind": "NOTE_ADDED", "uid": uid, "case_uid": case["uid"], "text": note["text"], "by": by,
             "on": str(settings.business_date), "at": note["at"], "attachments": note["attachments"]}
    state.events.append(event)
    from . import audit
    audit.describe(act="NOTE_ADDED", subject=("customer", case["customer_uid"]),
                   detail={"attachments": len(note["attachments"])})
    return event


def _make_ptp(state, case, amount, promise_date, created_by, source="APP", contact_uid=None):
    if case["open_ptp_uid"]:
        raise CaseError("ptp_already_open", "One open promise per customer", ptp_uid=case["open_ptp_uid"])
    promise_date = _valid_date(promise_date, "ptp_date_invalid")
    # Round-1 loophole: break, then promise again, reset the renegotiation count. A
    # promise made within 30 days of a broken one on the same case continues its lineage.
    last_broken = max((p for p in state.ptps.values() if p["customer_uid"] == case["customer_uid"] and p["status"] == "BROKEN"),
                      key=lambda p: (p["closed_on"] or "", p["uid"]), default=None)   # same-day breaks: the latest uid wins
    lineage = 0
    lineage_note_th = lineage_note_en = None
    lineage_from_closed_on = lineage_from_promise_date = None
    if last_broken and (last_broken["closed_on"] or "") >= str(settings.business_date - timedelta(days=30)):
        lineage = last_broken.get("renegotiation_count", 0) + 1
        # Round-2 nantapol N2-16: a fresh promise read "เจรจาใหม่แล้ว 1 ครั้ง" with nothing saying why.
        # Round-4 J4-03: ONE DATE FOR ONE EVENT. The sentence says "ผิดนัดเมื่อ" — the day
        # the promise BROKE (closed_on), never the day it was promised for. A promise made
        # for 30/10 and broken on 23/10 printed 30/10 under the words "broken on", and that
        # is the date an officer would quote to the customer.
        lineage_from_closed_on = last_broken["closed_on"] or last_broken["promise_date"]
        lineage_from_promise_date = last_broken["promise_date"]
        lineage_note_th = "ต่อเนื่องจากสัญญาที่ผิดนัดเมื่อ %s (%s)" % (lineage_from_closed_on, last_broken["uid"])
        lineage_note_en = "Continues the promise that broke on %s (%s)" % (lineage_from_closed_on, last_broken["uid"])
    ptp = {
        "uid": state.uid("ptp"), "case_uid": case["uid"], "customer_uid": case["customer_uid"],
        "promised_amount": str(Decimal(str(amount)).quantize(Decimal("0.01"))),
        "promise_date": str(promise_date), "created_by": created_by, "source": source,
        "status": "OPEN", "closed_on": None, "renegotiation_count": lineage,
        "lineage_note_th": lineage_note_th, "lineage_note_en": lineage_note_en, "lineage_from_uid": last_broken["uid"] if lineage else None,
        # J4-03: the two dates of the previous promise, each under its own name.
        "lineage_from_closed_on": lineage_from_closed_on,
        "lineage_from_promise_date": lineage_from_promise_date,
        "source_contact_uid": contact_uid, "broken_detected_at": None, "broken_reason": None,
    }
    state.ptps[ptp["uid"]] = ptp
    case["open_ptp_uid"] = ptp["uid"]
    if lineage >= 3 and not case["review_uid"]:
        request_review(state, case, "REPEATED_BROKEN_PTP", "นัดชำระครั้งที่สามหลังผิดนัดซ้ำบนยอดค้างเดิม", by="SYSTEM",
                       question_en="third promise after broken ones on the same arrears")
    case["next_action"], case["next_action_on"], case["next_action_set_by"] = "FOLLOW_PTP", str(promise_date), "SYSTEM"
    return ptp


def _break_ptp(state, case, ptp, on, reason=None, by="SYSTEM"):
    """Round-2 nantapol N2-16: a July promise was stamped BROKEN on 23/10. The promise
    is broken on its own date when that date has passed; the day it was noticed is
    broken_detected_at. An officer's reason travels with it."""
    on = date.fromisoformat(str(on)[:10])
    promised = date.fromisoformat(ptp["promise_date"])
    ptp["status"] = "BROKEN"
    ptp["closed_on"] = str(promised if promised < on else on)
    ptp["broken_detected_at"] = str(on)
    # Round-4 J4-04: a promise cannot fail before it is due. The app does not silently
    # accept it as if nothing were odd — the row carries the warning, in Thai, with the
    # gap named, and the route hands it to the screen for the officer to confirm.
    ptp["broken_before_due"] = promised > on
    ptp["broken_before_due_days"] = (promised - on).days if promised > on else 0
    ptp["broken_before_due_note_en"] = (
        "Broken before the promise date — promise %s still has %d days to go (business date %s). "
        "Confirm only when the customer has said they will not pay as promised"
        % (ptp["promise_date"], (promised - on).days, on)) if promised > on else None
    ptp["broken_before_due_note_th"] = (
        "บันทึกผิดนัดก่อนถึงวันนัด — นัดชำระ %s ยังเหลืออีก %d วัน (วันทำการ %s) "
        "ยืนยันเฉพาะเมื่อลูกค้าแจ้งแล้วว่าจะไม่ชำระตามนัด"
        % (ptp["promise_date"], (promised - on).days, on)) if promised > on else None
    ptp["broken_reason"] = (str(reason).strip() or None) if reason else None
    ptp["broken_by"] = by
    case["open_ptp_uid"] = None
    case["broken_ptp_count"] += 1
    # Round-3 J3-24: the promise status survived the break — the case still read
    # "ขอเลื่อนชำระ" / "นัดชำระ" after the promise it described was broken. A promise that
    # broke is no longer an arrangement, so the status the promise set is cleared and
    # says why. A status a PERSON governs is left alone (N2-09).
    if case["dc_status"] in ("EXTEND_PAYMENT_TO", "PTP") and \
            case.get("dc_status_set_by") in (None, "SYSTEM", "SHEET"):
        _set_dc(case, "NO_ACTION", "SYSTEM",
                "นัดชำระ %s ผิดนัดเมื่อ %s จึงไม่ใช่การขอเลื่อนชำระอีกต่อไป" % (ptp["uid"], ptp["closed_on"]),
                "Promise %s broke on %s, so it is no longer a payment extension" % (ptp["uid"], ptp["closed_on"]))
    case["next_action"], case["next_action_on"], case["next_action_set_by"] = "CALL", str(on), "SYSTEM"
    state.events.append({"kind": "PTP_BROKEN", "ptp_uid": ptp["uid"], "case_uid": case["uid"], "on": ptp["closed_on"],
                         "detected_on": str(on), "promise_date": ptp["promise_date"], "reason": ptp["broken_reason"], "by": by})


def _make_issue(state, case, fields):
    issue = {
        "uid": state.uid("iss"), "case_uid": case["uid"], "customer_uid": case["customer_uid"],
        "summary": fields.get("summary"), "responsible_team": fields.get("responsible_team", "CS"),
        "ticket_url": fields.get("ticket_url"), "ticket_ref": fields.get("ticket_ref"),
        "ticket_status": fields.get("ticket_status", "OPEN"), "deadline": fields.get("deadline"),
        "status": "OPEN", "opened_by": fields.get("opened_by"), "opened_on": fields.get("opened_on", str(settings.business_date)),
        "resolved_on": None, "closed_notified_at": None, "closed_by": None, "resolution_note": None,
        # Round-2 nantapol N2-07 / thip T2-08: the workflow freezes the fee AND the DPD
        # clock while a service issue is open (SERVICE_HOLD_FAULT_CONFIRMED stops both).
        "fee_clock": "PAUSED",
        "fee_clock_from": fields.get("opened_on", str(settings.business_date)),
        "fee_clock_until": None,
        "fee_clock_note_th": None, "fee_clock_note_en": None,       # set below, once the frozen day is known (J3-18)
        "fee_state": SERVICE_HOLD,
    }
    # Round-3 J3-18: the fee FELL 48.11 the moment the ticket opened, because the hold
    # excluded the opening day from accrual. A freeze that starts today holds the number
    # where it stands: the opening day still accrues, and the pause runs from the day
    # after. The panel now says both dates.
    opened = date.fromisoformat(str(issue["opened_on"])[:10])
    issue["fee_frozen_at_on"] = str(opened)
    issue["fee_clock_note_th"] = ("ค่าปรับและ DPD หยุดนับตั้งแต่ %s จนกว่าจะปิดตั๋ว (ตาม SOP) — ยอดค่าปรับคงไว้เท่ากับ ณ วันเปิดตั๋ว %s ไม่ลดลง"
                                  % (opened, opened))
    issue["fee_clock_note_en"] = ("Penalty and days-past-due stop counting from %s until the ticket closes — "
                                  "the penalty holds at its amount on the ticket's opening day %s and does not fall"
                                  % (opened, opened))
    state.issues[issue["uid"]] = issue
    case["open_issue_uid"] = issue["uid"]
    _apply_service_hold(case, opened)
    for contract in _contracts_of(case):
        _set_contract_fields(contract, service_hold_issue_uid=issue["uid"])
    # Round-4 J4-07: the ticket's deadline is the TICKET's own date and lives in its own
    # field. It is still the default next action when the officer named none — but it no
    # longer overwrites one they did name, and it is never lost when they do.
    case["ticket_deadline"] = issue["deadline"]
    case["ticket_deadline_note_th"] = ("กำหนดเสร็จของตั๋ว %s คือ %s" % (issue["uid"], issue["deadline"])) \
        if issue["deadline"] else "ตั๋ว %s ยังไม่มีกำหนดเสร็จ" % issue["uid"]
    case["ticket_deadline_note_en"] = ("Ticket %s is due to be finished on %s" % (issue["uid"], issue["deadline"])) \
        if issue["deadline"] else "Ticket %s has no finish date yet" % issue["uid"]
    case["next_action"], case["next_action_on"], case["next_action_set_by"] = "AWAIT_TICKET", fields.get("deadline") or str(settings.business_date), "SYSTEM"
    return issue


def _power_record(state, case, requested_by, backfilled=False):
    rec = {
        "uid": state.uid("pwr"), "case_uid": case["uid"], "customer_uid": case["customer_uid"],
        "requested_by": requested_by, "requested_at": str(settings.business_date), "reason": "ARREARS",
        "missed_count_at_request": None, "broken_ptp_at_request": case["broken_ptp_count"],
        "approver_role": settings.power_restriction_approver, "approved_by": None, "approved_at": None,
        "executed_by": None, "executed_at": None, "notified_om_at": None,
        "restore_due_at": None, "restored_at": None, "backfilled": backfilled,
        "state": "RESTRICTED" if backfilled else "REQUESTED",
    }
    state.power[rec["uid"]] = rec
    return rec


# --- public operations -----------------------------------------------------------

def get_case(state, customer_uid):
    case = state.cases.get(customer_uid)
    if case is None:
        raise CaseError("not_found", "No case for customer %s" % customer_uid)
    return case


def _valid_date(raw, code):
    """A date an officer typed must be a real ISO date within two years of the business
    date. Round-1 UAT saved a keyboard-mangled 61024-02-20 and the case read "no date"."""
    try:
        value = date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        raise CaseError(code, "%r is not a date (yyyy-mm-dd)" % raw)
    if abs(value.year - settings.business_date.year) > 2:
        raise CaseError(code, "%s is not within two years of the business date" % value)
    return value


def set_next_action(state, case, action, on, by, note=None):
    d = dictionaries.for_current()
    if not action or not on:
        raise CaseError("next_action_required", "Every case carries a next action and a date")
    d.resolve("NEXT_ACTION", action)
    if action == "AWAIT_REVIEW" and not _open_review_for(state, case):
        # Round-5 T5-03: the drawer let an officer close a contact with "waiting for the
        # manager" while no review had been raised, so the case looked escalated and
        # nobody was asked anything. Waiting on an answer requires a question.
        raise CaseError("review_required", "AWAIT_REVIEW needs an open review on the case",
                        message_th="ยังไม่ได้ส่งคำถามให้ผู้จัดการ — กด ส่งให้ผู้จัดการตรวจ ก่อน หรือเลือกงานถัดไปอย่างอื่น")
    on = _valid_date(on, "next_action_date_invalid")
    case["next_action"], case["next_action_on"], case["next_action_set_by"], case["next_action_note"] = action, str(on), by, note
    case["next_action_moved_from"] = None     # a fresh next action is not a moved one; the move route re-stamps it
    state.events.append({"kind": "NEXT_ACTION_SET", "case_uid": case["uid"], "action": action, "on": str(on), "by": by})
    return case


def _open_review_for(state, case):
    """The review currently blocking this case's workflow, if any.

    Threshold-only NPL reviews remain visible in the Manager queue but do not make
    an officer's unrelated action read as though it were awaiting that answer.
    """
    return next((r for r in state.reviews.values()
                 if (r["customer_uid"] == case["customer_uid"] and r["status"] == "OPEN"
                     and r.get("blocking", True))), None)

def set_dc_status(state, case, code, by, note=None, note_en=None):
    """A person's status, and a person's status carries a reason (Arina, 2026-09-11).

    Until now `note` was optional and the fallback wrote `"ตั้งโดย %s" % by` into
    dc_status_reason_th — a restatement of `by` sitting in the field a reader takes
    for a justification. Contract §1a: a confident wrong value outranks a blank, and
    a fabricated reason is exactly that. set_npl_type below has refused without one
    since J-46; this is the same rule on the field beside it.

    The dictionary code is resolved BEFORE the reason is checked, so an unknown code
    still raises DictionaryError rather than being masked by the reason refusal.
    """
    d = dictionaries.for_current()
    code = d.resolve("DC_STATUS", code)
    if not note or not str(note).strip():
        raise CaseError("reason_required", "Changing the follow-up status needs a reason",
                        message_th="ต้องระบุเหตุผลในการเปลี่ยนสถานะติดตาม")
    reason = str(note).strip()
    # R14's rule, borrowed from errors.override_source_unchanged: an adjustment that
    # changes nothing still leaves an audit row claiming someone changed something.
    if case.get("dc_status") == code:
        raise CaseError("status_unchanged",
                        "The follow-up status already reads %s" % code,
                        message_th="สถานะติดตามเป็นค่านี้อยู่แล้ว เลือกค่าอื่นหากต้องการเปลี่ยน",
                        code_value=code)
    previous = case.get("dc_status")
    case["dc_status"], case["dc_status_note"] = code, reason
    case["dc_status_set_by"], case["dc_status_reason_th"] = by, reason
    case["dc_status_reason_en"] = note_en or reason
    # The trail answers all four questions, not two: what it was, what it became,
    # who, and why. `from` was missing, so no reader could tell a NO_ACTION -> PAID
    # from a LEGAL_LETTER -> PAID.
    state.events.append({"kind": "DC_STATUS_SET", "case_uid": case["uid"],
                         "from": previous, "code": code, "by": by,
                         "reason": reason, "on": str(settings.business_date)})
    # These are the acts whose history gets asked about (interviews, disputes, a
    # supervisor reading the trail) — describe() is a no-op outside a request, so
    # calling it here costs nothing when this runs from a test or a job.
    from . import audit
    audit.describe(act="DC_STATUS_SET", subject=("customer", case["customer_uid"]),
                   detail={"from": previous, "to": code, "reason": reason})
    return case


def set_payment_status(state, case, code, by, reason=None):
    """A person's payment status, with a reason (Arina, 2026-09-14).

    SUPERSEDES PART OF Requirements Amendment v2.6 §3.6 (REQ-COL-075), which reads
    "payment_status is computed by the system". The system still computes it:
    `payment_status_system` keeps that answer, and follow_system_payment_status puts
    it back the moment it changes. But a person may now overrule it.
    Spec: docs/archive/superpowers/specs/2026-09-14-payment-status-adjustment-design.md

    Same order as set_dc_status: the code is checked BEFORE the reason, so an unknown
    code is never hidden behind the reason refusal.
    """
    _payment_status_fields(case)
    if code not in MANUAL_PAYMENT_STATUSES:
        raise CaseError("payment_status_unknown",
                        "%r is not a manually settable payment status; use one of %s" %
                        (code, ", ".join(MANUAL_PAYMENT_STATUSES)),
                        message_th="ไม่รู้จักสถานะการชำระนี้", known=list(MANUAL_PAYMENT_STATUSES))
    # 2026-09-20: TERMINATED exists, but not as a free pick — it must carry a cause
    # and a closed balance, so it is set by the terminate act alone. The refusal
    # points there rather than letting this route write a status with no cause.
    if code == "TERMINATED":
        raise CaseError("payment_status_terminate_via_route",
                        "TERMINATED is set by terminating the contract, with a cause",
                        message_th="สถานะยุติสัญญาตั้งได้จากคำสั่งยุติสัญญาเท่านั้น (ต้องระบุสาเหตุและปิดยอดก่อน)")
    if not reason or not str(reason).strip():
        raise CaseError("reason_required", "Changing the payment status needs a reason",
                        message_th="ต้องระบุเหตุผลในการเปลี่ยนสถานะการชำระ")
    reason = str(reason).strip()
    # R14's rule, as on set_dc_status: a change that changes nothing would still leave
    # a record claiming someone changed something.
    if case["payment_status"] == code:
        raise CaseError("status_unchanged", "The payment status already reads %s" % code,
                        message_th="สถานะการชำระเป็นค่านี้อยู่แล้ว เลือกค่าอื่นหากต้องการเปลี่ยน",
                        code_value=code)
    previous = case["payment_status"]
    system = case.get("payment_status_system")
    # Shared for everyone (Arina, 2026-09-24): written through the one store BEFORE the
    # case moves, so a store that refuses leaves this session unchanged too. Every other
    # session applies it on its next read (for_current).
    if code == system:
        payment_overrides.retire(case["customer_uid"], by)
    else:
        payment_overrides.set(case["customer_uid"], code, system, reason, by)
    case["payment_status"] = code
    if code == system:
        # Put back to the system's own answer: nothing is left to overrule.
        case["payment_status_set_by"], case["payment_status_reason"] = None, None
    else:
        case["payment_status_set_by"], case["payment_status_reason"] = by, reason
    state.events.append({"kind": "PAYMENT_STATUS_SET", "case_uid": case["uid"],
                         "from": previous, "code": code, "system": system, "by": by,
                         "reason": reason, "on": str(settings.business_date), "ended": None})
    from . import audit
    audit.describe(act="PAYMENT_STATUS_SET", subject=("customer", case["customer_uid"]),
                   detail={"from": previous, "to": code, "system": system, "reason": reason})
    from . import monthly_history
    monthly_history.safe_snapshot("override", uids=[case["customer_uid"]])
    return case


def set_npl_type(state, case, code, by, role, reason=None, via_review=None, by_role=None):
    if role not in ("MANAGER", "OWNER"):
        raise CaseError("forbidden", "Only a Manager sets the NPL type")
    if not reason or not str(reason).strip():
        # Judge J-46: the type is a Manager's judgement; the record keeps why.
        raise CaseError("reason_required", "Setting the NPL type needs a reason",
                        message_th="ต้องระบุเหตุผลในการกำหนดประเภท NPL")
    if code is None or not str(code).strip():
        # Judge round 2 (J2-16 observation): an empty code used to close the
        # SYSTEM review while leaving the case without a type.
        raise CaseError("npl_type_required", "The NPL type code is required",
                        message_th="ต้องเลือกประเภท NPL")
    # Round-4 J4-12: the type describes an NPL customer's recovery track. Nothing gated
    # it, so a merely LATE customer could be put on the decommission track — and the act
    # reaches the weekly npl_changes log a lead pastes upstairs.
    if case["payment_status"] != "NPL":
        raise CaseError("npl_type_not_applicable",
                        "The NPL type applies to an NPL customer; this case is %s" % case["payment_status"],
                        message_th="กำหนดประเภท NPL ได้เฉพาะลูกค้าที่สถานะเป็น NPL เท่านั้น — เคสนี้สถานะ %s "
                                   "ให้เปลี่ยนสถานะการชำระเป็น NPL ก่อน" % case["payment_status"],
                        payment_status=case["payment_status"], required_payment_status="NPL",
                        rule="REQ-COL-075", customer_uid=case["customer_uid"])
    d = dictionaries.for_current()
    case["npl_type"] = d.resolve("NPL_TYPE", code)
    # J4-12: the case says who classified and why — both were only ever in the event,
    # so no screen could show them.
    case["npl_type_set_by"] = by
    case["npl_type_set_by_role"] = by_role or role
    case["npl_type_reason"] = str(reason).strip()
    case["npl_type_set_on"] = str(settings.business_date)
    state.events.append({"kind": "NPL_TYPE_SET", "case_uid": case["uid"], "code": case["npl_type"], "by": by,
                         "by_role": by_role or role, "on": str(settings.business_date), "reason": str(reason).strip()})
    # Round-2 settasak S2-05: setting the type IS the answer to the system's NPL_TYPE_ASK.
    for review in state.reviews.values():
        if review["customer_uid"] == case["customer_uid"] and review["status"] == "OPEN" \
                and review["reason"] == "NPL_TYPE_ASK" and review["uid"] != via_review:
            review["decision"], review["status"] = "NPL_TYPE_SET", "ANSWERED"
            review["answered_by"], review["answered_at"], review["answered_by_role"] = by, str(settings.business_date), by_role or role
            review["comment"] = "กำหนดประเภท %s แล้ว: %s" % (d.label("NPL_TYPE", case["npl_type"]), str(reason).strip())
            review["closed_by_act"] = "NPL_TYPE_SET"
            if case["review_uid"] == review["uid"]:
                case["review_uid"] = None
            if case["next_action"] == "AWAIT_REVIEW":
                case["next_action"], case["next_action_on"], case["next_action_set_by"] = "CALL", str(settings.business_date), "SYSTEM"
    from . import audit
    audit.describe(act="NPL_TYPE_SET", subject=("customer", case["customer_uid"]),
                   detail={"to": case["npl_type"], "reason": case["npl_type_reason"]})
    return case


def _result_raises_review(result):
    """A flagged result (REFUSED_PAY and friends) raises its own review below."""
    if not result:
        return False
    row = dictionaries.for_current().get("CONTACT_RESULT", result)
    return bool(row and row.get("flag"))

def log_contact(state, case, fields, by):
    """One append-only row. The Act's counting is decided by the caller (the
    existing ContactLog enforces the daily slot); this records the fact.
    REQ-COL-070: a next action is required unless a PTP or an issue is created."""
    # Round-5 T5-03 / J5-09: an officer could close a contact with "waiting for the
    # manager" or "escalate" while no question had been asked, so the case looked
    # escalated and the review queue never heard about it. A contact that ESCALATES
    # must either raise the review itself (fields["review"]) or find one already open.
    # Reviews raised by the contact's own result (REFUSED_PAY) are created below and
    # are not caught here, which is why this checks the officer's own choice only.
    if fields.get("next_action") in ("AWAIT_REVIEW", "ESCALATE") \
            and not fields.get("review") and not _open_review_for(state, case) \
            and not _result_raises_review(fields.get("result")):
        raise CaseError(
            "review_required", "Escalating needs a question for the manager",
            message_th="เลือก \"รอผู้จัดการตอบ\" หรือ \"ส่งต่อผู้จัดการ\" ได้เมื่อส่งคำถามแล้ว — กด ส่งให้ผู้จัดการตรวจ ก่อน หรือเลือกงานถัดไปอย่างอื่น")
    # Round-4 R4-F51 / J4-02: every refusal this act can raise, raised BEFORE anything
    # is written (check_renegotiable's own precedent, below). Without this pre-flight,
    # a review_pending raised after the ptp/issue block would leave a half-written
    # contact — a PTP or an issue already created and no contact row for it.
    existing_review = _open_review_for(state, case)
    if fields.get("review") and existing_review:
        raise CaseError("review_pending", "A review is already open on this case",
                        review_uid=existing_review["uid"])
    # F7/F8: a contact may carry several notes, each with its own evidence files.
    # Checked here, beside the other pre-flight refusals and BEFORE the ptp/issue
    # block, so a refused note leaves no half-written contact, PTP or issue.
    notes = fields.get("notes") or []
    for i, n in enumerate(notes):
        _check_note(n.get("text"), n.get("attachment_uids"), pointer_base="/notes/%d" % i)
    d = dictionaries.for_current()
    result = d.resolve("CONTACT_RESULT", fields.get("result"))
    # R-E / feedback-r2 TASK-106 (F01c): a promise result needs an amount. The drawer
    # enforces it; this is the server's own refusal, named for the client to read.
    if result in ("REACHED_PTP", "PROMISED") and not (fields.get("ptp") or {}).get("amount"):
        raise CaseError("ptp_required_for_promise", "A promise needs an amount and a date",
                        message_th="ผลการติดต่อเป็นนัดชำระ ต้องระบุจำนวนเงินและวันที่นัดก่อนบันทึก")
    ptp = issue = None
    if fields.get("ptp"):
        p = fields["ptp"]
        ptp = _make_ptp(state, case, p["amount"], p["date"], created_by=by, contact_uid=None)
    if fields.get("issue"):
        issue = _make_issue(state, case, dict(fields["issue"], opened_by=by))
        derive_dc_status(state, case, "ISSUE_OPENED", by=by)   # the sheet's own practice; the work book filter finds it
        case["delay_cause"] = "VOLT_SERVICE_ISSUE"
    # Round-4 R4-F32 / R4-F51 (F3 BE-2): the officer's own question, raised HERE —
    # after the ptp/issue block, BEFORE set_next_action below — so AWAIT_REVIEW finds
    # the open review it needs (set_next_action's own gate, above) instead of
    # refusing a drawer that has no button for the review request it names. Docstring
    # at the top of this function has promised this since T5-03/J5-09; nothing built
    # it until now.
    review = None
    if fields.get("review"):
        r = fields["review"]
        review = request_review(state, case, r.get("reason"), r.get("question") or "", by=by,
                                question_th=r.get("question_th"), question_en=r.get("question_en"))
    if issue and fields.get("next_action") and fields.get("next_action_on"):
        # Round-4 J4-07: an officer who says "I will ring back on the 27th" while raising
        # a ticket due on the 12th of next month meant both. Their own next action stands
        # (it is what puts the row back on their list); the ticket's deadline is beside
        # it in case.ticket_deadline, never on top of it.
        set_next_action(state, case, fields["next_action"], fields["next_action_on"], by,
                        note="งานถัดไปนี้เจ้าหน้าที่ตั้งเอง — %s" % (case.get("ticket_deadline_note_th") or "ตั๋วมีกำหนดเสร็จของตัวเอง"))
    elif not (ptp or issue):
        if not fields.get("next_action") or not fields.get("next_action_on"):
            raise CaseError("next_action_required", "Say what happens next before closing the contact")
        set_next_action(state, case, fields["next_action"], fields["next_action_on"], by)
    row = _append_contact(state, case, {
        # Stamped on the app's business day (the demo runs on 2026-10-23) at the
        # wall-clock time, so the history reads in the same calendar as the case.
        "occurred_at": business_stamp(fields.get("occurred_at")),       # J3-19 / J4-01: one clock
        "officer_uid": by, "channel": fields.get("channel", "PHONE"), "direction": fields.get("direction", "OUTBOUND"),
        "result": result, "amount_stated": bool(fields.get("amount_stated")), "counted": bool(fields.get("counted")),
        # J4-02's second contact, declared not counted: the case row keeps the
        # declaration so the history shows its "ไม่นับ" chip (fix-all Leg R).
        "not_counted_declared": bool(fields.get("not_counted")),
        "note": fields.get("note"), "source": "APP", "ptp_uid": ptp["uid"] if ptp else None,
        "issue_uid": issue["uid"] if issue else None,
        # Round-4 R4-F32 (F3 BE-2): non-null only when THIS call created the review —
        # never a pre-existing one. log_contact's own return stays a 3-tuple (ten
        # sites unpack three); the router looks this up to answer the request.
        "review_uid": review["uid"] if review else None,
        "next_action": case["next_action"], "next_action_on": case["next_action_on"],
    })
    if notes:
        row["notes"] = [_note_record(state, n["text"], by, n.get("attachment_uids"), "contact:%s" % row["uid"])
                        for n in notes]
        if not row.get("note"):
            row["note"] = row["notes"][0]["text"]
    if ptp:
        derive_dc_status(state, case, "PTP", by=by)
    elif not issue:
        derive_dc_status(state, case, "CONTACT", result=result, next_action=fields.get("next_action"), by=by)
    if d.get("CONTACT_RESULT", result).get("flag"):
        label_th = d.label("CONTACT_RESULT", result) or result
        request_review(state, case, "DISPUTE" if result == "REFUSED_PAY" else "OTHER",
                       "ระบบส่งตรวจจากผลการติดต่อ: %s" % label_th, by="SYSTEM",
                       question_en="raised by the system from result %s" % result)
    from . import audit
    audit.describe(act="CONTACT_LOGGED", subject=("customer", case["customer_uid"]),
                   detail={"result": row["result"], "next_action": row["next_action"],
                           "counted": row["counted"]})
    return row, ptp, issue


# The setters that are not a person: what the seed, the import and the system wrote.
# A next action one of these set may be replaced; one an officer set may not (J4-07).
SYSTEM_SETTERS = ("SEED", "SYSTEM", "MAPLOG_IMPORT", "SERVICE_DEFERRAL", None)

UNREACHABLE_RESULTS = ("UNREACHABLE_NO_ANSWER", "LINE_SENT_UNREAD")


def _thai_date(moment):
    """Round-4 F3 BE-3: dd/mm/yyyy, as _sheet_reconciliation prints it
    (routers/today.py). Never clock.local_stamp_th here — that renders the
    BUSINESS date (R4-F59), and this sentence is about when a past run started.
    An unparseable stamp falls back to the previous behaviour, never a blank or
    an exception inside a served sentence."""
    try:
        d = date.fromisoformat(str(moment)[:10])
    except (TypeError, ValueError):
        return str(moment)[:10]
    return "%02d/%02d/%d" % (d.day, d.month, d.year)


def unreachable_run(state, customer_uid):
    """Round-4 J4-32: how many attempts since the customer was last actually reached.

    The SOP escalates "after repeated failure" and nothing counted the failures, so a
    supervisor reading a review could not tell the third from the first. Everything here
    is already in the case's own contact_log — it was only never added up.
    """
    rows = [r for r in state.contact_log if r["customer_uid"] == customer_uid]
    count, since, last_reach_at = 0, None, None
    for row in rows:                      # append-only, oldest first
        result = row.get("result")
        if row.get("kind") == "REMINDER":
            continue                      # a notification is not an attempt to reach
        if result in UNREACHABLE_RESULTS:
            count += 1
            since = since or row.get("occurred_at")
        elif result:
            count, since, last_reach_at = 0, None, row.get("occurred_at")
    return {
        "unreachable_since_last_reach": count,
        "first_unreachable_at": since,
        "last_reached_at": last_reach_at,
        "note_th": ("ติดต่อไม่ได้ต่อเนื่อง %d ครั้ง นับตั้งแต่ %s%s"
                    % (count, _thai_date(since),
                       (" (ติดต่อได้ครั้งล่าสุด %s)" % _thai_date(last_reach_at)) if last_reach_at else " (ยังไม่เคยติดต่อได้เลย)"))
                   if count else "ยังไม่มีการติดต่อไม่ได้ต่อเนื่อง",
        "note_en": ("Unreachable %d times in a row since %s%s"
                    % (count, _thai_date(since),
                       (" (last reached %s)" % _thai_date(last_reach_at)) if last_reach_at else " (never reached yet)"))
                   if count else "No run of unreachable attempts",
    }


def correct_contact(state, case, contact_uid, fields, by):
    old = next((r for r in state.contact_log if r["uid"] == contact_uid), None)
    if old is None:
        raise CaseError("not_found", "No contact %s" % contact_uid)
    row = _append_contact(state, case, dict(old, **fields, corrects_uid=old["uid"], officer_uid=by, source="APP"))
    return row


def close_ptp(state, case, ptp_uid, outcome, on, by, reason=None):
    ptp = state.ptps.get(ptp_uid)
    if ptp is None:
        raise CaseError("not_found", "No promise %s" % ptp_uid)
    if ptp["status"] != "OPEN":
        raise CaseError("ptp_already_closed", "Promise %s is %s" % (ptp_uid, ptp["status"]))
    if outcome == "BROKEN":
        _break_ptp(state, case, ptp, on, reason=reason, by=by)
    elif outcome in ("KEPT", "KEPT_PARTIAL"):
        ptp["status"], ptp["closed_on"] = outcome, str(on)
        case["open_ptp_uid"] = None
        case["kept_ptp_count"] += 1
        case["next_action"], case["next_action_on"], case["next_action_set_by"] = "SEND_REMINDER", str(_next_due_minus(date.fromisoformat(str(on)), reminder_offsets()[0])), "SYSTEM"
    else:
        raise CaseError("decision_unknown", "outcome must be KEPT, KEPT_PARTIAL or BROKEN")
    return ptp


THIRD_RENEGOTIATION_TH = "เจรจาใหม่ครั้งที่ 3 ต้องให้ผู้จัดการตรวจ"


def check_renegotiable(state, case, ptp_uid, amount, promise_date):
    """Round-4 J4-02: every refusal this act can raise, raised BEFORE anything is
    written — including the daily contact slot the route now spends. Returns
    (ptp, count, open_review, new_date). Called by renegotiate_ptp itself, so the two
    can never drift apart."""
    ptp = state.ptps.get(ptp_uid)
    if ptp is None or ptp["status"] not in ("OPEN", "BROKEN"):
        raise CaseError("ptp_already_closed", "Only an open or broken promise can be renegotiated",
                        message_th="นัดชำระนี้ปิดแล้ว เจรจาใหม่ได้เฉพาะนัดที่เปิดอยู่หรือผิดนัด")
    if ptp["status"] == "BROKEN" and case["open_ptp_uid"]:
        raise CaseError("ptp_already_open", "One open promise per customer", ptp_uid=case["open_ptp_uid"],
                        message_th="ลูกค้ามีนัดชำระที่เปิดอยู่แล้ว (%s) เจรจาใหม่จากนัดนั้นแทน" % case["open_ptp_uid"])
    count = ptp["renegotiation_count"] + 1
    open_review = state.reviews.get(case["review_uid"]) if case["review_uid"] else None
    if open_review and open_review["status"] == "OPEN" and open_review["reason"] == "REPEATED_BROKEN_PTP" and count > 3:
        raise CaseError("renegotiation_awaiting_review",
                        "A third renegotiation is under Manager review; wait for the answer before another",
                        message_th="%s — รอคำตอบคำขอตรวจ %s ก่อนเจรจาใหม่อีกครั้ง" % (THIRD_RENEGOTIATION_TH, open_review["uid"]),
                        review_uid=open_review["uid"], renegotiation_count=ptp["renegotiation_count"],
                        ptp_uid=ptp["uid"], promise_date=ptp["promise_date"])
    new_date = _valid_date(promise_date, "ptp_date_invalid")
    Decimal(str(amount)).quantize(Decimal("0.01"))
    return ptp, count, open_review, new_date


def renegotiate_ptp(state, case, ptp_uid, amount, promise_date, by):
    """Twice per instalment; the third is RECORDED and escalated (FigJam S10, REQ-COL-073).

    Round-2 nantapol N2-05: the third attempt was refused half-way and the typed date
    vanished. Now: everything is checked before anything moves; the new promise is
    always kept (still OPEN); the review references it; the response carries both.
    A further renegotiation while that review is unanswered is the one refusal, and
    it names the rule."""
    ptp, count, open_review, new_date = check_renegotiable(state, case, ptp_uid, amount, promise_date)
    previous_status = ptp["status"]
    if ptp["status"] == "OPEN":
        ptp["status"] = "RENEGOTIATED"
        case["open_ptp_uid"] = None
    case["renegotiation_count"] += 1
    new = _make_ptp(state, case, amount, new_date, created_by=by)
    new["renegotiation_count"] = count
    new["renegotiated_from"] = ptp["uid"]
    # J4-03: name which date this is. A renegotiation from a BROKEN promise quotes the
    # day it broke; one from an open promise quotes the day it was promised for.
    new["renegotiation_note_th"] = "เจรจาใหม่ครั้งที่ %d จาก %s (%s %s)" % (
        count, ptp["uid"],
        "ผิดนัดเมื่อ" if previous_status == "BROKEN" else "นัด",
        (ptp["closed_on"] or ptp["promise_date"]) if previous_status == "BROKEN" else ptp["promise_date"])
    ptp["renegotiated_to"] = new["uid"]
    ptp["closed_on"] = ptp["closed_on"] or str(settings.business_date)
    state.events.append({"kind": "PTP_RENEGOTIATED", "case_uid": case["uid"], "by": by, "on": str(settings.business_date),
                         "old_ptp_uid": ptp["uid"], "new_ptp_uid": new["uid"], "old_date": ptp["promise_date"],
                         "new_date": str(new_date), "old_amount": ptp["promised_amount"], "new_amount": new["promised_amount"],
                         "renegotiation_count": count, "previous_status": previous_status})
    review = None
    if count >= 3:
        if open_review and open_review["status"] == "OPEN":
            review = open_review          # the case already waits on the Manager; reference, never a second ask
        else:
            review = request_review(state, case, "REPEATED_BROKEN_PTP", "เจรจานัดชำระใหม่ครั้งที่สามบนงวดเดิม", by="SYSTEM",
                                    question_en="third renegotiation on the same instalment")
        review["ptp_uid"] = new["uid"]
        review.setdefault("ptp_uids", []).append(new["uid"])
        new["review_uid"] = review["uid"]
        new["escalated"] = True
        new["escalation_note_th"] = "%s — ส่งคำขอตรวจ %s แล้ว นัดชำระ %s ยังเปิดอยู่" % (THIRD_RENEGOTIATION_TH, review["uid"], new["promise_date"])
        state.events.append({"kind": "PTP_ESCALATED", "case_uid": case["uid"], "ptp_uid": new["uid"], "review_uid": review["uid"],
                             "on": str(settings.business_date), "renegotiation_count": count})
    return new, review


def detect_broken_ptps(state, as_of):
    """Nightly (02:30) and on demand: a promise whose date passed without a kept
    outcome is marked BROKEN by the system — never by an officer."""
    broken = []
    for ptp in list(state.ptps.values()):
        if ptp["status"] == "OPEN" and date.fromisoformat(ptp["promise_date"]) < as_of:
            case = state.cases[ptp["customer_uid"]]
            _break_ptp(state, case, ptp, as_of)
            broken.append(ptp["uid"])
    return broken


def request_review(state, case, reason, question, by, question_th=None, question_en=None,
                   allow_parallel=False, blocking=True):
    """Judge J-12a: every review carries `question_th`. A SYSTEM-raised review is
    written in Thai (the officer and the Manager read it); the English twin is kept
    in `question_en`. Judge J-15: `raised_at_time` is the business date + wall clock,
    so an age is never negative."""
    d = dictionaries.for_current()
    reason = d.resolve("REVIEW_REASON", reason)
    if (blocking and not allow_parallel and case["review_uid"]
            and state.reviews[case["review_uid"]]["status"] == "OPEN"):
        raise CaseError("review_pending", "A review is already open on this case", review_uid=case["review_uid"])
    question = question or ""
    if by == "SYSTEM":
        question_th = question_th or question
        question_en = question_en or question
        question = question_th
    else:
        question_th = question_th or question
        question_en = question_en or question
    review = {
        "uid": state.uid("rv"), "case_uid": case["uid"], "customer_uid": case["customer_uid"],
        "raised_by": by, "raised_at": str(settings.business_date), "raised_at_time": _now_on_business_date(),
        "reason": reason, "question": question, "question_th": question_th, "question_en": question_en,
        "blocking": blocking,
        "status": "OPEN", "answered_by": None, "answered_at": None, "decision": None, "comment": None,
        "snapshot": {
            "payment_status": case["payment_status"], "dc_status": case["dc_status"],
            "broken_ptp_count": case["broken_ptp_count"], "kept_ptp_count": case["kept_ptp_count"],
            "open_issue": bool(case["open_issue_uid"]), "last_contact_at": case["last_contact_at"],
            "sheet_days_late": case["sheet"]["days_late"],
        },
    }
    state.reviews[review["uid"]] = review
    if blocking:
        case["review_uid"] = review["uid"]
    if blocking and by != "SYSTEM":
        keep = case["next_action_on"] if (case["next_action_on"] or "") > str(settings.business_date) else str(settings.business_date)
        case["next_action"], case["next_action_on"], case["next_action_set_by"] = "AWAIT_REVIEW", keep, "SYSTEM"
    return review


# Round-4 J4-16: what each decision means for the case's next step, in the NEXT_ACTION
# dictionary's own codes. A Manager may override the pair on the answer itself.
DECISION_NEXT_ACTION = {
    "CONTINUE": "CALL",
    "ARRANGEMENT": "CALL",
    "RESTRUCTURE_PROPOSE": "ESCALATE",
    "LEGAL_REFER": "ESCALATE",
    "NPL_TYPE_SET": "CALL",
    "OTHER": "CALL",
}


def answer_review(state, review_uid, decision, comment, by, role, npl_type=None, by_role=None,
                  next_action=None, next_action_on=None):
    if role not in ("SUPERVISOR", "MANAGER", "OWNER"):
        raise CaseError("forbidden", "Only a Supervisor or Manager answers a review")
    review = state.reviews.get(review_uid)
    if review is None:
        raise CaseError("not_found", "No review %s" % review_uid)
    if review["status"] != "OPEN":
        raise CaseError("review_already_decided", "Review %s was answered" % review_uid)
    d = dictionaries.for_current()
    decision = d.resolve("REVIEW_DECISION", decision)
    case = state.cases[review["customer_uid"]]
    # Round-1 P2s: a decision that names an act performs the act, or is refused —
    # never stored as "answered" while the record disagrees.
    if decision == "NPL_TYPE_SET":
        if not npl_type:
            raise CaseError("npl_type_required", "Decision NPL_TYPE_SET must name the type")
        # Judge J-50: the event carries the code and a reason — the review's comment,
        # or the review itself when the Manager wrote none.
        set_npl_type(state, case, npl_type, by, role,
                     reason=(comment or "").strip() or "ตามคำตอบคำขอตรวจ %s" % review_uid, via_review=review_uid, by_role=by_role)
    # Round-3 J3-06: a cut-off request is DECIDED, not answered. A POWER_CUTOFF_ASK
    # review takes only อนุมัติ / ปฏิเสธ, and only from the role OQ-44 names.
    if review["reason"] == "POWER_CUTOFF_ASK":
        approver = settings.power_restriction_approver
        if decision not in POWER_DECISIONS:
            raise CaseError("power_decision_required",
                            "A power cut-off request is decided by %s (APPROVE or REJECT), not answered" % approver,
                            message_th="คำขอตัดระบบไฟต้องได้รับการตัดสิน (อนุมัติ หรือ ปฏิเสธ) โดย%s เท่านั้น — ตอบว่า \"%s\" ไม่ได้"
                                       % (ROLE_LABEL_TH.get(approver, approver), d.label("REVIEW_DECISION", decision) or decision),
                            approver_role=approver, allowed_decisions=list(POWER_DECISIONS),
                            review_uid=review_uid, power_uid=case["power_uid"])
        if role != approver and role != "OWNER":
            raise CaseError("forbidden", "Approver is %s — this answer is not stored" % approver,
                            message_th="ผู้อนุมัติคือ%s — บทบาทนี้ตัดสินคำขอตัดระบบไฟไม่ได้" % ROLE_LABEL_TH.get(approver, approver),
                            approver_role=approver, allowed_decisions=list(POWER_DECISIONS))
    if review["reason"] == "BOARD_MOVE_ASK":
        if decision not in BOARD_DECISIONS:
            raise CaseError("board_decision_required",
                            "A board move is approved or rejected, not answered",
                            message_th="คำขอย้ายคอลัมน์ต้องอนุมัติหรือปฏิเสธเท่านั้น",
                            allowed_decisions=list(BOARD_DECISIONS),
                            review_uid=review_uid)
        from . import journey as journey_domain
        js = journey_domain.for_current()
        pending = js.board_pending.pop(review["customer_uid"], None)
        if decision == "BOARD_MOVE_APPROVE" and pending is not None:
            pending["approved_by"] = by
            pending["approved_on"] = str(settings.business_date)
            # `derived_at_grant` is deliberately NOT re-taken here. It records the
            # derivation the officer's claim was made against, and that is the question
            # the Manager was asked. Re-pinning it against today's derivation would
            # launder an answer to an obsolete question into a fresh grant and let it
            # hold the card against data that has moved since — the one thing spec §6's
            # pin exists to prevent. If the case really did change while the review sat
            # open, the next read expires the override and says so in
            # BOARD_OVERRIDE_EXPIRED, naming what it was granted against.
            js.board_overrides[review["customer_uid"]] = pending
    # The mirror of the POWER arm below, and it exists for the same reason: a decision
    # that names an act may only answer the request that asked for the act. Without it
    # a Supervisor closes an NPL or broken-promise review with "อนุมัติย้ายคอลัมน์", the
    # case's review_uid is cleared, and the trail records an answer to a question
    # nobody asked. The reason arm above only refuses the OTHER direction — a foreign
    # decision on a board review.
    if decision in BOARD_DECISIONS and review["reason"] != "BOARD_MOVE_ASK":
        raise CaseError("board_decision_not_applicable",
                        "No board move is waiting for approval on this case — %s asks about %s"
                        % (review_uid, review["reason"]),
                        message_th="คำขอตรวจนี้ไม่ใช่คำขอย้ายคอลัมน์ — ตอบด้วยคำตัดสินการย้ายคอลัมน์ไม่ได้",
                        review_uid=review_uid, review_reason=review["reason"],
                        board_decisions=list(BOARD_DECISIONS))
    if decision in POWER_DECISIONS:
        rec = state.power.get(case["power_uid"]) if case["power_uid"] else None
        if rec is None or rec["state"] != "REQUESTED":
            raise CaseError("power_state_conflict", "No power restriction is waiting for approval on this case")
        if role != settings.power_restriction_approver and role != "OWNER":
            raise CaseError("forbidden", "Approver is %s — this answer is not stored" % settings.power_restriction_approver,
                            message_th="ผู้อนุมัติคือ%s" % ROLE_LABEL_TH.get(settings.power_restriction_approver, settings.power_restriction_approver),
                            approver_role=settings.power_restriction_approver)
    review["decision"] = decision
    review["comment"], review["answered_by"], review["answered_at"], review["status"] = comment, by, str(settings.business_date), "ANSWERED"
    review["answered_by_role"] = by_role or role      # S2-04: who answered, and as which role
    if case.get("npl_review_uid") == review_uid:
        case["npl_review_uid"] = None
    if case.get("review_uid") == review_uid:
        remaining = [r for r in state.reviews.values()
                     if (r["customer_uid"] == case["customer_uid"] and r["status"] == "OPEN"
                         and r.get("blocking", True))]
        case["review_uid"] = remaining[-1]["uid"] if remaining else None
    state.today_items.append({
        "uid": state.uid("ti"), "kind": "REVIEW_ANSWERED", "case_uid": case["uid"], "customer_uid": case["customer_uid"],
        "officer_uid": case["officer_uid"], "text": comment, "ref": review_uid, "on": str(settings.business_date), "done": False,
    })
    # Round-4 J4-16: the decision and the case's stated next step used to be unconnected
    # — every answer reset the case to a SYSTEM "CALL today" whatever the Manager decided.
    # The decision now shapes the step, the answering Manager signs it (so it is a
    # person's next action and reaches tier 2), and an explicit pair in the answer wins.
    if (decision not in POWER_DECISIONS and decision not in BOARD_DECISIONS
            and review["reason"] not in ("POWER_CUTOFF_ASK", "BOARD_MOVE_ASK")):
        action = next_action or DECISION_NEXT_ACTION.get(decision, "CALL")
        on = next_action_on or str(settings.business_date)
        if case["next_action"] == "AWAIT_REVIEW" or next_action:
            try:
                set_next_action(state, case, action, on, by,
                                note="ตามคำตอบคำขอตรวจ %s: %s%s"
                                     % (review_uid, d.label("REVIEW_DECISION", decision) or decision,
                                        (" — %s" % comment.strip()) if (comment or "").strip() else ""))
            except (CaseError, dictionaries.DictionaryError):
                # An unknown pair never costs the Manager their answer; the case keeps
                # the system default rather than the review staying open.
                case["next_action"], case["next_action_on"], case["next_action_set_by"] = "CALL", str(settings.business_date), "SYSTEM"
    elif case["next_action"] == "AWAIT_REVIEW":
        case["next_action"], case["next_action_on"], case["next_action_set_by"] = "CALL", str(settings.business_date), "SYSTEM"
    if review["decision"] == "POWER_CUTOFF_APPROVE" and case["power_uid"]:
        approve_power(state, case, by, role, by_role=by_role)
    if review["decision"] == "POWER_CUTOFF_REJECT" and case["power_uid"]:
        reject_power(state, case, by, role, reason=comment, by_role=by_role)
    return review


TICKET_CLOSED_TEXT_TH = "ปิดตั๋วแล้ว กลับมาติดตามต่อ"
TICKET_CLOSED_TEXT_EN = "ticket closed, resume follow-up"


def close_issue(state, case, issue_uid, by, note=None, resolution_note=None):
    """Judge J-13: the officer may close (the SOP lets them after O&M confirms), but
    the closure says how it was resolved and who closed it."""
    issue = state.issues.get(issue_uid)
    if issue is None:
        raise CaseError("not_found", "No issue %s" % issue_uid)
    if issue["status"] != "OPEN":
        raise CaseError("issue_already_closed", "Issue %s is %s" % (issue_uid, issue["status"]))
    if not resolution_note or not str(resolution_note).strip():
        raise CaseError("resolution_note_required", "Say how the ticket was resolved before closing it",
                        message_th="ต้องระบุผลการแก้ไขก่อนปิดตั๋ว")
    issue["status"], issue["ticket_status"], issue["resolved_on"] = "RESOLVED", "CLOSED", str(settings.business_date)
    issue["closed_notified_at"] = str(settings.business_date)
    issue["closed_by"] = by
    issue["resolution_note"] = str(resolution_note).strip()
    if case["open_issue_uid"] == issue_uid:
        case["open_issue_uid"] = None          # round-1: the case kept showing the issue open
        case["ticket_deadline"], case["ticket_deadline_note_th"] = None, None   # J4-07
        case["ticket_deadline_note_en"] = None
    # N2-07 / T2-08: the fee and the clock resume on closure; the paused days stay paused.
    _release_service_hold(case, date.fromisoformat(str(settings.business_date)))
    issue["fee_clock"], issue["fee_clock_until"] = "RESUMED", str(settings.business_date)
    issue["fee_clock_note_th"] = ("ค่าปรับและ DPD หยุดนับตั้งแต่ %s ถึง %s (ตั๋วปิดแล้ว กลับมานับต่อ) — ยอดค่าปรับคงไว้เท่ากับ ณ วันเปิดตั๋ว %s"
                                  % (issue["fee_clock_from"], issue["fee_clock_until"],
                                     issue.get("fee_frozen_at_on") or issue["fee_clock_from"]))
    issue["fee_clock_note_en"] = ("Penalty and days-past-due stopped counting from %s to %s (ticket closed, counting resumed) — "
                                  "the penalty held at its amount on the ticket's opening day %s"
                                  % (issue["fee_clock_from"], issue["fee_clock_until"],
                                     issue.get("fee_frozen_at_on") or issue["fee_clock_from"]))
    derive_dc_status(state, case, "ISSUE_CLOSED", by=by)   # N2-09: back to the status before the ticket
    state.events.append({"kind": "ISSUE_CLOSED", "case_uid": case["uid"], "issue_uid": issue_uid, "by": by,
                         "on": str(settings.business_date), "resolution_note": issue["resolution_note"]})
    state.today_items.append({
        "uid": state.uid("ti"), "kind": "TICKET_CLOSED", "case_uid": case["uid"], "customer_uid": case["customer_uid"],
        "officer_uid": case["officer_uid"], "text": note or TICKET_CLOSED_TEXT_TH,
        "text_th": note or TICKET_CLOSED_TEXT_TH, "text_en": note or TICKET_CLOSED_TEXT_EN,
        "resolution_note": issue["resolution_note"], "closed_by": by, "ref": issue_uid,
        "on": str(settings.business_date), "done": False,
    })
    # the hold ends only when the officer confirms with the customer (DC8)
    case["next_action"], case["next_action_on"], case["next_action_set_by"] = "CALL", str(settings.business_date), "SYSTEM"
    return issue


def request_power(state, case, by, missed_count, reason=None):
    if not settings.power_restriction_enabled:
        raise CaseError("feature_disabled", "Power restriction is disabled")
    if not reason or not str(reason).strip():
        # Judge J-48: a cut-off request carries the officer's reason, not only the counts.
        raise CaseError("reason_required", "A power restriction request carries its reason",
                        message_th="ต้องระบุเหตุผลในการขอตัดระบบไฟ")
    preconditions = power_preconditions(state, case, missed_count)
    unmet = [p for p in preconditions if not p["met"]]
    if unmet:
        # Round-2 settasak S2-03: the refusal names which precondition failed.
        raise CaseError("power_restriction_preconditions",
                        "Preconditions not met: %s" % ", ".join(p["code"] for p in unmet),
                        message_th="ยังไม่เข้าเงื่อนไขการตัดระบบไฟ: %s" % " · ".join(p["label_th"] for p in unmet),
                        preconditions=preconditions, unmet=[p["code"] for p in unmet],
                        missed=missed_count, broken_ptp_count=case["broken_ptp_count"])
    if case["power_state"] != "ON":
        raise CaseError("power_state_conflict", "Power is already %s" % case["power_state"],
                        message_th="สถานะไฟตอนนี้คือ %s" % POWER_STATE_LABEL_TH.get(case["power_state"], case["power_state"]))
    rec = _power_record(state, case, requested_by=by)
    rec["preconditions"] = preconditions
    rec["request_reason"] = str(reason).strip()
    state.events.append({"kind": "POWER_REQUESTED", "case_uid": case["uid"], "by": by, "on": str(settings.business_date),
                         "reason": rec["request_reason"]})
    rec["missed_count_at_request"] = missed_count
    case["power_state"], case["power_uid"] = "RESTRICTION_REQUESTED", rec["uid"]
    review = request_review(state, case, "POWER_CUTOFF_ASK",
                            "power restriction requested after %d missed and a broken promise: %s" % (missed_count, rec["request_reason"]), by=by,
                            question_th="ขอตัดระบบไฟหลังค้าง %d งวดและผิดนัดชำระ: %s" % (missed_count, rec["request_reason"]),
                            question_en="Power cut-off requested after %d missed instalments and a broken promise: %s" % (missed_count, rec["request_reason"]),
                            allow_parallel=bool(case.get("review_uid") and
                                                state.reviews[case["review_uid"]].get("reason")
                                                in ("NPL_REVIEW", "NPL_TYPE_ASK")))
    rec["review_uid"] = review["uid"]
    from . import audit
    audit.describe(act="POWER_REQUESTED", subject=("customer", case["customer_uid"]),
                   detail={"reason": rec["request_reason"]})
    return rec


def power_preconditions(state, case, missed_count):
    """[{code, met, label_th, value}] — the three gates of REQ-MOD-040, each answered.
    Contact evidence is a logged contact row OR a recorded promise: a promise is taken
    in a contact, and the sheet's PTP columns are the only trace many rows carry."""
    contacts = sum(1 for r in state.contact_log if r["customer_uid"] == case["customer_uid"])
    promises = sum(1 for p in state.ptps.values() if p["customer_uid"] == case["customer_uid"])
    need = settings.power_restriction_min_missed
    rows = [
        {"code": "MIN_MISSED", "met": missed_count >= need, "value": missed_count,
         "label_th": "ค้างชำระอย่างน้อย %d งวด (ตอนนี้ %d งวด)" % (need, missed_count)},
    ]
    if settings.power_restriction_require_broken_ptp:
        rows.append({"code": "BROKEN_PTP", "met": case["broken_ptp_count"] >= 1, "value": case["broken_ptp_count"],
                     "label_th": "มีนัดชำระที่ผิดนัดอย่างน้อย 1 ครั้ง (ตอนนี้ %d ครั้ง)" % case["broken_ptp_count"]})
    rows.append({"code": "CONTACT_LOGGED", "met": (contacts + promises) >= 1, "value": contacts + promises,
                 "label_th": "มีการติดต่อที่บันทึกไว้อย่างน้อย 1 ครั้ง — บันทึกการติดต่อหรือนัดชำระ (ตอนนี้ %d)" % (contacts + promises)})
    return rows


def approve_power(state, case, by, role, by_role=None):
    rec = state.power.get(case["power_uid"])
    if rec is None or rec["state"] != "REQUESTED":
        raise CaseError("power_state_conflict", "Nothing to approve")
    if role != settings.power_restriction_approver and role != "OWNER":
        raise CaseError("forbidden", "Approver is %s" % settings.power_restriction_approver)
    rec["approved_by"], rec["approved_at"], rec["state"] = by, str(settings.business_date), "APPROVED"
    rec["approved_by_role"] = by_role or role
    case["power_state"] = "RESTRICTION_APPROVED"    # S2-08: the case line no longer says "รออนุมัติ"
    state.events.append({"kind": "POWER_APPROVED", "case_uid": case["uid"], "by": by, "by_role": by_role or role,
                         "on": str(settings.business_date)})
    from . import audit
    audit.describe(act="POWER_APPROVED", subject=("customer", case["customer_uid"]))
    return rec


# Round-3 J3-07: the lifecycle after approval — who may do each act, in one place, so
# the API can tell the screen which button to draw and to whom.
POWER_EXECUTE_ROLES = ("SUPERVISOR", "MANAGER", "OWNER", "OPS")
POWER_RESTORE_ROLES = ("SUPERVISOR", "MANAGER", "OWNER", "OPS")


def power_next_act(case):
    """Round-3 J3-07: the case says what may happen next to the power and who may do it.
    RESTRICTION_APPROVED -> execute (cut) -> RESTRICTED -> restore -> ON."""
    state_code = case.get("power_state") or "ON"
    if state_code == "RESTRICTION_REQUESTED":
        return {"act": "approve", "label_th": "อนุมัติตัดไฟ", "roles": [settings.power_restriction_approver]}
    if state_code == "RESTRICTION_APPROVED":
        return {"act": "execute", "label_th": "ดำเนินการตัดไฟ", "roles": list(POWER_EXECUTE_ROLES)}
    if state_code in ("RESTRICTED", "RESTORE_DUE"):
        return {"act": "restore", "label_th": "คืนไฟ", "roles": list(POWER_RESTORE_ROLES)}
    return None


def reject_power(state, case, by, role, reason=None, by_role=None):
    """Round-3 J3-06: the approver may refuse. The request closes as REJECTED and the
    power goes back to ON — the case never sits on "รออนุมัติ" for a decided request."""
    rec = state.power.get(case["power_uid"]) if case["power_uid"] else None
    if rec is None or rec["state"] != "REQUESTED":
        raise CaseError("power_state_conflict", "Nothing to reject")
    if role != settings.power_restriction_approver and role != "OWNER":
        raise CaseError("forbidden", "Approver is %s" % settings.power_restriction_approver,
                        approver_role=settings.power_restriction_approver)
    rec["state"], rec["rejected_by"], rec["rejected_at"] = "REJECTED", by, str(settings.business_date)
    rec["rejected_by_role"] = by_role or role
    rec["reject_reason"] = (reason or "").strip() or None
    case["power_state"], case["power_uid"] = "ON", None
    state.events.append({"kind": "POWER_REJECTED", "case_uid": case["uid"], "by": by, "by_role": by_role or role,
                         "on": str(settings.business_date), "reason": rec["reject_reason"]})
    from . import audit
    audit.describe(act="POWER_REJECTED", subject=("customer", case["customer_uid"]),
                   detail={"reason": rec["reject_reason"]})
    return rec


def execute_power(state, case, by, notified_om=True, role="OPS"):
    rec = state.power.get(case["power_uid"])
    if rec is None or rec["state"] != "APPROVED":
        raise CaseError("power_state_conflict", "Not approved")
    if role not in POWER_EXECUTE_ROLES:
        raise CaseError("forbidden", "Cutting the power is an O&M or Supervisor act",
                        message_th="การตัดไฟทำได้โดยทีมปฏิบัติการ (O&M) หรือหัวหน้างานขึ้นไป",
                        allowed_roles=list(POWER_EXECUTE_ROLES))
    rec["executed_by"], rec["executed_at"], rec["state"] = by, str(settings.business_date), "RESTRICTED"
    rec["notified_om_at"] = str(settings.business_date) if notified_om else None
    case["power_state"] = "RESTRICTED"
    set_dc_status(state, case, "POWER_CUTOFF", by, note="ตัดไฟแล้ว %s" % settings.business_date,
                  note_en="Power cut off %s" % settings.business_date)
    state.events.append({"kind": "POWER_EXECUTED", "case_uid": case["uid"], "by": by, "on": str(settings.business_date)})
    from . import audit
    audit.describe(act="POWER_EXECUTED", subject=("customer", case["customer_uid"]))
    return rec


def payment_confirmed(state, case, on):
    """Any confirmed payment on a restricted case raises restoration (REQ-MOD-040);
    on any case the DC status follows the money (N2-09)."""
    derive_dc_status(state, case, "PAYMENT_CONFIRMED")
    if case["power_state"] != "RESTRICTED":
        return None
    rec = state.power.get(case["power_uid"])
    on = date.fromisoformat(str(on))
    due = on if clock.peek().hour < 15 else _next_business_day(on)      # J3-19: one clock
    rec["restore_due_at"], rec["state"] = str(due), "RESTORE_DUE"
    case["power_state"] = "RESTORE_DUE"
    return rec


def restore_power(state, case, by, role="SUPERVISOR"):
    # 26 August decision: restoration is by Supervisor or Customer Ops, not the officer.
    if role not in POWER_RESTORE_ROLES:
        raise CaseError("forbidden", "Restoration is a Supervisor's or Customer Ops act")
    rec = state.power.get(case["power_uid"])
    if rec is None or rec["state"] not in ("RESTRICTED", "RESTORE_DUE"):
        raise CaseError("power_state_conflict", "Nothing to restore")
    rec["restored_at"], rec["state"] = str(settings.business_date), "RESTORED"
    case["power_state"], case["power_uid"] = "ON", None
    if case["dc_status"] == "POWER_CUTOFF":
        set_dc_status(state, case, "NO_ACTION", by, note="คืนไฟแล้ว %s" % settings.business_date,
                      note_en="Power restored %s" % settings.business_date)
    state.events.append({"kind": "POWER_RESTORED", "case_uid": case["uid"], "by": by, "on": str(settings.business_date)})
    return rec


def _next_business_day(on):
    from datetime import timedelta
    nxt = on + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def mark_today_item_done(state, item_uid):
    for item in state.today_items:
        if item["uid"] == item_uid:
            item["done"] = True
            return item
    raise CaseError("not_found", "No item %s" % item_uid)


def follow_system_for_all():
    """After a PEAK report is applied (Task 8): every case in this session is re-checked
    the same way a contract change re-checks one — design F2 means applying a report can
    move LATE/CURRENT for every PEAK-linked customer at once, not just the one contract
    that changed. Returns the cases that moved."""
    state = for_current()
    moved = []
    for case in list(state.cases.values()):
        customer = customer_by_uid(case["customer_uid"])
        if customer is None:
            continue
        if _follow(state, case, customer) is not None:
            moved.append(case)
    return moved


def _refresh_sheet_snapshot(state, case, customer):
    """Refresh the case's copy of the sheet's own values after a re-import.

    `case["sheet"]` is a snapshot taken at seed; a corrected export left days-late,
    overdue, comments and the raw status frozen at first touch (sync audit,
    2026-09-20). Only import-derived fields move here. dc_status and npl_type follow
    only while the SHEET owns them, and a person's next action is never touched."""
    sheet = getattr(customer, "sheet", None) or {}
    row = sheet.get("leasing") or sheet.get("cash") or {}
    tracking = sheet.get("tracking") or {}
    fresh = {
        "days_late": row.get("days_late"),
        "late_fees": row.get("late_fees"),
        "overdue": row.get("overdue"),
        "bucket": row.get("bucket"),
        "payment_status": row.get("payment_status") or tracking.get("category"),
        "dc_status_raw": row.get("dc_status"),
        "npl_type_raw": row.get("npl_type"),
        "comment_th": row.get("comment_th") or row.get("comment") or tracking.get("note"),
        "comment_en": row.get("comment_en"),
        "source_refs": sheet.get("source_refs"),
    }
    current = case.setdefault("sheet", {})
    changed = sorted(k for k, v in fresh.items() if current.get(k) != v)
    if not changed:
        return None
    current.update({k: fresh[k] for k in changed})
    case["sheet_refreshed_on"] = str(settings.business_date)
    if "dc_status_raw" in changed and case.get("dc_status_set_by") in (None, "SHEET", "SYSTEM"):
        try:
            case["dc_status"] = dictionaries.for_current().resolve("DC_STATUS", fresh["dc_status_raw"]) or "NO_ACTION"
            case["dc_status_set_by"] = "SHEET" if fresh["dc_status_raw"] else "SYSTEM"
        except dictionaries.DictionaryError:
            case["dc_status"] = None
            case["dc_status_note"] = "sheet value not in the dictionary: %s" % fresh["dc_status_raw"]
    if "npl_type_raw" in changed and not case.get("npl_type_set_by"):
        try:
            case["npl_type"] = dictionaries.for_current().resolve("NPL_TYPE", fresh["npl_type_raw"])
        except dictionaries.DictionaryError:
            case["npl_type"] = None
    state.events.append({"kind": "CASE_REFRESHED", "case_uid": case["uid"],
                         "fields": changed, "by": "IMPORT", "on": str(settings.business_date)})
    return changed


def follow_import_for_all():
    """The seed follows the imported facts for this session, in place.

    Payment status follows the system exactly as follow_system_for_all did; on top
    of that the case's sheet snapshot is refreshed and the next action is re-derived
    when the SEED (not a person, a promise or a MapLog import) owned it. Person work
    — contacts, PTPs, tickets, reviews, overrides — is never touched. Returns
    {"moved", "refreshed"} so the apply response can say what changed."""
    state = for_current()
    moved = follow_system_for_all()
    refreshed = 0
    for case in list(state.cases.values()):
        customer = customer_by_uid(case["customer_uid"])
        if customer is None:
            continue
        if _refresh_sheet_snapshot(state, case, customer):
            refreshed += 1
            if case.get("next_action_set_by") in ("SEED", "MAPLOG_IMPORT"):
                _default_next_action(case, settings.business_date)
    return {"moved": len(moved), "refreshed": refreshed}
