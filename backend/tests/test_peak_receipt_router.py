"""The PEAK receipt door (feedback-r2 TASK-203/204/205, Q6).

The same doors, review list and apply as the invoice report, over its own table and
its own last-applied. Every test here is an ADDITION; the DB-backed ones follow
test_peak_router.py's own fixture pattern.
"""
import urllib.parse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db, journey, migrate
from app.book import SHEET
from app.main import app
from app.pipelines import peak_links, peak_service, peak_writer, runs
from tests.test_peak_receipt import FILENAME, _line, _report

client = TestClient(app)
MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


@pytest.fixture(autouse=True)
def clean_runs():
    runs.reset()
    yield
    runs.reset()


def _book_customer_no():
    return next(c.customer_no for c in journey.book_customers() if c.data_source == SHEET and c.contracts)


def _two_book_customer_nos():
    nos = []
    for c in journey.book_customers():
        if c.data_source == SHEET and c.contracts and c.customer_no not in nos:
            nos.append(c.customer_no)
    return nos[0], nos[1]


def _inv(doc, code, status="AWAITING"):
    return {"doc_no": doc, "doc_kind": doc.split("-")[0], "issued_on": "2026-07-11", "due_on": "2026-07-18",
            "reference": code, "system_reference": None, "contact_code": code, "customer_name": "Someone",
            "tax_id_13": "1234567890121", "status": status, "cycle": {"n": 16, "of": 84},
            "product_group": "Solar Leasing", "amount_total": "8399.00", "amount_due": "8399.00",
            "amount_awaiting": "8399.00", "payment": None, "note": None,
            "lines": [{"line_no": 1, "product_code": "P00004", "description": "Installment_M16/84",
                       "amount": "8399.00"}]}


def _exact(no, rule="CUSTOMER_NO"):
    return {"verdict": "EXACT", "rule": rule, "customer_no": no, "candidates": []}


def _parsed(*invoices):
    return {"report_as_of": "2026-09-14", "header_row": 10, "lines": [], "rejected": [], "invoices": list(invoices)}


def _rec(doc, ref=None, code=None, status="PAID", paid_on="2026-09-16"):
    return {"doc_no": doc, "doc_kind": doc.split("-")[0], "issued_on": "2026-09-16",
            "invoice_ref": ref, "journal_ref": None, "contact_code": code,
            "customer_name": "Somchai Tamdee", "tax_id_13": "123", "status": status,
            "cycle_n": 16, "cycle_of": 84, "amount_total": "8399.00", "amount_due": "8399.00",
            "paid_on": paid_on, "channel_code": "BNK-1", "paid_channel": "Beam 0001",
            "paid_amount": "8399.00", "note": None, "lines": []}


def _parsed_receipts(*receipts):
    return {"receipts": list(receipts),
            "meta": {"report_as_of": "2026-09-16", "covers_from": "2024-01-01", "covers_to": "2026-09-16",
                     "read": len(receipts), "rejected": []}}


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


def test_a_receipt_run_matches_its_invoice_and_the_book_reads_it_paid(db_env):
    conn = db_env
    no = _book_customer_no()
    invoice = peak_writer.write(conn, _parsed(_inv("IVT-90050", no)), [_exact(no)],
                                door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    peak_writer.apply_run(conn, invoice["run_id"], by="test")
    conn.commit()

    raw = _report([_line(**{"อ้างอิง": "IVT-90050", "อ้างอิงจากระบบ": "IVT-90050",
                            "รหัสผู้ติดต่อ": no})])
    run = peak_service.run_receipt_upload(raw, FILENAME)
    assert run["state"] == "done", run.get("problem")
    assert run["matched"] == 1 and run["receipts"] == 1
    row = conn.execute(text(
        "select verdict, rule, customer_no, invoice_doc_no, paid_amount, paid_on "
        "from landing.peak_receipt")).one()
    assert row[0] == "EXACT" and row[1] == "INVOICE_REF_AND_CUSTOMER" and row[2] == no
    assert row[3] == "IVT-90050" and str(row[4]) == "8399.00" and str(row[5]) == "2026-09-16"
    # the 13-digit id is never a stored column
    cols = [c[0] for c in conn.execute(text(
        "select column_name from information_schema.columns where table_schema='landing' "
        "and table_name='peak_receipt'")).all()]
    assert "tax_id_13" not in cols

    peak_writer.apply_receipt_run(conn, run["run_id"], by="test")
    conn.commit()
    block = peak_writer.invoices_for_book(conn)[no]
    served = next(i for i in block["invoices"] if i["doc_no"] == "IVT-90050")
    assert served["status"] == "PAID" and served["amount_awaiting"] == "0.00"
    assert served["receipt_no"] == "RE-20260900001"
    assert served["payment_source"] == "PEAK_RECEIPT"
    assert served["paid_on"] == "2026-09-16" and served["paid_amount"] == "8399.00"


def test_an_ambiguous_identity_lands_as_a_reviewable_candidate(db_env, monkeypatch):
    from app.pipelines import peak_match

    conn = db_env
    invoice_customer, proposed_customer = _two_book_customer_nos()
    invoice = peak_writer.write(
        conn, _parsed(_inv("IVT-AMBIGUOUS", invoice_customer)), [_exact(invoice_customer)],
        door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    peak_writer.apply_run(conn, invoice["run_id"], by="test")
    conn.commit()
    monkeypatch.setattr(peak_match, "match_one", lambda *_a, **_k: {
        "verdict": "CANDIDATE", "rule": None, "customer_no": None,
        "candidates": [{"customer_no": proposed_customer, "rule": "NAME", "code": "proposal"}],
    })

    raw = _report([_line(**{"อ้างอิง": "IVT-AMBIGUOUS", "อ้างอิงจากระบบ": "IVT-AMBIGUOUS"})])
    run = peak_service.run_receipt_upload(raw, FILENAME)

    assert run["state"] == "done", run.get("problem")
    assert run["candidates"] == 1
    page = peak_writer.receipt_rows(conn, run["run_id"], verdict="CANDIDATE")
    assert page["total"] == 1
    assert page["rows"][0]["candidates"] == [
        {"customer_no": invoice_customer, "rule": "INVOICE_REF_CUSTOMER", "code": "IVT-AMBIGUOUS"},
        {"customer_no": proposed_customer, "rule": "NAME", "code": "proposal"},
    ]


def test_a_receipt_without_its_invoice_rides_as_receipt_only(db_env):
    conn = db_env
    no = _book_customer_no()
    # no applied invoice run at all: the contact code still finds the customer
    written = peak_writer.write_receipts(conn, _parsed_receipts(_rec("RE-20260900077", code=no)),
                                         [_exact(no)], door="upload",
                                         filename="receipt_export_as_of_20240101_20260916.xlsx")
    conn.commit()
    peak_writer.apply_receipt_run(conn, written["run_id"], by="test")
    conn.commit()
    block = peak_writer.invoices_for_book(conn)[no]
    only = next(i for i in block["invoices"] if i["doc_no"] == "RE-20260900077")
    assert only["receipt_only"] is True and only["status"] == "PAID"
    assert only["note_th"] == peak_writer.RECEIPT_ONLY_TH
    assert only["payment"]["receipt_no"] == "RE-20260900077"
    assert block["report_as_of"] == "2026-09-16"


def _by_ref(no, ref):
    return {"verdict": "EXACT", "rule": "INVOICE_REF", "customer_no": no, "invoice_doc_no": ref, "candidates": []}


def test_two_receipts_on_one_invoice_are_both_carried_and_summed(db_env):
    """Fix-all P2 (F3): the first receipt per invoice won and the second vanished."""
    conn = db_env
    no = _book_customer_no()
    invoice = peak_writer.write(conn, _parsed(_inv("IVT-90051", no)), [_exact(no)],
                                door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    peak_writer.apply_run(conn, invoice["run_id"], by="test")
    conn.commit()
    later = dict(_rec("RE-20260900082", ref="IVT-90051", paid_on="2026-09-18"), paid_amount="5399.00")
    first = dict(_rec("RE-20260900081", ref="IVT-90051", paid_on="2026-09-16"), paid_amount="3000.00")
    written = peak_writer.write_receipts(conn, _parsed_receipts(later, first),
                                         [_by_ref(no, "IVT-90051"), _by_ref(no, "IVT-90051")], door="upload",
                                         filename="receipt_export_as_of_20240101_20260918.xlsx")
    conn.commit()
    peak_writer.apply_receipt_run(conn, written["run_id"], by="test")
    conn.commit()
    served = next(i for i in peak_writer.invoices_for_book(conn)[no]["invoices"] if i["doc_no"] == "IVT-90051")
    assert [(p["receipt_no"], p["amount"]) for p in served["payments"]] == [
        ("RE-20260900081", "3000.00"), ("RE-20260900082", "5399.00")]
    assert (served["status"], served["amount_awaiting"], served["paid_amount"]) == ("PAID", "0.00", "8399.00")
    assert served["payment"]["receipt_no"] == served["receipt_no"] == "RE-20260900082"
    assert served["paid_on"] == "2026-09-18"


def test_the_reports_own_payment_stays_when_the_receipt_run_does_not_carry_it(db_env):
    """Fix-all P2 (audit): 'never both' dropped the invoice report's own payment whenever
    the receipt run held other receipts for that invoice, so a run starting later than
    the report lost money the report saw. The run's receipts and the report's own payment
    are one list, told apart by receipt number, each minted with its own source."""
    import datetime
    conn = db_env
    no = _book_customer_no()
    own = {"on": "2026-08-01", "channel": "Beam", "amount": "300.00", "receipt_no": "RE-20260800083"}
    invoice = peak_writer.write(conn, _parsed(dict(_inv("IVT-90056", no), amount_total="1000.00", amount_due="1000.00",
                                                   amount_awaiting="700.00", payment=own)),
                                [_exact(no)], door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    peak_writer.apply_run(conn, invoice["run_id"], by="test")
    conn.commit()
    later = dict(_rec("RE-20260900084", ref="IVT-90056", paid_on="2026-09-10"), paid_amount="200.00")
    written = peak_writer.write_receipts(conn, _parsed_receipts(later), [_by_ref(no, "IVT-90056")], door="upload",
                                         filename="receipt_export_as_of_20260901_20260918.xlsx")
    conn.commit()
    peak_writer.apply_receipt_run(conn, written["run_id"], by="test")
    conn.commit()
    block = peak_writer.invoices_for_book(conn)[no]
    served = next(i for i in block["invoices"] if i["doc_no"] == "IVT-90056")
    assert [(p["receipt_no"], p["amount"], p["source"]) for p in served["payments"]] == [
        ("RE-20260800083", "300.00", "PEAK_REPORT"), ("RE-20260900084", "200.00", "PEAK_RECEIPT")]
    assert (served["status"], served["paid_amount"], served["amount_awaiting"]) == ("AWAITING", "500.00", "500.00")
    customer = next(c for c in journey.book_customers() if c.customer_no == no)
    state = journey.JourneyState()
    journey._seed_peak_invoices(state, customer, block, datetime.date(2026, 9, 24))
    assert sorted((r["ref"], r["source"], r["amount"]) for r in state.receipts.values()
                  if r["ref"] in ("RE-20260800083", "RE-20260900084")) == [
        ("RE-20260800083", "PEAK_REPORT", "300.00"), ("RE-20260900084", "PEAK_RECEIPT", "200.00")]


def test_a_receipt_whose_invoice_arrives_in_a_later_run_is_served_once(db_env):
    """Fix-all P2 (F2): a receipt matched by contact code before its invoice was in any
    applied run was served on the invoice AND again as receipt_only once it was."""
    conn = db_env
    no = _book_customer_no()
    written = peak_writer.write_receipts(conn, _parsed_receipts(_rec("RE-20260900085", ref="IVT-90055", code=no)),
                                         [_exact(no)], door="upload",
                                         filename="receipt_export_as_of_20240101_20260916.xlsx")
    conn.commit()
    peak_writer.apply_receipt_run(conn, written["run_id"], by="test")
    conn.commit()
    alone = peak_writer.invoices_for_book(conn)[no]["invoices"]
    assert [(i["doc_no"], i.get("receipt_only")) for i in alone] == [("RE-20260900085", True)]

    invoice = peak_writer.write(conn, _parsed(_inv("IVT-90055", no)), [_exact(no)],
                                door="upload", filename="export_as_of_20240101_20260920.xlsx")
    conn.commit()
    peak_writer.apply_run(conn, invoice["run_id"], by="test")
    conn.commit()
    block = peak_writer.invoices_for_book(conn)[no]["invoices"]
    carrying = [i["doc_no"] for i in block for p in i["payments"] if p["receipt_no"] == "RE-20260900085"]
    assert carrying == ["IVT-90055"]
    assert not any(i.get("receipt_only") for i in block)


def test_a_narrower_receipt_report_is_refused_and_a_same_day_re_export_applies(db_env):
    """Fix-all P4: a receipt report reaching back less far un-paid the invoices in between
    (F5), and a same-day re-export with new receipts could never be applied (F9)."""
    conn = db_env
    no = _book_customer_no()

    def stage(doc, filename, fingerprint):
        run_id = peak_writer.write_receipts(conn, _parsed_receipts(_rec(doc, code=no)), [_exact(no)], door="upload",
                                            filename=filename, fingerprint=fingerprint)["run_id"]
        conn.commit()
        return run_id

    wide = "receipt_export_as_of_20240101_20260916_20260916_090000.xlsx"
    peak_writer.apply_receipt_run(conn, stage("RE-20260900091", wide, "bytes-0900"), by="test")
    conn.commit()
    narrow = stage("RE-20260900092", "receipt_export_as_of_20260901_20260916_20260916_100000.xlsx", "bytes-1000")
    refused = client.post("/v1/pipelines/peak-receipt/landing-runs/%d:apply" % narrow, json={}, headers=OFFICER)
    assert refused.status_code == 409 and refused.json()["code"] == "receipt_range_narrower"
    # the receipt card's own words: export again from the same start date, not the older-report tick
    assert "ส่งออกรายงานใบเสร็จใหม่ตั้งแต่วันที่ 2024-01-01" in refused.json()["message_th"]
    assert "export the receipt report again from 2024-01-01" in refused.json()["detail"]
    assert "tick" not in refused.json()["title"]
    conn.rollback()
    same_file = stage("RE-20260900093", wide, "bytes-0900")
    with pytest.raises(peak_writer.WriterRefused) as exc:
        peak_writer.apply_receipt_run(conn, same_file, by="test")
    assert exc.value.code == "report_already_applied"
    conn.rollback()
    re_export = stage("RE-20260900094", "receipt_export_as_of_20240101_20260916_20260916_160000.xlsx", "bytes-1600")
    applied = peak_writer.apply_receipt_run(conn, re_export, by="test")
    conn.commit()
    assert applied["id"] == re_export
    assert peak_writer.last_run(conn, applied=True, source=peak_writer.RECEIPT_SOURCE)["id"] == re_export


def _served_receipts(conn, no):
    return [i["doc_no"] for i in peak_writer.invoices_for_book(conn).get(no, {}).get("invoices", [])]


def test_the_register_decides_a_receipts_customer_at_read_time_both_ways(db_env):
    """Fix-all P10a (M2, audit): a receipt's match was frozen when its run was written,
    and a first fix rewrote the landing rows on confirm — which a retire never undid. The
    register is read when the book is: confirming serves the receipt, retiring takes it
    back, re-pointing moves it, and the landed row is never rewritten."""
    conn = db_env
    a, b = _two_book_customer_nos()
    unmatched = {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}
    written = peak_writer.write_receipts(
        conn, _parsed_receipts(_rec("RE-20260900096", code="C 0990"), _rec("RE-20260900097", code="C0991")),
        [unmatched, unmatched], door="upload", filename="receipt_export_as_of_20240101_20260916.xlsx")
    conn.commit()
    peak_writer.apply_receipt_run(conn, written["run_id"], by="test")
    conn.commit()
    assert _served_receipts(conn, a) == []

    r = client.post("/v1/pipelines/peak-report/links", json={"contact_code": "c0990", "customer_no": a},
                    headers=OFFICER)
    assert r.status_code == 201, r.text
    conn.commit()
    assert _served_receipts(conn, a) == ["RE-20260900096"]
    listed = client.get("/v1/pipelines/peak-receipt/landing-runs/%d/rows" % written["run_id"],
                        params={"verdict": "UNMATCHED"}).json()["rows"]
    assert {row["doc_no"]: row["linked_no"] for row in listed} == {"RE-20260900096": a, "RE-20260900097": None}
    conn.rollback()

    r = client.post("/v1/pipelines/peak-report/links", json={"contact_code": "C0990", "customer_no": b},
                    headers=MANAGER)
    assert r.status_code == 201, r.text
    conn.commit()
    assert (_served_receipts(conn, a), _served_receipts(conn, b)) == ([], ["RE-20260900096"])

    r = client.post("/v1/pipelines/peak-report/links/%d:retire" % r.json()["link"]["uid"], json={}, headers=MANAGER)
    assert r.status_code == 200, r.text
    conn.commit()
    assert (_served_receipts(conn, a), _served_receipts(conn, b)) == ([], [])
    assert conn.execute(text("select verdict, rule, customer_no from landing.peak_receipt "
                             "where doc_no = 'RE-20260900096'")).one() == ("UNMATCHED", None, None)


def test_a_link_confirmed_while_a_receipt_run_is_staged_reaches_it_once_applied(db_env):
    conn = db_env
    no = _book_customer_no()
    unmatched = {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}
    written = peak_writer.write_receipts(conn, _parsed_receipts(_rec("RE-20260900098", code="C0992")), [unmatched],
                                         door="upload", filename="receipt_export_as_of_20240101_20260916.xlsx")
    conn.commit()
    peak_links.confirm(conn, "C0992", no, by="settasak")
    conn.commit()
    peak_writer.apply_receipt_run(conn, written["run_id"], by="test")
    conn.commit()
    assert _served_receipts(conn, no) == ["RE-20260900098"]


def test_the_door_starts_a_watchable_run_and_serves_its_review_rows(db_env):
    conn = db_env
    no = _book_customer_no()
    written = peak_writer.write_receipts(conn, _parsed_receipts(_rec("RE-20260900078", code=no)),
                                         [_exact(no)], door="upload", filename=FILENAME)
    conn.commit()

    started = client.post("/v1/pipelines/peak-receipt:start", content=_report([_line()]),
                          headers={**OFFICER, "X-Volt-Filename": urllib.parse.quote(FILENAME), "Content-Type": "application/octet-stream"})
    assert started.status_code == 202 and started.json()["uid"]
    last = client.get("/v1/pipelines/peak-receipt/last-run")
    assert last.status_code == 200
    assert set(last.json()) >= {"staged", "applied", "watch"}
    rows = client.get("/v1/pipelines/peak-receipt/landing-runs/%d/rows" % written["run_id"])
    assert rows.status_code == 200
    assert rows.json()["total"] == 1 and rows.json()["rows"][0]["doc_no"] == "RE-20260900078"
    unknown = client.get("/v1/pipelines/peak-receipt/runs/nope")
    assert unknown.status_code == 404


def test_receipt_rows_normalise_legacy_string_candidates(db_env):
    """Historical JSON strings remain actionable after candidates become objects."""
    conn = db_env
    legacy = {"verdict": "CANDIDATE", "rule": "INVOICE_NOT_FOUND",
              "customer_no": None, "invoice_doc_no": None, "candidates": ["CUST-A"]}
    written = peak_writer.write_receipts(
        conn, _parsed_receipts(_rec("RE-LEGACY", code="CUST-A")), [legacy],
        door="upload", filename=FILENAME)
    conn.commit()

    response = client.get(
        "/v1/pipelines/peak-receipt/landing-runs/%d/rows" % written["run_id"],
        params={"verdict": "CANDIDATE"})

    assert response.status_code == 200
    assert response.json()["rows"][0]["candidates"] == [
        {"customer_no": "CUST-A", "rule": None, "code": None},
    ]


def test_applying_through_the_door_serves_and_a_second_apply_is_a_409(db_env):
    conn = db_env
    no = _book_customer_no()
    written = peak_writer.write_receipts(conn, _parsed_receipts(_rec("RE-20260900079", code=no)),
                                         [_exact(no)], door="upload",
                                         filename="receipt_export_as_of_20240101_20260916.xlsx")
    conn.commit()
    first = client.post("/v1/pipelines/peak-receipt/landing-runs/%d:apply" % written["run_id"],
                        json={}, headers=OFFICER)
    assert first.status_code == 200, first.text
    assert first.json()["served"] is True
    assert first.json()["reconciliation"]["exceptions"] == 1
    exceptions = client.get("/v1/payment-reconciliation/exceptions").json()["exceptions"]
    exception = next(row for row in exceptions
                     if row.get("receipt_doc_no") == "RE-20260900079")
    assert exception["kind"] == "RECEIPT"
    assert exception["reason"] == "MISSING_INVOICE_REFERENCE"
    assert peak_writer.last_run(conn, applied=True, source=peak_writer.RECEIPT_SOURCE)["id"] == written["run_id"]
    again = client.post("/v1/pipelines/peak-receipt/landing-runs/%d:apply" % written["run_id"],
                        json={}, headers=OFFICER)
    assert again.status_code == 409 and again.json()["code"] == "already_applied"


def test_the_overview_carries_the_receipt_last_run(db_env):
    body = client.get("/v1/data-sources/overview").json()
    assert "receipt" in body["peak"] and "last" in body["peak"]["receipt"]


def test_a_receipt_matched_to_an_invoice_no_longer_served_still_reaches_the_book(db_env):
    """2026-09-25: a receipt the receipt run settled on an invoice (rule 1) was skipped
    whenever that invoice is not served now — a newer invoice report without it, or no
    applied report — and the payment vanished from the book. It rides as receipt_only."""
    conn = db_env
    no = _book_customer_no()
    written = peak_writer.write_receipts(conn, _parsed_receipts(_rec("RE-20260900091", ref="IVT-99991", code=no)),
                                         [_by_ref(no, "IVT-99991")], door="upload",
                                         filename="receipt_export_as_of_20240101_20260916.xlsx")
    conn.commit()
    peak_writer.apply_receipt_run(conn, written["run_id"], by="test")
    conn.commit()
    block = peak_writer.invoices_for_book(conn)[no]
    only = next(i for i in block["invoices"] if i["doc_no"] == "RE-20260900091")
    assert only["receipt_only"] is True and only["payment"]["receipt_no"] == "RE-20260900091"
