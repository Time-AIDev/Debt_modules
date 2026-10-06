import json

import pytest
from sqlalchemy import create_engine, text

from app import db, debt_imports, errors, migrate
from tests.test_debt_import_profiles import customer, lease, workbook


@pytest.fixture
def durable(pg_conn, pg_url, monkeypatch):
    migrate.apply(pg_conn)
    for statement in debt_imports.SCHEMA.split(";"):
        if statement.strip():
            pg_conn.execute(text(statement))
    pg_conn.commit()
    engine = create_engine(pg_url, future=True, hide_parameters=True, pool_size=2, max_overflow=0)
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(db, "_engine", engine)
    debt_imports.reset()
    yield pg_conn
    if pg_conn.in_transaction():
        pg_conn.rollback()
    for table in ("debt_import_preview", "contract_supplement", "debt_status_observation", "installation_confirmation"):
        pg_conn.execute(text("delete from records." + table))
    pg_conn.commit()
    engine.dispose()
    debt_imports.reset()


def stage(profile="debt_status"):
    return debt_imports.stage(workbook(lease=[lease()]), "synthetic.xlsx", profile, "Manager", [customer()])


def command(preview):
    return {"preview_version": preview["version"], "idempotency_key": "durable-command",
            "selected_keys": [preview["entries"][0]["key"]]}


def test_preview_and_applied_evidence_survive_memory_reset_and_new_connections(durable):
    preview = stage()
    debt_imports.reset()
    assert debt_imports.get_preview(preview["uid"], "Manager")["state"] == "STAGED"
    first = debt_imports.apply(preview["uid"], command(preview), "Manager", "MANAGER")
    debt_imports.reset()
    assert debt_imports.apply(preview["uid"], command(preview), "Manager", "MANAGER") == first
    assert len(debt_imports.observations(customer().uid)) == 1
    assert durable.execute(text("select count(*) from landing.customer")).scalar() == 0


def test_supplement_is_additive_and_does_not_install_or_retire_the_sheet_book(durable):
    preview = stage("contract_supplement")
    debt_imports.apply(preview["uid"], command(preview), "Manager", "MANAGER")
    stored = next(iter(debt_imports.supplements().values()))
    assert stored["record"]["financial_evidence_only"]
    assert durable.execute(text("select count(*) from landing.import_run")).scalar() == 0
    assert durable.execute(text("select count(*) from landing.customer")).scalar() == 0


def test_postgres_failure_rolls_back_every_selected_observation(durable, monkeypatch):
    preview = stage()
    def fail(*_args):
        raise RuntimeError("synthetic injected failure")
    monkeypatch.setattr(debt_imports, "_confirm_terminations", fail)
    with pytest.raises(RuntimeError):
        debt_imports.apply(preview["uid"], command(preview), "Manager", "MANAGER")
    assert debt_imports.observations(customer().uid) == []
    assert debt_imports.get_preview(preview["uid"], "Manager")["state"] == "STAGED"


def test_changed_source_epoch_invalidates_the_reviewed_preview(durable):
    preview = stage()
    durable.execute(text("insert into app.data_epoch(kind) values('SYNTHETIC_NEW_SOURCE')"))
    durable.commit()
    from app import data_epoch
    data_epoch.reset_cache()
    with pytest.raises(errors.Problem) as failure:
        debt_imports.apply(preview["uid"], command(preview), "Manager", "MANAGER")
    assert failure.value.code == "debt_import_preview_stale"


def test_payment_components_survive_invoice_writer_and_book_read(durable):
    from app.pipelines import peak_report, peak_writer
    from tests.test_peak_report import _line, _report
    parsed = peak_report.parse(_report([
        _line(**{"เลขที่ใบเสร็จ": "RE-ONE", "วันที่": "01/09/2026", "จำนวนเงิน": "1000"}),
        _line(**{"เลขที่ใบเสร็จ": "RE-TWO", "วันที่": "02/09/2026", "จำนวนเงิน": "2000"}),
    ]), "invoice_company_export_as_of_20240101_20260914_20260914_155330.xlsx")
    exact = {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": "99999000328", "candidates": []}
    written = peak_writer.write(durable, parsed, [exact])
    peak_writer.apply_run(durable, written["run_id"], "Manager")
    served = peak_writer.invoices_for_book(durable)["99999000328"]["invoices"][0]
    assert [payment["amount"] for payment in served["payments"]] == ["1000.00", "2000.00"]
    meta = durable.execute(text("select meta from landing.import_run where id=:r"),
                           {"r": written["run_id"]}).scalar()
    assert len(meta["source_rows"][parsed["invoices"][0]["doc_no"]]) == 2
    # Header-only schema diagnostics are allowed; the tax identifier value is not.
    assert "1234567890121" not in json.dumps(meta)


def test_database_preview_reads_canonical_identity_without_a_business_store(durable, monkeypatch):
    from app import landing, session
    from tests.test_debt_import_profiles import VID
    source = landing.start_run(durable, "ODOO")
    landing.write_customer(durable, source, "ODOO", {
        "volt_id": VID, "customer_no": customer().customer_no, "product": "LEASE"})
    landing.write_order(durable, source, "ODOO", VID, {
        "order_type": "Leasing", "crm_status": "Won", "order_status": "Order - Done"})
    landing.finish_run(durable, source, "OK")
    durable.commit()
    def forbidden_store(_self):
        raise AssertionError("A metadata preview must not read a mutable business Store")
    monkeypatch.setattr(session.Store, "for_current", forbidden_store)
    preview = debt_imports.stage(workbook(lease=[lease()]), "synthetic.xlsx", "debt_status", "Manager")
    assert preview["counts"]["matched"] == 1
    assert preview["entries"][0]["customer_uid"] == customer().uid
