#!/usr/bin/env python3
"""Run the synthetic mixed workload once against an isolated loopback API.

Fixtures and output stay outside Git. This command never seeds data, deploys,
pushes Git or targets the public production domain. k6 threshold exit 99 remains
99; resource samples are supporting evidence, not replacement latency metrics.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests/load/production.js"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")
SYNTHETIC_UID = re.compile(r"sheet-LOAD[0-9]{6,12}\Z")


def now():
    return datetime.now(timezone.utc).isoformat()


def duration_seconds(value):
    match = re.fullmatch(r"([1-9][0-9]*)([smh])", value)
    if not match:
        raise argparse.ArgumentTypeError("Duration must be an integer followed by s, m or h")
    seconds = int(match[1]) * {"s": 1, "m": 60, "h": 3600}[match[2]]
    if seconds > 3600:
        raise argparse.ArgumentTypeError("Duration may not exceed one hour")
    return seconds


def loopback_url(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
        valid = (parsed.scheme in ("http", "https") and address.is_loopback and port is not None
                 and 1024 <= port <= 65535 and port not in (8080, 8081)
                 and not parsed.username and not parsed.password and not parsed.query
                 and not parsed.fragment and parsed.path in ("", "/"))
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError("Use a literal loopback IP and explicit isolated port; production ports refused")
    return value.rstrip("/")


def outside_git(path):
    path = path.absolute()
    if path.resolve() != path or path.is_relative_to(ROOT) or any((parent / ".git").exists() for parent in path.parents):
        raise ValueError("Fixture/output paths must be outside Git and contain no symlinks")
    return path


def private_json(path, *, token_file=False):
    path = outside_git(path)
    info = path.stat()
    protected_parent = any(parent.stat().st_uid == os.geteuid() and not parent.stat().st_mode & 0o077
                           for parent in path.parents)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022
            or (token_file and info.st_mode & 0o077) or not protected_parent):
        raise ValueError("Fixtures must be privately protected and owned by the invoking user")
    if info.st_size > 4 * 1024 * 1024:
        raise ValueError("Fixture exceeds its permitted size")
    with path.open(encoding="utf-8") as file:
        return json.load(file), path


def validate_fixtures(dataset_path, tokens_path):
    dataset, dataset_path = private_json(dataset_path)
    users, tokens_path = private_json(tokens_path, token_file=True)
    if not isinstance(dataset, dict) or dataset.get("synthetic") is not True:
        raise ValueError("An explicitly synthetic dataset is required")
    uids = dataset.get("customer_uids")
    if (not isinstance(uids, list) or not uids or not all(isinstance(uid, str) and SYNTHETIC_UID.fullmatch(uid) for uid in uids)
            or len(set(uids)) != len(uids) or type(dataset.get("customers")) is not int or len(uids) != dataset["customers"]):
        raise ValueError("Dataset must contain unique synthetic sheet-LOAD customer UIDs and matching counts")
    for key in ("contracts", "instalments_per_contract"):
        if type(dataset.get(key)) is not int or dataset[key] < 1:
            raise ValueError("Dataset contract/cycle counts are required")
    if (not isinstance(users, list) or len(users) != 25
            or not all(isinstance(row, dict) and isinstance(row.get("token"), str) and 16 <= len(row["token"]) <= 8192
                       and isinstance(row.get("subject"), str) and re.fullmatch(r"vu[0-9]+@load\.example\.test", row["subject"])
                       for row in users)
            or len({row["subject"] for row in users}) != 25 or len({row["token"] for row in users}) != 25):
        raise ValueError("Exactly 25 distinct synthetic actor tokens are required")
    return dataset, users, dataset_path, tokens_path


def atomic_json(path, payload):
    descriptor, temporary = tempfile.mkstemp(prefix=".k6-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            os.fchmod(file.fileno(), 0o600)
            json.dump(payload, file, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def actor_roles(base, users):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    roles = Counter()
    for actor in users:
        request = urllib.request.Request(base + "/api/v1/auth/me", headers={
            "Authorization": "Bearer " + actor["token"], "Accept": "application/json"})
        with opener.open(request, timeout=10) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise ValueError("Synthetic actor authentication preflight failed")
            body = response.read(16385)
            if len(body) > 16384:
                raise ValueError("Authentication preflight response exceeds its limit")
            identity = json.loads(body)
        if identity.get("subject") != actor["subject"] or identity.get("role") not in (
                "OWNER", "MANAGER", "SUPERVISOR", "OFFICER", "OPS"):
            raise ValueError("Authenticated identity does not match the synthetic actor fixture")
        roles[identity["role"]] += 1
    return dict(roles)


def runtime_binding(container):
    """Bind the measured target to immutable metadata, without inspecting env."""
    if not container:
        return {}
    template = ('{"image":{{json .Image}},"revision":'
                '{{json (index .Config.Labels "org.opencontainers.image.revision")}}}')
    result = subprocess.run(["docker", "inspect", "--format", template, container],
                            capture_output=True, text=True, timeout=10, check=True)
    values = json.loads(result.stdout)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", values.get("image") or ""):
        raise ValueError("Isolated API image must be immutable")
    revision = values.get("revision")
    return {"api_image": values["image"],
            "revision": revision if re.fullmatch(r"[0-9a-f]{40}", revision or "") else None}


def bytes_size(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([kKMGTPE]?i?B)", value.strip())
    if not match:
        return None
    unit = match[2]
    power = 0 if unit == "B" else "KMGTPE".index(unit[0].upper()) + 1
    return int(float(match[1]) * (1024 if "i" in unit else 1000) ** power)


def resource_sample(names, started):
    sample = {"timestamp_utc": now(), "elapsed_seconds": round(time.monotonic() - started, 3),
              "host": {}, "containers": [], "errors": []}
    try:
        memory = {line.split(":", 1)[0]: int(line.split()[1]) * 1024
                  for line in Path("/proc/meminfo").read_text().splitlines() if len(line.split()) > 1}
        sample["host"] = {"mem_available_bytes": memory["MemAvailable"], "swap_total_bytes": memory["SwapTotal"],
                          "swap_free_bytes": memory["SwapFree"], "swap_used_bytes": memory["SwapTotal"] - memory["SwapFree"]}
    except (OSError, KeyError, ValueError):
        sample["errors"].append("host_memory_sample_unavailable")
    if names:
        try:
            result = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *names],
                                    capture_output=True, text=True, timeout=5, check=True)
            stats = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            template = ('{"name":{{json .Name}},"running":{{json .State.Running}},'
                        '"oom_killed":{{json .State.OOMKilled}},"restart_count":{{json .RestartCount}},'
                        '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}}')
            result = subprocess.run(["docker", "inspect", "--format", template, *names],
                                    capture_output=True, text=True, timeout=5, check=True)
            states = {row["name"].lstrip("/"): row for row in (json.loads(line) for line in result.stdout.splitlines() if line.strip())}
            for row in stats:
                usage, limit = row.get("MemUsage", " / ").split("/", 1)
                state = states.get(row.get("Name"), {})
                sample["containers"].append({"name": row.get("Name"),
                    "cpu_percent": float(row["CPUPerc"].rstrip("%")), "memory_percent": float(row["MemPerc"].rstrip("%")),
                    "memory_usage_bytes": bytes_size(usage), "memory_limit_bytes": bytes_size(limit),
                    **{key: state.get(key) for key in ("oom_killed", "restart_count", "running", "health")}})
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            sample["errors"].append("docker_resource_sample_unavailable")
    return sample


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, type=loopback_url)
    parser.add_argument("--tokens-file", required=True, type=Path)
    parser.add_argument("--dataset-file", required=True, type=Path)
    parser.add_argument("--vus", type=int, default=10)
    parser.add_argument("--duration", default="120s")
    parser.add_argument("--profile", choices=("historical", "paged", "debt-workflow"), default="historical",
                        help="Historical workload, paged Today supplement, or real Debt mutations")
    parser.add_argument("--concurrent-preview-file", type=Path, help="Private XLSX staged once during load, never applied")
    parser.add_argument("--preview-profile", choices=("debt_status", "contract_supplement"), default="debt_status")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--api-container")
    parser.add_argument("--db-container")
    parser.add_argument("--k6", default=shutil.which("k6") or "/srv/volt-hardening-tools/k6-v2.3.0-linux-amd64/k6")
    args = parser.parse_args(argv)
    try:
        args.duration_seconds = duration_seconds(args.duration)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if not 1 <= args.vus <= 25 or not SAFE_NAME.fullmatch(args.run_id):
        parser.error("Use 1–25 VUs and a safe alphanumeric run ID")
    for name in (args.api_container, args.db_container):
        if name and (not SAFE_NAME.fullmatch(name) or name.startswith("volt-debt-")):
            parser.error("Resource containers must be isolated load-test containers")
    return args


def main(argv=None):
    args = arguments(argv)
    os.umask(0o077)
    try:
        dataset, users, dataset_path, tokens_path = validate_fixtures(args.dataset_file, args.tokens_file)
        preview_path = outside_git(args.concurrent_preview_file) if args.concurrent_preview_file else None
        if preview_path:
            info = preview_path.stat()
            protected = any(parent.stat().st_uid == os.geteuid() and not parent.stat().st_mode & 0o077 for parent in preview_path.parents)
            if (not protected or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022
                    or preview_path.suffix.lower() != ".xlsx" or not 0 < info.st_size <= 100 * 1024 * 1024):
                raise ValueError("Preview XLSX must be private, regular, owned and below100MiB")
        output = outside_git(args.output_dir)
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        if output.stat().st_uid != os.geteuid() or output.stat().st_mode & 0o022:
            raise ValueError("Output directory must be protected from other writers")
        prefix = output / ("k6-" + args.run_id)
        paths = {name: Path(str(prefix) + suffix) for name, suffix in (
            ("summary", "-summary.json"), ("meta", "-meta.json"), ("resources", "-resources.json"), ("log", ".log"))}
        if any(path.exists() or path.is_symlink() for path in paths.values()):
            raise ValueError("Run ID already has output; choose a new run ID")
        binary = shutil.which(args.k6) if not Path(args.k6).is_absolute() else args.k6
        if not binary:
            raise ValueError("Installed k6 executable is unavailable")
        version = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        script = {"historical": SCRIPT, "paged": ROOT / "tests/load/capacity.js",
                  "debt-workflow": ROOT / "tests/load/debt_workflow.js"}[args.profile]
        binding = runtime_binding(args.api_container)
        roles = actor_roles(args.base_url, users)
        meta = {"timestamp_utc": now(), "run_id": args.run_id, "vus": args.vus,
                "duration": args.duration, "duration_seconds": args.duration_seconds,
                "dataset": {key: dataset[key] for key in ("synthetic", "customers", "contracts", "instalments_per_contract")},
                "actors": 25, "actor_roles": roles, "k6_version": version, "target": args.base_url,
                "generator_co_located": True, "workload_script": str(script.relative_to(ROOT)), "profile": args.profile,
                "workload_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                "historical_workload_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                "read_write_mix": {"primary_reads": {"workbook": 40, "today": 30, "case": 20, "monthly": 10},
                                   "write_every_iterations": 5, "write": "synthetic case note", "replay_on_success": True},
                "summary_file": str(paths["summary"]), "resources_file": str(paths["resources"]),
                "exit_code": None, "notes": ["25 authenticated actor-role preflight reads occur before measured k6 duration",
                    "Generator and target are co-located; results include host resource contention",
                    "Native k6 summary metrics and failed thresholds are authoritative",
                    "Dataset preparation and state priming are external and excluded from measured duration"]}
        meta.update(binding)
        if args.profile == "debt-workflow":
            meta["read_write_mix"] = {"reads": "case before each act and final conservation check",
                "writes": ["next_action", "dc_status", "uncounted_contact", "ptp_create", "ptp_close"],
                "complete_action_includes": ["case_read", "mutation", "conflict_refresh_retry", "idempotent_replay"],
                "customer_partitions": "distinct per actor", "cash_conservation": True}
        if preview_path:
            meta["concurrent_preview"] = {"profile": args.preview_profile, "source_bytes": preview_path.stat().st_size,
                "source_sha256": hashlib.sha256(preview_path.read_bytes()).hexdigest(), "never_applied": True,
                "isolated_staging_only": True, "contains_user_supplied_data": True, "started": False}
        atomic_json(paths["meta"], meta)
        samples, stop = [], threading.Event()
        names = list(dict.fromkeys(name for name in (args.api_container, args.db_container) if name))
        started = time.monotonic()

        def sample_loop():
            while not stop.is_set():
                began = time.monotonic()
                samples.append(resource_sample(names, started))
                if stop.wait(max(0, 2 - (time.monotonic() - began))):
                    break

        sampler = threading.Thread(target=sample_loop, daemon=True)
        sampler.start()
        preview_thread = None
        if preview_path:
            def preview_once():
                if stop.wait(5):
                    return
                observed = meta["concurrent_preview"]
                observed.update(started=True, started_at_utc=now())
                began = time.monotonic()
                owner = next((actor for actor in users if actor.get("role", "OWNER") in ("OWNER", "MANAGER")), users[0])
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    request = urllib.request.Request(args.base_url + "/api/v1/imports?profile=" + args.preview_profile,
                        data=preview_path.read_bytes(), headers={"Authorization": "Bearer " + owner["token"],
                        "Content-Type": "application/octet-stream", "X-Volt-Filename": preview_path.name,
                        "Idempotency-Key": args.run_id + "-owned-preview"}, method="POST")
                    with opener.open(request, timeout=180) as response:
                        observed["status"] = response.status
                        body = response.read(100 * 1024 * 1024 + 1)
                        if len(body) <= 100 * 1024 * 1024:
                            parsed = json.loads(body)
                            observed["counts"] = parsed.get("counts") or (parsed.get("preview") or {}).get("counts")
                        observed["passed"] = 200 <= response.status < 300
                except Exception as exc:
                    observed.update(passed=False, cause=type(exc).__name__, status=getattr(exc, "code", None))
                finally:
                    observed.update(elapsed_ms=round((time.monotonic() - began) * 1000, 3), completed_at_utc=now())
            preview_thread = threading.Thread(target=preview_once, daemon=True)
            preview_thread.start()
        # Avoid inherited HTTP debug/output flags that could reveal bearer headers
        # or silently change scenario behavior. No token values enter environment.
        environment = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
        environment.update(BASE_URL=args.base_url, TOKENS_FILE=str(tokens_path), DATASET_FILE=str(dataset_path),
                           VUS=str(args.vus), DURATION=args.duration, RUN_ID=args.run_id,
                           SUMMARY_FILE=str(paths["summary"]), THINK_SECONDS="1")
        code, raw_code = 1, None
        try:
            with paths["log"].open("xb") as log:
                process = subprocess.Popen([binary, "run", str(script)], cwd=output, env=environment,
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                try:
                    raw_code = process.wait(timeout=args.duration_seconds + 180)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raw_code = process.returncode
                    meta["notes"].append("Generator interrupted or exceeded its duration/grace budget")
                code = raw_code if raw_code >= 0 else 128 - raw_code
        finally:
            stop.set()
            sampler.join(timeout=12)
            if preview_thread:
                preview_thread.join(timeout=190)
                if not meta["concurrent_preview"].get("passed"):
                    code = code or 1
                    meta["notes"].append("Owned preview did not complete successfully; no apply was attempted")
            samples.append(resource_sample(names, started))
            atomic_json(paths["resources"], {"interval_seconds": 2, "samples": samples})
            meta.update(completed_at_utc=now(), elapsed_seconds=round(time.monotonic() - started, 3),
                        process_return_code=raw_code, exit_code=code, summary_present=paths["summary"].is_file())
            atomic_json(paths["meta"], meta)
        print("k6 completed; exit=" + str(code) + "; metadata=" + str(paths["meta"]))
        return code
    except (OSError, ValueError, subprocess.SubprocessError):
        print("k6 orchestration refused or failed; check private fixtures, target and installed tools", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
