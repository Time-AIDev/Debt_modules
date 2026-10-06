from app.pipelines.rejected_diagnostics import documents


def test_conflicting_document_rows_remain_together_and_never_apply():
    rejected = [
        {"row": 12, "doc_no": "RT001", "code": "receipt_document_conflict",
         "observation": {"status_th": "ชำระแล้ว", "paid_amount": "100.00"}},
        {"row": 13, "doc_no": "RT001", "code": "receipt_document_conflict",
         "observation": {"status_th": "ยกเลิก"}},
        {"row": 14, "doc_no": "RT002", "code": "receipt_document_conflict"},
    ]
    page = documents(rejected, limit=1)
    assert page["total"] == 2 and page["source_rows"] == 3
    assert len(page["rows"][0]["rows"]) == 2
    assert page["rows"][0]["can_apply"] is False
    assert documents(rejected, limit=1, offset=1)["rows"][0]["doc_no"] == "RT002"


def test_unidentified_rejected_rows_stay_separate():
    page = documents([{"row": 4, "code": "missing_reference"}, {"row": 5, "code": "missing_reference"}])
    assert page["total"] == 2
    assert all(not item["can_apply"] for item in page["rows"])


def test_parser_keeps_legacy_diagnostics_and_accounts_for_every_document_row():
    from app.pipelines import peak_receipt
    from tests.test_peak_receipt import _line, _report
    parsed = peak_receipt.parse(_report([
        _line(**{"สถานะ": "รับชำระแล้ว"}),
        _line(**{"สถานะ": "ยกเลิก"}),
        _line(**{"เลขที่เอกสาร": "RE-2"}),
    ]))
    meta = parsed["meta"]
    assert meta["source_read"] == 3 == meta["read"] + len(meta["rejected"])
    assert all(set(row) == {"row", "code", "value"} for row in meta["rejected"])
    page = documents(meta["rejected_documents"])
    assert page["total"] == 1 and page["source_rows"] == 2
    assert [row["observation"]["status_th"] for row in page["rows"][0]["rows"]] == ["รับชำระแล้ว", "ยกเลิก"]


def test_receipt_writer_refuses_a_short_match_list_before_landing_any_row():
    import pytest
    from app.pipelines.peak_writer import write_receipts
    with pytest.raises(ValueError, match='verdict count'):
        write_receipts(None, {'receipts': [{'doc_no': 'RE-1'}]}, [])
