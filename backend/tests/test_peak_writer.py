"""One PEAK import_run: the rows, the receipt, apply, and the read the book uses.
Feedback Round 1 / WP1 (design note 10 §3, F4)."""
import json

import pytest
from sqlalchemy import text

from app import landing, migrate


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    yield pg_conn
    # `records` is outside the schemas conftest truncates (deliberately — it must
    # outlive a deploy), so this file cleans its own rows.
    pg_conn.execute(text("delete from records.identity_link"))


def test_the_schema_accepts_a_peak_run_and_holds_its_invoices(schema):
    run = landing.start_run(schema, "PEAK", meta={"report_as_of": "2026-09-14"})
    schema.execute(text(
        "insert into landing.peak_invoice (import_run_id, doc_no, doc_kind, status, verdict, lines) "
        "values (:r, 'IVT-20260700089', 'IVT', 'PAID', 'UNMATCHED', '[]'::jsonb)"), {"r": run})
    assert schema.execute(text("select count(*) from landing.peak_invoice")).scalar() == 1


def test_the_link_register_allows_one_active_link_per_contact_code(schema):
    schema.execute(text(
        "insert into records.identity_link (contact_code, customer_no, rule, confirmed_by) "
        "values ('VC0098765', '28005096535', 'PERSON', 'settasak')"))
    with pytest.raises(Exception):
        with schema.begin_nested():
            schema.execute(text(
                "insert into records.identity_link (contact_code, customer_no, rule, confirmed_by) "
                "values ('VC0098765', '28000000001', 'PERSON', 'settasak')"))


from app.pipelines import peak_links, peak_writer


def _parsed(*invoices, as_of="2026-09-14"):
    return {"report_as_of": as_of, "header_row": 10, "lines": [], "rejected": [], "invoices": list(invoices)}


def _inv(doc, code, status="PAID", cycle=None, payment=None, awaiting="0.00"):
    return {"doc_no": doc, "doc_kind": doc.split("-")[0], "issued_on": "2026-07-11", "due_on": "2026-07-18",
            "reference": code, "system_reference": None, "contact_code": code, "customer_name": "Someone",
            "tax_id_13": "1234567890121", "status": status, "cycle": cycle, "product_group": "Solar Leasing",
            "amount_total": "8399.00", "amount_due": "8399.00", "amount_awaiting": awaiting,
            "payment": payment, "note": None, "lines": [{"line_no": 1, "product_code": "P00004",
                                                          "description": "Installment_M14/48", "amount": "8399.00"}]}


EXACT = {"verdict": "EXACT", "rule": "CUSTOMER_NO", "customer_no": "28005096535", "candidates": []}
CAND = {"verdict": "CANDIDATE", "rule": None, "customer_no": None,
        "candidates": [{"customer_no": "28005096535", "rule": "COMPOSITE:VOLT_ID", "code": "VC0098765"}]}
NONE = {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}


def test_a_run_lands_every_invoice_with_its_verdict_and_never_the_13_digit_id(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), _inv("IV-2", "VL0010239,VC0098765"),
                                               _inv("IV-3", "VRC0000022")), [EXACT, CAND, NONE], door="upload",
                               filename="export_as_of_20240101_20260914.xlsx")
    assert (result["invoices"], result["matched"], result["candidates"], result["unmatched"]) == (3, 1, 1, 1)
    cols = {r[0] for r in schema.execute(text(
        "select column_name from information_schema.columns where table_schema='landing' and table_name='peak_invoice'"))}
    assert "tax_id_13" not in cols
    meta = schema.execute(text("select meta from landing.import_run where id=:i"), {"i": result["run_id"]}).scalar()
    assert "1234567890121" not in json.dumps(meta)
    assert meta["report_as_of"] == "2026-09-14" and meta["door"] == "upload"


def test_import_run_meta_keeps_only_schema_diagnostics_from_the_parser(schema):
    parsed = _parsed(_inv("IV-1", "28005096535"))
    parsed["schema"] = {"report_type": "invoice", "header_row": 11,
                        "detected_fields": ["doc_no"], "ignored_headings": ["สาขา"]}
    result = peak_writer.write(schema, parsed, [EXACT])
    meta = schema.execute(text("select meta from landing.import_run where id=:i"),
                          {"i": result["run_id"]}).scalar()
    assert meta["schema"] == parsed["schema"]


def test_a_cancelled_invoice_lands_for_traceability_but_is_not_served_to_the_book(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535", status="CANCELLED")), [EXACT])
    peak_writer.apply_run(schema, result["run_id"], by="settasak")

    stored = schema.execute(text(
        "select status from landing.peak_invoice where import_run_id=:r and doc_no='IV-1'"),
        {"r": result["run_id"]}).scalar()

    assert stored == "CANCELLED"
    assert peak_writer.invoices_for_book(schema) == {}


def test_a_staged_run_is_not_read_by_the_book_until_it_is_applied(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535")), [EXACT])
    assert peak_writer.invoices_for_book(schema) == {}
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    served = peak_writer.invoices_for_book(schema)
    assert served["28005096535"]["report_as_of"] == "2026-09-14"
    assert served["28005096535"]["invoices"][0]["doc_no"] == "IV-1"


def test_applying_an_older_report_over_a_newer_one_refuses_unless_allowed(schema):
    new = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), as_of="2026-09-14"), [EXACT])
    peak_writer.apply_run(schema, new["run_id"], by="settasak")
    old = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), as_of="2026-08-31"), [EXACT])
    with pytest.raises(peak_writer.WriterRefused) as exc:
        peak_writer.apply_run(schema, old["run_id"], by="settasak")
    assert exc.value.code == "report_older_than_applied"
    peak_writer.apply_run(schema, old["run_id"], by="settasak", allow_older=True)
    assert peak_writer.last_run(schema, applied=True)["id"] == old["run_id"]


def test_a_confirmed_link_lifts_a_candidate_row_into_the_book_without_a_re_run(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-2", "VL0010239,VC0098765")), [CAND])
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    assert peak_writer.invoices_for_book(schema) == {}
    link = peak_links.confirm(schema, "vl0010239,vc0098765", "28005096535", by="settasak", reason="package change")
    assert link["contact_code"] == "VL0010239,VC0098765"
    assert peak_writer.invoices_for_book(schema)["28005096535"]["invoices"][0]["rule"] == "LINK"
    peak_links.retire(schema, link["uid"], by="settasak")
    assert peak_writer.invoices_for_book(schema) == {}


def test_confirming_a_code_again_retires_the_earlier_link_and_keeps_it_as_history(schema):
    first = peak_links.confirm(schema, "VC0098765", "28005096535", by="settasak")
    second = peak_links.confirm(schema, "VC0098765", "28006083653", by="settasak", reason="wrong person")
    assert peak_links.load(schema)["VC0098765"]["customer_no"] == "28006083653"
    history = peak_links.list_links(schema, include_retired=True)
    assert {l["uid"] for l in history} == {first["uid"], second["uid"]}


def test_rows_are_paged_by_verdict(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), _inv("IV-3", "VRC0000022")), [EXACT, NONE])
    page = peak_writer.rows(schema, result["run_id"], verdict="UNMATCHED", limit=10, offset=0)
    assert page["total"] == 1 and page["rows"][0]["doc_no"] == "IV-3"


def test_rows_carry_the_active_link_so_a_resolved_row_leaves_the_pending_list(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-2", "VL0010239,VC0098765")), [CAND])
    assert peak_writer.rows(schema, result["run_id"], verdict="CANDIDATE")["rows"][0]["linked_no"] is None
    peak_links.confirm(schema, "vl0010239,vc0098765", "28005096535", by="settasak")
    row = peak_writer.rows(schema, result["run_id"], verdict="CANDIDATE")["rows"][0]
    assert row["linked_no"] == "28005096535"


def test_the_odoo_phone_rows_come_from_ok_runs_only(schema):
    run = landing.start_run(schema, "ODOO")
    landing.write_customer(schema, run, "ODOO", {"volt_id": "VL0010239", "customer_no": "VL0010239",
                                                 "phone_e164": "0812345678", "source_refs": []})
    assert peak_writer.odoo_phone_rows(schema) == []
    landing.finish_run(schema, run, "OK")
    assert peak_writer.odoo_phone_rows(schema) == [{"volt_id": "VL0010239", "phone_e164": "0812345678"}]


def test_an_invoice_with_two_linked_codes_is_served_once_to_the_contact_codes_customer(schema):
    inv = _inv("IV-7", "CODEA")
    inv["reference"] = "CODEB"
    result = peak_writer.write(schema, _parsed(inv), [CAND])
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    peak_links.confirm(schema, "CODEA", "28005096535", by="settasak")
    peak_links.confirm(schema, "CODEB", "28006083653", by="settasak")
    served = peak_writer.invoices_for_book(schema)
    assert set(served.keys()) == {"28005096535"}
    assert [i["doc_no"] for i in served["28005096535"]["invoices"]] == ["IV-7"]


def test_a_link_joins_a_contact_code_that_carries_a_tab(schema):
    inv = _inv("IV-9", "COD\tEC")
    result = peak_writer.write(schema, _parsed(inv), [CAND])
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    link = peak_links.confirm(schema, "COD\tEC", "28005096535", by="settasak")
    assert link["contact_code"] == "CODEC"
    served = peak_writer.invoices_for_book(schema)
    assert served["28005096535"]["invoices"][0]["doc_no"] == "IV-9"


def test_an_undated_report_needs_allow_older_over_an_applied_one(schema):
    dated = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), as_of="2026-09-14"), [EXACT])
    peak_writer.apply_run(schema, dated["run_id"], by="settasak")
    undated = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), as_of=None), [EXACT])
    with pytest.raises(peak_writer.WriterRefused) as exc:
        peak_writer.apply_run(schema, undated["run_id"], by="settasak")
    assert exc.value.code == "report_as_of_unknown"
    peak_writer.apply_run(schema, undated["run_id"], by="settasak", allow_older=True)
    assert peak_writer.last_run(schema, applied=True)["id"] == undated["run_id"]


def test_a_dated_report_may_replace_an_undated_applied_one(schema):
    undated = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), as_of=None), [EXACT])
    peak_writer.apply_run(schema, undated["run_id"], by="settasak")
    dated = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535"), as_of="2026-09-14"), [EXACT])
    peak_writer.apply_run(schema, dated["run_id"], by="settasak")
    assert peak_writer.last_run(schema, applied=True)["id"] == dated["run_id"]


def test_rows_serve_amounts_as_strings(schema):
    inv = _inv("IV-1", "28005096535",
               payment={"on": "2026-07-12", "channel": "BANK", "amount": "8399.00", "receipt_no": "RC-1"})
    result = peak_writer.write(schema, _parsed(inv), [EXACT])
    page = peak_writer.rows(schema, result["run_id"])
    row = page["rows"][0]
    for key in ("amount_total", "amount_due", "amount_awaiting", "paid_amount"):
        assert isinstance(row[key], str), key


# --- Final review C1: the link register is authoritative at READ time ------------
# invoices_for_book served an EXACT row by its STORED customer_no and joined the
# register only for rows that were not EXACT, so a link confirmed after an exact
# match never moved the invoice, and a retired link kept serving the row it had
# lifted. Each row now also stores the ladder's own verdict WITHOUT links
# (ladder_verdict / ladder_customer_no / ladder_rule); the read is: active link →
# linked customer (LINK); else ladder EXACT → ladder customer; else a legacy row
# (no ladder columns) only when it was EXACT by a rule other than LINK.

A, B, C = "28005096535", "28006083653", "28000000003"


def _exact_to(no, rule="CUSTOMER_NO"):
    return {"verdict": "EXACT", "rule": rule, "customer_no": no, "candidates": []}


def _link_to(no):
    return {"verdict": "EXACT", "rule": "LINK", "customer_no": no, "candidates": []}


def _applied(schema, invoices, verdicts, ladder=None):
    kwargs = {} if ladder is None else {"ladder": ladder}
    result = peak_writer.write(schema, _parsed(*invoices), verdicts, **kwargs)
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    return result


def test_the_ladder_columns_are_stored_per_row_and_never_the_13_digit_id(schema):
    result = peak_writer.write(schema, _parsed(_inv("IV-20", "VC0098765")), [_link_to(A)], ladder=[_exact_to(C, "VOLT_ID")])
    row = schema.execute(text(
        "select verdict, rule, customer_no, ladder_verdict, ladder_customer_no, ladder_rule "
        "from landing.peak_invoice where import_run_id = :r"), {"r": result["run_id"]}).mappings().one()
    assert dict(row) == {"verdict": "EXACT", "rule": "LINK", "customer_no": A,
                         "ladder_verdict": "EXACT", "ladder_customer_no": C, "ladder_rule": "VOLT_ID"}
    stored = schema.execute(text("select row_to_json(p)::text from landing.peak_invoice p")).scalar()
    assert "1234567890121" not in stored


def test_a_link_confirmed_after_an_exact_match_serves_the_invoice_to_the_linked_customer(schema):
    _applied(schema, [_inv("IV-21", A)], [_exact_to(A)], ladder=[_exact_to(A)])
    assert set(peak_writer.invoices_for_book(schema)) == {A}
    peak_links.confirm(schema, A, B, by="settasak", reason="the code is B's")
    served = peak_writer.invoices_for_book(schema)
    assert set(served) == {B}, "the register outranks the stored exact match"
    assert [(i["doc_no"], i["rule"]) for i in served[B]["invoices"]] == [("IV-21", "LINK")]


def test_a_legacy_exact_row_is_also_moved_by_a_later_link(schema):
    # a run landed before the ladder columns existed: they are NULL
    _applied(schema, [_inv("IV-22", A)], [_exact_to(A)])
    peak_links.confirm(schema, A, B, by="settasak", reason="the code is B's")
    assert set(peak_writer.invoices_for_book(schema)) == {B}


def test_retiring_the_link_that_matched_a_row_stops_serving_it_when_the_ladder_alone_does_not_match(schema):
    link = peak_links.confirm(schema, "VRC0000022", A, by="settasak", reason="confirmed by phone")
    _applied(schema, [_inv("IV-23", "VRC0000022")], [_link_to(A)], ladder=[NONE])
    assert set(peak_writer.invoices_for_book(schema)) == {A}
    peak_links.retire(schema, link["uid"], by="settasak")
    assert peak_writer.invoices_for_book(schema) == {}


def test_retiring_the_link_that_matched_a_row_serves_it_to_the_ladders_own_exact_customer(schema):
    link = peak_links.confirm(schema, "VC0098765", A, by="settasak", reason="confirmed by phone")
    _applied(schema, [_inv("IV-24", "VC0098765")], [_link_to(A)], ladder=[_exact_to(C, "VOLT_ID")])
    assert set(peak_writer.invoices_for_book(schema)) == {A}
    peak_links.retire(schema, link["uid"], by="settasak")
    served = peak_writer.invoices_for_book(schema)
    assert set(served) == {C}
    assert [(i["doc_no"], i["rule"]) for i in served[C]["invoices"]] == [("IV-24", "VOLT_ID")]


def test_a_legacy_row_stored_as_a_link_is_not_served_without_an_active_link(schema):
    _applied(schema, [_inv("IV-25", "VRC0000022")], [_link_to(A)])
    assert peak_writer.invoices_for_book(schema) == {}


def test_a_candidate_row_whose_ladder_is_not_exact_is_not_served(schema):
    _applied(schema, [_inv("IV-26", "VL0010239,VC0098765")], [CAND], ladder=[CAND])
    assert peak_writer.invoices_for_book(schema) == {}


# --- Final review I2: applying an older-uploaded run over a newer one -------------
# last_run(applied=True) ordered by id, so applying an earlier-uploaded run (with
# allow_older) over a later-uploaded one was a silent no-op — the later run kept
# serving. Applied runs are ordered by their applied-at mark now, and a run that is
# already applied is refused rather than re-stamped.

def test_applying_an_earlier_uploaded_run_with_allow_older_serves_it(schema):
    run_a = peak_writer.write(schema, _parsed(_inv("IV-A", A), as_of="2026-09-14"), [_exact_to(A)])
    run_b = peak_writer.write(schema, _parsed(_inv("IV-B", B), as_of="2026-09-15"), [_exact_to(B)])
    peak_writer.apply_run(schema, run_b["run_id"], by="settasak")
    assert set(peak_writer.invoices_for_book(schema)) == {B}
    peak_writer.apply_run(schema, run_a["run_id"], by="settasak", allow_older=True)
    assert peak_writer.last_run(schema, applied=True)["id"] == run_a["run_id"]
    served = peak_writer.invoices_for_book(schema)
    assert set(served) == {A}
    assert served[A]["report_as_of"] == "2026-09-14"


def test_re_applying_an_applied_run_is_refused(schema):
    run = peak_writer.write(schema, _parsed(_inv("IV-A", A)), [_exact_to(A)])
    peak_writer.apply_run(schema, run["run_id"], by="settasak")
    with pytest.raises(peak_writer.WriterRefused) as exc:
        peak_writer.apply_run(schema, run["run_id"], by="settasak", allow_older=True)
    assert exc.value.code == "already_applied" and exc.value.detail_th


def test_invoices_land_in_chunks_and_progress_counts_landed_invoices(schema):
    # The 2026-09-20 batch path: one INSERT per 500 invoices, and on_progress still
    # reports invoices actually written — never lines, never a chunk index.
    seen = []
    invoices = [_inv("IV-%04d" % i, "VL%07d" % i) for i in range(1100)]
    result = peak_writer.write(schema, _parsed(*invoices), [NONE] * 1100,
                               on_progress=lambda **kw: seen.append(kw))
    assert result["invoices"] == 1100
    assert schema.execute(text("select count(*) from landing.peak_invoice")).scalar() == 1100
    assert seen == [{"landed": 500}, {"landed": 1000}, {"landed": 1100}]


def test_rejected_lines_are_written_where_the_rows_endpoint_reads_them(schema):
    """The rows endpoint offered verdict=REJECTED since the run view existed, and it
    was always empty: nothing ever wrote the rejected lines (sync audit, 2026-09-20)."""
    parsed = _parsed(_inv("IVT-90012", "99999000001"), as_of="2026-09-14")
    parsed["rejected"] = [{"row": 12, "code": "status_unknown", "value": "รอตรวจ"},
                          {"row": 15, "code": "status_unknown", "value": "ยกเลิก"}]
    result = peak_writer.write(schema, parsed, [_exact_to("99999000001")])
    out = peak_writer.rows(schema, result["run_id"], verdict="REJECTED")
    assert out["total"] == 2
    assert {r["code"] for r in out["rows"]} == {"status_unknown"}
    assert {r["value"] for r in out["rows"]} == {"รอตรวจ", "ยกเลิก"}
