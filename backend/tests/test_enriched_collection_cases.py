"""A Won identity enriched by an approved contract must become an operable case."""
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

from app import book, cases, errors, main
from app.fixtures import CustomerFixture
from app.routers.today import case_detail


def enriched():
    uid = "sheet-SYNTHETIC-ENRICHED"
    record = {"pmt_inc_vat": "1000", "term_original": 12, "first_payment_date": "2026-01-10",
              "financial_evidence_only": True, "months": []}
    contract, reason = book._lease_contract("K-SYNTHETIC-ENRICHED-L", uid, record, date(2026, 10, 23))
    assert contract is not None and reason is None
    customer = CustomerFixture(uid, "SYNTHETIC-ENRICHED", "Synthetic Enriched Customer", "TEST-REDACTED",
                               0, "SYNTHETIC", "nantapol", "CONTACT", contracts=[contract])
    customer.product = "LEASE"
    customer.sheet = {"leasing": record, "contract_supplement": {"product": "LEASE"}}
    return customer


def test_enrichment_seeds_only_missing_cases_and_keeps_person_work(monkeypatch):
    state = cases.for_current()
    before_cases = deepcopy(state.cases)
    before_children = {name: deepcopy(getattr(state, name)) for name in ("ptps", "reviews", "issues", "power")}
    customer = enriched()
    identity = deepcopy(customer)
    identity.uid, identity.contracts = "sheet-SYNTHETIC-IDENTITY", []
    monkeypatch.setattr(main, "CUSTOMERS", [*main.CUSTOMERS, customer, identity])
    monkeypatch.setattr(main, "BY_CUSTOMER", {**main.BY_CUSTOMER, customer.uid: customer, identity.uid: identity})
    assert cases.open_collection_cases(state) == 1
    assert identity.uid not in state.cases
    assert all(state.cases[uid] == value for uid, value in before_cases.items())
    for name, values in before_children.items():
        assert all(getattr(state, name)[key] == value for key, value in values.items())
    created = state.cases[customer.uid]
    assert created["next_action"] is not None
    assert created["payment_status"] != "NPL"
    first = deepcopy(vars(state))
    assert cases.open_collection_cases(state) == 0
    assert vars(state) == first


def test_real_contract_cannot_be_reported_as_an_identity_without_a_money_row(monkeypatch):
    state = cases.for_current()
    customer = enriched()
    monkeypatch.setattr(main, "CUSTOMERS", [*main.CUSTOMERS, customer])
    monkeypatch.setattr(main, "BY_CUSTOMER", {**main.BY_CUSTOMER, customer.uid: customer})
    monkeypatch.setattr(main, "BY_CONTRACT", {**main.BY_CONTRACT, customer.contracts[0].uid: (customer, customer.contracts[0])})
    with pytest.raises(errors.Problem) as pending:
        case_detail(customer.uid)
    assert pending.value.code == "collection_case_not_ready" and pending.value.status == 503
    cases.open_collection_cases(state)
    payload = case_detail(customer.uid)
    assert payload.get("identity_only") is not True
    assert [contract["uid"] for contract in payload["contracts"]] == [customer.contracts[0].uid]
    assert payload["case"]["customer_uid"] == customer.uid
    assert Decimal(payload["contracts"][0]["principal"]) > 0
    assert payload["contracts"][0]["paid_through"] == 0
    assert payload["case"]["npl_assessment"]["actual_dpd"] >= 90
    assert payload["case"]["payment_status"] != "NPL"


def test_reviewed_supplement_keeps_its_contract_when_peak_display_product_conflicts(monkeypatch):
    record = {"customer_no": "SYNTHETIC-ENRICHED", "volt_id": "SYNTHETIC-ENRICHED-ID", "product": "CASH",
              "name_roman": "Synthetic Enriched Customer", "cash": None,
              "leasing": {"pmt_inc_vat": "1000", "term_original": 12, "first_payment_date": "2026-01-10",
                          "financial_evidence_only": True, "months": []},
              "contract_supplement": {"product": "LEASE"}, "field_sources": {"product": "PEAK"}}
    monkeypatch.setattr(book, "load_sheet", lambda: {"customers": [record], "source": {"blocks": {}}})
    book.invalidate()
    customers, _ = book.build(date(2026, 10, 23))
    assert len(customers) == 1
    customer = customers[0]
    assert customer.product == "LEASE" and customer.contracts[0].entity == "SPV"
    assert customer.sheet["product"] == "CASH" and customer.field_sources["product"] == "PEAK"
    assert customer.contract_product_review == {"source_product": "CASH", "contract_product": "LEASE",
                                                "review_required": True, "reason": "SOURCE_PRODUCT_CONFLICT"}
    monkeypatch.setattr(main, "CUSTOMERS", customers)
    monkeypatch.setattr(main, "BY_CUSTOMER", {customer.uid: customer})
    state = cases.CaseState()
    cases.open_collection_cases(state)
    assert state.cases[customer.uid]["review_uid"] is not None
    assert state.reviews[state.cases[customer.uid]["review_uid"]]["reason"] == "OTHER"
