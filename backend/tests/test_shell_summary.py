"""Delta-100 D2b / SH1 / SH2 / SH4 — GET /v1/shell/summary.

The rail's one summary: the workload footer, the per-row badge counts and the KPI
strip. Every figure must be the one its own screen serves — the tests read those
screens' own payloads and compare, never recompute a second time.
"""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


def _client(name):
    c = TestClient(app)
    c.cookies.set("volt_session", name)
    return c


def test_shape_and_the_seven_row_settings_badge():
    body = _client("shell-shape").get("/v1/shell/summary").json()
    assert set(body) >= {"business_date", "workload", "badges", "kpi"}
    assert set(body["workload"]) >= {"caseload", "cap", "contact_denominator", "percentage", "bar_pct"}
    assert set(body["badges"]) >= {"today", "today_due", "book", "reviews", "pipeline",
                                   "payments", "recovery", "settings"}
    # The prototype's settings rail count is the flat register's own seven rows.
    assert body["badges"]["settings"] == 7
    assert set(body["kpi"]) >= {"value", "target", "achieved", "period", "week_label"}


def test_the_numbers_are_the_ones_the_reports_helpers_serve():
    c = _client("shell-numbers")
    body = c.get("/v1/shell/summary").json()
    team = c.get("/v1/reports/team").json()
    assert body["workload"]["caseload"] == team["team"]["cases_total"]
    assert body["workload"]["contact_denominator"] == team["team"]["in_scope"]
    assert body["badges"]["book"] == team["team"]["cases_total"]
    assert body["badges"]["reviews"] == team["queues"]["reviews_open"]
    assert body["badges"]["pipeline"] == team["queues"]["pipeline"]
    assert body["badges"]["payments"] == team["queues"]["peak_not_approved"]
    assert body["badges"]["recovery"] == team["queues"]["npl_cases"]


def test_the_today_badge_is_the_officers_own_today_page():
    c = _client("shell-officer")
    shell = c.get("/v1/shell/summary", params={"officer": "nantapol"}).json()
    today = c.get("/v1/today", params={"officer": "nantapol"}).json()
    assert shell["badges"]["today"] == today["meta"]["total"]
    assert shell["badges"]["today_due"] == \
        today["meta"]["total"] - today["meta"]["counts_by_tier"].get("ROUTINE", 0)
    # An officer the book does not know is refused by name, not served an empty desk.
    r = c.get("/v1/shell/summary", params={"officer": "nobody"})
    assert r.status_code == 422 and r.json()["message_th"]


def test_the_caseload_cap_is_config_tunable_and_the_percentage_follows():
    c = _client("shell-cap")
    workload = c.get("/v1/shell/summary").json()["workload"]
    assert workload["cap"] is None and workload["percentage"] is None and workload["cap_note_th"]
    assert c.put("/v1/config", json={"caseload_cap": 300}, headers=MANAGER).status_code == 200
    workload = c.get("/v1/shell/summary").json()["workload"]
    assert workload["cap"] == 300
    expected = (Decimal(workload["caseload"]) / 300 * 100).quantize(Decimal("0.1"))
    assert workload["percentage"] == str(expected)
    assert workload["bar_pct"] == str(max(Decimal("0.0"), min(Decimal("100.0"), expected)))
    assert workload["cap_note_th"] is None


def test_the_kpi_strip_serves_the_weekly_reports_cash_and_target():
    c = _client("shell-kpi")
    kpi = c.get("/v1/shell/summary").json()["kpi"]
    assert kpi["target"] is None and kpi["achieved"] is None
    weekly = c.get("/v1/reports/weekly").json()
    assert kpi["value"] == weekly["management_summary"]["cash_in"]["total"]
    period = weekly["period"]["label"]
    c.put("/v1/reports/weekly/%s/targets" % period, json={"total": "100"}, headers=MANAGER)
    kpi = c.get("/v1/shell/summary").json()["kpi"]
    weekly = c.get("/v1/reports/weekly").json()
    assert kpi["target"] == "100"
    assert kpi["achieved"] == weekly["management_summary"]["achievement"]["total"]
    assert kpi["period"] == period and kpi["week_label"].startswith("WK-")


def test_a_get_works_each_contract_out_once(monkeypatch):
    """Fix-all F5: the summary read the same contract five times in one request (769
    money walks for 151 contracts on the fixture book). A GET now works each
    (contract, day) out once; outside a request nothing is memoised."""
    from app import main

    walked = []
    real = main._work_out_contract
    monkeypatch.setattr(main, "_work_out_contract",
                        lambda contract, as_of=None: walked.append((contract.uid, as_of)) or real(contract, as_of))
    for path in ("/v1/shell/summary", "/v1/today"):
        walked.clear()
        assert _client("shell-memo").get(path).status_code == 200
        assert walked and len(walked) == len(set(walked)), path
    contract = main.CUSTOMERS[0].contracts[0]
    walked.clear()
    main._contract_view(contract)
    main._contract_view(contract)
    assert len(walked) == 2
