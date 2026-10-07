"""Validate exact-release quality evidence before opening production traffic.

These validators are deliberately independent of credentials and Docker. Native
k6 metrics remain authoritative; successful deployment is not quality approval.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

REQUIRED = ("lint", "regression", "capacity", "financial", "usability",
            "offsite_recovery", "alerts", "rollback")
LIMITS = {"business_read_ms": ("p(95)", 2000, "p(95)<2000"),
          "business_write_ms": ("p(95)", 2000, "p(95)<2000"),
          "business_errors": ("rate", .01, "rate<0.01"),
          "checks": ("rate", .99, "rate>0.99"),
            "idempotency_replay_errors": ("rate", 0, "rate==0")}
HISTORICAL_WORKLOAD_SHA256 = "480b0646dd3ec6405c4d0afa7b2e94371e62a9c47f711978cfed5f3ee8ab7ec5"
# Required IDs from tests/dataflow/coverage-map.json. This validator also runs
# from the installed operations directory, where the test inventory is absent.
REGRESSION_FLOWS = frozenset((
    "intake-odoo", "intake-sheet", "intake-invoices", "intake-receipts", "money", "orders",
    "assignment", "collection", "recovery", "calendar-notices", "files", "queue-worker",
    "scheduler", "persistence", "publication", "report-export", "audit", "auth-transport", "operations",
))


class QualityError(ValueError):
    """Public-safe error: never include artifact contents or raw diagnostics."""


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (AttributeError, ValueError, TypeError):
        raise QualityError("Quality evidence requires a timezone-aware timestamp") from None


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise QualityError("Quality metrics must be finite numeric values")
    return value


def require(condition, message):
    if not condition:
        raise QualityError(message)


def zero(value):
    return type(value) is int and value == 0


def local_machine_fingerprint():
    return hashlib.sha256(Path("/etc/machine-id").read_bytes().strip()).hexdigest()


def regression(data):
    """A final regression covers both full suites on unchanged committed source."""
    require(data.get("scope") == "full_backend_frontend"
            and data.get("backend_selection") == ["tests"]
            and data.get("frontend_selection") == "all"
            and data.get("actual_pg_executed") is True,
            "Final regression requires the full backend with PostgreSQL and full frontend")
    revision = data.get("revision")
    require(isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{40}", revision),
            "Final regression requires a full committed revision")
    before, after = data.get("source_before"), data.get("source_after")
    require(isinstance(before, dict) and isinstance(after, dict) and before == after
            and data.get("source_unchanged") is True,
            "Regression source manifests changed or are missing")
    for manifest in (before, after):
        digest = manifest.get("tracked_sha256")
        require(manifest.get("revision") == revision and isinstance(digest, str)
                and re.fullmatch(r"[a-f0-9]{64}", digest)
                and manifest.get("tracked_clean") is True and zero(manifest.get("untracked_code_files")),
                "Regression source is uncommitted or differs from the release revision")
    for area in ("backend", "frontend"):
        result = data.get(area, {})
        require(type(result.get("passed")) is int and result["passed"] > 0 and zero(result.get("failed"))
                and zero(result.get("errors")) and zero(result.get("skipped")),
                "Required regression tests failed or were skipped: " + area)
    flows = data.get("flows")
    require(isinstance(flows, list) and all(isinstance(flow, dict) for flow in flows),
            "Required regression flow execution is missing")
    required = [flow for flow in flows if flow.get("id") in REGRESSION_FLOWS]
    require(len(required) == len(REGRESSION_FLOWS) and {flow.get("id") for flow in required} == REGRESSION_FLOWS,
            "Every required regression flow must have execution evidence")
    for flow in required:
        require(type(flow.get("observed_tests")) is int and flow["observed_tests"] > 0
                and type(flow.get("passed")) is int and flow["passed"] > 0
                and zero(flow.get("failed")) and zero(flow.get("skipped")),
                "A required regression flow was not exercised successfully")
    require(zero(data.get("frontend_build_exit")) and data.get("runtime_parity") is True,
            "Build or runtime parity failed")


def native_capacity(run, minimum_duration, minimum_vus):
    require(zero(run.get("exit_code")), "k6 exited without passing its thresholds")
    require(number(run.get("duration_seconds")) >= minimum_duration
            and number(run.get("vus")) >= minimum_vus, "k6 duration or VUs do not meet policy")
    metrics = run.get("summary", {}).get("metrics", {})
    require(number(run.get("summary", {}).get("state", {}).get("testRunDurationMs")) >= minimum_duration * 1000,
            "Native k6 elapsed duration is too short")
    require(number(metrics.get("vus_max", {}).get("values", {}).get("max")) >= minimum_vus,
            "Native k6 VU maximum is below policy")
    for name, (statistic, limit, expression) in LIMITS.items():
        metric = metrics.get(name, {})
        actual = number(metric.get("values", {}).get(statistic))
        if name == "checks":
            passed = .99 < actual <= 1
        elif name == "idempotency_replay_errors":
            passed = actual == 0
        elif statistic == "rate":
            passed = 0 <= actual < limit
        else:
            passed = 0 < actual < limit
        require(passed, "k6 metric failed the unchanged policy: " + name)
        require(metric.get("thresholds", {}).get(expression, {}).get("ok") is True,
                "k6 native threshold is missing or failed: " + name)
    require(number(metrics.get("http_reqs", {}).get("values", {}).get("count")) > 0,
            "k6 produced no requests")
    replay = metrics["idempotency_replay_errors"]["values"]
    require(number(replay.get("passes")) + number(replay.get("fails")) > 0,
            "k6 did not exercise replay")
    require(run.get("oom_observed") is False and zero(run.get("restart_delta"))
            and run.get("queue_growth") is False, "k6 resource or queue stability failed")


def capacity(data):
    require(data.get("target_isolated") is True and data.get("matching_resource_profile") is True,
            "Capacity target must be isolated and match production resources")
    generator, target = data.get("generator_fingerprint"), data.get("target_fingerprint")
    require(isinstance(generator, str) and isinstance(target, str)
            and re.fullmatch(r"[a-f0-9]{64}", generator) and re.fullmatch(r"[a-f0-9]{64}", target)
            and generator != target, "Capacity generator must be on an independent host")
    historical = data.get("historical", [])
    require(isinstance(historical, list), "Historical k6 matrix is missing")
    for vus in (1, 10, 25):
        runs = [run for run in historical if run.get("vus") == vus]
        require(len(runs) == 1, "Historical k6 matrix requires exactly one final run per VU level")
        run = runs[0]
        require(run.get("customers") == 500 and run.get("instalments_per_contract") == 96
                and run.get("unchanged_workload") is True and run.get("legacy_unpaged_today") is True
                and run.get("workload_sha256") == HISTORICAL_WORKLOAD_SHA256,
                "Historical k6 workload or payload was changed")
        native_capacity(run, 120, vus)
    supplemental = data.get("supplemental", [])
    require(isinstance(supplemental, list), "Supplemental capacity scenarios are missing")
    for name in ("paged_ui", "mixed_roles", "import_concurrency", "soak"):
        runs = [run for run in supplemental if run.get("scenario") == name]
        require(len(runs) == 1, "Required capacity scenario is missing: " + name)
        native_capacity(runs[0], 900 if name == "soak" else 120, 25)
        metrics = runs[0].get("summary", {}).get("metrics", {})
        if name == "paged_ui":
            require(0 < number(metrics.get("capacity_page_ms", {}).get("values", {}).get("p(95)")) < 2000
                    and metrics.get("capacity_page_ms", {}).get("thresholds", {}).get("p(95)<2000", {}).get("ok") is True
                    and 0 <= number(metrics.get("capacity_page_errors", {}).get("values", {}).get("rate")) < .01
                    and metrics.get("capacity_page_errors", {}).get("thresholds", {}).get("rate<0.01", {}).get("ok") is True,
                    "Paged UI native gates did not pass")
        else:
            require(0 < number(metrics.get("complete_action_ms", {}).get("values", {}).get("p(95)")) < 2000
                    and metrics.get("complete_action_ms", {}).get("thresholds", {}).get("p(95)<2000", {}).get("ok") is True
                    and number(metrics.get("debt_mutations_committed", {}).get("values", {}).get("count")) > 0
                    and metrics.get("debt_mutations_committed", {}).get("thresholds", {}).get("count>0", {}).get("ok") is True,
                    "Complete debt commands must be exercised and meet the original latency target")
        if name == "mixed_roles":
            require(set(runs[0].get("roles", [])) >= {"OWNER", "MANAGER", "SUPERVISOR", "OFFICER", "OPS"},
                    "Mixed-role capacity was not tested")
        if name == "import_concurrency":
            preview = runs[0].get("concurrent_preview", {})
            require(all(preview.get(key) is True for key in ("started", "passed", "never_applied", "isolated_staging_only"))
                    and preview.get("profile") in ("debt_status", "contract_supplement"),
                    "Concurrent protected import preview did not pass")
        if name == "soak":
            require(number(runs[0].get("customers")) >= 1431, "Soak fixture must represent the current portfolio")


def validate_check(kind, data, now, production_fingerprint):
    require(data.get("status") == "passed", "Quality check is not passed: " + kind)
    if kind == "lint":
        require(zero(data.get("errors")) and set(data.get("areas", [])) >= {"backend", "frontend"},
                "Backend/frontend lint must pass")
    elif kind == "regression":
        regression(data)
    elif kind == "capacity":
        capacity(data)
    elif kind == "financial":
        for key in ("staging_isolated", "actual_input_files", "rows_accounted", "cash_conserved",
                    "snapshot_cash_not_double_counted", "duplicate_import_once", "book_preserved"):
            require(data.get(key) is True, "Financial validation is incomplete: " + key)
        require(zero(data.get("unexplained_differences")) and zero(data.get("tests_failed")),
                "Unexplained financial differences remain")
        sources = data.get("input_files", [])
        require(len(sources) == 3 and len({x.get("sha256") for x in sources}) == 3
                and all(re.fullmatch(r"[a-f0-9]{64}", str(x.get("sha256", "")))
                                       for x in sources), "Actual workbook provenance is missing")
    elif kind == "usability":
        require(data.get("method") == "simulated_debt_team" and data.get("score") == 10
                and zero(data.get("critical")) and zero(data.get("high"))
                and zero(data.get("open_defects")) and zero(data.get("failed")) and zero(data.get("skipped"))
                and zero(data.get("unexercised")) and number(data.get("feature_count")) >= 19
                and number(data.get("checkpoints_total")) >= max(33, number(data.get("feature_count")))
                and data.get("checkpoints_passed") == data.get("checkpoints_total")
                and set(data.get("roles_observed", [])) >= {"OFFICER", "MANAGER", "OPS"},
                "Debt-team usability estimate has not reached the agreed checkpoints")
        dimensions = data.get("dimensions", {})
        require(set(dimensions) == {"completion", "navigation", "financial_clarity", "recovery", "accessibility"}
                and all(value == 2 for value in dimensions.values()), "Usability dimensions must each pass")
    elif kind == "offsite_recovery":
        require(data.get("simulated") is False, "A simulated recovery cannot satisfy the offsite gate")
        host = data.get("recovery_host_fingerprint")
        require(isinstance(host, str) and re.fullmatch(r"[a-f0-9]{64}", host)
                and host != production_fingerprint, "Offsite recovery requires an independent host")
        for key in ("encrypted", "download_checksum_verified", "decrypted", "database_restored",
                    "objects_restored", "configuration_restored", "application_ready",
                    "source_images_verified", "counts_compared"):
            require(data.get(key) is True, "Offsite restore proof is incomplete: " + key)
        captured = timestamp(data.get("captured_at_utc"))
        require(0 <= (now - captured).total_seconds() <= 86400, "Offsite recovery exceeds the 24-hour RPO")
        started, completed = timestamp(data.get("started_at_utc")), timestamp(data.get("completed_at_utc"))
        require(0 <= (completed - started).total_seconds() <= 14400 and completed <= now,
                "Offsite recovery exceeds the four-hour RTO")
    elif kind == "alerts":
        require(data.get("simulated") is False and data.get("protocol") == "http_json"
                and data.get("failure_acknowledged") is True
                and data.get("recovery_acknowledged") is True and data.get("external_watchdog") is True,
                "Real incident/recovery alert acknowledgment is required")
    elif kind == "rollback":
        require(data.get("isolated") is True and data.get("schema_compatible") is True
                and data.get("preserves_new_writes") is True and data.get("database_downgraded") is False,
                "Rollback compatibility and preservation have not been tested")


def validate_bundle(path, *, revision, api_image, web_image, reader, now=None,
                    production_fingerprint=None):
    """Load checksum-bound private artifacts; return only non-sensitive outcomes."""
    now = now or datetime.now(timezone.utc)
    production_fingerprint = production_fingerprint or local_machine_fingerprint()
    try:
        bundle = json.loads(reader(Path(path)))
        require(bundle.get("format") == "volt-quality-bundle-v1", "Quality bundle format is unsupported")
        require(bundle.get("revision") == revision and bundle.get("images") == {"api": api_image, "web": web_image},
                "Quality bundle differs from the release revision/images")
        age = (now - timestamp(bundle.get("created_at_utc"))).total_seconds()
        require(0 <= age <= 86400, "Quality bundle is stale")
        checks = bundle.get("checks", {})
        require(set(checks) == set(REQUIRED), "All mandatory release quality checks are required")
        outcomes = {}
        for kind in REQUIRED:
            reference = checks[kind]
            artifact_path = Path(reference["path"])
            require(artifact_path.is_absolute(), "Quality artifact paths must be absolute")
            raw = reader(artifact_path)
            require(hashlib.sha256(raw).hexdigest() == reference.get("sha256"),
                    "Quality artifact checksum mismatch: " + kind)
            data = json.loads(raw)
            require(data.get("revision") == revision and data.get("images") == bundle["images"],
                    "Quality artifact differs from release revision/images: " + kind)
            artifact_age = (now - timestamp(data.get("verified_at_utc"))).total_seconds()
            require(0 <= artifact_age <= 86400, "Quality artifact is stale: " + kind)
            validate_check(kind, data, now, production_fingerprint)
            outcomes[kind] = {"passed": True, "artifact_sha256": reference["sha256"]}
        return {"passed": True, "revision": revision, "checks": outcomes,
                "policy": {"read_write_p95_ms": 2000, "business_errors_max": .01,
                           "checks_min": .99, "max_vus": 25, "soak_seconds": 900,
                           "rpo_hours": 24, "rto_hours": 4}}
    except QualityError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise QualityError("Quality evidence is missing or malformed") from None
