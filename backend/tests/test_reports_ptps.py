"""F16 / Q3 — the PTP report (feedback-r2 TASK-114/115).

Every promise of every status, from both promise stores, inside a date range, with
served totals and a CSV export that is audited. Every test here is an ADDITION.
"""
from datetime import timedelta
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app.config import settings
from app.main import app

BD = settings.business_date
OFFICER = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _uids(client, n):
    rows = client.get("/v1/workbook").json()["rows"]
    out = [r["customer"]["uid"] for r in rows]
    assert len(out) >= n
    return out[:n]


def _journey_promise(client, uid, day, amount="1000.00", by="Nok"):
    response = client.post("/v1/ptps", json={
        "customer_uid": uid, "promised_amount": amount, "promise_date": str(day), "by": by})
    assert response.status_code == 201, response.text
    return response.json()["ptp"]


def _case_promise(client, uid, day, amount="2000.00", officer="nantapol"):
    # a case promise needs a free case (one open promise per customer)
    state = cases_domain.for_current()
    if state.cases[uid]["open_ptp_uid"]:
        cases_domain.close_ptp(state, state.cases[uid], state.cases[uid]["open_ptp_uid"],
                               "CANCELLED", BD, by="test")
    response = client.post("/v1/cases/by-customer/%s/contacts" % uid,
                           headers={"X-Volt-Officer": officer},
                           json={"result": "REACHED_PTP", "counted": False, "amount_stated": True,
                                 "ptp": {"amount": amount, "date": str(day)}})
    assert response.status_code == 201, response.text
    return response.json()["ptp"]


def _report(client, **params):
    response = client.get("/v1/reports/ptps", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_range_is_inclusive_at_both_ends(client):
    uid_a, uid_b = _uids(client, 2)
    first_day = BD + timedelta(days=300)
    second_day = BD + timedelta(days=302)
    journey_ptp = _journey_promise(client, uid_a, first_day, by="nok")
    _case_promise(client, uid_b, second_day)

    only_first = _report(client, **{"from": str(first_day), "to": str(first_day)})
    assert [r["uid"] for r in only_first["rows"]] == [journey_ptp["uid"]]
    only_second = _report(client, **{"from": str(second_day), "to": str(second_day)})
    assert len(only_second["rows"]) == 1 and only_second["rows"][0]["source"] == "case"
    both = _report(client, **{"from": str(first_day), "to": str(second_day)})
    assert {r["uid"] for r in both["rows"]} == {journey_ptp["uid"], only_second["rows"][0]["uid"]}
    assert {r["source"] for r in both["rows"]} == {"case", "journey"}


def test_the_officer_and_status_filters_narrow_the_rows(client):
    uid_a, uid_b, uid_c = _uids(client, 3)
    day = BD + timedelta(days=320)
    mine = _journey_promise(client, uid_a, day, by="nok")
    other = _journey_promise(client, uid_b, day, by="other-officer")
    kept = _journey_promise(client, uid_c, day, by="nok")
    closed = client.post("/v1/ptps/%s:close" % kept["uid"], json={"outcome": "KEPT"})
    assert closed.status_code == 200, closed.text

    by_officer = _report(client, **{"from": str(day), "to": str(day)}, officer="nok")
    assert {r["uid"] for r in by_officer["rows"]} == {mine["uid"], kept["uid"]}
    by_status = _report(client, **{"from": str(day), "to": str(day)}, status="KEPT")
    assert [r["uid"] for r in by_status["rows"]] == [kept["uid"]]
    assert other["uid"] not in {r["uid"] for r in by_officer["rows"]}


def test_the_totals_are_served_and_tie_out_to_the_rows(client):
    uid_a, uid_b = _uids(client, 2)
    day = BD + timedelta(days=330)
    _journey_promise(client, uid_a, day, amount="1234.50", by="nok")
    _case_promise(client, uid_b, day, amount="765.50")
    body = _report(client, **{"from": str(day), "to": str(day)})
    assert body["totals"]["count"] == len(body["rows"]) == 2
    assert body["totals"]["promised_amount"] == "2000.00"
    by_status = body["totals"]["by_status"]
    assert by_status["OPEN"]["count"] == 2
    assert by_status["OPEN"]["promised_amount"] == "2000.00"
    assert body["meta"]["from"] == str(day) and body["meta"]["to"] == str(day)
    assert body["meta"]["note_th"] and body["meta"]["note_en"]


def test_the_default_range_is_the_business_month(client):
    body = _report(client)
    assert body["meta"]["from"] == str(BD.replace(day=1))
    assert body["meta"]["to"] >= str(BD)
    assert body["meta"]["to"].startswith(str(BD)[:7])


def test_a_bad_date_and_an_unknown_status_are_refused(client):
    bad = client.get("/v1/reports/ptps", params={"from": "not-a-date"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/from"
    inverted = client.get("/v1/reports/ptps", params={"from": "2026-12-01", "to": "2026-11-01"})
    assert inverted.status_code == 422 and inverted.json()["errors"][0]["code"] == "range_inverted"
    unknown = client.get("/v1/reports/ptps", params={"status": "MAYBE"})
    assert unknown.status_code == 422
    assert unknown.json()["errors"][0]["pointer"] == "/status"


def test_the_export_is_csv_with_one_header_row_and_the_same_rows(client):
    uid_a, uid_b = _uids(client, 2)
    day = BD + timedelta(days=340)
    _journey_promise(client, uid_a, day, amount="111.00")
    _case_promise(client, uid_b, day, amount="222.00")
    body = _report(client, **{"from": str(day), "to": str(day)})
    response = client.post("/v1/reports/ptps:export", json={"from": str(day), "to": str(day)})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert 'ptp-report_%s_%s.csv' % (day, day) in response.headers.get("content-disposition", "")
    lines = [ln for ln in response.text.lstrip("\ufeff").strip().splitlines() if ln]
    assert len(lines) == len(body["rows"]) + 1
    assert lines[0].startswith("customer,volt_id,officer,source,promise_date")
    entry = next(e for e in client.get("/v1/audit").json()["entries"] if e["act"] == "PTP_REPORT_EXPORTED")
    assert entry["subject_type"] == "report" and entry["subject_uid"] == "ptps"
    assert entry["detail"]["rows"] == len(body["rows"])


def test_ptp_csv_projection_and_order_match_the_screen_api(client):
    uid_a, uid_b = _uids(client, 2)
    day = BD + timedelta(days=345)
    _journey_promise(client, uid_a, day, amount="321.00", by="nok")
    _case_promise(client, uid_b, day, amount="654.00")
    params = {"from": str(day), "to": str(day), "status": "OPEN"}
    api_rows = _report(client, **params)["rows"]
    response = client.post("/v1/reports/ptps:export", json=params)
    csv_rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    expected = [{
        "customer": row["display_name"] or "", "volt_id": row["volt_id"] or "",
        "officer": row["officer_uid"] or "", "source": row["source"],
        "promise_date": row["promise_date"], "promised_amount": row["promised_amount"],
        "status": row["status"], "closed_on": row["closed_on"] or "",
        "renegotiation_count": str(row["renegotiation_count"]),
        "lineage_from_uid": row["lineage_from_uid"] or "",
    } for row in api_rows]
    assert csv_rows == expected
