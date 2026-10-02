"""The sheet's phone number is kept whole (2026-09-20).

The reader used to mask at parse and throw the digits away, so 206 of 212 customers
had no dialable number and the only remedy was re-keying one by hand (WP9). The
number now lands with the run — this is an internal collections tool — and the hiding
moved to the serving layer: `customer_contact.phone_fields` serves the mask plus
`phone_revealable`, and `POST /v1/cases/by-customer/{uid}/phone:reveal` is the one
audited door that answers it.
"""
import pytest
from sqlalchemy import text

from app import book, customer_contact, migrate, sheet_loader
from app.imports import _IMS


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


@pytest.mark.parametrize("raw, kept", [
    ("081-234-5678", "+66812345678"),
    ("0812345678", "+66812345678"),
    ("+66 81 234 5678", "+66812345678"),
    ("+66 (0)81 234 5678", "+66812345678"),
    ("021234567", "+6621234567"),
    ("", None),
    ("   ", None),
    ("#N/A", None),
])
def test_the_sheet_phone_keeps_its_dial_form(raw, kept):
    assert _IMS.e164(raw) == kept


def test_the_order_reader_keeps_the_number_beside_the_mask():
    rows = [["Order Status", "Volt ID", "EPC Start Date", "Phone", "Email"],
            ["Order - Done", "VC00001_a_ก_", "2026-01-01", "081-234-5678", "a@b.com"],
            ["Order - Done", "VC00002_b_ข_", "2026-01-01", "", ""]]
    got = _IMS.read_orders(0, [], rows)
    assert [r["phone_masked"] for r in got] == ["08x-xxx-5678", None]
    assert [r["phone_e164"] for r in got] == ["+66812345678", None]


def test_a_loaded_payload_lands_the_number_beside_the_mask(schema):
    payload = {
        "source": {"spreadsheet_id": "test", "blocks": []},
        "customers": [{
            "volt_id": "VC00001_a_ก_", "customer_no": "C-1", "name_th": "ทดสอบ",
            "product": "LEASE", "sales_lead": None,
            "phone_masked": "08x-xxx-5678", "phone_e164": "+66812345678",
            "email_masked": None, "source_refs": [],
        }],
        "counts": {},
    }
    sheet_loader.load_payload(schema, payload)
    row = schema.execute(text("select phone_masked, phone_e164 from landing.customer "
                              "where volt_id = 'VC00001_a_ก_'")).mappings().one()
    assert row["phone_e164"] == "+66812345678"
    assert row["phone_masked"] == "08x-xxx-5678"


def test_the_book_carries_the_number_into_the_fixture_and_serves_a_mask(monkeypatch):
    monkeypatch.setattr(book, "load_sheet", lambda: {
        "source": {"blocks": []}, "counts": {},
        "customers": [{
            "volt_id": "VC00001_a_ก_", "customer_no": "C-1", "name_th": "ทดสอบ",
            "name_roman": None, "epc": None, "product": "LEASE", "sales_lead": None,
            "phone_masked": "08x-xxx-5678", "phone_e164": "+66812345678",
            "email_masked": None, "source_refs": [], "data_source": None, "order": None,
        }]})
    book.invalidate()
    _, report = book.build()
    fixture = next(c for c in report["registry"] if c.volt_id == "VC00001_a_ก_")
    assert fixture.phone_e164 == "+66812345678"
    assert fixture.phone_masked == "08x-xxx-5678"
    fields = customer_contact.phone_fields(fixture.uid, fixture)
    assert fields["phone_revealable"] is True and "phone_e164" not in fields
    assert customer_contact.reveal_phone(fixture.uid, fixture)["phone_e164"] == "+66812345678"


@pytest.mark.parametrize("raw, e164, shown, kind", [
    ("0925423597", "+66925423597", "092-542-3597", "MOBILE"),
    ("+66 84 138 5770", "+66841385770", "084-138-5770", "MOBILE"),
    # The hand-authored synthetic numbers are deliberately invalid; an unparseable
    # number is kept as typed rather than dropped — a wrong dial the officer can see
    # beats a silent None.
    ("+66000000011", "+66000000011", "+66000000011", None),
])
def test_an_imported_number_reveals_in_its_dial_form(raw, e164, shown, kind):
    assert customer_contact._dial_parts(raw) == (e164, shown, kind)
