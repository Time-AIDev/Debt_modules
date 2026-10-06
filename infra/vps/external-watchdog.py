#!/usr/bin/env python3
"""Run on an independent host: public readiness and offsite recovery-point checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from incident_alerts import AlertError, NoRedirect, config, private_json, publish
from recovery_support import RecoveryError, private_file


def machine_fingerprint():
    return hashlib.sha256(Path("/etc/machine-id").read_bytes().strip()).hexdigest()


def independent(settings):
    production = settings.get("production_fingerprint", "")
    if not re.fullmatch(r"[a-f0-9]{64}", production):
        raise ValueError("A verified production host fingerprint is required")
    if machine_fingerprint() == production:
        raise ValueError("External watchdog must run on a host independent of production")


def configuration(path):
    settings = private_json(path)
    independent(settings)
    remote = settings.get("recovery_point_remote", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+:[^\s]+", remote) or ".." in remote.split(":", 1)[1].split("/"):
        raise ValueError("A configured offsite recovery point is required")
    private_file(Path(settings.get("rclone_config", "/etc/volt-debt/rclone.conf")), maximum=1048576)
    receiver = config(settings["alerts_config"])
    if not receiver.get("url"):
        raise ValueError("An incident receiver is required")
    return settings


def inspect(settings, *, now=None, opener=None, command=subprocess.run):
    now = now or datetime.now(timezone.utc)
    independent(settings)
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
        settings = configuration(args.config)
        os.environ['RCLONE_CONFIG'] = settings.get('rclone_config', '/etc/volt-debt/rclone.conf')
        failures = inspect(settings)
        receiver = config(settings["alerts_config"])
        receiver.update(service="volt-debt-external-watchdog")
        outcome = publish(failures, receiver, settings["state_path"])
        print(json.dumps({"healthy": not failures, "alerts": outcome}))
        return 1 if failures else 0
    except (AlertError, RecoveryError, ValueError, OSError, KeyError):
        print("External watchdog configuration or delivery failed; inspect private configuration", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
