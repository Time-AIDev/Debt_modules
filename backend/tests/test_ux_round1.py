"""UX loop, round 1 — the backend half of cluster 1.

The loop's contract lives in docs/ux-loop/00-design-contract.md; the finding these
tests pin is A's E6 / C7 (docs/ux-loop/round-1/cluster-1/A-research.md):

    The work book offered TWO exports and neither was a superset of the other. The
    server projection carried aging_bucket_label_th, invoice_state and
    invoice_peak_state; the screen's own client-side CSV carried customer_no, entity
    and amount_to_ask — and it was the one labelled "ส่งออกครบทุกคอลัมน์" (export
    every column). The team could not rebuild its own sheet from either file, and the
    button that claimed completeness was the one missing three columns.

Arina's ruling (round 1, decision 2): one export, and the claim becomes true. The
three client-only columns move into the server projection. These tests are an
ADDITION — no existing assertion was changed to make them pass.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

# Every column the screen's own CSV used to carry that the server projection did not.
# If one of these ever leaves meta["columns"] again, the export stops being a superset
# and the "every column" claim becomes false a second time.
CLIENT_ONLY_BEFORE = ("customer_no", "entity", "amount_to_ask")
# The three the server already had and the client CSV did not, kept here so the pair
# is documented in one place.
SERVER_ONLY_BEFORE = ("aging_bucket_label_th", "invoice_state", "invoice_peak_state")


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def test_the_workbook_projection_carries_both_sides_of_the_old_split(client):
    meta = client.get("/v1/workbook").json()["meta"]
    for column in CLIENT_ONLY_BEFORE + SERVER_ONLY_BEFORE:
        assert column in meta["columns"], column
    # No column is named twice — the header is what the reader sorts and filters on.
    assert len(meta["columns"]) == len(set(meta["columns"]))


def test_the_export_header_and_its_rows_stay_in_lockstep(client):
    """A column added to the list and not to the writer silently shifts every value
    one cell to the left, which is worse than a missing column."""
    meta = client.get("/v1/workbook").json()["meta"]
    body = client.get("/v1/workbook:export").text.lstrip("﻿")
    lines = [line for line in body.splitlines() if line]
    assert lines[0].split(",") == meta["columns"]
    import csv
    import io
    rows = list(csv.reader(io.StringIO(body)))
    assert len(rows) - 1 == meta["total"]
    for row in rows[1:]:
        assert len(row) == len(meta["columns"])


def test_the_added_columns_carry_the_values_the_screen_shows(client):
    """Not just present in the header — carrying the row's own figures, unchanged."""
    import csv
    import io
    data = client.get("/v1/workbook").json()
    body = client.get("/v1/workbook:export").text.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(body)))
    by_volt_id = {r["volt_id"]: r for r in rows}
    checked = 0
    for row in data["rows"]:
        out = by_volt_id.get(row["case"]["volt_id"])
        if out is None:
            continue
        assert out["customer_no"] == (row["customer"].get("customer_no") or "")
        assert out["entity"] == (row.get("entity") or "")
        ask = (row.get("money_position") or {}).get("amount_to_ask")
        assert out["amount_to_ask"] == ("" if ask is None else str(ask))
        checked += 1
    assert checked > 100, "the migrated book is in the file, not a handful of rows"


def test_entity_and_product_are_two_columns_because_they_answer_two_questions(client):
    """`product` is the sheet's word (LEASE / CASH); `entity` is which PEAK instance
    books the receivable (SPV / EPC). Data Model v2.3: entity and company_id travel
    together, and a reader reconciling against PEAK needs the entity, not the word."""
    import csv
    import io
    body = client.get("/v1/workbook:export").text.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(body)))
    assert {r["product"] for r in rows} <= {"LEASE", "CASH"}
    assert {r["entity"] for r in rows} <= {"SPV", "EPC"}
    assert any(r["product"] != r["entity"] for r in rows)
