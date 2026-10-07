"""Wire reuse preserves business bytes, visibility and fresh security boundaries."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace

import pytest
from starlette.responses import Response
from sqlalchemy import text

from app import main, projection_wire, read_projection
from app.production_unit import CURRENT
from app.routers.today import _json, today
from .test_capacity_projection import capacity as _capacity_fixture, generation, projected, unit
from .test_production_http import production as _production_fixture

capacity = _capacity_fixture
production = _production_fixture


@pytest.fixture(autouse=True)
def empty_wire_cache():
    projection_wire._CACHE.clear()
    yield
    projection_wire._CACHE.clear()


def test_same_key_reuses_exact_full_body_and_recreates_headers():
    cache = projection_wire.BodyCache()
    rows = [{'customer': {'uid': 'synthetic-%d' % i}, 'amount': '100.00'} for i in range(500)]
    builds = []
    def build():
        builds.append(True)
        response = _json({'items': rows, 'meta': {'total': 500}})
        response.headers['set-cookie'] = 'private-per-request'
        return response
    first, second = cache.body(('database', 1), build), cache.body(('database', 1), build)
    assert first == second and len(builds) == 1
    parsed = json.loads(second)
    assert parsed['items'] == rows and parsed['meta']['total'] == 500
    assert b'private-per-request' not in second


def test_body_budget_evicts_old_entries_and_oversize_is_returned_whole_without_caching():
    cache = projection_wire.BodyCache(max_bytes=6, max_entries=2)
    def build():
        return Response(b'1234', media_type='application/json')
    assert cache.body(('one',), build) == b'1234'
    assert cache.body(('two',), build) == b'1234' and cache.bytes == 4
    calls = []
    def oversized():
        calls.append(True)
        return Response(b'1234567890', media_type='application/json')
    assert cache.body(('big',), oversized) == cache.body(('big',), oversized) == b'1234567890'
    assert len(calls) == 2 and cache.bytes <= 6


def test_same_key_singleflight_different_keys_parallel_and_failed_build_can_retry():
    cache = projection_wire.BodyCache()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow():
        calls.append(True)
        entered.set()
        assert release.wait(2)
        return _json({'amount': '100.00'})
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(cache.body, ('same',), slow)
        assert entered.wait(2)
        second = pool.submit(cache.body, ('same',), slow)
        other = pool.submit(cache.body, ('other',), lambda: _json({'amount': '200.00'}))
        try:
            assert other.result(timeout=1) == b'{"amount":"200.00"}'
        finally:
            release.set()
        assert first.result(timeout=2) == second.result(timeout=2) and len(calls) == 1
    with pytest.raises(RuntimeError):
        cache.body(('failed',), lambda: (_ for _ in ()).throw(RuntimeError('Synthetic failure')))
    assert cache.body(('failed',), lambda: _json({'recovered': True})) == b'{"recovered":true}'


def test_code_epoch_day_order_filter_sort_and_database_are_distinct():
    pointer = {'generation': 1, 'ordering_version': 1, 'source_epoch': 1, 'business_date': '2026-10-23',
               'metadata': {'code_fingerprint': 'a' * 64}}
    conn = SimpleNamespace(engine=object())
    calls = []
    def build():
        calls.append(True)
        return _json({'all_rows': True})
    first = projection_wire.today_response(conn, pointer, {}, 'priority', build)
    first.headers['x-private'] = 'first-request'
    second = projection_wire.today_response(conn, pointer, {}, 'priority', build)
    assert second.body == first.body and 'x-private' not in second.headers and len(calls) == 1
    for name in ('generation', 'ordering_version', 'source_epoch', 'business_date', 'code'):
        changed = deepcopy(pointer)
        if name == 'code':
            changed['metadata']['code_fingerprint'] = 'b' * 64
        elif name == 'business_date':
            changed[name] = '2026-10-24'
        else:
            changed[name] += 1
        projection_wire.today_response(conn, changed, {}, 'priority', build)
    projection_wire.today_response(conn, pointer, {'entity': 'EPC'}, 'priority', build)
    projection_wire.today_response(conn, pointer, {}, 'arrears', build)
    projection_wire.today_response(SimpleNamespace(engine=object()), pointer, {}, 'priority', build)
    assert len(calls) == 9


def test_uncommitted_mutation_never_poison_shared_order_version_cache():
    pointer = {'generation': 1, 'ordering_version': 1, 'source_epoch': 1, 'business_date': '2026-10-23',
               'metadata': {'code_fingerprint': 'a' * 64}}
    conn = SimpleNamespace(engine=object())
    token = CURRENT.set({'mutation': True})
    try:
        assert projection_wire.today_response(conn, pointer, {}, 'priority', lambda: _json({'amount': '0.00'})).body == b'{"amount":"0.00"}'
    finally:
        CURRENT.reset(token)
    assert projection_wire.today_response(conn, pointer, {}, 'priority', lambda: _json({'amount': '100.00'})).body == b'{"amount":"100.00"}'


def test_indexed_today_hit_skips_payload_materialization_but_paged_always_builds(capacity, monkeypatch):
    generation(capacity, [projected('synthetic-%d' % i, overdue=100) for i in range(500)])
    capacity.execute(text("update app.projection_generation set metadata=metadata||jsonb_build_object('code_fingerprint',cast(:f as text))"),
                     {'f': read_projection.code_fingerprint()})
    original, builds = read_projection.today, []
    def counted(*args, **kwargs):
        builds.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(read_projection, 'today', counted)
    options = dict(officer=None, ladder_indicative=None, tier=None, payment_status=None, dc_status=None,
                   product=None, entity=None, q=None, unassigned=None, limit=None, cursor=None,
                   sort='priority', x_volt_role='OWNER', x_volt_officer='owner')
    with unit(capacity):
        first = today(**options)
        second = today(**options)
        assert first.body == second.body and len(builds) == 1
        result = json.loads(second.body)
        assert len(result['items']) == result['meta']['total'] == 500
        assert sum(result['meta']['counts_by_tier'].values()) == 500
        today(**dict(options, limit=50))
        today(**dict(options, limit=50))
        assert len(builds) == 3
        capacity.execute(text('update app.projection_current set ordering_version=ordering_version+1 where singleton'))
        changed = today(**options)
        assert changed.body == first.body and len(builds) == 4


def test_source_publication_retains_legacy_bytes_and_refreshes_after_scope_write(capacity):
    with unit(capacity):
        read_projection.rebuild(capacity)
        pointer = read_projection.current(capacity)
        expected = _json(read_projection.today({})).body
        actual = projection_wire.today_response(capacity, pointer, {}, 'priority', lambda: _json(read_projection.today({}))).body
        assert actual == expected
        # A real change to the case follow-up alters Today, advances its shared
        # ordering version and therefore cannot return the old body.
        from app import cases
        customer = main.CUSTOMERS[0]
        state = cases.for_current()
        state.cases[customer.uid]['next_action'] = 'CALLBACK'
        state.cases[customer.uid]['next_action_on'] = '2026-10-24'
        read_projection.refresh_customers(capacity, [customer.uid])
        newer = read_projection.current(capacity)
        assert newer['ordering_version'] > pointer['ordering_version']
        output = projection_wire.today_response(capacity, newer, {}, 'priority', lambda: _json(read_projection.today({}))).body
        assert output == _json(read_projection.today({})).body
        assert output != actual


def test_cached_today_does_not_bypass_new_role_or_disabled_account(production):
    from app import db
    api, headers = production
    owner = headers('owner@volt.co.th', 'OWNER', 'owner')
    first = api.get('/api/v1/today', headers=owner)
    assert first.status_code == 200
    second = api.get('/api/v1/today', headers=owner)
    assert second.status_code == 200 and second.content == first.content
    spoofed = api.get('/api/v1/today', headers={**owner, 'X-Volt-Role': 'MANAGER'})
    assert spoofed.status_code == 200 and spoofed.content == first.content
    identity = api.get('/api/v1/auth/me', headers={**owner, 'X-Volt-Role': 'MANAGER'})
    assert identity.status_code == 200 and identity.json()['role'] == 'OWNER'
    officer = headers('thip@volt.co.th', 'OFFICER', 'thip')
    assert api.get('/api/v1/today', headers=officer).status_code == 503
    with db.connect() as conn, conn.begin():
        conn.execute(text("insert into records.user_account(kind,email,role,officer,disabled_at) "
            "values('GOOGLE','owner@volt.co.th','OWNER','owner',now())"))
    try:
        disabled = api.get('/api/v1/today', headers=owner)
        assert disabled.status_code == 401
    finally:
        with db.connect() as conn, conn.begin():
            conn.execute(text("delete from records.user_account where email='owner@volt.co.th'"))
