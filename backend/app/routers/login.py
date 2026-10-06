"""/v1/auth/* — sign-in, the session, and (Feedback Round 1 / WP10) the user list.

Only auth.OPEN_PATHS answer without a session; the user list and the profile do not.

Design: docs/archive/superpowers/specs/2026-09-13-login-google-and-test-accounts-design.md §3.3
"""
from fastapi import APIRouter, Body, Header, Request
from fastapi.responses import JSONResponse

from .. import audit
from .. import auth, db, officers, user_accounts
from .today import who

router = APIRouter()

# A decoy hash, made once, at the real cost (auth.PBKDF2_ROUNDS): an unknown
# username used to refuse INSTANTLY while a known one paid 600k rounds of PBKDF2 —
# a timing oracle that told a guesser which usernames exist, defeating the one
# `login_failed` refusal `login_failed()`'s own docstring promises. Checking the
# decoy on every miss makes both paths cost the same real hash. The password
# checked against it is never a real account's, so the salt (random per call) is
# the only thing that needs to differ from any actual stored hash.
_DECOY_HASH = auth.hash_password("not-a-real-account-decoy")


def _me(session):
    """GET /v1/auth/me's body. WP11: display_name is the person's own, else the e-mail's
    user part, else the username (user_accounts.display_name_for)."""
    return dict(auth.me_payload(session), **user_accounts.display_name_for(session))


def _signed_in(session, config):
    if config.session_policy == "tab":
        from .. import tab_sessions
        session = tab_sessions.with_expiry(dict(session, session_policy="tab"))
        token = tab_sessions.issue(session)
        response = JSONResponse(dict(_me(session), session_token=token))
        response.headers["cache-control"] = "no-store"
        return response
    response = JSONResponse(_me(session))
    response.headers["set-cookie"] = auth.cookie_header(
        auth.sign_session(session, config.secret), config, auth.ABSOLUTE_SECONDS)
    return response


@router.get("/v1/auth/config")
def auth_config():
    config = auth.current_config()
    return {**({"session_policy": "tab"} if config.session_policy == "tab" else {}),
            "mode": "on" if config.on else "off",
            "google_client_id": config.google_client_id if config.on else None,
            "password_enabled": bool(config.on and config.test_accounts)}


@router.post("/v1/auth/password")
def password_login(body: dict = Body(default={})):
    audit.describe(act="SIGNED_IN", detail={"method": "PASSWORD"})
    config = auth.current_config()
    if not config.on:
        raise auth.auth_off()
    if not config.test_accounts:
        # No password identity exists in this mode. Paying PBKDF2 on arbitrary
        # names would only expose a CPU exhaustion endpoint.
        raise auth.login_failed()
    username = str((body or {}).get("username") or "").strip()
    password = str((body or {}).get("password") or "")
    if len(username) > 128 or len(password) > 1024:
        raise auth.login_failed()
    if auth.is_locked(username):
        raise auth.login_locked()
    account = config.test_accounts.get(username)
    if account is None:
        auth.check_password(password, _DECOY_HASH)  # pay the same PBKDF2 cost, discard the result
        auth.record_failure(username)
        raise auth.login_failed()
    if not auth.check_password(password, account["hash"]):
        auth.record_failure(username)
        raise auth.login_failed()
    auth.clear_failures(username)
    can_switch = account["role"] == "ANY"
    session = auth.new_session(username, "TEST", "OFFICER" if can_switch else account["role"],
                               account["officer"] or "nantapol", can_switch)
    return _signed_in(session, config)


@router.post("/v1/auth/google")
def google_login(body: dict = Body(default={})):
    audit.describe(act="SIGNED_IN", detail={"method": "GOOGLE"})
    config = auth.current_config()
    if not config.on:
        raise auth.auth_off()
    if not config.google_client_id:
        raise auth.google_not_configured()
    try:
        claims = auth.verify_google_token(str((body or {}).get("credential") or ""), config.google_client_id)
    except ImportError:
        # google-auth is not in this image. That is the service's fault, not the
        # token's: say "not configured" (503), never "your sign-in was rejected".
        raise auth.google_not_configured("google-auth is not installed on this service.")
    except Exception:                                  # noqa: BLE001
        raise auth.google_token_invalid()
    if not claims.get("email_verified"):
        raise auth.google_token_invalid()
    email = str(claims.get("email") or "").strip().lower()
    # B10b ruling: the same rule the list holds its rows to (user_accounts.valid_email,
    # never a copy of its pattern). An address that fails it — a zero-width space, a
    # Cyrillic letter, anything past ASCII — can be on no list, and is not echoed back.
    if not user_accounts.valid_email(email):
        raise auth.not_on_allow_list()
    # WP10 (F13): the managed rows are merged over the env seed on EVERY sign-in, read
    # fresh — an invitation made a moment ago on another instance counts, and a
    # disabled row wins over the seed.
    entry, state = user_accounts.allow_entry(email, config.allowlist, fresh=True)
    if state == "DISABLED":
        raise auth.account_disabled()
    if entry is None:
        raise auth.not_on_allow_list()          # fix round 1 / I2: never the address in the body
    return _signed_in(auth.new_session(email, "GOOGLE", entry["role"], entry["officer"], False), config)


@router.get("/v1/auth/me")
def me(request: Request):
    config = auth.current_config()
    if not config.on:
        raise auth.auth_off()
    session = auth.resolve_session(request.scope)
    if session is None:
        raise auth.auth_required()
    # WP10: /me is open (the gate calls it before anything else), so it must end a
    # withdrawn session itself, or a disabled person would see the app for one render.
    # A sync route, so FastAPI already runs this store read in the threadpool. The
    # refusal clears the cookie as the middleware's does (fix round 1 / M4).
    if not user_accounts.session_allowed(session, config.allowlist, fresh=config.session_policy == "tab"):
        raise auth.session_withdrawn()
    return _me(session)


@router.post("/v1/auth/logout")
def logout(request: Request):
    audit.describe(act="SIGNED_OUT")
    config = auth.current_config()
    if config.session_policy == "tab":
        from .. import tab_sessions
        tab_sessions.revoke(auth.bearer_token(request.scope))
    response = JSONResponse({"signed_out": True})
    response.headers["set-cookie"] = auth.cookie_header("", config, 0)
    return response


# --- WP10: the user list and one's own name ---------------------------------------------------
# None of these is in auth.OPEN_PATHS, so the middleware has already refused a request
# with no session, ended a withdrawn one, and rewritten X-Volt-Officer and a POST's `by`
# from the session. With login off there is no Google sign-in for the list to govern.
# A store refusal is raised as its Problem and rendered by main.problem_handler, which
# logs nothing: no route here catches a driver error or reads a Problem's __context__.

def _session(request):
    if not auth.current_config().on:
        raise auth.auth_off()
    session = request.scope.get("volt_auth")
    if session is None:
        raise auth.auth_required()
    return session


def _admin(request):
    session = _session(request)
    if session.get("can_switch"):
        raise user_accounts.identity_not_fixed()
    # Fix round 2: the role first, so an Officer's 403 costs no database read. It tells
    # nothing new: the role is the session's own, so an Officer gets 403 whether or not
    # withdrawn, and a withdrawn Manager or Owner still reaches the check below.
    if session.get("role") not in user_accounts.ADMIN_ROLES:
        raise user_accounts.admin_only()
    # Fix round 1 / M1: the middleware answered from this process's cache, up to
    # CACHE_SECONDS old, so a Manager disabled on another instance could still read
    # every e-mail on the list. Managing the list re-checks a Google actor with a
    # fresh read; a withdrawn one is refused, and the cookie cleared, before anything.
    if (session.get("kind") == "GOOGLE"
            and not user_accounts.session_allowed(session, auth.current_config().allowlist, fresh=True)):
        raise auth.session_withdrawn()
    return session


@router.get("/v1/auth/users")
def list_users(request: Request):
    session = _admin(request)
    rank = user_accounts.RANK[session["role"]]
    from .. import cases as cases_domain
    # Redesign v2 PR 7: caseload = the work-book rows assigned to the user's officer uid,
    # counted the way GET /v1/reports/officers counts `caseload`; null with no officer.
    load = {}
    for case in cases_domain.for_current().cases.values():
        load[case["officer_uid"]] = load.get(case["officer_uid"], 0) + 1
    users = [dict(u, caseload=load.get(u["officer"], 0) if u["officer"] else None)
             for u in user_accounts.listed(auth.current_config().allowlist, session["sub"])]
    return {"users": users,
            "grantable_roles": [r for r in auth.ROLES if user_accounts.RANK[r] <= rank],
            "durable": db.configured(),
            "note_th": None if db.configured() else user_accounts.NOT_DURABLE_TH,
            "note_en": None if db.configured() else user_accounts.NOT_DURABLE_EN}


@router.post("/v1/auth/users", status_code=201)
def invite_user(request: Request, body: dict = Body(default={}), x_volt_officer: str = Header(default=None)):
    session = _admin(request)
    user = user_accounts.invite(auth.current_config().allowlist, body or {}, who(body or {}, x_volt_officer),
                                session["role"], {row["uid"]: row["role"] for row in officers.registry()})
    return {"user": user}


@router.post("/v1/auth/users/{uid}:disable")
def disable_user(uid: str, request: Request, body: dict = Body(default={}),
                 x_volt_officer: str = Header(default=None)):
    session = _admin(request)
    user = user_accounts.disable(auth.current_config().allowlist, uid, who(body or {}, x_volt_officer),
                                 session["role"], session["sub"])
    if auth.current_config().session_policy == "tab":
        from .. import tab_sessions
        tab_sessions.revoke_subject(user["email"])
    return {"user": user}


@router.put("/v1/auth/me/profile")
def set_my_profile(request: Request, body: dict = Body(default={})):
    session = _session(request)
    user_accounts.set_profile(session, body or {})
    return _me(session)
