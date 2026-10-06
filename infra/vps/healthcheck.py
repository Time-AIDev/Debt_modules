#!/usr/bin/env python3
"""Local operational checks; failures appear in the systemd journal, not external alerts."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/usr/local/lib/volt-debt-ops")
from incident_alerts import AlertError, configured_notification


def main():
    failures = []
    names = [f"volt-debt-{service}-1" for service in ("db", "scanner", "api", "worker", "web", "edge")]
    try:
        result = subprocess.run(["docker", "inspect", *names], capture_output=True, text=True, timeout=20, check=True)
        for container in json.loads(result.stdout):
            state = container["State"]
            name = container["Name"].lstrip("/")
            if not state["Running"] or state.get("OOMKilled"):
                failures.append(f"{name}: stopped or OOM killed")
            if state.get("Health", {}).get("Status", "healthy") != "healthy":
                failures.append(f"{name}: health check not healthy")
    except (subprocess.SubprocessError, ValueError):
        failures.append("container inspection failed")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for label, url in (("API readiness", "http://127.0.0.1:8081/readyz"),
                       ("web", "http://127.0.0.1:8080/healthz"),
                       ("authentication", "http://127.0.0.1:8081/api/v1/auth/config")):
        try:
            with opener.open(url, timeout=5) as response:
                body = response.read(8192)
                if label == "authentication":
                    config = json.loads(body)
                    if config.get("mode") != "on" or config.get("password_enabled") is not False or not config.get("google_client_id"):
                        failures.append("production authentication configuration invalid")
        except Exception:
            failures.append(f"{label}: request failed")
    disk = shutil.disk_usage("/srv")
    if disk.free / disk.total < 0.15:
        failures.append("less than 15% disk space free")
    try:
        memory = {line.split(":", 1)[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if len(line.split()) >= 2}
        if memory["MemAvailable"] + memory["SwapFree"] < 256 * 1024:
            failures.append("less than 256 MiB memory and swap available")
        backups = [p / "COMPLETE" for p in Path("/srv/volt-debt-backups").iterdir()
                   if p.is_dir() and not p.name.startswith(".")
                   and (p / "BACKUP_FORMAT").is_file()
                   and (p / "BACKUP_FORMAT").read_text().strip() == "volt-debt-backup-v1"
                   and (p / "COMPLETE").is_file()]
        if not backups or time.time() - max(p.stat().st_mtime for p in backups) > 26 * 3600:
            failures.append("no completed backup in the last 26 hours")
    except (OSError, ValueError, KeyError):
        failures.append("capacity or backup inspection failed")
    try:
        configured_notification(failures)
    except AlertError:
        failures.append("incident notification was not acknowledged; pending retry retained")
    if failures:
        print("FAILED: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("OK: six services, database readiness, web, production auth, capacity, recent backup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
