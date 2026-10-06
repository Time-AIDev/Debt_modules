"""Invoice-backed instalment display, separate from the contract debt ledger."""
from decimal import Decimal, InvalidOperation

from . import instalment_evidence

ZERO = Decimal("0.00")
PAID_STATUSES = {"PAID", "INFERRED_PAID", "SHEET_REPORTED_PAID"}
OMIT_KINDS = {"DEPOSIT", "DOWN_PAYMENT", "FEE", "LATE_FEE", "PENALTY"}
OMIT_STATES = {"DRAFT", "CANCELLED", "VOID"}


def _money(value):
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _invoices(contract, state):
    from . import invoice_reviews
    seen = set()
    rows = []
    for invoice in instalment_evidence.evidence_invoices(contract.uid, state):
        if (invoice.get("source") != "PEAK_REPORT" or invoice.get("kind") in OMIT_KINDS
                or invoice.get("state") in OMIT_STATES or invoice.get("contract_resolved") is False
                or invoice.get("liability_verified") is False or invoice.get("receipt_only")):
            continue
        key = invoice_reviews.identity(invoice)
        if key in seen:
            continue
        seen.add(key)
        rows.append(invoice)
    return sorted(rows, key=lambda invoice: (invoice.get("due_date") or "9999", invoice.get("issued_on") or "", invoice["uid"]))


def _invoice_cycle(invoice, n, business_date):
    amount = Decimal(invoice["amount"])
    outstanding = instalment_evidence.invoice_outstanding(invoice)
    if amount <= 0 or (invoice.get("state") == "PAID" and outstanding > 0):
        status = "UNCONFIRMED"
    elif outstanding <= 0:
        status = "PAID"
    elif (invoice.get("due_date") or "9999") < str(business_date):
        status = "OVERDUE"
    else:
        status = "UPCOMING"
    from . import invoice_reviews
    review = invoice_reviews.decorate(invoice)
    if review["review_status"] == "REJECTED":
        status = "REJECTED"
    return {"n": n, "instalment_n": n, "kind": "BALANCE", "status": status,
            "due_date": invoice.get("due_date"), "amount": _money(amount),
            "paid": _money(max(ZERO, amount - outstanding)), "outstanding": _money(outstanding),
            "partly_paid": ZERO < outstanding < amount, "source": "PEAK",
            "doc_no": invoice.get("peak_number"), "invoice_uid": invoice["uid"],
            "review_status": review["review_status"]}


def _sheet_cycles(contract):
    cells = getattr(contract, "month_cells", None)
    if cells is None:
        cells = (getattr(contract, "sheet_row", None) or {}).get("months") or []
    rows = []
    for cell in cells:
        if cell and cell.get("kind") == "CLOSED":
            break
        if not cell:
            continue
        status = {"PAID": "UNCONFIRMED", "LATE": "OVERDUE",
                  "NOT_DUE": "UPCOMING"}.get(cell.get("kind"), "UNCONFIRMED")
        n = len(rows) + 1
        rows.append({"n": n, "instalment_n": n, "kind": "BALANCE", "status": status,
                     "due_date": None, "amount": cell.get("amount"), "paid": None,
                     "outstanding": None, "partly_paid": False, "source": "SHEET_DERIVED",
                     "doc_no": None, "invoice_uid": None})
    return rows


def _without_sheet_deposit(contract, invoices, sheet_count):
    """PEAK labels every CASH document as balance; identify a distinct paid DP only when the sheet resolves it."""
    if not sheet_count or len(invoices) != sheet_count + 1:
        return invoices
    deposit = (getattr(contract, "sheet_row", None) or {}).get("dp_inc_vat")
    if deposit in (None, ""):
        return invoices
    try:
        deposit_amount = Decimal(str(deposit))
    except InvalidOperation:
        return invoices
    candidates = [invoice for invoice in invoices
                  if Decimal(invoice["amount"]) == deposit_amount
                  and invoice.get("state") == "PAID"
                  and instalment_evidence.invoice_outstanding(invoice) == ZERO
                  and invoice.get("due_date")
                  and all(invoice["due_date"] < other.get("due_date", "")
                          for other in invoices if other is not invoice)]
    return [invoice for invoice in invoices if invoice is not candidates[0]] if len(candidates) == 1 else invoices


def _contract(contract, entry, state, business_date):
    if contract.product != "CASH":
        cycles = [dict(cycle) for cycle in entry["cycles"] if cycle["kind"] != "DEPOSIT"]
        source = entry["source"]
        peak_outstanding = None
    else:
        sheet_cycles = _sheet_cycles(contract)
        invoices = _without_sheet_deposit(contract, _invoices(contract, state), len(sheet_cycles))
        if invoices and (not sheet_cycles or len(invoices) == len(sheet_cycles)):
            cycles = [_invoice_cycle(inv, n, business_date) for n, inv in enumerate(invoices, 1)]
            source = "PEAK_REPORT"
        elif sheet_cycles:
            cycles = sheet_cycles
            source = "SHEET"
            # A documented month index is a match; an ordinal guess is not.
            for inv in invoices:
                n = inv.get("month_index")
                if isinstance(n, int) and 1 <= n <= len(cycles):
                    cycles[n - 1] = _invoice_cycle(inv, n, business_date)
                    source = "MIXED"
        else:
            cycles = [dict(cycle, status="UNCONFIRMED") if cycle["status"] in PAID_STATUSES
                      else dict(cycle) for cycle in entry["cycles"] if cycle["kind"] != "DEPOSIT"]
            source = entry["source"]
        peak_outstanding = _money(sum((instalment_evidence.invoice_outstanding(inv) for inv in invoices), ZERO)) if invoices else None
    return {"contract_uid": contract.uid, "source": source, "cycles": cycles,
            "peak_outstanding": peak_outstanding}


def build(contracts, entries, state, business_date, contract_outstanding):
    displayed = [_contract(contract, entry, state, business_date)
                 for contract, entry in zip(contracts, entries)]
    cycles = [cycle for item in displayed for cycle in item["cycles"]]
    paid = sum(cycle["status"] in PAID_STATUSES for cycle in cycles)
    peak_balances = [item["peak_outstanding"] for item in displayed if item["peak_outstanding"] is not None]
    peak_only = bool(displayed) and all(item["source"] == "PEAK_REPORT" for item in displayed)
    provenance_th = ("จำนวนและสถานะงวดจากใบแจ้งหนี้ PEAK ที่ยืนยันสัญญา; ยอดตามสัญญาแสดงแยก"
                     if peak_only else "จำนวนงวดจากตารางสัญญาและชีต; งวดที่มีหลักฐาน PEAK ใช้สถานะ PEAK")
    provenance_en = ("Instalment counts and status from contract-verified PEAK invoices; contract balance is separate"
                     if peak_only else "Instalment counts from contract and sheet; matched PEAK evidence supplies status")
    return {"contracts": displayed, "total_count": len(cycles), "paid_count": paid,
            "remaining_count": len(cycles) - paid,
            "overdue_count": sum(cycle["status"] == "OVERDUE" for cycle in cycles),
            "upcoming_count": sum(cycle["status"] == "UPCOMING" for cycle in cycles),
            "unconfirmed_count": sum(cycle["status"] == "UNCONFIRMED" for cycle in cycles),
            "unverified_paid_count": sum(cycle["status"] in ("INFERRED_PAID", "SHEET_REPORTED_PAID")
                                         or (cycle["status"] == "PAID" and cycle.get("source") == "SHEET_DERIVED")
                                         for cycle in cycles),
            "contract_outstanding": _money(contract_outstanding) if contract_outstanding is not None else None,
            "peak_outstanding": _money(sum((Decimal(value) for value in peak_balances), ZERO)) if peak_balances else None,
            "peak_balance_complete": peak_only,
            "provenance_th": provenance_th, "provenance_en": provenance_en}
