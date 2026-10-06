"""Customer-scoped immutable payment evidence; never recompute/write balances."""
import json
from decimal import Decimal

from sqlalchemy import text

from . import clock, db


def build(invoices, receipts, sources, reconciliation, component_allocations=None):
    from .payment_claims import reconcile_receipts
    # Prefer the immutable published trace; older versions can be replayed using
    # the same pure reconciler. Never split a folded receipt total by guessed dates.
    if component_allocations is None:
        component_allocations = reconcile_receipts(invoices, receipts).get("component_allocations", [])
    receipt_by_doc = {receipt["doc_no"]: receipt for receipt in receipts}
    allocated = {}
    payment_groups = {}
    invoice_components = {}
    for row in component_allocations:
        index = row.get("component_index", 0)
        indices = row.get("component_indices") or [index]
        receipt = receipt_by_doc.get(row["receipt_doc_no"], {})
        parts = receipt.get("payments") or []
        source = parts[index] if 0 <= index < len(parts) else {
            "amount": receipt.get("paid_amount"), "on": receipt.get("paid_on"), "channel": receipt.get("paid_channel")}
        raw_parts = [parts[i] for i in indices if 0 <= i < len(parts)] or [source]
        net_received = str(sum((Decimal(str(part["amount"])) for part in raw_parts), Decimal(0)).quantize(Decimal("0.01")))
        paid_on = row.get("paid_on") or source.get("on")
        channel = row.get("channel") or row.get("paid_channel") or source.get("channel")
        key = (row["receipt_doc_no"], tuple(indices))
        allocated.setdefault(key, []).append({"invoice_doc_no": row["invoice_doc_no"], "amount": row["amount"]})
        payment_groups[key] = {"uid": "%s:%s" % (row["receipt_doc_no"], ",".join(map(str, indices))),
                              "component_indices": indices, "paid_on": paid_on, "net_received": net_received}
        if row["invoice_doc_no"]:
            invoice_components.setdefault(row["invoice_doc_no"], []).append({
                "uid": "%s:%s:%s" % (row["receipt_doc_no"], ",".join(map(str, indices)), row["invoice_doc_no"]),
                "receipt_doc_no": row["receipt_doc_no"], "paid_on": paid_on, "channel": channel,
                "amount": net_received, "allocated_amount": row["amount"], "status": "PAID",
                "raw_components": [{"uid": "%s:%s" % (row["receipt_doc_no"], i),
                    "paid_on": part.get("on"), "amount": part.get("amount"), "channel": part.get("channel"),
                    "is_adjustment": Decimal(str(part["amount"])) < 0} for i, part in zip(indices, raw_parts)],
                "included_in_snapshot": bool(paid_on and reconciliation.get("snapshot_as_of") and
                    str(paid_on or "")[:10] <= str(reconciliation["snapshot_as_of"])[:10])})
    receipt_rows = []
    for receipt in receipts:
        parts = receipt.get("payments") or [{"on": receipt.get("paid_on"), "amount": receipt.get("paid_amount"),
                                            "channel": receipt.get("paid_channel")}]
        components = []
        for index, part in enumerate(parts):
            component = {"uid": "%s:%s" % (receipt["doc_no"], index), "paid_on": part.get("on"),
                         "amount": part.get("amount"), "channel": part.get("channel"),
                         "status": receipt.get("status"), "is_adjustment": bool(part.get("amount") is not None and Decimal(str(part["amount"])) < 0)}
            components.append(component)
            if receipt.get("status") == "CANCELLED" and receipt.get("invoice_ref"):
                invoice_components.setdefault(receipt["invoice_ref"], []).append({
                    **component, "receipt_doc_no": receipt["doc_no"], "allocated_amount": None,
                    "included_in_snapshot": False})
        receipt_rows.append({"doc_no": receipt["doc_no"], "invoice_ref": receipt.get("invoice_ref"),
                             "status": receipt.get("status"), "components": components,
                             "payment_groups": [{**group, "allocations": allocated[key]}
                                                for key, group in payment_groups.items() if key[0] == receipt["doc_no"]],
                             "source_run_id": receipt.get("run_id"), "exported_at": receipt.get("exported_at"),
                             "report_as_of": receipt.get("report_as_of")})
    for values in invoice_components.values():
        values.sort(key=lambda row: (str(row.get("paid_on") or ""), row["uid"]))
    receipt_rows.sort(key=lambda row: row["doc_no"])
    invoice_start = next((source.get("covers_from") for source in sources if source["source_system"] == "PEAK"), None)
    receipt_start = min((source["covers_from"] for source in sources
                         if source["source_system"] == "PEAK_RECEIPT" and source.get("covers_from")), default=None)
    limitations = []
    if receipt_start and invoice_start and receipt_start > invoice_start:
        limitations.append({"code": "RECEIPT_HISTORY_BEFORE_COVERAGE_UNAVAILABLE", "before": receipt_start,
                            "invoice_covers_from": invoice_start})
    return {"read_only": True, "reconciliation": reconciliation, "sources": sources,
            "receipts": receipt_rows, "invoice_components": invoice_components, "limitations": limitations}


def for_customer(customer_uid):
    if not db.configured():
        return None
    conn = db.connect()
    try:
        if not conn.execute(text("select to_regclass('records.payment_reconciliation_version')")).scalar():
            return None
        # SQL selects only this customer's arrays from the latest immutable version.
        # The complete book-sized inputs never travel through the case request.
        row = conn.execute(text("select sequence,created_at,reason,trigger_run_id,invoice_run_id,snapshot_as_of, "
            "jsonb_path_query_array(inputs,'$.invoices[*] ? (@.customer_uid == $uid)',cast(:vars as jsonb)) as invoices, "
            "jsonb_path_query_array(inputs,'$.receipts[*] ? (@.customer_uid == $uid)',cast(:vars as jsonb)) as receipts "
            ",case when outputs ? 'component_allocations' then "
            "jsonb_path_query_array(outputs,'$.component_allocations[*] ? (@.customer_uid == $uid)',cast(:vars as jsonb)) "
            "else null end as component_allocations "
            "from records.payment_reconciliation_version order by sequence desc limit 1"),
            {"vars": json.dumps({"uid": customer_uid})}).mappings().first()
        if row is None or not (row["invoices"] or row["receipts"]):
            return None
        run_ids = {receipt.get("run_id") for receipt in row["receipts"] if receipt.get("run_id")}
        if row["invoice_run_id"]:
            run_ids.add(row["invoice_run_id"])
        latest_receipt_run = conn.execute(text("select id from landing.import_run "
            "where source_system='PEAK_RECEIPT' and status='OK' and meta ? 'applied' "
            "order by coalesce(meta->>'exported_at',meta->>'report_as_of','') desc,id desc limit 1")).scalar()
        if latest_receipt_run:
            run_ids.add(latest_receipt_run)
        sources = []
        if run_ids:
            for source in conn.execute(text("select id,source_system,meta->>'report_as_of' as report_as_of, "
                "meta->>'exported_at' as exported_at,meta->>'covers_from' as covers_from,meta->>'covers_to' as covers_to "
                "from landing.import_run where id=any(:ids) order by source_system,id"), {"ids": sorted(run_ids)}).mappings():
                sources.append(dict(source))
        reconciled = clock.to_local(row["created_at"])
        reconciliation = {"sequence": row["sequence"], "created_at": reconciled.isoformat(),
                          "reason": row["reason"], "snapshot_as_of": str(row["snapshot_as_of"]) if row["snapshot_as_of"] else None}
        return build(row["invoices"], row["receipts"], sources, reconciliation, row["component_allocations"])
    finally:
        conn.close()
