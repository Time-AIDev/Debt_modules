import importlib.util
from pathlib import Path


_PATH = Path(__file__).resolve().parents[2] / "scripts" / "bench_peak_receipt.py"
_SPEC = importlib.util.spec_from_file_location("bench_peak_receipt", _PATH)
bench_peak_receipt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bench_peak_receipt)


def test_benchmark_summary_reports_only_safe_aggregate_fields():
    line = bench_peak_receipt.format_summary({
        "median_seconds": 1.23456,
        "max_seconds": 1.5,
        "receipts": 5399,
        "kept_lines": 5889,
        "rejected": 0,
        "peak_rss_mb": 42.25,
        "path": "/private/customer-name.xlsx",
    })

    assert line == (
        "median=1.235s max=1.500s receipts=5399 kept_lines=5889 "
        "rejected=0 peak_rss=42.2MiB"
    )
    assert "customer-name" not in line
