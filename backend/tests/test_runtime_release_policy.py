import pytest
from sqlalchemy import text
from app import approval_paths, production_runtime, runtime_policy, session


def test_release_environments_share_limits_and_durable_paths():
    policies=[runtime_policy.environment_defaults(env) for env in ('dev','staging','production')]
    for key in runtime_policy.DEFAULTS:
        assert len({p[key] for p in policies}) == 1
    assert all(runtime_policy.shared_state_enabled(p) for p in policies)
    assert policies[2]['AUTH_ALLOW_TEST_ACCOUNTS']=='false'
    with pytest.raises(ValueError):runtime_policy.environment_defaults('production','fixtures')


def test_every_shared_profile_imports_won_leads_without_requiring_install_dates():
    for name in ('dev', 'staging', 'production'):
        assert runtime_policy.environment_defaults(name)['CRM_WON_ONLY'] == 'true'


def test_approval_path_persists_and_can_be_read():
    token=session.CURRENT.set('approval-policy-test')
    try:
        row=approval_paths.create('COLLECTION_REVIEW',['OWNER'])
        assert row in approval_paths.list_all()
        with pytest.raises(Exception):approval_paths.create('', ['OWNER'])
    finally:session.CURRENT.reset(token)


def test_readiness_rejects_old_migration_version(pg_url,monkeypatch):
    from app import db,migrate
    monkeypatch.setenv("DATABASE_URL",pg_url)
    monkeypatch.setattr(db,"_engine",None)
    monkeypatch.delenv('REQUIRE_DEPENDENCY_READINESS',raising=False)
    with db.connect() as conn,conn.begin():
        migrate.apply(conn)
        conn.execute(text('update app.schema_version set version=1 where singleton=true'))
    assert production_runtime.readiness() is False
    with db.connect() as conn,conn.begin():
        conn.execute(text('update app.schema_version set version=2 where singleton=true'))
    assert production_runtime.readiness() is True


def test_invoice_identity_cache_tracks_changed_source_fields():
    from app import invoice_reviews,request_context
    row={"uid":"test-invoice","entity":"SPV","peak_ref":"IV1"}
    token=request_context.begin_read()
    try:
        original=invoice_reviews.identity(row)
        assert invoice_reviews.identity(dict(row))==original
        row["peak_ref"]="IV2"
        assert invoice_reviews.identity(row)!=original
    finally:request_context.end_read(token)
