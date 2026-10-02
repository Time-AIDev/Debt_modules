"""The seam. book.load_sheet() must return the same shape whichever rung served it.

The unconfigured case is the one that keeps the 569-test contract and a bare
python:3.12-slim CI container working, so it is tested first and hardest.
"""
import pytest

from app import book, book_source, db, landing, migrate


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    db.reset()
    yield
    db.reset()


def test_unconfigured_without_a_private_fixture_returns_no_imported_book(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(book_source, "FIXTURE_PATH", tmp_path / "not-present.json")
    assert book_source.load() is None


@pytest.mark.skipif(not book_source.FIXTURE_PATH.exists(),
                    reason="authorised private sheet fixture is not present")
def test_unconfigured_reads_the_local_private_fixture_when_present(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    payload = book_source.load()
    assert payload is not None
    assert payload["source"]["spreadsheet"] == "New Order Master"
    assert len(payload["customers"]) == 418


def test_book_load_sheet_delegates_to_book_source(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert book.load_sheet() == book_source.load()


def test_unreachable_refuses_rather_than_falling_back(monkeypatch):
    monkeypatch.setenv("DATABASE_URL",
                       "postgresql+psycopg://volt@127.0.0.1:1/nothing_listens_here")
    with pytest.raises(db.DatabaseUnreachable):
        book_source.load()


def test_configured_reads_landing_and_keeps_the_payload_shape(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    run = landing.start_run(pg_conn, "SHEET", spreadsheet_id="SHEET-X")
    landing.write_customer(pg_conn, run, "SHEET",
                           {"volt_id": "V1", "customer_no": "280", "name_roman": "Testname",
                            "product": "LEASE"})
    landing.write_block(pg_conn, run, "SHEET", "V1", "leasing", {"days_late": 0})
    landing.finish_run(pg_conn, run, "OK", row_counts={"customers": 1}, reconciled=True)
    pg_conn.commit()

    monkeypatch.setenv("DATABASE_URL", pg_url)
    payload = book_source.load()
    assert set(payload) >= {"source", "pivots", "flow_stages", "counts", "warnings", "customers"}
    assert len(payload["customers"]) == 1
    row = payload["customers"][0]
    assert row["volt_id"] == "V1" and row["leasing"] == {"days_late": 0}
    assert row["cash"] is None and row["cash_invoices"] == []


def test_odoo_only_serves_the_rows_with_a_volt_id_and_counts_the_rest(monkeypatch, pg_url, pg_conn):
    """The 2026-09-19 ruling: crm.lead is the served book. Phone-only leads (no VOLT
    id) are landed and counted, never served — 34k rows behind every screen would be
    a different product, and none of them can be acted on."""
    migrate.apply(pg_conn)
    # meta.door is what tells a crm.lead run from the sale.order sync (both are
    # source ODOO; the sync writes no meta and runs at every boot).
    run = landing.start_run(pg_conn, "ODOO", meta={"door": "odoo"})
    landing.write_customer(pg_conn, run, "ODOO", {
        "volt_id": "VL0000143", "customer_no": "280", "name_th": "สมชาย", "product": "LEASE"})
    landing.write_customer(pg_conn, run, "ODOO", {
        "volt_id": "phone-925423597", "product": "LEASE"})
    landing.finish_run(pg_conn, run, "OK", row_counts={"landed": 2, "rejected": 0, "read": 2})
    pg_conn.commit()

    monkeypatch.setenv("DATABASE_URL", pg_url)
    payload = book_source.load()
    assert [c["volt_id"] for c in payload["customers"]] == ["VL0000143"]
    source = payload["source"]
    assert source["serving_code"] == "ODOO"
    assert source["serving_name"] == "Odoo crm.lead"
    assert source["served_customers"] == 1
    assert source["landed_customers"] == 2
    assert "1 จาก 2" in source["served_note_th"]


@pytest.mark.skipif(not book_source.FIXTURE_PATH.exists(),
                    reason="authorised private sheet fixture is not present")
def test_dates_and_numerics_come_back_in_the_fixture_s_own_types(monkeypatch, pg_url, pg_conn):
    """A date column returns datetime.date and a numeric returns Decimal, but the
    sheet held ISO strings. The domain compares those against strings, so the
    mismatch surfaced as a 500 on every /v1/pipeline request rather than as
    anything that named a type."""
    from app import migrate, sheet_loader
    import json as _json
    from pathlib import Path as _Path

    migrate.apply(pg_conn)
    fixture = _Path(__file__).resolve().parent.parent / "app" / "fixtures_sheet.json"
    payload = _json.loads(fixture.read_text(encoding="utf-8"))
    sheet_loader.load_payload(pg_conn, payload)
    pg_conn.commit()

    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        loaded = book_source.load()
    finally:
        db.reset()
    order = next(c["order"] for c in loaded["customers"] if c.get("order"))
    for field in ("submit_date", "contract_signed_date", "epc_start_date", "epc_end_date"):
        if order.get(field) is not None:
            assert isinstance(order[field], str), "%s came back as %r" % (field, type(order[field]))
    if order.get("amount_total") is not None:
        assert isinstance(order["amount_total"], str)


def test_the_source_summary_is_counted_once_per_epoch(monkeypatch):
    """111 ms of COUNT(DISTINCT) per call on 34k rows, called by the workbook header
    and /v1/data-state; it can only change when an import lands (sync audit)."""
    import types

    from app import book_source, data_epoch, db, landing

    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(landing, "last_run", lambda conn, source: None)
    monkeypatch.setattr(landing, "last_lead_run", lambda conn: {"id": 1, "meta": {}, "row_counts": {},
                                                               "finished_at": None, "started_at": None})
    calls = {"n": 0}

    def _count(conn, shaped_only=False):
        calls["n"] += 1
        return 10
    monkeypatch.setattr(landing, "count_customers", _count)
    epoch = {"v": 1}
    monkeypatch.setattr(data_epoch, "current", lambda: epoch["v"])
    book_source.forget_summary()

    first = book_source.source_summary()
    assert calls["n"] == 2                          # landed + served, one pass
    assert book_source.source_summary() == first
    assert calls["n"] == 2                          # cached
    epoch["v"] = 2
    book_source.source_summary()
    assert calls["n"] == 4                          # a new epoch recounts
    book_source.forget_summary()
    book_source.source_summary()
    assert calls["n"] == 6                          # and invalidate() clears it
    assert first["serving_code"] == "ODOO"


# --- fix-all leg S: the sheet is the book (synthetic rows only) ----------------------

SHEET_ID = "91000000001_Kanda_กานดา_EPCZ"
LEASE_ROW = {"payment_status": "Current", "term_original": 60, "pmt_inc_vat": "5000.00",
             "first_payment_date": "2025-06-10", "months": []}


def _land_sheet_and_odoo(conn):
    sheet = landing.start_run(conn, "SHEET", spreadsheet_id="SHEET-X")
    landing.write_customer(conn, sheet, "SHEET", {"volt_id": SHEET_ID, "customer_no": "91000000001",
                                                   "name_roman": "Kanda", "product": "LEASE",
                                                   "phone_e164": "+66812345678"})
    landing.write_block(conn, sheet, "SHEET", SHEET_ID, "leasing", dict(LEASE_ROW, volt_id=SHEET_ID))
    landing.finish_run(conn, sheet, "OK", row_counts={"customers": 1})
    odoo = landing.start_run(conn, "ODOO", meta={"door": "odoo"})
    for volt_id, no, phone in ((SHEET_ID, "91000000001", None),          # the same volt_id
                               ("91000000001", "91000000001", None),     # the same customer number
                               ("VL0000902", "VL0000902", "081-234-5678"),  # the same phone
                               ("VL0000903", "VL0000903", "0899999999"),    # someone else
                               ("lead-555", None, None), ("phone-812000000", None, None)):
        landing.write_customer(conn, odoo, "ODOO", {"volt_id": volt_id, "customer_no": no, "product": "LEASE",
                                                     "phone_e164": phone})
    landing.finish_run(conn, odoo, "OK", row_counts={"landed": 6})
    conn.commit()
    return sheet


def test_the_sheet_book_serves_sheet_customers_and_odoo_ids_once(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    _land_sheet_and_odoo(pg_conn)
    monkeypatch.setenv("DATABASE_URL", pg_url)
    payload = book_source.load()
    served = {c["volt_id"]: c["data_source"] for c in payload["customers"]}
    # the sheet row wins its own volt_id; a real Odoo Volt ID is served; placeholder
    # keys and the Odoo rows that ARE the sheet customer (number or phone) are not
    assert served == {SHEET_ID: "SHEET", "VL0000903": "ODOO"}
    source = payload["source"]
    assert (source["served_customers"], source["merged_customers"], source["landed_customers"]) == (2, 2, 6)
    book_source.forget_summary()
    summary = book_source.source_summary()
    assert (summary["served_customers"], summary["merged_customers"]) == (2, 2)


def test_a_landed_book_carries_no_made_up_demo_customer_or_cancellation(monkeypatch, pg_url, pg_conn):
    from app import fixtures, journey, main
    assert journey.for_current().cancellations                     # the in-memory demo keeps them
    migrate.apply(pg_conn)
    _land_sheet_and_odoo(pg_conn)
    monkeypatch.setenv("DATABASE_URL", pg_url)
    book.invalidate()
    loaded = book.build()
    assert book.from_landing(loaded[1])
    served = fixtures.seed(loaded)
    assert [c.volt_id for c in served] == [SHEET_ID]
    monkeypatch.setattr(main, "CUSTOMERS", served)
    journey.reset()
    assert journey.for_current().cancellations == {}


def test_data_as_of_is_the_bangkok_day(monkeypatch, pg_url, pg_conn):
    """A run that finished at 18:30 UTC was captured on the NEXT day in Bangkok —
    whatever timezone the database session hands the stamp back in (Cloud SQL: UTC)."""
    from datetime import datetime, timezone
    from sqlalchemy import text
    assert book_source._iso_date(datetime(2026, 9, 24, 18, 30, tzinfo=timezone.utc)) == "2026-09-25"
    assert book_source._iso_date("2026-09-24T18:30:00Z") == "2026-09-25"
    migrate.apply(pg_conn)
    run = _land_sheet_and_odoo(pg_conn)
    pg_conn.execute(text("update landing.import_run set finished_at = '2026-09-24 18:30:00+00' where id = :i"),
                    {"i": run})
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    assert book_source.load()["source"]["captured_on"] == "2026-09-25"


def _applied_peak_invoice(conn, doc_no, customer_no):
    """An applied PEAK invoice run whose invoice was matched to `customer_no` — as it
    was while the Odoo identities were the served book. Synthetic."""
    import json as _json
    from sqlalchemy import text
    run = conn.execute(text(
        "insert into landing.import_run (source_system, status, finished_at, meta) values "
        "('PEAK', 'OK', now(), cast(:m as jsonb)) returning id"),
        {"m": _json.dumps({"applied": {"at": "2026-09-20T10:00:00+07:00"}, "report_as_of": "2026-09-20"})}).scalar()
    conn.execute(text(
        "insert into landing.peak_invoice (import_run_id, doc_no, doc_kind, due_on, contact_code, status, "
        "amount_total, amount_awaiting, verdict, rule, customer_no, ladder_verdict, ladder_customer_no, "
        "ladder_rule) values (:r, :d, 'INVOICE', '2026-09-10', :no, 'OVERDUE', 5000, 5000, 'EXACT', "
        "'VOLT_ID', :no, 'EXACT', :no, 'VOLT_ID')"), {"r": run, "d": doc_no, "no": customer_no})


def test_a_merged_odoo_identity_s_peak_invoices_ride_on_the_sheet_customer(monkeypatch, pg_url, pg_conn):
    """Audit finding 1: PEAK filed IV-A under the Odoo identity (VL0000902) the sheet
    customer now serves by phone; it must reach the sheet row and its status."""
    from app import cases
    migrate.apply(pg_conn)
    _land_sheet_and_odoo(pg_conn)
    _applied_peak_invoice(pg_conn, "IV-A", "VL0000902")
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    row = next(c for c in book_source.load()["customers"] if c["volt_id"] == SHEET_ID)
    assert [i["doc_no"] for i in row["peak"]["invoices"]] == ["IV-A"]
    book.invalidate()
    customer = next(c for c in book.build()[0] if c.volt_id == SHEET_ID)
    assert cases._peak_says(customer) == "LATE"


def test_a_merged_lead_link_rides_on_the_served_sheet_row(monkeypatch, pg_url, pg_conn):
    """2026-10-01: the crm.lead merge records the Odoo lead id on the link register;
    the served SHEET row must carry it so the case can deep-link to Odoo even though
    its own `crm_id` is the Freshworks deal id."""
    from sqlalchemy import text as _text
    from app.pipelines import writer
    migrate.apply(pg_conn)
    pg_conn.execute(_text("delete from records.identity_link"))
    sheet = landing.start_run(pg_conn, "SHEET")
    landing.write_customer(pg_conn, sheet, "SHEET", {"volt_id": SHEET_ID, "customer_no": "91000000001",
                                                      "name_roman": "Kanda", "product": "LEASE"})
    landing.finish_run(pg_conn, sheet, "OK", row_counts={"customers": 1})
    lead = {"volt_id": "91000000001", "customer_no": "91000000001", "name_th": "กานดา",
            "product": "LEASE", "source_refs": [], "reason": "no money row in Odoo"}
    lead["order"] = {"crm_id": "163354", "order_type": "Leasing", "source_ref": []}
    writer.write(pg_conn, [lead], [], mode="NEW_ONLY", retire=True)
    pg_conn.commit()

    monkeypatch.setenv("DATABASE_URL", pg_url)
    row = next(c for c in book_source.load()["customers"] if c["volt_id"] == SHEET_ID)
    assert row["odoo_lead_id"] == 163354

    book.invalidate()
    _customers, report = book.build()
    customer = next(c for c in report["registry"] if c.volt_id == SHEET_ID)
    assert customer.odoo_lead_id == 163354
    pg_conn.execute(_text("delete from records.identity_link"))
    pg_conn.commit()


def test_a_merged_lead_social_ids_ride_on_the_served_sheet_row(monkeypatch, pg_url, pg_conn):
    from sqlalchemy import text as _text
    from app.pipelines import writer

    migrate.apply(pg_conn)
    pg_conn.execute(_text("delete from records.identity_link"))
    sheet = landing.start_run(pg_conn, "SHEET")
    landing.write_customer(pg_conn, sheet, "SHEET", {
        "volt_id": SHEET_ID, "customer_no": "91000000001",
        "name_roman": "Kanda", "product": "LEASE",
    })
    landing.finish_run(pg_conn, sheet, "OK", row_counts={"customers": 1})
    lead = {
        "volt_id": "91000000001", "customer_no": "91000000001",
        "name_th": "กานดา", "product": "LEASE", "source_refs": [],
        "line_id": "line-kanda", "meta_id": "meta-kanda",
        "reason": "no money row in Odoo",
        "order": {"crm_id": "163354", "order_type": "Leasing", "source_ref": []},
    }
    writer.write(pg_conn, [lead], [], mode="NEW_ONLY", retire=True,
                 refresh_source_rows=True)
    pg_conn.commit()

    monkeypatch.setenv("DATABASE_URL", pg_url)
    row = next(c for c in book_source.load()["customers"] if c["volt_id"] == SHEET_ID)

    assert row["line_id"] == "line-kanda"
    assert row["meta_id"] == "meta-kanda"
    pg_conn.execute(_text("delete from records.identity_link"))
    pg_conn.commit()


def test_a_phone_several_odoo_leads_share_never_merges(monkeypatch, pg_url, pg_conn):
    """Audit finding 5: an agent's or a family's number is on several leads — none of
    them is the sheet customer by phone alone."""
    migrate.apply(pg_conn)
    sheet = landing.start_run(pg_conn, "SHEET")
    landing.write_customer(pg_conn, sheet, "SHEET", {"volt_id": SHEET_ID, "customer_no": "91000000001",
                                                      "product": "LEASE", "phone_e164": "+66815550100"})
    landing.finish_run(pg_conn, sheet, "OK")
    odoo = landing.start_run(pg_conn, "ODOO", meta={"door": "odoo"})
    for volt_id in ("VL0000911", "VL0000912", "VL0000913"):
        landing.write_customer(pg_conn, odoo, "ODOO", {"volt_id": volt_id, "customer_no": volt_id,
                                                        "product": "LEASE", "phone_e164": "081-555-0100"})
    landing.finish_run(pg_conn, odoo, "OK")
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    payload = book_source.load()
    assert sorted(c["volt_id"] for c in payload["customers"]) == [SHEET_ID, "VL0000911", "VL0000912", "VL0000913"]
    assert payload["source"]["merged_customers"] == 0


def test_a_peak_epoch_rereads_only_the_peak_data(monkeypatch, pg_url, pg_conn):
    """Fix-all F3: the served slice of landing is read once per non-PEAK epoch; a
    rebuild after a PEAK apply re-reads the PEAK invoices (and field decisions) alone,
    and a sheet install or a crm.lead pull that changed something reads it all again."""
    from app import data_epoch
    from app.pipelines import field_decisions, peak_writer

    migrate.apply(pg_conn)
    run = landing.start_run(pg_conn, "SHEET")
    landing.write_customer(pg_conn, run, "SHEET", {"volt_id": "V1", "customer_no": "280", "product": "LEASE"})
    landing.finish_run(pg_conn, run, "OK")
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    counts = {}
    for module, name in ((landing, "resolved_customers"), (landing, "resolved_orders"),
                         (landing, "blocks_for"), (peak_writer, "invoices_for_book"),
                         (field_decisions, "load")):
        def counting(*a, _real=getattr(module, name), _name=name, **k):
            counts[_name] = counts.get(_name, 0) + 1
            return _real(*a, **k)
        monkeypatch.setattr(module, name, counting)

    def load():
        assert [c["volt_id"] for c in book_source.load()["customers"]] == ["V1"]

    load()
    data_epoch.bump("peak")                    # a PEAK apply
    load()
    data_epoch.bump("peak-receipt")
    load()
    assert counts == {"resolved_customers": 1, "resolved_orders": 1, "blocks_for": 1,
                      "invoices_for_book": 3, "load": 3}
    data_epoch.bump("sheet")                   # a sheet install (or a pull that changed a row)
    load()
    assert counts["resolved_customers"] == counts["blocks_for"] == 2
    book.invalidate()                          # the test seam drops them as well
    load()
    assert counts["resolved_customers"] == 3



def test_a_cached_rebuild_still_folds_a_merged_identity_s_peak_invoices(monkeypatch, pg_url, pg_conn):
    """Fix-all F audit: the merged pairs travel in the non-PEAK read cache. After a PEAK
    apply the book rebuilds from cached reads, and the Odoo number's new invoice still
    rides on the sheet row — with landing's customers read once."""
    from app import data_epoch
    migrate.apply(pg_conn)
    _land_sheet_and_odoo(pg_conn)
    _applied_peak_invoice(pg_conn, "IV-A", "VL0000902")
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    reads = {"customers": 0}
    real = landing.resolved_customers

    def counting(*a, **k):
        reads["customers"] += 1
        return real(*a, **k)
    monkeypatch.setattr(landing, "resolved_customers", counting)

    def served_invoices():
        row = next(c for c in book_source.load()["customers"] if c["volt_id"] == SHEET_ID)
        return sorted(i["doc_no"] for i in (row["peak"] or {}).get("invoices") or [])

    assert served_invoices() == ["IV-A"]
    _applied_peak_invoice(pg_conn, "IV-B", "VL0000902")      # the next applied PEAK run
    pg_conn.commit()
    data_epoch.bump("peak")
    assert served_invoices() == ["IV-B"]
    assert reads["customers"] == 1
