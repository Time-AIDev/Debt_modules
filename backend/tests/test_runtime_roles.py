import pytest
from app import migrate


def test_production_migration_grants_both_runtime_accounts():
    assert migrate.runtime_roles({"DB_RUNTIME_ROLES": "api@p.iam,worker@p.iam"}) == ["api@p.iam", "worker@p.iam"]


def test_invalid_role_never_reaches_ddl():
    with pytest.raises(SystemExit): migrate.runtime_roles({"DB_RUNTIME_ROLES": 'api@p.iam,evil";drop schema app'})
