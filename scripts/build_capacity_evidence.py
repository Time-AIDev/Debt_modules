#!/usr/bin/env python3
"""Map actual private k6 artifacts to the release gate, without certifying them.

This local mapper always preserves COLOCATED_PROVISIONAL status and the identical
generator/target host fingerprint. It cannot satisfy the independent-host gate.
Missing observations remain unknown; native summaries are copied only to a
private output outside Git.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ORIGINAL = "480b0646dd3ec6405c4d0afa7b2e94371e62a9c47f711978cfed5f3ee8ab7ec5"
REVISION = re.compile(r"[0-9a-f]{40}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
RUN_ID = re.compile(r"[0-9a-f]{7,40}-(?:historical|paged|debt-workflow)-(?:1|10|25)vu(?:-(?:mixed|import|growth|soak))?\Z")


def read(path):
    return json.loads(path.read_text()) if path.is_file() else None


def private_output(path):
    path = path.absolute()
    if path.resolve() != path or any((parent / ".git").exists() for parent in path.parents):
        raise ValueError("Quality capacity output must be outside Git without symlinks")
    if not any(parent.exists() and parent.stat().st_mode & 0o077 == 0 for parent in path.parents):
        raise ValueError("Quality capacity output requires a protected private parent")
    return path


def observation_resources(resources):
    samples = (resources or {}).get("samples") or []
    containers = [row for sample in samples for row in sample.get("containers", [])]
    if not containers or any(type(row.get("oom_killed")) is not bool or type(row.get("restart_count")) is not int
                             for row in containers):
        return None, None
    grouped = {}
    for row in containers:
        grouped.setdefault(row["name"], []).append(row["restart_count"])
    if len(grouped) != 2:
        return None, None
    return any(row["oom_killed"] for row in containers), max(values[-1] - values[0] for values in grouped.values())


def map_run(directory, planned, revision, api_image, queue):
    run_id = planned["run_id"]
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Unknown capacity run identifier")
    prefix = directory / ("k6-" + run_id)
    summary, meta = read(Path(str(prefix) + "-summary.json")), read(Path(str(prefix) + "-meta.json"))
    resources = read(Path(str(prefix) + "-resources.json"))
    if not meta:
        return {"scenario": planned.get("scenario"), "run_id": run_id, "execution": "not_executed",
                "vus": planned["vus"], "exit_code": None, "summary": None}
    if not summary:
        return {"scenario": planned.get("scenario"), "run_id": run_id, "execution": "incomplete_native_evidence",
                "vus": meta.get("vus"), "exit_code": meta.get("exit_code"), "native_exit_code": meta.get("process_return_code"),
                "summary": None, "source_binding_verified": meta.get("revision") == revision and meta.get("api_image") == api_image}
    dataset = meta.get("dataset") or {}
    oom, restarts = observation_resources(resources)
    counts = (queue or {}).get(run_id) or {}
    bound_queue = counts.get("revision") == revision and counts.get("api_image") == api_image and counts.get("isolated_read_only") is True
    before, after = counts.get("pending_before"), counts.get("pending_after")
    queue_growth = after > before if bound_queue and type(before) is int and type(after) is int else None
    guard = meta.get("production_health_guard") or {}
    return {"run_id": run_id, "scenario": planned.get("scenario"), "execution": "observed",
            "source_binding_verified": meta.get("revision") == revision and meta.get("api_image") == api_image,
            "exit_code": meta.get("exit_code"), "native_exit_code": meta.get("process_return_code"),
            "duration_seconds": meta.get("duration_seconds"), "vus": meta.get("vus"),
            "customers": dataset.get("customers"), "instalments_per_contract": dataset.get("instalments_per_contract"),
            "unchanged_workload": meta.get("profile") == "historical" and meta.get("workload_sha256") == ORIGINAL,
            "legacy_unpaged_today": meta.get("profile") == "historical" and meta.get("workload_sha256") == ORIGINAL,
            "workload_sha256": meta.get("workload_sha256"), "roles": sorted((meta.get("actor_roles") or {}).keys()),
            "oom_observed": oom, "restart_delta": restarts, "queue_growth": queue_growth,
            "production_health_guard_passed": guard.get("baseline_passed") is True and guard.get("monitor_completed") is True
                and guard.get("aborted") is False,
            "concurrent_preview": {key: (meta.get("concurrent_preview") or {}).get(key)
                for key in ("profile", "started", "passed", "never_applied", "isolated_staging_only")},
            "summary_sha256": hashlib.sha256(Path(str(prefix) + "-summary.json").read_bytes()).hexdigest(),
            "meta_sha256": hashlib.sha256(Path(str(prefix) + "-meta.json").read_bytes()).hexdigest(),
            "summary": summary}


def build(directory, plan, revision, api_image, web_image, queue):
    runs = [map_run(directory, row, revision, api_image, queue) for row in plan["runs"]]
    fingerprint = hashlib.sha256(Path("/etc/machine-id").read_bytes().strip()).hexdigest()
    return {"status": "provisional", "classification": "COLOCATED_PROVISIONAL", "revision": revision,
            "images": {"api": api_image, "web": web_image}, "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "generator_fingerprint": fingerprint, "target_fingerprint": fingerprint,
            "target_isolated": plan.get("target_isolated") is True,
            "matching_resource_profile": all(run.get("production_health_guard_passed") is True for run in runs),
            "historical": [run for run in runs if run.get("scenario") == "historical"],
            "supplemental": [run for run in runs if run.get("scenario") != "historical"],
            "unexecuted": sum(run["execution"] == "not_executed" for run in runs),
            "source_binding_complete": all(run.get("source_binding_verified") is True for run in runs),
            "capacity_acceptance_certified": False,
            "scope": "Native local diagnostics; independent-generator acceptance remains unfulfilled"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--queue-observations", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not REVISION.fullmatch(args.revision) or not IMAGE.fullmatch(args.api_image) or not IMAGE.fullmatch(args.web_image):
        parser.error("Exact committed revision and immutable images required")
    output = private_output(args.output)
    data = build(args.results_dir, read(args.run_plan), args.revision, args.api_image, args.web_image, read(args.queue_observations))
    output.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    output.chmod(0o600)
    print("Provisional capacity artifact written; unexecuted=" + str(data["unexecuted"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
