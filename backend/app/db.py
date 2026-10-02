"""The database seam — and the three states that are easy to collapse into two.

  DATABASE_URL unset        the code behaves exactly as it did before there was
                            a database. Unit tests, CI, a laptop with no Postgres.
  set and reachable         the deployed path.
  set but unreachable       REFUSE.

The third case is the one worth spelling out. Falling back to fixtures or to
in-memory state when a configured database has gone away would resurrect the very
defect this work exists to remove — a tester's work silently vanishing — while
looking like success. app/config.py already names the principle: RUNNING and
REFUSING are both honest, LEAKING is not.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import SQLAlchemyError

from .integrations import env


class DatabaseUnreachable(RuntimeError):
    """Configured, and not answering. Never caught to fall back — only to report."""


_engine = None


def url():
    return env("DATABASE_URL")


def configured():
    return bool(url())


def engine():
    global _engine
    if not configured():
        return None
    if _engine is None:
        parsed = make_url(url())
        # pool_pre_ping: Cloud SQL drops idle connections, and a dead one taken from
        # the pool would surface as a random 500 on whichever request drew it.
        # pool_size 10 / overflow 5 against a default threadpool of 40: the old 5+2
        # queued sync handlers on connection checkout before they did any work.
        # pool_recycle keeps a long-lived Cloud SQL socket from outliving its network
        # path; pool_use_lifo reuses the hottest connection, so fewer idle ones age.
        # hide_parameters: a mid-query failure's str() must never carry a bound
        # parameter — a phone number, an e-mail — into a log (Fix round 1 / I3).
        _engine = create_engine(parsed, pool_pre_ping=True, pool_timeout=5, connect_args={"connect_timeout": 3}, pool_size=int(env("DB_POOL_SIZE", "5")),
                                max_overflow=int(env("DB_MAX_OVERFLOW", "2")), pool_recycle=1800, pool_use_lifo=True,
                                future=True, hide_parameters=True)
        if _iam_user(parsed):
            _attach_iam_token(_engine)
        _attach_slow_query_log(_engine)
    return _engine


def _attach_slow_query_log(target):
    """Print every statement slower than $SLOW_SQL_MS. Off unless it is set.

    Performance work needs a witness. Without one, "this query is slow" is an
    impression and every later fix is judged by another impression.

    Bound parameters are deliberately never printed: hide_parameters above already
    keeps them out of driver errors, and a phone number or an e-mail sitting in a
    slow-query log would be the same leak through a different door.
    """
    raw = env("SLOW_SQL_MS")
    if not raw:
        return
    try:
        threshold = float(raw)
    except ValueError:
        return
    if threshold <= 0:
        return
    import sys
    import time

    @event.listens_for(target, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        conn.info["sql_started"] = time.perf_counter()

    @event.listens_for(target, "after_cursor_execute")
    def _stop(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        started = conn.info.pop("sql_started", None)
        if started is None:
            return
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms < threshold:
            return
        one_line = " ".join(statement.split())
        if len(one_line) > 240:
            one_line = one_line[:240] + "…"
        print("slow-sql %8.1fms rows=%-6s many=%s %s"
              % (elapsed_ms, getattr(cursor, "rowcount", "?"), bool(executemany), one_line),
              file=sys.stderr)


def _iam_user(parsed):
    """True when the URL names a Cloud SQL IAM database user and carries no password.

    IAM database authentication still speaks ordinary Postgres password auth on the
    wire — the password is simply a short-lived OAuth2 access token. Cloud Run's Unix
    socket does not supply one, so a passwordless connect fails with the unhelpful
    "fe_sendauth: no password supplied". A local Postgres has neither an .iam user nor
    an empty password here, so this stays false off GCP and the seam is unchanged.
    """
    return bool(parsed.username) and parsed.username.endswith(".iam") and parsed.password is None


_credentials = None


def _iam_access_token():
    # Imported lazily: a checkout with no google-auth installed must still run the
    # DATABASE_URL-unset and local-Postgres paths exactly as before.
    global _credentials
    import google.auth
    import google.auth.transport.requests

    if _credentials is None:
        _credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/sqlservice.login"])
    if not _credentials.valid:
        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


def _attach_iam_token(target):
    # do_connect fires for every NEW pooled connection, so each authenticates with a
    # token valid at that moment. Postgres checks the password only at connect time,
    # so a connection outliving its token keeps working — no reconnect storm at the
    # one-hour mark.
    @event.listens_for(target, "do_connect")
    def _supply_token(dialect, conn_rec, cargs, cparams):  # noqa: ARG001
        cparams["password"] = _iam_access_token()


def connect():
    """A live connection, or None when no database is configured.

    Raises DatabaseUnreachable when one IS configured and cannot be reached.
    """
    from .production_unit import CURRENT, BorrowedConnection
    unit = CURRENT.get()
    if unit is not None:
        return BorrowedConnection(unit["conn"])
    active = engine()
    if active is None:
        return None
    try:
        return active.connect()
    except SQLAlchemyError as exc:
        raise DatabaseUnreachable(str(exc)) from exc


def reset():
    """Drop the cached engine. Test seam — never call it from a request."""
    global _engine, _credentials
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _credentials = None
