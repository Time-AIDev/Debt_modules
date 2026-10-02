"""The filename carries a period, not just an end date."""
import pytest
from app.pipelines import peak_report, peak_writer

REAL = "invoice_x_export_as_of_20240101_20260914_20260914_155330.xlsx"


def test_range_reads_both_dates():
    assert peak_report.report_range(REAL) == ("2024-01-01", "2026-09-14")


def test_as_of_is_the_end_of_the_range():
    assert peak_report.report_as_of(REAL) == "2026-09-14"


def test_a_name_that_does_not_say():
    assert peak_report.report_range("renamed.xlsx") == (None, None)


def test_a_narrower_report_is_refused_even_when_it_ends_later():
    applied = {"covers_from": "2024-01-01"}
    with pytest.raises(peak_writer.WriterRefused) as e:
        peak_writer.check_range({"covers_from": "2026-08-01"}, applied, allow_older=False)
    assert e.value.code == "report_range_narrower"


def test_a_report_that_covers_everything_applied_passes():
    peak_writer.check_range({"covers_from": "2024-01-01"}, {"covers_from": "2024-01-01"}, allow_older=False)


def test_allow_older_lets_a_person_through():
    peak_writer.check_range({"covers_from": "2026-08-01"}, {"covers_from": "2024-01-01"}, allow_older=True)
