"""Delta-100 D2i — the editions list carries per-edition figures.

Contacts over the edition's own frozen period, the kept/total PTP pair and the cash
total from its frozen payload, and the numeric cash mirror the sort toggle reads.
The row shape must stay the summary (no payload), and a genuinely missing figure is
None, never 0.
"""
from decimal import Decimal

from fastapi.testclient import TestClient

from app import cases as cases_domain
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


def _client(name):
    c = TestClient(app)
    c.cookies.set("volt_session", name)
    return c


def test_a_published_edition_carries_contacts_ptp_and_cash():
    c = _client("editions-figures")
    c.post("/v1/reports/weekly:publish", headers=MANAGER)
    row = c.get("/v1/reports/weekly/editions").json()["editions"][0]
    assert "payload" not in row
    frozen = c.get("/v1/reports/weekly/editions/%s" % row["edition_uid"]).json()["edition"]
    promises = frozen["payload"]["promises"]
    assert row["ptp_kept"] == promises["kept"]
    assert row["ptp_total"] == promises["kept"] + promises["broken"]
    # The same number the edition froze, in the wire's money shape (2dp).
    assert Decimal(row["cash_total"]) == Decimal(frozen["payload"]["management_summary"]["cash_in"]["total"])
    assert row["cash_sort"] == float(Decimal(row["cash_total"]))

    # The contacts count is the edition's OWN period over the contact log — the same
    # date rule reports.officers() counts by — so it cannot disagree with the roster.
    cs = cases_domain.for_current()
    start, end = row["period"].split("..")
    rows = [r for r in cs.contact_log if start <= str(r.get("occurred_at") or "")[:10] <= end]
    assert row["contacts"] == len(rows)
    assert row["counted_contacts"] == sum(1 for r in rows if r.get("counted"))
    assert isinstance(row["contacts"], int) and isinstance(row["counted_contacts"], int)


def test_every_edition_of_a_week_carries_its_own_figures():
    c = _client("editions-figures-two")
    c.post("/v1/reports/weekly:publish", headers=MANAGER)
    c.post("/v1/reports/weekly:publish", headers=MANAGER)
    rows = c.get("/v1/reports/weekly/editions").json()["editions"]
    assert len(rows) == 2
    assert [r["number"] for r in rows] == [2, 1]
    for row in rows:
        assert row["cash_total"] is not None and row["cash_sort"] is not None
        assert row["ptp_kept"] is not None and row["ptp_total"] is not None


def test_an_edition_with_no_figure_serves_none_never_zero():
    from app.routers.reports import _edition_figures
    row = _edition_figures({"edition_uid": "wke-99999", "period": "x..y", "payload": {}},
                           cases_domain.for_current())
    assert row["contacts"] is None and row["counted_contacts"] is None
    assert row["ptp_kept"] is None and row["ptp_total"] is None
    assert row["cash_total"] is None and row["cash_sort"] is None
