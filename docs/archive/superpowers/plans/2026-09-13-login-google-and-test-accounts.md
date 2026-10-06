# Login — Google Sign-in, Test Accounts and Tester Guidebook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A login page that signs people in with Google (allow-listed) or with one of six test accounts, a server that takes role and name from that session when login is on, and a Thai-first .docx guidebook for testers.

**Architecture:** A new `backend/app/auth.py` owns config, password hashes, the signed `volt_auth` cookie, lockout and a plain-ASGI middleware. The middleware is placed between `audit_trail` and `request_identity`. It rewrites `X-Volt-Role` / `X-Volt-Officer` (and the actor fields in five JSON bodies) from the session, so no route changes. `backend/app/routers/login.py` serves `/v1/auth/*`. On the frontend, an `AuthGate` wraps `<App/>` in `main.jsx` and shows `screens/Login.jsx` when the server says login is on and there is no session. `AUTH_MODE` unset = today's behaviour, byte for byte.

**Tech Stack:** FastAPI 0.128 / Starlette 0.49 on Python **3.9.6** (no `X | Y` types, no `match`), standard-library `hmac`/`hashlib`, `google-auth` (lazy import), React 18 + Vite + Vitest, `python-docx` in a separate venv.

**Spec:** `docs/archive/superpowers/specs/2026-09-13-login-google-and-test-accounts-design.md` (rulings L1–L7). Read it before any task.

## Global Constraints

- `AUTH_MODE` unset → exactly today's behaviour. Every existing test runs in this mode and must stay green.
- `AUTH_MODE` is read **only from the real process environment**, never from `backend/.env`. `integrations.load_env()` copies `.env` into `os.environ`, so a `.env` line would put the whole test suite behind a login. `auth.load_config()` refuses if `backend/.env` contains an `AUTH_MODE=` line.
- `AUTH_MODE=on` with a missing or short (<32 chars) `AUTH_SESSION_SECRET` → the app refuses to start with a named error. It never falls back to open.
- Session: **8 h absolute, 30 min idle** (SEC-002). Lockout: **5 failures in 15 min** per username.
- Passwords: `pbkdf2_sha256`, **600 000** rounds, stored only as hashes, compared with `hmac.compare_digest`.
- Roles: `OFFICER, SUPERVISOR, MANAGER, OWNER, OPS`, identical to `backend/app/routers/today.py:19`.
- Problems are RFC 9457 via `errors.Problem` and are rendered verbatim by the client (`components/Problem.jsx`).
- New user-facing strings go in `frontend/src/i18n-journey.js` (`auth.*`, `role.OPS`) or `i18n-admin.js` (`audit.*`), in **both** EN and TH. Never in `prefs.jsx`'s `DICT`.
- Test contract: `./scripts/verify_all.sh` green at or above the baseline measured in Task 0. **A test that must change is escalated to Arina, never edited.** The one pre-priced edit is **authorised test edit 27** (Task 4), gated by a stop step.
- Test-account passwords never enter git. The committed guide has no passwords; the vault guide does (spec §2).
- No new backend runtime dependency beyond `google-auth`, which is already in `backend/requirements.txt` (uncommitted, owned by the GCP work — **do not commit that file from this plan**).
- Commits end with the session's attribution lines. Before every commit, run `git log --oneline -1` and check nobody else moved HEAD mid-task (other sessions commit to `design-team`).

## Three refinements to the spec, made while planning (tell Arina at hand-off)

1. **Audit source values.** The spec says `actor_source = SESSION`. The plan records **`SESSION`** for Google sign-ins and **`TEST_ACCOUNT`** for password sign-ins, so the audit screen can badge test activity from a served value instead of guessing from the name's shape.
2. **Body rewrite is limited to routes where `role` means the actor.** `POST /v1/config/approval-paths` uses body `role` for the role being *configured* (`main.py:1457`), so a blanket rewrite would corrupt it. The rewrite covers exactly `POST /v1/contacts`, `/v1/cases/{uid}:advance`, `/v1/restructures/{uid}:approve`, `/v1/manager-review/{uid}:decide` and `/v1/recovery-cases/{uid}:resolve`. The body `by` field always names the actor, and `officers.sign()` prefers it over the header, so it is rewritten wherever present.
3. **No `/login` route.** The gate renders the login screen in place, so the URL never changes and "the page to return to" is kept for free.

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `backend/app/auth.py` | create | config, hashing, session token, lockout, identity rule, problems, middleware |
| `backend/app/routers/login.py` | create | `/v1/auth/config`, `/google`, `/password`, `/me`, `/logout` |
| `backend/app/main.py` | modify | install middleware (after `audit_trail`), include router, `_actor_of` reads the session |
| `backend/app/officers.py` | modify | `FIXED` gains the `ops` identity |
| `backend/app/schema.sql` | modify | `actor_source` allows `SESSION`, `TEST_ACCOUNT` (idempotent) |
| `backend/tests/test_auth_core.py` | create | unit tests for `auth.py` |
| `backend/tests/test_auth_http.py` | create | middleware + routes through `TestClient` |
| `backend/tests/test_auth_schema.py` | create | constraint re-applies on Postgres (skips without it) |
| `frontend/src/api.js` | modify | `auth*` calls, `AUTH_REQUIRED_EVENT` on 401 `auth_required` |
| `frontend/src/components/role.jsx` | modify | `OPS` in `ROLES`; `lockIdentity` / `unlockIdentity` |
| `frontend/src/components/auth.jsx` | create | session store (`setSession`, `useSession`) |
| `frontend/src/components/googleScript.js` | create | loads Google Identity Services once |
| `frontend/src/components/AuthGate.jsx` | create | decides open / login / signed in |
| `frontend/src/screens/Login.jsx` | create | Google button + test-account form |
| `frontend/src/main.jsx` | modify | wrap `<App/>` in `<AuthGate>` |
| `frontend/src/components/RoleSwitcher.jsx` | modify | `IdentityMenu`: locked view + sign out |
| `frontend/src/components/Shell.jsx` | modify | TEST ACCOUNT badge in the top bar |
| `frontend/src/screens/AuditLog.jsx` | modify | badge by `actor_source` |
| `frontend/src/i18n-journey.js`, `i18n-admin.js` | modify | strings |
| `frontend/src/app.css` | modify | `.login`, `.topbar__test`, `.audit__test` |
| `frontend/src/components/RoleSwitcher.test.jsx` | **authorised edit 27** (Task 4) | line 27 + its title |
| `frontend/src/**/*.auth*.test.jsx` etc. | create | new frontend tests |
| `scripts/guides/make_test_accounts.py` | create | six passwords → hashes in `backend/.env`, plain text to `~/.volt-test-accounts.json` |
| `scripts/guides/role_matrix.py` | create | who-can-do-what rows, each citing file:line |
| `scripts/guides/build_login_guide.py` | create | both .docx files |
| `scripts/guides/test_guides.py` | create | citations exist; the repo build carries no password |
| `scripts/push_secrets.sh`, `scripts/deploy_gcp.sh` | modify | auth secrets + env |
| `.gitignore` | modify | `docs/guides/*with-passwords*`, `scripts/guides/.venv/` |

---

### Task 0: Measure the baseline

**Files:** none changed.

- [ ] **Step 1: Check HEAD and the working tree**

Run: `git log --oneline -3 && git status --short`
Expected: HEAD is `4406c47` or later. The uncommitted `.gitignore`, `backend/Dockerfile`, `backend/requirements.txt` and `pictures/` changes belong to other work. Leave them alone, and never `git add -A`.

- [ ] **Step 2: Install google-auth into the backend venv**

Run: `backend/.venv/bin/pip install 'google-auth>=2.30' 'requests>=2.32'`
Expected: installs. (The requirement lines already exist in the uncommitted `requirements.txt`.)

- [ ] **Step 3: Run the full harness and record the counts**

Run: `./scripts/verify_all.sh 2>&1 | tee /tmp/claude-baseline.txt | grep -E "passed|failed|Tests|EVERYTHING|SOMETHING|checks"`
Expected: `EVERYTHING PASSED`. Write down the backend passed/skipped, frontend tests/files and e2e counts. **These numbers, not the remembered 761/577/31, are the floor.** If it is not green before any change, stop and report to Arina.

---

### Task 1: `auth.py` core — config, hashes, session token, lockout, identity rule

**Files:**
- Create: `backend/app/auth.py`
- Test: `backend/tests/test_auth_core.py`

**Interfaces — Produces:**
- `ROLES: tuple` (five roles), `COOKIE = "volt_auth"`, `ABSOLUTE_SECONDS = 28800`, `IDLE_SECONDS = 1800`, `LOCK_AFTER = 5`, `LOCK_WINDOW_SECONDS = 900`
- `class AuthConfigError(Exception)`
- `@dataclass(frozen=True) class AuthConfig(on: bool, secret: bytes, google_client_id: Optional[str], allowlist: dict, test_accounts: dict, cookie_secure: bool)`. `allowlist` is `{email_lower: {"role", "officer"}}`; `test_accounts` is `{username: {"hash", "role", "officer"}}`, where `role` may be `"ANY"`.
- `load_config(environ=None, env_file=None) -> AuthConfig`
- `check_officers(config, registry_rows) -> None` (raises `AuthConfigError`)
- `set_config(config)`, `current_config() -> AuthConfig`, `reset()`
- `hash_password(password, salt=None, rounds=600000) -> str`, `check_password(password, stored) -> bool`
- `new_session(sub, kind, role, officer, can_switch, now=None) -> dict`, where `kind` is `"GOOGLE"` or `"TEST"`
- `sign_session(payload, secret) -> str`, `read_session(token, secret, now=None) -> Optional[dict]`
- `is_locked(username, now=None) -> bool`, `record_failure(username, now=None)`, `clear_failures(username)`
- `effective_identity(session, sent_role, sent_officer, roster) -> (role, officer)`, where `roster` is `[{"uid","role"}]`
- `audit_source(session) -> "SESSION" | "TEST_ACCOUNT"`
- `me_payload(session) -> dict`
- module attribute `_now = time.time` (tests monkeypatch it)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_auth_core.py
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
    with pytest.raises(auth.AuthConfigError, match="a@volt.co.th"):
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
```

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_auth_core.py`
Expected: FAIL / error `ModuleNotFoundError: No module named 'app.auth'` or `ImportError`.

- [ ] **Step 3: Write `backend/app/auth.py` (core part)**

```python
"""Login — Google sign-in, test accounts, and the signed session cookie.

Design: docs/archive/superpowers/specs/2026-09-13-login-google-and-test-accounts-design.md

Two modes, and the difference is the whole safety argument:

  - AUTH_MODE unset: nothing here runs. Headers are trusted exactly as before, so
    every existing test and every curl keeps working.
  - AUTH_MODE=on: every /v1 call outside /v1/auth/ needs a valid session, and the
    role and acting name come from that session, not from the browser.

AUTH_MODE is read from the real environment ONLY. integrations.load_env() copies
backend/.env into os.environ, and the test suite loads that file too — one line
there would put 700+ tests behind a login. So a .env that names AUTH_MODE is refused.

Standard library only for the cookie (hmac + hashlib). google-auth is imported
lazily, where a Google token is actually checked.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import errors

# Identical to routers/today.py ROLES; test_auth_core pins the equality. Not imported,
# because routers.today imports main and this module is imported BY main.
ROLES = ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS")
COOKIE = "volt_auth"
ABSOLUTE_SECONDS = 8 * 60 * 60     # SEC-002
IDLE_SECONDS = 30 * 60             # SEC-002
LOCK_AFTER = 5
LOCK_WINDOW_SECONDS = 15 * 60
PBKDF2_ROUNDS = 600000
MIN_SECRET = 32

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_now = time.time


class AuthConfigError(Exception):
    """Login is configured wrongly. Raised at start-up so the app refuses to run."""


@dataclass(frozen=True)
class AuthConfig:
    on: bool = False
    secret: bytes = b""
    google_client_id: Optional[str] = None
    allowlist: dict = field(default_factory=dict)
    test_accounts: dict = field(default_factory=dict)
    cookie_secure: bool = True


_OFF = AuthConfig()
_config = _OFF
_FAILURES = {}


def set_config(config):
    global _config
    _config = config


def current_config():
    return _config


def reset():
    set_config(_OFF)
    _FAILURES.clear()


def _file_names_auth_mode(env_file):
    try:
        lines = Path(env_file).read_text().splitlines()
    except OSError:
        return False
    return any(line.strip().startswith("AUTH_MODE=") for line in lines)


def _read(environ, key):
    """Real environment first; when reading the process environment, backend/.env
    is a fallback for everything EXCEPT AUTH_MODE (see the module docstring)."""
    if key in environ:
        return environ[key]
    if environ is os.environ:
        from .integrations import env
        return env(key)
    return None


def _json_or_file(value, name):
    text = value.strip()
    if not text.startswith("{"):
        try:
            text = Path(text).read_text()
        except OSError as exc:
            raise AuthConfigError("%s names a file that cannot be read: %s" % (name, exc))
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AuthConfigError("%s is not valid JSON: %s" % (name, exc))
    if not isinstance(data, dict):
        raise AuthConfigError("%s must be a JSON object" % name)
    return data


def load_config(environ=None, env_file=None):
    environ = os.environ if environ is None else environ
    env_file = _ENV_FILE if env_file is None else env_file
    if _file_names_auth_mode(env_file):
        raise AuthConfigError(
            "AUTH_MODE is set in %s. Set it in the shell or the service, never in the "
            "env file: the test suite reads that file." % env_file)
    if (environ.get("AUTH_MODE") or "").strip().lower() != "on":
        return _OFF

    secret = _read(environ, "AUTH_SESSION_SECRET") or ""
    if len(secret) < MIN_SECRET:
        raise AuthConfigError("AUTH_MODE=on needs AUTH_SESSION_SECRET of at least %d characters" % MIN_SECRET)

    allowlist = {}
    raw_allow = _read(environ, "AUTH_ALLOWLIST")
    if raw_allow:
        for email, entry in _json_or_file(raw_allow, "AUTH_ALLOWLIST").items():
            entry = entry if isinstance(entry, dict) else {}
            if entry.get("role") not in ROLES or not entry.get("officer"):
                raise AuthConfigError("AUTH_ALLOWLIST entry %s needs a role in %s and an officer" % (email, ", ".join(ROLES)))
            allowlist[email.strip().lower()] = {"role": entry["role"], "officer": entry["officer"]}

    accounts = {}
    if (_read(environ, "AUTH_ALLOW_TEST_ACCOUNTS") or "").strip().lower() == "true":
        raw_accounts = _read(environ, "AUTH_TEST_ACCOUNTS")
        if raw_accounts:
            for username, entry in _json_or_file(raw_accounts, "AUTH_TEST_ACCOUNTS").items():
                entry = entry if isinstance(entry, dict) else {}
                role = entry.get("role")
                if role != "ANY" and role not in ROLES:
                    raise AuthConfigError("AUTH_TEST_ACCOUNTS entry %s has an unknown role" % username)
                if role != "ANY" and not entry.get("officer"):
                    raise AuthConfigError("AUTH_TEST_ACCOUNTS entry %s is locked to a role and needs an officer" % username)
                if not entry.get("hash"):
                    raise AuthConfigError("AUTH_TEST_ACCOUNTS entry %s has no hash" % username)
                accounts[username] = {"hash": entry["hash"], "role": role, "officer": entry.get("officer")}

    return AuthConfig(
        on=True,
        secret=secret.encode("utf-8"),
        google_client_id=(_read(environ, "GOOGLE_CLIENT_ID") or "").strip() or None,
        allowlist=allowlist,
        test_accounts=accounts,
        cookie_secure=(_read(environ, "AUTH_COOKIE_SECURE") or "").strip().lower() != "false",
    )


def check_officers(config, registry_rows):
    """Every allow-list and locked test-account officer must be a registry identity."""
    known = {row["uid"] for row in registry_rows}
    named = [(email, e["officer"]) for email, e in config.allowlist.items()]
    named += [(user, e["officer"]) for user, e in config.test_accounts.items() if e["role"] != "ANY"]
    for who, officer in named:
        if officer not in known:
            raise AuthConfigError("%s acts as officer %s, who is not in /v1/officers" % (who, officer))


# --- passwords -----------------------------------------------------------------------

def hash_password(password, salt=None, rounds=PBKDF2_ROUNDS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), rounds).hex()
    return "pbkdf2_sha256$%d$%s$%s" % (rounds, salt, digest)


def check_password(password, stored):
    try:
        scheme, rounds, salt, digest = stored.split("$")
        rounds = int(rounds)
    except (AttributeError, ValueError):
        return False
    if scheme != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), rounds).hex()
    return hmac.compare_digest(candidate, digest)


# --- the session token ---------------------------------------------------------------

def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(body, secret):
    return _b64(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())


def new_session(sub, kind, role, officer, can_switch, now=None):
    now = int(_now() if now is None else now)
    return {"sub": sub, "kind": kind, "role": role, "officer": officer,
            "can_switch": bool(can_switch), "iat": now, "seen": now}


def sign_session(payload, secret):
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return body + "." + _mac(body, secret)


def read_session(token, secret, now=None):
    """The payload, or None when the token is forged, malformed or expired."""
    now = _now() if now is None else now
    try:
        body, mac = token.split(".")
        if not hmac.compare_digest(mac, _mac(body, secret)):
            return None
        payload = json.loads(_unb64(body))
    except Exception:                                  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if now - payload.get("iat", 0) > ABSOLUTE_SECONDS or now - payload.get("seen", 0) > IDLE_SECONDS:
        return None
    return payload


# --- lockout -------------------------------------------------------------------------
# In memory, per process. Cloud Run staging runs --max-instances 4, so a determined
# guesser spread across instances gets up to 4 x 5 tries per window. Accepted for
# test accounts behind IAP; SEC-001 proper replaces this with Identity Platform.

def _recent(username, now):
    kept = [t for t in _FAILURES.get(username, []) if now - t < LOCK_WINDOW_SECONDS]
    _FAILURES[username] = kept
    return kept


def is_locked(username, now=None):
    now = _now() if now is None else now
    return len(_recent(username, now)) >= LOCK_AFTER


def record_failure(username, now=None):
    now = _now() if now is None else now
    _recent(username, now).append(now)


def clear_failures(username):
    _FAILURES.pop(username, None)


# --- identity --------------------------------------------------------------------------

def effective_identity(session, sent_role, sent_officer, roster):
    """(role, officer) the request acts as. A locked session is always itself; a
    switching one may pick any API role and any roster identity."""
    if not session.get("can_switch"):
        return session["role"], session["officer"]
    role = (sent_role or "").strip().upper()
    role = role if role in ROLES else "OFFICER"
    uids = [row["uid"] for row in roster]
    if sent_officer in uids:
        return role, sent_officer
    same_role = [row["uid"] for row in roster if row.get("role") == role]
    return role, (same_role or uids or ["nantapol"])[0]


def audit_source(session):
    return "TEST_ACCOUNT" if session.get("kind") == "TEST" else "SESSION"


def me_payload(session):
    return {
        "subject": session["sub"], "kind": session["kind"], "role": session["role"],
        "officer": session["officer"], "can_switch": session["can_switch"],
        "expires_at": min(session["iat"] + ABSOLUTE_SECONDS, session["seen"] + IDLE_SECONDS),
    }
```

(`errors` is imported now because Task 2 appends the problems to this module.)

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_auth_core.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git log --oneline -1
git add backend/app/auth.py backend/tests/test_auth_core.py
git commit -m "feat(auth): config, password hashes, the signed session and lockout — off unless AUTH_MODE=on"
```

---

### Task 2: Middleware, `/v1/auth/*` routes, audit source, the `ops` identity, schema

**Files:**
- Modify: `backend/app/auth.py` (append problems + middleware + Google verifier)
- Create: `backend/app/routers/login.py`
- Modify: `backend/app/main.py:163-253` (install after `audit_trail`, `_actor_of`), `backend/app/main.py:1552` (include router)
- Modify: `backend/app/officers.py:16-19`
- Modify: `backend/app/schema.sql:126`
- Test: `backend/tests/test_auth_http.py`, `backend/tests/test_auth_schema.py`

**Interfaces:**
- Consumes: everything Task 1 produced.
- Produces (HTTP):
  - `GET /v1/auth/config` → `{"mode": "on"|"off", "google_client_id": str|null, "password_enabled": bool}`
  - `POST /v1/auth/password {username, password}` → 200 me-payload + `Set-Cookie: volt_auth`
  - `POST /v1/auth/google {credential}` → the same
  - `GET /v1/auth/me` → me-payload | 401 `auth_required` | 404 `auth_off`
  - `POST /v1/auth/logout` → `{"signed_out": true}` and clears the cookie
  - Problem codes: `auth_required` 401, `login_failed` 401, `login_locked` 429, `not_on_allow_list` 403, `google_not_configured` 503, `google_token_invalid` 401, `auth_off` 404
  - Audit `actor_source` gains `SESSION` and `TEST_ACCOUNT`
- Produces (Python): `auth.AuthMiddleware(app, request_id, roster)`, `auth.verify_google_token(credential, client_id) -> dict` (monkeypatchable)

- [ ] **Step 1: Write the failing HTTP tests**

```python
# backend/tests/test_auth_http.py
"""Login through HTTP: the middleware, the routes, and what the audit log records."""
import json

import pytest
from fastapi.testclient import TestClient

from app import audit_store, auth
from app.main import app

SECRET = "s" * 40
FAST = 1000


def _accounts():
    return {
        "tester": {"hash": auth.hash_password("tester-pw", rounds=FAST), "role": "ANY", "officer": None},
        "manager.test": {"hash": auth.hash_password("manager-pw", rounds=FAST), "role": "MANAGER", "officer": "settasak"},
        "ops.test": {"hash": auth.hash_password("ops-pw", rounds=FAST), "role": "OPS", "officer": "ops"},
    }


@pytest.fixture
def on(tmp_path):
    environ = {"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET, "AUTH_COOKIE_SECURE": "false",
               "AUTH_ALLOW_TEST_ACCOUNTS": "true", "AUTH_TEST_ACCOUNTS": json.dumps(_accounts()),
               "GOOGLE_CLIENT_ID": "client-123.apps.googleusercontent.com",
               "AUTH_ALLOWLIST": json.dumps({"thip@volt.co.th": {"role": "OFFICER", "officer": "thip"}})}
    auth.set_config(auth.load_config(environ, env_file=tmp_path / "none"))
    yield
    auth.reset()


def _login(client, username, password):
    return client.post("/v1/auth/password", json={"username": username, "password": password})


def test_off_by_default_headers_still_decide():
    client = TestClient(app)
    assert client.get("/v1/auth/config").json() == {"mode": "off", "google_client_id": None, "password_enabled": False}
    assert client.get("/v1/workbook").status_code == 200
    assert client.get("/v1/auth/me").json()["code"] == "auth_off"


def test_on_without_a_session_every_v1_call_is_refused(on):
    client = TestClient(app)
    r = client.get("/v1/workbook")
    assert r.status_code == 401 and r.json()["code"] == "auth_required"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert client.get("/healthz").status_code == 200
    assert client.get("/v1/auth/config").json()["mode"] == "on"


def test_password_login_sets_a_cookie_and_me_answers(on):
    client = TestClient(app)
    r = _login(client, "manager.test", "manager-pw")
    assert r.status_code == 200
    assert r.json()["role"] == "MANAGER" and r.json()["kind"] == "TEST" and r.json()["can_switch"] is False
    assert auth.COOKIE in client.cookies
    assert client.get("/v1/auth/me").json()["subject"] == "manager.test"
    assert client.get("/v1/workbook").status_code == 200


def test_wrong_password_then_lockout(on):
    client = TestClient(app)
    for _ in range(auth.LOCK_AFTER):
        assert _login(client, "tester", "nope").json()["code"] == "login_failed"
    r = _login(client, "tester", "tester-pw")
    assert r.status_code == 429 and r.json()["code"] == "login_locked"


def test_unknown_username_is_the_same_refusal_as_a_wrong_password(on):
    assert _login(TestClient(app), "nobody", "x").json()["code"] == "login_failed"


# What the middleware hands a route is read back through a tiny echo app wrapped in
# the SAME middleware class: spying on the real routes would test FastAPI's body
# parsing, not the rewrite.
ROSTER = [{"uid": "nantapol", "role": "OFFICER"}, {"uid": "settasak", "role": "MANAGER"},
          {"uid": "owner", "role": "OWNER"}, {"uid": "ops", "role": "OPS"}]


def _echo_client():
    from fastapi import Body, FastAPI, Request

    mini = FastAPI()

    @mini.post("/v1/contacts")
    def contacts(request: Request, body: dict = Body(...)):
        return {"body": body, "role": request.headers.get("x-volt-role"),
                "officer": request.headers.get("x-volt-officer")}

    @mini.post("/v1/config/approval-paths")
    def approval(body: dict = Body(...)):
        return {"body": body}

    mini.add_middleware(auth.AuthMiddleware, roster=lambda: ROSTER)
    return TestClient(mini)


def _cookie_for(username, role, officer, can_switch):
    session = auth.new_session(username, "TEST", role, officer, can_switch)
    return {auth.COOKIE: auth.sign_session(session, SECRET.encode())}


def test_a_locked_account_cannot_claim_another_role_by_header_or_body(on):
    client = _echo_client()
    client.cookies.update(_cookie_for("manager.test", "MANAGER", "settasak", False))
    r = client.post("/v1/contacts", json={"role": "OFFICER", "by": "nantapol", "note": "สวัสดี"},
                    headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}).json()
    assert r["role"] == "MANAGER" and r["officer"] == "settasak"
    assert r["body"] == {"role": "MANAGER", "by": "settasak", "note": "สวัสดี"}


def test_approval_path_body_role_is_left_alone_but_by_is_not(on):
    client = _echo_client()
    client.cookies.update(_cookie_for("tester", "OFFICER", "nantapol", True))
    r = client.post("/v1/config/approval-paths", json={"role": "DEBT_MANAGER", "by": "Nok"},
                    headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}).json()
    assert r["body"] == {"role": "DEBT_MANAGER", "by": "owner"}


def test_tester_switches_within_the_roles(on):
    client = TestClient(app)
    _login(client, "tester", "tester-pw")
    r = client.post("/v1/reports/weekly:snapshot", headers={"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"})
    assert r.json()["snapshot"]["taken_by_role"] == "OWNER"


def test_google_sign_in_on_the_allow_list(on, monkeypatch):
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": "Thip@volt.co.th", "email_verified": True})
    client = TestClient(app)
    r = client.post("/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 200 and r.json()["officer"] == "thip" and r.json()["kind"] == "GOOGLE"


def test_google_sign_in_refusals(on, monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": "stranger@volt.co.th", "email_verified": True})
    assert client.post("/v1/auth/google", json={"credential": "t"}).json()["code"] == "not_on_allow_list"
    monkeypatch.setattr(auth, "verify_google_token",
                        lambda credential, client_id: {"email": "thip@volt.co.th", "email_verified": False})
    assert client.post("/v1/auth/google", json={"credential": "t"}).json()["code"] == "google_token_invalid"

    def boom(credential, client_id):
        raise ValueError("bad signature")
    monkeypatch.setattr(auth, "verify_google_token", boom)
    assert client.post("/v1/auth/google", json={"credential": "t"}).json()["code"] == "google_token_invalid"


def test_google_not_configured(tmp_path):
    auth.set_config(auth.load_config({"AUTH_MODE": "on", "AUTH_SESSION_SECRET": SECRET}, env_file=tmp_path / "x"))
    try:
        r = TestClient(app).post("/v1/auth/google", json={"credential": "t"})
        assert r.status_code == 503 and r.json()["code"] == "google_not_configured"
    finally:
        auth.reset()


def test_logout_clears_the_session(on):
    client = TestClient(app)
    _login(client, "tester", "tester-pw")
    assert client.post("/v1/auth/logout").json() == {"signed_out": True}
    assert client.get("/v1/workbook").status_code == 401


def test_an_expired_session_is_refused(on, monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(auth, "_now", lambda: 1_000_000)
    _login(client, "tester", "tester-pw")
    monkeypatch.setattr(auth, "_now", lambda: 1_000_000 + auth.IDLE_SECONDS + 1)
    assert client.get("/v1/workbook").status_code == 401


def test_audit_records_the_session_as_the_source(on):
    client = TestClient(app)
    _login(client, "manager.test", "manager-pw")
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid, json={"code": "PAID"})
    entry = audit_store.read({}, limit=1, before_seq=None)[0]
    assert entry["actor_source"] == "TEST_ACCOUNT" and entry["actor_claimed"] == "manager.test"


def test_the_ops_identity_is_in_the_registry():
    body = TestClient(app).get("/v1/officers").json()
    assert {"uid": "ops", "role": "OPS"}.items() <= next(o for o in body["officers"] if o["uid"] == "ops").items()
```

```python
# backend/tests/test_auth_schema.py
"""The audit constraint admits the two session sources and re-applies cleanly."""
from sqlalchemy import text

from app import migrate


def test_actor_source_constraint_admits_session_sources_and_reapplies(pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    migrate.apply(pg_conn)  # idempotent: a second deploy re-runs schema.sql
    pg_conn.commit()
    definition = pg_conn.execute(text(
        "select pg_get_constraintdef(oid) from pg_constraint where conname = 'entry_actor_source_check'"
    )).scalar()
    assert "SESSION" in definition and "TEST_ACCOUNT" in definition and "HEADER" in definition
```

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_auth_http.py tests/test_auth_schema.py`
Expected: FAIL. `/v1/auth/config` 404s; `test_auth_schema` either fails on the constraint text or SKIPS without Postgres. Start Postgres with `./scripts/pg_local.sh start` so it runs, and use `VOLT_TEST_PG_URL` (memory: the local test database).

- [ ] **Step 3: Append problems, the Google verifier and the middleware to `auth.py`**

```python
# --- problems (RFC 9457, errors.Problem) ----------------------------------------------

def auth_required():
    return errors.Problem("auth_required", 401, "Sign in to continue",
                          "This build requires a signed-in session.",
                          "กรุณาเข้าสู่ระบบก่อนใช้งาน", "DEBT-AUTH-401")


def login_failed():
    # One refusal for "no such user" and "wrong password": telling them apart tells a
    # guesser which usernames exist.
    return errors.Problem("login_failed", 401, "Wrong username or password",
                          "The username or password is not correct.",
                          "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "DEBT-AUTH-402")


def login_locked():
    return errors.Problem("login_locked", 429, "Too many wrong passwords",
                          "This username is locked for 15 minutes after %d wrong passwords." % LOCK_AFTER,
                          "ใส่รหัสผ่านผิด %d ครั้ง ชื่อผู้ใช้นี้ถูกล็อกไว้ 15 นาที" % LOCK_AFTER,
                          "DEBT-AUTH-429", retryable=True)


def not_on_allow_list(email):
    return errors.Problem("not_on_allow_list", 403, "This Google account is not on the allow-list",
                          "Ask the system owner to add this email to AUTH_ALLOWLIST.",
                          "บัญชี Google นี้ยังไม่ได้รับสิทธิ์ใช้ระบบ กรุณาขอสิทธิ์จากเจ้าของระบบ",
                          "DEBT-AUTH-403", extensions={"email": email})


def google_not_configured():
    return errors.Problem("google_not_configured", 503, "Google sign-in is not configured",
                          "GOOGLE_CLIENT_ID is not set on this service.",
                          "ยังไม่ได้ตั้งค่าการเข้าสู่ระบบด้วย Google ใช้บัญชีทดสอบแทนได้",
                          "DEBT-AUTH-503")


def google_token_invalid():
    return errors.Problem("google_token_invalid", 401, "Google sign-in could not be verified",
                          "The Google token was rejected or its email is not verified.",
                          "ยืนยันบัญชี Google ไม่สำเร็จ กรุณาลองใหม่", "DEBT-AUTH-404")


def auth_off():
    return errors.Problem("auth_off", 404, "Login is not enabled on this service",
                          "AUTH_MODE is not on.", "ระบบนี้ไม่ได้เปิดใช้การเข้าสู่ระบบ", "DEBT-AUTH-405")


def verify_google_token(credential, client_id):
    """The token's claims, or raises. Lazy import: only a Google sign-in needs it."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    return id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)


# --- the middleware ------------------------------------------------------------------
import re  # noqa: E402

# Routes whose JSON body `role` names the ACTOR (spec plan refinement 2). Not
# /v1/config/approval-paths: there `role` is the role being configured.
ACTOR_ROLE_BODY = re.compile(
    r"^/v1/(contacts|cases/[^/]+:advance|restructures/[^/]+:approve"
    r"|manager-review/[^/]+:decide|recovery-cases/[^/]+:resolve)$")
OPEN_PREFIX = "/v1/auth/"
REFRESH_AFTER = 60  # seconds; re-sign `seen` at most once a minute


def _header(scope, name):
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None


def _cookie(scope, name):
    raw = _header(scope, b"cookie") or ""
    for part in raw.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


def cookie_header(value, config, max_age):
    parts = ["%s=%s" % (COOKIE, value), "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=%d" % max_age]
    if config.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


async def _read_body(receive):
    chunks, more = [], True
    while more:
        message = await receive()
        if message["type"] != "http.request":
            return None
        chunks.append(message.get("body", b""))
        more = message.get("more_body", False)
    return b"".join(chunks)


class AuthMiddleware:
    """Plain ASGI, like ApiPrefixMiddleware: rewriting headers and a body is a scope
    and receive edit. Registered straight after audit_trail, so it sits OUTSIDE it
    (audit sees the rewritten identity) and INSIDE request_identity (a refusal
    carries the request id)."""

    def __init__(self, app, request_id=lambda: "unknown", roster=lambda: []):
        self.app = app
        self.request_id = request_id
        self.roster = roster

    async def __call__(self, scope, receive, send):
        config = current_config()
        path = scope.get("path", "")
        if (scope["type"] != "http" or not config.on or not path.startswith("/v1/")
                or path.startswith(OPEN_PREFIX) or scope.get("method") == "OPTIONS"):
            await self.app(scope, receive, send)
            return

        token = _cookie(scope, COOKIE)
        session = read_session(token, config.secret) if token else None
        if session is None:
            response = auth_required().response(instance="urn:request:" + self.request_id())
            await response(scope, receive, send)
            return

        role, officer = effective_identity(session, _header(scope, b"x-volt-role"),
                                           _header(scope, b"x-volt-officer"), self.roster())
        headers = [(k, v) for k, v in scope["headers"]
                   if k not in (b"x-volt-role", b"x-volt-officer", b"content-length")]
        original_length = _header(scope, b"content-length")
        headers += [(b"x-volt-role", role.encode("latin-1")), (b"x-volt-officer", officer.encode("utf-8"))]

        body = None
        is_json = "application/json" in (_header(scope, b"content-type") or "")
        if scope.get("method") not in ("GET", "HEAD") and is_json:
            body = await _read_body(receive)
            if body is not None:
                body = self._rewrite(path, body, role, officer)
                headers.append((b"content-length", str(len(body)).encode("ascii")))
        if body is None and original_length is not None:
            headers.append((b"content-length", original_length.encode("ascii")))

        scope = dict(scope)
        scope["headers"] = headers
        scope["volt_auth"] = session

        if body is not None:
            delivered = False

            async def receive_rewritten():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            inner_receive = receive_rewritten
        else:
            inner_receive = receive

        now = _now()
        set_cookie = None
        if now - session.get("seen", 0) >= REFRESH_AFTER:
            refreshed = dict(session, seen=int(now))
            set_cookie = cookie_header(sign_session(refreshed, config.secret), config, ABSOLUTE_SECONDS)

        async def send_with_cookie(message):
            if set_cookie and message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = list(message.get("headers") or []) + [(b"set-cookie", set_cookie.encode("latin-1"))]
            await send(message)

        await self.app(scope, inner_receive, send_with_cookie)

    @staticmethod
    def _rewrite(path, body, role, officer):
        try:
            data = json.loads(body) if body else None
        except ValueError:
            return body
        if not isinstance(data, dict):
            return body
        changed = False
        if "by" in data:
            data["by"] = officer
            changed = True
        if "role" in data and ACTOR_ROLE_BODY.match(path):
            data["role"] = role
            changed = True
        return json.dumps(data, ensure_ascii=False).encode("utf-8") if changed else body
```

Move `import re` to the top-of-file imports rather than leaving the `# noqa` version. It is shown inline here only to keep the snippet self-contained.

- [ ] **Step 4: Create `backend/app/routers/login.py`**

```python
"""/v1/auth/* — the only /v1 routes the login middleware lets through without a session.

Design: docs/archive/superpowers/specs/2026-09-13-login-google-and-test-accounts-design.md §3.3
"""
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from .. import auth

router = APIRouter()


def _signed_in(session, config):
    response = JSONResponse(auth.me_payload(session))
    response.headers["set-cookie"] = auth.cookie_header(
        auth.sign_session(session, config.secret), config, auth.ABSOLUTE_SECONDS)
    return response


@router.get("/v1/auth/config")
def auth_config():
    config = auth.current_config()
    return {"mode": "on" if config.on else "off",
            "google_client_id": config.google_client_id if config.on else None,
            "password_enabled": bool(config.on and config.test_accounts)}


@router.post("/v1/auth/password")
def password_login(body: dict = Body(default={})):
    config = auth.current_config()
    if not config.on:
        raise auth.auth_off()
    username = str((body or {}).get("username") or "").strip()
    password = str((body or {}).get("password") or "")
    if auth.is_locked(username):
        raise auth.login_locked()
    account = config.test_accounts.get(username)
    if account is None or not auth.check_password(password, account["hash"]):
        auth.record_failure(username)
        raise auth.login_failed()
    auth.clear_failures(username)
    can_switch = account["role"] == "ANY"
    session = auth.new_session(username, "TEST", "OFFICER" if can_switch else account["role"],
                               account["officer"] or "nantapol", can_switch)
    return _signed_in(session, config)


@router.post("/v1/auth/google")
def google_login(body: dict = Body(default={})):
    config = auth.current_config()
    if not config.on:
        raise auth.auth_off()
    if not config.google_client_id:
        raise auth.google_not_configured()
    try:
        claims = auth.verify_google_token(str((body or {}).get("credential") or ""), config.google_client_id)
    except Exception:                                  # noqa: BLE001
        raise auth.google_token_invalid()
    if not claims.get("email_verified"):
        raise auth.google_token_invalid()
    email = str(claims.get("email") or "").strip().lower()
    entry = config.allowlist.get(email)
    if entry is None:
        raise auth.not_on_allow_list(email)
    return _signed_in(auth.new_session(email, "GOOGLE", entry["role"], entry["officer"], False), config)


@router.get("/v1/auth/me")
def me(request: Request):
    config = auth.current_config()
    if not config.on:
        raise auth.auth_off()
    token = request.cookies.get(auth.COOKIE)
    session = auth.read_session(token, config.secret) if token else None
    if session is None:
        raise auth.auth_required()
    return auth.me_payload(session)


@router.post("/v1/auth/logout")
def logout():
    config = auth.current_config()
    response = JSONResponse({"signed_out": True})
    response.headers["set-cookie"] = auth.cookie_header("", config, 0)
    return response
```

Check that `errors.Problem` raised from a route is turned into a problem response by main's existing exception handler (`main.py:387` `problem.response(...)`). If the handler is registered for `errors.Problem`, nothing more is needed.

- [ ] **Step 5: Wire it into `main.py`**

1. Insert this directly **after** the `audit_trail` function ends (after `main.py:229`) and **before** `def _route_template`:

```python
# Login (design 2026-09-13). Added straight after audit_trail so it wraps it: the
# audit row sees the identity the session decided, not the one the browser sent.
# It stays inside request_identity (registered below, so more outer), which is
# what gives a refusal its request id. With AUTH_MODE unset it passes straight on.
from . import auth  # noqa: E402
from . import officers as _officers  # noqa: E402

auth.set_config(auth.load_config())
if auth.current_config().on:
    auth.check_officers(auth.current_config(), _officers.registry())
app.add_middleware(auth.AuthMiddleware,
                   request_id=lambda: REQUEST_ID.get(),
                   roster=lambda: _officers.registry())
```

Check: `officers.registry()` does `from . import main` and reads `main.CUSTOMERS`, which is defined at `main.py:80`, above this point, so the partial module already carries it. If `routers/today.py` already imports `officers` in a way that makes this circular, move the two imports inside the lambdas and the `if`.

2. Replace `_actor_of` (`main.py:241-253`) with:

```python
async def _actor_of(request):
    """The acting name, and WHERE it came from. Only a session is authenticated."""
    session = request.scope.get("volt_auth")
    if session:
        from . import auth
        return session["sub"], auth.audit_source(session)
    header = request.headers.get("X-Volt-Officer")
    if header:
        return header, "HEADER"
    if request.method != "GET":
        try:
            body = await request.json()
        except Exception:                              # noqa: BLE001
            body = None
        if isinstance(body, dict) and body.get("by"):
            return str(body["by"]), "BODY"
    return None, "NONE"
```

Check that `request.scope` in BaseHTTPMiddleware is the dict the ASGI middleware set. The test `test_audit_records_the_session_as_the_source` proves it.

3. Next to `app.include_router(audit_router)` (`main.py:1552`), add the import beside the other router imports and:

```python
app.include_router(login_router)
```

where the import is `from .routers.login import router as login_router`.

- [ ] **Step 6: The `ops` identity — `backend/app/officers.py:16-19`**

```python
FIXED = (
    {"uid": "settasak", "display_name_th": "settasak", "role": "MANAGER", "roles": ["SUPERVISOR", "MANAGER"]},
    {"uid": "owner", "display_name_th": "เจ้าของระบบ (owner)", "role": "OWNER", "roles": ["OWNER"]},
    # The O&M team's seat (round-3 J3-07 added OPS to the API roles; login 2026-09-13
    # gives it an identity so ops.test signs as someone the registry knows).
    {"uid": "ops", "display_name_th": "ทีมปฏิบัติการ (ops)", "role": "OPS", "roles": ["OPS"]},
)
```

`test_round2.py:296-298` reads roles by uid lookup (containment), so an extra row does not break it. That was verified while planning.

- [ ] **Step 7: Schema — `backend/app/schema.sql`**

Change line 126 to:

```sql
    actor_source    text        NOT NULL CHECK (actor_source IN ('HEADER','BODY','NONE','SESSION','TEST_ACCOUNT')),
```

and append straight after the `CREATE TABLE IF NOT EXISTS audit.entry (...)` statement:

```sql
-- Login (design 2026-09-13): a database made before login exists still carries the
-- three-value check, and CREATE TABLE IF NOT EXISTS will not touch it. Dropped and
-- re-added by name so every deploy converges on the same constraint. Postgres named
-- the inline check entry_actor_source_check. A row trigger does not block ALTER TABLE.
ALTER TABLE audit.entry DROP CONSTRAINT IF EXISTS entry_actor_source_check;
ALTER TABLE audit.entry ADD CONSTRAINT entry_actor_source_check
    CHECK (actor_source IN ('HEADER','BODY','NONE','SESSION','TEST_ACCOUNT'));
```

Check the real constraint name first: `psql "$VOLT_TEST_PG_URL" -c "select conname from pg_constraint where conrelid='audit.entry'::regclass"`. If it differs, use that name.

- [ ] **Step 8: Run the new tests, then the whole backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_auth_core.py tests/test_auth_http.py tests/test_auth_schema.py`
Expected: all PASS (the schema test PASSES with Postgres up).

Run: `cd backend && .venv/bin/python -m pytest tests/`
Expected: passed = the Task 0 backend figure + the new tests, and 0 failed. **If any existing test fails, stop.** Do not edit it; report the failing test and its output to Arina.

- [ ] **Step 9: Commit**

```bash
git log --oneline -1
git add backend/app/auth.py backend/app/routers/login.py backend/app/main.py backend/app/officers.py backend/app/schema.sql backend/tests/test_auth_http.py backend/tests/test_auth_schema.py
git commit -m "feat(auth): the session decides role and name when login is on; /v1/auth/* and the audit source"
```

---

### Task 3: Frontend — API calls, the role lock, OPS, strings

**Files:**
- Modify: `frontend/src/api.js`
- Modify: `frontend/src/components/role.jsx`
- Create: `frontend/src/components/auth.jsx`
- Modify: `frontend/src/i18n-journey.js` (EN block near `:386-393`, TH block near `:744-751`)
- Test: `frontend/src/components/role.lock.test.jsx`, `frontend/src/api.auth.test.js`

**Interfaces — Produces:**
- `api.authConfig()`, `api.authMe()`, `api.authPassword({username,password})`, `api.authGoogle({credential})`, `api.authLogout()`
- `export const AUTH_REQUIRED_EVENT = 'volt:auth-required'` in `api.js`
- `role.jsx`: `ROLES` = five roles; `lockIdentity({role, officer})`, `unlockIdentity()`, `readLocked()`, `useLocked()`
- `auth.jsx`: `readSession()`, `setSession(me|null)`, `useSession()`

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/components/role.lock.test.jsx
// Login (design 2026-09-13): a session locked to one role pins the role and name the
// API layer stamps, whatever the switcher or storage says.
import { beforeEach, describe, expect, it } from 'vitest'
import { lockIdentity, unlockIdentity, readRole, readOfficer, setRole, setOfficer, readLocked, ROLES } from './role.jsx'
import { setSession, readSession } from './auth.jsx'

beforeEach(() => {
  window.localStorage.clear()
  unlockIdentity()
  setSession(null)
  setRole('OFFICER')
  setOfficer('nantapol')
})

describe('the identity lock', () => {
  it('OPS is a role the interface knows', () => {
    expect(ROLES).toContain('OPS')
  })

  it('a lock overrides storage and refuses changes until unlocked', () => {
    lockIdentity({ role: 'MANAGER', officer: 'settasak' })
    expect(readRole()).toBe('MANAGER')
    expect(readOfficer()).toBe('settasak')
    setRole('OWNER'); setOfficer('thip')
    expect(readRole()).toBe('MANAGER')
    expect(readOfficer()).toBe('settasak')
    unlockIdentity()
    expect(readLocked()).toBeNull()
    expect(readRole()).toBe('OFFICER')
  })

  it('a lock to a name outside the hard-coded team still holds (owner, ops)', () => {
    lockIdentity({ role: 'OPS', officer: 'ops' })
    expect(readOfficer()).toBe('ops')
  })

  it('a malformed lock is ignored', () => {
    lockIdentity({ role: 'ROOT', officer: 'x' })
    expect(readLocked()).toBeNull()
  })

  it('setSession locks a fixed-role session and unlocks a switching one', () => {
    setSession({ subject: 'manager.test', kind: 'TEST', role: 'MANAGER', officer: 'settasak', can_switch: false })
    expect(readRole()).toBe('MANAGER')
    setSession({ subject: 'tester', kind: 'TEST', role: 'OFFICER', officer: 'nantapol', can_switch: true })
    expect(readLocked()).toBeNull()
    setSession(null)
    expect(readSession()).toBeNull()
  })
})
```

```js
// frontend/src/api.auth.test.js
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, AUTH_REQUIRED_EVENT } from './api.js'

beforeEach(() => { window.localStorage.clear() })
afterEach(() => { vi.unstubAllGlobals() })

function reply(status, body) {
  return vi.fn(() => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) }))
}

describe('login calls', () => {
  it('authConfig reads /v1/auth/config through the /api prefix', async () => {
    const fetchMock = reply(200, { mode: 'off' })
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.authConfig()).resolves.toEqual({ mode: 'off' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/auth/config')
  })

  it('authPassword posts the username and password', async () => {
    const fetchMock = reply(200, { subject: 'tester' })
    vi.stubGlobal('fetch', fetchMock)
    await api.authPassword({ username: 'tester', password: 'pw' })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/auth/password')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ username: 'tester', password: 'pw' })
  })

  it('a 401 auth_required anywhere announces itself once', async () => {
    vi.stubGlobal('fetch', reply(401, { code: 'auth_required' }))
    const heard = vi.fn()
    window.addEventListener(AUTH_REQUIRED_EVENT, heard)
    await expect(api.workbook()).rejects.toMatchObject({ status: 401 })
    window.removeEventListener(AUTH_REQUIRED_EVENT, heard)
    expect(heard).toHaveBeenCalledTimes(1)
  })

  it('a wrong password (login_failed) does not announce auth_required', async () => {
    vi.stubGlobal('fetch', reply(401, { code: 'login_failed' }))
    const heard = vi.fn()
    window.addEventListener(AUTH_REQUIRED_EVENT, heard)
    await expect(api.authPassword({ username: 'x', password: 'y' })).rejects.toMatchObject({ status: 401 })
    window.removeEventListener(AUTH_REQUIRED_EVENT, heard)
    expect(heard).not.toHaveBeenCalled()
  })
})
```

Before running, check that `api.workbook` exists (`grep -n "workbook:" frontend/src/api.js`). If it is named differently, use any existing GET call.

- [ ] **Step 2: Run to see them fail**

Run: `cd frontend && npx vitest run src/components/role.lock.test.jsx src/api.auth.test.js`
Expected: FAIL (`lockIdentity is not a function`, `auth.jsx` missing, `authConfig` missing).

- [ ] **Step 3: `api.js`**

After `notifyChanged` (around `api.js:37`), add:

```js
// Login (design 2026-09-13): a 401 auth_required means the session ended (idle, 8 h,
// signed out elsewhere). AuthGate listens and shows the login screen in place, so
// the URL, and the page the person was on, survives. Only that code: a wrong
// password is also a 401, and must stay on the login form.
export const AUTH_REQUIRED_EVENT = 'volt:auth-required'
function signalAuth(status, body) {
  if (status !== 401 || !body || body.code !== 'auth_required') return
  try {
    if (typeof window !== 'undefined' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new window.CustomEvent(AUTH_REQUIRED_EVENT))
    }
  } catch { /* the screen still shows the problem */ }
}
```

`AUTH_REQUIRED_EVENT` is used by `get` above its declaration. `const` in module scope is initialised before any call runs, so this is safe. In each of `get`, `post`, `send` and `postRaw`, change the throw line to:

```js
  if (!response.ok) { signalAuth(response.status, body); throw Object.assign(new Error(path), { problem: body, status: response.status }) }
```

In `exportCsv` and `exportCsvPost`, add `signalAuth(response.status, body)` right after `const body = await response.json().catch(() => null)`.

In the `api` object, next to `officers:`, add:

```js
  // Login (design 2026-09-13).
  authConfig: () => get('/v1/auth/config'),
  authMe: () => get('/v1/auth/me'),
  authPassword: (payload) => post('/v1/auth/password', payload),
  authGoogle: (payload) => post('/v1/auth/google', payload),
  authLogout: () => post('/v1/auth/logout', {}),
```

- [ ] **Step 4: `role.jsx`**

Change the header comment line and `ROLES`:

```js
// The session role (API Surface v2.3 §0): OFFICER | SUPERVISOR | MANAGER | OWNER | OPS,
...
// OPS joined 2026-09-13 (login ruling L5): the API has accepted it since round-3
// J3-07, and ops.test needs the interface to name it.
export const ROLES = ['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER', 'OPS']
```

After `const listeners = new Set()` add:

```js
// Login (design 2026-09-13): a signed-in session locked to one role. While a lock
// holds, it IS the role and the name: readRole/readOfficer return it and the setters
// refuse, so no screen and no storage value can put a different identity on the wire.
// (The server rewrites the headers anyway. This keeps the screen honest about it.)
let locked = null

export function lockIdentity(next) {
  const ok = next && ROLES.includes(next.role) && typeof next.officer === 'string' && next.officer !== ''
  locked = ok ? { role: next.role, officer: next.officer } : null
  listeners.forEach((fn) => fn())
  officerListeners.forEach((fn) => fn())
}

export function unlockIdentity() {
  if (!locked) return
  locked = null
  listeners.forEach((fn) => fn())
  officerListeners.forEach((fn) => fn())
}

export function readLocked() {
  return locked
}

export function useLocked() {
  return useSyncExternalStore(subscribe, readLocked, () => null)
}
```

(`officerListeners` is declared further down with `const`. It is only touched when `lockIdentity` runs, after the module has finished loading, so the order is safe. `subscribe` is declared further down as a function declaration, which is hoisted.)

First line of `readRole`: `if (locked) return locked.role`. First line of `setRole`: `if (locked) return`. First line of `readOfficer`: `if (locked) return locked.officer`. First line of `setOfficer`: `if (locked) return`.

- [ ] **Step 5: `components/auth.jsx`**

```jsx
import { useSyncExternalStore } from 'react'
import { lockIdentity, unlockIdentity } from './role.jsx'

// The signed-in session as /v1/auth/me served it: {subject, kind, role, officer,
// can_switch, expires_at}, or null. A module store like the role, because the top
// bar, the gate and the identity menu all read it and none of them owns it.
let session = null
const listeners = new Set()

export function readSession() {
  return session
}

export function setSession(next) {
  session = next && typeof next === 'object' ? next : null
  if (session && !session.can_switch) lockIdentity({ role: session.role, officer: session.officer })
  else unlockIdentity()
  listeners.forEach((fn) => fn())
}

function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function useSession() {
  return useSyncExternalStore(subscribe, readSession, () => null)
}
```

- [ ] **Step 6: Strings in `i18n-journey.js`**

In the EN block, after `'role.OWNER': 'Owner',`:

```js
  'role.OPS': 'O&M team',
  // --- Login (design 2026-09-13) ----------------------------------------------------
  'auth.title': 'Sign in to Volt Debt',
  'auth.sub': 'Use your volt.co.th Google account, or a test account.',
  'auth.google': 'Sign in with Google',
  'auth.googleOff': 'Google sign-in is not set up on this service yet.',
  'auth.googleFailed': 'The Google button could not load. Check the connection, or use a test account.',
  'auth.or': 'or',
  'auth.testTitle': 'Test account',
  'auth.username': 'Username',
  'auth.password': 'Password',
  'auth.submit': 'Sign in',
  'auth.busy': 'Signing in…',
  'auth.checking': 'Checking your session…',
  'auth.testBadge': 'TEST ACCOUNT',
  'auth.signOut': 'Sign out',
  'auth.lockedRole': 'This account works only as {role}.',
  'auth.signedInAs': 'Signed in as {who}',
```

In the TH block, after `'role.OWNER': 'เจ้าของ',`:

```js
  'role.OPS': 'ทีมปฏิบัติการ (O&M)',
  // --- Login (design 2026-09-13) ----------------------------------------------------
  'auth.title': 'เข้าสู่ระบบ Volt Debt',
  'auth.sub': 'ใช้บัญชี Google ของ volt.co.th หรือบัญชีทดสอบ',
  'auth.google': 'เข้าสู่ระบบด้วย Google',
  'auth.googleOff': 'ระบบนี้ยังไม่ได้ตั้งค่าการเข้าสู่ระบบด้วย Google',
  'auth.googleFailed': 'โหลดปุ่ม Google ไม่สำเร็จ ตรวจสอบอินเทอร์เน็ต หรือใช้บัญชีทดสอบ',
  'auth.or': 'หรือ',
  'auth.testTitle': 'บัญชีทดสอบ',
  'auth.username': 'ชื่อผู้ใช้',
  'auth.password': 'รหัสผ่าน',
  'auth.submit': 'เข้าสู่ระบบ',
  'auth.busy': 'กำลังเข้าสู่ระบบ…',
  'auth.checking': 'กำลังตรวจสอบการเข้าสู่ระบบ…',
  'auth.testBadge': 'บัญชีทดสอบ',
  'auth.signOut': 'ออกจากระบบ',
  'auth.lockedRole': 'บัญชีนี้ใช้ได้เฉพาะบทบาท {role}',
  'auth.signedInAs': 'เข้าสู่ระบบในชื่อ {who}',
```

- [ ] **Step 7: Run the new tests**

Run: `cd frontend && npx vitest run src/components/role.lock.test.jsx src/api.auth.test.js src/i18n.test.js`
Expected: PASS.

- [ ] **Step 8: Run the full frontend suite — this is where authorised edit 27 is priced**

Run: `cd frontend && npx vitest run 2>&1 | tail -40`
Expected: exactly **one** failure, `RoleSwitcher.test.jsx > offers exactly the four API roles` (line 27, `toEqual` of four roles).

**STOP GATE.** If anything else fails (for example `api.test.js`, `Shell.test.jsx`, `density.test.jsx`, a screen test using `setRole`), do not continue and do not edit any test. Write the list of failing tests with their output and bring it to Arina as the true price.

Do not commit yet; the next task spends the edit.

---

### Task 4: Authorised test edit 27

**Files:** Modify `frontend/src/components/RoleSwitcher.test.jsx:25-27`

- [ ] **Step 1: Confirm authorisation before touching the file**

Arina approved this spec with edit 27 priced at "one line" (spec §5). The true price found while planning is **one test function, two lines**: the assertion on line 27 and the test's own title on line 25, which would otherwise say "four" over a five-role list. That matches how edit 25 was spent (title changed under its quote). **Ask Arina to confirm the two-line price before this step.** If she refuses the title change, change only line 27 and leave the title.

- [ ] **Step 2: Make the edit**

```jsx
  // AUTHORISED TEST EDIT 27 (Arina, 2026-09-13, login ruling L5): OPS joins the
  // interface's roles. One test function; the assertion and this title, nothing else.
  it('offers exactly the five API roles', () => {
    renderIn('en', <RoleSwitcher />)
    expect(ROLES).toEqual(['OFFICER', 'SUPERVISOR', 'MANAGER', 'OWNER', 'OPS'])
    for (const role of ROLES) expect(screen.getByTestId(`role-${role}`)).toBeInTheDocument()
  })
```

- [ ] **Step 3: Run the full frontend suite**

Run: `cd frontend && npx vitest run 2>&1 | tail -8`
Expected: 0 failed; tests = Task 0 figure + new tests.

- [ ] **Step 4: Commit**

```bash
git log --oneline -1
git add frontend/src/api.js frontend/src/components/role.jsx frontend/src/components/auth.jsx frontend/src/i18n-journey.js frontend/src/components/role.lock.test.jsx frontend/src/api.auth.test.js frontend/src/components/RoleSwitcher.test.jsx
git commit -m "feat(auth): the interface learns the session — role lock, OPS, login calls (authorised test edit 27)"
```

---

### Task 5: The gate and the login screen

**Files:**
- Create: `frontend/src/components/googleScript.js`, `frontend/src/components/AuthGate.jsx`, `frontend/src/screens/Login.jsx`
- Modify: `frontend/src/main.jsx`, `frontend/src/app.css`
- Test: `frontend/src/components/AuthGate.test.jsx`, `frontend/src/screens/Login.test.jsx`

**Interfaces:**
- Consumes: `api.authConfig/authMe/authPassword/authGoogle`, `AUTH_REQUIRED_EVENT`, `setSession`.
- Produces: `<AuthGate>{children}</AuthGate>`; `<Login config onSignedIn(me) />`; `loadGoogleScript(): Promise<google|null>`.

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/components/AuthGate.test.jsx
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'

vi.mock('../api.js', () => ({
  api: { authConfig: vi.fn(), authMe: vi.fn(), authPassword: vi.fn(), authGoogle: vi.fn() },
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))

import { api } from '../api.js'
import { AuthGate } from './AuthGate.jsx'
import { readSession, setSession } from './auth.jsx'

beforeEach(() => {
  window.localStorage.clear()
  setSession(null)
  Object.values(api).forEach((fn) => fn.mockReset())
})

describe('AuthGate', () => {
  it('login off: renders the app exactly as before', async () => {
    api.authConfig.mockResolvedValue({ mode: 'off', google_client_id: null, password_enabled: false })
    renderIn('en', <AuthGate><p>the app</p></AuthGate>)
    expect(await screen.findByText('the app')).toBeInTheDocument()
    expect(api.authMe).not.toHaveBeenCalled()
  })

  it('an older API with no config route: renders the app', async () => {
    api.authConfig.mockRejectedValue(Object.assign(new Error('x'), { status: 404 }))
    renderIn('en', <AuthGate><p>the app</p></AuthGate>)
    expect(await screen.findByText('the app')).toBeInTheDocument()
  })

  it('login on and no session: the login screen, not the app', async () => {
    api.authConfig.mockResolvedValue({ mode: 'on', google_client_id: null, password_enabled: true })
    api.authMe.mockRejectedValue(Object.assign(new Error('x'), { status: 401, problem: { code: 'auth_required' } }))
    renderIn('en', <AuthGate><p>the app</p></AuthGate>)
    expect(await screen.findByRole('heading', { name: 'Sign in to Volt Debt' })).toBeInTheDocument()
    expect(screen.queryByText('the app')).toBeNull()
  })

  it('login on with a session: the app, and the session is stored', async () => {
    api.authConfig.mockResolvedValue({ mode: 'on', google_client_id: null, password_enabled: true })
    api.authMe.mockResolvedValue({ subject: 'manager.test', kind: 'TEST', role: 'MANAGER', officer: 'settasak', can_switch: false })
    renderIn('en', <AuthGate><p>the app</p></AuthGate>)
    expect(await screen.findByText('the app')).toBeInTheDocument()
    expect(readSession().subject).toBe('manager.test')
  })

  it('a session that ends mid-use brings the login screen back', async () => {
    api.authConfig.mockResolvedValue({ mode: 'on', google_client_id: null, password_enabled: true })
    api.authMe.mockResolvedValue({ subject: 'tester', kind: 'TEST', role: 'OFFICER', officer: 'nantapol', can_switch: true })
    renderIn('en', <AuthGate><p>the app</p></AuthGate>)
    await screen.findByText('the app')
    act(() => { window.dispatchEvent(new window.CustomEvent('volt:auth-required')) })
    await waitFor(() => expect(screen.queryByText('the app')).toBeNull())
    expect(readSession()).toBeNull()
  })
})
```

```jsx
// frontend/src/screens/Login.test.jsx
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'

vi.mock('../api.js', () => ({ api: { authPassword: vi.fn(), authGoogle: vi.fn() } }))
vi.mock('../components/googleScript.js', () => ({ loadGoogleScript: vi.fn(() => Promise.resolve(null)) }))

import { api } from '../api.js'
import { loadGoogleScript } from '../components/googleScript.js'
import Login from './Login.jsx'

beforeEach(() => {
  window.localStorage.clear()
  api.authPassword.mockReset(); api.authGoogle.mockReset(); loadGoogleScript.mockClear()
})

describe('Login', () => {
  it('Thai first: the title, the test-account form, and Google marked as not set up', () => {
    renderIn('th', <Login config={{ mode: 'on', google_client_id: null, password_enabled: true }} onSignedIn={() => {}} />)
    expect(screen.getByRole('heading', { name: 'เข้าสู่ระบบ Volt Debt' })).toBeInTheDocument()
    expect(screen.getByLabelText('ชื่อผู้ใช้')).toBeInTheDocument()
    expect(screen.getByLabelText('รหัสผ่าน')).toHaveAttribute('type', 'password')
    expect(screen.getByText('ระบบนี้ยังไม่ได้ตั้งค่าการเข้าสู่ระบบด้วย Google')).toBeInTheDocument()
    expect(loadGoogleScript).not.toHaveBeenCalled()
  })

  it('a right password hands the session up', async () => {
    const me = { subject: 'tester', kind: 'TEST', role: 'OFFICER', officer: 'nantapol', can_switch: true }
    api.authPassword.mockResolvedValue(me)
    const onSignedIn = vi.fn()
    renderIn('en', <Login config={{ mode: 'on', google_client_id: null, password_enabled: true }} onSignedIn={onSignedIn} />)
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: ' tester ' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(me))
    expect(api.authPassword).toHaveBeenCalledWith({ username: 'tester', password: 'pw' })
  })

  it('a refusal is shown verbatim, in Thai', async () => {
    api.authPassword.mockRejectedValue(Object.assign(new Error('x'), {
      status: 429, problem: { code: 'login_locked', error_id: 'DEBT-AUTH-429', message_th: 'ใส่รหัสผ่านผิด 5 ครั้ง ชื่อผู้ใช้นี้ถูกล็อกไว้ 15 นาที' },
    }))
    renderIn('th', <Login config={{ mode: 'on', google_client_id: null, password_enabled: true }} onSignedIn={() => {}} />)
    fireEvent.change(screen.getByLabelText('ชื่อผู้ใช้'), { target: { value: 'tester' } })
    fireEvent.change(screen.getByLabelText('รหัสผ่าน'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'เข้าสู่ระบบ' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ใส่รหัสผ่านผิด 5 ครั้ง')
  })

  it('no test accounts on this service: the form is not offered', () => {
    renderIn('en', <Login config={{ mode: 'on', google_client_id: 'c', password_enabled: false }} onSignedIn={() => {}} />)
    expect(screen.queryByLabelText('Password')).toBeNull()
  })

  it('a client id loads the Google button and its credential is posted', async () => {
    const renderButton = vi.fn()
    let callback
    loadGoogleScript.mockResolvedValue({ accounts: { id: { initialize: (o) => { callback = o.callback }, renderButton } } })
    const me = { subject: 'thip@volt.co.th', kind: 'GOOGLE', role: 'OFFICER', officer: 'thip', can_switch: false }
    api.authGoogle.mockResolvedValue(me)
    const onSignedIn = vi.fn()
    renderIn('en', <Login config={{ mode: 'on', google_client_id: 'c', password_enabled: false }} onSignedIn={onSignedIn} />)
    await waitFor(() => expect(renderButton).toHaveBeenCalled())
    callback({ credential: 'tok' })
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(me))
    expect(api.authGoogle).toHaveBeenCalledWith({ credential: 'tok' })
  })
})
```

- [ ] **Step 2: Run to see them fail**

Run: `cd frontend && npx vitest run src/components/AuthGate.test.jsx src/screens/Login.test.jsx`
Expected: FAIL (modules missing).

- [ ] **Step 3: `components/googleScript.js`**

```js
// Google Identity Services, loaded once and only by the login screen. The script is
// Google's own; nothing else on any page depends on it.
const SRC = 'https://accounts.google.com/gsi/client'
let pending = null

export function loadGoogleScript() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return Promise.resolve(null)
  if (window.google?.accounts?.id) return Promise.resolve(window.google)
  if (!pending) {
    pending = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = SRC
      script.async = true
      script.onload = () => resolve(window.google || null)
      script.onerror = () => { pending = null; reject(new Error('google identity script failed to load')) }
      document.head.appendChild(script)
    })
  }
  return pending
}
```

- [ ] **Step 4: `screens/Login.jsx`**

```jsx
import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useT } from '../prefs.jsx'
import { Problem } from '../components/Problem.jsx'
import { loadGoogleScript } from '../components/googleScript.js'

// Login (design 2026-09-13 §3.5). Two ways in: Google (the server checks the token
// and the allow-list) and a test account. A refusal is the server's own problem,
// shown verbatim; this screen decides nothing about who may enter.
export default function Login({ config, onSignedIn }) {
  const t = useT()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const [googleFailed, setGoogleFailed] = useState(false)
  const googleRef = useRef(null)
  const clientId = config?.google_client_id || null

  async function finish(promise) {
    setBusy(true)
    setProblem(null)
    try {
      onSignedIn(await promise)
    } catch (error) {
      setProblem(error?.problem || { code: 'login_failed', message_th: t('auth.googleFailed') })
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!clientId) return undefined
    let cancelled = false
    loadGoogleScript()
      .then((google) => {
        if (cancelled || !google || !googleRef.current) return
        google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => finish(api.authGoogle({ credential: response.credential })),
        })
        google.accounts.id.renderButton(googleRef.current, { theme: 'outline', size: 'large', text: 'signin_with' })
      })
      .catch(() => { if (!cancelled) setGoogleFailed(true) })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId])

  function submit(event) {
    event.preventDefault()
    finish(api.authPassword({ username: username.trim(), password }))
  }

  return (
    <main className="login" id="main">
      <section className="login__card" aria-labelledby="login-title">
        <h1 id="login-title" className="login__title">{t('auth.title')}</h1>
        <p className="login__sub">{t('auth.sub')}</p>

        {clientId
          ? <div className="login__google" ref={googleRef} data-testid="google-button" aria-label={t('auth.google')} />
          : <p className="login__note">{t('auth.googleOff')}</p>}
        {googleFailed && <p className="login__note">{t('auth.googleFailed')}</p>}

        {config?.password_enabled && (
          <form className="login__form" onSubmit={submit}>
            <p className="login__or" aria-hidden="true">{t('auth.or')}</p>
            <h2 className="login__h2">{t('auth.testTitle')}</h2>
            <label className="field">
              <span className="field__label">{t('auth.username')}</span>
              <input className="field__input" autoComplete="username" value={username}
                     onChange={(e) => setUsername(e.target.value)} required />
            </label>
            <label className="field">
              <span className="field__label">{t('auth.password')}</span>
              <input className="field__input" type="password" autoComplete="current-password" value={password}
                     onChange={(e) => setPassword(e.target.value)} required />
            </label>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? t('auth.busy') : t('auth.submit')}
            </button>
          </form>
        )}
        <Problem problem={problem} />
      </section>
    </main>
  )
}
```

Before writing, check the class names `field`, `field__label`, `field__input`, `btn--primary` exist in `app.css` (`grep -n "\.field__input\|\.btn--primary" frontend/src/app.css`). Use whatever the house form classes are.

The "Sign in" test clicks a button whose name must be exactly `Sign in` while not busy. The `required` attribute does not block `fireEvent.click` submission in jsdom. If it does, fire `submit` on the form instead in the test. That is a new test, so changing it costs nothing.

- [ ] **Step 5: `components/AuthGate.jsx`**

```jsx
import { useCallback, useEffect, useState } from 'react'
import { api, AUTH_REQUIRED_EVENT } from '../api.js'
import { useT } from '../prefs.jsx'
import { setSession } from './auth.jsx'
import Login from '../screens/Login.jsx'

// Login (design 2026-09-13). The server says whether login is on. Off, or an older
// API with no /v1/auth/config, renders the app exactly as before. The gate never
// guesses "on": the server refuses every /v1 call without a session anyway, and that
// refusal (AUTH_REQUIRED_EVENT) brings this screen back.
export function AuthGate({ children }) {
  const t = useT()
  const [phase, setPhase] = useState('checking')
  const [config, setConfig] = useState(null)

  const check = useCallback(async () => {
    let served
    try {
      served = await api.authConfig()
    } catch {
      setSession(null); setPhase('open'); return
    }
    setConfig(served)
    if (!served || served.mode !== 'on') { setSession(null); setPhase('open'); return }
    try {
      setSession(await api.authMe())
      setPhase('in')
    } catch {
      setSession(null)
      setPhase('login')
    }
  }, [])

  useEffect(() => { check() }, [check])

  useEffect(() => {
    const onRequired = () => { setSession(null); setPhase('login') }
    window.addEventListener(AUTH_REQUIRED_EVENT, onRequired)
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onRequired)
  }, [])

  if (phase === 'checking') return <p className="login__checking" role="status">{t('auth.checking')}</p>
  if (phase === 'login') {
    return <Login config={config} onSignedIn={(me) => { setSession(me); setPhase('in') }} />
  }
  return children
}
```

- [ ] **Step 6: `main.jsx`**

```jsx
import { AuthGate } from './components/AuthGate.jsx'
...
      <BrowserRouter>
        <AuthGate>
          <App />
        </AuthGate>
      </BrowserRouter>
```

- [ ] **Step 7: CSS — append to `frontend/src/app.css`** (use the token names already in `tokens.css`; check with `grep -n "^  --" frontend/src/tokens.css | head -40` and substitute the real names)

```css
/* Login (design 2026-09-13) */
.login { min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; background: var(--bg); }
.login__card { width: 100%; max-width: 420px; display: grid; gap: 16px; padding: 32px 24px;
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }
.login__title { margin: 0; font-size: 1.5rem; }
.login__sub, .login__note { margin: 0; color: var(--ink-2); }
.login__google { min-height: 44px; }
.login__form { display: grid; gap: 12px; }
.login__or { margin: 0; text-align: center; color: var(--ink-2); }
.login__h2 { margin: 0; font-size: 1rem; }
.login__checking { padding: 24px 16px; }
.topbar__test { padding: 2px 8px; border-radius: 999px; font-size: .75rem; font-weight: 700;
  background: var(--warn-bg); color: var(--warn-ink); }
```

- [ ] **Step 8: Run the tests, then the whole frontend suite**

Run: `cd frontend && npx vitest run src/components/AuthGate.test.jsx src/screens/Login.test.jsx`
Expected: PASS.
Run: `cd frontend && npx vitest run 2>&1 | tail -8`
Expected: 0 failed.

- [ ] **Step 9: Commit**

```bash
git log --oneline -1
git add frontend/src/components/googleScript.js frontend/src/components/AuthGate.jsx frontend/src/screens/Login.jsx frontend/src/main.jsx frontend/src/app.css frontend/src/components/AuthGate.test.jsx frontend/src/screens/Login.test.jsx
git commit -m "feat(login): the gate and the login screen — Google button and test-account form, Thai first"
```

---

### Task 6: Identity menu, TEST ACCOUNT badge, audit badges

**Files:**
- Modify: `frontend/src/components/RoleSwitcher.jsx` (`IdentityMenu`)
- Modify: `frontend/src/components/Shell.jsx:343-344`
- Modify: `frontend/src/screens/AuditLog.jsx:159-171`
- Modify: `frontend/src/i18n-admin.js` (EN near `:540`, TH near `:1030`)
- Test: `frontend/src/components/IdentityMenu.session.test.jsx`, `frontend/src/screens/AuditLog.session.test.jsx`

- [ ] **Step 1: Write the failing tests**

```jsx
// frontend/src/components/IdentityMenu.session.test.jsx
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderIn } from '../test-utils.jsx'

vi.mock('../api.js', () => ({
  api: { officers: vi.fn(() => Promise.resolve({ officers: [] })), authLogout: vi.fn(() => Promise.resolve({ signed_out: true })) },
  AUTH_REQUIRED_EVENT: 'volt:auth-required',
}))

import { api } from '../api.js'
import { IdentityMenu } from './RoleSwitcher.jsx'
import { setSession, readSession } from './auth.jsx'
import { setRole, setOfficer } from './role.jsx'

beforeEach(() => {
  window.localStorage.clear()
  setSession(null); setRole('OFFICER'); setOfficer('nantapol')
  api.authLogout.mockClear()
})

describe('IdentityMenu with a session', () => {
  it('no session: the switchers as before and no sign-out', () => {
    renderIn('en', <IdentityMenu />)
    fireEvent.click(screen.getByTestId('identity-menu'))
    expect(screen.getByTestId('role-OFFICER')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
  })

  it('a locked session: the role stated, no switchers, and sign out', async () => {
    setSession({ subject: 'manager.test', kind: 'TEST', role: 'MANAGER', officer: 'settasak', can_switch: false })
    renderIn('en', <IdentityMenu />)
    fireEvent.click(screen.getByTestId('identity-menu'))
    expect(screen.getByText('This account works only as Manager.')).toBeInTheDocument()
    expect(screen.queryByTestId('role-OWNER')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(api.authLogout).toHaveBeenCalled())
    await waitFor(() => expect(readSession()).toBeNull())
  })

  it('a switching session keeps the switchers, OPS included', () => {
    setSession({ subject: 'tester', kind: 'TEST', role: 'OFFICER', officer: 'nantapol', can_switch: true })
    renderIn('en', <IdentityMenu />)
    fireEvent.click(screen.getByTestId('identity-menu'))
    expect(screen.getByTestId('role-OPS')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })
})
```

Check the trigger test id and how `Popover` opens (`grep -n "testid" frontend/src/components/Popover.jsx`). If the clickable element's testid differs (for example `identity-menu-trigger`), use that one.

```jsx
// frontend/src/screens/AuditLog.session.test.jsx
// Login (design 2026-09-13): a signed-in actor is no longer "claimed"; a test
// account's act says so.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'

const row = (seq, source, who) => ({
  seq, at: '2026-09-13T03:00:00Z', business_date: '2026-09-13', actor_claimed: who, actor_source: source,
  session_id: 's', request_id: 'r', verb: 'POST', route_template: '/v1/x', act: 'DC_STATUS_SET',
  subject_type: null, subject_uid: null, detail: {}, outcome: 'OK', status: 200, error_code: null,
})

vi.mock('../api.js', () => ({
  api: {
    audit: vi.fn(() => Promise.resolve({
      entries: [row(3, 'SESSION', 'thip@volt.co.th'), row(2, 'TEST_ACCOUNT', 'manager.test'), row(1, 'HEADER', 'nantapol')],
      meta: { actors: ['thip@volt.co.th', 'manager.test', 'nantapol'] },
    })),
    auditVerify: vi.fn(() => Promise.resolve({ intact: true, complete: true })),
  },
}))

import AuditLog from './AuditLog.jsx'

beforeEach(() => { window.localStorage.clear() })

describe('audit badges by source', () => {
  it('SESSION: no badge · TEST_ACCOUNT: test badge · HEADER: claimed', async () => {
    renderIn('en', <MemoryRouter><AuditLog /></MemoryRouter>)
    expect(await screen.findByTestId('audit-claimed-1')).toBeInTheDocument()
    expect(screen.queryByTestId('audit-claimed-3')).toBeNull()
    expect(screen.queryByTestId('audit-claimed-2')).toBeNull()
    expect(screen.getByTestId('audit-test-2')).toHaveTextContent('test account')
  })
})
```

Before running, compare the mock shapes with `AuditLog.test.jsx:1-60` and copy its exact `api.audit` / `auditVerify` response shape, so the screen renders.

- [ ] **Step 2: Run to see them fail**

Run: `cd frontend && npx vitest run src/components/IdentityMenu.session.test.jsx src/screens/AuditLog.session.test.jsx`
Expected: FAIL.

- [ ] **Step 3: `IdentityMenu` in `RoleSwitcher.jsx`**

Imports:

```jsx
import { api, AUTH_REQUIRED_EVENT } from '../api.js'
import { setSession, useSession } from './auth.jsx'
```

(Replace the existing `import { api } from '../api.js'`.) Replace the body of the popover inside `IdentityMenu`:

```jsx
      <p className="pop__title">{t('shell.identityHint')}</p>
      {session && !session.can_switch
        ? <p className="identity__locked" data-testid="identity-locked">{t('auth.lockedRole', { role: roleLabel })}</p>
        : (<><RoleSwitcher /><OfficerSwitcher /></>)}
      {session && (
        <>
          <p className="identity__subject">{t('auth.signedInAs', { who: session.subject })}</p>
          <button type="button" className="btn btn--sm" onClick={signOut}>{t('auth.signOut')}</button>
        </>
      )}
```

and at the top of `IdentityMenu`:

```jsx
  const session = useSession()
  function signOut() {
    Promise.resolve()
      .then(() => api.authLogout())
      .catch(() => { /* the cookie may already be gone; signing out locally still holds */ })
      .finally(() => {
        setSession(null)
        try { window.dispatchEvent(new window.CustomEvent(AUTH_REQUIRED_EVENT)) } catch { /* gate re-checks on next call */ }
      })
  }
```

- [ ] **Step 4: TEST ACCOUNT badge in `Shell.jsx`**

Import `import { useSession } from './auth.jsx'`, read `const session = useSession()` at the top of the component, and just before `<IdentityMenu />`:

```jsx
          {session?.kind === 'TEST' && (
            <span className="topbar__test" data-testid="test-account-badge">{t('auth.testBadge')}</span>
          )}
```

- [ ] **Step 5: `AuditLog.jsx` badge by source**

Replace the claimed-badge pair (`:167-170`) with:

```jsx
                {e.actor_source === 'TEST_ACCOUNT' && (
                  <span className="audit__claimed audit__test" data-testid={`audit-test-${e.seq}`}>{t('audit.testAccount')}</span>
                )}
                {e.actor_source !== 'SESSION' && e.actor_source !== 'TEST_ACCOUNT' && (
                  <>
                    <span className="audit__claimed" data-testid={`audit-claimed-${e.seq}`}
                          title={t('audit.claimedWhy')}
                          aria-describedby={`audit-claimed-why-${e.seq}`}>{t('audit.claimed')}</span>
                    <span id={`audit-claimed-why-${e.seq}`} className="sr-only">{t('audit.claimedWhy')}</span>
                  </>
                )}
```

Update the comment above it: "Removed only for a signed-in session (login, 2026-09-13). A header or body name is still a claim." Also update header comment item 1 at `AuditLog.jsx:11` in the same spirit.

`i18n-admin.js`: EN `'audit.testAccount': 'test account',`; TH `'audit.testAccount': 'บัญชีทดสอบ',`.

- [ ] **Step 6: Run the new tests and the whole frontend suite**

Run: `cd frontend && npx vitest run 2>&1 | tail -8`
Expected: 0 failed. `AuditLog.test.jsx`'s claimed-badge test still passes (its rows are `HEADER`). `Shell.test.jsx` still passes (no session). If either fails, stop and report; do not edit.

- [ ] **Step 7: Commit**

```bash
git log --oneline -1
git add frontend/src/components/RoleSwitcher.jsx frontend/src/components/Shell.jsx frontend/src/screens/AuditLog.jsx frontend/src/i18n-admin.js frontend/src/components/IdentityMenu.session.test.jsx frontend/src/screens/AuditLog.session.test.jsx
git commit -m "feat(login): sign out, a locked identity stated plainly, TEST ACCOUNT marked in the bar and the log"
```

---

### Task 7: Test accounts, secrets and deploy

**Files:**
- Create: `scripts/guides/make_test_accounts.py`
- Modify: `scripts/push_secrets.sh`, `scripts/deploy_gcp.sh`, `.gitignore`

- [ ] **Step 1: `scripts/guides/make_test_accounts.py`**

```python
#!/usr/bin/env python3
"""Make the six test accounts (login design 2026-09-13 §3.4).

  backend/.venv/bin/python scripts/guides/make_test_accounts.py            # new passwords
  backend/.venv/bin/python scripts/guides/make_test_accounts.py --keep     # re-hash the saved ones

Writes:
  ~/.volt-test-accounts.json   plain passwords, mode 600, OUTSIDE the repo. Read only by
                               build_login_guide.py for the vault copy.
  backend/.env                 AUTH_TEST_ACCOUNTS (hashes only), AUTH_ALLOW_TEST_ACCOUNTS,
                               and AUTH_SESSION_SECRET if it is not already there.
                               NEVER AUTH_MODE: the test suite reads this file.

Prints the usernames, never the passwords.
"""
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import auth  # noqa: E402

PLAIN = Path.home() / ".volt-test-accounts.json"
ENV_FILE = ROOT / "backend" / ".env"

ACCOUNTS = (
    ("tester", "ANY", None),
    ("officer.test", "OFFICER", "nantapol"),
    ("supervisor.test", "SUPERVISOR", "settasak"),
    ("manager.test", "MANAGER", "settasak"),
    ("owner.test", "OWNER", "owner"),
    ("ops.test", "OPS", "ops"),
)


def _set_env_lines(path, values):
    lines = path.read_text().splitlines() if path.exists() else []
    keys = set(values)
    kept = [line for line in lines if line.split("=", 1)[0].strip() not in keys]
    kept += ["%s=%s" % (k, v) for k, v in values.items()]
    path.write_text("\n".join(kept) + "\n")


def main():
    keep = "--keep" in sys.argv
    if keep:
        plain = json.loads(PLAIN.read_text())
    else:
        plain = {user: secrets.token_urlsafe(12) for user, _role, _officer in ACCOUNTS}
        PLAIN.write_text(json.dumps(plain, indent=2))
        os.chmod(PLAIN, 0o600)

    hashed = {user: {"hash": auth.hash_password(plain[user]), "role": role, "officer": officer}
              for user, role, officer in ACCOUNTS}
    values = {"AUTH_TEST_ACCOUNTS": json.dumps(hashed, separators=(",", ":")),
              "AUTH_ALLOW_TEST_ACCOUNTS": "true"}
    existing = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    if "AUTH_SESSION_SECRET=" not in existing:
        values["AUTH_SESSION_SECRET"] = secrets.token_urlsafe(48)
    _set_env_lines(ENV_FILE, values)

    print("Accounts written (hashes in %s, passwords in %s):" % (ENV_FILE, PLAIN))
    for user, role, officer in ACCOUNTS:
        print("  %-16s %-10s %s" % (user, role, officer or "(chooses)"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and check what it wrote**

Run: `backend/.venv/bin/python scripts/guides/make_test_accounts.py`
Expected: six usernames printed and no password on the terminal.
Run: `grep -c "^AUTH_MODE" backend/.env; ls -l ~/.volt-test-accounts.json; git status --short backend/.env`
Expected: `0`; `-rw-------`; nothing (`.env` is gitignored).

- [ ] **Step 3: Prove login works end to end on a real server**

```bash
( cd backend && exec env AUTH_MODE=on AUTH_COOKIE_SECURE=false .venv/bin/uvicorn app.main:app --port 8098 --log-level warning ) &
API_PID=$!
for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8098/healthz >/dev/null && break; sleep 0.25; done
PW=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.volt-test-accounts.json')))['manager.test'])")
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8098/v1/workbook            # expect 401
curl -s -c /tmp/claude-jar -H 'Content-Type: application/json' \
  -d "{\"username\":\"manager.test\",\"password\":\"$PW\"}" http://127.0.0.1:8098/v1/auth/password   # expect role MANAGER
curl -s -b /tmp/claude-jar -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8098/v1/workbook   # expect 200
kill "$API_PID"; wait "$API_PID" 2>/dev/null; rm -f /tmp/claude-jar
```

Expected: `401`, a JSON body with `"role":"MANAGER"`, then `200`. Repeat the login for each of the six accounts (loop over the JSON keys) and check that each role matches the table.

- [ ] **Step 4: `push_secrets.sh`**

Change `NAMES` to add `AUTH_SESSION_SECRET AUTH_TEST_ACCOUNTS AUTH_ALLOWLIST GOOGLE_CLIENT_ID`. In the `--apply` branch, before `versions add`, create the secret if it does not exist:

```bash
    gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1 \
      || gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic >/dev/null
```

Update the header comment: "seven secret values" → "the secret values (integrations + login)".

- [ ] **Step 5: `deploy_gcp.sh`**

Straight after the `Attaching Cloud SQL, the secrets, and DATABASE_URL` update command, add:

```bash
say "Login (design 2026-09-13)"
# Only secrets that HOLD a version are wired; --update-secrets on an empty secret
# fails the whole update. GOOGLE_CLIENT_ID stays empty until the OAuth Web client
# exists, and until then the login page offers test accounts only.
AUTH_SECRETS=""
for name in AUTH_SESSION_SECRET AUTH_TEST_ACCOUNTS AUTH_ALLOWLIST GOOGLE_CLIENT_ID; do
  if gcloud secrets versions list "$name" --project "$PROJECT" --limit 1 --format='value(name)' 2>/dev/null | grep -q .; then
    AUTH_SECRETS="${AUTH_SECRETS:+$AUTH_SECRETS,}$name=$name:latest"
  else
    echo "  $name: no version — not wired"
  fi
done
if printf '%s' "$AUTH_SECRETS" | grep -q "AUTH_SESSION_SECRET="; then
  gcloud run services update "$SERVICE" --region "$REGION" \
    --update-secrets "$AUTH_SECRETS" \
    --update-env-vars "AUTH_MODE=on,AUTH_ALLOW_TEST_ACCOUNTS=true" \
    --quiet
else
  printf '\033[33m  SKIPPED — AUTH_SESSION_SECRET has no version; login stays off.\033[0m\n'
fi
```

Add to the final `Access` line a login status: `Login    $(printf '%s' "$AUTH_SECRETS" | grep -q AUTH_SESSION_SECRET= && echo "on — app login page after IAP" || echo "off")`.

- [ ] **Step 6: Syntax-check both scripts and do a dry run**

Run: `bash -n scripts/push_secrets.sh && bash -n scripts/deploy_gcp.sh && PROJECT=dept-collection-508109 ./scripts/push_secrets.sh`
Expected: no syntax error; the dry run lists the new names with byte lengths (GOOGLE_CLIENT_ID and AUTH_ALLOWLIST show `EMPTY — skipped`).

Do **not** run `--apply` or `deploy_gcp.sh`. Those touch GCP and are Arina's call.

- [ ] **Step 7: `.gitignore`**

The file already has uncommitted changes from other work. Append the lines, then stage **only this hunk** with `git add -p .gitignore`:

```gitignore
# Login tester guide (design 2026-09-13): the copy WITH passwords lives in the vault only.
docs/guides/*with-passwords*
scripts/guides/.venv/
```

- [ ] **Step 8: Commit**

```bash
git log --oneline -1
git add scripts/guides/make_test_accounts.py scripts/push_secrets.sh scripts/deploy_gcp.sh
git add -p .gitignore
git commit -m "chore(login): six test accounts made locally, auth secrets pushed and wired only when they exist"
```

---

### Task 8: The guidebook

**Files:**
- Create: `scripts/guides/role_matrix.py`, `scripts/guides/build_login_guide.py`, `scripts/guides/test_guides.py`
- Create (built): `docs/guides/login-tester-guide.docx`
- Create (vault, outside git): `~/Documents/Obsidian Vault/Debt modules (self build)/06 - Login Tester Guide (with passwords).docx`, `06 - Login Tester Guide.md`; modify `00 - README & Source Map.md`

- [ ] **Step 1: Make the tool venv**

Run: `uv venv scripts/guides/.venv --python 3.12 && uv pip install --python scripts/guides/.venv/bin/python python-docx==1.1.2 pytest`
Expected: installs.

- [ ] **Step 2: `scripts/guides/role_matrix.py` — who can do what, each row citing the code**

```python
"""Who can see and do what, per role — the source for the guide's checklists.

Every row cites the code that decides it (file, line, and a literal `needle` that
must appear within 3 lines of it). test_guides.py opens each citation, so when the
code moves, the guide's build fails instead of quietly going stale.
"""
ROLES = ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS")
ALL = ROLES

# (screen_th, screen_en, what_th, what_en, allowed_roles, file, line, needle)
ROWS = (
    ("วันนี้", "Today", "เห็นรายการงานของตัวเอง", "See your own work list",
     ALL, "frontend/src/screens/Today.jsx", 147, "NEEDLE"),
    ("วันนี้", "Today", "มุมมองหัวหน้า มอบหมายงาน และภาระงานของทีม", "Lead view, assign work, team workload",
     ("SUPERVISOR", "MANAGER", "OWNER"), "frontend/src/screens/Today.jsx", 286, "NEEDLE"),
    ("รอตรวจ", "Review queue", "ตอบรายการรอตรวจ", "Answer a review",
     ("SUPERVISOR", "MANAGER", "OWNER"), "frontend/src/screens/ReviewQueue.jsx", 19, "NEEDLE"),
    ("เงินเข้าและ PEAK", "Payments", "ออกใบลดหนี้", "Issue a credit note",
     ("MANAGER", "OWNER"), "frontend/src/screens/Payments.jsx", 21, "NEEDLE"),
    ("เงินเข้าและ PEAK", "Payments", "ปุ่มเฉพาะเจ้าของ", "Owner-only stub action",
     ("OWNER",), "frontend/src/screens/Payments.jsx", 418, "NEEDLE"),
    ("ติดตามหนี้เสีย", "Recovery", "อนุมัติและกำหนดประเภท", "Approve and set the type",
     ("MANAGER", "OWNER"), "frontend/src/screens/Recovery.jsx", 52, "NEEDLE"),
    ("รายงาน", "Reports", "ตั้งเป้าหมาย", "Set targets",
     ("MANAGER", "OWNER"), "frontend/src/components/role.jsx", 20, "canSetTargets"),
    ("ตั้งค่า", "Settings", "แก้ไขค่าตั้ง", "Edit settings",
     ("MANAGER", "OWNER"), "frontend/src/screens/Settings.jsx", 28, "NEEDLE"),
    ("ตั้งค่า", "Settings", "มอบหมายเจ้าหน้าที่", "Assign officers",
     ("SUPERVISOR", "MANAGER", "OWNER"), "frontend/src/screens/Settings.jsx", 222, "NEEDLE"),
    ("ลูกค้า", "Customer case", "สั่งตัดไฟ / คืนไฟ", "Execute / restore a power cut",
     ("SUPERVISOR", "MANAGER", "OWNER", "OPS"), "backend/app/cases.py", 1401, "POWER_EXECUTE_ROLES"),
    ("ลูกค้า", "Customer case", "อนุมัติการตัดไฟ", "Approve a power cut",
     ("OWNER",), "backend/app/config.py", 210, "power_restriction_approver"),
    ("ลูกค้า", "Customer case", "บันทึกการติดต่อเกินโควตาวันนี้", "Log a contact past today's slot",
     ("MANAGER", "OWNER"), "backend/app/collections/contact.py", 66, "OVERRIDE_ROLES"),
    ("แหล่งข้อมูล", "Data sources", "ส่วนของผู้จัดการขึ้นไป", "Manager-and-above section",
     ("MANAGER", "OWNER"), "frontend/src/screens/DataSourcesMigration.jsx", 35, "NEEDLE"),
    ("บันทึกการกระทำ", "Action log", "เปิดดูบันทึกทั้งหมด", "Read the whole log",
     ALL, "backend/app/routers/audit.py", 45, "NEEDLE"),
)
```

**Fill every `"NEEDLE"`** by opening each cited line (`sed -n '<line-3>,<line+3>p' <file>`) and copying a short literal from it that names the gate (for example `role === 'OWNER'`). While there, correct the line, the roles and the wording to what the code actually does; the table above was taken from a code sweep and has not been re-read line by line. Add rows for any gate found at the other sites the sweep listed: `Today.jsx:469,706,823`, `ReviewQueue.jsx:119,320`, `Payments.jsx:337`, `Recovery.jsx:164`, `Dashboard.jsx:483`, `Settings.jsx:29,271`, `CustomerCase.jsx:356,365,1162`, `DataSourcesMigration.jsx:33`, `cases.py:819,1173,1203,1246,1387,1424`, `routers/settings.py:31-35`, `config.py:233`. The test in Step 3 refuses any leftover `NEEDLE`.

- [ ] **Step 3: `scripts/guides/test_guides.py`**

```python
"""The guide stays true to the code, and the committed copy carries no password."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import role_matrix  # noqa: E402


@pytest.mark.parametrize("row", role_matrix.ROWS, ids=lambda r: "%s:%s" % (r[5], r[6]))
def test_every_citation_still_says_what_the_guide_says(row):
    *_text, allowed, file, line, needle = row
    assert needle != "NEEDLE", "fill the needle for %s:%s" % (file, line)
    assert set(allowed) <= set(role_matrix.ROLES)
    lines = (ROOT / file).read_text(encoding="utf-8").splitlines()
    window = "\n".join(lines[max(0, line - 4): line + 3])
    assert needle in window, "%s:%s no longer contains %r" % (file, line, needle)


def test_the_repo_build_has_no_password(tmp_path):
    fake = tmp_path / "accounts.json"
    fake.write_text(json.dumps({u: "PW-%s-SECRET" % u for u in
                                ["tester", "officer.test", "supervisor.test", "manager.test", "owner.test", "ops.test"]}))
    out = tmp_path / "repo.docx"
    subprocess.run([sys.executable, str(HERE / "build_login_guide.py"), "--accounts", str(fake),
                    "--repo-out", str(out), "--vault-out", str(tmp_path / "vault.docx")], check=True)
    import zipfile
    repo_xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    vault_xml = zipfile.ZipFile(tmp_path / "vault.docx").read("word/document.xml").decode("utf-8")
    assert "SECRET" not in repo_xml
    assert "PW-manager.test-SECRET" in vault_xml
```

- [ ] **Step 4: Run the tests to see them fail**

Run: `scripts/guides/.venv/bin/python -m pytest scripts/guides/test_guides.py -q`
Expected: FAIL (NEEDLEs unfilled, builder missing). Fill the NEEDLEs (Step 2) until the citation tests pass.

- [ ] **Step 5: `scripts/guides/build_login_guide.py`**

```python
#!/usr/bin/env python3
"""Build the login tester guide (design 2026-09-13 §4) as two .docx files from one source.

  scripts/guides/.venv/bin/python scripts/guides/build_login_guide.py

  --repo-out   docs/guides/login-tester-guide.docx       (committed; password cells masked)
  --vault-out  <vault>/06 - Login Tester Guide (with passwords).docx
  --accounts   ~/.volt-test-accounts.json                (from make_test_accounts.py)
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import role_matrix  # noqa: E402

VERSION = "1.0"
VAULT = Path.home() / "Documents" / "Obsidian Vault" / "Debt modules (self build)"
FONT = "Sarabun"
MASK = "ดูฉบับในคลังเอกสาร (vault copy)"
ROLE_TH = {"OFFICER": "เจ้าหน้าที่", "SUPERVISOR": "หัวหน้างาน", "MANAGER": "ผู้จัดการ",
           "OWNER": "เจ้าของ", "OPS": "ทีมปฏิบัติการ (O&M)"}
ACCOUNTS = (
    ("tester", "ทุกบทบาท (สลับได้) · any role", "เลือกเอง · chooses"),
    ("officer.test", "OFFICER", "nantapol"),
    ("supervisor.test", "SUPERVISOR", "settasak"),
    ("manager.test", "MANAGER", "settasak"),
    ("owner.test", "OWNER", "owner"),
    ("ops.test", "OPS", "ops"),
)
AMBER = "F5A524"


# --- template ------------------------------------------------------------------------

def _font(run, size=None, bold=None, color=None):
    run.font.name = FONT
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:cs"), FONT)
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def _shade(cell, hex_fill):
    props = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    props.append(shd)


def _page_number(paragraph):
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)
    _font(run, 9)


def new_document():
    doc = Document()
    section = doc.sections[0]
    section.page_height, section.page_width = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(2.2))
    for name in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Title"):
        style = doc.styles[name]
        style.font.name = FONT
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:cs"), FONT)
    doc.styles["Normal"].font.size = Pt(11)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(footer.add_run("Volt Debt · ข้อมูลทดสอบ / Test data · หน้า "), 9)
    _page_number(footer)
    return doc


def heading(doc, th, en, level=1):
    p = doc.add_heading(level=level)
    _font(p.add_run(th))
    sub = doc.add_paragraph()
    _font(sub.add_run(en), 10, color="666666")


def para(doc, th, en=None):
    p = doc.add_paragraph()
    _font(p.add_run(th))
    if en:
        q = doc.add_paragraph()
        _font(q.add_run(en), 10, color="666666")


def steps(doc, items):
    for th, en in items:
        p = doc.add_paragraph(style="List Number")
        _font(p.add_run(th))
        _font(p.add_run("\n" + en), 10, color="666666")


def table(doc, header, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, text in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        _font(cell.paragraphs[0].add_run(text), 10, bold=True)
        _shade(cell, AMBER)
    for row in rows:
        cells = t.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = ""
            _font(cells[i].paragraphs[0].add_run(str(text)), 10)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


# --- content ---------------------------------------------------------------------------

def build(passwords, with_passwords):
    doc = new_document()
    title = doc.add_paragraph()
    _font(title.add_run("คู่มือการเข้าสู่ระบบและบัญชีทดสอบ"), 24, bold=True)
    _font(doc.add_paragraph().add_run("Volt Debt — Login and Test Account Guide"), 14, color="666666")
    _font(doc.add_paragraph().add_run("ฉบับ %s · %s%s" % (
        VERSION, date.today().isoformat(), " · มีรหัสผ่าน — ห้ามส่งต่อ" if with_passwords else "")), 11)
    doc.add_page_break()

    heading(doc, "ประวัติเอกสาร", "Document history")
    table(doc, ["ฉบับ · Version", "วันที่ · Date", "เปลี่ยนแปลง · Change"],
          [[VERSION, date.today().isoformat(), "ฉบับแรก · first issue (design 2026-09-13)"]], [3, 3, 11])

    heading(doc, "1. การเข้าสู่ระบบคืออะไร", "1. What the login is")
    para(doc, "บนระบบทดสอบ (staging) มีสองประตูต่อกัน ประตูแรกคือ Google (IAP) ให้เข้าได้เฉพาะบัญชี volt.co.th "
              "ประตูที่สองคือหน้าเข้าสู่ระบบของแอป ที่ใช้ Google หรือบัญชีทดสอบก็ได้",
         "On staging there are two gates. First Google (IAP) lets in volt.co.th accounts only. "
         "Then the app's own login page, with Google or a test account.")
    para(doc, "บนเครื่องของนักพัฒนาไม่มี IAP จะเห็นเฉพาะหน้าเข้าสู่ระบบของแอป",
         "On a developer's laptop there is no IAP; only the app's login page appears.")

    heading(doc, "2. เข้าสู่ระบบด้วย Google", "2. Signing in with Google")
    steps(doc, [
        ("เปิดลิงก์ของระบบ แล้วเลือกบัญชี volt.co.th ของคุณในหน้าของ Google", "Open the link and pick your volt.co.th account on Google's page."),
        ("ในหน้าเข้าสู่ระบบของแอป กดปุ่ม \"เข้าสู่ระบบด้วย Google\"", "On the app's login page, press \"Sign in with Google\"."),
        ("ถ้าเห็น \"บัญชี Google นี้ยังไม่ได้รับสิทธิ์ใช้ระบบ\" แปลว่าอีเมลยังไม่อยู่ในรายชื่อ ให้ขอสิทธิ์จากเจ้าของระบบ (หัวข้อ 5)",
         "\"This Google account is not on the allow-list\" means your email is not listed yet — ask the system owner (section 5)."),
    ])

    heading(doc, "3. เข้าสู่ระบบด้วยบัญชีทดสอบ", "3. Signing in with a test account")
    para(doc, "บัญชีทดสอบทุกบัญชีจะมีป้าย \"บัญชีทดสอบ\" ที่แถบด้านบน และในบันทึกการกระทำ",
         "Every test account shows a \"TEST ACCOUNT\" badge in the top bar and in the action log.")
    table(doc, ["ชื่อผู้ใช้ · Username", "บทบาท · Role", "ทำงานในชื่อ · Acts as", "รหัสผ่าน · Password"],
          [[user, role, officer, passwords.get(user, "—") if with_passwords else MASK]
           for user, role, officer in ACCOUNTS], [3.5, 4.5, 3.5, 5.5])
    para(doc, "tester สลับบทบาทได้จากเมนูชื่อที่มุมขวาบน บัญชีอื่นล็อกไว้บทบาทเดียว",
         "tester can switch roles from the identity menu, top right. The others are locked to one role.")
    para(doc, "ใส่รหัสผ่านผิด 5 ครั้งใน 15 นาที ชื่อผู้ใช้นั้นจะถูกล็อก 15 นาที ถ้าไม่ได้ใช้งาน 30 นาที หรือครบ 8 ชั่วโมง ต้องเข้าสู่ระบบใหม่",
         "5 wrong passwords in 15 minutes locks that username for 15 minutes. After 30 idle minutes, or 8 hours in all, sign in again.")

    heading(doc, "4. รายการตรวจสอบตามบทบาท", "4. Checklist by role")
    para(doc, "สำหรับแต่ละบทบาท ให้ลองทุกแถว \"ควรทำได้\" คือต้องเห็นปุ่มและทำสำเร็จ \"ควรถูกปฏิเสธ\" คือต้องไม่เห็นปุ่ม หรือระบบแจ้งปฏิเสธ",
         "For each role, try every row. \"Should work\" = the control is there and succeeds. \"Should be refused\" = no control, or a refusal message.")
    for role in role_matrix.ROLES:
        heading(doc, "4.%d %s (%s)" % (role_matrix.ROLES.index(role) + 1, ROLE_TH[role], role),
                "Sign in as %s" % next(u for u, r, _o in ACCOUNTS if r == role), level=2)
        rows = []
        for screen_th, screen_en, what_th, what_en, allowed, file, line, _needle in role_matrix.ROWS:
            expect = "ควรทำได้ · should work" if role in allowed else "ควรถูกปฏิเสธ · should be refused"
            rows.append(["%s · %s" % (screen_th, screen_en), "%s · %s" % (what_th, what_en), expect, "☐"])
        table(doc, ["หน้าจอ · Screen", "สิ่งที่ลอง · Try", "ผลที่ควรได้ · Expected", "ผ่าน · Pass"], rows, [3.5, 7, 4.5, 2])

    heading(doc, "5. เพิ่มคนเข้ารายชื่อที่อนุญาต", "5. Adding a person to the allow-list")
    steps(doc, [
        ("แก้ค่า AUTH_ALLOWLIST (JSON) เพิ่มอีเมล บทบาท และชื่อเจ้าหน้าที่ เช่น {\"thip@volt.co.th\": {\"role\": \"OFFICER\", \"officer\": \"thip\"}}",
         "Edit AUTH_ALLOWLIST (JSON): add the email, role and officer name."),
        ("ชื่อเจ้าหน้าที่ต้องมีอยู่ใน /v1/officers ไม่อย่างนั้นระบบจะไม่ยอมเริ่มทำงาน", "The officer must exist in /v1/officers, or the app refuses to start."),
        ("รัน ./scripts/push_secrets.sh --apply แล้ว ./scripts/deploy_gcp.sh", "Run ./scripts/push_secrets.sh --apply, then ./scripts/deploy_gcp.sh."),
    ])

    heading(doc, "6. ปัญหาที่พบบ่อย", "6. Common problems")
    table(doc, ["อาการ · Symptom", "สาเหตุ · Cause", "ทำอย่างไร · Fix"], [
        ["กลับมาหน้าเข้าสู่ระบบเรื่อยๆ · keeps returning to login", "ไม่ได้ใช้งาน 30 นาที หรือครบ 8 ชั่วโมง · idle 30 min or 8 h", "เข้าสู่ระบบใหม่ · sign in again"],
        ["ชื่อผู้ใช้ถูกล็อก · username locked", "รหัสผ่านผิด 5 ครั้ง · 5 wrong passwords", "รอ 15 นาที · wait 15 minutes"],
        ["ไม่มีปุ่ม Google · no Google button", "ยังไม่ได้ตั้งค่า GOOGLE_CLIENT_ID · not configured", "ใช้บัญชีทดสอบ · use a test account"],
        ["หน้าปฏิเสธของ Google ก่อนเข้าแอป · Google refusal before the app", "บัญชีไม่ใช่ volt.co.th (IAP) · not a volt.co.th account", "ใช้บัญชีบริษัท · use your company account"],
        ["ปุ่มที่ควรมีไม่ขึ้น · an expected control is missing", "เข้าสู่ระบบผิดบทบาท · wrong role", "ดูบทบาทที่เมนูชื่อ มุมขวาบน · check the identity menu"],
    ], [5.5, 5.5, 6])
    return doc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts", default=str(Path.home() / ".volt-test-accounts.json"))
    parser.add_argument("--repo-out", default=str(ROOT / "docs" / "guides" / "login-tester-guide.docx"))
    parser.add_argument("--vault-out", default=str(VAULT / "06 - Login Tester Guide (with passwords).docx"))
    args = parser.parse_args()

    accounts_path = Path(args.accounts)
    passwords = json.loads(accounts_path.read_text()) if accounts_path.exists() else {}

    repo_out = Path(args.repo_out)
    repo_out.parent.mkdir(parents=True, exist_ok=True)
    build(passwords, with_passwords=False).save(repo_out)
    print("repo copy (no passwords): %s" % repo_out)

    if passwords:
        vault_out = Path(args.vault_out)
        vault_out.parent.mkdir(parents=True, exist_ok=True)
        build(passwords, with_passwords=True).save(vault_out)
        print("vault copy (with passwords): %s" % vault_out)
    else:
        print("no %s — vault copy not built" % accounts_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the guide tests**

Run: `scripts/guides/.venv/bin/python -m pytest scripts/guides/test_guides.py -q`
Expected: all PASS.

- [ ] **Step 7: Build both copies and look at them**

Run: `scripts/guides/.venv/bin/python scripts/guides/build_login_guide.py`
Expected: both paths printed.
Run: `unzip -p docs/guides/login-tester-guide.docx word/document.xml | grep -c -- "$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.volt-test-accounts.json')))['tester'])")"`
Expected: `0`, meaning no real password in the committed copy.
Convert one page to an image to check the layout: `qlmanage -t -s 1200 -o /tmp docs/guides/login-tester-guide.docx`, then Read the PNG. Check the Thai renders (Sarabun, or a fallback if not installed), the header row is shaded, and the footer has a page number.

- [ ] **Step 8: The vault note**

Create `~/Documents/Obsidian Vault/Debt modules (self build)/06 - Login Tester Guide.md`:

```markdown
# 06 - Login Tester Guide

The login tester guide, built from the repo by `scripts/guides/build_login_guide.py`.

- **With passwords (this folder only):** `06 - Login Tester Guide (with passwords).docx` — do not forward outside the team; rotate with `make_test_accounts.py` if it leaks.
- **Without passwords (in git):** `docs/guides/login-tester-guide.docx`
- Design: `docs/archive/superpowers/specs/2026-09-13-login-google-and-test-accounts-design.md`
- Your console step: an OAuth **Web client ID** in `dept-collection-508109` — see [[02 - Setup Guide - What You Do]].

Rebuild after roles or screens change: `scripts/guides/.venv/bin/python scripts/guides/build_login_guide.py`.
```

Add a line to `00 - README & Source Map.md` pointing at `[[06 - Login Tester Guide]]`, matching the style of the existing entries (read the file first). Add the OAuth Web client step to `02 - Setup Guide - What You Do.md`, next to the consent-screen step (read the file first and match its numbering):

```markdown
### Create the OAuth Web client ID (login, 2026-09-13)
1. Console → APIs & Services → Credentials → Create credentials → OAuth client ID → **Web application**.
2. Authorised JavaScript origins: the Cloud Run URL printed by `deploy_gcp.sh`, and `http://localhost:5173`.
3. Copy the client ID into `backend/.env` as `GOOGLE_CLIENT_ID=…`, then `./scripts/push_secrets.sh --apply` and `./scripts/deploy_gcp.sh`.
```

- [ ] **Step 9: Commit (repo files only)**

```bash
git log --oneline -1
git add scripts/guides/role_matrix.py scripts/guides/build_login_guide.py scripts/guides/test_guides.py docs/guides/login-tester-guide.docx
git status --short docs/guides   # must NOT list any *with-passwords* file
git commit -m "docs(guide): login tester guide — Thai first, per-role checklists cited to the code, passwords only in the vault copy"
```

---

### Task 9: Whole-harness verification and hand-off

- [ ] **Step 1: Full harness, login off (the contract)**

Run: `./scripts/verify_all.sh 2>&1 | grep -E "passed|failed|Tests|EVERYTHING|SOMETHING|checks"`
Expected: `EVERYTHING PASSED`, with backend, frontend and e2e counts at or above Task 0 plus the new tests. Paste the counts.

- [ ] **Step 2: Login on, in a real browser**

Start `cd backend && AUTH_MODE=on AUTH_COOKIE_SECURE=false .venv/bin/uvicorn app.main:app --port 8000` and `cd frontend && npm run dev`. Use the `run` skill or Chrome to open `http://localhost:5173`:
1. The login page appears, Thai first.
2. Sign in as `manager.test`: the top bar shows the TEST ACCOUNT badge and the identity menu says "works only as Manager".
3. Sign out → the login page appears.
4. Sign in as `tester`: switch to OPS; the power-cut controls on a case follow the OPS row of the matrix.
5. Open the action log: the acts show "test account", not "claimed".

Take a screenshot of the login page and of one signed-in screen.

- [ ] **Step 3: Update memory**

Update `volt-debt-project.md`'s ledger line: **edit 27 spent 2026-09-13** (RoleSwitcher five roles; true price). Add the new test contract counts. Add a pointer memory for the login work if the facts are not already in the repo: `AUTH_MODE` must never go in `backend/.env`, the passwords live at `~/.volt-test-accounts.json`, and the vault note is 06.

- [ ] **Step 4: Tell Arina**

Report the counts, the two spec refinements (audit source values, body-rewrite scope), the edit-27 true price, and the two steps only she can take: the OAuth Web client ID and `push_secrets.sh --apply` + `deploy_gcp.sh`.
