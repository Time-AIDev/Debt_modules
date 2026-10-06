"""Fast customer lookup and compact invoice previews for the command palette."""
from decimal import Decimal

from fastapi import APIRouter, Query

from .. import customer_search, data_epoch, errors, journey


router = APIRouter()


@router.get("/v1/customers/search")
def search_customers(q: str = Query(..., min_length=1, max_length=100),
                     limit: int = Query(default=6, ge=1, le=10)):
    query = q.strip()
    if not query:
        raise errors.validation_failed([{
            "pointer": "/q", "code": "required", "message": "Search text is required.",
            "message_th": "กรุณาพิมพ์คำค้นหา",
        }])
    from .. import main
    items = customer_search.search(
        main.CUSTOMERS, main.IDENTITIES, data_epoch.current(), query, limit,
        officer_overrides=customer_search.officer_overrides(),
    )
    return {"items": items, "meta": {"total": len(items), "limit": limit}}


@router.get("/v1/customers/{customer_uid}/invoice-statuses")
def invoice_statuses(customer_uid: str, limit: int = Query(default=5, ge=1, le=20),
                     include_all: bool = False):
    customer = journey.customer_by_uid(customer_uid)
    if customer is None:
        raise errors.not_found("customer")
    contract_uids = {contract.uid for contract in customer.contracts}
    invoices = [invoice for invoice in journey.for_current().invoices.values()
                if invoice.get("customer_uid") == customer_uid or invoice.get("contract_uid") in contract_uids]
    from .. import invoice_reviews
    from .today import _with_peak_state, _resolve_amended_due
    invoices = invoice_reviews.project(customer, journey.for_current(),
        [_resolve_amended_due(_with_peak_state(i)) for i in invoices])
    due_totals = invoice_reviews.totals(invoices)
    invoices = [i for i in invoices if i["invoice_visible"]]
    invoices.sort(key=journey.invoice_collection_sort_key)

    def compact(invoice):
        # The PEAK document store, not the invoice's creation-time copy, owns the
        # current accounting state. Reuse the case projection so both views agree.
        from .today import _with_peak_state
        invoice = _with_peak_state(invoice)
        return {
            "uid": invoice["uid"],
            "reference": invoice.get("peak_number") or invoice.get("peak_ref") or invoice["uid"],
            "kind": invoice.get("kind"),
            "month_index": invoice.get("month_index"),
            "due_date": invoice.get("due_date"),
            "state": invoice.get("state"),
            "peak_state": invoice.get("peak_state"),
            "amount": invoice.get("amount"),
            "outstanding": invoice.get("outstanding"),
            "collection_due_date": invoice.get("collection_due_date"),
            "review_status": invoice.get("review_status"),
            "collection_included": invoice.get("collection_included"),
        }

    total = len(invoices)
    paid = Decimal("0")
    outstanding = Decimal("0")
    for invoice in invoices:
        if not invoice["collection_included"] or not invoice["is_due"]:
            continue
        amount = Decimal(invoice.get("amount") or "0")
        balance = (Decimal("0") if invoice.get("state") == "PAID" else
                   Decimal(invoice.get("outstanding") if invoice.get("outstanding") is not None else amount))
        outstanding += max(Decimal("0"), balance)
        paid += max(Decimal("0"), amount - balance)
    page_limit = total if include_all else limit
    return {
        "customer_uid": customer_uid,
        "items": [compact(invoice) for invoice in invoices[:page_limit]],
        "summary": {
            **due_totals,
            "paid": str(paid.quantize(Decimal("0.01"))),
            "outstanding": str(outstanding.quantize(Decimal("0.01"))),
        },
        "meta": {
            "total": total,
            "limit": page_limit,
            "has_more": total > page_limit,
            "remaining": max(0, total - page_limit),
        },
    }
