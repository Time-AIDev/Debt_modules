"""Financial release gates: snapshot overlap, observation chronology and evidence.

Postgres cases use the disposable VOLT_TEST_PG_URL database, never production.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import db, errors, journey, landing, migrate, payment_claims, service_deferrals
from app.pipelines import peak_writer


def _invoice(outstanding="40.00", snapshot="2026-09-30"):
    return {"doc_no": "IV-1", "uid": "inv-pk-IV-1", "amount": "100.00",
            "outstanding": outstanding, "snapshot_as_of": snapshot,
            "customer_uid": "cus-1", "customer_no": "C1", "due_on": "2026-09-01"}


def _receipt(amount="60.00", paid_on="2026-09-15", **kw):
    return dict({"doc_no": "RE-1", "invoice_ref": "IV-1", "paid_amount": amount,
                 "paid_on": paid_on, "status": "PAID", "customer_uid": "cus-1",
                 "customer_no": "C1", "exported_at": "2026-09-30T12:00:00", "run_id": 1}, **kw)


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity", "1e9999"])
def test_nonfinite_money_is_a_validation_error(value):
    with pytest.raises(errors.Problem) as raised:
        payment_claims._money(value)
    assert raised.value.status == 422
    result = payment_claims.reconcile_receipts([_invoice()], [_receipt(value)])
    assert result["allocations"] == []
    assert result["exceptions"][0]["reason"] == "AMOUNT_INVALID"


def test_historical_receipt_does_not_subtract_snapshot_twice_or_manufacture_credit():
    result = payment_claims.reconcile_receipts([_invoice()], [_receipt()])
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "40.00"
    assert result["invoices"]["IV-1"]["confirmed_paid"] == "60.00"
    assert result["credit_by_customer"] == {}
    assert [(row["invoice_doc_no"], row["amount"]) for row in result["allocations"]] == [("IV-1", "60.00")]


def test_cash_after_snapshot_is_capped_at_remaining_debt_and_excess_is_credit():
    result = payment_claims.reconcile_receipts([_invoice()], [
        _receipt("20.00"), _receipt("60.00", "2026-10-01", doc_no="RE-2", run_id=2)])
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "0.00"
    assert result["credit_by_customer"] == {"cus-1": "20.00"}
    assert [(row["invoice_doc_no"], row["amount"]) for row in result["allocations"]
            if row["receipt_doc_no"] == "RE-2"] == [("IV-1", "40.00"), (None, "20.00")]


def test_partial_receipt_after_snapshot_reduces_balance_without_history_present():
    result = payment_claims.reconcile_receipts([_invoice()], [_receipt("10.00", "2026-10-01")])
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "30.00"
    assert result["invoices"]["IV-1"]["confirmed_paid"] == "70.00"


def test_newer_cancellation_wins_over_later_import_of_old_paid_export():
    result = payment_claims.reconcile_receipts([_invoice("100.00")], [
        _receipt(status="CANCELLED", exported_at="2026-10-01T12:00:00", run_id=2),
        _receipt(exported_at="2026-09-30T12:00:00", run_id=99)])
    assert result["allocations"] == []
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "100.00"


def test_cancellation_after_snapshot_reverses_the_historical_cash_it_included():
    result = payment_claims.reconcile_receipts([_invoice()], [
        _receipt(status="CANCELLED", exported_at="2026-10-01T12:00:00", run_id=2)])
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "100.00"
    assert result["invoices"]["IV-1"]["confirmed_paid"] == "0.00"
    assert result["credit_by_customer"] == {}


def test_cancellation_reverses_historical_fifo_spill_to_a_second_invoice():
    invoices = [_invoice("0.00"), dict(_invoice("80.00"), doc_no="IV-2", uid="inv-pk-IV-2")]
    result = payment_claims.reconcile_receipts(invoices, [
        _receipt("120.00", status="CANCELLED", exported_at="2026-10-01T12:00:00")])
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "100.00"
    assert result["invoices"]["IV-2"]["confirmed_outstanding"] == "100.00"
    assert result["allocations"] == [] and result["credit_by_customer"] == {}


def test_zero_amount_cancellation_uses_prior_paid_evidence():
    result = payment_claims.reconcile_receipts([_invoice()], [
        _receipt(), _receipt("0", paid_on=None, status="CANCELLED", run_id=2,
                             exported_at="2026-10-01T12:00:00")])
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == "100.00"
    assert result["exceptions"] == []


@pytest.mark.parametrize("replacement", ["35.00", "100.00"])
def test_distinct_paid_receipt_settles_a_cancelled_snapshot_payment(replacement):
    """Cancellation restores liability, while a separate valid receipt still pays it.

    A proof-removal comparison is not a before-cancellation ledger: the current
    paid replacement and opening snapshot remain in that comparison. Gross
    cancelled cash therefore need not equal the increase in unpaid invoices.
    """
    invoices = [dict(_invoice("0.00", "2026-09-14"), doc_no=doc,
                     source_payments=[{"receipt_no": old, "on": on, "amount": "100.00"}])
                for doc, old, on in (("IV-1", "RE-OLD-1", "2026-08-11"),
                                     ("IV-2", "RE-OLD-2", "2026-09-03"))]
    cancelled = [_receipt(None, None, doc_no=old, invoice_ref=doc,
                          status="CANCELLED", exported_at="2026-09-30", run_id=2)
                 for doc, old in (("IV-1", "RE-OLD-1"), ("IV-2", "RE-OLD-2"))]
    paid = _receipt(replacement, "2026-09-08", doc_no="RE-REPLACEMENT",
                    exported_at="2026-09-30", run_id=2)
    result = payment_claims.reconcile_receipts(invoices, [*cancelled, paid])
    unpaid = sum((Decimal(row["confirmed_outstanding"])
                  for row in result["invoices"].values()), Decimal(0))
    cash = sum((Decimal(row["amount"]) for row in result["allocations"]), Decimal(0))
    assert unpaid + cash == Decimal("200.00")
    assert cash == Decimal(replacement)
    assert result["invoices"]["IV-1"]["confirmed_outstanding"] == str(Decimal("100.00") - cash)
    assert result["invoices"]["IV-2"]["confirmed_outstanding"] == "100.00"
    assert {row["receipt_doc_no"] for row in result["allocations"]} == {"RE-REPLACEMENT"}
    assert result["credit_by_customer"] == {} and result["exceptions"] == []
    assert payment_claims.reconcile_receipts(invoices, [*cancelled, paid] * 2) == result
    without_replacement = payment_claims.reconcile_receipts(invoices, cancelled)
    assert sum(Decimal(row["confirmed_outstanding"])
               for row in without_replacement["invoices"].values()) == Decimal("200.00")


def test_undated_receipt_or_balance_is_queued_for_review_instead_of_guessing():
    invalid_date = payment_claims.reconcile_receipts([_invoice()], [_receipt(paid_on=None)])
    assert invalid_date["exceptions"][0]["reason"] == "PAID_DATE_INVALID"
    unknown_snapshot = payment_claims.reconcile_receipts([_invoice(snapshot=None)], [_receipt()])
    assert unknown_snapshot["exceptions"][0]["reason"] == "SNAPSHOT_DATE_MISSING"
    assert unknown_snapshot["credit_by_customer"] == {}


def test_large_independent_customer_book_keeps_receipt_cash_isolated():
    invoices, receipts = [], []
    for index in range(1000):
        customer = "customer-%04d" % index
        doc = "IV-%04d" % index
        invoices.append(dict(_invoice("100.00"), doc_no=doc, uid=doc,
                             customer_uid=customer, customer_no=customer))
        receipts.append(dict(_receipt("100.00", "2026-10-01"), doc_no="RE-%04d" % index,
                             invoice_ref=doc, customer_uid=customer, customer_no=customer))
    result = payment_claims.reconcile_receipts(invoices, receipts)
    assert len(result["allocations"]) == 1000 and result["credit_by_customer"] == {}
    assert all(row["confirmed_outstanding"] == "0.00" for row in result["invoices"].values())
    assert all(row["order"] == 1 for row in result["allocations"])
    assert all(row["invoice_doc_no"].split("-")[1] == row["receipt_doc_no"].split("-")[1]
               for row in result["allocations"])


@pytest.fixture
def financial_db(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.execute(text(
        "truncate landing.import_run, records.payment_claim, records.payment_reconciliation_exception "
        "restart identity cascade"))
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    monkeypatch.setattr(journey, "book_customers", lambda: [SimpleNamespace(uid="cus-1", customer_no="C1")])
    monkeypatch.setattr(service_deferrals, "records", lambda: [])
    return pg_conn


def _run(conn, source, as_of, exported_at=None, applied=True):
    meta = {"report_as_of": as_of, "exported_at": exported_at or as_of}
    if applied:
        meta["applied"] = {"at": "2026-10-06T00:00:00+00:00", "by": "review"}
    run_id = landing.start_run(conn, source, meta=meta)
    landing.finish_run(conn, run_id, "OK")
    return run_id


def _invoice_row(conn, run_id, outstanding="40.00", doc_no="IV-1"):
    conn.execute(text(
        "insert into landing.peak_invoice (import_run_id,doc_no,doc_kind,status,customer_no, "
        "contact_code,issued_on,due_on,amount_total,amount_due,amount_awaiting,verdict,rule) "
        "values (:run,:doc,'IV','AWAITING','C1','C1','2026-09-01','2026-09-01',100,100,:out,'EXACT','CUSTOMER_NO')"),
        {"run": run_id, "out": outstanding, "doc": doc_no})


def _receipt_row(conn, run_id, status="PAID", amount="60.00", paid_on="2026-09-15"):
    conn.execute(text(
        "insert into landing.peak_receipt (import_run_id,doc_no,doc_kind,status,customer_no, "
        "invoice_ref,invoice_doc_no,paid_on,paid_amount,verdict,rule) "
        "values (:run,'RE-1','RE',:status,'C1','IV-1','IV-1',cast(:paid as date),:amount,'EXACT','INVOICE_REF_AND_CUSTOMER')"),
        {"run": run_id, "status": status, "amount": amount, "paid": paid_on})


def _claim_row(conn, uid, paid_on, amount="60.00", doc_no="IV-1"):
    conn.execute(text(
        "insert into records.payment_claim (uid,customer_uid,amount,paid_on,reference,created_by, "
        "created_role,idempotency_key,state,note) "
        "values (:uid,'cus-1',:amount,cast(:paid as date),:doc,'review','OWNER',:uid,'PENDING','evidence')"),
        {"uid": uid, "paid": paid_on, "amount": amount, "doc": doc_no})
    conn.execute(text(
        "insert into records.payment_claim_target "
        "(claim_uid,invoice_doc_no,amount,allocation_order,before_amount,after_amount) "
        "values (:uid,:doc,:amount,1,100,:after)"),
        {"uid": uid, "doc": doc_no, "amount": Decimal(amount), "after": Decimal("100.00") - Decimal(amount)})


def test_database_claim_match_requires_customer_invoice_and_payment_date(financial_db):
    conn = financial_db
    invoice_run = _run(conn, "PEAK", "2026-09-30")
    _invoice_row(conn, invoice_run)
    receipt_run = _run(conn, "PEAK_RECEIPT", "2026-09-30")
    _receipt_row(conn, receipt_run)
    _claim_row(conn, "claim-different-day", "2026-10-20")
    _claim_row(conn, "claim-matching-day", "2026-09-15")
    result = payment_claims.reconcile_applied(conn, receipt_run)
    assert result["customer_credit"] == "0.00"
    states = dict(conn.execute(text("select uid,state from records.payment_claim")).all())
    assert states == {"claim-different-day": "PENDING", "claim-matching-day": "CONFIRMED"}
    assert conn.execute(text(
        "select claim_uid from records.payment_claim_receipt where active")).scalar() == "claim-matching-day"


def test_immutable_versions_keep_old_claims_and_balances_after_cancellation(financial_db):
    conn = financial_db
    invoice_run = _run(conn, "PEAK", "2026-09-30")
    _invoice_row(conn, invoice_run)
    paid_run = _run(conn, "PEAK_RECEIPT", "2026-09-30")
    _receipt_row(conn, paid_run)
    _claim_row(conn, "claim-history", "2026-09-15")
    first = payment_claims.reconcile_applied(conn, paid_run)
    old = conn.execute(text(
        "select inputs,outputs from records.payment_reconciliation_version where sequence=:s"),
        {"s": first["reconciliation_version"]}).one()
    cancelled_run = _run(conn, "PEAK_RECEIPT", "2026-10-01")
    _receipt_row(conn, cancelled_run, status="CANCELLED", amount="0", paid_on=None)
    second = payment_claims.reconcile_applied(conn, cancelled_run)
    assert second["reconciliation_version"] > first["reconciliation_version"]
    assert conn.execute(text(
        "select inputs,outputs from records.payment_reconciliation_version where sequence=:s"),
        {"s": first["reconciliation_version"]}).one() == old
    assert old.outputs["claims"][0]["state"] == "CONFIRMED"
    assert old.outputs["invoices"]["IV-1"]["confirmed_outstanding"] == "40.00"
    assert conn.execute(text("select count(*) from records.payment_claim_receipt where active")).scalar() == 0
    latest = conn.execute(text(
        "select outputs from records.payment_reconciliation_version order by sequence desc limit 1")).scalar()
    assert latest["invoices"]["IV-1"]["confirmed_outstanding"] == "100.00"
    served = peak_writer.invoices_for_book(conn)["C1"]["invoices"][0]
    assert served["amount_awaiting"] == "100.00"
    for command in ("update records.payment_reconciliation_version set reason='tampered'",
                    "delete from records.payment_reconciliation_version"):
        with pytest.raises(DBAPIError, match="append-only"):
            with conn.begin_nested():
                conn.execute(text(command))


def test_database_old_paid_export_cannot_resurrect_newer_cancelled_receipt(financial_db):
    conn = financial_db
    invoice_run = _run(conn, "PEAK", "2026-09-30")
    _invoice_row(conn, invoice_run, "100.00")
    cancelled_run = _run(conn, "PEAK_RECEIPT", "2026-10-01", "2026-10-01T12:00:00")
    _receipt_row(conn, cancelled_run, status="CANCELLED")
    old_paid_run = _run(conn, "PEAK_RECEIPT", "2026-09-30", "2026-09-30T12:00:00")
    _receipt_row(conn, old_paid_run)
    result = payment_claims.reconcile_applied(conn, old_paid_run)
    assert result["allocated_to_invoices"] == "0.00"
    assert conn.execute(text("select count(*) from records.payment_allocation where active")).scalar() == 0
    served = peak_writer.invoices_for_book(conn)["C1"]["invoices"][0]
    assert served["amount_awaiting"] == "100.00"


def test_invoice_apply_rebuilds_existing_receipt_projection_atomically(financial_db, monkeypatch):
    from app.routers import peak_pipeline
    conn = financial_db
    first_invoice = _run(conn, "PEAK", "2026-09-01")
    _invoice_row(conn, first_invoice, "100.00")
    receipt_run = _run(conn, "PEAK_RECEIPT", "2026-09-16")
    _receipt_row(conn, receipt_run, amount="20.00")
    payment_claims.reconcile_applied(conn, receipt_run)
    new_invoice = _run(conn, "PEAK", "2026-09-30", applied=False)
    _invoice_row(conn, new_invoice, "40.00")
    conn.commit()
    monkeypatch.setattr(peak_pipeline, "_served", lambda payload, *_args: payload)
    result = peak_pipeline.apply_run(new_invoice, {}, "OWNER", "review")
    assert result["reconciliation"]["customer_credit"] == "0.00"
    latest = conn.execute(text(
        "select invoice_run_id,reason,outputs from records.payment_reconciliation_version "
        "order by sequence desc limit 1")).one()
    assert latest.invoice_run_id == new_invoice and latest.reason == "invoice_apply"
    assert latest.outputs["invoices"]["IV-1"]["confirmed_outstanding"] == "40.00"
    served = peak_writer.invoices_for_book(conn)["C1"]["invoices"][0]
    assert served["amount_awaiting"] == "40.00"


def test_reconciliation_works_under_runtime_role_without_delete_permission(financial_db):
    conn = financial_db
    invoice_run = _run(conn, "PEAK", "2026-09-30")
    _invoice_row(conn, invoice_run)
    receipt_run = _run(conn, "PEAK_RECEIPT", "2026-09-30")
    _receipt_row(conn, receipt_run)
    _claim_row(conn, "claim-runtime-role", "2026-09-15")
    conn.commit()
    # The role and grants exist only in this test transaction and roll back.
    conn.execute(text("create role financial_runtime_review"))
    migrate.grant_runtime(conn, "financial_runtime_review")
    conn.execute(text("set local role financial_runtime_review"))
    assert not conn.execute(text(
        "select has_table_privilege(current_user,'records.payment_claim_receipt','DELETE')")).scalar()
    result = payment_claims.reconcile_applied(conn, receipt_run)
    assert result["claims_confirmed"] == 1
    conn.rollback()


def test_post_snapshot_cash_and_ledger_agree_in_served_book(financial_db):
    conn = financial_db
    invoice_run = _run(conn, "PEAK", "2026-09-30")
    _invoice_row(conn, invoice_run)
    receipt_run = _run(conn, "PEAK_RECEIPT", "2026-10-01")
    _receipt_row(conn, receipt_run, amount="10.00", paid_on="2026-10-01")
    payment_claims.reconcile_applied(conn, receipt_run)
    served = peak_writer.invoices_for_book(conn)["C1"]["invoices"][0]
    assert (served["amount_awaiting"], served["paid_amount"]) == ("30.00", "70.00")


def test_claim_cannot_consume_cash_allocated_to_a_different_invoice(financial_db):
    conn = financial_db
    invoice_run = _run(conn, "PEAK", "2026-09-30")
    _invoice_row(conn, invoice_run)
    _invoice_row(conn, invoice_run, "80.00", "IV-2")
    receipt_run = _run(conn, "PEAK_RECEIPT", "2026-10-01")
    _receipt_row(conn, receipt_run, amount="60.00", paid_on="2026-10-01")
    # This claim sorts first but only 20 of the receipt's 60 belong to IV-2.
    _claim_row(conn, "claim-a-IV2", "2026-10-01", "40.00", "IV-2")
    _claim_row(conn, "claim-b-IV1", "2026-10-01", "40.00")
    payment_claims.reconcile_applied(conn, receipt_run)
    claims = {row.uid: (row.state, str(row.confirmed_amount)) for row in conn.execute(text(
        "select uid,state,confirmed_amount from records.payment_claim"))}
    assert claims == {"claim-a-IV2": ("PARTIALLY_CONFIRMED", "20.00"),
                      "claim-b-IV1": ("CONFIRMED", "40.00")}


def test_credit_only_claim_requires_matching_customer_reference_and_date(financial_db):
    conn = financial_db
    invoice_run = _run(conn, "PEAK", "2026-09-30")
    _invoice_row(conn, invoice_run, "0.00")
    receipt_run = _run(conn, "PEAK_RECEIPT", "2026-10-01")
    _receipt_row(conn, receipt_run, amount="20.00", paid_on="2026-10-01")
    conn.execute(text(
        "insert into records.payment_claim (uid,customer_uid,amount,paid_on,reference,created_by, "
        "created_role,idempotency_key,state,credit_amount,note) values "
        "('claim-credit','cus-1',20,'2026-10-01','IV-1','review','OWNER','credit','PENDING',20,'credit')"))
    result = payment_claims.reconcile_applied(conn, receipt_run)
    assert result["customer_credit"] == "20.00"
    assert conn.execute(text("select state from records.payment_claim where uid='claim-credit'")).scalar() == "CONFIRMED"


def test_identity_link_commands_rebuild_ownership_without_reimport(financial_db, monkeypatch):
    from app.routers import peak_pipeline
    conn = financial_db
    monkeypatch.setattr(journey, "book_customers", lambda: [
        SimpleNamespace(uid="cus-1", customer_no="C1"), SimpleNamespace(uid="cus-2", customer_no="C2")])
    invoice_run = _run(conn, "PEAK", "2026-09-30")
    _invoice_row(conn, invoice_run)
    receipt_run = _run(conn, "PEAK_RECEIPT", "2026-09-30")
    _receipt_row(conn, receipt_run)
    conn.execute(text("update landing.peak_receipt set contact_code='C1'"))
    payment_claims.reconcile_applied(conn, receipt_run)
    conn.commit()
    monkeypatch.setattr(peak_pipeline, "_served", lambda payload, *_args: payload)
    confirmed = peak_pipeline.confirm_link({"contact_code": "C1", "customer_no": "C2"}, "OWNER", "review")
    assert confirmed["reconciliation"] is not None
    assert conn.execute(text(
        "select customer_uid from records.payment_allocation where active")).scalar() == "cus-2"
    conn.commit()
    retired = peak_pipeline.retire_link(confirmed["link"]["uid"], {}, "OWNER", "review")
    assert retired["reconciliation"] is not None
    assert conn.execute(text(
        "select customer_uid from records.payment_allocation where active")).scalar() == "cus-1"
