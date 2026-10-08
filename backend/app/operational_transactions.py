"""Audited queue submissions that require no mutable portfolio graph.

This classification is only for the HTTP enqueue branch. The worker invokes the
same PEAK route to parse/match/stage a file and must retain the global barrier.
The caller uses READ COMMITTED for live quota checks and serializes authenticated
idempotency keys before checking the saved response.
"""
import re

PEAK_STARTS = frozenset({"/v1/pipelines/peak-report:start", "/v1/pipelines/peak-receipt:start"})


def is_peak_apply_enqueue(scope, *, worker_run=False):
    if (scope.get("method") != "POST" or scope.get("volt_worker") or worker_run
            or scope.get("query_string", b"") != b"" or not re.fullmatch(
                r"/v1/pipelines/peak-(report|receipt)/landing-runs/[0-9]+:apply", scope.get("path", ""))):
        return False
    values = [value for name, value in scope.get("headers", []) if name.lower() == b"content-type"]
    return len(values) == 1 and values[0].split(b";", 1)[0].strip().lower() == b"application/json"


def is_peak_enqueue(scope, *, worker_run=False):
    if (scope.get("type", "http") != "http" or scope.get("method") != "POST"
            or scope.get("path") not in PEAK_STARTS or scope.get("volt_worker") or worker_run
            or scope.get("query_string", b"") != b""):
        return False
    content_types = [value for name, value in scope.get("headers", []) if name.lower() == b"content-type"]
    # No API door, including variants and ambiguous duplicate selector headers.
    # A missing header still selects the raw file branch in both audited routes.
    return len(content_types) <= 1 and not any(b"json" in value.lower() for value in content_types)
