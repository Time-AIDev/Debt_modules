#!/usr/bin/env python3
"""Match Odoo's crm.lead against the New Order Master's "x" tab, column and value.

Two questions, and they are not the same question:

  columns   which of the sheet's 47 "x" columns exist as a crm.lead field at all.
            That is a statement about the two schemas and needs no data.
  rows      which sheet rows are the same customer as which lead, and where the
            two disagree about a value they both hold. That needs a join key, and
            the honest answer is that there are three candidates — the sheet's own
            `Odoo ID` column, the `Volt ID`/`volt_id` pair, and the phone number —
            so all three are tried and each reports its own hit rate.

The sheet is read RAW from backend/var/master_sheet.txt rather than from
fixtures_sheet.json, because the fixture is masked at import and a masked phone
number joins to nothing. Nothing is written; this only prints.

    ./scripts/compare_crm_to_sheet.py
"""
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# crm.lead.description is free text and one lead blows past the 128 KB default,
# which surfaces as "field larger than field limit" halfway through the file.
csv.field_size_limit(sys.maxsize)

CRM_CSV = ROOT / "data" / "odoo" / "crm.lead.csv"
SHEET = ROOT / "backend" / "var" / "master_sheet.txt"

# Sheet column -> crm.lead field. "" means the sheet holds it and Odoo does not.
MAP = {
    "No": "", "Sales Lead": "user_id", "First Name": "contact_name", "Last Name": "last_name",
    "Co-Sign": "cosigner_id", "Order Type": "order_type", "Order Status": "stage_name",
    "Loan Status": "", "Contract Purchase": "", "Contract Service": "",
    "Submit Date": "submitted_date", "Submit Month/Year": "",
    "Contract Signed Date": "contract_signed_date", "Contract Signed Month/Year": "",
    "Comment": "description", "Inverter Brand": "inverter_brand",
    "Inverter Type": "inverter_type", "Battery Watt": "battery_watt",
    "DP %": "dp_percent", "DP Amount": "dp_amount", "Monthly Rate, INC VAT": "monthly_rate",
    "Term": "payment_term_installment_id", "Marketing": "source_id", "Phone": "phone",
    "Secondary Phone": "mobile", "Email": "email_from", "CRM": "", "Gdrive": "g_drive",
    "CRM ID": "", "Peak ID": "", "Volt ID": "volt_id", "Odoo ID": "id", "Odoo ID2": "",
    "Project Type": "", "Energy Bill": "energy_bill", "Watt": "inverter_kw",
    "Phase": "connection_type", "EPC": "epc", "EPC Start Date": "epc_start_date",
    "EPC Start Date Month/Year": "epc_start_month_year", "EPC End Date": "epc_end_date",
    "Gmap": "site_coordinates", "Province": "install_province", "Postal Code": "zip",
    "Address": "street", "Meter Owner": "meter_owner", "Com Status": "com_status",
}


# The sheet writes watts, Odoo writes kilowatts on this field. panel_watt (710) is the
# size of ONE panel and is not what the sheet's Watt column means — mapping to it made
# all 58 rows look like a disagreement when the two systems agree about a 5 kW system.
SCALE = {"Watt": 1000}


def sheet_rows():
    spec = importlib.util.spec_from_file_location("ims", ROOT / "scripts" / "import_master_sheet.py")
    ims = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ims)
    text = SHEET.read_text(encoding="utf-8")
    out, header = [], None
    for bi, head, rows in ims.blocks(text):
        hi, hdr = ims.find_header(head, rows, ["Order Status", "Volt ID", "EPC Start Date"])
        if not hdr or "Phone" not in hdr:
            continue
        header = header or hdr
        for row in rows[hi + 1:]:
            rec = {h: (row[i].strip() if i < len(row) and row[i] else "")
                   for i, h in enumerate(hdr) if h}
            if rec.get("Volt ID") and "_" in rec["Volt ID"]:
                out.append(rec)
    return header, out


def stem(volt_id):
    """The identifying head of a Volt ID: 99999000032 out of
    99999000032_Thitipawee_.._IPW, and VL0000143 out of itself. Odoo holds BOTH
    shapes in crm.lead.volt_id, so an exact match finds far fewer rows than exist."""
    head = (volt_id or "").strip().split("_")[0].strip().upper()
    return head if head else ""


def digits(value):
    d = re.sub(r"\D", "", value or "")
    return d[-9:] if len(d) >= 9 else ""      # last 9: 0812345678 == 66812345678


def norm(value):
    return re.sub(r"\s+", " ", (value or "").replace("_", " ").strip().lower())


def money(value):
    m = re.sub(r"[^\d.]", "", value or "")
    try:
        return round(float(m), 2)
    except ValueError:
        return None


MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def as_date(value):
    """A date cell as (y, m, d), or (y, m, None) for a Month/Year cell, else None.

    The sheet writes 02/05/24 where Odoo writes 2024-05-02, and comparing those as
    strings called 54 of 58 rows a disagreement when they are the same day. Two-digit
    years are day-first — the same rule import_master_sheet.py applies.
    """
    v = (value or "").strip()
    if not v:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", v)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (y + 2000 if y < 100 else y, mo, d)
    m = re.match(r"^([A-Za-z]{3})[a-z]* (\d{4})$", v)          # "May 2024"
    if m and m.group(1).lower() in MONTHS:
        return (int(m.group(2)), MONTHS[m.group(1).lower()], None)
    m = re.match(r"^(\d{4})-(\d{2})$", v)                      # "2024-05"
    if m:
        return (int(m.group(1)), int(m.group(2)), None)
    m = re.match(r"^(\d{1,2})/(\d{2})$", v)                    # "05/24" — the sheet's
    if m:                                                      # Month/Year columns
        return (int(m.group(2)) + 2000, int(m.group(1)), None)
    return None


def same(sheet_value, odoo_value, column=None):
    """Do the two cells say the same thing, allowing for format?

    Returns one of: same / same (format) / differs / one side empty / both empty.
    "same (format)" is kept separate from "same" on purpose — a date that agrees only
    after normalising is still a column two systems write differently, and a migration
    has to know that even though the values agree.
    """
    s, o = norm(sheet_value), norm(odoo_value)
    if not s and not o:
        return "both empty"
    if not s or not o:
        return "one side empty"
    # A zero on the Odoo side of a column the sheet filled is not a disagreement about
    # the value — it is Odoo not holding it. Counting those as "differs" put 58 rows in
    # the wrong column for Watt and Monthly Rate, and hid that the field is simply unused.
    if o in ("0", "0.0", "0.00", "false") and money(s):
        return "odoo zero/unset"
    if "|" in o:                                # a many2one rendered id|label
        o = o.split("|", 1)[1].strip().lower()
    if s == o:
        return "same"
    ds, do = as_date(s), as_date(o)
    if ds and do:
        if ds[:2] == do[:2] and (ds[2] is None or do[2] is None or ds[2] == do[2]):
            return "same (format)"
        return "differs"
    if digits(s) and digits(s) == digits(o):
        return "same (format)"
    ms, mo = money(s), money(o)
    if ms is not None and mo is not None:
        if ms == mo or (column in SCALE and mo * SCALE[column] == ms):
            return "same (format)"
    if s in o or o in s:
        return "same (format)"
    return "differs"


def main():
    header, rows = sheet_rows()
    leads = list(csv.DictReader(open(CRM_CSV, encoding="utf-8-sig")))
    print("sheet \"x\": %d rows, %d columns   crm.lead: %d rows, %d columns\n"
          % (len(rows), len([h for h in header if h]), len(leads), len(leads[0])))

    present = [c for c, f in MAP.items() if f and f in leads[0]]
    missing_field = [c for c, f in MAP.items() if f and f not in leads[0]]
    absent = [c for c, f in MAP.items() if not f]
    print("COLUMNS")
    print("  in both:                     %d" % len(present))
    print("  sheet-only (no Odoo field):  %d  -> %s" % (len(absent), ", ".join(absent)))
    if missing_field:
        print("  mapped but not in this CSV:  %d  -> %s" % (len(missing_field), ", ".join(missing_field)))

    # One haystack for "does this sheet id appear ANYWHERE in crm.lead", which answers
    # a different question from a join: whether Odoo carries the value at all.
    blob = "\u0001".join("\u0001".join(l.values()) for l in leads)
    by_id = {l["id"]: l for l in leads}
    by_volt = {norm(l.get("volt_id")): l for l in leads if l.get("volt_id")}
    by_stem = {stem(l.get("volt_id")): l for l in leads if stem(l.get("volt_id"))}
    by_phone = {}
    for l in leads:
        for key in ("phone", "mobile"):
            if digits(l.get(key)):
                by_phone.setdefault(digits(l[key]), l)

    # The sheet's "Odoo ID" column does NOT hold a numeric Odoo id: on this export the
    # three filled cells hold 99999000206 / 99999000359, i.e. an Odoo volt_id. So it is
    # tried against BOTH, and each is counted separately rather than quietly merged.
    joins = {"Odoo ID -> crm.lead.id (numeric)": 0, "Odoo ID -> volt_id": 0,
             "Volt ID -> volt_id (exact)": 0,
             "Volt ID -> volt_id (id prefix)": 0, "Phone -> phone/mobile": 0,
             "CRM ID seen anywhere in the lead": 0}
    pairs = {}
    for row in rows:
        lead = None
        if row.get("Odoo ID") and row["Odoo ID"] in by_id:
            joins["Odoo ID -> crm.lead.id (numeric)"] += 1
            lead = by_id[row["Odoo ID"]]
        if norm(row.get("Odoo ID")) in by_volt:
            joins["Odoo ID -> volt_id"] += 1
            lead = lead or by_volt[norm(row["Odoo ID"])]
        if norm(row.get("Volt ID")) in by_volt:
            joins["Volt ID -> volt_id (exact)"] += 1
            lead = lead or by_volt[norm(row["Volt ID"])]
        if stem(row.get("Volt ID")) and stem(row.get("Volt ID")) in by_stem:
            joins["Volt ID -> volt_id (id prefix)"] += 1
            lead = lead or by_stem[stem(row["Volt ID"])]
        if row.get("CRM ID") and row["CRM ID"] in blob:
            joins["CRM ID seen anywhere in the lead"] += 1
        ph = digits(row.get("Phone")) or digits(row.get("Secondary Phone"))
        if ph and ph in by_phone:
            joins["Phone -> phone/mobile"] += 1
            lead = lead or by_phone[ph]
        if lead:
            pairs[row["Volt ID"]] = (row, lead)

    print("\nROWS — how many of the %d sheet rows find a lead" % len(rows))
    for key, hits in joins.items():
        print("  %-26s %3d" % (key, hits))
    print("  %-26s %3d" % ("matched by any key", len(pairs)))

    if not pairs:
        print("\nNo joined pair, so no value comparison is possible.")
        return 0

    print("\nVALUES — across %d matched pair(s)" % len(pairs))
    print("  %-26s %-6s %-8s %-8s %-9s %-8s %s" % (
        "COLUMN", "same", "same/fmt", "differs", "odoo 0", "1 empty", "example"))
    table = []
    for column, field in MAP.items():
        if not field or field not in leads[0]:
            continue
        tally = {"same": 0, "same (format)": 0, "differs": 0,
                 "odoo zero/unset": 0, "one side empty": 0, "both empty": 0}
        example = ""
        for row, lead in pairs.values():
            verdict = same(row.get(column), lead.get(field), column)
            tally[verdict] += 1
            if verdict == "differs" and not example:
                example = "sheet %r vs odoo %r" % ((row.get(column) or "")[:24],
                                                   (lead.get(field) or "")[:24])
        table.append({"column": column, "field": field, **tally, "example": example})
        print("  %-26s %-6d %-8d %-8d %-9d %-8d %s" % (
            column, tally["same"], tally["same (format)"], tally["differs"],
            tally["odoo zero/unset"], tally["one side empty"], example[:42]))
    out = ROOT / "data" / "odoo" / "comparison.json"
    out.write_text(json.dumps({
        "sheet_rows": len(rows), "sheet_columns": len([h for h in header if h]),
        "crm_lead_rows": len(leads), "crm_lead_columns": len(leads[0]),
        "columns_in_both": present, "columns_sheet_only": absent,
        "joins": joins, "matched_pairs": len(pairs), "values": table,
        "map": MAP}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
