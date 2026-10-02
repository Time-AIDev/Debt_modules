""".xlsx out, stdlib only (zipfile + escaped XML) — the writing twin of
`imports.read_xlsx`, and for the same reason: no new dependency.

A sheet is a name and a list of rows. A row is a list of cells:
  str       -> an inline string
  Decimal   -> a number shown as #,##0.00 (money)
  int       -> a whole number
  Bold(str) -> an inline string in bold (headings)
  None      -> an empty cell
Nothing here computes a figure; it only lays out what the caller hands it.
"""
import io
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# Style indices in _STYLES' <cellXfs>: 0 plain, 1 bold, 2 money.
_PLAIN, _BOLD, _MONEY = 0, 1, 2

_STYLES = (
    _HEAD + '<styleSheet xmlns="%s">' % _MAIN
    + '<numFmts count="0"/>'
    + '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    + '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    + '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    + '<fill><patternFill patternType="gray125"/></fill></fills>'
    + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    + '<cellXfs count="3">'
    + '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    + '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    + '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    + '</cellXfs>'
    + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    + '</styleSheet>'
)

_BAD_SHEET_CHARS = set('[]:*?/\\')


class Bold(str):
    """A heading cell."""


def _col(index):
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _cell(ref, value):
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        value = "TRUE" if value else "FALSE"
    if isinstance(value, Decimal):
        return '<c r="%s" s="%d"><v>%s</v></c>' % (ref, _MONEY, value)
    if isinstance(value, int):
        return '<c r="%s" s="%d"><v>%d</v></c>' % (ref, _PLAIN, value)
    style = _BOLD if isinstance(value, Bold) else _PLAIN
    return ('<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
            % (ref, style, escape(str(value))))


def _sheet_xml(rows, widths):
    parts = [_HEAD, '<worksheet xmlns="%s">' % _MAIN]
    if widths:
        parts.append("<cols>")
        for i, w in enumerate(widths):
            parts.append('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w))
        parts.append("</cols>")
    parts.append("<sheetData>")
    for r, row in enumerate(rows, start=1):
        cells = "".join(_cell("%s%d" % (_col(c), r), v) for c, v in enumerate(row))
        parts.append('<row r="%d">%s</row>' % (r, cells))
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def _sheet_name(name, taken):
    clean = "".join("_" if ch in _BAD_SHEET_CHARS else ch for ch in str(name)).strip() or "Sheet"
    clean = clean[:31]
    candidate, n = clean, 2
    while candidate.lower() in taken:
        suffix = " (%d)" % n
        candidate = clean[:31 - len(suffix)] + suffix
        n += 1
    taken.add(candidate.lower())
    return candidate


def workbook(sheets):
    """`sheets` is [{"name": str, "rows": [[cell, ...], ...], "widths": [float, ...]?}].
    Returns the .xlsx file as bytes."""
    if not sheets:
        raise ValueError("a workbook needs at least one sheet")
    taken = set()
    names = [_sheet_name(s["name"], taken) for s in sheets]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        overrides = "".join(
            '<Override PartName="/xl/worksheets/sheet%d.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1)
            for i in range(len(sheets)))
        zf.writestr("[Content_Types].xml", (
            _HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + overrides + "</Types>"))
        zf.writestr("_rels/.rels", (
            _HEAD + '<Relationships xmlns="%s">' % _PKG_REL
            + '<Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/>' % _REL
            + "</Relationships>"))
        zf.writestr("xl/workbook.xml", (
            _HEAD + '<workbook xmlns="%s" xmlns:r="%s"><sheets>' % (_MAIN, _REL)
            + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(n, {'"': "&quot;"}), i + 1, i + 1)
                      for i, n in enumerate(names))
            + "</sheets></workbook>"))
        rels = "".join('<Relationship Id="rId%d" Type="%s/worksheet" Target="worksheets/sheet%d.xml"/>'
                       % (i + 1, _REL, i + 1) for i in range(len(sheets)))
        rels += '<Relationship Id="rId%d" Type="%s/styles" Target="styles.xml"/>' % (len(sheets) + 1, _REL)
        zf.writestr("xl/_rels/workbook.xml.rels",
                    _HEAD + '<Relationships xmlns="%s">%s</Relationships>' % (_PKG_REL, rels))
        zf.writestr("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets):
            zf.writestr("xl/worksheets/sheet%d.xml" % (i + 1), _sheet_xml(s["rows"], s.get("widths")))
    return buf.getvalue()
