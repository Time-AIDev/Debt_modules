import json
import time

import pytest
from sqlalchemy import text

from app import db, task_objects
from app.operational_transactions import is_upload_control
from app.production_unit import LOCK_KEY
from tests.test_production_http import production as production

UPLOAD = '11111111-1111-4111-8111-111111111111'


def scope(path, method='POST', query=b'', **extra):
    return dict(type='http', path=path, method=method, query_string=query, headers=[], **extra)


@pytest.mark.parametrize('path,query', [
    (f'/v1/imports/parts/{UPLOAD}/0', b'of=1'),
    ('/v1/imports:start', b''),
    ('/v1/imports:start', b'profile=debt_status'),
    ('/v1/imports:start', b'profile=contract_supplement&install=false'),
    ('/v1/pipelines/peak-report:start', b''),
    ('/v1/pipelines/peak-receipt:start', b''),
])
def test_upload_control_is_narrow_and_never_applies_to_worker(path, query):
    value = scope(path, query=query)
    assert is_upload_control(value)
    assert not is_upload_control(dict(value, volt_worker=True))
    assert not is_upload_control(value, worker_run=True)


@pytest.mark.parametrize('path,query', [
    ('/v1/imports:start', b'install=true'),
    ('/v1/imports:start', b'profile=debt_status&profile=contract_supplement'),
    ('/v1/imports:start', b'profile=unknown'),
    ('/v1/imports:start', b'install=false&unknown=true'),
    ('/v1/pipelines/peak-receipt/landing-runs/1:apply', b''),
    ('/v1/pipelines/peak-report/landing-runs/1:recheck', b'x=1'),
    (f'/v1/imports/parts/{UPLOAD}/0', b'of=1&of=2'),
    ('/v1/imports/parts/not-a-uuid/0', b'of=1'),
])
def test_unproved_routes_remain_business_transactions(path, query):
    assert not is_upload_control(scope(path, query=query))


@pytest.mark.parametrize('path', [
    '/v1/pipelines/peak-report/landing-runs/7:recheck',
    '/v1/pipelines/peak-receipt/landing-runs/7:recheck',
])
def test_the_landing_recheck_is_operational_and_never_applies_to_worker(path):
    # A re-check re-binds a staged run's review fence to the version that stands
    # now — landing metadata only, so it is control, like the upload transport.
    assert is_upload_control(scope(path))
    assert not is_upload_control(dict(scope(path), volt_worker=True))
    assert not is_upload_control(scope(path), worker_run=True)


@pytest.fixture
def objects(monkeypatch):
    held = {}
    monkeypatch.setattr(task_objects, 'put', lambda name, raw: held.setdefault(name, raw) and name)
    monkeypatch.setattr(task_objects, 'get', lambda name: held[name])
    return held


def test_parts_and_cleanup_do_not_wait_for_portfolio_or_move_its_version(production, objects, monkeypatch):
    api, headers = production
    monkeypatch.setenv('PROD_GO_LIVE_ENABLED', 'true')
    actor = headers('owner@volt.co.th', 'OWNER', 'owner')
    actor.update({'If-Match': '-999', 'Idempotency-Key': 'part-while-locked'})
    with db.connect() as blocker, blocker.begin():
        blocker.execute(text('select pg_advisory_xact_lock(:k)'), {'k': LOCK_KEY})
        before = blocker.execute(text('select version from app.business_version')).scalar_one()
        began = time.monotonic()
        response = api.post(f'/api/v1/imports/parts/{UPLOAD}/0?of=1', content=b'original', headers=actor)
        assert response.status_code == 200, response.text
        assert time.monotonic()-began < 3
        actor['Idempotency-Key'] = 'part-repeat'
        assert api.post(f'/api/v1/imports/parts/{UPLOAD}/0?of=1', content=b'original', headers=actor).status_code == 200
        actor['Idempotency-Key'] = 'part-changed'
        assert api.post(f'/api/v1/imports/parts/{UPLOAD}/0?of=1', content=b'changed', headers=actor).status_code == 422
        actor['Idempotency-Key'] = 'cleanup-while-locked'
        assert api.delete(f'/api/v1/imports/parts/{UPLOAD}', headers=actor).status_code == 200
        assert blocker.execute(text('select version from app.business_version')).scalar_one() == before
        assert len(objects) == 1


@pytest.mark.parametrize('path', ['/v1/imports:start', '/v1/imports:start?profile=debt_status',
                                '/v1/pipelines/peak-report:start', '/v1/pipelines/peak-receipt:start'])
def test_preview_enqueue_ignores_old_browser_version_without_global_lock(production, objects, monkeypatch, path):
    api, headers = production
    monkeypatch.setenv('PROD_GO_LIVE_ENABLED', 'true')
    actor = headers('owner@volt.co.th', 'OWNER', 'owner')
    actor.update({'If-Match': '-999', 'Content-Type': 'application/octet-stream',
                  'Idempotency-Key': 'preview-while-locked'})
    with db.connect() as blocker, blocker.begin():
        blocker.execute(text('select pg_advisory_xact_lock(:k)'), {'k': LOCK_KEY})
        before = blocker.execute(text('select version from app.business_version')).scalar_one()
        response = api.post('/api'+path, content=b'file', headers=actor)
        assert response.status_code == 202, response.text
        replay = api.post('/api'+path, content=b'file', headers=actor)
        assert replay.json() == response.json()
        assert blocker.execute(text('select version from app.business_version')).scalar_one() == before
        assert blocker.execute(text('select count(*) from app.task_outbox')).scalar_one() == 1


def test_review_fence_is_published_at_commit_and_checked_again(production, monkeypatch):
    from app import preview_review
    from app.durable_runs import WORKER_RUN
    from app.production_unit import CURRENT
    import gzip
    api, headers = production
    monkeypatch.setenv('PROD_GO_LIVE_ENABLED', 'true')
    with db.connect() as conn, conn.begin():
        conn.execute(text("insert into app.operation_run(uid,payload) values('test-preview',cast(:p as jsonb))"),
                     {'p': json.dumps({'kind': 'master-sheet', 'state': 'done', 'result': {'installed': False}})})
        token = WORKER_RUN.set('test-preview')
        compressed = gzip.compress(b'{"state":"done","result":{"installed":false}}')
        messages = [{'type': 'http.response.start', 'status': 202,
                     'headers': [(b'content-encoding', b'gzip')]},
                    {'type': 'http.response.body', 'body': compressed}]
        try:
            preview_review.publish(conn, {'version': 8}, {}, messages)
        finally:
            WORKER_RUN.reset(token)
        payload = conn.execute(text("select payload from app.operation_run where uid='test-preview'")).scalar_one()
        assert payload['result']['review_state_version'] == '8'
        assert messages[1]['body'] == compressed
        conn.execute(text('update app.business_version set version=9'))
        with pytest.raises(Exception) as caught:
            preview_review.require(conn, '8')
        assert caught.value.code == 'preview_stale'
    actor = headers('owner@volt.co.th', 'OWNER', 'owner')
    actor['If-Match'] = '8'
    response = api.post('/api/v1/imports:start?install=true', content=b'file', headers=actor)
    assert response.status_code == 409
    assert response.json()['code'] == 'state_conflict'
    assert CURRENT.get() is None
