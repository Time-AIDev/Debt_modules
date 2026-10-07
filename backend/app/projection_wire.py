"""Bounded immutable bodies for unpaged Today, after normal request validation.

Only JSON bytes are cached. Authentication, authorization, audit, transaction and
fresh response headers remain the caller's responsibility on every request.
"""
from collections import OrderedDict
import json
import threading

from starlette.responses import Response

from . import perf


class BodyCache:
    def __init__(self, max_bytes=32 * 1024 * 1024, max_entries=16):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self._lock = threading.RLock()
        self._entries = OrderedDict()
        self._building = {}
        self.bytes = 0

    def clear(self):
        with self._lock:
            self._entries.clear()
            self.bytes = 0

    def body(self, key, build):
        while True:
            with self._lock:
                saved = self._entries.pop(key, None)
                if saved is not None:
                    self._entries[key] = saved
                    return saved
                flight = self._building.get(key)
                if flight is None:
                    # Bound coordination state as well as cached bytes. Excess
                    # unrelated cold keys build independently without caching.
                    if len(self._building) >= max(1, self.max_entries):
                        break
                    flight = threading.Event()
                    self._building[key] = flight
                    break
            flight.wait()
        if flight is None:
            return self._build_uncached(build)
        try:
            body = self._build_uncached(build)
            with self._lock:
                if 0 < len(body) <= self.max_bytes and self.max_entries > 0:
                    self._entries[key] = body
                    self.bytes += len(body)
                    while self.bytes > self.max_bytes or len(self._entries) > self.max_entries:
                        _, removed = self._entries.popitem(last=False)
                        self.bytes -= len(removed)
            return body
        finally:
            with self._lock:
                self._building.pop(key, None)
                flight.set()

    @staticmethod
    def _build_uncached(build):
        response = build()
        if response.status_code != 200 or not isinstance(response.body, bytes):
            raise ValueError("Only a successful JSON business body can enter the wire cache")
        return response.body


_CACHE = BodyCache()


def today_response(conn, pointer, filters, sort, build):
    from . import read_projection
    unit = read_projection._unit()
    if unit and unit.get("mutation"):
        # An uncommitted scoped ordering version can be reused after rollback.
        # Internal mutation callers must never populate shared immutable bytes.
        return build()
    key = (conn.engine, pointer["generation"], pointer["ordering_version"], pointer["source_epoch"],
           str(pointer["business_date"]), pointer["metadata"]["code_fingerprint"],
           json.dumps(filters, sort_keys=True, ensure_ascii=False, separators=(",", ":")), sort)
    with perf.phase("today_wire"):
        body = _CACHE.body(key, build)
    # Never reuse headers/cookies/status or a mutable Response instance from a
    # different request. The production unit stamps its current version afresh.
    return Response(body, media_type="application/json")
