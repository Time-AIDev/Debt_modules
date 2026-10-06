"""Ruling 71 — the officer's own upload, parsed with the existing importer's own
rules, staged and reported on.

Arina, 2026-09-24 — reverses ruling 73 ("never installed"): the New Order Master IS
the book now, so a MANAGER/OWNER may install a checked file (`install` below, the
`?install=true` door). The plain check stays open to every role and still installs
nothing. The payload is built by the importer's own `assemble_payload`, the same
function the CLI uses, so an uploaded .xlsx and the Drive render become one book.

`scripts/import_master_sheet.py` is IMPORTED, not copied — copying it would be the
second-pattern MAJOR (ruling 36) on the one file whose rules ruling 71 explicitly
adopts. That script reads a Drive markdown *text render*, which a browser upload is
not, so three of its rules do not survive unchanged — see `_clean_cell` below and
`_classify_sheet`'s own docstring for which ones.

Nothing here does client-side-style arithmetic either: every count in the run report
is produced once, in this module, and served — never recomputed from other served
numbers by a caller (`api.js:1-4`'s rule, applied to the server that OWNS the numbers).
"""
import csv
import importlib.util
import io
import re
import threading
import time
import zipfile
from collections import Counter, OrderedDict
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from . import book as book_domain
from . import clock
from .config import settings
from .integrations import env
from .session import Store

# 2026-09-11: raised 5 MB -> 25 MB on request, for the whole-book exports the team
# actually produces. See the router for the two enforcement points.
#
# 2026-09-25: 25 MB -> 100 MB, and the zip ceiling 200 MB -> 1 GiB. New Order Master-6
# was 23.3 MB zipped / 198 MB inflated (Done - Cash alone: 97.7 MB of XML, formulas
# filled down to row 49,764 for ~600 customers) and grows ~7 MB a month. The sheet
# reader streams each tab now (_sheet_rows), so memory follows the rows KEPT, not the
# XML size; the inflate ceiling stays as the zip-bomb guard. A body over Cloud Run's
# 32 MiB request limit arrives in parts (put_part / take_upload below).
# 2026-10-06: actual inflation capped at 512 MiB; kept data, shared strings,
# individual cells and processing time also have independent bounds. Styled
# blank cells still stream and do not consume the kept-data budget.
MAX_BYTES = 100 * 1024 * 1024
MAX_ZIP_INFLATE = 512 * 1024 * 1024
CSV_MAX_BYTES = 25 * 1024 * 1024
MAX_MB = MAX_BYTES // (1024 * 1024)
XLSX_MAX_COLUMNS = 16384  # Excel's own column limit, checked before list allocation.
XLSX_MAX_CELL_CHARS = 32767
XLSX_MAX_XML_TOKEN_BYTES = 1024 * 1024


def _xlsx_refused(detail="The workbook exceeds a safe parsing limit."):
    raise UploadRefused("/file", detail, "ไฟล์ตารางเกินขอบเขตที่ระบบอ่านได้อย่างปลอดภัย กรุณาลดขนาดไฟล์")


class _XlsxBudget:
    """Whole-workbook bounds; blank formatted cells are processed, never retained."""
    def __init__(self):
        self.started = time.monotonic()
        self.seconds = float(env("XLSX_PARSE_MAX_SECONDS", "120"))
        self.max_processed = int(env("XLSX_MAX_PROCESSED_CELLS", "10000000"))
        self.max_kept = int(env("XLSX_MAX_KEPT_CELLS", "1000000"))
        self.max_text = int(env("XLSX_MAX_KEPT_TEXT_BYTES", str(64 * 1024 * 1024)))
        self.max_shared = int(env("XLSX_MAX_SHARED_STRINGS", "250000"))
        self.max_shared_bytes = int(env("XLSX_MAX_SHARED_STRING_BYTES", str(16 * 1024 * 1024)))
        self.processed = self.kept = self.text_bytes = self.shared_bytes = 0

    def check(self):
        if time.monotonic() - self.started > self.seconds:
            _xlsx_refused("The workbook exceeded the parsing time limit.")

    def retain(self, width, cells):
        self.kept += width
        self.text_bytes += sum(len(value.encode("utf-8")) for value in cells.values())
        if self.kept > self.max_kept or self.text_bytes > self.max_text:
            _xlsx_refused()
        self.check()


class _SafeXmlReader:
    """Reject huge XML text/attribute tokens before ElementTree builds them."""
    def __init__(self, source, budget=None):
        self.source, self.budget = source, budget
        self.token_bytes, self.tail = 0, b""

    def read(self, size=-1):
        data = self.source.read(min(size, 64 * 1024) if size >= 0 else 64 * 1024)
        scan = self.tail + data
        if b"<!DOCTYPE" in scan or b"<!ENTITY" in scan:
            _xlsx_refused("Workbook XML declarations are not allowed.")
        self.tail = scan[-16:]
        pieces = re.split(br"[<>]", data)
        for index, piece in enumerate(pieces):
            self.token_bytes = self.token_bytes + len(piece) if index == 0 else len(piece)
            if self.token_bytes > XLSX_MAX_XML_TOKEN_BYTES:
                _xlsx_refused("A workbook XML token exceeds the safe limit.")
        if self.budget:
            self.budget.check()
        return data


def _small_xml(zf, part, cap=4 * 1024 * 1024):
    with zf.open(part) as fh:
        raw = fh.read(cap + 1)
    if len(raw) > cap or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        _xlsx_refused("Workbook metadata exceeds a safe parsing limit.")
    return ET.fromstring(raw)

_XLSX_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


# --- the existing importer, loaded as a module, never copied ----------------------

def _load_import_master_sheet():
    # Two layouts, one file. In a checkout the importer sits at <root>/scripts/; in the
    # container image `scripts/deploy_gcp.sh` stages that same file to /app/scripts/,
    # exactly as it stages the built interface to /app/static, because `--source
    # backend` cannot see anything above backend/. This is still IMPORTED, not copied:
    # ruling 36's second-pattern MAJOR is about a second copy of these rules living in
    # the source tree, not about packaging the one file into an image. The checkout is
    # tried first, so a stale staged copy can never shadow the real one.
    here = Path(__file__).resolve()
    candidates = (
        here.parents[2] / "scripts" / "import_master_sheet.py",  # repo checkout
        here.parents[1] / "scripts" / "import_master_sheet.py",  # container image
    )
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("volt_import_master_sheet", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    raise FileNotFoundError(
        "import_master_sheet.py not found. Looked in: "
        + ", ".join(str(c) for c in candidates)
        + ". In a container it is staged by scripts/deploy_gcp.sh before the build."
    )


_IMS = _load_import_master_sheet()


class UploadRefused(Exception):
    """A whole-file refusal — nothing is recognisable enough to report on. Carries
    the same three things every §1a fallback in this backend carries: a pointer, an
    English message and a Thai one. Never partial: no run is created for one of
    these (F-api.md §4.1's rule — "never a partial parse")."""

    def __init__(self, pointer, message, message_th, extensions=None):
        self.pointer = pointer
        self.message = message
        self.message_th = message_th
        self.extensions = extensions or {}


# --- an upload in parts (2026-09-25) -------------------------------------------------
# Cloud Run refuses a request body over 32 MiB, and New Order Master grows ~7 MB a
# month. The browser sends a big file as parts of PART_BYTES; the upload endpoint then
# names the parts by id (X-Volt-Upload) instead of carrying a body. Parts are joined
# once and forgotten: take_upload pops them.
# ponytail: held in this process, which holds because the service runs one instance
# (--max-instances 1, the same premise as session.Store). Move the parts to Postgres
# or a bucket if the service ever scales out.
PART_BYTES = 8 * 1024 * 1024
PART_TTL_SECONDS = 15 * 60
_UPLOAD_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_PARTS = {}
_PARTS_LOCK = threading.Lock()


def _forget_stale_parts(now):
    for key in [k for k, u in _PARTS.items() if now - u["at"] > PART_TTL_SECONDS]:
        del _PARTS[key]


def check_part(upload_id, index, of):
    """The id and position alone — checked before the part's body is read."""
    if not _UPLOAD_ID.match(upload_id or ""):
        raise UploadRefused("/upload_id", "The upload id is not a uuid.", "รหัสการอัปโหลดไม่ถูกต้อง")
    if not (0 < of and of * PART_BYTES <= MAX_BYTES + PART_BYTES and 0 <= index < of):
        raise UploadRefused("/part", "Part %s of %s is out of range (the cap is %d MB)." % (index, of, MAX_MB),
                            "ลำดับชิ้นไฟล์ไม่ถูกต้อง หรือไฟล์ใหญ่เกิน %d MB" % MAX_MB, {"cap_bytes": MAX_BYTES})


def put_part(upload_id, index, of, data, by):
    """Holds part `index` (0-based) of `of` for `by`. Returns how many parts are held.
    One upload in flight per person: starting another drops their older one, so an
    abandoned upload cannot sit on the shared ceiling for everyone else."""
    check_part(upload_id, index, of)
    if len(data) > PART_BYTES:
        raise UploadRefused("/part", "A part is larger than %d bytes." % PART_BYTES,
                            "ชิ้นไฟล์ใหญ่เกินกำหนด", {"part_bytes": PART_BYTES})
    from .production_unit import enabled
    if enabled():
        from .durable_uploads import put
        return put(upload_id, index, of, bytes(data), by)
    with _PARTS_LOCK:
        now = time.monotonic()
        _forget_stale_parts(now)
        for key in [k for k, u in _PARTS.items() if u["by"] == by and k != upload_id]:
            del _PARTS[key]
        held = sum(len(b) for u in _PARTS.values() for b in u["parts"].values())
        if held + len(data) > 2 * MAX_BYTES:
            raise UploadRefused("/part", "Too many uploads are in flight; try again in a few minutes.",
                                "มีการอัปโหลดค้างอยู่มากเกินไป ลองใหม่อีกครั้งในไม่กี่นาที")
        upload = _PARTS.setdefault(upload_id, {"of": of, "by": by, "parts": {}, "at": now})
        if upload["of"] != of or upload["by"] != by:
            raise UploadRefused("/upload_id", "This upload id belongs to another upload.",
                                "รหัสการอัปโหลดนี้เป็นของการอัปโหลดอื่น")
        upload["parts"][index] = bytes(data)
        upload["at"] = now
        total = sum(len(b) for b in upload["parts"].values())
        if total > MAX_BYTES:
            del _PARTS[upload_id]
            raise UploadRefused("/file", "The file is larger than the %d MB cap." % MAX_MB,
                                "ไฟล์ใหญ่เกิน %d MB" % MAX_MB, {"cap_bytes": MAX_BYTES})
        return len(upload["parts"])


def take_upload(upload_id, by):
    """The joined bytes of a complete upload, once. Missing parts, a stale id or
    someone else's id all refuse the same way — nothing is guessed."""
    from .production_unit import enabled
    if enabled():
        from .durable_uploads import take
        return take(upload_id, by)
    with _PARTS_LOCK:
        _forget_stale_parts(time.monotonic())
        upload = _PARTS.get(upload_id or "")
        if upload is None or upload["by"] != by or len(upload["parts"]) != upload["of"]:
            raise UploadRefused("/upload_id", "The upload is missing, incomplete or expired; send the file again.",
                                "ไฟล์ที่อัปโหลดไม่ครบหรือหมดเวลา — อัปโหลดใหม่อีกครั้ง")
        del _PARTS[upload_id]
    return b"".join(upload["parts"][i] for i in range(upload["of"]))


def discard_upload(upload_id, by):
    """Drop an incomplete chunk set after the browser aborts an upload."""
    from .production_unit import enabled
    if enabled():
        from .durable_uploads import discard
        return discard(upload_id, by)
    with _PARTS_LOCK:
        upload = _PARTS.get(upload_id or "")
        if upload is None or upload["by"] != by:
            return False
        del _PARTS[upload_id]
        return True


# --- per-session state, the established remedy (session.py, ruling 43) ------------

class ImportState:
    def __init__(self):
        self.runs = OrderedDict()
        self._counter = 0

    def uid(self, prefix):
        self._counter += 1
        return "%s-%05d" % (prefix, self._counter)


_store = Store(ImportState, key="imports.state")


def for_current() -> ImportState:
    return _store.for_current()


def reset():
    _store.reset()


# --- sniffing -----------------------------------------------------------------

def sniff_kind(raw: bytes):
    """The declared content type is a hint; the magic bytes decide (ruling 71's own
    words) — a `.xlsx` renamed `.csv` must be read as what it is."""
    if raw[:4] == b"PK\x03\x04" or raw[:4] == b"PK\x05\x06" or raw[:4] == b"PK\x07\x08":
        return "XLSX"
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "OLE"          # legacy .xls OR a password-protected .xlsx — see §4.2
    return "MAYBE_CSV"        # decided by whether it decodes, next


def decode_csv(raw: bytes):
    """`utf-8-sig` first (handles Excel's BOM), `cp874` second (Excel-on-Windows'
    Thai CSV encoding) — detection, not a guess: cp874 Thai reliably fails a UTF-8
    decode. Returns (encoding_used, text) or raises UploadRefused.

    A .csv keeps the 25 MB cap: only the .xlsx reader streams, and a CSV is held as
    text, raw rows and cleaned rows at once (a 100 MB one peaked past 1 GB)."""
    if len(raw) > CSV_MAX_BYTES:
        raise UploadRefused("/file", "A .csv is capped at %d MB; save it as .xlsx." % (CSV_MAX_BYTES // 2 ** 20),
                            "ไฟล์ .csv ใหญ่เกิน %d MB — บันทึกเป็น .xlsx แล้วอัปโหลดใหม่" % (CSV_MAX_BYTES // 2 ** 20),
                            {"cap_bytes": CSV_MAX_BYTES})
    try:
        return "utf-8-sig", raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return "cp874", raw.decode("cp874")
    except UnicodeDecodeError:
        raise UploadRefused(
            "/file",
            "The file is neither valid UTF-8 nor cp874 (Excel/Windows Thai CSV).",
            "อ่านไฟล์ไม่ได้ — บันทึกใหม่เป็น CSV UTF-8 แล้วลองอีกครั้ง",
        )


def _clean_cell(value):
    """The markdown pipeline's `unescape()` minus the half that does not survive a
    real file (F-api.md §4.3 rule 6): ERROR-token blanking is KEPT (`#N/A` etc. must
    still read as empty, or `month_cell` renders it as literal text) — but the
    backslash-unescape is DROPPED, because it would silently delete a literal `\\`
    from a real Thai note, which the markdown render never contained one of."""
    text = ("" if value is None else str(value)).strip()
    return "" if text in _IMS.ERRORS else text


def _clean_rows(rows):
    return [[_clean_cell(c) for c in row] for row in rows]


# --- .xlsx, stdlib only (zipfile + ElementTree) — no new dependency ----------------

def _local(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _tag_prefix(tag):
    """The once-per-document/row namespace prefix, including its closing brace."""
    end = tag.find("}")
    return tag[:end + 1] if end >= 0 else ""


def _col_index(ref):
    """"C7" -> 2 (0-based), after checking Excel's complete cell-reference limits."""
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", ref)
    if not match or int(match[2]) > 1048576:
        _xlsx_refused("An XLSX cell reference is invalid.")
    n = 0
    for ch in match[1]:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    if n > XLSX_MAX_COLUMNS:
        _xlsx_refused("An XLSX column exceeds Excel's column limit.")
    return n - 1


def _shared_strings(zf, budget=None):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out = []
    with zf.open("xl/sharedStrings.xml") as fh:   # streamed, like _sheet_rows
        prefix, root = None, None
        for event, si in ET.iterparse(_SafeXmlReader(fh, budget), events=("start", "end")):
            if prefix is None:
                root = si
                prefix = _tag_prefix(si.tag)
                si_tag, text_tag = prefix + "si", prefix + "t"
            if event == "end" and si.tag == si_tag:
                value = "".join(t.text or "" for t in si.iter() if t.tag == text_tag)
                if len(value) > XLSX_MAX_CELL_CHARS:
                    _xlsx_refused("An XLSX cell exceeds Excel's text limit.")
                out.append(value)
                if budget:
                    budget.shared_bytes += len(value.encode("utf-8"))
                    if len(out) > budget.max_shared or budget.shared_bytes > budget.max_shared_bytes:
                        _xlsx_refused("The workbook's shared strings exceed the safe memory limit.")
                si.clear()
                root.clear()
    return out


def _date_style_indices(zf):
    """Which `cellXfs` indices are formatted as a date, so a numeric cell under one
    of them is a serial day-count, not a plain number. Built-in numFmtIds 14-22 and
    45-47 are date/time formats in every localisation; custom ones (id >= 164) are
    read from their own `formatCode` and treated as a date if the code carries a
    date token (y/m/d)."""
    if "xl/styles.xml" not in zf.namelist():
        return set()
    root = _small_xml(zf, "xl/styles.xml")
    custom_date_ids = set()
    for numfmts in root:
        if _local(numfmts.tag) != "numFmts":
            continue
        for nf in numfmts:
            code = (nf.get("formatCode") or "").lower()
            if re.search(r"[ymd]", code):
                custom_date_ids.add(int(nf.get("numFmtId")))
    builtin_date_ids = set(range(14, 23)) | set(range(45, 48))
    date_ids = builtin_date_ids | custom_date_ids
    date_style_idx = set()
    for cellxfs in root:
        if _local(cellxfs.tag) != "cellXfs":
            continue
        for i, xf in enumerate(cellxfs):
            fmt_id = int(xf.get("numFmtId") or 0)
            if fmt_id in date_ids:
                date_style_idx.add(i)
    return date_style_idx


def _workbook_pr_1904(zf):
    root = _small_xml(zf, "xl/workbook.xml")
    for child in root:
        if _local(child.tag) == "workbookPr":
            return (child.get("date1904") or "").strip() in ("1", "true")
    return False


def _workbook_sheets(zf):
    """[(name, target_part)], in the workbook's own tab order."""
    wb_root = _small_xml(zf, "xl/workbook.xml")
    rels = {}
    if "xl/_rels/workbook.xml.rels" in zf.namelist():
        rel_root = _small_xml(zf, "xl/_rels/workbook.xml.rels")
        for rel in rel_root:
            rels[rel.get("Id")] = rel.get("Target")
    out = []
    for child in wb_root:
        if _local(child.tag) != "sheets":
            continue
        for sheet in child:
            name = sheet.get("name")
            rid = sheet.get("{%s}id" % _XLSX_NS["r"])
            target = rels.get(rid, "worksheets/sheet%d.xml" % (len(out) + 1))
            if not target.startswith("worksheets/") and "worksheets/" not in target:
                target = "worksheets/" + target.lstrip("/")
            part = "xl/" + target if not target.startswith("xl/") else target
            out.append((name, part))
            if len(out) > 128:
                _xlsx_refused("The workbook has too many worksheets.")
    return out


def _serial_to_iso(serial, epoch_1904):
    try:
        days = float(serial)
    except (TypeError, ValueError):
        return None
    base = date(1904, 1, 1) if epoch_1904 else date(1899, 12, 30)
    try:
        return (base + timedelta(days=days)).isoformat()
    except OverflowError:
        return None


def _row_cells(row_el, shared, date_styles, epoch_1904, tag_prefix=None, budget=None):
    """({column index: text}, width) for one `<row>` element."""
    prefix = _tag_prefix(row_el.tag) if tag_prefix is None else tag_prefix
    cell_tag, value_tag, inline_tag, text_tag = (
        prefix + "c", prefix + "v", prefix + "is", prefix + "t")
    cells = {}
    width = 0
    for c in row_el:
        if c.tag != cell_tag:
            continue
        if budget:
            budget.processed += 1
            if budget.processed > budget.max_processed:
                _xlsx_refused("The workbook has too many cells to process safely.")
        ref = c.get("r") or ""
        idx = _col_index(ref) if ref else width
        if idx >= XLSX_MAX_COLUMNS:
            _xlsx_refused("An XLSX row exceeds Excel's column limit.")
        width = max(width, idx + 1)
        ctype = c.get("t")
        style = int(c.get("s") or 0)
        v_el = next((e for e in c if e.tag == value_tag), None)
        is_el = next((e for e in c if e.tag == inline_tag), None)
        if ctype == "s":
            i = int(v_el.text) if v_el is not None and v_el.text else 0
            if i < 0 or i >= len(shared):
                _xlsx_refused("An XLSX shared-string reference is invalid.")
            text = shared[i]
        elif ctype == "inlineStr":
            text = "".join(t.text or "" for t in (is_el.iter() if is_el is not None else [])
                           if t.tag == text_tag)
        elif ctype == "str":
            text = v_el.text if v_el is not None else ""
        elif ctype == "e":
            # A spreadsheet error token — the SAME set the markdown pipeline
            # blanks (ERRORS), read off the cell's own type rather than its
            # text, which is the more reliable signal a real file gives us.
            text = v_el.text if v_el is not None else "#N/A"
        elif ctype == "b":
            text = "TRUE" if (v_el is not None and v_el.text == "1") else "FALSE"
        elif v_el is None:
            # `<f>` present (or absent, on a wholly blank cell) with no
            # cached `<v>` — a formula never opened/recalculated in a
            # spreadsheet application, or simply nothing here. Empty, never
            # a guessed zero (F-api.md §4.2: "the cell is empty ... never
            # zero"). `f_el` itself is not read further; its presence is
            # not needed to decide this — the ABSENCE of `<v>` already is.
            text = ""
        elif style in date_styles:
            text = _serial_to_iso(v_el.text, epoch_1904) or (v_el.text or "")
        else:
            text = v_el.text or ""
        value = "" if text is None else str(text)
        if len(value) > XLSX_MAX_CELL_CHARS:
            _xlsx_refused("An XLSX cell exceeds Excel's text limit.")
        cells[idx] = value
    return cells, width


def _sheet_rows(zf, part, shared, date_styles, epoch_1904, budget=None):
    """(rows, the 1-based spreadsheet row number of each), cells already cleaned.

    Streamed (2026-09-25): ET.fromstring built the whole tab as a tree first, and
    New Order Master-6's Done - Cash (97.7 MB of XML, 3.3 M formatted-but-empty cells)
    took the process past 2 GiB on Cloud Run. Each `<row>` is read, then dropped, so
    memory follows the rows kept, not the size of the XML."""
    if part not in zf.namelist():
        return [], []
    rows, numbers = [], []
    sheet_data = None
    with zf.open(part) as fh:
        prefix = None
        for event, el in ET.iterparse(_SafeXmlReader(fh, budget), events=("start", "end")):
            tag = el.tag
            if prefix is None:
                prefix = _tag_prefix(tag)
                sheet_data_tag, row_tag = prefix + "sheetData", prefix + "row"
            if tag == sheet_data_tag:
                sheet_data = el if event == "start" else None   # a <row> outside it is not a sheet row
                continue
            if event == "start":
                continue
            if tag != row_tag or sheet_data is None:
                continue
            cells, width = _row_cells(el, shared, date_styles, epoch_1904, prefix, budget)
            r = el.get("r") or ""
            el.clear()
            sheet_data.clear()   # drops the rows already read, so the tree never grows
            # A row keeps its own `<row r>` as its number: Excel omits empty rows, and
            # numbering by sequence moved every row below a gap up — a refusal then
            # named the wrong spreadsheet row. Nothing is padded, so one stray value at
            # row 1,048,576 costs one row. No `r` falls back to sequence; a row with
            # nothing in it is skipped.
            if not any(cells.values()):
                continue
            if budget:
                budget.retain(width, cells)
            numbers.append(int(r) if r.isdigit() else (numbers[-1] + 1 if numbers else 1))
            rows.append([_clean_cell(cells.get(i, "")) for i in range(width)])
    return rows, numbers


def read_xlsx(raw: bytes):
    """Returns [{"name": tab name, "rows": [[cell,...],...]}], one per tab, in
    workbook order. Raises UploadRefused for every case §4.2 names as a refusal
    rather than a guess."""
    if len(raw) > MAX_BYTES:
        _xlsx_refused()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise UploadRefused("/file", "Not a readable .xlsx (zip) file.",
                            "รองรับเฉพาะไฟล์ .csv และ .xlsx")
    with zf:
        try:
            return _read_xlsx_archive(zf)
        except (ET.ParseError, zipfile.BadZipFile, ValueError, EOFError, RuntimeError) as exc:
            raise UploadRefused("/file", "The XLSX workbook is malformed and cannot be read.",
                                "ไฟล์ XLSX เสียหายหรือรูปแบบไม่ถูกต้อง กรุณาบันทึกใหม่แล้วลองอีกครั้ง") from exc


def _read_xlsx_archive(zf):
    budget = _XlsxBudget()
    infos = zf.infolist()
    if len(infos) > 2048 or len({info.filename for info in infos}) != len(infos):
        _xlsx_refused("The workbook ZIP has too many or duplicate entries.")
    inflated = sum(i.file_size for i in infos)
    if inflated > MAX_ZIP_INFLATE:
        raise UploadRefused("/file", "The .xlsx inflates past the size this reader will extract.",
                            "ไฟล์ .xlsx นี้ขยายตัวใหญ่เกินกว่าที่ระบบอ่านได้",
                            {"inflated_bytes": inflated, "cap_bytes": MAX_ZIP_INFLATE})
    # Validate actual bytes, not only untrusted ZIP metadata. Discard each chunk;
    # parsing afterwards still streams worksheets rather than keeping XML trees.
    actual = 0
    for info in infos:
        with zf.open(info) as source:
            while chunk := source.read(64 * 1024):
                actual += len(chunk)
                if actual > MAX_ZIP_INFLATE:
                    _xlsx_refused()
                budget.check()
    if "xl/workbook.xml" not in zf.namelist():
        raise UploadRefused("/file", "A zip file, but not a recognisable .xlsx workbook.",
                            "รองรับเฉพาะไฟล์ .csv และ .xlsx")
    epoch_1904 = _workbook_pr_1904(zf)
    if epoch_1904:
        # Legacy Mac epoch. Silently reusing the 1900 math would put every date in
        # the file four years and a day wrong — a whole-file refusal, not a guess.
        raise UploadRefused("/file", "This workbook uses the 1904 date system, which this reader does not support.",
                            "วันที่ในไฟล์นี้ใช้ฐานปี 1904 ระบบยังไม่รองรับ")
    shared = _shared_strings(zf, budget)
    date_styles = _date_style_indices(zf)
    sheets = []
    for name, part in _workbook_sheets(zf):
        rows, numbers = _sheet_rows(zf, part, shared, date_styles, epoch_1904, budget)
        sheets.append({"name": name, "rows": rows, "row_numbers": numbers})
    return sheets


# --- sheet classification, mirroring scripts/import_master_sheet.py:main() --------

# (kind, must_have, unconditional). LEASING_BOOK and ORDER_MASTER only claim the
# sheet if their reader actually returns rows — read_orders additionally requires a
# "Phone" or "Order Type" column, read_leasing_block a term/month-cell column — both
# guards live INSIDE the imported functions and are exercised by calling them, not
# duplicated here.
_LEASING_MUST = ["VOLT ID", "Payment Status"]
_CASH_MUST = ["VOLT ID", "Price", "DC Status"]
_CASH_INV_MUST = ["Invoice Number", "PEAK Contact Code", "Days Overdue"]
_TRACKING_MUST = ["VOLT ID", "Category", "Total Overdue"]
_ASSET_MUST = ["VOLT ID", "Panel Brand", "Inverter Serial"]
_ORDER_MUST = ["Order Status", "Volt ID", "EPC Start Date"]
_PIVOT_MUST = ["Payment Status", "NPL Type", "COUNTA of VOLT ID"]
_FLOW_MUST = ["Monthly Payments", "Timeframe", "Repercussion"]
# The two tabs the book is taken from (Arina, 2026-09-25): name → the kind they must
# read as, and the header a reader needs to find them.
_DONE_TABS = {"done - collection": ("LEASING_BOOK", _LEASING_MUST + ["Term, Original"]),
              "done - cash": ("CASH_TAB", _CASH_MUST)}
# Shaped like a leasing book, but not one (DQ 2026-09-26 F02): 'EPC - Collection'
# tracks installations — Rate and First Payment Date are empty on every row and half
# of it is cash orders — and reading it made 291 cash customers leases. Its customers
# come from tab x and the Done tabs.
_NOT_A_BOOK = ("epc - collection",)


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month_header(cell):
    """"2024-06-01" (a date-cell header, as read_xlsx serves it) -> "Jun 2024"."""
    m = re.match(r"^(\d{4})-(\d{2})-01", cell or "")
    return "%s %s" % (_MONTHS[int(m.group(2)) - 1], m.group(1)) if m and 1 <= int(m.group(2)) <= 12 else cell


def _identity_refusals(hdr, rows, hi, sheet_name, id_column, nums):
    """Every row in the recognised data range that the tab reader's own identity
    filter (`if not volt_id or "_" not in volt_id`) would drop — computed here
    because the imported reader functions filter these OUT silently (a `continue`,
    no record of why) and ruling 71 asks for "refused, and why", one row per
    refusal. Same rule, made visible, not a new rule. `hi` is always a valid 0-based
    header index here — every caller already confirmed `hdr is not None` first.
    `nums[i]` is the spreadsheet row number of `rows[i]`."""
    out = []
    for ri, row in enumerate(rows[hi + 1:]):
        if not any(row):
            continue                      # a blank row is spacing, not a refused customer
        value = _IMS.col(row, hdr, id_column)
        if not value or "_" not in value:
            out.append({
                "source_ref": {"sheet": sheet_name, "row": nums[hi + 1 + ri]},
                "volt_id": value or None,
                "reason": "missing_or_malformed_%s" % id_column.lower().replace(" ", "_"),
                "reason_th": "ไม่มีค่า %s ที่ถูกต้องในแถวนี้ — ไม่สามารถระบุลูกค้าได้" % id_column,
                "reason_en": "This row has no valid %s — the customer cannot be identified" % id_column,
            })
    return out


def _respecify_refs(records, hi, sheet_name, nums):
    """`(block, row)` -> `{sheet, row}`, 1-based as the spreadsheet numbers it
    (F-api.md's respecification, §4.3 rule 2). `hi` is 0-based into the row list
    this sheet was read from; a record's own `source_ref` is `[bi, ri]` where `ri` is
    0-based into `rows[hi+1:]` — so the spreadsheet row is `nums[hi + 1 + ri]`."""
    for rec in records:
        bi_ri = rec.get("source_ref")
        if isinstance(bi_ri, (list, tuple)) and len(bi_ri) == 2:
            rec["source_ref"] = {"sheet": sheet_name, "row": nums[hi + 1 + bi_ri[1]]}
            for cell in rec.get("calendar_months") or rec.get("months") or []:
                if cell and "source_column" in cell:
                    column, letters = cell["source_column"] + 1, ""
                    while column:
                        column, rem = divmod(column - 1, 26)
                        letters = chr(65 + rem) + letters
                    cell["source_ref"] = {**rec["source_ref"], "column": letters}


def _classify_sheet(header, rows, sheet_name, warnings, nums):
    """Returns (kind, hi, header_cells, records, refusals, extra) — `extra` carries
    the per-kind summary rows (the pivot / cash-invoice summaries) where the tab
    carries one, else None. Mirrors the priority order and the conditional/
    unconditional distinction in import_master_sheet.py:main() — with one upload-only
    step: a leasing header carrying the reader's own term/month columns is a leasing
    tab even when every row on it is refused, so the refusals are reported rather
    than the file called unrecognised."""
    if str(sheet_name).strip().lower() in _NOT_A_BOOK:
        return None, None, header, [], [], None
    _IMS.alias_payment_status(rows)
    hi, hdr = _IMS.find_header(header, rows, _LEASING_MUST)
    if hdr is not None:
        got = _IMS.read_leasing_block(0, header, rows, warnings)
        if got or "Term, Original" in hdr or any(re.match(r"^M\d+$", h) for h in hdr):
            refusals = _identity_refusals(hdr, rows, hi, sheet_name, "VOLT ID", nums)
            _respecify_refs(got, hi, sheet_name, nums)
            for w in warnings:
                # `read_leasing_block` (import_master_sheet.py:284) writes {block,
                # row, volt_id, warning, value} — respecify to the same {source_ref,
                # volt_id, warning, value} shape every other list in this report
                # uses, and drop the raw (block, row) pair once it is folded in, so
                # there is one row-locator vocabulary on the response, not two.
                w["source_ref"] = {"sheet": sheet_name, "row": nums[hi + 1 + w.pop("row", 0)]}
                w.pop("block", None)
            return "LEASING_BOOK", hi, hdr, got, refusals, None

    hi, hdr = _IMS.find_header(header, rows, _CASH_MUST)
    if hdr is not None:
        got = _IMS.read_cash_tab(0, header, rows)
        refusals = _identity_refusals(hdr, rows, hi, sheet_name, "VOLT ID", nums)
        _respecify_refs(got, hi, sheet_name, nums)
        return "CASH_TAB", hi, hdr, got, refusals, None

    hi, hdr = _IMS.find_header(header, rows, _CASH_INV_MUST)
    if hdr is not None:
        summary, got = _IMS.read_cash_invoices(0, header, rows)
        refusals = []
        data = rows[hi + 1:]
        for ri, row in enumerate(data):
            inv = _IMS.col(row, hdr, "Invoice Number")
            if any(row) and (not inv or not inv.startswith("IV")):
                refusals.append({
                    "source_ref": {"sheet": sheet_name, "row": nums[hi + 1 + ri]},
                    "volt_id": _IMS.col(row, hdr, "Volt ID (ID_Name)") or _IMS.col(row, hdr, "Volt ID / Match"),
                    "reason": "missing_invoice_number",
                    "reason_th": "ไม่มีเลขที่ใบแจ้งหนี้ (Invoice Number) ที่ขึ้นต้นด้วย IV",
                    "reason_en": "No invoice number starting with IV",
                })
        _respecify_refs(got, hi, sheet_name, nums)
        return "CASH_INVOICES", hi, hdr, got, refusals, {"summary": summary}

    hi, hdr = _IMS.find_header(header, rows, _TRACKING_MUST)
    if hdr is not None:
        # The "done collection" tab's month headers are DATE cells in the .xlsx, which
        # read_xlsx turns into ISO text; the reader keeps only "Mon YYYY" headers, so
        # without this every month of the payment-status source was dropped.
        rows[hi] = hdr = [_month_header(c) for c in hdr]
        summary, got = _IMS.read_collection_tracking(0, header, rows)
        refusals = _identity_refusals(hdr, rows, hi, sheet_name, "VOLT ID", nums)
        _respecify_refs(got, hi, sheet_name, nums)
        return "COLLECTION_TRACKING", hi, hdr, got, refusals, {"summary": summary}

    hi, hdr = _IMS.find_header(header, rows, _ASSET_MUST)
    if hdr is not None:
        got = _IMS.read_assets(0, header, rows)
        refusals = _identity_refusals(hdr, rows, hi, sheet_name, "VOLT ID", nums)
        _respecify_refs(got, hi, sheet_name, nums)
        return "ASSET_REGISTER", hi, hdr, got, refusals, None

    hi, hdr = _IMS.find_header(header, rows, _ORDER_MUST)
    if hdr is not None:
        got = _IMS.read_orders(0, header, rows)
        if got:
            refusals = _identity_refusals(hdr, rows, hi, sheet_name, "Volt ID", nums)
            _respecify_refs(got, hi, sheet_name, nums)
            return "ORDER_MASTER", hi, hdr, got, refusals, None

    hi, hdr = _IMS.find_header(header, rows, _PIVOT_MUST)
    if hdr is not None:
        got = _IMS.read_pivot(0, header, rows)
        return "PAYMENT_STATUS_PIVOT", hi, hdr, [], [], {"pivot": got}

    hi, hdr = _IMS.find_header(header, rows, _FLOW_MUST)
    if hdr is not None:
        flow = _IMS.read_flow_stages(0, header, rows)
        return "FLOW_STAGES", hi, hdr, [], [], {"flow": flow}

    if len(header) == 2 and len(rows) > 300:
        roster = [r for r in rows if len(r) == 2 and r[1] and "_" in r[1]]
        return "ROSTER", None, header, roster, [], None

    return None, None, header, [], [], None


# --- reconciliation, the SAME shape migration.py already serves -------------------

def _reconcile(leasing_records, pivot_rows, cash_records, cash_summary):
    """Three states, never a boolean (§4.5's fix). `all([])` is `True` in Python —
    on the live book that is harmless (there are always four rows); on a one-tab
    upload with no summary sheet the list is empty and the SAME expression would
    tick green on an import that checked nothing. `NO_BASIS` exists for exactly
    that file. `GET /v1/migration/report`'s own boolean is untouched — this is a
    field on the NEW endpoint only (e2e_check.py:934 pins the old one as a bool)."""
    imported_by_status = Counter()
    for rec in leasing_records:
        code = book_domain.payment_status_code(rec.get("payment_status"))
        if code in ("CURRENT", "LATE", "NPL", "CLOSED", "TERMINATED"):
            imported_by_status[code] += 1

    sheet_by_status = {}
    for row in pivot_rows or []:
        name = (row.get("payment_status") or "").replace(" Total", "").strip()
        if name in ("Current", "Late", "NPL", "Closed", "Terminated") and row.get("npl_type") is None and row.get("count"):
            sheet_by_status[name.upper()] = max(sheet_by_status.get(name.upper(), 0), row["count"])

    rows = []
    if pivot_rows:
        for key in ("CURRENT", "LATE", "NPL", "CLOSED"):
            expected = sheet_by_status.get(key)
            actual = imported_by_status.get(key, 0)
            rows.append({
                "payment_status": key, "sheet": expected, "imported": actual,
                "matches": expected is not None and expected == actual,
                "judged": expected is not None,
                "note": None if (expected is None or expected == actual) else
                        "sheet %s vs imported %s — check whether every leasing row's tab was included" % (expected, actual),
            })
        # 2026-09-20: TERMINATED is imported now (the ended-contract status), but the
        # sheet's Payment Status column does not carry the value yet. The row is served
        # as explicitly UNJUDGED — not a pass, not a failure — with the note that says
        # what to ask for. A green tick here would be the exact dishonesty this module
        # exists to prevent; a red one would blame the importer for the sheet's shape.
        terminated_sheet = sheet_by_status.get("TERMINATED")
        terminated_imported = imported_by_status.get("TERMINATED", 0)
        if terminated_sheet is not None or terminated_imported:
            rows.append({
                "payment_status": "TERMINATED", "sheet": terminated_sheet, "imported": terminated_imported,
                "matches": terminated_sheet is not None and terminated_sheet == terminated_imported,
                "judged": terminated_sheet is not None,
                "note": None if terminated_sheet is not None else
                        "the sheet's Payment Status column carries no Terminated value yet — "
                        "ask the sheet owner to add it, then this row can be judged",
            })

    cash_total = next((r for r in (cash_summary or []) if r.get("dc_status") == "Total"), None)
    cash_imported = len(cash_records or [])
    cash = {
        "sheet_invoices": cash_total["invoices"] if cash_total else None,
        "sheet_outstanding": cash_total["outstanding"] if cash_total else None,
        "imported_invoices": cash_imported,
    }

    if not rows:
        basis = "NO_BASIS"
    elif all(r["matches"] for r in rows if r.get("judged", True)) and (cash_total is None or cash_imported >= cash_total["invoices"]):
        basis = "RECONCILED"
    else:
        basis = "NOT_RECONCILED"
    return {"basis": basis, "rows": rows, "cash": cash,
            # The rows nobody can judge yet, named so the screen prints "ยังพิสูจน์ไม่ได้"
            # instead of leaving them out of sight.
            "unjudged": [r["payment_status"] for r in rows if not r.get("judged", True)]}


# --- the whole run ------------------------------------------------------------

def parse_upload(raw: bytes, filename, x_volt_officer, x_volt_role, with_payload=False,
                 on_progress=None, checkpoint=None):
    """The reconciliation report IS the feature (ruling 71). Returns the run dict
    (also stored, keyed by uid, in this session's ImportState) or raises
    UploadRefused for a whole-file failure — no run is created for those, so an
    empty run never pretends to be an import (§4.1's rule). `with_payload` also
    returns the book payload the importer's own `assemble_payload` built from the
    file — what `install` lands. When supplied, `on_progress` is called after each
    classified sheet with keyword arguments `processed` and `phase_total` (sheet
    counts, including unrecognised tabs)."""
    kind = sniff_kind(raw)
    if kind == "OLE":
        raise UploadRefused("/file", "Legacy .xls (BIFF) or a password-protected .xlsx — neither is readable here.",
                            "ไฟล์นี้เป็น .xls รุ่นเก่าหรือมีรหัสผ่าน — บันทึกใหม่เป็น .xlsx ที่ไม่ใส่รหัสผ่าน")

    warnings = []
    if kind == "XLSX":
        encoding = None
        sheets_raw = read_xlsx(raw)
    else:
        encoding, text = decode_csv(raw)
        from .csv_safety import formula
        reader_rows = []
        total_cells = 0
        try:
            for number, row in enumerate(csv.reader(io.StringIO(text)), 1):
                total_cells += len(row)
                if len(row) > XLSX_MAX_COLUMNS or total_cells > 1000000 or any(len(value) > XLSX_MAX_CELL_CHARS for value in row):
                    _xlsx_refused()
                if any(formula(value) for value in row):
                    raise UploadRefused("/file", "CSV row %d contains spreadsheet formula text." % number,
                                        "ไฟล์ CSV มีข้อความที่โปรแกรมตารางจะตีความเป็นสูตร กรุณาใช้ค่าข้อมูลแทน")
                reader_rows.append(row)
        except csv.Error as exc:
            raise UploadRefused("/file", "The CSV is malformed or contains an oversized field.",
                                "ไฟล์ CSV มีรูปแบบไม่ถูกต้องหรือมีช่องข้อมูลใหญ่เกินขอบเขต") from exc
        sheets_raw = [{"name": None, "rows": _clean_rows(reader_rows)}]

    sheets_out = []
    all_leasing, all_cash, all_cash_inv, all_assets, all_orders = [], [], [], [], []
    all_tracking, tracking_summary, flow = [], [], {}
    all_refusals, contact_log_count = [], 0
    pivot_rows, cash_summary = None, None
    customers_touched = set()

    for index, sheet in enumerate(sheets_raw):
        if checkpoint:
            checkpoint()
        name = sheet["name"]
        rows = sheet["rows"]
        nums = sheet.get("row_numbers") or list(range(1, len(rows) + 1))   # a .csv numbers by sequence
        header = []
        sheet_warnings = []
        sheet_kind, hi, hdr, records, refusals, extra = _classify_sheet(
            header, rows, name if name is not None else 0, sheet_warnings, nums)
        for w in sheet_warnings:
            w.setdefault("source_ref", {"sheet": name if name is not None else 0, "row": None})
        warnings.extend(sheet_warnings)

        header_cells = hdr if hdr else None
        # `find_header` is always called here with an empty `header` argument (every
        # row lives in `rows`, title rows and all — see `_classify_sheet`), so `hi`
        # is either `None` (not recognised) or a valid 0-based index into `rows`;
        # the "-1 means the markdown header line itself" case in `find_header`'s own
        # docstring cannot arise from how this module calls it.
        header_row = nums[hi] if hi is not None else None
        sheets_out.append({
            "index": index, "name": name, "kind": sheet_kind,
            "header_row": header_row, "header_cells": header_cells, "rows": len(rows),
        })
        all_refusals.extend(refusals)

        if sheet_kind == "LEASING_BOOK":
            all_leasing.extend(records)
            for rec in records:
                customers_touched.add(rec["volt_id"])
                contact_log_count += len(_IMS.parse_maplog(" ".join(
                    x for x in (rec.get("comment_th"), rec.get("comment_en")) if x)))
        elif sheet_kind == "CASH_TAB":
            all_cash.extend(records)
            for rec in records:
                customers_touched.add(rec["volt_id"])
        elif sheet_kind == "CASH_INVOICES":
            all_cash_inv.extend(records)
            cash_summary = (extra or {}).get("summary")
            for rec in records:
                if rec.get("volt_id"):
                    customers_touched.add(rec["volt_id"])
        elif sheet_kind == "COLLECTION_TRACKING":
            all_tracking.extend(records)
            tracking_summary.extend((extra or {}).get("summary") or [])
            for rec in records:
                customers_touched.add(rec["volt_id"])
        elif sheet_kind == "ASSET_REGISTER":
            all_assets.extend(records)
            for rec in records:
                customers_touched.add(rec["volt_id"])
        elif sheet_kind == "ORDER_MASTER":
            all_orders.extend(records)
            for rec in records:
                customers_touched.add(rec["volt_id"])
        elif sheet_kind == "PAYMENT_STATUS_PIVOT":
            pivot_rows = (extra or {}).get("pivot")
        elif sheet_kind == "FLOW_STAGES":
            flow = (extra or {}).get("flow") or {}
        if on_progress:
            on_progress(processed=index + 1, phase_total=len(sheets_raw))

    if not any(s["kind"] for s in sheets_out) and any(any(row) for s in sheets_raw for row in s["rows"]):
        # Nothing in the file is a tab the importer knows: a 200 with zero rows read
        # would say "checked" about a file nobody read.
        raise UploadRefused(
            "/file", "No tab in this file has a header the importer recognises: a leasing tab "
                     "needs VOLT ID, Payment Status AND Term, Original (or month columns M1, M2, ...); "
                     "the \"done collection\" tab needs VOLT ID, Category and Total Overdue.",
            "ไม่พบแท็บที่ระบบรู้จักในไฟล์นี้ — แท็บสัญญาเช่าต้องมีหัวตาราง VOLT ID, Payment Status "
            "และ Term, Original (หรือคอลัมน์เดือน M1, M2, …) · แท็บ done collection ต้องมี "
            "VOLT ID, Category และ Total Overdue",
            {"sheets": [s["name"] for s in sheets_out]})

    # A Done tab the file carries but the importer could not read (a renamed column)
    # must stop the install — never let an older copy stand in unnoticed (2026-09-25).
    done_tabs_unread = []
    for s, raw_sheet in zip(sheets_out, sheets_raw):
        want = _DONE_TABS.get((s["name"] or "").strip().lower())
        if want and s["kind"] != want[0]:
            head = next((r for r in raw_sheet["rows"][:30]
                         if any(isinstance(c, str) and c.strip() == "VOLT ID" for c in r)), [])
            cells = {c.replace("\n", " ").strip() for c in head if isinstance(c, str)}
            done_tabs_unread.append({"sheet": s["name"], "expected": want[0],
                                     "missing": [m for m in want[1] if m not in cells]})
            warnings.append({"source_ref": {"sheet": s["name"], "row": None}, "volt_id": None,
                             "warning": "done_tab_unread", "value": ", ".join(done_tabs_unread[-1]["missing"])})

    rows_imported = (len(all_leasing) + len(all_cash) + len(all_cash_inv) + len(all_assets)
                     + len(all_orders) + len(all_tracking))
    rows_refused = len(all_refusals)
    blocks = [{"block": s["index"], "name": s["name"], "kind": s["kind"], "rows": s["rows"]} for s in sheets_out]
    # No roster: an upload's tabs are classified with an empty header, which the
    # two-column ROSTER rule never matches.
    payload = _IMS.assemble_payload(all_leasing, all_cash, all_cash_inv, tracking_summary, all_tracking,
                                    all_assets, all_orders, [], pivot_rows or [], flow, warnings,
                                    blocks, cash_summary or [])

    reconciliation = _reconcile(all_leasing, pivot_rows, all_cash_inv, cash_summary)
    payload["done_tabs_unread"] = done_tabs_unread

    run = {
        "run": {
            "uid": None, "filename": filename, "bytes": len(raw), "kind": kind if kind != "MAYBE_CSV" else "CSV",
            "encoding": encoding, "taken_at": clock.stamp(), "business_date": str(settings.business_date),
            "by": x_volt_officer or "officer", "by_role": (x_volt_role or "OFFICER").upper(),
        },
        "sheets": sheets_out,
        "counts": {
            "rows_read": rows_imported + rows_refused,
            "rows_imported": rows_imported,
            "rows_refused": rows_refused,
            "customers": len(customers_touched),
            "contracts": len(all_leasing) + len(all_cash),
            "invoices": len(all_cash_inv),
            "tracked": len(all_tracking),
            "contact_log": contact_log_count,
        },
        "refusals": all_refusals,
        "done_tabs_unread": done_tabs_unread,
        "refusals_by_reason": [
            {"reason": reason, "reason_th": next((r["reason_th"] for r in all_refusals if r["reason"] == reason), ""),
             "reason_en": next((r.get("reason_en", "") for r in all_refusals if r["reason"] == reason), ""),
             "count": count}
            for reason, count in Counter(r["reason"] for r in all_refusals).most_common()
        ],
        "warnings": warnings,
        "reconciliation": reconciliation,
        "truncation": {"cut": False, "at_bytes": None, "cap_bytes": MAX_BYTES, "reason_th": None, "reason_en": None},
        "masking": {
            "phone": "read whole for the dial actions; a check stores no rows, an install lands them, and the serving layer hides the number",
            "email": "masked at parse — never written to the run record or logged",
            "phone_e164": "kept by the reader for the pipeline; the audited phone:reveal route is the only door that answers it",
        },
        "installed": False,
        "installed_note_th": "ไฟล์นี้อ่านและตรวจแล้ว แต่ยังไม่ได้นำเข้าระบบ",
        "installed_note_en": "This file was read and checked, but not imported yet",
    }
    state = for_current()
    uid = state.uid("imp")
    run["run"]["uid"] = uid
    state.runs[uid] = run
    return (run, payload) if with_payload else run


def can_install(payload):
    """The file carries the book: a leasing tab with at least one customer on it. A
    "done collection" tab alone would rebuild every contract from its tracking rows."""
    return any(c.get("leasing") for c in payload["customers"])


class InstallWouldRetire(Exception):
    """The install would take a large share of the book out; `preview` says how much."""

    def __init__(self, preview):
        super().__init__("install_would_retire")
        self.preview = preview


_BOOK_TABS = ("leasing", "tracking", "cash")


def _retire_preview(conn, payload):
    """What installing `payload` takes out of the live book: the SHEET customers the
    file does not carry, and each tab kind (leasing / done collection / cash) the live
    book has and the file lacks. More than a tenth of the book, or a whole tab kind,
    installs only with that customer count confirmed back (`confirm_retire`)."""
    from sqlalchemy import text
    live = {r[0] for r in conn.execute(text(
        "select volt_id from landing.customer where data_source = 'SHEET' and retired_at is null"))}
    kinds = {r[0] for r in conn.execute(text(
        "select distinct block from landing.customer_block where data_source = 'SHEET' "
        "and retired_at is null and block = any(:k)"), {"k": list(_BOOK_TABS)})}
    carried = {c["volt_id"] for c in payload["customers"]}
    dropped = sorted(kinds - {b for c in payload["customers"] for b in _BOOK_TABS if c.get(b)})
    retire = len(live - carried)
    return {"customers": retire, "live": len(live), "dropped_tabs": dropped,
            "needs_confirm": retire * 10 > len(live) or bool(dropped)}


def retire_preview(payload):
    """`_retire_preview` on its own connection — the check shows it before any click."""
    from . import db
    conn = db.connect()
    try:
        return _retire_preview(conn, payload)
    finally:
        conn.close()


def install(payload, confirm_retire=None, before_commit=None):
    """Land a checked New Order Master as the book: one transaction lands it as a
    SHEET run and retires every SHEET row it no longer carries (retired, never
    deleted — a later install brings the row back); then this process serves it and
    the epoch tells every other session. Returns the served counts. A file that would
    retire a large share of the book raises InstallWouldRetire unless
    `confirm_retire` echoes that count — checked inside the transaction, so the count
    confirmed is the count retired."""
    from sqlalchemy import text
    from . import book, db, landing, refresh, sheet_loader
    conn = db.connect()
    try:
        with conn.begin():
            preview = _retire_preview(conn, payload)
            if preview["needs_confirm"] and confirm_retire != preview["customers"]:
                raise InstallWouldRetire(preview)
            landed = sheet_loader.load_payload(conn, payload)
            retired = landing.retire_unseen(conn, "SHEET", [c["volt_id"] for c in payload["customers"]])
            # retire_unseen is per volt_id; a customer still on the sheet but gone from
            # one tab (off the "done collection" tab, say) must not keep serving the
            # last install's block for it.
            for table in ("landing.customer_block", 'landing."order"'):
                conn.execute(text("update %s set retired_at = now() where data_source = 'SHEET' "
                                  "and retired_at is null and import_run_id <> :r" % table),
                             {"r": landed["import_run_id"]})
            if before_commit:
                before_commit()
    finally:
        conn.close()
    served = refresh.after_landing("sheet", landed["import_run_id"])
    customers, _report = book.build()
    # The browser gets the problem's code and words only — never exception text.
    problem = {k: served["problem"].get(k) for k in ("code", "message_th", "message_en")} \
        if served["problem"] else None
    return {"run_id": landed["import_run_id"], "customers": landed["customers"],
            "contracts": sum(len(c.contracts) for c in customers),
            "tracked": sum(1 for c in payload["customers"] if c.get("tracking")),
            "retired": retired, "served": served["served"], "problem": problem}


def get_current(uid):
    return for_current().runs.get(uid)


def list_current():
    return list(for_current().runs.values())
