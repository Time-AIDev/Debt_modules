"""Design F6 / the manager's ask: a crm.lead run adds customers the platform has never
seen and leaves every existing customer and contract exactly as it is. What differs
is written down as a proposal, never applied."""
import pytest
from sqlalchemy import text

from app import landing, migrate
from app.pipelines import writer
from tests.test_pipeline_writer import _record


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def _sheet(conn, volt_id, customer_no, phone=None, **fields):
    run = landing.start_run(conn, "SHEET")
    landing.write_customer(conn, run, "SHEET", dict({"volt_id": volt_id, "customer_no": customer_no,
                                                    "name_th": "ชื่อจากชีต", "epc": "SLT", "product": "LEASE",
                                                    "phone_e164": phone, "source_refs": []}, **fields))
    landing.finish_run(conn, run, "OK")


def _odoo_rows(conn):
    return conn.execute(text("select volt_id from landing.customer where data_source='ODOO' order by volt_id")).scalars().all()


def test_new_only_lands_only_the_leads_nobody_holds(schema):
    _sheet(schema, "28005096535_Manop_มานพ_IPW", "28005096535", phone="0812345678")
    result = writer.write(schema, [_record("28005096535"), _record("VL0009999")], [], mode="NEW_ONLY")
    assert (result["new"], result["skipped"]) == (1, 1)
    assert _odoo_rows(schema) == ["VL0009999"]


def test_an_existing_customer_is_found_by_customer_number_phone_or_v_id_prefix(schema):
    _sheet(schema, "VC0098765_Somchai_สมชาย_SLT", "28006083653", phone="0898765432")
    by_no = _record("28006083653")
    by_phone = dict(_record("VL0000001"), phone_e164="+66898765432")
    by_vid = _record("VC0098765")
    result = writer.write(schema, [by_no, by_phone, by_vid], [], mode="NEW_ONLY")
    assert result["skipped"] == 3 and _odoo_rows(schema) == []
    assert {p["matched_by"] for p in result["proposals"]} <= {"CUSTOMER_NO", "PHONE", "VOLT_ID"}


def test_a_phone_carried_by_one_sheet_customer_still_resolves(schema):
    _sheet(schema, "VC0098765_Somchai_สมชาย_SLT", "28006083653", phone="0898765432")
    lead = dict(_record("VL0000001"), phone_e164="+66898765432")
    result = writer.write(schema, [lead], [], mode="NEW_ONLY")
    assert result["skipped"] == 1 and _odoo_rows(schema) == []
    assert not any(p["kind"] == "SHARED_PHONE" for p in result["proposals"])


def test_a_phone_shared_by_two_sheet_customers_does_not_skip_a_new_lead(schema):
    _sheet(schema, "VC0000001_a", "28000000001", phone="0812345678")
    _sheet(schema, "VC0000002_b", "28000000002", phone="0812345678")
    lead = dict(_record("VL0009999"), phone_e164="0812345678")
    result = writer.write(schema, [lead], [], mode="NEW_ONLY")
    assert (result["new"], result["skipped"]) == (1, 0)
    assert _odoo_rows(schema) == ["VL0009999"]
    prop = next(p for p in result["proposals"] if p["kind"] == "SHARED_PHONE")
    assert set(prop["shared_by"]) == {"28000000001", "28000000002"}


def test_a_differing_field_becomes_a_proposal_with_both_values_and_nothing_moves(schema):
    _sheet(schema, "VL0000143_x", "VL0000143", epc="SLT")
    result = writer.write(schema, [_record("VL0000143")], [], mode="NEW_ONLY")     # _record's epc is IPW
    prop = next(p for p in result["proposals"] if p["kind"] == "FIELDS_DIFFER")
    assert {"field": "epc", "sheet": "SLT", "odoo": "IPW", "odoo_blank": False} in prop["fields"]
    assert schema.execute(text("select epc from landing.customer where data_source='SHEET'")).scalar() == "SLT"


def test_an_odoo_blank_over_a_filled_sheet_value_is_proposed_and_marked(schema):
    _sheet(schema, "VL0000143_x", "VL0000143", epc="SLT", sales_lead="Varunya")
    lead = dict(_record("VL0000143"), sales_lead=None)
    result = writer.write(schema, [lead], [], mode="NEW_ONLY")
    prop = next(p for p in result["proposals"] if p["kind"] == "FIELDS_DIFFER")
    assert {"field": "sales_lead", "sheet": "Varunya", "odoo": None, "odoo_blank": True} in prop["fields"]
    assert schema.execute(text("select sales_lead from landing.customer where data_source='SHEET'")).scalar() == "Varunya"


def test_a_new_v_id_on_an_old_phone_is_a_new_contract_proposal(schema):
    _sheet(schema, "VC0000001_old", "28000000001", phone="0812345678")
    lead = dict(_record("VC0009999"), phone_e164="0812345678")
    result = writer.write(schema, [lead], [], mode="NEW_ONLY")
    assert result["skipped"] == 1
    assert result["proposals"][0]["kind"] == "NEW_CONTRACT_FOR_EXISTING"
    assert result["proposals"][0]["odoo_volt_id"] == "VC0009999"


def test_overwrite_mode_behaves_exactly_as_before(schema):
    _sheet(schema, "VL0000143", "VL0000143", epc="SLT")
    result = writer.write(schema, [_record("VL0000143")], [], mode="OVERWRITE")
    assert result["overwrote"] >= 1 and "VL0000143" in _odoo_rows(schema)


def test_the_run_receipt_says_which_mode_ran(schema):
    result = writer.write(schema, [_record("VL0000143")], [], mode="NEW_ONLY")
    meta = schema.execute(text("select meta from landing.import_run where id=:i"), {"i": result["run_id"]}).scalar()
    assert meta["mode"] == "NEW_ONLY" and meta["new"] == 1 and meta["skipped"] == 0 and meta["proposals"] == []


# --- 2026-09-25: NEW_ONLY sees its own ODOO rows, and a complete pull retires ---------

def _live_odoo(conn):
    return conn.execute(text("select volt_id from landing.customer where data_source='ODOO' "
                             "and retired_at is null order by volt_id")).scalars().all()


def test_an_identical_second_pull_is_all_unchanged_and_moves_no_row(schema):
    leads = [_record("VL0000201"), _record("VL0000202")]
    first = writer.write(schema, [dict(r) for r in leads], [], mode="NEW_ONLY", retire=True)
    assert (first["new"], first["changed"], first["unchanged"]) == (2, 0, 0)
    second = writer.write(schema, [dict(r) for r in leads], [], mode="NEW_ONLY", retire=True)
    assert (second["new"], second["changed"], second["unchanged"], second["landed"]) == (0, 0, 2, 0)
    assert second["retired"] == 0
    owners = schema.execute(text("select distinct import_run_id from landing.customer")).scalars().all()
    assert owners == [first["run_id"]], "an unchanged lead is not rewritten under the new run"


def test_one_changed_field_rewrites_that_lead_only(schema):
    writer.write(schema, [_record("VL0000201"), _record("VL0000202")], [], mode="NEW_ONLY", retire=True)
    moved = dict(_record("VL0000202"), sales_lead="Someone Else")
    verdicts = [{"volt_id": "VL0000201", "verdict": "landed", "rule": None, "unmapped": [["stage_name", "x_y"]]},
                {"volt_id": "VL0000202", "verdict": "landed", "rule": None, "unmapped": [["stage_name", "x_y"]]}]
    result = writer.write(schema, [_record("VL0000201"), moved], verdicts, mode="NEW_ONLY", retire=True)
    assert (result["new"], result["changed"], result["unchanged"], result["landed"]) == (0, 1, 1, 1)
    # the unchanged lead writes no unmapped rows under this run
    assert result["run_id"] and schema.execute(text(
        "select volt_id from landing.import_unmapped where import_run_id = :r"),
        {"r": result["run_id"]}).scalars().all() == ["VL0000202"]


# Ten leads: one retirement is 10% of the served Odoo rows, under the 20% guard.
TEN = ["VL%07d" % (201 + i) for i in range(10)]


def _book(schema, volt_ids=TEN):
    return writer.write(schema, [_record(v) for v in volt_ids], [], mode="NEW_ONLY", retire=True)


def test_a_lead_missing_from_a_complete_pull_is_retired_and_comes_back(schema):
    _book(schema)
    gone = _book(schema, TEN[:-1])
    assert gone["retired"] == 1
    assert _live_odoo(schema) == TEN[:-1]
    assert [r["volt_id"] for r in landing.resolved_customers(schema)] == TEN[:-1]
    back = _book(schema)
    assert (back["new"], back["unchanged"]) == (1, 9), "a retired row is not in the digest index"
    assert _live_odoo(schema) == TEN


def test_a_lead_the_sheet_now_holds_is_not_seen_so_its_odoo_row_retires(schema):
    _book(schema)
    _sheet(schema, TEN[1] + "_x", TEN[1])                   # the same customer number
    result = _book(schema)
    assert (result["skipped"], result["retired"]) == (1, 1)
    assert TEN[1] not in _live_odoo(schema)


def test_leads_the_sheet_now_holds_retire_without_tripping_the_retire_guard(schema):
    """2026-09-25 (runs 325-334 all refused): a sheet install took over 1,667 of the 2,630
    served Odoo rows by customer number, and every later pull refused as "would retire
    too much". Those retirements are the sheet taking over, not a lead gone from Odoo —
    they retire, and only a lead truly missing from the pull counts against the cap."""
    _book(schema)
    for vid in TEN[:7]:
        _sheet(schema, vid + "_x", vid)                      # the sheet now holds seven
    result = _book(schema)
    assert (result["skipped"], result["retired"]) == (7, 7)
    assert _live_odoo(schema) == TEN[7:]


def test_a_different_contract_that_only_shares_a_phone_keeps_its_odoo_row(schema):
    """A sheet row for another contract (its own customer number and V-id) carries the
    same phone as a served Odoo lead: that is a NEW_CONTRACT_FOR_EXISTING proposal,
    "reported, not applied" — the lead is seen, and its row stays served."""
    leads = [dict(_record("VL0000777"), phone_e164="0800000777"),
             dict(_record("VL0000778"), phone_e164="0800000778")]
    writer.write(schema, [dict(r) for r in leads], [], mode="NEW_ONLY", retire=True)
    _sheet(schema, "VC0000555_x_PRB", "28000000555", phone="0800000777")
    result = writer.write(schema, [dict(r) for r in leads], [], mode="NEW_ONLY", retire=True)
    assert (result["skipped"], result["retired"]) == (1, 0)
    assert [(p["kind"], p["odoo_volt_id"], p["matched_by"]) for p in result["proposals"]] == \
        [("NEW_CONTRACT_FOR_EXISTING", "VL0000777", "PHONE")]
    assert _live_odoo(schema) == ["VL0000777", "VL0000778"]
    assert [r["volt_id"] for r in landing.resolved_customers(schema, shaped_only=True)] == \
        ["VC0000555_x_PRB", "VL0000777", "VL0000778"]


def test_a_pull_that_would_retire_over_a_fifth_of_the_served_rows_lands_nothing(schema):
    """A complete but wrong pull (record rules narrowed, a lost field_map row) must
    not empty the Odoo part of the book: it is refused before anything is written."""
    _book(schema)
    changed = dict(_record(TEN[0]), sales_lead="Someone Else")
    before = schema.execute(text("select count(*) from landing.import_run")).scalar()
    with pytest.raises(writer.TooMuchToRetire):
        with schema.begin_nested():                            # _land's transaction, in small
            writer.write(schema, [changed] + [_record(v) for v in TEN[1:7]], [], mode="NEW_ONLY", retire=True)
    assert _live_odoo(schema) == TEN
    assert schema.execute(text("select sales_lead from landing.customer where volt_id = :v"),
                          {"v": TEN[0]}).scalar() is None, "the changed lead was not written either"
    assert schema.execute(text("select count(*) from landing.import_run")).scalar() == before


def test_placeholders_and_legacy_rows_are_outside_the_retire_guard_and_overwrite_is_not_limited(schema):
    # beside the ten served rows: five placeholders, and three rows an older door
    # landed with no digest (the sale.order sync's) — the first pull after the key
    # change retires all eight by design, and the guard must not count them
    writer.write(schema, [_record(v) for v in TEN] + [_record("lead-%d" % i) for i in range(5)],
                 [], mode="NEW_ONLY", retire=True)
    legacy = landing.start_run(schema, "ODOO")
    for i in range(3):
        landing.write_customer(schema, legacy, "ODOO", {"volt_id": "SO900%d_ODOO" % i, "product": "LEASE",
                                                        "source_refs": []})
        landing.write_order(schema, legacy, "ODOO", "SO900%d_ODOO" % i, {"crm_id": "SO900%d" % i})
    landing.finish_run(schema, legacy, "OK")
    first = _book(schema, TEN[:-1])
    assert first["retired"] == 9                                # 5 placeholders + 3 legacy + 1 served
    # a manager's OVERWRITE may retire past the limit
    result = writer.write(schema, [_record(v) for v in TEN[:3]], [], mode="OVERWRITE", retire=True)
    assert result["retired"] == 6
    assert _live_odoo(schema) == TEN[:3]


def test_a_phone_in_another_format_is_not_a_field_difference(schema):
    _sheet(schema, "VL0000143_x", "VL0000143", phone="0925423597")
    lead = dict(_record("VL0000143"), phone_e164="+66 92 542 3597")
    result = writer.write(schema, [lead], [], mode="NEW_ONLY")
    assert all(f["field"] != "phone_e164" for p in result["proposals"] for f in p["fields"])
