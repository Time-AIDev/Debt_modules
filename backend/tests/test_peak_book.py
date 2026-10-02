"""PEAK facts reach the domain through the one seam the sheet already uses."""
import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import book_source, cases, journey, landing, main, migrate
from app.book import SHEET
from app.config import settings
from app.main import app
from app.pipelines import peak_writer
from tests.test_peak_writer import _parsed, _inv, EXACT


@pytest.fixture
def client():
    # Task 25c fix round 1: `_with_peak`/`journey.reseed_peak` below mutate the
    # "shared" session's state directly, in-process (no HTTP request is involved).
    # tester_session (main.py) hands a request with NO cookie a brand-new random
    # session id, which would see none of that state -- the cookie must be forced
    # to "shared" so the HTTP call below lands in the SAME session/state.
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    yield pg_conn
    pg_conn.execute(text("delete from records.identity_link"))


def _sheet_customer(conn, customer_no="28005096535"):
    run = landing.start_run(conn, "SHEET")
    landing.write_customer(conn, run, "SHEET", {
        "volt_id": "%s_Manop_มานพ ทดสอบ_IPW" % customer_no, "customer_no": customer_no, "name_th": "มานพ ทดสอบ",
        "epc": "IPW", "product": "LEASE", "source_refs": []})
    landing.finish_run(conn, run, "OK")


def test_an_applied_run_puts_a_peak_block_on_the_customer_and_an_unapplied_one_does_not(schema):
    _sheet_customer(schema)
    result = peak_writer.write(schema, _parsed(_inv("IV-1", "28005096535", cycle={"n": 14, "of": 48})), [EXACT])
    rec = next(c for c in book_source._from_landing(schema)["customers"] if c["customer_no"] == "28005096535")
    assert rec["peak"] is None
    peak_writer.apply_run(schema, result["run_id"], by="settasak")
    rec = next(c for c in book_source._from_landing(schema)["customers"] if c["customer_no"] == "28005096535")
    assert rec["peak"]["report_as_of"] == "2026-09-14"
    assert rec["peak"]["invoices"][0]["cycle"] == {"n": 14, "of": 48}


def test_the_fixture_path_carries_the_key_as_none_so_no_caller_has_to_guard():
    rec = book_source.load()["customers"][0]
    assert "peak" in rec and rec["peak"] is None


def test_reload_book_rebinds_the_globals_in_place():
    before = main.CUSTOMERS
    main.reload_book()
    assert main.CUSTOMERS is not before
    # 2026-09-19: identites are served beside the book (contract-less crm.lead rows),
    # so BY_CUSTOMER is the union — and the two lists stay disjoint by uid.
    assert set(main.BY_CUSTOMER) == {c.uid for c in main.CUSTOMERS + main.IDENTITIES}
    assert not ({c.uid for c in main.CUSTOMERS} & {c.uid for c in main.IDENTITIES})
    assert all(main.BY_CONTRACT[k.uid][0] is c for c in main.CUSTOMERS for k in c.contracts)


def _with_peak(invoices, report_as_of="2026-09-14"):
    """Put a peak block on the one PAST_DUE single-contract LEASE customer of the
    fixture book, for this test only (fresh_app_state re-seeds main.CUSTOMERS per
    test). Controller ruling, task-7: the brief's `next(c for c in
    journey.book_customers() if c.contracts and c.contracts[0].product == "LEASE")`
    finds a DEMO fixture (uid 018f3b91-...) that is not SHEET-sourced and has no
    `.sheet` attribute at all, so no PEAK invoice could ever be seeded through it.
    Selecting on the contract's own status (not on cases._payment_status) keeps the
    choice stable once a later task makes `_payment_status` PEAK-aware."""
    customer = next(c for c in journey.book_customers()
                    if c.data_source == SHEET and len(c.contracts) == 1
                    and c.contracts[0].product == "LEASE"
                    and cases.contract_field_of(c.contracts[0], "status") == "PAST_DUE")
    customer.sheet = dict(customer.sheet, peak={"report_as_of": report_as_of, "run_id": 1, "invoices": invoices})
    journey.reset()
    return customer, journey.for_current()


PAID = {"doc_no": "IVT-1", "doc_kind": "IVT", "issued_on": "2026-06-05", "due_on": "2026-06-12", "status": "PAID",
        "cycle": {"n": 3, "of": 48}, "product_group": "Solar Leasing", "amount_total": "8399.00", "amount_due": "8399.00",
        "amount_awaiting": "0.00", "payment": {"on": "2026-06-10", "channel": "Beam", "amount": "8399.00",
                                               "receipt_no": "RE-1"}, "contact_code": "VC1", "rule": "CUSTOMER_NO"}
LATE = dict(PAID, doc_no="IVT-2", due_on="2026-07-12", status="OVERDUE", cycle={"n": 4, "of": 48},
            amount_awaiting="8399.00", payment=None)
DRAFT = dict(PAID, doc_no="IVT-3", status="DRAFT", payment=None)


def _mine(state, customer):
    uids = {k.uid for k in customer.contracts}
    return ([i for i in state.invoices.values() if i["contract_uid"] in uids],
            [r for r in state.receipts.values() if r["contract_uid"] in uids])


def test_a_customer_with_peak_facts_gets_peak_invoices_and_no_sheet_invented_ones():
    customer, state = _with_peak([PAID, LATE, DRAFT])
    invoices, receipts = _mine(state, customer)
    assert {i["peak_number"] for i in invoices} == {"IVT-1", "IVT-2"}, "a DRAFT is not an issued invoice"
    assert all(i["source"] == "PEAK_REPORT" and i["scenario"] == "PEAK" for i in invoices)
    late = next(i for i in invoices if i["peak_number"] == "IVT-2")
    assert late["state"] == "OVERDUE" and late["outstanding"] == "8399.00" and late["month_index"] == 4
    assert late["peak_state"] == "APPROVED_IN_PEAK" and "PEAK" in late["peak_state_note_th"]
    assert len(receipts) == 1 and receipts[0]["ref"] == "RE-1" and receipts[0]["source"] == "PEAK_REPORT"
    assert receipts[0]["invoice_uid"] == next(i["uid"] for i in invoices if i["peak_number"] == "IVT-1")


def test_a_peak_receipt_is_allocated_by_ruling_f3_and_not_when_the_switch_is_off(monkeypatch):
    customer, state = _with_peak([PAID])
    assert _mine(state, customer)[1][0]["is_allocated"] is True
    monkeypatch.setattr(settings, "peak_report_allocates", False)
    customer, state = _with_peak([PAID])
    rcp = _mine(state, customer)[1][0]
    assert rcp["is_allocated"] is False and rcp["pending_decision"] == "OD-02"


def test_an_awaiting_invoice_past_its_due_date_reads_overdue_by_the_business_date():
    customer, state = _with_peak([dict(LATE, status="AWAITING", due_on="2020-01-01")])
    assert _mine(state, customer)[0][0]["state"] == "OVERDUE"


def test_reseed_replaces_peak_rows_and_keeps_everything_else():
    customer, state = _with_peak([PAID])
    before = len(state.invoices)
    customer.sheet = dict(customer.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": [PAID, LATE]})
    journey.reseed_peak(state, datetime.date(2026, 9, 21))
    invoices, _ = _mine(state, customer)
    assert {i["peak_number"] for i in invoices} == {"IVT-1", "IVT-2"}
    assert len(state.invoices) == before + 1


def test_a_slip_receipt_keeps_its_peak_invoice_across_a_reseed():
    # Fix round 1 / finding I1: a person's own receipt named a PEAK invoice's uid.
    # Reseeding the SAME PEAK content must not orphan it -- the invoice reseeds onto
    # the same stable id (`inv-pk-<doc_no>`), so the receipt's invoice_uid is still good.
    customer, state = _with_peak([PAID, LATE])
    invoices, _ = _mine(state, customer)
    late_uid = next(i["uid"] for i in invoices if i["peak_number"] == "IVT-2")
    contract = customer.contracts[0]
    slip = journey.make_receipt(state, contract.uid, contract.entity, "100.00",
                                datetime.date(2026, 9, 14), invoice_uid=late_uid)
    journey.reseed_peak(state, datetime.date(2026, 9, 14))
    assert slip["invoice_uid"] in state.invoices
    assert not slip.get("invoice_missing_after_reseed")


def test_a_receipt_whose_peak_invoice_vanished_is_marked_not_deleted():
    # Same slip receipt as above, but this reseed's PEAK content no longer carries
    # IVT-2 at all -- the invoice is genuinely gone. The receipt is kept, not deleted,
    # and flagged so a screen can surface it.
    customer, state = _with_peak([PAID, LATE])
    invoices, _ = _mine(state, customer)
    late_uid = next(i["uid"] for i in invoices if i["peak_number"] == "IVT-2")
    contract = customer.contracts[0]
    slip = journey.make_receipt(state, contract.uid, contract.entity, "100.00",
                                datetime.date(2026, 9, 14), invoice_uid=late_uid)
    customer.sheet = dict(customer.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": [PAID]})
    journey.reseed_peak(state, datetime.date(2026, 9, 21))
    assert slip["uid"] in state.receipts
    assert slip["invoice_missing_after_reseed"] is True


def test_reseed_seeds_peak_invoices_for_sheet_customers_only():
    # Final review (minor): reseed_peak carries _seed_migrated_invoices' own guard, so
    # a customer the sheet did not source is never given PEAK invoices at reseed
    # either — while the SHEET customer beside it reseeds exactly as before.
    customer, state = _with_peak([PAID])
    other = next(c for c in journey.book_customers() if c.data_source != SHEET and c.contracts)
    other.sheet = {"peak": {"report_as_of": "2026-09-14", "run_id": 1,
                            "invoices": [dict(PAID, doc_no="IVT-OTHER")]}}
    journey.reseed_peak(state, datetime.date(2026, 9, 14))
    assert _mine(state, other) == ([], [])
    invoices, receipts = _mine(state, customer)
    assert {i["peak_number"] for i in invoices} == {"IVT-1"} and len(receipts) == 1


def _other_lease_sheet_customer(exclude_uid):
    return next(c for c in journey.book_customers()
               if c.data_source == SHEET and c.contracts
               and c.contracts[0].product == "LEASE" and c.uid != exclude_uid)


def test_a_receipt_whose_invoice_moved_to_another_customer_is_flagged_not_counted():
    # Task 25c: a link confirmed by a Manager can move a PEAK invoice from customer A
    # to customer B at the next reseed_peak (same stable uid `inv-pk-<doc_no>`, a
    # different contract_uid). A's own receipt against that invoice_uid must never be
    # deleted or re-pointed -- it is flagged, and it must stop counting toward B's
    # invoice.
    customer_a, state = _with_peak([PAID])
    invoices, _ = _mine(state, customer_a)
    inv_uid = invoices[0]["uid"]
    contract_a = customer_a.contracts[0]
    slip = journey.make_receipt(state, contract_a.uid, contract_a.entity, "100.00",
                                datetime.date(2026, 9, 21), invoice_uid=inv_uid)
    customer_b = _other_lease_sheet_customer(customer_a.uid)
    customer_a.sheet = dict(customer_a.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": []})
    customer_b.sheet = dict(customer_b.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": [PAID]})
    journey.reseed_peak(state, datetime.date(2026, 9, 21))

    assert slip["uid"] in state.receipts, "a receipt is never deleted"
    assert not slip.get("invoice_missing_after_reseed"), "the uid still exists -- under a different customer"
    assert slip.get("invoice_moved_to_other_customer") is True
    moved_invoice = state.invoices[inv_uid]
    assert moved_invoice["contract_uid"] == customer_b.contracts[0].uid
    # B's own report brought its own legitimate receipt (PAID's payment field, now
    # seeded under B) -- A's slip must not be among what counts toward B's invoice.
    assert slip not in journey.invoice_receipts(state, moved_invoice), \
        "A's slip must not count toward B's invoice"


def test_moving_the_invoice_back_to_its_own_customer_clears_the_flag_and_it_counts_again():
    customer_a, state = _with_peak([PAID])
    invoices, _ = _mine(state, customer_a)
    inv_uid = invoices[0]["uid"]
    contract_a = customer_a.contracts[0]
    slip = journey.make_receipt(state, contract_a.uid, contract_a.entity, "100.00",
                                datetime.date(2026, 9, 21), invoice_uid=inv_uid)
    customer_b = _other_lease_sheet_customer(customer_a.uid)
    customer_a.sheet = dict(customer_a.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": []})
    customer_b.sheet = dict(customer_b.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": [PAID]})
    journey.reseed_peak(state, datetime.date(2026, 9, 21))
    assert slip.get("invoice_moved_to_other_customer") is True

    customer_a.sheet = dict(customer_a.sheet, peak={"report_as_of": "2026-09-28", "run_id": 3, "invoices": [PAID]})
    customer_b.sheet = dict(customer_b.sheet, peak={"report_as_of": "2026-09-28", "run_id": 3, "invoices": []})
    journey.reseed_peak(state, datetime.date(2026, 9, 28))

    assert slip.get("invoice_moved_to_other_customer") is False
    home_invoice = state.invoices[inv_uid]
    assert home_invoice["contract_uid"] == contract_a.uid
    assert slip in journey.invoice_receipts(state, home_invoice)


# ---------------------------------------------------------------------------------
# Task 25c fix round 1, finding 1: the REVIEW found record_receipt's own cumulative
# sum (routers/journey.py) untested -- the round-1 tests above call
# journey.invoice_receipts() directly, and both moved invoices there were already
# PAID, so putting the old invoice_uid-only filter back into record_receipt left
# the suite green. These go through the real HTTP endpoint instead.
# ---------------------------------------------------------------------------------

# An open (AWAITING) PEAK invoice, not the already-PAID one `_with_peak([PAID])`
# tests use -- record_receipt only runs its cumulative match on a matchable state.
LATE_OPEN = dict(LATE, doc_no="IVT-9", due_on="2026-09-30", status="AWAITING", amount_awaiting="8399.00")


def test_record_receipt_via_http_is_scoped_to_the_invoice_owning_customer(client):
    customer_a, state = _with_peak([LATE_OPEN])
    invoices, _ = _mine(state, customer_a)
    inv_uid = invoices[0]["uid"]
    contract_a = customer_a.contracts[0]
    slip = journey.make_receipt(state, contract_a.uid, contract_a.entity, "100.00",
                                datetime.date(2026, 9, 14), invoice_uid=inv_uid)
    customer_b = _other_lease_sheet_customer(customer_a.uid)
    customer_a.sheet = dict(customer_a.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": []})
    customer_b.sheet = dict(customer_b.sheet, peak={"report_as_of": "2026-09-21", "run_id": 2, "invoices": [LATE_OPEN]})
    journey.reseed_peak(state, datetime.date(2026, 9, 21))
    assert journey.for_current() is state             # the HTTP call below shares this state

    # 8,299 alone is PARTIAL against the 8,399 due; under the OLD invoice_uid-only
    # filter, A's stray 100 would count too (8,399 total) and this would read FULL.
    response = client.post("/v1/receipts", json={
        "contract_uid": customer_b.contracts[0].uid, "invoice_uid": inv_uid, "amount": "8299"})
    assert response.status_code == 201
    assert response.json()["receipt"]["matched"] == "PARTIAL"

    # Move the invoice back to A and reseed: A's own slip counts again.
    customer_a.sheet = dict(customer_a.sheet, peak={"report_as_of": "2026-09-28", "run_id": 3, "invoices": [LATE_OPEN]})
    customer_b.sheet = dict(customer_b.sheet, peak={"report_as_of": "2026-09-28", "run_id": 3, "invoices": []})
    journey.reseed_peak(state, datetime.date(2026, 9, 28))
    assert slip.get("invoice_moved_to_other_customer") is False

    # A's 100 (slip) + this 8,299 reaches the 8,399 due -- FULL only if the slip counts.
    response = client.post("/v1/receipts", json={
        "contract_uid": contract_a.uid, "invoice_uid": inv_uid, "amount": "8299"})
    assert response.status_code == 201
    assert response.json()["receipt"]["matched"] == "FULL"


# ---------------------------------------------------------------------------------
# Task 25c fix round 1, finding 2: record_receipt must refuse a receipt posted from
# a contract whose customer is not the invoice's own customer -- nothing is
# written.
# ---------------------------------------------------------------------------------

def test_record_receipt_refuses_a_receipt_against_another_customers_invoice(client):
    customer_a, state = _with_peak([LATE_OPEN])
    invoices, _ = _mine(state, customer_a)
    invoice = invoices[0]
    inv_uid = invoice["uid"]
    before_state = invoice["state"]
    before_receipt_count = len(state.receipts)
    customer_b = _other_lease_sheet_customer(customer_a.uid)
    assert journey.for_current() is state

    response = client.post("/v1/receipts", json={
        "contract_uid": customer_b.contracts[0].uid, "invoice_uid": inv_uid, "amount": "8399"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invoice_other_customer"
    assert body["errors"][0]["pointer"] == "/invoice_uid"
    assert body["errors"][0]["message"] == "This invoice belongs to another customer"
    # Fix round 2, finding (c): the invoice uid is guessable (inv-pk-<doc_no>) --
    # the detail must name the invoice and the POSTING contract only, never the
    # invoice's OWNING customer's id or customer number (that would map a PEAK
    # document number straight to a customer identity).
    assert customer_a.uid not in body["detail"]
    assert customer_a.customer_no not in body["detail"]
    assert body["message_th"] == "ใบแจ้งหนี้นี้เป็นของลูกค้ารายอื่น — เลือกใบแจ้งหนี้ของลูกค้ารายนี้"
    # Nothing was written.
    assert state.invoices[inv_uid]["state"] == before_state
    assert len(state.receipts) == before_receipt_count


# ---------------------------------------------------------------------------------
# Task 25c fix round 1, minor: `_customer_uid_for_contract` returning None on BOTH
# sides must never count as a match (`None == None`) -- a receipt or invoice whose
# contract no longer resolves must never count by accident. `invoice_owner_unknown`
# is re-evaluated every reseed in both directions, like the other flags.
# ---------------------------------------------------------------------------------

def test_a_receipt_or_invoice_whose_contract_no_longer_resolves_is_never_counted(monkeypatch):
    customer_a, state = _with_peak([PAID])
    invoices, _ = _mine(state, customer_a)
    inv_uid = invoices[0]["uid"]
    contract_a = customer_a.contracts[0]
    slip = journey.make_receipt(state, contract_a.uid, contract_a.entity, "100.00",
                                datetime.date(2026, 9, 21), invoice_uid=inv_uid)

    # Simulate every contract_uid failing to resolve to a customer (an orphaned
    # contract) -- under the old `== None` comparison this would make EVERY
    # receipt against this invoice_uid match, regardless of whose it really is.
    monkeypatch.setattr(journey, "_customer_uid_for_contract", lambda contract_uid: None)
    journey.reseed_peak(state, datetime.date(2026, 9, 21))

    assert slip.get("invoice_owner_unknown") is True
    assert slip.get("invoice_moved_to_other_customer") is False
    invoice = state.invoices[inv_uid]
    assert journey.invoice_receipts(state, invoice) == []


def test_invoice_owner_unknown_clears_once_the_contract_resolves_again():
    customer_a, state = _with_peak([PAID])
    invoices, _ = _mine(state, customer_a)
    inv_uid = invoices[0]["uid"]
    contract_a = customer_a.contracts[0]
    slip = journey.make_receipt(state, contract_a.uid, contract_a.entity, "100.00",
                                datetime.date(2026, 9, 21), invoice_uid=inv_uid)
    # An orphaned contract_uid on the RECEIPT alone: its own customer resolves to
    # None, the invoice's still resolves fine.
    real_customer_uid = journey._customer_uid_for_contract(contract_a.uid)
    slip["contract_uid"] = "no-such-contract"
    journey.reseed_peak(state, datetime.date(2026, 9, 21))
    assert slip.get("invoice_owner_unknown") is True
    assert slip.get("invoice_moved_to_other_customer") is False

    slip["contract_uid"] = contract_a.uid
    journey.reseed_peak(state, datetime.date(2026, 9, 21))
    assert slip.get("invoice_owner_unknown") is False
    assert journey._customer_uid_for_contract(slip["contract_uid"]) == real_customer_uid


# --- fix-all P1 (F1): receipt-run money is reseeded, never added again -----------------

def test_receipt_run_money_reseeds_onto_the_same_receipts_heal_after_heal():
    """A receipt the receipt run settled is minted PEAK_RECEIPT. The reseed cleared
    only PEAK_REPORT rows, so every heal minted it again as rcp-pk-<no>-2, -3, ..."""
    paid = {"on": "2026-09-16", "channel": "Beam", "amount": "8399.00", "receipt_no": "RE-P1-1"}
    settled = dict(LATE, status="PAID", amount_awaiting="0.00", payment_source="PEAK_RECEIPT",
                   payment=paid, payments=[paid])
    alone = {"on": "2026-09-17", "channel": "Beam", "amount": "500.00", "receipt_no": "RE-P1-2"}
    receipt_only = {"doc_no": "RE-P1-2", "doc_kind": "RE", "status": "PAID", "receipt_only": True,
                    "issued_on": "2026-09-17", "due_on": None, "cycle": None, "amount_total": "500.00",
                    "amount_due": "500.00", "amount_awaiting": "0.00", "payment": alone, "payments": [alone],
                    "contact_code": "VC1", "rule": "CUSTOMER_NO"}
    customer, state = _with_peak([settled, receipt_only])
    _, first = _mine(state, customer)
    assert sorted((r["source"], r["ref"]) for r in first) == [("PEAK_RECEIPT", "RE-P1-1"), ("PEAK_RECEIPT", "RE-P1-2")]
    for _ in range(2):
        journey.reseed_peak(state, datetime.date(2026, 9, 21))
    _, after = _mine(state, customer)
    assert sorted(r["uid"] for r in after) == sorted(r["uid"] for r in first) == ["rcp-pk-RE-P1-1", "rcp-pk-RE-P1-2"]
