"""F01 / F01c / REQ-112 — a contact carries its promise, and a promise result without
an amount is refused (feedback-r2 TASK-106, R-E, numbered edit 42).

The one pinned call this rule changed is `test_round2.py:272`; every other promise
creating call in the suite already carried its `ptp`. This file is ADDITIVE.
"""
from datetime import timedelta

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


@pytest.fixture
def state():
    return cases_domain.for_current()


@pytest.fixture
def uid(state):
    case = next(k for k in state.cases.values()
                if k["open_ptp_uid"] is None and k["payment_status"] not in ("CLOSED", "TERMINATED"))
    return case["customer_uid"]


def _post(client, uid, **body):
    return client.post("/v1/cases/by-customer/%s/contacts" % uid, json=body, headers=OFFICER)


def test_a_contact_creates_the_promise_and_the_case_follows_it(client, state, uid):
    day = str(BD + timedelta(days=7))
    response = _post(client, uid, result="PROMISED", channel="PHONE", counted=False,
                     ptp={"amount": "6985.42", "date": day})
    assert response.status_code == 201, response.text
    ptp = response.json()["ptp"]
    assert ptp["status"] == "OPEN" and ptp["promised_amount"] == "6985.42" and ptp["promise_date"] == day
    assert state.cases[uid]["next_action"] == "FOLLOW_PTP"
    detail = client.get("/v1/cases/by-customer/%s" % uid).json()
    assert detail["ptps"][0]["uid"] == ptp["uid"]
    assert detail["contact_log"][0]["ptp_uid"] == ptp["uid"]


def test_a_second_promise_on_the_same_case_is_refused_with_the_open_uid(client, uid):
    first = _post(client, uid, result="REACHED_PTP", counted=False,
                  ptp={"amount": "1000.00", "date": str(BD + timedelta(days=3))})
    assert first.status_code == 201, first.text
    opened = first.json()["ptp"]["uid"]
    second = _post(client, uid, result="PROMISED", counted=False,
                   ptp={"amount": "1000.00", "date": str(BD + timedelta(days=5))})
    assert second.status_code == 409 and second.json()["code"] == "ptp_already_open"
    assert second.json()["extensions"]["ptp_uid"] == opened


def test_a_promise_result_without_an_amount_is_refused_server_side(client, uid):
    for result in ("PROMISED", "REACHED_PTP"):
        response = _post(client, uid, result=result, counted=False,
                         next_action="CALL", next_action_on=str(BD))
        assert response.status_code == 422, response.text
        problem = response.json()
        assert problem["code"] == "ptp_required_for_promise"
        assert problem["error_id"] == "DEBT-COL-0476"
        assert problem["message_th"]
        assert "นัดชำระ" in problem["message_th"]
    # nothing was written: the case still holds no promise from the refused calls
    assert cases_domain.for_current().cases[uid]["open_ptp_uid"] is None


def test_a_promise_result_with_an_amount_but_no_date_is_refused_by_the_domain(client, uid):
    response = _post(client, uid, result="PROMISED", counted=False,
                     ptp={"amount": "1000.00", "date": "not-a-date"})
    assert response.status_code == 422
    assert response.json()["code"] == "ptp_date_invalid"
