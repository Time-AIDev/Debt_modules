from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app import db, financial_evidence, payment_claims


def inputs(parts, *, status='PAID', snapshot='2026-09-14'):
    invoices = [{'doc_no': 'IV-1', 'customer_uid': 'C1', 'customer_no': 'C1', 'amount': '100',
                 'outstanding': '60', 'snapshot_as_of': snapshot, 'due_on': '2026-09-01'}]
    receipts = [{'doc_no': 'RE-1', 'invoice_ref': 'IV-1', 'customer_uid': 'C1', 'customer_no': 'C1',
                 'status': status, 'paid_on': parts[-1]['on'], 'paid_amount': str(sum(int(p['amount']) for p in parts)),
                 'payments': parts, 'exported_at': '2026-09-30', 'run_id': 2}]
    sources = [{'id': 1, 'source_system': 'PEAK', 'covers_from': '2024-01-01'},
               {'id': 2, 'source_system': 'PEAK_RECEIPT', 'covers_from': '2026-01-01'}]
    reconciliation = {'sequence': 1, 'snapshot_as_of': snapshot}
    return invoices, receipts, sources, reconciliation


def test_read_dto_preserves_split_dates_channels_without_changing_balance_rules():
    data = inputs([{'on': '2026-09-10', 'amount': '40', 'channel': 'Bank A'},
                   {'on': '2026-09-20', 'amount': '60', 'channel': 'Bank B'}])
    before = payment_claims.reconcile_receipts(data[0], data[1])
    evidence = financial_evidence.build(*data)
    assert evidence['read_only']
    assert [float(row['amount']) for row in evidence['invoice_components']['IV-1']] == [40, 60]
    assert [row['paid_on'] for row in evidence['invoice_components']['IV-1']] == ['2026-09-10', '2026-09-20']
    assert [row['channel'] for row in evidence['invoice_components']['IV-1']] == ['Bank A', 'Bank B']
    assert evidence['limitations'][0]['before'] == '2026-01-01'
    assert payment_claims.reconcile_receipts(data[0], data[1]) == before


def test_read_dto_does_not_deduplicate_legitimate_identical_components():
    data = inputs([{'on': '2026-09-20', 'amount': '40', 'channel': 'Bank A'},
                   {'on': '2026-09-20', 'amount': '40', 'channel': 'Bank A'}], snapshot=None)
    data[0][0]['outstanding'] = '100'
    evidence = financial_evidence.build(*data)
    parts = evidence['invoice_components']['IV-1']
    assert len(parts) == 2 and sum(float(row['allocated_amount']) for row in parts) == 80
    assert parts[0]['uid'] != parts[1]['uid']


def test_cancelled_components_remain_visible_and_have_no_current_allocation():
    evidence = financial_evidence.build(*inputs([{'on': '2026-09-10', 'amount': '40', 'channel': 'Bank A'}], status='CANCELLED'))
    part = evidence['invoice_components']['IV-1'][0]
    assert part['status'] == 'CANCELLED' and part['allocated_amount'] is None
    assert evidence['receipts'][0]['payment_groups'] == []


def test_read_dto_exposes_signed_parts_and_same_date_net_allocations_without_cross_date_netting():
    data = inputs([{'on': '2026-09-10', 'amount': '50', 'channel': 'Bank A'},
                   {'on': '2026-09-10', 'amount': '-10', 'channel': 'Adjustment'},
                   {'on': '2026-09-20', 'amount': '60', 'channel': 'Bank B'}])
    evidence = financial_evidence.build(*data)
    parts = evidence['receipts'][0]['components']
    assert len(parts) == 3 and parts[1]['is_adjustment']
    groups = evidence['receipts'][0]['payment_groups']
    assert [group['net_received'] for group in groups] == ['40.00', '60.00']
    assert groups[0]['component_indices'] == [0, 1]
    assert groups[1]['component_indices'] == [2]


def test_publication_partitions_customers_without_replaying_the_whole_book_per_customer(monkeypatch):
    first = inputs([{'on': '2026-09-20', 'amount': '40', 'channel': 'Bank A'}], snapshot=None)
    second_invoices = [{**first[0][0], 'doc_no': 'IV-2', 'customer_uid': 'C2', 'customer_no': 'C2'}]
    second_receipts = [{**first[1][0], 'doc_no': 'RE-2', 'invoice_ref': 'IV-2', 'customer_uid': 'C2', 'customer_no': 'C2'}]
    output = {'component_allocations': [
        {'receipt_doc_no': 'RE-1', 'invoice_doc_no': 'IV-1', 'customer_uid': 'C1', 'amount': '40.00', 'paid_on': '2026-09-20', 'component_index': 0},
        {'receipt_doc_no': 'RE-2', 'invoice_doc_no': 'IV-2', 'customer_uid': 'C2', 'amount': '40.00', 'paid_on': '2026-09-20', 'component_index': 0},
    ]}
    def forbidden_replay(*_args, **_kwargs):
        raise AssertionError('Published traces must not replay the book per customer')
    monkeypatch.setattr(payment_claims, 'reconcile_receipts', forbidden_replay)
    payloads = dict(financial_evidence.customer_payloads(
        {'invoices': first[0] + second_invoices, 'receipts': first[1] + second_receipts}, output, first[2], first[3]))
    assert set(payloads) == {'C1', 'C2'}
    assert set(payloads['C1']['invoice_components']) == {'IV-1'}
    assert set(payloads['C2']['invoice_components']) == {'IV-2'}
    assert payloads['C1']['receipts'][0]['doc_no'] == 'RE-1'
    assert payloads['C2']['receipts'][0]['doc_no'] == 'RE-2'


def test_indexed_latest_read_does_not_fetch_or_scan_book_wide_json(monkeypatch):
    class Result:
        def __init__(self, value): self.value = value
        def scalar(self): return self.value
        def mappings(self): return self
        def first(self): return self.value
    class Connection:
        def execute(self, statement, _params=None):
            query = str(statement)
            assert 'jsonb_path_query' not in query
            if 'to_regclass' in query: return Result(True)
            return Result({'sequence': 7, 'payload': {'read_only': True, 'customer': 'C1'}, 'published': True})
        def close(self): pass
    monkeypatch.setattr(db, 'configured', lambda: True)
    monkeypatch.setattr(db, 'connect', lambda: Connection())
    assert financial_evidence.for_customer('C1') == {'read_only': True, 'customer': 'C1'}


def test_indexed_customer_publication_is_atomic_idempotent_and_case_scoped(pg_conn, pg_url, monkeypatch):
    from sqlalchemy import event
    from app import migrate
    migrate.apply(pg_conn)
    pg_conn.execute(text('create table if not exists records.customer_payment_evidence ('
        'sequence bigint not null references records.payment_reconciliation_version(sequence),'
        'customer_uid text not null,payload jsonb not null,primary key(sequence,customer_uid))'))
    data = inputs([{'on': '2026-09-20', 'amount': '40', 'channel': 'Bank A'}], snapshot=None)
    data[0][0]['outstanding'] = '100'
    output = {'component_allocations': [{'receipt_doc_no': 'RE-1', 'invoice_doc_no': 'IV-1',
        'customer_uid': 'C1', 'amount': '40.00', 'paid_on': '2026-09-20', 'component_index': 0}]}
    import json
    version_inputs = {'invoices': data[0], 'receipts': data[1]}
    sequence = pg_conn.execute(text('insert into records.payment_reconciliation_version(reason,inputs,outputs) '
        "values('SYNTHETIC_READ',cast(:inputs as jsonb),cast(:outputs as jsonb)) returning sequence"),
        {'inputs': json.dumps(version_inputs), 'outputs': json.dumps(output)}).scalar()
    assert financial_evidence.publish(pg_conn, sequence, version_inputs, output)['customers'] == 1
    assert financial_evidence.publish(pg_conn, sequence, version_inputs, output)['customers'] == 1
    assert pg_conn.execute(text('select count(*) from records.customer_payment_evidence where sequence=:seq'), {'seq': sequence}).scalar() == 1
    pg_conn.commit()
    engine = create_engine(pg_url, future=True, hide_parameters=True)
    monkeypatch.setenv('DATABASE_URL', pg_url)
    monkeypatch.setattr(db, '_engine', engine)
    def no_book_blob(_conn, _cursor, statement, _params, _ctx, _many):
        assert 'jsonb_path_query' not in statement
    event.listen(engine, 'before_cursor_execute', no_book_blob)
    try:
        evidence = financial_evidence.for_customer('C1')
        assert evidence['receipts'][0]['doc_no'] == 'RE-1'
        assert financial_evidence.for_customer('C2') is None
    finally:
        event.remove(engine, 'before_cursor_execute', no_book_blob)
        engine.dispose()
        pg_conn.execute(text('truncate records.payment_reconciliation_version restart identity cascade'))
        pg_conn.commit()


@pytest.mark.parametrize('parts', [
    [{'on': '2026-09-10', 'amount': '40.00', 'channel': 'Bank A'},
     {'on': '2026-09-20', 'amount': '60.00', 'channel': 'Bank B'}],
    [{'on': '2026-09-20', 'amount': '40.00', 'channel': 'Bank A'},
     {'on': '2026-09-20', 'amount': '40.00', 'channel': 'Bank A'}],
])
def test_database_book_journey_and_case_keep_component_dates_and_cash(pg_conn, pg_url, monkeypatch, parts):
    from app import journey, main, migrate, service_deferrals
    from app.fixtures import ContractFixture
    from app.pipelines import peak_writer
    from tests.test_peak_writer import _inv, _parsed
    migrate.apply(pg_conn)
    pg_conn.commit()
    engine = create_engine(pg_url, future=True, hide_parameters=True)
    monkeypatch.setenv('DATABASE_URL', pg_url)
    monkeypatch.setattr(db, '_engine', engine)
    customer = main.CUSTOMERS[0]
    contract = ContractFixture('K-COMPONENT-READ', customer.uid, 'LEASE', Decimal('100'), 1,
                               date(2026, 9, 1)).build()
    customer.contracts = [contract]
    monkeypatch.setattr(journey, 'book_customers', lambda: [customer])
    monkeypatch.setattr(journey, 'identity_customers', lambda: [])
    monkeypatch.setattr(service_deferrals, 'records', lambda: [])
    no = str(customer.customer_no)
    exact = {'verdict': 'EXACT', 'rule': 'CUSTOMER_NO', 'customer_no': no, 'candidates': []}
    snapshot = '60.00' if parts[0]['on'] < '2026-09-14' else '100.00'
    invoice = _inv('IV-COMPONENT', no, status='AWAITING', awaiting=snapshot)
    invoice.update(amount_due='100.00', amount_total='100.00')
    run = peak_writer.write(pg_conn, _parsed(invoice), [exact])
    peak_writer.apply_run(pg_conn, run['run_id'], 'Synthetic Manager')
    total = str(sum(Decimal(part['amount']) for part in parts))
    receipt = {'doc_no': 'RE-COMPONENT', 'doc_kind': 'RE', 'issued_on': '2026-09-30',
               'invoice_ref': 'IV-COMPONENT', 'contact_code': no, 'status': 'PAID',
               'amount_total': total, 'amount_due': total, 'paid_amount': total, 'paid_on': parts[-1]['on'],
               'payments': parts, 'lines': []}
    receipt_verdict = {**exact, 'invoice_doc_no': 'IV-COMPONENT'}
    receipt_run = peak_writer.write_receipts(pg_conn, {'receipts': [receipt], 'meta': {
        'report_as_of': '2026-09-30', 'exported_at': '2026-09-30T16:50:15', 'read': 2}}, [receipt_verdict],
        filename='receipt_company_export_as_of_20260101_20261231_20260930_165015.xlsx')
    peak_writer.apply_receipt_run(pg_conn, receipt_run['run_id'], 'Synthetic Manager')
    payment_claims.reconcile_applied(pg_conn, receipt_run['run_id'])
    pg_conn.commit()
    try:
        book = peak_writer.invoices_for_book(pg_conn)[no]
        payments = book['invoices'][0]['payments']
        assert len(payments) == 2
        assert [payment['on'] for payment in payments] == [part['on'] for part in parts]
        assert sum(Decimal(payment['amount']) for payment in payments) == Decimal(total)
        state = journey.JourneyState()
        journey._seed_peak_invoices(state, customer, book, date(2026, 10, 23))
        assert len(state.receipts) == 2
        assert sum(Decimal(receipt['amount']) for receipt in state.receipts.values()) == Decimal(total)
        _, invoices, _, _ = payment_claims.decorate(customer.uid, {'payment_status': 'CURRENT'}, list(state.invoices.values()))
        assert len(invoices[0]['payment_components']) == 2
        assert [row['paid_on'] for row in invoices[0]['payment_components']] == [part['on'] for part in parts]
        assert sum(Decimal(row['allocated_amount']) for row in invoices[0]['payment_components']) == Decimal(total)
    finally:
        if pg_conn.in_transaction():
            pg_conn.rollback()
        pg_conn.execute(text('truncate records.payment_reconciliation_version, records.payment_allocation, records.payment_reconciliation_exception restart identity cascade'))
        pg_conn.commit()
        engine.dispose()
