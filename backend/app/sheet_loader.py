"""Load a New Order Master payload into the landing schema.

The payload is exactly what scripts/import_master_sheet.py assembles and what
fixtures_sheet.json holds, so this module is the only place that knows how one
maps onto the other. It does not parse anything; parsing stays in the script.
"""
from . import landing

BLOCKS = ("leasing", "tracking", "cash", "cash_invoices", "asset", "contact_log")

SPREADSHEET_ID = "SYNTHETIC-SPREADSHEET-ID"


def load_payload(conn, payload):
    """One import_run, one transaction. The caller owns the transaction so a
    failure leaves the previous run's rows serving."""
    source = payload.get("source") or {}
    run = landing.start_run(
        conn, "SHEET",
        spreadsheet_id=source.get("spreadsheet_id") or SPREADSHEET_ID,
        meta={"pivots": payload.get("pivots") or {},
              "flow_stages": payload.get("flow_stages") or {},
              "warnings": payload.get("warnings") or []})
    customers = orders = blocks = 0
    for record in payload.get("customers") or []:
        volt_id = record.get("volt_id")
        if not volt_id:
            continue
        landing.write_customer(conn, run, "SHEET", record)
        customers += 1
        order = record.get("order")
        if order:
            landing.write_order(conn, run, "SHEET", volt_id, order)
            orders += 1
        for block in BLOCKS:
            value = record.get(block)
            # An empty list and None both mean "the sheet said nothing here". Writing
            # them would make an absent block indistinguishable from an empty one.
            if value in (None, [], {}):
                continue
            landing.write_block(conn, run, "SHEET", volt_id, block, value)
            blocks += 1

    counts = dict(payload.get("counts") or {})
    counts["customers"] = customers
    landing.finish_run(conn, run, "OK", row_counts=counts,
                       reconciled=None, truncated_blocks=source.get("blocks") or [])
    return {"import_run_id": run, "customers": customers, "orders": orders, "blocks": blocks}
