"""F07 — the calendar serves promises first and names each item's rank (feedback-r2 TASK-103).

The screen colours by kind and draws PTP entries first; the order comes from the
server's own KIND_RANK, served as `priority` on every item and as `meta.kind_order`.
Every test here is an ADDITION to the suite.
"""
from fastapi.testclient import TestClient

from app import cases as cases_domain
from app.config import settings
from app.main import app

BD = settings.business_date
HEAD = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "OFFICER"}


def _client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def test_meta_serves_the_urgency_order_with_ptp_first():
    body = _client().get("/v1/calendar", headers=HEAD).json()
    order = body["meta"]["kind_order"]
    assert order[0] == "PTP_DUE" and order[1] == "NEXT_ACTION"
    assert set(order) == {"PTP_DUE", "NEXT_ACTION", "REVIEW_SLA", "ISSUE_DEADLINE",
                          "NPL_BUYBACK", "RESTRUCTURE", "SETTLEMENT", "REMINDER_BATCH", "NOTICE"}


def test_a_promise_outranks_a_next_action_on_the_same_day_and_carries_its_rank():
    c = _client()
    state = cases_domain.for_current()
    case = next(k for k in state.cases.values()
                if k["open_ptp_uid"] is None and k["payment_status"] not in ("CLOSED", "TERMINATED"))
    uid = case["customer_uid"]
    made = c.post("/v1/cases/by-customer/%s/contacts" % uid, headers=HEAD,
                  json={"result": "REACHED_PTP", "counted": False, "amount_stated": True,
                        "ptp": {"amount": "1000", "date": str(BD)}})
    assert made.status_code == 201, made.text

    day = [i for i in c.get("/v1/calendar", headers=HEAD).json()["items"] if i["on"] == str(BD)]
    kinds = [i["kind"] for i in day]
    # The whole book carries NEXT_ACTIONs on the business date (test_calendar.py pins
    # more than three); the promise we just made must sort ahead of every one.
    assert "NEXT_ACTION" in kinds and "PTP_DUE" in kinds
    assert kinds.index("PTP_DUE") < kinds.index("NEXT_ACTION")
    assert all(i["priority"] == 0 for i in day if i["kind"] == "PTP_DUE")
    assert all(i["priority"] == 1 for i in day if i["kind"] == "NEXT_ACTION")
