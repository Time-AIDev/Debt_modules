"""Integration endpoints (R13–R16): Odoo discovery/status, PEAK issue, and the local
status overrides with provenance (R14). The Odoo sync and source switches went on
2026-09-25: "Sync Odoo" is the crm.lead pull (routers/pipelines.py)."""
from fastapi import APIRouter, Body, Query

from .. import audit
from .. import errors
from .. import journey
from ..config import settings
from ..integrations import odoo as odoo_client
from ..integrations import peak as peak_client

router = APIRouter()


@router.get("/v1/integrations/status")
def integrations_status():
    peak_probe = None
    peak_state = peak_client.status()
    if peak_state["configured"]:
        try:
            peak_probe = peak_client.probe()
        except peak_client.PeakError as exc:
            peak_probe = {"reachable": False, "reason": str(exc)}
    return {"odoo": odoo_client.status(), "peak": {**peak_state, "probe": peak_probe}}


@router.get("/v1/integrations/odoo/discovery")
def odoo_discovery():
    try:
        return odoo_client.discovery()
    except odoo_client.NotConfigured as exc:
        raise errors.integration_not_configured("Odoo", exc.missing)
    except odoo_client.OdooError as exc:
        raise errors.integration_unavailable("Odoo", str(exc))
    except Exception as exc:  # httpx transport errors
        raise errors.integration_unavailable("Odoo", exc.__class__.__name__)


# --- R14: local overrides with provenance -----------------------------------------

@router.post("/v1/orders/{no}/status-override", status_code=201)
def override_order_status(no: int, body: dict = Body(...)):
    from .. import orders as orders_domain
    order = orders_domain.get(no)
    if order is None:
        raise errors.not_found("order")
    adjusted = (body or {}).get("adjusted_value")
    reason = (body or {}).get("reason")
    by = (body or {}).get("by") or "Nok"
    if not adjusted or not str(adjusted).strip():
        raise errors.validation_failed([{
            "pointer": "/adjusted_value", "code": "required",
            "message": "adjusted_value is required",
            "message_th": "ต้องระบุค่าที่ปรับ"}])
    if not reason or not str(reason).strip():
        raise errors.validation_failed([{
            "pointer": "/reason", "code": "required",
            "message": "An override requires a logged reason (R14).",
            "message_th": "การปรับสถานะต้องระบุเหตุผล"}])
    field = (body or {}).get("field") or "loan_status"
    source_value = order.get(field)
    if str(adjusted) == str(source_value):
        raise errors.override_source_unchanged("order %d %s" % (no, field), adjusted)
    state = journey.for_current()
    # Keyed by the stable order identity, not the positional `no`: an Odoo pull
    # numbers its rows 9000+n, so a re-sync that reorders them re-pointed an
    # override at another order (sync audit, 2026-09-20).
    ref = "order:%s:%s" % (_order_key(order), field)
    state.overrides[ref] = {
        "ref": ref, "field": field,
        "source_value": source_value,
        "adjusted_value": adjusted,
        "by": by, "reason": str(reason).strip(),
        "on": str(settings.business_date),
        "source_system": order.get("data_source") or "SHEET",
        # A fact about the moment of the override: the source has not moved SINCE it
        # (an equal value is refused above, so the override always differs). The read
        # path recomputes this against each later sync in journey.reconcile_overrides.
        "source_changed_since_override": False,
        "source_value_now": source_value,
        "source_missing": False,
        "note": "Local override — the source system is never written (R14).",
    }
    # R14 is exactly the act a reconciliation dispute asks about: which value did
    # a person substitute for the source's, and why.
    from .. import audit
    audit.describe(act="R14_OVERRIDE", subject=("order", _order_key(order)),
                   detail={"field": field, "from": source_value,
                           "to": adjusted, "reason": str(reason).strip()})
    return {"override": state.overrides[ref]}


def _order_key(order):
    """The same stable key orders.py uses: volt_id, then crm_id, then the number."""
    return str(order.get("volt_id") or order.get("crm_id") or order.get("no"))


def _order_lookup():
    from .. import orders as orders_domain
    lookup = {}
    for order in orders_domain.orders():
        lookup[_order_key(order)] = order
        lookup.setdefault(str(order.get("no")), order)   # legacy refs used the number
    return lookup


@router.get("/v1/status-overrides")
def list_overrides():
    state = journey.for_current()
    # Recomputed on read: whether the source moved since the override is a fact
    # about the current order, not about the moment someone typed the override.
    journey.reconcile_overrides(_order_lookup())
    return {"overrides": list(state.overrides.values())}


@router.delete("/v1/status-overrides/{ref:path}")
def clear_override(ref: str):
    audit.describe(act="R14_OVERRIDE_CLEARED", subject=("override", ref))
    state = journey.for_current()
    if ref not in state.overrides:
        raise errors.not_found("override")
    removed = state.overrides.pop(ref)
    return {"cleared": removed}


# --- C3: PEAK draft only (was R15 full write) --------------------------------------

@router.post("/v1/invoices/{uid}:issue-peak", status_code=201)
def issue_peak(uid: str):
    """Legacy alias kept for the invoice card: creates the invoice in PEAK as a
    DRAFT through the peak_documents layer. Approval happens inside PEAK."""
    audit.describe(act="PEAK_INVOICE_ISSUED", subject=("invoice", uid))
    from .. import peak_documents as pkd
    state = journey.for_current()
    invoice = state.invoices.get(uid)
    if invoice is None:
        raise errors.not_found("invoice")
    if invoice.get("peak_state") in ("DRAFT_CREATED", "APPROVED_IN_PEAK"):
        raise errors.idempotency_key_reused("invoice %s already in PEAK (%s)"
                                            % (uid, invoice.get("peak_ref")))
    found = journey.contract_by_uid(invoice["contract_uid"])
    customer_name = found[0].display_name if found else "(unknown)"
    docs = pkd.for_current()
    if pkd.transport_for(docs) is pkd.peak_client:
        # No stub injected: a missing credential set must surface as the same
        # 422 the rest of the integration layer raises, not as a silent UNSENT.
        from ..integrations import peak as peak_client
        try:
            peak_client._config(invoice.get("entity") or "EPC")
        except peak_client.NotConfigured as exc:
            invoice["peak_state"] = "UNSENT"
            raise errors.integration_not_configured("PEAK", exc.missing)
    try:
        [record] = pkd.raise_document(
            docs, "INVOICE_CREATE", invoice["uid"], invoice.get("entity"),
            {"amount": invoice["amount"], "due_date": invoice["due_date"], "kind": invoice["kind"]},
            by="api", customer_name=customer_name)
    except pkd.PeakDocumentError as exc:
        raise errors.validation_failed([{"pointer": "/intent", "code": exc.code,
                                         "message": exc.detail, "message_th": "สร้างเอกสารร่างใน PEAK ไม่ได้"}])
    invoice["peak_document_uid"] = record["uid"]
    invoice["peak_state"] = record["state"]
    invoice["peak_ref"] = record.get("peak_ref")
    invoice["qr_payload"] = None            # a draft has no QR (PC3)
    if record["state"] == "UNSENT":
        raise errors.peak_unsent(uid, record["last_error"] or "not sent")
    return {"invoice": invoice, "peak_document": record}
