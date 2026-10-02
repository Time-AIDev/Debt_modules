"""The Odoo-lead link the crm.lead merge leaves behind (2026-10-01).

A complete pull retires the ODOO landing row of every lead the SHEET book already
holds, and the served SHEET row's `crm_id` is the Freshworks deal id. Without
records.identity_link source='ODOO_CRM_LEAD' the case loses its Odoo deep link —
exactly what happened to Jessada Nonmaha (Odoo crm.lead 163354).
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app import landing, migrate
from app.pipelines import odoo_links, peak_links, writer


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    pg_conn.execute(text("delete from records.identity_link"))
    pg_conn.commit()
    yield pg_conn
    pg_conn.execute(text("delete from records.identity_link"))
    pg_conn.commit()


def _odoo_record(volt_id, crm_id, phone="0925423597", customer_no=None):
    base = {"volt_id": volt_id, "customer_no": customer_no or volt_id,
            "name_roman": None, "name_th": "ทดสอบ", "epc": "IPW", "product": "LEASE",
            "sales_lead": None, "phone_masked": "09x-xxx-3597",
            "phone_e164": phone, "email_masked": None, "source_refs": [],
            "reason": "no money row in Odoo"}
    base["order"] = {"crm_id": crm_id, "order_type": "Leasing",
                     "order_status": "Order - Done", "loan_status": None,
                     "submit_date": None, "source_ref": []}
    return base


def _sheet_customer(schema, volt_id, customer_no, phone="0925423597", name="Jessada"):
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET", {
        "volt_id": volt_id, "customer_no": customer_no, "name_th": name,
        "name_roman": name, "epc": "VOLT", "product": "LEASE",
        "phone_masked": "09x-xxx-3597", "phone_e164": phone, "source_refs": []})
    landing.finish_run(schema, run, "OK")
    return run


def test_a_merged_lead_leaves_its_odoo_link_before_the_row_retires(schema):
    _sheet_customer(schema, "VL0000143_Long_VOLT", "VL0000143")

    result = writer.write(schema, [_odoo_record("VL0000143", "163354")], [],
                          mode="NEW_ONLY", retire=True)
    assert result["skipped"] == 1
    assert result["links_added"] == 1

    row = schema.execute(text(
        "select source, contact_code, customer_no, odoo_lead_id, rule "
        "from records.identity_link where retired_at is null")).mappings().one()
    assert dict(row) == {"source": "ODOO_CRM_LEAD", "contact_code": "VL0000143",
                         "customer_no": "VL0000143", "odoo_lead_id": 163354,
                         "rule": "ODOO_CRM_LEAD"}
    assert odoo_links.active_for_customers(schema, ["VL0000143"]) == {"VL0000143": 163354}


def test_the_same_link_twice_is_not_rewritten(schema):
    _sheet_customer(schema, "VL0000143_Long_VOLT", "VL0000143")
    writer.write(schema, [_odoo_record("VL0000143", "163354")], [],
                 mode="NEW_ONLY", retire=True)

    second = writer.write(schema, [_odoo_record("VL0000143", "163354")], [],
                          mode="NEW_ONLY", retire=True)
    assert second["links_added"] == 0
    assert second["links_retired"] == 0
    assert schema.execute(text(
        "select count(*) from records.identity_link where source = 'ODOO_CRM_LEAD' "
        "and retired_at is null")).scalar() == 1


def test_a_complete_pull_retires_the_link_its_lead_left(schema):
    _sheet_customer(schema, "VL0000143_Long_VOLT", "VL0000143")
    writer.write(schema, [_odoo_record("VL0000143", "163354")], [],
                 mode="NEW_ONLY", retire=True)

    result = writer.write(schema, [], [], mode="NEW_ONLY", retire=True)
    assert result["links_retired"] == 1
    assert odoo_links.active_for_customers(schema, ["VL0000143"]) == {}
    assert schema.execute(text(
        "select retired_at is not null from records.identity_link "
        "where source = 'ODOO_CRM_LEAD'")).scalar() is True


def test_a_new_lead_id_repoints_the_link_and_keeps_the_history(schema):
    _sheet_customer(schema, "VL0000143_Long_VOLT", "VL0000143")
    writer.write(schema, [_odoo_record("VL0000143", "163354")], [],
                 mode="NEW_ONLY", retire=True)

    result = writer.write(schema, [_odoo_record("VL0000143", "163400")], [],
                          mode="NEW_ONLY", retire=True)
    assert result["links_added"] == 1
    assert result["links_retired"] == 1
    assert odoo_links.active_for_customers(schema, ["VL0000143"]) == {"VL0000143": 163400}
    assert schema.execute(text(
        "select count(*) from records.identity_link "
        "where source = 'ODOO_CRM_LEAD'")).scalar() == 2


def test_a_phone_only_match_never_creates_a_link(schema):
    # Another person's lead can share the phone (Jessada vs the Longlist lead 56010).
    # The writer already refuses to attach that lead; the link register must too.
    _sheet_customer(schema, "VL0000143_Long_VOLT", "VL0000143")
    result = writer.write(schema, [_odoo_record("VL8888888", "56010", customer_no="VL8888888")],
                          [], mode="NEW_ONLY", retire=True)
    assert result["links_added"] == 0
    assert schema.execute(text(
        "select count(*) from records.identity_link")).scalar() == 0


def test_overwrite_mode_never_touches_the_link_register(schema):
    _sheet_customer(schema, "VL0000143_Long_VOLT", "VL0000143")
    writer.write(schema, [_odoo_record("VL0000143", "163354")], [],
                 mode="NEW_ONLY", retire=True)

    writer.write(schema, [_odoo_record("VL0000143", "163354")], [], mode="OVERWRITE")
    assert odoo_links.active_for_customers(schema, ["VL0000143"]) == {"VL0000143": 163354}


def test_the_peak_register_never_reads_an_odoo_lead_link(schema):
    # An Odoo volt_id and a PEAK contact code can be the same string without being
    # the same claim. The PEAK register must not see, retire or re-point Odoo links.
    schema.execute(text(
        "insert into records.identity_link "
        "(source, contact_code, customer_no, odoo_lead_id, rule, confirmed_by) "
        "values ('ODOO_CRM_LEAD', 'VL0000143', 'VL0000143', 163354, 'ODOO_CRM_LEAD', 'system:odoo-sync')"))
    uid = schema.execute(text(
        "select uid from records.identity_link where source = 'ODOO_CRM_LEAD'")).scalar()

    assert peak_links.load(schema) == {}
    assert peak_links.list_links(schema) == []
    assert peak_links.retire(schema, uid, by="settasak") is None
    assert schema.execute(text(
        "select retired_at is null from records.identity_link where uid = :u"),
        {"u": uid}).scalar() is True

    peak_links.confirm(schema, "VL0000143", "VL0000143", by="settasak")
    assert [l["contact_code"] for l in peak_links.list_links(schema)] == ["VL0000143"]
    assert schema.execute(text(
        "select count(*) from records.identity_link where source = 'ODOO_CRM_LEAD' "
        "and retired_at is null")).scalar() == 1


def _customer(identity, crm_id=None, odoo_lead_id=None):
    order = {"crm_id": crm_id} if crm_id is not None else {}
    return SimpleNamespace(
        data_source={"identity": identity, "history": identity},
        sheet={"order": order}, odoo_lead_id=odoo_lead_id)


def test_the_sheet_freshworks_id_never_becomes_an_odoo_link(monkeypatch):
    from app.routers.today import _customer_odoo_crm
    monkeypatch.setenv("ODOO_URL", "https://odoo.example.com")

    # The scientific-notation Freshworks deal id (what the sheet stores for Jessada).
    assert _customer_odoo_crm(_customer("SHEET", crm_id="2.8005118095E10")) is None
    # A plain 11-digit Freshworks id is still not an int4 crm.lead id.
    assert _customer_odoo_crm(_customer("SHEET", crm_id="28005004093")) is None
    # The recorded merge link is the honest source.
    served = _customer_odoo_crm(_customer("SHEET", crm_id="2.8005118095E10",
                                          odoo_lead_id=163354))
    assert served["record_id"] == 163354
    assert served["url"].endswith("/web#id=163354&model=crm.lead&view_type=form")


def test_an_odoo_sourced_row_links_by_its_own_lead_id(monkeypatch):
    from app.routers.today import _customer_odoo_crm
    monkeypatch.setenv("ODOO_URL", "https://odoo.example.com")

    assert _customer_odoo_crm(_customer("ODOO", crm_id="163354"))["record_id"] == 163354
    assert _customer_odoo_crm(_customer("ODOO", crm_id="28005004093")) is None
