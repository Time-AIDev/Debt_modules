"""The journey domain — everything the Debt team's flow moves that the money engine
does not: invoices and receipts (AR pipeline), PTPs, collection cases on the deck's
ladders, restructures, manager reviews, NPL/recovery/repossession, month-37 service
billing, the S10 inter-company register, cancellations, board placement, and the
R11 priority tiers.

Design rules inherited from the rest of the app:
  - State is per tester session (session.Store), seeded deterministically from the
    fixture book so every tester starts from the same demo state.
  - Money is Decimal. Uids are prefixed strings. Every routed object carries
    entity + company_id together (entities.assert_entity_present).
  - Stages move only by explicit human POST. app/ladder.py computes INDICATIVE
    rungs only (OD-04: a human flags).
  - Receipts never write instalment components while OD-02 is open — the same
    asymmetry as the PEAK webhook: recorded, unallocated, exception raised.
"""
from datetime import date, timedelta
from decimal import Decimal

from . import ladder as ladder_mod
from .config import settings
from .entities import EPC, SPV, entity_fields, entity_for
from .pipelines.peak_writer import RECEIPT_SOURCE
from .session import Store

# --- constants -------------------------------------------------------------------

INVOICE_KINDS = ("DEPOSIT", "HANDOVER_BALANCE", "INSTALMENT", "PENALTY",
                 "SERVICE_MONTHLY", "PROJECT_SALE", "BUYBACK", "SERVICE_BULK")
INVOICE_STATES = ("DRAFT", "AR_REVIEW", "ISSUED", "SENT", "PARTIALLY_PAID", "PAID",
                  "OVERDUE", "REVIEW_ORIGINAL", "CANCELLED")


def invoice_collection_sort_key(invoice):
    """One collection-facing order for invoice tables and compact previews."""
    actionable = {"OVERDUE": 0, "PARTIALLY_PAID": 1, "SENT": 2, "ISSUED": 3}
    fallback = {state: 10 + index for index, state in enumerate(INVOICE_STATES)}
    state = invoice.get("state")
    return (
        actionable.get(state, fallback.get(state, 99)),
        str(invoice.get("due_date") or "9999-12-31"),
        invoice.get("uid") or "",
    )

PTP_STATUSES = ("OPEN", "KEPT", "KEPT_PARTIAL", "BROKEN", "CANCELLED")

REVIEW_REASONS = ("BROKEN_PTP", "REFUSE_TO_PAY", "UNREACHABLE", "ARRANGEMENT_BROKEN",
                  "RESTRUCTURE_FAILED", "ESCALATED_OTHER")
REVIEW_DECISIONS = ("CONTINUE_FOLLOWUP", "REPAYMENT_ARRANGEMENT", "RESTRUCTURE",
                    "CONFIRM_NPL")

RECOVERY_STRATEGIES = ("LEGAL", "REPOSSESSION", "COOP_DECOMMISSION",
                       "EXTERNAL_COLLECTION")
RECOVERY_OUTCOMES = ("FULL", "PARTIAL", "NO_CONCLUSION", "CLOSED_WRITE_OFF")
# Q2 / feedback-r2 TASK-112: a strategy change closes the old record as SUPERSEDED
# and opens a new one — the money already recovered stays with the strategy that
# earned it, so the old record is never mutated into a different path.
RECOVERY_STATUSES = ("IN_PROGRESS", "RESOLVED", "SUPERSEDED")

# Delta-100 D2c / REC-11. The prototype's recovery-path cards carry a commercial
# sample rate per path (72% restructure / 55% settlement / 38% recovery of the
# remaining NPV). Those are ILLUSTRATIONS, not rulings: no decision register entry
# exists for them, and two of the three name paths this model does not offer as
# recovery strategies (restructure is a ladder flow; settlement was never confirmed
# — REC-12). The four strategies below are all the prototype's 38% "ถอดระบบและ
# เรียกคืนทรัพย์" enforcement family, so that one declared commercial assumption is
# what every served figure is computed from, and every payload carries
# rate_basis_* saying exactly that. Replace when a real recovery model is ruled;
# nothing here decides anything. EXTERNAL_COLLECTION carries no rate at all because
# D27 has not approved the path — no estimate is offered for a path that cannot be
# opened.
RECOVERY_RATE_PCT = {
    "LEGAL": Decimal("38"),
    "REPOSSESSION": Decimal("38"),
    "COOP_DECOMMISSION": Decimal("38"),
    "EXTERNAL_COLLECTION": None,
}
RECOVERY_RATE_BASIS_TH = ("สมมติฐานเชิงพาณิชย์จากตัวอย่างในแบบ (38% ของ NPV คงเหลือ) "
                          "— ยังไม่ใช่คำตัดสิน ต้องมีโมเดลการเรียกคืนที่ตัดสินแล้วก่อน")
RECOVERY_RATE_BASIS_EN = ("Commercial assumption from the design's sample (38% of the remaining NPV) "
                          "— not a ruling; a decided recovery model is still required")
RECOVERY_RATE_REFUSED_TH = ("แนวทางนี้ยังไม่ได้รับอนุมัติให้ใช้ (รอคำตัดสิน) "
                            "— จึงไม่ให้ตัวเลขประมาณการเรียกคืน")
RECOVERY_RATE_REFUSED_EN = ("This path is not yet approved for use (a decision is pending) "
                            "— no recovery estimate is offered")
# The rate the design's sample itself carries, for reconciliation on the card.
RECOVERY_RATE_DESIGN_SAMPLE = {"RESTRUCTURE": Decimal("72"), "SETTLEMENT": Decimal("55"),
                               "RECOVER": Decimal("38")}

LOT_STATUSES = ("PLANNED", "UNINSTALLED", "COUNTED", "GRADED", "PRICED", "SOLD")

WORKING_BUCKETS = ("DUE_TODAY", "OVERDUE", "PTP_DUE", "BROKEN_PTP", "SERVICE_ISSUE",
                   "UNREACHABLE", "ARRANGEMENT", "NPL_RECOVERY")

RECOVERY_BOARD_STAGES = ("CONTACT", "NEGOTIATE", "PROMISE", "ESCALATE", "RECOVERY")

PRIORITY_REASONS = ("PTP_DUE_TODAY", "DEEPEST_LADDER", "BROKEN_PTP", "LARGEST_ARREARS")


# --- the per-session state -------------------------------------------------------

class JourneyState:
    def __init__(self):
        self.invoices = {}
        self.receipts = {}
        self.ptps = {}
        self.cases = {}          # lease ladder cases, by uid
        self.cash_cases = {}
        self.restructures = {}
        self.reviews = {}
        self.npl_cases = {}
        self.recovery_cases = {}
        self.lots = {}
        self.service_accounts = {}   # by contract_uid
        self.issues = {}
        self.arrangements = {}
        self.intercompany = []
        self.cancellations = {}
        # Spec 2026-09-09: `board_overlay` was an unguarded per-session placement — any
        # caller could put any card anywhere and it was recorded as fact. It is replaced
        # by an override that must be justified, may need a Manager, and expires the
        # moment the data disagrees with it (board.column_for).
        self.board_overrides = {}    # customer_uid -> override record
        # A backward move is a claim the case is healthier than the record says, so it
        # is HELD here — keyed the same way — until a Manager answers its review, and
        # nothing reads it as a placement. Its own dict rather than a reserved key
        # inside `board_overrides`: a magic key that must never collide with a customer
        # uid is a trap for whoever adds the next reader.
        self.board_pending = {}      # customer_uid -> pending override record
        self.board_last_served = {}  # customer_uid -> column_id, for BOARD_AUTO_MOVED
        # The board's audit trail is NOT here. BOARD_AUTO_MOVED and BOARD_OVERRIDE_EXPIRED
        # go where PTP_BROKEN goes — `cases.CaseState.events`, the one trail for a case.
        self.recovery_overlay = {}   # customer_uid -> stage
        # Ruling 40: POST /v1/customers/{uid}/assign used to write straight onto the
        # shared Customer fixture's `.officer` (routers/settings.py:242, pre-fix) — the
        # same shape as officer_overlay/recovery_overlay exist to prevent. This overlay is
        # the third of that pattern in this class: a session's reassignment of who holds
        # a customer never touches the fixture, only this per-session projection.
        self.officer_overlay = {}    # customer_uid -> officer_uid
        self.overrides = {}          # ref -> override record
        self.ladder_mode = settings.ladder_mode_default
        # Final fix F-R2: the PEAK report date THIS session's own receipts were seeded
        # from (the book's peak_report_as_of() at the moment _seed_migrated_invoices or
        # reseed_peak last ran for this state) — never touched by a GET. weekly_figures
        # reads it (peak_session_gap) to tell a session whose receipts are stale against
        # a report applied and reseeded only for another session, and to badge that
        # instead of serving a 0 that reads as nobody paid. None until a session is
        # seeded at least once.
        self.peak_as_of = None
        self._counter = 0

    def uid(self, prefix):
        self._counter += 1
        return "%s-%04d" % (prefix, self._counter)


def _factory():
    state = JourneyState()
    _seed(state)
    return state


_store = Store(_factory, key="journey.state")


def for_current() -> JourneyState:
    state = _store.for_current()
    # Search has a deliberately tiny overlay store so its first keystroke never
    # restores this full workflow graph. If an older persisted session already has
    # assignments here, any normal journey read migrates them forward lazily.
    if state.officer_overlay:
        from . import customer_search
        customer_search.remember_officer_overrides(state.officer_overlay)
    return state


def reconcile_overrides(order_lookup):
    """Re-truth every R14 override against the currently served orders.

    `source_changed_since_override` was written False once and never recomputed, so
    after a sync changed loan_status the override still claimed the source had not
    moved (sync audit, 2026-09-20). The flag is now a function of the order as it is
    served: True when the current value differs from the override's adjusted value,
    and `source_value_now` carries it. An order the current rung does not serve is
    flagged `source_missing`, never silently deleted — the override is a record a
    person made. Returns which refs moved or went missing.
    """
    state = for_current()
    changed, missing = [], []
    for ref, record in state.overrides.items():
        parts = ref.split(":", 2)
        key = parts[1] if len(parts) == 3 else ""
        order = order_lookup.get(key)
        if order is None:
            record["source_missing"] = True
            missing.append(ref)
            continue
        record["source_missing"] = False
        now = order.get(record.get("field"))
        record["source_value_now"] = now
        record["source_system"] = order.get("data_source") or record.get("source_system")
        # The source moved when it no longer reads as it did when the override was
        # taken — `source_value` is that snapshot; the override's adjusted value is
        # deliberately different by construction.
        moved = str(record.get("source_value")) != str(now)
        if moved != bool(record.get("source_changed_since_override")):
            changed.append(ref)
        record["source_changed_since_override"] = moved
    return {"changed": changed, "missing": missing}


# --- restructure concurrency guard (ruling 47) ------------------------------------
#
# Deliberately NOT a JourneyState field and NOT session-keyed, unlike officer_overlay /
# recovery_overlay above. Those exist because a session must NOT see another session's
# write. A concurrency guard needs the opposite: every session
# must see it, or it guards nothing. `routers/journey.py:approve_restructure` used to
# get this behaviour by accident, by reading `line.schedule_status` /
# `contract.instalments` straight off the shared Contract fixture object -- the
# session-isolation census (ruling 43) named this the one shared-mutable-Contract
# read it did NOT close, because closing it the way fee_state/status were closed
# (cases.py's per-session contract_field_of() overlay) would let a second session's
# restructure succeed silently: each session would consult only its OWN empty
# overlay slot and see no prior restructure. Ruling 47 replaces the accidental
# mechanism with a deliberate one, the same shape `main._IDEMPOTENCY` /
# `main._RETRACTABLE` already use for a cross-session write-once record -- keyed by
# the real contract uid (not by session), set once, checked by every session
# regardless of who set it.
#
# Ruling 47 deliberately did NOT move `contract.instalments` / `line.schedule_status`
# onto a per-session overlay in the same pass, because
# `test_adversarial_regressions.py::test_two_sessions_cannot_both_apply_a_restructure`
# read the raw shared attribute directly (outside any request, so outside any
# session context), and moving the schedule data would have broken that assertion
# without an authorised edit to make it.
#
# Ruling 49 authorised exactly that edit (the fourteenth), and the schedule data is
# now isolated too -- cases.py's `contract_field_of`/`_set_contract_fields`, a THIRD
# field on the same overlay, not a new mechanism. This lock stays exactly as
# designed above and is UNCHANGED by that: the lock is what stops a second session
# from succeeding at all; the overlay only decides who sees the resulting schedule
# once one session has won. See routers/journey.py:approve_restructure's own
# comment and this round's C-changes.md.
_RESTRUCTURE_LOCKS = {}
_restructure_locks_store = Store(dict, key="journey.restructure_locks")


def _restructure_locks():
    from .production_unit import CURRENT
    return _restructure_locks_store.for_current() if CURRENT.get() is not None else _RESTRUCTURE_LOCKS


def restructure_lock(contract_uid):
    """None if no session has restructured this contract yet, else the record of
    who did and when."""
    return _restructure_locks().get(contract_uid)


def lock_restructure(contract_uid, **info):
    """The only write path. Recorded BEFORE the schedule mutation it guards --
    the same ordering `main.py`'s Idempotency-Key check uses, so a second call
    arriving before the first finishes still sees the lock."""
    _restructure_locks()[contract_uid] = info


def reset():
    """Test seam, across every session — the same contract orders_domain.reset() has."""
    _store.reset()
    _RESTRUCTURE_LOCKS.clear()


# --- book access (honours the conftest monkeypatch seam) --------------------------

def book_customers():
    from . import main
    return main.CUSTOMERS


def identity_customers():
    """The contract-less customers the serving source holds (2026-09-19 ruling).

    Kept beside the book, never inside it: the domain's loops are contract-only by
    construction, and an identity has no contract to collect on. The workbook lists
    these and the record opens them."""
    from . import main
    return main.IDENTITIES


def customer_by_uid(uid):
    from . import main
    return main.BY_CUSTOMER.get(uid)


def contract_by_uid(uid):
    from . import main
    return main.BY_CONTRACT.get(uid)


def _customer_uid_for_contract(contract_uid):
    """Task 25c: the customer a contract_uid actually belongs to, right now — used to
    tell whether a receipt and the invoice it names still belong to the SAME
    customer, since a link a Manager confirms can move a PEAK invoice to a different
    customer at the next reseed while the receipt's own contract_uid never changes."""
    found = contract_by_uid(contract_uid)
    return found[0].uid if found else None


# --- derived facts ---------------------------------------------------------------

def month_index(acceptance: date, as_of: date) -> int:
    """S09 — month 1 starts at system acceptance. Month 37 is the first billable."""
    if acceptance is None:
        return 0
    return (as_of.year - acceptance.year) * 12 + (as_of.month - acceptance.month) + 1


def missed_count(contract, as_of=None) -> int:
    as_of = as_of or settings.business_date
    # Ruling 49: session-scoped read — a session that has not restructured this
    # contract must not count missed instalments off another session's addendum.
    from . import cases as cases_domain
    return sum(
        1 for line in cases_domain.contract_field_of(contract, "instalments")
        if line.is_active_regular and line.due_date < as_of and line.outstanding_amount > 0
    )


def ladder_kind(contract) -> str:
    return "LEASE" if contract.product == "LEASE" else "CASH"


def case_for_customer(state: JourneyState, customer_uid):
    for case in state.cases.values():
        if case["customer_uid"] == customer_uid:
            return case
    return None


def cash_case_for_customer(state: JourneyState, customer_uid):
    for case in state.cash_cases.values():
        if case["customer_uid"] == customer_uid:
            return case
    return None


def open_ptp_for(state: JourneyState, customer_uid):
    for ptp in state.ptps.values():
        if ptp["customer_uid"] == customer_uid and ptp["status"] == "OPEN":
            return ptp
    return None


def broken_ptp_for(state: JourneyState, customer_uid):
    return [p for p in state.ptps.values()
            if p["customer_uid"] == customer_uid and p["status"] == "BROKEN"]


def open_issue_for(state: JourneyState, customer_uid):
    return [i for i in state.issues.values()
            if i["customer_uid"] == customer_uid and i["status"] != "RESOLVED"]


def open_review_for(state: JourneyState, customer_uid):
    return [r for r in state.reviews.values()
            if r["customer_uid"] == customer_uid and r["status"] == "OPEN"]


def customer_stage(state: JourneyState, customer) -> str:
    """The actual (human-moved) ladder stage of the customer's worst case."""
    case = case_for_customer(state, customer.uid)
    cash = cash_case_for_customer(state, customer.uid)
    stages = [c["stage"] for c in (case, cash) if c]
    if not stages:
        return "NORMAL"
    return max(stages, key=ladder_mod.stage_depth)


def ladder_payload_for(state: JourneyState, customer, dpd, missed):
    """One ladder block per customer, keyed on the worst receivable's kind."""
    cash = cash_case_for_customer(state, customer.uid)
    case = case_for_customer(state, customer.uid)
    if cash and not case:
        kind, actual = "CASH", cash["stage"]
        markers = {}
    else:
        kind = "LEASE" if any(k.product == "LEASE" for k in customer.contracts) else "CASH"
        actual = case["stage"] if case else "NORMAL"
        markers = {}
        if case:
            markers = {
                "restructure_offered": any(
                    h["stage"] == "RESTRUCTURE_OFFER_60" for h in case["stage_history"]),
                "npl_declared": case.get("npl_uid") is not None,
                "assigned_to_epc": case["stage"] == "ASSIGNED_120",
            }
    payload = ladder_mod.ladder_payload(kind, actual, dpd, missed,
                                        mode=state.ladder_mode, markers=markers)
    # F05 / feedback-r2 TASK-109: the strip knows which journey case it draws, so a
    # hand move can call the right :set-stage route without guessing.
    payload["kind"] = kind
    payload["case_uid"] = cash["uid"] if kind == "CASH" and cash else (case["uid"] if case else None)
    return payload


# --- R11: the priority tiers ------------------------------------------------------

def priority_key(state: JourneyState, customer, arrears: Decimal, business_date: date):
    """Tiered sequential sort (R11, Arina, verbatim order): PTP due today →
    biggest arrears → deepest ladder → broken PTP. Lexicographic on purpose."""
    ptp = open_ptp_for(state, customer.uid)
    ptp_due_today = bool(ptp and ptp["promise_date"] == str(business_date))
    depth = ladder_mod.stage_depth(customer_stage(state, customer))
    broken = bool(broken_ptp_for(state, customer.uid))
    return (0 if ptp_due_today else 1, -arrears, -depth, 0 if broken else 1)


def priority_reason(state: JourneyState, customer, arrears: Decimal, business_date: date):
    ptp = open_ptp_for(state, customer.uid)
    if ptp and ptp["promise_date"] == str(business_date):
        return "PTP_DUE_TODAY"
    if ladder_mod.stage_depth(customer_stage(state, customer)) >= 3:
        return "DEEPEST_LADDER"
    if broken_ptp_for(state, customer.uid):
        return "BROKEN_PTP"
    return "LARGEST_ARREARS"


# --- factories -------------------------------------------------------------------

def make_invoice(state, contract_uid, entity, kind, amount, due_date, invoice_state,
                 scenario=None, issued_on=None):
    uid = state.uid("inv")
    state.invoices[uid] = {
        "uid": uid,
        "contract_uid": contract_uid,
        **entity_fields(entity),
        "kind": kind,
        "amount": str(Decimal(amount)),
        "due_date": str(due_date) if due_date else None,
        "issued_on": str(issued_on) if issued_on else None,
        "state": invoice_state,
        "scenario": scenario,
        "peak_state": None,       # LOCAL until issued to PEAK; SENT_PEAK / UNSENT after
        "peak_ref": None,
        "qr_payload": None,
        "channel": "QR_PEAK",     # every customer invoice is PEAK + QR, never transfer
    }
    return state.invoices[uid]


def make_receipt(state, contract_uid, entity, amount, received_on, invoice_uid=None,
                 matched="UNMATCHED"):
    uid = state.uid("rcp")
    state.receipts[uid] = {
        "uid": uid,
        "contract_uid": contract_uid,
        **entity_fields(entity),
        "amount": str(Decimal(amount)),
        "received_on": str(received_on),
        "invoice_uid": invoice_uid,
        "matched": matched,
        # OD-02 is open: recorded, never allocated to components. Same asymmetry
        # as the PEAK webhook — a real payment is never lost, and never guessed at.
        "is_allocated": False,
        "exception_raised": True,
        "pending_decision": "OD-02",
    }
    return state.receipts[uid]


def invoice_receipts(state, invoice):
    """Task 25c: every receipt booked against THIS invoice, by ITS OWN customer only.

    A receipt names an invoice by uid alone (`invoice_uid`); the receipt's own
    customer never changes, but the uid it names can now point at a DIFFERENT
    customer's invoice after a reseed moves the PEAK invoice that owned that uid
    (see `reseed_peak`'s `invoice_moved_to_other_customer`). Every place that adds
    up receipts for one invoice -- a paid-so-far / cumulative-match check, an
    outstanding computation -- must call this rather than filter `state.receipts`
    by `invoice_uid` alone, or a stranger's receipt counts toward this invoice.

    Fix round 1, minor: `_customer_uid_for_contract` returns None for a contract_uid
    that no longer resolves. A plain `==` would let TWO such orphaned records match
    each other (`None == None`) and count as the same customer by accident -- a
    receipt is counted only when the invoice's OWN customer resolves at all."""
    inv_customer = _customer_uid_for_contract(invoice["contract_uid"])
    if inv_customer is None:
        return []
    return [r for r in state.receipts.values()
            if r.get("invoice_uid") == invoice["uid"]
            and _customer_uid_for_contract(r["contract_uid"]) == inv_customer]


def make_case(state, customer_uid, contract_uid, stage="NORMAL", history=None):
    uid = state.uid("case")
    state.cases[uid] = {
        "uid": uid,
        "customer_uid": customer_uid,
        "contract_uid": contract_uid,
        **entity_fields(SPV),
        "ladder": "LEASE",
        "stage": stage,
        "stage_history": history or [],
        "restructure_uid": None,
        "npl_uid": None,
        "restructured": False,
        "post_assignment_owner": None,
    }
    return state.cases[uid]


def make_cash_case(state, customer_uid, contract_uid, stage, history=None, path=None):
    uid = state.uid("cash")
    state.cash_cases[uid] = {
        "uid": uid,
        "customer_uid": customer_uid,
        "contract_uid": contract_uid,
        **entity_fields(EPC),
        "ladder": "CASH",
        "stage": stage,
        "stage_history": history or [],
        "path": path,             # LEGAL_CLAIM | REMOVAL once confirmed
        "recovery_uid": None,
    }
    return state.cash_cases[uid]


def make_review(state, customer_uid, reason, source_ref=None, opened_by="system",
                snapshot=None):
    uid = state.uid("mrv")
    state.reviews[uid] = {
        "uid": uid,
        "customer_uid": customer_uid,
        "reason": reason,
        "source_ref": source_ref,
        "status": "OPEN",
        "opened_by": opened_by,
        "opened_on": str(settings.business_date),
        "snapshot": snapshot or {},
        "decision": None,
        "decided_by": None,
        "decided_on": None,
        "note": None,
    }
    return state.reviews[uid]


def make_ptp(state, customer_uid, amount, promise_date, created_by,
             contract_uids=(), source_contact_id=None, status="OPEN", kind="LEASE"):
    uid = state.uid("ptp")
    state.ptps[uid] = {
        "uid": uid,
        "customer_uid": customer_uid,
        "contract_uids": list(contract_uids),
        "promised_amount": str(Decimal(amount)),
        "promise_date": str(promise_date),
        "created_by": created_by,
        "source_contact_id": source_contact_id,
        "status": status,
        "closed_on": None,
        "receipt_uid": None,
        "broken_review_uid": None,
        "kind": kind,  # LEASE/CASH instalment promise, or SERVICE — never mixed
    }
    return state.ptps[uid]


def make_npl_case(state, case_uid, contract_uid, declared_on, declared_by):
    uid = state.uid("npl")
    state.npl_cases[uid] = {
        "uid": uid,
        "case_uid": case_uid,
        "contract_uid": contract_uid,
        **entity_fields(SPV),
        "declared_on": str(declared_on),
        "declared_by": declared_by,
        "provisioning_note": "Declared at 90 — provisioning and ECL only; the contract is not moved yet.",
        "assignment": None,
        "recovery_uid": None,
        "pending_decision": "OD-04",
    }
    return state.npl_cases[uid]


def remaining_npv(contract, as_of=None) -> Decimal:
    """100% of the remaining NPV — the buyback and acquisition basis (deck v20.0).

    INDICATIVE: discounted at the declared-but-open OQ-31 rate. Two rules the
    adversarial round enforced: the declared rate is EFFECTIVE annual, so the
    monthly factor is (1+r)^(1/12)-1 — never r/12, which underpaid SPV on every
    deed; and the discount horizon is TIME TO CASH — an instalment already past
    due is money owed today and enters at face, never discounted as future."""
    as_of = as_of or settings.business_date
    annual = settings.discount_rate_effective_annual / Decimal("100")
    monthly_rate = ((Decimal(1) + annual).ln() / Decimal(12)).exp() - Decimal(1)
    total = Decimal("0.00")
    # Ruling 49: session-scoped read, same reasoning as missed_count above.
    from . import cases as cases_domain
    for line in cases_domain.contract_field_of(contract, "instalments"):
        if not (line.is_active_regular and line.outstanding_amount > 0):
            continue
        months_out = max(0, (line.due_date.year - as_of.year) * 12
                         + (line.due_date.month - as_of.month))
        total += line.outstanding_amount / ((Decimal(1) + monthly_rate) ** months_out)
    pct = settings.acquisition_pct_of_npv / Decimal("100")
    return (total * pct).quantize(Decimal("0.01"))


def risk_score_for_customer(customer, as_of=None, aggregate=None):
    """Delta-100 D2a/D2c: one risk number for every row that needs a severity edge.

    The signals are the ones the system already holds, read through the same
    owners the working list reads: the money engine's aggregate (oldest DPD,
    arrears vs outstanding) and the case store's broken-PTP count and last
    contact. Returns None — never a zero pretending to be a score — for a
    customer that does not resolve.

    `aggregate` lets a caller hand in the (arrears, oldest_dpd, band,
    outstanding) snapshot it already computed and is about to serve, so the
    score is computed from the same figures on the same screen and the money
    engine is not asked twice for one row.
    """
    if customer is None:
        return None
    from . import cases as cases_domain
    from . import main
    from . import risk
    as_of = as_of or settings.business_date
    if aggregate is None:
        aggregate = main._customer_aggregate(customer)
    total, oldest, _band, outstanding = aggregate
    case = cases_domain.for_current().cases.get(customer.uid) or {}
    days = None
    last = case.get("last_contact_at")
    if last:
        try:
            days = (as_of - date.fromisoformat(str(last)[:10])).days
        except (TypeError, ValueError):
            days = None
    return risk.score(dpd=oldest, arrears=total, outstanding=outstanding,
                      broken_ptps=case.get("broken_ptp_count") or 0,
                      days_since_contact=days)


def execute_assignment(state, case, contract, executed_on, by):
    """The 120-day deed: contract + asset to EPC, EPC pays SPV 100% of remaining NPV,
    any month-37 service account is cancelled, EPC owns collection from here."""
    npv = remaining_npv(contract)
    deed = {
        "executed_on": str(executed_on),
        "by": by,
        "remaining_npv": str(npv),
        "npv_basis": "%s%% of remaining NPV — no discount, not 90 (deck v20.0)" % settings.acquisition_pct_of_npv,
        "is_indicative": True,
        "discount_rate_effective_annual": str(settings.discount_rate_effective_annual),
        "discount_rate_pending_decision": "OQ-31",
        "paid_by": EPC,
        "paid_to": SPV,
    }
    npl = state.npl_cases.get(case["npl_uid"]) if case.get("npl_uid") else None
    if npl:
        npl["assignment"] = deed
    case["post_assignment_owner"] = EPC
    # S10 docs 7 and 8: the deed and the buyback payment.
    add_intercompany(state, "ASSIGNMENT_DEED", SPV, EPC, None, executed_on,
                     contract.uid, note="Lease contract + asset, executed after 120 days past due")
    add_intercompany(state, "NPL_BUYBACK_PAYMENT", EPC, SPV, npv, executed_on,
                     contract.uid, note="100% of remaining NPV — no discount, against the deed")
    # Any month-37 service contract is cancelled with the lease at assignment.
    account = state.service_accounts.get(contract.uid)
    if account and account["status"] != "CANCELLED":
        account["status"] = "CANCELLED"
        account["cancelled_reason"] = "ASSIGNED_TO_EPC"
    return deed


def make_recovery(state, source_ref, contract_uid, strategy, entity,
                  opened_by=None, opened_on=None, opened_reason=None):
    uid = state.uid("rec")
    state.recovery_cases[uid] = {
        "uid": uid,
        "source_ref": source_ref,
        "contract_uid": contract_uid,
        **entity_fields(entity),
        "strategy": strategy,
        "status": "IN_PROGRESS",
        "recoveries": [],
        "recovered_total": "0.00",
        "outcome": None,
        # Who opened it, when and why (fix-all Leg R); null where the open came from
        # the seed or a ladder move rather than a person's open act.
        "opened_by": opened_by,
        "opened_on": opened_on,
        "opened_reason": opened_reason,
        "resolved_by": None,
        "resolved_on": None,
        # Q2 / TASK-112: the supersede lineage, null on a first open.
        "supersedes": None,
        "superseded_by": None,
        "superseded_on": None,
        "superseded_reason": None,
    }
    return state.recovery_cases[uid]


def make_lot(state, recovery_uid, contract_uid, lot_no, expected_count, watt,
             status="PLANNED", actual_count=None, grades=None):
    uid = state.uid("lot")
    fee = (Decimal(watt) * settings.uninstall_fee_thb_per_watt).quantize(Decimal("0.01"))
    state.lots[uid] = {
        "uid": uid,
        "lot_no": lot_no,
        "recovery_uid": recovery_uid,
        "contract_uid": contract_uid,
        **entity_fields(EPC),
        "status": status,
        "expected_count": expected_count,
        "actual_count": actual_count,
        "count_variance": (actual_count - expected_count) if actual_count is not None else None,
        "variance_note": None,
        "grades": grades or {},
        "product_code": "PANEL-550-R",
        "location": "WH/REFURB",
        "watt": watt,
        "uninstall_fee": str(fee),
        "resale_price": None,
        "priced_by": None,
        "stock_blocked": True,
        "sold_amount": None,
        "history_note": "Lot carries origin contract, removal date, site, grade, written-down value — audit only; nothing downstream waits on it.",
    }
    return state.lots[uid]


def add_intercompany(state, doc_type, from_entity, to_entity, amount, occurred_on,
                     contract_uid=None, note=None, manual=False):
    state.intercompany.append({
        "uid": state.uid("ico"),
        "doc_type": doc_type,
        "from_entity": from_entity,
        "to_entity": to_entity,
        "entity": from_entity,
        "company_id": entity_fields(from_entity)["company_id"],
        "amount": str(Decimal(amount)) if amount is not None else None,
        "occurred_on": str(occurred_on),
        "contract_uid": contract_uid,
        "note": note,
        "is_manual_outside_erp": manual,
    })
    return state.intercompany[-1]


def make_service_account(state, contract, as_of=None):
    as_of = as_of or settings.business_date
    idx = month_index(contract.acceptance_date, as_of)
    status = "PREPAID" if idx <= settings.service_prepaid_months else "BILLING"
    account = {
        "contract_uid": contract.uid,
        **entity_fields(EPC),
        "receivable_type": "SERVICE",
        "acceptance_date": str(contract.acceptance_date),
        "month_index": idx,
        "status": status,
        "monthly_amount": str(settings.service_monthly_floor_thb),
        "billing_window": {"from_day": settings.service_billing_window[0],
                           "to_day": settings.service_billing_window[1]},
        "channel": "QR_PEAK",
        "decline_requested": False,
        "decline_pending_decision": "SVC-37",
        "dunning_stage": "SVC_CURRENT",
        "cancelled_reason": None,
        "note": "Service arrears are EPC's own receivable and NEVER feed the lease NPL ladder (deck S09).",
    }
    state.service_accounts[contract.uid] = account
    return account


def make_issue(state, customer_uid, routed_to, summary, owner, status="OPEN"):
    uid = state.uid("iss")
    state.issues[uid] = {
        "uid": uid,
        "customer_uid": customer_uid,
        "routed_to": routed_to,     # CS | O_AND_M | OPS
        "owner": owner,
        "summary": summary,
        "status": status,           # OPEN | IN_PROGRESS | RESOLVED
        "opened_on": str(settings.business_date),
        "resolved_on": None,
        "note": "การติดตามหนี้หยุดรอจนแก้ไขเสร็จ — นาฬิกา DPD ไม่หยุด",
    }
    return state.issues[uid]


# --- the deterministic demo seed --------------------------------------------------

def _seed(state: JourneyState):
    by_no = {c.customer_no: c for c in book_customers()}
    bd = settings.business_date

    def contract(no, idx=0):
        return by_no[no].contracts[idx] if no in by_no else None

    # ---- S01: cash happy (C-002001) ----
    c = by_no.get("C-002001")
    if c:
        k = c.contracts[0]
        make_invoice(state, k.uid, EPC, "DEPOSIT", "20000", date(2026, 9, 10), "PAID",
                     scenario="S01", issued_on=date(2026, 9, 8))
        make_receipt(state, k.uid, EPC, "20000", date(2026, 9, 10),
                     matched="FULL")
        make_invoice(state, k.uid, EPC, "HANDOVER_BALANCE", "137353",
                     date(2026, 10, 30), "SENT", scenario="S01",
                     issued_on=date(2026, 10, 13))

    # ---- S11: cash default (C-002011) ----
    c = by_no.get("C-002011")
    if c:
        k = c.contracts[0]
        make_invoice(state, k.uid, EPC, "DEPOSIT", "20000", date(2026, 6, 5), "PAID",
                     scenario="S11", issued_on=date(2026, 6, 3))
        make_invoice(state, k.uid, EPC, "HANDOVER_BALANCE", "135000",
                     date(2026, 8, 20), "OVERDUE", scenario="S11",
                     issued_on=date(2026, 8, 2))
        make_cash_case(state, c.uid, k.uid, "SETTLEMENT_PLAN_60", history=[
            {"stage": "NOTICE_30", "on": "2026-09-19", "by": "noon",
             "note": "Notice and cure sent"},
            {"stage": "SETTLEMENT_PLAN_60", "on": "2026-10-19", "by": "noon",
             "note": "Instalment plan on the outstanding balance offered"},
        ])

    # ---- S07 rungs (C-002031/32/33/34) ----
    c = by_no.get("C-002031")
    if c:
        make_case(state, c.uid, c.contracts[0].uid, "NOTICE_30", history=[
            {"stage": "NOTICE_30", "on": "2026-10-20", "by": "ploy",
             "note": "1 instalment missed — notice and cure"},
        ])
    c = by_no.get("C-002032")
    if c:
        case = make_case(state, c.uid, c.contracts[0].uid, "RESTRUCTURE_OFFER_60", history=[
            {"stage": "NOTICE_30", "on": "2026-09-21", "by": "ploy", "note": "Notice"},
            {"stage": "RESTRUCTURE_OFFER_60", "on": "2026-10-20", "by": "ploy",
             "note": "Restructure OFFERED before NPL (S08)"},
        ])
        rst = state.uid("rst")
        state.restructures[rst] = {
            "uid": rst, "case_uid": case["uid"], "contract_uid": c.contracts[0].uid,
            "status": "PROPOSED", "proposed_by": "ploy",
            "proposed_on": str(date(2026, 10, 21)),
            "new_term_months": 72, "new_first_due": str(date(2026, 12, 1)),
            "approved_by": None, "missed_on_new_schedule": 0,
            "note": "Extend term / lower instalment — affordability assessed",
        }
        case["restructure_uid"] = rst
    c = by_no.get("C-002033")
    if c:
        case = make_case(state, c.uid, c.contracts[0].uid, "NPL_DECLARED_90", history=[
            {"stage": "NOTICE_30", "on": "2026-08-21", "by": "noon", "note": "Notice"},
            {"stage": "RESTRUCTURE_OFFER_60", "on": "2026-09-20", "by": "noon",
             "note": "Offer refused"},
            {"stage": "NPL_DECLARED_90", "on": "2026-10-19", "by": "Owner",
             "note": "Declared — provisioning only; month-4 window open"},
        ])
        npl = make_npl_case(state, case["uid"], c.contracts[0].uid,
                            date(2026, 10, 19), "Owner")
        case["npl_uid"] = npl["uid"]
    c = by_no.get("C-002034")
    if c:
        k = c.contracts[0]
        case = make_case(state, c.uid, k.uid, "ASSIGNED_120", history=[
            {"stage": "NOTICE_30", "on": "2026-07-16", "by": "noon", "note": "Notice"},
            {"stage": "RESTRUCTURE_OFFER_60", "on": "2026-08-15", "by": "noon",
             "note": "Offer unanswered"},
            {"stage": "NPL_DECLARED_90", "on": "2026-09-14", "by": "Owner",
             "note": "Declared"},
            {"stage": "ASSIGNED_120", "on": "2026-10-14", "by": "Owner",
             "note": "Deed executed after 120 days — the customer did not come back"},
        ])
        npl = make_npl_case(state, case["uid"], k.uid, date(2026, 9, 14), "Owner")
        case["npl_uid"] = npl["uid"]
        make_service_account(state, k)  # created so the assignment can cancel it
        execute_assignment(state, case, k, date(2026, 10, 14), "Owner")
        rec = make_recovery(state, npl["uid"], k.uid, "REPOSSESSION", EPC)
        npl["recovery_uid"] = rec["uid"]
        make_lot(state, rec["uid"], k.uid, "RP-2026-0148", expected_count=12,
                 watt=5000, status="GRADED", actual_count=11,
                 grades={"A": 6, "B": 4, "C": 1})
        lot = list(state.lots.values())[-1]
        lot["variance_note"] = "12 went up, 11 came back — reason and photo required; nobody can prove which"

    # ---- S08 active restructure (C-002035) ----
    c = by_no.get("C-002035")
    if c:
        case = make_case(state, c.uid, c.contracts[0].uid, "NORMAL", history=[
            {"stage": "RESTRUCTURE_OFFER_60", "on": "2026-09-10", "by": "ploy",
             "note": "Offered at 60 days"},
        ])
        case["restructured"] = True
        rst = state.uid("rst")
        state.restructures[rst] = {
            "uid": rst, "case_uid": case["uid"], "contract_uid": c.contracts[0].uid,
            "status": "ACTIVE", "proposed_by": "ploy",
            "proposed_on": str(date(2026, 9, 12)),
            "new_term_months": 60, "new_first_due": str(date(2026, 11, 1)),
            "approved_by": "Owner", "missed_on_new_schedule": 0,
            "note": "Old lines SUPERSEDED; two missed on THIS schedule declares NPL — no second restructure",
        }
        case["restructure_uid"] = rst

    # ---- S09: month-37+ service (C-002036) + prepaid examples ----
    for no in ("C-002001", "C-002031", "C-002036"):
        c = by_no.get(no)
        if c and c.contracts[0].acceptance_date:
            if c.contracts[0].uid not in state.service_accounts:
                make_service_account(state, c.contracts[0])
    c = by_no.get("C-002036")
    if c:
        k = c.contracts[0]
        account = state.service_accounts[k.uid]
        account["decline_requested"] = True
        account["dunning_stage"] = "SVC_OVERDUE"
        inv37 = make_invoice(state, k.uid, EPC, "SERVICE_MONTHLY",
                             settings.service_monthly_floor_thb, date(2026, 8, 25),
                             "PAID", scenario="S09", issued_on=date(2026, 8, 25))
        make_receipt(state, k.uid, EPC, settings.service_monthly_floor_thb,
                     date(2026, 8, 28), invoice_uid=inv37["uid"], matched="FULL")
        make_invoice(state, k.uid, EPC, "SERVICE_MONTHLY",
                     settings.service_monthly_floor_thb, date(2026, 9, 25),
                     "OVERDUE", scenario="S09", issued_on=date(2026, 9, 25))
        # S02/S10 doc 3: the project sale at acceptance, 100% of customer NPV.
        add_intercompany(state, "PROJECT_SALE_INVOICE", EPC, SPV, "288000",
                         date(2023, 8, 15), k.uid,
                         note="100% of customer NPV, single line, on system acceptance")
        # S10 doc 5: THB 50,000 accounting fee — manual, outside the ERP, unpostable.
        add_intercompany(state, "ACCOUNTING_FEE_50000", EPC, SPV,
                         settings.accounting_fee_thb, date(2023, 9, 1), None,
                         note="Once — the only standing inter-company fee. Manual, outside the ERP.",
                         manual=True)
        # S09: the bulk EPC→SPV service invoice — ONE manual document a month.
        # The book holds exactly one system past month 36, so the amount is 1 × 399
        # (the reconciles-to-nothing finding); the 3% WHT is withheld on payment.
        add_intercompany(state, "SERVICE_BULK_INVOICE", EPC, SPV,
                         settings.service_monthly_floor_thb,
                         date(2026, 9, 25), None,
                         note=("Month 37+ bulk service — one manual document; 1 active "
                               "system this month at THB 399; 3% WHT withheld on payment"),
                         manual=True)

    # ---- the journey backlog on the original six ----
    c = by_no.get("C-000912")   # PROMISE_DUE_TODAY — finally backed by an entity
    if c:
        make_ptp(state, c.uid, "6985.42", bd, "noon",
                 contract_uids=[k.uid for k in c.contracts])
        make_invoice(state, c.contracts[0].uid, EPC, "INSTALMENT", "6985.42",
                     date(2026, 10, 1), "OVERDUE", issued_on=date(2026, 9, 25))
    c = by_no.get("C-000871")   # BROKEN_PROMISE — the broken PTP and its review
    if c:
        ptp = make_ptp(state, c.uid, "11857.50", date(2026, 10, 20), "noon",
                       contract_uids=[k.uid for k in c.contracts], status="BROKEN")
        ptp["closed_on"] = str(date(2026, 10, 20))
        review = make_review(state, c.uid, "BROKEN_PTP", source_ref=ptp["uid"],
                             opened_by="system")
        ptp["broken_review_uid"] = review["uid"]
    c = by_no.get("C-001120")   # DISPUTE_OPEN — refuses to pay, no agreement
    if c:
        make_review(state, c.uid, "REFUSE_TO_PAY", opened_by="noon")
    c = by_no.get("C-001188")   # a service issue in flight, routed to O&M
    if c:
        make_issue(state, c.uid, "O_AND_M", "Inverter fault reported on the call",
                   owner="Krit (O&M)", status="IN_PROGRESS")

    # ---- 2026-09-02: invoices for the MIGRATED book (round-1 P1) ----------------
    # Every instalment the engine says is due and unpaid is an OVERDUE invoice, and
    # the next one is SENT (the sheet's "Link Sent"). Cash rows carry the sheet's own
    # PEAK invoice numbers. Without these, no slip can be recorded for a real customer.
    _seed_migrated_invoices(state, bd)

    # ---- S03/S05/S06: pre-install cancellations, order-level ----
    # Made-up rows: only the in-memory demo carries them. A landed book is the real
    # one (Arina, 2026-09-24), so none is invented beside it.
    from . import book as book_mod
    if book_mod.from_landing():
        return
    for phase, cause, outcome, order_no, kept_or_refund in (
        ("PRE_INSTALL", "CUSTOMER", "FORFEIT_DEPOSIT", 4, "Deposit forfeited — logged as EPC revenue (S03)"),
        ("PRE_INSTALL", "VOLT", "FULL_REFUND_WEEKLY_BATCH", 7, "100% refund — weekly batch, 7 business days (S05)"),
        ("PRE_INSTALL", "SITE", "REQUOTE_RESIGN", 10, "Revised package accepted; money carried over (S06)"),
    ):
        uid = state.uid("cxl")
        state.cancellations[uid] = {
            "uid": uid, "phase": phase, "cause": cause, "outcome": outcome,
            "order_no": order_no, "contract_uid": None,
            "note": kept_or_refund,
            "refund_batch_date": str(bd + timedelta(days=(4 - bd.weekday()) % 7 or 7))
            if outcome == "FULL_REFUND_WEEKLY_BATCH" else None,
            "opened_on": str(date(2026, 10, 15)),
        }


def _seed_migrated_invoices(state, bd):
    from .book import SHEET
    for customer in book_customers():
        if customer.data_source != SHEET or not customer.contracts:
            continue
        peak = (getattr(customer, "sheet", {}) or {}).get("peak")
        if peak and peak.get("invoices"):
            # Feedback Round 1 / WP1: PEAK facts exist for this customer, so nothing is
            # walked back from the sheet's cells — a real invoice beats an inferred one.
            _seed_peak_invoices(state, customer, peak, bd)
            continue
        sheet = getattr(customer, "sheet", {}) or {}
        for contract in customer.contracts:
            entity = contract.entity or ("SPV" if contract.product == "LEASE" else "EPC")
            # Invoices this contract creates, so the link-sent check below reads its own
            # work instead of rescanning every invoice in the session (O(contracts x
            # invoices) at the 350k/500-contract bench: 2.4s per fresh session).
            created = []
            if contract.product == "CASH":
                rows = sheet.get("cash_invoices") or []
                if rows:
                    for row in rows:
                        if not row.get("amount"):
                            continue
                        outstanding = Decimal(row.get("outstanding") or "0")
                        state_code = "PAID" if outstanding <= 0 else ("OVERDUE" if (row.get("due_on") or "") < str(bd) else "SENT")
                        inv = make_invoice(state, contract.uid, entity, "HANDOVER_BALANCE", row["amount"],
                                           row.get("due_on") or bd, state_code, scenario="SHEET",
                                           issued_on=row.get("issued_on") or bd)
                        inv["peak_number"] = row.get("invoice_number")
                        _sheet_peak_state(inv)
                        inv["outstanding"] = str(outstanding)
                        inv["source_ref"] = row.get("source_ref")
                    continue
                for line in contract.instalments:
                    if line.outstanding_amount > 0:
                        inv = make_invoice(state, contract.uid, entity, "HANDOVER_BALANCE", line.outstanding_amount,
                                           line.due_date, "OVERDUE" if line.due_date < bd else "SENT", scenario="SHEET",
                                           issued_on=line.due_date - timedelta(days=7))
                        _sheet_peak_state(inv)
                continue
            # LEASE (round-3 J3-02/J3-03): ONE month axis — the SHEET's cells. The LATE
            # cells are the sheet's own record of which months are unpaid, so the
            # due-and-unpaid instalment lines are paired with them in date order and each
            # invoice is stamped with its SHEET cell, never its position in the schedule.
            # The LINK_SENT cell carries the next (not yet due) invoice. "Link sent" is a
            # fact beside the state (`link_sent`), never the state itself: an invoice due
            # before the business date whose money is inside the arrears reads OVERDUE.
            link_cells = set(getattr(contract, "link_sent_cells", None) or [])
            late_cells = sorted(getattr(contract, "late_cells", None) or [])
            lines = [l for l in contract.instalments
                     if l.category == "REGULAR" and getattr(l, "schedule_status", "ACTIVE") != "SUPERSEDED"]
            sched_index = {id(l): i for i, l in enumerate(lines, start=1)}
            due_unpaid = [l for l in lines if l.due_date <= bd and l.outstanding_amount > 0]
            next_line = next((l for l in lines if l.due_date > bd), None)
            usual = getattr(contract, "pmt", None)
            fallback_cells = []
            if late_cells and not due_unpaid:
                # The sheet's status column (Closed) overrides its own month cells: nothing
                # is owed, so no OVERDUE invoice is invented on those cells.
                if getattr(contract, "derivation", None) is not None:
                    contract.derivation["late_cells_unbilled"] = (
                        "LATE cells %s carry no invoice — the sheet's status (%s) leaves nothing due and unpaid"
                        % (", ".join("M%d" % i for i in late_cells), contract.status))
            elif late_cells:
                cells = list(late_cells)
                # more due-and-unpaid lines than LATE cells: the extra lines keep their own
                # schedule month so no money is dropped.
                for extra in due_unpaid[len(cells):]:
                    cells.append(sched_index[id(extra)])
                for pos, cell in enumerate(cells):
                    line = due_unpaid[pos] if pos < len(due_unpaid) else None
                    if line is not None:
                        amount, outstanding, due_on = line.total_amount, line.outstanding_amount, line.due_date
                    elif usual is None:
                        continue           # no line and no instalment to fall back on
                    else:
                        amount = outstanding = usual
                        due_on = _cell_due_date(contract, cell)
                        fallback_cells.append(cell)
                    state_code = "PARTIALLY_PAID" if outstanding < amount else "OVERDUE"
                    inv = make_invoice(state, contract.uid, entity, "INSTALMENT", amount, due_on,
                                       state_code, scenario="SHEET", issued_on=due_on - timedelta(days=10))
                    inv["outstanding"] = str(outstanding)
                    _sheet_lease_invoice(inv, cell, cell in link_cells, contract)
                    created.append(inv)
            else:
                for line in due_unpaid:
                    idx = sched_index[id(line)]
                    state_code = "PARTIALLY_PAID" if line.outstanding_amount < line.total_amount else "OVERDUE"
                    inv = make_invoice(state, contract.uid, entity, "INSTALMENT", line.total_amount, line.due_date,
                                       state_code, scenario="SHEET", issued_on=line.due_date - timedelta(days=10))
                    inv["outstanding"] = str(line.outstanding_amount)
                    _sheet_lease_invoice(inv, idx, idx in link_cells, contract)
                    created.append(inv)
            if next_line is not None:
                # the not-yet-due instalment sits on the LINK_SENT cell when the sheet has
                # one, else on the cell after the last LATE cell.
                nxt = max(link_cells) if link_cells else (
                    (late_cells[-1] + 1) if late_cells else sched_index[id(next_line)])
                inv = make_invoice(state, contract.uid, entity, "INSTALMENT", next_line.total_amount,
                                   next_line.due_date, "SENT" if nxt in link_cells else "ISSUED",
                                   scenario="SHEET", issued_on=bd)
                inv["outstanding"] = str(next_line.total_amount)
                _sheet_lease_invoice(inv, nxt, nxt in link_cells, contract)
                created.append(inv)
            if fallback_cells and getattr(contract, "derivation", None) is not None:
                contract.derivation["invoice_amount_fallback"] = (
                    "LATE cells %s have no instalment line left in the schedule — amount taken from the contract's usual instalment %s"
                    % (", ".join("M%d" % i for i in fallback_cells), usual))
            carried = {i.get("month_index") for i in created if i.get("link_sent")}
            gap = sorted(link_cells - carried)
            if gap and getattr(contract, "derivation", None) is not None:
                # e.g. ปัทมวรรณ (2): the LINK_SENT cell is on a month the sheet's Current status counts as paid.
                contract.derivation["link_sent_gap"] = ("LINK_SENT cell %s falls on an instalment the sheet status counts as paid — no invoice carries that link"
                                                        % ", ".join("M%d" % i for i in gap))
    # Final fix F-R2: stamp the book's PEAK report date onto this session, right after
    # seeding from it — see JourneyState.peak_as_of and weekly_figures.peak_session_gap.
    state.peak_as_of = _book_peak_report_as_of()


def _book_peak_report_as_of():
    """The same date `weekly_figures.peak_report_as_of()` computes (the applied PEAK
    report's date, from the book, right now) — read directly here instead of imported,
    since weekly_figures imports journey and a module-level import back would cycle.
    Duplicated on purpose: five lines, one seam (customer.sheet["peak"]["report_as_of"]),
    kept identical to its twin so a session's `peak_as_of` and the book's own reading of
    itself can never silently drift apart."""
    dates = []
    for customer in book_customers():
        peak = (getattr(customer, "sheet", None) or {}).get("peak") or {}
        if peak.get("report_as_of"):
            dates.append(str(peak["report_as_of"]))
    return max(dates) if dates else None


def _cell_due_date(contract, cell):
    """Round-3 J3-02: the due date of a SHEET month cell with no instalment line left —
    the contract's first due date walked forward (cell - 1) months, same day."""
    first = contract.first_due
    total = (first.month - 1) + (cell - 1)
    year, month = first.year + total // 12, total % 12 + 1
    day = first.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


PEAK_STATE = {"PAID": "PAID", "OVERDUE": "OVERDUE", "AWAITING": "SENT"}
# Every receipt a reseed mints from the book: the invoice report's own paid columns and
# the receipt run's money. Both are cleared and minted again on each reseed (fix-all P1).
PEAK_SOURCES = ("PEAK_REPORT", RECEIPT_SOURCE)


def _peak_contract_for(customer, inv):
    """One contract → it. Several → the product group decides (Cash → CASH, Solar
    Leasing → LEASE); otherwise the first, marked unresolved rather than guessed silently."""
    contracts = list(customer.contracts)
    if len(contracts) == 1:
        return contracts[0], True
    group = (inv.get("product_group") or "").lower()
    want = "CASH" if "cash" in group else ("LEASE" if "leas" in group else None)
    for k in contracts:
        if want and k.product == want:
            return k, True
    return contracts[0], False


def _stable_uid(mapping, prefix, key):
    """Fix round 1 / finding I1: a PEAK-sourced record's id must survive a reseed of
    unchanged content, or a person's own receipt pointing at a PEAK invoice is orphaned
    the moment the invoice is re-minted under a new uid. `prefix + key` is that stable
    id; if it is already taken -- two PEAK rows deriving the same id, e.g. one receipt
    settling two invoices and so sharing a receipt_no -- the first keeps it and the
    rest are suffixed -2, -3, ... rather than colliding or overwriting."""
    uid = prefix + key
    n = 2
    while uid in mapping:
        uid = "%s-%d" % (prefix + key, n)
        n += 1
    return uid


def _restable(mapping, record, uid):
    """Re-key an already-minted record onto its stable uid: drop the minted entry,
    stamp the new uid onto the record itself, store it under the stable key."""
    del mapping[record["uid"]]
    record["uid"] = uid
    mapping[uid] = record


def _seed_peak_invoices(state, customer, peak, bd):
    note_th = "จากรายงานใบแจ้งหนี้ PEAK ณ %s" % (peak.get("report_as_of") or "—")
    note_en = "From the PEAK invoice report as of %s" % (peak.get("report_as_of") or "—")
    for row in peak["invoices"]:
        # feedback round 2 / Q6 (TASK-204): a receipt whose invoice is not in the
        # applied report is money without an invoice row. The case shows the receipt,
        # never a phantom invoice with no cycle.
        if row.get("receipt_only"):
            pay = row.get("payment")
            if pay and pay.get("amount") and pay.get("on"):
                contract, _resolved = _peak_contract_for(customer, row)
                entity = contract.entity or ("SPV" if contract.product == "LEASE" else "EPC")
                rcp = make_receipt(state, contract.uid, entity, pay["amount"], pay["on"],
                                   invoice_uid=None, matched="MATCHED")
                rcp["source"] = RECEIPT_SOURCE
                rcp["ref"] = pay.get("receipt_no")
                rcp["channel"] = pay.get("channel")
                _restable(state.receipts, rcp,
                          _stable_uid(state.receipts, "rcp-pk-", pay.get("receipt_no") or row["doc_no"]))
            continue
        if row["status"] in ("DRAFT", "CANCELLED"):
            continue                                   # not an issued invoice
        contract, resolved = _peak_contract_for(customer, row)
        entity = contract.entity or ("SPV" if contract.product == "LEASE" else "EPC")
        due_on = _date_or(row.get("due_on"), bd)
        state_code = PEAK_STATE[row["status"]]
        if row["status"] == "AWAITING" and due_on < bd:
            state_code = "OVERDUE"
        amount = row.get("amount_due") or row.get("amount_total") or "0"
        inv = make_invoice(state, contract.uid, entity,
                           "INSTALMENT" if contract.product == "LEASE" else "HANDOVER_BALANCE",
                           amount, due_on, state_code, scenario="PEAK",
                           issued_on=_date_or(row.get("issued_on"), due_on))
        inv["source"] = "PEAK_REPORT"
        inv["peak_number"] = row["doc_no"]
        inv["peak_state"] = "APPROVED_IN_PEAK"
        inv["peak_state_note_th"] = note_th
        inv["peak_state_note_en"] = note_en
        inv["outstanding"] = str(Decimal(row.get("amount_awaiting") or "0").quantize(Decimal("0.01")))
        inv["month_index"] = (row.get("cycle") or {}).get("n")
        inv["contract_resolved"] = resolved
        inv["link_sent"] = None                      # PEAK does not say; nothing is invented
        # stable id (fix round 1, I1): the SAME PEAK invoice reseeds onto the SAME uid.
        _restable(state.invoices, inv, _stable_uid(state.invoices, "inv-pk-", row["doc_no"]))
        # Fix-all P2: one receipt per payment the book serves (a part-paid invoice can
        # carry several); a block written before `payments` existed carries `payment`.
        for pay in (row["payments"] if "payments" in row else [row.get("payment")]):
            if not (pay and pay.get("amount") and pay.get("on")):
                continue
            rcp = make_receipt(state, contract.uid, entity, pay["amount"], pay["on"],
                               invoice_uid=inv["uid"], matched="MATCHED")
            # Q6/TASK-204: money the receipt run settled says so; an invoice report's
            # own paid columns stay PEAK_REPORT — per payment where the overlay names it.
            rcp["source"] = pay.get("source") or row.get("payment_source") or "PEAK_REPORT"
            rcp["ref"] = pay.get("receipt_no")
            rcp["channel"] = pay.get("channel")
            if settings.peak_report_allocates:      # design F3
                rcp["is_allocated"], rcp["exception_raised"], rcp["pending_decision"] = True, False, None
            _restable(state.receipts, rcp,
                     _stable_uid(state.receipts, "rcp-pk-", pay.get("receipt_no") or row["doc_no"]))


def _date_or(raw, fallback):
    if not raw:
        return fallback
    y, m, d = (int(p) for p in str(raw)[:10].split("-"))
    return date(y, m, d)


def reseed_peak(state, bd):
    """After a PEAK report is applied in THIS session: drop every PEAK-sourced invoice
    and receipt and seed again from the book as it is now served. Everything a
    person recorded (slips, contacts, PTPs) is untouched.

    Fix round 1 / finding I1: a person's own receipt can name a PEAK invoice's uid
    (`invoice_uid`). PEAK invoices now reseed onto a stable id (`_stable_uid`), so an
    unchanged report recreates the same uid and that receipt stays valid without any
    help here. But if the report's content changed enough that the invoice is gone --
    or never comes back -- the receipt is NEVER deleted for that: it is kept and
    flagged so a screen can surface it, not silently orphaned. The flag is
    re-evaluated every reseed in both directions, since the same stable-id scheme
    that can make an invoice disappear can also bring it back on a later report.

    Task 25c: the same stable-id scheme can also hand `inv-pk-<doc_no>` to a
    DIFFERENT customer -- a link a Manager confirms moves which customer's PEAK
    block carries that doc_no. A receipt is never re-pointed or deleted for that
    either: `invoice_moved_to_other_customer` is set when the receipt's own
    customer (by its `contract_uid`) differs from the invoice's now-owning
    customer, and cleared when the invoice is back with its own customer -- also
    re-evaluated every reseed, in both directions.

    Fix round 1, minor: `invoice_owner_unknown` is set instead of
    `invoice_moved_to_other_customer` when EITHER side's customer cannot be
    resolved at all (an orphaned `contract_uid`) -- `None == None` must never read
    as "same customer". Also re-evaluated every reseed, in both directions."""
    for uid in [u for u, i in state.invoices.items() if i.get("source") == "PEAK_REPORT"]:
        del state.invoices[uid]
    for uid in [u for u, r in state.receipts.items() if r.get("source") in PEAK_SOURCES]:
        del state.receipts[uid]
    from .book import SHEET
    for customer in book_customers():
        # Final review (minor): the same guard _seed_migrated_invoices has — only a
        # SHEET-sourced customer is ever seeded from PEAK, at reset or at reseed.
        if customer.data_source != SHEET or not customer.contracts:
            continue
        peak = (getattr(customer, "sheet", {}) or {}).get("peak")
        if peak and peak.get("invoices"):
            _seed_peak_invoices(state, customer, peak, bd)
    for rcp in state.receipts.values():
        if rcp.get("source") in PEAK_SOURCES or not rcp.get("invoice_uid"):
            continue
        invoice = state.invoices.get(rcp["invoice_uid"])
        rcp["invoice_missing_after_reseed"] = invoice is None
        if invoice is None:
            rcp["invoice_moved_to_other_customer"] = False
            rcp["invoice_owner_unknown"] = False
            continue
        rcp_customer = _customer_uid_for_contract(rcp["contract_uid"])
        inv_customer = _customer_uid_for_contract(invoice["contract_uid"])
        rcp["invoice_owner_unknown"] = rcp_customer is None or inv_customer is None
        rcp["invoice_moved_to_other_customer"] = bool(not rcp["invoice_owner_unknown"] and rcp_customer != inv_customer)
    # Final fix F-R2: this session just reseeded from the book, so it is caught up —
    # same stamp _seed_migrated_invoices makes at the initial seed.
    state.peak_as_of = _book_peak_report_as_of()


def _on_or_before(value, bd):
    raw = str(value or "")[:10]
    try:
        return date.fromisoformat(raw) <= bd
    except ValueError:
        return False


def _person_receipt_on(state, invoice_uid):
    """A receipt a person recorded against this invoice. PEAK receipts are reseeded
    from the report; a slip is work, and a refresh must not overwrite the money it
    settled."""
    return any(r.get("invoice_uid") == invoice_uid and r.get("source") not in PEAK_SOURCES
               for r in state.receipts.values())


def reseed_migrated_invoices(state, bd):
    """Refresh the SHEET-sourced invoices in place after a re-import.

    Before this, only PEAK invoices ever reseeded: a corrected sheet or a new pull
    left every seeded amount, due date and status frozen at first touch (sync audit,
    2026-09-20). The refresh is deliberately in place, matched by what the seed
    already writes — `month_index` for a lease instalment, scheduled order for a
    cash handover — so every uid survives and a person's receipt on it stays valid.
    A month that no longer owes money is FLAGGED (`sheet_no_longer_due`), never
    deleted: the invoice may carry a slip.

    Returns {"updated", "added", "flagged"}.
    """
    from .book import SHEET
    updated = added = flagged = 0
    for customer in book_customers():
        if customer.data_source != SHEET or not customer.contracts:
            continue
        sheet = getattr(customer, "sheet", {}) or {}
        peak = sheet.get("peak")
        if peak and peak.get("invoices"):
            continue                         # reseed_peak owns every row of this customer
        for contract in customer.contracts:
            entity = contract.entity or ("SPV" if contract.product == "LEASE" else "EPC")
            lines = [l for l in contract.instalments
                     if getattr(l, "schedule_status", "ACTIVE") != "SUPERSEDED"]
            due = [l for l in lines if l.due_date <= bd and l.outstanding_amount > 0]
            mine = [(uid, inv) for uid, inv in state.invoices.items()
                    if inv.get("contract_uid") == contract.uid and inv.get("source") != "PEAK_REPORT"]
            if contract.product == "CASH":
                mine = [(uid, inv) for uid, inv in mine if inv.get("kind") == "HANDOVER_BALANCE"]
                for pos, line in enumerate(due):
                    if pos < len(mine):
                        uid, inv = mine[pos]
                        if _person_receipt_on(state, uid):
                            continue
                        if (str(inv.get("amount")) != str(line.total_amount)
                                or str(inv.get("outstanding")) != str(line.outstanding_amount)):
                            inv["amount"] = str(line.total_amount)
                            inv["outstanding"] = str(line.outstanding_amount)
                            inv["due_on"] = line.due_date
                            updated += 1
                    else:
                        inv = make_invoice(state, contract.uid, entity, "HANDOVER_BALANCE",
                                           line.total_amount, line.due_date,
                                           "OVERDUE" if line.due_date < bd else "SENT",
                                           scenario="SHEET", issued_on=line.due_date - timedelta(days=7))
                        inv["outstanding"] = str(line.outstanding_amount)
                        added += 1
                for uid, inv in mine[len(due):]:
                    if _on_or_before(inv.get("due_on"), bd) and not inv.get("sheet_no_longer_due"):
                        inv["sheet_no_longer_due"] = True
                        flagged += 1
                continue
            # LEASE: the month cell is the axis; the same source the seed used.
            link_cells = set(getattr(contract, "link_sent_cells", None) or [])
            sched = {i: l for i, l in enumerate(lines, start=1)}
            by_month = {inv.get("month_index"): (uid, inv) for uid, inv in mine if inv.get("month_index")}
            for idx, line in sched.items():
                hit = by_month.get(idx)
                past = line.due_date <= bd
                owing = past and line.outstanding_amount > 0
                if hit is None:
                    if not owing:
                        continue
                    inv = make_invoice(state, contract.uid, entity, "INSTALMENT", line.total_amount,
                                       line.due_date,
                                       "PARTIALLY_PAID" if line.outstanding_amount < line.total_amount else "OVERDUE",
                                       scenario="SHEET", issued_on=line.due_date - timedelta(days=10))
                    inv["outstanding"] = str(line.outstanding_amount)
                    _sheet_lease_invoice(inv, idx, idx in link_cells, contract)
                    added += 1
                    continue
                uid, inv = hit
                if not past:
                    # a future instalment is not "no longer due"; leave it alone
                    inv.pop("sheet_no_longer_due", None)
                    continue
                if not owing:
                    if not inv.get("sheet_no_longer_due"):
                        inv["sheet_no_longer_due"] = True
                        flagged += 1
                    continue
                inv.pop("sheet_no_longer_due", None)
                if _person_receipt_on(state, uid):
                    continue
                state_code = "PARTIALLY_PAID" if line.outstanding_amount < line.total_amount else "OVERDUE"
                if (str(inv.get("amount")) != str(line.total_amount)
                        or str(inv.get("outstanding")) != str(line.outstanding_amount)
                        or inv.get("state") != state_code):
                    inv["amount"] = str(line.total_amount)
                    inv["outstanding"] = str(line.outstanding_amount)
                    inv["due_on"] = line.due_date
                    inv["state"] = state_code
                    updated += 1
    return {"updated": updated, "added": added, "flagged": flagged}


def _sheet_peak_state(inv):
    """Round-2 nantapol N2-15: "อนุมัติใน PEAK" beside "ไม่มีเลข PEAK" on every row. An
    invoice the sheet recorded is APPROVED_IN_PEAK only when the sheet gave its number."""
    if inv.get("peak_number"):
        inv["peak_state"] = "APPROVED_IN_PEAK"
        inv["peak_state_note_th"] = "อนุมัติใน PEAK แล้ว (เลขจากชีต)"
        inv["peak_state_note_en"] = "Approved in PEAK (number from the sheet)"
    else:
        inv["peak_state"] = "SHEET_RECORDED"
        inv["peak_state_note_th"] = "ตามชีต ยังไม่มีเลข PEAK"
        inv["peak_state_note_en"] = "Per the sheet, no PEAK number yet"


def _sheet_lease_invoice(inv, month_index, link_sent, contract):
    inv["month_index"] = month_index          # aligns with month_grid[index] (N2-04)
    inv["contract_uid"] = contract.uid
    inv["peak_number"] = None
    _sheet_peak_state(inv)
    inv["link_sent"] = bool(link_sent)
    # The sheet's cell says the link went out; it does not say when. No date is invented.
    inv["link_sent_on"] = None
    inv["link_sent_source"] = "SHEET_CELL" if link_sent else None
    inv["link_sent_note_th"] = ("ชีตบันทึกว่าส่งลิงก์แล้ว (ช่อง M%d) ไม่ระบุวันที่" % month_index) if link_sent \
        else "ชีตไม่ได้บันทึกว่าส่งลิงก์เดือนนี้"
    inv["link_sent_note_en"] = ("The sheet records the link as sent (cell M%d), no date given" % month_index) if link_sent \
        else "The sheet does not record a link sent this month"
