"""Production boundary regressions: hostile files, queue failures and retention."""
import asyncio
import hashlib
import io
import json
import os
import time
import uuid
import zipfile
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import text
from app import csv_safety, db, errors, imports, migrate, task_objects
from app.attachments import guard, store
from tests.test_round5_data_flow import _xlsx_bytes_multi


@pytest.mark.parametrize("value", ["=1+2", "+1+2", "-1+2", "@SUM(A1)", "\t+1+2", "\ufeff=1"])
def test_formula_text_is_refused_at_import_and_escaped_at_export(value):
    assert csv_safety.formula(value)
    assert csv_safety.cell(value) == "'" + value
    with pytest.raises(guard.Refused):
        guard._check_csv((value + "\n").encode("utf-8"))


@pytest.mark.parametrize("value", ["-100", "+100.25", "-1,000.50", "-1e-3", "hello", "กานดา", 123, None])
def test_csv_safety_preserves_numeric_and_ordinary_data(value):
    assert not csv_safety.formula(value)
    assert csv_safety.cell(value) == value


@pytest.mark.parametrize("reference", ["ZZZZZZ1", "XFE1", "A0", "A1048577", "-A1", "1"])
def test_xlsx_refuses_huge_or_invalid_column_before_allocating_a_row(reference):
    row = ET.fromstring('<row><c r="%s" t="inlineStr"><is><t>data</t></is></c></row>' % reference)
    with pytest.raises(imports.UploadRefused):
        imports._row_cells(row, [], set(), False)


def test_xlsx_permits_excel_last_column_but_rejects_large_kept_data(monkeypatch):
    assert imports._col_index("XFD1") == 16383
    monkeypatch.setenv("XLSX_MAX_KEPT_CELLS", "3")
    workbook = _xlsx_bytes_multi([("data", [["a", "b", "c", "d"]])])
    with pytest.raises(imports.UploadRefused):
        imports.read_xlsx(workbook)


def test_styled_blank_rows_do_not_consume_kept_data_budget(monkeypatch):
    from tests.test_upload_scale import _with_formatted_tail
    monkeypatch.setenv("XLSX_MAX_KEPT_CELLS", "3")
    plain = _xlsx_bytes_multi([("data", [["a", "b", "c"]])])
    padded = _with_formatted_tail(plain, rows=500, cols=26)
    assert imports.read_xlsx(padded) == imports.read_xlsx(plain)


def test_shared_string_table_has_a_memory_budget(monkeypatch):
    monkeypatch.setenv("XLSX_MAX_SHARED_STRING_BYTES", "3")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", '<sst><si><t>abcd</t></si></sst>')
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as archive:
        with pytest.raises(imports.UploadRefused):
            imports._shared_strings(archive, imports._XlsxBudget())


def test_xml_token_is_refused_before_unbounded_text_is_parsed():
    reader = imports._SafeXmlReader(io.BytesIO(b"<t>" + b"x" * (imports.XLSX_MAX_XML_TOKEN_BYTES + 1)))
    with pytest.raises(imports.UploadRefused):
        while reader.read(65536):
            pass


def test_parse_time_limit_and_malformed_csv_return_validation_refusals(monkeypatch):
    monkeypatch.setenv("XLSX_PARSE_MAX_SECONDS", "0")
    workbook = _xlsx_bytes_multi([("data", [["a"]])])
    with pytest.raises(imports.UploadRefused):
        imports.read_xlsx(workbook)
    with pytest.raises(imports.UploadRefused):
        imports.parse_upload(b"x" * 140000, "bad.csv", "owner", "OWNER")
    with pytest.raises(imports.UploadRefused):
        imports.parse_upload(b"name\n+1+2\n", "formula.csv", "owner", "OWNER")


def test_attachment_integrity_is_checked_on_reads(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: False)
    raw = b"original"
    row = store.put({"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "kind": "PDF",
                     "content_type": "application/pdf", "filename": "a.pdf"}, raw, "owner",
                    {"state": "RULES_ONLY", "by": "rules"})
    store._MEMORY[row["uid"]]["bytes"] = b"modified"
    with pytest.raises(errors.Problem) as exc:
        store.get(row["uid"])
    assert exc.value.code == "attachment_integrity_failed"
    assert store.metadata(row["uid"])["uid"] == row["uid"]


@pytest.fixture
def wired(monkeypatch, pg_url, pg_conn, tmp_path):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ENV", "prd")
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("UPLOADS_BUCKET", "uploads")
    monkeypatch.setenv("CLEAN_BUCKET", "clean")
    yield pg_conn, tmp_path / "objects"
    db.reset()


def _seed_job(conn, uid="review-job"):
    conn.execute(text("insert into app.operation_run(uid,payload) values(:u,cast(:p as jsonb))"),
                 {"u": uid, "p": json.dumps({"uid": uid, "state": "queued", "kind": "import", "started_at": 1, "finished_at": None})})
    conn.execute(text("insert into app.task_outbox(uid,payload) values(:u,cast(:p as jsonb))"),
                 {"u": uid, "p": json.dumps({"object_name": "jobs/" + uid + "/body", "sha256": "wrong"})})
    conn.commit()


def test_upload_retry_is_identical_and_replacement_creates_no_orphan(wired):
    from app import durable_uploads
    conn, root = wired
    uid = str(uuid.uuid4())
    assert durable_uploads.put(uid, 0, 1, b"original", "owner") == 1
    assert durable_uploads.put(uid, 0, 1, b"original", "owner") == 1
    with pytest.raises(imports.UploadRefused):
        durable_uploads.put(uid, 0, 1, b"modified", "owner")
    assert len(list((root / "uploads" / "chunks").rglob("*"))) == 3  # UUID dir, part dir, immutable file
    assert durable_uploads.take(uid, "owner") == b"original"


def test_upload_owner_and_total_quota_enforced_before_object_write(wired, monkeypatch):
    from app import durable_uploads
    _, root = wired
    monkeypatch.setenv("UPLOAD_OWNER_MAX_BYTES", "6")
    monkeypatch.setenv("UPLOAD_TOTAL_MAX_BYTES", "8")
    durable_uploads.put(str(uuid.uuid4()), 0, 1, b"12345", "one")
    with pytest.raises(imports.UploadRefused):
        durable_uploads.put(str(uuid.uuid4()), 0, 1, b"12", "one")
    with pytest.raises(imports.UploadRefused):
        durable_uploads.put(str(uuid.uuid4()), 0, 1, b"1234", "two")
    assert len(list(task_objects.list_transient_objects())) == 1


def test_transient_worker_failure_stops_at_retry_limit(wired, monkeypatch):
    from app import local_worker, worker
    conn, _ = wired
    _seed_job(conn)
    monkeypatch.setenv("MAX_JOB_ATTEMPTS", "2")
    async def unavailable(uid):
        raise errors.Problem("dependency_unavailable", 503, "Unavailable", "retry", "ลองใหม่", "DEBT-JOB-503", retryable=True)
    monkeypatch.setattr(worker, "_execute_job_body", unavailable)
    assert asyncio.run(local_worker.run_once()) == 1
    conn.commit()
    first = conn.execute(text("select attempt_count,finished_at,last_error_code from app.task_outbox")).one()
    assert first.attempt_count == 1 and first.finished_at is None
    assert first.last_error_code == "dependency_unavailable"
    conn.execute(text("update app.task_outbox set next_attempt_at=null"))
    conn.commit()
    assert asyncio.run(local_worker.run_once()) == 1
    conn.commit()
    last = conn.execute(text("select attempt_count,dead_lettered_at from app.task_outbox")).one()
    assert last.attempt_count == 2 and last.dead_lettered_at
    assert asyncio.run(local_worker.run_once()) == 0


def test_job_storage_quota_refuses_submission_before_bytes_written(wired, monkeypatch):
    from app import task_outbox
    conn, _ = wired
    monkeypatch.setenv("JOB_OWNER_MAX_BYTES", "6")
    monkeypatch.setenv("JOB_TOTAL_MAX_BYTES", "8")
    conn.execute(text("insert into app.operation_run(uid,payload) values('one','{}'),('two','{}'),('three','{}')"))
    conn.commit()
    task_outbox.enqueue("one", "/v1/imports", b"12345", b"", {}, {"sub": "one"})
    with pytest.raises(errors.Problem) as exc:
        task_outbox.enqueue("two", "/v1/imports", b"12", b"", {}, {"sub": "one"})
    assert exc.value.code == "job_storage_quota"
    with pytest.raises(errors.Problem):
        task_outbox.enqueue("three", "/v1/imports", b"1234", b"", {}, {"sub": "two"})
    assert len(list(task_objects.list_transient_objects())) == 1


def test_successful_job_input_is_deleted_only_after_finish_commit(wired):
    from app import worker
    conn, _ = wired
    _seed_job(conn)
    task_objects.put("jobs/review-job/body", b"input")
    worker._finished("review-job")
    assert conn.execute(text("select finished_at is not null from app.task_outbox")).scalar_one()
    with pytest.raises(FileNotFoundError):
        task_objects.get("jobs/review-job/body")


@pytest.mark.parametrize("status, terminal", [(401, True), (403, True), (422, True), (503, False)])
def test_worker_classifies_real_api_refusals_without_retrying_permanent_errors(wired, monkeypatch, status, terminal):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from app import local_worker, main, task_outbox
    conn, _ = wired
    conn.execute(text("insert into app.operation_run(uid,payload) values('http-job',cast(:p as jsonb))"),
                 {"p": json.dumps({"uid": "http-job", "state": "queued", "kind": "import", "started_at": 1, "finished_at": None})})
    conn.commit()
    application = FastAPI()
    @application.post("/v1/refuse")
    def refuse():
        return JSONResponse({"code": "account_disabled" if terminal else "upstream_unavailable", "retryable": not terminal}, status_code=status)
    monkeypatch.setattr(main, "app", application)
    task_outbox.enqueue("http-job", "/v1/refuse", b"{}", b"", {}, {"sub": "owner", "role": "OWNER"})
    assert asyncio.run(local_worker.run_once()) == 1
    conn.commit()
    row = conn.execute(text("select attempt_count,dead_lettered_at,next_attempt_at,last_error_code from app.task_outbox")).one()
    assert row.attempt_count == 1
    assert bool(row.dead_lettered_at) == terminal
    assert bool(row.next_attempt_at) != terminal
    assert row.last_error_code == ("account_disabled" if terminal else "upstream_unavailable")


def test_heartbeat_detects_stale_idle_and_stalled_working_process(wired):
    from app import local_worker
    conn, _ = wired
    assert not local_worker.healthy()
    local_worker.heartbeat("idle")
    assert local_worker.healthy()
    conn.execute(text("update app.worker_heartbeat set last_seen_at=now()-interval '31 seconds'"))
    conn.commit()
    assert not local_worker.healthy()
    local_worker.heartbeat("working", "job")
    assert local_worker.healthy()
    conn.execute(text("update app.worker_heartbeat set job_started_at=now()-interval '301 seconds'"))
    conn.commit()
    assert not local_worker.healthy()


def test_retention_preserves_active_jobs_fresh_writes_and_attachments(wired):
    from app import object_retention
    conn, root = wired
    old = time.time() - 3 * 86400
    for name in ("chunks/active/0/file", "chunks/consumed/0/file", "jobs/orphan/body"):
        task_objects.put(name, b"old")
        os.utime(root / "uploads" / name, (old, old))
    task_objects.put("jobs/fresh/body", b"fresh")
    task_objects.put("attachments/evidence", b"evidence", bucket_env="CLEAN_BUCKET")
    os.utime(root / "clean" / "attachments/evidence", (old, old))
    conn.execute(text("insert into app.upload_session(upload_id,owner,parts,created_at,consumed_at) values"
                      "('active','owner',1,now(),null),('consumed','owner',1,now()-interval '3 days',now()-interval '2 days')"))
    conn.execute(text("insert into app.upload_part(upload_id,part_index,object_name,size) values"
                      "('active',0,'chunks/active/0/file',3),('consumed',0,'chunks/consumed/0/file',3)"))
    conn.commit()
    preview = object_retention.cleanup()
    assert preview["objects"] == 2 and preview["upload_sessions"] == 1
    assert task_objects.get("jobs/orphan/body") == b"old"
    applied = object_retention.cleanup(apply=True)
    assert applied["objects"] == 2
    assert task_objects.get("chunks/active/0/file") == b"old"
    assert task_objects.get("jobs/fresh/body") == b"fresh"
    assert task_objects.get("attachments/evidence", bucket_env="CLEAN_BUCKET") == b"evidence"
    with pytest.raises(FileNotFoundError):
        task_objects.get("chunks/consumed/0/file")
