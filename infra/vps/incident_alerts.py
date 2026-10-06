"""Acknowledged incident/recovery events with durable retry and deduplication."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from urllib.parse import urlsplit
import urllib.request


class AlertError(RuntimeError):
    """Diagnostics must not contain receiver URLs, tokens or response bodies."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def private_json(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise AlertError("Alert configuration/state must be an absolute private file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise AlertError("Alert configuration/state permissions are not private")
        raw = file.read(65537)
    if len(raw) > 65536:
        raise AlertError("Alert configuration/state is too large")
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeDecodeError):
        raise AlertError("Alert configuration/state is malformed") from None


def config(path):
    data = private_json(path)
    target = urlsplit(data.get("url", ""))
    if target.scheme != "https" or not target.hostname or target.username or target.password:
        raise AlertError("Incident receiver requires HTTPS without URL credentials")
    token = data.get("token", "")
    if not isinstance(token, str) or "\r" in token or "\n" in token:
        raise AlertError("Incident receiver authentication is malformed")
    return data


def write_state(path, data):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or path.parent.is_symlink():
        raise AlertError("Alert state path is unsafe")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".alert-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            os.fchmod(file.fileno(), 0o600)
            json.dump(data, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def publish(failures, settings, state_path, *, now=None, opener=None, sleeper=time.sleep):
    """Retain the same pending event ID until the receiver acknowledges it.

    Callers supply only fixed operational labels; customer data, credentials and
    raw transport exceptions never belong in incident summaries.
    """
    if not settings:
        return {"configured": False, "acknowledged": False}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise AlertError("Incident time must include its timezone")
    epoch = now.timestamp()
    path = Path(state_path)
    previous = private_json(path) if path.exists() else {}
    failures = sorted(set(failures))
    pending = previous.get("pending")
    was_failed = previous.get("state") == "failure" or (pending or {}).get("state") == "failure"
    state = "failure" if failures else "recovery" if was_failed else "heartbeat"
    signature = hashlib.sha256(json.dumps([state, failures], sort_keys=True).encode()).hexdigest()
    interval = 900 if state == "failure" else 60
    if (not pending and previous.get("signature") == signature
            and 0 <= epoch - previous.get("ack_at", 0) < interval):
        return {"configured": True, "acknowledged": False, "deduplicated": True}
    if not pending or pending.get("signature") != signature:
        event_id = hashlib.sha256((signature + ":" + now.isoformat()).encode()).hexdigest()
        pending = {
            "format": "volt-incident-v1", "event_id": event_id,
            "environment": settings.get("environment", "production"),
            "service": settings.get("service", "volt-debt"),
            "severity": "critical" if failures else "info", "state": state,
            "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
            "summary": "; ".join(failures) if failures else "Operational checks recovered" if was_failed else "Operational heartbeat",
            "signature": signature,
        }
        previous["pending"] = pending
        write_state(path, previous)
    wire = {key: value for key, value in pending.items() if key != "signature"}
    headers = {"Content-Type": "application/json", "Idempotency-Key": pending["event_id"],
               "User-Agent": "Volt-operations/1"}
    if settings.get("token"):
        headers["Authorization"] = "Bearer " + settings["token"]
    request = urllib.request.Request(settings["url"], data=json.dumps(wire).encode(), headers=headers, method="POST")
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(request, timeout=5) as response:
                if not 200 <= response.status < 300:
                    raise AlertError("Incident receiver did not acknowledge the event")
                response.read(4096)
            write_state(path, {"state": state, "signature": signature, "ack_at": epoch,
                               "last_event_id": pending["event_id"]})
            return {"configured": True, "acknowledged": True,
                    "state": state, "event_id": pending["event_id"]}
        except Exception:
            if attempt < 2:
                sleeper(2 ** attempt)
    raise AlertError("Incident delivery failed; private pending event retained for retry") from None


def configured_notification(failures, *, service="volt-debt", now=None):
    path = Path(os.environ.get("VOLT_ALERT_CONFIG", "/etc/volt-debt/alerts.json"))
    if not path.exists():
        return {"configured": False, "acknowledged": False}
    settings = config(path)
    settings["service"] = service
    return publish(failures, settings, settings.get("state_path", "/var/lib/volt-debt-ops/alert-state.json"), now=now)
