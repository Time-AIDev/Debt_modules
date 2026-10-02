"""auth.py without HTTP: config, hashes, the session token, lockout, the identity rule.

Design: docs/archive/superpowers/specs/2026-09-13-login-google-and-test-accounts-design.md
"""
import json

import pytest

from app import auth

SECRET = "s" * 40
FAST = 1000  # rounds: 600 000 is the production figure and too slow for a unit test


def _environ(**extra):
    base = {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET}
    base.update(extra)
    return base


@pytest.fixture(autouse=True)
def _clean():
    auth.reset()
    yield
    auth.reset()


def test_roles_match_the_api_roles():
    from app.routers.today import ROLES
    assert auth.ROLES == ROLES


def test_mode_unset_is_off_and_needs_nothing_else(tmp_path):
    config = auth.load_config({}, env_file=tmp_path / "none.env")
    assert config.on is False
    assert auth.current_config().on is False


def test_auth_mode_in_the_env_file_is_refused(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ODOO_URL=x\nAUTH_MODE=on\n")
    with pytest.raises(auth.AuthConfigError, match="AUTH_MODE"):
        auth.load_config({}, env_file=env_file)


def test_on_without_a_long_secret_refuses(tmp_path):
    with pytest.raises(auth.AuthConfigError, match="AUTH_SESSION_SECRET"):
        auth.load_config({"AUTH_MODE": "on", "AUTH_SESSION_SECRET": "short"}, env_file=tmp_path / "x")


def test_allowlist_inline_json_is_lowercased_and_checked(tmp_path):
    allow = json.dumps({"Settasak@Volt.co.th": {"role": "MANAGER", "officer": "settasak"}})
    config = auth.load_config(_environ(AUTH_ALLOWLIST=allow), env_file=tmp_path / "x")
    assert config.allowlist == {"settasak@volt.co.th": {"role": "MANAGER", "officer": "settasak"}}


def test_allowlist_from_a_file(tmp_path):
    path = tmp_path / "allow.json"
    path.write_text(json.dumps({"a@volt.co.th": {"role": "OFFICER", "officer": "thip"}}))
    config = auth.load_config(_environ(AUTH_ALLOWLIST=str(path)), env_file=tmp_path / "x")
    assert "a@volt.co.th" in config.allowlist


def test_allowlist_bad_role_names_the_entry(tmp_path):
    allow = json.dumps({"a@volt.co.th": {"role": "ROOT", "officer": "thip"}})
    # Edit 40 (Feedback Round 1, B10b fix 1): start-up errors name a seed entry by position, never its e-mail (PDPA).
    with pytest.raises(auth.AuthConfigError, match=r"AUTH_ALLOWLIST entry 1 \(of 1\) needs a role"):
        auth.load_config(_environ(AUTH_ALLOWLIST=allow), env_file=tmp_path / "x")


def test_test_accounts_load_only_when_allowed(tmp_path):
    accounts = json.dumps({"tester": {"hash": auth.hash_password("pw", rounds=FAST), "role": "ANY", "officer": None}})
    off = auth.load_config(_environ(AUTH_TEST_ACCOUNTS=accounts), env_file=tmp_path / "x")
    assert off.test_accounts == {}
    on = auth.load_config(_environ(AUTH_TEST_ACCOUNTS=accounts, AUTH_ALLOW_TEST_ACCOUNTS="true"), env_file=tmp_path / "x")
    assert set(on.test_accounts) == {"tester"}


def test_a_locked_test_account_needs_an_officer(tmp_path):
    accounts = json.dumps({"officer.test": {"hash": "x", "role": "OFFICER", "officer": None}})
    with pytest.raises(auth.AuthConfigError, match="officer.test"):
        auth.load_config(_environ(AUTH_TEST_ACCOUNTS=accounts, AUTH_ALLOW_TEST_ACCOUNTS="true"), env_file=tmp_path / "x")


def test_check_officers_refuses_an_unknown_name(tmp_path):
    allow = json.dumps({"a@volt.co.th": {"role": "OFFICER", "officer": "ghost"}})
    config = auth.load_config(_environ(AUTH_ALLOWLIST=allow), env_file=tmp_path / "x")
    with pytest.raises(auth.AuthConfigError, match="ghost"):
        auth.check_officers(config, [{"uid": "nantapol", "role": "OFFICER"}])


def test_cookie_secure_defaults_on(tmp_path):
    assert auth.load_config(_environ(), env_file=tmp_path / "x").cookie_secure is True
    assert auth.load_config(_environ(AUTH_COOKIE_SECURE="false"), env_file=tmp_path / "x").cookie_secure is False


def test_password_hash_round_trip_and_wrong_password():
    stored = auth.hash_password("correct horse", rounds=FAST)
    assert stored.startswith("pbkdf2_sha256$1000$")
    assert auth.check_password("correct horse", stored) is True
    assert auth.check_password("wrong", stored) is False
    assert auth.check_password("x", "not-a-hash") is False
    assert auth.check_password("x", None) is False


def test_default_rounds_are_600000():
    assert auth.PBKDF2_ROUNDS == 600000


def test_session_token_round_trip_and_forgery():
    session = auth.new_session("tester", "TEST", "OFFICER", "nantapol", True, now=1000)
    token = auth.sign_session(session, SECRET.encode())
    assert auth.read_session(token, SECRET.encode(), now=1001) == session
    assert auth.read_session(token, b"another-secret-another-secret-xx", now=1001) is None
    body, mac = token.split(".")
    assert auth.read_session(body + "." + mac[:-1] + ("A" if mac[-1] != "A" else "B"), SECRET.encode(), now=1001) is None
    assert auth.read_session("garbage", SECRET.encode(), now=1001) is None


def test_session_idle_and_absolute_expiry():
    session = auth.new_session("tester", "TEST", "OFFICER", "nantapol", True, now=0)
    token = auth.sign_session(session, SECRET.encode())
    assert auth.read_session(token, SECRET.encode(), now=auth.IDLE_SECONDS) is not None
    assert auth.read_session(token, SECRET.encode(), now=auth.IDLE_SECONDS + 1) is None
    session["seen"] = auth.ABSOLUTE_SECONDS  # active all day, still capped at 8 h
    token = auth.sign_session(session, SECRET.encode())
    assert auth.read_session(token, SECRET.encode(), now=auth.ABSOLUTE_SECONDS + 1) is None


def test_lockout_after_five_failures_and_release_after_fifteen_minutes():
    for i in range(4):
        auth.record_failure("tester", now=100 + i)
    assert auth.is_locked("tester", now=105) is False
    auth.record_failure("tester", now=105)
    assert auth.is_locked("tester", now=106) is True
    assert auth.is_locked("tester", now=100 + auth.LOCK_WINDOW_SECONDS + 5) is False
    auth.record_failure("tester", now=2000)
    auth.clear_failures("tester")
    assert auth.is_locked("tester", now=2001) is False


ROSTER = [{"uid": "nantapol", "role": "OFFICER"}, {"uid": "settasak", "role": "MANAGER"},
          {"uid": "owner", "role": "OWNER"}, {"uid": "ops", "role": "OPS"}]


def test_a_locked_session_ignores_what_the_browser_sent():
    session = auth.new_session("manager.test", "TEST", "MANAGER", "settasak", False)
    assert auth.effective_identity(session, "OWNER", "owner", ROSTER) == ("MANAGER", "settasak")


def test_a_switching_session_may_choose_within_the_roles_and_roster():
    session = auth.new_session("tester", "TEST", "OFFICER", "nantapol", True)
    assert auth.effective_identity(session, "owner", "owner", ROSTER) == ("OWNER", "owner")
    assert auth.effective_identity(session, "ROOT", "nantapol", ROSTER) == ("OFFICER", "nantapol")
    # an unknown name falls back to the first roster identity of the chosen role
    assert auth.effective_identity(session, "OPS", "Nok", ROSTER) == ("OPS", "ops")
    assert auth.effective_identity(session, "SUPERVISOR", None, ROSTER) == ("SUPERVISOR", "nantapol")


def test_audit_source_and_me_payload():
    google = auth.new_session("a@volt.co.th", "GOOGLE", "OFFICER", "thip", False, now=0)
    test = auth.new_session("tester", "TEST", "OFFICER", "nantapol", True, now=0)
    assert auth.audit_source(google) == "SESSION"
    assert auth.audit_source(test) == "TEST_ACCOUNT"
    me = auth.me_payload(google)
    assert me["subject"] == "a@volt.co.th" and me["kind"] == "GOOGLE" and me["can_switch"] is False
    assert me["expires_at"] == 1800  # min(iat + 8h, seen + 30 min), epoch seconds
