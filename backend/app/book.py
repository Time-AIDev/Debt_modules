"""The migrated book — REQ-INT-030..032.

Turns backend/app/fixtures_sheet.json (produced by scripts/import_master_sheet.py
from the New Order Master export) into CustomerFixture / ContractFixture objects the
money engine already understands, and keeps the sheet's own figures beside them so
the migration screen can show "the sheet says X · the engine says Y" (MC4).

Honesty rules:
  - data_source = SHEET for identity and history: the numbers came from the team's
    own tabs. Where a value had to be DERIVED (a principal from an instalment and a
    term; a paid-through count from Days Late) the derivation is named on the row.
  - Phone and email were masked at import; since 2026-09-20 the PHONE is kept whole
    with the row (import_master_sheet.py's `e164`) and hidden at the serving layer
    instead — the case serves a mask plus `phone_revealable`, and the audited
    `phone:reveal` route is the only door that answers the number. Email still has no
    full value anywhere (R12).
  - The engine's DPD is measured against settings.business_date. The export is a
    snapshot of 2026-09-02; the row keeps sheet_days_late so the two can be compared.
"""
import json
import math
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .config import settings
from .fixtures import ContractFixture, CustomerFixture, make_cash_contract

SHEET = {"identity": "SHEET", "history": "SHEET"}
ODOO = {"identity": "ODOO", "history": "ODOO"}
FLAT_RATE = Decimal("7.9")
DEFAULT_TERM = 96          # the live book runs mostly on 84/96 (⚠ L4)
LEASE_DUE_DAY = 10         # ⚠ I-14: lease due on the 10th
CASH_TERMS_DAYS = 7        # cash invoices are due seven days after issue
# Round-3 J3-17: the sheet's Days Late is measured from the export's own snapshot day,
# the app's DPD from the business date. Naming the snapshot is what makes the gap
# readable ("ชีต 54 วัน ณ 02/09/2026" vs "แอป 13 วัน ณ 23/10/2026"). The held
# export's day; a landed sheet names its own (snapshot_date below).
SHEET_SNAPSHOT_DATE = date(2026, 9, 2)

FIXTURE_PATH = Path(__file__).with_name("fixtures_sheet.json")

# One build per invalidation (and per explicit as_of). A full build reads the whole
# landing schema (1.5s at the 350k bench); a fresh session's invoice_pipeline seed
# called it again even though boot had just built the same book. The business date is
# NOT in the key: the sheet's facts do not change at midnight, so a new calendar day
# must not build a second book.
_CACHE = {}
_VERSION = 0


def invalidate(reads=True):
    global _VERSION
    _VERSION += 1
    _CACHE.clear()
    # The source block is counted from landing and cached per import epoch; a caller
    # invalidating the book (a test swapping the landing, a reload) wants it re-read.
    from . import book_source
    book_source.forget_summary()
    # The non-PEAK landing reads are kept per non-PEAK epoch (fix-all F3); only
    # main.reload_book keeps them (`reads=False`) — a test that swaps the landing
    # without an epoch must not be served the old rows.
    if reads:
        book_source.forget_reads()


def _d(value):
    return Decimal(value) if value not in (None, "") else None


def _date(value):
    return date.fromisoformat(value) if value else None


def from_landing(report=None):
    """Whether the served book was read from the landing schema (a landed sheet or
    Odoo pull) rather than the held fixture — the made-up demo rows only ever sit
    beside the fixture."""
    report = report if report is not None else build()[1]
    return (report.get("source") or {}).get("origin") == "LANDING"


def _sheet_day(source):
    """A landed SHEET run's own capture day, or None — the held fixture carries none,
    and an Odoo-only landing is not the sheet."""
    return _date(source.get("captured_on")) if source.get("serving_code") == "SHEET" else None


def sheet_captured_on():
    """The landed SHEET run's capture day — what its contracts were derived as of —
    or None for the held fixture book (derived as of the business date)."""
    return _sheet_day(build()[1].get("source") or {})


def snapshot_date():
    """The day the served sheet was captured: the landed SHEET run's, or the held
    export's 2026-09-02."""
    return sheet_captured_on() or SHEET_SNAPSHOT_DATE


def principal_from_instalment(pmt: Decimal, term: int) -> Decimal:
    """Flat rate: total = P × (1 + rate × years); PMT = total / term."""
    years = Decimal(term) / Decimal(12)
    total = pmt * Decimal(term)
    return (total / (Decimal(1) + FLAT_RATE / Decimal(100) * years)).quantize(Decimal("0.01"))


def instalments_due_by(first_due: date, term: int, as_of: date) -> int:
    # The same dates the schedule is built on (fixtures._add_months), so a due on the
    # 31st is counted on the day its line falls due, not on the 28th.
    from .fixtures import _add_months
    return sum(1 for i in range(term) if _add_months(first_due, i) <= as_of)


def payment_status_code(raw):
    return {
        "Current": "CURRENT", "Late": "LATE", "NPL": "NPL", "Closed": "CLOSED",
        "Not Installed": "NOT_INSTALLED",
        # 2026-09-20 (Closed/Terminated ruling): when the sheet owner adds the value,
        # it lands as its own status. Until then `imports._reconcile` carries the
        # TERMINATED row as explicitly unjudged — never a green tick.
        "Terminated": "TERMINATED",
    }.get(raw or "", None)


def officer_for(product):
    # Interview: one officer follows leasing, the other cash (names from the MapLog).
    return "nantapol" if product == "LEASE" else "thip"


def load_sheet():
    # The seam. Where the book comes from is book_source's business; this module
    # only ever needed the payload. Unconfigured, it still reads FIXTURE_PATH.
    from . import book_source
    return book_source.load()


def usual_instalment(months):
    """Round-2 nantapol N2-03: the ONE rule for "what is this contract's instalment"
    when the sheet's PMT column is empty — the amount the customer most often paid,
    ties going to the most recent cell. The month grid (routers/today._month_grid)
    reads the same rule, so the header, the invoices, the grid footer and the old
    promise can no longer disagree (5,799 vs 25,299 on ปัทมวรรณ (1)).
    Returns (pmt or None, count of cells at that amount, count of paid cells)."""
    paid = [str(m.get("amount")) for m in months if m and m.get("kind") == "PAID" and m.get("amount")]
    if not paid:
        return None, 0, 0
    best = max(reversed(paid), key=paid.count)
    return _d(best), paid.count(best), len(paid)


def grid_cells(months, kind):
    """1-based month indexes of the cells of one kind (LATE, LINK_SENT, PAID)."""
    return [i + 1 for i, m in enumerate(months) if m and m.get("kind") == kind]


def _lease_contract(uid, customer_uid, row, as_of, confirmation=None):
    """A leasing row -> ContractFixture, or None with a reason."""
    pmt = _d(row.get("pmt_inc_vat"))
    months = row.get("months") or []
    pmt_note = "sheet PMT column"
    if pmt is None:
        pmt, hits, paid_n = usual_instalment(months)
        if pmt is not None:
            pmt_note = "most frequent paid month cell %s (%d of %d paid cells); sheet PMT column empty" % (pmt, hits, paid_n)
    term = row.get("term_original") or (len(months) if len(months) > 30 else None) or DEFAULT_TERM
    first_due = _date(confirmation["first_due"]) if confirmation else _date(row.get("first_payment_date"))
    first_due_note = "verified contract schedule" if confirmation else "sheet First Payment Date"
    if first_due is None:
        signed = _date(row.get("contract_signed"))
        if signed:
            first_due = date(signed.year + (signed.month // 12), signed.month % 12 + 1, LEASE_DUE_DAY)
            # DQ 2026-09-26 F10: this said "sheet First Payment Date" for 155 customers.
            first_due_note = "derived: the 10th of the month after Contract Signed (sheet First Payment Date empty)"
    if first_due is None and pmt is not None and months:
        # No date on the row: count the month cells the sheet has filled and walk
        # back from the snapshot date, due on the 10th (⚠ I-14). Named as derived.
        filled = max((i for i, m in enumerate(months) if m), default=-1) + 1
        if filled:
            y, m = as_of.year, as_of.month - (filled - 1)
            while m <= 0:
                y, m = y - 1, m + 12
            first_due = date(y, m, LEASE_DUE_DAY)
            first_due_note = "walked back from %d filled month cells, due on the 10th" % len([m for m in months if m])
    if pmt is None or first_due is None:
        return None, "no instalment or first due date in the export"
    principal = principal_from_instalment(pmt, term)
    due_by = instalments_due_by(first_due, term, as_of)
    status = payment_status_code(row.get("payment_status"))
    evidence_only = bool(row.get("financial_evidence_only"))
    days_late = row.get("days_late") or 0
    late_cells = grid_cells(months, "LATE")
    link_sent_cells = grid_cells(months, "LINK_SENT")
    if status in (None, "CURRENT", "CLOSED", "NOT_INSTALLED"):
        missed = 0
        missed_note = "status %s: nothing missed" % (status or "blank")
    elif late_cells:
        # Round-2 nantapol N2-04: the grid is the sheet's own statement of which
        # months are unpaid — one LATE cell is one missed instalment. Days Late is
        # only the fallback when the grid has no LATE cell.
        missed = len(late_cells)
        missed_note = "%d LATE month cells (%s)" % (missed, ", ".join("M%d" % i for i in late_cells))
    elif status == "LATE":
        missed = max(1, int(math.ceil(days_late / 30.0))) if days_late else 1
        missed_note = "sheet Days Late %s (no LATE month cell)" % days_late
    else:  # NPL
        missed = max(3, int(math.ceil(days_late / 30.0))) if days_late else 3
        missed_note = "NPL: sheet Days Late %s, floor 3 (no LATE month cell)" % days_late
    paid_through = max(0, due_by - missed)
    if status == "CLOSED":
        paid_through = term
    engine_status = {"CLOSED": "CLOSED", "NPL": "NON_PERFORMING", "LATE": "PAST_DUE",
                     "NOT_INSTALLED": "PRE_COLLECTION",
                     # 2026-09-20: when the sheet owner adds the value, it becomes the
                     # engine status of its own — never folded into CLOSED.
                     "TERMINATED": "TERMINATED"}.get(status, "ACTIVE")
    if evidence_only:
        # The maintained worksheet is contractual/status evidence, never a receipt.
        paid_through, engine_status = 0, "ACTIVE"
    fixture = ContractFixture(uid, customer_uid, "LEASE", principal, term, first_due,
                              status=engine_status, paid_through=paid_through,
                              acceptance_date=_date(row.get("contract_signed"))).build()
    fixture.derivation = {
        "principal": "derived from PMT %s × term %d at 7.9%% flat" % (pmt, term),
        "pmt": pmt_note,
        "paid_through": "%d due by %s minus %d missed (%s)" % (due_by, as_of, missed, missed_note),
        "first_due": first_due_note,
        "invoices": ("one OVERDUE invoice per LATE month cell (%s)" % ", ".join("M%d" % i for i in late_cells) if late_cells
                     else "one OVERDUE invoice per instalment due and unpaid (Days Late derivation)")
                    + ("; the link sits on the LINK_SENT cell M%d" % link_sent_cells[-1] if link_sent_cells
                       else "; no LINK_SENT cell — the next instalment is ISSUED, no link claimed"),
    }
    # The sheet row travels with the contract so a customer with two contracts keeps
    # two grids, two PMTs and two notes (N2-03).
    fixture.requires_schedule_confirmation = True
    fixture.requires_installation_confirmation = True
    fixture.financial_evidence_only = evidence_only
    if evidence_only:
        from . import debt_imports
        installation = debt_imports.installation_for(uid) or debt_imports.pipeline_installation_for(fixture)
        fixture.acceptance_date = _date(installation["completed_on"]) if installation else None
    fixture.schedule_confirmation = confirmation
    fixture.calendar_months = row.get("calendar_months") or []
    fixture.pmt = pmt
    fixture.sheet_row = row
    fixture.month_cells = months
    fixture.comment_th = row.get("comment_th") or row.get("comment")
    fixture.late_cells = late_cells
    fixture.link_sent_cells = link_sent_cells
    return fixture, None


CASH_STATUS_WORD = {"closed": "CLOSED", "late": "PAST_DUE", "link sent": "PAST_DUE",
                    "not due": "ACTIVE", "not issued": "ACTIVE", "terminated": "TERMINATED"}


def _cash_contract(uid, customer_uid, row, invoices, as_of):
    price = _d(row.get("price")) if row else None
    if price is None and invoices:
        price = sum(_d(i["amount"]) for i in invoices if i.get("amount")) or None
    if price is None:
        return None, "no price in the export"
    deposit = _d(row.get("dp_inc_vat")) if row else None
    paid_cells = [m for m in (row.get("months") if row else []) if m and m.get("kind") == "PAID"]
    deposit_note = "sheet DP" if deposit is not None else None
    if deposit is None and invoices and all(i.get("amount") for i in invoices):
        # Round-2 thip T2-01: the sheet's own invoices say what was paid. Inventing a
        # 20% deposit on top of an invoice that is fully outstanding put 470,800 on the
        # screen against a 588,500 invoice. Paid = amount - outstanding, per invoice.
        deposit = sum((_d(i["amount"]) - (_d(i["outstanding"]) if i.get("outstanding") not in (None, "") else _d(i["amount"])))
                      for i in invoices)
        deposit_note = "paid so far per the sheet's invoices (amount minus outstanding)"
    if deposit is None:
        deposit = _d(paid_cells[0]["amount"]) if paid_cells and len(paid_cells) > 1 else max(Decimal("5000"), (price * Decimal("0.2")).quantize(Decimal("1")))
        deposit_note = "derived"
    deposit = min(deposit, price)
    issued = None
    if invoices:
        issued = _date(invoices[0].get("issued_on"))
    signed = _date(row.get("contract_signed")) if row else None
    deposit_paid_on = signed or (issued - timedelta(days=30) if issued else as_of - timedelta(days=60))
    balance_due = _date(invoices[0].get("due_on")) if invoices and invoices[0].get("due_on") else \
        _date((row or {}).get("next_due_date")) or \
        (_date(row.get("first_payment_date")) if row and row.get("first_payment_date") else deposit_paid_on + timedelta(days=45))
    closed = bool(row and any(m and m.get("kind") == "CLOSED" for m in row.get("months") or [])) or \
        (row or {}).get("dc_comment") in ("Close", "Closed") or (row or {}).get("comment") in ("Close", "Closed")
    outstanding = None
    if invoices:
        outstanding = sum(_d(i["outstanding"]) for i in invoices if i.get("outstanding"))
    elif row and row.get("outstanding_amount") is not None:
        outstanding = _d(row["outstanding_amount"])         # the tab's own OUTSTANDING AMOUNT
    elif row and (paid_cells or row.get("deposit_paid") == "Paid"):
        # 'Done - Cash' (2026-09-25): the deposit it marks Paid plus every paid
        # instalment cell, against the price.
        outstanding = price - sum(_d(m["amount"]) for m in paid_cells if m.get("amount")) - \
            (_d(row.get("dp_inc_vat")) or Decimal("0") if row.get("deposit_paid") == "Paid" else Decimal("0"))
    balance_paid = closed or (outstanding is not None and outstanding <= 0)
    # The cash tab counts its own overdue instalments; where it does, that count (or a
    # LATE cell) decides, not a due date this function had to guess.
    sheet_overdue = None if invoices else _d((row or {}).get("overdue"))
    late = (sheet_overdue > 0 or any(m and m.get("kind") == "LATE" for m in row.get("months") or [])) \
        if sheet_overdue is not None else balance_due < as_of
    status = "CLOSED" if closed else ("PAST_DUE" if (late and not balance_paid) else "ACTIVE")
    # 'Done - Cash' states each customer's status itself (2026-09-25); where it does,
    # its word decides.
    status = CASH_STATUS_WORD.get(((row or {}).get("status_word") or "").lower(), status)
    balance_paid = balance_paid or status == "CLOSED"
    fixture = make_cash_contract(uid, customer_uid, str(price), str(deposit), deposit_paid_on,
                                 balance_due, balance_paid=balance_paid, status=status,
                                 acceptance_date=signed)
    if (row or {}).get("financial_evidence_only"):
        fixture.financial_evidence_only = True
        fixture.status = "ACTIVE"
        from . import debt_imports
        installation = debt_imports.installation_for(uid) or debt_imports.pipeline_installation_for(fixture)
        fixture.acceptance_date = _date(installation["completed_on"]) if installation else None
        fixture.requires_installation_confirmation = True
        fixture.requires_schedule_confirmation = True
        from . import schedule_confirmation
        fixture.schedule_confirmation = schedule_confirmation.active().get(uid)
        for line in fixture.instalments:
            line.paid_principal = line.paid_interest = line.paid_fee = Decimal("0.00")
    fixture.derivation = {"deposit": deposit_note, "balance_due": str(balance_due),
                          "price": ("sum of the sheet's invoices" + (" (instalment %s — later invoices not yet issued)" % invoices[0]["instalment"]
                                                                     if invoices and invoices[0].get("instalment") else ""))
                                   if not (row and row.get("price")) else "sheet price"}
    fixture.pmt = None
    fixture.sheet_row = row or {}
    fixture.month_cells = (row or {}).get("months") or []
    fixture.comment_th = (row or {}).get("comment_th") or (row or {}).get("comment")
    fixture.late_cells, fixture.link_sent_cells = [], []
    return fixture, None


def build(as_of: date = None):
    from . import debt_imports
    with debt_imports.proof_read_scope():
        return _build(as_of)


def _build(as_of: date = None):
    """Returns (customers, migration_report). Deterministic: uids derive from the
    VOLT ID, so a tester's session and a test see the same book.

    The result is cached per invalidation (and per explicit as_of) — building it
    costs a full landing read, and a fresh session seeds invoice_pipeline from it
    while the book at boot is already in memory. `invalidate()` is called by the two
    things that make the cache wrong: an import/apply (main.reload_book) and the
    test fixture that rebuilds state between tests. A server never mutates the
    returned fixtures; sessions already share main.CUSTOMERS, so this shares no more.

    Contracts are derived as of the day the sheet knows: a landed SHEET run's
    capture day (what the sheet says was paid by then), else the business date (the
    held fixture book, unchanged).
    """
    key = (as_of, _VERSION)
    if key in _CACHE:
        return _CACHE[key]
    data = load_sheet()
    if data is None:
        return [], {"imported": 0, "reason": "fixtures_sheet.json absent"}
    as_of = as_of or _sheet_day(data.get("source") or {}) or settings.business_date
    from . import schedule_confirmation
    confirmations = schedule_confirmation.active()
    customers, skipped = [], []
    for i, rec in enumerate(data["customers"]):
        # An approved financial supplement owns its contract classification.
        # Q7 display-field decisions stay on the source record; a later invoice
        # product label cannot discard that contract or rebuild it as another entity.
        supplement_product = (rec.get("contract_supplement") or {}).get("product")
        product = supplement_product if supplement_product in ("LEASE", "CASH") else rec["product"]
        no = rec["customer_no"] or "row%d" % i
        # The uid must not come from the row's POSITION when the row carries an
        # identifier of its own. `row%d` used the enumeration index, so a re-pull
        # that reordered the export gave a case keyed to the old uid a different
        # person (sync audit, 2026-09-20). The business key stays first: one sheet
        # holds the same customer_no on two rows (a money row and a tracking row)
        # with different volt_ids, and those must keep collapsing onto one uid —
        # `taken` in main._serve_book relies on it.
        if rec.get("customer_no"):
            uid_key = rec["customer_no"]
        else:
            uid_key = rec.get("volt_id") or rec.get("crm_id") or no
        cust_uid = "sheet-%s" % uid_key
        lease_row = rec.get("leasing")
        contracts = []
        reason = None
        if product == "LEASE":
            row = lease_row or _tracking_as_lease(rec.get("tracking"))
            if row:
                contract_uid = "K-%s-L" % no
                confirmation = confirmations.get(contract_uid)
                if confirmation and confirmation["customer_uid"] != cust_uid:
                    confirmation = None
                k, reason = _lease_contract(contract_uid, cust_uid, row, as_of, confirmation)
                if k and not k.calendar_months:
                    k.calendar_months = (rec.get("tracking") or {}).get("months") or []
                if k:
                    contracts.append(k)
            else:
                reason = "leasing customer with no money row in the export"
        else:
            k, reason = _cash_contract("K-%s-C" % no, cust_uid, rec.get("cash"), rec.get("cash_invoices"), as_of)
            if k:
                contracts.append(k)
        # 2026-09-20 (Closed/Terminated ruling): the sheet's tracking category states
        # an ended contract (Repossessed - * on default, Cooperative - Decommission at
        # the customer's request). Baked here at build time like the NPL rows the
        # fixtures already carry; a runtime termination goes through the session
        # overlay (cases.record_termination) instead.
        from . import cases as cases_domain
        termination = cases_domain.termination_from_tracking(rec.get("tracking"))
        if termination:
            for contract in contracts:
                contract.status = "TERMINATED"
                contract.termination = termination
        display = " ".join(p for p in (rec.get("name_th") or rec.get("name_roman") or "", ) if p) or rec["volt_id"]
        fixture = CustomerFixture(
            uid=cust_uid, customer_no=no, display_name=display,
            # R5-F01: the placeholder stays — nothing downstream may see a shape change
            # in phone_masked itself (test_journey_rebuild.py:63 asserts "x" in it for
            # every working-list row) — but phone_on_file now says, separately and
            # honestly, whether this is a real mask or the fallback. Only ORDER_MASTER
            # rows ever carry a Phone cell (import_master_sheet.py:404); everyone else
            # gets the placeholder AND phone_on_file=False, so a screen can render
            # absence instead of a copyable non-number. phone_e164 travels whole when
            # the reader kept one (2026-09-20) — unmasked in the book, because the
            # serving layer is what hides it now (customer_contact.phone_fields).
            phone_masked=rec.get("phone_masked") or "xxx-xxx-xxxx",
            phone_e164=rec.get("phone_e164"),
            line_id=rec.get("line_id"), meta_id=rec.get("meta_id"),
            phone_on_file=bool(rec.get("phone_masked")), priority=99,
            reason_code="SHEET_IMPORT", officer=officer_for(product),
            recovery_stage="CONTACT", contracts=contracts,
            # The row's own provenance, not a blanket label: since crm.lead became
            # the served book (2026-09-19) most rows are ODOO-sourced identities.
            data_source=dict(ODOO) if (rec.get("order") or {}).get("data_source") == "ODOO" else dict(SHEET),
            order_ref={"volt_id": rec["volt_id"], "source_refs": rec.get("source_refs"),
                       "bridge_note": "imported row; source_ref names the block and row"},
        )
        fixture.volt_id = rec["volt_id"]
        fixture.name_roman = rec.get("name_roman")
        fixture.epc = rec.get("epc")
        fixture.sales_lead = rec.get("sales_lead")
        fixture.sheet = rec  # the whole imported record travels for cases.py and the migration screen
        fixture.product = product
        fixture.contract_product_review = ({"source_product": rec["product"], "contract_product": product,
                                            "review_required": True, "reason": "SOURCE_PRODUCT_CONFLICT"}
                                           if supplement_product in ("LEASE", "CASH") and rec["product"] != product else None)
        # The Odoo lead this row is, when the crm.lead merge recorded one. The sheet's
        # own crm_id is the Freshworks deal id and must never become a crm.lead link.
        fixture.odoo_lead_id = rec.get("odoo_lead_id")
        fixture.odoo_lead_name = rec.get("odoo_lead_name") or (
            (rec.get("order") or {}).get("odoo_lead_name")
            if (rec.get("order") or {}).get("data_source") == "ODOO" else None)
        # Q7 / TASK-209: provenance for any field a person decided (empty otherwise).
        fixture.field_sources = rec.get("field_sources") or {}
        fixture.field_notes_th = rec.get("field_notes_th") or {}
        fixture.field_notes_en = rec.get("field_notes_en") or {}
        if not contracts:
            skipped.append({"volt_id": rec["volt_id"], "reason": reason})
        customers.append(fixture)
    report = {
        "registry": [c for c in customers if not c.contracts],
        "imported": len(customers),
        "with_contracts": len([c for c in customers if c.contracts]),
        "skipped": skipped,
        # A row with no volt_id, crm_id or customer_no keeps a positional uid; the
        # migration report says how many, because those are the rows a re-pull can
        # re-identify. Zero on every real export (all rows carry a VOLT id).
        "unstable_uid_rows": len([r for r in data["customers"]
                                  if not (r.get("volt_id") or r.get("crm_id") or r.get("customer_no"))]),
        "pivots": data.get("pivots"),
        # Final v2 (prototype 2363): the source block travels on the report so the
        # migration report can carry the import instant (imported_at) without a
        # second read of the book source.
        "source": data.get("source"),
        "blocks": data["source"]["blocks"],
        "warnings": data.get("warnings"),
        "counts": data.get("counts"),
    }
    result = ([c for c in customers if c.contracts], report)
    _CACHE[key] = result
    return result


def _tracking_as_lease(tracking):
    """The collection-tracking tab carries PMT and month cells by calendar month
    but no term; treat it as a leasing row with the default term."""
    if not tracking:
        return None
    months = [m.get("cell") for m in tracking.get("months") or []]
    first_label = next((m["month"] for m in tracking.get("months") or [] if m.get("cell") and m["cell"].get("kind") == "PAID"), None)
    first_due = None
    if first_label:
        mon, year = first_label.split(" ")
        month_no = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(mon) + 1
        first_due = "%s-%02d-%02d" % (year, month_no, LEASE_DUE_DAY)
    category = tracking.get("category") or ""
    status = "Late" if category == "Late" else ("NPL" if category.startswith("NPL") else "Current")
    return {
        "pmt_inc_vat": tracking.get("pmt"), "months": months, "term_original": None,
        "first_payment_date": first_due, "payment_status": status,
        "days_late": 45 if status == "Late" else (100 if status == "NPL" else 0),
        "dc_status": None, "npl_type": category if category.startswith("NPL") else None,
        "ptp_date": tracking.get("ptp_date"), "ptp_amount": tracking.get("ptp_amount"),
        "comment_th": tracking.get("note"), "bucket": None, "contract_signed": None,
    }
