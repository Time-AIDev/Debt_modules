#!/usr/bin/env python3
"""20-user staging load test for the interactive customer-list workflow.

Each worker owns a fresh cookie jar (a fresh browser/session), ramps in, then cycles
through page 1, search, cursor page 2, case detail and officer scoreboard. Defaults
match the acceptance run: 20 users, 60-second ramp, 10 minutes at load.

    python scripts/load_test_workbook.py https://staging.example \
      --vus 20 --ramp 60 --duration 600 --assert-sla --json perf.json
"""
import argparse
import concurrent.futures
import http.cookiejar
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * pct) - 1)]


def request(opener, base_url, path, headers, timeout):
    started = time.perf_counter()
    status, body, error = 0, b"", None
    try:
        req = urllib.request.Request(base_url.rstrip("/") + path, headers=headers)
        with opener.open(req, timeout=timeout) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
        error = "http_%d" % exc.code
    except Exception as exc:  # noqa: BLE001 - the report groups transport failures
        error = exc.__class__.__name__
    return {
        "status": status,
        "ms": (time.perf_counter() - started) * 1000.0,
        "bytes": len(body),
        "error": error,
        "body": body,
    }


def worker(index, args, deadline, output, lock):
    time.sleep(args.ramp * index / max(args.vus, 1))
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip"}
    if args.bearer:
        headers["Authorization"] = "Bearer " + args.bearer
    if args.cookie:
        headers["Cookie"] = args.cookie
    sequence = 0
    first = None
    while time.monotonic() < deadline:
        label = ("page1", "search", "page2", "case_detail", "officer_scoreboard")[sequence % 5]
        if label == "page1":
            path = "/v1/workbook?identities=1&limit=50"
        elif label == "search":
            path = "/v1/workbook?identities=1&limit=50&q=Bench"
        elif label == "page2" and first and first.get("cursor"):
            path = "/v1/workbook?identities=1&limit=50&cursor=" + urllib.parse.quote(first["cursor"], safe="")
        elif label == "case_detail" and first and first.get("uid"):
            path = "/v1/cases/by-customer/" + urllib.parse.quote(first["uid"], safe="")
        elif label == "officer_scoreboard" and first and first.get("officer_uid"):
            path = "/v1/reports/officers/" + urllib.parse.quote(first["officer_uid"], safe="")
        else:
            sequence += 1
            continue
        result = request(opener, args.base_url, path, headers, args.timeout)
        if label == "page1" and result["status"] == 200:
            try:
                decoded = result["body"]
                if decoded[:2] == b"\x1f\x8b":
                    import gzip
                    decoded = gzip.decompress(decoded)
                payload = json.loads(decoded)
                rows = payload.get("rows") or []
                first = {
                    "cursor": (payload.get("page") or {}).get("next_cursor"),
                    "uid": ((rows[0].get("customer") or {}).get("uid")) if rows else None,
                    "officer_uid": next((
                        (row.get("case") or {}).get("officer_uid")
                        or (row.get("customer") or {}).get("officer")
                        for row in rows
                        if ((row.get("case") or {}).get("officer_uid")
                            or (row.get("customer") or {}).get("officer"))
                    ), None),
                }
            except Exception:  # noqa: BLE001 - recorded response still counts
                first = None
        result.pop("body", None)
        result["endpoint"] = label
        with lock:
            output.append(result)
        sequence += 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url")
    parser.add_argument("--vus", type=int, default=20)
    parser.add_argument("--ramp", type=float, default=60)
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--bearer", default=None, help="optional auth token; never written to the report")
    parser.add_argument("--cookie", default=None, help="optional Cookie header; never written to the report")
    parser.add_argument("--json", default=None)
    parser.add_argument("--assert-sla", action="store_true")
    args = parser.parse_args(argv)
    if args.vus < 1 or args.ramp < 0 or args.duration <= 0:
        parser.error("vus/duration must be positive and ramp cannot be negative")

    samples, lock = [], threading.Lock()
    deadline = time.monotonic() + args.ramp + args.duration
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.vus) as pool:
        futures = [pool.submit(worker, i, args, deadline, samples, lock) for i in range(args.vus)]
        for future in futures:
            future.result()

    grouped = defaultdict(list)
    for sample in samples:
        grouped[sample["endpoint"]].append(sample)
    report = {
        "config": {"base_url": args.base_url, "vus": args.vus, "ramp_s": args.ramp,
                   "duration_s": args.duration},
        "total_requests": len(samples),
        "error_rate": (sum(1 for row in samples if row["error"] or row["status"] >= 400) / len(samples))
                      if samples else 1.0,
        "endpoints": {},
    }
    for label, rows in sorted(grouped.items()):
        values = [row["ms"] for row in rows]
        report["endpoints"][label] = {
            "count": len(rows),
            "p50_ms": round(percentile(values, 0.50), 1),
            "p95_ms": round(percentile(values, 0.95), 1),
            "p99_ms": round(percentile(values, 0.99), 1),
            "max_bytes": max(row["bytes"] for row in rows),
            "errors": sum(1 for row in rows if row["error"] or row["status"] >= 400),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if args.assert_sla:
        list_rows = [row for label, row in report["endpoints"].items()
                     if label in ("page1", "search", "page2")]
        list_p95 = max((row["p95_ms"] for row in list_rows), default=float("inf"))
        list_p99 = max((row["p99_ms"] for row in list_rows), default=float("inf"))
        detail_p95 = report["endpoints"].get("case_detail", {}).get("p95_ms", float("inf"))
        officer_p95 = report["endpoints"].get("officer_scoreboard", {}).get("p95_ms", float("inf"))
        page_bytes = report["endpoints"].get("page1", {}).get("max_bytes", float("inf"))
        if (report["error_rate"] >= 0.01 or list_p95 > 1200 or list_p99 > 1800
                or detail_p95 > 500 or officer_p95 > 500 or page_bytes > 100_000):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
