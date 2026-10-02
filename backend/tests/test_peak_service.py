"""The PEAK run sequence, once: parse → match → write, every exit through the registry."""
import types

import pytest
from sqlalchemy import text

from app import db, journey, migrate
from app.book import SHEET
from app.pipelines import peak_service, peak_writer, runs
from tests.test_peak_report import _line, _report, FILENAME


@pytest.fixture(autouse=True)
def clean_runs():
    runs.reset()
    yield
    runs.reset()


def test_without_a_database_the_run_fails_honestly_and_says_why(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: False)
    run = peak_service.run_upload(_report([_line()]), FILENAME)
    assert run["state"] == "failed"
    assert run["problem"]["code"] == "database_required"


def test_an_unreadable_file_fails_with_the_parsers_own_code(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: True)
    run = peak_service.run_upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 not really", "old.xls")
    assert run["state"] == "failed" and run["problem"]["code"] == "unreadable"


def test_a_receipt_run_announces_reading_then_matching(monkeypatch):
    from app.pipelines import peak_receipt
    uid = runs.start(peak_service.KIND_RECEIPT)
    seen = []

    def fake_parse(_raw, _filename):
        seen.append(runs.get(uid)["phase"])
        return {"receipts": [{"doc_no": "RE-1"}], "meta": {"read": 1, "rejected": []}}

    def fake_land(run_uid, parsed, filename, fingerprint=None, kind="report", stage_timings=None):
        seen.append(runs.get(run_uid)["phase"])
        return {"run_id": 1, "receipts": len(parsed["receipts"]), "matched": 0,
                "candidates": 0, "unmatched": 1, "rejected": 0,
                "receipt_only": 0, "report_as_of": None, "door": "upload"}

    monkeypatch.setattr(peak_receipt, "parse", fake_parse)
    monkeypatch.setattr(peak_service, "_land", fake_land)

    run = peak_service.run_receipt_upload(b"receipt", "receipt.xlsx", uid)

    assert seen == ["reading", "matching"]
    assert run["phase"] == "done" and (run["read"], run["total"]) == (1, 1)


def test_receipt_matching_reports_each_completed_batch(monkeypatch):
    class Result:
        def mappings(self): return self
        def all(self): return []

    class Conn:
        def execute(self, *_args, **_kwargs): return Result()

    monkeypatch.setattr(peak_writer, "last_run", lambda *_a, **_k: None)
    monkeypatch.setattr(peak_writer, "odoo_phone_rows", lambda _conn: [])
    monkeypatch.setattr(journey, "book_customers", lambda: [])
    monkeypatch.setattr(journey, "identity_customers", lambda: [])
    from app.pipelines import peak_links
    monkeypatch.setattr(peak_links, "load", lambda _conn: {})
    updates = []
    parsed = {"receipts": [{"doc_no": "RE-%s" % i} for i in range(501)]}

    verdicts = peak_service._receipt_verdicts(
        Conn(), parsed, on_progress=lambda processed, total: updates.append((processed, total)))

    assert len(verdicts) == 501
    assert updates == [(500, 501), (501, 501)]


def test_empty_receipt_matching_still_reports_completion(monkeypatch):
    class Result:
        def mappings(self): return self
        def all(self): return []

    class Conn:
        def execute(self, *_args, **_kwargs): return Result()

    monkeypatch.setattr(peak_writer, "last_run", lambda *_a, **_k: None)
    monkeypatch.setattr(peak_writer, "odoo_phone_rows", lambda _conn: [])
    monkeypatch.setattr(journey, "book_customers", lambda: [])
    monkeypatch.setattr(journey, "identity_customers", lambda: [])
    from app.pipelines import peak_links
    monkeypatch.setattr(peak_links, "load", lambda _conn: {})
    updates = []

    verdicts = peak_service._receipt_verdicts(
        Conn(), {"receipts": []},
        on_progress=lambda processed, total: updates.append((processed, total)))

    assert verdicts == []
    assert updates == [(0, 0)]


def test_receipt_landing_announces_writing_before_copy(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    monkeypatch.setattr(peak_service, "_receipt_verdicts",
                        lambda _conn, _parsed, on_progress=None: [])
    uid = runs.start(peak_service.KIND_RECEIPT)
    runs.progress(uid, phase="matching", phase_total=1)
    seen = []

    def fake_write(*_args, **_kwargs):
        seen.append(runs.get(uid)["phase"])
        return {"run_id": 1, "receipts": 1, "matched": 0, "candidates": 0,
                "unmatched": 1, "rejected": 0, "receipt_only": 0,
                "report_as_of": None, "door": "upload"}

    monkeypatch.setattr(peak_writer, "write_receipts", fake_write)

    peak_service._land(uid, {"receipts": [{"doc_no": "RE-1"}], "meta": {}},
                       "receipt.xlsx", kind="receipt")

    assert seen == ["writing"]


def test_a_run_reports_the_parsed_total_before_it_writes(monkeypatch):
    # Ruling 2: the progress bar reads invoices against invoices, never lines
    # against invoices (7,998 lines vs 7,638 invoices would show past 100%).
    # The fixture below is deliberately TWO lines of ONE invoice (the same
    # pattern as test_peak_report.py::test_lines_of_one_invoice_fold_into_one_record)
    # so that len(parsed["lines"]) != len(parsed["invoices"]) — with a single-line
    # fixture the two counts coincide at 1 and the assertions below would pass
    # identically whether run_upload counted lines or invoices.
    seen = []
    captured = {}
    monkeypatch.setattr(db, "configured", lambda: True)

    def fake_land(uid, parsed, filename, fingerprint=None):
        seen.append(uid)
        captured["parsed"] = parsed
        return {"run_id": 1, "invoices": 1, "matched": 1, "candidates": 0, "unmatched": 0, "rejected": 0,
                "report_as_of": "2026-09-14", "door": "upload"}

    monkeypatch.setattr(peak_service, "_land", fake_land)
    raw = _report([_line(), _line(**{"รายการที่": "2", "รหัสสินค้า/บริการ": "P00042",
                                      "ชื่อสินค้า/บริการ": "Late Fee (No VAT)",
                                      "คำอธิบาย": "Late Fee M11", "ราคา": "2,368.52"})])
    run = peak_service.run_upload(raw, FILENAME)
    # Ruling 1: state is "done" (never "finished"), and result fields land at the
    # TOP LEVEL of the run view — never nested under "result".
    assert run["state"] == "done"
    assert run["matched"] == 1
    # Ruling 2: "landed" is the invoices actually written, for the bar's own number.
    assert run["landed"] == 1
    assert seen == [run["uid"]]
    # The fixture provably has more lines than invoices — proving read/total were
    # counted in invoices, not lines.
    assert len(captured["parsed"]["lines"]) == 2
    assert run["read"] == 1 and run["total"] == 1


def test_latest_can_be_asked_for_one_kind():
    a = runs.start("odoo")
    runs.finish(a, {})
    b = runs.start("peak-report")
    runs.finish(b, {})
    assert runs.latest()["uid"] == b
    assert runs.latest(kind="odoo")["uid"] == a
    assert runs.latest(kind="nothing") is None


def test_a_report_runs_end_to_end_against_the_database(pg_conn, monkeypatch):
    """The mocked-`_land` tests above prove the sequencing; this proves the real
    wiring — build_book_index, build_odoo_index, peak_links.load, match and
    peak_writer.write — actually lands a matched invoice in the landing schema."""
    migrate.apply(pg_conn)
    # migrate.apply leaves the connection in an autobegun transaction; _land opens
    # its own `with conn.begin():`, which would otherwise fail on a connection
    # that is already mid-transaction.
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    # _land's `finally: conn.close()` must not close the fixture's own connection.
    monkeypatch.setattr(pg_conn, "close", lambda: None)

    no = next(c.customer_no for c in journey.book_customers() if c.data_source == SHEET and c.contracts)
    raw = _report([_line(**{"รหัสผู้ติดต่อ": no, "อ้างอิง": no})])
    run = peak_service.run_upload(raw, FILENAME)

    assert run["state"] == "done", run.get("problem")
    assert run["matched"] == 1
    assert run["invoices"] == 1
    assert pg_conn.execute(text(
        "select verdict, customer_no from landing.peak_invoice")).all() == [("EXACT", no)]


def test_an_identity_from_the_served_book_is_matched_not_left_unmatched(pg_conn, monkeypatch):
    """The 2026-09-19 ruling serves crm.lead identities, and most PEAK contact codes
    name one of them, not a contract row. The ladder indexes identities beside the
    contract holders, so the invoice lands matched; whether it can move money still
    needs a contract the identity does not have, which is a later ruling."""
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    ident = types.SimpleNamespace(customer_no="99900000001", volt_id="99900000001",
                                  phone_e164=None, display_name="Identity Lead", name_roman=None)
    monkeypatch.setattr(journey, "identity_customers", lambda: [ident])

    run = peak_service.run_upload(_report([_line(**{"รหัสผู้ติดต่อ": "99900000001",
                                                    "อ้างอิง": "99900000001"})]), FILENAME)

    assert run["state"] == "done", run.get("problem")
    assert run["matched"] == 1 and run["unmatched"] == 0
    row = pg_conn.execute(text("select rule, customer_no from landing.peak_invoice")).one()
    assert (row[0], row[1]) == ("CUSTOMER_NO", "99900000001")


def test_a_run_that_dies_serves_and_logs_only_the_exceptions_class(monkeypatch, caplog):
    """Final review I4: `pipeline_failed` forwarded the raw exception text into the
    run view (and from there into :run's 500 and the polled run) — a message can
    carry a customer's name or a 13-digit id. The view says which class failed and
    nothing more; so does the server log."""
    import json
    import logging

    from fastapi.testclient import TestClient
    from app.main import app

    def _boom(uid, parsed, filename, fingerprint=None):
        raise RuntimeError("secret-name 1234567890121")
    monkeypatch.setattr(peak_service, "_land", _boom)
    with caplog.at_level(logging.DEBUG):
        run = peak_service.run_upload(_report([_line()]), FILENAME)
    assert run["state"] == "failed"
    problem = run["problem"]
    assert problem["code"] == "pipeline_failed"
    assert problem["detail"] == "The PEAK report run failed (RuntimeError)"
    assert problem["detail_th"]
    polled = TestClient(app).get("/v1/pipelines/peak-report/runs/%s" % run["uid"])
    assert polled.status_code == 200
    for text_ in (json.dumps(run, ensure_ascii=False), polled.text, caplog.text):
        assert "secret-name" not in text_ and "1234567890121" not in text_
    assert "RuntimeError" in caplog.text


def test_a_receipt_failure_log_names_the_safe_phase_and_application_frame(monkeypatch, caplog):
    import logging
    from app.pipelines import peak_receipt

    def _boom(_raw, _filename):
        raise RuntimeError("private-name 1234567890121")

    monkeypatch.setattr(peak_receipt, "parse", _boom)
    with caplog.at_level(logging.ERROR):
        run = peak_service.run_receipt_upload(b"receipt", "private-name.xlsx")

    assert run["state"] == "failed"
    assert run["problem"]["code"] == "pipeline_failed"
    assert "phase=reading" in caplog.text
    assert "exception_class=RuntimeError" in caplog.text
    assert "failure_location=app.pipelines.peak_service:run_receipt_upload:" in caplog.text
    assert "private-name" not in caplog.text
    assert "1234567890121" not in caplog.text


def test_a_completed_receipt_run_logs_safe_stage_timings(monkeypatch, caplog):
    import logging
    from app.pipelines import peak_receipt

    monkeypatch.setattr(peak_receipt, "parse", lambda *_a: {
        "receipts": [{"doc_no": "RE-1"}], "meta": {"read": 1, "rejected": []},
    })

    def fake_land(_uid, _parsed, _filename, fingerprint=None, kind="report", stage_timings=None):
        stage_timings.update({"matching_ms": 250, "writing_ms": 375})
        return {"run_id": 1, "receipts": 1, "matched": 0, "candidates": 0,
                "unmatched": 1, "rejected": 0, "receipt_only": 0,
                "report_as_of": None, "door": "upload"}

    monkeypatch.setattr(peak_service, "_land", fake_land)
    ticks = iter((10.0, 10.125))
    monkeypatch.setattr(peak_service.time, "perf_counter", lambda: next(ticks))

    with caplog.at_level(logging.INFO):
        run = peak_service.run_receipt_upload(b"receipt", "private-name.xlsx")

    assert run["state"] == "done"
    assert "receipts=1" in caplog.text
    assert "reading_ms=125" in caplog.text
    assert "matching_ms=250" in caplog.text
    assert "writing_ms=375" in caplog.text
    assert "private-name" not in caplog.text


def test_a_run_stores_the_ladders_own_verdict_beside_a_link_verdict(pg_conn, monkeypatch):
    """Final review C1: _land runs the ladder a second time WITHOUT the register and
    the writer stores it per row, so retiring the link later can fall back to it."""
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    from app.pipelines import peak_links

    nos = []
    for c in journey.book_customers():
        if c.data_source == SHEET and c.contracts and c.customer_no not in nos:
            nos.append(c.customer_no)
    no, other = nos[0], nos[1]
    try:
        with pg_conn.begin():
            peak_links.confirm(pg_conn, no, other, by="settasak", reason="test")
        run = peak_service.run_upload(_report([_line(**{"รหัสผู้ติดต่อ": no, "อ้างอิง": no})]), FILENAME)
        assert run["state"] == "done", run.get("problem")
        row = pg_conn.execute(text(
            "select verdict, rule, customer_no, ladder_verdict, ladder_rule, ladder_customer_no, "
            "row_to_json(p)::text as whole from landing.peak_invoice p")).mappings().one()
        assert (row["verdict"], row["rule"], row["customer_no"]) == ("EXACT", "LINK", other)
        assert (row["ladder_verdict"], row["ladder_rule"], row["ladder_customer_no"]) == ("EXACT", "CUSTOMER_NO", no)
        assert "1234567890121" not in row["whole"], "the 13-digit id is never written (F5)"
    finally:
        if pg_conn.in_transaction():
            pg_conn.rollback()
        pg_conn.execute(text("delete from records.identity_link"))
        pg_conn.commit()


def _db_env(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)


def test_a_write_failure_leaves_a_durable_failed_row(pg_conn, monkeypatch):
    """Before 2026-09-20 the run row was opened inside the write's transaction, so a
    failure rolled it back and the only trace died with the process."""
    _db_env(pg_conn, monkeypatch)
    monkeypatch.setattr(peak_writer, "write",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write blew up")))
    run = peak_service.run_upload(_report([_line()]), FILENAME)
    assert run["state"] == "failed"
    row = pg_conn.execute(text(
        "select status, note from landing.import_run where source_system = 'PEAK' "
        "order by id desc limit 1")).first()
    assert row is not None
    assert row[0] == "FAILED"
    assert "RuntimeError" in (row[1] or "")
    # fix-all P6 (K5): the note is served on last-run — a code and the class, never the text
    assert row[1].startswith("pipeline_failed:") and "write blew up" not in row[1]
    # and the screen can read it back, so an old OK receipt cannot look current
    failed = peak_writer.last_failed(pg_conn)
    assert failed is not None
    assert failed["meta"].get("filename") == FILENAME


def test_the_same_file_cannot_be_staged_twice_but_can_be_reapplied_after_use(pg_conn, monkeypatch):
    _db_env(pg_conn, monkeypatch)
    no = next(c.customer_no for c in journey.book_customers() if c.data_source == SHEET and c.contracts)
    raw = _report([_line(**{"รหัสผู้ติดต่อ": no, "อ้างอิง": no})])

    first = peak_service.run_upload(raw, FILENAME)
    assert first["state"] == "done"
    again = peak_service.run_upload(raw, FILENAME)
    assert again["state"] == "failed"
    assert again["problem"]["code"] == "peak_duplicate_report"
    assert again["problem"]["run_id"] == first["run_id"]

    # Once the staged run is applied, the same bytes are the documented re-upload
    # path for re-applying (the already_applied refusal says so), so they are allowed.
    peak_writer.apply_run(pg_conn, first["run_id"], by="manager")
    pg_conn.commit()
    third = peak_service.run_upload(raw, FILENAME)
    assert third["state"] == "done"


class _OtherSession:
    """A second database session holding the PEAK lock, as a run in another instance would."""

    def __init__(self, url):
        from sqlalchemy import create_engine
        self.engine = create_engine(url, future=True)
        self.conn = self.engine.connect()

    def __enter__(self):
        self.conn.execute(text("select pg_advisory_lock(:k)"), {"k": peak_writer.PEAK_LOCK_KEY})
        return self

    def __exit__(self, *exc):
        self.conn.execute(text("select pg_advisory_unlock(:k)"), {"k": peak_writer.PEAK_LOCK_KEY})
        self.conn.close()
        self.engine.dispose()


def test_a_run_refused_by_the_lock_leaves_a_row_that_names_the_refusal(pg_conn, pg_url, monkeypatch):
    _db_env(pg_conn, monkeypatch)
    with _OtherSession(pg_url):
        run = peak_service.run_upload(_report([_line()]), FILENAME)
    assert run["state"] == "failed" and run["problem"]["code"] == "peak_run_in_progress"
    note = pg_conn.execute(text(
        "select note from landing.import_run where source_system = 'PEAK' order by id desc limit 1")).scalar()
    assert note.startswith("peak_run_in_progress:")


def test_a_run_that_takes_the_lock_ends_a_run_left_running_by_a_dead_process(pg_conn, monkeypatch):
    """Fix-all P9 (M7): a process that died mid-write left its row RUNNING for ever."""
    _db_env(pg_conn, monkeypatch)
    dead = pg_conn.execute(text(
        "insert into landing.import_run (source_system, status, started_at) "
        "values ('PEAK_RECEIPT', 'RUNNING', now() - interval '2 hours') returning id")).scalar()
    pg_conn.commit()
    run = peak_service.run_upload(_report([_line()]), FILENAME)
    assert run["state"] == "done", run.get("problem")
    status, note = pg_conn.execute(text("select status, note from landing.import_run where id = :i"),
                                   {"i": dead}).one()
    assert status == "FAILED" and note.startswith("pipeline_failed:")
