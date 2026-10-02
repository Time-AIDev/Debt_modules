"""The file guard (vault note 10 §3 WP4, F8): a file is stored only after every rule
for its type passes, and a refusal names the rule. Standard library only.

Controller ruling (2026-09-15, ledgered): the brief's `_sniff` falls back to CSV
whenever bytes decode as UTF-8 or TIS-620 — but TIS-620 decodes almost ANY byte
string, so an arbitrary binary would be sniffed as CSV. Corrected: `_sniff` calls
something CSV only if the bytes decode (UTF-8, UTF-8 with BOM, or TIS-620) AND
contain no NUL byte AND are overwhelmingly text (>= 95% of decoded characters are
printable or common whitespace). Otherwise `_sniff` returns None, which `check`
turns into `type_not_allowed`.

Controller ruling, fix round 1 (2026-09-15, ledgered) — a security review found four
real bypasses in the brief's own code (three) plus one PDF escape:
- I1: `_check_office` trusted a zip entry's declared `file_size`, so a DOCX/XLSX
  entry with its real bytes inflating past the cap but a lying, small declared
  `file_size` sailed through. Fixed to stream every entry's REAL bytes and refuse
  `office_zip_bomb` the moment the running total crosses the cap.
- I2: a malformed "PK..." file raised a bare `zipfile.BadZipFile`/CRC exception out
  of `check()` instead of a named refusal. Fixed: every zip open/read now catches
  the library's damage exceptions and refuses a new code, `file_corrupt`.
- I3: an SVG's `<style>` element text and `style=` attribute values were never
  inspected, so `@import`/`expression(`/`javascript:`/off-document `url(...)` inside
  CSS passed untouched. Fixed: both are now scanned and refused `svg_active_content`.
- PDF escape: `/J#61vaScript` (the PDF `#XX` name-escape a reader decodes to
  `/JavaScript`) passed the literal dangerous-name regex. Fixed: `#XX` escapes are
  decoded in a scanning copy before that regex runs.
"""
import io
import struct
import zipfile
import zlib

import pytest

from app import xlsx_writer
from app.attachments import guard


def _png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _zip(parts):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return buf.getvalue()


CT = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>'
DOCX = {"[Content_Types].xml": CT, "word/document.xml": "<w:document><w:body>hello</w:body></w:document>"}


def test_a_well_formed_png_passes_and_a_corrupt_one_is_refused():
    out = guard.check(_png(), "site.png")
    assert out["kind"] == "PNG" and out["content_type"] == "image/png" and len(out["sha256"]) == 64
    with pytest.raises(guard.Refused) as exc:
        guard.check(_png()[:-3], "site.png")
    assert exc.value.code == "png_corrupt"


def test_an_extension_that_disagrees_with_the_bytes_is_refused():
    with pytest.raises(guard.Refused) as exc:
        guard.check(_png(), "site.pdf")
    assert exc.value.code == "extension_mismatch"


def test_svg_with_a_script_or_a_handler_or_an_external_href_is_refused():
    assert guard.check(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>', "a.svg")["kind"] == "SVG"
    for bad in (b'<svg><script>1</script></svg>', b'<svg onload="x()"></svg>',
                b'<svg><a href="javascript:1"/></svg>', b'<svg><image href="http://x/y.png"/></svg>',
                b'<svg><foreignObject/></svg>', b'<!DOCTYPE svg [<!ENTITY x "y">]><svg/>'):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.svg")
        assert exc.value.code == "svg_active_content"


def test_csv_with_a_formula_cell_is_refused_and_the_cell_is_named():
    assert guard.check("ชื่อ,ยอด\nมานพ,100\n".encode("utf-8"), "a.csv")["kind"] == "CSV"
    with pytest.raises(guard.Refused) as exc:
        guard.check(b"name,amount\nx,=1+1\n", "a.csv")
    assert exc.value.code == "csv_formula_cell" and "B2" in exc.value.detail


def test_xlsx_and_docx_pass_and_macros_external_links_and_dde_are_refused():
    assert guard.check(xlsx_writer.workbook([{"name": "s", "rows": [["a"]]}]), "a.xlsx")["kind"] == "XLSX"
    assert guard.check(_zip(DOCX), "a.docx")["kind"] == "DOCX"
    with pytest.raises(guard.Refused) as exc:
        guard.check(_zip({**DOCX, "word/vbaProject.bin": b"\x00"}), "a.docx")
    assert exc.value.code == "office_macro"
    with pytest.raises(guard.Refused) as exc:
        guard.check(_zip({**DOCX, "word/document.xml": '<w:instrText> DDEAUTO c:\\x</w:instrText>'}), "a.docx")
    assert exc.value.code == "office_external"
    with pytest.raises(guard.Refused) as exc:
        guard.check(_zip({**DOCX, "word/embeddings/oleObject1.bin": b"\x00"}), "a.docx")
    assert exc.value.code == "office_external"


def test_an_office_file_that_inflates_past_the_cap_is_refused_before_it_is_trusted(monkeypatch):
    monkeypatch.setattr(guard, "OFFICE_INFLATE_MAX", 1000)
    with pytest.raises(guard.Refused) as exc:
        guard.check(_zip({**DOCX, "word/media/big.bin": b"\x00" * 5000}), "a.docx")
    assert exc.value.code == "office_zip_bomb"


def test_pdf_passes_and_active_content_is_refused():
    assert guard.check(b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n", "a.pdf")["kind"] == "PDF"
    for bad in (b"%PDF-1.4\n/JavaScript (x)\n%%EOF", b"%PDF-1.4\n/Launch\n%%EOF", b"%PDF-1.4\n/EmbeddedFile\n%%EOF"):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.pdf")
        assert exc.value.code == "pdf_active_content"


def test_size_and_emptiness_are_refused_first(monkeypatch):
    from app.config import settings
    with pytest.raises(guard.Refused) as exc:
        guard.check(b"", "a.pdf")
    assert exc.value.code == "empty"
    monkeypatch.setattr(settings, "attachment_max_bytes", 10)
    with pytest.raises(guard.Refused) as exc:
        guard.check(_png(), "a.png")
    assert exc.value.code == "too_large"


def test_a_type_not_on_the_list_is_refused_by_name():
    with pytest.raises(guard.Refused) as exc:
        guard.check(b"MZ\x90\x00", "tool.exe")
    assert exc.value.code == "type_not_allowed"


def test_random_binary_bytes_named_as_csv_are_refused_as_type_not_allowed():
    """Controller ruling: TIS-620 decodes almost any byte string, so decodability
    alone can't mean CSV. Binary bytes that happen to decode under TIS-620 (no NUL,
    but not overwhelmingly printable text) must be refused by type, not accepted
    as CSV just because the extension says so."""
    raw = bytes(range(256)) * 4
    with pytest.raises(guard.Refused) as exc:
        guard.check(raw, "data.csv")
    assert exc.value.code == "type_not_allowed"


def _tis620_decodable(b):
    try:
        bytes([b]).decode("tis-620")
        return True
    except UnicodeDecodeError:
        return False


def test_binary_bytes_that_decode_cleanly_under_tis_620_but_are_not_text_are_refused():
    """A direct exercise of the controller ruling's mechanism: this blob has no NUL
    byte and decodes end to end under TIS-620 (mostly as control characters), which
    is exactly why decodability alone can't mean CSV. Because well under 95% of its
    decoded characters are printable or common whitespace, it must still be refused
    by type, not accepted as CSV just because it decodes and the extension says so."""
    raw = bytes(b for b in range(1, 256) if _tis620_decodable(b)) * 4
    assert b"\x00" not in raw
    raw.decode("tis-620")  # sanity: this blob really is TIS-620-decodable end to end
    with pytest.raises(guard.Refused) as exc:
        guard.check(raw, "data.csv")
    assert exc.value.code == "type_not_allowed"


# ---------------------------------------------------------------------------------
# Fix round 1: I1 (zip-bomb via lying size fields), I2 (damaged zip -> file_corrupt),
# I3 (SVG <style>/style= content), and the PDF #XX name-escape.
# ---------------------------------------------------------------------------------

def _patch_declared_uncompressed_size(raw, target_name, fake_size):
    """Rewrite ONLY the declared uncompressed-size (file_size) field for
    `target_name`, in BOTH the local file header and the central directory record,
    to `fake_size` — leaving the real compressed bytes, the compressed-size field
    and the CRC-32 untouched. This is the exact shape of the I1 proof of concept:
    `_check_office` used to trust `i.file_size` (this lie) without ever reading the
    entry's real bytes."""
    raw = bytearray(raw)
    name = target_name.encode()
    start = 0
    patched = 0
    while True:
        idx = raw.find(name, start)
        if idx == -1:
            break
        start = idx + 1
        if bytes(raw[idx - 30:idx - 26]) == b"PK\x03\x04":
            # local file header: 30 fixed bytes before the filename; the
            # uncompressed-size field sits at relative offset 22, i.e. name_offset-8.
            raw[idx - 8:idx - 4] = struct.pack("<I", fake_size)
            patched += 1
            continue
        if bytes(raw[idx - 46:idx - 42]) == b"PK\x01\x02":
            # central directory record: 46 fixed bytes before the filename; the
            # uncompressed-size field sits at relative offset 24, i.e. name_offset-22.
            raw[idx - 22:idx - 18] = struct.pack("<I", fake_size)
            patched += 1
    assert patched == 2, "expected to patch the local header and the central directory record, patched %d" % patched
    return bytes(raw)


def test_a_zip_bomb_with_lying_size_fields_is_refused(monkeypatch):
    """I1: a DOCX whose word/media/bomb.bin entry really inflates past the cap, with
    ONLY its declared uncompressed-size (file_size) field patched small (100) in both
    the local header and the central directory — the real compressed bytes and the
    CRC-32 are untouched, exactly reproducing the reviewer's proof of concept against
    the old `total = sum(i.file_size for i in infos)`.

    Empirically (this Python/zipfile), streaming the entry through `zf.open()`
    surfaces this as `file_corrupt`, not `office_zip_bomb`: CPython's ZipExtFile
    truncates the decompressed output it returns to the entry's declared file_size
    (our lie, 100 bytes) before comparing the running CRC to the header's CRC-32 —
    which was computed over the REAL, full 3 MB of data — so the two can never match.
    That is the I2-anticipated branch ("if patching the headers makes zipfile raise
    before inflating ... that must surface as file_corrupt"). The running-byte-count
    mechanism I1 asks for is exercised directly, without any lie, by
    test_an_office_file_that_inflates_past_the_cap_is_refused_before_it_is_trusted
    above (real and declared sizes agree there, and it is `office_zip_bomb` that
    fires). Together the two tests close I1: an honestly large entry is caught by
    the running count, and a lying-small declared size cannot be used to sneak one
    past the guard either — it is caught by zipfile's own size/CRC discipline, which
    only ever runs now because I1 makes every entry actually get read.
    """
    monkeypatch.setattr(guard, "OFFICE_INFLATE_MAX", 1_000_000)
    real = _zip({**DOCX, "word/media/bomb.bin": b"\x00" * 3_000_000})
    patched = _patch_declared_uncompressed_size(real, "word/media/bomb.bin", 100)
    with zipfile.ZipFile(io.BytesIO(patched)) as zf:
        assert zf.getinfo("word/media/bomb.bin").file_size == 100  # sanity: the lie is in place
    with pytest.raises(guard.Refused) as exc:
        guard.check(patched, "a.docx")
    assert exc.value.code == "file_corrupt"  # see docstring: the empirically observed branch


def test_a_damaged_zip_is_refused_as_file_corrupt():
    with pytest.raises(guard.Refused) as exc:
        guard.check(b"PK\x03\x04" + b"not a zip at all", "a.xlsx")
    assert exc.value.code == "file_corrupt"


def _flip_one_content_byte(raw, target_name):
    """Flip the first byte of `target_name`'s compressed data in place, leaving its
    declared sizes and CRC-32 untouched — a minimally damaged, otherwise well-formed
    zip entry."""
    raw = bytearray(raw)
    name = target_name.encode()
    idx = raw.find(name)
    assert idx != -1 and bytes(raw[idx - 30:idx - 26]) == b"PK\x03\x04"
    fn_len = struct.unpack("<H", bytes(raw[idx - 4:idx - 2]))[0]
    extra_len = struct.unpack("<H", bytes(raw[idx - 2:idx]))[0]
    assert fn_len == len(name)
    data_start = idx + fn_len + extra_len
    raw[data_start] ^= 0xFF
    return bytes(raw)


def test_a_zip_entry_with_a_bad_crc_is_refused_as_file_corrupt():
    corrupted = _flip_one_content_byte(_zip(DOCX), "word/document.xml")
    with pytest.raises(guard.Refused) as exc:
        guard.check(corrupted, "a.docx")
    assert exc.value.code == "file_corrupt"


def test_svg_style_element_with_import_or_javascript_url_is_refused():
    bad = (b'<svg><style>*{fill:url(javascript:alert(1))} '
           b'@import url("http://evil.example/x.css");</style></svg>')
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"


def test_svg_style_attribute_with_javascript_url_is_refused():
    with pytest.raises(guard.Refused) as exc:
        guard.check(b'<svg><rect style="fill:url(javascript:1)"/></svg>', "a.svg")
    assert exc.value.code == "svg_active_content"


def test_svg_style_attribute_with_a_fragment_url_is_allowed():
    ok = b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(#grad)"/></svg>'
    assert guard.check(ok, "a.svg")["kind"] == "SVG"


# Final review (minor): the sniff calls anything with "<svg" in it an SVG, so the
# document's own root must be <svg>; and a protocol-relative href is external.

def test_a_document_whose_root_is_not_svg_is_refused_by_name():
    for bad in (b'<html xmlns="http://www.w3.org/1999/xhtml"><body><svg/></body></html>',
                b'<?xml version="1.0"?><div><svg xmlns="http://www.w3.org/2000/svg"/></div>'):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.svg")
        assert exc.value.code == "svg_root" and exc.value.detail_th


def test_a_namespaced_svg_root_is_still_an_svg():
    ok = b'<?xml version="1.0"?><svg:svg xmlns:svg="http://www.w3.org/2000/svg"><svg:rect/></svg:svg>'
    assert guard.check(ok, "a.svg")["kind"] == "SVG"


def test_a_protocol_relative_href_is_refused_like_an_external_one():
    for bad in (b'<svg xmlns="http://www.w3.org/2000/svg"><image href="//evil.example/x.png"/></svg>',
                b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
                b'<a xlink:href=" //evil.example/"/></svg>'):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.svg")
        assert exc.value.code == "svg_active_content"


def test_a_pdf_name_written_with_hex_escapes_is_refused():
    with pytest.raises(guard.Refused) as exc:
        guard.check(b"%PDF-1.4\n/J#61vaScript (x)\n%%EOF", "a.pdf")
    assert exc.value.code == "pdf_active_content"


# ---------------------------------------------------------------------------------
# Task 25a: the router decodes X-Volt-Filename before calling check(); check()'s own
# sanitiser must still widen past \w to keep the Thai block (U+0E00-U+0E7F), because
# Thai vowel and tone marks are category Mn and are NOT matched by \w even once a
# name is decoded.
# ---------------------------------------------------------------------------------

def test_a_thai_file_name_keeps_its_vowel_marks():
    out = guard.check(_png(), "สลิปโอนเงิน.png")
    assert out["filename"] == "สลิปโอนเงิน.png"


# ---------------------------------------------------------------------------------
# Task 25c: an href/xlink:href/src on an SVG element is allowed ONLY empty or an
# internal fragment (#...) after every ASCII whitespace/control character
# (U+0000-U+0020, U+007F) is stripped out -- a scheme-prefix denylist still let a
# backslash or an XML character reference that decodes to a tab through, which a
# browser treats as protocol-relative.
# ---------------------------------------------------------------------------------

def test_svg_href_bypasses_via_backslash_or_a_decoded_control_character_are_refused():
    for bad in (b'<svg xmlns="http://www.w3.org/2000/svg"><image href="/\\evil.example"/></svg>',
                b'<svg xmlns="http://www.w3.org/2000/svg"><image href="\\\\evil.example"/></svg>',
                b'<svg xmlns="http://www.w3.org/2000/svg"><image href="/&#9;/evil.example"/></svg>'):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.svg")
        assert exc.value.code == "svg_active_content"


def test_svg_href_and_xlink_href_fragments_still_pass():
    ok = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
         b'<a href="#grad1"/><a xlink:href="#p"/></svg>')
    assert guard.check(ok, "a.svg")["kind"] == "SVG"


def test_an_svg_with_no_hrefs_still_passes():
    ok = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
    assert guard.check(ok, "a.svg")["kind"] == "SVG"


# ---------------------------------------------------------------------------------
# Task 25c fix round 1, finding 3: the refusal must echo the NORMALISED value, not
# the raw one -- a decoded control character (XML "&#9;" -> a literal tab) must
# never reach `detail`.
# ---------------------------------------------------------------------------------

def test_svg_href_refusal_names_the_normalised_value_not_the_raw_one():
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="/&#9;/evil.example"/></svg>'
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"
    assert "\t" not in exc.value.detail and "\r" not in exc.value.detail and "\n" not in exc.value.detail
    assert "//evil.example" in exc.value.detail  # the tab is gone, not merely hidden


# ---------------------------------------------------------------------------------
# Task 25c fix round 1, minor: a SMIL <set>/<animate>/<animateMotion>/
# <animateTransform> can retarget href without ever writing an href/xlink:href/src
# attribute itself.
# ---------------------------------------------------------------------------------

def test_svg_smil_set_or_animate_retargeting_href_is_refused():
    for bad in (b'<svg xmlns="http://www.w3.org/2000/svg"><set attributeName="href" to="javascript:alert(1)"/></svg>',
                b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="href" values="javascript:alert(1)"/></svg>',
                b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
                b'<set attributeName="xlink:href" to="//evil.example"/></svg>'):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.svg")
        assert exc.value.code == "svg_active_content"


def test_svg_smil_to_from_by_values_carrying_script_or_import_are_refused():
    # Fix round 2, finding (b): to/from/by/values are held to the SAME rule as
    # <style>/style= (javascript:, expression(, @import, a url(...) that is not a
    # #fragment) -- NOT the stricter empty-or-fragment test round 1 wrongly used,
    # which refused an ordinary animation too (see the "still pass" test below).
    for bad in (b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="x" to="javascript:alert(1)"/></svg>',
                b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="x" from="expression(alert(1))"/></svg>',
                b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="x" by="@import url(evil.css)"/></svg>',
                # values is ";"-separated -- one bad part among good ones is still refused.
                b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="x" values="#a;javascript:alert(1);#b"/></svg>'):
        with pytest.raises(guard.Refused) as exc:
            guard.check(bad, "a.svg")
        assert exc.value.code == "svg_active_content"


def test_svg_smil_values_with_a_javascript_part_among_good_ones_is_refused():
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="x" values="#a; javascript:alert(1)"/></svg>'
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"


def test_svg_smil_to_with_a_wrapped_url_off_document_is_refused():
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="x" to="url(//evil.example)"/></svg>'
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"


def test_svg_smil_animation_of_an_ordinary_attribute_with_fragment_values_passes():
    ok = b'<svg xmlns="http://www.w3.org/2000/svg"><animate attributeName="x" to="#a" values="#a;#b;"/></svg>'
    assert guard.check(ok, "a.svg")["kind"] == "SVG"


def test_svg_animatetransform_with_no_smil_value_attrs_still_passes():
    ok = b'<svg xmlns="http://www.w3.org/2000/svg"><animateTransform attributeName="transform"/></svg>'
    assert guard.check(ok, "a.svg")["kind"] == "SVG"


# ---------------------------------------------------------------------------------
# Task 25c fix round 2, finding (b): a legitimate colour, number, or transform
# animation must pass -- round 1's stricter empty-or-fragment test on to/from/by/
# values refused these outright ("SVG references red").
# ---------------------------------------------------------------------------------

def test_svg_smil_ordinary_colour_and_number_animations_pass():
    ok = (b'<svg xmlns="http://www.w3.org/2000/svg">'
         b'<animate attributeName="fill" values="red;blue"/>'
         b'<animate attributeName="opacity" from="0" to="1"/>'
         b'</svg>')
    assert guard.check(ok, "a.svg")["kind"] == "SVG"


def test_svg_animatetransform_ordinary_transform_values_pass():
    ok = (b'<svg xmlns="http://www.w3.org/2000/svg"><animateTransform attributeName="transform" '
         b'type="rotate" from="0 50 50" to="360 50 50"/></svg>')
    assert guard.check(ok, "a.svg")["kind"] == "SVG"


def test_svg_animatecolor_is_recognised_as_a_smil_tag():
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><animateColor attributeName="href" to="javascript:alert(1)"/></svg>'
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"


# ---------------------------------------------------------------------------------
# Task 25c fix round 2, finding (a): a decoy namespaced attributeName/to duplicate
# must not hide the real one -- `_local_attr` (singular) returned the FIRST match
# in document order, so a namespaced decoy declared before the real, plain
# attribute made the guard look at the decoy and never the real one.
# ---------------------------------------------------------------------------------

def test_svg_smil_decoy_namespaced_attributename_does_not_hide_the_real_one():
    # The reviewer's exact probe: a decoy x:attributeName="fill"/x:to="#a" appears
    # BEFORE the real, un-namespaced attributeName="href"/to="javascript:...".
    bad = (b'<svg xmlns="http://www.w3.org/2000/svg"><a><set xmlns:x="urn:x" '
          b'x:attributeName="fill" attributeName="href" x:to="#a" to="javascript:alert(1)"/></a></svg>')
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"


def test_svg_smil_attributename_with_a_prefix_bound_to_the_xlink_namespace_is_refused():
    # attributeName's own value is a plain string a renderer resolves against the
    # document's namespace bindings -- "foo:href", with "foo" bound to XLink, names
    # the same real attribute xlink:href does. The last-":"-part rule catches it
    # without actually resolving the binding.
    bad = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:foo="http://www.w3.org/1999/xlink">'
          b'<set attributeName="foo:href" to="javascript:alert(1)"/></svg>')
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"


def test_svg_smil_attributename_src_is_also_refused():
    # Fix round 2, finding (a): "src" is refused alongside "href"/"xlink:href".
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><set attributeName="src" to="javascript:alert(1)"/></svg>'
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"


# ---------------------------------------------------------------------------------
# Task 25c fix round 2, finding (d): _css_active_content's url() refusal (from
# both style= and <style>) must echo the NORMALISED target, not the raw one.
# ---------------------------------------------------------------------------------

def test_svg_style_attribute_url_refusal_names_the_normalised_value():
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(/&#9;/evil.example)"/></svg>'
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"
    assert "\t" not in exc.value.detail and "\r" not in exc.value.detail and "\n" not in exc.value.detail
    assert "//evil.example" in exc.value.detail


def test_svg_style_element_url_refusal_names_the_normalised_value():
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><style>*{fill:url(/&#9;/evil.example)}</style></svg>'
    with pytest.raises(guard.Refused) as exc:
        guard.check(bad, "a.svg")
    assert exc.value.code == "svg_active_content"
    assert "\t" not in exc.value.detail and "\r" not in exc.value.detail and "\n" not in exc.value.detail
    assert "//evil.example" in exc.value.detail
