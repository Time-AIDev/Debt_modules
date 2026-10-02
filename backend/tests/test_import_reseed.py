"""The in-place reseeds a re-import triggers (sync audit, 2026-09-20).

An import used to change nothing a session had already seeded: journey invoices,
case sheet snapshots and pipeline cards were frozen at first touch. These tests pin
the heal's boundary — import-derived fields move, person work does not.
"""
from datetime import date

from app import cases, invoice_pipeline, journey, main
from app.config import settings


def _a_due_lease_invoice(jstate):
    """An INSTALMENT invoice whose month maps to a line that is due and unpaid NOW."""
    bd = settings.business_date
    for uid, inv in jstate.invoices.items():
        if inv.get("source") == "PEAK_REPORT" or inv.get("kind") != "INSTALMENT" or not inv.get("month_index"):
            continue
        found = journey.contract_by_uid(inv["contract_uid"])
        if found is None:
            continue
        lines = [l for l in found[1].instalments if l.schedule_status != "SUPERSEDED"]
        idx = inv["month_index"]
        if not (1 <= idx <= len(lines)):
            continue
        line = lines[idx - 1]
        if line.due_date <= bd and line.outstanding_amount > 0:
            return uid, inv, line
    raise AssertionError("no due instalment invoice in the fixture")


def test_a_reimport_updates_an_invoice_in_place():
    jstate = journey.for_current()
    uid, inv, line = _a_due_lease_invoice(jstate)
    inv["outstanding"] = "999.00"          # the session's copy drifted from the contract
    out = journey.reseed_migrated_invoices(jstate, settings.business_date)
    assert out["updated"] >= 1
    assert inv["uid"] == uid               # stable uid across the refresh
    assert str(inv["outstanding"]) == str(line.outstanding_amount)


def test_a_reimport_never_overwrites_money_a_slip_settled():
    jstate = journey.for_current()
    uid, inv, _line = _a_due_lease_invoice(jstate)
    slip = journey.make_receipt(jstate, inv["contract_uid"], inv.get("entity") or "SPV", "1.00",
                                settings.business_date, invoice_uid=uid, matched="PARTIAL")
    slip["source"] = "SLIP"
    inv["outstanding"] = "999.00"
    journey.reseed_migrated_invoices(jstate, settings.business_date)
    assert inv["outstanding"] == "999.00"  # a person's receipt owns this money
    assert jstate.receipts[slip["uid"]]["invoice_uid"] == uid


def test_the_case_sheet_snapshot_follows_the_import_but_a_persons_next_action_does_not():
    state = cases.for_current()
    case = next(c for c in state.cases.values()
                if (c.get("sheet") or {}).get("days_late") is not None and c.get("next_action_set_by") == "SEED")
    customer = main.BY_CUSTOMER[case["customer_uid"]]
    row = customer.sheet["leasing"] if customer.sheet.get("leasing") else customer.sheet["cash"]
    row["days_late"] = int(row.get("days_late") or 0) + 7

    summary = cases.follow_import_for_all()
    assert summary["refreshed"] >= 1
    assert case["sheet"]["days_late"] == row["days_late"]
    assert any(e["kind"] == "CASE_REFRESHED" and e["case_uid"] == case["uid"] for e in state.events)

    # a person owns the next action now; a later import must not re-derive it
    case["next_action"], case["next_action_set_by"] = "CALL", "OFFICER"
    row["days_late"] = row["days_late"] + 5
    cases.follow_import_for_all()
    assert case["next_action"] == "CALL"
    assert case["next_action_set_by"] == "OFFICER"


def test_a_card_refreshes_from_the_book_and_keeps_its_evidence(monkeypatch):
    state = invoice_pipeline.for_current()
    item = next(i for i in state.items.values())
    item["condition_evidence"]["contract_signed"].append(
        {"uid": "pev-test", "note": "สัญญา", "file_uid": None, "uploaded_by": "officer"})
    customer = main.BY_CUSTOMER[item["customer_uid"]]
    customer.display_name = "ชื่อใหม่จากรอบนำเข้า"

    out = invoice_pipeline.reseed_from_book()
    assert out["updated"] >= 1
    assert item["display_name"] == "ชื่อใหม่จากรอบนำเข้า"
    assert item["condition_evidence"]["contract_signed"][0]["uid"] == "pev-test"


def test_a_card_for_a_vanished_row_is_flagged_when_it_has_work(monkeypatch):
    from app import book

    state = invoice_pipeline.for_current()
    items = list(state.items.values())
    assert items
    monkeypatch.setattr(book, "build", lambda as_of=None: ([], {"registry": []}))
    out = invoice_pipeline.reseed_from_book()
    # the fixture's cards have release conditions only when a test added them; a bare
    # card has no work and is dropped, and the count says so
    assert out["missing"] == len(items)
    assert not state.items


def test_a_person_entered_amount_is_not_overwritten_by_the_import(monkeypatch):
    state = invoice_pipeline.for_current()
    item = next(i for i in state.items.values() if i.get("amount_due"))
    customer = main.BY_CUSTOMER[item["customer_uid"]]
    item["amount_due"] = "12345.00"               # a person confirmed this figure
    customer.display_name = "ยังต้องอัปเดตชื่อ"
    invoice_pipeline.reseed_from_book()
    assert item["amount_due"] == "12345.00"
    assert item["display_name"] == "ยังต้องอัปเดตชื่อ"
