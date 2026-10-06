"""Only verified Won CRM identities may reach the staging book."""
import pytest
from sqlalchemy import text
from app import landing, migrate
from app.pipelines import crm_lead, ingress, rules


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def lead(conn, volt, status, crm_id, source="ODOO", customer_no=None, ok=True):
    run = landing.start_run(conn, source)
    landing.write_customer(conn, run, source, {
        "volt_id": volt, "customer_no": customer_no or volt.split("_")[0],
        "name_th": volt, "source_refs": []})
    landing.write_order(conn, run, source, volt, {
        "crm_id": str(crm_id), "order_status": "Order - Done" if status == "Won" else status,
        "crm_status": status})
    landing.finish_run(conn, run, "OK" if ok else "FAILED")


def test_won_without_install_dates_is_accepted_in_won_only_mode(monkeypatch):
    monkeypatch.setenv("CRM_WON_ONLY", "1")
    rows = [{"id": 1, "volt_id": "VL0000143", "stage_name": "Won"},
            {"id": 2, "volt_id": "VL0000144", "stage_name": "Lost"}]
    records, verdicts = crm_lead.normalise(rows, rules.load())
    assert [r["order"]["crm_id"] for r in records] == [1]
    assert records[0]["order"]["crm_status"] == "Won"
    assert records[0]["order"]["epc_start_date"] is None
    assert verdicts[1]["rule"] == "not_won"


def test_source_domain_does_not_require_install_dates_in_won_only_mode(monkeypatch):
    monkeypatch.setenv("CRM_WON_ONLY", "1")
    assert ingress.eligibility_domain() == [("stage_name", "=", "Won")]


def test_book_excludes_non_won_sheet_rows_and_unknown_customers(schema, monkeypatch):
    lead(schema, "28000000001_Sheet", "Won", 28000000001, "SHEET")
    lead(schema, "28000000001_Odoo", "Won", 101)
    lead(schema, "28000000002_Sheet", "Won", 28000000002, "SHEET")
    lead(schema, "28000000002_Odoo", "Lost", 102)
    lead(schema, "28000000003_Sheet", "Won", 28000000003, "SHEET")
    lead(schema, "VL0000143", "Won", 103)
    monkeypatch.setenv("CRM_WON_ONLY", "1")
    rows = landing.resolved_customers(schema, shaped_only=True)
    assert {r["volt_id"] for r in rows} == {"28000000001_Sheet", "28000000001_Odoo", "VL0000143"}
    assert landing.count_customers(schema, shaped_only=True) == 3
    assert landing.count_customers(schema) == 6, "source history stays available"


def test_failed_and_retired_won_snapshots_do_not_qualify_sheet_customers(schema, monkeypatch):
    lead(schema, "VL0000143", "Won", 103, ok=False)
    lead(schema, "VL0000144", "Won", 104)
    schema.execute(text("update landing.customer set retired_at=now() where volt_id='VL0000144'"))
    lead(schema, "VL0000143_Sheet", "Won", 28000000001, "SHEET", "VL0000143")
    lead(schema, "VL0000144_Sheet", "Won", 28000000002, "SHEET", "VL0000144")
    monkeypatch.setenv("CRM_WON_ONLY", "1")
    assert landing.resolved_customers(schema, shaped_only=True) == []
    assert landing.count_customers(schema, shaped_only=True) == 0


def test_verified_link_to_non_won_lead_cannot_fall_back_to_another_won_lead(schema, monkeypatch):
    lead(schema, "VL0000143_Sheet", "Won", 28000000001, "SHEET", "VL0000143")
    lead(schema, "VL0000143_Won", "Won", 101)
    lead(schema, "VL0000143_Lost", "Lost", 102)
    schema.execute(text("""insert into records.identity_link
        (source, contact_code, customer_no, odoo_lead_id, rule, confirmed_by, reason)
        values ('ODOO_CRM_LEAD', 'VL0000143_Lost', 'VL0000143', 102,
                'ODOO_CRM_LEAD', 'system:odoo-sync', 'test verified identity')"""))
    monkeypatch.setenv("CRM_WON_ONLY", "1")
    assert {r["volt_id"] for r in landing.resolved_customers(schema, shaped_only=True)} == {"VL0000143_Won"}


def test_a_complete_refresh_removes_a_former_won_customer_from_book(schema, monkeypatch):
    lead(schema, "VL0000143", "Won", 101)
    lead(schema, "VL0000143_Sheet", "Won", 28000000001, "SHEET", "VL0000143")
    monkeypatch.setenv("CRM_WON_ONLY", "1")
    assert landing.count_customers(schema, shaped_only=True) == 2
    lead(schema, "VL0000143", "Lost", 101)
    assert landing.resolved_customers(schema, shaped_only=True) == []
