"""The allow-list people manage — records.user_account merged over AUTH_ALLOWLIST.

Feedback Round 1 / WP10 and WP11 (design F13, F14). The rules, each load-bearing:

  - The env AUTH_ALLOWLIST is the SEED. auth.load_config reads it at start-up and
    nothing writes it. A row here is merged over it: a row with a role replaces the
    seed's role and officer; a row with only a display name changes nothing about who
    may sign in.
  - A DISABLED row wins over everything, the seed included. There is no delete, so a
    seed entry can never be removed from a screen — only disabled, and a disabled
    entry comes back by being invited again.
  - Nobody hands out a role above their own, and nobody disables a role above their
    own or themselves.
  - E-mail addresses live in this table and in the audit subject only. Nothing here
    prints one, and no refusal's detail or message carries one.

Durable when a database is configured (schema records: survives a deploy); a process
dict labelled not-durable when it is not — the three states db.py names. A configured
database that does not answer refuses (503); it never falls back to the seed alone.

Sessions are stateless signed cookies, so ending a disabled person's session means the
login middleware asks session_allowed() on every request. It answers from a cache
refreshed at most every CACHE_SECONDS, and at once on the instance that made the
change: on another Cloud Run instance a disabled session ends within CACHE_SECONDS.

Fix round 1 (security review, 2026-09-15) — each of these is load-bearing too:
  - An invited e-mail is ASCII and matches EMAIL, or it is refused. A zero-width space,
    a BOM, a direction override or a Cyrillic letter each made a second ACTIVE row that
    looked like the real person; and past ASCII, Python's lower() and Postgres's
    lower() disagree, which surfaced as a false user_exists.
  - Re-inviting a DISABLED person is bound by the role they last held (the row's, else
    the seed's) as well as the role offered: a Manager cannot undo an Owner's disable.
    An actor role the store does not rank is refused, never a KeyError.
  - The cache is snapshotted once under _CACHE_LOCK. B10b's middleware reads it on the
    request path while writes run in the threadpool, and two separate reads of "at"
    and "rows" crashed on a concurrent forget(). _GENERATION, bumped by forget(),
    keeps a read that overlapped a write from being saved: it would have put the
    pre-disable rows back for CACHE_SECONDS.
  - No driver exception leaves _transaction(): its text carries the bound e-mail. A
    connection lost mid-query is the same retryable 503 as one that never opened;
    anything else is an opaque Problem, raised from None. db.engine() also hides bound
    parameters from every statement error.
  - A listed seed uid is HMAC-SHA256 keyed with AUTH_SESSION_SECRET when it is set, so
    it cannot be reversed from a word list of likely addresses.

B10b rulings (2026-09-15):
  - valid_email() is the one e-mail rule: invite(), the Google sign-in and
    auth.load_config's seed check all call it, so the three can never disagree.
  - disable() writes on the row the role and officer it saw (the seed's for a person
    known only to the seed), so removing that seed entry later cannot let a Manager
    re-invite an Owner-ranked person (the M1 edge).
  - A configured database with no records.user_account (the migration never ran) is
    the labelled 503 user_list_not_migrated naming debt-migrate, not internal_error:
    the login middleware asks this store on every Google session's every request.

B10b fix round 1 (opus review, 2026-09-15):
  - I1: session_allowed() also refuses a session signed before the row's invited_at
    (+1 s for iat's whole seconds), so a cookie from before a disable stays dead after
    a same-role re-invitation. Still one read of the rows; fresh=True bypasses the
    cache (routers/login.py re-checks a Google actor on the user list with it, M1).
  - M3: invite() takes {registry uid: role}; an officer identity whose registry role
    outranks the actor refuses role_above_actor, like the role handed out.
"""
import hashlib
import hmac
import re
import threading
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.exc import (DisconnectionError, IntegrityError, InterfaceError, OperationalError,
                            SQLAlchemyError)

from . import audit, db, errors
from .integrations import env

CACHE_SECONDS = 30
DISPLAY_NAME_MAX = 60
MAX_COMBINING_MARKS = 3
NOT_DURABLE_TH = "ไม่มีฐานข้อมูล — รายชื่อนี้อยู่ในหน่วยความจำและหายเมื่อรีสตาร์ท"
NOT_DURABLE_EN = "No database — this list lives in memory and is lost on restart"
# ASCII only (see the module docstring: Python/Postgres lower() disagree past ASCII).
EMAIL = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")
# Nonspacing and enclosing marks — accents and the like that ride on a base character.
_MARK_CATEGORIES = ("Mn", "Me")
# Code points that render as nothing yet pass a category-based "is it visible" check:
# the Hangul fillers (letters) and, B10b ruling, U+2800 BRAILLE PATTERN BLANK (a symbol).
# A display name built only from these (plus marks) would be invisible.
_INVISIBLE_FILLERS = ("\u115f", "\u1160", "\u3164", "\uffa0", "\u2800")
_SEED_UID_LABEL = b"volt-debt user_account seed uid\x00"
# Who may hand out which role. OPS is the O&M team's seat, ranked with OFFICER.
RANK = {"OFFICER": 1, "OPS": 1, "SUPERVISOR": 2, "MANAGER": 3, "OWNER": 4}
ADMIN_ROLES = ("MANAGER", "OWNER")
COLUMNS = ("id", "kind", "email", "username", "role", "officer", "display_name",
           "invited_by", "invited_at", "disabled_at", "disabled_by")

_MEMORY = {}
_NEXT = {"id": 0}
_CACHE = {"at": None, "rows": None}
_CACHE_LOCK = threading.Lock()
_GENERATION = [0]
_clock = time.monotonic


def reset():
    """Test seam: the memory rows and the cache."""
    _MEMORY.clear()
    _NEXT["id"] = 0
    forget()


def forget():
    with _CACHE_LOCK:
        _CACHE["at"], _CACHE["rows"] = None, None
        _GENERATION[0] += 1


# --- refusals (RFC 9457) --------------------------------------------------------------

def list_unreachable():
    return errors.Problem("user_list_unreachable", 503, "The user list cannot be read",
                          "A database is configured and did not answer, so sign-in cannot be decided.",
                          "อ่านรายชื่อผู้ใช้จากฐานข้อมูลไม่ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง",
                          "DEBT-AUTH-506", retryable=True)


def list_not_migrated():
    # B10b ruling: the database answers but records.user_account is not there. Not
    # retryable by the person: it stays this way until the migration job runs.
    return errors.Problem("user_list_not_migrated", 503, "The user list table is missing",
                          "records.user_account does not exist on the configured database. "
                          "Run the debt-migrate job (schema.sql), then try again.",
                          "ฐานข้อมูลยังไม่มีตารางรายชื่อผู้ใช้ (records.user_account) "
                          "กรุณาให้ผู้ดูแลระบบรัน debt-migrate ก่อน แล้วลองใหม่อีกครั้ง",
                          "DEBT-AUTH-507")


def admin_only():
    return errors.Problem("forbidden", 403, "Manager or Owner only",
                          "Only a Manager or the Owner manages who may sign in.",
                          "เฉพาะผู้จัดการหรือเจ้าของระบบจัดการรายชื่อผู้ใช้ได้", "DEBT-IAM-0403")


def identity_not_fixed():
    return errors.Problem("identity_not_fixed", 403, "A switching account cannot manage users",
                          "This session may act as any role, so it cannot vouch for an invitation.",
                          "บัญชีที่สลับบทบาทได้จัดการผู้ใช้ไม่ได้ กรุณาเข้าสู่ระบบด้วยบัญชีของผู้จัดการหรือเจ้าของระบบ",
                          "DEBT-AUTH-411")


def role_above_actor(role):
    return errors.Problem("role_above_actor", 403, "That role is above your own",
                          "A %s cannot be invited or disabled by someone whose role ranks lower." % role,
                          "จัดการผู้ใช้ที่มีบทบาทสูงกว่าตัวเองไม่ได้", "DEBT-AUTH-412",
                          extensions={"role": role})


def cannot_disable_self():
    return errors.Problem("cannot_disable_self", 409, "You cannot disable yourself",
                          "Ask another Manager or the Owner.",
                          "ปิดการใช้งานบัญชีของตัวเองไม่ได้", "DEBT-AUTH-413")


def user_exists():
    return errors.Problem("user_exists", 409, "Already on the list",
                          "This e-mail may already sign in; disable it first to change it.",
                          "อีเมลนี้มีสิทธิ์ใช้ระบบอยู่แล้ว", "DEBT-AUTH-414")


def user_already_disabled():
    return errors.Problem("user_already_disabled", 409, "Already disabled",
                          "Invite the e-mail again to bring it back.",
                          "บัญชีนี้ถูกปิดการใช้งานอยู่แล้ว เชิญใหม่เพื่อเปิดใช้อีกครั้ง", "DEBT-AUTH-415")


def _invalid(pointer, code, message, message_th):
    return errors.validation_failed([{"pointer": pointer, "code": code, "message": message,
                                      "message_th": message_th}])


# --- reading ----------------------------------------------------------------------------

def _key(row):
    return (row["kind"], row["email"] if row["kind"] == "GOOGLE" else row["username"])


def _connect():
    try:
        return db.connect()
    except db.DatabaseUnreachable:
        raise list_unreachable() from None


def _connection_lost(exc):
    return (isinstance(exc, (OperationalError, InterfaceError, DisconnectionError))
            or bool(getattr(exc, "connection_invalidated", False)))


def _table_missing(conn):
    """True only when records.user_account itself is absent (B10b ruling). Asked on the
    failure path alone, in a transaction of its own after the failed one rolled back,
    and by name — never by reading the driver exception, whose text quotes the e-mail —
    so a ProgrammingError about anything else stays the opaque internal_error."""
    try:
        with conn.begin():
            return conn.execute(text("select to_regclass('records.user_account') is null")).scalar() is True
    except SQLAlchemyError:
        return False


@contextmanager
def _transaction(on_conflict=None):
    """One read or write connection, closed either way, and no driver exception ever
    leaves it (fix round 1 / I3). A driver exception's text quotes the statement's
    bound values — the e-mail — so each becomes a Problem raised `from None`:

      - a connection lost after it opened (killed mid-query)  -> the retryable 503,
        the same answer as a connection that never opened;
      - an IntegrityError                                     -> on_conflict() when
        the caller names its own conflict (invite: user_exists), else internal_error;
      - records.user_account not there (migration not run)    -> the 503
        user_list_not_migrated (B10b ruling);
      - anything else (DataError, ProgrammingError, ...)      -> internal_error.
    """
    conn = _connect()
    try:
        with conn.begin():
            yield conn
    except IntegrityError:
        raise (on_conflict or errors.internal_error)() from None
    except SQLAlchemyError as exc:
        if _connection_lost(exc):
            raise list_unreachable() from None
        if _table_missing(conn):
            raise list_not_migrated() from None
        raise errors.internal_error() from None
    finally:
        try:
            conn.close()
        except SQLAlchemyError:
            pass          # a dead connection's close; the answer above already stands


def _read_rows():
    if not db.configured():
        return {_key(r): dict(r) for r in _MEMORY.values()}
    with _transaction() as conn:
        rows = conn.execute(text("select " + ", ".join(COLUMNS) + " from records.user_account order by id")).mappings().all()
    return {_key(r): dict(r) for r in rows}


def _rows(fresh):
    # Fix round 1 / I2: "at", "rows" and "generation" are snapshotted together under
    # the lock — two separate unlocked dict reads let a concurrent forget() land
    # between them (observed: AttributeError/TypeError under a real thread race).
    with _CACHE_LOCK:
        at, rows, generation = _CACHE["at"], _CACHE["rows"], _GENERATION[0]
    if not fresh and rows is not None and _clock() - at <= CACHE_SECONDS:
        return rows
    read = _read_rows()
    now = _clock()
    with _CACHE_LOCK:
        # A forget() (any write) landed while _read_rows() was in flight: that read
        # may predate the write, so it is handed back to THIS caller but never saved
        # — saving it would put pre-write data back in the cache for CACHE_SECONDS.
        if _GENERATION[0] == generation:
            _CACHE["rows"], _CACHE["at"] = read, now
    return read


def refresh():
    """The start-up merge: read the rows once so the first request needs no query."""
    return len(_rows(fresh=True))


def _merged(rows, email, seed):
    """(entry, state, row) from one snapshot of the rows — see allow_entry()."""
    row = rows.get(("GOOGLE", email))
    if row is not None and row["disabled_at"] is not None:
        return None, "DISABLED", row
    if row is not None and row["role"]:
        return {"role": row["role"], "officer": row["officer"]}, "ACTIVE", row
    entry = seed.get(email)
    return (dict(entry), "ACTIVE", row) if entry else (None, None, row)


def allow_entry(email, seed, fresh=True):
    """({role, officer}, "ACTIVE"), (None, "DISABLED") or (None, None) for an e-mail."""
    entry, state, _row = _merged(_rows(fresh), email, seed)
    return entry, state


# A session's iat is whole seconds (auth.new_session); a row's invited_at is not.
INVITED_AFTER_SLACK_SECONDS = 1


def session_allowed(session, seed, fresh=False):
    """False when a Google session's person was disabled, dropped from the seed,
    re-invited with another role or officer, or (fix round 1 / I1) invited at all after
    the session was signed — a cookie from before a disable must stay dead after a
    same-role re-invitation, because disabling is the answer to a lost laptop or a
    leaked cookie. One read of the rows (the cache unless fresh=True). A test account is
    not managed here (design F13: password test accounts are unchanged)."""
    if session.get("kind") != "GOOGLE":
        return True
    entry, _state, row = _merged(_rows(fresh), session.get("sub"), seed)
    if (entry is None or entry["role"] != session.get("role")
            or entry["officer"] != session.get("officer")):
        return False
    invited_at = row["invited_at"] if row is not None else None
    if invited_at is None:
        return True
    # A session with no iat counts as signed at 0, and an invited_at that is not a
    # datetime refuses: both fail closed.
    stamp = getattr(invited_at, "timestamp", None)
    return stamp is not None and stamp() <= float(session.get("iat") or 0) + INVITED_AFTER_SLACK_SECONDS


def display_name_for(session, fresh=True):
    """WP11: {display_name, display_name_source, display_name_fallback} — the person's
    own name (PROFILE), else the e-mail's user part (EMAIL), else the username
    (USERNAME). The fallback is served too, so no screen derives it from the subject."""
    kind = "GOOGLE" if session.get("kind") == "GOOGLE" else "TEST"
    sub = str(session.get("sub") or "")
    fallback, source = (sub.split("@", 1)[0], "EMAIL") if kind == "GOOGLE" else (sub, "USERNAME")
    row = _rows(fresh).get((kind, sub))
    if row is not None and row["display_name"]:
        return {"display_name": row["display_name"], "display_name_source": "PROFILE",
                "display_name_fallback": fallback}
    return {"display_name": fallback, "display_name_source": source, "display_name_fallback": fallback}


def _seed_uid(email):
    # A listed seed entry needs an id for its disable URL, and an e-mail in a URL would
    # land in every request log. A plain digest is reversible from a word list of
    # plausible addresses, so when AUTH_SESSION_SECRET is set (AUTH_MODE=on) the id is
    # HMAC-SHA256 keyed with it — read the way auth.py reads it, the real environment
    # first and backend/.env as the fallback. The message carries a purpose label, so
    # this MAC can never double as a session-cookie MAC made with the same key. With no
    # secret (auth off, a local run) it is the plain digest. Either way the uid is
    # STABLE ACROSS INSTANCES: every Cloud Run instance holds the same secret and
    # derives the same id, so an id listed by one instance resolves on another.
    secret = env("AUTH_SESSION_SECRET") or ""
    if secret:
        digest = hmac.new(secret.encode("utf-8"), _SEED_UID_LABEL + email.encode("utf-8"), hashlib.sha256)
    else:
        digest = hashlib.sha256(email.encode("utf-8"))
    return "env-" + digest.hexdigest()[:16]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def listed(seed, viewer_sub):
    """The merged list a Manager reads: every seed e-mail and every GOOGLE row."""
    rows = _rows(fresh=True)
    out = []
    for email in sorted(set(seed) | {k[1] for k in rows if k[0] == "GOOGLE"}):
        row = rows.get(("GOOGLE", email))
        entry = seed.get(email)
        disabled = row is not None and row["disabled_at"] is not None
        if row is not None and row["role"]:
            role, officer = row["role"], row["officer"]
        elif entry:
            role, officer = entry["role"], entry["officer"]
        else:
            role, officer = None, None
        if role is None and not disabled:
            continue          # a display-name row for an e-mail no longer on any list
        out.append({
            "uid": str(row["id"]) if row is not None else _seed_uid(email),
            "email": email, "role": role, "officer": officer,
            "display_name": row["display_name"] if row is not None else None,
            "state": "DISABLED" if disabled else "ACTIVE",
            "seeded": entry is not None,
            "invited_by": row["invited_by"] if row is not None else None,
            "invited_at": _iso(row["invited_at"]) if row is not None else None,
            "disabled_by": row["disabled_by"] if row is not None else None,
            "disabled_at": _iso(row["disabled_at"]) if row is not None else None,
            "self": email == viewer_sub,
        })
    return out


def _resolve(uid, seed):
    rows = _rows(fresh=True)
    if uid.startswith("env-"):
        email = next((e for e in seed if _seed_uid(e) == uid), None)
    else:
        row = next((r for r in rows.values() if r["kind"] == "GOOGLE" and str(r["id"]) == uid), None)
        email = row["email"] if row else None
    return email


def _require_actor_role(actor_role):
    # Fix round 1 / M3: an actor_role this store does not rank (None, a stray string)
    # used to reach RANK[actor_role] and raise a bare KeyError — a 500, not a refusal.
    if actor_role not in RANK:
        raise admin_only()


def _known_role(email, seed):
    """The role on record for this e-mail, active or disabled — the row's if it still
    carries one (disable() never clears role/officer, only disabled_at/disabled_by),
    else the seed's. None when nobody has ever named a role for it.

    Fix round 1 / M1: re-inviting a DISABLED person is management of THAT person, and
    must be bound by the same rank rule a live disable() already enforces — the role
    they last held, not only the role the invite hands out. Without this a Manager
    could re-invite a disabled Owner as a mere Manager, quietly undoing an Owner's
    disable with an authority the store would never grant to disable that Owner
    directly."""
    row = _rows(fresh=False).get(("GOOGLE", email))       # invite() read them fresh a moment ago
    if row is not None and row["role"]:
        return row["role"]
    entry = seed.get(email)
    return entry["role"] if entry else None


# --- writing ----------------------------------------------------------------------------

def _memory_row(kind, email=None, username=None):
    for row in _MEMORY.values():
        if _key(row) == (kind, email if kind == "GOOGLE" else username):
            return row
    _NEXT["id"] += 1
    row = dict.fromkeys(COLUMNS)
    row.update(id=_NEXT["id"], kind=kind, email=email, username=username)
    _MEMORY[row["id"]] = row
    return row


def _now():
    return datetime.now(timezone.utc)


def valid_email(email):
    """True for an address this list can hold: a str, ASCII, and EMAIL — checked AFTER
    the caller's strip().lower(), so "Thip@..." is False here. The one rule (B10b):
    invite(), routers/login.py's Google sign-in and auth.load_config's seed check."""
    return isinstance(email, str) and email.isascii() and EMAIL.fullmatch(email) is not None


def invite(seed, body, by, actor_role, officer_roles):
    """officer_roles: {registry uid: registry role} (officers.registry())."""
    _require_actor_role(actor_role)
    email = str(body.get("email") or "").strip().lower()
    role = str(body.get("role") or "").strip().upper()
    officer = str(body.get("officer") or "").strip()
    problems = []
    if not valid_email(email):
        problems.append({"pointer": "/email", "code": "email_invalid", "message": "not an e-mail address",
                         "message_th": "อีเมลไม่ถูกต้อง"})
    if role not in RANK:
        problems.append({"pointer": "/role", "code": "role_unknown",
                         "message": "role is one of %s" % ", ".join(sorted(RANK)),
                         "message_th": "บทบาทไม่ถูกต้อง เลือกจากรายการ"})
    if officer not in officer_roles:
        problems.append({"pointer": "/officer", "code": "officer_unknown",
                         "message": "officer is not in /v1/officers",
                         "message_th": "ไม่พบเจ้าหน้าที่คนนี้ในรายชื่อ"})
    if problems:
        raise errors.validation_failed(problems)
    if RANK[role] > RANK[actor_role]:
        raise role_above_actor(role)
    # B10b fix round 1 / M3: the officer identity handed out is bound by the same rank
    # as the role — a Manager tying an invitee to `owner` made records read "by owner".
    # A registry role this store does not rank refuses (fail closed).
    officer_role = officer_roles[officer]
    if RANK.get(officer_role, max(RANK.values()) + 1) > RANK[actor_role]:
        raise role_above_actor(officer_role)
    _entry, state = allow_entry(email, seed, fresh=True)
    if state == "ACTIVE":
        raise user_exists()
    if state == "DISABLED":
        # Fix round 1 / M1: bound by who they WERE, not only by the role now offered.
        previous_role = _known_role(email, seed)
        if previous_role and RANK[previous_role] > RANK[actor_role]:
            raise role_above_actor(previous_role)
    audit.describe(act="USER_INVITED", subject=("user_account", email),
                   detail={"role": role, "officer": officer, "reenabled": state == "DISABLED"})
    if not db.configured():
        _memory_row("GOOGLE", email=email).update(role=role, officer=officer, invited_by=by, invited_at=_now(),
                                                   disabled_at=None, disabled_by=None)
    else:
        # an IntegrityError is user_exists — never the driver's text: it quotes the e-mail
        with _transaction(on_conflict=user_exists) as conn:
            done = conn.execute(text(
                "insert into records.user_account (kind, email, role, officer, invited_by, invited_at) "
                "values ('GOOGLE', :e, :r, :o, :b, now()) "
                "on conflict (email) where email is not null do update set role = excluded.role, "
                "officer = excluded.officer, invited_by = excluded.invited_by, "
                "invited_at = excluded.invited_at, disabled_at = null, disabled_by = null "
                "where records.user_account.disabled_at is not null or records.user_account.role is null "
                "returning id"), {"e": email, "r": role, "o": officer, "b": by}).first()
        if done is None:
            raise user_exists()          # made active by someone else a moment ago
    forget()
    return next(u for u in listed(seed, None) if u["email"] == email)


def disable(seed, uid, by, actor_role, actor_sub):
    _require_actor_role(actor_role)
    email = _resolve(uid, seed)
    entry, state = allow_entry(email, seed, fresh=False) if email else (None, None)
    if state is None:
        raise errors.not_found("user")
    if state == "DISABLED":
        raise user_already_disabled()
    if email == actor_sub:
        raise cannot_disable_self()
    if RANK[entry["role"]] > RANK[actor_role]:
        raise role_above_actor(entry["role"])
    audit.describe(act="USER_DISABLED", subject=("user_account", email),
                   detail={"role": entry["role"], "seeded": email in seed})
    # B10b ruling (the M1 edge): the row keeps the role and officer this disable saw —
    # the seed's for a person known only to the seed. _known_role() reads the row first,
    # so a later redeploy that drops the seed entry cannot let a Manager re-invite an
    # Owner-ranked person. A row that already names a role keeps its own (the two are
    # the same unless an invitation raced this disable; the stored one then wins).
    if not db.configured():
        row = _memory_row("GOOGLE", email=email)
        if not row["role"]:
            row.update(role=entry["role"], officer=entry["officer"])
        row.update(disabled_at=_now(), disabled_by=by)
    else:
        with _transaction() as conn:
            # Fix round 1 / M2: "where disabled_at is null" so a racing second
            # disable() (both passed the Python pre-check above before either wrote)
            # affects zero rows instead of silently overwriting the first's
            # disabled_by — it gets user_already_disabled(), same as a sequential one.
            done = conn.execute(text(
                "insert into records.user_account (kind, email, role, officer, disabled_at, disabled_by) "
                "values ('GOOGLE', :e, :r, :o, now(), :b) "
                "on conflict (email) where email is not null do update set disabled_at = now(), "
                "disabled_by = excluded.disabled_by, "
                "role = coalesce(records.user_account.role, excluded.role), "
                "officer = case when records.user_account.role is null then excluded.officer "
                "else records.user_account.officer end "
                "where records.user_account.disabled_at is null "
                "returning id"), {"e": email, "r": entry["role"], "o": entry["officer"], "b": by}).first()
        if done is None:
            raise user_already_disabled()
    forget()
    return next(u for u in listed(seed, actor_sub) if u["email"] == email)


def _shaped_like_a_name(name):
    """Fix round 1 / M5: a name needs a visible base character once combining marks
    (Mn, Me), format characters (Cf), spaces (Z*) and the invisible Hangul fillers are
    set aside — "\\u3164 \\u3164" is blank on every screen — and no base character
    carries more than MAX_COMBINING_MARKS marks (an unbounded stack of accents, "zalgo"
    text, spills over the rows around it)."""
    run = 0
    visible = False
    for c in name:
        category = unicodedata.category(c)
        if category in _MARK_CATEGORIES:
            run += 1
            if run > MAX_COMBINING_MARKS:
                return False
            continue
        run = 0
        if category != "Cf" and not category.startswith("Z") and c not in _INVISIBLE_FILLERS:
            visible = True
    return visible


def _clean_name(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid("/display_name", "display_name_invalid", "a display name is text",
                       "ชื่อที่แสดงต้องเป็นข้อความ")
    name = " ".join(value.split())
    if not name:
        return None
    if len(name) > DISPLAY_NAME_MAX or any(unicodedata.category(c).startswith("C") for c in name):
        raise _invalid("/display_name", "display_name_invalid",
                       "at most %d characters, no control characters" % DISPLAY_NAME_MAX,
                       "ชื่อที่แสดงยาวได้ไม่เกิน %d ตัวอักษร และห้ามมีอักขระควบคุม" % DISPLAY_NAME_MAX)
    if not _shaped_like_a_name(name):
        raise _invalid("/display_name", "display_name_invalid",
                       "needs a visible base character, and at most %d combining marks on any one of them"
                       % MAX_COMBINING_MARKS,
                       "ชื่อที่แสดงต้องมีตัวอักษรที่มองเห็นได้ และมีเครื่องหมายกำกับเสียงต่อกันได้ไม่เกิน %d ตัว"
                       % MAX_COMBINING_MARKS)
    return name


def set_profile(session, body):
    kind = "GOOGLE" if session.get("kind") == "GOOGLE" else "TEST"
    sub = str(session.get("sub") or "")
    # B12a controller ruling (d): described BEFORE anything that can raise — the same
    # concern as set_phone's M7 (customer_contact.py) — so a refused not_editable or
    # display_name_invalid still writes a REFUSED PROFILE_SET row naming this actor's
    # own subject, instead of the audit middleware's untouched act=None default.
    audit.describe(act="PROFILE_SET", subject=("user_account", sub))
    unknown = sorted(set(body) - {"display_name"})
    if unknown:
        raise _invalid("/" + unknown[0], "not_editable", "only display_name is set here",
                       "ตั้งค่าได้เฉพาะชื่อที่แสดง")
    name = _clean_name(body.get("display_name"))
    audit.describe(detail={"display_name": "set" if name else "cleared"})
    if not db.configured():
        if kind == "GOOGLE":
            _memory_row(kind, email=sub)["display_name"] = name
        else:
            _memory_row(kind, username=sub)["display_name"] = name
    else:
        column = "email" if kind == "GOOGLE" else "username"
        with _transaction() as conn:
            conn.execute(text(
                "insert into records.user_account (kind, %s, display_name) values (:k, :s, :n) "
                "on conflict (%s) where %s is not null do update set display_name = excluded.display_name"
                % (column, column, column)), {"k": kind, "s": sub, "n": name})
    forget()
    return name
