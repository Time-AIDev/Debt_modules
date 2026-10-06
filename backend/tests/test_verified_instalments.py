"""Calendar matching must not turn a sheet assumption into payment evidence."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import main, payment_summary
from app.fixtures import ContractFixture
import pytest


@pytest.fixture(autouse=True)
def isolate_confirmations():
    from app import schedule_confirmation
    schedule_confirmation._MEMORY.clear()
    yield
    schedule_confirmation._MEMORY.clear()


def contract(confirmed=True):
    k = ContractFixture('K-calendar', 'cu-calendar', 'LEASE', Decimal('1000'), 3,
                        date(2025, 10, 10), paid_through=2).build()
    k.sheet_row = {'first_payment_date': '2025-02-10'}
    k.requires_schedule_confirmation = True
    k.schedule_confirmation = ({'first_due': '2025-10-10', 'document_ref': 'contract.pdf',
                                'reason': 'Checked signed schedule', 'confirmed_by': 'Manager'}
                               if confirmed else None)
    main.BY_CONTRACT[k.uid] = (SimpleNamespace(contracts=[k]), k)
    return k


def invoice(uid='pk-1', **changes):
    return {'uid': uid, 'contract_uid': 'K-calendar', 'source': 'PEAK_REPORT',
            'state': 'PAID', 'amount': '100.00', 'outstanding': '0.00',
            'due_date': '2025-10-25', 'issued_on': '2025-10-01',
            'month_index': 1, 'contract_resolved': True, 'peak_number': uid, **changes}


def test_inferred_paid_cycles_do_not_count_as_confirmed_money():
    entry = payment_summary.for_contract(contract(False), date(2025, 12, 20), Decimal('100'))
    assert entry['paid_amount'] == '0.00'
    assert entry['counts']['PAID'] == 0
    assert entry['cycles'][0]['payment_evidence'] == 'INFERRED_PAID'
    assert entry['review_amount'] != '0.00'


def test_peak_matches_imported_schedule_without_manual_confirmation():
    k = contract(False)
    cycles, unplaced, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={'a': invoice()}))
    assert set(cycles) == {1}
    assert unplaced == 0


def test_peak_uses_calendar_date_and_keeps_actual_due_date():
    k = contract()
    cycles, unplaced, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={'a': invoice()}))
    entry = payment_summary.for_contract(k, date(2025, 12, 20), Decimal('100'), peak_cycles=cycles)
    assert unplaced == 0
    assert entry['cycles'][0]['due_date'] == '2025-10-25'
    assert entry['cycles'][0]['schedule_due_date'] == '2025-10-10'
    assert entry['cycles'][0]['payment_evidence'] == 'CONFIRMED'


def test_peak_cycle_number_conflict_is_not_silently_placed():
    k = contract()
    cycles, unplaced, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={'a': invoice(month_index=17)}))
    assert cycles == {}
    assert unplaced == 1


def test_multiple_invoices_in_one_month_are_all_kept_and_totalled():
    k = contract()
    cycles, unplaced, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={
        'a': invoice(), 'b': invoice('pk-2', state='PARTIALLY_PAID', amount='80.00', outstanding='30.00')}))
    assert unplaced == 0
    assert cycles[1]['paid'] == '150.00'
    assert cycles[1]['outstanding'] == '30.00'
    assert len(cycles[1]['invoices']) == 2


@pytest.mark.parametrize('reviewed_date, cycle', [('2025-10-10', 1), ('2025-02-10', 9)])
def test_danudech_october_cell_follows_reviewed_calendar_not_global_m17(reviewed_date, cycle):
    """Two hypothetical signed schedules: neither is a verification of Danudech."""
    k = contract()
    k.first_due = date.fromisoformat(reviewed_date)
    k.instalments = ContractFixture(k.uid, k.customer_uid, 'LEASE', Decimal('1000'), 48,
                                  k.first_due, paid_through=2).build().instalments
    k.schedule_confirmation['first_due'] = reviewed_date
    k.calendar_months = [{'period': '2025-10', 'header': 'M17',
                          'cell': {'kind': 'PAID', 'amount': '12323.00'},
                          'source_ref': {'sheet': 'Done - Collection', 'row': 58, 'column': 'BP'}}]
    entry = payment_summary.for_contract(k, date(2025, 12, 20), Decimal('100'))
    row = entry['cycles'][cycle - 1]
    assert row['payment_evidence'] == 'SHEET_REPORTED_PAID'
    assert row['paid'] == '0.00'
    assert row['sheet_evidence']['period'] == '2025-10'
    assert row['sheet_evidence']['header'] == 'M17'


def test_ambiguous_contract_is_not_placed_even_with_a_cycle_number():
    k = contract()
    cycles, unplaced, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={'a': invoice(contract_resolved=False)}))
    assert cycles == {}
    assert unplaced == 1


def test_same_source_invoice_seen_twice_is_not_double_counted():
    k = contract()
    cycles, _, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={'a': invoice(), 'b': invoice('copy', peak_number='pk-1')}))
    assert cycles[1]['paid'] == '100.00'
    assert len(cycles[1]['invoices']) == 1


def test_manager_can_confirm_schedule_and_officer_cannot():
    k = next(c for c in main.CUSTOMERS if c.uid.startswith("sheet-") and c.contracts[0].product == "LEASE").contracts[0]
    client = TestClient(main.app)
    body = {'first_due': '2025-10-10', 'document_ref': 'contract.pdf', 'reason': 'Checked signed contract'}
    response = client.post(f'/v1/contracts/{k.uid}/schedule-confirmation', json=body)
    assert response.status_code == 403
    response = client.post(f'/v1/contracts/{k.uid}/schedule-confirmation', json=body,
                           headers={'X-Volt-Role': 'MANAGER', 'X-Volt-Officer': 'Manager'})
    assert response.status_code == 201
    assert response.json()['confirmation']['first_due'] == '2025-10-10'
    history = client.get(f'/v1/contracts/{k.uid}/schedule-confirmation').json()['history']
    assert len(history) == 1
    assert history[0]['confirmed_by'] == 'Manager'


def test_confirmed_first_due_survives_rebuilding_imported_contract():
    from app import book, schedule_confirmation
    k = next(c for c in main.CUSTOMERS if c.uid.startswith("sheet-") and c.contracts[0].product == "LEASE").contracts[0]
    schedule_confirmation._MEMORY.clear()
    schedule_confirmation.confirm(k, {'first_due': '2025-10-10', 'document_ref': 'signed.pdf',
                                      'reason': 'signed payment schedule'}, 'Manager')
    book.invalidate()
    customers, _ = book.build()
    rebuilt = next(c for c in customers if c.uid == k.customer_uid).contracts[0]
    assert str(rebuilt.first_due) == '2025-10-10'
    assert rebuilt.schedule_confirmation['document_ref'] == 'signed.pdf'
    schedule_confirmation._MEMORY.clear()


def test_service_month_wins_over_shifted_invoice_due_month():
    k = contract()
    cycles, _, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={
        'a': invoice(due_date='2025-12-25', service_month='2025-10')}))
    assert cycles[1]['matching_method'] == 'SERVICE_MONTH'
    assert cycles[1]['due_date'] == '2025-12-25'


def test_a_valid_but_conflicting_cycle_mark_is_unplaced():
    k = contract()
    cycles, unplaced, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={
        'a': invoice(month_index=2)}))
    assert cycles == {}
    assert unplaced == 1


def test_collection_money_does_not_treat_unconfirmed_sheet_balance_as_debt():
    k = contract(False)
    _k, _dpd, _band, block, _period = main._contract_view(k)
    assert block.cumulative_arrears == Decimal('0.00')


def test_reader_preserves_calendar_header_above_m17_and_cell_location():
    from app import imports
    header = ['VOLT ID', 'Payment Status', 'Term, Original', 'M17']
    rows = [['', '', '', '2025-10-01'], header,
            ['28006752779_Danudech_ดนุเดช เลขะสันต์_VOLT', 'Late', '48', '12323']]
    kind, _, _, records, _, _ = imports._classify_sheet([], rows, 'Done - Collection', [], [2, 3, 58])
    assert kind == 'LEASING_BOOK'
    assert records[0]['calendar_months'][0]['period'] == '2025-10'
    assert records[0]['calendar_months'][0]['source_ref'] == {'sheet': 'Done - Collection', 'row': 58, 'column': 'D'}


def test_same_product_multiple_contracts_are_not_resolved_by_first_match():
    from app.journey import _peak_contract_for
    k = contract()
    customer = SimpleNamespace(contracts=[k, ContractFixture('K-other', 'cu-calendar', 'LEASE',
        Decimal('1000'), 3, date(2025, 10, 10)).build()])
    _chosen, resolved = _peak_contract_for(customer, {'product_group': 'Solar Leasing'})
    assert resolved is False


def test_peak_service_month_is_preserved_from_invoice_description():
    from app.pipelines.peak_report import _invoice, COLUMNS
    row = dict.fromkeys(COLUMNS.values(), '')
    row.update(doc_no='IV-1', status='PAID', description='Service month Oct 2025 M1/48',
               due_on='2025-12-25', amount_awaiting='0', amount_total='100', sheet_row=11)
    inv = _invoice([row])
    assert inv['service_month'] == '2025-10'


def test_confirmation_history_is_durable_and_append_only(pg_conn, monkeypatch):
    from app import migrate, db, schedule_confirmation
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    migrate.apply(pg_conn)
    pg_conn.commit()
    # Real isolated PostgreSQL transaction, never staging.
    monkeypatch.setattr(db, 'configured', lambda: True)
    monkeypatch.setattr(db, 'connect', lambda: pg_conn.engine.connect())
    k = contract(False)
    body = {'first_due': '2025-10-10', 'document_ref': 'signed.pdf', 'reason': 'checked'}
    schedule_confirmation.confirm(k, body, 'Manager')
    schedule_confirmation.confirm(k, dict(body, first_due='2025-11-10'), 'Owner')
    rows = schedule_confirmation.history(k.uid)
    assert [r['first_due'] for r in rows] == ['2025-10-10', '2025-11-10']
    with pytest.raises(DBAPIError):
        pg_conn.execute(text("update app.schedule_confirmation set contract_uid='corrupt'"))
    pg_conn.rollback()


def test_auto_matched_peak_debt_is_visible_as_confirmed_document_evidence():
    k = contract(False)
    state = SimpleNamespace(invoices={'a': invoice(state='OVERDUE', outstanding='100.00')}, receipts={})
    cycles, unplaced, _ = payment_summary.peak_cycles_for(k.uid, state)
    entry = payment_summary.for_contract(k, date(2025, 12, 20), Decimal('100'), peak_cycles=cycles)
    assert set(cycles) == {1} and unplaced == 0
    assert entry['overdue_amount'] == '100.00'
    assert entry['outstanding_amount'] == '100.00'
    assert entry['unplaced_confirmed_outstanding'] == '0.00'


def test_sheet_only_receivables_are_not_claimed_as_confirmed_in_case_detail():
    k = next(c for c in main.CUSTOMERS if c.uid.startswith('sheet-') and c.contracts[0].product == 'LEASE').contracts[0]
    data = TestClient(main.app).get('/v1/cases/by-customer/' + k.customer_uid).json()
    assert all(i.get('confirmed_paid') is None and i.get('confirmed_outstanding') is None
               for i in data['invoices'] if i.get('scenario') == 'SHEET')
    assert data['work_item']['money_position']['review_required'] is True


def test_unknown_balances_do_not_allow_a_contract_to_be_closed_as_paid():
    from app import cases
    k = contract(False)
    blocking, _ = cases.termination_gate(SimpleNamespace(contracts=[k]))
    assert blocking[0]['reason'] == 'BALANCE_REQUIRES_REVIEW'
    assert blocking[0]['payoff_amount'] is None


def test_unplaced_evidence_does_not_leak_between_sessions_on_shared_contract():
    k = contract(False)
    first, _, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={'a': invoice()}))
    second, _, _ = payment_summary.peak_cycles_for(k.uid, SimpleNamespace(invoices={}))
    one = payment_summary.for_contract(k, date(2025, 12, 20), Decimal('0'), peak_cycles=first)
    two = payment_summary.for_contract(k, date(2025, 12, 20), Decimal('0'), peak_cycles=second)
    assert one['cycles'][0]['payment_evidence'] == 'CONFIRMED'
    assert two['cycles'][0]['payment_evidence'] != 'CONFIRMED'
    assert two['unplaced_peak_details'] == []
    assert not hasattr(k, 'unplaced_peak_details')


def test_thai_service_month_buddhist_year_is_matched_to_calendar_year():
    from app.instalment_evidence import service_period
    assert service_period([{'description': 'ค่าเช่าประจำเดือน ตุลาคม 2568 M1/48'}]) == ('2025-10', False)


def test_peak_issue_month_text_is_not_used_as_a_service_period():
    from app.instalment_evidence import service_period
    assert service_period([{'description': 'Issued Oct 2025'}]) == (None, False)


def test_matching_never_labels_a_manual_receipt_as_peak_evidence():
    k = contract()
    state = SimpleNamespace(invoices={'a': invoice(source='SHEET', scenario='SHEET', state='PAID')},
        receipts={'r': {'uid': 'r', 'contract_uid': k.uid, 'invoice_uid': 'pk-1', 'matched': 'FULL', 'amount': '100'}})
    cycles, _, _ = payment_summary.peak_cycles_for(k.uid, state)
    entry = payment_summary.for_contract(k, date(2025, 12, 20), Decimal('0'), peak_cycles=cycles)
    assert entry['cycles'][0]['source'] == 'RECEIPT'


def test_manual_partial_receipt_uses_confirmed_amount_once_not_stale_sheet_balance():
    k = contract()
    receipt = {'uid': 'r', 'contract_uid': k.uid, 'invoice_uid': 'pk-1', 'matched': 'PARTIAL', 'amount': '40'}
    state = SimpleNamespace(invoices={'a': invoice(source='SHEET', state='PARTIALLY_PAID', outstanding='100.00')},
                            receipts={'r': receipt, 'duplicate': dict(receipt)})
    cycles, _, _ = payment_summary.peak_cycles_for(k.uid, state)
    assert cycles[1]['paid'] == '40.00'
    assert cycles[1]['outstanding'] == '0.00'
    assert cycles[1]['liability_verified'] is False


def test_unconfirmed_sheet_cycles_do_not_trigger_missed_payment_escalation():
    from app import journey
    k = contract(False)
    assert journey.missed_count(k, date(2025, 12, 20)) == 0


def test_unconfirmed_invoice_does_not_prefill_a_collection_demand(monkeypatch):
    from app import journey
    customer = next(c for c in main.CUSTOMERS if c.uid.startswith('sheet-') and c.contracts[0].product == 'LEASE')
    state = journey.for_current()
    state.invoices['sheet-unknown'] = {'uid': 'sheet-unknown', 'customer_uid': customer.uid,
        'contract_uid': customer.contracts[0].uid, 'source': 'SHEET', 'state': 'OVERDUE',
        'kind': 'INSTALMENT', 'due_date': '2026-09-23', 'amount': '100.00', 'outstanding': '100.00'}
    monkeypatch.setattr(journey, 'for_current', lambda: state)
    data = TestClient(main.app).get('/v1/cases/by-customer/' + customer.uid + '/invoices').json()
    assert data['invoices']
    assert all(inv['amount_to_ask'] is None for inv in data['invoices'])


def test_invoice_detail_exposes_calendar_match_and_both_dates():
    from app.instalment_evidence import annotate_invoices
    k = contract()
    rows = annotate_invoices(SimpleNamespace(contracts=[k]),
                             SimpleNamespace(invoices={'a': invoice()}), [invoice()])
    assert rows[0]['matching_method'] == 'DUE_MONTH'
    assert rows[0]['contract_cycle'] == 1
    assert rows[0]['schedule_due_date'] == '2025-10-10'
    assert rows[0]['peak_due_date'] == '2025-10-25'
    rows = annotate_invoices(SimpleNamespace(contracts=[contract(False)]),
                             SimpleNamespace(invoices={'a': invoice()}), [invoice()])
    assert rows[0]['unmatched_reason'] is None
    assert rows[0]['contract_cycle'] == 1


def test_summary_explains_that_inference_is_excluded_from_confirmed_totals():
    entry = payment_summary.for_contract(contract(False), date(2025, 12, 20), Decimal('0'))
    summary = payment_summary.build([entry], date(2025, 12, 20))
    assert entry['requires_schedule_confirmation'] is True
    assert 'excluded' in summary['provenance_en']


def test_confirmation_invalidates_cached_epoch_immediately(pg_conn, monkeypatch):
    from app import migrate, db, schedule_confirmation, data_epoch
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, 'configured', lambda: True)
    monkeypatch.setattr(db, 'connect', lambda: pg_conn.engine.connect())
    data_epoch.reset_cache()
    before = data_epoch.current()
    schedule_confirmation.confirm(contract(False), {
        'first_due': '2025-10-10', 'document_ref': 'signed.pdf', 'reason': 'checked',
    }, 'Manager')
    assert data_epoch.current() > before


def test_unknown_sheet_debt_has_an_explicit_review_band_instead_of_current_or_blank():
    from app.money.band_sets import label_for
    k = contract(False)
    arrears, dpd, band, _ = main._customer_aggregate(SimpleNamespace(contracts=[k]))
    assert arrears == Decimal('0') and dpd is None
    assert band.code == 'EVIDENCE_UNVERIFIED'
    assert label_for(band.band_set_code, band.code) == 'รอตรวจสอบยอด'


def test_unallocated_receipt_does_not_reduce_confirmed_invoice_debt():
    from app.instalment_evidence import evidence_invoices
    receipt = {'uid': 'rc-1', 'contract_uid': 'K-calendar', 'invoice_uid': 'pk-1',
               'ref': 'R1', 'amount': '100.00', 'matched': 'FULL', 'source': 'SLIP',
               'is_allocated': False}
    state = SimpleNamespace(invoices={'a': invoice(state='OVERDUE', outstanding='100.00')},
                            receipts={'r': receipt})
    assert evidence_invoices('K-calendar', state)[0]['outstanding'] == '100.00'


def test_receipt_against_a_sheet_invoice_does_not_verify_its_remaining_liability():
    from app.instalment_evidence import collection_lines
    k = contract()
    state = SimpleNamespace(invoices={'a': invoice(source='SHEET', state='OVERDUE', outstanding='100.00')},
        receipts={'r': {'uid': 'r', 'contract_uid': k.uid, 'invoice_uid': 'pk-1', 'matched': 'PARTIAL',
                        'source': 'SLIP', 'amount': '40'}})
    assert collection_lines(k, state, k.instalments) == []
    cycles, _, _ = payment_summary.peak_cycles_for(k.uid, state)
    entry = payment_summary.for_contract(k, date(2025, 12, 20), Decimal('0'), peak_cycles=cycles)
    assert entry['paid_amount'] == '40.00'
    assert entry['outstanding_amount'] == '0.00'
    assert entry['counts']['PAID'] == 0
    assert entry['review_amount'] != '0.00'


def test_manual_receipt_annotation_uses_its_evidence_period_and_keeps_balance_unknown():
    from app.instalment_evidence import annotate_invoices
    from app import payment_claims
    k = contract()
    original = invoice(source='SHEET', state='OVERDUE', month_index=17, outstanding='100.00')
    state = SimpleNamespace(invoices={'a': original}, receipts={'r': {'uid': 'r',
        'contract_uid': k.uid, 'invoice_uid': 'pk-1', 'matched': 'PARTIAL', 'source': 'SLIP', 'amount': '40'}})
    rows = annotate_invoices(SimpleNamespace(contracts=[k]), state, [original])
    assert rows[0]['matching_method'] == 'DUE_MONTH'
    assert rows[0]['evidence_source'] == 'RECEIPT'
    assert rows[0]['liability_verified'] is False
    _, rows, _, _ = payment_claims.decorate(k.customer_uid, {}, rows)
    assert rows[0]['confirmed_paid'] == '40.00'
    assert rows[0]['confirmed_outstanding'] is None


def test_confirmed_peak_invoice_detail_uses_the_same_receipt_adjustment_as_summary():
    from app.instalment_evidence import annotate_invoices
    from app import payment_claims
    k = contract()
    original = invoice(state='OVERDUE', outstanding='100.00')
    state = SimpleNamespace(invoices={'a': original}, receipts={'r': {'uid': 'r',
        'contract_uid': k.uid, 'invoice_uid': 'pk-1', 'matched': 'PARTIAL', 'source': 'SLIP',
        'amount': '40', 'is_allocated': True}})
    rows = annotate_invoices(SimpleNamespace(contracts=[k]), state, [original])
    _, rows, _, _ = payment_claims.decorate(k.customer_uid, {}, rows)
    assert rows[0]['confirmed_paid'] == '40.00'
    assert rows[0]['confirmed_outstanding'] == '60.00'


def test_confirmation_does_not_succeed_for_a_format_that_cannot_apply_the_date():
    k = next(c for c in main.CUSTOMERS if c.uid.startswith('sheet-')
             and c.contracts[0].product == 'CASH').contracts[0]
    client = TestClient(main.app)
    response = client.post(f'/v1/contracts/{k.uid}/schedule-confirmation',
        json={'first_due': '2025-10-10', 'document_ref': 'cash.pdf', 'reason': 'checked'},
        headers={'X-Volt-Role': 'MANAGER'})
    assert response.status_code == 422
    assert client.get(f'/v1/contracts/{k.uid}/schedule-confirmation').json()['history'] == []


def test_peak_without_due_date_does_not_invent_one_or_break_next_due():
    k = contract()
    jstate = SimpleNamespace(invoices={'a': invoice(state='SENT', outstanding='100.00',
                                                   due_date=None, service_month='2025-10')})
    cycles, _, _ = payment_summary.peak_cycles_for(k.uid, jstate)
    entry = payment_summary.for_contract(k, date(2025, 9, 20), Decimal('0'), peak_cycles=cycles)
    assert entry['cycles'][0]['due_date'] is None
    assert entry['cycles'][0]['schedule_due_date'] == '2025-10-10'
    assert entry['next_due']['n'] == 3
