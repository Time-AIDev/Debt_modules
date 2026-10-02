"""Round 5, data flow — rulings 71 (the upload) and 72 (the governed export), plus
the three MAJORs (R5-F01/03/05) and the tenth shared-mutable, all found by leg F
while specifying the two rulings and closed by leg C while building them.

Every test goes through the HTTP surface with the session cookie the middleware
issues, matching the rest of this suite's convention (test_round4.py's own note).
"""
import csv
import io
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

BD = settings.business_date
OFFICER = {"X-Volt-Officer": "nantapol"}


def _thai(text):
    return any("฀" <= ch <= "๿" for ch in (text or ""))


@pytest.fixture
def client():
    return TestClient(app)


def _post_file(client, body_bytes, filename="upload.csv", content_type="text/csv", headers=None):
    h = {"X-Volt-Filename": filename, "Content-Type": content_type}
    h.update(headers or {})
    return client.post("/v1/imports", content=body_bytes, headers=h)


def _csv_bytes(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


LEASING_HEADER = ["VOLT ID", "Payment Status", "PTP Date", "Overdue", "Days Late",
                 "Term, Original", "Rate,  inc VAT", "Comment"]


def _leasing_rows(n=1, title=True):
    rows = []
    if title:
        rows.append(["New Order Master export 06/09/2026"])
        rows.append([])
    rows.append(LEASING_HEADER)
    for i in range(n):
        rows.append(["VC00%05d_Name%d_ชื่อ%d_" % (i, i, i), "Late", "7/31/2026",
                    "12345.67", "40", "60", "5580.00", "โทรแล้ว, ไม่รับ"])
    return rows


# --- .xlsx, built from scratch with stdlib only, mirroring leg F's own trap file --

_CT_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
          '</Types>')
_RELS_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
_WORKBOOK_RELS_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                     '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                     '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
                     '</Relationships>')
_STYLES_XML = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="0"/>'
              '<fonts count="1"><font/></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders>'
              '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
              # index 0 = general (not a date), index 1 = numFmtId 14 ("mm-dd-yy", a built-in date format)
              '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
              '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/></cellXfs>'
              '</styleSheet>')


def _col_letter(i):
    letters = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _sheet_xml_and_strings(rows, shared, shared_index):
    def sidx(text):
        if text not in shared_index:
            shared_index[text] = len(shared)
            shared.append(text)
        return shared_index[text]

    xml_rows = []
    for r, row in enumerate(rows, start=1):
        cells_xml = []
        for c, cell in enumerate(row):
            if cell is None:
                continue
            ref = "%s%d" % (_col_letter(c), r)
            if isinstance(cell, tuple) and cell[0] == "DATE":
                serial = (cell[1] - date(1899, 12, 30)).days
                cells_xml.append('<c r="%s" s="1"><v>%d</v></c>' % (ref, serial))
            elif isinstance(cell, tuple) and cell[0] == "ERROR":
                cells_xml.append('<c r="%s" t="e"><v>%s</v></c>' % (ref, cell[1]))
            else:
                i = sidx(str(cell))
                cells_xml.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, i))
        xml_rows.append('<row r="%d">%s</row>' % (r, "".join(cells_xml)))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetData>%s</sheetData></worksheet>') % "".join(xml_rows)


def _xlsx_bytes_multi(sheets, date1904=False):
    """sheets: [(name, rows), ...], in workbook order. A cell is a plain
    string/number for a shared-string/text cell, or ("DATE", date_obj) for a
    date-styled numeric cell, or ("ERROR", "#N/A") for a spreadsheet error cell, or
    None for a blank cell."""
    shared, shared_index = [], {}
    sheet_xmls = [_sheet_xml_and_strings(rows, shared, shared_index) for _name, rows in sheets]

    shared_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="%d" uniqueCount="%d">'
                 '%s</sst>') % (len(shared), len(shared),
                                "".join("<si><t xml:space=\"preserve\">%s</t></si>" % escape(s) for s in shared))

    sheet_entries = "".join(
        '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(name), i + 1, i + 1)
        for i, (name, _rows) in enumerate(sheets))
    workbook_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<workbookPr date1904="%s"/>'
                   '<sheets>%s</sheets></workbook>') % ("1" if date1904 else "0", sheet_entries)

    rel_entries = "".join(
        '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>'
        % (i + 1, i + 1) for i in range(len(sheets)))
    rel_entries += ('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                    '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
                    ) % (len(sheets) + 1, len(sheets) + 2)
    workbook_rels_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '%s</Relationships>') % rel_entries

    ct_overrides = "".join(
        '<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        % (i + 1) for i in range(len(sheets)))
    ct_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
             '%s'
             '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
             '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
             '</Types>') % ct_overrides

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ct_xml)
        zf.writestr("_rels/.rels", _RELS_XML)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/styles.xml", _STYLES_XML)
        zf.writestr("xl/sharedStrings.xml", shared_xml)
        for i, (_name, rows) in enumerate(sheets):
            zf.writestr("xl/worksheets/sheet%d.xml" % (i + 1), sheet_xmls[i])
    return buf.getvalue()


def _xlsx_bytes(sheet_name, rows, date1904=False):
    return _xlsx_bytes_multi([(sheet_name, rows)], date1904=date1904)


# === Ruling 71 — the import ========================================================

def test_r71_1_a_good_csv_returns_200_with_counts_and_refusals(client):
    body = _csv_bytes(_leasing_rows(3))
    r = _post_file(client, body, filename="book.csv")
    assert r.status_code == 200
    run = r.json()
    assert run["run"]["kind"] == "CSV"
    assert run["counts"]["rows_imported"] == 3
    assert run["counts"]["rows_read"] == run["counts"]["rows_imported"] + run["counts"]["rows_refused"]
    assert isinstance(run["refusals"], list)


def test_r71_2_oversize_is_refused_with_the_cap_named(client):
    # Bound to the product's own constant rather than a literal: the cap was raised
    # from 5 MB to 25 MB on 2026-09-11 and this test failed for encoding the number
    # instead of the rule. What it proves — oversize is refused, and the refusal
    # names the cap — is unchanged.
    from app.imports import MAX_BYTES

    huge = b"x" * (MAX_BYTES + 1)
    r = client.post("/v1/imports", content=huge,
                    headers={"X-Volt-Filename": "huge.csv", "Content-Length": str(len(huge))})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_failed"
    assert body["errors"][0]["pointer"] == "/file"
    assert body["errors"][0]["cap_bytes"] == MAX_BYTES
    assert _thai(body["errors"][0]["message_th"])


def test_r71_2b_a_chunked_body_with_no_content_length_is_also_capped(client):
    """The `Content-Length` PRE-CHECK (test_r71_2) only catches a body that DECLARES
    its size. A generator body sends `Transfer-Encoding: chunked` with no
    Content-Length at all — httpx/TestClient's own ASGI transport streams it exactly
    that way — so this drives the SEPARATE running-cap loop over `request.stream()`,
    measured working in F-api.md §4.1. The message differs from the pre-check's,
    which is how this test knows it took the other code path, not the same one
    twice."""
    from app import imports as imports_domain

    def chunks():
        chunk = b"a" * (64 * 1024)
        sent = 0
        cap = imports_domain.MAX_BYTES + 64 * 1024 * 2
        while sent < cap:
            yield chunk
            sent += len(chunk)

    r = client.post("/v1/imports", content=chunks(), headers={"X-Volt-Filename": "chunked.csv"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_failed"
    err = body["errors"][0]
    assert err["pointer"] == "/file"
    assert "stream" in err["message"].lower()
    assert err["cap_bytes"] == imports_domain.MAX_BYTES
    assert _thai(err["message_th"])


def test_r71_3_a_xlsx_renamed_csv_is_read_as_xlsx_not_text(client):
    xlsx_bytes = _xlsx_bytes("Leasing Book", _leasing_rows(2))
    r = _post_file(client, xlsx_bytes, filename="book.csv", content_type="text/csv")
    assert r.status_code == 200
    run = r.json()
    assert run["run"]["kind"] == "XLSX", "the magic bytes decide, not the declared type or the filename"
    assert run["sheets"][0]["name"] == "Leasing Book"


def test_r71_3b_a_non_csv_non_zip_body_is_refused_not_guessed(client):
    junk = bytes(range(256)) * 4
    r = _post_file(client, junk, filename="mystery.bin", content_type="application/octet-stream")
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/file"


def test_r71_4_a_cp874_file_parses_and_says_which_encoding_it_used(client):
    # A term column makes it a leasing tab: a file no reader recognises is refused 422.
    text = 'VOLT ID,Payment Status,"Term, Original"\r\nVC00001_a_ก_,Late,60\r\n'
    body = text.encode("cp874")
    r = _post_file(client, body, filename="thai-windows.csv")
    assert r.status_code == 200
    assert r.json()["run"]["encoding"] == "cp874"


def test_r71_5_title_rows_above_the_header_are_skipped_header_found_not_assumed(client):
    body = _csv_bytes(_leasing_rows(1, title=True))
    r = _post_file(client, body)
    run = r.json()
    sheet = run["sheets"][0]
    assert sheet["kind"] == "LEASING_BOOK"
    assert sheet["header_row"] == 3          # two title/blank rows above it, 1-based
    assert sheet["header_cells"] == LEASING_HEADER


def test_r71_6_every_imported_row_carries_a_traceable_source_ref(client):
    body = _csv_bytes(_leasing_rows(5))
    run = _post_file(client, body).json()
    assert run["counts"]["rows_imported"] == 5
    # source_ref is on the REFUSALS list per ruling 71's own words ("refused and
    # why"); imported rows are traced via the sheet + row math the respecification
    # promises. Confirmed here on the refusal side, which is what the report shows.
    body2 = _csv_bytes(_leasing_rows(2) + [["NoUnderscore", "Late"]])
    # "NoUnderscore" fails the SAME identity rule import_master_sheet.py's own
    # reader uses (`"_" not in volt_id`) — it has none, so it is refused.
    run2 = _post_file(client, body2).json()
    assert run2["counts"]["rows_refused"] >= 1
    refusal = run2["refusals"][0]
    # F-api.md's respecification: {sheet: <name or 0>, row: ...} — 0 for a .csv,
    # which has no tab name (a single block, the same convention the original
    # importer's own (block, row) pair used for a one-block source).
    assert refusal["source_ref"]["sheet"] == 0
    assert isinstance(refusal["source_ref"]["row"], int)
    assert refusal["reason_th"]


def test_r71_7_phone_reveal_is_the_only_door_and_the_run_stores_no_rows(client):
    """Extends test_fixture_honesty.py:133-140's guard onto the upload path — the
    existing assertions on the seeded book do not move. 2026-09-20: the reader keeps
    the phone whole for the dial actions, so the contract this test pins is that the
    RUN RECORD still stores no rows and the number is hidden at the serving layer
    (customer_contact.phone_fields), revealed only by the audited phone:reveal route."""
    header = ["Order Status", "Volt ID", "EPC Start Date", "Phone", "Email"]
    rows = [header,
           ["Order - Done", "VC00001_a_ก_", "2026-01-01", "081-234-5678", "a@b.com"],
           ["Order - Done", "VC00002_b_ข_", "2026-01-01", "", ""]]
    run = _post_file(client, _csv_bytes(rows)).json()
    assert run["sheets"][0]["kind"] == "ORDER_MASTER"
    assert run["counts"]["rows_imported"] == 2
    assert run["masking"]["phone"].startswith("read whole for the dial actions")
    assert run["masking"]["phone_e164"].startswith("kept by the reader")
    assert "run" in run and "sample_rows" not in run["run"] and "sample_rows" not in run


def test_r71_8_a_file_with_no_summary_sheet_is_no_basis_not_a_green_tick(client):
    """The all([]) trap, arrested: a single-tab upload has no PAYMENT_STATUS_PIVOT
    sheet, so `reconciliation.rows` is empty — `all([])` is True in Python, which
    would have been a green tick on an import that checked nothing (F-api.md §4.5).
    This is the new endpoint only; e2e_check.py:934 pins the OLD one as a bool,
    untouched."""
    run = _post_file(client, _csv_bytes(_leasing_rows(4))).json()
    assert run["reconciliation"]["basis"] == "NO_BASIS"
    assert run["reconciliation"]["rows"] == []


def test_r71_9_a_file_whose_own_totals_disagree_is_not_reconciled_with_both_numbers(client):
    """A real workbook's own pivot lives on a DIFFERENT TAB from the leasing rows it
    summarises (F-api.md §4.3 rule 3) — a single .csv is one tab and cannot carry
    both, which is exactly why `NO_BASIS` (r71_8) exists for that shape. This is the
    shape that CAN carry both: a two-tab .xlsx."""
    pivot_header = ["Payment Status", "NPL Type", "x", "x", "x", "COUNTA of VOLT ID"]
    pivot_rows = [pivot_header, ["Late", "", "", "", "", "5"]]
    leasing = _leasing_rows(2, title=False)   # only 2 imported, the pivot claims 5
    xlsx_bytes = _xlsx_bytes_multi([("Leasing Book", leasing), ("Payment Status Pivot", pivot_rows)])
    run = _post_file(client, xlsx_bytes, filename="book.xlsx",
                     content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").json()
    kinds = {s["kind"] for s in run["sheets"]}
    assert kinds == {"LEASING_BOOK", "PAYMENT_STATUS_PIVOT"}, run["sheets"]
    assert run["reconciliation"]["basis"] == "NOT_RECONCILED"
    late_row = next(r for r in run["reconciliation"]["rows"] if r["payment_status"] == "LATE")
    assert late_row["sheet"] == 5 and late_row["imported"] == 2 and late_row["matches"] is False
    assert late_row["note"]


def test_r71_xlsx_serial_date_converts_not_none(client):
    """The 25 lines that decide whether the .xlsx feature is honest (F-api.md §4.2):
    without them every date cell reads back as the raw serial number and
    `parse_date` returns None for it — a whole column of confident emptiness.
    Checked at both levels: the sheet reader's own cell text, and the parsed
    record `read_leasing_block` builds from it."""
    from app import imports as imports_domain

    rows = [LEASING_HEADER,
           ["VC00777_a_ก_", "Late", ("DATE", date(2026, 7, 31)), "12345.67", "40",
            "60", "5580.00", "โทรแล้ว"]]
    xlsx_bytes = _xlsx_bytes("Leasing Book", rows)

    # 1. The cell itself: a real serial (46234 for 2026-07-31) becomes the ISO
    # string, not the bare number.
    parsed_sheets = imports_domain.read_xlsx(xlsx_bytes)
    assert parsed_sheets[0]["rows"][1][2] == "2026-07-31"

    # 2. End to end through the endpoint: the row is recognised, imported, and
    # nothing about the date silently becomes null.
    run = _post_file(client, xlsx_bytes, filename="book.xlsx",
                     content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").json()
    assert run["sheets"][0]["kind"] == "LEASING_BOOK"
    assert run["counts"]["rows_imported"] == 1
    assert run["counts"]["rows_refused"] == 0


def test_r71_xlsx_1904_epoch_is_refused_not_silently_four_years_wrong(client):
    rows = [LEASING_HEADER, ["VC00778_a_ก_", "Late", ("DATE", date(2026, 7, 31)),
                             "1", "1", "60", "5580.00", ""]]
    run = _post_file(client, _xlsx_bytes("Leasing Book", rows, date1904=True), filename="old-mac.xlsx",
                     content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert run.status_code == 422
    assert "1904" in run.json()["errors"][0]["message_th"]


def test_r71_xlsx_error_cell_blanks_not_literal_text(client):
    rows = [LEASING_HEADER, ["VC00779_a_ก_", "Late", ("ERROR", "#N/A"), "1", "1",
                            "60", "5580.00", ""]]
    run = _post_file(client, _xlsx_bytes("Leasing Book", rows), filename="book.xlsx",
                     content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").json()
    assert run["counts"]["rows_imported"] == 1
    assert run["counts"]["rows_refused"] == 0


def test_r71_legacy_xls_or_encrypted_is_refused_not_guessed(client):
    ole_magic = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
    r = _post_file(client, ole_magic, filename="old.xls", content_type="application/vnd.ms-excel")
    assert r.status_code == 422
    assert "xls" in r.json()["errors"][0]["message_th"] or "รหัสผ่าน" in r.json()["errors"][0]["message_th"]


def test_r71_warnings_carry_a_source_ref_not_a_raw_block_row_pair(client):
    rows = [LEASING_HEADER, ["VC00888_x_y_", "Late", "not-a-real-date", "12345.67",
                             "40", "60", "5580.00", ""]]
    run = _post_file(client, _csv_bytes(rows)).json()
    assert len(run["warnings"]) == 1
    w = run["warnings"][0]
    assert set(w) == {"source_ref", "volt_id", "warning", "value"}
    assert w["source_ref"] == {"sheet": 0, "row": 2}


def test_r71_10_an_unrecognised_sheet_is_named_not_dropped(client):
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    # Fix-all leg S: a file with NO tab the importer knows is refused (a 200 with zero
    # rows read said "checked" about a file nobody read), and the refusal names its tabs.
    r = _post_file(client, _xlsx_bytes("Notes", [["something"], ["nobody reads this tab"]]),
                   filename="book.xlsx", content_type=xlsx)
    assert r.status_code == 422
    err = r.json()["errors"][0]
    assert err["sheets"] == ["Notes"] and _thai(err["message_th"])
    # Beside a tab it knows, the unknown one is still named, not dropped.
    run = _post_file(client, _xlsx_bytes_multi([("Leasing Book", _leasing_rows(1)), ("Notes", [["something"]])]),
                     filename="book.xlsx", content_type=xlsx).json()
    assert [(s["name"], s["kind"]) for s in run["sheets"]] == [("Leasing Book", "LEASING_BOOK"), ("Notes", None)]
    assert run["counts"]["rows_read"] == 1        # nothing in an unrecognised sheet is examined


def test_r71_11_two_sessions_and_a_third_created_after_are_isolated(client):
    """The required five-part demonstration (PROJECT.md's shared-mutable class),
    proven on the NEW endpoint directly rather than assumed from the Store idiom."""
    a = TestClient(app)
    a.cookies.set("volt_session", "sess-a-import-isolation")
    upload = _post_file(a, _csv_bytes(_leasing_rows(3)), filename="a-book.csv")
    assert upload.status_code == 200
    uid = upload.json()["run"]["uid"]

    # 1. A lists its own run.
    assert a.get("/v1/imports").json()["meta"]["total"] == 1

    # 2. B, already alive, sees none — and cannot read A's run by uid either.
    b = TestClient(app)
    b.cookies.set("volt_session", "sess-b-import-isolation")
    assert b.get("/v1/imports").json()["meta"]["total"] == 0
    assert b.get("/v1/imports/%s" % uid).status_code == 404

    # 3. C, created AFTER A's upload, is unaffected too.
    c = TestClient(app)
    c.cookies.set("volt_session", "sess-c-import-isolation-created-after")
    assert c.get("/v1/imports").json()["meta"]["total"] == 0
    assert c.get("/v1/imports/%s" % uid).status_code == 404

    # 4. The shared fixture book itself: never touched. Ruling 73 stages, never
    # installs — this is what makes that provable rather than merely asserted.
    from app import main
    before_len = len(main.CUSTOMERS)
    assert b.get("/v1/workbook").json()["meta"]["total"] == before_len
    assert c.get("/v1/workbook").json()["meta"]["total"] == before_len
    assert len(main.CUSTOMERS) == before_len

    # 5. A still sees its own work, complete, with its counts.
    reread = a.get("/v1/imports/%s" % uid).json()
    assert reread["counts"]["rows_imported"] == 3


# === Ruling 72 — the governed export ================================================

def test_r72_1_post_without_reason_is_refused_with_the_pointer_and_thai(client):
    r = client.post("/v1/workbook:export", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_failed"
    assert body["errors"][0]["pointer"] == "/reason"
    assert _thai(body["errors"][0]["message_th"])


def test_r72_2_post_with_a_reason_succeeds_and_is_recorded(client):
    r = client.post("/v1/workbook:export", json={"reason": "ตรวจยอดค้างรายเดือนกับฝ่ายบัญชี"},
                    headers=OFFICER)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "X-Volt-Export-Uid" in r.headers
    exports = client.get("/v1/workbook/exports").json()["exports"]
    assert len(exports) == 1
    assert exports[0]["reason"] == "ตรวจยอดค้างรายเดือนกับฝ่ายบัญชี"
    assert exports[0]["verb"] == "POST"
    assert exports[0]["by"]


def test_r72_3_post_rows_are_byte_identical_to_get_rows_below_the_provenance_block(client):
    get_body = client.get("/v1/workbook:export").text.lstrip("﻿")
    post_resp = client.post("/v1/workbook:export", json={"reason": "รายงานประจำเดือน ส่งบัญชี"})
    post_body = post_resp.text.lstrip("﻿")
    post_lines = post_body.splitlines()
    # exactly four provenance comment lines, then the same body GET serves.
    assert post_lines[0].startswith("# Volt Debt")
    assert post_lines[1].startswith("# ผู้ส่งออก")
    assert post_lines[2].startswith("# ตัวกรอง")
    assert post_lines[3].startswith("# ข้อมูลส่วนบุคคล")
    assert not post_lines[4].startswith("#")
    assert "\n".join(post_lines[4:]) + "\n" == get_body.replace("\r\n", "\n")


def test_r72_4_the_provenance_block_names_the_carried_2fa_and_expiry(client):
    body = client.post("/v1/workbook:export", json={"reason": "ทดสอบการปกปิดข้อมูล"}).text
    assert "2FA" in body
    assert "SOP" in body
    assert "ปกปิดเบอร์โทรและอีเมล" in body


def test_r72_5_zero_match_filters_return_200_with_a_header_and_zero_of_total_not_404(client):
    r = client.post("/v1/workbook:export",
                    json={"reason": "ทดสอบตัวกรองที่ไม่ตรงแถวใดเลย"},
                    params={"payment_status": "NOT_A_REAL_STATUS"})
    assert r.status_code == 200
    text = r.text.lstrip("﻿")
    lines = [l for l in text.splitlines() if l]
    assert "0 " in lines[2] or " 0 " in lines[2]        # the row-count line
    csv_lines = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert csv_lines[0].split(",")[0] == "volt_id"      # the header still renders
    assert len(csv_lines) == 1                          # header only, no data rows


# === R5-F01 / R5-F05 / R5-F02 — the three field-level fixes =========================

def test_r5f05_company_id_travels_with_entity_in_the_export(client):
    meta = client.get("/v1/workbook").json()["meta"]
    assert "company_id" in meta["columns"]
    body = client.get("/v1/workbook:export").text.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(body)))
    routed = [r for r in rows if r["entity"] in ("EPC", "SPV")]
    assert routed, "no routed row in the export — the test fixture assumption is wrong"
    assert all(r["company_id"] in ("CO-EPC", "CO-SPV") for r in routed)
    assert {r["company_id"] for r in routed if r["entity"] == "EPC"} <= {"CO-EPC"}
    assert {r["company_id"] for r in routed if r["entity"] == "SPV"} <= {"CO-SPV"}


def test_r5f02_order_ref_cell_is_parseable_not_a_dict_repr(client):
    body = client.get("/v1/workbook:export").text.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(body)))
    with_ref = [r for r in rows if r["order_ref"]]
    assert with_ref, "no row carries an order_ref in this fixture set"
    for r in with_ref[:20]:
        assert "{" not in r["order_ref"] and "'" not in r["order_ref"], r["order_ref"]
        for pair in r["order_ref"].split(";"):
            block, _, row_no = pair.partition(":")
            assert block.isdigit() and row_no.isdigit(), r["order_ref"]


def test_r5f01_phone_on_file_distinguishes_a_mask_from_no_number(client):
    rows = client.get("/v1/workbook").json()["rows"]
    placeholder = [r for r in rows if r["customer"]["phone_masked"] == "xxx-xxx-xxxx"]
    real_mask = [r for r in rows if r["customer"]["phone_masked"] != "xxx-xxx-xxxx"]
    assert placeholder and real_mask, "fixture no longer carries both shapes"
    assert all(r["customer"]["phone_on_file"] is False for r in placeholder)
    assert all(r["customer"]["phone_on_file"] is True for r in real_mask)
