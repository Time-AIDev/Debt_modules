"""Rollback-compatible Today keeps complete totals and bounded, stale-safe pages."""
import copy

import pytest
from fastapi.testclient import TestClient

from app import errors, today_pagination
from app.main import app
from app.production_unit import CURRENT


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize('entity', [None, 'SPV', 'EPC'])
@pytest.mark.parametrize('sort', ['priority', 'arrears'])
def test_compatible_pages_preserve_full_order_totals_and_financial_rows(client, entity, sort):
    query = {'sort': sort, **({'entity': entity} if entity else {})}
    full_response = client.get('/v1/today', params=query)
    assert full_response.status_code == 200
    full = full_response.json()
    assert 'page' not in full
    seen, cursor = [], None
    while True:
        response = client.get('/v1/today', params={**query, 'limit': 7, **({'cursor': cursor} if cursor else {})})
        assert response.status_code == 200, response.json()
        value = response.json()
        assert value['meta'] == full['meta']
        assert value['page']['returned'] == len(value['items']) <= 7
        seen.extend(value['items'])
        cursor = value['page']['next_cursor']
        if not value['page']['has_more']:
            assert cursor is None
            break
        assert cursor
    assert seen == full['items']
    assert len({row['customer']['uid'] for row in seen}) == len(seen)
    assert full['meta']['pending_unworked_count'] == sum(
        not row['worked_today'] and row['case']['payment_status'] == 'PENDING' for row in seen)
    assert sum(full['meta']['unworked_tier_counts'].values()) == sum(
        not row['worked_today'] and row['case']['payment_status'] != 'PENDING' for row in seen)


@pytest.mark.parametrize('change', ['version', 'subject', 'date', 'filter', 'sort', 'rows'])
def test_compatible_cursor_rejects_changed_view_instead_of_skipping_customers(change):
    data = {'items': [{'customer': {'uid': 'a'}}, {'customer': {'uid': 'b'}}], 'meta': {'total': 2}}
    state = {'version': 1, 'subject': 'owner-a'}
    if change == 'rows':
        state.pop('version')
    token = CURRENT.set(state)
    try:
        first = today_pagination.page(data, {'entity': 'SPV'}, 'priority', 1, None, '2026-10-07')
        cursor = first['page']['next_cursor']
        updated = copy.deepcopy(data)
        filters, sort, day = {'entity': 'SPV'}, 'priority', '2026-10-07'
        if change == 'version': state['version'] += 1
        if change == 'subject': state['subject'] = 'owner-b'
        if change == 'date': day = '2026-10-08'
        if change == 'filter': filters['entity'] = 'EPC'
        if change == 'sort': sort = 'arrears'
        if change == 'rows': updated['items'][0]['customer']['uid'] = 'changed'
        with pytest.raises(errors.Problem) as raised:
            today_pagination.page(updated, filters, sort, 1, cursor, day)
        assert raised.value.code == 'today_cursor_stale'
    finally:
        CURRENT.reset(token)


def test_compatible_cursor_requires_a_page_and_refuses_malformed_tokens(client):
    assert client.get('/v1/today', params={'cursor': 'bad'}).status_code == 422
    response = client.get('/v1/today', params={'limit': 1, 'cursor': 'bad'})
    assert response.status_code == 422 and response.json()['code'] == 'today_cursor_invalid'
