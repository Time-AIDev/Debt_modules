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

from . import cases as cases_domain
from . import journey

ZERO = Decimal("0.00")
STATUSES = ("PAID", "OVERDUE", "UPCOMING", "NO_AMOUNT")

PROVENANCE_TH = ("ยอดชำระแต่ละงวดมาจากตารางผ่อนชำระของแอป ซึ่งคำนวณย้อนจากชีต "
                 "(งวดที่ครบกำหนดแล้ว ลบงวดที่ชีตเขียนว่าค้าง) ไม่ใช่จากใบเสร็จรับเงินโดยตรง")
PROVENANCE_EN = ("each cycle's paid figure comes from the app's schedule, walked back from the sheet "
                 "(cycles due, minus the cycles the sheet marks late) — not from receipts")

PROVENANCE_PEAK_TH = "สถานะแต่ละงวดมาจากรายงานใบแจ้งหนี้ PEAK (จ่ายแล้ว / เกินกำหนด / รอชำระ) ตามเลขงวด M n/N บนใบแจ้งหนี้"
PROVENANCE_PEAK_EN = "each cycle's status comes from the PEAK invoice report, by the M n/N cycle mark on the invoice"
PROVENANCE_MIXED_TH = PROVENANCE_TH + " · งวดที่มีใบแจ้งหนี้ PEAK ใช้สถานะจาก PEAK"
PROVENANCE_MIXED_EN = PROVENANCE_EN + " · cycles with a PEAK invoice take PEAK's status"

PEAK_CYCLE_STATUS = {"PAID": "PAID", "OVERDUE": "OVERDUE", "SENT": "UPCOMING", "ISSUED": "UPCOMING",
                     "PARTIALLY_PAID": "OVERDUE"}


def _money(value):
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _kind(product, n):
    # Deck v20.0 CASH has one format: a deposit, then the whole balance (fixtures.make_cash_contract).
    if product == "CASH":
        return "DEPOSIT" if n == 1 else "BALANCE"
    return "INSTALMENT"


def _status(line, business_date):
    outstanding = line.outstanding_amount
    if line.total_amount <= 0:
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
    for name, rows in groups.items():
        counts = {status: sum(1 for row in rows if row["status"] == status) for status in STATUSES}
        breakdown[name] = {
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


def peak_cycles_for(contract_uid, jstate):
    """This session's PEAK invoices for one contract, keyed by cycle. An invoice with no
    cycle mark, below cycle 1, or past the contract's own last cycle, is counted as
    unplaced, never dropped onto a slot. Two invoices landing on the same cycle: the one
    issued latest wins (ties by the greater doc_no); the one it beats is superseded, not
    silently lost — each winning cycle carries how many it beat."""
    found = journey.contract_by_uid(contract_uid)
    cycle_count = len(_active_lines(found[1])) if found else None
    by_cycle = {}
    unplaced = 0
    as_of = None
    for inv in jstate.invoices.values():
        if inv["contract_uid"] != contract_uid or inv.get("source") != "PEAK_REPORT":
            continue
        # journey.py's _seed_peak_invoices stamps this note from the template
        # "จากรายงานใบแจ้งหนี้ PEAK ณ %s" — an edit to that template must change this parse too.
        as_of = as_of or (inv.get("peak_state_note_th") or "").rsplit(" ", 1)[-1]
        n = inv.get("month_index")
        if not n or n < 1 or (cycle_count is not None and n > cycle_count):
            unplaced += 1
            continue
        by_cycle.setdefault(n, []).append(inv)
    cycles = {}
    for n, invs in by_cycle.items():
        winner = max(invs, key=lambda i: (i.get("issued_on") or "", i.get("peak_number") or ""))
        outstanding = Decimal(winner.get("outstanding") or winner["amount"])
        cycles[n] = {"status": PEAK_CYCLE_STATUS.get(winner["state"], "UPCOMING"),
                     "paid": _money(Decimal(winner["amount"]) - outstanding), "outstanding": _money(outstanding),
                     "doc_no": winner.get("peak_number"), "superseded_count": len(invs) - 1}
    return cycles, unplaced, (as_of if as_of and as_of != "—" else None)


def for_contract(contract, business_date, overdue_amount, month_cells=None, peak_cycles=None):
    """One contract's cycles. A superseded line (a restructure's old schedule) is not
    a cycle — the engine follows is_active_regular, and so does this."""
    lines = _active_lines(contract)
    cycles = []
    instalment_n = 0
    for n, line in enumerate(lines, start=1):
        paid = line.paid_principal + line.paid_interest + line.paid_fee
        outstanding = max(line.outstanding_amount, ZERO)
        kind = _kind(contract.product, n)
        if kind != "DEPOSIT":
            instalment_n += 1
        cycle = {
            "n": n, "kind": kind, "instalment_n": instalment_n if kind != "DEPOSIT" else None,
            "due_date": str(line.due_date),
            "amount": _money(line.total_amount), "paid": _money(paid), "outstanding": _money(outstanding),
            "status": _status(line, business_date), "partly_paid": paid > 0 and outstanding > 0,
            "source": "SHEET_DERIVED", "doc_no": None,
        }
        hit = (peak_cycles or {}).get(n)
        if hit:
            # A real invoice beats an inferred cycle: PEAK's status, paid and outstanding
            # replace the engine's for this slot, and the slot says so.
            cycle.update(status=hit["status"], paid=hit["paid"], outstanding=hit["outstanding"],
                         partly_paid=Decimal(hit["paid"]) > 0 and Decimal(hit["outstanding"]) > 0,
                         source="PEAK", doc_no=hit.get("doc_no"))
        move = getattr(line, "service_deferral", None)
        if move:
            cycle.update(deferral=move, collection_status="DEFERRED",
                         status=_status(line, business_date), paid=_money(paid),
                         outstanding=_money(outstanding), partly_paid=paid > 0 and outstanding > 0)
        cycles.append(cycle)
    upcoming = min((c for c in cycles if c["status"] == "UPCOMING"),
                   key=lambda c: c["due_date"], default=None)
    counts = {s: sum(1 for c in cycles if c["status"] == s) for s in STATUSES}
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
        "paid_amount": _money(sum((Decimal(c["paid"]) for c in cycles), ZERO)),
        "outstanding_amount": _money(sum((Decimal(c["outstanding"]) for c in cycles), ZERO)),
        "overdue_amount": _money(overdue_amount),
        "next_due": ({"n": upcoming["n"], "due_date": upcoming["due_date"], "amount": upcoming["amount"]}
                     if upcoming else None),
        "sheet": _sheet_count(month_cells),
        "cycles": cycles,
        "source": "PEAK" if any(c["source"] == "PEAK" for c in cycles) else "SHEET_DERIVED",
        "peak": ({"invoices": len(peak_cycles), "report_as_of": None,
                  "superseded_invoices": sum(v.get("superseded_count", 0) for v in peak_cycles.values())}
                 if peak_cycles else None),
        "unplaced_peak_invoices": 0,
    }


def build(entries, business_date):
    """The case's overview from its per-contract entries, with the totals summed here."""
    totals = {
        "cycle_count": sum(e["cycle_count"] for e in entries),
        "counts": {s: sum(e["counts"][s] for e in entries) for s in STATUSES},
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
        "provenance_th": PROVENANCE_PEAK_TH if all_peak else (PROVENANCE_MIXED_TH if any_peak else PROVENANCE_TH),
        "provenance_en": PROVENANCE_PEAK_EN if all_peak else (PROVENANCE_MIXED_EN if any_peak else PROVENANCE_EN),
    }
