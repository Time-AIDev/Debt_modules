"""Audited queue submissions that require no mutable portfolio graph.

This classification is only for the HTTP enqueue branch. The worker invokes the
same PEAK route to parse/match/stage a file and must retain the global barrier.
The caller uses READ COMMITTED for live quota checks and serializes authenticated
idempotency keys before checking the saved response.
"""
import re
from urllib.parse import parse_qs

PEAK_STARTS = frozenset({"/v1/pipelines/peak-report:start", "/v1/pipelines/peak-receipt:start"})

# An officer's re-check re-binds a staged run's review fence to the version that
# stands now (preview_review.restamp) — landing metadata only, never the book.
LANDING_RECHECK = re.compile(r"^/v1/pipelines/peak-(report|receipt)/landing-runs/[0-9]+:recheck$")

UPLOAD_ID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def is_upload_transport(scope):
    if scope.get("type", "http") != "http" or scope.get("volt_worker"):
        return False
    path, method = scope.get("path", ""), scope.get("method")
    query = scope.get("query_string", b"")
    if method == "DELETE":
        return query == b"" and bool(re.fullmatch(r"/v1/imports/parts/" + UPLOAD_ID, path))
    if method != "POST" or not re.fullmatch(r"/v1/imports/parts/" + UPLOAD_ID + r"/[0-9]+", path):
        return False
    return bool(re.fullmatch(rb"of=[0-9]+", query))


def is_master_preview_enqueue(scope, *, worker_run=False):
    if (scope.get("type", "http") != "http" or scope.get("method") != "POST"
            or scope.get("path") != "/v1/imports:start" or scope.get("volt_worker") or worker_run):
        return False
    try:
        query = parse_qs(scope.get("query_string", b"").decode("ascii"), keep_blank_values=True,
                         strict_parsing=True)
    except (ValueError, UnicodeDecodeError):
        return False
    return (set(query) <= {"profile", "install"} and all(len(values) == 1 for values in query.values())
            and query.get("profile", [None])[0] in (None, "debt_status", "contract_supplement")
            and query.get("install", ["false"])[0].lower() in ("false", "0", "off", "no"))


def is_upload_control(scope, *, worker_run=False):
    return (not worker_run and (is_upload_transport(scope)
            or is_master_preview_enqueue(scope) or is_peak_enqueue(scope)
            or is_landing_recheck(scope)))


def is_landing_recheck(scope, *, worker_run=False):
    if (scope.get("type", "http") != "http" or scope.get("method") != "POST"
            or scope.get("volt_worker") or worker_run
            or scope.get("query_string", b"") != b""
            or not LANDING_RECHECK.fullmatch(scope.get("path", ""))):
        return False
    return True


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
