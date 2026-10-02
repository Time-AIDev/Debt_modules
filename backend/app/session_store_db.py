"""Postgres backing for legacy browser Stores and durable per-account Stores.

Why pickle and not JSON. Twenty Store factories return list, dict, set and seven
custom classes. JSONB can hold the first two. Writing a codec for each of the rest
would mean editing twenty domain modules, which is the one thing this design
promised not to do.

Authenticated state is governed by an explicit schema version that is independent
of Cloud Run revisions. Unsupported or unreadable account state raises loudly and
is never overwritten. The old revision guard remains only for legacy browser rows,
which are retained as the rollback source for the one-time account backfill.
"""
import pickle
import sys

from sqlalchemy import text

from .integrations import env

CODEC = "pickle-v1"

# K_REVISION is set by Cloud Run and is the revision name. Stable across restarts of
# the same revision; different after every deploy. Locally there is no deploy, so
# "dev" keeps state across a laptop restart too.
CODE_VERSION = env("K_REVISION") or "dev"
STATE_SCHEMA_VERSION = 2
USER_PREFIX = "user:"

MISSING = object()


class StateUnreadable(RuntimeError):
    """A durable row exists but cannot be decoded safely; never replace it."""

    code = "user_state_unreadable"


def load(conn, session_id, key):
    if session_id.startswith(USER_PREFIX):
        return _load_user(conn, session_id, key)
    row = conn.execute(text(
        "select payload, codec, code_version from app.session_state "
        "where session_id=:s and key=:k"), {"s": session_id, "k": key}).first()
    if row is None:
        return MISSING
    if row.codec != CODEC or row.code_version != CODE_VERSION:
        return MISSING          # legacy browser state retains its old revision guard
    try:
        return pickle.loads(row.payload)
    except Exception:
        return MISSING


def _load_user(conn, principal_key, key):
    row = conn.execute(text(
        "select payload, codec, schema_version from app.user_state "
        "where principal_key=:p and key=:k"), {"p": principal_key, "k": key}).first()
    if row is None:
        return MISSING
    if row.codec != CODEC or row.schema_version > STATE_SCHEMA_VERSION:
        raise StateUnreadable(
            "state %s uses unsupported codec/schema %s/%s" %
            (key, row.codec, row.schema_version)
        )
    try:
        return pickle.loads(row.payload)
    except Exception as exc:
        raise StateUnreadable("state %s could not be decoded" % key) from exc


def dump(value):
    """The pickle payload, or None when the value cannot be pickled.

    Unpicklable state stays in memory rather than taking the request down — but it
    is REPORTED, never swallowed. State that silently fails to persist while looking
    as though it did is precisely the defect this module exists to remove. In
    practice this means a Store factory returning something defined in a function
    scope, which pickle stores by reference and cannot find again.
    """
    try:
        return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        print("session_state: not picklable, not persisted: %s" % exc, file=sys.stderr)
        return None


def save_blob(conn, session_id, key, blob):
    if blob is None:
        return
    if session_id.startswith(USER_PREFIX):
        conn.execute(text(
            "insert into app.user_state "
            "(principal_key, key, payload, codec, schema_version, updated_at) "
            "values (:s, :k, :p, :c, :v, now()) "
            "on conflict (principal_key, key) do update set payload=excluded.payload, "
            "codec=excluded.codec, schema_version=excluded.schema_version, updated_at=now()"),
            {"s": session_id, "k": key, "p": blob, "c": CODEC,
             "v": STATE_SCHEMA_VERSION})
        return
    conn.execute(text(
        "insert into app.session_state (session_id, key, payload, codec, code_version, updated_at) "
        "values (:s, :k, :p, :c, :v, now()) "
        "on conflict (session_id, key) do update set payload=excluded.payload, "
        "codec=excluded.codec, code_version=excluded.code_version, updated_at=now()"),
        {"s": session_id, "k": key, "p": blob, "c": CODEC, "v": CODE_VERSION})


def save(conn, session_id, key, value):
    save_blob(conn, session_id, key, dump(value))
