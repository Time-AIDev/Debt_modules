"""The PEAK invoice report, parsed. Column names are the report's own Thai headings
(measured on the 2026-09-14 export: 56 columns, header on row 11)."""
import pytest

from app import xlsx_writer
from app.pipelines import peak_report

HEADER = ["ลำดับที่", "เลขที่เอกสาร", "วันที่ออก", "วันที่ครบกำหนด", "อ้างอิง", "อ้างอิงจากระบบ", "บันทึกบัญชี",
          "สถานะ", "รหัสผู้ติดต่อ", "ชื่อลูกค้า", "เลขที่ 13 หลัก", "สาขา", "ประเภทราคา", "ใบกำกับภาษี",
          "สกุลเงิน", "อัตราแลกเปลี่ยน", "รายการที่", "รหัสสินค้า/บริการ", "ชื่อสินค้า/บริการ", "ผังบัญชี",
          "คำอธิบาย", "จำนวน", "หน่วย", "ราคา", "ส่วนลด", "มูลค่าก่อนภาษี", "ประเภทภาษี", "ยอด VAT",
          "หัก ณ ที่จ่าย", "ส่วนลดรวม", "เงินมัดจำ", "ไม่มี VAT", "VAT 0%", "VAT 7%", "ยอด VAT", "ทั้งหมด",
          "หัก ณ ที่จ่าย", "ต้องชำระ", "วันที่", "เลขที่ช่องทางการเงิน", "ช่องทางการชำระเงิน", "จำนวนเงิน",
          "e-WHT", "มูลค่ารอรับชำระ", "บันทึกบัญชี", "เลขที่ใบเสร็จ", "กลุ่มใหญ่", "กลุ่มย่อย", "%", "หมายเหตุ",
          "ไฟล์แนบ", "แท็ก", "ผู้สร้าง", "วันที่สร้าง", "ผู้อนุมัติ", "วันที่อนุมัติ"]


def _line(**over):
    row = {h: "" for h in HEADER}
    row.update({"ลำดับที่": "1", "เลขที่เอกสาร": "IVT-20260700089", "วันที่ออก": "11/07/2026",
                "วันที่ครบกำหนด": "18/07/2026", "อ้างอิง": "99999000328", "สถานะ": "รับชำระแล้ว",
                "รหัสผู้ติดต่อ": "99999000328", "ชื่อลูกค้า": "Somchai Tamdee", "เลขที่ 13 หลัก": "1234567890121",
                "รายการที่": "1", "รหัสสินค้า/บริการ": "P00004",
                "ชื่อสินค้า/บริการ": "Solar Rooftop (On-grid) 3 Phase_10kWp",
                "คำอธิบาย": "Solar Rooftop (On-grid) 3 Phase_10kWp Installment_M14/48",
                "ราคา": "8,399.00", "ทั้งหมด": "13060.45", "ต้องชำระ": "13060.45", "มูลค่ารอรับชำระ": "0.0",
                "วันที่": "16/07/2026", "ช่องทางการชำระเงิน": "Beam 0001", "จำนวนเงิน": "13060.45",
                "เลขที่ใบเสร็จ": "RE-20260700272", "กลุ่มใหญ่": "โครงการ", "กลุ่มย่อย": "Solar Leasing"})
    row.update(over)
    return row


def _report(lines, preamble=10):
    """The report as PEAK writes it: ten preamble rows, then the header, then lines.
    Duplicate headings (ยอด VAT twice) are kept — the parser must take the first."""
    rows = [["รายงานใบแจ้งหนี้"] + [""] * (len(HEADER) - 1)] * preamble
    rows.append(list(HEADER))
    for ln in lines:
        rows.append([ln.get(h, "") for h in HEADER])
    return xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้", "rows": rows}])


FILENAME = "invoice_บริษัท_โวลต์_จำกัด_export_as_of_20240101_20260914_20260914_155330.xlsx"


def test_header_detection_is_bounded_to_the_first_100_rows():
    header_on_row_100 = [["report preamble"]] * 99 + [list(HEADER)]
    assert peak_report._find_header(header_on_row_100)[0] == 99

    header_on_row_101 = [["report preamble"]] * 100 + [list(HEADER)]
    with pytest.raises(peak_report.ReportError) as exc:
        peak_report._find_header(header_on_row_101)
    assert exc.value.code == "header_not_found"


def test_it_finds_the_header_row_and_reads_one_invoice():
    out = peak_report.parse(_report([_line()]), FILENAME)
    assert out["header_row"] == 10
    assert out["report_as_of"] == "2026-09-14"
    inv = out["invoices"][0]
    assert inv["doc_no"] == "IVT-20260700089" and inv["doc_kind"] == "IVT"
    assert inv["issued_on"] == "2026-07-11" and inv["due_on"] == "2026-07-18"
    assert inv["status"] == "PAID"
    assert inv["contact_code"] == "99999000328" and inv["reference"] == "99999000328"
    assert inv["cycle"] == {"n": 14, "of": 48}
    assert inv["amount_due"] == "13060.45" and inv["amount_awaiting"] == "0.00"
    assert inv["payment"] == {"on": "2026-07-16", "channel": "Beam 0001",
                              "amount": "13060.45", "receipt_no": "RE-20260700272"}
    assert inv["product_group"] == "Solar Leasing"
    assert inv["lines"][0]["product_code"] == "P00004"


def test_lines_of_one_invoice_fold_into_one_record():
    out = peak_report.parse(_report([_line(), _line(**{"รายการที่": "2", "รหัสสินค้า/บริการ": "P00042",
                                                    "ชื่อสินค้า/บริการ": "Late Fee (No VAT)",
                                                    "คำอธิบาย": "Late Fee M11 (94 days)", "ราคา": "2,368.52"})]))
    assert len(out["invoices"]) == 1
    assert [l["product_code"] for l in out["invoices"][0]["lines"]] == ["P00004", "P00042"]


def test_every_status_the_report_uses_is_mapped_and_an_unknown_one_is_rejected_by_name():
    lines = [_line(**{"เลขที่เอกสาร": "IV-1", "สถานะ": "เกินเวลารับชำระ"}),
             _line(**{"เลขที่เอกสาร": "IV-2", "สถานะ": "รอชำระ"}),
             _line(**{"เลขที่เอกสาร": "IV-3", "สถานะ": "ร่าง"}),
             _line(**{"เลขที่เอกสาร": "IV-4", "สถานะ": "ยกเลิก"})]
    out = peak_report.parse(_report(lines))
    assert [i["status"] for i in out["invoices"]] == ["OVERDUE", "AWAITING", "DRAFT", "CANCELLED"]
    assert out["rejected"] == []


def test_a_new_withholding_amount_column_does_not_shadow_the_payment_amount():
    """PEAK's wider export inserts withholding document/amount columns before the
    payment block. The payment amount is the occurrence after the paid date, not the
    first column carrying the same heading."""
    header = list(HEADER)
    split = header.index("ส่วนลดรวม")
    header[split:split] = ["เลขที่เอกสาร", "จำนวนเงิน"]
    row = [_line().get(h, "") for h in HEADER]
    row[split:split] = ["DRT-20260700022", "5000.00"]
    raw = xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้", "rows": [header, row]}])

    payment = peak_report.parse(raw)["invoices"][0]["payment"]

    assert payment["amount"] == "13060.45"


def test_schema_diagnostics_explain_contextual_duplicates_and_ignored_columns():
    header = list(HEADER)
    split = header.index("ส่วนลดรวม")
    header[split:split] = ["เลขที่เอกสาร", "จำนวนเงิน", "ฟิลด์ใหม่จาก PEAK"]
    row = [_line().get(h, "") for h in HEADER]
    row[split:split] = ["DRT-20260700022", "5000.00", "ไม่ถูกอ่าน"]
    raw = xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้", "rows": [header, row]}])

    schema = peak_report.parse(raw)["schema"]

    assert schema["report_type"] == "invoice"
    assert schema["header_row"] == 1
    assert "doc_no" in schema["detected_fields"]
    assert schema["bindings"]["doc_no"]["strategy"] == "first"
    assert schema["bindings"]["paid_amount"]["strategy"] == "after"
    assert {item["heading"] for item in schema["duplicate_headings"]} >= {"เลขที่เอกสาร", "จำนวนเงิน"}
    assert "ฟิลด์ใหม่จาก PEAK" in schema["ignored_headings"]


def test_an_unresolved_duplicate_required_heading_is_refused_as_ambiguous():
    header = list(HEADER)
    header.insert(header.index("อ้างอิง"), "สถานะ")
    row = [_line().get(h, "") for h in HEADER]
    row.insert(header.index("อ้างอิง") - 1, "รับชำระแล้ว")
    raw = xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้", "rows": [header, row]}])

    with pytest.raises(peak_report.ReportError) as exc:
        peak_report.parse(raw)

    assert exc.value.code == "schema_ambiguous_header"
    assert exc.value.schema["ambiguous_required_fields"] == ["status_th"]
    assert "Somchai" not in str(exc.value.schema)


def test_invoice_identity_columns_are_optional_when_the_export_checklist_omits_them():
    omitted = {"อ้างอิง", "รหัสผู้ติดต่อ"}
    header = [h for h in HEADER if h not in omitted]
    line = _line()
    raw = xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้",
                                 "rows": [header, [line.get(h, "") for h in header]]}])

    invoice = peak_report.parse(raw)["invoices"][0]

    assert invoice["reference"] is None and invoice["contact_code"] is None


def test_invoice_required_heading_error_names_only_the_missing_columns():
    header = [h for h in HEADER if h != "มูลค่ารอรับชำระ"]
    line = _line()
    raw = xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้",
                                 "rows": [header, [line.get(h, "") for h in header]]}])

    with pytest.raises(peak_report.ReportError) as exc:
        peak_report.parse(raw)

    assert exc.value.code == "missing_required_columns"
    assert exc.value.missing == ("มูลค่ารอรับชำระ",)
    assert exc.value.schema["missing_required_fields"] == ["amount_awaiting"]


def test_required_headings_tolerate_embedded_excel_whitespace():
    header = list(HEADER)
    replacements = {
        "เลขที่เอกสาร": "เลขที่\nเอกสาร",
        "วันที่ครบกำหนด": "วันที่ครบ\u00a0กำหนด",
        "มูลค่ารอรับชำระ": "มูลค่า\nรอรับชำระ",
    }
    header = [replacements.get(h, h) for h in header]
    raw = xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้",
                                 "rows": [header, [_line().get(h, "") for h in HEADER]]}])

    assert peak_report.parse(raw)["invoices"][0]["doc_no"] == "IVT-20260700089"


def test_a_missing_required_heading_refuses_and_names_it():
    bad = [h if h != "วันที่ครบกำหนด" else "Due" for h in HEADER]
    rows = [["x"] * len(HEADER)] * 3 + [bad] + [[_line().get(h, "") for h in HEADER]]
    raw = xlsx_writer.workbook([{"name": "r", "rows": rows}])
    with pytest.raises(peak_report.ReportError) as exc:
        peak_report.parse(raw)
    assert exc.value.code == "missing_required_columns"
    assert exc.value.missing == ("วันที่ครบกำหนด",)


def test_a_receipt_report_dropped_on_the_invoice_door_is_refused():
    from tests.test_peak_receipt import _line as receipt_line, _report as receipt_report

    with pytest.raises(peak_report.ReportError) as exc:
        peak_report.parse(receipt_report([receipt_line()]), FILENAME)

    assert exc.value.code == "wrong_report"
    assert exc.value.detail_th == "ไฟล์นี้เป็นรายงานรับชำระ ไม่ใช่รายงานใบแจ้งหนี้"


def test_a_missing_amount_awaiting_heading_refuses_instead_of_zeroing_the_book():
    """Finding 1: มูลค่ารอรับชำระ decides every payment status. A renamed or
    missing heading must refuse the file, never read as zero owed."""
    bad = [h if h != "มูลค่ารอรับชำระ" else "Outstanding" for h in HEADER]
    rows = [["x"] * len(HEADER)] * 3 + [bad] + [[_line().get(h, "") for h in HEADER]]
    raw = xlsx_writer.workbook([{"name": "r", "rows": rows}])
    with pytest.raises(peak_report.ReportError) as exc:
        peak_report.parse(raw)
    assert exc.value.code == "missing_required_columns"
    assert exc.value.missing == ("มูลค่ารอรับชำระ",)


def test_no_cycle_mark_means_no_cycle_not_a_guess():
    inv = peak_report.parse(_report([_line(**{"คำอธิบาย": "Uninstall fee"})]))["invoices"][0]
    assert inv["cycle"] is None


def test_the_report_date_comes_from_the_file_name_or_is_none():
    assert peak_report.report_as_of(FILENAME) == "2026-09-14"
    assert peak_report.report_as_of("invoices.xlsx") is None


def test_a_csv_export_reads_the_same_as_the_xlsx():
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    for _ in range(2):
        w.writerow(["รายงานใบแจ้งหนี้"] + [""] * (len(HEADER) - 1))
    w.writerow(HEADER)
    w.writerow([_line().get(h, "") for h in HEADER])
    out = peak_report.parse(("﻿" + buf.getvalue()).encode("utf-8"), "x.csv")
    assert out["invoices"][0]["doc_no"] == "IVT-20260700089"


def test_malformed_xlsx_raises_report_error_with_code_unreadable():
    """Bad ZIP data (claims to be XLSX but is not) raises ReportError."""
    bad_xlsx = b"PK\x03\x04" + b"not a valid zip"
    with pytest.raises(peak_report.ReportError) as exc:
        peak_report.parse(bad_xlsx)
    assert exc.value.code == "unreadable"


def test_an_excel_lock_file_is_refused_as_unreadable_instead_of_leaking_csv_error():
    with pytest.raises(peak_report.ReportError) as exc:
        peak_report.parse(b"\x00\x00temporary excel owner file")

    assert exc.value.code == "unreadable"


def test_a_non_numeric_line_number_falls_back_to_position():
    """Line numbers that don't parse as numbers use the position within the invoice."""
    out = peak_report.parse(_report([_line(**{"รายการที่": "x"})]))
    assert out["invoices"][0]["lines"][0]["line_no"] == 1


# --- fix-all P8 (M1): dates and amounts parse strictly, or the invoice is rejected ------

def test_a_buddhist_era_year_reads_as_the_christian_year():
    inv = peak_report.parse(_report([_line(**{"วันที่ออก": "11/7/2569", "วันที่ครบกำหนด": "18/07/2569"})]))["invoices"][0]
    assert (inv["issued_on"], inv["due_on"]) == ("2026-07-11", "2026-07-18")


def test_an_impossible_date_rejects_every_line_of_its_invoice_by_name():
    """31/02 and a month-first 07/18 reached the COPY into a date column and failed the
    whole run; the invoice is rejected instead, every line of it, like an unknown status."""
    lines = [_line(**{"เลขที่เอกสาร": "IV-1"}),
             _line(**{"เลขที่เอกสาร": "IV-2", "วันที่ครบกำหนด": "31/02/2026"}),
             _line(**{"เลขที่เอกสาร": "IV-2", "รายการที่": "2"}),
             _line(**{"เลขที่เอกสาร": "IV-3", "วันที่ออก": "07/18/2026"})]
    out = peak_report.parse(_report(lines))
    assert [i["doc_no"] for i in out["invoices"]] == ["IV-1"] and len(out["lines"]) == 1
    assert out["rejected"] == [{"row": 13, "code": "date_unreadable", "value": "31/02/2026"},
                               {"row": 14, "code": "date_unreadable", "value": "31/02/2026"},
                               {"row": 15, "code": "date_unreadable", "value": "07/18/2026"}]


def test_amounts_read_the_baht_sign_the_word_and_brackets_and_an_unreadable_one_rejects():
    """฿1,000.00, 1,000.00 บาท and (250.00) read as None, and an awaiting of None was
    stored as 0.00 — nothing owed. They read as numbers; anything else rejects."""
    lines = [_line(**{"เลขที่เอกสาร": "IV-1", "ต้องชำระ": "฿1,000.00", "ทั้งหมด": "1,000.00 บาท",
                      "จำนวนเงิน": "(250.00)"}),
             _line(**{"เลขที่เอกสาร": "IV-2", "มูลค่ารอรับชำระ": "ค้าง"})]
    out = peak_report.parse(_report(lines))
    [inv] = out["invoices"]
    assert (inv["amount_due"], inv["amount_total"], inv["payment"]["amount"]) == ("1000.00", "1000.00", "-250.00")
    assert out["rejected"] == [{"row": 13, "code": "amount_unreadable", "value": "ค้าง"}]


def test_the_product_name_rides_on_the_invoice_so_the_system_size_can_be_compared():
    """Fix-all P10b (M4): the system-size compare read a product_name nobody set."""
    from app.pipelines import peak_conflicts
    inv = peak_report.parse(_report([_line()]))["invoices"][0]
    assert inv["product_name"] == "Solar Rooftop (On-grid) 3 Phase_10kWp"
    size = [c for c in peak_conflicts.compare(inv, {"order": {"watt": "5000"}}) if c["field"] == "system_size_kwp"]
    assert size == [{"field": "system_size_kwp", "odoo_value": "5.00", "peak_value": "10.00", "same": False}]
