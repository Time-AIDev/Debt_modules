"""NPV read projection from verified cycle balances; no component/money mutation."""
from datetime import date
from decimal import Decimal, InvalidOperation

from . import errors


def pending(reason):
    return errors.Problem("npv_payment_evidence_unconfirmed", 409, "NPV needs reviewed payment evidence",
                          reason, "ต้องตรวจสอบสัญญาและหลักฐานรับชำระก่อนประเมินยอด NPV",
                          "DEBT-NPV-0409")


def outstanding_by_cycle(lines, cycles, *, as_of: date, allocation_order=None, unresolved=0):
    """Future uninvoiced obligations remain; historical unknown cash is refused."""
    if unresolved:
        raise pending("Some payment evidence cannot be assigned to a verified contract cycle")
    result = {}
    for n, line in enumerate(lines, 1):
        evidence = cycles.get(n)
        if evidence is None:
            if line.due_date < as_of:
                raise pending("A past-due cycle has no verified invoice/payment balance")
            result[n] = line.outstanding_amount
            continue
        try:
            amount = Decimal(str(evidence.get("amount")))
            outstanding = Decimal(str(evidence.get("outstanding")))
        except (InvalidOperation, ValueError, TypeError):
            raise pending("A verified cycle balance is unreadable") from None
        if (not evidence.get("liability_verified") or not amount.is_finite() or
                not outstanding.is_finite() or amount != line.total_amount or
                outstanding < 0 or outstanding > amount):
            raise pending("Invoice liability or amount does not match the contractual cycle")
        if 0 < outstanding < amount and not allocation_order:
            # Keep the existing OD-02 refusal; do not invent principal/interest order.
            raise errors.allocation_rule_pending()
        result[n] = outstanding
    return result
