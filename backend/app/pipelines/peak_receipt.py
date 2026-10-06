"""The PEAK receipt report ("รายงานใบเสร็จรับเงิน"), parsed into receipt records.

Feedback round 2 / Q6 (TASK-201). The frequent export: header on row 12, 46 columns;
one row per receipt line, grouped into one receipt per เลขที่เอกสาร. The receipt
settles the invoice it references (อ้างอิง / อ้างอิงจากระบบ → an IV-/IVT- number) and
its cycle (คำอธิบาย "Installment_M n/N").

Pure: bytes in, records out. No clock, no database, no network. The reader is
app.imports (ruling 36: never a second csv/xlsx parser), and the header/date/money
helpers are the invoice parser's own — one implementation, two reports.

Missing payment-defining headings refuse the whole file by name; identity/reference
columns omitted by the export checklist remain reviewable. Duplicate headings use
their report section, and an unknown status rejects that row by value. A date or
amount that does not parse rejects its whole receipt (fix-all P8).
The 13-digit id is parsed in-run only and never reaches a writer (F5/PDPA).
"""
from . import peak_report as invoice_report
from .peak_report import (ReportError, _cell, _date, _find_header, _money, _normalise_heading,
                          _require_columns, _resolve_columns, _table, group_documents,
                          report_as_of, report_range)

REQUIRED_FIELDS = ("doc_no", "status_th", "paid_amount", "paid_on")
ALIASES = {}
FIRST_FIELDS = ("doc_no", "journal_ref")

STATUS_MAP = {"รับชำระแล้ว": "PAID", "ร่าง": "DRAFT", "ยกเลิก": "CANCELLED"}

# Column heading -> record key, the receipt export's own columns. Unanchored repeated
# headings take their first index; paid_amount is resolved after the paid-date column.
COLUMNS = {
    "เลขที่เอกสาร": "doc_no", "วันที่ออก": "issued_on",
    "อ้างอิง": "invoice_ref", "อ้างอิงจากระบบ": "system_invoice_ref",
    "บันทึกบัญชี": "journal_ref",
    "สถานะ": "status_th", "รหัสผู้ติดต่อ": "contact_code", "ชื่อลูกค้า": "customer_name",
    "เลขที่ 13 หลัก": "tax_id_13",                       # in-run only; never written
    "รายการที่": "line_no", "รหัสสินค้า/บริการ": "product_code",
    "ชื่อสินค้า/บริการ": "product_name", "คำอธิบาย": "description",
    "ราคา": "price", "ทั้งหมด": "amount_total", "ต้องชำระ": "amount_due",
    "วันที่": "paid_on", "เลขที่ช่องทางการเงิน": "channel_code",
    "ช่องทางการชำระเงิน": "paid_channel", "จำนวนเงิน": "paid_amount", "หมายเหตุ": "note",
}

COLUMN_AFTER = {"paid_amount": "วันที่"}

# Headings only the invoice report carries: an invoice export dropped on the receipt
# door would otherwise read as receipts, since it has every heading REQUIRED names.
INVOICE_ONLY = ("มูลค่ารอรับชำระ", "วันที่ครบกำหนด")

# The receipt's own document kinds. RE/RT are the two the export writes; anything
# else keeps its own word as OTHER rather than being guessed into one of them.
DOC_KINDS = ("RE", "RT")


def parse(raw, filename=None):
    table = _table(raw)
    header_row, cells = _find_header(table, COLUMNS)
    headings = {_normalise_heading(cell) for cell in cells}
    if any(_normalise_heading(h) in headings for h in INVOICE_ONLY):
        raise ReportError("wrong_report", "this is the PEAK invoice report, not the receipt report",
                          "ไฟล์นี้เป็นรายงานใบแจ้งหนี้ ไม่ใช่รายงานรับชำระ")
    col, schema = _resolve_columns(cells, COLUMNS, REQUIRED_FIELDS, ALIASES,
                                   COLUMN_AFTER, FIRST_FIELDS, "receipt")
    schema["header_row"] = header_row + 1
    _require_columns(col, REQUIRED_FIELDS, COLUMNS, schema)
    lines, rejected = [], []
    for n, row in enumerate(table[header_row + 1:], start=header_row + 2):   # 1-based sheet row
        doc_no = _cell(row, col["doc_no"])
        if not doc_no:
            continue
        status_th = _cell(row, col["status_th"])
        status = STATUS_MAP.get(status_th)
        lines.append({key: _cell(row, i) for key, i in col.items()} | {"status": status, "sheet_row": n})
    receipts, lines = group_documents(lines, _receipt, rejected)
    covers_from, covers_to = report_range(filename)
    return {
        "receipts": receipts,
        "meta": {"report_as_of": report_as_of(filename),
                 "exported_at": invoice_report.export_timestamp(filename),
                 "covers_from": covers_from, "covers_to": covers_to,
                 "read": len(lines), "rejected": rejected, "schema": schema},
    }


def public_schema():
    return invoice_report.schema_contract(
        "receipt", COLUMNS, REQUIRED_FIELDS, ALIASES, COLUMN_AFTER, FIRST_FIELDS)


def _receipt(lines):
    """One receipt from its lines (they share เลขที่เอกสาร); the receipt-level cells
    repeat on every line and are read from the first. The cycle comes from the
    description (or the product name) with the invoice parser's own regex."""
    first = lines[0]
    invoice_report.require_consistent(lines, ("status", "contact_code", "issued_on", "invoice_ref",
        "system_invoice_ref", "amount_total", "amount_due"))
    payments = {}
    for line in lines:
        component = {"on": _date(line.get("paid_on")), "amount": _money(line.get("paid_amount")),
                     "channel": line.get("paid_channel") or None, "channel_code": line.get("channel_code") or None}
        if component["amount"] is None and not component["on"]:
            continue
        key = tuple(component.values())
        payments[key] = component
    components = sorted(payments.values(), key=lambda value: (value["on"] or "", value["channel"] or ""))
    doc = first["doc_no"]
    cycle = invoice_report._cycle(first["description"], first["product_name"])
    prefix = doc.split("-")[0] if "-" in doc else doc
    rec = {
        "doc_no": doc,
        "doc_kind": prefix if prefix in DOC_KINDS else "OTHER",
        "issued_on": _date(first["issued_on"]),
        "invoice_ref": first["system_invoice_ref"] or first["invoice_ref"] or None,
        "journal_ref": first["journal_ref"] or None,
        "contact_code": first["contact_code"] or None,
        "customer_name": first["customer_name"] or None,
        "tax_id_13": first["tax_id_13"] or None,          # in-run only (F5)
        "status": first["status"],
        "cycle_n": (cycle or {}).get("n"), "cycle_of": (cycle or {}).get("of"),
        "amount_total": _money(first["amount_total"]),
        "amount_due": _money(first["amount_due"]),
        "paid_on": _date(first["paid_on"]),
        "channel_code": first["channel_code"] or None,
        "paid_channel": first["paid_channel"] or None,
        "paid_amount": _money(first["paid_amount"]),
        "note": first["note"] or None,
        "lines": [],
        "source_rows": [line["sheet_row"] for line in lines],
        "payments": components,
    }
    if components:
        if any(value["amount"] is None for value in components):
            raise invoice_report.Unreadable("payment_component_incomplete", "paid_amount")
        rec["paid_amount"] = str(sum((invoice_report.Decimal(value["amount"]) for value in components),
                                    invoice_report.Decimal(0)).quantize(invoice_report.Decimal("0.01")))
        rec["paid_on"] = components[-1]["on"]
    seen_items = set()
    for ln in lines:
        try:
            line_no = int(float(ln["line_no"])) if ln["line_no"] else len(rec["lines"]) + 1
        except (ValueError, TypeError):
            line_no = len(rec["lines"]) + 1
        item = {"line_no": line_no,
                             "product_code": ln["product_code"] or None,
                             "product_name": ln["product_name"] or None,
                             "description": ln["description"] or None,
                             "amount": _money(ln["price"])}
        item_key = tuple(item.items())
        if item_key not in seen_items:
            seen_items.add(item_key)
            rec["lines"].append(item)
    return rec
