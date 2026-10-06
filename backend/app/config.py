"""Configuration — and, more importantly, the register of what is NOT yet decided.

Nothing in this file is a number someone typed because the code needed one. Every
pending value carries the decision that gates it and the owner who has to close it,
because a prototype that silently picks a side of an open question is worse than one
that refuses: the number looks settled the moment it renders.
"""
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from .session import Store


# The three ways an undecided value behaves once the engine runs. The distinction
# is NOT cosmetic: RUNNING and REFUSING are both honest, and LEAKING is not. A config
# slot that is None while a number still reaches the screen from a literal elsewhere
# is strictly worse than a refusal, because it looks settled to whoever reads it.
RUNNING = "RUNNING"    # a declared default is live and producing figures
REFUSING = "REFUSING"  # the engine stops; nothing is written
LEAKING = "LEAKING"    # the slot is empty and a figure renders anyway, from elsewhere


@dataclass(frozen=True)
class PendingRule:
    key: str
    decision: str
    owner: str
    note: str
    state: str
    # What actually reaches a screen today, and from where. Free text on purpose:
    # it cites a file and line, because the point is that somebody can go and look.
    surfaces_as: str


@dataclass(frozen=True)
class DecidedRule:
    """A decision that HAS been taken and whose value stays tunable by the Owner.

    PendingRule says "nobody has chosen". This says "Arina chose, here is when and on
    what". The distinction matters on screen: an officer told a settled thing is still
    open cannot trust either state.
    """

    key: str
    decision: str        # the code this closes, e.g. "CF1"
    decided_by: str
    decided_on: date
    ruling: int          # the entry in docs/design/round-6/00-ledger.md
    basis: str           # what the decision was taken on — cite something checkable
    editable_by: str = "OWNER"


DECIDED = {
    "late_payment_daily_rate": DecidedRule(
        key="late_payment_daily_rate",
        decision="CF1",
        decided_by="Arina",
        decided_on=date(2026, 9, 9),
        ruling=87,
        basis="Arina 2026-09-09, reaffirmed on challenge. Evidence read 0.3 %/day "
              "(agreement VL0010399 §13.1; three late-fee lines on IVT-20260700089); "
              "0.03 %/day = 10.95 %/yr, inside §13.2's 15 %/yr ceiling and close to the "
              "10 %/yr Volt's own lawyer claimed in Notice.pdf.",
    ),
    "late_payment_grace_days": DecidedRule(
        key="late_payment_grace_days",
        decision="OD-31",
        decided_by="Arina",
        decided_on=date(2026, 9, 9),
        ruling=88,
        basis="IVT-20260700089 — three instalments with three different due dates, all "
              "billed to one as-of date 2026-07-15, matching 0.3 %/day with zero days "
              "deducted. Penalty runs from the due date.",
    ),
}


PENDING = {
    "allocation_component_order": PendingRule(
        key="allocation_component_order",
        decision="OD-02",
        owner="Accounting with Legal",
        note=(
            "Oldest-instalment-first is settled; the component order within an "
            "instalment is not. The engine refuses rather than guessing."
        ),
        state=REFUSING,
        surfaces_as=(
            "422 allocation_rule_pending. Nothing is written."
        ),
    ),
    "early_settlement_method": PendingRule(
        key="early_settlement_method",
        decision="OD-03",
        owner="Owner with Accounting and Legal",
        note="Until this is set, full payoff is the fallback sum, not a settlement quote.",
        state=LEAKING,
        surfaces_as=(
            "A fallback sum, drawn to the officer as a payoff figure. "
            "money/arrears.py:130"
        ),
    ),
    "npl_dpd_threshold_days": PendingRule(
        key="npl_dpd_threshold_days",
        decision="OD-04",  # distinct from OD-03; the two were conflated once
        owner="Whan",
        note=(
            "NPL is never automatic — the system raises the review at DPD 30+, a human "
            "flags. Deck v20.0 declares NPL at 90 days on the lease ladder; that figure "
            "is recorded as the INDICATIVE rung's source, not as this threshold."
        ),
        state=LEAKING,
        surfaces_as=(
            "Two surfaces: 30, from a bare literal in the band table (money/dpd.py:19); "
            "and 90, deck v20.0, as the indicative NPL rung in app/ladder.py — "
            "indicative only, a human flags."
        ),
    ),
    "discount_rate_version": PendingRule(
        key="discount_rate_version",
        decision="OQ-31",
        owner="Accounting",
        note=(
            "15.00 % effective annual (1.17149 %/month) was hard-coded in every NPV in "
            "the live book and appeared in no spec, requirement or config. The rebuild "
            "moves it to a DECLARED default (discount_rate_effective_annual) used by the "
            "remaining-NPV figures on deeds and project-sale invoices. Declared is not "
            "decided: the decision stays open."
        ),
        state=RUNNING,
        surfaces_as=(
            "15.00 % effective annual, declared in config.py "
            "(discount_rate_effective_annual) and flagged on every NPV it produces."
        ),
    ),
    "service_month37_decline_allowed": PendingRule(
        key="service_month37_decline_allowed",
        decision="SVC-37",
        owner="Jo",
        note=(
            "Jo says the month-37 service contract is not mandatory to sign; Win says "
            "the customer must pay the THB 399+. The deck bills 399 from month 37 "
            "either way — what is open is whether the customer may decline. It matters "
            "on a LEASE, where the asset is still SPV's until month 60."
        ),
        state=RUNNING,
        surfaces_as=(
            "Billing runs either way (R1, grilling 2026-08-30). A decline request is "
            "recorded with 202 and changes nothing; the open flag renders wherever "
            "service billing appears."
        ),
    ),
}


@dataclass
class Settings:
    # --- settled -------------------------------------------------------------
    annual_interest_rate_financing: Decimal = Decimal("7.9")  # percent per year, flat
    day_count_basis: str = "CALENDAR"
    business_timezone: str = "Asia/Bangkok"
    band_set_code: str = "COLLECTION_STATUS_V1"
    daily_contact_limit_per_customer: int = 1
    # REQ-COL-055 — the slot is spent at amount-stated or 90 s, whichever is first.
    retraction_window_seconds: int = 90

    # --- decided, and still Owner-tunable (see DECIDED above) ----------------
    # Ruling 87 (CF1), Arina 2026-09-09. Evidence said 0.3 %/day; she ruled 0.03 %/day
    # = 10.95 %/yr, which is what Volt's lawyer actually claims. NOTE: PEAK still bills
    # 0.3 %/day, so our figures are 10x lower until AR moves PEAK's setting.
    late_payment_daily_rate: Decimal = Decimal("0.0003")
    # Ruling 88 (OD-31), Arina 2026-09-09. Penalty runs from the due date, no grace.
    late_payment_grace_days: int = 0

    # Feedback Round 1 / WP4, design F7: per file and per note. Chosen, not ruled.
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachments_per_note: int = 5

    # Feedback Round 1 / WP1, design F3: a PEAK receipt naming its invoice is PEAK's own
    # allocation. True records it as allocated (PEAK-sourced receipts only); False
    # leaves it under OD-02 like a slip. The engine's instalment lines are NOT
    # re-allocated by this switch — that is allocation-engine work, priced separately.
    peak_report_allocates: bool = True

    # Feedback Round 1, design F2: for a customer linked to PEAK, the system's own
    # payment status is worked out from the PEAK invoices. This partly supersedes
    # Requirements Amendment v2.6 §3.6 a second time (the first was 2026-09-14's
    # person-may-change rule); recorded here, at cases._payment_status, and in the
    # commit that introduced it.
    peak_report_drives_status: bool = True

    # Delta-100 D2a (2026-09-18): the record's risk score. The prototype drew a
    # 0–100 score from sample data; this computes one from signals the system
    # already holds. The four weights are settings, not decisions — tunable.
    risk_weight_dpd: int = 40
    risk_weight_arrears: int = 30
    risk_weight_broken_ptp: int = 15
    risk_weight_recency: int = 15

    # Delta-100 D2e (2026-09-18): the KPI bars' targets. The receipts target already
    # has a store — a manager saves it per calendar month on the collection targets
    # route (reports.TARGETS, key "cash_received:portfolio") — and is served as
    # `team.target_month`. The other three have no store yet, so they are Settings
    # fields with None defaults. None means "nobody set a target", never a guess; a
    # screen must print the no-target note rather than a zero. `receipts_monthly_target`
    # is the fallback actually used only when no monthly target is saved for the month.
    ptp_kept_target_pct: Optional[Decimal] = None
    contact_target_pct: Optional[Decimal] = None
    dso_target_days: Optional[int] = None
    receipts_monthly_target: Optional[Decimal] = None
    # The shell rail's workload bar compares the work-book caseload with a cap. None
    # means no cap has been set, so the percentage served with it is None as well.
    caseload_cap: Optional[int] = None

    # Plan 2026-09-11 §1.3, carried into Feedback Round 1: a chosen default, not a
    # ruled one. payment_position.build() marks its block stale past this many days.
    payment_position_stale_days: int = 30

    # --- pending, with a shipped default that is NOT a decision ---------------
    # None means "refuse", not "use a sensible default". See allocation.py.
    allocation_component_order: Optional[tuple] = None
    early_settlement_method: Optional[str] = None
    npl_dpd_threshold_days: Optional[int] = None
    # SVC-37 (Jo). The string IS the shipped behaviour, not a decision.
    service_month37_decline_allowed: str = "UNDECIDED_BILLED_EITHER_WAY"
    # OQ-31 (Accounting). Declared, flagged, still open.
    discount_rate_effective_annual: Decimal = Decimal("15.00")

    # --- deck v20.0 commercial constants (config, not code) -------------------
    service_monthly_floor_thb: Decimal = Decimal("399.00")
    service_billing_window: tuple = (25, 30)  # day-of-month, inclusive
    service_prepaid_months: int = 36
    acquisition_pct_of_npv: Decimal = Decimal("100")  # was 85, changed 25 Aug
    # Ruling 89, Arina 2026-09-09: 5, not 3. The signed agreement §16.1 and the
    # lawyer's demand in Notice.pdf both say 5 THB/watt (6.3 kWp -> THB 31,500).
    uninstall_fee_thb_per_watt: Decimal = Decimal("5")
    cash_deposit_floor_thb: Decimal = Decimal("5000")
    accounting_fee_thb: Decimal = Decimal("50000")  # manual, outside the ERP
    # R6 — the default ladder mode; a session may switch to MANUAL.
    ladder_mode_default: str = "ASSISTED"

    # --- Requirements Amendment v2.6 §4 (2026-09-02) --------------------------
    # C3 — LOCKED. Debt creates PEAK drafts and reads state; it never approves.
    peak_write_mode: str = "DRAFT_ONLY"
    # OPEN (Owner). COLLECTION while open — the team does it today.
    invoice_owner_role: str = "COLLECTION"
    pipeline_lookahead_days: int = 3
    # OD-04 extended — OPEN (Owner, Whan). The accounting flag stays automatic.
    npl_review_dpd: int = 60
    npl_review_missed_no_contact: int = 2
    # REQ-MOD-040 — OWNER while the Debt Manager post is vacant (OQ-44).
    power_restriction_approver: str = "OWNER"
    power_restriction_min_missed: int = 2
    power_restriction_require_broken_ptp: bool = True
    review_sla_hours: int = 24
    # Round-2 nantapol N2-13: the reminder batch offsets (days before the due date). The
    # SOP handed to the officer says D-1/D0, the interview said D-3/D0 — a Manager sets it.
    reminder_offsets_days: tuple = (3, 0)

    # --- feature flags -------------------------------------------------------
    # Ruling 87 (Arina, 2026-09-09): CF1 is decided, so this goes live. The rate is
    # Owner-tunable and every PenaltyRow snapshots the rate it used, so a later change
    # never restates history. C3 still holds: what reaches PEAK is a DRAFT.
    # ACCEPTED RISK, on the record: PEAK bills 0.3 %/day today and we now compute
    # 0.03 %/day, so our drafts read one tenth of the customer's own tax invoice until
    # AR moves PEAK's setting.
    penalty_invoicing_enabled: bool = True
    # Power restriction went LIVE (approver Owner, Legal consulted). It shipped with
    # the flag false and the permission granted to nobody; that is now wrong.
    power_restriction_enabled: bool = True

    # --- the vacant post -----------------------------------------------------
    # REQ-IAM-015. There is no Debt Manager in post. The Owner absorbs every route as
    # one time-boxed reassignment with a review date.
    vacant_roles: tuple = ("DEBT_MANAGER",)

    business_date: date = date(2026, 10, 23)

    def is_pending(self, key: str) -> bool:
        """A shipped default does not close a decision. `service_month37_decline_allowed`
        has a value AND is pending — that is the whole point of the register."""
        return key in PENDING

    def pending_rule(self, key: str) -> Optional[PendingRule]:
        return PENDING.get(key)


# Round-3, R3-F04 / ruling 32 (Arina, 2026-09-04): `settings` was a process-wide
# singleton while its six sibling mutable domains (cases.py:87, journey.py:89,
# dictionaries.py:209, invoice_pipeline.py:49, peak_documents.py:76, reports.py:17,
# criteria.py:49) already use `session.Store.for_current()` — so one session's
# `PUT /v1/config` mutated every session's state (206/212 WorkBook rows re-bucketed
# for a session that took no action; measured live, cluster-2 round-3 leg F, R3-F15).
# All 31 fields above are scalar / Decimal / date / tuple — no mutable default, no
# `default_factory` — so a fresh `Settings()` per session is safe with the plain
# constructor the sibling domains use.
#
# `_SettingsProxy` keeps every one of the 226 `settings.<attr>` read sites (26
# modules, counted) and the single `setattr(settings, key, new)` write site
# (`routers/settings.py:153`) working unchanged: they still see a module-level name
# called `settings` and do plain attribute access on it: the indirection through
# `_store.for_current()` is invisible to every caller.
_store = Store(Settings, key="config.settings")

# Feedback Round 1 / WP10 (B8): who last changed each key and when — {key: {"by",
# "role", "at"}} — kept in the same per-session Store family as the values it
# describes, so it persists exactly as they do (app.session_state when a database is
# configured, memory when not) and a deploy discards both together. A second Store,
# not a Settings field: a Settings pickle written before the field existed would
# restore without it (session_store_db keeps "dev" pickles across code changes).
_changed_store = Store(dict, key="config.changed")


def for_current() -> Settings:
    return _store.for_current()


def changed_for_current() -> dict:
    return _changed_store.for_current()


def reset():
    _store.reset()
    _changed_store.reset()


# The business date (Arina, 2026-09-24): the demo world keeps 2026-10-23, real data
# runs on today in Bangkok. Resolved on READ, never stored: every session saved before
# this carries the old default in its Settings pickle, so a stored date would pin it.
DEMO_BUSINESS_DATE = date(2026, 10, 23)
_BANGKOK = timezone(timedelta(hours=7))   # Asia/Bangkok has no DST
_today_cache = {"at": -60.0, "value": None}


def business_date_is_live():
    """True when the date follows the real calendar: a database is configured and no
    VOLT_BUSINESS_DATE pin is set (tests, e2e and the in-memory demo pin or fall back)."""
    if os.environ.get("VOLT_BUSINESS_DATE"):
        return False
    from . import db
    return db.configured()


def resolve_business_date():
    """VOLT_BUSINESS_DATE > today in Bangkok when a database is configured > the demo
    date. Today is re-read at most every 5 s: this sits under every money loop."""
    pinned = os.environ.get("VOLT_BUSINESS_DATE")
    if pinned:
        return date.fromisoformat(pinned)
    if not business_date_is_live():
        return DEMO_BUSINESS_DATE
    now = time.monotonic()
    if now - _today_cache["at"] > 5.0:
        _today_cache.update(at=now, value=datetime.now(_BANGKOK).date())
    return _today_cache["value"]


class _SettingsProxy:
    def __getattr__(self, name):
        current = _store.for_current()
        from .runtime_policy import shared_state_enabled
        if shared_state_enabled():
            if name == "business_date": return resolve_business_date()
            if name == "penalty_invoicing_enabled": return False
        if name == "business_date":
            # An explicit set (tests only — no route edits it) wins; old pickles never
            # carry `business_date_set`, so their stale default is never read.
            return getattr(current, "business_date_set", None) or resolve_business_date()
        return getattr(current, name)

    def __setattr__(self, name, value):
        current = _store.for_current()
        if name == "business_date":
            # Setting it back to the resolved date (or None) clears the explicit set, so
            # a test's `settings.business_date = saved` never leaves a pin behind.
            if value is None or value == resolve_business_date():
                current.__dict__.pop("business_date_set", None)
            else:
                current.business_date_set = value
            return
        setattr(current, name, value)


settings = _SettingsProxy()
