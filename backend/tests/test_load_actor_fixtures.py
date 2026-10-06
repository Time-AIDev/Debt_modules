"""Synthetic role fixtures obey the actual served assignments and IAM roster."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import auth, officers, production_permissions

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('load_seeder', ROOT / 'tests/load/seed.py')
seeder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seeder)


def test_mixed_actors_match_served_assignment_and_pass_exact_roster_validation(tmp_path):
    customers = [SimpleNamespace(officer='nantapol') for _ in range(500)]
    actors = seeder.actor_specifications('mixed', customers)
    assert len(actors) == len({row['subject'] for row in actors}) == 25
    assert {role: sum(row['role'] == role for row in actors) for role in (
        'OWNER', 'MANAGER', 'SUPERVISOR', 'OFFICER', 'OPS')} == dict.fromkeys(
            ('OWNER', 'MANAGER', 'SUPERVISOR', 'OFFICER', 'OPS'), 5)
    assert {row['officer'] for row in actors if row['role'] == 'OFFICER'} == {'nantapol'}
    allowlist = {row['subject']: {'role': row['role'], 'officer': row['officer']} for row in actors}
    config = auth.load_config({'AUTH_MODE': 'on', 'AUTH_SESSION_SECRET': 's' * 40,
        'GOOGLE_CLIENT_ID': 'synthetic', 'AUTH_ALLOWLIST': json.dumps(allowlist)}, env_file=tmp_path / 'none')
    roster = officers._build_registry(('nantapol',), tuple((r['officer'], r['role']) for r in actors))
    auth.check_officers(config, roster)
    for actor in actors:
        if actor['role'] != 'OPS':
            production_permissions._role_gate('/v1/cases/by-customer/{uid}/contacts', actor, {})
            production_permissions.require_assignment(actor, 'nantapol')
        else:
            with pytest.raises(Exception) as refused:
                production_permissions._role_gate('/v1/customers/{uid}/payment-claims', actor, {})
            assert refused.value.status == 403


def test_original_owner_profile_does_not_change_with_case_assignments():
    actors = seeder.actor_specifications('owner', [SimpleNamespace(officer='nantapol')])
    assert all(row['role'] == 'OWNER' and row['officer'] == 'owner' for row in actors)
    assert [row['subject'] for row in actors] == ['vu%d@load.example.test' % i for i in range(25)]


@pytest.mark.parametrize('customers', [[], [SimpleNamespace(officer=None)],
    [SimpleNamespace(officer='nantapol'), SimpleNamespace(officer='thip')]])
def test_mixed_fixture_refuses_unknown_or_inconsistent_assignment(customers):
    with pytest.raises(ValueError):
        seeder.actor_specifications('mixed', customers)
