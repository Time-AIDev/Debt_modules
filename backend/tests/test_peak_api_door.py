# backend/tests/test_peak_api_door.py
"""WP5 — the PEAK API door is a port with an honest state, never a client against a
guessed endpoint (vault note 10 §3 WP5, ruling F19)."""
import inspect

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations import peak as pinned_peak
from app.integrations import peak_reports
from app.main import app
from app.pipelines import peak_service, runs

client = TestClient(app)
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}
NAMES = ["PEAK_REPORT_API_BASE_URL", "PEAK_REPORT_API_TOKEN"]
TOKEN = "t0ken-never-printed"


@pytest.fixture
def unset(monkeypatch):
    monkeypatch.setattr(peak_reports, "env", lambda key, default=None: default)


@pytest.fixture
def configured(monkeypatch):
    values = {"PEAK_REPORT_API_BASE_URL": "https://peak.invalid", "PEAK_REPORT_API_TOKEN": TOKEN}
    monkeypatch.setattr(peak_reports, "env", lambda key, default=None: values.get(key, default))


@pytest.fixture
def no_network(monkeypatch):
    # The real network transport only: TestClient's own transport is not an HTTPTransport.
    def _refuse(*args, **kwargs):
        raise AssertionError("the PEAK report port must not call out before an endpoint is verified")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


def test_unconfigured_the_port_says_not_configured_and_names_only_the_variables(unset):
    assert peak_reports.state() == {"state": "not_configured", "env": NAMES, "missing_env": NAMES,
                                    "verified_endpoint": None, "webhook": "not_built"}
    with pytest.raises(peak_reports.NotConfigured) as err:
        peak_reports.list_invoices("2026-09-01", "EPC")
    assert err.value.missing == NAMES and err.value.code == "integration_not_configured"


def test_configured_but_unverified_the_port_says_untested_and_calls_nothing(configured, no_network):
    s = peak_reports.state()
    assert s["state"] == "untested" and s["missing_env"] == [] and s["verified_endpoint"] is None
    assert TOKEN not in repr(s)
    with pytest.raises(peak_reports.Untested) as err:
        peak_reports.list_invoices("2026-09-01", "SPV")
    assert err.value.code == "integration_untested" and TOKEN not in repr(err.value.problem())


def test_a_bad_argument_is_the_callers_mistake_whatever_the_state(unset):
    with pytest.raises(peak_reports.PeakReportApiError) as err:
        peak_reports.list_invoices("01/09/2026", "EPC")
    assert err.value.code == "since_invalid"
    with pytest.raises(peak_reports.PeakReportApiError) as err:
        peak_reports.list_invoices(None, "ACME")
    assert err.value.code == "instance_unknown"


def test_the_port_is_a_new_module_that_never_touches_the_pinned_one():
    source = inspect.getsource(peak_reports)
    assert "from .peak import" not in source and "import peak\n" not in source and "httpx" not in source
    assert "peak_reports" not in inspect.getsource(pinned_peak)
    forbidden = ("approve", "post_", "update", "delete", "void", "issue")
    for name, _fn in inspect.getmembers(peak_reports, inspect.isfunction):
        assert not any(bad in name.lower() for bad in forbidden), name


def test_run_api_refuses_before_any_run_starts(unset):
    runs.reset()
    with pytest.raises(peak_service.PipelineRefused) as err:
        peak_service.run_api(since="2026-09-01")
    assert err.value.problem["code"] == "integration_not_configured"
    assert err.value.problem["missing_env"] == NAMES
    assert runs.latest(kind=peak_service.KIND) is None


def test_run_api_refuses_as_untested_once_configured(configured, no_network):
    with pytest.raises(peak_service.PipelineRefused) as err:
        peak_service.run_api()
    assert err.value.problem["code"] == "integration_untested"


def test_if_the_port_ever_answers_the_service_still_refuses_until_an_adapter_is_written(monkeypatch):
    monkeypatch.setattr(peak_reports, "list_invoices", lambda since, instance: [{"doc_no": "IVT-1"}])
    with pytest.raises(peak_service.PipelineRefused) as err:
        peak_service.run_api()
    assert err.value.problem["code"] == "adapter_missing"


def test_the_doors_route_serves_both_doors_by_code(unset):
    body = client.get("/v1/pipelines/peak-report/doors").json()
    doors = {d["door"]: d for d in body["doors"]}
    assert doors["upload"]["state"] == "ready"
    assert doors["api"]["state"] == "not_configured" and doors["api"]["missing_env"] == NAMES
    assert doors["api"]["webhook"] == "not_built"


def test_the_api_door_is_manager_only(unset):
    assert client.post("/v1/pipelines/peak-report:run", json={"source": "api"}, headers=OFFICER).status_code == 403
    assert client.post("/v1/pipelines/peak-report:start", json={"source": "api"}, headers=OFFICER).status_code == 403


def test_the_api_door_refuses_with_a_problem_and_starts_nothing_when_unconfigured(unset):
    runs.reset()
    for verb in (":run", ":start"):
        r = client.post("/v1/pipelines/peak-report" + verb, json={"source": "api", "since": "2026-09-01"},
                        headers=MANAGER)
        assert r.status_code == 422, r.json()
        body = r.json()
        assert body["code"] == "integration_not_configured" and body["message_th"]
        assert body["extensions"]["missing_env"] == NAMES
    assert runs.latest(kind=peak_service.KIND) is None


def test_the_api_door_answers_501_untested_once_configured_and_never_echoes_the_token(configured, no_network):
    r = client.post("/v1/pipelines/peak-report:run", json={"source": "api"}, headers=MANAGER)
    assert r.status_code == 501 and r.json()["code"] == "integration_untested"
    assert r.json()["extensions"]["state"] == "untested" and TOKEN not in r.text


def test_a_json_body_that_is_not_the_api_door_is_a_validation_problem(unset):
    r = client.post("/v1/pipelines/peak-report:run", json={"source": "sftp"}, headers=MANAGER)
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/source"
    r = client.post("/v1/pipelines/peak-report:run", json={"source": "api", "since": "yesterday"}, headers=MANAGER)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "since_invalid"
