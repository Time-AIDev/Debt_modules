"""2026-09-25: New Order Master-6 (23.3 MB) ran staging out of memory at 1 and 2 GiB.
The reader streams each tab now, and a file past Cloud Run's 32 MiB body limit comes
in parts. Every workbook here is SYNTHETIC."""
import io
import subprocess
import sys
import tracemalloc
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app import imports
from app.main import app
from tests.test_round5_data_flow import _xlsx_bytes_multi
from tests.test_sheet_install import _workbook

K1 = "91000000001_Kanda_กานดา_EPCZ"
ROWS = [["VOLT ID", "Payment Status", "Note"], [K1, "Current", "สวัสดี"], ["", "", ""], ["x_y", "Late", "#N/A"]]
OFFICER = {"X-Volt-Officer": "nantapol", "X-Volt-Role": "MANAGER"}


def test_hot_path_keeps_support_for_any_xlsx_main_namespace():
    row = ET.fromstring(
        '<row xmlns="http://purl.oclc.org/ooxml/spreadsheetml/main">'
        '<c r="A1" t="inlineStr"><is><t>strict</t></is></c></row>')

    assert imports._row_cells(row, [], set(), False) == ({0: "strict"}, 1)


def _with_formatted_tail(raw, rows=25000, cols=26):
    """The same workbook plus `rows` rows of styled-but-empty cells under the data —
    what a formula/format filled down to row 50,000 leaves in the real file."""
    src = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                cells = "".join('<c r="%s{r}" s="0"/>' % chr(65 + i) for i in range(cols))
                tail = "".join('<row r="%d">%s</row>' % (r, cells.replace("{r}", str(r))) for r in range(100, 100 + rows))
                data = data.replace(b"</sheetData>", tail.encode() + b"</sheetData>")
            zf.writestr(info, data)
    return out.getvalue()


def _formatted_tail_reader_peak():
    plain = _xlsx_bytes_multi([("Done - Cash", ROWS)])
    padded = _with_formatted_tail(plain)
    assert imports.read_xlsx(padded) == imports.read_xlsx(plain)
    tracemalloc.start()
    imports.read_xlsx(padded)
    _now, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


def test_a_formatted_tail_reads_the_same_rows_in_little_memory():
    # tracemalloc is process-wide. Run the measurement in a clean interpreter so
    # background upload/schedule threads from earlier integration tests cannot be
    # charged to this reader call and make the suite-order-dependent check flaky.
    code = (
        "from tests.test_upload_scale import _formatted_tail_reader_peak; "
        "print(_formatted_tail_reader_peak())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    peak = int(result.stdout.strip().splitlines()[-1])
    # The whole-tree reader held every one of the 650,000 empty cells at once.
    assert peak < 15 * 1024 * 1024, peak


def test_parts_join_in_any_order_once():
    uid = str(uuid.uuid4())
    imports.put_part(uid, 1, 2, b"world", "a")
    imports.put_part(uid, 0, 2, b"hello ", "a")
    assert imports.take_upload(uid, "a") == b"hello world"
    with pytest.raises(imports.UploadRefused):
        imports.take_upload(uid, "a")          # single use


def test_parts_refuse_what_is_missing_foreign_or_malformed():
    uid = str(uuid.uuid4())
    imports.put_part(uid, 0, 2, b"x", "a")
    with pytest.raises(imports.UploadRefused):
        imports.take_upload(uid, "a")          # part 1 never came
    with pytest.raises(imports.UploadRefused):
        imports.take_upload(uid, "b")          # someone else's upload
    with pytest.raises(imports.UploadRefused):
        imports.put_part(uid, 1, 2, b"y", "b")
    with pytest.raises(imports.UploadRefused):
        imports.put_part("../etc", 0, 1, b"x", "a")
    with pytest.raises(imports.UploadRefused):
        imports.put_part(str(uuid.uuid4()), 2, 2, b"x", "a")
    with pytest.raises(imports.UploadRefused):
        imports.put_part(str(uuid.uuid4()), 0, imports.MAX_BYTES // imports.PART_BYTES + 2, b"x", "a")
    with pytest.raises(imports.UploadRefused):
        imports.put_part(str(uuid.uuid4()), 0, 1, b"x" * (imports.PART_BYTES + 1), "a")


def test_the_import_route_reads_a_file_sent_in_parts_as_if_sent_whole():
    client = TestClient(app)
    raw = _workbook()
    whole = client.post("/v1/imports", content=raw, headers={**OFFICER, "X-Volt-Filename": "a.xlsx"})
    uid = str(uuid.uuid4())
    half = len(raw) // 2
    for i, part in enumerate((raw[:half], raw[half:])):
        r = client.post("/v1/imports/parts/%s/%d?of=2" % (uid, i), content=part, headers=OFFICER)
        assert r.status_code == 200, r.text
    parted = client.post("/v1/imports", content=b"", headers={**OFFICER, "X-Volt-Filename": "a.xlsx", "X-Volt-Upload": uid})
    assert parted.status_code == whole.status_code == 200, parted.text
    assert parted.json()["sheets"] == whole.json()["sheets"]
    again = client.post("/v1/imports", content=b"", headers={**OFFICER, "X-Volt-Upload": uid})
    assert again.status_code == 422


def test_a_csv_keeps_the_25_mb_cap():
    with pytest.raises(imports.UploadRefused):
        imports.decode_csv(b"a," * (imports.CSV_MAX_BYTES // 2 + 1))


def test_one_upload_in_flight_per_person():
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    imports.put_part(first, 0, 2, b"x", "a")
    imports.put_part(second, 0, 1, b"y", "a")
    with pytest.raises(imports.UploadRefused):
        imports.take_upload(first, "a")        # dropped when the second one started
    assert imports.take_upload(second, "a") == b"y"


def test_a_row_after_sheet_data_is_not_a_sheet_row():
    plain = _xlsx_bytes_multi([("Done - Cash", ROWS)])
    src, out = zipfile.ZipFile(io.BytesIO(plain)), io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b"</worksheet>", b'<extLst><row r="99"><c r="A99" t="inlineStr"><is><t>X</t></is></c></row></extLst></worksheet>')
            zf.writestr(info, data)
    assert imports.read_xlsx(out.getvalue()) == imports.read_xlsx(plain)


def test_a_part_route_refuses_a_bad_id_before_reading():
    r = TestClient(app).post("/v1/imports/parts/not-a-uuid/0?of=1", content=b"x", headers=OFFICER)
    assert r.status_code == 422
