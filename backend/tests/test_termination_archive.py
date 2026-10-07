"""Regression contract for the shared, immutable terminated-case register."""
import pytest
from fastapi.testclient import TestClient
from app import cases, journey
from app.main import app
client = TestClient(app)
@pytest.fixture(autouse=True)
def isolated_archive(tmp_path, monkeypatch):
    monkeypatch.setenv('TERMINATION_ARCHIVE_PATH', str(tmp_path / 'archive.sqlite3'))
    client.cookies.clear()
    client.cookies.set('volt_session', 'shared')
def target():
    return next(c for c in cases.for_current().cases.values() if c['customer_no'] == 'C-002032')['customer_uid']

def active_recovery(customer_uid, strategy, recovery_uid):
    state = journey.for_current()
    contract = journey.customer_by_uid(customer_uid).contracts[0]
    rec = journey.make_recovery(state, 'PAYMENT_STATUS:' + customer_uid, contract.uid, strategy, contract.entity)
    state.recovery_cases.pop(rec['uid'])
    rec.update(uid=recovery_uid, customer_uid=customer_uid)
    state.recovery_cases[recovery_uid] = rec
    return rec

def end(monkeypatch):
    monkeypatch.setattr(cases, 'termination_gate', lambda customer: ([], []))
    uid = target()
    response = client.post('/v1/cases/by-customer/%s:terminate' % uid, headers={'X-Volt-Role': 'MANAGER', 'X-Volt-Officer': 'ploy'}, json={'cause': 'DEFAULT', 'reason': 'บรรทัดหนึ่ง\nบรรทัดสอง'})
    assert response.status_code == 200, response.text
    return uid

def test_shared_immutable_snapshot_and_audit_link(monkeypatch):
    uid = end(monkeypatch)
    listing = client.get('/v1/terminated-customers', params={'q': uid})
    assert listing.status_code == 200
    row = listing.json()['entries'][0]
    assert row['reason'] == 'บรรทัดหนึ่ง\nบรรทัดสอง'
    archived = client.get('/v1/terminated-customers/' + row['archive_uid']).json()
    assert archived['snapshot']['case']['payment_status'] == 'TERMINATED'
    assert archived['read_only'] is True
    cases.for_current().cases[uid]['dc_status'] = 'CHANGED'
    assert client.get('/v1/terminated-customers/' + row['archive_uid']).json() == archived
    other = client.get('/v1/terminated-customers', headers={'Cookie': 'volt_session=another'}, params={'q': uid})
    assert other.json()['entries'] == listing.json()['entries']
    audit = client.get('/v1/audit', params={'act': 'CONTRACT_TERMINATED'}).json()['entries'][0]
    assert audit['display']['case_url'] == '/terminated/' + row['archive_uid']


def test_officer_unpaid_termination_preserves_balance_in_immutable_snapshot():
    uid = target()
    before = client.get('/v1/cases/by-customer/' + uid).json()
    balance = before['work_item']['contract_outstanding']
    assert float(balance) > 0
    response = client.post('/v1/cases/by-customer/%s:terminate' % uid,
                           headers={'X-Volt-Role': 'OFFICER', 'X-Volt-Officer': 'thip'},
                           json={'cause': 'DEFAULT', 'reason': 'เหตุผลที่บันทึก\nบรรทัดสอง'})
    assert response.status_code == 200, response.text
    listing = client.get('/v1/terminated-customers', params={'q': uid}).json()['entries']
    assert len(listing) == 1
    archived = client.get('/v1/terminated-customers/' + listing[0]['archive_uid']).json()
    assert archived['actor'] == 'thip'
    assert archived['reason'] == 'เหตุผลที่บันทึก\nบรรทัดสอง'
    assert archived['snapshot']['work_item']['contract_outstanding'] == balance
    assert archived['snapshot']['invoices'] == before['invoices']
    assert archived['snapshot']['receipts'] == before['receipts']
    assert client.get('/v1/cases/by-customer/' + uid).json()['work_item']['contract_outstanding'] == balance
    assert client.get('/v1/terminated-customers/' + listing[0]['archive_uid']).json() == archived


def test_route_ends_all_live_contracts_with_one_customer_archive():
    import copy
    from app import main
    uid = target()
    customer = journey.customer_by_uid(uid)
    extra = copy.deepcopy(customer.contracts[0]); extra.uid = 'extra-route-unpaid'; extra.customer_uid = uid
    customer.contracts.append(extra); main.BY_CONTRACT[extra.uid] = (customer, extra)
    try:
        response = client.post('/v1/cases/by-customer/%s:terminate' % uid,
                               headers={'X-Volt-Role': 'SUPERVISOR', 'X-Volt-Officer': 'settasak'},
                               json={'cause': 'DEFAULT', 'reason': 'สองสัญญายังมียอด'})
        assert response.status_code == 200, response.text
        rows = client.get('/v1/terminated-customers', params={'q': uid}).json()['entries']
        assert len(rows) == 1
        assert {t['contract_uid'] for t in rows[0]['terminations']} == {customer.contracts[0].uid, extra.uid}
        assert all(cases.contract_field_of(k, 'status') == 'TERMINATED' for k in customer.contracts)
    finally:
        customer.contracts.remove(extra); main.BY_CONTRACT.pop(extra.uid, None)

def test_archive_write_failure_rolls_back_termination(monkeypatch):
    from app import termination_archive
    uid = target()
    contract = journey.customer_by_uid(uid).contracts[0]
    original = cases.contract_field_of(contract, 'status')
    monkeypatch.setattr(cases, 'termination_gate', lambda customer: ([], []))
    monkeypatch.setattr(termination_archive, 'save', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('offline')))
    response = client.post('/v1/cases/by-customer/%s:terminate' % uid, headers={'X-Volt-Role': 'MANAGER'}, json={'cause': 'DEFAULT', 'reason': 'why'})
    assert response.status_code == 503
    assert cases.contract_field_of(contract, 'status') == original

def test_backfill_idempotent_and_missing_evidence():
    from app import termination_archive
    uid = target()
    customer = journey.customer_by_uid(uid)
    cases._set_contract_fields(customer.contracts[0], status='TERMINATED', termination={'cause': 'DEFAULT', 'origin': 'SHEET', 'reason_th': 'นำเข้า\nครบ'})
    termination_archive.backfill_current()
    termination_archive.backfill_current()
    entries = client.get('/v1/terminated-customers', params={'q': uid}).json()['entries']
    assert len(entries) == 1
    assert entries[0]['terminated_on'] is None
    assert entries[0]['actor'] is None
    assert entries[0]['capture_kind'] == 'BACKFILL'
    assert entries[0]['reason'] == 'นำเข้า\nครบ'

@pytest.mark.parametrize('strategy,outcome,cause', [('REPOSSESSION','FULL','DEFAULT'), ('COOP_DECOMMISSION','PARTIAL','CUSTOMER_REQUEST'), ('LEGAL','CLOSED_WRITE_OFF','DEFAULT')])
def test_recovery_routes_capture_final_state(strategy, outcome, cause):
    uid = target()
    rec = active_recovery(uid, strategy, 'rec-archive')
    response = client.post('/v1/recovery-cases/rec-archive:resolve', json={'outcome': outcome, 'role': 'OWNER', 'reason': 'เหตุผลจริง'})
    assert response.status_code == 200, response.text
    row = client.get('/v1/terminated-customers', params={'q': uid}).json()['entries'][0]
    assert row['causes'] == [cause]
    assert row['reason'] == 'เหตุผลจริง'
    assert client.get('/v1/terminated-customers/' + row['archive_uid']).json()['snapshot']['case']['payment_status'] == 'TERMINATED'
    assert rec['status'] == 'RESOLVED'


def test_partial_case_shared_facts_only_archive_after_final_contract():
    import copy
    from app import main, session
    uid = target()
    customer = journey.customer_by_uid(uid)
    extra = copy.deepcopy(customer.contracts[0]); extra.uid = 'extra-archive'; extra.customer_uid = uid
    customer.contracts.append(extra); main.BY_CONTRACT[extra.uid] = (customer, extra)
    try:
        cases.record_termination(customer.contracts[0], 'DEFAULT', 'ploy', 'first', 'WRITE_OFF')
        assert client.get('/v1/terminated-customers', params={'q': uid}).json()['meta']['total'] == 0
        token = session.CURRENT.set('second-account')
        try:
            assert cases.contract_field_of(customer.contracts[0], 'status') == 'TERMINATED'
            assert cases.for_current().cases[uid]['payment_status'] != 'TERMINATED'
            cases.record_termination(extra, 'CUSTOMER_REQUEST', 'thip', 'second', 'TERMINATE_ACT')
        finally:
            session.CURRENT.reset(token)
        row = client.get('/v1/terminated-customers', params={'q': uid}).json()['entries'][0]
        assert set(row['reason'].split('\n\n')) == {'first', 'second'}
        assert len(row['terminations']) == 2
        assert cases.for_current().cases[uid]['payment_status'] == 'TERMINATED'
    finally:
        customer.contracts.remove(extra); main.BY_CONTRACT.pop(extra.uid, None)


def test_closed_excluded_filters_and_registry_survives_store_reset(monkeypatch):
    from app import termination_archive as archive
    uid = end(monkeypatch)
    row = client.get('/v1/terminated-customers', params={'q': uid}).json()['entries'][0]
    assert client.get('/v1/terminated-customers', params={'q': uid, 'cause': 'CUSTOMER_REQUEST'}).json()['meta']['total'] == 0
    assert client.get('/v1/terminated-customers', params={'q': uid, 'actor': row['actor'], 'source': 'PERSON'}).json()['meta']['total'] == 1
    cases._store._by_session.clear(); cases._fee_state_store._by_session.clear()
    assert archive.get(row['archive_uid'])['snapshot']['customer']['uid'] == uid
    assert cases.for_current().cases[uid]['payment_status'] == 'TERMINATED'
    assert client.get('/v1/terminated-customers', params={'since': 'bad'}).status_code == 422


def test_postgres_archive_restart_and_immutability(pg_url, pg_conn, monkeypatch):
    from sqlalchemy import text
    from app import db, migrate, termination_archive as archive
    migrate.apply(pg_conn); pg_conn.commit()
    monkeypatch.setenv('DATABASE_URL', pg_url)
    db.reset()
    fact = {'contract_uid': 'pg-archive-test', 'customer_uid': 'pg-customer', 'status': 'TERMINATED', 'termination': {'reason': 'one\ntwo'}}
    row = {'archive_uid': 'pg-archive', 'dedupe_key': 'pg-key', 'customer_uid': 'pg-customer', 'snapshot': {'value': 'immutable'}}
    archive.save([fact], [row]); archive.save([fact], [{**row, 'snapshot': {'value': 'changed'}}])
    db.reset()
    assert archive.get('pg-archive')['snapshot']['value'] == 'immutable'
    with pytest.raises(Exception):
        pg_conn.execute(text("update app.termination_archive set payload='{}' where uid='pg-archive'"))
    pg_conn.rollback()
    assert archive.facts()['pg-archive-test']['termination']['reason'] == 'one\ntwo'


def test_audit_enrichment_preserves_hash_and_searches_names(monkeypatch):
    from app import audit, audit_store
    uid = end(monkeypatch)
    original = audit_store.read({'act': 'CONTRACT_TERMINATED'}, limit=1, before_seq=None)[0]
    name = journey.customer_by_uid(uid).display_name
    result = client.get('/v1/audit', params={'q': name, 'outcome': 'OK', 'act': 'CONTRACT_TERMINATED'}).json()
    assert result['entries'][0]['hash'] == original['hash']
    assert audit.hash_entry(result['entries'][0], original['prev_hash']) == original['hash']
    refused = client.get('/v1/audit', params={'q': name, 'outcome': 'REFUSED', 'act': 'CONTRACT_TERMINATED'}).json()['entries']
    assert all(r['outcome'] == 'REFUSED' and r['seq'] != original['seq'] for r in refused)


def test_pagination_is_50_and_sorted_with_unknown_dates_last():
    from app import termination_archive as archive
    rows = [{'archive_uid': 'a-%03d' % i, 'customer_uid': 'cust-%03d' % i, 'customer_name': 'Customer %d' % i,
             'customer_no': 'C-%d' % i, 'actor': None, 'causes': ['DEFAULT'], 'source': 'SHEET',
             'captured_at': '2026-10-01T00:00:00Z', 'terminated_on': '2026-10-%02d' % (i % 28 + 1), 'snapshot': {}}
            for i in range(51)]
    archive.save([], rows)
    first = client.get('/v1/terminated-customers').json()
    second = client.get('/v1/terminated-customers?page=2').json()
    assert len(first['entries']) == 50 and len(second['entries']) == 1
    assert first['meta']['total'] == 51
    assert not ({r['archive_uid'] for r in first['entries']} & {r['archive_uid'] for r in second['entries']})
    dates = [r['terminated_on'] for r in first['entries'] + second['entries']]
    assert dates == sorted(dates, reverse=True)


def test_shared_commit_conflict_refuses_duplicate():
    from app import errors, termination_archive as archive
    fact = {'contract_uid': 'conflict-k', 'customer_uid': 'conflict-c', 'status': 'TERMINATED', 'termination': {}}
    archive.save([fact], [])
    with pytest.raises(errors.Problem) as exc:
        archive.save([fact], [], strict=True)
    assert exc.value.status == 409


def test_authenticated_accounts_share_archive_and_queue_status(monkeypatch, tmp_path):
    from app import auth, user_accounts
    from tests.test_auth_middleware_audit import _environ
    user_accounts.reset()
    auth.set_config(auth.load_config(_environ(), env_file=tmp_path / 'none'))
    try:
        manager = TestClient(app)
        officer = TestClient(app)
        assert manager.post('/v1/auth/password', json={'username': 'owner.test', 'password': 'owner-pw'}).status_code == 200
        assert officer.post('/v1/auth/password', json={'username': 'officer.test', 'password': 'officer-pw'}).status_code == 200
        uid = target()
        monkeypatch.setattr(cases, 'termination_gate', lambda customer: ([], []))
        response = manager.post('/v1/cases/by-customer/%s:terminate' % uid, json={'cause': 'DEFAULT', 'reason': 'same across accounts'})
        assert response.status_code == 200, response.text
        first = manager.get('/v1/terminated-customers', params={'q': uid}).json()
        second = officer.get('/v1/terminated-customers', params={'q': uid}).json()
        assert first['entries'] == second['entries'] and len(first['entries']) == 1
        archive_uid = first['entries'][0]['archive_uid']
        assert manager.get('/v1/terminated-customers/' + archive_uid).json() == officer.get('/v1/terminated-customers/' + archive_uid).json()
        assert officer.get('/v1/cases/by-customer/' + uid).json()['case']['payment_status'] == 'TERMINATED'
        assert TestClient(app).get('/v1/terminated-customers').status_code == 401
        assert officer.patch('/v1/terminated-customers/' + archive_uid, json={}).status_code in (404, 405)
    finally:
        auth.reset(); user_accounts.reset()


def test_backfill_prefers_evidenced_reason_across_accounts_without_inventing_fields():
    from app.termination_backfill import best_facts
    uid = target(); customer = journey.customer_by_uid(uid); k = customer.contracts[0]
    data = {'empty-account': {'cases.fee_state': {k.uid: {'status': 'TERMINATED', 'termination': {}}}},
            'recorded-account': {'cases.fee_state': {k.uid: {'status': 'TERMINATED', 'termination': {'reason': 'ครบ\nหลายบรรทัด', 'cause': 'DEFAULT'}}}}}
    selected = next(r for r in best_facts(data, [customer]) if r['contract_uid'] == k.uid)
    assert selected['termination'] == {'reason': 'ครบ\nหลายบรรทัด', 'cause': 'DEFAULT'}


def test_audit_search_resolves_recovery_reference_after_session_state_disappears():
    uid = target(); customer = journey.customer_by_uid(uid)
    active_recovery(uid, 'LEGAL', 'gone-recovery')
    assert client.post('/v1/recovery-cases/gone-recovery:resolve', json={'outcome': 'CLOSED_WRITE_OFF', 'role': 'OWNER', 'reason': 'proof'}).status_code == 200
    journey.for_current().recovery_cases.clear()
    result = client.get('/v1/audit', params={'q': customer.display_name, 'act': 'RECOVERY_RESOLVED'}).json()['entries']
    assert any(r['subject_uid'] == 'gone-recovery' and r['display']['case_url'].startswith('/terminated/') for r in result)
