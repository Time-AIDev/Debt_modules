"""Read-only production probes protect the host during provisional local load."""
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import time
import urllib.request

MIN_AVAILABLE_BYTES = 512 * 1024 * 1024
URLS = {"liveness": "https://collection.volt.co.th/healthz",
        "readiness": "https://collection.volt.co.th/readyz"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def probe_health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    endpoints = {}
    for name, url in URLS.items():
        began = time.monotonic()
        status, valid_json = None, False
        try:
            with opener.open(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=2) as response:
                status = response.status
                body = response.read(4097)
                valid_json = (len(body) <= 4096 and response.headers.get_content_type() == "application/json"
                              and isinstance(json.loads(body), dict))
        except Exception as exc:
            status = getattr(exc, "code", None)
        endpoints[name] = {"status": status, "json": valid_json,
                           "elapsed_ms": round((time.monotonic() - began) * 1000, 3)}
    memory = {line.split(":", 1)[0]: int(line.split()[1]) * 1024
              for line in Path("/proc/meminfo").read_text().splitlines() if len(line.split()) > 1}
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "endpoints": endpoints, "available_memory_bytes": memory["MemAvailable"],
            "production_healthy": all(row["status"] == 200 and row["json"] and row["elapsed_ms"] < 2000
                                      for row in endpoints.values())}


def owned_inventory(api, database):
    template = ('{"name":{{json .Name}},"tag":{{json (index .Config.Labels "volt.capacity.diagnostic")}},'
                '"memory":{{json .HostConfig.Memory}},"quota":{{json .HostConfig.CpuQuota}},'
                '"running":{{json .State.Running}},"oom":{{json .State.OOMKilled}},'
                '"restarts":{{json .RestartCount}}}')
    raw = subprocess.run(["docker", "inspect", "--format", template, api, database],
                         capture_output=True, text=True, timeout=5, check=True).stdout
    rows = [json.loads(line) for line in raw.splitlines() if line]
    if (len(rows) != 2 or not rows[0].get("tag") or rows[0]["tag"] != rows[1].get("tag")
            or [row["name"].lstrip("/") for row in rows] != [api, database]
            or api != rows[0]["tag"] + "-api" or database != rows[0]["tag"] + "-db"
            or [row["memory"] for row in rows] != [1024 ** 3, 512 * 1024 ** 2]
            or any(row["quota"] not in (-1, 0) for row in rows)):
        raise ValueError("Health guard requires the owned diagnostic resource limits")
    return rows


class Guard:
    interval_seconds = 5

    def __init__(self, api, database):
        self.api, self.database = api, database
        self.bad_health, self.low_memory = 0, 0
        self.evidence = {"enabled": True, "minimum_available_memory_bytes": MIN_AVAILABLE_BYTES,
                         "interval_seconds": self.interval_seconds, "aborted": False,
                         "reason": None, "isolated_api_stopped": False, "samples": []}

    def poll(self, *, baseline=False):
        rows = owned_inventory(self.api, self.database)
        observed = probe_health()
        self.evidence["samples"].append(observed)
        self.bad_health = self.bad_health + 1 if not observed["production_healthy"] else 0
        self.low_memory = self.low_memory + 1 if observed["available_memory_bytes"] < MIN_AVAILABLE_BYTES else 0
        reason = ("target_oom" if any(row["oom"] for row in rows) else
                  "target_restart" if any(row["restarts"] for row in rows) else
                  "target_not_running" if any(not row["running"] for row in rows) else
                  "production_health" if self.bad_health >= (1 if baseline else 3) else
                  "host_low_memory" if self.low_memory >= (1 if baseline else 2) else None)
        if baseline:
            self.evidence["baseline_passed"] = reason is None
        if reason:
            self.evidence.update(aborted=True, reason=reason)
        return reason

    def stop_isolated_api(self):
        # Prove ownership again immediately before mutation. Production containers
        # never match this label/name contract and are never stopped or restarted.
        owned_inventory(self.api, self.database)
        subprocess.run(["docker", "stop", "--time", "2", self.api],
                       capture_output=True, timeout=8, check=True)
        self.evidence["isolated_api_stopped"] = True
