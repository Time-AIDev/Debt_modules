"""The receipt after an Odoo import: a run id that resolves, a per-row
provenance, and a registry that can be filtered.

Definition of "went in" (plan 2026-09-11): the import_run closed OK, the rows
are addressable under its id, the precedence winner is named, and every
replacement is listed — an empty ledger reads as "no measurement", never as
"no harm".
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import landing, migrate
from app.main import app
from app.pipelines import writer

client = TestClient(app)


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def _record(volt_id, **over):
    base = {"volt_id": volt_id, "customer_no": volt_id, "name_roman": None,
            "name_th": "ทดสอบ", "epc": "IPW", "product": "LEASE",
            "sales_lead": None, "phone_masked": "09x-xxx-3597",
            "phone_e164": "0925423597", "email_masked": None, "source_refs": [],
            "reason": "no money row in Odoo"}
    base["order"] = {"crm_id": "1", "order_type": "Leasing",
                     "order_status": "Order - Done", "loan_status": None,
                     "submit_date": None, "source_ref": []}
    base.update({k: v for k, v in over.items() if k != "order"})
    if "order" in over:
        base["order"].update(over["order"])
    return base


def test_the_run_id_resolves_to_a_durable_receipt(schema):
    result = writer.write(schema, [_record("VL0000143")], [],
                          read=5, door="odoo")
    assert result["import_run_id"] == result["run_id"]
    assert result["read"] == 5
    assert result["door"] == "odoo"

    run = landing.get_run(schema, result["run_id"])
    assert run["status"] == "OK"
    assert run["row_counts"]["read"] == 5
    assert run["row_counts"]["landed"] == 1
    assert run["meta"]["door"] == "odoo"
    assert run["meta"]["reason"] == "no money row in Odoo"
    # datetimes leave as ISO strings, never driver objects
    assert isinstance(run["finished_at"], str)


def test_an_unknown_run_id_is_none_not_invented(schema):
    assert landing.get_run(schema, 999999) is None


def test_provenance_names_the_winner_and_the_ledger_entry(schema):
    sheet_run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, sheet_run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143",
        "name_th": "ชื่อจากชีต", "epc": "SLT", "product": "LEASE",
        "source_refs": []})
    landing.finish_run(schema, sheet_run, "OK")

    writer.write(schema, [_record("VL0000143")], [], read=1, door="odoo")

    found = landing.rows_for_volt(schema, "VL0000143")
    # Arina, 2026-09-24: the sheet is the book, so its row wins for the same volt_id.
    assert found["winner"] == "SHEET"
    assert {c["data_source"] for c in found["customers"]} == {"SHEET", "ODOO"}
    assert {"volt_id": "VL0000143", "field": "epc",
            "sheet": "SLT", "odoo": "IPW"} in found["ledger"]


def test_provenance_is_empty_for_an_id_nobody_landed(schema):
    found = landing.rows_for_volt(schema, "VL-NOPE")
    assert found["customers"] == [] and found["orders"] == []
    assert found["winner"] is None


def test_the_registry_lists_by_source_and_searches(schema):
    sheet_run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, sheet_run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143",
        "name_th": "ชื่อจากชีต", "product": "LEASE", "source_refs": []})
    landing.finish_run(schema, sheet_run, "OK")
    writer.write(schema, [_record("VL0000144")], [], read=1, door="odoo")

    odoo_only = landing.list_landing_customers(schema, data_source="ODOO")
    assert {r["volt_id"] for r in odoo_only["rows"]} == {"VL0000144"}
    assert odoo_only["total"] == 1

    both = landing.list_landing_customers(schema, q="VL000014")
    assert both["total"] == 2

    page = landing.list_landing_customers(schema, limit=1, offset=1)
    assert page["total"] == 2 and len(page["rows"]) == 1


def test_unmapped_travels_per_volt_without_breaking_the_tally(schema):
    verdicts = [{"volt_id": "VL0000143", "verdict": "landed", "rule": None,
                 "unmapped": [["stage_name", "qualified_lead"]]}]
    result = writer.write(schema, [_record("VL0000143")], verdicts, read=1)
    meta = schema.execute(text("select meta from landing.import_run where id=:i"),
                          {"i": result["run_id"]}).scalar()
    # The whole list left meta on 2026-09-20 (700k entries decoded to ~400 MB at the
    # 350k bench); the sample and the true total stay for the receipt.
    assert meta["unmapped_sample"] == [["stage_name", "qualified_lead"]]
    assert meta["unmapped_total"] == 1
    rows = schema.execute(text(
        "select volt_id, field, value from landing.import_unmapped "
        "where import_run_id=:i"), {"i": result["run_id"]}).mappings().all()
    assert [dict(r) for r in rows] == [
        {"volt_id": "VL0000143", "field": "stage_name", "value": "qualified_lead"}]
    # The per-volt view still finds it, now by query instead of by meta scan.
    detail = landing.rows_for_volt(schema, "VL0000143")
    assert {"volt_id": "VL0000143", "field": "stage_name",
            "value": "qualified_lead"} in detail["unmapped"]


def test_last_run_carries_both_the_durable_receipt_and_the_watch(schema, monkeypatch, pg_url):
    from app import db
    from app.pipelines import runs
    runs.reset()
    runs.start("peak-report")               # the registry is shared; this is not a crm.lead run
    sheet_run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, sheet_run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143", "name_th": "ชื่อจากชีต",
        "epc": "SLT", "product": "LEASE", "source_refs": []})
    landing.finish_run(schema, sheet_run, "OK")
    rejected = [{"volt_id": "", "verdict": "rejected", "rule": "no_identity", "unmapped": []}]
    writer.write(schema, [_record("VL0000143"), _record("VL0000144")], rejected,
                 read=3, door="odoo", mode="NEW_ONLY")
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        r = client.get("/v1/pipelines/crm-lead/last-run")
    finally:
        db.reset()
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["source_system"] == "ODOO"
    assert body["receipt"]["landed"] == 1
    assert body["receipt"]["reason"] == "no money row in Odoo"
    # 2026-09-25: the slim row used to strip both, so every last-run said {} and 0.
    assert body["receipt"]["rejected_by_rule"] == {"no_identity": 1}
    assert body["receipt"]["proposals_total"] == 1
    assert (body["receipt"]["new"], body["receipt"]["skipped"], body["receipt"]["unchanged"]) == (1, 1, 0)
    assert body["watch"] is None, "a PEAK run in the shared registry is not the crm.lead watch"
    assert body["failed"] is None


def test_the_run_history_serves_every_status_and_a_failure_until_a_pull_succeeds(schema, monkeypatch, pg_url):
    from app import db
    ok = writer.write(schema, [_record("VL0000143")], [], read=1, door="odoo", mode="NEW_ONLY")
    failed = landing.start_run(schema, "ODOO", meta={"door": "odoo", "mode": "NEW_ONLY"})
    landing.finish_run(schema, failed, "FAILED", note="odoo_unreachable: ConnectError")
    running = landing.start_run(schema, "ODOO", meta={"door": "odoo", "mode": "NEW_ONLY"})
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        overview = client.get("/v1/data-sources/overview").json()
        last = client.get("/v1/pipelines/crm-lead/last-run").json()
        writer.write(schema, [_record("VL0000143")], [], read=1, door="odoo", mode="NEW_ONLY")
        schema.commit()
        recovered = client.get("/v1/pipelines/crm-lead/last-run").json()
    finally:
        db.reset()
    runs = overview["crm"]["runs"]
    assert [(r["id"], r["status"]) for r in runs] == [(running, "RUNNING"), (failed, "FAILED"), (ok["run_id"], "OK")]
    assert runs[2]["meta"]["new"] == 1 and "proposals" not in runs[2]["meta"]
    assert last["failed"]["id"] == failed and last["failed"]["note"] == "odoo_unreachable: ConnectError"
    assert recovered["failed"] is None, "a failure a later pull recovered from is history"


def test_landing_run_detail_paginates_the_ledger(schema, monkeypatch, pg_url):
    from app import db
    sheet_run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, sheet_run, "SHEET", {
        "volt_id": "VL0000143", "customer_no": "VL0000143",
        "name_th": "ชื่อจากชีต", "epc": "SLT", "product": "LEASE",
        "source_refs": []})
    landing.finish_run(schema, sheet_run, "OK")
    result = writer.write(schema, [_record("VL0000143")], [], read=1, door="odoo")
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        r = client.get("/v1/pipelines/crm-lead/landing-runs/%d" % result["run_id"])
    finally:
        db.reset()
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["id"] == result["run_id"]
    assert body["run"]["ledger_total"] >= 1
    assert body["run"]["receipt"]["overwrote"] >= 1
    assert {"volt_id": "VL0000143", "field": "epc",
            "sheet": "SLT", "odoo": "IPW"} in (
        body["run"]["meta"]["overwrite_ledger"])


def test_provenance_endpoint_is_readable_by_an_officer(schema, monkeypatch, pg_url):
    from app import db
    writer.write(schema, [_record("VL0000143")], [], read=1, door="odoo")
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        r = client.get("/v1/pipelines/crm-lead/provenance",
                       params={"volt_id": "VL0000143"},
                       headers={"X-Volt-Role": "OFFICER"})
        missing = client.get("/v1/pipelines/crm-lead/provenance",
                             params={"volt_id": "VL-NOPE"})
    finally:
        db.reset()
    assert r.status_code == 200
    assert r.json()["winner"] == "ODOO"
    assert missing.status_code == 404
    # 2026-09-25: an officer's provenance read serves the mask, never the number
    # (the audited phone:reveal route answers that), and the run's meta slim — the
    # full meta names every other lead the run touched.
    body = r.json()
    assert body["customers"] and all("phone_e164" not in row for row in body["customers"] + body["orders"])
    assert body["customers"][0]["phone_masked"] == "09x-xxx-3597"
    assert all("overwrite_ledger" not in run["meta"] and "proposals" not in run["meta"]
               for run in body["runs"])


def test_customers_endpoint_refuses_a_source_nobody_knows():
    r = client.get("/v1/pipelines/crm-lead/customers",
                   params={"data_source": "TELEPATHY"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/data_source"


# --- fix leg 2026-09-25: nothing a provenance read serves gives a number back -------

def test_the_pull_digest_is_never_served(schema, monkeypatch, pg_url):
    """The change detector is a sha256 of the whole normalised lead, the full phone
    number included. Served beside every other input (as extra.row_digest), it gave
    the number back to a 10^4 brute force; it lives in its own column now."""
    import json

    from app import book_source, db
    writer.write(schema, [_record("VL0000143")], [], read=1, door="odoo", mode="NEW_ONLY")
    # a row the earlier fix/o code landed kept its digest in extra, which the book serves
    legacy = landing.start_run(schema, "ODOO", meta={"door": "odoo"})
    landing.write_customer(schema, legacy, "ODOO", {"volt_id": "VL0000144", "product": "LEASE", "source_refs": []})
    landing.write_order(schema, legacy, "ODOO", "VL0000144", {"crm_id": "2", "legacy_digest": "x"})
    schema.execute(text("update landing.\"order\" set extra = extra || '{\"row_digest\": \"%s\"}'::jsonb "
                        "where volt_id = 'VL0000144'" % ("ab" * 32)))
    landing.finish_run(schema, legacy, "OK")
    migrate.apply(schema)                              # the deploy's migrate drops it from extra
    schema.commit()
    assert schema.execute(text("select count(*) from landing.\"order\" where extra ? 'row_digest'")).scalar() == 0
    digest, in_extra = schema.execute(text(
        "select row_digest, extra ? 'row_digest' from landing.\"order\" where volt_id = 'VL0000143'")).one()
    assert len(digest) == 64 and in_extra is False
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        prov = client.get("/v1/pipelines/crm-lead/provenance", params={"volt_id": "VL0000143"},
                          headers={"X-Volt-Role": "OFFICER"})
        served = json.dumps(book_source.load(), default=str)
        old_prov = client.get("/v1/pipelines/crm-lead/provenance", params={"volt_id": "VL0000144"})
    finally:
        db.reset()
    assert prov.status_code == 200 and old_prov.status_code == 200
    assert "row_digest" not in old_prov.text and "ab" * 32 not in old_prov.text
    for body in (prov.text, served):
        assert digest not in body and "row_digest" not in body
    assert "VL0000143" in served, "the lead is in the served book, without its digest"


def test_a_retired_placeholder_key_answers_nobody_and_run_details_are_slim(schema, monkeypatch, pg_url):
    import json

    from app import db
    old = landing.start_run(schema, "ODOO", meta={"door": "odoo"})
    landing.write_customer(schema, old, "ODOO", {"volt_id": "phone-800000001", "name_th": "ทดสอบ",
                                                 "product": "LEASE", "source_refs": []})
    landing.finish_run(schema, old, "OK")
    # a run landed before 2026-09-25 kept keyed lists on its meta
    schema.execute(text("update landing.import_run set meta = meta || cast(:m as jsonb) where id = :i"),
                   {"i": old, "m": json.dumps({"proposals": [{"kind": "SHARED_PHONE", "odoo_volt_id": "phone-800000001"}],
                                               "unmapped_by_volt": [{"volt_id": "phone-800000001"}]})})
    result = writer.write(schema, [_record("VL0000143")], [], read=1, door="odoo", mode="NEW_ONLY", retire=True)
    assert result["retired"] == 1                      # the complete pull retired the legacy key
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        gone = client.get("/v1/pipelines/crm-lead/provenance", params={"volt_id": "phone-800000001"})
        live = client.get("/v1/pipelines/crm-lead/provenance", params={"volt_id": "VL0000143"})
        detail = client.get("/v1/pipelines/crm-lead/landing-runs/%d" % old)
    finally:
        db.reset()
    assert gone.status_code == 404 and live.status_code == 200
    assert detail.status_code == 200 and "phone-800000001" not in detail.text
    assert detail.json()["run"]["meta"]["proposals_total"] == 1
    assert detail.json()["run"]["receipt"]["proposals_total"] == 1


def test_a_lock_refused_run_stays_in_the_history_but_is_not_the_latest_failure(schema, monkeypatch, pg_url):
    from app import db
    ok = writer.write(schema, [_record("VL0000143")], [], read=1, door="odoo", mode="NEW_ONLY")
    refused = landing.start_run(schema, "ODOO", meta={"door": "odoo", "mode": "NEW_ONLY"})
    landing.finish_run(schema, refused, "FAILED", note="crm_lead_run_in_progress: PipelineRefused")
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        last = client.get("/v1/pipelines/crm-lead/last-run").json()
        history = client.get("/v1/data-sources/overview").json()["crm"]["runs"]
    finally:
        db.reset()
    assert last["run"]["id"] == ok["run_id"] and last["failed"] is None
    assert [(r["id"], r["status"]) for r in history] == [(refused, "FAILED"), (ok["run_id"], "OK")]
