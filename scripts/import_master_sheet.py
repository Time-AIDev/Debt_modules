#!/usr/bin/env python3
"""Import the New Order Master working tabs into backend/app/fixtures_sheet.json.

REQ-INT-030..032 (Requirements Amendment v2.6). Source: the Drive MCP text render of
Google Sheet SYNTHETIC-SPREADSHEET-ID ("New Order Master"),
saved as backend/var/master_sheet.txt. The render is a sequence of markdown tables
with no tab names, truncated per tab at roughly 20-50 KB, so:

  - tabs are recognised by their HEADER ROW, never by position;
  - every imported row keeps source_ref = (block index, row index) so a figure on
    screen can be traced to a cell;
  - counts are reconciled against the sheet's OWN summary rows (the portfolio
    summary and the payment-status pivot) and the run says where the export was
    truncated rather than pretending the sample is the book.

Masking (C5, R12, changed 2026-09-20): email and identity numbers are masked; the
PHONE is kept whole — this is an internal collections tool and the dial/copy actions
need the real digits, so hiding moved to the serving layer (the case screen serves a
mask plus `phone_revealable`; the full number comes only from the audited
phone:reveal route — backend/app/customer_contact.py). `phone_masked` still travels
beside it for the screens. Names, VOLT IDs, amounts, statuses and notes are kept. No
screen needs the Google Maps pin.

The MapLog string the LINE tooling appends to the Comment cell uses a vertical bar
as its separator, so in a markdown table those rows are column-shifted. The parser
re-joins the shifted cells before reading the row (MC1 in Case Register v1.4).

Re-run:  ./scripts/import_master_sheet.py backend/var/master_sheet.txt backend/app/fixtures_sheet.json
"""
import json
import math
import re
import sys
from collections import Counter, OrderedDict

ERRORS = {"#N/A", "#REF!", "#VALUE!", "#DIV/0!", "#NAME?"}
MONTH_TOKENS = {
    "late": "LATE", "link sent": "LINK_SENT", "restructure": "RESTRUCTURE",
    "credit note": "CREDIT_NOTE", "no payment: service issue": "NO_PAYMENT_SERVICE_ISSUE",
    "no payment service issue": "NO_PAYMENT_SERVICE_ISSUE", "paid": "PAID", "closed": "CLOSED",
}
CONTACT_RESULTS = {
    "ติดต่อได้ - รับสาย": "REACHED_ANSWERED",
    "ติดต่อไม่ได้ - ไม่รับสาย": "UNREACHABLE_NO_ANSWER",
    "ติดต่อได้ - นัดชำระ": "REACHED_PTP",
    "cannot contact - no answer": "UNREACHABLE_NO_ANSWER",
}


def unescape(value):
    text = re.sub(r"\\(.)", r"\1", value or "").strip()
    return "" if text in ERRORS else text


PIPE = re.compile(r"(?<!\\)\|")


def cells(line):
    # Split on UNESCAPED bars only: a MapLog comment carries "\|" inside one cell.
    return [unescape(c) for c in PIPE.split(line)[1:-1]]


def blocks(text):
    """Yield (block_index, header_cells, rows) for every markdown table."""
    lines = text.split("\n")
    seps = [i for i, l in enumerate(lines) if ":-:" in l] + [len(lines)]
    for bi, (a, b) in enumerate(zip(seps, seps[1:])):
        header = cells(lines[a - 1]) if a > 0 else []
        rows = [cells(l) for l in lines[a + 1:b] if l.strip().strip("|").strip()]
        yield bi, header, rows


def find_header(header, rows, must_have):
    """The real header is the first row containing every name in must_have. An .xlsx
    cell keeps its line breaks ('Rate, \\ninc VAT'); the Drive render the readers name
    columns by turns them into spaces — so the header comes back in the render's form."""
    for i, r in enumerate([header] + rows):
        if all(any(c.strip() == m for c in r) for m in must_have):
            return i - 1, [c.replace("\n", " ") if isinstance(c, str) else c for c in r]  # -1: the markdown header line
    return None, None


def money(raw):
    value = (raw or "").replace("฿", "").replace(",", "").strip()
    if value in ("", "-", "–"):
        return None
    try:
        amount = float(value)
    except ValueError:
        return None
    return "%.2f" % amount if math.isfinite(amount) else None   # "NaN" / "inf" are not money


def number(raw):
    value = (raw or "").replace(",", "").strip()
    try:
        return int(float(value))
    except ValueError:
        return None


def parse_date(raw, day_first=False):
    """Two live formats. Four-digit year => month first (7/31/2026, the leasing
    tabs); two-digit year => day first (31/08/26, the cash tab). ISO passes.
    `day_first` reads the four-digit form day first as well: 'Done - Cash' writes
    01/09/2024 for 1 September (DQ 2026-09-26 F14), while the leasing tabs' PTP Date
    is still m/d/yyyy. A date that cannot be day first stays month first."""
    value = (raw or "").strip()
    if not value:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return "%s-%s-%s" % m.groups()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mo, d = (b, a) if a > 12 or (day_first and b <= 12) else (a, b)
        if mo > 12 or d > 31:
            return None
        return "%04d-%02d-%02d" % (y, mo, d)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2})$", value)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3))
        if mo > 12 and d <= 12:
            d, mo = mo, d
        if mo > 12 or d > 31:
            return None
        return "%04d-%02d-%02d" % (y, mo, d)
    m = re.match(r"^(\d{2})/(\d{2})$", value)  # MM/YY month stamp
    if m:
        return "20%s-%s-01" % (m.group(2), m.group(1))
    return None


def month_cell(raw):
    value = (raw or "").strip()
    if not value or value in ("-", "–", "·"):
        return None
    key = value.lower()
    if key in MONTH_TOKENS:
        return {"kind": MONTH_TOKENS[key]}
    amt = money(value)
    if amt is not None:
        return {"kind": "PAID", "amount": amt}
    return {"kind": "TEXT", "text": value}


def split_volt_id(volt_id):
    parts = (volt_id or "").split("_")
    return {
        "customer_no": parts[0] if parts else None,
        "name_roman": parts[1] if len(parts) > 1 else None,
        "name_th": parts[2] if len(parts) > 2 else None,
        "epc": parts[3] if len(parts) > 3 else None,
    }


MAPLOG = re.compile(r"\[MapLog:([^|\]]+)\|([^|\]]+)\|([^\]]+)\]")


def parse_maplog(comment):
    """Every MapLog entry in a comment -> contact_log rows. The format:
    [MapLog:ID|timestamp|agent] | result | PTP amt | PTP Date d | Next Call d | note"""
    rows = []
    pieces = re.split(r"(?=\[MapLog:)", comment or "")
    for piece in pieces:
        m = MAPLOG.match(piece)
        if not m:
            continue
        rest = piece[m.end():]
        fields = [f.strip() for f in rest.split("|")]
        fields = [f for f in fields if f]
        entry = {
            "occurred_at": m.group(2).strip(),
            "officer": m.group(3).strip(),
            "result": None, "result_raw": None,
            "ptp_amount": None, "ptp_date": None, "next_call": None, "note": [],
        }
        for f in fields:
            low = f.lower()
            if f in CONTACT_RESULTS or low in CONTACT_RESULTS:
                entry["result"] = CONTACT_RESULTS.get(f) or CONTACT_RESULTS.get(low)
                entry["result_raw"] = f
            elif low.startswith("ptp date"):
                entry["ptp_date"] = parse_date(f.split(" ", 2)[2][:10]) if len(f.split(" ", 2)) > 2 else None
            elif low.startswith("ptp "):
                entry["ptp_amount"] = money(f[4:])
            elif low.startswith("next call"):
                entry["next_call"] = parse_date(f.split(" ", 2)[2][:10]) if len(f.split(" ", 2)) > 2 else None
            else:
                entry["note"].append(f)
        entry["note"] = " ".join(entry["note"]) or None
        rows.append(entry)
    return rows


def rejoin_shifted(row, header_len, comment_index):
    """A MapLog comment carries bars, so the row has more cells than the header.
    Fold the surplus back into the comment cell."""
    extra = len(row) - header_len
    if extra <= 0:
        return row, False
    joined = " | ".join(row[comment_index:comment_index + extra + 1])
    return row[:comment_index] + [joined] + row[comment_index + extra + 1:], True


def cell(row, i):
    return row[i] if 0 <= i < len(row) else None


def col(row, header, name, default=None):
    try:
        i = header.index(name)
    except ValueError:
        return default
    return row[i] if i < len(row) else default


def cols_like(header, prefix):
    return [(i, h) for i, h in enumerate(header) if h.startswith(prefix)]


def mask_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    return "%sx-xxx-%s" % (digits[:2], digits[-4:]) if len(digits) >= 4 else None


def e164(raw):
    """The sheet's Phone cell, kept whole for the dial actions (2026-09-20).

    A plain national Thai number gains the +66 it must dial as; the +66 form and the
    +66 (0) form lose the redundant national 0; anything odd (an extension, a foreign
    number) is kept as the digits that were typed rather than dropped — a wrong dial
    the officer can see beats a silent None. Never raises: the sheet is data, not a
    person's keyed input.
    """
    text = str(raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if digits.startswith("66") and len(digits) in (11, 12):
        return "+" + (digits[:2] + digits[2:].lstrip("0"))
    if digits.startswith("0"):
        return "+66" + digits[1:]
    return "+" + digits if text.startswith("+") else digits


def mask_email(raw):
    if "@" not in (raw or ""):
        return None
    local, _, domain = raw.partition("@")
    return "%s•••@%s" % (local[:1], domain)


# --- tab readers -----------------------------------------------------------------

def alias_payment_status(rows):
    """The 2026-09-25 'Done - Collection' calls its payment status "Status". A leasing
    header — VOLT ID and Term, Original — with no "Payment Status" reads its "Status"
    as one, in place, so the tab is found and read like every older copy."""
    for r in rows[:30]:
        cells = [c.replace("\n", " ").strip() if isinstance(c, str) else c for c in r]
        if "VOLT ID" in cells and "Term, Original" in cells and "Payment Status" not in cells and "Status" in cells:
            r[cells.index("Status")] = "Payment Status"
            return


def read_leasing_block(bi, header, rows, warnings):
    alias_payment_status([header] + rows)
    hi, hdr = find_header(header, rows, ["VOLT ID", "Payment Status"])
    if hdr is None:
        return []
    month_cols = [i for i, h in enumerate(hdr) if re.match(r"^M\d+$", h)]
    if "Term, Original" not in hdr and not month_cols:
        return []
    comment_idx = hdr.index("Comment") if "Comment" in hdr else None
    out = []
    data = rows[hi + 1:] if hi >= 0 else rows
    for ri, row in enumerate(data):
        shifted = False
        if comment_idx is not None:
            row, shifted = rejoin_shifted(row, len(hdr), comment_idx)
        volt_id = col(row, hdr, "VOLT ID")
        if not volt_id or "_" not in volt_id:
            continue
        comments = [row[i] for i, h in enumerate(hdr) if h == "Comment" and i < len(row)]
        rec = OrderedDict(
            volt_id=volt_id, source_ref=[bi, ri], product="LEASE",
            sales_lead=col(row, hdr, "Sales Lead"), crm_id=col(row, hdr, "CRM ID"),
            order_status=col(row, hdr, "Order Status"),
            contract_signed=parse_date(col(row, hdr, "Contract Signed")),
            first_payment_date=parse_date(col(row, hdr, "First Payment Date")),
            invoice_due_date=parse_date(col(row, hdr, "Invoice Due Date")),
            last_payment_date=parse_date(col(row, hdr, "Last Payment Date")),
            pledge=col(row, hdr, "Pledge"),
            system_kwp=money(col(row, hdr, "System Size (kWp)")),
            term_original=number(col(row, hdr, "Term, Original")),
            term_remain=number(col(row, hdr, "Term, Remain")),
            pmt_inc_vat=money(col(row, hdr, "Rate,  inc VAT")),
            dp_inc_vat=money(col(row, hdr, "DP  incl VAT")),
            total_inc_vat=money(col(row, hdr, "PMT,  Inc VAT")),
            paid_inc_vat=money(col(row, hdr, "PMT paid inc VAT")),
            remain_inc_vat=money(col(row, hdr, "PMT remain, inc VAT")),
            npv_ex_vat=money(col(row, hdr, "NPV ex VAT")),
            npv_ex_vat_remain=money(col(row, hdr, "NPV ex VAT Remain")),
            cost_ex_vat=money(col(row, hdr, "Cost  ex VAT")),
            overdue=money(col(row, hdr, "Overdue")),
            days_late=number(col(row, hdr, "Days Late")),
            late_fees=money(col(row, hdr, "Late Fees")),
            issue=col(row, hdr, "Issue"),
            comment_th=comments[0] if comments else None,
            comment_en=comments[1] if len(comments) > 1 else None,
            dc_status=col(row, hdr, "DC Status"),
            legal=col(row, hdr, "Legal"),
            contract_cancelled=col(row, hdr, "Contract Canceled?"),
            ptp_date=parse_date(col(row, hdr, "PTP Date")),
            ptp_amount=money(col(row, hdr, "PTP Amount")),
            payment_status=col(row, hdr, "Payment Status"),
            npl_type=col(row, hdr, "NPL Type"),
            bucket=col(row, hdr, "Bucket - Weeks Late"),
            dp_paid=col(row, hdr, "DP Paid"),
            months=[month_cell(row[i]) if i < len(row) else None for i in month_cols],
            ticket=OrderedDict(
                action_type=col(row, hdr, "Action Type"), responsible_team=col(row, hdr, "Responsible Team"),
                ticket_link=col(row, hdr, "Ticket Link"), deadline=col(row, hdr, "Deadline"),
                case_status=col(row, hdr, "Case Status"), remark=col(row, hdr, "Remark"),
            ),
            maplog=parse_maplog(" ".join(comments)),
            shifted_row=shifted,
        )
        if col(row, hdr, "PTP Date") and rec["ptp_date"] is None:
            warnings.append({"block": bi, "row": ri, "volt_id": volt_id, "warning": "unparseable PTP date", "value": col(row, hdr, "PTP Date")})
        out.append(rec)
    return out


def read_collection_tracking(bi, header, rows):
    hi, hdr = find_header(header, rows, ["VOLT ID", "Category", "Total Overdue"])
    summary = []
    for r in rows:
        if len(r) >= 3 and r[0] and r[1] and re.match(r"^[\d,]+$", r[1] or "") and money(r[2]):
            summary.append({"category": r[0], "count": number(r[1]), "total_overdue": money(r[2])})
    if hdr is None:
        return summary, []
    month_cols = [(i, h) for i, h in enumerate(hdr) if re.match(r"^[A-Z][a-z]{2} \d{4}$", h)]
    out = []
    for ri, row in enumerate(rows[hi + 1:]):
        volt_id = col(row, hdr, "VOLT ID")
        if not volt_id or "_" not in volt_id:
            continue
        out.append(OrderedDict(
            volt_id=volt_id, source_ref=[bi, ri], category=col(row, hdr, "Category"),
            ptp_date=parse_date(col(row, hdr, "PTP Date")), ptp_amount=money(col(row, hdr, "PTP Amount")),
            note=col(row, hdr, "Note (for supervisor review)"), action=col(row, hdr, "Action"),
            pmt=money(col(row, hdr, "PMT (excl. late fee)")),
            months=[{"month": h, "cell": month_cell(row[i]) if i < len(row) else None} for i, h in month_cols],
            total_paid=money(col(row, hdr, "Total Paid")), total_overdue=money(col(row, hdr, "Total Overdue")),
            total_outstanding=money(col(row, hdr, "Total Outstanding")),
        ))
    return summary, out


def cash_instalment(row, hdr, i):
    """(month cell, due date, still owed) for instalment Mn at column i.

    'Done - Cash' fills Mn's amount even when the instalment is unpaid, and the
    Status right after Mn says which it is (Paid / Late / Not Due / Link sent /
    Partial / Not issued), so that Status decides (DQ 2026-09-26 F06). 'Closed' there
    marks where the schedule ends, not a closed account: the customer's own Status
    says that. With no Status, an amount is a payment."""
    amount = cell(row, i)
    due = parse_date(cell(row, i - 1), day_first=True) if i and str(hdr[i - 1]).startswith("Due Date") else None
    word = (cell(row, i + 1) or "").strip().lower() if hdr[i + 1:i + 2] == ["Status"] else ""
    if not word:
        return month_cell(amount), due, not money(amount)
    if word == "paid":
        return month_cell(amount) or month_cell(word), due, False
    if word == "closed":
        return month_cell(amount), due, False
    return month_cell(cell(row, i + 1)), due, word != "terminated"


def read_cash_tab(bi, header, rows):
    hi, hdr = find_header(header, rows, ["VOLT ID", "Price", "DC Status"])
    if hdr is None:
        return []
    month_cols = [i for i, h in enumerate(hdr) if re.match(r"^M\d+$", h)]
    # 2026-09-25: the tab's first "Status" (before the instalment columns) is the
    # customer's own status; each "Status" after an Mn is that instalment's.
    word_col = hdr.index("Status") if "Status" in hdr and hdr.index("Status") < min(month_cols or [len(hdr)]) else None
    overdue_name = "Overdue" if "Overdue" in hdr else "Invoices Overdue"
    out = []
    for ri, row in enumerate(rows[hi + 1:]):
        volt_id = col(row, hdr, "VOLT ID")
        if not volt_id or "_" not in volt_id:
            continue
        instalments = [cash_instalment(row, hdr, i) for i in month_cols]
        out.append(OrderedDict(
            volt_id=volt_id, source_ref=[bi, ri], product="CASH",
            status_word=(cell(row, word_col) or "").strip() or None if word_col is not None else None,
            outstanding_amount=money(col(row, hdr, "OUTSTANDING AMOUNT")),
            sales_lead=col(row, hdr, "Sales Lead"), crm_id=col(row, hdr, "CRM ID"),
            order_status=col(row, hdr, "Order Status"), peak_url=col(row, hdr, "Peak URL"),
            # The cash tab writes dd/mm/yyyy (F14).
            contract_signed=parse_date(col(row, hdr, "Contract Signed"), day_first=True),
            installation_month=parse_date(col(row, hdr, "Installation Month"), day_first=True),
            first_payment_date=parse_date(col(row, hdr, "First Payment Date"), day_first=True),
            price=money(col(row, hdr, "Price")), dp_inc_vat=money(col(row, hdr, "DP  incl VAT")),
            cost_ex_vat=money(col(row, hdr, "Cost Total  ex VAT")),
            dc_status=col(row, hdr, "DC Status"), dc_comment=col(row, hdr, "DC Comment"),
            comment=col(row, hdr, "Comment"), overdue=money(col(row, hdr, overdue_name)),
            days_late=number(col(row, hdr, "Days Late")), late_fees=money(col(row, hdr, "Late Fees")),
            deposit_paid=col(row, hdr, "Deposit Paid"),
            months=[m for m, _due, _owed in instalments],
            # The first instalment still owed that has a due date.
            next_due_date=next((due for _m, due, owed in instalments if owed and due), None),
            ticket=OrderedDict(
                action_type=col(row, hdr, "Action Type"), responsible_team=col(row, hdr, "Responsible Team"),
                ticket_link=col(row, hdr, "Ticket Link"), deadline=col(row, hdr, "Deadline"),
                case_status=col(row, hdr, "Case Status"), remark=col(row, hdr, "Remark"),
            ),
        ))
    return out


def read_cash_invoices(bi, header, rows):
    hi, hdr = find_header(header, rows, ["Invoice Number", "PEAK Contact Code", "Days Overdue"])
    summary = []
    for r in rows:
        if len(r) >= 4 and r[0] and re.match(r"^\d+$", r[1] or "") and money(r[2]) and (r[3] or "").endswith("%"):
            summary.append({"dc_status": r[0], "invoices": number(r[1]), "outstanding": money(r[2])})
    if hdr is None:
        return summary, []
    out = []
    for ri, row in enumerate(rows[hi + 1:]):
        volt_id = col(row, hdr, "Volt ID (ID_Name)") or col(row, hdr, "Volt ID / Match")
        inv = col(row, hdr, "Invoice Number")
        if not inv or not inv.startswith("IV"):
            continue
        out.append(OrderedDict(
            volt_id=volt_id, source_ref=[bi, ri], priority=col(row, hdr, "Priority"),
            peak_contact_code=col(row, hdr, "PEAK Contact Code"), invoice_number=inv,
            instalment=col(row, hdr, "Invoice Installment") or col(row, hdr, "Installment"),
            amount=money(col(row, hdr, "Amount (THB)")), outstanding=money(col(row, hdr, "Amount Outstanding (THB)")),
            issued_on=parse_date(col(row, hdr, "Date Issued")), due_on=parse_date(col(row, hdr, "Due Date")),
            days_overdue=number(col(row, hdr, "Days Overdue")), status=col(row, hdr, "Status"),
            dc_note=col(row, hdr, "DC Note"), ptp_date=parse_date(col(row, hdr, "PTP Date")),
            ptp_amount=money(col(row, hdr, "PTP Amount")), paid=money(col(row, hdr, "PAID")),
            dc_status=col(row, hdr, "DC Status"),
            ticket=OrderedDict(
                action_type=col(row, hdr, "Action Type"), responsible_team=col(row, hdr, "Responsible Team"),
                ticket_link=col(row, hdr, "Ticket Link"), deadline=col(row, hdr, "Deadline"),
                case_status=col(row, hdr, "Case Status"), remark=col(row, hdr, "Remark"),
            ),
        ))
    return summary, out


def read_assets(bi, header, rows):
    hi, hdr = find_header(header, rows, ["VOLT ID", "Panel Brand", "Inverter Serial"])
    if hdr is None:
        return []
    out = []
    for ri, row in enumerate(rows[hi + 1:]):
        volt_id = col(row, hdr, "VOLT ID")
        if not volt_id or "_" not in volt_id:
            continue
        out.append(OrderedDict(
            volt_id=volt_id, source_ref=[bi, ri], active=col(row, hdr, "Active in Collection"),
            order_type=col(row, hdr, "Order Type"), system_kwp=money(col(row, hdr, "System Size (kWp)")),
            panel_serial=col(row, hdr, "Panel Serial Num."), panel_brand=col(row, hdr, "Panel Brand"),
            panels=number(col(row, hdr, "Number of Panels")), inverter_serial=col(row, hdr, "Inverter Serial"),
            inverter_brand=col(row, hdr, "Inverter Brand"), inverter_kwp=money(col(row, hdr, "Inverter KWP")),
            battery=col(row, hdr, "Battery"), npv_ex_vat=money(col(row, hdr, "NPV ex VAT")),
            cost_ex_vat=money(col(row, hdr, "Cost  ex VAT")),
        ))
    return out


def read_orders(bi, header, rows):
    hi, hdr = find_header(header, rows, ["Order Status", "Volt ID", "EPC Start Date"])
    # Tab x itself has no Phone column (DQ 2026-09-26 F01): its Order Type is what
    # tells an order tab from 'Licensing VOLT', which shares the three names above.
    if hdr is None or ("Phone" not in hdr and "Order Type" not in hdr):
        return []
    out = []
    for ri, row in enumerate(rows[hi + 1:]):
        volt_id = col(row, hdr, "Volt ID")
        if not volt_id or "_" not in volt_id:
            continue
        out.append(OrderedDict(
            volt_id=volt_id, source_ref=[bi, ri], no=number(col(row, hdr, "No")),
            sales_lead=col(row, hdr, "Sales Lead"), order_type=col(row, hdr, "Order Type"),
            order_status=col(row, hdr, "Order Status"), loan_status=col(row, hdr, "Loan Status"),
            submit_date=parse_date(col(row, hdr, "Submit Date")),
            contract_signed_date=parse_date(col(row, hdr, "Contract Signed Date")),
            dp_pct=col(row, hdr, "DP %"), dp_amount=money(col(row, hdr, "DP Amount")),
            monthly_rate_inc_vat=money(col(row, hdr, "Monthly Rate, INC VAT")), term=number(col(row, hdr, "Term")),
            phone_masked=mask_phone(col(row, hdr, "Phone")), phone_e164=e164(col(row, hdr, "Phone")),
            email_masked=mask_email(col(row, hdr, "Email")),
            crm_id=col(row, hdr, "CRM ID"), peak_id=col(row, hdr, "Peak ID"), odoo_id=col(row, hdr, "Odoo ID"),
            project_type=col(row, hdr, "Project Type"), watt=number(col(row, hdr, "Watt")),
            epc=col(row, hdr, "EPC"), epc_start_date=parse_date(col(row, hdr, "EPC Start Date")),
            epc_end_date=parse_date(col(row, hdr, "EPC End Date")), province=col(row, hdr, "Province"),
        ))
    return out


def read_pivot(bi, header, rows):
    hi, hdr = find_header(header, rows, ["Payment Status", "NPL Type", "COUNTA of VOLT ID"])
    if hdr is None:
        return []
    out = []
    for row in rows[hi + 1:]:
        if len(row) >= 6 and row[0] and number(row[5]) is not None:
            out.append({"payment_status": row[0], "npl_type": row[1] or None, "count": number(row[5])})
    return out


def read_flow_stages(bi, header, rows):
    hi, hdr = find_header(header, rows, ["Monthly Payments", "Timeframe", "Repercussion"])
    if hdr is None:
        return {"stages": [], "late_fee_logic": []}
    stages, logic = [], []
    for row in rows[hi + 1:]:
        if len(row) > 3 and row[1] and row[3]:
            stages.append({"step": row[0] or None, "name": row[1], "description": row[2], "timeframe": row[3],
                           "responsible": row[4] if len(row) > 4 else None, "tools": row[5] if len(row) > 5 else None,
                           "action": row[6] if len(row) > 6 else None, "action_date": row[7] if len(row) > 7 else None,
                           "repercussion": row[8] if len(row) > 8 else None})
        elif len(row) > 1 and row[1] and re.match(r"^(Late fee|Unpaid|The monthly|For the first|In subsequent|Month \d|M\d)", row[1] or ""):
            logic.append(" ".join(c for c in row if c))
    return {"stages": stages, "late_fee_logic": logic}


# --- main ------------------------------------------------------------------------

def main(src, out_path):
    text = open(src, encoding="utf-8").read()
    warnings = []
    leasing, cash, cash_invoices, assets, orders = [], [], [], [], []
    tracking_summary, tracking_rows, cash_summary, pivot, flow = [], [], [], [], {}
    roster = []
    blocks_seen = []
    for bi, header, rows in blocks(text):
        kind = None
        if find_header(header, rows, ["VOLT ID", "Payment Status"])[1] is not None:
            got = read_leasing_block(bi, header, rows, warnings)
            if got:
                leasing.extend(got); kind = "LEASING_BOOK"
        if kind is None and find_header(header, rows, ["VOLT ID", "Price", "DC Status"])[1] is not None:
            cash.extend(read_cash_tab(bi, header, rows)); kind = "CASH_TAB"
        if kind is None and find_header(header, rows, ["Invoice Number", "PEAK Contact Code", "Days Overdue"])[1] is not None:
            s, r = read_cash_invoices(bi, header, rows); cash_summary.extend(s); cash_invoices.extend(r); kind = "CASH_INVOICES"
        if kind is None and find_header(header, rows, ["VOLT ID", "Category", "Total Overdue"])[1] is not None:
            s, r = read_collection_tracking(bi, header, rows); tracking_summary.extend(s); tracking_rows.extend(r); kind = "COLLECTION_TRACKING"
        if kind is None and find_header(header, rows, ["VOLT ID", "Panel Brand", "Inverter Serial"])[1] is not None:
            assets.extend(read_assets(bi, header, rows)); kind = "ASSET_REGISTER"
        if kind is None and find_header(header, rows, ["Order Status", "Volt ID", "EPC Start Date"])[1] is not None:
            got = read_orders(bi, header, rows)
            if got:
                orders.extend(got); kind = "ORDER_MASTER"
        if kind is None and find_header(header, rows, ["Payment Status", "NPL Type", "COUNTA of VOLT ID"])[1] is not None:
            pivot.extend(read_pivot(bi, header, rows)); kind = "PAYMENT_STATUS_PIVOT"
        if kind is None and find_header(header, rows, ["Monthly Payments", "Timeframe", "Repercussion"])[1] is not None:
            flow = read_flow_stages(bi, header, rows); kind = "FLOW_STAGES"
        if kind is None and len(header) == 2 and len(rows) > 300:
            roster = [{"sales_lead": r[0], "volt_id": r[1]} for r in rows if len(r) == 2 and r[1] and "_" in r[1]]
            kind = "ROSTER"
        blocks_seen.append({"block": bi, "kind": kind, "rows": len(rows), "cols": len(header)})

    payload = assemble_payload(leasing, cash, cash_invoices, tracking_summary, tracking_rows, assets,
                               orders, roster, pivot, flow, warnings, blocks_seen, cash_summary)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    customers = payload["customers"]
    print("customers=%d leasing_rows=%d cash=%d cash_invoices=%d assets=%d orders=%d contact_log=%d warnings=%d -> %s" % (
        len(customers), len(leasing), len(cash), len(cash_invoices), len(assets), len(orders),
        sum(len(c["contact_log"]) for c in customers), len(warnings), out_path))
    print("counts:", payload["counts"])


# The debt team's two live tabs (Arina, 2026-09-25). Every tab is still read, but a
# VOLT ID these tabs carry takes its contract and status from here, never from an
# older copy ('Done - Cash Old', 'Absolete collection', a backup).
DONE_TABS = ("done - collection", "done - cash")
# Tab x is the order master: its order wins over an older copy ('Copy of x',
# 'Customer BL') of the same VOLT ID (DQ 2026-09-26 F01).
ORDER_TAB = "x"


def _tab(rec):
    ref = rec.get("source_ref")
    sheet = ref.get("sheet") if isinstance(ref, dict) else None
    return sheet.strip().lower() if isinstance(sheet, str) else None


def _done(rec):
    return _tab(rec) in DONE_TABS


def assemble_payload(leasing, cash, cash_invoices, tracking_summary, tracking_rows, assets, orders,
                     roster, pivot, flow, warnings, blocks_seen, cash_summary=()):
    """The classified tab rows -> the book payload (fixtures_sheet.json's shape). The
    CLI and the upload door (backend/app/imports.py) both call this, so a sheet read
    from a Drive render and one uploaded as .xlsx become the same book."""
    # One customer per VOLT ID; the latest snapshot wins on money, every snapshot
    # keeps its source_ref, and MapLog rows are merged across snapshots by timestamp.
    customers = OrderedDict()

    def touch(volt_id, product):
        if volt_id not in customers:
            ident = split_volt_id(volt_id)
            customers[volt_id] = OrderedDict(
                volt_id=volt_id, customer_no=ident["customer_no"], name_roman=ident["name_roman"],
                name_th=ident["name_th"], epc=ident["epc"], product=product,
                sales_lead=None, phone_masked=None, phone_e164=None, email_masked=None, source_refs=[],
                leasing=None, cash=None, cash_invoices=[], tracking=None, asset=None, order=None,
                contact_log=[],
            )
        return customers[volt_id]

    for rec in leasing:
        c = touch(rec["volt_id"], "LEASE")
        c["source_refs"].append(rec["source_ref"])
        c["sales_lead"] = c["sales_lead"] or rec["sales_lead"]
        # 'Done - Collection' wins (Arina, 2026-09-25); otherwise keep the fullest
        # snapshot: the one with term data, else the one with more month cells
        cur = c["leasing"]
        if cur is None or _done(rec) > _done(cur) or _done(rec) == _done(cur) and (
                (rec["term_original"] and not cur.get("term_original")) or
                len([m for m in rec["months"] if m]) > len([m for m in cur["months"] if m])):
            c["leasing"] = rec
        seen = {(e["occurred_at"], e["officer"]) for e in c["contact_log"]}
        for e in rec["maplog"]:
            if (e["occurred_at"], e["officer"]) not in seen:
                c["contact_log"].append(dict(e, source_ref=rec["source_ref"]))
                seen.add((e["occurred_at"], e["officer"]))
    for rec in cash:
        c = touch(rec["volt_id"], "CASH"); c["source_refs"].append(rec["source_ref"])
        c["sales_lead"] = c["sales_lead"] or rec["sales_lead"]
        if c["cash"] is None or _done(rec) >= _done(c["cash"]):   # 'Done - Cash' wins, else the last read
            c["cash"] = rec
    for rec in cash_invoices:
        if rec["volt_id"] and "_" in rec["volt_id"]:
            c = touch(rec["volt_id"], "CASH"); c["source_refs"].append(rec["source_ref"]); c["cash_invoices"].append(rec)
    for rec in tracking_rows:
        c = touch(rec["volt_id"], "LEASE"); c["source_refs"].append(rec["source_ref"]); c["tracking"] = rec
    for rec in assets:
        c = touch(rec["volt_id"], "LEASE" if rec["order_type"] == "Leasing" else "CASH")
        c["source_refs"].append(rec["source_ref"]); c["asset"] = rec
    for rec in orders:
        c = touch(rec["volt_id"], "LEASE" if rec["order_type"] == "Leasing" else "CASH")
        c["source_refs"].append(rec["source_ref"])
        if c["order"] is None or _tab(rec) == ORDER_TAB or _tab(c["order"]) != ORDER_TAB:
            c["order"] = rec
        if rec["phone_masked"] or rec["phone_e164"]:   # x carries no Phone or Email: a copy's stay
            c["phone_masked"], c["phone_e164"] = rec["phone_masked"], rec["phone_e164"]
        c["email_masked"] = rec["email_masked"] or c["email_masked"]
    for r in roster:
        if r["volt_id"] in customers and not customers[r["volt_id"]]["sales_lead"]:
            customers[r["volt_id"]]["sales_lead"] = r["sales_lead"]
    for c in customers.values():
        c["contact_log"].sort(key=lambda e: e["occurred_at"])
        # Lease or cash (DQ 2026-09-26 F02): the Done tab carrying the customer says,
        # else x's Order Type. The tab a VOLT ID was first seen on does not: a
        # leasing-shaped tab made 291 cash customers leases.
        c["product"] = ("LEASE" if _done(c["leasing"] or {}) else "CASH" if _done(c["cash"] or {}) else
                        {"Leasing": "LEASE", "Cash": "CASH"}.get((c["order"] or {}).get("order_type"))) or c["product"]

    counts = Counter()
    for c in customers.values():
        ps = (c["leasing"] or {}).get("payment_status") or (c["tracking"] or {}).get("category")
        counts["%s/%s" % (c["product"], ps or "unknown")] += 1

    return OrderedDict(
        source=OrderedDict(
            spreadsheet="New Order Master", spreadsheet_id="SYNTHETIC-SPREADSHEET-ID",
            render="Drive MCP text render, truncated per tab (see blocks)",
            pii="phone kept whole for the dial actions (hidden at the serving layer, audited reveal); email masked; names, VOLT IDs, amounts, statuses and notes kept",
            blocks=blocks_seen,
        ),
        pivots=OrderedDict(payment_status=list(pivot), collection_tracking=list(tracking_summary),
                           cash_invoices=list(cash_summary)),
        flow_stages=flow,
        counts=dict(counts),
        warnings=warnings,
        customers=list(customers.values()),
    )


def to_postgres(payload):
    """Write an already-parsed payload into the landing schema.

    Imported lazily and only on this path, so the parser keeps running on a machine
    with no database and no SQLAlchemy — which is how it has always been run.
    """
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app import db, sheet_loader
    if not db.configured():
        raise SystemExit("DATABASE_URL is not set — nothing to write to")
    conn = db.connect()
    try:
        with conn.begin():
            result = sheet_loader.load_payload(conn, payload)
    finally:
        conn.close()
    print("landing: run=%(import_run_id)d customers=%(customers)d "
          "orders=%(orders)d blocks=%(blocks)d" % result)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0], args[1])
    if "--to-postgres" in sys.argv:
        with open(args[1], encoding="utf-8") as handle:
            to_postgres(json.load(handle))
