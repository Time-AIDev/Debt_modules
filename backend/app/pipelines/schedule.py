"""The 2-hour refetch (Arina, 2026-09-25; was 15 minutes): a daemon thread, ON from boot (2026-09-21 ruling).

The Import data screen defaults to the Odoo tab, and that tab says the system
fetches by itself — so the schedule is not a box a Manager ticks any more. It is
on when the process starts (`ensure_auto()` from the lifespan), and the durable
copy of the same cadence is the Cloud Scheduler job `crm-lead-refresh`, which
triggers the `debt-crm-lead-sync` Cloud Run job every 2 hours.

Three things it deliberately still is NOT, all of which the screen states:

  - It is not durable. It lives in this process and dies with it. The durable
    schedule is the Cloud Scheduler job in scripts/deploy_gcp.sh.
  - It is not safe to assume on Cloud Run, where the service scales to zero and to
    N instances: the timer would fire zero times or N times. `in_process_only` is
    how a caller learns that without having to know it already.
  - It does not fire on enable. Turning it on must not start a 34k-row fetch in the
    same second; boot-time freshness is `service.refresh_if_stale`'s six-hour window,
    and the first timer run is one full interval away.

A tick also refuses to spend itself when there is nothing to fetch: no database (a
test harness) or no Odoo credentials means the loop skips WITHOUT stamping
`last_run_at`, so a deployment that gains credentials later does not wait out an
interval that was consumed by a guaranteed failure.

`tick()` is the whole decision and is pure, so the interval logic is tested without
waiting two hours for it.
"""
import sys
import threading
import time

INTERVAL_DEFAULT = 120
POLL_SECONDS = 5

_LOCK = threading.Lock()
# ON by default (2026-09-21). `disable()` still exists for ops and tests; the
# lifespan calls `ensure_auto()` so every boot turns it back on.
_STATE = {"enabled": True, "interval_minutes": INTERVAL_DEFAULT,
          "last_run_at": None, "last_run_uid": None}
_THREAD = None
_THREAD_LOCK = threading.Lock()
_STOP = threading.Event()


def odoo_ready():
    """Whether the crm.lead pull could run at all. Read-only, never raises."""
    from ..integrations import odoo as odoo_client
    try:
        odoo_client._config()
        return True
    except Exception:                                  # noqa: BLE001 — "not ready" is the answer
        return False


def ensure_auto(interval_minutes=INTERVAL_DEFAULT):
    """The boot call: on, at the default cadence, idempotent.

    Enabling must not reset a clock that is already running — a second call (or a
    call after an ops `enable`) keeps the current `last_run_at`, or a 2-hour
    cadence becomes "2 hours from every restart".
    """
    with _LOCK:
        _STATE["enabled"] = True
        _STATE["interval_minutes"] = max(1, int(interval_minutes))
        # Start the clock ONCE: a second call (or a call after an ops `enable`) keeps
        # the stamp, or a 2-hour cadence becomes "2 hours from every restart".
        # It is still not a run — the first fetch is one full interval away.
        if _STATE["last_run_at"] is None:
            _STATE["last_run_at"] = time.time()
    _ensure_thread()
    return state()


def reset():
    """Restore the module defaults. Thread lifecycle is handled by ``shutdown``."""
    with _LOCK:
        _STATE.update(enabled=True, interval_minutes=INTERVAL_DEFAULT,
                      last_run_at=None, last_run_uid=None)
    return state()


def enable(interval_minutes=INTERVAL_DEFAULT):
    with _LOCK:
        _STATE.update(enabled=True,
                      interval_minutes=max(1, int(interval_minutes)),
                      last_run_at=time.time())      # the clock starts now, not a run
    _ensure_thread()
    return state()


def disable():
    with _LOCK:
        _STATE.update(enabled=False, last_run_at=None)
    return state()


def tick(now=None):
    """Should a run start at `now`? Pure — no threads, no pipeline, no clock beyond
    the one passed in, which is what makes the interval testable in milliseconds."""
    now = time.time() if now is None else now
    with _LOCK:
        if not _STATE["enabled"]:
            return False
        last = _STATE["last_run_at"]
        if last is None:
            return True
        return (now - last) >= _STATE["interval_minutes"] * 60


def state():
    ready = odoo_ready()
    with _LOCK:
        now = time.time()
        last = _STATE["last_run_at"]
        nxt = None
        if _STATE["enabled"] and last is not None:
            nxt = last + _STATE["interval_minutes"] * 60
        return {"enabled": _STATE["enabled"],
                "interval_minutes": _STATE["interval_minutes"],
                "last_run_at": last, "next_run_at": nxt,
                "last_run_uid": _STATE["last_run_uid"], "now": now,
                "in_process_only": True,
                # 2026-09-21: "on" is the process default; these two tell the screen
                # whether it is actually fetching, and why not when it is not.
                "auto": True,
                "odoo_configured": ready,
                "paused_reason": None if ready else "integration_not_configured"}


def _loop():
    from .. import db
    from . import service
    while not _STOP.wait(POLL_SECONDS):
        # A skipped tick does NOT stamp: a guaranteed failure (no database, no Odoo
        # credentials) must not consume the interval, or gaining credentials later
        # would still wait out the window that failure already spent.
        if not db.configured() or not odoo_ready():
            continue
        if not tick():
            continue
        # Stamp BEFORE the run, not after: a 90-second run stamped on completion
        # would shorten every subsequent interval by its own duration.
        with _LOCK:
            _STATE["last_run_at"] = time.time()
        view = service.run_odoo(mode="NEW_ONLY")
        with _LOCK:
            _STATE["last_run_uid"] = view["uid"] if view else None
        if view and view.get("state") == "failed":
            # e.g. crm_lead_run_in_progress when the Cloud Run job holds the landing
            # lock; the durable run row already says FAILED with the same code.
            print("crm.lead timer run failed: %s" % (view.get("problem") or {}).get("code"),
                  file=sys.stderr)


def _ensure_thread():
    global _THREAD
    with _THREAD_LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _STOP.clear()
            _THREAD = threading.Thread(target=_loop, name="crm-lead-schedule", daemon=True)
            _THREAD.start()


def shutdown():
    """Stop the in-process timer at app/test shutdown and allow a clean restart.

    The stop event interrupts the polling wait immediately. If an Odoo pull is
    already in progress it remains non-cancellable; the daemon exits after that
    pull returns instead of spawning a second scheduler beside it.
    """
    global _THREAD
    with _THREAD_LOCK:
        thread = _THREAD
        if thread is None:
            return
        _STOP.set()
    if thread is not threading.current_thread():
        thread.join(timeout=POLL_SECONDS + 1)
    with _THREAD_LOCK:
        if _THREAD is thread and not thread.is_alive():
            _THREAD = None
