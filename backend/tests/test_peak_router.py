"""The PEAK report endpoints: Manager-only writes, honest about the database, and
the same (200, 503) latitude test_pipeline_router.py already takes.

Controller ruling 1 (2026-09-15): the run registry's finished state is "done", and a
finished run's result fields are merged at the TOP LEVEL of the run view
(backend/app/pipelines/runs.py:48-54) — there is no "finished" state and no nested
"result" key. The 200 branch below asserts state == "done" and invoices == 1 at the
top level, not body["result"]["invoices"].
"""
import urllib.parse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db, journey, migrate, xlsx_writer
from app import peak_documents as pkd
from app.book import SHEET
from app.config import settings
from app.main import app
from app.pipelines import field_decisions, peak_links, peak_report, peak_writer
from app.routers import peak_pipeline
from tests.test_peak_report import _line, _report, FILENAME, HEADER

client = TestClient(app)
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}
BD = settings.business_date


# Task 4, Ruling 5: Arina chose "open all four" — an OFFICER may run/start, apply,
# confirm a link and retire a link. Only allow_older and the api door stay Manager's.
#
# Order matters here: both apply and confirm_link end in _served() -> _after_apply()
# -> main.reload_book(), which rebuilds journey.book_customers() from book_source
# rather than the small fixture fresh_app_state seeded for this test — under test
# conditions that reload leaves NO SHEET customer with contracts at all, so
# `_book_customer_no()` raises StopIteration if it is drawn again afterward (this
# is also why test_confirming_then_retiring_a_link_through_the_router_moves_the_
# served_customer, above, applies through peak_writer directly instead of the HTTP
# route). Confirm-link is done FIRST, on the ORIGINAL `no`, before anything reloads
# the book; the run+apply that follow never call journey.book_customers() at all
# (the write below hands its verdict a customer_no directly), so the reload triggered
# by confirm_link cannot touch them.
def test_an_officer_may_run_and_apply_and_link(db_env):
    conn = db_env
    no = _book_customer_no()

    r = client.post("/v1/pipelines/peak-report/links",
                    json={"contact_code": "VC-OFFICER-TEST", "customer_no": no}, headers=OFFICER)
    assert r.status_code == 201, r.text
    conn.commit()   # the shared fixture connection; see the confirm→retire test above

    r = client.post("/v1/pipelines/peak-report:run", content=_report([_line()]),
                    headers={**OFFICER, "X-Volt-Filename": FILENAME_HEADER, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "done"
    conn.commit()

    result = peak_writer.write(conn, _parsed(_inv("IVT-90030", no)), [_exact(no)],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    r = client.post("/v1/pipelines/peak-report/landing-runs/%d:apply" % result["run_id"], json={}, headers=OFFICER)
    assert r.status_code == 200, r.text


def test_an_empty_body_is_a_validation_problem():
    r = client.post("/v1/pipelines/peak-report:run", content=b"", headers={**MANAGER, "X-Volt-Filename": "x.xlsx"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "required"


def test_schema_contract_is_served_for_both_peak_report_types():
    r = client.get("/v1/pipelines/peak-report/schemas")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"invoice", "receipt"}
    assert {field["field"] for field in body["invoice"]["required"]} == {
        "doc_no", "status_th", "amount_awaiting", "due_on",
    }
    assert body["receipt"]["contextual_bindings"]["paid_amount"]["after"] == "วันที่"


# FILENAME (tests/test_peak_report.py) carries Thai text, and httpx 0.28's Headers
# normalisation encodes a str header value as strict ascii (_models.py:82) — passing
# it as a plain str raises UnicodeEncodeError before any request is sent. Encoding it
# to bytes ourselves is the same thing a real client does under the hood; the router
# never asserts on the filename's content, only that the upload runs.
FILENAME_HEADER = FILENAME.encode("utf-8")


def test_a_report_runs_and_the_answer_names_its_counts_or_the_missing_database():
    r = client.post("/v1/pipelines/peak-report:run", content=_report([_line()]),
                    headers={**MANAGER, "X-Volt-Filename": FILENAME_HEADER, "Content-Type": "application/octet-stream"})
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        assert body["state"] == "done" and body["invoices"] == 1
    else:
        assert r.json()["code"] == "database_required"


def test_starting_answers_at_once_with_a_uid_to_watch():
    r = client.post("/v1/pipelines/peak-report:start", content=_report([_line()]),
                    headers={**MANAGER, "X-Volt-Filename": FILENAME_HEADER, "Content-Type": "application/octet-stream"})
    assert r.status_code == 202 and r.json()["uid"]
    assert client.get("/v1/pipelines/peak-report/runs/%s" % r.json()["uid"]).status_code == 200


def test_an_unknown_run_is_a_404():
    assert client.get("/v1/pipelines/peak-report/runs/run-nope").status_code == 404


def test_a_link_needs_a_code_and_a_customer():
    r = client.post("/v1/pipelines/peak-report/links", json={"contact_code": "", "customer_no": ""}, headers=MANAGER)
    assert r.status_code in (422, 503)


# --- I1 (fix round 1): a failed :run is a problem, not a 200 --------------------

def test_an_unreadable_report_is_a_validation_problem_not_a_200():
    """The OLE magic bytes (the same fixture test_peak_service.py's own
    test_an_unreadable_file_fails_with_the_parsers_own_code uses) make
    peak_report.parse raise ReportError("unreadable", ...) before _land is ever
    reached, so this needs no database either way."""
    r = client.post("/v1/pipelines/peak-report:run",
                    content=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x",
                    headers={**MANAGER, "X-Volt-Filename": "old.xls"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "unreadable"


def test_a_report_missing_a_debt_column_is_a_validation_problem_not_a_500():
    header = [h for h in HEADER if h != "มูลค่ารอรับชำระ"]
    line = _line()
    raw = xlsx_writer.workbook([{"name": "รายงานใบแจ้งหนี้",
                                 "rows": [header, [line.get(h, "") for h in header]]}])

    r = client.post("/v1/pipelines/peak-report:run", content=raw,
                    headers={**MANAGER, "X-Volt-Filename": FILENAME_HEADER,
                             "Content-Type": "application/octet-stream"})

    assert r.status_code == 422
    assert r.json()["errors"][0]["code"] == "missing_required_columns"
    assert r.json()["extensions"]["schema"]["missing_required_fields"] == ["amount_awaiting"]


# --- Task 25a: the browser sends encodeURIComponent(file.name); decode before -----
# --- sanitising, so a Thai file name and the report's own "as of" date survive. ---

def test_filename_decodes_percent_encoding_before_sanitising_so_the_as_of_date_survives():
    """The real PEAK export name, sent the way the browser sends it
    (X-Volt-Filename: encodeURIComponent(file.name)) — decoded, the sanitiser must
    keep the whole name (well under the 120-char cap) so report_as_of still reads
    the true date instead of None."""
    header = urllib.parse.quote(FILENAME)
    assert peak_report.report_as_of(peak_pipeline._filename(header)) == "2026-09-14"


def test_filename_leaves_an_ascii_name_unchanged():
    assert peak_pipeline._filename("report.xlsx") == "report.xlsx"


def test_filename_of_a_quoted_traversal_keeps_only_its_last_segment():
    header = urllib.parse.quote("../../etc/passwd", safe="")
    assert peak_pipeline._filename(header) == "passwd"


# --- database-backed tests -------------------------------------------------------
# The pattern test_peak_service.py::test_a_report_runs_end_to_end_against_the_database
# already uses: migrate the schema, point db.configured/db.connect at the fixture's
# own connection, and stop the route's own `conn.close()` from closing it out from
# under the fixture. `records` is outside the schemas conftest's pg_conn truncates
# (deliberately — it must outlive a deploy), so this file cleans its own rows.

def _parsed(*invoices, as_of="2026-09-14"):
    return {"report_as_of": as_of, "header_row": 10, "lines": [], "rejected": [], "invoices": list(invoices)}


def _inv(doc, code):
    return {"doc_no": doc, "doc_kind": doc.split("-")[0], "issued_on": "2026-07-11", "due_on": "2026-07-18",
            "reference": code, "system_reference": None, "contact_code": code, "customer_name": "Someone",
            "tax_id_13": "1234567890121", "status": "PAID", "cycle": None, "product_group": "Solar Leasing",
            "amount_total": "8399.00", "amount_due": "8399.00", "amount_awaiting": "0.00",
            "payment": None, "note": None, "lines": [{"line_no": 1, "product_code": "P00004",
                                                        "description": "Installment_M14/48", "amount": "8399.00"}]}


def _exact(no):
    return {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": no, "candidates": []}


@pytest.fixture
def db_env(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    # migrate.apply leaves the connection in an autobegun transaction; the route's
    # own `with conn.begin():` would otherwise fail on a connection already
    # mid-transaction (same note as test_peak_service.py's e2e test).
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    # the route's own `finally: conn.close()` must not close the fixture's connection.
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        yield pg_conn
    finally:
        pg_conn.execute(text("delete from records.field_decision"))
        pg_conn.execute(text("delete from records.identity_link"))
        pg_conn.commit()


def _book_customer_no():
    return next(c.customer_no for c in journey.book_customers() if c.data_source == SHEET and c.contracts)


def test_apply_serves_the_report_and_says_so(db_env):
    conn = db_env
    no = _book_customer_no()
    result = peak_writer.write(conn, _parsed(_inv("IVT-90010", no)), [_exact(no)],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()

    r = client.post("/v1/pipelines/peak-report/landing-runs/%d:apply" % result["run_id"], json={}, headers=MANAGER)
    assert r.status_code == 200
    body = r.json()
    assert body["served"] is True
    # The monthly status move is the point of the upload, so the apply response
    # reports how many cases it changed (never a number the client would compute).
    assert isinstance(body["moved_cases"], int) and body["moved_cases"] >= 0
    assert peak_writer.last_run(conn, applied=True)["id"] == result["run_id"]


def test_a_failed_reload_after_apply_still_answers_the_committed_apply(db_env, monkeypatch):
    from app import main
    conn = db_env
    no = _book_customer_no()
    result = peak_writer.write(conn, _parsed(_inv("IVT-90011", no)), [_exact(no)],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()

    def _boom():
        raise RuntimeError("reload blew up")
    monkeypatch.setattr(main, "reload_book", _boom)

    r = client.post("/v1/pipelines/peak-report/landing-runs/%d:apply" % result["run_id"], json={}, headers=MANAGER)
    assert r.status_code == 200
    body = r.json()
    assert body["served"] is False
    assert body["note_th"]
    # The write itself committed regardless of the reload failing afterward.
    assert peak_writer.last_run(conn, applied=True)["id"] == result["run_id"]


def test_confirm_link_against_the_database(db_env):
    conn = db_env
    no = _book_customer_no()
    r = client.post("/v1/pipelines/peak-report/links",
                    json={"contact_code": "vc test 001", "customer_no": no}, headers=MANAGER)
    assert r.status_code == 201
    assert peak_links.load(conn)["VCTEST001"]["customer_no"] == no


def test_a_run_uploaded_with_a_percent_encoded_filename_lands_its_true_as_of_date(db_env):
    """Task 25a end to end: the router decodes X-Volt-Filename the way the browser
    sends it, so the landed run's own report_as_of reads the real date instead of
    None (which would later refuse every apply as report_as_of_unknown)."""
    r = client.post("/v1/pipelines/peak-report:run", content=_report([_line()]),
                    headers={**MANAGER, "X-Volt-Filename": urllib.parse.quote(FILENAME),
                             "Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "done" and body["invoices"] == 1
    assert body["report_as_of"] == "2026-09-14"


# --- Task 4, Ruling 5: retiring a link is officer work now (superseding final review I7) --

def test_an_officer_may_retire_a_link(db_env):
    conn = db_env
    no = _book_customer_no()
    link = peak_links.confirm(conn, "VC-OFFICER-RETIRE", no, by="settasak")
    conn.commit()
    r = client.post("/v1/pipelines/peak-report/links/%d:retire" % link["uid"], json={}, headers=OFFICER)
    assert r.status_code == 200, r.text


# --- Final review C1: the register is authoritative at read time, end to end ------

def _two_book_customer_nos():
    nos = []
    for c in journey.book_customers():
        if c.data_source == SHEET and c.contracts and c.customer_no not in nos:
            nos.append(c.customer_no)
        if len(nos) == 2:
            return nos
    raise AssertionError("the fixture book needs two SHEET customers with contracts")


def test_confirming_then_retiring_a_link_through_the_router_moves_the_served_customer(db_env):
    conn = db_env
    a, b = _two_book_customer_nos()
    result = peak_writer.write(conn, _parsed(_inv("IVT-90020", a)), [_exact(a)], ladder=[_exact(a)],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx")
    peak_writer.apply_run(conn, result["run_id"], by="settasak")
    conn.commit()
    assert set(peak_writer.invoices_for_book(conn)) == {a}
    # Every route below shares this ONE fixture connection, and the post-write reload
    # (_after_apply → reload_book) reads through it without closing it the way a real
    # per-request connection would; end that read before the next route's own begin().
    conn.commit()

    r = client.post("/v1/pipelines/peak-report/links",
                    json={"contact_code": a, "customer_no": b, "reason": "the code is the other customer's"},
                    headers=MANAGER)
    assert r.status_code == 201
    conn.commit()
    uid = r.json()["link"]["uid"]
    assert set(peak_writer.invoices_for_book(conn)) == {b}
    listed = client.get("/v1/pipelines/peak-report/links").json()["links"]
    assert [(l["uid"], l["contact_code"], l["customer_no"]) for l in listed] == [(uid, a, b)]
    conn.commit()

    r = client.post("/v1/pipelines/peak-report/links/%d:retire" % uid, json={"reason": "wrong"}, headers=MANAGER)
    assert r.status_code == 200
    conn.commit()
    assert set(peak_writer.invoices_for_book(conn)) == {a}
    assert client.get("/v1/pipelines/peak-report/links").json()["links"] == []


# --- fix-all P5 (F8): a link's defaulted fields leave with the link ------------------

def _apply_through_a_link(conn, code, no, doc):
    """A run matched to `no` by the link on `code`, applied: the name differs, so the
    apply defaults it to PEAK (volt_id differs too, and is never defaulted)."""
    identity = {"name_th": "ชื่อ ในระบบ", "volt_id": "VL0000005_P5", "customer_no": no, "product": "LEASE"}
    result = peak_writer.write(conn, _parsed(_inv(doc, code)), [dict(_exact(no), rule="LINK")],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx",
                               identities={str(no): identity})
    peak_writer.apply_run(conn, result["run_id"], by="settasak")
    conn.commit()
    assert set(field_decisions.load(conn)[no]) == {"customer_name"}


def test_retiring_a_link_takes_back_the_fields_its_apply_defaulted(db_env):
    conn = db_env
    no = _book_customer_no()
    link = peak_links.confirm(conn, "VC-P5-RETIRE", no, by="settasak")
    _apply_through_a_link(conn, "VC-P5-RETIRE", no, "IVT-90041")
    field_decisions.decide(conn, no, "product", "ODOO", by="settasak", reason="checked by hand")
    conn.commit()
    r = client.post("/v1/pipelines/peak-report/links/%d:retire" % link["uid"], json={}, headers=OFFICER)
    assert r.status_code == 200, r.text
    conn.commit()
    assert set(field_decisions.load(conn).get(no, {})) == {"product"}, "a person's own decision stays"


def test_re_pointing_a_link_takes_back_the_fields_its_apply_defaulted(db_env):
    conn = db_env
    a, b = _two_book_customer_nos()
    peak_links.confirm(conn, "VC-P5-MOVE", a, by="settasak")
    _apply_through_a_link(conn, "VC-P5-MOVE", a, "IVT-90042")
    r = client.post("/v1/pipelines/peak-report/links", json={"contact_code": "VC-P5-MOVE", "customer_no": b},
                    headers=MANAGER)
    assert r.status_code == 201, r.text
    conn.commit()
    assert field_decisions.load(conn) == {}


def test_a_link_retired_or_re_pointed_before_the_apply_defaults_nothing(db_env):
    """Fix-all P5 (audit): the apply defaulted fields from stored LINK verdicts whose link
    was retired or re-pointed after the upload — onto a customer the invoice no longer
    belongs to. Only a row the book serves to that customer now is defaulted."""
    conn = db_env
    a, b = _two_book_customer_nos()
    identity = {"name_th": "ชื่อ ในระบบ", "volt_id": "VL0000005_P5", "customer_no": a, "product": "LEASE"}
    gone = peak_links.confirm(conn, "VC-P5-GONE", a, by="settasak")
    peak_links.confirm(conn, "VC-P5-MOVED", a, by="settasak")
    result = peak_writer.write(conn, _parsed(_inv("IVT-90044", "VC-P5-GONE"), _inv("IVT-90045", "VC-P5-MOVED")),
                               [dict(_exact(a), rule="LINK")] * 2, door="upload",
                               filename="export_as_of_20240101_20260914.xlsx", identities={str(a): identity})
    peak_links.retire(conn, gone["uid"], by="settasak")
    peak_links.confirm(conn, "VC-P5-MOVED", b, by="settasak")
    conn.commit()
    assert peak_writer.conflict_rows(conn, result["run_id"]) == []
    assert peak_writer.apply_run(conn, result["run_id"], by="settasak")["defaulted_fields"] == 0
    conn.commit()
    assert field_decisions.load(conn) == {}


def test_retiring_a_link_keeps_a_default_from_the_customers_own_invoice(db_env):
    """Fix-all P5 (audit): a default names the invoice it came from, so a link's retire
    takes back only what that link's rows defaulted, not one from the customer's own."""
    conn = db_env
    no = _book_customer_no()
    identity = {"name_th": "ชื่อ ในระบบ", "volt_id": "VL0000005_P5", "customer_no": no, "product": "LEASE"}
    link = peak_links.confirm(conn, "VC-P5-KEEP", no, by="settasak")
    own = dict(_inv("IVT-90046", no), customer_name="Own Name")
    linked = dict(_inv("IVT-90047", "VC-P5-KEEP"), product_group="Cash")
    result = peak_writer.write(conn, _parsed(own, linked), [_exact(no), dict(_exact(no), rule="LINK")],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx",
                               identities={str(no): identity})
    peak_writer.apply_run(conn, result["run_id"], by="settasak")
    conn.commit()
    assert {f: d["reason"] for f, d in field_decisions.load(conn)[no].items()} == {
        "customer_name": "default PEAK on apply by settasak from IVT-90046",
        "product": "default PEAK on apply by settasak from IVT-90047"}
    peak_links.retire(conn, link["uid"], by="settasak")
    conn.commit()
    kept = field_decisions.load(conn)[no]
    assert set(kept) == {"customer_name"} and kept["customer_name"]["peak_value"] == "Own Name"


# --- fix-all P9 (M6): an apply waits for no one — it refuses while a run holds the lock ---

def test_an_apply_while_another_peak_run_holds_the_lock_is_a_409(db_env, pg_url):
    from tests.test_peak_receipt_router import _parsed_receipts, _rec
    from tests.test_peak_service import _OtherSession
    conn = db_env
    no = _book_customer_no()
    invoices = peak_writer.write(conn, _parsed(_inv("IVT-90043", no)), [_exact(no)],
                                 door="upload", filename="export_as_of_20240101_20260914.xlsx")
    receipts = peak_writer.write_receipts(conn, _parsed_receipts(_rec("RE-20260900095", code=no)), [_exact(no)],
                                          door="upload", filename="receipt_export_as_of_20240101_20260916.xlsx")
    conn.commit()
    with _OtherSession(pg_url):
        for door, run_id in (("peak-report", invoices["run_id"]), ("peak-receipt", receipts["run_id"])):
            r = client.post("/v1/pipelines/%s/landing-runs/%d:apply" % (door, run_id), json={}, headers=OFFICER)
            assert r.status_code == 409 and r.json()["code"] == "peak_run_in_progress", r.text
            assert r.json()["title"] == peak_pipeline._REFUSED_TITLE["peak_run_in_progress"]
    assert peak_writer.last_run(conn, applied=True) is None
    assert peak_writer.last_run(conn, applied=True, source=peak_writer.RECEIPT_SOURCE) is None


# --- Final review I2: re-applying an applied run is a 409 problem -----------------

def test_re_applying_an_applied_run_is_a_409_problem_with_thai(db_env):
    conn = db_env
    no = _book_customer_no()
    result = peak_writer.write(conn, _parsed(_inv("IVT-90021", no)), [_exact(no)],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    url = "/v1/pipelines/peak-report/landing-runs/%d:apply" % result["run_id"]
    assert client.post(url, json={}, headers=MANAGER).status_code == 200
    conn.commit()   # the shared fixture connection; see the confirm→retire test above
    r = client.post(url, json={"allow_older": True}, headers=MANAGER)
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "already_applied" and body["message_th"]


# --- Final review I4: a failed run never serves the exception's own text ----------

def test_a_run_that_dies_answers_a_generic_500_without_the_exceptions_text(monkeypatch):
    from app.pipelines import peak_service

    def _boom(uid, parsed, filename, fingerprint=None):
        raise RuntimeError("secret-name 1234567890121")
    monkeypatch.setattr(peak_service, "_land", _boom)
    r = client.post("/v1/pipelines/peak-report:run", content=_report([_line()]),
                    headers={**MANAGER, "X-Volt-Filename": FILENAME_HEADER, "Content-Type": "application/octet-stream"})
    assert r.status_code == 500
    assert r.json()["code"] == "pipeline_failed"
    assert "RuntimeError" in r.json()["detail"]
    assert "secret-name" not in r.text and "1234567890121" not in r.text


# --- the payments queue's own age (prototype 2038) ----------------------------------

def test_peak_documents_serve_the_business_date_and_each_documents_age():
    """A client cannot compute an honest age from `created_at` alone — it does not
    know the business date — so /v1/peak-documents serves the date in meta and each
    document's `waiting_days` beside its stamp. A queue the store has nothing in is
    served empty; this test seeds nothing to make the screen look full."""
    from datetime import date

    from app.config import settings

    before = client.get("/v1/peak-documents").json()
    assert before["meta"]["business_date"] == str(settings.business_date)
    for d in before["documents"]:
        expected = max(0, (settings.business_date - date.fromisoformat(str(d["created_at"])[:10])).days)
        assert d["waiting_days"] == expected

    invoices = client.get("/v1/ar/pipeline", params={"open_only": "true"}).json()["invoices"]
    assert invoices, "the fixture book has open invoices"
    inv = invoices[0]
    amount = inv.get("amount_to_ask") or inv.get("outstanding") or inv.get("amount")
    assert amount, "an open invoice carries an amount a slip can be confirmed against"
    r = client.post("/v1/slips", json={"invoice_uid": inv["uid"], "amount": str(amount), "slip_ref": "slip-age-check"})
    assert r.status_code in (200, 201), r.json()
    uid = r.json()["peak_document"]["uid"]

    after = client.get("/v1/peak-documents").json()
    assert after["meta"]["business_date"] == str(settings.business_date)
    doc = next(d for d in after["documents"] if d["uid"] == uid)
    # Raised on the business date: the honest age is 0, never a negative or an invented one.
    assert doc["waiting_days"] == 0


# --- Delta-100 PAY-10/11: the allocation block and the state need -------------------

def _an_open_invoice():
    invoices = client.get("/v1/ar/pipeline", params={"open_only": "true"}).json()["invoices"]
    assert invoices, "the fixture book has open invoices"
    return invoices[0]


def _slip_against_open_invoice(slip_ref):
    inv = _an_open_invoice()
    amount = inv.get("amount_to_ask") or inv.get("outstanding") or inv.get("amount")
    r = client.post("/v1/slips", json={"invoice_uid": inv["uid"], "amount": str(amount),
                                       "slip_ref": slip_ref, "by": "thip"})
    assert r.status_code in (200, 201), r.json()
    return r.json()["peak_document"], amount


def test_the_allocation_block_serves_its_three_lines_and_never_invents_one():
    from app.config import settings
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    body = client.get("/v1/peak-documents").json()
    alloc = body["meta"]["allocation"]
    lines = {line["state"]: line for line in alloc["lines"]}
    assert list(lines) == ["ALLOCATED", "NOT_ALLOCATED", "AWAITING_RULING"]
    assert (lines["ALLOCATED"]["label_th"], lines["ALLOCATED"]["label_en"]) == ("จัดสรรแล้ว", "Allocated")
    assert (lines["NOT_ALLOCATED"]["label_th"], lines["NOT_ALLOCATED"]["label_en"]) == ("ยังไม่จัดสรร", "Not allocated yet")
    assert (lines["AWAITING_RULING"]["label_th"], lines["AWAITING_RULING"]["label_en"]) == ("รอคำตัดสิน", "Awaiting the ruling")
    for line in lines.values():
        assert isinstance(line["count"], int) and line["count"] >= 0
        assert line["amount"] is None or line["amount"].count(".") == 1
    # OD-02 is unset in the shipped config, so the awaiting line names the decision
    # and the block says the component order is not set.
    assert settings.allocation_component_order is None
    assert alloc["pending_decision"] == "OD-02"
    assert lines["AWAITING_RULING"]["pending_decision"] == "OD-02"
    assert "ยังไม่ตัดสินลำดับการจัดสรร" in alloc["note_th"]
    assert alloc["note_en"]
    # Every document states its own line and the prototype's payNeed twins.
    for d in body["documents"]:
        assert d["allocation"]["state"] in lines
        assert d["state_need_th"] and d["state_need_en"]
    # A fresh slip is real money the engine refuses to allocate: the awaiting line
    # grows by one and the document's own money lands there with its exact amount.
    doc, amount = _slip_against_open_invoice("alloc-line-check")
    after = client.get("/v1/peak-documents").json()["meta"]["allocation"]
    after_lines = {line["state"]: line for line in after["lines"]}
    assert after_lines["AWAITING_RULING"]["count"] == lines["AWAITING_RULING"]["count"] + 1
    row = next(d for d in client.get("/v1/peak-documents").json()["documents"] if d["uid"] == doc["uid"])
    assert row["state"] == "DRAFT_CREATED"
    assert row["allocation"]["state"] == "AWAITING_RULING"
    assert row["allocation"]["amount"] == str(amount)
    assert row["allocation"]["receipt_uids"]
    assert row["state_need_th"] == "รอ AR อนุมัติใน PEAK"


def test_a_document_with_no_money_yet_is_not_allocated_and_carries_no_amount():
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport(fail_create=True)
    doc, _amount = _slip_against_open_invoice("unsent-alloc-check")
    row = next(d for d in client.get("/v1/peak-documents").json()["documents"] if d["uid"] == doc["uid"])
    assert row["state"] == "UNSENT"
    assert row["allocation"]["state"] == "AWAITING_RULING"   # the money arrived and is blocked on OD-02
    assert row["state_need_th"] and row["state_need_en"]
    # A document with no linked receipt at all has nothing to allocate yet: a
    # standalone credit note drafts a document and no money has arrived against it.
    inv = _an_open_invoice()
    note = client.post("/v1/credit-notes", json={"invoice_uid": inv["uid"], "reason": "alloc check",
                                                 "amount": "100.00"}, headers=MANAGER)
    assert note.status_code == 201, note.text
    row = next(d for d in client.get("/v1/peak-documents").json()["documents"]
               if d["uid"] == note.json()["peak_document"]["uid"])
    assert row["allocation"]["state"] == "NOT_ALLOCATED"
    assert row["allocation"]["amount"] is None
    assert row["allocation"]["receipt_uids"] == []
    assert row["state_need_th"] and row["state_need_en"]


def test_a_document_with_a_customer_serves_a_risk_edge():
    doc, _amount = _slip_against_open_invoice("risk-edge-check")
    row = next(d for d in client.get("/v1/peak-documents").json()["documents"] if d["uid"] == doc["uid"])
    assert isinstance(row["risk_score"], int) and 0 <= row["risk_score"] <= 100


def test_the_allocation_lines_come_from_the_stored_flags_never_a_guess():
    """The peak_report_allocates path (a receipt whose own is_allocated flag is
    true) is the only thing that lands in จัดสรรแล้ว; an OD-02 hold lands in รอคำตัดสิน;
    a record with neither flag is served as not yet allocated. Unit-level because
    those stored combinations cannot all be produced through the HTTP surface."""
    from app.routers import payments
    lines = {line["state"]: line for line in payments._allocation_meta([
        {"uid": "r1", "amount": "100.00", "is_allocated": True},
        {"uid": "r2", "amount": "50.00", "is_allocated": False, "pending_decision": "OD-02"},
        {"uid": "r3", "amount": "25.00", "is_allocated": False},
    ])["lines"]}
    assert (lines["ALLOCATED"]["count"], lines["ALLOCATED"]["amount"]) == (1, "100.00")
    assert (lines["AWAITING_RULING"]["count"], lines["AWAITING_RULING"]["amount"]) == (1, "50.00")
    assert lines["AWAITING_RULING"]["pending_decision"] == "OD-02"
    assert (lines["NOT_ALLOCATED"]["count"], lines["NOT_ALLOCATED"]["amount"]) == (1, "25.00")
    # A document with an allocated linked receipt reads ALLOCATED; no linked receipt
    # reads NOT_ALLOCATED with no amount.
    allocated = payments._document_allocation(
        {"uid": "pkd-1"}, [{"uid": "r1", "amount": "100.00", "is_allocated": True,
                            "peak_document_uid": "pkd-1"}])
    assert allocated["state"] == "ALLOCATED" and allocated["amount"] == "100.00"
    bare = payments._document_allocation({"uid": "pkd-2"}, [])
    assert bare["state"] == "NOT_ALLOCATED" and bare["amount"] is None
    assert bare["receipt_uids"] == []


# --- Delta-100 PAY-12: fix and resubmit ---------------------------------------------

def _a_rejected_document():
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    doc, _amount = _slip_against_open_invoice("resubmit-check")
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport(reject_reason="wrong amount on the draft")
    rejected = client.post("/v1/peak-documents/%s:refresh" % doc["uid"]).json()["document"]
    assert rejected["state"] == "REJECTED"
    return rejected


def test_resubmit_is_manager_gated_and_advances_a_refused_document_to_draft():
    from app import audit_store
    rejected = _a_rejected_document()
    # An OFFICER cannot take the act.
    refused = client.post("/v1/peak-documents/%s/resubmit" % rejected["uid"], headers=OFFICER)
    assert refused.status_code == 403 and refused.json()["message_th"]
    # Only a REFUSED document is resubmitted: the same act on a live draft is a 409.
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport()
    live, _amount = _slip_against_open_invoice("resubmit-live-check")
    conflict = client.post("/v1/peak-documents/%s/resubmit" % live["uid"], headers=MANAGER)
    assert conflict.status_code == 409 and conflict.json()["code"] == "document_state_conflict"
    # Manager + a working transport: the document advances to a fresh draft.
    r = client.post("/v1/peak-documents/%s/resubmit" % rejected["uid"], headers=MANAGER)
    assert r.status_code == 200, r.text
    body = r.json()["document"]
    assert body["state"] == "DRAFT_CREATED"
    assert body["rejection_reason"] is None and body["last_error"] is None
    assert body["resubmitted_by"] == "settasak" and body["resubmitted_at"]
    assert body["state_need_th"] == "รอ AR อนุมัติใน PEAK"
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["act"] == "PEAK_DOCUMENT_RESUBMITTED"
    assert entry["subject_uid"] == rejected["uid"]
    assert entry["actor_role"] == "MANAGER"


def test_resubmit_refuses_with_the_transports_own_reason_and_leaves_the_record_refused():
    rejected = _a_rejected_document()
    pkd.TRANSPORT_OVERRIDE = pkd.StubTransport(fail_create=True)
    r = client.post("/v1/peak-documents/%s/resubmit" % rejected["uid"], headers=MANAGER)
    assert r.status_code == 502
    body = r.json()
    assert body["code"] == "resubmit_transport_failed"
    assert "transport failure" in body["detail"]          # the honest server reason
    assert body["message_th"]
    still = next(d for d in client.get("/v1/peak-documents").json()["documents"]
                 if d["uid"] == rejected["uid"])
    assert still["state"] == "REJECTED"

    class _NoPeak(pkd.StubTransport):
        def create_draft(self, document, instance="EPC"):
            raise pkd.peak_client.NotConfigured(["PEAK_UAT_BASE"])
    pkd.TRANSPORT_OVERRIDE = _NoPeak()
    r = client.post("/v1/peak-documents/%s/resubmit" % rejected["uid"], headers=MANAGER)
    assert r.status_code == 503
    body = r.json()
    assert body["code"] == "resubmit_transport_unavailable"
    assert "not configured" in body["detail"]
    assert body["retryable"] is True
    assert next(d for d in client.get("/v1/peak-documents").json()["documents"]
                if d["uid"] == rejected["uid"])["state"] == "REJECTED"



def test_refresh_served_recovers_a_committed_apply_whose_reload_failed(db_env, monkeypatch):
    """The apply commits and audits before the reload; when the reload failed there
    was no way back (re-apply is 409, re-upload was the only advice). This re-runs
    the idempotent after-apply step for the same run."""
    from app import main

    conn = db_env
    no = _book_customer_no()
    result = peak_writer.write(conn, _parsed(_inv("IVT-90014", no)), [_exact(no)],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    original = main.reload_book
    monkeypatch.setattr(main, "reload_book", lambda: (_ for _ in ()).throw(RuntimeError("reload blew up")))
    applied = client.post("/v1/pipelines/peak-report/landing-runs/%d:apply" % result["run_id"],
                          json={}, headers=MANAGER)
    assert applied.status_code == 200
    assert applied.json()["served"] is False

    monkeypatch.setattr(main, "reload_book", original)
    fixed = client.post("/v1/pipelines/peak-report/landing-runs/%d:refresh-served" % result["run_id"],
                        json={}, headers=MANAGER)
    assert fixed.status_code == 200
    assert fixed.json()["served"] is True


def test_refresh_served_refuses_a_run_that_was_never_applied(db_env):
    conn = db_env
    no = _book_customer_no()
    result = peak_writer.write(conn, _parsed(_inv("IVT-90015", no)), [_exact(no)],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    r = client.post("/v1/pipelines/peak-report/landing-runs/%d:refresh-served" % result["run_id"],
                    json={}, headers=MANAGER)
    assert r.status_code == 409
    assert r.json()["code"] == "run_not_applied"


def test_the_same_report_cannot_be_processed_twice_without_force(db_env):
    conn = db_env
    no = _book_customer_no()
    first = peak_writer.write(conn, _parsed(_inv("IVT-90016", no)), [_exact(no)],
                              door="upload", filename="export_as_of_20240101_20260914.xlsx")
    second = peak_writer.write(conn, _parsed(_inv("IVT-90017", no)), [_exact(no)],
                               door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    assert client.post("/v1/pipelines/peak-report/landing-runs/%d:apply" % first["run_id"],
                       json={}, headers=MANAGER).status_code == 200
    refused = client.post("/v1/pipelines/peak-report/landing-runs/%d:apply" % second["run_id"],
                          json={}, headers=MANAGER)
    assert refused.status_code == 409
    assert refused.json()["code"] == "report_already_applied"
    forced = client.post("/v1/pipelines/peak-report/landing-runs/%d:apply" % second["run_id"],
                         json={"force": True}, headers=MANAGER)
    assert forced.status_code == 200
