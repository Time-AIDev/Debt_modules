"""F17 / R-A — worked rows and the daily summary (feedback-r2 TASK-118).

"Worked today" is a served fact: the case's own last contact, or this session's own
stamp, on the business date. The seven tiers are untouched; the summary is a second
served object beside them. Every test here is an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient

from app import today as today_domain
from app.config import settings
from app.main import app

BD = settings.business_date
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _pick(client, **where):
    """A row with an officer and no open promise (where the act under test is free)."""
    for item in client.get("/v1/today").json()["items"]:
        if item["case"]["officer_uid"] != OFFICER["X-Volt-Officer"] or item["case"]["open_ptp"]:
            continue
        if all(item["case"].get(k) == v for k, v in where.items()):
            return item
    raise AssertionError("no row matches %r" % where)


def _contact(client, uid, **body):
    payload = {"counted": True, "next_action": "CALL", "next_action_on": str(BD), **body}
    return client.post("/v1/cases/by-customer/%s/contacts" % uid, headers=OFFICER, json=payload)


def test_a_contact_logged_today_marks_the_row_and_moves_the_summary(client):
    item = _pick(client)
    uid, officer = item["customer"]["uid"], item["case"]["officer_uid"]
    before = client.get("/v1/today").json()["meta"]["daily_summary"][officer]
    response = _contact(client, uid, result="REACHED_ANSWERED")
    assert response.status_code == 201, response.text

    body = client.get("/v1/today").json()
    row = next(i for i in body["items"] if i["customer"]["uid"] == uid)
    assert row["worked_today"] is True
    assert row["worked_at"] and str(row["worked_at"])[:10] == str(BD)
    assert body["meta"]["worked_today_count"] == 1
    summary = body["meta"]["daily_summary"][officer]
    assert summary["worked"] == before["worked"] + 1
    assert summary["not_yet"] == before["not_yet"] - 1
    assert summary["total"] == before["total"]
    whole = body["meta"]["daily_summary"]["*"]
    assert whole["worked"] == 1 and whole["not_yet"] == body["meta"]["total"] - 1
    assert all(not i["worked_today"] for i in body["items"] if i["customer"]["uid"] != uid)


def test_a_promise_made_today_adds_its_amount_to_the_summary(client):
    item = _pick(client)
    uid, officer = item["customer"]["uid"], item["case"]["officer_uid"]
    response = _contact(client, uid, result="REACHED_PTP", ptp={"amount": "1234.50", "date": str(BD)})
    assert response.status_code == 201, response.text
    summary = client.get("/v1/today").json()["meta"]["daily_summary"][officer]
    assert summary["ptp_count"] == 1
    assert summary["ptp_amount"] == "1234.50"
    assert client.get("/v1/today").json()["meta"]["daily_summary"]["*"]["ptp_amount"] == "1234.50"


def test_an_unreachable_result_counts_in_the_summary(client):
    item = _pick(client)
    uid, officer = item["customer"]["uid"], item["case"]["officer_uid"]
    assert _contact(client, uid, result="UNREACHABLE_NO_ANSWER").status_code == 201
    summary = client.get("/v1/today").json()["meta"]["daily_summary"][officer]
    assert summary["unreachable"] == 1
    assert client.get("/v1/today").json()["meta"]["daily_summary"]["*"]["unreachable"] == 1


def test_the_seven_tiers_still_partition_the_list(client):
    body = client.get("/v1/today").json()
    assert set(body["meta"]["counts_by_tier"]) == set(today_domain.TIERS)
    assert sum(body["meta"]["counts_by_tier"].values()) == body["meta"]["total"] == len(body["items"])
    assert all("worked_today" in i and "worked_at" in i for i in body["items"])
