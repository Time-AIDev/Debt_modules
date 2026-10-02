"""Small mutable cache shared by every sync worker used by one read request.

Context variables themselves are copied when FastAPI moves a route to its thread
pool.  The dict stored here is intentionally mutable: the copied contexts still
point at the same dict, so domain helpers can publish an expensive read once and
all other helpers in that request see it.
"""
from contextvars import ContextVar


_READS = ContextVar("request_reads", default=None)


def begin_read():
    return _READS.set({})


def end_read(token):
    _READS.reset(token)


def reads():
    return _READS.get()
