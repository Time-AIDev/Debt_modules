"""D03 / Q7 — pairing from the case side (feedback-r2 TASK-210).

The case searches the applied run's contact codes, sees a code already linked
elsewhere, and binds one to its own customer (rule PERSON_CASE). Every test here is
an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db, journey, migrate
from app.book import SHEET
from app.main import app
from app.pipelines import peak_writer

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


def _book_customer_no():
    return next(c.customer_no for c in journey.book_customers() if c.data_source == SHEET and c.contracts)


def _inv(doc, code):
    return {"doc_no": doc, "doc_kind": doc.split("-")[0], "issued_on": "2026-07-11", "due_on": "2026-07-18",
            "reference": code, "system_reference": None, "contact_code": code,
            "customer_name": "Worarut Sangtong", "tax_id_13": "123", "status": "AWAITING", "cycle": None,
            "product_group": None, "amount_total": "8399.00", "amount_due": "8399.00",
            "amount_awaiting": "8399.00", "payment": None, "note": None, "lines": []}


def _parsed(*invoices):
    return {"report_as_of": "2026-09-14", "header_row": 10, "lines": [], "rejected": [], "invoices": list(invoices)}


@pytest.fixture
def db_env(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        yield pg_conn
    finally:
        pg_conn.execute(text("delete from records.identity_link"))
        pg_conn.commit()


def test_the_case_searches_and_links_a_peak_code(db_env):
    conn = db_env
    no = _book_customer_no()
    uid = "sheet-%s" % no
    written = peak_writer.write(conn, _parsed(_inv("IVT-90200", "VC-CASE-1")), [
        {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": no, "candidates": []}])
    conn.commit()
    peak_writer.apply_run(conn, written["run_id"], by="test")
    conn.commit()

    found = client.get("/v1/cases/by-customer/%s/peak-codes" % uid, params={"q": "VC-CASE"}).json()
    assert found["meta"]["total"] == 1
    assert found["codes"][0]["contact_code"] == "VC-CASE-1"
    assert found["codes"][0]["linked_to"] is None
    conn.rollback()
    short = client.get("/v1/cases/by-customer/%s/peak-codes" % uid, params={"q": "V"}).json()
    assert short["codes"] == [] and short["meta"]["min_chars"] == 2
    conn.rollback()

    linked = client.post("/v1/cases/by-customer/%s/peak-link" % uid, headers=OFFICER,
                         json={"contact_code": "VC-CASE-1", "reason": "ตรงกับเคสนี้"})
    assert linked.status_code == 201, linked.text
    assert linked.json()["link"]["rule"] == "PERSON_CASE"
    conn.commit()
    rows = conn.execute(text("select customer_no, rule from records.identity_link")).all()
    assert rows == [(no, "PERSON_CASE")]

    # the case's own list, and the code now says who it is linked to
    links = client.get("/v1/pipelines/peak-report/links", params={"customer_no": no}).json()["links"]
    assert [r["contact_code"] for r in links] == ["VC-CASE-1"]
    conn.rollback()
    again = client.get("/v1/cases/by-customer/%s/peak-codes" % uid, params={"q": "VC-CASE"}).json()
    assert again["codes"][0]["linked_to"] == no


def test_a_link_needs_a_contact_code(db_env):
    no = _book_customer_no()
    uid = "sheet-%s" % no
    bad = client.post("/v1/cases/by-customer/%s/peak-link" % uid, headers=OFFICER, json={"reason": "x"})
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["pointer"] == "/contact_code"
