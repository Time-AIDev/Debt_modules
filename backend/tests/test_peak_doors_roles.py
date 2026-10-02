"""Staging changes nothing, linking is reversible, applying is guarded by the date
and range refusals — all officer work. allow_older overrides both refusals, so it
stays a Manager's (Task 4, Ruling 5: "open all four").

Fixtures reuse test_peak_router.py's db_env/_book_customer_no/_parsed/_inv/_exact
and test_peak_report.py's report builder; no new fixture pattern was needed.

Ruling 1: staged_peak_run's covers_from/report_as_of are built to sit AFTER an
already-applied baseline (so its own apply succeeds for role reasons, not by luck
of the date policy); staged_older_peak_run's are built narrower/older than that
same baseline, which is what makes allow_older necessary.

Ruling 2: no guard on the read endpoints (/last-run, /doors, /rows, /links) —
test_reading_the_unmatched_rows_needs_a_role is deliberately not written here.
"""
import pytest

from app.pipelines import peak_writer
from tests.test_peak_report import _line, _report
from tests.test_peak_router import _book_customer_no, _exact, _inv, _parsed, client, db_env

OFFICER = {"X-Volt-Role": "OFFICER"}
MANAGER = {"X-Volt-Role": "MANAGER"}

BASELINE_FILENAME = "export_as_of_20240101_20260901.xlsx"  # covers 2024-01-01..2026-09-01, applied
NEWER_FILENAME = "export_as_of_20240101_20260914.xlsx"      # same start, later as-of: not narrower, not older
OLDER_FILENAME = "export_as_of_20260601_20260910.xlsx"      # later start (narrower) AND earlier as-of


@pytest.fixture
def peak_file():
    return _report([_line()])


@pytest.fixture
def book_customer_no():
    return _book_customer_no()


def _apply_baseline(conn):
    no = _book_customer_no()
    result = peak_writer.write(conn, _parsed(_inv("IVT-BASE", no), as_of="2026-09-01"),
                               [_exact(no)], door="upload", filename=BASELINE_FILENAME)
    peak_writer.apply_run(conn, result["run_id"], by="settasak")
    conn.commit()


@pytest.fixture
def staged_peak_run(db_env):
    conn = db_env
    _apply_baseline(conn)
    no = _book_customer_no()
    result = peak_writer.write(conn, _parsed(_inv("IVT-NEW", no), as_of="2026-09-14"),
                               [_exact(no)], door="upload", filename=NEWER_FILENAME)
    conn.commit()
    return result["run_id"]


@pytest.fixture
def staged_older_peak_run(db_env):
    conn = db_env
    _apply_baseline(conn)
    no = _book_customer_no()
    result = peak_writer.write(conn, _parsed(_inv("IVT-OLD", no), as_of="2026-08-01"),
                               [_exact(no)], door="upload", filename=OLDER_FILENAME)
    conn.commit()
    return result["run_id"]


def test_an_officer_may_upload(peak_file):
    r = client.post("/v1/pipelines/peak-report:start", content=peak_file,
                    headers={**OFFICER, "X-Volt-Filename": "export_as_of_20240101_20260914_x.xlsx"})
    assert r.status_code == 202, r.text


def test_an_officer_may_confirm_a_link(staged_peak_run, book_customer_no):
    r = client.post("/v1/pipelines/peak-report/links", headers=OFFICER,
                    json={"contact_code": "99999000005", "customer_no": book_customer_no,
                          "reason": "matched on the PEAK contact record"})
    # /links answers 201 (routers/peak_pipeline.py:265); the brief's own draft said
    # 200, which is apply_run's convention, not confirm_link's.
    assert r.status_code == 201, r.text


def test_an_officer_may_apply_a_newer_report(staged_peak_run):
    r = client.post("/v1/pipelines/peak-report/landing-runs/%s:apply" % staged_peak_run,
                    json={}, headers=OFFICER)
    assert r.status_code == 200, r.text


def test_an_officer_may_not_roll_the_book_backwards(staged_older_peak_run):
    r = client.post("/v1/pipelines/peak-report/landing-runs/%s:apply" % staged_older_peak_run,
                    json={"allow_older": True}, headers=OFFICER)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_a_manager_may(staged_older_peak_run):
    r = client.post("/v1/pipelines/peak-report/landing-runs/%s:apply" % staged_older_peak_run,
                    json={"allow_older": True}, headers=MANAGER)
    assert r.status_code == 200, r.text
