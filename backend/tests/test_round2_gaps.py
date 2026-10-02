"""Round-2 judge acceptance gaps the two fix batches did not cover.

Ids are the judge's (docs/uat/round-2/judge.md).
"""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


@pytest.fixture
def officer():
    return OFFICER


@pytest.fixture
def manager():
    return MANAGER


def test_npl_type_needs_a_code(client, manager):
    """J2-16 (judge's own observation): an empty code closed the SYSTEM review
    and left the case without a type."""
    uid = _an_npl_case(client, manager)
    r = client.post("/v1/cases/by-customer/%s/npl-type" % uid, headers=manager,
                    json={"reason": "ตกลงในที่ประชุม"})
    assert r.status_code == 422
    assert r.json()["code"] == "npl_type_required"
    assert r.json()["message_th"]


def test_link_sent_records_the_person_and_the_day(client, officer):
    """J2-03: the sheet says a link was sent but not when. The officer records
    the send; no sheet invoice is ever stamped with the business date by itself."""
    case = client.get("/v1/cases/by-customer/sheet-99999000027", headers=officer).json()
    unsent = [i for i in case["invoices"] if not i.get("link_sent")]
    assert unsent, "the migrated book must have an invoice with no link"
    inv = unsent[0]
    r = client.post("/v1/invoices/%s:link-sent" % inv["uid"], headers=officer, json={})
    assert r.status_code == 200
    got = r.json()["invoice"]
    assert got["link_sent"] is True
    assert got["link_sent_on"] == str(settings.business_date)
    assert got["link_sent_by"] == officer["X-Volt-Officer"]
    assert got["link_sent_source"] == "APP"
    assert str(settings.business_date) in got["link_sent_note_th"]


def test_link_sent_needs_an_officer(client):
    case = client.get("/v1/cases/by-customer/sheet-99999000027",
                      headers={"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}).json()
    inv = [i for i in case["invoices"] if not i.get("link_sent")][0]
    r = client.post("/v1/invoices/%s:link-sent" % inv["uid"], json={})
    assert r.status_code == 422
    assert r.json()["code"] == "officer_required"


def test_sheet_invoices_are_not_stamped_with_the_business_date(client, officer):
    """J2-03: 63 of 69 sent sheet invoices carried link_sent_on = today."""
    rows = client.get("/v1/ar/pipeline", headers=officer).json()["invoices"]
    stamped = [i for i in rows
               if i.get("link_sent_source") == "SHEET_CELL" and i.get("link_sent_on")]
    assert stamped == []


def test_pipeline_counts_separate_the_window_from_the_rest(client, officer):
    """J2-26: with everything shown, rows outside the look-ahead were counted
    under "within N days"."""
    windowed = client.get("/v1/pipeline", headers=officer).json()["meta"]["counts"]
    everything = client.get("/v1/pipeline", headers=officer, params={"all": "true"}).json()["meta"]["counts"]
    # Round-3 J3-10: `beyond` is counted over the whole book in BOTH views — counted
    # over the returned rows it could never be non-zero in the default view.
    assert windowed["beyond"] == everything["beyond"] > 0
    assert everything["upcoming"] == windowed["upcoming"]
    assert everything["window_days"] == settings.pipeline_lookahead_days


def _an_npl_case(client, manager):
    rows = client.get("/v1/npl-cases", headers=manager).json()
    items = rows.get("npl_cases") or rows.get("cases") or rows.get("items") or []
    assert items, "the book has NPL cases"
    return items[0].get("customer_uid") or items[0]["case"]["customer_uid"]
