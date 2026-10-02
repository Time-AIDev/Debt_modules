"""The sheet's payload goes into landing without changing shape on the way."""
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app import book_source, landing, migrate, sheet_loader

FIXTURE = Path(__file__).resolve().parent.parent / "app" / "fixtures_sheet.json"
pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(), reason="authorised private sheet fixture is not present"
)


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def test_loads_every_customer_from_the_real_export(schema):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = sheet_loader.load_payload(schema, payload)
    assert result["customers"] == 418
    assert schema.execute(text("select count(*) from landing.customer")).scalar() == 418


def test_the_run_carries_the_sheet_identity_and_counts(schema):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = sheet_loader.load_payload(schema, payload)
    row = schema.execute(text("select * from landing.import_run where id=:i"),
                         {"i": result["import_run_id"]}).mappings().one()
    assert row["source_system"] == "SHEET"
    assert row["spreadsheet_id"] == "SYNTHETIC"
    assert row["status"] == "OK"
    assert row["row_counts"]["customers"] == 418


def test_a_leasing_block_round_trips_byte_for_byte(schema):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sheet_loader.load_payload(schema, payload)
    original = next(c for c in payload["customers"] if c.get("leasing"))
    stored = landing.blocks_for(schema, [original["volt_id"]])[original["volt_id"]]["leasing"]
    assert stored == original["leasing"]


def test_the_book_reads_back_the_same_customer_count(schema, monkeypatch, pg_url):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sheet_loader.load_payload(schema, payload)
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    from app import db
    db.reset()
    try:
        assert len(book_source.load()["customers"]) == 418
    finally:
        db.reset()


def test_no_order_field_is_lost_in_the_round_trip(schema, monkeypatch, pg_url):
    """The normalised columns hold ten of the sheet's twenty-four order keys.

    The other thirteen — dp_amount, dp_pct, epc, term, watt, monthly_rate_inc_vat,
    project_type, province, odoo_id, peak_id and the masked contacts — go to
    `extra`. Dropping them made GET /v1/pipeline return 500, because the
    down-payment gate reads dp_amount. This test is why that cannot recur.
    """
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sheet_loader.load_payload(schema, payload)
    schema.commit()

    original = next(c for c in payload["customers"] if c.get("order"))
    monkeypatch.setenv("DATABASE_URL", pg_url)
    from app import db
    db.reset()
    try:
        loaded = book_source.load()
    finally:
        db.reset()
    got = next(c for c in loaded["customers"] if c["volt_id"] == original["volt_id"])["order"]
    missing = sorted(k for k in original["order"] if k not in got)
    assert missing == [], "these order fields were lost: %s" % missing


def test_the_sheets_own_pivots_survive_the_round_trip(schema, monkeypatch, pg_url):
    """REQ-INT-032: the migration report reconciles against the sheet's own pivots,
    or says why not. Empty pivots meant it could do neither."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sheet_loader.load_payload(schema, payload)
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    from app import db
    db.reset()
    try:
        loaded = book_source.load()
    finally:
        db.reset()
    assert loaded["pivots"]["payment_status"] == payload["pivots"]["payment_status"]
    assert loaded["flow_stages"] == payload["flow_stages"]


def test_the_landed_book_is_derived_as_of_the_day_the_sheet_was_captured(schema, monkeypatch, pg_url):
    """Fix-all leg S: the sheet knows what was paid up to its capture day, so a landed
    contract is derived as of that day (a synthetic row, due on the 10th from June),
    and a new calendar day never builds a second book."""
    from datetime import date
    from app import book, db
    assert book.snapshot_date() == date(2026, 9, 2)            # the held fixture's own day
    volt_id = "91000000005_Somsri_สมศรี_EPCZ"
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET", {"volt_id": volt_id, "customer_no": "91000000005",
                                                  "product": "LEASE"})
    landing.write_block(schema, run, "SHEET", volt_id, "leasing", {
        "volt_id": volt_id, "payment_status": "Current", "term_original": 60, "pmt_inc_vat": "5000.00",
        "first_payment_date": "2026-06-10", "months": []})
    landing.finish_run(schema, run, "OK")
    schema.execute(text("update landing.import_run set finished_at = '2026-08-20 03:00:00+00' where id = :i"),
                   {"i": run})
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        book.invalidate()
        customers, _report = book.build()
        # due 10 Jun, 10 Jul, 10 Aug by the 20 Aug capture — not the five due by 23 Oct
        assert customers[0].contracts[0].paid_through == 3
        assert book.snapshot_date() == date(2026, 8, 20)
        monkeypatch.setenv("VOLT_BUSINESS_DATE", "2026-10-24")
        assert book.build()[0][0] is customers[0]
    finally:
        db.reset()
