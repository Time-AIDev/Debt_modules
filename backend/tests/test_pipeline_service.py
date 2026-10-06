"""The button and the timer call the same function."""
import pytest
from sqlalchemy import create_engine, text

from app import migrate
from app.pipelines import runs, service


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


@pytest.fixture
def live_db(schema, monkeypatch, pg_url):
    """The service on its own connections to the test database, as in production:
    the durable run row is committed on one, the landing on another."""
    from app import db
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    yield schema
    db.reset()


def setup_function():
    runs.reset()


# Invented leads — none of these is a real customer.
LEADS = [{"id": 101, "volt_id": "VL0000101", "phone": "0811111101", "stage_name": "Won"},
         {"id": 102, "volt_id": "VL0000102", "phone": "0811111102", "stage_name": "Won"},
         {"id": 103, "volt_id": "New", "phone": "0811111103", "stage_name": "Won"}]


def _pull(monkeypatch, rows):
    monkeypatch.setattr(service.ingress, "from_odoo",
                        lambda rules, on_progress=None, on_exclusions=None: [
                            {"epc_start_date": "2026-01-01", "epc_end_date": "2026-01-02", **r}
                            for r in rows])


def _runs(conn):
    return conn.execute(text("select status, note, meta from landing.import_run "
                             "where source_system = 'ODOO' order by id")).mappings().all()


def test_an_identical_second_pull_lands_nothing_and_moves_no_epoch(live_db, monkeypatch):
    from app import data_epoch
    _pull(monkeypatch, LEADS)
    first = service.run_odoo()
    assert first["state"] == "done", first
    assert (first["landed"], first["new"], first["new_data"]) == (3, 3, True)
    epoch = data_epoch.current()

    second = service.run_odoo()
    assert second["state"] == "done", second
    assert (second["landed"], second["new"], second["changed"], second["unchanged"]) == (0, 0, 0, 3)
    assert second["new_data"] is False and second["retired"] == 0
    data_epoch.reset_cache()
    assert data_epoch.current() == epoch, "a pull that changed nothing must not heal every session"
    # no row moved to the second run
    owners = live_db.execute(text("select distinct import_run_id from landing.customer")).scalars().all()
    assert owners == [first["run_id"]]
    # both runs are durable and OK, each with its door and mode
    assert [(r["status"], r["meta"]["door"], r["meta"]["mode"]) for r in _runs(live_db)] == \
        [("OK", "odoo", "NEW_ONLY"), ("OK", "odoo", "NEW_ONLY")]


def test_normal_odoo_sync_refreshes_source_fields_behind_a_served_sheet_customer(live_db, monkeypatch):
    from app import landing

    sheet_run = landing.start_run(live_db, "SHEET")
    landing.write_customer(live_db, sheet_run, "SHEET", {
        "volt_id": "VL0000101", "customer_no": "VL0000101",
        "name_th": "ชื่อที่ผู้ใช้ดูแล", "product": "LEASE", "source_refs": [],
    })
    landing.finish_run(live_db, sheet_run, "OK")
    live_db.commit()
    _pull(monkeypatch, [{**LEADS[0], "line_id": "line-101", "meta_id": "meta-101"}])

    result = service.run_odoo()

    assert result["state"] == "done", result
    source = live_db.execute(text(
        "select line_id, meta_id, retired_at from landing.customer "
        "where volt_id='VL0000101' and data_source='ODOO'"
    )).mappings().one()
    assert dict(source) == {"line_id": "line-101", "meta_id": "meta-101", "retired_at": None}
    served = live_db.execute(text(
        "select name_th from landing.customer "
        "where volt_id='VL0000101' and data_source='SHEET'"
    )).scalar_one()
    assert served == "ชื่อที่ผู้ใช้ดูแล"


def test_a_refusal_from_odoo_leaves_a_durable_failed_run(live_db, monkeypatch):
    from app.integrations import odoo as odoo_client

    def refuse(rules, on_progress=None, on_exclusions=None):
        raise odoo_client.OdooError("Odoo refused the login")
    monkeypatch.setattr(service.ingress, "from_odoo", refuse)
    view = service.run_odoo()
    assert view["state"] == "failed"
    [row] = _runs(live_db)
    assert row["status"] == "FAILED"
    # the code and the class, never the exception's own text
    assert row["note"] == "odoo_refused: OdooError"
    assert row["meta"] == {"door": "odoo", "mode": "NEW_ONLY"}


def test_missing_odoo_configuration_is_a_permanent_actionable_failure():
    from app.integrations import odoo
    problem, code = service._failure(odoo.NotConfigured())
    assert code == "integration_not_configured"
    assert problem["status"] == 422 and problem["retryable"] is False
    assert problem["missing"] and problem["message_th"]


def test_an_unexpected_failure_is_named_by_class_only(live_db, monkeypatch):
    def boom(rules, on_progress=None, on_exclusions=None):
        raise RuntimeError("DETAIL: Failing row contains (a customer's name)")
    monkeypatch.setattr(service.ingress, "from_odoo", boom)
    view = service.run_odoo()
    assert view["problem"] == {"code": "pipeline_failed", "detail": "RuntimeError"}
    assert _runs(live_db)[0]["note"] == "pipeline_failed: RuntimeError"


def test_a_second_landing_is_refused_while_one_holds_the_lock(live_db, monkeypatch, pg_url):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.pipelines import rules as rules_mod

    engine = create_engine(pg_url, future=True)
    holder = engine.connect()
    try:
        holder.execute(text("select pg_advisory_lock(:k)"), {"k": service.CRM_LEAD_LOCK_KEY})
        with pytest.raises(service.PipelineRefused) as refused:
            service._land(None, [dict(r) for r in LEADS], rules_mod.load(), door="odoo")
        assert refused.value.problem["code"] == "crm_lead_run_in_progress"

        _pull(monkeypatch, LEADS)
        r = TestClient(app).post("/v1/pipelines/crm-lead:run", json={"source": "odoo"},
                                 headers={"X-Volt-Role": "MANAGER"})
        assert r.status_code == 409 and r.json()["code"] == "crm_lead_run_in_progress"
        assert _runs(live_db)[-1]["note"] == "crm_lead_run_in_progress: PipelineRefused"
    finally:
        holder.execute(text("select pg_advisory_unlock(:k)"), {"k": service.CRM_LEAD_LOCK_KEY})
        holder.close()
        engine.dispose()
    assert live_db.execute(text("select count(*) from landing.customer")).scalar() == 0


def test_a_pull_that_would_retire_too_much_fails_by_name_and_overwrite_may_go_ahead(live_db, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    ten = [{"id": 200 + i, "volt_id": "VL00002%02d" % i, "phone": "08111112%02d" % i, "stage_name": "Won"}
           for i in range(10)]
    _pull(monkeypatch, ten)
    assert service.run_odoo()["state"] == "done"
    _pull(monkeypatch, ten[:7])                         # three of ten gone: 30%
    view = service.run_odoo()
    assert view["state"] == "failed" and view["problem"]["code"] == "pull_would_retire_too_much"
    assert _runs(live_db)[-1]["note"] == "pull_would_retire_too_much: TooMuchToRetire"
    assert live_db.execute(text("select count(*) from landing.customer where retired_at is null")).scalar() == 10
    r = TestClient(app).post("/v1/pipelines/crm-lead:run", json={"source": "odoo"},
                             headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 409 and r.json()["code"] == "pull_would_retire_too_much"
    # a manager's OVERWRITE is not limited
    done = service.run_odoo(mode="OVERWRITE")
    assert done["state"] == "done" and done["retired"] == 3


def test_a_late_failure_never_flips_a_finished_run(live_db):
    from app import landing
    run_id = service._open_durable_run("NEW_ONLY")
    live_db.rollback()
    live_db.execute(text("update landing.import_run set status = 'OK', finished_at = now() where id = :i"),
                    {"i": run_id})
    live_db.commit()
    service._fail_durable(run_id, "pipeline_failed", RuntimeError("the client lost the commit"))
    assert landing.get_run(live_db, run_id)["status"] == "OK"
    service._fail_durable(service._open_durable_run("NEW_ONLY"), "pipeline_failed", RuntimeError())
    live_db.rollback()
    assert _runs(live_db)[-1]["note"] == "pipeline_failed: RuntimeError"


def test_a_refusal_from_odoo_fails_the_run_rather_than_finishing_it(monkeypatch):
    from app.integrations import odoo as odoo_client

    def refuse(rules, execute=None, on_progress=None, on_exclusions=None):
        raise odoo_client.OdooError("Odoo refused the login")

    monkeypatch.setattr(service.ingress, "from_odoo", refuse)
    view = service.run_odoo()
    assert view["state"] == "failed"
    assert "refused" in view["problem"]["detail"]


def test_a_run_with_no_database_fails_by_name_rather_than_pretending(monkeypatch):
    monkeypatch.setattr(service.db, "configured", lambda: False)
    _pull(monkeypatch, LEADS)
    view = service.run_odoo()
    assert view["state"] == "failed"
    assert view["problem"]["code"] == "database_required"


def test_the_run_view_carries_the_mode_it_ran_in(monkeypatch):
    monkeypatch.setattr(service, "_land", lambda uid, raw_rows, rules, door=None, mode=None, run_id=None,
                                                    exclusion_counts=None: {
        "run_id": 1, "landed": 0, "rejected": 0, "overwrote": 0, "read": 0, "door": door, "ledger": [],
        "mode": mode, "new": 0, "skipped": 0, "proposals": []})
    monkeypatch.setattr(service.rules_mod, "load", lambda: object())
    _pull(monkeypatch, [])
    run = service.run_odoo(mode="OVERWRITE")
    assert run["mode"] == "OVERWRITE"


# --- Delta-100 D2h — the three conditions and their evidence --------------------------

def _cond_item(**over):
    from app import invoice_pipeline as pipeline
    item = {
        "uid": "pip-unit-1",
        "condition_evidence": {key: [] for key in pipeline.CONDITION_KEYS},
        "gate_down_payment": {"state": "OPEN", "ref": None, "on": None, "by": None},
        "gate_epc_confirmed": {"state": "OPEN", "ref": None, "on": None, "by": None, "source": None},
        "entity": "SPV", "company_id": "CO-SPV", "history": [],
    }
    item.update(over)
    return item


def test_the_condition_state_reads_its_own_data_path():
    from app import invoice_pipeline as pipeline
    item = _cond_item()
    assert [c["key"] for c in pipeline.conditions_for(item)] == \
        ["contract_signed", "down_payment", "entity_resolved"]
    # down_payment is the existing gate dict; entity_resolved is the resolved pair.
    assert pipeline.condition_state(item, "down_payment") == "OPEN"
    assert pipeline.condition_state(item, "entity_resolved") == "PASSED"
    item["gate_down_payment"] = {"state": "PASSED", "ref": "slip-1", "on": "2026-09-18", "by": "thip"}
    assert pipeline.condition_state(item, "down_payment") == "PASSED"
    item["entity"], item["company_id"] = None, None
    assert pipeline.condition_state(item, "entity_resolved") == "OPEN"
    with pytest.raises(pipeline.PipelineError):
        pipeline.condition_state(item, "not_a_condition")


def test_contract_signed_passes_by_evidence_only_and_reopens_when_emptied():
    from app import invoice_pipeline as pipeline
    state = pipeline.PipelineState()
    item = _cond_item()
    assert pipeline.open_conditions(item) == ["contract_signed", "down_payment"]
    assert pipeline.condition_state(item, "contract_signed") == "OPEN"

    one = pipeline.attach_evidence(state, item, "contract_signed", "สำเนาสัญญา", by="thip")
    assert one["condition"] == "contract_signed" and one["file_uid"] is None
    assert one["scope"] == "pipeline:pip-unit-1:condition:contract_signed"
    assert one["uploaded_by"] == "thip" and one["uploaded_at"]
    assert pipeline.condition_state(item, "contract_signed") == "PASSED"

    two = pipeline.attach_evidence(state, item, "contract_signed", None, file_uid="att-1", by="thip")
    assert two["file_uid"] == "att-1"
    pipeline.remove_evidence(state, item, "contract_signed", one["uid"])
    assert pipeline.condition_state(item, "contract_signed") == "PASSED", "one of two left"
    pipeline.remove_evidence(state, item, "contract_signed", two["uid"])
    assert pipeline.condition_state(item, "contract_signed") == "OPEN", "the last removal reopens"
    assert [h["act"] for h in item["history"]].count("CONDITION_EVIDENCE_ATTACHED") == 2
    assert [h["act"] for h in item["history"]].count("CONDITION_EVIDENCE_REMOVED") == 2


def test_attaching_evidence_needs_a_note_or_a_file_and_an_unknown_uid_is_named():
    from app import invoice_pipeline as pipeline
    state = pipeline.PipelineState()
    item = _cond_item()
    with pytest.raises(pipeline.PipelineError) as err:
        pipeline.attach_evidence(state, item, "contract_signed", "  ", by="thip")
    assert err.value.code == "gate_evidence_required"
    with pytest.raises(pipeline.PipelineError) as err:
        pipeline.attach_evidence(state, item, "not_a_condition", "x", by="thip")
    assert err.value.code == "gate_key_unknown"
    with pytest.raises(pipeline.PipelineError) as err:
        pipeline.remove_evidence(state, item, "contract_signed", "pev-nope", by="thip")
    assert err.value.code == "evidence_not_found"
    assert item["condition_evidence"]["contract_signed"] == []


def test_down_payment_evidence_passes_the_gate_and_removal_reopens_only_an_evidence_gate():
    from app import invoice_pipeline as pipeline
    state = pipeline.PipelineState()
    item = _cond_item()
    # A transfer slip IS the receipt the gate asks for: the condition passes AND the
    # gate dict moves with it, so SOP and every non-condition reader agree (2026-09-20).
    ev = pipeline.attach_evidence(state, item, "down_payment", "สลิปโอนเงิน", by="thip", amount="4500.00")
    assert pipeline.condition_state(item, "down_payment") == "PASSED"
    assert item["gate_down_payment"]["state"] == "PASSED"
    assert item["gate_down_payment"]["ref"] == "EVIDENCE:%s" % ev["uid"]
    assert item["gate_down_payment"]["source"] == "EVIDENCE"
    assert item["amount_due"] == "4500.00"
    pipeline.remove_evidence(state, item, "down_payment", ev["uid"])
    assert pipeline.condition_state(item, "down_payment") == "OPEN"
    assert item["gate_down_payment"]["state"] == "OPEN", "the gate the evidence passed reopens"
    assert "GATE_REOPENED" in [h["act"] for h in item["history"]]
    # Once a PERSON passed the gate, removing evidence does NOT reopen it.
    item["gate_down_payment"] = {"state": "PASSED", "ref": "slip-9", "on": "2026-09-18", "by": "thip"}
    ev = pipeline.attach_evidence(state, item, "down_payment", "สลิปโอนเงิน", by="thip")
    pipeline.remove_evidence(state, item, "down_payment", ev["uid"])
    assert pipeline.condition_state(item, "down_payment") == "PASSED"
    assert item["gate_down_payment"]["ref"] == "slip-9"


def test_epc_is_not_a_condition_and_evidence_never_resolves_an_entity():
    from app import invoice_pipeline as pipeline
    state = pipeline.PipelineState()
    item = _cond_item(entity=None, company_id=None)
    assert "gate_epc_confirmed" not in pipeline.open_conditions(item)
    ev = pipeline.attach_evidence(state, item, "entity_resolved", "เอกสารบริษัท", by="thip")
    assert ev["condition"] == "entity_resolved"
    # A file cannot resolve a company: the condition still reads the entity pair.
    assert pipeline.condition_state(item, "entity_resolved") == "OPEN"
    item["entity"], item["company_id"] = "SPV", "CO-SPV"
    assert pipeline.condition_state(item, "entity_resolved") == "PASSED"
