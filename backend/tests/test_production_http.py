import json
import pytest
from fastapi.testclient import TestClient
from app import auth, db, main, migrate, tab_sessions


@pytest.fixture
def production(monkeypatch, pg_url, pg_conn, tmp_path):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ENV", "prd")
    monkeypatch.setenv("PROD_GO_LIVE_ENABLED", "false")
    auth.set_config(auth.load_config({"AUTH_MODE": "on", "AUTH_SESSION_SECRET": "s" * 40,
                                     "AUTH_SESSION_POLICY": "tab", "GOOGLE_CLIENT_ID": "client",
                                     "AUTH_ALLOWLIST": json.dumps({
                                         "owner@volt.co.th": {"role": "OWNER", "officer": "owner"},
                                         "thip@volt.co.th": {"role": "OFFICER", "officer": "thip"}})}, env_file=tmp_path / "none"))
    def headers(email, role, officer):
        session = auth.new_session(email, "GOOGLE", role, officer, False)
        return {"Authorization": "Bearer " + tab_sessions.issue(dict(session, session_policy="tab"))}
    yield TestClient(main.app, raise_server_exceptions=False), headers
    auth.reset()
    db.reset()


def test_production_empty_database_never_seeds_demo_customers(production):
    api, headers = production
    response = api.get("/api/v1/workbook", headers=headers("owner@volt.co.th", "OWNER", "owner"))
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == []


def test_authentication_and_business_reads_share_one_leased_connection(production, pg_url, monkeypatch):
    from sqlalchemy import create_engine
    api, headers = production
    db.reset()
    engine = create_engine(pg_url, pool_size=1, max_overflow=0, pool_timeout=0.1,
                           future=True, hide_parameters=True)
    monkeypatch.setattr(db, '_engine', engine)
    try:
        actor = headers('owner@volt.co.th', 'OWNER', 'owner')
        for path in ('/api/v1/auth/me', '/api/v1/workbook'):
            response = api.get(path, headers=actor)
            assert response.status_code == 200, response.text
    finally:
        db.reset()


def test_odoo_missing_config_refuses_before_creating_a_job(production):
    from sqlalchemy import text
    api, headers = production
    response = api.post("/api/v1/pipelines/crm-lead:start", json={"source": "odoo"},
                        headers=headers("owner@volt.co.th", "OWNER", "owner"))
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "integration_not_configured"
    assert set(response.json()["extensions"]["missing_env"]) == {
        "ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY"}
    with db.connect() as conn:
        assert conn.execute(text("select count(*) from app.task_outbox")).scalar_one() == 0
        assert conn.execute(text("select count(*) from app.operation_run")).scalar_one() == 0


def test_candidate_does_not_allow_officers_into_business_routes(production):
    api, headers = production
    assert api.get("/api/v1/workbook", headers=headers("thip@volt.co.th", "OFFICER", "thip")).status_code == 503


def test_production_openapi_requires_ops_or_owner(production):
    api, headers = production
    response = api.get("/api/openapi.json", headers=headers("owner@volt.co.th", "OWNER", "owner"))
    assert response.status_code == 200
    assert "/v1/workbook" in response.json()["paths"]
    assert api.get("/api/openapi.json").status_code == 401


def test_production_assignment_cannot_be_bypassed_by_headers_or_body(production, monkeypatch):
    from types import SimpleNamespace
    from app import cases, production_runtime
    api, headers = production
    monkeypatch.setenv("PROD_GO_LIVE_ENABLED", "true")
    monkeypatch.setattr(production_runtime, "prepare_book", lambda **_kwargs: None)
    monkeypatch.setattr(cases, "for_current", lambda: SimpleNamespace(cases={
        "other-case": {"uid": "case-other", "customer_uid": "other-case", "officer_uid": "nantapol"},
        "own-case": {"uid": "case-own", "customer_uid": "own-case", "officer_uid": "thip"}}))
    actor = headers("thip@volt.co.th", "OFFICER", "thip")
    actor.update({"X-Volt-Role": "OWNER", "X-Volt-Officer": "nantapol"})
    response = api.post("/api/v1/cases/by-customer/other-case/notes", headers=actor,
                        json={"customer_uid": "own-case", "by": "nantapol", "role": "OWNER", "text": "unsafe"})
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "assignment_required"


def test_shared_saved_criteria_round_trip(production):
    api,headers=production
    actor=headers("owner@volt.co.th","OWNER","owner")
    response=api.put("/api/v1/criteria/default",json={"population":"all_orders","targets":{"at_risk_30":7}},headers=actor)
    assert response.status_code==200,response.text
    saved=api.get("/api/v1/criteria/default",headers=actor)
    assert saved.status_code==200,saved.text
    assert saved.json()["default"]["targets"]=={"at_risk_30":7}


def test_idempotency_distinguishes_upload_semantic_headers(production):
    api,headers=production
    actor=headers("owner@volt.co.th","OWNER","owner")
    actor.update({"Idempotency-Key":"semantic-upload-test","X-Volt-Upload":"first-upload"})
    first=api.put("/api/v1/criteria/default",json={"population":"all_orders"},headers=actor)
    assert first.status_code==200,first.text
    actor["X-Volt-Upload"]="second-upload"
    second=api.put("/api/v1/criteria/default",json={"population":"all_orders"},headers=actor)
    assert second.status_code==409,second.text
    assert second.json()["code"]=="idempotency_conflict"


def test_shared_existing_record_write_requires_version_when_policy_enabled(production,monkeypatch):
    api,headers=production
    monkeypatch.setenv("REQUIRE_STATE_VERSION","true")
    actor=headers("owner@volt.co.th","OWNER","owner")
    missing=api.put("/api/v1/criteria/default",json={"population":"all_orders"},headers=actor)
    assert missing.status_code==428,missing.text
    read=api.get("/api/v1/criteria/default",headers=actor)
    actor["If-Match"]=read.headers["x-volt-state-version"]
    saved=api.put("/api/v1/criteria/default",json={"population":"all_orders"},headers=actor)
    assert saved.status_code==200,saved.text
