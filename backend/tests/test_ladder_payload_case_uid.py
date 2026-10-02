"""F05 / TASK-109 — the ladder payload names the journey case it draws.

The strip needs `case_uid` and `kind` to call the right `:set-stage` route; the
hand-move tests (test_ladder_set_stage.py) are next door. This file is ADDITIVE.
"""
import pytest
from fastapi.testclient import TestClient

from app import journey
from app.main import app


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def test_the_ladder_names_its_journey_case_for_a_lease_and_a_cash_customer(client):
    state = journey.for_current()
    lease = next(iter(state.cases.values()))
    detail = client.get("/v1/cases/by-customer/%s" % lease["customer_uid"]).json()
    ladder = detail["work_item"]["ladder"]
    assert ladder["kind"] == "LEASE" and ladder["case_uid"] == lease["uid"]

    cash = next(iter(state.cash_cases.values()))
    detail = client.get("/v1/cases/by-customer/%s" % cash["customer_uid"]).json()
    ladder = detail["work_item"]["ladder"]
    assert ladder["kind"] == "CASH" and ladder["case_uid"] == cash["uid"]


def test_a_sheet_row_with_no_journey_case_serves_nulls_never_a_guessed_uid(client):
    rows = client.get("/v1/workbook").json()["rows"]
    plain = next(r for r in rows if (r.get("ladder") or {}).get("steps"))
    assert plain["ladder"]["case_uid"] is None
    assert plain["ladder"]["kind"] in ("LEASE", "CASH")
