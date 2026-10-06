#!/usr/bin/env python3
"""Run on an independent host: public readiness and offsite recovery-point checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from incident_alerts import AlertError, NoRedirect, config, private_json, publish


def machine_fingerprint():
    return hashlib.sha256(Path("/etc/machine-id").read_bytes().strip()).hexdigest()


def inspect(settings, *, now=None, opener=None, command=subprocess.run):
    now = now or datetime.now(timezone.utc)
    if machine_fingerprint() == settings.get("production_fingerprint"):
        raise ValueError("External watchdog must run on a host independent of production")
    failures = []
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open("https://collection.volt.co.th/readyz", timeout=5) as response:
            data = json.loads(response.read(8192))
            if response.status != 200 or data.get("status") != "ready":
                failures.append("production public readiness failed")
    except Exception:
        failures.append("production public HTTPS unreachable or not ready")
    try:
        result = command(["rclone", "cat", settings["recovery_point_remote"]],
                         capture_output=True, timeout=30, check=True)
        point = json.loads(result.stdout)
        captured = datetime.fromisoformat(point["captured_at_utc"].replace("Z", "+00:00"))
        age = (now - captured).total_seconds()
        if point.get("encrypted") is not True or not 0 <= age <= 86400:
            failures.append("encrypted offsite recovery point exceeds 24-hour RPO")
    except Exception:
        failures.append("offsite recovery point cannot be verified")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        settings = private_json(args.config)
        failures = inspect(settings)
        receiver = config(settings["alerts_config"])
        receiver.update(service="volt-debt-external-watchdog")
        outcome = publish(failures, receiver, settings["state_path"])
        print(json.dumps({"healthy": not failures, "alerts": outcome}))
        return 1 if failures else 0
    except (AlertError, ValueError, OSError, KeyError):
        print("External watchdog configuration or delivery failed; inspect private configuration", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
