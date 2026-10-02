#!/usr/bin/env python3
"""Import the 'x' and 'Loan Book' tabs of the New Order Master sheet into a fixture.

Provenance: Google Sheet SYNTHETIC-SPREADSHEET-ID
("New Order Master", owner daniel@volt.co.th), read through the authenticated
Drive MCP because the sheet is not link-readable. The MCP renders each tab as a
markdown table, which is why this parses pipes rather than CSV: the raw CSV
export is comma-hazardous — baht amounts are written `3,199฿` and `157,353฿`,
so a naive split misaligns every row after the money columns.

PII: names and order facts are kept; phone, email, street number and the Google
Maps pin are masked. The pin is dropped outright — it is the precise location of
a private home, and no screen in this prototype needs it.

Re-run:  ./scripts/import_order_master.py <mcp-result.txt> backend/app/fixtures_orders.json
"""
import json
import re
import sys


def cells(line):
    return [c.strip() for c in line.split("|")][1:-1]


def tables(text):
    lines = text.split("\n")
    seps = [i for i, l in enumerate(lines) if ":-:" in l] + [len(lines)]
    for a, b in zip(seps, seps[1:]):
        rows = [cells(l) for l in lines[a + 1:b] if l.strip().strip("|").strip()]
        if rows:
            yield rows


def unescape(value):
    # The markdown renderer escapes *, _, \ and & inside cells.
    text = re.sub(r"\\(.)", r"\1", value or "").strip()
    # A spreadsheet formula error is not a value. Carrying "#N/A" through would
    # print it on screen as though somebody had entered it.
    return "" if text in {"#N/A", "#REF!", "#VALUE!", "#DIV/0!"} else text


def mask_phone(raw):
    digits = re.sub(r"\D", "", unescape(raw))
    if len(digits) < 4:
        return None
    # Matches the convention already used on the Today List: 08x-xxx-4471.
    return f"{digits[:2]}x-xxx-{digits[-4:]}"


def mask_email(raw):
    value = unescape(raw)
    if "@" not in value:
        return None
    local, _, domain = value.partition("@")
    return f"{local[:1]}•••@{domain}"


def mask_address(raw):
    value = unescape(raw)
    if not value:
        return None
    # Drop the leading house/plot number, keep street, district and province so
    # the row still reads as a real Thai address.
    return re.sub(r"^[\d/\-]+\s*", "••• ", value)


def money(raw):
    """'3,199฿' -> '3199.00'. Returns None rather than guessing on a blank."""
    value = unescape(raw).replace("฿", "").replace(",", "").strip()
    if not value:
        return None
    try:
        return f"{float(value):.2f}"
    except ValueError:
        return None


def pick(row, header, name):
    try:
        return unescape(row[header.index(name)]) or None
    except (ValueError, IndexError):
        return None


def main(src, out):
    text = json.load(open(src))["fileContent"]
    blocks = list(tables(text))

    orders_block = next(b for b in blocks if any("Order Status" in r for r in b))
    header = next(r for r in orders_block if "Order Status" in r)
    rows = [r for r in orders_block[orders_block.index(header) + 1:] if r and r[0].isdigit()]

    orders = []
    for row in rows:
        phone = pick(row, header, "Phone")
        orders.append({
            "no": int(pick(row, header, "No")),
            "crm_id": pick(row, header, "CRM ID"),
            "volt_id": pick(row, header, "Volt ID"),
            "first_name": pick(row, header, "First Name"),
            "last_name": pick(row, header, "Last Name"),
            "thai_name": pick(row, header, "Peak ID"),
            "sales_lead": pick(row, header, "Sales Lead"),
            "order_type": pick(row, header, "Order Type"),
            # The sheet ships every row already closed. The prototype seeds the
            # queue at EPC Installation instead, because an approval queue with
            # nothing pending demonstrates nothing. `sheet_order_status` keeps
            # what the sheet actually said, so the two are never confused.
            "sheet_order_status": pick(row, header, "Order Status"),
            "loan_status": pick(row, header, "Loan Status"),
            "contract_purchase": pick(row, header, "Contract Purchase"),
            "contract_service": pick(row, header, "Contract Service"),
            "submit_date": pick(row, header, "Submit Date"),
            "contract_signed_date": pick(row, header, "Contract Signed Date"),
            "inverter_brand": pick(row, header, "Inverter Brand"),
            "inverter_type": pick(row, header, "Inverter Type"),
            "monthly_rate_incl_vat": money(pick(row, header, "Monthly Rate, INC VAT")),
            "term_months": pick(row, header, "Term"),
            "project_type": pick(row, header, "Project Type"),
            "energy_bill": pick(row, header, "Energy Bill"),
            "watt": pick(row, header, "Watt"),
            "phase": pick(row, header, "Phase"),
            "epc": pick(row, header, "EPC"),
            "epc_start_date": pick(row, header, "EPC Start Date"),
            "epc_end_date": pick(row, header, "EPC End Date"),
            "province": pick(row, header, "Province"),
            "postal_code": pick(row, header, "Postal Code"),
            "address_masked": mask_address(pick(row, header, "Address")),
            "phone_masked": mask_phone(phone) if phone else None,
            "email_masked": mask_email(pick(row, header, "Email")),
            "com_status": pick(row, header, "Com Status"),
        })

    # The workbook holds TWO tables with these headings — two revisions of the
    # loan book. They differ in the tenor unit: one is keyed in years, the other
    # in months, and the months revision is the maintained one (its first row
    # resolves, the other's is #N/A). Selecting on that column is explicit; taking
    # the first match imports the stale cohort silently.
    def is_months_revision(block):
        return any(
            any("Lease/PPA Tenor (Months)" in c for c in row)
            for row in block
        )

    candidates = [b for b in blocks if any("Lessee/Offtaker Name" in r for r in b)]
    lb_block = next((b for b in candidates if is_months_revision(b)), candidates[0])
    lb_header = next(r for r in lb_block if "Lessee/Offtaker Name" in r)
    lb_rows = [r for r in lb_block[lb_block.index(lb_header) + 1:] if r and r[0].isdigit()]

    book = []
    for row in lb_rows:
        book.append({
            "no": int(pick(row, lb_header, "No")),
            "lessee": pick(row, lb_header, "Lessee/Offtaker Name"),
            "customer_id": pick(row, lb_header, "Customer ID"),
            "province": pick(row, lb_header, "State/Province"),
            "address_masked": mask_address(pick(row, lb_header, "Property Address")),
            "installer": pick(row, lb_header, "Installer"),
            "system_size_kwp": pick(row, lb_header, "System Size (kwp)"),
            "original_cost_thb": money(pick(row, lb_header, "Original System Cost (local currency)")),
            "book_value_usd": money(pick(row, lb_header, "Current Book Value (loan currency)")),
            "commencement_date": pick(row, lb_header, "Lease/PPA Commencement date"),
            "tenor_months": pick(row, lb_header, "Lease/PPA Tenor (Months)"),
            "monthly_excl_vat_thb": money(
                pick(row, lb_header, "Monthly Lease Payment (local currency) - excl. VAT")),
            "monthly_incl_vat_thb": money(
                pick(row, lb_header, "Monthly Lease Payment (local currency) incl. VAT")),
            "total_lease_incl_vat_thb": money(
                pick(row, lb_header, "Total Lease Amount (local currency) incl. VAT")),
            "age_years": pick(row, lb_header, "Age (year)"),
            "origin": "sheet",
        })

    payload = {
        "source": {
            "spreadsheet": "New Order Master",
            "spreadsheet_id": "SYNTHETIC-SPREADSHEET-ID",
            "tabs": ["x", "Loan Book"],
            "pii": "phone, email and street number masked; map pin dropped",
        },
        "orders": orders,
        "loan_book": book,
    }
    with open(out, "w") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print(f"orders={len(orders)} loan_book={len(book)} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
