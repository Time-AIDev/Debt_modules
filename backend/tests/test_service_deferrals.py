"""Service faults move due dates, never cash or invoice accounting facts."""
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib

import pytest
from fastapi.testclient import TestClient

from app import cases, journey, main, payment_summary
from app.fixtures import ContractFixture
from app.money.models import Instalment


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    monkeypatch.setenv("VOLT_SERVICE_DEFERRALS_PATH", str(tmp_path / "deferrals.sqlite3"))
    customer = main.CUSTOMERS[0]
    lines = [Instalment(date(2026, m, 1), "REGULAR", Decimal("100"), Decimal("0"))
             for m in (8, 9, 10, 11)]
    # The migrated sheet would wrongly infer that the FIRST cycle was paid.
    lines[0].paid_principal = Decimal("100")
    contract = ContractFixture("K-SERVICE", customer.uid, "LEASE", Decimal("400"), 4,
                               date(2026, 8, 1), instalments=lines)
    customer = replace(customer, contracts=[contract])
    main.CUSTOMERS[0] = customer
    main.BY_CUSTOMER[customer.uid] = customer
    main.BY_CONTRACT[contract.uid] = (customer, contract)
    state = journey.for_current()
    state.invoices = {"fault-%s" % n: {
        "uid": "fault-%s" % n, "contract_uid": contract.uid, "month_index": n,
        "amount": "100.00", "outstanding": "0.00" if n == 3 else "100.00",
        "state": "PAID" if n == 3 else "OVERDUE", "peak_number": "IV-%s" % n,
        "source": "PEAK_REPORT", "due_date": str(lines[n - 1].due_date),
        "issued_on": str(lines[n - 1].due_date), "kind": "INSTALMENT",
    } for n in (1, 2, 3)}
    state.receipts = {}
    body = {"cycles": [1, 2], "reason": "ติดตั้งไม่สมบูรณ์",
            "service_from": "2026-08-01", "service_until": "2026-09-30",
            "confirmation_note": "ทีมติดตั้งยืนยันว่าใช้งานไม่ได้", "confirmed_by": "Installation"}
    client = TestClient(main.app)
    client.cookies.set("volt_session", "shared")
    return client, contract, state, body


def preview(client, contract, body):
    return client.post(f"/v1/contracts/{contract.uid}/service-deferrals/preview", json=body)


def create(scenario):
    client, contract, state, body = scenario
    response = preview(client, contract, body)
    assert response.status_code == 200, response.text
    return client.post(f"/v1/contracts/{contract.uid}/service-deferrals", json={
        **body, "preview_version": response.json()["version"], "idempotency_key": "first"})


def test_move_first_two_cycles_preserves_cash_and_contract_total(scenario):
    client, contract, state, body = scenario
    before = preview(client, contract, body)
    assert before.status_code == 200, before.text
    proposed = before.json()
    assert [(r["n"], r["new_due_date"]) for r in proposed["moves"]] == [
        (1, "2026-12-01"), (2, "2027-01-01")]
    assert proposed["collection_overdue_after"] == "0.00"
    response = create(scenario)
    assert response.status_code == 200, response.text
    assert response.json()["deferral"]["accounting"]["status"] == "PENDING_REVIEW"
    _, dpd, _, block, _ = main._contract_view(contract)
    assert block.cumulative_arrears == Decimal("0")
    assert block.closing_balance == Decimal("300")
    assert block.penalty_accrued_unbilled == Decimal("0")
    assert dpd in (None, 0)
    hits, _, _ = payment_summary.peak_cycles_for(contract.uid, state)
    summary = payment_summary.for_contract(contract, date(2026, 10, 23), block.cumulative_arrears,
                                           peak_cycles=hits)
    assert summary["paid_count"] == 1
    assert summary["deferred_count"] == 2
    assert summary["contract_amount"] == "400.00"
    assert summary["paid_amount"] == "100.00"
    assert [c["n"] for c in summary["cycles"]] == [1, 2, 3, 4]
    assert summary["cycles"][0]["status"] == "UPCOMING"
    assert summary["cycles"][2]["status"] == "PAID"
    assert state.invoices["fault-1"]["state"] == "OVERDUE"
    assert not state.receipts
    assert contract.instalments[0].due_date == date(2026, 8, 1)


def test_a_later_unpaid_cycle_still_has_dpd_and_penalty(scenario):
    assert create(scenario).status_code == 200
    _, contract, _, _ = scenario
    _, dpd, _, block, _ = main._contract_view(contract, date(2026, 12, 1))
    assert dpd == 30
    assert block.cumulative_arrears == Decimal("100")
    assert block.penalty_accrued_unbilled > 0


@pytest.mark.parametrize("change", ["paid", "partial", "receipt", "pending"])
def test_paid_or_part_paid_or_pending_cycles_cannot_be_moved(scenario, change):
    client, contract, state, body = scenario
    if change in ("paid", "partial"):
        state.invoices["fault-1"]["outstanding"] = "0.00" if change == "paid" else "50.00"
    elif change == "receipt":
        state.receipts["rcp"] = {"uid": "rcp", "invoice_uid": "fault-1", "amount": "10",
                                  "contract_uid": contract.uid, "received_on": "2026-10-01"}
    else:
        state.invoices["fault-1"]["pending_amount"] = "10.00"
    response = preview(client, contract, body)
    assert response.status_code == 409
    assert response.json()["code"] == "service_deferral_payment_conflict"


def test_preview_is_stale_after_payment_or_another_deferral(scenario):
    client, contract, state, body = scenario
    old = preview(client, contract, body)
    assert old.status_code == 200
    assert create(scenario).status_code == 200
    response = client.post(f"/v1/contracts/{contract.uid}/service-deferrals", json={
        **body, "preview_version": old.json()["version"], "idempotency_key": "second"})
    assert response.status_code == 409


def test_reversal_previews_current_money_and_restores_original_dates(scenario):
    client, contract, state, body = scenario
    result = create(scenario)
    assert result.status_code == 200
    uid = result.json()["deferral"]["uid"]
    path = f"/v1/contracts/{contract.uid}/service-deferrals/{uid}"
    data = {"reason": "ยืนยันวันที่เดิมใหม่"}
    p = client.post(path + "/reverse-preview", json=data)
    assert p.status_code == 200
    assert p.json()["collection_overdue_after"] == "200.00"
    r = client.post(path + "/reverse", json={**data, "preview_version": p.json()["version"]})
    assert r.status_code == 200
    assert r.json()["deferral"]["status"] == "REVERSED"
    assert main._contract_view(contract)[3].cumulative_arrears == Decimal("200")
    assert main._contract_view(contract)[3].closing_balance == Decimal("300")


def test_reversal_is_blocked_after_a_moved_cycle_receives_money(scenario):
    client, contract, state, body = scenario
    result = create(scenario)
    assert result.status_code == 200
    uid = result.json()["deferral"]["uid"]
    state.invoices["fault-2"]["outstanding"] = "50.00"
    response = client.post(f"/v1/contracts/{contract.uid}/service-deferrals/{uid}/reverse-preview",
                           json={"reason": "ย้อน"})
    assert response.status_code == 409


def test_deferral_survives_a_new_session_and_module_reload(scenario):
    import importlib
    from app import service_deferrals, session
    _, contract, state, _ = scenario
    assert create(scenario).status_code == 200
    importlib.reload(service_deferrals)
    token = session.CURRENT.set("another-officer")
    try:
        journey.for_current().invoices = dict(state.invoices)
        assert main._contract_view(contract)[3].cumulative_arrears == Decimal("0")
        assert service_deferrals.list_for_contract(contract.uid)[0]["status"] == "ACTIVE"
    finally:
        session.CURRENT.reset(token)


def test_unknown_role_cannot_confirm_and_note_evidence_is_required(scenario):
    client, contract, state, body = scenario
    assert preview(client, contract, {**body, "confirmation_note": ""}).status_code == 422
    r = client.post(f"/v1/contracts/{contract.uid}/service-deferrals/preview", json=body,
                    headers={"X-Volt-Role": "OPS"})
    assert r.status_code == 403


def test_case_detail_shows_peak_arrears_separately_and_current_collection_status(scenario):
    client, contract, state, body = scenario
    assert create(scenario).status_code == 200
    response = client.get(f"/v1/cases/by-customer/{contract.customer_uid}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["case"]["payment_status_system"] == "CURRENT"
    assert data["service_deferrals"][0]["status"] == "ACTIVE"
    pp = data["work_item"]["payment_position"]
    assert pp["peak_outstanding"] == "200.00"
    assert pp["collection_overdue"] == "0.00"
    assert pp["deferred_amount"] == "200.00"
    assert data["invoices"][0]["service_deferral"]["n"] in (1, 2)


def test_unreferenced_payment_uses_effective_due_dates(scenario):
    from app import payment_claims
    client, contract, state, body = scenario
    assert create(scenario).status_code == 200
    state.invoices["fault-4"] = dict(state.invoices["fault-2"], uid="fault-4", peak_number="IV-4",
                                     month_index=4, due_date="2026-11-01")
    previewed = payment_claims.preview(contract.customer_uid, "100", "2026-10-23")
    assert previewed["allocations"][0]["invoice_doc_no"] == "IV-4"
    named = payment_claims.preview(contract.customer_uid, "100", "2026-10-23", reference="IV-2")
    assert named["allocations"][0]["invoice_doc_no"] == "IV-2"


def test_accounting_review_is_durable_and_repeated_confirm_does_not_double_move(scenario):
    client, contract, state, body = scenario
    old = preview(client, contract, body).json()
    args = {**body, "preview_version": old["version"], "idempotency_key": "same"}
    path = f"/v1/contracts/{contract.uid}/service-deferrals"
    first = client.post(path, json=args)
    second = client.post(path, json=args)
    assert first.status_code == second.status_code == 200
    uid = first.json()["deferral"]["uid"]
    assert uid == second.json()["deferral"]["uid"]
    review = client.post(path + f"/{uid}/accounting-review", json={
        "status": "REVIEWED", "document_refs": ["CN-1", "IV-NEW"], "note": "บัญชีตรวจแล้ว"})
    assert review.status_code == 200, review.text
    stored = client.get(path).json()["deferrals"]
    assert len(stored) == 1
    assert stored[0]["accounting"]["document_refs"] == ["CN-1", "IV-NEW"]


def test_postgres_deferral_survives_new_connections(scenario, pg_conn, pg_url, monkeypatch):
    from sqlalchemy import text
    from app import db, migrate, service_deferrals
    migrate.apply(pg_conn)
    pg_conn.execute(text("delete from records.service_deferral"))
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    _, contract, state, body = scenario
    try:
        p = service_deferrals.preview(contract.uid, body)
        row = service_deferrals.confirm(contract.uid, {**body, "preview_version": p["version"],
                                          "idempotency_key": "pg"}, "debt-user", "OFFICER")
        db.reset()
        saved = service_deferrals.list_for_contract(contract.uid)
        assert saved[0]["uid"] == row["uid"]
        assert saved[0]["moves"][1]["new_due_date"] == "2027-01-01"
        assert main._contract_view(contract)[3].cumulative_arrears == Decimal("0")
    finally:
        pg_conn.rollback()
        pg_conn.execute(text("delete from records.service_deferral"))
        pg_conn.commit()
        db.reset()


def test_deferral_is_not_erased_by_same_peak_invoice_reseed(scenario):
    client, contract, state, body = scenario
    assert create(scenario).status_code == 200
    state.invoices = {uid: dict(inv) for uid, inv in state.invoices.items()}
    cases.reset()
    assert main._contract_view(contract)[3].cumulative_arrears == Decimal("0")
    assert client.get(f"/v1/cases/by-customer/{contract.customer_uid}").json()["payment_summary"]["totals"]["paid_count"] == 1


def test_lost_invoice_mapping_refuses_instead_of_using_paid_through(scenario):
    client, contract, state, body = scenario
    assert create(scenario).status_code == 200
    del state.invoices["fault-1"]
    response = client.get(f"/v1/cases/by-customer/{contract.customer_uid}")
    assert response.status_code == 409
    assert response.json()["code"] == "service_deferral_invoice_missing"


def test_note_with_optional_case_attachment_is_accepted(scenario):
    from app.attachments import store as attachments
    client, contract, state, body = scenario
    attachment = attachments.put({"filename": "service.pdf", "content_type": "application/pdf",
                                  "sha256": hashlib.sha256(b"%PDF service").hexdigest(), "kind": "PDF", "size": 12}, b"%PDF service",
                                 "debt-user", {"state": "CLEAN", "by": "test"})
    attachments.attach(attachment["uid"], "case:" + contract.customer_uid)
    response = preview(client, contract, {**body, "evidence_uid": attachment["uid"]})
    assert response.status_code == 200, response.text


def test_accounting_queue_lists_pending_tasks_and_ops_can_review_them(scenario):
    client, contract, state, body = scenario
    assert create(scenario).status_code == 200
    queue = client.get("/v1/service-deferrals", params={"accounting_status": "PENDING_REVIEW"})
    assert queue.status_code == 200
    assert queue.json()["deferrals"][0]["customer_uid"] == contract.customer_uid
    uid = queue.json()["deferrals"][0]["uid"]
    response = client.post(f"/v1/contracts/{contract.uid}/service-deferrals/{uid}/accounting-review",
                           json={"status": "REVIEWED", "note": "บัญชีตรวจสอบแล้ว", "document_refs": ["CN-2"]},
                           headers={"X-Volt-Role": "OPS"})
    assert response.status_code == 200
    assert not client.get("/v1/service-deferrals", params={"accounting_status": "PENDING_REVIEW"}).json()["deferrals"]


def test_replacing_schedule_requires_reversing_active_deferrals(scenario):
    from app import errors
    assert create(scenario).status_code == 200
    _, contract, state, _ = scenario
    with pytest.raises(errors.Problem) as rejected:
        cases._set_contract_fields(contract, instalments=list(contract.instalments))
    assert rejected.value.code == "service_deferral_schedule_locked"


def test_open_service_ticket_does_not_hold_other_cycles_after_deferral(scenario):
    client, contract, state, body = scenario
    cs = cases.for_current()
    case = cs.cases[contract.customer_uid]
    issue = cases._make_issue(cs, case, {"summary": "ติดตั้งไม่สมบูรณ์", "opened_on": "2026-08-01"})
    body["issue_uid"] = issue["uid"]
    assert create(scenario).status_code == 200
    assert issue["status"] == "OPEN"
    served = client.get(f"/v1/cases/by-customer/{contract.customer_uid}").json()
    assert "งวดอื่นยังนับตามปกติ" in served["issues"][0]["fee_clock_note_th"]
    assert main._contract_view(contract, date(2026, 12, 1))[3].penalty_accrued_unbilled > ZERO
    from app.npl_assessment import assess
    assessment = assess([contract], as_of=date(2027, 2, 1), field_of=cases.contract_field_of)
    assert assessment.automatic_npl
    assert not assessment.assessment_hold


ZERO = Decimal("0")


def test_other_contract_payment_invalidates_preview(scenario):
    client, contract, state, body = scenario
    other = ContractFixture("K-OTHER", contract.customer_uid, "LEASE", Decimal("100"), 1,
        date(2026, 10, 1), instalments=[Instalment(date(2026, 10, 1), "REGULAR", Decimal("100"), ZERO)])
    customer = main.BY_CUSTOMER[contract.customer_uid]
    customer.contracts.append(other)
    main.BY_CONTRACT[other.uid] = (customer, other)
    state.invoices["other"] = dict(state.invoices["fault-1"], uid="other", peak_number="IV-OTHER",
        contract_uid=other.uid, month_index=1, due_date="2026-10-01")
    p = preview(client, contract, body).json()
    state.invoices["other"].update(outstanding="0.00", state="PAID")
    response = client.post(f"/v1/contracts/{contract.uid}/service-deferrals", json={
        **body, "preview_version": p["version"], "idempotency_key": "stale-other"})
    assert response.status_code == 409
    assert "preview_stale" in response.text


def test_retry_succeeds_after_original_ticket_is_unavailable(scenario):
    client, contract, state, body = scenario
    cs = cases.for_current()
    issue = cases._make_issue(cs, cs.cases[contract.customer_uid], {
        "summary": "ติดตั้งไม่สมบูรณ์", "opened_on": "2026-08-01"})
    issue["fault_confirmed"] = True
    body.update(issue_uid=issue["uid"], confirmation_note="", confirmed_by="")
    p = preview(client, contract, body).json()
    command = {**body, "preview_version": p["version"], "idempotency_key": "retry-ticket"}
    path = f"/v1/contracts/{contract.uid}/service-deferrals"
    first = client.post(path, json=command)
    assert first.status_code == 200
    cs.issues.pop(issue["uid"])
    second = client.post(path, json=command)
    assert second.status_code == 200
    assert second.json()["deferral"]["uid"] == first.json()["deferral"]["uid"]


def test_other_contracts_keep_authoritative_peak_arrears(scenario):
    client, contract, state, body = scenario
    line = Instalment(date(2026, 10, 1), "REGULAR", Decimal("100"), ZERO, paid_principal=Decimal("100"))
    other = ContractFixture("K-OTHER", contract.customer_uid, "LEASE", Decimal("100"), 1,
                            date(2026, 10, 1), instalments=[line])
    customer = main.BY_CUSTOMER[contract.customer_uid]
    customer.contracts.append(other)
    main.BY_CONTRACT[other.uid] = (customer, other)
    state.invoices["other"] = dict(state.invoices["fault-1"], uid="other", peak_number="IV-OTHER",
                                    contract_uid=other.uid, month_index=1, due_date="2026-10-01")
    assert create(scenario).status_code == 200
    data = client.get(f"/v1/cases/by-customer/{customer.uid}").json()
    assert data["case"]["payment_status_system"] == "LATE"
    assert data["payment_summary"]["totals"]["overdue_amount"] == "100.00"


def test_receipt_snapshot_does_not_spill_m3_cash_into_deferred_m1(scenario):
    from app import payment_claims, service_deferrals
    _, contract, state, _ = scenario
    assert create(scenario).status_code == 200
    invoices = [dict(service_deferrals.decorate_invoice(i), customer_uid=contract.customer_uid,
                     snapshot_as_of="2026-10-23") for i in state.invoices.values()]
    result = payment_claims.reconcile_receipts(invoices, [{"doc_no": "RC-3", "invoice_ref": "IV-3",
        "paid_amount": "100", "paid_on": "2026-10-01", "status": "PAID", "customer_uid": contract.customer_uid}])
    assert [(r["invoice_doc_no"], r["amount"]) for r in result["allocations"]] == [("IV-3", "100.00")]
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "100.00"
    assert result["invoices"]["IV-3"]["confirmed_outstanding"] == "0.00"


def test_original_reminders_are_closed_but_next_unmoved_cycle_is_still_schedulable(scenario):
    from app import payment_claims
    client, contract, state, body = scenario
    case = cases.for_current().cases[contract.customer_uid]
    case.update(next_action="SEND_REMINDER", next_action_on="2026-10-01", next_action_set_by="debt-user")
    assert create(scenario).status_code == 200
    rows = client.get("/v1/today/reminders", params={"days": 0}).json()["reminders"]
    assert not any(r["customer_uid"] == contract.customer_uid for r in rows)
    reminder = payment_claims.reminder_preview(contract.customer_uid)
    assert reminder["invoice_count"] == 0
    assert reminder["blocked_reason"] == "SERVICE_DEFERRED"
    after = cases.for_current().cases[contract.customer_uid]
    assert after["next_action_on"] == "2026-11-01"
    assert after["service_deferral_followup_history"][0]["next_action_on"] == "2026-10-01"


def test_receipts_after_the_invoice_snapshot_reduce_the_latest_balance(scenario):
    from app import payment_claims, service_deferrals
    _, contract, state, _ = scenario
    assert create(scenario).status_code == 200
    state.invoices["fault-3"]["outstanding"] = "50.00"
    inv = dict(service_deferrals.decorate_invoice(state.invoices["fault-3"]),
               customer_uid=contract.customer_uid, snapshot_as_of="2026-10-01")
    result = payment_claims.reconcile_receipts([inv], [{"doc_no": "NEW-3", "invoice_ref": "IV-3",
        "paid_amount": "10", "paid_on": "2026-10-02", "status": "PAID", "customer_uid": contract.customer_uid}])
    assert result["invoices"]["IV-3"]["confirmed_outstanding"] == "40.00"
    assert result["invoices"]["IV-3"]["confirmed_paid"] == "60.00"


def test_new_due_date_becomes_overdue_and_can_be_reminded(scenario, monkeypatch):
    from app import clock, payment_claims
    client, contract, state, _ = scenario
    assert create(scenario).status_code == 200
    monkeypatch.setenv("VOLT_BUSINESS_DATE", "2027-01-02")
    clock.reset()
    pp = payment_claims.reminder_preview(contract.customer_uid)
    assert pp["invoice_count"] == 2
    assert {r["due_on"] for r in pp["invoices"]} == {"2026-12-01", "2027-01-01"}


def test_closing_ticket_after_deferral_does_not_restore_a_permanent_hold_on_reversal(scenario):
    client, contract, state, body = scenario
    cs = cases.for_current()
    case = cs.cases[contract.customer_uid]
    issue = cases._make_issue(cs, case, {"summary": "ปัญหาบริการ", "opened_on": "2026-08-01"})
    body["issue_uid"] = issue["uid"]
    created = create(scenario)
    assert created.status_code == 200
    cases.close_issue(cs, case, issue["uid"], "ops", resolution_note="ติดตั้งสมบูรณ์แล้ว")
    uid = created.json()["deferral"]["uid"]
    path = f"/v1/contracts/{contract.uid}/service-deferrals/{uid}"
    p = client.post(path + "/reverse-preview", json={"reason": "ย้อน"})
    assert p.status_code == 200
    assert client.post(path + "/reverse", json={"reason": "ย้อน", "preview_version": p.json()["version"]}).status_code == 200
    assert cases.contract_field_of(contract, "fee_state") is None


def test_postgres_receipt_reimport_keeps_cash_on_m3(scenario, pg_conn, pg_url, monkeypatch):
    from sqlalchemy import text
    from app import db, migrate, payment_claims, service_deferrals
    migrate.apply(pg_conn)
    pg_conn.execute(text("delete from records.service_deferral"))
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    _, contract, state, body = scenario
    try:
        p = service_deferrals.preview(contract.uid, body)
        service_deferrals.confirm(contract.uid, {**body, "preview_version": p["version"],
                                    "idempotency_key": "pg-import"}, "debt", "OFFICER")
        inv_run = pg_conn.execute(text("insert into landing.import_run(source_system,status,meta) "
            "values ('PEAK','OK',cast(:m as jsonb)) returning id"), {"m": '{"report_as_of":"2026-10-23","applied":{"at":"2026-10-23T10:00:00Z"}}'}).scalar_one()
        no = main.BY_CUSTOMER[contract.customer_uid].customer_no
        for n in (1, 2, 3):
            pg_conn.execute(text("insert into landing.peak_invoice(import_run_id,doc_no,doc_kind,status,"
                "amount_due,amount_awaiting,verdict,customer_no,cycle_n,due_on) "
                "values (:r,:doc,'INVOICE',:s,100,:owed,'EXACT',:no,:n,:due)"),
                {"r": inv_run, "doc": f"IV-{n}", "s": "PAID" if n == 3 else "OVERDUE",
                 "owed": 0 if n == 3 else 100, "no": no, "n": n, "due": date(2026, n + 7, 1)})
        receipt_run = pg_conn.execute(text("insert into landing.import_run(source_system,status,meta) "
            "values ('PEAK_RECEIPT','OK',cast(:m as jsonb)) returning id"), {"m": '{"applied":{"at":"2026-10-23T11:00:00Z"}}'}).scalar_one()
        pg_conn.execute(text("insert into landing.peak_receipt(import_run_id,doc_no,doc_kind,status,paid_amount,paid_on,"
            "invoice_ref,invoice_doc_no,customer_no,verdict) values (:r,'RC-3','RECEIPT','PAID',100,'2026-10-01','IV-3','IV-3',:no,'EXACT')"),
            {"r": receipt_run, "no": no})
        pg_conn.commit()
        for _ in range(2):
            payment_claims.reconcile_applied(pg_conn, receipt_run)
            pg_conn.commit()
            rows = pg_conn.execute(text("select invoice_doc_no, amount from records.payment_allocation "
                "where active and receipt_doc_no='RC-3'")).fetchall()
            assert [(r[0], str(r[1])) for r in rows] == [("IV-3", "100.00")]
            pg_conn.commit()
        # A later receipt must supplement the snapshot's unnamed partial payment
        # when the durable ledger is read into a fresh served book.
        pg_conn.execute(text("update landing.peak_invoice set amount_awaiting=70, status='OVERDUE' where doc_no='IV-3'"))
        pg_conn.execute(text("update landing.peak_receipt set paid_amount=40, paid_on='2026-10-24' where doc_no='RC-3'"))
        payment_claims.reconcile_applied(pg_conn, receipt_run)
        from app.pipelines import peak_writer
        served = peak_writer.invoices_for_book(pg_conn)[no]["invoices"]
        third = next(i for i in served if i["doc_no"] == "IV-3")
        assert Decimal(third["amount_awaiting"]) == Decimal("30.00")
        assert Decimal(third["paid_amount"]) == Decimal("70.00")
        # Customer identity must also work for a deferral recorded before PEAK
        # issued the original invoices, without any stored document references.
        saved = pg_conn.execute(text("select uid,payload from records.service_deferral")).first()
        import json
        payload = dict(saved[1])
        payload["moves"] = [dict(m, invoice_doc_no=None) for m in payload["moves"]]
        pg_conn.execute(text("update records.service_deferral set payload=cast(:p as jsonb) where uid=:uid"),
                        {"p": json.dumps(payload), "uid": saved[0]})
        third = next(i for i in peak_writer.invoices_for_book(pg_conn)[no]["invoices"] if i["doc_no"] == "IV-3")
        assert Decimal(third["amount_awaiting"]) == Decimal("30.00")
    finally:
        pg_conn.rollback()
        pg_conn.execute(text("delete from records.service_deferral"))
        pg_conn.execute(text("delete from records.payment_allocation where receipt_doc_no='RC-3'"))
        pg_conn.commit()
        db.reset()
