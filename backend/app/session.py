"""Per-account state isolation, with a browser-session fallback for local development.

Every mutable thing in this prototype — approvals, added and removed orders, the
saved criteria default — lived in one process-wide dictionary. That is fine for one
person on a laptop and wrong the moment two testers share a deployment: the second
tester sees the first one's approvals and cannot tell whose work they are looking at.

Authenticated requests use a stable `user:<subject>` principal, so work follows the
account across browsers, logins, restarts and Cloud Run revisions. When authentication
is disabled, the legacy browser cookie remains as an explicit development fallback.
"""
import hashlib
import uuid
import unicodedata
from contextvars import ContextVar

COOKIE = "volt_session"

# "shared" is the id used when no cookie is present — a direct curl, a health check,
# or a test that has not opted into a session. It behaves exactly as the old
# process-wide state did, so nothing that worked before breaks.
SHARED = "shared"

CURRENT: ContextVar = ContextVar("session_id", default=SHARED)

# The Stores the current REQUEST asked for (set by main.tester_session). flush_current()
# checks only these: a store a request never touched cannot have changed in it, and
# pickling every store a session holds cost ~230 ms a request at 10x (a 17.7 MB copy)
# for no write. None outside a request — then every store is checked, as before.
TOUCHED: ContextVar = ContextVar("session_touched", default=None)


def new_id():
    return "s-" + uuid.uuid4().hex[:16]


def current():
    return CURRENT.get()


def principal_key(subject):
    """Stable Store owner for one authenticated account."""
    value = unicodedata.normalize("NFKC", str(subject or "")).strip().casefold()
    return "user:" + value if value else None


def touched_current():
    """Whether any Store already holds a slot for the current session.

    A session that has touched no store yet seeds every store from the CURRENT book
    on that first touch, so an import heal for it would do the same work twice
    (measured 2026-09-20: 646 ms for the first heal on a 34k-row landing).
    """
    session_id = CURRENT.get()
    return any(session_id in store._by_session for store in REGISTRY)


REGISTRY = []


class Store:
    """A per-session container.

    `for_current()` creates the session's slot on first touch, so callers never
    have to check whether it exists — unchanged. What is new is that, when a
    database is configured, first touch also LOOKS for the slot in Postgres, and
    flush_current() writes every touched slot back after the request.

    `key` is required and must be unique across the process. It is the column
    value rows are stored under, so two Stores sharing a key would silently mix a
    tester's data. Three call sites use Store(dict), which is why this cannot be
    derived from the factory.
    """

    def __init__(self, factory, key):
        self._factory = factory
        self.key = key
        self._by_session = {}
        # The digest of what was last written, per session. flush_current() pickles
        # once, compares, and skips the write when nothing moved — measured 2026-09-20:
        # a warm request rewrote 11 stores / 7.8 MB to Postgres, 292 ms, for a state
        # nobody had touched. Only user work should cost a write.
        self._written = {}
        REGISTRY.append(self)

    def for_current(self):
        session_id = CURRENT.get()
        if session_id not in self._by_session:
            # A page's parallel GETs each seeded this store, the last one winning
            # (2026-09-27 staging: every tester's first page after a deploy paid N
            # seeds on one vCPU). The session's own heal lock — re-entrant, so a
            # factory may touch other stores — makes it one; the check repeats inside.
            from .import_sync import session_lock
            with session_lock():
                if session_id not in self._by_session:
                    self._by_session[session_id] = self._restore(session_id)
        touched = TOUCHED.get()
        if touched is not None:
            touched.add(self)
        return self._by_session[session_id]

    def _restore(self, session_id):
        from .production_unit import CURRENT, restore
        if CURRENT.get() is not None:
            return restore(self.key, self._factory)
        from . import db, session_store_db
        from . import perf
        with perf.phase("session_restore"):
            if not db.configured():
                return self._factory()
            conn = db.connect()          # raises DatabaseUnreachable — deliberately not caught
            try:
                value = session_store_db.load(conn, session_id, self.key)
            finally:
                conn.close()
            return self._factory() if value is session_store_db.MISSING else value

    def reset(self):
        """Clears EVERY session — memory AND, when one is configured, the database.

        Test seam; never call it from a request. Clearing only memory would leave the
        rows behind, and the next test would restore them on first touch: the suite
        becomes order-dependent, and tests that pass alone fail together. That is the
        precise failure conftest.fresh_app_state exists to prevent, so reset() has to
        mean what it says.
        """
        self._by_session.clear()
        self._written.clear()
        from . import db
        if not db.configured():
            return
        from sqlalchemy import text
        try:
            conn = db.connect()
        except db.DatabaseUnreachable:
            return          # nothing to clear, and a test seam must not raise
        try:
            with conn.begin():
                conn.execute(text("delete from app.session_state where key = :k"),
                             {"k": self.key})
                conn.execute(text("delete from app.user_state where key = :k"),
                             {"k": self.key})
        except Exception:
            pass            # the schema may not exist yet; that is not a test failure
        finally:
            conn.close()

    def sessions(self):
        return list(self._by_session)


def flush_current():
    """Write every Store's slot for the current session. Called after each request.

    Callers mutate the object returned by for_current() in place, so there is no
    per-mutation hook to hang a write on; the end of the request is the honest
    moment. Each slot is pickled once, hashed, and written only when that digest
    differs from what this process last persisted — a read-only request writes
    nothing. Inside a request only the slots it touched (TOUCHED) are checked.
    Returns the number of rows written.
    """
    from .production_unit import CURRENT as production_current, flush
    if production_current.get() is not None:
        return int(flush())
    from . import db, session_store_db
    if not db.configured():
        return 0
    session_id = CURRENT.get()
    touched = TOUCHED.get()
    if touched is not None and not touched:
        return 0
    written = 0
    conn = db.connect()
    try:
        with conn.begin():
            for store in REGISTRY:
                if session_id not in store._by_session:
                    continue
                if touched is not None and store not in touched:
                    continue
                blob = session_store_db.dump(store._by_session[session_id])
                if blob is None:
                    continue
                digest = hashlib.sha256(blob).digest()
                if store._written.get(session_id) == digest:
                    continue
                session_store_db.save_blob(conn, session_id, store.key, blob)
                store._written[session_id] = digest
                written += 1
    finally:
        conn.close()
    return written


def clear_all_persisted():
    """Delete every persisted session slot. Test seam only.

    Per-store reset() covers the stores a domain module chooses to reset; this
    covers all of them at once, including the ones nothing resets by name — the
    band-set registry among them, which is how two round-4 tests started seeing a
    band set created by an earlier test.
    """
    from . import db
    if not db.configured():
        return
    from sqlalchemy import text
    try:
        conn = db.connect()
    except db.DatabaseUnreachable:
        return
    try:
        with conn.begin():
            conn.execute(text("delete from app.session_state"))
            conn.execute(text("delete from app.user_state"))
            conn.execute(text("delete from app.user_state_archive"))
    except Exception:
        pass                # the schema may not exist yet; not a test failure
    finally:
        conn.close()
