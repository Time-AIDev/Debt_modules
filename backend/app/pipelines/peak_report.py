"""The PEAK invoice report ("รายงานใบแจ้งหนี้"), parsed into invoice records.

Feedback Round 1 / WP1 (vault note 10 §2.1, §3). Measured on the 2026-09-14 export:
7,999 lines, 7,638 invoices, header on row 11, 56 columns, three headings repeated.

Pure: bytes in, records out. No clock, no database, no network. The reader is
app.imports (ruling 36: never a second csv/xlsx parser).

Missing debt-defining headings refuse the whole file by exact name, while identity
and descriptive columns may be omitted by PEAK's export checklist. Duplicate
headings are resolved by their section: notably the received amount follows the
payment date, rather than the newer withholding amount with the same label. An
unknown status rejects that row instead of guessing. An unreadable date or amount
rejects its whole document (fix-all P8): never a Buddhist-era year read as 2569,
never an unreadable amount read as nothing owed.
"""
import csv
import io
import re
from decimal import Decimal, InvalidOperation

from .. import imports as imports_domain
from .. import parsing

REQUIRED_FIELDS = ("doc_no", "status_th", "amount_awaiting", "due_on")
ALIASES = {}
FIRST_FIELDS = ("doc_no",)

STATUS_MAP = {"รับชำระแล้ว": "PAID", "เกินเวลารับชำระ": "OVERDUE", "รอชำระ": "AWAITING",
              "ร่าง": "DRAFT", "ยกเลิก": "CANCELLED"}
RECEIPT_DOC_KINDS = ("RE", "RT")

# Column heading -> record key. Unanchored repeated headings take their first index;
# fields in COLUMN_AFTER use their report section instead.
COLUMNS = {
    "เลขที่เอกสาร": "doc_no", "วันที่ออก": "issued_on", "วันที่ครบกำหนด": "due_on",
    "อ้างอิง": "reference", "อ้างอิงจากระบบ": "system_reference", "สถานะ": "status_th",
    "รหัสผู้ติดต่อ": "contact_code", "ชื่อลูกค้า": "customer_name", "เลขที่ 13 หลัก": "tax_id_13",
    "รายการที่": "line_no", "รหัสสินค้า/บริการ": "product_code", "ชื่อสินค้า/บริการ": "product_name",
    "คำอธิบาย": "description", "ราคา": "price", "ทั้งหมด": "amount_total", "ต้องชำระ": "amount_due",
    "มูลค่ารอรับชำระ": "amount_awaiting", "วันที่": "paid_on", "ช่องทางการชำระเงิน": "paid_channel",
    "จำนวนเงิน": "paid_amount", "เลขที่ใบเสร็จ": "receipt_no", "กลุ่มย่อย": "product_group",
    "หมายเหตุ": "note",
}

# PEAK's wider exports add another เลขที่เอกสาร / จำนวนเงิน pair for withholding.
# The payment amount is the occurrence after the payment date, not the first heading
# with the same text. Optional identity columns deliberately have no entry here: an
# unchecked export column makes the row reviewable/unmatched, not unreadable.
COLUMN_AFTER = {"paid_amount": "วันที่"}

_RANGE = re.compile(r"export_as_of_(\d{4})(\d{2})(\d{2})_(\d{4})(\d{2})(\d{2})")
_STAMP = re.compile(r"export_as_of_\d{8}_\d{8}_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})")
_CYCLE = re.compile(r"M\s?(\d+)\s*/\s*(\d+)")


class ReportError(Exception):
    def __init__(self, code, detail, detail_th, missing=(), schema=None):
        super().__init__(detail)
        self.code, self.detail, self.detail_th = code, detail, detail_th
        self.missing = tuple(missing)
        # Header-only diagnostics are safe to return to the browser. Never put row
        # values in here: a failed upload may contain names, tax ids or notes.
        self.schema = schema or {}


class Unreadable(ValueError):
    """A non-empty date or amount cell that does not parse; `group` rejects its document."""

    def __init__(self, code, value):
        super().__init__(code)
        self.code, self.value = code, value


def report_range(filename):
    """PEAK names the export "…export_as_of_<from>_<to>_<stamp>.xlsx". <to> is the
    day it is true for; <from> is how far back it reaches. A report reaching back
    less far is not a replacement. (None, None) when the name does not say."""
    m = _RANGE.search(filename or "")
    if not m:
        return (None, None)
    g = m.groups()
    return ("%s-%s-%s" % g[0:3], "%s-%s-%s" % g[3:6])


def report_as_of(filename):
    stamp = export_timestamp(filename)
    return stamp[:10] if stamp else report_range(filename)[1]


def export_timestamp(filename):
    """The third date/time in PEAK's filename is when it was actually exported.

    The second date is the selected coverage end and may be in the future.  It must
    never be used as data freshness when the real export stamp is present.
    """
    m = _STAMP.search(filename or "")
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    return "%s-%s-%sT%s:%s:%s" % (y, mo, d, hh, mm, ss)


def _table(raw):
    if raw.startswith(b"\x00\x00"):
        raise ReportError("unreadable", "temporary Excel owner file", "ไฟล์ล็อกของ Excel — ส่งออกไฟล์รายงานใหม่")
    kind = imports_domain.sniff_kind(raw)
    if kind == "XLSX":
        try:
            tabs = imports_domain.read_xlsx(raw)
            return [list(r) for r in (tabs[0]["rows"] if tabs else [])]
        except imports_domain.UploadRefused as exc:
            raise ReportError("unreadable", exc.message, exc.message_th)
    if kind == "OLE":
        raise ReportError("unreadable", "legacy .xls or a password-protected workbook",
                          "ไฟล์เป็น .xls เก่าหรือติดรหัสผ่าน — ส่งออกเป็น .xlsx หรือ .csv")
    try:
        _enc, text = imports_domain.decode_csv(raw)
        return list(csv.reader(io.StringIO(text)))
    except imports_domain.UploadRefused as exc:
        raise ReportError("unreadable", exc.message, exc.message_th)
    except csv.Error:
        raise ReportError("unreadable", "the CSV structure is unreadable",
                          "อ่านโครงสร้างไฟล์ CSV ไม่ได้ — ส่งออกจาก PEAK ใหม่แล้วลองอีกครั้ง") from None


def _cell(row, i):
    if i is None or i >= len(row) or row[i] is None:
        return ""
    return str(row[i]).strip()


def _normalise_heading(value):
    """Compare PEAK headings independently of Excel wrapping and non-breaking spaces."""
    return re.sub(r"\s+", "", str(value or "").replace("\ufeff", ""))


def _find_header(table, columns=COLUMNS):
    """Find the strongest PEAK-looking row without requiring every checked column.

    Requiring the complete schema here made an omitted optional column look as if the
    workbook had no header at all. Required fields are validated after contextual
    duplicate resolution, so the error can name only what is actually missing.
    """
    known = {_normalise_heading(name) for name in columns}
    candidates = []
    # PEAK exports put headings near the top (normally row 11). Limiting the scan
    # prevents a wide data row from being normalised thousands of times before a
    # malformed workbook is rejected.
    for i, row in enumerate(table[:100]):
        cells = [str(c).strip() if c is not None else "" for c in row]
        score = sum(1 for cell in cells if _normalise_heading(cell) in known)
        if score >= 3:
            candidates.append((score, -i, i, cells))
    if candidates:
        _score, _first, i, cells = max(candidates)
        return i, cells
    raise ReportError("header_not_found", "no PEAK report header row was found",
                      "ไม่พบแถวหัวตารางของรายงาน PEAK")


def schema_contract(report_type, columns, required_fields, aliases=None, after=None, first_fields=()):
    """The public, deterministic contract used by both parser and upload screen."""
    aliases, after = aliases or {}, after or {}
    by_field = {field: heading for heading, field in columns.items()}

    def field_spec(field):
        return {"field": field, "heading": by_field[field], "aliases": list(aliases.get(field) or [])}

    required = [field_spec(field) for field in required_fields]
    optional = [field_spec(field) for field in by_field if field not in required_fields]
    bindings = {field: {"strategy": "after", "after": heading} for field, heading in after.items()}
    bindings.update({field: {"strategy": "first"} for field in first_fields})
    return {"report_type": report_type, "required": required, "optional": optional,
            "aliases": {field: list(values) for field, values in aliases.items()},
            "contextual_bindings": bindings}


def _resolve_columns(cells, columns=COLUMNS, required_fields=REQUIRED_FIELDS, aliases=None,
                     after=None, first_fields=(), report_type="invoice"):
    """Resolve canonical fields and return header-only diagnostics.

    A repeated required heading is not guessed unless the report contract declares
    how to bind it. Optional repetitions keep their first occurrence and are called
    out in diagnostics, because they do not define whether a debt can be read.
    """
    positions = {}
    for pos, name in enumerate(cells):
        positions.setdefault(_normalise_heading(name), []).append(pos)
    aliases, after = aliases or {}, after or {}
    first_fields = set(first_fields or ())
    resolved = {}
    ambiguous = []
    binding_details = {}
    for heading, key in columns.items():
        headings = [heading] + list(aliases.get(key) or [])
        choices = sorted({pos for name in headings for pos in positions.get(_normalise_heading(name), [])})
        anchor = after.get(key)
        if choices and anchor:
            anchor_positions = positions.get(_normalise_heading(anchor), [])
            if anchor_positions:
                choices = [pos for pos in choices if pos > anchor_positions[-1]]
            elif len(choices) > 1:
                choices = []
            strategy = "after"
        elif key in first_fields:
            strategy = "first"
        else:
            strategy = "exact"
            if key in required_fields and len(choices) > 1:
                ambiguous.append(key)
                choices = []
        resolved[key] = choices[0] if choices else None
        if resolved[key] is not None:
            binding_details[key] = {"heading": heading, "column": resolved[key] + 1, "strategy": strategy}
            if anchor:
                binding_details[key]["after"] = anchor

    known = {_normalise_heading(name) for name in columns}
    for values in aliases.values():
        known.update(_normalise_heading(name) for name in values)
    ignored = []
    for value in cells:
        label = str(value or "").strip()
        if label and _normalise_heading(label) not in known and label not in ignored:
            ignored.append(label)
    duplicates = []
    for normalised, indexes in positions.items():
        if normalised and len(indexes) > 1:
            label = next((str(cells[i]).strip() for i in indexes if str(cells[i]).strip()), normalised)
            duplicates.append({"heading": label, "columns": [i + 1 for i in indexes]})
    optional = [field for field in resolved if field not in required_fields and resolved[field] is None]
    warnings = []
    if optional:
        warnings.append("optional_fields_missing")
    if ignored:
        warnings.append("extra_columns_ignored")
    if duplicates:
        warnings.append("duplicate_headings_present")
    if ambiguous:
        warnings.append("ambiguous_required_fields")
    diagnostics = {
        "report_type": report_type,
        "header_row": None,
        "detected_fields": [field for field, pos in resolved.items() if pos is not None],
        "missing_required_fields": [field for field in required_fields if resolved.get(field) is None],
        "missing_optional_fields": optional,
        "ignored_headings": ignored,
        "duplicate_headings": duplicates,
        "ambiguous_required_fields": ambiguous,
        "bindings": binding_details,
        "warnings": warnings,
    }
    return resolved, diagnostics


def _require_columns(resolved, required_fields, columns, diagnostics=None):
    heading_by_field = {field: heading for heading, field in columns.items()}
    diagnostics = diagnostics or {}
    ambiguous = diagnostics.get("ambiguous_required_fields") or []
    if ambiguous:
        names = tuple(heading_by_field[field] for field in ambiguous)
        raise ReportError(
            "schema_ambiguous_header",
            "ambiguous required PEAK columns: %s" % ", ".join(names),
            "พบคอลัมน์หลักซ้ำและระบุตำแหน่งไม่ได้: %s" % ", ".join(names),
            schema=diagnostics,
        )
    missing = tuple(heading_by_field[field] for field in required_fields if resolved.get(field) is None)
    if missing:
        raise ReportError(
            "missing_required_columns",
            "missing required PEAK columns: %s" % ", ".join(missing),
            "ไฟล์ขาดคอลัมน์หลัก: %s" % ", ".join(missing),
            missing=missing,
            schema=diagnostics,
        )


def _date(text):
    """Day-first (parsing.day_first_date) as ISO text; blank is None."""
    try:
        day = parsing.day_first_date(text)
    except ValueError:
        raise Unreadable("date_unreadable", text) from None
    return day.isoformat() if day else None


def _money(text):
    """฿ / บาท / commas / (x) as a two-place string (parsing.money_amount); blank is None."""
    try:
        amount = parsing.money_amount(text)
        return None if amount is None else str(amount.quantize(Decimal("0.01")))
    except (ValueError, InvalidOperation):
        raise Unreadable("amount_unreadable", text) from None


def group_documents(lines, build, rejected):
    """One record per document from its lines (first appearance kept), each built by
    `build(lines)`. A document with a cell that does not parse sends every one of its
    lines to `rejected`, the way an unknown status rejects its line. Returns the
    records and the lines they were built from."""
    docs = {}
    for ln in lines:
        docs.setdefault(ln["doc_no"], []).append(ln)
    records, kept = [], []
    for own in docs.values():
        try:
            records.append(build(own))
        except Unreadable as exc:
            rejected.extend({"row": ln["sheet_row"], "code": exc.code, "value": exc.value} for ln in own)
            continue
        kept.extend(own)
    return records, kept


def _cycle(*texts):
    for t in texts:
        m = _CYCLE.search(t or "")
        if m:
            return {"n": int(m.group(1)), "of": int(m.group(2))}
    return None


def parse(raw, filename=None):
    table = _table(raw)
    header_row, cells = _find_header(table)
    col, schema = _resolve_columns(cells, COLUMNS, REQUIRED_FIELDS, ALIASES,
                                   COLUMN_AFTER, FIRST_FIELDS, "invoice")
    schema["header_row"] = header_row + 1
    doc_column = col.get("doc_no")
    if doc_column is not None:
        first_doc = next((_cell(row, doc_column) for row in table[header_row + 1:]
                          if _cell(row, doc_column)), "")
        doc_kind = first_doc.split("-")[0] if "-" in first_doc else first_doc
        if doc_kind in RECEIPT_DOC_KINDS:
            raise ReportError(
                "wrong_report",
                "this is the PEAK receipt report, not the invoice report",
                "ไฟล์นี้เป็นรายงานรับชำระ ไม่ใช่รายงานใบแจ้งหนี้",
                schema=schema,
            )
    _require_columns(col, REQUIRED_FIELDS, COLUMNS, schema)
    lines, rejected = [], []
    for n, row in enumerate(table[header_row + 1:], start=header_row + 2):   # 1-based sheet row
        doc_no = _cell(row, col["doc_no"])
        if not doc_no:
            continue
        status_th = _cell(row, col["status_th"])
        status = STATUS_MAP.get(status_th)
        if status is None:
            rejected.append({"row": n, "code": "status_unknown", "value": status_th})
            continue
        lines.append({key: _cell(row, i) for key, i in col.items()} | {"status": status, "sheet_row": n})
    invoices, lines = group_documents(lines, _invoice, rejected)
    return {"report_as_of": report_as_of(filename), "exported_at": export_timestamp(filename), "header_row": header_row,
            "schema": schema, "lines": lines, "invoices": invoices, "rejected": rejected}


def public_schema():
    return schema_contract("invoice", COLUMNS, REQUIRED_FIELDS, ALIASES, COLUMN_AFTER, FIRST_FIELDS)


def _invoice(lines):
    """One invoice from its lines; the invoice-level cells repeat on every line and
    are read from the first."""
    first = lines[0]
    doc = first["doc_no"]
    paid_on = _date(first["paid_on"])
    inv = {
        "doc_no": doc, "doc_kind": doc.split("-")[0] if "-" in doc else doc,
        "issued_on": _date(first["issued_on"]), "due_on": _date(first["due_on"]),
        "reference": first["reference"] or None, "system_reference": first["system_reference"] or None,
        "contact_code": first["contact_code"] or None, "customer_name": first["customer_name"] or None,
        "tax_id_13": first["tax_id_13"] or None,            # in-run only; never written (F5)
        "status": first["status"], "cycle": None,
        "product_group": first["product_group"] or None,
        # in-run only, for the system-size compare (peak_conflicts); never written
        "product_name": first["product_name"] or None,
        "amount_total": _money(first["amount_total"]), "amount_due": _money(first["amount_due"]),
        "amount_awaiting": _money(first["amount_awaiting"]) or "0.00",
        "payment": ({"on": paid_on, "channel": first["paid_channel"] or None,
                     "amount": _money(first["paid_amount"]), "receipt_no": first["receipt_no"] or None}
                    if paid_on or first["receipt_no"] else None),
        "note": first["note"] or None, "lines": [],
    }
    from ..instalment_evidence import service_period
    inv["service_month"], inv["service_month_conflict"] = service_period(lines)
    for ln in lines:
        if inv["cycle"] is None:
            inv["cycle"] = _cycle(ln["description"], ln["product_name"])
        try:
            line_no = int(float(ln["line_no"])) if ln["line_no"] else len(inv["lines"]) + 1
        except (ValueError, TypeError):
            line_no = len(inv["lines"]) + 1
        inv["lines"].append({"line_no": line_no,
                             "product_code": ln["product_code"] or None,
                             "description": ln["description"] or None, "amount": _money(ln["price"])})
    return inv
