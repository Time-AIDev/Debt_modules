"""Fix-all leg S: the New Order Master uploaded as .xlsx IS the book (Arina,
2026-09-24, reversing ruling 73). Every workbook here is SYNTHETIC — invented names
and ids under the importer's own headers; the real sheet holds real customers.
"""
import io
import re
import zipfile
import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import book, db, imports, journey, main, migrate
from app.main import app
from app.pipelines import runs
from tests.test_round5_data_flow import _xlsx_bytes_multi

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MANAGER = {"X-Volt-Role": "MANAGER"}

K1 = "91000000001_Kanda_กานดา_EPCZ"      # leasing row says Current; "done collection" says Late
K2 = "91000000002_Pichai_พิชัย_EPCZ"     # leasing row only
K3 = "91000000003_Ratree_ราตรี_EPCZ"     # "done collection" only

LEASING = ["VOLT ID", "Payment Status", "Term, Original", "Rate,  inc VAT", "First Payment Date",
           "Days Late", "Comment"]
# The month headers are DATE cells, as the real tab's are.
TRACKING = ["VOLT ID", "Category", "PTP Date", "PTP Amount", "Note (for supervisor review)", "Action",
            "PMT (excl. late fee)", ("DATE", date(2025, 6, 1)), ("DATE", date(2025, 7, 1)),
            "Total Paid", "Total Overdue", "Total Outstanding"]


def _workbook(leasing=(K1, K2), tracked=(K1, K3)):
    """`tracked=None` leaves the "done collection" tab out of the file altogether."""
    rows = {K1: [K1, "Current", "60", "5000.00", "6/10/2025", "0", ""],
            K2: [K2, "Late", "60", "4000.00", "6/10/2025", "40", ""]}
    track = {K1: [K1, "Late", "", "", "", "", "5000.00", "5000.00", "Late", "5000.00", "5000.00", "250000.00"],
             K3: [K3, "Active", "", "", "", "", "3000.00", "3000.00", "3000.00", "6000.00", "0", "150000.00"]}
    tabs = [("Leasing A", [LEASING] + [rows[v] for v in leasing])]
    if tracked is not None:
        tabs.append(("done collection", [TRACKING] + [track[v] for v in tracked]))
    return _xlsx_bytes_multi(tabs)


def _leasing_book(n):
    """n synthetic leasing customers on one tab."""
    return _xlsx_bytes_multi([("Leasing A", [LEASING] + [
        ["9200000%04d_Name%d_ชื่อ%d_EPCZ" % (i, i, i), "Current", "60", "5000.00", "6/10/2025", "0", ""]
        for i in range(n)])])


def _drop_empty_rows(xlsx):
    """Excel omits an empty row entirely; the test builder writes `<row r="n"></row>`."""
    src, buf = zipfile.ZipFile(io.BytesIO(xlsx)), io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("xl/worksheets/"):
                data = re.sub(rb'<row r="\d+"></row>', b"", data)
            out.writestr(item, data)
    return buf.getvalue()


def _post(client, body, install=False, headers=None, filename="new-order-master.xlsx", confirm=None):
    query = "?install=true" if install else ""
    if confirm is not None:
        query += "&confirm_retire=%d" % confirm
    return client.post("/v1/imports" + query, content=body,
                       headers={"X-Volt-Filename": filename, "Content-Type": XLSX, **(headers or {})})


@pytest.fixture
def client():
    return TestClient(app)


# --- one assembly path, and the months the xlsx carries as dates ---------------------

def test_an_uploaded_done_collection_tab_keeps_every_month_and_joins_the_book_payload():
    run, payload = imports.parse_upload(_workbook(), "nom.xlsx", "x", "MANAGER", with_payload=True)
    assert run["counts"]["tracked"] == 2 and run["counts"]["rows_imported"] == 4
    by_id = {c["volt_id"]: c for c in payload["customers"]}
    assert set(by_id) == {K1, K2, K3}
    months = by_id[K1]["tracking"]["months"]
    assert [m["month"] for m in months] == ["Jun 2025", "Jul 2025"]
    assert [m["cell"]["kind"] for m in months] == ["PAID", "LATE"]
    assert by_id[K1]["leasing"]["payment_status"] == "Current"      # both tabs on one customer
    assert by_id[K3]["leasing"] is None and by_id[K3]["tracking"]["category"] == "Active"


# --- sheet-check fixes ---------------------------------------------------------------

def test_a_refusal_names_the_spreadsheet_row_even_below_rows_excel_left_out():
    rows = [LEASING, [K1, "Current", "60", "5000.00", "6/10/2025", "0", ""], [], [], [],
            ["NoUnderscore", "Late", "60", "4000.00", "6/10/2025", "40", ""]]
    run = imports.parse_upload(_drop_empty_rows(_xlsx_bytes_multi([("Leasing A", rows)])), "a.xlsx", "x", "OFFICER")
    assert [r["source_ref"]["row"] for r in run["refusals"]] == [6]


def test_one_value_at_the_last_spreadsheet_row_costs_one_row_not_a_million():
    rows = [LEASING, [K1, "Current", "60", "5000.00", "6/10/2025", "0", ""],
            ["NoUnderscore", "Late", "60", "4000.00", "6/10/2025", "40", ""]]
    xlsx = _xlsx_bytes_multi([("Leasing A", rows)])
    src, buf = zipfile.ZipFile(io.BytesIO(xlsx)), io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("xl/worksheets/"):
                data = data.replace(b'<row r="3">', b'<row r="1048576">')
            out.writestr(item, data)
    sheet = imports.read_xlsx(buf.getvalue())[0]
    assert len(sheet["rows"]) == 3 and sheet["row_numbers"] == [1, 2, 1048576]
    run = imports.parse_upload(buf.getvalue(), "far.xlsx", "x", "OFFICER")
    assert [r["source_ref"]["row"] for r in run["refusals"]] == [1048576]


def test_a_leasing_tab_whose_every_row_is_refused_reports_its_rows_not_an_unknown_file():
    rows = [LEASING, ["NoUnderscore", "Late", "60", "1.00", "6/10/2025", "0", ""]]
    run = imports.parse_upload(_xlsx_bytes_multi([("Leasing A", rows)]), "a.xlsx", "x", "OFFICER")
    assert run["sheets"][0]["kind"] == "LEASING_BOOK"
    assert [r["source_ref"]["row"] for r in run["refusals"]] == [2]


def test_an_unrecognised_file_says_what_a_leasing_tab_needs(client):
    r = client.post("/v1/imports", content=b"VOLT ID,Payment Status\nVC1_Aa_Bb_,Late\n",
                    headers={"X-Volt-Filename": "a.csv"})
    assert r.status_code == 422
    err = r.json()["errors"][0]
    assert "Term, Original" in err["message"] and "Term, Original" in err["message_th"]


def test_blank_rows_are_never_refused():
    rows = [LEASING, [K1, "Current", "60", "5000.00", "6/10/2025", "0", ""], ["", "", ""], [],
            [K2, "Late", "60", "4000.00", "6/10/2025", "40", ""]]
    run = imports.parse_upload(_xlsx_bytes_multi([("Leasing A", rows)]), "a.xlsx", "x", "OFFICER")
    assert run["counts"]["rows_refused"] == 0 and run["counts"]["rows_imported"] == 2


# --- the install door ----------------------------------------------------------------

def test_install_is_a_managers_act_and_the_plain_check_stays_open(client):
    r = _post(client, _workbook(), install=True, headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    r = _post(client, _workbook(), headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 200 and r.json()["installed"] is False


def test_install_refuses_a_file_that_is_not_the_book(client):
    assets = [["VOLT ID", "Panel Brand", "Inverter Serial"], [K1, "Brand A", "INV-1"]]
    r = _post(client, _xlsx_bytes_multi([("Assets", assets)]), install=True, headers=MANAGER)
    assert r.status_code == 422 and r.json()["code"] == "sheet_incomplete"
    # a "done collection" tab alone would rebuild every contract from its tracking rows
    r = _post(client, _workbook(leasing=()), install=True, headers=MANAGER)
    assert r.status_code == 422 and r.json()["code"] == "sheet_incomplete"


def test_install_without_a_database_is_refused_503(client, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = _post(client, _workbook(), install=True, headers=MANAGER)
    assert r.status_code == 503 and r.json()["code"] == "database_required"


@pytest.fixture
def landed_db(pg_url, pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    try:
        yield pg_conn
    finally:
        db.reset()


def test_install_lands_the_sheet_serves_it_and_retires_what_the_next_file_drops(client, landed_db):
    r = _post(client, _workbook(), install=True, headers=MANAGER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["installed"] is True
    done = body["install"]
    assert (done["customers"], done["tracked"], done["retired"], done["served"]) == (3, 2, 0, True)
    assert done["contracts"] == 3
    served = {c.volt_id: c for c in main.CUSTOMERS}
    assert set(served) == {K1, K2, K3}                           # the sheet, and no made-up demo customer
    assert book.from_landing() and journey.for_current().cancellations == {}

    # K1: the leasing row says Current, the "done collection" tab says Late — the tab wins.
    case = client.get("/v1/cases/by-customer/%s" % served[K1].uid).json()["case"]
    assert case["payment_status"] == "LATE"
    assert case["sheet_status"] == {"code": "LATE", "word": "Late", "unknown": False, "month": "Jul 2025"}
    assert case["sheet_captured_on"] == str(book.sheet_captured_on()) and book.sheet_captured_on()
    assert [(m["month"], m["status"], m["source"]) for m in case["month_status"]] == \
        [("Jun 2025", "PAID", "SHEET"), ("Jul 2025", "LATE", "SHEET")]
    assert case["status_disagreements"] == []

    # PEAK bills K1's July and says it is paid: PEAK decides the status, and the
    # disagreement with the sheet is listed — on the case and on the review list.
    from app import cases
    paid = {"doc_no": "IVT-7001", "status": "PAID", "due_on": "2025-07-10", "amount_awaiting": "0.00"}
    served[K1].sheet["peak"] = {"report_as_of": "2025-07-31", "invoices": [paid]}
    assert cases._payment_status(served[K1]) == "CURRENT"
    expected = [{"month": None, "peak": "CURRENT", "sheet": "LATE", "peak_off": False},
                {"month": "Jul 2025", "peak": "PAID", "sheet": "LATE"}]
    case = client.get("/v1/cases/by-customer/%s" % served[K1].uid).json()["case"]
    assert case["status_disagreements"] == expected
    assert [(m["month"], m["status"], m["source"]) for m in case["month_status"]] == \
        [("Jun 2025", "PAID", "SHEET"), ("Jul 2025", "PAID", "PEAK")]
    listed = client.get("/v1/imports/sheet/disagreements").json()
    assert listed["meta"] == {"total": 2, "customers": 1}
    assert [{k: v for k, v in row.items() if k not in ("customer_uid", "name", "customer_no")}
            for row in listed["rows"]] == expected
    assert {row["customer_uid"] for row in listed["rows"]} == {served[K1].uid}
    # nothing overwritten: the sheet keeps its word and PEAK its invoice
    assert served[K1].sheet["tracking"]["category"] == "Late"
    assert served[K1].sheet["tracking"]["months"][1]["cell"] == {"kind": "LATE"}
    assert served[K1].sheet["peak"]["invoices"] == [paid]

    # The next file carries K1 alone, off the "done collection" tab: K2 and K3 would
    # retire — two of three, and a whole tab — so the check says so and the install
    # asks for that count back before it retires anything.
    smaller = _workbook(leasing=(K1,), tracked=())
    shown = _post(client, smaller).json()["retire"]
    assert shown == {"customers": 2, "live": 3, "dropped_tabs": ["tracking"], "needs_confirm": True}
    for confirm in (None, 1):
        r = _post(client, smaller, install=True, headers=MANAGER, confirm=confirm)
        assert r.status_code == 422 and r.json()["code"] == "install_would_retire"
        assert r.json()["extensions"]["retire"] == shown
    assert {c.volt_id for c in main.CUSTOMERS} == {K1, K2, K3}          # nothing retired
    r = _post(client, smaller, install=True, headers=MANAGER, confirm=2)
    assert r.status_code == 200 and r.json()["install"]["retired"] == 2
    served = {c.volt_id: c for c in main.CUSTOMERS}
    assert set(served) == {K1} and served[K1].sheet["tracking"] is None


def test_a_partial_file_never_installs_as_the_whole_book_unconfirmed(client, landed_db):
    """Audit probe steps 3 and 5: a file without the "done collection" tab, and a
    one-customer CSV, each refused with the counts; nothing changes until confirmed."""
    assert _post(client, _workbook(), install=True, headers=MANAGER).status_code == 200
    r = _post(client, _workbook(tracked=None), install=True, headers=MANAGER)
    assert r.status_code == 422 and r.json()["extensions"]["retire"] == {
        "customers": 1, "live": 3, "dropped_tabs": ["tracking"], "needs_confirm": True}
    one = ('"VOLT ID","Payment Status","Term, Original","Rate,  inc VAT","First Payment Date"\r\n'
           '"%s","Current","60","5000.00","6/10/2025"\r\n' % K1).encode("utf-8")
    r = client.post("/v1/imports?install=true", content=one,
                    headers={"X-Volt-Filename": "one.csv", "Content-Type": "text/csv", **MANAGER})
    assert r.status_code == 422 and r.json()["extensions"]["retire"]["customers"] == 2
    served = {c.volt_id: c for c in main.CUSTOMERS}
    assert set(served) == {K1, K2, K3} and served[K1].sheet["tracking"]      # unchanged
    from app import cases
    assert cases._payment_status(served[K1]) == "LATE"


def test_a_tenth_of_the_book_may_leave_without_a_confirmation(client, landed_db):
    assert _post(client, _leasing_book(11), install=True, headers=MANAGER).status_code == 200
    r = _post(client, _leasing_book(9), install=True, headers=MANAGER)        # 2 of 11 would leave
    assert r.status_code == 422 and r.json()["extensions"]["retire"]["customers"] == 2
    r = _post(client, _leasing_book(10), install=True, headers=MANAGER)       # 1 of 11: no question
    assert r.status_code == 200 and r.json()["install"]["retired"] == 1


def _await_import(client, uid):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get("/v1/operation-runs/%s" % uid)
        assert response.status_code == 200, response.text
        operation = response.json()
        if operation["state"] in ("done", "failed", "cancelled"):
            return operation
        time.sleep(0.01)
    pytest.fail("Import did not finish: %s" % operation)


def _start_import(client, raw, install=False, confirm=None):
    query = "?install=true" if install else ""
    if confirm is not None:
        query += "&confirm_retire=%d" % confirm
    response = client.post("/v1/imports:start" + query, content=raw,
                           headers={"X-Volt-Filename": "synthetic.xlsx", "Content-Type": XLSX, **MANAGER})
    assert response.status_code == 202, response.text
    return response.json()["uid"]


def test_async_sheet_check_reports_real_parser_progress_and_completes(client, monkeypatch):
    progress = []
    original = runs.progress

    def observe(uid, **fields):
        original(uid, **fields)
        if fields.get("phase") == "parsing" and fields.get("phase_total") is not None:
            snapshot = runs.get(uid)
            progress.append((snapshot["processed"], snapshot["phase_total"]))

    monkeypatch.setattr(runs, "progress", observe)
    operation = _await_import(client, _start_import(client, _workbook()))
    assert operation["state"] == "done", operation["problem"]
    assert progress == [(1, 2), (2, 2)]
    report = operation["result"]
    assert report["installed"] is False
    assert report["counts"]["rows_imported"] == 4
    assert report["counts"]["customers"] == 3
    assert [s["kind"] for s in report["sheets"]] == ["LEASING_BOOK", "COLLECTION_TRACKING"]


def test_async_sheet_install_requires_the_exact_retirement_confirmation(client, landed_db):
    from sqlalchemy import text

    installed = _await_import(client, _start_import(client, _workbook(), install=True))
    assert installed["state"] == "done", installed
    assert installed["result"]["install"]["customers"] == 3
    smaller = _workbook(leasing=(K1,), tracked=())
    checked = _await_import(client, _start_import(client, smaller))
    assert checked["state"] == "done", checked
    assert checked["result"]["retire"] == {
        "customers": 2, "live": 3, "dropped_tabs": ["tracking"], "needs_confirm": True}
    for confirm in (None, 1):
        refused = _await_import(client, _start_import(client, smaller, install=True, confirm=confirm))
        assert refused["state"] == "failed", refused
        assert refused["problem"]["code"] == "install_would_retire"
        assert landed_db.execute(text(
            "select count(*) from landing.customer where data_source='SHEET' and retired_at is null"
        )).scalar_one() == 3
    confirmed = _await_import(client, _start_import(client, smaller, install=True, confirm=2))
    assert confirmed["state"] == "done", confirmed
    assert confirmed["result"]["installed"] is True
    assert confirmed["result"]["install"]["retired"] == 2
    assert {c.volt_id for c in main.CUSTOMERS} == {K1}


def test_async_sheet_cancel_before_commit_rolls_back_the_install(client, landed_db, monkeypatch):
    from sqlalchemy import text

    reached_commit = threading.Event()
    install_exited = threading.Event()
    release = threading.Event()
    original = imports.install

    def pause_install(payload, confirm_retire=None, before_commit=None):
        commit_callback = before_commit

        def pause():
            reached_commit.set()
            assert release.wait(10), "Test did not release the commit boundary"
            commit_callback()

        try:
            return original(payload, confirm_retire, before_commit=pause)
        finally:
            install_exited.set()

    monkeypatch.setattr(imports, "install", pause_install)
    uid = _start_import(client, _workbook(), install=True)
    try:
        assert reached_commit.wait(10), runs.get(uid)
        stopped = client.post("/v1/operation-runs/%s:cancel" % uid)
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["state"] == "cancel_requested"
    finally:
        release.set()
        operation = _await_import(client, uid)
        if reached_commit.is_set():
            assert install_exited.wait(10), "Install did not finish rolling back"
    assert operation["state"] == "cancelled", operation
    assert operation["committed"] is False
    assert landed_db.execute(text("select count(*) from landing.customer")).scalar_one() == 0
    assert landed_db.execute(text("select count(*) from landing.import_run")).scalar_one() == 0
    assert client.get("/v1/imports").json()["meta"]["total"] == 0
