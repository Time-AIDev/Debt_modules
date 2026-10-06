"""The file guard. A file is stored only after every rule for its type passes.

Design F8: format rules here, standard library only; a virus scanner is a separate
port (scanner.py) that this module never assumes. Each refusal names the rule so the
officer can fix the file rather than guess.

Controller ruling (2026-09-15, ledgered): `_sniff`'s CSV fallback does NOT trust mere
decodability. TIS-620 decodes almost any byte string, so an arbitrary binary would
otherwise be sniffed as CSV. A byte string is called CSV only if it decodes (UTF-8,
UTF-8 with BOM, or TIS-620) AND carries no NUL byte AND is overwhelmingly text — at
least 95% of the decoded characters are printable or common whitespace (\\t \\r \\n).
Otherwise `_sniff` returns None, which `check` turns into `type_not_allowed`.

Controller ruling, fix round 1 (2026-09-15, ledgered) — four security-review findings:
- I1: `_check_office` never trusts a zip entry's declared `file_size`. Every entry is
  read through `zf.open()` in chunks, keeping a running count of ACTUAL bytes
  produced across all entries; the moment that count exceeds `OFFICE_INFLATE_MAX` it
  stops and refuses `office_zip_bomb`. Every `.xml` entry's actual (cap-bounded)
  content is scanned for DDE — there is no file_size-based skip any more.
- I2: every zip open/read in `_sniff` and `_check_office` catches
  `zipfile.BadZipFile`, `zipfile.LargeZipFile`, `zlib.error`, `EOFError`,
  `RuntimeError`, `NotImplementedError` and `ValueError`, and refuses a NEW code,
  `file_corrupt` — "the file is damaged and cannot be read" — instead of letting the
  library exception escape `check()`.
- I3: `_check_svg` inspects the text of every `<style>` element (CDATA included,
  since ElementTree folds CDATA into `.text`) and every `style=` attribute, and
  refuses `svg_active_content` when that text carries `@import`, `expression(`,
  `javascript:`, or a `url(...)` whose target (trimmed of spaces/quotes) does not
  start with `#`.
- PDF escape: `_check_pdf` decodes `#XX` PDF name escapes (`re.sub(rb"#([0-9A-Fa-f]
  {2})", ...)`) in a scanning copy of the bytes before running the dangerous-name
  regex, so `/J#61vaScript` (which a PDF reader decodes to `/JavaScript`) is caught.

Task 25c: `href`/`xlink:href`/`src` on any SVG element allow ONLY empty or an
internal fragment (`#...`) — normalise by stripping every ASCII whitespace/control
character (U+0000-U+0020, U+007F), then require the result be empty or start with
`#`. A scheme-prefix denylist let a backslash or an XML `&#9;` (decodes to a tab)
through; this closes that. Fix round 1: the refusal echoes the NORMALISED value,
never the raw one, so a decoded control character never reaches `detail`. A SMIL
`<set>`/`<animate>`/`<animateMotion>`/`<animateTransform>` is refused outright
when its `attributeName` is `href`/`xlink:href` (any namespace/prefix on the
element), and its `to`/`from`/`values`/`by` (each `;`-separated part of `values`
checked on its own) is held to the same empty-or-fragment rule.

Refusal codes: too_large, type_not_allowed, extension_mismatch, empty, file_corrupt,
png_corrupt, svg_active_content, svg_root, csv_formula_cell, office_macro, office_external,
office_zip_bomb, pdf_active_content.
"""
import csv
import hashlib
import io
import re
import struct
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

from ..config import settings

CONTENT_TYPES = {"PNG": "image/png", "SVG": "image/svg+xml", "CSV": "text/csv",
                 "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "PDF": "application/pdf"}
EXTENSIONS = {"png": "PNG", "svg": "SVG", "csv": "CSV", "xlsx": "XLSX", "docx": "DOCX", "pdf": "PDF"}
OFFICE_INFLATE_MAX = 50 * 1024 * 1024
OFFICE_ENTRIES_MAX = 2000
# I1: real bytes are counted as every entry is streamed, this many at a time.
OFFICE_READ_CHUNK = 1024 * 1024
# I2: exceptions any zip open/read can raise on a damaged or hostile file.
_ZIP_DAMAGE_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, EOFError,
                      RuntimeError, NotImplementedError, ValueError)

# CSV sniff: the fraction of decoded characters that must be printable (or the common
# whitespace below) before a decodable byte string is trusted as text at all.
_CSV_TEXT_RATIO_MIN = 0.95
_CSV_WHITESPACE = "\t\r\n"

_SVG_BAD_TAGS = {"script", "foreignobject", "iframe", "embed", "object", "use"}
# I3: a <style> element's text (CDATA included) or a style= attribute value is
# active content if it imports, evaluates, or references anything but a same-
# document fragment.
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_PDF_BAD = re.compile(rb"/(JavaScript|JS|Launch|AA|OpenAction|EmbeddedFile|RichMedia|XFA)\b")
# PDF escape: a PDF reader decodes #XX inside a name token to that hex byte, so the
# dangerous-name regex must run against a copy with those escapes already decoded.
_PDF_HEX_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")
_OFFICE_MACRO = re.compile(r"(^|/)vbaProject\.bin$|macroEnabled", re.IGNORECASE)
_OFFICE_EXTERNAL = re.compile(r"(^|/)(oleObject\d*\.bin|externalLink\d*\.xml)$", re.IGNORECASE)
_DDE = re.compile(r"\bDDE(AUTO)?\b")
# Task 25c: a scheme-prefix denylist on href/xlink:href/src still let a backslash
# ("/\evil.example", browsers treat backslash like forward slash) or an XML
# character reference that decodes to a tab ("/&#9;/evil.example" -> a literal tab,
# which a browser strips when parsing a URL, leaving "//evil.example") through. The
# only value ever allowed now is empty or an internal fragment (#...), after every
# ASCII whitespace/control character (U+0000-U+0020, U+007F) is stripped out.
_SVG_HREF_CONTROL_WS = re.compile("[\x00-\x20\x7f]")
# Task 25c fix round 1, minor: a SMIL <set>/<animate>/<animateMotion>/
# <animateTransform>/<animateColor> can retarget href without ever writing an
# href/xlink:href/src attribute itself -- attributeName names WHICH attribute it
# drives, and to/from/by/values carry the value(s) it drives it to. Same local-name
# matching as every other tag/attribute check in this file (any namespace or
# prefix). Fix round 2, finding (b): animateColor added.
_SMIL_TAGS = {"set", "animate", "animatemotion", "animatetransform", "animatecolor"}
_SMIL_VALUE_ATTRS = ("to", "from", "by", "values")


class Refused(Exception):
    def __init__(self, code, detail, detail_th, rule=None):
        super().__init__(detail)
        self.code, self.detail, self.detail_th, self.rule = code, detail, detail_th, rule or code


def _looks_like_text(raw):
    """Controller ruling: decodable is not enough. No NUL byte, and at least
    _CSV_TEXT_RATIO_MIN of the decoded characters must be printable or common
    whitespace, before a decodable byte string is trusted as CSV."""
    if b"\x00" in raw:
        return False
    text = None
    for enc in ("utf-8-sig", "tis-620"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return False
    printable = sum(1 for ch in text if ch.isprintable() or ch in _CSV_WHITESPACE)
    return (printable / len(text)) >= _CSV_TEXT_RATIO_MIN


def _sniff(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if raw.startswith(b"%PDF-"):
        return "PDF"
    if raw[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
        except _ZIP_DAMAGE_ERRORS:
            raise Refused("file_corrupt", "the file is damaged and cannot be read", "ไฟล์เสียหาย อ่านไม่ได้")
        if "[Content_Types].xml" in names:
            if any(n.startswith("xl/") for n in names):
                return "XLSX"
            if any(n.startswith("word/") for n in names):
                return "DOCX"
        return None
    head = raw[:4096].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<") and b"<svg" in raw[:65536].lower():
        return "SVG"
    if _looks_like_text(raw):
        return "CSV"
    return None


def _check_png(raw):
    pos, seen_end = 8, False
    while pos + 8 <= len(raw):
        length, kind = struct.unpack(">I", raw[pos:pos + 4])[0], raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + length]
        crc = raw[pos + 8 + length:pos + 12 + length]
        if len(data) != length or len(crc) != 4:
            raise Refused("png_corrupt", "a PNG chunk is truncated", "ไฟล์ PNG ไม่สมบูรณ์ (ข้อมูลขาด)")
        if struct.unpack(">I", crc)[0] != (zlib.crc32(kind + data) & 0xFFFFFFFF):
            raise Refused("png_corrupt", "a PNG chunk fails its CRC", "ไฟล์ PNG เสียหาย (CRC ไม่ตรง)")
        pos += 12 + length
        if kind == b"IEND":
            seen_end = True
            break
    if not seen_end or pos != len(raw):
        raise Refused("png_corrupt", "the PNG does not end at IEND", "ไฟล์ PNG มีข้อมูลเกินท้ายไฟล์หรือไม่มี IEND")


def _local_attrs(el, local_name):
    """EVERY attribute value on this element whose LOCAL name matches, whatever
    namespace or prefix (if any) each was declared under and however many times it
    occurs -- the same local-name rule `tag`/`local` already apply to element and
    href/xlink:href/src attribute names in this function.

    Fix round 2, finding (a): a first-match-wins lookup let a DECOY namespaced
    duplicate hide the real one --
    `x:attributeName="fill" attributeName="href"` returned "fill" and never even
    looked at the real, un-namespaced "href". Every occurrence must be checked."""
    return [value for name, value in el.attrib.items()
            if name.rsplit("}", 1)[-1].lower() == local_name]


def _check_svg(raw):
    text = raw.decode("utf-8", errors="replace")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise Refused("svg_active_content", "SVG carries a DOCTYPE or an entity", "ไฟล์ SVG มี DOCTYPE/ENTITY ซึ่งไม่อนุญาต")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise Refused("svg_active_content", "SVG is not well-formed XML: %s" % exc, "ไฟล์ SVG ไม่ใช่ XML ที่ถูกต้อง")
    # Final review (minor): _sniff calls anything carrying "<svg" in its first 64 KB an
    # SVG, so an XHTML page (or any other document) with an <svg> inside it would pass
    # as one. The document itself must BE an svg.
    root_tag = root.tag.rsplit("}", 1)[-1].lower()
    if root_tag != "svg":
        raise Refused("svg_root", "the document's root element is <%s>, not <svg>" % root_tag[:40],
                      "ไฟล์นี้ไม่ใช่ SVG — องค์ประกอบหลักคือ <%s> ไม่ใช่ <svg>" % root_tag[:40])
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag in _SVG_BAD_TAGS:
            raise Refused("svg_active_content", "SVG carries <%s>" % tag, "ไฟล์ SVG มีแท็ก <%s> ซึ่งไม่อนุญาต" % tag)
        if tag == "style":
            bad = _css_active_content(el.text)
            if bad:
                raise Refused("svg_active_content", "SVG <style> carries %s" % bad, "ไฟล์ SVG มี %s ใน <style> ซึ่งไม่อนุญาต" % bad)
        if tag in _SMIL_TAGS:
            # Fix round 2, finding (a): check EVERY attributeName occurrence (any
            # namespace/prefix, not just the first), strip whitespace/control
            # characters, lowercase, and take the part after the LAST ":" --
            # attributeName's own value is a plain string reference a renderer
            # resolves against the document's namespace bindings; this same rule
            # (rather than actually resolving them) catches a plain "href", an
            # "xlink:href", and any OTHER prefix ("foo:href") bound to it.
            for raw_name in _local_attrs(el, "attributename"):
                normalised_name = _SVG_HREF_CONTROL_WS.sub("", raw_name or "").lower()
                target_attr = normalised_name.rsplit(":", 1)[-1]
                if target_attr in ("href", "src"):
                    raise Refused("svg_active_content", "SVG SMIL <%s> retargets %s" % (tag, target_attr),
                                  "ไฟล์ SVG มีแอนิเมชันเปลี่ยนค่า href ซึ่งไม่อนุญาต")
            # Fix round 2, finding (b): to/from/by/values (every occurrence, "values"
            # split on ";") are held to the SAME rule as <style>/style= -- javascript:,
            # expression(, @import, or a url(...) that is not a #fragment -- not the
            # stricter empty-or-fragment test, which refused an ordinary animation
            # (values="red;blue", from="0" to="1", a transform's "0 50 50").
            for attr in _SMIL_VALUE_ATTRS:
                for raw_value in _local_attrs(el, attr):
                    parts = raw_value.split(";") if attr == "values" else [raw_value]
                    for part in parts:
                        normalised = _SVG_HREF_CONTROL_WS.sub("", part)
                        bad = _css_active_content(normalised)
                        if bad:
                            raise Refused("svg_active_content", "SVG SMIL <%s> %s carries %s" % (tag, attr, bad),
                                          "ไฟล์ SVG อ้างอิงลิงก์ภายนอกหรือสคริปต์")
        for name, value in el.attrib.items():
            local = name.rsplit("}", 1)[-1].lower()
            if local.startswith("on"):
                raise Refused("svg_active_content", "SVG carries an event handler %s" % local, "ไฟล์ SVG มี event handler (%s)" % local)
            # Task 25c: the only href/xlink:href/src ever allowed is empty or an
            # internal fragment (#...), once every ASCII whitespace/control
            # character is stripped out -- not a scheme-prefix denylist, which a
            # backslash or a decoded control character (XML "&#9;" -> a tab) bypassed.
            if local in ("href", "xlink:href", "src"):
                normalised = _SVG_HREF_CONTROL_WS.sub("", value or "")
                if not (normalised == "" or normalised.startswith("#")):
                    # Fix round 1: echo the NORMALISED value, never the raw one --
                    # the raw value can still carry a control character (a decoded
                    # XML "&#9;" is a literal tab) that must not reach a log or a
                    # response body.
                    raise Refused("svg_active_content", "SVG references %s" % normalised[:40],
                                 "ไฟล์ SVG อ้างอิงลิงก์ภายนอกหรือสคริปต์")
            if local == "style":
                bad = _css_active_content(value)
                if bad:
                    raise Refused("svg_active_content", "SVG style attribute carries %s" % bad, "ไฟล์ SVG มี %s ใน style attribute ซึ่งไม่อนุญาต" % bad)


def _css_active_content(text):
    """I3: refuse CSS-like text (a <style> element's text or a style= attribute
    value) that imports, evaluates, or references anything but a same-document
    fragment. Returns the offending token, or None if the text is clean.

    Fix round 2, finding (d): the url(...) target is echoed into a Refused detail
    (a response body) by every caller -- normalised (whitespace/control characters
    stripped) BEFORE it is returned, the same rule the href/xlink:href/src check
    already applies, so a decoded control character never reaches one."""
    if not text:
        return None
    low = text.lower()
    if "@import" in low:
        return "@import"
    if "expression(" in low:
        return "expression("
    if "javascript:" in low:
        return "javascript:"
    for m in _CSS_URL.finditer(text):
        target = _SVG_HREF_CONTROL_WS.sub("", m.group(2).strip().strip("'\""))
        if not target.startswith("#"):
            return "url(%s)" % target[:40]
    return None


def _check_csv(raw):
    from ..csv_safety import formula
    text = None
    for enc in ("utf-8-sig", "tis-620"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    for r, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        for c, cell in enumerate(row):
            v = cell.lstrip(" \t\r\n\ufeff")
            if formula(cell):
                col = chr(ord("A") + c) if c < 26 else "col%d" % (c + 1)
                raise Refused("csv_formula_cell", "cell %s%d starts with %r (spreadsheet formula)" % (col, r, v[:1]),
                              "เซลล์ %s%d ขึ้นต้นด้วย %s ซึ่งโปรแกรมตารางจะตีความเป็นสูตร" % (col, r, v[:1]))


def _check_office(raw):
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except _ZIP_DAMAGE_ERRORS:
        raise Refused("file_corrupt", "the file is damaged and cannot be read", "ไฟล์เสียหาย อ่านไม่ได้")
    with zf:
        try:
            infos = zf.infolist()
        except _ZIP_DAMAGE_ERRORS:
            raise Refused("file_corrupt", "the file is damaged and cannot be read", "ไฟล์เสียหาย อ่านไม่ได้")
        if len(infos) > OFFICE_ENTRIES_MAX:
            raise Refused("office_zip_bomb", "%d zip entries" % len(infos), "ไฟล์มีรายการภายในมากผิดปกติ")
        for info in infos:
            if _OFFICE_MACRO.search(info.filename):
                raise Refused("office_macro", "carries %s" % info.filename, "ไฟล์มีมาโคร (%s) ซึ่งไม่อนุญาต" % info.filename)
            if _OFFICE_EXTERNAL.search(info.filename):
                raise Refused("office_external", "carries %s" % info.filename, "ไฟล์มีอ็อบเจกต์ฝังหรือลิงก์ภายนอก (%s)" % info.filename)

        # I1: never trust a declared file_size. Stream every entry's REAL bytes and
        # keep one running count across the whole archive; the moment it crosses the
        # cap, stop and refuse — before any entry is otherwise trusted. Each .xml
        # entry's actual (cap-bounded) text is kept for the DDE scan below; there is
        # no size-based skip any more.
        total = 0
        xml_bodies = {}
        for info in infos:
            is_xml = info.filename.endswith(".xml")
            chunks = [] if is_xml else None
            try:
                with zf.open(info) as fh:
                    while True:
                        chunk = fh.read(OFFICE_READ_CHUNK)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > OFFICE_INFLATE_MAX:
                            raise Refused("office_zip_bomb", "inflates past %d bytes" % OFFICE_INFLATE_MAX,
                                          "ไฟล์ขยายตัวใหญ่ผิดปกติ")
                        if is_xml:
                            chunks.append(chunk)
            except _ZIP_DAMAGE_ERRORS:
                raise Refused("file_corrupt", "the file is damaged and cannot be read", "ไฟล์เสียหาย อ่านไม่ได้")
            if is_xml:
                xml_bodies[info.filename] = b"".join(chunks).decode("utf-8", errors="replace")

        ct = xml_bodies.get("[Content_Types].xml", "")
        if "macroEnabled" in ct:
            raise Refused("office_macro", "macro-enabled content type", "ไฟล์เป็นชนิดเปิดใช้มาโคร")
        for name, body in xml_bodies.items():
            if _DDE.search(body):
                raise Refused("office_external", "DDE field in %s" % name, "ไฟล์มีฟิลด์ DDE (%s)" % name)


def _check_pdf(raw):
    if b"%%EOF" not in raw[-2048:]:
        raise Refused("pdf_active_content", "no %%EOF trailer", "ไฟล์ PDF ไม่มีส่วนท้าย (%%EOF)")
    # PDF escape: a reader decodes #XX inside a name token to that hex byte before
    # comparing it (so /J#61vaScript IS /JavaScript to a reader) — decode the same
    # way in this scanning copy before the dangerous-name regex runs.
    decoded = _PDF_HEX_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), raw)
    m = _PDF_BAD.search(decoded)
    if m:
        raise Refused("pdf_active_content", "PDF carries %s" % m.group(0).decode(), "ไฟล์ PDF มี %s ซึ่งไม่อนุญาต" % m.group(0).decode())


CHECKS = {"PNG": _check_png, "SVG": _check_svg, "CSV": _check_csv, "XLSX": _check_office, "DOCX": _check_office, "PDF": _check_pdf}


def check(raw, filename):
    if not raw:
        raise Refused("empty", "the file is empty", "ไฟล์ว่าง")
    if len(raw) > settings.attachment_max_bytes:
        raise Refused("too_large", "%d bytes; the cap is %d" % (len(raw), settings.attachment_max_bytes),
                      "ไฟล์ใหญ่เกิน %d MB" % (settings.attachment_max_bytes // (1024 * 1024)))
    # Task 25a: the caller (routers/attachments.py) decodes X-Volt-Filename before
    # calling check() — this sanitiser only widens past \w to keep the Thai block
    # (U+0E00-U+0E7F), because Thai vowel/tone marks are category Mn and are not
    # matched by \w even once a name is already decoded.
    clean = re.sub(r"[^\w฀-๿.\- ]", "", Path(filename or "").name)[:120] or "file"
    ext = clean.rsplit(".", 1)[-1].lower() if "." in clean else ""
    kind = _sniff(raw)
    if kind is None or ext not in EXTENSIONS:
        raise Refused("type_not_allowed", "only png, svg, csv, xlsx, docx, pdf are accepted",
                      "รับเฉพาะไฟล์ png, svg, csv, xlsx, docx, pdf")
    if EXTENSIONS[ext] != kind:
        raise Refused("extension_mismatch", "named .%s but the bytes are %s" % (ext, kind),
                      "นามสกุลไฟล์ .%s ไม่ตรงกับเนื้อไฟล์ (%s)" % (ext, kind))
    CHECKS[kind](raw)
    return {"kind": kind, "content_type": CONTENT_TYPES[kind], "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw), "filename": clean}
