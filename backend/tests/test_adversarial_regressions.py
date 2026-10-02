"""Regressions from the 2026-08-31 adversarial review (15 confirmed findings).

Each test pins one finding closed. The finding titles are quoted from the review;
the fixes live in routers/journey.py, journey.py and fixtures.py.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def _case_of(client, customer_no):
    from app import main
    for case in client.get("/v1/cases").json()["cases"]:
        if main.BY_CUSTOMER[case["customer_uid"]].customer_no == customer_no:
            return case
    raise AssertionError("no case for %s" % customer_no)


# --- the ladder only advances ------------------------------------------------------

def test_a_backwards_move_is_refused_for_everyone(client):
    """'Assignment deed + 100%-NPV buyback executes TWICE via a backwards move.'"""
    case = _case_of(client, "C-002034")   # ASSIGNED_120, deed executed
    response = client.post("/v1/cases/%s:advance" % case["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OWNER",
                                 "note": "unwind"})
    assert response.status_code == 422
    assert response.json()["code"] == "ladder_move_not_forward"
    # And the buyback was NOT paid twice.
    docs = client.get("/v1/intercompany/docs").json()["documents"]
    buybacks = [d for d in docs if d["doc_type"] == "NPL_BUYBACK_PAYMENT"
                and d["contract_uid"] == "K-2034-1"]
    assert len(buybacks) == 1


def test_a_same_stage_move_is_refused(client):
    """'NPL can be declared twice on one case (same-stage advance).'"""
    case = _case_of(client, "C-002033")   # NPL_DECLARED_90
    response = client.post("/v1/cases/%s:advance" % case["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OWNER",
                                 "note": "again"})
    assert response.status_code == 422
    assert response.json()["code"] == "ladder_move_not_forward"
    npl_cases = client.get("/v1/npl-cases").json()["npl_cases"]
    assert sum(1 for n in npl_cases if n["contract_uid"] == "K-2033-1") == 1


# --- the cash restriction is enforced, not advertised ------------------------------

def test_confirm_npl_on_a_cash_review_is_refused_at_decide_time(client):
    """'decide_review ignores the cash-account restriction.'"""
    reviews = client.get("/v1/manager-review").json()["reviews"]
    cash_review = next(r for r in reviews
                       if r["customer"]["customer_no"] == "C-001120"
                       and r["status"] == "OPEN")
    assert "CONFIRM_NPL" not in cash_review["available_decisions"]
    response = client.post("/v1/manager-review/%s:decide" % cash_review["uid"],
                           json={"decision": "CONFIRM_NPL", "role": "OWNER"})
    assert response.status_code == 422
    assert response.json()["code"] == "decision_unknown"
    # The CASH contract never entered the lease ladder.
    from app import main
    assert main.BY_CONTRACT["K-1120-1"][1].status != "NON_PERFORMING"


# --- restructure: no double application, no interest on interest -------------------

def test_two_sessions_cannot_both_apply_a_restructure(client):
    """'Session isolation is defeated ... instalment count goes 96 -> 240.'

    Ruling 49 (round 4, the fourteenth authorised test edit): the schedule DATA
    (`contract.instalments` / `line.schedule_status`) is isolated onto cases.py's
    per-session overlay now (`contract_field_of` / `_set_contract_fields`), the
    same mechanism fee_state and status already used — so the raw shared
    `Contract.instalments` attribute is never written by a request again. The
    property this test guards is unchanged: two sessions must not both apply a
    restructure to the same contract. What changed is only how it is proved —
    through the per-session accessor, the way test_round2.py's test_n2_07 already
    does under ruling 46a — and the refusal is now asserted as the explicit,
    deliberately process-wide `journey.restructure_lock` (ruling 47), not read as
    a side effect of a shared list happening to grow.
    """
    from app import cases as cases_domain
    from app import journey
    from app import main
    contract = main.BY_CONTRACT["K-2032-1"][1]
    before = len(contract.instalments)
    a, b = TestClient(app), TestClient(app)
    # A is pinned to the "shared" session — the slot a direct, non-request Python
    # read resolves to by session.CURRENT's documented default — so the accessor
    # read below and A's own write land in the same overlay slot, exactly the way
    # test_round2.py's `client` fixture already relies on for the same reason.
    a.cookies.set("volt_session", "shared")
    rst_a = next(c for c in a.get("/v1/cases").json()["cases"]
                 if c["contract_uid"] == "K-2032-1")["restructure_uid"]
    assert a.post("/v1/restructures/%s:approve" % rst_a,
                  json={"role": "OWNER"}).status_code == 200
    rst_b = next(c for c in b.get("/v1/cases").json()["cases"]
                 if c["contract_uid"] == "K-2032-1")["restructure_uid"]
    second = b.post("/v1/restructures/%s:approve" % rst_b, json={"role": "OWNER"})
    assert second.status_code == 422
    assert second.json()["code"] == "second_restructure_forbidden"
    # The refusal is the explicit lock, not an accident of storage shape.
    lock = journey.restructure_lock("K-2032-1")
    assert lock is not None and lock["restructure_uid"] == rst_a
    # A still sees its own restructure through the per-session accessor — one
    # addendum, not two, and not lost by the isolation that keeps B from seeing
    # it: 96 -> 168, exactly +72.
    assert len(cases_domain.contract_field_of(contract, "instalments")) == before + 72
    # The shared fixture object itself — read raw, the way this test always has —
    # is UNTOUCHED: it is never written by a request any more, so B's refused
    # attempt cannot corrupt it and neither can A's successful one. This is what
    # makes the historical "96 -> 240" corruption structurally impossible now,
    # not merely refused: there is no shared list left for a second session to
    # double-append to.
    assert len(contract.instalments) == before


def test_the_addendum_never_capitalises_future_interest(client):
    """'approve_restructure capitalises unpaid FLAT interest ... interest on interest.'"""
    from app import main
    contract = main.BY_CONTRACT["K-2032-1"][1]
    rst = next(c for c in client.get("/v1/cases").json()["cases"]
               if c["contract_uid"] == "K-2032-1")["restructure_uid"]
    client.post("/v1/restructures/%s:approve" % rst, json={"role": "OWNER"})
    new_lines = [l for l in contract.instalments if l.is_active_regular]
    new_principal = sum((l.principal_amount for l in new_lines), Decimal("0.00"))
    # 240,000 principal outstanding + the 3 EARNED (due, unpaid) interest lines —
    # never the 151,680 of future flat interest.
    assert new_principal < Decimal("250000")
    assert new_principal >= Decimal("240000")


def test_the_seeded_restructure_carries_the_engines_own_balance(client):
    """'Seeded restructured contract K-2035-1 silently forgives ~119,580 THB.'"""
    from app import main
    contract = main.BY_CONTRACT["K-2035-1"][1]
    superseded = sum((l.outstanding_principal for l in contract.instalments
                      if l.schedule_status == "SUPERSEDED"), Decimal("0.00"))
    addendum = sum((l.principal_amount for l in contract.instalments
                    if l.is_active_regular), Decimal("0.00"))
    # The addendum principal carries the outstanding principal (plus earned
    # interest) — nothing is silently forgiven.
    assert addendum >= superseded


# --- the NPV is effective-annual and time-to-cash ----------------------------------

def test_remaining_npv_discounts_effective_annual_and_face_values_overdue():
    """Two findings: 'EA rate as nominal/12' and 'exponent is the ordinal'."""
    from app.fixtures import ContractFixture
    from app.journey import remaining_npv
    # A contract whose every line is already overdue: NPV must equal FACE.
    overdue = ContractFixture("T-NPV-1", "c", "LEASE", Decimal("120000"), 12,
                              date(2025, 1, 1)).build()
    face = sum((l.outstanding_amount for l in overdue.instalments), Decimal("0.00"))
    assert remaining_npv(overdue, as_of=date(2026, 10, 23)) == face.quantize(Decimal("0.01"))
    # A single line 12 months out: discounted by exactly (1.15), not (1+0.15/12)^12.
    future = ContractFixture("T-NPV-2", "c", "LEASE", Decimal("120000"), 1,
                             date(2027, 10, 23)).build()
    line = future.instalments[0].outstanding_amount
    npv = remaining_npv(future, as_of=date(2026, 10, 23))
    expected = (line / Decimal("1.15")).quantize(Decimal("0.01"))
    assert abs(npv - expected) <= Decimal("0.02")


# --- receipts: cumulative, state-guarded, invoice-entity ---------------------------

def test_two_partials_cumulate_to_paid_and_overpayment_is_said(client):
    """'Receipt matching compares each receipt to the FACE amount.'"""
    invoices = client.get("/v1/contracts/K-2011-1/invoices").json()["invoices"]
    balance = next(i for i in invoices if i["kind"] == "HANDOVER_BALANCE")
    first = client.post("/v1/receipts", json={
        "contract_uid": "K-2011-1", "invoice_uid": balance["uid"], "amount": "100000"})
    assert first.json()["receipt"]["matched"] == "PARTIAL"
    second = client.post("/v1/receipts", json={
        "contract_uid": "K-2011-1", "invoice_uid": balance["uid"], "amount": "40000"})
    body = second.json()["receipt"]
    assert body["matched"] == "FULL"                      # 140,000 >= 135,000
    assert body["overpayment_unallocated"] == "5000.00"   # and the excess is SAID
    after = client.get("/v1/contracts/K-2011-1/invoices").json()["invoices"]
    assert next(i for i in after if i["uid"] == balance["uid"])["state"] == "PAID"


def test_a_receipt_against_a_paid_invoice_is_refused(client):
    """'record_receipt has no invoice-state guard.'"""
    invoices = client.get("/v1/contracts/K-2001-1/invoices").json()["invoices"]
    paid = next(i for i in invoices if i["state"] == "PAID")
    response = client.post("/v1/receipts", json={
        "contract_uid": "K-2001-1", "invoice_uid": paid["uid"], "amount": "100"})
    assert response.status_code == 409
    assert response.json()["code"] == "invoice_state_conflict"


def test_a_service_receipt_books_where_the_invoice_books(client):
    """'Receipt legal entity is stamped from the CONTRACT, not the invoice.'"""
    invoices = client.get("/v1/contracts/K-2036-1/invoices").json()["invoices"]
    service = next(i for i in invoices
                   if i["kind"] == "SERVICE_MONTHLY" and i["state"] == "OVERDUE")
    receipt = client.post("/v1/receipts", json={
        "contract_uid": "K-2036-1", "invoice_uid": service["uid"],
        "amount": "399.00"}).json()["receipt"]
    # The lease is SPV's; the service money is EPC's — the invoice decides.
    assert receipt["entity"] == "EPC"
    assert receipt["company_id"] == "CO-EPC"


# --- money-input gates -------------------------------------------------------------

def test_infinity_and_nan_amounts_are_refused_not_recorded(client):
    """'Amount guards accept Decimal Infinity and crash (500) on NaN.'"""
    for bad in ("Infinity", "-Infinity", "NaN"):
        response = client.post("/v1/receipts", json={
            "contract_uid": "K-2011-1", "amount": bad})
        assert response.status_code == 422, bad
        assert response.json()["code"] == "validation_failed", bad


def test_a_zero_or_negative_dan_price_is_refused(client):
    """'price_lot accepts zero/negative resale_price ... NEGATIVE recovery.'"""
    lots = client.get("/v1/repossession-lots").json()["lots"]
    lot = next(l for l in lots if l["status"] == "GRADED")
    for bad in ("0", "-50000"):
        response = client.post("/v1/repossession-lots/%s:price" % lot["uid"],
                               json={"by": "Dan", "resale_price": bad})
        assert response.status_code == 422, bad


# --- fixture honesty extensions ----------------------------------------------------

def test_multi_line_cash_contracts_are_flagged_legacy():
    """'Two seeded CASH contracts violate the one-format rule' — they predate it
    and now SAY so; an unflagged one is a defect."""
    from app.fixtures import seed
    for customer in seed():
        for contract in customer.contracts:
            if contract.product == "CASH" and len(contract.instalments) > 2:
                assert contract.legacy_pre_v20, contract.uid


def test_the_bulk_service_invoice_reconciles_to_the_billing_book(client):
    """'Seeded SERVICE_BULK_INVOICE amount 798.00 reconciles to nothing.'"""
    docs = client.get("/v1/intercompany/docs").json()["documents"]
    bulk = next(d for d in docs if d["doc_type"] == "SERVICE_BULK_INVOICE")
    accounts = client.get("/v1/service-billing").json()["accounts"]
    billing = [a for a in accounts if a["status"] == "BILLING"]
    expected = sum((Decimal(a["monthly_amount"]) for a in billing), Decimal("0.00"))
    assert Decimal(bulk["amount"]) == expected
