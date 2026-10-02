"""Rows go in, rows come back, and precedence is applied by the database.

The precedence property is the one that matters: a SHEET row for a volt_id wins
over an ODOO row for the same volt_id (Arina, 2026-09-24: the sheet is the book), a
FAILED run is invisible, and so is a retired row.
"""
import pytest
from sqlalchemy import text

from app import landing, migrate


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def test_start_run_returns_an_id_and_marks_it_running(schema):
    run = landing.start_run(schema, "SHEET", spreadsheet_id="SHEET-X")
    row = schema.execute(text("select status, spreadsheet_id from landing.import_run where id=:i"),
                         {"i": run}).one()
    assert row.status == "RUNNING" and row.spreadsheet_id == "SHEET-X"


def test_finish_run_records_counts_and_status(schema):
    run = landing.start_run(schema, "SHEET")
    landing.finish_run(schema, run, "OK", row_counts={"customers": 418}, reconciled=True)
    row = schema.execute(text("select status, row_counts, reconciled, finished_at "
                              "from landing.import_run where id=:i"), {"i": run}).one()
    assert row.status == "OK" and row.row_counts == {"customers": 418}
    assert row.reconciled is True and row.finished_at is not None


def test_write_and_resolve_a_sheet_customer(schema):
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET",
                           {"volt_id": "V1", "customer_no": "280", "name_roman": "Testname",
                            "name_th": "ทดลอง", "epc": "IPW", "product": "LEASE",
                            "sales_lead": "Varunya", "phone_masked": "08x-xxx-4810",
                            "email_masked": "p•••@yahoo.co.th", "source_refs": [[13, 2]]})
    landing.finish_run(schema, run, "OK")
    rows = landing.resolved_customers(schema)
    assert len(rows) == 1
    assert rows[0]["name_th"] == "ทดลอง" and rows[0]["data_source"] == "SHEET"


def test_the_sheet_wins_over_odoo_for_the_same_volt_id(schema):
    sheet = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, sheet, "SHEET", {"volt_id": "V1", "name_roman": "FromSheet"})
    landing.finish_run(schema, sheet, "OK")
    odoo = landing.start_run(schema, "ODOO")
    landing.write_customer(schema, odoo, "ODOO", {"volt_id": "V1", "name_roman": "FromOdoo"})
    landing.finish_run(schema, odoo, "OK")
    rows = landing.resolved_customers(schema)
    assert len(rows) == 1 and rows[0]["name_roman"] == "FromSheet"


def test_a_failed_run_is_invisible(schema):
    sheet = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, sheet, "SHEET", {"volt_id": "V1", "name_roman": "FromSheet"})
    landing.finish_run(schema, sheet, "OK")
    odoo = landing.start_run(schema, "ODOO")
    landing.write_customer(schema, odoo, "ODOO", {"volt_id": "V1", "name_roman": "HalfWritten"})
    landing.finish_run(schema, odoo, "FAILED", note="odoo refused the login")
    rows = landing.resolved_customers(schema)
    assert rows[0]["name_roman"] == "FromSheet", "a failed run must never serve rows"


def test_blocks_round_trip_unchanged(schema):
    run = landing.start_run(schema, "SHEET")
    payload = {"days_late": 0, "months": [{"kind": "PAID", "amount": "3199.00"}]}
    landing.write_block(schema, run, "SHEET", "V1", "leasing", payload)
    landing.finish_run(schema, run, "OK")
    assert landing.blocks_for(schema, ["V1"])["V1"]["leasing"] == payload


def test_batched_writes_land_the_same_rows_as_one_at_a_time(schema):
    run = landing.start_run(schema, "ODOO")
    customers = [{"volt_id": "VL%07d" % i, "customer_no": "VL%07d" % i,
                  "name_th": "แถว %d" % i, "source_refs": [[i, 2]]} for i in range(25)]
    assert landing.write_customers(schema, run, "ODOO", customers, batch=10) == 25
    orders = [("VL%07d" % i, {"crm_id": str(i), "order_type": "Cash",
                              "amount_total": "100.00", "private_note": "keep%d" % i})
              for i in range(25)]
    assert landing.write_orders(schema, run, "ODOO", orders, batch=10) == 25
    landing.finish_run(schema, run, "OK")

    rows = landing.resolved_customers(schema)
    assert len(rows) == 25
    assert rows[7]["name_th"] == "แถว 7" and rows[7]["source_refs"] == [[7, 2]]
    order = landing.resolved_orders(schema)["VL0000007"]
    assert order["crm_id"] == "7" and order["order_type"] == "Cash"
    assert order["extra"]["private_note"] == "keep7", "extra must survive the chunked path"


def test_a_batched_write_updates_its_own_row(schema):
    run = landing.start_run(schema, "ODOO")
    landing.write_customers(schema, run, "ODOO", [{"volt_id": "VL1", "name_th": "แรก"}])
    landing.write_customers(schema, run, "ODOO",
                            [{"volt_id": "VL1", "name_th": "ใหม่"}, {"volt_id": "VL2"}], batch=10)
    landing.finish_run(schema, run, "OK")
    rows = {r["volt_id"]: r for r in landing.resolved_customers(schema)}
    assert len(rows) == 2 and rows["VL1"]["name_th"] == "ใหม่"


def test_an_empty_batch_executes_nothing(schema):
    run = landing.start_run(schema, "ODOO")
    assert landing.write_customers(schema, run, "ODOO", []) == 0
    assert landing.write_orders(schema, run, "ODOO", []) == 0
    assert schema.execute(text("select count(*) from landing.customer")).scalar() == 0
    assert schema.execute(text('select count(*) from landing."order"')).scalar() == 0



def _landed(conn, source, volt_ids):
    run = landing.start_run(conn, source)
    for volt_id in volt_ids:
        landing.write_customer(conn, run, source, {"volt_id": volt_id, "name_roman": volt_id})
        landing.write_order(conn, run, source, volt_id, {"order_type": "Leasing"})
        landing.write_block(conn, run, source, volt_id, "tracking", {"category": "Active"})
    landing.finish_run(conn, run, "OK")
    return run


def test_retire_unseen_hides_every_row_of_a_volt_id_the_run_did_not_carry(schema):
    _landed(schema, "ODOO", ["VA", "VB", "VC"])
    assert landing.retire_unseen(schema, "ODOO", ["VA", "VC"]) == 1
    assert [r["volt_id"] for r in landing.resolved_customers(schema)] == ["VA", "VC"]
    assert set(landing.resolved_orders(schema)) == {"VA", "VC"}
    assert set(landing.blocks_for(schema, ["VA", "VB", "VC"])) == {"VA", "VC"}
    assert landing.count_customers(schema) == 2
    # landing it again brings it back
    _landed(schema, "ODOO", ["VB"])
    assert {r["volt_id"] for r in landing.resolved_customers(schema)} == {"VA", "VB", "VC"}


def test_retire_unseen_touches_only_its_own_source_and_refuses_an_empty_run(schema):
    _landed(schema, "SHEET", ["VS"])
    _landed(schema, "ODOO", ["VO"])
    assert landing.retire_unseen(schema, "ODOO", ["VX"]) == 1
    assert [r["volt_id"] for r in landing.resolved_customers(schema)] == ["VS"]
    with pytest.raises(ValueError):
        landing.retire_unseen(schema, "SHEET", [])


def test_a_placeholder_key_is_never_served(schema):
    _landed(schema, "ODOO", ["VL0000001", "lead-42", "phone-812345678"])
    assert [r["volt_id"] for r in landing.resolved_customers(schema, shaped_only=True)] == ["VL0000001"]
    assert landing.count_customers(schema, shaped_only=True) == 1


def test_sweep_running_fails_only_old_running_runs(schema):
    stale = landing.start_run(schema, "ODOO")
    fresh = landing.start_run(schema, "ODOO")
    schema.execute(text("update landing.import_run set started_at = now() - interval '2 hours' "
                        "where id = :i"), {"i": stale})
    assert landing.sweep_running(schema, "ODOO", older_than_minutes=30) == [stale]
    statuses = dict(schema.execute(text("select id, status from landing.import_run "
                                        "where id in (:a, :b)"), {"a": stale, "b": fresh}).all())
    assert statuses == {stale: "FAILED", fresh: "RUNNING"}
