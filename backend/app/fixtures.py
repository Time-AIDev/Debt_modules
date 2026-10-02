"""Seed data for the prototype.

Every number here traces to a spec fixture (FX-C1..FX-C4, FX-ARR-1) or to a finding
from the live working sheet. Nothing is decorative.

THE AUDIT LESSON THIS FILE EXISTS UNDER: in the 25-08 cross-artefact audit every
defect found was in illustrative fixture data, never in a rule. The prose stated D13
correctly ten times and two screens still drew the held customer at DPD 0. A design
set is only as honest as its worst number — so the permit-held customer below is
deliberately shown at a NON-ZERO DPD, because a permit hold pauses the fee and does
NOT pause the clock.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

from .entities import entity_for
from .money.models import Instalment
from .money.schedule import build_schedule

BUSINESS_DATE = date(2026, 10, 23)

# R5 (grilling 2026-08-30): the demo book is sheet-derived with synthetic gap-fill,
# and the split is MARKED so a reviewer can tell real from invented. data_source is
# field-grouped: identity (who the customer is) versus history (what they owe and did).
SYNTHETIC = {"identity": "SYNTHETIC", "history": "SYNTHETIC"}
SHEET_IDENTITY = {"identity": "SHEET", "history": "SYNTHETIC"}


@dataclass
class ContractFixture:
    uid: str
    customer_uid: str
    product: str
    principal: Decimal
    term_months: int
    first_due: date
    status: str = "PAST_DUE"
    fee_state: Optional[str] = None
    fee_state_from: Optional[date] = None
    paid_through: int = 0  # how many instalments are fully paid
    part_payment: Decimal = Decimal("0.00")
    instalments: List[Instalment] = field(default_factory=list)
    # Deck v20.0 — every receivable routes on its entity: CASH→EPC, LEASE→SPV.
    entity: Optional[str] = None
    # S09 — the month counter runs from system acceptance, not from signing.
    acceptance_date: Optional[date] = None
    # A CASH contract with an instalment schedule predates the deck's one-format
    # rule (Cash 2/3 retired, Win 26 Aug). Kept as engine proof cases, FLAGGED —
    # a multi-line cash contract that is not flagged is a fixture defect.
    legacy_pre_v20: bool = False

    def __post_init__(self):
        if self.entity is None:
            try:
                self.entity = entity_for(self.product)
            except ValueError:
                self.entity = None  # unknown products stay unrouted, visibly

    def build(self):
        schedule = build_schedule(self.principal, Decimal("7.9"), self.term_months)
        per_principal = (self.principal / Decimal(self.term_months)).quantize(Decimal("0.01"))
        per_interest = (schedule.total_interest / Decimal(self.term_months)).quantize(Decimal("0.01"))

        lines = []
        for n in range(self.term_months):
            due = _add_months(self.first_due, n)
            is_final = n == self.term_months - 1
            paid_p = per_principal if n < self.paid_through else Decimal("0.00")
            paid_i = per_interest if n < self.paid_through else Decimal("0.00")
            if n == self.paid_through and self.part_payment > 0:
                # A part payment lands on principal first only because that is the
                # SHIPPED default order — it is not a decision (OD-02).
                paid_p = min(self.part_payment, per_principal)
                paid_i = max(self.part_payment - per_principal, Decimal("0.00"))
            line_principal, line_interest = per_principal, per_interest
            if is_final:
                # REQ-MNY-003: the FINAL line is the balancing figure, so the schedule
                # sums to total_amount exactly with no residue. Repeating the regular
                # instalment here leaves 0.12 on FX-C2 — a fixture quietly contradicting
                # the requirement it exists to illustrate.
                drawn_principal = per_principal * Decimal(self.term_months - 1)
                line_principal = self.principal - drawn_principal
                # The final TOTAL must equal the schedule builder's own balancing
                # figure for ANY principal — per-component remainders drift from it
                # by a satang when the term does not divide cleanly, and the
                # fixture-honesty tests compare against the builder.
                line_interest = schedule.final_installment_amount - line_principal
                if paid_p > Decimal("0.00"):
                    paid_p, paid_i = line_principal, line_interest

            lines.append(
                Instalment(
                    due_date=due,
                    category="REGULAR",
                    principal_amount=line_principal,
                    interest_amount=line_interest,
                    fee_amount=Decimal("0.00"),
                    paid_principal=paid_p,
                    paid_interest=paid_i,
                )
            )
        self.instalments = lines
        return self


def _add_months(start: date, months: int) -> date:
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))   # 31 Jan + 1 = 28/29 Feb


@dataclass
class CustomerFixture:
    uid: str
    customer_no: str
    display_name: str
    phone_masked: str
    priority: int
    reason_code: str
    officer: str
    recovery_stage: str
    contracts: List[ContractFixture] = field(default_factory=list)
    # There is NO customer identity key in any live Volt data — the join key is a
    # composite Volt ID and no citizen or juristic id exists anywhere upstream. The
    # Act's one-contact-per-day rule is unenforceable on real data until Odoo supplies
    # one. This field stands in for it and must not be mistaken for the real thing.
    identity_key: str = ""
    # R5 — field-grouped provenance, rendered as a marker chip. See SHEET_IDENTITY.
    data_source: dict = field(default_factory=lambda: dict(SYNTHETIC))
    # The fixture-authored bridge to a real sheet row (R5). No join key exists in
    # live data; this is authorship, and the wire says so.
    order_ref: Optional[dict] = None
    scenario_codes: tuple = ()
    # R12 — link-only fields for โทร/LINE. The DISPLAYED number stays masked.
    # Synthetic customers carry a deliberately INVALID number (safe to tap, dials
    # nobody); sheet-derived customers carry None because the import masked the
    # real number and inventing one could dial a stranger. Odoo sync fills real
    # values for ODOO-sourced rows only.
    phone_e164: Optional[str] = None
    line_id: Optional[str] = None
    meta_id: Optional[str] = None
    # Round-5 R5-F01: `phone_masked` alone cannot distinguish "we have this number,
    # masked" from "we have no number for this customer" — book.py fell back to the
    # literal string "xxx-xxx-xxxx" for both, and that placeholder rendered on 159 of
    # 212 rows next to a copy affordance (ruling 68) that would have copied a string
    # that was never a number. Defaults True: every hand-authored fixture below carries
    # a real-looking masked number. book.build() sets this explicitly per row from
    # whether the sheet's own Phone column was present.
    phone_on_file: bool = True
    # 2026-10-01: the Odoo crm.lead id this sheet-served customer is, recorded by the
    # crm.lead merge (pipelines/odoo_links). None on every other row; the case's Odoo
    # deep link uses it instead of the sheet's Freshworks `crm_id`.
    odoo_lead_id: Optional[int] = None

    def __post_init__(self):
        if not self.identity_key:
            self.identity_key = "identity:hash:%s" % self.customer_no


def make_cash_contract(uid, customer_uid, price, deposit, deposit_paid, balance_due,
                       balance_paid=False, status="ACTIVE", acceptance_date=None):
    """Deck v20.0 CASH — ONE FORMAT ONLY: a deposit from THB 5,000 scaling with
    system size, then instalment 2 for the WHOLE remaining balance. Cash 2 and
    Cash 3 are retired; a third line here would resurrect them."""
    price, deposit = Decimal(price), Decimal(deposit)
    fixture = ContractFixture(uid, customer_uid, "CASH", price, 2, deposit_paid,
                              status=status, acceptance_date=acceptance_date)
    balance = price - deposit
    fixture.instalments = [
        Instalment(due_date=deposit_paid, category="REGULAR",
                   principal_amount=deposit, interest_amount=Decimal("0.00"),
                   paid_principal=deposit, legal_entity="EPC"),
        Instalment(due_date=balance_due, category="REGULAR",
                   principal_amount=balance, interest_amount=Decimal("0.00"),
                   paid_principal=balance if balance_paid else Decimal("0.00"),
                   legal_entity="EPC"),
    ]
    return fixture


def make_restructured_contract(uid, customer_uid, old_principal, old_term, old_first_due,
                               old_paid_through, new_term, new_first_due,
                               acceptance_date=None):
    """Deck S08 — the addendum's new schedule SUPERSEDES the old lines. The money
    engine follows is_active_regular, so DPD, arrears and penalty move to the new
    schedule with zero engine edits. One restructure ever.

    The addendum's principal is COMPUTED by the same rule the approve endpoint
    uses — outstanding principal plus interest already earned (due, unpaid) —
    never hard-coded: a hard-coded figure silently forgave 119,580 THB in the
    first seed (the adversarial round's finding)."""
    base = ContractFixture(uid, customer_uid, "LEASE", Decimal(old_principal), old_term,
                           old_first_due, paid_through=old_paid_through,
                           acceptance_date=acceptance_date).build()
    carried = Decimal("0.00")
    for line in base.instalments:
        carried += line.outstanding_principal
        if line.due_date <= BUSINESS_DATE:
            carried += line.outstanding_interest
        line.schedule_status = "SUPERSEDED"
    addendum = ContractFixture(uid, customer_uid, "LEASE",
                               carried.quantize(Decimal("0.01")),
                               new_term, new_first_due).build()
    base.instalments = base.instalments + addendum.instalments
    base.status = "ACTIVE"
    return base


# ---- Round 4, ruling 45: re-seeding board_column_id — SUPERSEDED 2026-09-09 --------
#
# Ruling 45 measured "Call today" holding 141/151 (93.4%) of the live desk and had this
# file compute a starting column for all 212 customers in one deterministic seed-time
# pass, writing it onto `CustomerFixture.board_column_id`. The rule it implemented is
# `docs/design/round-4/board/B-system.md` §1.2, and §1.7 of that document required the
# pass to run at seed time and FORBADE deriving the column per request.
#
# That is reversed. The column is now computed where it is served, by `app/board.py`,
# because the board has to answer to a due date passing — a promise lapsing or an
# instalment falling overdue must move a card with no officer and no nightly job. See
# `docs/archive/superpowers/specs/2026-09-09-board-derived-columns-design.md` §9f, which answers
# §1.7's three objections one at a time rather than stepping over them.
#
# The stored field went with the pass: it had four readers, all replaced, and a value
# written at seed time and read nowhere is dead state.


def seed(book_result=None):
    # `book_result` lets the caller hand in one book.build() instead of paying for a
    # second read (main.reload_book needs both halves of it).
    from . import book as book_mod
    book_result = book_result if book_result is not None else book_mod.build()
    if book_mod.from_landing(book_result[1]):
        # Arina, 2026-09-24: a landed sheet IS the book — no made-up demo customer
        # is served beside the real ones. The in-memory demo keeps them below.
        return list(book_result[0])
    customers = [
        CustomerFixture(
            uid="018f3b91-4c22-7a0e-9d51-6b7c8e9f0a12",
            customer_no="C-000871",
            display_name="สมชาย ใจดี",
            phone_masked="08x-xxx-4471",
            priority=1,
            reason_code="BROKEN_PROMISE",
            officer="noon",
            recovery_stage="CONTACT",
            contracts=[
                # FX-C1: 300,000 price, 20 % down, 240,000 over 60 at 7.9 % = 5,580.00.
                ContractFixture("K-0871-1", "018f3b91-4c22-7a0e-9d51-6b7c8e9f0a12", "LEASE",
                                Decimal("240000"), 60, date(2026, 10, 1)).build(),
                # FX-C4: 270,000 over 60 = 6,277.50, one instalment behind.
                # DELIBERATELY WORSE THAN THE FIRST, and listed second. A customer's
                # band must follow this contract, not contracts[0].
                ContractFixture("K-0871-2", "018f3b91-4c22-7a0e-9d51-6b7c8e9f0a12", "LEASE",
                                Decimal("270000"), 60, date(2026, 9, 1)).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3b92-5d33-7b1f-8e62-7c8d9f0a1b23",
            customer_no="C-000912",
            display_name="อารีย์ พงษ์ไพบูลย์",
            phone_masked="09x-xxx-2210",
            priority=2,
            reason_code="PROMISE_DUE_TODAY",
            officer="noon",
            recovery_stage="PROMISE",
            contracts=[
                # FX-C2: the non-dividing case — 210,000 over 36, final line 7,215.95.
                ContractFixture("K-0912-1", "018f3b92-5d33-7b1f-8e62-7c8d9f0a1b23", "CASH",
                                Decimal("210000"), 36, date(2026, 10, 1),
                                legacy_pre_v20=True).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3b93-6e44-7c20-9f73-8d9e0a1b2c34",
            customer_no="C-001004",
            display_name="บริษัท ไทยโซล่าร์ จำกัด",
            phone_masked="02x-xxx-8890",
            priority=3,
            reason_code="PERMIT_HOLD_AGEING",
            officer="ploy",
            recovery_stage="CONTACT",
            contracts=[
                # THE ONE THAT PROVES D13. A permit hold pauses the FEE and does not
                # pause the CLOCK, so this contract is 38 days past due with a fee that
                # stopped accruing. Drawing it at DPD 0 is the exact defect the audit found.
                ContractFixture("K-1004-1", "018f3b93-6e44-7c20-9f73-8d9e0a1b2c34", "LEASE",
                                Decimal("300000"), 60, date(2026, 9, 15),
                                fee_state="PERMIT_HOLD",
                                fee_state_from=date(2026, 10, 10)).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3b94-7f55-7d31-a084-9e0f1b2c3d45",
            customer_no="C-001067",
            display_name="วิไล ศรีสุข",
            phone_masked="08x-xxx-1123",
            priority=4,
            reason_code="PART_PAYMENT_SHORTFALL",
            officer="ploy",
            recovery_stage="NEGOTIATE",
            contracts=[
                # TC-MNY-045: 5,000.00 against a 5,580.00 line leaves 580.00, so DPD
                # keeps running. "Sufficient payment" means the line reaches zero.
                ContractFixture("K-1067-1", "018f3b94-7f55-7d31-a084-9e0f1b2c3d45", "LEASE",
                                Decimal("240000"), 60, date(2026, 10, 1),
                                part_payment=Decimal("5000.00")).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3b95-8066-7e42-b195-af102c3d4e56",
            customer_no="C-001120",
            display_name="ธนกร รุ่งเรือง",
            phone_masked="06x-xxx-7734",
            priority=5,
            reason_code="DISPUTE_OPEN",
            officer="noon",
            recovery_stage="ESCALATE",
            contracts=[
                # REQ-MNY-033: a dispute does NOT pause the fee. G9 paused it; G13
                # reversed that, because a pause on complaint makes a complaint worth money.
                ContractFixture("K-1120-1", "018f3b95-8066-7e42-b195-af102c3d4e56", "CASH",
                                Decimal("300000"), 60, date(2026, 8, 1),
                                fee_state="DISPUTE_UNDER_REVIEW",
                                fee_state_from=date(2026, 9, 1),
                                legacy_pre_v20=True).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3b96-9177-7f53-c2a6-b0213d4e5f67",
            customer_no="C-001188",
            display_name="กมล เจริญทรัพย์",
            phone_masked="08x-xxx-9902",
            priority=6,
            reason_code="EARLY_OVERDUE",
            officer="ploy",
            recovery_stage="CONTACT",
            contracts=[
                ContractFixture("K-1188-1", "018f3b96-9177-7f53-c2a6-b0213d4e5f67", "LEASE",
                                Decimal("240000"), 60, date(2026, 10, 20)).build(),
            ],
        ),
        # ---- 2026-08-30 rebuild: the scenario book (deck v20.0, S01–S12) ----------
        # Identities below come from real rows of the imported Order Master sheet
        # (masked at import); their arrears and histories are ENGINE-BUILT SYNTHETIC.
        # data_source says which half is which — R5: mark it, or a reviewer reads
        # invention as fact. order_ref is a fixture-AUTHORED bridge (no join key
        # exists in live data), and the wire repeats that.
        CustomerFixture(
            uid="018f3c01-0001-7a00-9000-000000002001",
            customer_no="C-002001",
            display_name="ลูกค้าทดสอบ 0171",
            phone_masked="08x-xxx-4559",
            priority=7,
            reason_code="BALANCE_INVOICED",
            officer="noon",
            recovery_stage="CONTACT",
            data_source=dict(SHEET_IDENTITY),
            order_ref={"no": 5, "crm_id": "SYN-ORDER-005",
                       "bridge_note": "fixture-authored bridge; no join key exists in live data"},
            scenario_codes=("S01",),
            contracts=[
                # S01 happy path: deposit received (THB 20,000 ≥ the 5,000 floor,
                # scaled to a 157k system), handover done, the WHOLE balance invoiced
                # and not yet due. Nothing overdue — this is what "on track" looks like.
                make_cash_contract("K-2001-1", "018f3c01-0001-7a00-9000-000000002001",
                                   "157353", "20000", date(2026, 9, 10), date(2026, 10, 30),
                                   acceptance_date=date(2026, 10, 12)),
            ],
        ),
        CustomerFixture(
            uid="018f3c01-0011-7a00-9000-000000002011",
            customer_no="C-002011",
            display_name="ลูกค้าทดสอบ 0165",
            phone_masked="08x-xxx-6632",
            priority=8,
            reason_code="CASH_BALANCE_OVERDUE",
            officer="noon",
            recovery_stage="NEGOTIATE",
            data_source=dict(SHEET_IDENTITY),
            order_ref={"no": 12, "crm_id": "SYN-ORDER-012",
                       "bridge_note": "fixture-authored bridge; no join key exists in live data"},
            scenario_codes=("S11",),
            contracts=[
                # S11: the system is on the roof and the closing payment is 64 days
                # late — EPC's real cash exposure. No SPV leg exists for this contract.
                make_cash_contract("K-2011-1", "018f3c01-0011-7a00-9000-000000002011",
                                   "155000", "20000", date(2026, 6, 5), date(2026, 8, 20),
                                   status="PAST_DUE", acceptance_date=date(2026, 8, 1)),
            ],
        ),
        CustomerFixture(
            uid="018f3c01-0031-7a00-9000-000000002031",
            customer_no="C-002031",
            display_name="ลูกค้าทดสอบ 0048",
            phone_masked="09x-xxx-3964",
            priority=9,
            reason_code="LEASE_NOTICE_30",
            officer="ploy",
            recovery_stage="CONTACT",
            data_source=dict(SHEET_IDENTITY),
            order_ref={"no": 2, "crm_id": "SYN-ORDER-002",
                       "bridge_note": "fixture-authored bridge; no join key exists in live data"},
            scenario_codes=("S02", "S07"),
            contracts=[
                # S07 rung 1: DPD 33, two lines open — notice and cure.
                ContractFixture("K-2031-1", "018f3c01-0031-7a00-9000-000000002031", "LEASE",
                                Decimal("150000"), 96, date(2026, 9, 20),
                                acceptance_date=date(2026, 9, 1)).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3c01-0032-7a00-9000-000000002032",
            customer_no="C-002032",
            display_name="ลูกค้าทดสอบ 0098",
            phone_masked="09x-xxx-2626",
            priority=10,
            reason_code="RESTRUCTURE_OFFERED",
            officer="ploy",
            recovery_stage="NEGOTIATE",
            data_source=dict(SHEET_IDENTITY),
            order_ref={"no": 3, "crm_id": "SYN-ORDER-003",
                       "bridge_note": "fixture-authored bridge; no join key exists in live data"},
            scenario_codes=("S07", "S08"),
            contracts=[
                # S07 rung 2: DPD 64 — the restructure is OFFERED here, before NPL.
                ContractFixture("K-2032-1", "018f3c01-0032-7a00-9000-000000002032", "LEASE",
                                Decimal("240000"), 96, date(2026, 8, 20),
                                acceptance_date=date(2026, 8, 1)).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3c01-0033-7a00-9000-000000002033",
            customer_no="C-002033",
            display_name="ลูกค้าทดสอบ 0189",
            phone_masked="09x-xxx-2296",
            priority=11,
            reason_code="NPL_DECLARED",
            officer="noon",
            recovery_stage="ESCALATE",
            data_source=dict(SHEET_IDENTITY),
            order_ref={"no": 6, "crm_id": "SYN-ORDER-006",
                       "bridge_note": "fixture-authored bridge; no join key exists in live data"},
            scenario_codes=("S07",),
            contracts=[
                # S07 rung 3: DPD 95, NPL DECLARED by a human on 2026-10-19 —
                # provisioning only; the contract is NOT moved yet. The month-4
                # window exists on purpose.
                ContractFixture("K-2033-1", "018f3c01-0033-7a00-9000-000000002033", "LEASE",
                                Decimal("240000"), 96, date(2026, 7, 20),
                                status="NON_PERFORMING",
                                acceptance_date=date(2026, 7, 1)).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3c01-0034-7a00-9000-000000002034",
            customer_no="C-002034",
            display_name="ลูกค้าทดสอบ 0236",
            phone_masked="08x-xxx-6684",
            priority=12,
            reason_code="ASSIGNED_TO_EPC",
            officer="noon",
            recovery_stage="RECOVERY",
            data_source=dict(SHEET_IDENTITY),
            order_ref={"no": 8, "crm_id": "SYN-ORDER-008",
                       "bridge_note": "fixture-authored bridge; no join key exists in live data"},
            scenario_codes=("S07", "S12"),
            contracts=[
                # S07 rung 4: DPD 130 — the deed executed on 2026-10-14, EPC paid SPV
                # 100% of the remaining NPV, EPC now collects. S12 runs on this one:
                # lot RP-2026-0148, expected 12 / actual 11, unpriced → stock blocked.
                ContractFixture("K-2034-1", "018f3c01-0034-7a00-9000-000000002034", "LEASE",
                                Decimal("240000"), 48, date(2026, 6, 15),
                                status="NON_PERFORMING",
                                acceptance_date=date(2026, 6, 1)).build(),
            ],
        ),
        CustomerFixture(
            uid="018f3c01-0035-7a00-9000-000000002035",
            customer_no="C-002035",
            display_name="ลูกค้าทดสอบ 0176",
            phone_masked="06x-xxx-8798",
            priority=13,
            reason_code="RESTRUCTURE_ACTIVE",
            officer="ploy",
            recovery_stage="PROMISE",
            data_source=dict(SHEET_IDENTITY),
            order_ref={"no": 9, "crm_id": "SYN-ORDER-009",
                       "bridge_note": "fixture-authored bridge; no join key exists in live data"},
            scenario_codes=("S08",),
            contracts=[
                # S08 after approval: the old lines are SUPERSEDED, the addendum's
                # schedule runs from 2026-11-01, and the engine reads DPD 0 from the
                # new lines with zero engine edits. Two missed on THIS schedule
                # declares NPL immediately — no second restructure.
                make_restructured_contract("K-2035-1", "018f3c01-0035-7a00-9000-000000002035",
                                           "180000", 96, date(2026, 6, 1), 3,
                                           60, date(2026, 11, 1),
                                           acceptance_date=date(2026, 5, 15)),
            ],
        ),
        CustomerFixture(
            uid="018f3c01-0036-7a00-9000-000000002036",
            customer_no="C-002036",
            display_name="ลูกค้าทดสอบ 0005",
            phone_masked="08x-xxx-4810",
            priority=14,
            reason_code="SERVICE_ARREARS",
            officer="ploy",
            recovery_stage="CONTACT",
            data_source=dict(SHEET_IDENTITY),
            order_ref={"no": 1, "crm_id": "SYN-ORDER-001",
                       "bridge_note": "fixture-authored bridge; no join key exists in live data"},
            scenario_codes=("S02", "S09"),
            line_id="volt-demo-2036",
            contracts=[
                # S09 — the two-entity showcase: the LEASE (SPV) is current, and the
                # month-37+ SERVICE receivable (EPC) is what's overdue. Service
                # arrears NEVER feed the lease NPL ladder. Acceptance 2023-08-15
                # puts the business date in month 39.
                ContractFixture("K-2036-1", "018f3c01-0036-7a00-9000-000000002036", "LEASE",
                                Decimal("288000"), 96, date(2023, 10, 1), paid_through=37,
                                status="ACTIVE",
                                acceptance_date=date(2023, 8, 15)).build(),
            ],
        ),
    ]
    # R12 — safe link-only numbers for the six SYNTHETIC customers: deliberately
    # invalid (dial nobody), present so the โทร/LINE actions are demonstrable.
    for customer in customers:
        if customer.data_source.get("identity") == "SYNTHETIC":
            customer.phone_e164 = "+66000000%s" % customer.customer_no[-3:]
            customer.line_id = "volt-demo-%s" % customer.customer_no[-4:]
    # ---- 2026-09-02 realignment: the migrated book (C5, REQ-INT-030) -----------
    # Real VOLT IDs, amounts, statuses and notes from the New Order Master export,
    # appended after the proof cases so every uid above keeps its meaning.
    customers.extend(book_result[0])
    return customers


def identities(book_result=None):
    """The contract-less rows the serving source holds.

    The 2026-09-19 ruling made Odoo crm.lead the served book, and a lead carries no
    money row: book.build() returns it in `registry`, not among the contract holders.
    These are people, not cases — the workbook lists them, the record opens them
    (routers/today.py::_identity_only_case_detail), and no collection-engine loop
    sees them: every one of those loops assumes a contract.
    """
    from . import book as book_mod
    _customers, report = book_result if book_result is not None else book_mod.build()
    return list(report.get("registry") or [])
