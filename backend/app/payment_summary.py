"""The case's payment overview — every cycle of every contract, and what it adds up to.

Arina, 2026-09-14: the case page should show at a glance how much a customer has
paid across all their cycles and where each cycle stands, drawn as a picture rather
than printed as raw numbers. The interface may not add anything up (api.js:1-4), so
every count and total the picture needs is served from here.

Two sources, kept apart and never blended:

- The engine's schedule (`instalments`, read session-scoped) gives each cycle its due
  date, amount, paid and outstanding. For a sheet-migrated contract `paid_through` is
  derived as `due_by − missed` (book.py), so a cycle's paid figure is the sheet's
  statement walked back, not a record of cash. `indicative` is therefore always
  true — the same rule collection_kpi.due_month follows (L4 / R5-F16).
- The sheet's own month grid is counted separately under `sheet`, so the page can say
  "sheet says 19 paid cells" beside the engine's 22 instead of picking one.

The overdue figure is not re-derived here: it is the engine's `cumulative_arrears`,
passed in by the caller, so the overview can never disagree with the header.
"""
from decimal import Decimal
from collections import Counter

from . import cases as cases_domain
from . import journey

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
STATUSES = ("PAID", "OVERDUE", "UPCOMING", "NO_AMOUNT", "INFERRED_PAID", "SHEET_REPORTED_PAID", "UNCONFIRMED", "REJECTED")

PROVENANCE_TH = ("ยอดชำระแต่ละงวดมาจากตารางผ่อนชำระของแอป ซึ่งคำนวณย้อนจากชีต "
                 "(งวดที่ครบกำหนดแล้ว ลบงวดที่ชีตเขียนว่าค้าง) ไม่ใช่จากใบเสร็จรับเงินโดยตรง")
PROVENANCE_EN = ("each cycle's paid figure comes from the app's schedule, walked back from the sheet "
                 "(cycles due, minus the cycles the sheet marks late) — not from receipts")

PROVENANCE_PEAK_TH = "สถานะแต่ละงวดมาจากรายงานใบแจ้งหนี้ PEAK (จ่ายแล้ว / เกินกำหนด / รอชำระ) ตามสัญญาที่ยืนยันและเดือน/วันที่ของใบแจ้งหนี้"
PROVENANCE_PEAK_EN = "each cycle's status comes from the PEAK invoice report, by verified contract and invoice calendar period"
PROVENANCE_MIXED_TH = PROVENANCE_TH + " · งวดที่มีใบแจ้งหนี้ PEAK ใช้สถานะจาก PEAK"
PROVENANCE_MIXED_EN = PROVENANCE_EN + " · cycles with a PEAK invoice take PEAK's status"

PEAK_CYCLE_STATUS = {"PAID": "PAID", "OVERDUE": "OVERDUE", "SENT": "UPCOMING", "ISSUED": "UPCOMING",
                     "PARTIALLY_PAID": "OVERDUE"}


def _money(value):
    value = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(value.quantize(CENT))


def _kind(product, n):
    # Deck v20.0 CASH has one format: a deposit, then the whole balance (fixtures.make_cash_contract).
    if product == "CASH":
        return "DEPOSIT" if n == 1 else "BALANCE"
    return "INSTALMENT"


def _status(line, business_date, *, outstanding=None, total=None):
    outstanding = line.outstanding_amount if outstanding is None else outstanding
    total = line.total_amount if total is None else total
    if total <= 0:
        return "NO_AMOUNT"
    if outstanding <= 0:
        return "PAID"
    # arrears_block's own rule: overdue means due BEFORE the ledger date.
    if line.due_date < business_date:
        return "OVERDUE"
    return "UPCOMING"


def _sheet_count(month_cells):
    if not month_cells:
        return None
    paid = [m for m in month_cells if m and m.get("kind") == "PAID"]
    return {
        "paid_cells": len(paid),
        "paid_amount": _money(sum((Decimal(str(m["amount"])) for m in paid if m.get("amount")), ZERO)),
        "late_cells": sum(1 for m in month_cells if m and m.get("kind") == "LATE"),
        "cells": len(month_cells),
    }


def _breakdown(cycles):
    groups = {
        "deposit": [cycle for cycle in cycles if cycle["kind"] == "DEPOSIT"],
        "instalment": [cycle for cycle in cycles if cycle["kind"] != "DEPOSIT"],
    }
    breakdown = {}
    statuses = STATUSES if any(c.get("payment_evidence") for c in cycles) else STATUSES[:4]
    for name, rows in groups.items():
        counted = Counter(row["status"] for row in rows)
        counts = {status: counted[status] for status in statuses}
        unverified_paid = sum(1 for row in rows
                              if row["status"] in ("INFERRED_PAID", "SHEET_REPORTED_PAID")
                              or (row["status"] == "PAID" and row.get("source") == "SHEET_DERIVED"))
        display_paid = counts["PAID"] + counts.get("INFERRED_PAID", 0) + counts.get("SHEET_REPORTED_PAID", 0)
        breakdown[name] = {
            "display_paid_count": display_paid,
            "unverified_paid_count": unverified_paid,
            "display_remaining_count": len(rows) - display_paid,
            "count": len(rows),
            "counts": counts,
            "remaining_count": len(rows) - counts["PAID"],
        }
    return breakdown


def _active_lines(contract):
    """The schedule lines a cycle is built from — the same filter for_contract's cycle
    loop uses, so peak_cycles_for's out-of-range check never disagrees with it about
    how many cycles a contract actually has."""
    from .service_deferrals import ordered_regular
    return ordered_regular(cases_domain.contract_field_of(contract, "instalments") or [])


class PeakCycles(dict):
    """Per-read cycle matches with unplaced evidence; never stored on shared fixtures."""
    def __init__(self, unresolved):
        super().__init__()
        self.unplaced_details = unresolved


def peak_cycles_for(contract_uid, jstate):
    """Verified contract/calendar matches, retaining every effective document and
    exposing unmatched evidence separately without mutating shared fixtures."""
    from . import instalment_evidence as evidence
    found = journey.contract_by_uid(contract_uid)
    if not found:
        return {}, 0, None
    contract = found[1]
    own = evidence.evidence_invoices(contract_uid, jstate)
    lines = _active_lines(contract)
    groups, unresolved = evidence.group_invoices(contract, own, lines)
    cycles = PeakCycles(unresolved)
    from . import invoice_reviews
    reviews = invoice_reviews.decisions()
    rejected = [i for i in own if invoice_reviews.decorate(i, reviews)["review_status"] == "REJECTED"]
    rejected_groups = {}
    for inv in rejected:
        n = evidence.match_invoice(contract, inv, lines)[0]
        if n and n not in groups:
            rejected_groups.setdefault(n, []).append(inv)
    cycles.rejected = rejected_groups
    for n, invoices in groups.items():
        amount = sum((Decimal(inv["amount"]) for inv in invoices), ZERO)
        outstanding = sum((evidence.invoice_outstanding(inv) for inv in invoices), ZERO)
        dates = sorted({inv["due_date"] for inv in invoices if inv.get("due_date")})
        cycles[n] = {"status": "NO_AMOUNT" if amount <= 0 else "PAID" if outstanding <= 0 else
                     "OVERDUE" if any(PEAK_CYCLE_STATUS.get(inv["state"]) == "OVERDUE" for inv in invoices)
                     else "UPCOMING", "paid": _money(max(ZERO, amount - outstanding)),
                     "source": "PEAK" if any(i.get("source") == "PEAK_REPORT" for i in invoices) else "RECEIPT",
                     "amount": _money(amount), "outstanding": _money(outstanding),
                     "doc_no": invoices[0].get("peak_number"), "superseded_count": 0,
                     "invoices": [{"uid": i["uid"], "doc_no": i.get("peak_number"),
                                   "due_date": i.get("due_date"), "state": i["state"],
                                   "matching_method": i["matching_method"]} for i in invoices],
                     "due_date": dates[0] if dates else None, "due_dates": dates,
                     "open_due_date": min((inv["due_date"] for inv in invoices
                        if Decimal(inv.get("outstanding") or "0") > 0 and inv.get("due_date")), default=None),
                     "matching_method": invoices[0]["matching_method"],
                     "liability_verified": all(not i.get("receipt_only") for i in invoices)}
    as_of = next(((inv.get("peak_state_note_th") or "").rsplit(" ", 1)[-1] for inv in own), None)
    return cycles, len(unresolved), as_of if as_of and as_of != "—" else None


def for_contract(contract, business_date, overdue_amount, month_cells=None, peak_cycles=None):
    """One contract's cycles. A superseded line (a restructure's old schedule) is not
    a cycle — the engine follows is_active_regular, and so does this."""
    from . import instalment_evidence as evidence
    strict = evidence.required(contract)
    lines = _active_lines(contract)
    cycles = []
    instalment_n = 0
    for n, line in enumerate(lines, start=1):
        paid = line.paid_principal + line.paid_interest + line.paid_fee
        total = line.total_amount
        raw_outstanding = line.outstanding_amount
        outstanding = max(raw_outstanding, ZERO)
        kind = _kind(contract.product, n)
        if kind != "DEPOSIT":
            instalment_n += 1
        cycle = {
            "n": n, "kind": kind, "instalment_n": instalment_n if kind != "DEPOSIT" else None,
            "due_date": str(line.due_date),
            "amount": _money(total), "paid": _money(paid), "outstanding": _money(outstanding),
            "status": _status(line, business_date, outstanding=raw_outstanding, total=total),
            "partly_paid": paid > 0 and outstanding > 0,
            "source": "SHEET_DERIVED", "doc_no": None,
        }
        hit = (peak_cycles or {}).get(n)
        if hit:
            # A real invoice beats an inferred cycle: PEAK's status, paid and outstanding
            # replace the engine's for this slot, and the slot says so.
            cycle.update(status=hit["status"], paid=hit["paid"], outstanding=hit["outstanding"],
                         partly_paid=Decimal(hit["paid"]) > 0 and Decimal(hit["outstanding"]) > 0,
                         source=hit.get("source", "PEAK"), doc_no=hit.get("doc_no"))
        move = getattr(line, "service_deferral", None)
        if move and not strict:
            cycle.update(deferral=move, collection_status="DEFERRED",
                         status=_status(line, business_date), paid=_money(paid),
                         outstanding=_money(outstanding), partly_paid=paid > 0 and outstanding > 0)
        if strict:
            cycle["original_status"] = _status(line, business_date)
            evidence.cycle_evidence(contract, line, cycle, hit)
            if move:
                cycle.update(deferral=move, collection_status="DEFERRED", collection_due_date=str(line.due_date))
            if hit and Decimal(cycle["outstanding"]) > 0:
                due = str(line.due_date) if move else hit.get("open_due_date") or cycle["due_date"]
                cycle["status"] = "OVERDUE" if due and due < str(business_date) else "UPCOMING"
            if line.due_date > business_date:
                cycle["review_amount"] = "0.00"
        elif hit and hit.get("due_date") and not move:
            cycle["schedule_due_date"] = str(line.due_date)
            cycle["due_date"] = hit["due_date"]
            if Decimal(cycle["outstanding"]) > 0:
                cycle["status"] = "OVERDUE" if cycle["due_date"] < str(business_date) else "UPCOMING"
        if n in getattr(peak_cycles, "rejected", {}):
            cycle.update(status="REJECTED", review_status="REJECTED", collection_included=False,
                         paid="0.00", outstanding="0.00", review_amount="0.00", partly_paid=False)
        cycles.append(cycle)
    upcoming = min((c for c in cycles if c["status"] == "UPCOMING" and c["due_date"]),
                   key=lambda c: c["due_date"], default=None)
    unplaced = getattr(peak_cycles, "unplaced_details", []) if strict else []
    confirmed_unplaced = [inv for inv in unplaced if inv.get("contract_resolved")]
    unplaced_paid = sum((max(ZERO, Decimal(inv["amount"]) - Decimal(inv["outstanding"])) for inv in confirmed_unplaced), ZERO)
    unplaced_outstanding = sum((Decimal(inv["outstanding"]) for inv in confirmed_unplaced), ZERO)
    counted = Counter(c["status"] for c in cycles)
    counts = {s: counted[s] for s in (STATUSES if strict else STATUSES[:4])}
    cycle_paid = sum((Decimal(c["paid"]) for c in cycles), ZERO)
    cycle_outstanding = sum((Decimal(c["outstanding"]) for c in cycles), ZERO)
    return {
        "contract_uid": contract.uid,
        "product": contract.product,
        "cycle_count": len(cycles),
        "counts": counts,
        "breakdown": _breakdown(cycles),
        # F03/F14 / feedback-r2 TASK-102: the two figures the header prints are served
        # here, computed once — the client never subtracts.
        "paid_count": counts["PAID"],
        "deferred_count": sum(1 for c in cycles if c.get("deferral")),
        "contract_end": str(max((ln.due_date for ln in lines), default=contract.first_due)),
        "remaining_count": len(cycles) - counts["PAID"],
        "partly_paid_count": sum(1 for c in cycles if c["partly_paid"]),
        "contract_amount": _money(sum((ln.total_amount for ln in lines), ZERO)),
        # I1: summed per cycle, not per schedule line — a PEAK-overlaid cycle's already-
        # quantized paid/outstanding must show up here too, or the contract totals would
        # disagree with the very cycle table they sit above. `cycles` is one entry per
        # `lines` entry (same loop), so nothing here is dropped or counted twice.
        "matched_paid_amount": _money(cycle_paid),
        "unplaced_confirmed_paid": _money(unplaced_paid),
        "unplaced_confirmed_outstanding": _money(unplaced_outstanding),
        "paid_amount": _money(cycle_paid + unplaced_paid),
        "outstanding_amount": _money(cycle_outstanding + unplaced_outstanding),
        "review_amount": _money(sum((Decimal(c.get("review_amount", "0")) for c in cycles), ZERO)),
        "review_count": sum(1 for c in cycles if Decimal(c.get("review_amount", "0")) > 0 or
                            (c.get("liability_verified") is False and c["due_date"] <= str(business_date))),
        "schedule_confirmation": getattr(contract, "schedule_confirmation", None),
        "requires_schedule_confirmation": strict,
        "source_first_due": getattr(contract, "sheet_row", {}).get("first_payment_date") if strict else str(contract.first_due),
        "schedule_verified": bool(getattr(contract, "schedule_confirmation", None)) if strict else True,
        "schedule_conflict": ({"source_first_due": contract.sheet_row.get("first_payment_date"),
            "confirmed_first_due": str(contract.first_due)} if strict and getattr(contract, "schedule_confirmation", None)
            and contract.sheet_row.get("first_payment_date") != str(contract.first_due) else None),
        "unplaced_peak_details": unplaced,
        "overdue_amount": _money(overdue_amount),
        "next_due": ({"n": upcoming["n"], "due_date": upcoming["due_date"], "amount": upcoming["amount"]}
                     if upcoming else None),
        "sheet": _sheet_count(month_cells),
        "cycles": cycles,
        "source": "PEAK" if any(c["source"] == "PEAK" for c in cycles) else
                  "RECEIPT" if any(c["source"] == "RECEIPT" for c in cycles) else "SHEET_DERIVED",
        "peak": ({"invoices": sum(len(v.get("invoices") or [None]) for v in peak_cycles.values()), "report_as_of": None,
                  "superseded_invoices": sum(v.get("superseded_count", 0) for v in peak_cycles.values())}
                 if peak_cycles else None),
        "unplaced_peak_invoices": 0,
    }


def review_summary(contract, business_date, peak_cycles=None):
    """The four review fields used on list rows, without materializing cycle DTOs.

    Full case detail still uses ``for_contract``. Review money follows its exact
    per-cycle quantization and evidence rules: unconfirmed past schedule amounts,
    receipt-only liability shortfalls, future suppression and rejected documents.
    No invoice/cycle is omitted from the case's full financial overview.
    """
    from . import instalment_evidence as evidence
    strict = evidence.required(contract)
    if not strict:
        return {"review_amount": "0.00", "review_count": 0,
                "schedule_verified": True, "unplaced_peak_details": []}
    total, count = ZERO, 0
    rejected = getattr(peak_cycles, "rejected", {})
    bd = str(business_date)
    for n, line in enumerate(_active_lines(contract), 1):
        hit = (peak_cycles or {}).get(n)
        liability_unverified = bool(hit and hit.get("liability_verified", True) is False)
        due = hit["due_date"] if hit else str(line.due_date)
        amount = ZERO
        if line.due_date <= business_date:
            if not hit:
                amount = line.total_amount.quantize(CENT)
            elif liability_unverified:
                amount = max(ZERO, line.total_amount - Decimal(hit["paid"])).quantize(CENT)
        if n in rejected:
            amount = ZERO
        total += amount
        if amount > ZERO or (liability_unverified and due <= bd):
            count += 1
    return {"review_amount": _money(total), "review_count": count,
            "schedule_verified": bool(getattr(contract, "schedule_confirmation", None)),
            "unplaced_peak_details": getattr(peak_cycles, "unplaced_details", [])}


def build(entries, business_date):
    """The case's overview from its per-contract entries, with the totals summed here."""
    totals = {
        "review_amount": _money(sum((Decimal(e.get("review_amount", "0")) for e in entries), ZERO)),
        "review_count": sum(e.get("review_count", 0) for e in entries),
        "cycle_count": sum(e["cycle_count"] for e in entries),
        "counts": {s: sum(e["counts"].get(s, 0) for e in entries)
                   for s in (STATUSES if any(c.get("payment_evidence") for e in entries for c in e["cycles"]) else STATUSES[:4])},
        "contract_amount": _money(sum((Decimal(e["contract_amount"]) for e in entries), ZERO)),
        "paid_amount": _money(sum((Decimal(e["paid_amount"]) for e in entries), ZERO)),
        "outstanding_amount": _money(sum((Decimal(e["outstanding_amount"]) for e in entries), ZERO)),
        "overdue_amount": _money(sum((Decimal(e["overdue_amount"]) for e in entries), ZERO)),
    }
    # F03/F14 / feedback-r2 TASK-102: the totals carry the same two figures each
    # contract serves, summed here beside them.
    totals["paid_count"] = totals["counts"]["PAID"]
    totals["remaining_count"] = totals["cycle_count"] - totals["counts"]["PAID"]
    totals["deferred_count"] = sum(e.get("deferred_count", 0) for e in entries)
    all_cycles = [cycle for entry in entries for cycle in entry["cycles"]]
    totals["breakdown"] = _breakdown(all_cycles)
    due_cycles = [c for e in entries for c in e["cycles"] if c["due_date"] <= str(business_date)]
    all_peak = bool(due_cycles) and all(c["source"] == "PEAK" for c in due_cycles)
    any_peak = any(c["source"] == "PEAK" for e in entries for c in e["cycles"])
    return {
        "contracts": entries,
        "totals": totals,
        "summed_across_contracts": len(entries) > 1,
        "business_date": str(business_date),
        "indicative": not all_peak,
        "provenance_th": ("ยอดชำระและยอดค้างยืนยันนับจาก PEAK หรือใบรับเงินที่ยืนยันแล้วเท่านั้น ชีตระบุว่าจ่ายและงวดอนุมานแสดงแยก และไม่รวมในยอดยืนยัน"
                          if any(e.get("requires_schedule_confirmation") for e in entries) else
                          PROVENANCE_PEAK_TH if all_peak else (PROVENANCE_MIXED_TH if any_peak else PROVENANCE_TH)),
        "provenance_en": ("Confirmed totals use PEAK or verified receipts only. Sheet-reported and inferred payments are shown separately and excluded from confirmed totals."
                          if any(e.get("requires_schedule_confirmation") for e in entries) else
                          PROVENANCE_PEAK_EN if all_peak else (PROVENANCE_MIXED_EN if any_peak else PROVENANCE_EN)),
    }
