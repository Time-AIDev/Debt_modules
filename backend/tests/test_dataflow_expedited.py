"""Upload, export chronology and durable retry boundary regressions."""
import io
import json
import zipfile

import httpx
from sqlalchemy import text

from app import db, imports, migrate, payment_claims, worker
from app.pipelines import service
from tests.test_round5_data_flow import _xlsx_bytes_multi


def test_formatted_columns_and_error_only_templates_do_not_consume_kept_budget(monkeypatch):
    monkeypatch.setenv("XLSX_MAX_KEPT_CELLS", "3")
    original = _xlsx_bytes_multi([("data", [["identity", "", "0"]])])
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            raw = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                raw = raw.replace(b"</row>", b'<c r="XFD1" s="0"/></row>')
                raw = raw.replace(b"</sheetData>",
                    b'<row r="8"><c r="A8" t="e"><v>#N/A</v></c></row></sheetData>')
            target.writestr(info, raw)
    parsed = imports.read_xlsx(output.getvalue())[0]
    assert parsed["rows"] == [["identity", "", "0"]]
    assert parsed["row_numbers"] == [1]


def test_export_observation_caps_missing_payment_evidence():
    base = {"covers_from": "2026-01-01", "covers_to": "2026-12-31",
            "exported_at": "2026-09-30T16:50:15", "report_as_of": "2026-12-31"}
    assert payment_claims.effective_receipt_coverage(base) == ("2026-01-01", "2026-09-30")
    assert payment_claims.effective_receipt_coverage(dict(base, covers_to="2026-08-31")) == (
        "2026-01-01", "2026-08-31")
    assert payment_claims.effective_receipt_coverage(dict(base, covers_from="2026-10-01")) == (None, None)
    assert payment_claims.effective_receipt_coverage({"covers_from": "2026-01-01",
        "covers_to": "2026-12-31"}) == (None, None)


def test_transient_odoo_transport_failure_has_worker_retry_policy():
    request = httpx.Request("POST", "https://synthetic.example/jsonrpc")
    for code, transient in ((503, True), (429, True), (401, False)):
        problem, _ = service._failure(httpx.HTTPStatusError("synthetic", request=request,
            response=httpx.Response(code, request=request)))
        assert problem["retryable"] is transient
        assert problem["status"] == (503 if transient else 422)


def test_retry_reopens_only_uncommitted_transient_runs(pg_conn, pg_url, monkeypatch):
    migrate.apply(pg_conn)
    for uid, committed, retryable in (("transient", False, True), ("committed", True, True),
                                      ("invalid-file", False, False)):
        payload = {"state": "failed", "phase": "failed", "committed": committed,
                   "finished_at": 1, "cancel_requested_at": None,
                   "problem": {"code": "test", "status": 503, "retryable": retryable}}
        pg_conn.execute(text("insert into app.operation_run(uid,payload) values(:u,cast(:p as jsonb))"),
                        {"u": uid, "p": json.dumps(payload)})
        pg_conn.execute(text("insert into app.task_outbox(uid,payload) values(:u,'{}')"), {"u": uid})
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        for uid in ("transient", "committed", "invalid-file"):
            worker._retry(uid, "transport", 5)
        pg_conn.rollback()
        rows = dict(pg_conn.execute(text("select uid,payload from app.operation_run")).all())
        assert rows["transient"]["state"] == "queued"
        assert rows["transient"]["last_attempt_problem"]["retryable"] is True
        assert rows["transient"]["problem"] is None
        assert rows["committed"]["state"] == rows["invalid-file"]["state"] == "failed"
    finally:
        db.reset()


def test_future_claim_remains_pending_after_older_export(financial_db):
    # Defined with the existing financial DB seam below to exercise actual SQL.
    from tests.test_payment_integrity import _claim_row, _invoice_row, _run
    conn = financial_db
    invoice = _run(conn, "PEAK", "2026-09-14")
    _invoice_row(conn, invoice, outstanding="100.00")
    receipt = _run(conn, "PEAK_RECEIPT", "2026-09-30", "2026-09-30T16:50:15")
    conn.execute(text("update landing.import_run set meta=meta || "
                      "'{\"covers_from\":\"2026-01-01\",\"covers_to\":\"2026-12-31\"}'::jsonb where id=:r"),
                 {"r": receipt})
    _claim_row(conn, "before-export", "2026-09-29")
    _claim_row(conn, "after-export", "2026-10-08")
    payment_claims.reconcile_applied(conn, receipt)
    states = dict(conn.execute(text("select uid,state from records.payment_claim")).all())
    assert states == {"before-export": "NEEDS_REVIEW", "after-export": "PENDING"}


from tests.test_payment_integrity import financial_db  # noqa: E402,F401
