"""Request-scoped phase timings used by staging latency logs."""
import time
from contextlib import contextmanager
from contextvars import ContextVar


_PHASES = ContextVar("request_perf_phases", default=None)


def begin():
    values = {}
    return _PHASES.set(values), values


def end(token):
    _PHASES.reset(token)


@contextmanager
def phase(name):
    values = _PHASES.get()
    if values is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        values[name] = values.get(name, 0.0) + (time.perf_counter() - started) * 1000.0


def rounded(values):
    return {name: round(ms, 1) for name, ms in sorted(values.items())}
