"""The PEAK receipt report, parsed (feedback-r2 TASK-201, Q6).

Column names are the receipt export's own Thai headings (46 columns, header on
row 12). Every test here is an ADDITION.
"""
import pytest

from app import xlsx_writer
from app.pipelines import peak_receipt

HEADER = ["ลำดับที่", "เลขที่เอกสาร", "วันที่ออก", "อ้างอิง", "อ้างอิงจากระบบ", "บันทึกบัญชี",
          "สถานะ", "รหัสผู้ติดต่อ", "ชื่อลูกค้า", "เลขที่ 13 หลัก", "สาขา", "ประเภทราคา",
          "ใบกำกับภาษี", "สกุลเงิน", "อัตราแลกเปลี่ยน", "รายการที่", "รหัสสินค้า/บริการ",
          "ชื่อสินค้า/บริการ", "ผังบัญชี", "คำอธิบาย", "จำนวน", "หน่วย", "ราคา", "ส่วนลด",
          "มูลค่าก่อนภาษี", "ประเภทภาษี", "ยอด VAT", "หัก ณ ที่จ่าย", "ส่วนลดรวม", "เงินมัดจำ",
          "ไม่มี VAT", "VAT 0%", "VAT 7%", "ยอด VAT", "ทั้งหมด", "หัก ณ ที่จ่าย", "ต้องชำระ",
          "วันที่", "เลขที่ช่องทางการเงิน", "ช่องทางการชำระเงิน", "จำนวนเงิน", "e-WHT",
          "บันทึกบัญชี", "หมายเหตุ", "ไฟล์แนบ", "ผู้สร้าง"]


def _line(**over):
    row = {h: "" for h in HEADER}
    row.update({"ลำดับที่": "1", "เลขที่เอกสาร": "RE-20260900001", "วันที่ออก": "16/09/2026",
                "อ้างอิง": "IVT-20260700089", "อ้างอิงจากระบบ": "IVT-20260700089",
                "บันทึกบัญชี": "RE-2026-09-0001", "สถานะ": "รับชำระแล้ว",
                "รหัสผู้ติดต่อ": "99999000328", "ชื่อลูกค้า": "Somchai Tamdee",
                "เลขที่ 13 หลัก": "1234567890121", "รายการที่": "1",
                "รหัสสินค้า/บริการ": "P00004", "ชื่อสินค้า/บริการ": "Solar Rooftop (On-grid) 3 Phase_10kWp",
                "คำอธิบาย": "Installment_M16/84", "ราคา": "8,399.00", "ทั้งหมด": "8,399.00",
                "ต้องชำระ": "8,399.00", "วันที่": "16/09/2026", "เลขที่ช่องทางการเงิน": "BNK-1",
                "ช่องทางการชำระเงิน": "Beam 0001", "จำนวนเงิน": "8,399.00"})
    row.update(over)
    return row


def _report(lines, preamble=11):
    """As PEAK writes it: eleven preamble rows, then the header, then lines."""
    rows = [["รายงานใบเสร็จรับเงิน"] + [""] * (len(HEADER) - 1)] * preamble
    rows.append(list(HEADER))
    for ln in lines:
        rows.append([ln.get(h, "") for h in HEADER])
    return xlsx_writer.workbook([{"name": "รายงานใบเสร็จรับเงิน", "rows": rows}])


FILENAME = "receipt_บริษัท_โวลต์_จำกัด_export_as_of_20240101_20260916_20260916_155330.xlsx"


def test_it_groups_two_lines_into_one_receipt_and_rejects_an_unknown_status():
    out = peak_receipt.parse(_report([
        _line(),
        _line(**{"รายการที่": "2", "รหัสสินค้า/บริการ": "P00042",
                 "ชื่อสินค้า/บริการ": "Late Fee (No VAT)", "คำอธิบาย": "Late Fee M16 (3 days)",
                 "ราคา": "12.00"}),
        _line(**{"เลขที่เอกสาร": "RT-20260900002", "อ้างอิง": "IV-20260900001",
                 "รหัสสินค้า/บริการ": "P00004", "ราคา": "100.00", "วันที่": "17/09/2026"}),
        _line(**{"เลขที่เอกสาร": "RE-20260900003", "สถานะ": "รอตรวจ"}),
    ]), FILENAME)
    assert out["meta"]["report_as_of"] == "2026-09-16"
    assert out["meta"]["read"] == 3
    assert [r["doc_no"] for r in out["receipts"]] == ["RE-20260900001", "RT-20260900002"]
    first = out["receipts"][0]
    assert first["doc_kind"] == "RE" and first["status"] == "PAID"
    assert first["invoice_ref"] == "IVT-20260700089"
    assert first["journal_ref"] == "RE-2026-09-0001"
    assert first["cycle_n"] == 16 and first["cycle_of"] == 84
    assert first["paid_on"] == "2026-09-16" and first["paid_amount"] == "8399.00"
    assert [ln["amount"] for ln in first["lines"]] == ["8399.00", "12.00"]
    assert out["receipts"][1]["doc_kind"] == "RT"
    assert out["meta"]["rejected"] == [{"row": 16, "code": "status_unknown", "value": "รอตรวจ"}]


def test_the_thirteen_digit_id_is_parsed_in_run_only():
    out = peak_receipt.parse(_report([_line()]), FILENAME)
    assert out["receipts"][0]["tax_id_13"] == "1234567890121"
    # and it is NOT a stored column: the writer's own list never names it
    from app.pipelines import peak_writer
    assert "tax_id_13" not in peak_writer._RECEIPT_COLUMNS


def test_a_document_kind_the_report_never_writes_keeps_other():
    out = peak_receipt.parse(_report([_line(**{"เลขที่เอกสาร": "RB-1"})]), FILENAME)
    assert out["receipts"][0]["doc_kind"] == "OTHER"


def test_a_missing_required_heading_refuses_and_names_it():
    bad = [h if h != "วันที่" else "Paid on" for h in HEADER]
    rows = [["x"] * len(HEADER)] * 3 + [bad] + [[_line().get(h, "") for h in HEADER]]
    raw = xlsx_writer.workbook([{"name": "r", "rows": rows}])
    with pytest.raises(peak_receipt.ReportError) as exc:
        peak_receipt.parse(raw)
    assert exc.value.code == "missing_required_columns"
    assert exc.value.missing == ("วันที่",)


def test_new_withholding_columns_do_not_shadow_the_received_amount():
    """The annual export adds another document/amount pair for withholding before
    the payment block. The received amount remains the occurrence after paid date."""
    header = list(HEADER)
    split = header.index("ส่วนลดรวม")
    header[split:split] = ["เลขที่เอกสาร", "จำนวนเงิน"]
    row = [_line().get(h, "") for h in HEADER]
    row[split:split] = ["DRT-20260700022", "5000.00"]
    raw = xlsx_writer.workbook([{"name": "รายงานใบเสร็จรับเงิน", "rows": [header, row]}])

    receipt = peak_receipt.parse(raw)["receipts"][0]

    assert receipt["paid_amount"] == "8399.00"


def test_receipt_schema_diagnostics_use_the_receipt_contract():
    out = peak_receipt.parse(_report([_line()]), FILENAME)
    schema = out["meta"]["schema"]
    assert schema["report_type"] == "receipt"
    assert set(schema["detected_fields"]) >= {"doc_no", "paid_on", "paid_amount"}
    assert schema["bindings"]["paid_amount"]["after"] == "วันที่"


def test_receipt_matching_columns_are_optional_when_the_export_checklist_omits_them():
    omitted = {"อ้างอิง", "อ้างอิงจากระบบ", "รหัสผู้ติดต่อ"}
    header = [h for h in HEADER if h not in omitted]
    line = _line()
    raw = xlsx_writer.workbook([{"name": "รายงานใบเสร็จรับเงิน",
                                 "rows": [header, [line.get(h, "") for h in header]]}])

    receipt = peak_receipt.parse(raw)["receipts"][0]

    assert receipt["invoice_ref"] is None and receipt["contact_code"] is None


def test_receipt_requires_the_payment_amount_occurrence_after_the_paid_date():
    header = [h for h in HEADER if h != "จำนวนเงิน"]
    split = header.index("ส่วนลดรวม")
    header[split:split] = ["เลขที่เอกสาร", "จำนวนเงิน"]
    line = _line()
    row = [line.get(h, "") for h in HEADER if h != "จำนวนเงิน"]
    row[split:split] = ["DRT-20260700022", "5000.00"]
    raw = xlsx_writer.workbook([{"name": "รายงานใบเสร็จรับเงิน", "rows": [header, row]}])

    with pytest.raises(peak_receipt.ReportError) as exc:
        peak_receipt.parse(raw)

    assert exc.value.code == "missing_required_columns"
    assert exc.value.missing == ("จำนวนเงิน",)


def test_no_cycle_mark_means_no_cycle_not_a_guess():
    out = peak_receipt.parse(_report([_line(**{"คำอธิบาย": "ค่าธรรมเนียมถอดระบบ"})]), FILENAME)
    assert out["receipts"][0]["cycle_n"] is None and out["receipts"][0]["cycle_of"] is None


def test_an_invoice_report_dropped_on_the_receipt_door_is_refused():
    """Fix-all P4 (F6): the invoice export carries every heading the receipt parser
    requires, so it was read as receipts. An invoice-only heading refuses it."""
    from tests.test_peak_report import _line as invoice_line, _report as invoice_report
    with pytest.raises(peak_receipt.ReportError) as exc:
        peak_receipt.parse(invoice_report([invoice_line()]), FILENAME)
    assert exc.value.code == "wrong_report"
    assert exc.value.detail_th == "ไฟล์นี้เป็นรายงานใบแจ้งหนี้ ไม่ใช่รายงานรับชำระ"


def test_a_receipt_with_an_unreadable_date_is_rejected_whole():
    """Fix-all P8: the receipt parser shares the invoice parser's strict cells."""
    out = peak_receipt.parse(_report([_line(**{"เลขที่เอกสาร": "RE-1", "วันที่": "2026/13/40"}),
                                      _line(**{"เลขที่เอกสาร": "RE-1", "รายการที่": "2"}),
                                      _line(**{"เลขที่เอกสาร": "RE-2"})]), FILENAME)
    assert [r["doc_no"] for r in out["receipts"]] == ["RE-2"] and out["meta"]["read"] == 1
    assert [(r["row"], r["code"]) for r in out["meta"]["rejected"]] == [(13, "date_unreadable"), (14, "date_unreadable")]


def test_receipt_export_timestamp_is_not_confused_with_the_coverage_end():
    """A future range end must not make a mid-month export look future-dated."""
    out = peak_receipt.parse(
        _report([_line()]),
        "receipt_company_export_as_of_20260901_20260930_20260914_114532.xlsx",
    )
    assert out["meta"]["covers_from"] == "2026-09-01"
    assert out["meta"]["covers_to"] == "2026-09-30"
    assert out["meta"]["exported_at"] == "2026-09-14T11:45:32"
    assert out["meta"]["report_as_of"] == "2026-09-14"


def test_invoice_reference_alone_cannot_confirm_a_different_customer():
    from app.pipelines import peak_service
    invoice = {"doc_no": "IV-1", "customer_no": "CUST-A", "ladder_customer_no": None}
    wrong_identity = {"verdict": "EXACT", "rule": "CUSTOMER_NO",
                      "customer_no": "CUST-B", "candidates": []}
    verdict = peak_service.receipt_match_verdict(
        {"doc_no": "RE-1", "invoice_ref": "IV-1"}, invoice, wrong_identity)
    assert verdict["verdict"] == "CANDIDATE"
    assert verdict["rule"] == "INVOICE_CUSTOMER_MISMATCH"
    assert verdict["invoice_doc_no"] is None


def test_receipt_confirms_only_when_reference_and_customer_both_match():
    from app.pipelines import peak_service
    invoice = {"doc_no": "IV-1", "customer_no": "CUST-A", "ladder_customer_no": None}
    same_identity = {"verdict": "EXACT", "rule": "CUSTOMER_NO",
                     "customer_no": "CUST-A", "candidates": []}
    verdict = peak_service.receipt_match_verdict(
        {"doc_no": "RE-1", "invoice_ref": "IV-1"}, invoice, same_identity)
    assert verdict == {"verdict": "EXACT", "rule": "INVOICE_REF_AND_CUSTOMER",
                       "customer_no": "CUST-A", "invoice_doc_no": "IV-1", "candidates": []}


def test_ambiguous_identity_against_found_invoice_stays_reviewable():
    """An object-shaped identity proposal must not crash candidate de-duplication."""
    from app.pipelines import peak_service
    invoice = {"doc_no": "IV-1", "customer_no": "CUST-A", "ladder_customer_no": None}
    ambiguous_identity = {
        "verdict": "CANDIDATE", "rule": None, "customer_no": None,
        "candidates": [{"customer_no": "CUST-B", "rule": "NAME", "code": "Somchai"}],
    }

    verdict = peak_service.receipt_match_verdict(
        {"doc_no": "RE-1", "invoice_ref": "IV-1"}, invoice, ambiguous_identity)

    assert verdict == {
        "verdict": "CANDIDATE", "rule": "INVOICE_CUSTOMER_MISMATCH",
        "customer_no": None, "invoice_doc_no": None,
        "candidates": [
            {"customer_no": "CUST-A", "rule": "INVOICE_REF_CUSTOMER", "code": "IV-1"},
            {"customer_no": "CUST-B", "rule": "NAME", "code": "Somchai"},
        ],
    }


def test_exact_identity_without_invoice_uses_the_candidate_object_contract():
    """A receipt-only proposal must be renderable by the same UI as every candidate."""
    from app.pipelines import peak_service
    identity = {"verdict": "EXACT", "rule": "CUSTOMER_NO",
                "customer_no": "CUST-A", "candidates": []}

    verdict = peak_service.receipt_match_verdict(
        {"doc_no": "RE-1", "invoice_ref": "IV-MISSING", "contact_code": "CUST-A"},
        None, identity)

    assert verdict["candidates"] == [
        {"customer_no": "CUST-A", "rule": "CUSTOMER_NO", "code": "CUST-A"},
    ]


def test_candidate_identity_without_invoice_normalises_and_deduplicates_proposals():
    from app.pipelines import peak_service
    identity = {
        "verdict": "CANDIDATE", "rule": "NAME", "customer_no": None,
        "candidates": [" CUST-A ", {"customer_no": "CUST-A", "rule": "NAME", "code": "A"},
                       {"customer_no": "CUST-B", "rule": "NAME", "code": "B"}],
    }

    verdict = peak_service.receipt_match_verdict(
        {"doc_no": "RE-1", "invoice_ref": "IV-MISSING"}, None, identity)

    assert verdict["invoice_doc_no"] is None
    assert verdict["candidates"] == [
        {"customer_no": "CUST-A", "rule": None, "code": None},
        {"customer_no": "CUST-B", "rule": "NAME", "code": "B"},
    ]


def test_found_invoice_with_unmatched_identity_keeps_the_invoice_as_a_proposal():
    from app.pipelines import peak_service
    invoice = {"doc_no": "IV-1", "customer_no": "CUST-A", "ladder_customer_no": None}
    identity = {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}

    verdict = peak_service.receipt_match_verdict(
        {"doc_no": "RE-1", "invoice_ref": "IV-1"}, invoice, identity)

    assert verdict["verdict"] == "CANDIDATE"
    assert verdict["candidates"] == [
        {"customer_no": "CUST-A", "rule": "INVOICE_REF_CUSTOMER", "code": "IV-1"},
    ]


def test_invoice_proposal_wins_when_identity_candidates_repeat_its_customer():
    from app.pipelines import peak_service
    invoice = {"doc_no": "IV-1", "customer_no": "CUST-A", "ladder_customer_no": None}
    identity = {
        "verdict": "CANDIDATE", "rule": None, "customer_no": None,
        "candidates": [{"customer_no": "CUST-A", "rule": "NAME", "code": "duplicate"}],
    }

    verdict = peak_service.receipt_match_verdict(
        {"doc_no": "RE-1", "invoice_ref": "IV-1"}, invoice, identity)

    assert verdict["candidates"] == [
        {"customer_no": "CUST-A", "rule": "INVOICE_REF_CUSTOMER", "code": "IV-1"},
    ]
