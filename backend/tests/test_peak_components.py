from app.pipelines import peak_receipt, peak_report
from tests.test_peak_receipt import _line as receipt_line, _report as receipt_report
from tests.test_peak_report import _line as invoice_line, _report as invoice_report


def test_invoice_item_payment_cartesian_rows_are_deduplicated_separately():
    lines = [invoice_line(**{"รายการที่": str(item), "ราคา": str(100 * item),
                            "เลขที่ใบเสร็จ": "RE-%s" % payment, "วันที่": "0%s/09/2026" % payment,
                            "จำนวนเงิน": "500"}) for item in (1, 2) for payment in (1, 2)]
    parsed = peak_report.parse(invoice_report(lines))
    [invoice] = parsed["invoices"]
    assert len(parsed["lines"]) == 4
    assert len(invoice["lines"]) == 2 and len(invoice["payments"]) == 2
    assert sum(float(row["amount"]) for row in invoice["payments"]) == 1000
    assert len(invoice["source_rows"]) == 4


def test_same_receipt_component_cannot_change_amount_inside_an_invoice():
    parsed = peak_report.parse(invoice_report([invoice_line(), invoice_line(**{"จำนวนเงิน": "100"})]))
    assert parsed["invoices"] == []
    assert len(parsed["rejected"]) == 2
    assert {row["code"] for row in parsed["rejected"]} == {"payment_component_conflict"}


def test_conflicting_receipt_header_is_quarantined_whole_not_first_row():
    parsed = peak_receipt.parse(receipt_report([receipt_line(), receipt_line(**{"ต้องชำระ": "100"})]))
    assert parsed["receipts"] == []
    assert len(parsed["meta"]["rejected"]) == 2
    assert all(row["code"] == "document_fields_conflict" for row in parsed["meta"]["rejected"])
    assert all(row["value"] == "amount_due" for row in parsed["meta"]["rejected"])


def test_receipt_split_channels_are_components_not_document_conflicts():
    parsed = peak_receipt.parse(receipt_report([
        receipt_line(**{"จำนวนเงิน": "1000", "ช่องทางการชำระเงิน": "BANK-A"}),
        receipt_line(**{"จำนวนเงิน": "7399", "ช่องทางการชำระเงิน": "BANK-B"}),
    ]))
    [receipt] = parsed["receipts"]
    assert receipt["paid_amount"] == "8399.00" and len(receipt["payments"]) == 2


def test_repeated_receipt_item_rows_keep_one_cash_amount_and_all_source_rows():
    parsed = peak_receipt.parse(receipt_report([receipt_line(), receipt_line()]))
    [receipt] = parsed["receipts"]
    assert receipt["paid_amount"] == "8399.00"
    assert len(receipt["lines"]) == 1 and len(receipt["source_rows"]) == 2


def test_unknown_status_on_one_row_quarantines_other_rows_of_same_document():
    parsed = peak_receipt.parse(receipt_report([receipt_line(), receipt_line(**{"สถานะ": "unknown"})]))
    assert parsed["receipts"] == []
    assert len(parsed["meta"]["rejected"]) == 2


def test_missing_invoice_balance_is_unknown_not_zero_paid():
    parsed = peak_report.parse(invoice_report([invoice_line(**{"มูลค่ารอรับชำระ": ""})]))
    assert parsed["invoices"] == []
    assert parsed["rejected"][0]["code"] == "invoice_balance_missing"


def test_paid_receipt_word_without_cached_cash_and_date_is_quarantined():
    parsed = peak_receipt.parse(receipt_report([receipt_line(**{"จำนวนเงิน": "", "วันที่": ""})]))
    assert parsed["receipts"] == []
    assert parsed["meta"]["rejected"][0]["code"] == "payment_component_incomplete"


def test_component_money_equivalent_formatting_is_not_a_false_conflict():
    parsed = peak_receipt.parse(receipt_report([receipt_line(), receipt_line(**{"จำนวนเงิน": "8399.00"})]))
    assert len(parsed["receipts"]) == 1


def test_different_customer_identity_inside_receipt_cannot_be_auto_matched():
    parsed = peak_receipt.parse(receipt_report([receipt_line(), receipt_line(**{"รหัสผู้ติดต่อ": "99999009999"})]))
    assert parsed["receipts"] == []
    assert parsed["meta"]["rejected"][0]["value"] == "contact_code"


def test_split_receipt_components_respect_each_snapshot_date_and_conserve_cash():
    from app.payment_claims import reconcile_receipts
    invoices = [{"doc_no": "IV-1", "customer_no": "C1", "amount": "1000", "outstanding": "500",
                 "due_on": "2026-09-01", "snapshot_as_of": "2026-09-14"}]
    receipt = {"doc_no": "RE-1", "invoice_ref": "IV-1", "customer_no": "C1", "status": "PAID",
               "paid_on": "2026-09-20", "paid_amount": "700", "exported_at": "2026-09-30",
               "payments": [{"on": "2026-09-10", "amount": "500"}, {"on": "2026-09-20", "amount": "200"}]}
    result = reconcile_receipts(invoices, [receipt, receipt])
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "300.00"
    assert len(result["allocations"]) == 1 and result["allocations"][0]["amount"] == "700.00"
    assert result["active_receipts"] == 1 and result["credit_by_customer"] == {}


def test_cancellation_restores_only_historical_split_cash_in_snapshot():
    from app.payment_claims import reconcile_receipts
    invoices = [{"doc_no": "IV-1", "customer_no": "C1", "amount": "1000", "outstanding": "500",
                 "due_on": "2026-09-01", "snapshot_as_of": "2026-09-14"}]
    components = [{"on": "2026-09-10", "amount": "500"}, {"on": "2026-09-20", "amount": "200"}]
    receipt = {"doc_no": "RE-1", "invoice_ref": "IV-1", "customer_no": "C1", "status": "CANCELLED",
               "paid_on": "2026-09-20", "paid_amount": "700", "exported_at": "2026-09-30", "payments": components}
    result = reconcile_receipts(invoices, [receipt])
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "1000.00"
    assert result["allocations"] == []


def test_invalid_component_total_cannot_partially_allocate_a_receipt():
    from app.payment_claims import reconcile_receipts
    receipt = {"doc_no": "RE-1", "invoice_ref": "IV-1", "customer_no": "C1", "status": "PAID",
               "paid_on": "2026-09-20", "paid_amount": "500",
               "payments": [{"on": "2026-09-20", "amount": "100"}]}
    result = reconcile_receipts([], [receipt])
    assert result["allocations"] == []
    assert result["exceptions"][0]["reason"] == "PAYMENT_COMPONENTS_INVALID"
