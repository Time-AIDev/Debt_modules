"""Volt Debt — prototype API.

The document set is at version 2.x. The HTTP surface stays at /v1, deliberately:
"This document is version 2.1. The addresses still begin with slash v1." Every v2.x
change is additive under v1.0's own rule. Minting /v2 would be a breaking change
needing a plan, not a patch.
"""
import json
import os
from .runtime_policy import shared_state_enabled
import re
import sys
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .production_runtime import validate_environment
validate_environment()

from . import audit
from . import board
from . import clock
from . import errors
from . import criteria as criteria_domain
from . import orders as orders_domain
from . import overview as overview_domain
from . import feedback as feedback_domain
from . import payment_position
from . import peak_webhooks
from . import session as session_domain
from . import uat_tasks
from .collections.contact import (
    OVERRIDE_ROLES,
    ContactLocked,
    ContactLog,
    SessionContactLog,
    ContactOnHold,
    OverrideForbidden,
    OverrideReasonRequired,
    bangkok_day,
    parse_timestamp,
)
from .config import PENDING, settings
from .fixtures import BUSINESS_DATE, seed
from .money.arrears import arrears_block
from .money.band_sets import resolve_band
from .money.dpd import compute_dpd
from .money.penalty import accrue_range, chargeable_arrears_by_day

from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _lifespan(app_):
    """Boot: every step guarded, so nothing here can hold the app down.

    The sale.order sync that used to run first is gone (fix-all 2026-09-25, Arina's
    decision 6); the crm.lead pull below is the only Odoo door."""
    # The book was built at import from the current landing; say so, or the first
    # request would rebuild it again for the same epoch (import_sync.ensure_current).
    from . import data_epoch as _data_epoch, import_sync as _import_sync
    _import_sync.note_book_epoch(_data_epoch.current())
    # D05 / TASK-221: the early-payment scan once at boot, after the served book is
    # fresh. Guarded — a notice must never hold the app down.
    from . import request_context as _boot_reads
    boot_read_token = _boot_reads.begin_read()
    try:
        from . import cases as _cases, journey as _journey
        from .config import settings as _settings
        from .ptp_watch import notice_early_payments as _notice_early
        if not shared_state_enabled():
            _notice_early(_journey.for_current(), _cases.for_current(), _settings.business_date)
    except Exception as exc:                       # noqa: BLE001 — boot must proceed
        print("early-payment scan failed: %s" % exc.__class__.__name__, file=sys.stderr)
    finally:
        _boot_reads.end_read(boot_read_token)
    # The 2026-09-19 ruling: Odoo crm.lead is the served book. Refresh it on a
    # background thread when the last run is older than the window — never in the
    # boot path itself, so a 34k pull cannot hold the app down. No database (tests,
    # the black-box gate) is a silent no-op.
    from .pipelines import service as pipelines_service
    try:
        if not shared_state_enabled() and pipelines_service.refresh_if_stale():
            print("crm.lead refresh started in the background")
    except Exception as exc:                       # noqa: BLE001 — boot must proceed
        print("crm.lead refresh not started: %s" % exc.__class__.__name__, file=sys.stderr)
    # 2026-09-21: the refetch (every 2 hours since 2026-09-25) is ON by default now — the Import data screen
    # defaults to the Odoo tab and says the system fetches by itself. `ensure_auto`
    # is idempotent and does not fire immediately; boot-time freshness stays
    # `refresh_if_stale`'s six-hour window above. The loop skips without spending a
    # tick when there is no database or no Odoo credentials.
    from .pipelines import schedule as schedule_mod
    try:
        if not shared_state_enabled():
            schedule_mod.ensure_auto()
        print("crm.lead auto-sync on: every %d minutes" % schedule_mod.INTERVAL_DEFAULT)
    except Exception as exc:                       # noqa: BLE001 — boot must proceed
        print("crm.lead auto-sync not enabled: %s" % exc.__class__.__name__, file=sys.stderr)
    # Monthly history (2026-09-25): a new month has its row from the first boot in it.
    from . import monthly_history
    if not shared_state_enabled(): monthly_history.safe_snapshot("boot")
    # WP10 (F13): the start-up merge of records.user_account over AUTH_ALLOWLIST. A
    # database that does not answer at boot is not fatal here — every sign-in and
    # every session check reads the rows again and refuses 503 until it answers. The
    # line printed names the Problem's code only, never its __context__ (a driver
    # exception whose text can quote an e-mail).
    from . import auth as _auth, errors as _errors, user_accounts as _accounts
    if _auth.current_config().on:
        try:
            _accounts.refresh()
        except _errors.Problem as problem:
            print("user list not read at start-up: %s; Google sign-in and Google sessions refuse until it is"
                  % problem.code, file=sys.stderr)
    if shared_state_enabled():
        from .production_runtime import warm_projections
        await run_in_threadpool(warm_projections)
    try:
        yield
    finally:
        schedule_mod.shutdown()


app = FastAPI(title="Volt Debt", version="0.1.0", lifespan=_lifespan,
              openapi_url=None if shared_state_enabled() else "/openapi.json",
              docs_url=None if shared_state_enabled() else "/docs",
              redoc_url=None if shared_state_enabled() else "/redoc")

# The browser only ever talks to this API through the vite proxy in development and
# through the load balancer in every deployed environment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Kept inside the timing middleware so the route metric includes bytes compression;
# the responder also records gzip as its own phase.
from .timed_gzip import TimedGZipMiddleware  # noqa: E402
app.add_middleware(TimedGZipMiddleware, minimum_size=1024, compresslevel=6)

def _serve_book():
    """(contract holders, identities) from ONE read of the serving source.

    The 2026-09-19 ruling serves Odoo crm.lead: identities are the majority of the
    real book, and the contract-only engine loops must never see them — they carry
    no contract and every one of those loops assumes one.
    """
    from . import book as book_mod
    from .fixtures import identities as _identities, seed as _seed
    loaded = book_mod.build()
    customers = _seed(loaded)
    # A row that holds a contract is not an identity. The sheet carries a few
    # duplicate customer numbers — one row with money, one without — and a uid in
    # both lists would let the contract-less copy shadow the case in BY_CUSTOMER.
    taken = {c.uid for c in customers}
    return customers, [c for c in _identities(loaded) if c.uid not in taken]


CUSTOMERS, IDENTITIES = _serve_book()
BY_CUSTOMER = {c.uid: c for c in CUSTOMERS + IDENTITIES}
BY_CONTRACT = {k.uid: (c, k) for c in CUSTOMERS for k in c.contracts}

# See reload_book(): readers on other threads must not see a half-swapped book.
_BOOK_LOCK = threading.RLock()
# ...and two callers must not build it at once (fix-all F1).
_BUILD_LOCK = threading.Lock()


def reload_book():
    """Rebuild the served book from book_source (Feedback Round 1 / WP1 Task 6).

    Called after a PEAK report is applied so the new facts are served without a
    restart, and since the 2026-09-20 sync audit by every landing door through
    app/refresh.after_landing (crm.lead run/start/schedule, the Odoo order sync, a
    pipeline upload) — before that, only a PEAK apply rebound these globals and a
    crm.lead pull left the served book stale in the same process.

    The lock makes the four rebinds atomic for readers on other threads: a request
    that reads CUSTOMERS while a background pull finishes must not see the new list
    beside the old BY_CUSTOMER map. Per-session journey and cases state seeded from
    the OLD book is healed by app/import_sync.py on the session's next request.

    Fix-all F1: one build at a time. The epoch is re-read under the build lock, so a
    caller that waited while another built that epoch returns without building it
    twice, and builds never overlap, so an older one cannot swap in over a newer one.
    refresh.after_landing bumps the epoch BEFORE it calls this, so a landing is never
    taken for a book this process already serves.
    """
    global CUSTOMERS, IDENTITIES, BY_CUSTOMER, BY_CONTRACT
    from . import book as book_mod, data_epoch, import_sync
    with _BUILD_LOCK:
        epoch = data_epoch.current()
        if epoch and import_sync._book_epoch["value"] >= epoch:
            return
        # The book's own caches only: book_source keeps its non-PEAK landing reads per
        # non-PEAK epoch (fix-all F3), so a PEAK apply re-reads the PEAK data alone.
        book_mod.invalidate(reads=False)
        customers, identities = _serve_book()
        with _BOOK_LOCK:
            CUSTOMERS, IDENTITIES = customers, identities
            BY_CUSTOMER = {c.uid: c for c in CUSTOMERS + IDENTITIES}
            BY_CONTRACT = {k.uid: (c, k) for c in CUSTOMERS for k in c.contracts}
        # Feedback Round 1 / Task 10 controller ruling: the book only changes here (and
        # at process start), so this is the one place payment_position's memoised sheet
        # capture date has to be forgotten.
        payment_position.forget_capture_date()
        from . import customer_search, workbook_index
        customer_search.invalidate()
        workbook_index.invalidate()
        import_sync.note_book_epoch(epoch)

# Judge J-12c: one contact log per tester session (see collections/contact.py).
contact_log = SessionContactLog()

# REQ-COL-054 — a column carries a STABLE IDENTIFIER that is not its name, so a
# rename is a non-event. The default grouping is "Work today"; screen 05 owns
# recovery stage, so screen 01 must not duplicate it.
#
# Round-4, ruling 39 (Arina, 2026-09-05): this was a bare process-wide list, and
# `DELETE /v1/board/columns/{id}` (below) mutated it AND the shared `CUSTOMERS`
# fixture objects directly — worse than R3-F04/ruling 32's settings leak, because a
# write to a fixture object outlives every session, not just the process's read of
# a singleton. Read/write census, backend/app: 2 read sites here (`main.py:718`,
# `:729` post-fix — GET's `"columns"` key and the `known` set), 2 more inside
# DELETE (`affected`, `moved` below), 1 write site here (`:760`, the `[:]` rewrite
# that drops the deleted entry), plus one read site in `routers/journey.py:458`
# (`main.BOARD_COLUMNS`, the board-move endpoint's own `known` check) — 4 read, 1
# write, 2 modules, matching the "small census, distinct remedy" case this leg's
# brief called out in advance.
#
# The remedy differs from ruling 32's `_SettingsProxy` in shape, not in principle:
# `Settings` was read by 226 *dotted-attribute* sites, so the proxy forwarded
# `__getattr__`/`__setattr__`. `BOARD_COLUMNS` is read by *iteration and indexing*
# (`for c in BOARD_COLUMNS`, `BOARD_COLUMNS[:] = ...` in `tests/conftest.py:41`,
# untouched here), so this proxy forwards the list protocol instead
# (`__iter__`/`__getitem__`/`__setitem__`/`__len__`/`__contains__`). Every existing
# read site above, and the test-fixture reset, keep the name `BOARD_COLUMNS` and
# see something that behaves exactly like the list it used to be — the indirection
# through `_board_columns_store.for_current()` is invisible to every caller, same
# guarantee ruling 32 made for `settings`.
def _default_board_columns():
    # A fresh list of fresh dicts on every call — never a shared reference two
    # sessions could alias into the same object graph.
    return [
        {"column_id": "col_01H8X", "name": "Call today", "order": 1},
        {"column_id": "col_01H8Y", "name": "Awaiting payment", "order": 2},
        {"column_id": "col_01H8Z", "name": "Promise made", "order": 3},
        {"column_id": "col_01H90", "name": "Escalate", "order": 4},
    ]


_board_columns_store = session_domain.Store(_default_board_columns, key="main.board_columns")


class _BoardColumnsProxy:
    """List-shaped stand-in for the old module-level `BOARD_COLUMNS`. Delegates
    every list operation to the current session's slot."""

    def _list(self):
        return _board_columns_store.for_current()

    def __iter__(self):
        return iter(self._list())

    def __getitem__(self, key):
        return self._list()[key]

    def __setitem__(self, key, value):
        self._list()[key] = value

    def __len__(self):
        return len(self._list())

    def __contains__(self, item):
        return item in self._list()


BOARD_COLUMNS = _BoardColumnsProxy()


# X-Request-Id is generated when absent and ALWAYS echoed, and it is the `instance` of
# every problem response. A constant instance means a refused contact cannot be tied to
# the audit row it produced — which is the one thing an investigation needs.
REQUEST_ID: ContextVar = ContextVar("request_id", default="unknown")

# Dictionaries and static config may be cached; anything carrying a name, a phone number
# or a balance may not.
CACHEABLE_PATHS = ("/v1/board/columns", "/v1/meta/version", "/v1/config/pending",
                   "/healthz", "/livez", "/readyz")


@app.middleware("http")
async def audit_trail(request: Request, call_next):
    """Every act, recorded once, without any route having to remember.

    Ruling 12: registered FIRST — before request_identity and tester_session — so
    that it is the INNERMOST layer, not the outermost one. add_middleware() does
    insert(0, ...), so the LAST-registered middleware ends up outermost; that rule
    is already stated correctly below, at ApiPrefixMiddleware's docstring ("Added
    last, so it wraps outermost"). The original version of this middleware was
    registered AFTER tester_session on the mistaken belief that "after" in source
    order meant "runs after" — it meant the opposite: being added later made it
    MORE outer, so its body ran BEFORE request_identity set REQUEST_ID and BEFORE
    tester_session set session_domain.CURRENT, and every entry recorded
    session_id=None, request_id=None. Registered early, it runs late: both
    ContextVars are already populated by the time this body executes. Verify by
    reading a real entry back (test_audit_middleware.py), not by reasoning about
    registration order — reasoning about it is exactly how this broke the first
    time.
    """
    from . import audit, audit_store

    template = _route_template(request)
    logged = audit.is_logged(request.method, template)
    if not logged:
        return await call_next(request)

    claimed, source = await _actor_of(request)
    entry = {"actor_claimed": claimed, "actor_source": source,
             "actor_role": _role_of(request),
             "verb": request.method, "route_template": template,
             "act": "CASE_VIEWED" if request.method == "GET" else None,
             "subject_type": None, "subject_uid": None, "detail": {},
             "outcome": "OK", "status": 200, "error_code": None,
             "session_id": session_domain.CURRENT.get(None),
             "request_id": REQUEST_ID.get(None)}
    token = audit.CURRENT.set(entry)
    try:
        try:
            response = await call_next(request)
        except BaseException:
            # Final-review CRITICAL: this middleware sits INSIDE the framework's
            # own error handling, so an exception a route never caught propagates
            # straight through this call_next — and the code below that fills in
            # outcome/status never runs. Left alone, the `finally` block appended
            # the entry with its INITIALISED values: outcome="OK", status=200,
            # error_code=None. A route that crashed with an unhandled 500 was
            # recorded as a success — the worst thing this log can say, because
            # it is believed. Caught as BaseException, not Exception, so nothing
            # (not even a KeyboardInterrupt-shaped surprise) slips past this
            # without being recorded — and re-raised so the framework still
            # produces its own 500 response; this middleware never manufactures
            # a response of its own.
            entry["status"] = 500
            entry["outcome"] = "REFUSED"
            entry["error_code"] = "unhandled"
            raise
        entry["status"] = response.status_code
        entry["outcome"] = "OK" if response.status_code < 400 else "REFUSED"
        return response
    finally:
        try:
            from .production_unit import CURRENT as production_current
            unit = production_current.get()
            if unit is not None and entry.get("status", 500) >= 400:
                unit["refusal_audit"] = entry
            else:
                audit_store.append(entry)
        except Exception as exc:                       # noqa: BLE001
            # The act already happened. Refusing the response would not undo it,
            # only hide it — so the miss is counted and surfaced by /v1/audit/verify.
            from .production_unit import CURRENT as production_current
            if production_current.get() is not None:
                raise
            audit_store.record_gap(exc)
            print("audit append failed: %s" % exc, file=sys.stderr)
        finally:
            audit.CURRENT.reset(token)


# Login (design 2026-09-13). Added straight after audit_trail so it wraps it: the
# audit row sees the identity the session decided, not the one the browser sent.
# It stays inside request_identity (registered below, so more outer), which is
# what gives a refusal its request id. With AUTH_MODE unset it passes straight on.
from . import auth  # noqa: E402
from . import officers as _officers  # noqa: E402
from . import user_accounts as _user_accounts  # noqa: E402

auth.set_config(auth.load_config())
if auth.current_config().on:
    auth.check_officers(auth.current_config(), _officers.registry())
app.add_middleware(auth.AuthMiddleware,
                   request_id=lambda: REQUEST_ID.get(),
                   roster=lambda: _officers.registry(),
                   # WP10 (F13): a Google account's cookie stops here once its person is
                   # disabled, dropped from the seed, re-invited with another role or
                   # officer, or re-invited at all after the cookie was signed (B10b fix
                   # round 1 / I1: a cookie from before a disable stays dead after a
                   # same-role re-invitation) — at once on this process, within
                   # CACHE_SECONDS (30 s) on any other (the bound is spelled out in
                   # AuthMiddleware.__init__). Managing the user list re-checks fresh.
                   still_allowed=lambda session: _user_accounts.session_allowed(
                       session, auth.current_config().allowlist,
                       fresh=auth.current_config().session_policy == "tab"))


def _route_template(request):
    """The matched route's path, so rows group. None when nothing matched (404)."""
    for route in app.routes:
        match, _scope = route.matches(request.scope)
        if match.name == "FULL":
            return getattr(route, "path", None)
    return None


# B6 fix round 3 / M14: a NUL or a lone surrogate copied verbatim into
# actor_claimed makes audit_store.append's own INSERT fail ("surrogates not
# allowed"), so a request refused for exactly that reason (customer_contact.py's
# own text_invalid) left no audit row at all — the worse of the two dishonesties
# this log exists to avoid. Same character class as customer_contact._DANGEROUS_RE
# and notices.py's DANGEROUS_RE; not imported (this module does not otherwise
# depend on either), copied with the reason named.
_DANGEROUS_ACTOR_RE = re.compile("[\x00\ud800-\udfff]")


def _safe_actor_claim(value):
    """None when `value` cannot be recorded as an actor_claimed at all — not a str,
    or carrying a NUL/lone surrogate. None is honest here: the claim was not
    usable, not that nobody claimed anything."""
    if not isinstance(value, str) or _DANGEROUS_ACTOR_RE.search(value):
        return None
    return value


def _role_of(request):
    """R13: the signing role. The session's when there is one; else X-Volt-Role if it
    names a known role; else None. Never a body field."""
    session = request.scope.get("volt_auth")
    if session:
        return session.get("role")
    role = (request.headers.get("X-Volt-Role") or "").strip().upper()
    return role if role in audit.ROLES else None


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
            claimed = _safe_actor_claim(body["by"])
            if claimed is not None:
                return claimed, "BODY"
    return None, "NONE"


@app.middleware("http")
async def request_identity(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or "gen-" + uuid.uuid4().hex[:16]
    token = REQUEST_ID.set(request_id)
    try:
        response = await call_next(request)
    finally:
        REQUEST_ID.reset(token)
    response.headers["X-Request-Id"] = request_id
    # 2026-09-21: the staging link is shared publicly for user testing, so every
    # response refuses indexing — one line, on every path, including the SPA shell.
    # If a public marketing origin ever serves this app, this is the line to revisit.
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if request.url.path.startswith("/assets/") and response.status_code == 200:
        # Vite names every built file by its content hash, so a file here never changes:
        # a year, immutable. It was no-store (2026-09-27): every load re-sent ~745 KB and
        # re-gzipped it on staging's one CPU. index.html stays no-store, so a deploy
        # still reaches everyone on the next load.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif not any(request.url.path.startswith(p) for p in CACHEABLE_PATHS):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def tester_session(request: Request, call_next):
    """Bind durable work to the authenticated account; retain browser fallback in dev."""
    from .production_unit import CURRENT as production_current
    if production_current.get() is not None or shared_state_enabled():
        return await call_next(request)
    existing = request.cookies.get(session_domain.COOKIE)
    auth_session = None
    config = auth.current_config()
    if config.on:
        try:
            auth_session = await run_in_threadpool(auth.resolve_session, request.scope)
        except errors.Problem as problem:
            return problem.response()
    allowed_session = False
    if auth_session:
        try:
            allowed_session = await run_in_threadpool(
                _user_accounts.session_allowed, auth_session, config.allowlist,
                fresh=config.session_policy == "tab")
        except errors.Problem:
            # AuthMiddleware renders the authoritative refusal. The session layer
            # must only avoid loading a withdrawn account's durable state first.
            allowed_session = False
    principal = session_domain.principal_key(auth_session.get("sub")) if allowed_session else None
    session_id = principal or (session_domain.SHARED if config.on and auth_session else None) \
        or existing or session_domain.new_id()
    token = session_domain.CURRENT.set(session_id)
    # Only /v1 reads or writes a session's stores. The page shell, a static file or a
    # probe must not heal the session or pickle every store it holds — measured at 10x,
    # a warm session paid ~230 ms of pickling on each JS/CSS file the page loaded. The
    # cookie is still set here, so the shell hands it out before the first API calls.
    # PEAK's webhooks carry no browser (fix-all P7): no heal, no flush and no cookie, so
    # an event never mints and persists a session of its own.
    hook = request.url.path in auth.WEBHOOK_PATHS
    api = request.url.path.startswith("/v1/") and not hook
    # The stores this request asks for (the heal included); the flush checks only those.
    touched_token = session_domain.TOUCHED.set(set())
    try:
        # 2026-09-20 sync audit: a session that did not press Apply still meets the
        # imported facts on its own next request. The heal runs inside the session
        # scope (it reads and stamps that session's stores) and never fails the
        # request — the epoch stays unstamped, so the next request tries again.
        # Fix-all F1: in the threadpool, under the session's heal lock (ensure_current
        # takes it) — on the event loop a heal held every browser's request for its
        # second or more. anyio copies the context in: the session id, and TOUCHED,
        # whose set object stays shared, so the heal's stores are still flushed.
        from . import import_sync
        try:
            if api:
                from . import perf
                with perf.phase("session_heal"):
                    await run_in_threadpool(import_sync.ensure_current)
        except Exception as exc:                       # noqa: BLE001
            print("session import heal failed: %s" % exc.__class__.__name__, file=sys.stderr)
        # Fix-all F5: each contract worked out once per GET (see _contract_view).
        from . import request_context
        is_read = api and request.method == "GET"
        memo_token = _VIEW_MEMO.set({} if is_read else None)
        read_token = request_context.begin_read() if is_read else None
        try:
            response = await call_next(request)
        finally:
            if read_token is not None:
                request_context.end_read(read_token)
            _VIEW_MEMO.reset(memo_token)
        # The screen compares this with what it last saw; the rail and the stale
        # banner both read it. Cheap: the epoch is cached for a second in-process.
        from . import data_epoch
        response.headers["x-volt-data-epoch"] = str(data_epoch.current())
        # Callers mutate session state in place, so there is no per-mutation hook to
        # hang a write on; the end of the request is the honest moment. It must run
        # INSIDE the token's scope, or flush_current() would write to the wrong
        # session. A flush failure must never corrupt a response that already
        # succeeded, so it is reported and the request still returns.
        try:
            if api:
                from . import perf
                with perf.phase("session_flush"):
                    await run_in_threadpool(_flush_locked)
        except Exception as exc:                       # noqa: BLE001
            print("session flush failed: %s" % exc, file=sys.stderr)
    finally:
        session_domain.TOUCHED.reset(touched_token)
        session_domain.CURRENT.reset(token)
    if principal is None and not existing and not hook:
        response.set_cookie(
            session_domain.COOKIE, session_id,
            httponly=True, samesite="lax", max_age=60 * 60 * 12, path="/",
        )
    return response


def _flush_locked():
    """The end-of-request flush, off the event loop and under the session's heal lock
    (fix-all F1): a heal on another request of this session must not move the stores
    while they are pickled."""
    from . import import_sync
    with import_sync.session_lock():
        return session_domain.flush_current()


@app.middleware("http")
async def request_timing(request: Request, call_next):
    """Report request latency to stderr, behind $ROUTE_TIMING / $SLOW_REQUEST_MS.

    Off by default: with neither variable set this is one environment read, so the
    test suite and production are unchanged. ROUTE_TIMING=1 prints every request;
    SLOW_REQUEST_MS=250 prints requests over the line and every workbook sample so
    its logs-based p95 sees the complete distribution. The route template is used,
    not the live path, so a customer uid does not end up in a log line.

    Registered after tester_session, so it wraps it: the number includes the session
    flush, which is the write this instrumentation exists to make visible.
    """
    from .integrations import env as read_env
    threshold_raw = read_env("SLOW_REQUEST_MS")
    verbose = read_env("ROUTE_TIMING")
    if not threshold_raw and not verbose:
        return await call_next(request)
    from . import perf
    perf_token, phases = perf.begin()
    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        perf.end(perf_token)
    try:
        limit = float(threshold_raw) if threshold_raw else 0.0
    except ValueError:
        limit = 0.0
    route = _route_template(request) or request.url.path
    workbook_slo_sample = request.method == "GET" and route == "/v1/workbook"
    if verbose or workbook_slo_sample or elapsed_ms >= limit:
        print(json.dumps({
            "severity": "WARNING" if threshold_raw and elapsed_ms >= limit else "INFO",
            "metric": "http_server_duration_ms",
            "elapsed_ms": round(elapsed_ms, 1),
            "method": request.method,
            "route": route,
            "status": response.status_code if response is not None else 500,
            "phases_ms": perf.rounded(phases),
        }, sort_keys=True), file=sys.stderr)
    if response is None:
        raise RuntimeError("request completed without a response")
    return response


class ApiPrefixMiddleware:
    """Let the one origin serve /api without a proxy in front of it.

    api.js sends every call to /api (its BASE); this API serves /v1. In development
    the vite proxy strips the prefix (vite.config.js) and that was the ONLY thing
    that ever did. Deployed — Cloud Run, one service, interface built into the image
    — nothing stripped it, so every screen called /api/v1/... , hit the SPA
    catch-all's `api/` guard, took a 404 problem document and rendered its empty
    state. No suite caught it: e2e_check.py calls :8000 with no prefix, the browser
    round calls the dev proxy, and the unit tests stub fetch.

    Only /api/v1/... is stripped, and the trailing slash is the whole point: the
    prefix has to match a SEGMENT boundary. Anything else under /api — /api/nonsense,
    /api/v1board/columns, /api/v1 itself — stays unknown and reaches the guard in
    spa(), which refuses it as a problem document. /api/v1 with nothing after it names
    no route in either shape, so it is left alone rather than rewritten to a bare /v1
    that happens to 404 today.

    Plain ASGI rather than @app.middleware("http"): rewriting a path is a scope
    edit, and BaseHTTPMiddleware's re-entry into the app has moved between Starlette
    versions. Added last, so it wraps outermost and everything below — the cacheable
    path check in request_identity included — sees the real /v1 path.
    """

    _PREFIX = "/api"
    # The boundary, not the substring. `startswith("/api/v1")` also matched
    # `/api/v1board/columns`, rewrote it to `/v1board/columns`, and spa()'s guard tests
    # for `v1/` and `api/` and matches neither — so a typo came back as the HTML shell
    # with a 200, which api.js reads as success and parses into null.
    _API_ROOT = "/api/v1/"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") == "/api/openapi.json":
            scope = dict(scope, path="/v1/meta/openapi", raw_path=b"/v1/meta/openapi")
        if scope["type"] == "http" and scope.get("path", "").startswith(self._API_ROOT):
            scope = dict(scope)
            scope["path"] = scope["path"][len(self._PREFIX):]
            raw = scope.get("raw_path")
            if isinstance(raw, bytes) and raw.startswith(self._API_ROOT.encode()):
                scope["raw_path"] = raw[len(self._PREFIX):]
        await self.app(scope, receive, send)


from .production_unit import ProductionUnitMiddleware
app.add_middleware(ProductionUnitMiddleware)
app.add_middleware(ApiPrefixMiddleware)


@app.exception_handler(errors.Problem)
async def problem_handler(request: Request, exc: errors.Problem):
    from . import audit
    # Read here rather than parsed out of the response body: the handler already has
    # the code, and buffering a response to re-read it would be a second source of
    # truth for the same fact.
    audit.note_error(exc.code)
    return exc.response(instance="urn:request:" + REQUEST_ID.get())


# The framework raises its own errors for unknown routes, wrong methods and schema
# failures. Left alone they answer in FastAPI's shape, which has no `code` for a client
# to branch on and no `message_th` at all — and message_th is specified as ALWAYS
# present. One envelope means ONE envelope, including the errors nobody wrote by hand.
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Final-review finding: only problem_handler ever called audit.note_error, so a
    # request refused by the FRAMEWORK — an unknown route, a wrong method, any other
    # bare HTTPException — logged REFUSED with error_code left null, even though
    # spec §4 says the Problem code is recorded whenever an act is refused. Each
    # branch below builds its Problem first and records ITS code, same as
    # problem_handler does; note_error is a no-op when nothing is being logged for
    # this request (most 404s: an unmatched route has no route_template, so
    # audit.is_logged never opened an entry for it), so this is safe to call
    # unconditionally.
    from . import audit
    if exc.status_code == 404:
        problem = errors.not_found("route")
    elif exc.status_code == 405:
        problem = errors.method_not_allowed(request.method, request.url.path)
    else:
        problem = errors.Problem(
            code="http_error", status=exc.status_code, title=str(exc.detail),
            detail=str(exc.detail), message_th="เกิดข้อผิดพลาดในการเรียกใช้งาน",
            error_id="DEBT-PLT-%04d" % exc.status_code,
        )
    audit.note_error(problem.code)
    return problem.response(instance="urn:request:" + REQUEST_ID.get())


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    from . import audit
    field_errors = []
    malformed = False
    for err in exc.errors():
        if err.get("type") == "json_invalid":
            malformed = True
        pointer = "/" + "/".join(str(p) for p in err.get("loc", [])[1:]) or "/"
        field_errors.append({
            "pointer": pointer,
            "code": err.get("type", "invalid"),
            "message": err.get("msg", "invalid"),
            "message_th": "ข้อมูลในฟิลด์นี้ไม่ถูกต้อง",
        })
    if malformed:
        problem = errors.malformed_request()
        problem.errors = field_errors
    else:
        problem = errors.validation_failed(field_errors)
    audit.note_error(problem.code)
    return problem.response(instance="urn:request:" + REQUEST_ID.get())


# --- platform ------------------------------------------------------------------

# Google's front end reserves /healthz on *.run.app and answers 404 itself before the
# request reaches the container (found 2026-09-21 while smoke-testing staging — the
# local estate had hidden it). /livez is the same handler under a name the edge does
# not own, and it is what the smoke tools and uptime checks should use on a deployed
# estate. /healthz stays for local scripts and any internal caller.
@app.get("/livez")
@app.get("/healthz")
def healthz():
    """Cloud Run startup and liveness probe target."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """For the LB uptime check and the deploy smoke test. Cloud Run never calls this —
    readiness in the Kubernetes sense does not exist there."""
    if shared_state_enabled():
        from .production_runtime import readiness
        from fastapi.responses import JSONResponse
        import anyio
        try:
            with anyio.fail_after(2):
                ready = await anyio.to_thread.run_sync(readiness, abandon_on_cancel=True)
        except TimeoutError:
            ready = False
        return JSONResponse({"status": "ready" if ready else "unavailable"}, status_code=200 if ready else 503)
    from .integrations import odoo as odoo_client
    from .integrations import peak as peak_client
    return {
        "status": "ready",
        "business_date": str(settings.business_date),
        # R16 — configured/not, by variable NAME only. No probe here: readiness
        # must answer fast and a dead integration must not fail the deploy check.
        "integrations": {
            "odoo_configured": odoo_client.status()["configured"],
            "peak_configured": peak_client.status()["configured"],
        },
    }




@app.get("/v1/meta/openapi", include_in_schema=False)
def protected_openapi(request: Request):
    identity = request.scope.get("volt_auth")
    if not identity or identity.get("role") not in ("OPS", "OWNER"):
        raise errors.Problem("openapi_forbidden", 403, "API schema restricted",
                             "OPS or OWNER access is required.", "เฉพาะ OPS หรือ OWNER", "DEBT-API-403")
    return app.openapi()


@app.get("/v1/meta/version")
def version():
    return {
        "url_version": "v1",
        "document_version": "2.6",
        "note": "The document version moves; the URL version does not. Every change is additive.",
    }


# --- origination: orders and the loan book --------------------------------------
# Kept on their own paths so nothing here is mistaken for the arrears engine, which
# owns every figure under /v1/contracts.

@app.get("/v1/orders")
def list_orders(order_status: Optional[str] = None, q: Optional[str] = None):
    rows = orders_domain.orders()
    known = (orders_domain.STATUS_PENDING, orders_domain.STATUS_DONE)
    if order_status:
        if order_status not in known:
            raise errors.order_status_unknown(order_status, known)
        rows = [r for r in rows if r["order_status"] == order_status]
    if q:
        needle = q.strip().lower()
        fields = ("first_name", "last_name", "thai_name", "crm_id", "volt_id", "province")
        rows = [
            r for r in rows
            if needle in " ".join(str(r.get(f) or "") for f in fields).lower()
        ]
    everything = orders_domain.orders()
    return {
        "source": orders_domain.source(),
        "counts": {
            "pending": sum(1 for r in everything
                           if r["order_status"] == orders_domain.STATUS_PENDING),
            "done": sum(1 for r in everything
                        if r["order_status"] == orders_domain.STATUS_DONE),
        },
        "items": rows,
    }


@app.post("/v1/orders/{no}/approve")
def approve_order(no: int, payload: dict = Body(default=None)):
    audit.describe(act="ORDER_APPROVED", subject=("order", str(no)))
    by = (payload or {}).get("by") or "Nok"
    existing = orders_domain.get(no)
    if existing is None:
        raise errors.not_found("order")
    entry, error = orders_domain.approve(no, by)
    if error == "already_approved":
        raise errors.order_already_approved(no, orders_domain.STATUS_DONE)
    if error == "loan_not_approved":
        raise errors.loan_not_approved(no, existing.get("loan_status"))
    return {"order": entry, "loan_book_size": len(orders_domain.loan_book())}


@app.post("/v1/orders", status_code=201)
def create_order(body: dict = Body(...)):
    audit.describe(act="ORDER_CREATED")
    by = (body or {}).get("by") or "Nok"
    order, error = orders_domain.add(body, by)
    if error and error.startswith("missing:"):
        fields = error.split(":", 1)[1].split(",")
        raise errors.order_invalid([
            {"pointer": "/" + f, "code": "required", "message": "%s is required." % f}
            for f in fields
        ])
    if error == "crm_id_taken":
        raise errors.crm_id_taken(str(body.get("crm_id")).strip())
    return {"order": order}


@app.delete("/v1/orders/{no}")
def delete_order(no: int):
    audit.describe(act="ORDER_DELETED", subject=("order", str(no)))
    order, error = orders_domain.remove(no)
    if error == "not_found":
        raise errors.not_found("order")
    if error == "in_loan_book":
        raise errors.order_in_loan_book(no)
    return {
        "removed": order,
        # Said plainly on every removal: the sheet is read-only from here.
        "note": "Removed for this run only. The source sheet is not written to.",
    }


@app.get("/v1/loan-book")
def get_loan_book():
    entries = orders_domain.loan_book()
    return {
        # NOT orders_domain.source(): loan_book() reads the sheet's Loan Book tab and
        # never the Odoo rows, so the orders rung would have named a system that
        # supplied none of these 80 entries (live UAT, 2026-09-09). Each entry still
        # declares its own `origin`, and counts split sheet from approved-here.
        "source": orders_domain.sheet_source(),
        "counts": {
            "total": len(entries),
            "from_sheet": sum(1 for e in entries if e["origin"] == "sheet"),
            "approved_here": sum(1 for e in entries if e["origin"] == "approved"),
        },
        "entries": entries,
    }


# --- UAT: the task script and feedback -----------------------------------------
# Tester STATE is per session; tester FEEDBACK is not. Feedback is the output of the
# round and the whole team must see it.

@app.get("/v1/uat/tasks")
def uat_tasks_list():
    return {
        "tasks": uat_tasks.tasks(),
        "limitations": uat_tasks.LIMITATIONS,
        "ratings": list(feedback_domain.RATINGS),
    }


@app.post("/v1/feedback", status_code=201)
def create_feedback(body: dict = Body(...)):
    audit.describe(act="FEEDBACK_SUBMITTED")
    tester = (body or {}).get("tester") or "unnamed tester"
    entry, error = feedback_domain.add(body, tester, str(settings.business_date))
    if error == "empty":
        raise errors.feedback_empty()
    if error == "rating_unknown":
        raise errors.feedback_rating_unknown((body or {}).get("rating"), feedback_domain.RATINGS)
    if error == "comment_too_long":
        raise errors.feedback_too_long(feedback_domain.MAX_COMMENT)
    return {"feedback": entry}


@app.get("/v1/feedback")
def list_feedback():
    """The export path. Everything the round has collected, newest last."""
    return {"summary": feedback_domain.summary(), "entries": feedback_domain.entries()}


# --- executive overview ---------------------------------------------------------

def _collections_figures():
    """The collections side of the overview, counted PER CUSTOMER.

    Counting per contract would let one customer holding three late contracts
    appear three times in a portfolio-at-risk figure.
    """
    accounts = 0
    arrears = Decimal("0.00")
    at_risk = 0
    for customer in CUSTOMERS:
        total, oldest, _band, _outstanding = _customer_aggregate(customer)
        accounts += 1
        arrears += total
        if oldest is not None and oldest >= 30:
            at_risk += 1
    return {"accounts": accounts, "arrears": str(arrears), "at_risk_30": at_risk}


@app.get("/v1/criteria/default")
def get_default_criteria():
    saved = criteria_domain.get_default()
    return {
        "default": saved.to_dict() if saved else None,
        "populations": criteria_domain.POPULATIONS,
        "targetable": list(criteria_domain.TARGETABLE),
    }


@app.put("/v1/criteria/default")
def put_default_criteria(body: dict = Body(default={})):
    audit.describe(act="CRITERIA_SET")
    by = (body or {}).get("by") or "Nok"
    saved, error = criteria_domain.save_default(body, by, str(settings.business_date))
    if error:
        raise errors.criteria_invalid(error)
    return {"default": saved.to_dict()}


@app.delete("/v1/criteria/default")
def delete_default_criteria():
    audit.describe(act="CRITERIA_CLEARED")
    return {"cleared": criteria_domain.clear_default()}


@app.get("/v1/overview")
def overview(
    population: Optional[str] = Query(default=None),
    province: Optional[str] = Query(default=None),
    order_type: Optional[str] = Query(default=None),
):
    saved = criteria_domain.get_default()
    if population or province or order_type:
        # An explicit query beats the saved default, and the response says which
        # one it used so a figure can never be read against the wrong population.
        active, error = criteria_domain.build({
            "population": population or (saved.population if saved else "all_orders"),
            "province": province or (saved.province if saved else None),
            "order_type": order_type or (saved.order_type if saved else None),
            "targets": saved.targets if saved else {},
        })
        if error:
            raise errors.criteria_invalid(error)
        if saved:
            active.set_by, active.set_at = saved.set_by, saved.set_at
        source = "query"
    elif saved:
        active, source = saved, "saved_default"
    else:
        active, _ = criteria_domain.build({})
        source = "fallback"

    body = overview_domain.build(
        orders_domain.orders(),
        orders_domain.loan_book(),
        _collections_figures(),
        active,
    )
    body["criteria_source"] = source
    return body


@app.get("/v1/config/pending")
def pending_decisions():
    """Everything the prototype refuses to decide on its own behalf."""
    return {
        "pending": [
            {
                "key": rule.key,
                "decision": rule.decision,
                "owner": rule.owner,
                "note": rule.note,
                "shipped_default": _shipped_default(rule.key),
                # RUNNING / REFUSING / LEAKING. The interface must not derive this
                # from a null shipped_default: null covers both "the engine stops"
                # and "the engine renders a number from a literal somewhere else",
                # and those two are not the same fact.
                "state": rule.state,
                "surfaces_as": rule.surfaces_as,
            }
            for rule in PENDING.values()
        ]
    }


def _shipped_default(key):
    value = getattr(settings, key, None)
    return str(value) if value is not None else None


# --- money helpers --------------------------------------------------------------

# Fix-all F5: one GET works the same contract out several times (the list, each
# customer's aggregate, the rail's counts). tester_session gives every GET /v1 request
# a dict here — None otherwise, and outside a request — keyed (contract uid, as_of). A
# hit needs the SAME contract object: the book may be rebuilt mid-request. Callers only
# read the result.
_VIEW_MEMO: ContextVar = ContextVar("contract_view_memo", default=None)


def _contract_view(contract, as_of=None):
    """(contract, dpd, band, block, period) — memoised per GET request (fix-all F5)."""
    as_of = as_of or settings.business_date
    memo = _VIEW_MEMO.get()
    if memo is None:
        return _work_out_contract(contract, as_of)
    hit = memo.get((contract.uid, as_of))
    if hit is None or hit[0] is not contract:
        hit = memo[(contract.uid, as_of)] = (contract, _work_out_contract(contract, as_of))
    return hit[1]


def rows_for(rows, field, values):
    """[r for r in rows if r[field] in values], in store order, over a dict or list store.

    2026-09-27 staging: payment_position scanned every invoice and receipt of the
    session for EVERY row of every build — 64% of today.build() on the real book. The
    second ask within one GET builds an index (kept in _VIEW_MEMO; same store object
    and size, or it is rebuilt). The first ask, and anything outside a GET, is the plain
    scan — a case page asks once and must not pay for an index.
    """
    store = rows.values() if isinstance(rows, dict) else rows
    memo = _VIEW_MEMO.get()
    if memo is None:
        return [r for r in store if r[field] in values]
    key = ("rows_for", id(rows), field)
    hit = memo.get(key)
    if hit is None or hit[0] is not rows or hit[1] != len(rows):
        memo[key] = (rows, len(rows), None)
        return [r for r in store if r[field] in values]
    if hit[2] is None:
        index = {}
        for n, row in enumerate(store):
            index.setdefault(row[field], []).append((n, row))
        hit = memo[key] = (rows, len(rows), index)
    found = [pair for value in values for pair in hit[2].get(value, ())]
    if len(values) > 1:
        found.sort(key=lambda pair: pair[0])
    return [row for _n, row in found]


def _work_out_contract(contract, as_of=None):
    """One place computes every money figure. No arithmetic in the API layer above
    this function and none at all in the interface."""
    # 2026-09-24: the business date is resolved on read (config.resolve_business_date),
    # so the default is the date NOW, not the one this module was imported on.
    as_of = as_of or settings.business_date
    from . import instalment_evidence, payment_summary, journey
    strict = instalment_evidence.required(contract)
    # The fee state decides the fee, and separately the clock. Never derive one from
    # the other: a permit hold pauses the fee and leaves the clock running.
    #
    # And it pauses FROM THE DAY IT OPENS. Applying it to the whole history would erase
    # fee that legitimately accrued before the hold, restating the customer's arrears
    # retroactively — the mirror image of the rule that a paused day is never recomputed.
    # Round-2 N2-07 / T2-08: a hold that has ended stays on the record
    # (fee_state_history) so its paused days are never recomputed either.
    # Ruling 43 / R4-F01: these six fields are session-scoped now — read through
    # _contract_field_of, never off the shared contract attribute directly.
    state_from = _contract_field_of(contract, "fee_state_from")
    state_until = _contract_field_of(contract, "fee_state_until")
    history = [h for h in (_contract_field_of(contract, "fee_state_history") or []) if h.get("from")]
    # Ruling 49: the schedule itself is session-scoped too, the same way — a session
    # that has not restructured this contract never sees another session's addendum.
    instalments = _contract_field_of(contract, "instalments")
    if strict:
        instalments = instalment_evidence.collection_lines(
            contract, journey.for_current(), payment_summary._active_lines(contract))

    def state_on(day):
        # Round-3 J3-18: the fee FELL the moment a ticket opened — the hold's own opening
        # day was excluded from accrual, so a freeze announced for today took a day off
        # the number the officer was looking at. The freeze holds the fee WHERE IT STANDS:
        # the opening day still accrues, every day after it is paused. (The DPD freeze is
        # a separate column and still starts on the opening day — the frozen-day count
        # below reads the interval, not this gate.)
        for hold in history:
            if hold["from"] < day and (hold.get("until") is None or day < hold["until"]):
                return hold["state"]
        current = _contract_field_of(contract)
        if not current:
            return None
        if state_from and day <= state_from:
            return None
        if state_until and day >= state_until:
            return None
        return current

    # The clock: days under a state whose table row says stops_clock are frozen days.
    overdue_dates = [i.due_date for i in instalments
                     if i.is_active_regular and i.due_date < as_of and i.outstanding_amount > 0]
    frozen = 0
    if overdue_dates:
        from .money.fee_states import FEE_STATES
        intervals = [(h["state"], h["from"], h.get("until")) for h in history]
        current = _contract_field_of(contract)
        if current and state_from:
            intervals.append((current, state_from, state_until))
        start = min(overdue_dates)
        for code, from_day, until_day in intervals:
            row = FEE_STATES.get(code)
            if not row or not row.stops_clock:
                continue
            lo, hi = max(from_day, start), min(until_day or as_of, as_of)
            frozen += max(0, (hi - lo).days)
    # Amendment v2.6: while a service-fault hold exempts NPL assessment, the screen
    # still shows the debt's real age. Other historical clock rules remain intact.
    actual_dpd = compute_dpd(instalments, as_of=as_of, frozen_days=0)
    assessment_hold = _contract_field_of(contract) == "SERVICE_HOLD_FAULT_CONFIRMED"
    dpd = actual_dpd if assessment_hold else compute_dpd(
        instalments, as_of=as_of, frozen_days=frozen
    )

    if strict and not instalments:
        dpd = None

    arrears_at = _arrears_as_of(contract, instalments if strict else None)

    oldest_overdue = [i for i in instalments
                      if i.due_date < as_of and i.outstanding_amount > 0]
    if oldest_overdue:
        period = accrue_range(
            due_date=min(i.due_date for i in oldest_overdue),
            arrears_on=arrears_at,
            through=as_of,
            rate=settings.late_payment_daily_rate,
            grace_days=settings.late_payment_grace_days,
            state_on=state_on,
        )
    else:
        period = None

    # Ruling 43 / R4-F03: session-scoped read — never contract.status directly.
    status = _contract_field_of(contract, "status")
    band = resolve_band(status, dpd, settings.band_set_code)
    if strict and dpd is None and band.code is None:
        band = resolve_band("EVIDENCE_UNVERIFIED", dpd, settings.band_set_code)
    block = arrears_block(
        instalments,
        ledger_date=as_of,
        penalty_accrued_unbilled=period.cumulative_amount if period else Decimal("0.00"),
        days_past_due=dpd,
        aging_bucket=band.code,
        band_set_code=band.band_set_code,
    )
    return contract, dpd, band, block, period


def _arrears_as_of(contract, evidence_lines=None):
    """The fee base for each day, respecting EACH instalment's own grace.

    Not simply "everything past due": an instalment that fell due yesterday is in
    arrears and is not yet chargeable. Using the arrears figure directly overcharges
    by 234.36 on a two-instalment contract — see tests/test_contract_accrual.py.
    """
    return chargeable_arrears_by_day(
        evidence_lines if evidence_lines is not None else _contract_field_of(contract, "instalments"),
        settings.late_payment_grace_days)


# Aging bands ordered by how bad they are. A customer's band must be the most severe
# band among their contracts: an officer reading a DPD from one contract beside a band
# from another cannot tell whether the customer is in Risk Review at all.
_BAND_SEVERITY = {
    None: -1, "CLOSED": 0, "RESOLVED": 0, "CURRENT": 1, "EVIDENCE_UNVERIFIED": 1.5,
    "EARLY_OVERDUE": 2, "MID_OVERDUE": 3, "RISK_REVIEW": 4, "NPL_CONFIRMED": 5,
    "COLLECTION_1_30": 2, "COLLECTION_31_60": 3,
    "COLLECTION_61_89": 4, "COLLECTION_90_PLUS": 5,
}


def _customer_band(status_dpd_pairs, band_set_code):
    bands = [resolve_band(status, dpd, band_set_code) for status, dpd in status_dpd_pairs]
    if not bands:
        return resolve_band("PRE_COLLECTION", None, band_set_code)
    return max(bands, key=lambda b: _BAND_SEVERITY.get(b.code, -1))


def _customer_aggregate(customer):
    """Returns the customer's arrears, their worst DPD, and their worst band.

    aggregate_overdue must reconcile EXACTLY to the contracts beneath it — a fully
    drawn total that does not is the defect class the 25-08 audit found.
    """
    total = Decimal("0.00")
    outstanding = Decimal("0.00")
    oldest = None
    pairs = []
    for contract in customer.contracts:
        _, dpd, contract_band, block, _ = _contract_view(contract)
        from . import invoice_reviews, journey
        imported = invoice_reviews.contract_arrears(customer, contract, journey.for_current(), settings.business_date)
        arrears = block.cumulative_arrears
        if imported is not None:
            arrears, dpd = imported
        total += arrears
        outstanding += block.closing_balance
        # Ruling 43 / R4-F03: session-scoped read.
        status = "EVIDENCE_UNVERIFIED" if contract_band.code == "EVIDENCE_UNVERIFIED" else _contract_field_of(contract, "status")
        pairs.append((status, dpd))
        if dpd is not None and (oldest is None or dpd > oldest):
            oldest = dpd
    return total, oldest, _customer_band(pairs, settings.band_set_code), outstanding


# --- screen 01, the today list ---------------------------------------------------

def _officer_overlay():
    # Ruling 40: same shape as _contract_field_of below — POST /v1/customers/{uid}/assign
    # writes here, never onto the shared Customer fixture's `.officer`.
    from . import journey
    return journey.for_current().officer_overlay


def _contract_field_of(contract, field="fee_state"):
    # Ruling 43 / R4-F01 + R4-F03: fee_state and its five siblings, plus `status`,
    # live in cases.py's per-session overlay now — same shape as
    # _officer_overlay above. Never read contract.<field> directly for
    # these; a session's service hold or NPL/write-off must not be visible to a
    # session that never took the action.
    from . import cases as cases_domain
    return cases_domain.contract_field_of(contract, field)


@app.get("/v1/today-list")
def today_list(date: Optional[str] = None, group_by: str = "work_today"):
    """Grouped by CUSTOMER, never by contract. A customer holding several contracts
    has one officer and receives one contact covering all of them — a list keyed on
    contracts would let one customer be called twice in a day."""
    if date and date != str(settings.business_date):
        raise errors.business_date_unavailable(date, settings.business_date)

    items = []
    counts = {}
    for customer in CUSTOMERS:
        total, oldest, band, outstanding = _customer_aggregate(customer)
        lock = contact_log.locks_for(customer.identity_key, settings.business_date, level="PERSON")
        items.append({
            "uid": "tli-%s" % customer.customer_no,
            "priority": customer.priority,
            "reason_code": customer.reason_code,
            "customer": {
                "uid": customer.uid,
                "customer_no": customer.customer_no,
                "display_name": customer.display_name,
                "phone_masked": customer.phone_masked,
                "contract_count": len(customer.contracts),
            },
            "aggregate_overdue": str(total),
            # The balance that sits small beneath the arrears. Without it on the wire the
            # interface would have to invent a figure or draw a lone number.
            "aggregate_outstanding": str(outstanding),
            # Placement by stable id. A renamed column must not move a single card.
            # Derived where it is served, by app/board.py — the seed-time pass and the
            # per-session placement store it raced are both gone.
            **board.serve(customer, oldest),
            "oldest_dpd": oldest,
            "aging_bucket": band.code,
            "band_set_code": band.band_set_code,
            "fee_state": _contract_field_of(customer.contracts[0]),
            "recovery_stage": customer.recovery_stage,
            "officer": _officer_overlay().get(customer.uid, customer.officer),
            "contact_lock": {
                "state": "LOCKED" if lock else "OPEN",
                # WHO holds today's slot, not the customer's identity hash — an officer
                # cannot act on a hash.
                "locked_by": lock[0].officer if lock else None,
                "locked_at": str(lock[0].taken_at) if lock else None,
                "locked_at_local_th": clock.local_stamp_th(lock[0].taken_at) if lock else None,   # J3-15
                "locked_at_local_en": clock.local_stamp_en(lock[0].taken_at) if lock else None,
                "result": lock[0].result if lock else None,
            },
        })
        counts[str(customer.priority)] = counts.get(str(customer.priority), 0) + 1

    items.sort(key=lambda i: i["priority"])
    return {
        "run": {
            "run_uid": "run-prototype",
            "business_date": str(settings.business_date),
            "job": "today-list",
        },
        "items": items,
        "meta": {"total_estimate": len(items), "counts_by_priority": counts, "group_by": group_by},
    }


@app.get("/v1/board/columns")
def board_columns():
    # `list(...)`, not the bare proxy: FastAPI's `jsonable_encoder` only recognises
    # the built-in container types by `isinstance`, so a custom iterable (however
    # list-shaped in Python) serialises as `{}` — caught live by the failing gate
    # run below, not asserted from memory.
    return {
        "columns": list(BOARD_COLUMNS),
        "note": (
            "A column's identity is column_id, never its name. Renaming is a non-event. "
            "An officer's arrangement is a hidden set plus an explicit order stored only "
            "once they reorder, so an Owner reorder still reaches anyone with no preference."
        ),
    }


@app.delete("/v1/board/columns/{column_id}")
def delete_column(column_id: str, body: dict = Body(default={})):
    audit.describe(act="BOARD_COLUMN_DELETED", subject=("board_column", column_id))
    known = {c["column_id"] for c in BOARD_COLUMNS}
    if column_id not in known:
        raise errors.not_found("column")
    # Round-4, ruling 39: this used to read AND write `customer.board_column_id`
    # directly on the shared `CUSTOMERS` fixture objects — a write that outlived
    # every session, not merely leaked across them. Ruling 39 moved it onto the
    # per-session `board_overlay`; the 2026-09-09 spec deletes that store, so the
    # column is asked for in `app/board.py`, where every other reader asks, instead of
    # a second mechanism beside it (PROJECT.md: a second pattern for the same job is a
    # MAJOR finding waiting to happen). The two helpers below both ask that one module
    # — `column_for` for the act, `derive` (which `column_for` itself calls) for the
    # count. `CUSTOMERS` itself is read here only for identity (uid, customer_no) —
    # never assigned to.
    from . import journey

    def _column_of(customer):
        """The column a customer stands on, as a real read: `board.column_for` expires
        an outlived override and records what it served, which is what a placement
        rewrite should do. Only the relocation sweep below — the successful act — is
        allowed to call this."""
        _t, oldest, _b, _o = _customer_aggregate(customer)
        return board.column_for(customer, oldest)

    def _count_standing_on(target):
        """The same question asked WITHOUT touching anybody's state.

        `board.column_for` is a writer: it expires overrides, appends
        BOARD_OVERRIDE_EXPIRED / BOARD_AUTO_MOVED to the case trail and consumes the
        one-read `auto_moved` marker. This count exists only to fill one extension on
        one refusal, and a refused request must not cost a customer the news they were
        about to be shown — so it derives, and derives nothing else.
        """
        return sum(1 for c in CUSTOMERS
                   if board.derive(**board.facts_for(c, _customer_aggregate(c)[1])) == target)

    # Nothing above here has touched a customer, and nothing below here does until the
    # request is known to be well formed.
    destination = (body.get("destination_column_id") or "").strip()
    if not destination:
        # Counted lazily, inside the one refusal that reports it — the Owner is being
        # asked to find each of these customers a destination, so it is a real figure
        # and not a stand-in.
        raise errors.destination_column_required(column_id, _count_standing_on(column_id))
    if destination not in known or destination == column_id:
        raise errors.destination_column_unknown(destination)
    # Spec §9b: the four the rule can return are not the Owner's to remove — deleting one
    # would leave `board.derive` naming a column that does not exist. Any column an Owner
    # adds beyond them still deletes, and still relocates its cards.
    #
    # This sits AFTER the destination checks on purpose. Both are 422s, so the order is
    # not about status codes but about which question the caller is answering: whether a
    # destination was nominated, and whether it exists, are facts about the REQUEST, and
    # `test_api.py:296` and `test_api_hardening.py:107` both assert them against a derived
    # column. Refusing on policy first would make a malformed request report a policy it
    # never got far enough to violate. What DID move is the customer sweep, which used
    # to run in front of all three of these and made every refusal a write.
    if column_id in board.DERIVED_COLUMNS:
        raise errors.board_column_derived(column_id, board.DERIVED_COLUMNS)

    # A card can only be standing on a non-derived column because an override put it
    # there, so relocating one is rewriting that override — never a second placement
    # store beside it.
    overrides = journey.for_current().board_overrides
    moved = []
    for customer in CUSTOMERS:
        if _column_of(customer) == column_id:
            moved.append(customer.customer_no)
            if customer.uid in overrides:
                overrides[customer.uid]["to_column_id"] = destination
    BOARD_COLUMNS[:] = [c for c in BOARD_COLUMNS if c["column_id"] != column_id]
    # Logged per customer — that is the requirement, not a bulk count.
    return {"deleted": column_id, "moved_to": destination, "moved_customers": moved}


# --- screen 02, the contract card -------------------------------------------------

@app.get("/v1/customers/{customer_uid}/contracts")
def customer_contracts(customer_uid: str):
    customer = BY_CUSTOMER.get(customer_uid)
    if customer is None:
        raise errors.not_found("customer")

    rows = []
    for contract in customer.contracts:
        _, dpd, band, block, _ = _contract_view(contract)
        rows.append({
            "uid": contract.uid,
            "product": contract.product,
            # Ruling 43 / R4-F03: session-scoped read.
            "status": _contract_field_of(contract, "status"),
            "arrears": str(block.cumulative_arrears),
            "outstanding_balance": str(block.closing_balance),
            "days_past_due": dpd,
            "aging_bucket": band.code,
            "band_set_code": band.band_set_code,
            "fee_state": _contract_field_of(contract),
        })
    return {"customer_uid": customer_uid, "contracts": rows}


@app.get("/v1/contracts/{contract_uid}/summary")
def contract_summary(contract_uid: str):
    found = BY_CONTRACT.get(contract_uid)
    if found is None:
        raise errors.not_found("contract")
    _customer, contract = found
    _, dpd, band, block, period = _contract_view(contract)

    payload = dict(block.to_ordered_dict())
    decomposition = period.decomposition() if period else {
        "accrued": Decimal("0.00"), "not_accrued_by_state": {}, "reversed": Decimal("0.00"),
    }
    payload["accrued_penalty"] = {
        **{k: str(v) for k, v in payload["accrued_penalty"].items() if k != "composition"},
        "composition": {k: str(v) for k, v in payload["accrued_penalty"]["composition"].items()},
        # Ruling 87: CF1 is decided, so this figure is no longer indicative and a PEAK
        # penalty draft may be created from it (C3 keeps that a draft).
        "is_indicative": False,
        "decided_by_ruling": 87,
        "rate_applied": str(settings.late_payment_daily_rate),
        "grace_days_applied": settings.late_payment_grace_days,
        # Ruling 88: OD-31 (grace days) is decided too, the same way CF1 is — see
        # config.DECIDED.
        "grace_decided_by_ruling": 88,
        # REQ-MNY-032 item 6 — never a single net number.
        "accrued": str(decomposition["accrued"]),
        "not_accrued_by_state": {k: str(v) for k, v in decomposition["not_accrued_by_state"].items()},
        "reversed": str(decomposition["reversed"]),
    }
    payload["fee_state"] = _contract_field_of(contract)
    payload["schedule_note"] = (
        "The final instalment is the balancing figure and may differ from the regular "
        "instalment. Accounting must be told before the first customer statement."
    )
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in payload.items()}


@app.post("/v1/contracts/{contract_uid}/penalty-invoices", status_code=201)
def raise_penalty_invoice(contract_uid: str, body: dict = Body(default={})):
    audit.describe(act="PENALTY_INVOICE_RAISED", subject=("contract", contract_uid))
    if contract_uid not in BY_CONTRACT:
        raise errors.not_found("contract")
    if not settings.penalty_invoicing_enabled:
        # Ruling 87 decided CF1, so a flag left off here is an Owner's configuration
        # choice, not an open decision — no more pending_decision/owner to name, the
        # same shape as the sibling gate in peak_documents.py's PENALTY_INVOICE path.
        raise errors.feature_disabled(
            feature="penalty_invoicing",
            reason="Penalty invoicing to PEAK is off by configuration (penalty_invoicing_enabled).",
        )
    return {"created": True}


@app.post("/v1/contracts/{contract_uid}/transactions", status_code=201)
def create_transaction(contract_uid: str, body: dict = Body(...)):
    """The MANUAL path. Refuses and writes nothing while OD-02 is open."""
    audit.describe(act="TRANSACTION_RECORDED", subject=("contract", contract_uid))
    # Existence first: answering a business-rule 422 for a contract that is not there
    # tells an integrator their payload was wrong when their ID was wrong.
    if contract_uid not in BY_CONTRACT:
        raise errors.not_found("contract")
    if settings.allocation_component_order is None:
        raise errors.allocation_rule_pending()
    return {"allocated": True}


@app.post("/v1/webhooks/peak/payments")
def peak_payment():
    """Gone (fix-all P10c): this answered 202 `recorded: true` and kept nothing but an
    in-memory idempotency entry. PEAK posts to its registered webhooks below, which
    store every event; the 410 names them so a caller of the old path learns where."""
    audit.describe(act="PEAK_PAYMENT_RECEIVED")
    raise errors.Problem(
        code="webhook_gone", status=410,
        title="This webhook is gone — PEAK posts to /v1/webhooks/peak/{contact,invoice,receipt}",
        detail="Nothing is recorded here. PEAK's registered webhooks are %s" % ", ".join(auth.WEBHOOK_PATHS),
        message_th="ช่องทางนี้เลิกใช้แล้ว ไม่มีการบันทึกใด ๆ — PEAK ส่งข้อมูลมาที่ %s" % ", ".join(auth.WEBHOOK_PATHS),
        error_id="DEBT-INT-0410", extensions={"paths": list(auth.WEBHOOK_PATHS)})


@app.post("/v1/webhooks/peak/{kind}")
async def peak_webhook(kind: str, request: Request):
    """PEAK's registered webhooks, Stage A: stored, not acted on (app/peak_webhooks.py).

    No login session — auth.WEBHOOK_PATHS lets these through; the x-api-key is the gate.
    """
    audit.describe(act="PEAK_WEBHOOK_RECEIVED", detail={"kind": kind})
    if kind not in peak_webhooks.KINDS:
        raise errors.not_found("webhook")
    peak_webhooks.check_key(request.headers.get("x-api-key"))
    body = await request.body()
    # Fix-all P7: an empty or oversized body is stored (cut and flagged), never refused —
    # PEAK does not retry a 4xx, so a refusal loses the event.
    new = await run_in_threadpool(peak_webhooks.record, kind, body,
                                  request.headers.get("content-type"))
    return {"received": True, "duplicate": not new}


# --- screen 03, the exception dashboard --------------------------------------------

# A population is a real selection, not a label. Echoing one the endpoint did not apply
# stamps a fabricated answer on the dashboard's own face — the blind pass called this
# out, and it is worse than the refusal it sits next to.
POPULATION_FILTERS = {
    "ALL_OPEN": lambda contract, dpd: True,
    "OVERDUE": lambda contract, dpd: bool(dpd),
    "PERMIT_HELD": lambda contract, dpd: _contract_field_of(contract) == "PERMIT_HOLD",
    "FEE_PAUSED": lambda contract, dpd: _contract_field_of(contract) in ("PERMIT_HOLD", "DECEASED",
                                                              "PROPERTY_SOLD_NOVATION_UNRESOLVED",
                                                              "JURISTIC_DISSOLVED",
                                                              "SERVICE_HOLD_FAULT_CONFIRMED"),
    "RISK_REVIEW": lambda contract, dpd: (dpd or 0) >= 30,
}


@app.get("/v1/dashboards/exceptions")
def exception_dashboard(population_filter: Optional[str] = Query(default=None)):
    if not population_filter or not population_filter.strip():
        raise errors.population_filter_unset()
    population_filter = population_filter.strip()
    if population_filter not in POPULATION_FILTERS:
        raise errors.population_filter_unknown(population_filter, sorted(POPULATION_FILTERS))
    matches = POPULATION_FILTERS[population_filter]

    rows = []
    for customer in CUSTOMERS:
        for contract in customer.contracts:
            _, dpd, band, block, period = _contract_view(contract)
            if not matches(contract, dpd):
                continue
            paused = bool(period and any(d.paused_by_state for d in period.days))
            rows.append({
                "contract_uid": contract.uid,
                "customer_name": customer.display_name,
                "days_past_due": dpd,
                "aging_bucket": band.code,
                "band_set_code": band.band_set_code,
                "arrears": str(block.cumulative_arrears),
                "outstanding_balance": str(block.closing_balance),
                "fee_state": _contract_field_of(contract),
                "fee_paused": paused,
            })
    return {
        "population_filter": population_filter,
        "rows": rows,
        "meta": {
            "business_date": str(settings.business_date),
            # RB-KPI-01: "Read the report's own face: population filter, band set,
            # discount rate version. If ANY is absent the run is void." Unset is a
            # legitimate value; silence is not.
            "population_filter": population_filter,
            "band_set_code": settings.band_set_code,
            "discount_rate_version": None,
            "discount_rate_pending_decision": "OQ-31",
            # Two named indicators, not one.
            "collection_indicators": ["cash_received", "due_month_attainment"],
            # The denominator excludes service-held, permit-held and closing contracts.
            "denominator_excludes": ["SERVICE_HOLD_FAULT_CONFIRMED", "PERMIT_HOLD", "CLOSING"],
        },
    }


# --- screen 05, the recovery board ---------------------------------------------------

@app.get("/v1/recovery-board")
def recovery_board():
    from . import cases, journey
    from .money.band_sets import label_for
    overlay = journey.for_current().recovery_overlay
    case_of = cases.for_current().cases
    stages = ["CONTACT", "NEGOTIATE", "PROMISE", "ESCALATE", "RECOVERY"]
    columns = []
    for stage in stages:
        members = [c for c in CUSTOMERS
                   if overlay.get(c.uid, c.recovery_stage) == stage]
        total = Decimal("0.00")
        cards = []
        for customer in members:
            arrears, oldest, band, outstanding = _customer_aggregate(customer)
            total += arrears
            case = case_of.get(customer.uid)
            cards.append({
                "customer_uid": customer.uid,
                "display_name": customer.display_name,
                "arrears": str(arrears),
                # fix-all Leg R: the card's balance line, band words and status pill —
                # the same figures and labels the work item serves.
                "aggregate_outstanding": str(outstanding),
                "oldest_dpd": oldest,
                "aging_bucket": band.code,
                "aging_bucket_label_th": label_for(band.band_set_code, band.code),
                "aging_bucket_label_en": label_for(band.band_set_code, band.code, "en"),
                "band_set_code": band.band_set_code,
                "payment_status": case["payment_status"] if case else None,
                "fee_state": _contract_field_of(customer.contracts[0]),
            })
        columns.append({
            "stage": stage,
            "cards": cards,
            # A fully-drawn column must reconcile EXACTLY to its cards. Only a column
            # with a "more" card may merely exceed what is visible.
            "column_total": str(total),
            "fully_drawn": True,
        })
    return {"columns": columns}


# --- contacts, the daily slot ----------------------------------------------------------

@app.post("/v1/contacts", status_code=201)
def log_contact(body: dict = Body(...)):
    audit.describe(act="CONTACT_LOGGED")
    # Order matters: schema first, then existence, then business rules. A request that
    # cannot be parsed has no resource to be missing, and telling a caller "no such
    # customer" when they simply omitted the disposition sends them hunting for the
    # wrong bug.
    field_errors = []
    for required in ("customer_uid", "disposition"):
        if not body.get(required):
            field_errors.append({
                "pointer": "/" + required,
                "code": "required",
                "message": "%s is required" % required,
                "message_th": "ต้องระบุข้อมูลในฟิลด์นี้",
            })
    reported = None
    if body.get("at"):
        try:
            reported = parse_timestamp(body["at"])
        except (TypeError, ValueError):
            field_errors.append({
                "pointer": "/at", "code": "not_a_timestamp",
                "message": "at must be an ISO-8601 timestamp with an offset",
                "message_th": "รูปแบบวันเวลาไม่ถูกต้อง",
            })
    if field_errors:
        raise errors.validation_failed(field_errors)

    # Round-4 J4-01 — ONE CLOCK, and it is the business clock.
    # The drawer stamped `at` from the laptop (2026-09-03) while /v1/today looks the
    # lock up on the business day (2026-10-23): the customer was refused a second
    # contact AND still offered as รายต่อไป. The caller's `at` no longer decides the
    # day a slot is spent — clock.business_now() does, and the client's own value is
    # kept beside it as `at_reported` so nothing an officer typed is thrown away.
    moment = clock.business_now().replace(tzinfo=clock.BANGKOK)
    lock_day = settings.business_date

    customer = BY_CUSTOMER.get(body.get("customer_uid"))
    if customer is None:
        raise errors.not_found("customer")

    try:
        attempt = contact_log.log_contact(
            customer_key=customer.identity_key,
            contract_uids=[k.uid for k in customer.contracts],
            channel=body.get("channel", "PHONE"),
            direction=body.get("direction", "OUTBOUND"),
            disposition=body["disposition"],
            at=moment,
            officer=body.get("officer", "noon"),
            role=body.get("role", "OFFICER"),
            override=body.get("override", False),
            override_reason=body.get("override_reason"),
            not_counted=bool(body.get("not_counted")),      # J4-02
        )
    except ContactLocked as exc:
        # Report the EXISTING lock, not the attempt being refused. Echoing the refused
        # attempt's own timestamp told the officer the customer was contacted at a time
        # they were not — and that sentence ends up in front of a customer.
        held = contact_log.locks_for(customer.identity_key, lock_day, level="PERSON")
        lock = held[0] if held else None
        # Judge J-04: name the way through. Inbound never counts; an OPEN promise on
        # the case can be renegotiated without a second counting contact.
        from . import cases as cases_domain
        case = cases_domain.for_current().cases.get(customer.uid)
        alternatives = [{"code": "INBOUND_NOT_COUNTED",
                         "label_th": errors.CONTACT_LOCKED_ALTERNATIVES["INBOUND_NOT_COUNTED"]},
                        # Round-4 J4-02: the only way through used to be writing "the
                        # customer called me" about a call the officer made. A second
                        # contact today may be RECORDED as long as it is not counted —
                        # the record stays true and the daily slot stays spent.
                        {"code": "SECOND_CONTACT_NOT_COUNTED",
                         "label_th": errors.CONTACT_LOCKED_ALTERNATIVES["SECOND_CONTACT_NOT_COUNTED"],
                         "field": "not_counted",
                         "how_th": "ส่งคำขอเดิมอีกครั้งพร้อม not_counted: true — บันทึกไว้เป็นประวัติ ไม่นับเป็นการทวงถามของวันนี้"}]
        if case and case.get("open_ptp_uid"):
            alternatives.append({"code": "RENEGOTIATE_OPEN_PTP",
                                 "label_th": errors.CONTACT_LOCKED_ALTERNATIVES["RENEGOTIATE_OPEN_PTP"]})
        raise errors.contact_locked(
            alternatives=alternatives,
            locked_by=lock.officer if lock else None,
            locked_at=str(lock.taken_at) if lock else None,
            result=lock.result if lock else None,
            lock_id=exc.blocked_by_lock_id,
            # §5.9 has the client offer the override control ONLY when this is true.
            # Hardcoding false leaves a Manager unable to reach a permission they hold.
            override_allowed=body.get("role", "OFFICER") in OVERRIDE_ROLES,
        )
    except ContactOnHold:
        raise errors.contact_on_hold()
    except OverrideReasonRequired:
        raise errors.validation_failed(
            [{"pointer": "/override_reason", "code": "override_reason_required",
              "message": "An override requires a logged reason.",
              "message_th": "การใช้สิทธิ์ข้ามข้อจำกัดต้องระบุเหตุผล"}]
        )
    except OverrideForbidden:
        raise errors.Problem(
            code="forbidden", status=403, title="Override not permitted for this role",
            detail="Only Manager and Owner may override the daily contact limit.",
            message_th="เฉพาะผู้จัดการหรือเจ้าของระบบเท่านั้นที่ข้ามข้อจำกัดได้",
            error_id="DEBT-IAM-0403",
        )
    except ValueError as exc:
        raise errors.validation_failed(
            [{"pointer": "/disposition", "code": "unknown_contact_result",
              "message": str(exc), "message_th": "ผลการติดต่อไม่อยู่ในรายการที่กำหนด"}]
        )

    _retractable()[("production" if shared_state_enabled() else session_domain.current(), attempt.contact_id)] = {
        # The 90-second retraction window is measured against the client's own moment
        # when it sent one (a real elapsed wall time); the LOCK is on the business day.
        "at": reported or moment,
        "lock_day": lock_day,
        "amount_stated": bool(body.get("amount_stated")),
        "customer_key": customer.identity_key,
    }

    # Flow part 3 — a flag-raising result routes to Manager Review: REFUSED_PAY is
    # the refuse-to-pay branch, LINE_BLOCKED the unreachable escalation.
    review_uid = None
    if attempt.raises_flag:
        from . import journey
        reason = "REFUSE_TO_PAY" if body["disposition"] == "REFUSED_PAY" else "UNREACHABLE"
        review = journey.make_review(
            journey.for_current(), customer.uid, reason,
            source_ref="contact:%s" % attempt.contact_id,
            opened_by=body.get("officer", "noon"))
        review_uid = review["uid"]

    return {
        "contact_id": attempt.contact_id,
        "counted": attempt.counted,
        "lock_consumed": attempt.lock_consumed,
        "override": attempt.override,
        "raises_flag": attempt.raises_flag,
        "manager_review_uid": review_uid,
        # Round-4 J4-01: the row says which clock stamped it and on which business day
        # the slot was spent, so a screen can never disagree with /v1/today again.
        "at": moment.isoformat(timespec="seconds"),
        "at_reported": reported.isoformat(timespec="seconds") if reported else None,
        "stamped_from": "BUSINESS_CLOCK",
        "business_date": str(lock_day),
        "lock_date": str(lock_day),
        "not_counted_declared": bool(body.get("not_counted")),
        "stamp_note_th": ("บันทึกด้วยวันทำการ %s (นาฬิกาธุรกิจ) ไม่ใช่เวลาเครื่อง" % lock_day),
    }


_RETRACTABLE = {}
_IDEMPOTENCY = {}
_retractable_store = session_domain.Store(dict, key="contacts.retractable")


def _retractable():
    from .production_unit import CURRENT as production_current
    return _retractable_store.for_current() if production_current.get() is not None else _RETRACTABLE


@app.post("/v1/contacts/{contact_id}:retract")
def retract_contact(contact_id: int, body: dict = Body(default={})):
    """REQ-COL-055 — a 90-second retraction window on the daily slot.

    The slot is spent at amount-stated OR 90 seconds, whichever comes first.
    Retraction is impossible once the amount is stated, so the loophole closes itself:
    there is no way to hold a slot open by delaying.
    """
    audit.describe(act="CONTACT_RETRACTED", subject=("contact", str(contact_id)))
    record = _retractable().get(("production" if shared_state_enabled() else session_domain.current(), contact_id))
    if record is None:
        raise errors.not_found("contact")

    if record["amount_stated"]:
        raise errors.retraction_window_closed(
            "The amount was stated, which spends the slot immediately regardless of elapsed time."
        )

    moment = parse_timestamp(body["at"])
    elapsed = moment - record["at"]
    # A SIGNED comparison here was a bypass: a retraction stamped EARLIER than the
    # contact satisfied "< 90 seconds" and handed the slot back every time. The window
    # opens at the contact and closes 90 seconds later; nothing outside it qualifies.
    if elapsed < timedelta(0):
        raise errors.retraction_window_closed(
            "The retraction is dated before the contact it retracts. The window opens "
            "when the contact is logged."
        )
    if elapsed > timedelta(seconds=settings.retraction_window_seconds):
        raise errors.retraction_window_closed(
            "More than %d seconds have elapsed since the contact was logged."
            % settings.retraction_window_seconds
        )

    # J4-01: the lock lives on the business day, so that is the day handed back.
    contact_log.retract(record["customer_key"], record.get("lock_day") or bangkok_day(record["at"]))
    return {"slot_restored": True, "contact_id": contact_id}


@app.get("/v1/config/approval-paths")
def list_approval_paths():
    from . import approval_paths
    return {"items": approval_paths.list_all()}


# --- approval paths ------------------------------------------------------------------

@app.post("/v1/config/approval-paths", status_code=201)
def create_approval_path(body: dict = Body(...)):
    """REQ-IAM-015 — the system refuses to seed an approval path whose role is vacant.

    Taken literally, the vacant Debt Manager post means nothing can be flagged
    non-performing — yet ten contracts are. This guard is what stops a new path being
    written into the same trap.
    """
    audit.describe(act="APPROVAL_PATH_CREATED")
    role = body.get("role")
    # An exact byte match was a bypass: "debt_manager", " DEBT_MANAGER " and a list
    # containing it all seeded a route to a post nobody holds. Normalise before
    # comparing, and check every role in a list — the guard must fail closed.
    candidates = role if isinstance(role, (list, tuple)) else [role]
    vacant = {_normalise_role(v) for v in settings.vacant_roles}
    for candidate in candidates:
        if _normalise_role(candidate) in vacant:
            raise errors.authority_gap_blocks_approval(candidate, body.get("action"))
    from . import approval_paths
    path = approval_paths.create(body.get("action"), [_normalise_role(r) for r in candidates])
    return {"created": True, "action": path["action"], "role": role, "path": path}


def _normalise_role(value):
    if not isinstance(value, str):
        return value
    return value.strip().upper().replace("-", "_").replace(" ", "_")


@app.get("/v1/contracts/{contract_uid}/instalments")
def contract_instalments(contract_uid: str):
    """The schedule rows. The interface cannot derive these from contract totals, and
    deriving them there would be arithmetic in the interface."""
    found = BY_CONTRACT.get(contract_uid)
    if found is None:
        raise errors.not_found("contract")
    _customer, contract = found
    # Ruling 49: session-scoped, same as _contract_view — a session that has not
    # restructured this contract must not see another session's addendum here.
    instalments = _contract_field_of(contract, "instalments")

    rows = []
    for n, line in enumerate(instalments, start=1):
        paid = line.paid_principal + line.paid_interest + line.paid_fee
        if line.outstanding_amount <= Decimal("0.00"):
            status = "PAID"
        elif paid > Decimal("0.00"):
            status = "PARTIALLY_PAID"
        elif line.due_date < settings.business_date:
            status = "OVERDUE"
        else:
            status = "DUE"
        rows.append({
            "no": n,
            "due_date": str(line.due_date),
            "category": line.category,
            "amount": str(line.total_amount),
            "principal": str(line.principal_amount),
            "interest": str(line.interest_amount),
            "paid": str(paid),
            "outstanding": str(line.outstanding_amount),
            "status": status,
        })

    regular = [line for line in instalments if line.category == "REGULAR"]
    return {
        "contract_uid": contract_uid,
        "instalments": rows,
        "total_amount": str(sum((line.total_amount for line in instalments), Decimal("0.00"))),
        "installment_amount": str(regular[0].total_amount) if regular else None,
        "final_installment_amount": str(regular[-1].total_amount) if regular else None,
        # REQ-MNY-003 — the final line is the balancing figure and may differ.
        # Accounting must be told before the first customer statement is issued.
        "final_installment_differs": bool(regular) and regular[0].total_amount != regular[-1].total_amount,
        "basis_business_date": str(settings.business_date),
    }


# --- the 2026-08-30 rebuild routers ----------------------------------------------
# Registered BEFORE the static catch-all so every /v1 journey route wins.

from .routers.journey import router as journey_router      # noqa: E402
from .routers.integrations import router as integrations_router  # noqa: E402

app.include_router(journey_router)
app.include_router(integrations_router)
# 2026-09-02 realignment routers (API Surface v2.3)
from .routers.today import router as today_router  # noqa: E402
from .routers.settings import router as settings_router  # noqa: E402
from .routers.pipeline import router as pipeline_router  # noqa: E402
from .routers.payments import router as payments_router  # noqa: E402
from .routers.migration import router as migration_router  # noqa: E402
from .routers.reports import router as reports_router  # noqa: E402
# Round-5 ruling 71: the officer's own upload, raw-body (see routers/imports.py's
# own note on why — no python-multipart, no UploadFile).
from .routers.imports import router as imports_router  # noqa: E402
from .routers.debt_imports import router as debt_imports_router  # noqa: E402
from .routers.pipelines import router as pipelines_router  # noqa: E402
from .routers.peak_pipeline import router as peak_pipeline_router  # noqa: E402
# Task 22: evidence files on a contact or a note — guard, scan, store (F7/F8).
from .routers.attachments import router as attachments_router  # noqa: E402
from .routers.audit import router as audit_router  # noqa: E402
from .routers.login import router as login_router  # noqa: E402
# Feedback Round 1 / WP6 (F16): the calendar — one dated list, a moved next action, personal notices.
from .routers.calendar import router as calendar_router  # noqa: E402
# Delta-100 D2b / SH1 / SH2 / SH4: the rail's one summary (workload, badges, KPI strip).
from .routers.shell import router as shell_router  # noqa: E402
from .routers.customers import router as customers_router  # noqa: E402
from .routers.message_templates import router as message_templates_router  # noqa: E402
from .routers.operation_runs import router as operation_runs_router  # noqa: E402
# 2026-09-20 sync audit: the import epoch a screen reads + the session's own catch-up.
from .routers.data_state import router as data_state_router  # noqa: E402
from .routers.payment_claims import router as payment_claims_router  # noqa: E402
app.include_router(data_state_router)
app.include_router(payment_claims_router)
from .routers.service_deferrals import router as service_deferrals_router, queue_router as service_deferral_queue_router
app.include_router(service_deferrals_router)
app.include_router(service_deferral_queue_router)
from .routers.invoice_reviews import router as invoice_reviews_router
app.include_router(invoice_reviews_router)
app.include_router(today_router)
app.include_router(settings_router)
app.include_router(pipeline_router)
app.include_router(payments_router)
app.include_router(migration_router)
app.include_router(reports_router)
app.include_router(imports_router)
app.include_router(debt_imports_router)
app.include_router(pipelines_router)
app.include_router(peak_pipeline_router)
app.include_router(attachments_router)
app.include_router(audit_router)
from .routers.terminated import router as terminated_router
app.include_router(terminated_router)
app.include_router(login_router)
app.include_router(calendar_router)
app.include_router(shell_router)
app.include_router(customers_router)
app.include_router(message_templates_router)
app.include_router(operation_runs_router)


# --- serving the built interface ------------------------------------------------
# On Cloud Run the API and the interface are ONE service and one origin. That is not
# the production shape — §5.1 and §5.2 keep debt-api and debt-web apart, and the two
# Dockerfiles for that still stand — but a split needs the web tier to mint an
# identity token for every call to a private API service, which nginx cannot do
# natively. One origin removes that problem, and with it CORS and a second IAP
# session, which is the right trade for a UAT round.
#
# Mounted LAST and only when a build exists: the /v1 routes above must win, and a
# developer running uvicorn without having built the frontend must not see a crash.
_STATIC = Path(__file__).resolve().parent.parent / "static"

if _STATIC.is_dir():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=_STATIC / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """SPA deep links must return 200, not 404 — the reason nginx was chosen over
        GCS in §5.2, and the same rule applies here.

        An unknown /v1 path must still 404 as a problem document rather than silently
        returning the HTML shell, which would make a typo in an endpoint look like a
        working page.
        """
        if full_path.startswith("v1/") or full_path.startswith("api/"):
            raise errors.not_found("route")
        candidate = (_STATIC / full_path).resolve()
        # resolve() then check the prefix: without it, ../ in the path escapes the
        # static directory and serves arbitrary files.
        if full_path and candidate.is_file() and str(candidate).startswith(str(_STATIC)):
            return FileResponse(candidate)
        return FileResponse(_STATIC / "index.html")


@app.middleware("http")
async def termination_request_cache(request: Request, call_next):
    # Mutable ContextVar contents follow the request into sync workers. Every
    # request refreshes the shared facts, including POSTs and import healing.
    from . import termination_archive
    token = termination_archive._CACHE.set({})
    try:
        return await call_next(request)
    finally:
        termination_archive._CACHE.reset(token)
