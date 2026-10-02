"""One run, batched, and honest about what it replaced."""
import pytest
from sqlalchemy import text

from app import landing, migrate
from app.pipelines import writer


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def _record(volt_id, **order):
    base = {"volt_id": volt_id, "customer_no": volt_id, "name_roman": None,
            "name_th": "ทดสอบ", "epc": "IPW", "product": "LEASE",
            "sales_lead": None, "phone_masked": "09x-xxx-3597",
            "phone_e164": "0925423597", "email_masked": None, "source_refs": [],
            "reason": "no money row in Odoo"}
    base["order"] = dict({"crm_id": "1", "order_type": "Leasing",
                          "order_status": "Order - Done", "loan_status": None,
                          "submit_date": None, "source_ref": []}, **order)
    return base


def test_a_run_lands_every_record_and_finishes_ok(schema):
    result = writer.write(schema, [_record("VL0000143"), _record("VL0000144")], [])
    assert result["landed"] == 2
    row = schema.execute(text("select source_system, status, row_counts "
                              "from landing.import_run where id=:i"),
                         {"i": result["run_id"]}).mappings().one()
    assert row["source_system"] == "ODOO"
    assert row["status"] == "OK"
    assert row["row_counts"]["landed"] == 2


def test_batching_lands_the_same_rows_as_one_at_a_time(schema):
    records = [_record("VL%07d" % i) for i in range(2500)]
    writer.write(schema, records, [], batch=1000)
    assert schema.execute(text("select count(*) from landing.customer")).scalar() == 2500


def test_replacing_a_sheet_value_is_recorded_with_both_values(schema):
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143", "name_th": "ชื่อจากชีต",
        "epc": "SLT", "product": "LEASE", "source_refs": []})
    landing.finish_run(schema, run, "OK")

    result = writer.write(schema, [_record("VL0000143")], [])
    assert result["overwrote"] >= 1
    entry = [e for e in result["ledger"] if e["field"] == "epc"][0]
    assert entry == {"volt_id": "VL0000143", "field": "epc",
                     "sheet": "SLT", "odoo": "IPW"}


def test_an_odoo_blank_over_a_filled_sheet_value_is_in_the_ledger_too(schema):
    # The whole point of the ledger under the chosen precedence rule.
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143", "epc": "SLT",
        "product": "LEASE", "sales_lead": "Varunya", "source_refs": []})
    landing.finish_run(schema, run, "OK")

    result = writer.write(schema, [_record("VL0000143")], [])
    assert {"volt_id": "VL0000143", "field": "sales_lead",
            "sheet": "Varunya", "odoo": None} in result["ledger"]


def test_the_phone_is_masked_on_both_sides_of_the_ledger_and_never_in_meta(schema):
    """2026-09-20: the sheet's number is kept whole at import now, so a phone diff
    would put the real digits on import_run.meta — served by the receipt and the
    paginated landing-run route. Both sides land on the mask the customer object
    serves; the audited phone:reveal route is the only door that answers a number."""
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143", "product": "LEASE",
        "phone_masked": "08x-xxx-3333", "phone_e164": "+66812343333", "source_refs": []})
    landing.finish_run(schema, run, "OK")

    result = writer.write(schema, [_record("VL0000143")], [])
    entry = [e for e in result["ledger"] if e["field"] == "phone_e164"]
    assert entry == [{"volt_id": "VL0000143", "field": "phone_e164",
                      "sheet": "08x-xxx-3333", "odoo": "09x-xxx-3597"}]
    meta = schema.execute(text("select meta::text from landing.import_run where id=:i"),
                          {"i": result["run_id"]}).scalar()
    for fragment in ("812343333", "925423597", "+66"):
        assert fragment not in meta
    # The row itself still carries the whole number — that is what reveal answers.
    landed = schema.execute(text("select phone_e164 from landing.customer where volt_id='VL0000143'")).scalar()
    assert landed == "0925423597"


def test_the_verdicts_travel_on_the_run_so_a_rejection_is_never_lost(schema):
    verdicts = [{"volt_id": "", "verdict": "rejected", "rule": "no_identity",
                 "unmapped": []},
                {"volt_id": "VL0000143", "verdict": "landed", "rule": None,
                 "unmapped": [["stage_name", "qualified_lead"]]}]
    result = writer.write(schema, [_record("VL0000143")], verdicts)
    meta = schema.execute(text("select meta from landing.import_run where id=:i"),
                          {"i": result["run_id"]}).scalar()
    assert meta["rejected"] == {"no_identity": 1}
    assert meta["unmapped_sample"] == [["stage_name", "qualified_lead"]]
    assert meta["unmapped_total"] == 1


def test_source_eligibility_exclusions_travel_on_the_run_receipt(schema):
    counts = {"not_won": 35800, "install_start_missing": 40,
              "install_end_missing": 11}
    result = writer.write(schema, [_record("VL0000143")], [],
                          exclusion_counts=counts)
    meta = schema.execute(text("select meta from landing.import_run where id=:i"),
                          {"i": result["run_id"]}).scalar()
    assert meta["eligibility_exclusions"] == counts


def test_filtered_odoo_retirement_preserves_identity_links(schema, monkeypatch):
    from app.pipelines import odoo_links
    calls = []
    monkeypatch.setattr(
        odoo_links, "reconcile",
        lambda conn, desired, retire: calls.append(retire) or (0, 0),
    )

    writer.write(schema, [_record("VL0000143")], [], mode="NEW_ONLY", retire=True,
                 preserve_identity_links=True)

    assert calls == [False]


def test_confirmed_eligibility_preview_bypasses_mass_retire_guard_only_for_exact_count(schema):
    ten = [_record("VL00002%02d" % i) for i in range(10)]
    writer.write(schema, ten, [], mode="NEW_ONLY", retire=True)
    preview = writer.retirement_preview(schema, ten[:7])
    assert preview["would_retire"] == 3

    result = writer.write(schema, ten[:7], [], mode="NEW_ONLY", retire=True,
                          expected_retire=3, preserve_identity_links=True)
    assert result["retired"] == 3


def test_eligibility_preview_counts_missing_odoo_rows_when_every_eligible_row_is_sheet_linked(schema):
    ten = [_record("VL00004%02d" % i) for i in range(10)]
    writer.write(schema, ten, [], mode="NEW_ONLY", retire=True)
    sheet_run = landing.start_run(schema, "SHEET")
    for record in ten[:7]:
        landing.write_customer(schema, sheet_run, "SHEET", {
            **record,
            "name_th": "ข้อมูลผู้ใช้จากชีต",
        })
    landing.finish_run(schema, sheet_run, "OK")

    preview = writer.retirement_preview(schema, ten[:7])

    assert preview["held_by_sheet"] == 7
    assert preview["would_retire"] == 3


def test_eligibility_apply_refreshes_sheet_linked_odoo_source_rows_without_touching_sheet(schema):
    ten = [_record("VL00005%02d" % i) for i in range(10)]
    ten[0]["line_id"] = "old-line"
    ten[0]["meta_id"] = "old-meta"
    writer.write(schema, ten, [], mode="NEW_ONLY", retire=True)
    sheet_run = landing.start_run(schema, "SHEET")
    for record in ten[:7]:
        landing.write_customer(schema, sheet_run, "SHEET", {
            **record,
            "name_th": "ข้อมูลผู้ใช้จากชีต",
            "line_id": None,
            "meta_id": None,
        })
    landing.finish_run(schema, sheet_run, "OK")
    eligible = [dict(record) for record in ten[:7]]
    eligible[0]["line_id"] = "new-line"
    eligible[0]["meta_id"] = "new-meta"

    result = writer.write(
        schema, eligible, [], mode="NEW_ONLY", retire=True,
        expected_retire=3, preserve_identity_links=True,
        refresh_source_rows=True,
    )

    assert result["retired"] == 3
    odoo = schema.execute(text(
        "select line_id, meta_id, retired_at from landing.customer "
        "where volt_id=:v and data_source='ODOO'"
    ), {"v": ten[0]["volt_id"]}).mappings().one()
    assert dict(odoo) == {"line_id": "new-line", "meta_id": "new-meta", "retired_at": None}
    sheet = schema.execute(text(
        "select name_th, line_id, meta_id from landing.customer "
        "where volt_id=:v and data_source='SHEET'"
    ), {"v": ten[0]["volt_id"]}).mappings().one()
    assert dict(sheet) == {
        "name_th": "ข้อมูลผู้ใช้จากชีต",
        "line_id": None,
        "meta_id": None,
    }


def test_changed_count_refuses_eligibility_apply_before_any_row_moves(schema):
    ten = [_record("VL00003%02d" % i) for i in range(10)]
    writer.write(schema, ten, [], mode="NEW_ONLY", retire=True)
    with pytest.raises(writer.PreviewCountMismatch):
        writer.write(schema, ten[:7], [], mode="NEW_ONLY", retire=True,
                     expected_retire=2, preserve_identity_links=True)
    assert schema.execute(text(
        "select count(*) from landing.customer where data_source='ODOO' and retired_at is null"
    )).scalar() == 10


def test_the_writer_reports_a_batch_at_a_time(schema):
    seen = []
    records = [_record("VL%07d" % i) for i in range(2500)]
    writer.write(schema, records, [], batch=1000,
                 on_progress=lambda **kw: seen.append(kw))
    assert seen == [{"landed": 1000}, {"landed": 2000}, {"landed": 2500}]


def test_two_leads_for_one_volt_id_land_once_and_the_drop_is_counted(schema):
    """Odoo's crm.lead can carry the same customer number on two leads. The landing
    upsert is one INSERT ... ON CONFLICT, which Postgres refuses when the same row is
    touched twice in one command — staging's first fresh pull died on it (2026-09-21).
    The pull is ordered by Odoo id, so the last row is the newest lead and wins."""
    result = writer.write(schema, [_record("VL0000143", crm_id="1"),
                                   _record("VL0000143", crm_id="2")], [])
    assert result["landed"] == 1
    assert result["duplicates"] == 1
    rows = schema.execute(text("select count(*) from landing.customer where volt_id='VL0000143'")).scalar()
    assert rows == 1
    crm_id = schema.execute(text("select crm_id from landing.\"order\" where volt_id='VL0000143'")).scalar()
    assert crm_id == "2", "the newest lead wins"
