#!/usr/bin/env python3
"""Benchmark the pure PEAK receipt parser without printing workbook values.

The workbook remains outside the repository. One warm-up parse is followed by the
requested number of measured parses so before/after runs are comparable.
"""
import argparse
import resource
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.pipelines import peak_receipt  # noqa: E402


def _peak_rss_mb():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux and common CI images report KiB.
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def benchmark(path, repeats=5):
    workbook = Path(path)
    raw = workbook.read_bytes()
    peak_receipt.parse(raw, workbook.name)
    samples = []
    parsed = None
    for _ in range(repeats):
        started = time.perf_counter()
        parsed = peak_receipt.parse(raw, workbook.name)
        samples.append(time.perf_counter() - started)
    return {
        "median_seconds": statistics.median(samples),
        "max_seconds": max(samples),
        "receipts": len(parsed["receipts"]),
        "kept_lines": parsed["meta"]["read"],
        "rejected": len(parsed["meta"]["rejected"]),
        "peak_rss_mb": _peak_rss_mb(),
    }


def format_summary(result):
    return (
        f"median={result['median_seconds']:.3f}s max={result['max_seconds']:.3f}s "
        f"receipts={result['receipts']} kept_lines={result['kept_lines']} "
        f"rejected={result['rejected']} peak_rss={result['peak_rss_mb']:.1f}MiB"
    )


def main():
    parser = argparse.ArgumentParser(description="Benchmark a PEAK receipt workbook safely")
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    print(format_summary(benchmark(args.workbook, args.repeats)))


if __name__ == "__main__":
    main()
