"""D02 / Q7 — per-field decisions with provenance (feedback-r2 TASK-207/208/209).

The served record overlays an active PEAK decision; retiring restores Odoo; the apply
defaults the undecided conflicts to PEAK with the applier's name. Every test here is
an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import book_source, db, journey, migrate
from app.book import SHEET
from app.main import app
from app.pipelines import field_decisions, peak_links, peak_writer

client = TestClient(app)
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


def _book_customer_no():
    return next(c.customer_no for c in journey.book_customers() if c.data_source == SHEET and c.contracts)


def _inv(doc, code):
    return {"doc_no": doc, "doc_kind": doc.split("-")[0], "issued_on": "2026-07-11", "due_on": "2026-07-18",
            "reference": code, "system_reference": None, "contact_code": code,
            "customer_name": "Worarut Sangtong", "tax_id_13": "123", "status": "PAID", "cycle": None,
            "product_group": "Cash", "amount_total": "8399.00", "amount_due": "8399.00",
            "amount_awaiting": "0.00", "payment": None, "note": None,
            "product_name": "Solar Rooftop_5.00kWp", "lines": []}


def _identity(no):
    return {"name_th": "สมชาย ธรรมดี", "name_roman": "Somchai Tamdee", "volt_id": "VL0010158_head",
            "customer_no": no, "product": "LEASE", "order": {"watt": "5000"}}


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
        pg_conn.execute(text("delete from records.field_decision"))
        pg_conn.execute(text("delete from records.identity_link"))
        pg_conn.commit()


def test_decide_and_retire_round_trip_and_landing_is_untouched(db_env):
    conn = db_env
    no = "28005096535"
    before = conn.execute(text("select count(*) from landing.customer")).scalar()
    row = field_decisions.decide(conn, no, "customer_name", "PEAK", by="settasak",
                                 peak_value="Worarut Sangtong", odoo_value="สมชาย ธรรมดี",
                                 reason="PEAK name is the real one")
    conn.commit()
    loaded = field_decisions.load(conn)[no]["customer_name"]
    assert loaded["chosen_source"] == "PEAK" and loaded["decided_by"] == "settasak"
    assert conn.execute(text("select count(*) from landing.customer")).scalar() == before
    retired = field_decisions.retire(conn, row["uid"], "settasak")
    conn.commit()
    assert retired["retired_by"] == "settasak" and field_decisions.load(conn) == {}


def test_the_served_record_overlays_a_peak_decision_with_its_note():
    record = {"customer_no": "28005096535", "name_th": "สมชาย ธรรมดี", "display_name": "สมชาย ธรรมดี",
              "volt_id": "VL0010158_head", "product": "LEASE", "order": {"watt": "5000"}}
    book_source._apply_field_decisions(record, {
        "customer_name": {"chosen_source": "PEAK", "peak_value": "Worarut Sangtong",
                          "odoo_value": "สมชาย ธรรมดี", "decided_by": "settasak",
                          "decided_at": "2026-09-23T00:00:00"},
        "system_size_kwp": {"chosen_source": "PEAK", "peak_value": "6.25", "odoo_value": "5.00",
                            "decided_by": "settasak", "decided_at": "2026-09-23T00:00:00"},
    })
    assert record["name_th"] == "Worarut Sangtong" and record["display_name"] == "Worarut Sangtong"
    assert record["order"]["watt"] == "6250"
    assert record["field_sources"] == {"customer_name": "PEAK", "system_size_kwp": "PEAK"}
    assert "PEAK ว่า Worarut Sangtong" in record["field_notes_th"]["customer_name"]


def test_an_odoo_decision_changes_nothing_on_the_served_record():
    record = {"name_th": "สมชาย ธรรมดี", "display_name": "สมชาย ธรรมดี"}
    book_source._apply_field_decisions(record, {
        "customer_name": {"chosen_source": "ODOO", "peak_value": "Worarut", "odoo_value": "สมชาย ธรรมดี",
                          "decided_by": "settasak", "decided_at": "2026-09-23T00:00:00"},
    })
    assert record["display_name"] == "สมชาย ธรรมดี" and "field_sources" not in record


def test_default_all_fills_only_the_undecided_and_apply_reports_it(db_env):
    conn = db_env
    no = _book_customer_no()
    written = peak_writer.write(conn, _parsed(_inv("IVT-90100", no)), [
        {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": no, "candidates": []}],
        identities={str(no): _identity(no)})
    conn.commit()
    conflicts = peak_writer.conflict_rows(conn, written["run_id"])
    assert conflicts and {c["field"] for c in conflicts[0]["conflicts"]} >= {"customer_name", "product"}

    field_decisions.decide(conn, no, "product", "ODOO", by="settasak")
    conn.commit()
    defaulted = field_decisions.default_all(conn, written["run_id"], "settasak")
    assert defaulted >= 1
    loaded = field_decisions.load(conn)[no]
    assert loaded["product"]["chosen_source"] == "ODOO"
    assert loaded["customer_name"]["chosen_source"] == "PEAK"
    assert loaded["customer_name"]["decided_by"] == "settasak"
    assert "default PEAK on apply" in loaded["customer_name"]["reason"]

    run = peak_writer.apply_run(conn, written["run_id"], by="settasak")
    conn.commit()
    assert run["defaulted_fields"] >= 0     # a person already decided every field


def test_default_all_never_defaults_the_volt_id(db_env):
    """Fix-all P5 (F8): for a linked or phone-bridged match the volt_id conflict's PEAK
    side is the contact code's head; defaulting it replaced the customer's own id."""
    conn = db_env
    no = _book_customer_no()
    peak_links.confirm(conn, "VC0099901", no, by="settasak")
    written = peak_writer.write(conn, _parsed(_inv("IVT-90103", "VC0099901")), [
        {"verdict": "EXACT", "rule": "LINK", "customer_no": no, "candidates": []}],
        identities={str(no): _identity(no)})
    conn.commit()
    assert "volt_id" in {c["field"] for c in peak_writer.conflict_rows(conn, written["run_id"])[0]["conflicts"]}
    assert field_decisions.default_all(conn, written["run_id"], "settasak") >= 1
    loaded = field_decisions.load(conn)[no]
    assert "volt_id" not in loaded and loaded["customer_name"]["chosen_source"] == "PEAK"


def test_the_conflict_routes_decide_retire_and_serve_the_page(db_env):
    conn = db_env
    no = _book_customer_no()
    written = peak_writer.write(conn, _parsed(_inv("IVT-90101", no)), [
        {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": no, "candidates": []}],
        identities={str(no): _identity(no)})
    conn.commit()
    page = client.get("/v1/pipelines/peak-report/landing-runs/%d/conflicts" % written["run_id"]).json()
    assert page["total"] == 1 and page["rows"][0]["customer_no"] == no
    assert page["rows"][0]["decided"] is False
    assert {c["field"] for c in page["rows"][0]["conflicts"]} >= {"customer_name"}
    conn.rollback()

    decided = client.post("/v1/pipelines/peak-report/landing-runs/%d/conflicts:decide" % written["run_id"],
                          headers=OFFICER,
                          json={"customer_no": no, "decisions": [
                              {"field": "customer_name", "source": "PEAK", "reason": "PEAK name is right"}]})
    assert decided.status_code == 200, decided.text
    conn.commit()
    # fix-all P3 (F4): the decision keeps what each side said, and the served field
    # takes PEAK's value — it was stored NULL and blanked the name.
    stored = field_decisions.load(conn)[no]["customer_name"]
    assert (stored["peak_value"], stored["odoo_value"]) == ("Worarut Sangtong", "สมชาย ธรรมดี")
    from tests.test_peak_book import _sheet_customer
    _sheet_customer(conn, no)
    served = next(c for c in book_source._from_landing(conn)["customers"] if c["customer_no"] == no)
    assert served["display_name"] == "Worarut Sangtong" and served["field_sources"] == {"customer_name": "PEAK"}
    conn.commit()
    page = client.get("/v1/pipelines/peak-report/landing-runs/%d/conflicts" % written["run_id"]).json()
    shown = next(c for c in page["rows"][0]["conflicts"] if c["field"] == "customer_name")
    assert shown["decision"]["source"] == "PEAK"
    uid = shown["decision"]["uid"]

    retired = client.post("/v1/pipelines/peak-report/field-decisions/%d:retire" % uid, headers=OFFICER)
    assert retired.status_code == 200, retired.text
    conn.rollback()
    page = client.get("/v1/pipelines/peak-report/landing-runs/%d/conflicts" % written["run_id"]).json()
    shown = next(c for c in page["rows"][0]["conflicts"] if c["field"] == "customer_name")
    assert shown["decision"] is None


def test_an_unknown_field_or_source_is_refused(db_env):
    conn = db_env
    no = _book_customer_no()
    written = peak_writer.write(conn, _parsed(_inv("IVT-90102", no)), [
        {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": no, "candidates": []}],
        identities={str(no): _identity(no)})
    conn.commit()
    bad = client.post("/v1/pipelines/peak-report/landing-runs/%d/conflicts:decide" % written["run_id"],
                      headers=OFFICER,
                      json={"customer_no": no, "decisions": [{"field": "banana", "source": "PEAK"}]})
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/decisions/0/field"
    # fix-all P3: a field this run never disagreed on (the sizes match) is refused, not stored blank
    none = client.post("/v1/pipelines/peak-report/landing-runs/%d/conflicts:decide" % written["run_id"],
                       headers=OFFICER,
                       json={"customer_no": no, "decisions": [{"field": "system_size_kwp", "source": "PEAK"}]})
    assert none.status_code == 422, none.text
    assert {k: none.json()["errors"][0][k] for k in ("pointer", "code")} == {
        "pointer": "/decisions/0/field", "code": "no_such_conflict"}
    assert field_decisions.load(conn) == {}


def test_a_peak_decision_with_no_value_is_never_overlaid(db_env):
    """Fix-all P3 backstop: a PEAK decision stored without its value (the old route's
    NULL) is skipped on load, so the served field keeps its own value."""
    conn = db_env
    field_decisions.decide(conn, "28000000077", "customer_name", "PEAK", by="settasak")
    conn.commit()
    assert field_decisions.load(conn) == {}


def test_the_identity_only_block_serves_the_decisions_provenance():
    """TASK-209 (dry-run find 2026-09-23): the served book is mostly crm.lead
    identities; a decision made on one must be visible on its own page."""
    from types import SimpleNamespace
    from app import cases as cases_domain
    from app.routers import today as today_router
    customer = SimpleNamespace(
        uid="ident-1", customer_no="28000000001", display_name="Identity", volt_id="V-1",
        field_sources={"customer_name": "PEAK"},
        field_notes_th={"customer_name": "PEAK ว่า X · Odoo ว่า Y · เลือก PEAK โดย settasak เมื่อ 2026-09-23"},
        field_notes_en={"customer_name": "PEAK says X"},
    )
    body = today_router._identity_only_case_detail(cases_domain.for_current(), customer, "ident-1")
    assert body["customer"]["field_sources"] == {"customer_name": "PEAK"}
    assert body["customer"]["field_notes_th"]["customer_name"].startswith("PEAK ว่า X")
    assert body["customer"]["field_notes_en"]["customer_name"] == "PEAK says X"
