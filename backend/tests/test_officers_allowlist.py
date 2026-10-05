import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app import auth, main, officers


@pytest.fixture(autouse=True)
def reset_auth():
    previous = auth.current_config()
    yield
    auth.set_config(previous)


def configure(monkeypatch, entries):
    config = auth.load_config({"AUTH_MODE": "on", "AUTH_SESSION_SECRET": "s" * 40,
                              "AUTH_ALLOWLIST": json.dumps(entries)}, env_file="/nonexistent")
    auth.set_config(config)
    monkeypatch.setattr(main, "CUSTOMERS", [])
    monkeypatch.setattr(main, "IDENTITIES", [])
    return config


def test_seven_accounts_start_with_empty_book(monkeypatch):
    pairs = [("settasak", "MANAGER")] * 3 + [("nantapol", "OFFICER")] * 2 + [("owner", "OWNER")] * 2
    config = configure(monkeypatch, {f"user{i}@example.com": {"officer": uid, "role": role}
                                   for i, (uid, role) in enumerate(pairs)})
    rows = officers.registry()
    auth.check_officers(config, rows)
    assert len(config.allowlist) == 7
    assert sum(r["uid"] == "nantapol" for r in rows) == 1
    assert officers.role_of_officer("nantapol") == "OFFICER"
    main.CUSTOMERS.append(SimpleNamespace(officer="nantapol"))
    assert sum(r["uid"] == "nantapol" for r in officers.registry()) == 1


def test_cache_tracks_in_place_changes_and_does_not_leak_mutations(monkeypatch):
    config = configure(monkeypatch, {"user@example.com": {"officer": "new", "role": "OFFICER"}})
    rows = officers.registry()
    rows[0]["roles"].append("OWNER")
    assert officers.registry()[0]["roles"] == ["OFFICER"]
    config.allowlist["user@example.com"]["officer"] = "other"
    assert "new" not in {r["uid"] for r in officers.registry()}
    main.CUSTOMERS.append(SimpleNamespace(officer="before"))
    officers.registry()
    main.CUSTOMERS[0].officer = "after"
    assert "before" not in {r["uid"] for r in officers.registry()}
    assert "after" in {r["uid"] for r in officers.registry()}


@pytest.mark.parametrize("uids,entries", [
    ([], [("same", "OFFICER"), ("same", "OWNER")]),
    ([], [("owner", "OFFICER")]),
    (["assigned"], [("assigned", "OWNER")]),
])
def test_conflicting_roles_fail_without_exposing_email(uids, entries):
    with pytest.raises(auth.AuthConfigError, match="conflict") as error:
        officers._build_registry(uids, entries)
    assert "@" not in str(error.value)


def test_disabled_auth_does_not_add_allowlist_identities(monkeypatch):
    configure(monkeypatch, {"user@example.com": {"officer": "new", "role": "OFFICER"}})
    auth.set_config(replace(auth.current_config(), on=False))
    assert "new" not in {r["uid"] for r in officers.registry()}
