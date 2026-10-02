"""Database adapter for operation progress and cooperative cancellation."""
import json
import threading
from contextvars import ContextVar
from functools import wraps

from sqlalchemy import text
from . import db
from .production_unit import enabled, CURRENT

WORKER_RUN = ContextVar("worker_run", default=None)


def adapt(name, original, module):
    @wraps(original)
    def wrapped(*args, **kwargs):
        if not enabled(): return original(*args, **kwargs)
        # Progress and cancellation are operational state. Publish them while the
        # business transaction is still running; finish remains commit-bound.
        if WORKER_RUN.get() and CURRENT.get() is not None and name in ("progress", "checkpoint"):
            token = CURRENT.set(None)
            try: return wrapped(*args, **kwargs)
            finally: CURRENT.reset(token)
        if name == "start" and WORKER_RUN.get(): return WORKER_RUN.get()
        if name in ("get", "all", "latest"):
            with db.connect() as conn:
                if name == "get":
                    row = conn.execute(text("select payload from app.operation_run where uid=:u"), {"u": args[0]}).scalar()
                    return module._view(row) if row else None
                found = conn.execute(text("select payload from app.operation_run order by created_at,uid")).scalars().all()
                views = [module._view(row) for row in found]
                if name == "all": return views
                kind = args[0] if args else kwargs.get("kind")
                selected = [row for row in views if kind is None or row["kind"] == kind]
                return selected[-1] if selected else None
        with module._LOCK, db.connect() as conn, conn.begin():
            uid = args[0] if name != "start" else None
            if uid:
                row = conn.execute(text("select payload from app.operation_run where uid=:u for update"), {"u": uid}).scalar()
                if row:
                    row = dict(row, _cancel=threading.Event())
                    if row.get("cancel_requested_at"): row["_cancel"].set()
                    module._RUNS[uid] = row
            # Cancellation must commit before the cooperative exception is raised.
            cancelled = None
            try:
                result = original(*args, **kwargs)
            except module.RunCancelled as exc:
                cancelled, result = exc, None
            if name == "start": uid = result
            row = module._RUNS.get(uid)
            if row:
                payload = {k: v for k, v in row.items() if not k.startswith("_")}
                conn.execute(text("insert into app.operation_run(uid,payload) values(:u,cast(:p as jsonb)) "
                                  "on conflict(uid) do update set payload=excluded.payload,updated_at=now()"),
                             {"u": uid, "p": json.dumps(payload, default=str)})
            if cancelled:
                # Outside a surrounding production unit this boundary commits here.
                # Within a job, the worker records cancellation after rolling it back.
                result = cancelled
        if isinstance(result, module.RunCancelled): raise result
        return result
    return wrapped
