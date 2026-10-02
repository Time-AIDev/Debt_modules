#!/usr/bin/env python3
"""Load 10x the current book into a scratch database and time the paths that pay.

The plan (README, 2026-09-20) targets ~350k landed leads and ~25k served rows, 10x
today's pull. Nothing here estimates: it lands synthetic rows through the REAL
pipeline code (`crm_lead.normalise` -> `writer.write`, the same sequence
`pipelines.service._land` runs), then times the real `book_source.load()` /
`book.build()` and the endpoints whose latency matters. Run it before a change and
after it, same command, and the difference is the change.

The database is dedicated and rebuilt on every run: `volt_bench` by default, never
`volt_debt` (the walkthrough book) and never `volt_test` (the suite's).
`scripts/pg_local.sh start` creates it if absent; every schema this script touches is
dropped and re-migrated first, so a run is repeatable.

    backend/.venv/bin/python scripts/bench_scale.py            # 350k / 25k
    backend/.venv/bin/python scripts/bench_scale.py --leads 50000   # a quick smoke
    backend/.venv/bin/python scripts/bench_scale.py --skip-seed     # reads only

The suite's `pg_conn` never sees this database; nothing here writes to the prototype.
"""
import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PG_LOCAL = ROOT / "scripts" / "pg_local.sh"


def say(message):
    print(message, flush=True)


def timed(fn):
    started = time.perf_counter()
    value = fn()
    return (time.perf_counter() - started), value


def ensure_database(name):
    out = subprocess.run([str(PG_LOCAL), "start", name], check=True,
                         capture_output=True, text=True).stdout.strip().splitlines()
    url = out[-1].strip()
    if not url.startswith("postgresql"):
        raise SystemExit("pg_local.sh did not print a URL: %r" % out)
    return url


def raw_rows(leads, served):
    """crm.lead-shaped dicts, the same keys `ingress.from_odoo` fills.

    `served` of them carry a real VOLT id (`VL` + 7 digits, the shape the live pull
    uses); the rest carry Odoo's literal "New" placeholder with a phone, which is
    how a majority of the 34,147 real leads land — and which `book_source` counts
    but does not serve. This is what makes the served/landed split in the report.
    """
    rows = []
    for i in range(leads):
        served_row = i < served
        phone = "08%08d" % i
        rows.append({
            "id": 900000 + i,
            "volt_id": ("VL%07d" % i) if served_row else "New",
            "contact_name": "Bench %06d" % i,
            "phone": phone,
            "mobile": False,
            "email_from": "bench%d@volt.co.th" % i,
            "order_type": "Leasing" if i % 2 == 0 else "Cash",
            "stage_name": "new",
            "connection_type": "new_install",
            "com_status": False,
            "submitted_date": "2026-01-15",
            "contract_signed_date": "2026-02-01" if served_row else False,
            "epc_start_date": "2026-03-01" if served_row else False,
            "epc_end_date": False,
            "epc_start_month_year": "2026-03",
            "epc": "EPC%06d" % i,
            "install_province": "Bangkok",
            "zip": "10250",
            "user_id": "7|Bench Officer",
            "inverter_kw": "5",
        })
    return rows


def lease_block(i):
    return {
        "pmt_inc_vat": "12900",
        "term_original": 96,
        "first_payment_date": "2023-10-10",
        "payment_status": "Late",
        "days_late": 45,
        "contract_signed": "2023-09-10",
        "comment_th": "bench row",
        "months": [{"kind": "LATE", "amount": "12900"},
                   {"kind": "PAID", "amount": "12900"}],
    }


def reset_schema(db):
    from sqlalchemy import text
    with db.connect() as conn:
        with conn.begin():
            for schema in ("landing", "app", "audit", "records"):
                conn.execute(text("drop schema if exists %s cascade" % schema))


def db_size_mb(db):
    from sqlalchemy import text
    with db.connect() as conn:
        return conn.execute(text("select pg_database_size(current_database())")).scalar() / 1e6


def table_counts(db):
    from sqlalchemy import text
    counts = {}
    with db.connect() as conn:
        for table in ("landing.customer", 'landing."order"', "landing.customer_block",
                      "landing.peak_invoice", "app.session_state", "audit.entry"):
            try:
                counts[table] = conn.execute(
                    text("select count(*) from %s" % table)).scalar()
            except Exception:
                counts[table] = None
    return counts


def endpoint_times(client, paths, repeats):
    results = {}
    for path, method in paths:
        samples = []
        status = None
        response = None
        for _ in range(repeats):
            started = time.perf_counter()
            if method == "GET":
                response = client.get(path)
            else:
                response = client.post(path, json={})
            samples.append((time.perf_counter() - started) * 1000.0)
            status = response.status_code
            if status >= 400 and repeats == 1:
                break
        ordered = sorted(samples)
        p95 = ordered[max(0, int(len(ordered) * 0.95 + 0.999999) - 1)]
        p99 = ordered[max(0, int(len(ordered) * 0.99 + 0.999999) - 1)]
        results[path] = {"status": status, "ms_min": round(min(samples), 1),
                         "ms_median": round(statistics.median(samples), 1),
                         "ms_p95": round(p95, 1),
                         "ms_p99": round(p99, 1),
                         "raw_bytes": len(response.content) if response is not None else None,
                         "wire_bytes": int(response.headers["content-length"])
                         if response is not None and response.headers.get("content-length") else None,
                         "content_encoding": response.headers.get("content-encoding") if response is not None else None,
                         "samples_ms": [round(s, 1) for s in samples]}
    return results


def rss_mb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--leads", type=int, default=350000)
    parser.add_argument("--served", type=int, default=25000,
                        help="rows carrying a real VOLT id (the served slice)")
    parser.add_argument("--contracts", type=int, default=1000,
                        help="served rows given a leasing block, so book.build has cases")
    parser.add_argument("--database", default="volt_bench")
    parser.add_argument("--repeats", type=int, default=2, help="endpoint samples")
    parser.add_argument("--skip-seed", action="store_true",
                        help="measure reads against whatever is already landed")
    parser.add_argument("--skip-endpoints", action="store_true")
    parser.add_argument("--json", default=None, help="write the full report here")
    parser.add_argument("--assert-sla", action="store_true",
                        help="exit non-zero unless the interactive workbook meets its backend gates")
    args = parser.parse_args(argv)

    if args.served > args.leads:
        raise SystemExit("--served cannot exceed --leads")
    if args.contracts > args.served:
        raise SystemExit("--contracts cannot exceed --served")

    url = ensure_database(args.database)
    os.environ["DATABASE_URL"] = url
    os.environ.pop("AUTH_MODE", None)
    sys.path.insert(0, str(BACKEND))

    from app import book as book_mod
    from app import book_source, db
    from app import migrate
    from app.pipelines import crm_lead, rules as rules_mod, writer

    report = {"scale": {"leads": args.leads, "served": args.served,
                        "contracts": args.contracts, "database": args.database},
              "database_url": url, "steps": {}}

    say("Bench scale: %s leads, %s served, %s contracts -> %s"
        % (args.leads, args.served, args.contracts, args.database))

    if not args.skip_seed:
        reset_schema(db)
        with db.connect() as conn:
            with conn.begin():
                migrate.apply(conn)
        say("schema: dropped and re-migrated")

        seconds, rows = timed(lambda: raw_rows(args.leads, args.served))
        report["steps"]["generate_rows_s"] = round(seconds, 2)
        say("rows generated: %s in %.2fs" % (len(rows), seconds))

        rules = rules_mod.load()
        seconds, normalised = timed(lambda: crm_lead.normalise(rows, rules))
        records, verdicts = normalised
        report["steps"]["normalise_s"] = round(seconds, 2)
        report["normalise"] = {"records": len(records), "verdicts": len(verdicts)}
        say("normalise: %s records, %s verdicts in %.2fs"
            % (len(records), len(verdicts), seconds))

        def land():
            conn = db.connect()
            try:
                with conn.begin():
                    return writer.write(conn, records, verdicts, read=len(rows),
                                        door="bench", mode="NEW_ONLY")
            finally:
                conn.close()

        seconds, result = timed(land)
        report["steps"]["writer_write_s"] = round(seconds, 2)
        report["writer"] = {"landed": result.get("landed"), "run_id": result.get("run_id")}
        say("writer.write: %s landed in %.2fs" % (result.get("landed"), seconds))

        block_count = min(args.contracts, args.served)
        if block_count:

            def seed_blocks():
                conn = db.connect()
                try:
                    with conn.begin():
                        for i in range(block_count):
                            from app import landing
                            landing.write_block(conn, result["run_id"], "ODOO",
                                                "VL%07d" % i, "leasing", lease_block(i))
                finally:
                    conn.close()

            seconds, _ = timed(seed_blocks)
            report["steps"]["seed_blocks_s"] = round(seconds, 2)
            say("lease blocks: %d in %.2fs" % (block_count, seconds))

        # The seeding process holds 350k raw dicts and records; releasing them before
        # the read measurements keeps the RSS numbers about the app, not the generator.
        del rows, records, verdicts, result

    # Reads: the same functions the app runs at boot, timed without any HTTP.
    report["rss_after_seed_mb"] = rss_mb()
    seconds, payload = timed(book_source.load)
    report["steps"]["book_source_load_s"] = round(seconds, 2)
    say("book_source.load(): %.2fs" % seconds)

    # `book.build()` calls load_sheet() itself, so timing it bare would time a
    # SECOND full load. The seam is patched to hand back the payload just read, and
    # restored after, so this number is object construction alone.
    original_load = book_source.load
    book_source.load = lambda: payload
    try:
        seconds, built = timed(book_mod.build)
    finally:
        book_source.load = original_load
    customers, migration_report = built
    report["steps"]["book_build_s"] = round(seconds, 2)
    report["book"] = {"with_contracts": len(customers),
                      "identities": len(migration_report.get("registry") or []),
                      "imported": migration_report.get("imported")}
    say("book.build(): %s with contracts, %s identities in %.2fs"
        % (len(customers), report["book"]["identities"], seconds))

    seconds, main_module = timed(lambda: __import__("app.main", fromlist=["app"]))
    report["steps"]["app_import_s"] = round(seconds, 2)
    report["rss_after_boot_mb"] = rss_mb()
    say("import app.main (serves the book): %.2fs" % seconds)

    if not args.skip_endpoints:
        from fastapi.testclient import TestClient
        workbook_page = "/v1/workbook?identities=1&limit=50"
        paths = [
            ("/healthz", "GET"),
            ("/v1/board/columns", "GET"),
            ("/v1/shell/summary", "GET"),
            ("/v1/today", "GET"),
            ("/v1/workbook", "GET"),
            (workbook_page, "GET"),
            ("/v1/workbook?identities=1&limit=50&q=Bench%20000001", "GET"),
            ("/v1/reports/weekly", "GET"),
            ("/v1/reports/officers", "GET"),
        ]
        with TestClient(main_module.app) as client:
            first_page = client.get(workbook_page).json()
            next_cursor = (first_page.get("page") or {}).get("next_cursor")
            if next_cursor:
                paths.append((workbook_page + "&cursor=" + quote(next_cursor, safe=""), "GET"))
            first_rows = first_page.get("rows") or []
            first_uid = ((first_rows or [{}])[0].get("customer") or {}).get("uid")
            if first_uid:
                paths.append(("/v1/cases/by-customer/" + quote(first_uid, safe=""), "GET"))
            first_officer_uid = next((
                (row.get("case") or {}).get("officer_uid")
                or (row.get("customer") or {}).get("officer")
                for row in first_rows
                if ((row.get("case") or {}).get("officer_uid")
                    or (row.get("customer") or {}).get("officer"))
            ), None)
            if first_officer_uid:
                paths.append(("/v1/reports/officers/" + quote(first_officer_uid, safe=""), "GET"))
            warmup = {}
            for path, method in paths:
                started = time.perf_counter()
                response = client.get(path) if method == "GET" else client.post(path, json={})
                warmup[path] = {"status": response.status_code,
                                "ms": round((time.perf_counter() - started) * 1000.0, 1)}
                say("  warm-up %-20s -> %s %8.1fms"
                    % (path, response.status_code, warmup[path]["ms"]))
            report["warmup"] = warmup
            report["endpoints"] = endpoint_times(client, paths, args.repeats)

    report["max_rss_mb"] = rss_mb()
    report["db_size_mb"] = round(db_size_mb(db), 1)
    report["rows"] = table_counts(db)

    say("")
    say("step timings (s):")
    for key, value in sorted(report["steps"].items()):
        say("  %-22s %10.2f" % (key, value))
    if report.get("endpoints"):
        say("endpoint timings (ms, median of %d):" % args.repeats)
        for path, row in report["endpoints"].items():
            say("  %-64s p50 %8.1f  p95 %8.1f  p99 %8.1f  status %s"
                % (path, row["ms_median"], row["ms_p95"], row["ms_p99"], row["status"]))
    say("max RSS %.1f MB · database %.1f MB" % (report["max_rss_mb"], report["db_size_mb"]))

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        say("report written to %s" % args.json)
    if args.assert_sla:
        page = report.get("endpoints", {}).get("/v1/workbook?identities=1&limit=50") or {}
        failures = []
        if page.get("status") != 200:
            failures.append("workbook page did not return 200")
        interactive_lists = [
            (path, row) for path, row in report.get("endpoints", {}).items()
            if path.startswith("/v1/workbook?identities=1&limit=50")
        ]
        for path, row in interactive_lists:
            if row.get("ms_p95", float("inf")) > 1200:
                failures.append("%s p95 exceeds 1200 ms" % path)
            if row.get("ms_p99", float("inf")) > 1800:
                failures.append("%s p99 exceeds 1800 ms" % path)
        if (page.get("raw_bytes") or float("inf")) > 500_000:
            failures.append("workbook page exceeds 500 KB raw")
        if (page.get("wire_bytes") or float("inf")) > 100_000:
            failures.append("workbook page exceeds 100 KB on the wire")
        detail = next((row for path, row in report.get("endpoints", {}).items()
                       if path.startswith("/v1/cases/by-customer/")), None)
        if not detail or detail.get("ms_p95", float("inf")) > 500:
            failures.append("case detail p95 exceeds 500 ms")
        officer = next((row for path, row in report.get("endpoints", {}).items()
                        if path.startswith("/v1/reports/officers/")), None)
        if not officer or officer.get("ms_p95", float("inf")) > 500:
            failures.append("officer scoreboard p95 exceeds 500 ms")
        if failures:
            for failure in failures:
                say("SLA FAIL: " + failure)
            return 2
        say("SLA PASS: interactive backend gates met")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
