"""Shared operation-run state for uploads, parsers, scanners and imports.

Process-wide and NOT per-session (app/session.py), deliberately: the work happens on
a background thread, which has no request and therefore no session contextvar, and
the point of the feature is that an officer can navigate away and come back to a run
that is still going.

In memory, so it dies with the process. That is honest for a prototype and is stated
on the screen; the durable record of what a run did is the import_run row the writer
already creates.
"""
import threading
import time
import uuid
from collections import OrderedDict

KEEP = 20                    # a laptop session's worth; the oldest fall off

_LOCK = threading.RLock()
_RUNS = OrderedDict()

ACTIVE_STATES = frozenset({
    "queued", "uploading", "parsing", "scanning", "applying", "cancel_requested"
})
TERMINAL_STATES = frozenset({"cancelled", "done", "failed"})
PHASE_STATE = {
    "queued": "queued",
    "uploading": "uploading",
    "reading": "parsing",
    "parsing": "parsing",
    "matching": "parsing",
    "scanning": "scanning",
    "writing": "applying",
    "applying": "applying",
}


class RunCancelled(Exception):
    pass


class RunNotCancellable(Exception):
    code = "run_not_cancellable"

    def __init__(self, uid):
        super().__init__("operation run %s has committed or already ended" % uid)
        self.uid = uid


def reset():
    """Test seam. Never called from a request."""
    with _LOCK:
        _RUNS.clear()


def start(kind, **fields):
    from ..auth import ACTOR, actor_key
    actor = ACTOR.get()
    if actor:
        fields["initiated_by"] = actor_key(actor)
        fields["initiated_role"] = actor["role"]
    uid = "run-" + uuid.uuid4().hex[:12]
    with _LOCK:
        _RUNS[uid] = {"uid": uid, "kind": kind, "state": "queued",
                      "read": 0, "total": None, "landed": 0, "rejected": 0,
                      "overwrote": 0, "started_at": time.time(),
                      "finished_at": None, "problem": None,
                      "phase": "queued", "processed": 0, "phase_total": None,
                      "uploaded_bytes": 0, "total_bytes": None,
                      "committed": False, "cancel_requested_at": None,
                      "_cancel": threading.Event(), **fields}
        while len(_RUNS) > KEEP:
            _RUNS.popitem(last=False)
    return uid


def progress(uid, **fields):
    with _LOCK:
        run = _RUNS.get(uid)
        if run and run["state"] in ACTIVE_STATES and run["state"] != "cancel_requested":
            phase = fields.get("phase")
            if phase in PHASE_STATE:
                run["state"] = PHASE_STATE[phase]
            run.update(fields)


def cancel(uid):
    with _LOCK:
        run = _RUNS.get(uid)
        if run is None:
            return None
        if run.get("committed") or run["state"] in TERMINAL_STATES:
            raise RunNotCancellable(uid)
        run["_cancel"].set()
        run["state"] = "cancel_requested"
        run["phase"] = "cancel_requested"
        run["cancel_requested_at"] = time.time()
        return _view(run)


def checkpoint(uid, *, raise_cancelled=True):
    """Cooperative cancellation gate. Raise inside a DB transaction to roll it back."""
    with _LOCK:
        run = _RUNS.get(uid)
        requested = bool(run and run["_cancel"].is_set())
        if requested:
            run["state"] = "cancelled"
            run["phase"] = "cancelled"
            run["finished_at"] = time.time()
        view = _view(run) if run else None
    if requested and raise_cancelled:
        raise RunCancelled(uid)
    return view


def mark_committed(uid):
    with _LOCK:
        run = _RUNS.get(uid)
        if run:
            if run["_cancel"].is_set():
                raise RunCancelled(uid)
            run["committed"] = True
        return _view(run) if run else None


def commit(uid, apply):
    """Atomically cross the cancellation boundary for a short in-memory write."""
    with _LOCK:
        run = _RUNS.get(uid)
        if run is None or run["_cancel"].is_set():
            if run:
                run["state"] = "cancelled"
                run["phase"] = "cancelled"
                run["finished_at"] = time.time()
            raise RunCancelled(uid)
        result = apply()
        run["committed"] = True
        return result


def finish(uid, result):
    with _LOCK:
        run = _RUNS.get(uid)
        if run:
            if run["_cancel"].is_set() and not run.get("committed"):
                run["state"] = "cancelled"
                run["phase"] = "cancelled"
                run["finished_at"] = time.time()
                return
            run.update(result)
            run["committed"] = True
            run["state"] = "done"
            run["phase"] = "done"
            run["finished_at"] = time.time()


def fail(uid, problem):
    with _LOCK:
        run = _RUNS.get(uid)
        if run:
            if isinstance(problem, RunCancelled) or (
                run["_cancel"].is_set() and not run.get("committed")
            ):
                run["state"] = "cancelled"
                run["phase"] = "cancelled"
                run["finished_at"] = time.time()
                return
            run["state"] = "failed"
            run["phase"] = "failed"
            run["problem"] = problem
            run["finished_at"] = time.time()


def _view(run):
    """Elapsed counts up while running and freezes when it ends — a clock that kept
    running after the run finished would make every old run look eternal."""
    # Two decimals, not one: a run that took 40 ms reporting "0.0" is a clock
    # saying nothing happened. The screen formats this to m:ss regardless.
    end = run["finished_at"] or time.time()
    return {k: v for k, v in dict(
        run, elapsed_seconds=round(end - run["started_at"], 2)
    ).items() if not k.startswith("_")}


def get(uid):
    with _LOCK:
        run = _RUNS.get(uid)
        return _view(run) if run else None


def all():
    with _LOCK:
        return [_view(r) for r in _RUNS.values()]


def latest(kind=None):
    """The newest run, of any kind or of one. `kind` is the value start() was given."""
    found = [r for r in all() if kind is None or r.get("kind") == kind]
    return found[-1] if found else None


from .. import durable_runs as _durable
import sys as _sys
for _name in ("start", "progress", "cancel", "checkpoint", "mark_committed", "commit", "finish", "fail", "get", "all", "latest"):
    globals()[_name] = _durable.adapt(_name, globals()[_name], _sys.modules[__name__])
