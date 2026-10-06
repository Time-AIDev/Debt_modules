"""Evidence matching by verified contract and calendar period, never ordinal alone."""
from datetime import date
from decimal import Decimal
import re

ZERO = Decimal('0.00')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def period(value):
    if not value:
        return None
    if isinstance(value, date):
        return f'{value.year:04d}-{value.month:02d}'
    raw = str(value)
    if re.match(r'^\d{4}-\d{2}(?:-|$)', raw):
        try:
            year, month = map(int, raw[:7].split('-'))
            return f'{year:04d}-{month:02d}' if 1 <= month <= 12 else None
        except ValueError:
            return None
    match = re.fullmatch(r'([A-Z][a-z]{2}) (\d{4})', raw)
    if match and match[1] in MONTHS:
        return f'{match[2]}-{MONTHS.index(match[1]) + 1:02d}'
    return None


def required(contract):
    return bool(getattr(contract, 'requires_schedule_confirmation', False))


def match_invoice(contract, inv, lines):
    if not required(contract):
        n = inv.get('month_index')
        if n and 1 <= n <= len(lines):
            return n, 'LEGACY_CYCLE'
    if inv.get('contract_resolved') is False:
        return None, 'CONTRACT_AMBIGUOUS'
    if inv.get('service_month_conflict'):
        return None, 'SERVICE_PERIOD_CONFLICT'
    service_month = inv.get('service_month')
    target = period(service_month or inv.get('due_date'))
    if not target:
        return None, 'PERIOD_MISSING'
    from . import request_context
    cache = request_context.reads()
    key = ('instalment_evidence.period_index', id(lines), len(lines))
    hit = cache.get(key) if cache is not None else None
    if hit is None or hit[0] is not lines:
        index = {}
        for n, line in enumerate(lines, 1):
            index.setdefault(period(getattr(line, 'service_original_due_date', line.due_date)), []).append((n, line))
        hit = (lines, index)
        if cache is not None: cache[key] = hit
    candidates = hit[1].get(target, [])
    if len(candidates) != 1:
        return None, 'PERIOD_AMBIGUOUS' if candidates else 'OUTSIDE_SCHEDULE'
    n, _line = candidates[0]
    mark = inv.get('month_index')
    if mark is not None and mark != n:
        return None, 'CYCLE_CONFLICT'
    return n, 'SERVICE_MONTH' if service_month else 'DUE_MONTH'


def group_invoices(contract, invoices, lines):
    from . import invoice_reviews
    reviews = invoice_reviews.decisions()
    groups, unresolved, seen = {}, [], set()
    for inv in invoices:
        if inv.get('state') in ('DRAFT', 'CANCELLED', 'VOID'):
            continue
        if invoice_reviews.decorate(inv, reviews)['review_status'] == 'REJECTED':
            continue
        key = invoice_reviews.identity(inv)
        if key in seen:
            continue
        seen.add(key)
        n, method = match_invoice(contract, inv, lines)
        if n is None:
            unresolved.append({'uid': inv['uid'], 'doc_no': inv.get('peak_number'),
                               'due_date': inv.get('due_date'), 'reason': method,
                               'amount': inv['amount'], 'outstanding': str(invoice_outstanding(inv)),
                               'contract_resolved': inv.get('contract_resolved', True),
                               'evidence_source': inv.get('source'), 'liability_verified': not inv.get('receipt_only', False)})
        else:
            groups.setdefault(n, []).append({**inv, 'matching_method': method})
    return groups, unresolved


def sheet_for(contract, due):
    if not getattr(contract, 'schedule_confirmation', None):
        return None
    matches = [cell for cell in getattr(contract, 'calendar_months', [])
               if period(cell.get('period') or cell.get('month')) == period(due)]
    return matches[0] if len(matches) == 1 else None


def cycle_evidence(contract, line, cycle, hit):
    cycle['schedule_due_date'] = str(line.due_date)
    cycle['payment_evidence'] = 'CONFIRMED' if hit else 'UNCONFIRMED'
    cycle['review_amount'] = '0.00'
    if hit:
        cycle.update(due_date=hit['due_date'], peak_due_dates=hit['due_dates'],
                     invoices=hit['invoices'], matching_method=hit['matching_method'],
                     amount=hit['amount'], payment_evidence='CONFIRMED',
                     liability_verified=hit.get('liability_verified', True))
        if not cycle['liability_verified']:
            cycle.update(status='UNCONFIRMED', amount=str(line.total_amount.quantize(Decimal('0.01'))),
                         partly_paid=False, review_amount=str(max(ZERO, line.total_amount - Decimal(hit['paid'])).quantize(Decimal('0.01'))))
        return
    reported = sheet_for(contract, line.due_date)
    if reported:
        cycle['sheet_evidence'] = reported
    paid = line.paid_principal + line.paid_interest + line.paid_fee
    evidence = ('SHEET_REPORTED_PAID' if reported and (reported.get('cell') or {}).get('kind') == 'PAID'
                else 'INFERRED_PAID' if paid > 0 else 'UNCONFIRMED')
    cycle.update(payment_evidence=evidence, paid='0.00', outstanding='0.00', partly_paid=False,
                 review_amount=cycle['amount'],
                 status=evidence if evidence != 'UNCONFIRMED' else 'UNCONFIRMED')
    # Future dates are still a schedule forecast, not a receivable with evidence.
    if cycle.get('original_status') == 'UPCOMING':
        cycle['status'] = 'UPCOMING'


def collection_lines(contract, jstate, lines):
    """Verified invoice liabilities survive an unplaced cycle; no assumed payment."""
    from .money.models import Instalment
    from . import invoice_reviews
    reviews = invoice_reviews.decisions()
    own = evidence_invoices(contract.uid, jstate)
    result, seen = [], set()
    for inv in own:
        key = invoice_reviews.identity(inv)
        if invoice_reviews.decorate(inv, reviews)['review_status'] == 'REJECTED':
            continue
        if key in seen or inv.get('receipt_only') or inv.get('contract_resolved') is False or inv.get('state') in ('DRAFT', 'CANCELLED', 'VOID'):
            continue
        seen.add(key)
        if inv.get('due_date'):
            n, _ = match_invoice(contract, inv, lines)
            if required(contract) and n is None:
                continue
            line = lines[n - 1] if n else None
            due = line.due_date if line and getattr(line, 'service_deferral', None) else date.fromisoformat(inv['due_date'])
            result.append(Instalment(due_date=due, category='REGULAR',
                                     principal_amount=invoice_outstanding(inv), interest_amount=ZERO))
    return result


def evidence_invoices(contract_uid, jstate):
    from . import main
    invoices = main.rows_for(jstate.invoices, "contract_uid", {contract_uid})
    receipts = main.rows_for(getattr(jstate, "receipts", {}), "contract_uid", {contract_uid})
    by_invoice, seen = {}, set()
    reported_refs = {r.get("ref") for r in receipts
                     if r.get("source") in ("PEAK_REPORT", "PEAK_RECEIPT") and r.get("ref")}
    for receipt in receipts:
        if receipt.get("is_allocated") is False or receipt.get("matched") not in ("MATCHED", "FULL", "PARTIAL") or receipt.get("source") in (
                "PEAK_REPORT", "PEAK_RECEIPT", "SHEET"):
            continue
        key = receipt.get("ref") or receipt.get("uid")
        if not key or key in seen or key in reported_refs:
            continue
        seen.add(key)
        by_invoice.setdefault(receipt.get("invoice_uid"), []).append(receipt)
    result = []
    for inv in invoices:
        manual = by_invoice.get(inv["uid"], [])
        if inv.get("source") != "PEAK_REPORT" and not manual:
            continue
        row = dict(inv, contract_resolved=inv.get("contract_resolved", True))
        amount = Decimal(inv["amount"])
        manual_paid = sum((Decimal(r["amount"]) for r in manual), ZERO)
        if inv.get("source") == "PEAK_REPORT":
            reported_paid = max(ZERO, amount - invoice_outstanding(inv))
            as_of = inv.get("report_as_of")
            later = sum((Decimal(r["amount"]) for r in manual
                         if as_of and (r.get("received_on") or "") > as_of), ZERO)
            # Older/undated manual receipts may already be in the report. Never
            # add those to report cash a second time without reconciliation.
            paid = max(reported_paid, manual_paid - later) + later
        else:
            row.update(month_index=None, contract_resolved=True, source="RECEIPT",
                       receipt_only=True, source_invoice_amount=inv["amount"], amount=str(manual_paid))
            amount = paid = manual_paid
        row["outstanding"] = str(max(ZERO, amount - paid))
        result.append(row)
    return result


def service_period(lines):
    """Read explicit service-month labels, retaining conflicts for review."""
    import calendar
    found = set()
    thai = ('มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
            'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม')
    short = ('ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.')
    names = {name.lower(): n for n in range(1, 13)
             for name in (MONTHS[n - 1], calendar.month_name[n], thai[n - 1], short[n - 1])}
    pattern = '(' + '|'.join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r')\s+(20\d{2}|25\d{2})'
    for line in lines:
        raw = ' '.join(str(line.get(k) or '') for k in ('description', 'product_name'))
        if not re.search(r'service\s+month|billing\s+period|period|เดือน|งวด|M\s*\d+\s*/\s*\d+', raw, re.I):
            continue
        for mon, year in re.findall(pattern, raw, re.I):
            year = int(year) - (543 if int(year) >= 2500 else 0)
            found.add(f'{year:04d}-{names[mon.lower()]:02d}')
        for year, mon in re.findall(r'(?:service\s+month|period|งวดเดือน|เดือน)\s*[:\-]?\s*(20\d{2})-(\d{2})(?!-\d)', raw, re.I):
            if 1 <= int(mon) <= 12:
                found.add(f'{int(year):04d}-{int(mon):02d}')
    return (next(iter(found)) if len(found) == 1 else None), len(found) > 1


def invoice_outstanding(inv):
    value = inv.get('outstanding')
    return max(ZERO, Decimal(value if value is not None else '0' if inv['state'] == 'PAID' else inv['amount']))


def fully_reviewed(contract, jstate, lines):
    groups, unresolved = group_invoices(contract, evidence_invoices(contract.uid, jstate), lines)
    return (bool(lines) and len(groups) == len(lines) and not unresolved
            and all(not inv.get("receipt_only") for rows in groups.values() for inv in rows))


def annotate_invoices(customer, jstate, invoices):
    from . import payment_summary
    strict = {k.uid: k for k in customer.contracts}
    evidenced = {inv['uid']: inv for uid in strict for inv in evidence_invoices(uid, jstate)}
    schedules = {uid: payment_summary._active_lines(k) for uid, k in strict.items()}
    result = []
    for inv in invoices:
        contract = strict.get(inv.get('contract_uid'))
        if contract is None:
            result.append(inv)
            continue
        proof = evidenced.get(inv['uid']) if required(contract) else inv
        confirmed = proof is not None
        n, method = match_invoice(contract, proof, schedules[contract.uid]) if confirmed else (None, 'EVIDENCE_UNCONFIRMED')
        result.append(dict(inv, outstanding=str(invoice_outstanding(proof)) if proof and not proof.get('receipt_only') else inv.get('outstanding'),
                           payment_evidence='CONFIRMED' if confirmed else 'UNCONFIRMED',
                           schedule_verified=bool(n),
                           matching_method=method if n else None, contract_cycle=n,
                           unmatched_reason=None if n else method,
                           evidence_source=proof.get('source') if proof else inv.get('source'),
                           liability_verified=bool(proof and not proof.get('receipt_only')),
                           verified_payment=proof['amount'] if proof and proof.get('receipt_only') else None,
                           schedule_due_date=str(schedules[contract.uid][n - 1].due_date) if n else None,
                           peak_due_date=inv.get('due_date') if inv.get('source') == 'PEAK_REPORT' else None))
    return result
