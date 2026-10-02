"""Login — Google sign-in, test accounts, and the signed session cookie.

Design: docs/archive/superpowers/specs/2026-09-13-login-google-and-test-accounts-design.md

Two modes, and the difference is the whole safety argument:

  - AUTH_MODE unset: nothing here runs. Headers are trusted exactly as before, so
    every existing test and every curl keeps working.
  - AUTH_MODE=on: every /v1 call outside OPEN_PATHS (the five sign-in routes) needs a
    valid session, and the role and acting name come from that session, not from the
    browser. A Google session also has to still be on the user list (WP10).

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
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from starlette.concurrency import run_in_threadpool

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
    session_policy: str = "cookie"


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
        # B10b ruling: every seed address passes the user list's own rule, or the service
        # refuses to start. A look-alike seed (a zero-width space, a Cyrillic letter)
        # used to sign in and then break disable() with a 500. The message names the
        # entry's position only: it reaches the service log, and an e-mail must not.
        # Imported where it is used, the way _read() imports integrations.env: this
        # module stays importable without the store's own imports (audit, db).
        from .user_accounts import valid_email
        entries = _json_or_file(raw_allow, "AUTH_ALLOWLIST").items()
        for position, (email, entry) in enumerate(entries, start=1):
            if not valid_email(email.strip().lower()):
                raise AuthConfigError(
                    "AUTH_ALLOWLIST entry %d (of %d) is not a plain ASCII e-mail address the user list "
                    "accepts; the address is not repeated here" % (position, len(entries)))
            if email.strip().lower() in allowlist:
                # "A@x" and "a@x" are one person after lower-casing; keeping whichever
                # came last would pick their role silently.
                raise AuthConfigError(
                    "AUTH_ALLOWLIST entry %d (of %d) repeats an earlier entry's address once lower-cased"
                    % (position, len(entries)))
            entry = entry if isinstance(entry, dict) else {}
            if entry.get("role") not in ROLES or not entry.get("officer"):
                # B10b fix round 1 / M2: by position, never the e-mail (edit 40).
                raise AuthConfigError("AUTH_ALLOWLIST entry %d (of %d) needs a role in %s and an officer"
                                      % (position, len(entries), ", ".join(ROLES)))
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

    policy = (_read(environ, "AUTH_SESSION_POLICY") or "cookie").strip()
    if policy not in ("cookie", "tab"):
        raise AuthConfigError("AUTH_SESSION_POLICY must be cookie or tab")
    return AuthConfig(
        on=True,
        secret=secret.encode("utf-8"),
        google_client_id=(_read(environ, "GOOGLE_CLIENT_ID") or "").strip() or None,
        allowlist=allowlist,
        test_accounts=accounts,
        cookie_secure=(_read(environ, "AUTH_COOKIE_SECURE") or "").strip().lower() != "false",
        session_policy=policy,
    )


def check_officers(config, registry_rows):
    """Every allow-list and locked test-account officer must be a registry identity."""
    known = {row["uid"] for row in registry_rows}
    # B10b fix round 1 / M2: an allow-list entry is named by its position (load_config
    # keeps the file's order), never its e-mail — this error reaches the service log.
    total = len(config.allowlist)
    named = [("AUTH_ALLOWLIST entry %d (of %d)" % (position, total), e["officer"])
             for position, e in enumerate(config.allowlist.values(), start=1)]
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
# In memory, per process. Cloud Run staging runs --max-instances 1, so one counter holds
# except for a brief overlap during a revision rollout or surge. Accepted for
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
        "expires_at": None if session.get("session_policy") == "tab" else min(session["iat"] + ABSOLUTE_SECONDS, session["seen"] + IDLE_SECONDS),
        **({"session_policy": "tab"} if session.get("session_policy") == "tab" else {}),
    }


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


def not_on_allow_list(email=None):
    # B10b fix round 1 / I2: the body never carries the address (PDPA: e-mails live in
    # records.user_account and the audit subject/actor only). `email` is accepted and
    # ignored so an older call site cannot put it back.
    return errors.Problem("not_on_allow_list", 403, "This Google account is not on the allow-list",
                          "Ask the system owner to add this email to AUTH_ALLOWLIST.",
                          "บัญชี Google นี้ยังไม่ได้รับสิทธิ์ใช้ระบบ กรุณาขอสิทธิ์จากเจ้าของระบบ",
                          "DEBT-AUTH-403")


def account_disabled():
    # Feedback Round 1 / WP10 (F13): a disabled row wins over the seed. Said plainly —
    # the person proved the address is theirs, so naming the state leaks nothing.
    return errors.Problem("account_disabled", 403, "This account is disabled",
                          "A Manager or the Owner disabled this e-mail on the user list.",
                          "บัญชีนี้ถูกปิดการใช้งาน กรุณาติดต่อผู้จัดการหรือเจ้าของระบบ",
                          "DEBT-AUTH-406")


class _WithdrawnSession(errors.Problem):
    """A refusal that also clears the session cookie wherever it is rendered — the
    middleware, GET /v1/auth/me and the user list (B10b fix round 1 / M4) — so a
    withdrawn cookie is dropped by the browser on the first refusal, not kept."""

    def response(self, instance="urn:request:unknown"):
        response = super().response(instance=instance)
        response.headers["set-cookie"] = cookie_header("", current_config(), 0)
        return response


def session_withdrawn():
    # The same code as auth_required ON PURPOSE: api.js signalAuth() brings the login
    # screen back on exactly that code, so a withdrawn session lands where an expired
    # one does. extensions.reason says which it was.
    return _WithdrawnSession("auth_required", 401, "Sign in to continue",
                             "This account's access was withdrawn or changed since it signed in.",
                             "สิทธิ์ใช้ระบบของบัญชีนี้ถูกยกเลิกหรือเปลี่ยนแปลง กรุณาเข้าสู่ระบบใหม่",
                             "DEBT-AUTH-407", extensions={"reason": "account_withdrawn"})


def google_not_configured(detail="GOOGLE_CLIENT_ID is not set on this service."):
    # Same code whichever part is missing; the detail names which one it is.
    return errors.Problem("google_not_configured", 503, "Google sign-in is not configured",
                          detail,
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

# Routes whose JSON body `role` names the ACTOR (spec plan refinement 2). Not
# /v1/config/approval-paths: there `role` is the role being configured.
ACTOR_ROLE_BODY = re.compile(
    r"^/v1/(contacts|cases/[^/]+:advance|restructures/[^/]+:approve"
    r"|manager-review/[^/]+:decide|recovery-cases/[^/]+:resolve)$")
# Exactly the routes that must answer WITHOUT a session. Was the prefix "/v1/auth/";
# Feedback Round 1 / WP10 put the user list and the profile under /v1/auth/ too, and
# those must never be reachable without one. An exact match, so "/v1/auth/users",
# "/v1/auth/me/..." and any route added under /v1/auth/ later need a session.
OPEN_PATHS = ("/v1/auth/config", "/v1/auth/password", "/v1/auth/google", "/v1/auth/me", "/v1/auth/logout")
# PEAK calls these with no session; the route checks its x-api-key instead
# (app/peak_webhooks.py). Exact paths, like OPEN_PATHS.
WEBHOOK_PATHS = ("/v1/webhooks/peak/contact", "/v1/webhooks/peak/invoice", "/v1/webhooks/peak/receipt")
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


def bearer_token(scope):
    header = _header(scope, b"authorization") or ""
    scheme, _, token = header.partition(" ")
    return token if scheme.lower() == "bearer" else None


def resolve_session(scope):
    """Single resolver shared by authentication, account state and /me."""
    if "volt_resolved_auth" in scope:
        return scope["volt_resolved_auth"]
    config = current_config()
    if config.session_policy == "tab":
        from . import tab_sessions
        session = tab_sessions.read(bearer_token(scope))
    else:
        token = _cookie(scope, COOKIE)
        session = read_session(token, config.secret) if token else None
    scope["volt_resolved_auth"] = session
    return session


def cookie_header(value, config, max_age):
    parts = ["%s=%s" % (COOKIE, value), "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=%d" % max_age]
    if config.cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


def _refresh_may_follow(start_message):
    """B10b fix round 2: the re-signed session cookie is added to a response only when
    the route did not refuse the session (401) and did not set the session cookie
    itself. A route's session_withdrawn() sends `volt_auth=; Max-Age=0`; a refreshed
    cookie appended after it would win in the browser and keep the withdrawn session."""
    if start_message.get("status") == 401:
        return False
    own = (COOKIE + "=").encode("latin-1")
    return not any(key.lower() == b"set-cookie" and value.lstrip().startswith(own)
                   for key, value in start_message.get("headers") or [])


def _route_template(scope):
    """The matched route's path, or None — main._route_template's own rule, read from
    the raw scope (Starlette puts the application in scope["app"] before any
    middleware runs). Not imported from main: main imports this module."""
    from starlette.routing import Match
    for route in getattr(scope.get("app"), "routes", ()):
        match, _child = route.matches(scope)
        if match == Match.FULL:
            return getattr(route, "path", None)
    return None


def _append_refusal(entry):
    from . import audit_store
    from .production_unit import CURRENT
    if CURRENT.get() is not None:
        CURRENT.get()["refusal_audit"] = entry
        return
    try:
        audit_store.append(entry)
    except Exception as exc:                           # noqa: BLE001
        # audit_trail's own answer to a failed append: count the miss, so
        # /v1/audit/verify reports it. By type only — the text may quote the row.
        audit_store.record_gap(type(exc).__name__)
        print("audit append failed for a session refusal: %s" % type(exc).__name__, file=sys.stderr)


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

    def __init__(self, app, request_id=lambda: "unknown", roster=lambda: [],
                 still_allowed=lambda session: True):
        self.app = app
        self.request_id = request_id
        self.roster = roster
        # WP10 (F13): asked on every request, so a disabled person's cookie stops working.
        # main.py passes user_accounts.session_allowed. The bound: on the process that
        # made the change (disable, re-invite) the very next request is refused, because
        # the write forget()s that process's cache; on any other process (another Cloud
        # Run instance or worker) the answer comes from a cache read at most
        # user_accounts.CACHE_SECONDS (30 s) earlier, so the session ends at that process's
        # first request once its last read is more than 30 s old — within 30 s of the
        # change, plus the duration of a read already in flight when it committed.
        self.still_allowed = still_allowed

    async def __call__(self, scope, receive, send):
        config = current_config()
        path = scope.get("path", "")
        if (scope["type"] != "http" or not config.on or not path.startswith("/v1/")
                or path in OPEN_PATHS or path in WEBHOOK_PATHS or scope.get("method") == "OPTIONS"):
            await self.app(scope, receive, send)
            return

        try:
            session = await run_in_threadpool(resolve_session, scope)
        except errors.Problem as problem:
            await problem.response()(scope, receive, send)
            return
        if session is None:
            response = auth_required().response(instance="urn:request:" + self.request_id())
            await response(scope, receive, send)
            return
        try:
            # In the threadpool: with a cold cache this is a database read, and it
            # must never block the event loop.
            allowed = await run_in_threadpool(self.still_allowed, session)
        except errors.Problem as problem:
            # A configured user list that does not answer (503 user_list_unreachable),
            # a table the migration never made (503 user_list_not_migrated), or the
            # store's opaque internal_error. Only the Problem is rendered: its
            # __context__ may be a driver exception whose text quotes an e-mail
            # (Postgres's "DETAIL: Failing row contains ..."), so it is never logged,
            # printed or put in the answer.
            await self._audit_refusal(scope, session, problem.status, problem.code)
            response = problem.response(instance="urn:request:" + self.request_id())
            await response(scope, receive, send)
            return
        if not allowed:
            # session_withdrawn() clears the cookie itself (Max-Age=0).
            withdrawn = session_withdrawn()
            await self._audit_refusal(scope, session, withdrawn.status, withdrawn.extensions["reason"])
            response = withdrawn.response(instance="urn:request:" + self.request_id())
            await response(scope, receive, send)
            return

        role, officer = effective_identity(session, _header(scope, b"x-volt-role"),
                                           _header(scope, b"x-volt-officer"), self.roster())
        headers = [(k, v) for k, v in scope["headers"]
                   if k not in (b"x-volt-role", b"x-volt-officer", b"content-length")]
        original_length = _header(scope, b"content-length")
        headers += [(b"x-volt-role", role.encode("latin-1")), (b"x-volt-officer", officer.encode("utf-8"))]

        # Read-and-maybe-rewrite runs for EVERY non-GET/HEAD body, regardless of
        # Content-Type: FastAPI parses JSON with no Content-Type, `Application/JSON`
        # and `application/vnd.x+json` alike, so gating this read on a literal
        # "application/json" substring let those three shapes reach the route
        # un-rewritten — a locked session's real role/identity, sent past the
        # middleware unchanged, then trusted by officers.sign()/journey.py's body
        # role. _rewrite() below is what actually decides "is this JSON, is it a
        # dict, does it carry `by`/`role`" — this layer no longer pre-judges by
        # header, so non-JSON and non-dict bodies still pass through byte-identical.
        body = None
        disconnected = False
        if scope.get("method") not in ("GET", "HEAD"):
            raw = await _read_body(receive)
            if raw is None:
                # The client went away mid-body (an http.disconnect message, not
                # http.request). Handing a half-read stream to the inner app would
                # have it wait on a receive() that will never deliver the rest, or
                # believe an empty/truncated body was the whole request. Neither
                # the framework nor a route should ever see this request.
                disconnected = True
            else:
                if os.environ.get("ENV") == "prd":
                    from . import production_permissions
                    try:
                        await run_in_threadpool(production_permissions.enforce, scope, session, raw)
                    except errors.Problem as problem:
                        await self._audit_refusal(scope, session, problem.status, problem.code)
                        await problem.response(instance="urn:request:" + self.request_id())(scope, receive, send)
                        return
                body = self._rewrite(path, raw, role, officer, scope.get("method"))
                headers.append((b"content-length", str(len(body)).encode("ascii")))
        if body is None and not disconnected and original_length is not None:
            headers.append((b"content-length", original_length.encode("ascii")))

        if disconnected:
            return

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
        # Fix-all F4: a request the screen sent on its own (X-Volt-Background: the 30 s
        # data poll, and anything sent when nobody has touched the page for a minute) is
        # not the person working, so it never moves the idle clock (SEC-002).
        background = _header(scope, b"x-volt-background") == "1"
        if config.session_policy == "cookie" and not background and now - session.get("seen", 0) >= REFRESH_AFTER:
            refreshed = dict(session, seen=int(now))
            set_cookie = cookie_header(sign_session(refreshed, config.secret), config, ABSOLUTE_SECONDS)

        async def send_with_cookie(message):
            if (set_cookie and message["type"] == "http.response.start"
                    and _refresh_may_follow(message)):
                message = dict(message)
                message["headers"] = list(message.get("headers") or []) + [(b"set-cookie", set_cookie.encode("latin-1"))]
            await send(message)

        await self.app(scope, inner_receive, send_with_cookie)

    async def _audit_refusal(self, scope, session, status, error_code):
        """Final fix F-R1 / I2: ONE REFUSED audit entry for a session this middleware
        ends — withdrawn or disabled (401, `account_withdrawn`), or refused because the
        user list could not answer (503 `user_list_unreachable` / `user_list_not_migrated`,
        or the store's `internal_error`). This middleware sits outside audit_trail, so
        without this a disabled person's replayed cookie on an act left no row at all.

        Only on a path the log records, by the log's own rule (audit.is_logged on the
        matched route template), and in the entry shape audit_trail builds, so a reader
        sees the row a refusal inside the route would have given. A request with no
        valid session cookie is not recorded here (the F-R1 ruling). The e-mail goes into
        actor_claimed only, which the PDPA rule allows; a failed append counts a gap by
        exception type and prints the type alone, because a driver's own text can quote
        the row it refused.
        """
        # Imported here, as load_config imports user_accounts: this module stays
        # importable without the store's own imports (audit, db).
        from . import audit
        from . import session as session_domain
        method = scope.get("method")
        template = _route_template(scope)
        if not audit.is_logged(method, template):
            return
        entry = {"actor_claimed": session.get("sub"), "actor_source": audit_source(session),
                 "verb": method, "route_template": template,
                 "act": "CASE_VIEWED" if method == "GET" else None,
                 "subject_type": None, "subject_uid": None, "detail": {},
                 "outcome": "REFUSED", "status": status, "error_code": error_code,
                 "session_id": session_domain.CURRENT.get(None),
                 "request_id": self.request_id()}
        # In the threadpool, like the session check: with a database this is a write.
        await run_in_threadpool(_append_refusal, entry)

    @staticmethod
    def _rewrite(path, body, role, officer, method="POST"):
        try:
            data = json.loads(body) if body else None
        except ValueError:
            return body
        if not isinstance(data, dict):
            return body
        changed = False
        # A POST is an act, and every `by` a POST route reads names who acted, so an
        # absent `by` is added: otherwise the route signs with its demo default
        # ("Nok"). A PUT/PATCH/DELETE only has a `by` it sent replaced. PUT
        # /v1/config and PUT /v1/reports/collection/{month}/targets refuse any key
        # they do not know, and the weekly targets PUT stores every key as a target.
        if "by" in data or method == "POST":
            data["by"] = officer
            changed = True
        if path == "/v1/contacts":
            # POST /v1/contacts names its actor `officer`, not `by` (main.py log_contact
            # and the review it opens). Added when absent: the route's own default is a
            # demo name, and the daily lock would be spent in that name.
            data["officer"] = officer
            changed = True
        if "role" in data and ACTOR_ROLE_BODY.match(path):
            data["role"] = role
            changed = True
        # ensure_ascii at its default (final fix F-R1 / I1): every non-ASCII character
        # leaves as a \uXXXX escape, so the bytes are ASCII and json.loads in the route
        # decodes exactly the string that arrived — Thai included. A lone surrogate (a
        # string cut mid-emoji, which JSON.stringify sends) is escaped too instead of
        # raising UnicodeEncodeError here, outside audit_trail, as a text/plain 500 with
        # no row; the route's own text_invalid now refuses it and its REFUSED row is kept.
        return json.dumps(data).encode("ascii") if changed else body
