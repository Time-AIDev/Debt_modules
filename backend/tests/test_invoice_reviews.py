"""Invoice review changes collection eligibility, never the source cash ledger."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from app import cases, journey, main, payment_summary
from app.fixtures import ContractFixture
from app.money.models import Instalment

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    monkeypatch.setenv("VOLT_INVOICE_REVIEWS_PATH", str(tmp_path / "reviews.sqlite3"))
    customer = main.CUSTOMERS[0]
    contract = ContractFixture("K-review", customer.uid, "LEASE", Decimal("300"), 3,
                               date(2026, 9, 23), status="ACTIVE").build()
    contract.instalments = [Instalment(due_date=date(2026, m, 23), category="REGULAR",
                                     principal_amount=Decimal("100"), interest_amount=Decimal("0"))
                            for m in (9, 10, 11)]
    contract.requires_schedule_confirmation = True
    contract.schedule_confirmation = None
    contract.sheet_row = {"first_payment_date": "2026-09-23"}
    customer.contracts = [contract]
    monkeypatch.setattr(main, "BY_CONTRACT", {contract.uid: (customer, contract)})
    state = journey.for_current()
    state.invoices.clear()
    state.receipts.clear()
    for n, month in enumerate((9, 10, 11), 1):
        state.invoices[f"iv-{n}"] = {"uid": f"iv-{n}", "contract_uid": contract.uid,
            "customer_uid": customer.uid, "source": "PEAK_REPORT", "kind": "INSTALMENT",
            "entity": "SPV", "peak_number": f"IV-{n}", "state": "ISSUED",
            "amount": "100.00", "outstanding": "100.00", "due_date": f"2026-{month:02d}-23",
            "issued_on": "2026-09-01", "month_index": n, "contract_resolved": True}
    cases.for_current().cases[customer.uid]["officer_uid"] = "nantapol"
    case_state = cases.for_current()
    monkeypatch.setattr(journey, "for_current", lambda: state)
    monkeypatch.setattr(cases, "for_current", lambda: case_state)
    from app import import_sync
    monkeypatch.setattr(import_sync, "ensure_current", lambda: None)
    return TestClient(main.app), customer, contract, state


def path(customer):
    return f"/v1/cases/by-customer/{customer.uid}/invoice-reviews"


def review(api, customer, ids, action="REJECT", key="review-one", reason="Wrong billing period"):
    body = {"invoice_uids": ids, "action": action, "reason": reason}
    preview = api.post(path(customer) + "/preview", json=body, headers=MANAGER)
    assert preview.status_code == 200, preview.text
    body.update(preview_version=preview.json()["version"], idempotency_key=key)
    return api.post(path(customer), json=body, headers=MANAGER), body, preview.json()


def test_auto_matching_does_not_require_contract_confirmation(scenario):
    _, _, contract, state = scenario
    cycles, unresolved, _ = payment_summary.peak_cycles_for(contract.uid, state)
    assert set(cycles) == {1, 2, 3}
    assert unresolved == 0


def test_case_hides_future_invoices_but_keeps_the_complete_calendar(scenario):
    api, customer, _, _ = scenario
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    assert [row["uid"] for row in data["invoices"]] == ["iv-1", "iv-2"]
    assert data["payment_summary"]["totals"]["due_outstanding_amount"] == "200.00"
    assert len(data["payment_summary"]["contracts"][0]["cycles"]) == 3
    assert data["work_item"]["payment_position"]["open_count"] == 2


def test_reject_removes_liability_without_changing_source_invoice(scenario):
    api, customer, _, state = scenario
    response, _, preview = review(api, customer, ["iv-1"])
    assert response.status_code == 200, response.text
    assert preview["before"]["due_outstanding_amount"] == "200.00"
    assert preview["after"]["due_outstanding_amount"] == "100.00"
    assert state.invoices["iv-1"]["outstanding"] == "100.00"
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    assert data["payment_summary"]["totals"]["due_outstanding_amount"] == "100.00"
    assert data["work_item"]["contract_outstanding"] == "300.00"
    assert data["payment_summary"]["totals"]["source_outstanding_amount"] == "300.00"
    assert data["work_item"]["payment_position"]["open_count"] == 1
    assert next(row for row in data["invoices"] if row["uid"] == "iv-1")["review_status"] == "REJECTED"


def test_accept_restores_a_rejected_invoice_without_creating_cash(scenario):
    api, customer, _, state = scenario
    assert review(api, customer, ["iv-1"])[0].status_code == 200
    response, _, _ = review(api, customer, ["iv-1"], "ACCEPT", "restore")
    assert response.status_code == 200
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    assert data["payment_summary"]["totals"]["due_outstanding_amount"] == "200.00"
    assert state.receipts == {}


def test_rejection_survives_reimport_with_a_new_runtime_uid(scenario):
    api, customer, _, state = scenario
    assert review(api, customer, ["iv-1"])[0].status_code == 200
    old = state.invoices.pop("iv-1")
    state.invoices["reimported"] = dict(old, uid="reimported")
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    assert next(row for row in data["invoices"] if row["uid"] == "reimported")["review_status"] == "REJECTED"


def test_bulk_preview_is_stale_if_money_changes(scenario):
    api, customer, _, state = scenario
    body = {"invoice_uids": ["iv-1", "iv-2"], "action": "REJECT", "reason": "Check sources"}
    preview = api.post(path(customer) + "/preview", json=body, headers=MANAGER)
    assert preview.status_code == 200
    state.invoices["iv-2"]["outstanding"] = "70.00"
    body.update(preview_version=preview.json()["version"], idempotency_key="stale")
    assert api.post(path(customer), json=body, headers=MANAGER).status_code == 409
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    assert all(row["review_status"] != "REJECTED" for row in data["invoices"])


def test_duplicate_confirmation_replays_without_another_history_record(scenario):
    api, customer, _, _ = scenario
    response, body, _ = review(api, customer, ["iv-1"])
    assert response.status_code == 200
    duplicate = api.post(path(customer), json=body, headers=MANAGER)
    assert duplicate.status_code == 200
    assert duplicate.json() == response.json()
    body["action"] = "ACCEPT"
    assert api.post(path(customer), json=body, headers=MANAGER).status_code == 409


@pytest.mark.parametrize("day,due,overdue", [(22, "100.00", False), (23, "200.00", False), (24, "200.00", True)])
def test_due_boundary_is_shared_with_customer_preview(scenario, monkeypatch, day, due, overdue):
    from app.config import settings
    api, customer, _, _ = scenario
    monkeypatch.setenv("VOLT_BUSINESS_DATE", f"2026-10-{day}")
    settings.business_date = date(2026, 10, day)
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    compact = api.get(f"/v1/customers/{customer.uid}/invoice-statuses?include_all=true").json()
    assert compact["summary"]["outstanding"] == due
    assert data["payment_summary"]["totals"]["due_outstanding_amount"] == due
    assert data["work_item"]["aggregate_outstanding"] == due
    if day >= 23:
        assert next(i for i in data["invoices"] if i["uid"] == "iv-2")["is_overdue"] is overdue


def test_accepted_source_change_requires_review_again(scenario):
    api, customer, _, state = scenario
    assert review(api, customer, ["iv-1"], "ACCEPT")[0].status_code == 200
    state.invoices["iv-1"]["amount"] = "110.00"
    row = next(i for i in api.get(f"/v1/cases/by-customer/{customer.uid}").json()["invoices"] if i["uid"] == "iv-1")
    assert row["review_status"] == "PENDING_REVIEW"


def test_many_invoices_in_one_cycle_deduplicate_documents_not_cycles(scenario):
    api, customer, _, state = scenario
    state.invoices["extra"] = dict(state.invoices["iv-1"], uid="extra", peak_number="EXTRA")
    state.invoices["duplicate"] = dict(state.invoices["iv-1"], uid="duplicate")
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    totals = data["payment_summary"]["totals"]
    assert totals["due_outstanding_amount"] == "300.00"
    assert totals["due_invoice_count"] == 3
    assert totals["due_cycle_count"] == 2


def test_same_document_number_in_another_company_is_a_distinct_invoice(scenario):
    api, customer, _, state = scenario
    state.invoices["other-company"] = dict(state.invoices["iv-1"], uid="other-company", company_id="COMPANY-B")
    assert review(api, customer, ["iv-1"])[0].status_code == 200
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    assert next(i for i in data["invoices"] if i["uid"] == "other-company")["review_status"] == "AUTO_MATCHED"
    assert data["payment_summary"]["totals"]["due_outstanding_amount"] == "200.00"


def test_bulk_failure_after_preview_rolls_back_every_decision(scenario):
    from app import invoice_review_store
    api, customer, _, state = scenario
    body = {"invoice_uids": ["iv-1", "iv-2"], "action": "REJECT", "reason": "Check"}
    preview = api.post(path(customer) + "/preview", json=body, headers=MANAGER).json()
    body.update(preview_version=preview["version"], idempotency_key="atomic-invalid")
    state.invoices["iv-2"]["customer_uid"] = "foreign"
    assert api.post(path(customer), json=body, headers=MANAGER).status_code == 403
    assert invoice_review_store.read() == []


def test_review_is_readable_in_a_fresh_process(scenario):
    import os
    import subprocess
    import sys
    api, customer, _, _ = scenario
    assert review(api, customer, ["iv-1"])[0].status_code == 200
    result = subprocess.run([sys.executable, "-c", "from app.invoice_review_store import read; print(read()[0]['decisions'][0]['action'])"],
                            capture_output=True, text=True, check=True, env=dict(os.environ, DATABASE_URL=""))
    assert result.stdout.strip() == "REJECT"


def test_reject_keeps_existing_cash_evidence(scenario):
    import copy
    api, customer, contract, state = scenario
    state.receipts['cash'] = {'uid': 'cash', 'contract_uid': contract.uid, 'invoice_uid': 'iv-1',
        'customer_uid': customer.uid, 'amount': '30.00', 'source': 'SLIP', 'ref': 'REAL-CASH',
        'received_on': '2026-10-01', 'is_allocated': True, 'matched': 'PARTIAL'}
    before = copy.deepcopy(state.receipts)
    response, _, preview = review(api, customer, ['iv-1'])
    assert response.status_code == 200
    assert preview['before']['due_outstanding_amount'] == '170.00'
    assert preview['after']['due_outstanding_amount'] == '100.00'
    assert state.receipts == before


def test_reject_is_durable_in_postgres_and_append_only(scenario, pg_conn, monkeypatch):
    from app import db, migrate, invoice_review_store
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn.engine.connect())
    api, customer, _, state = scenario
    # Delete only this test customer's prior events through TRUNCATE in the isolated test database.
    pg_conn.execute(text("truncate records.invoice_review restart identity")); pg_conn.commit()
    assert review(api, customer, ["iv-1"])[0].status_code == 200
    old = state.invoices.pop("iv-1")
    state.invoices["new-id"] = dict(old, uid="new-id")
    invoice_review_store.invalidate()
    data = api.get(f"/v1/cases/by-customer/{customer.uid}").json()
    assert next(i for i in data["invoices"] if i["uid"] == "new-id")["review_status"] == "REJECTED"
    assert len(invoice_review_store.read()) == 1
    with pytest.raises(DBAPIError):
        pg_conn.execute(text("delete from records.invoice_review"))
    pg_conn.rollback()
    pg_conn.execute(text("truncate records.invoice_review restart identity")); pg_conn.commit()


@pytest.mark.parametrize("ids,action,reason,status", [
    (["iv-3"], "ACCEPT", "", 409),
    (["iv-1"], "REJECT", "", 422),
    (["missing", "iv-1"], "REJECT", "Check", 404),
    (["iv-1"], "DELETE", "Check", 422),
    ([], "ACCEPT", "", 422),
])
def test_invalid_bulk_cannot_change_any_invoice(scenario, ids, action, reason, status):
    api, customer, _, _ = scenario
    response = api.post(path(customer) + "/preview", json={
        "invoice_uids": ids, "action": action, "reason": reason}, headers=MANAGER)
    assert response.status_code == status


def test_invoice_from_another_customer_is_refused(scenario):
    api, customer, _, state = scenario
    state.invoices["foreign"] = dict(state.invoices["iv-1"], uid="foreign", contract_uid="K-other", customer_uid="other")
    assert api.post(path(customer) + "/preview", json={"invoice_uids": ["iv-1", "foreign"],
        "action": "REJECT", "reason": "Check"}, headers=MANAGER).status_code == 403


@pytest.mark.parametrize("role,officer,status", [("OFFICER", "nantapol", 200),
    ("OFFICER", "thip", 403), ("SUPERVISOR", "settasak", 200),
    ("MANAGER", "settasak", 200), ("OWNER", "owner", 200), ("OPS", "ops", 403)])
def test_review_roles_and_assignment(scenario, role, officer, status):
    api, customer, _, _ = scenario
    response = api.post(path(customer) + "/preview", json={"invoice_uids": ["iv-1"], "action": "ACCEPT"},
        headers={"X-Volt-Role": role, "X-Volt-Officer": officer})
    assert response.status_code == status


def test_reject_cash_updates_arrears_without_changing_whole_contract_balance(scenario):
    api, customer, contract, _ = scenario
    contract.product = 'CASH'
    contract.requires_schedule_confirmation = False
    response, _, _ = review(api, customer, ['iv-1'])
    assert response.status_code == 200
    data = api.get(f'/v1/cases/by-customer/{customer.uid}').json()
    assert Decimal(data['work_item']['aggregate_overdue']) == 0
    assert Decimal(data['work_item']['money_position']['amount_to_ask']) == 0
    assert Decimal(data['payment_summary']['totals']['overdue_amount']) == 0
    assert Decimal(data['work_item']['contract_outstanding']) == 300
    assert data['work_item']['payment_position']['due_outstanding_amount'] == '100.00'


def test_reimported_preview_ids_return_a_stale_conflict(scenario):
    api, customer, _, state = scenario
    body = {'invoice_uids':['iv-1'], 'action':'REJECT', 'reason':'Source correction'}
    preview = api.post(path(customer)+'/preview',json=body,headers=MANAGER).json()
    state.invoices['new-runtime-id'] = dict(state.invoices.pop('iv-1'),uid='new-runtime-id')
    body.update(preview_version=preview['version'],idempotency_key='removed-preview')
    result = api.post(path(customer),json=body,headers=MANAGER)
    assert result.status_code == 409
    from app.invoice_review_store import read
    assert read() == []


def test_invalid_duplicate_does_not_hide_the_active_source_document(scenario):
    from app import invoice_reviews
    _, customer, _, state = scenario
    first = dict(state.invoices['iv-1'],uid='void-copy',state='VOID')
    state.invoices = {'void-copy':first, **state.invoices}
    rows = invoice_reviews.project(customer,state)
    assert next(i for i in rows if i['uid']=='iv-1')['collection_included'] is True
    assert invoice_reviews.totals(rows)['due_outstanding_amount'] == '200.00'
