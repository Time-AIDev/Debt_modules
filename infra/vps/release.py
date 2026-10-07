#!/usr/bin/env python3
"""Promote pinned VPS images after backup, readiness and public HTTPS checks.

Run as root. Diagnostics and rollback configuration are private; credentials are
never copied into the release evidence or printed. No schema downgrade or database
restore is attempted automatically. --check performs preflight checks only.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_evidence import verified_offsite
from quality_evidence import QualityError, validate_bundle

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path("/etc/volt-debt")
BACKUPS = Path("/srv/volt-debt-backups")
HISTORY = Path("/srv/volt-debt-release-history")
LOCK = Path("/run/volt-debt-backup.lock")
DOMAIN = "collection.volt.co.th"
PUBLIC_IP = "143.198.207.143"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


class ReleaseError(RuntimeError):
    """A public-safe description; raw command diagnostics stay in a private file."""


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ReleaseError("Timestamp must include its timezone")
    return parsed.astimezone(timezone.utc)


def rollback_image_for_schema(actual, previous_image, previous_schema, compatible_image, compatible_schema):
    if actual == previous_schema:
        return previous_image
    if compatible_image and actual == compatible_schema:
        return compatible_image
    raise ReleaseError("No schema-compatible rollback image is available; maintenance remains enabled")


def ensure_directory(path, *, private=False, create=False):
    path = Path(path)
    if not path.is_absolute():
        raise ReleaseError("Paths must be absolute")
    if create and not path.exists():
        ensure_directory(path.parent, create=True)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    if not path.is_dir() or path.is_symlink() or path.resolve() != path:
        raise ReleaseError("Directory is missing or contains a symlink")
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ReleaseError("Directory must be root owned and protected from other writers")
    if private and info.st_mode & 0o077:
        raise ReleaseError("Configuration directory must be root only")
    return path


def read_private(path, *, max_bytes=1048576):
    path = Path(path)
    ensure_directory(path.parent, private=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ReleaseError("Private file must be a root-only regular file")
        data = file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ReleaseError("Private metadata exceeds the permitted size")
        return data


def atomic_write(path, data):
    path = Path(path)
    ensure_directory(path.parent)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            raise ReleaseError("Refusing to replace an unsafe output file")
    descriptor, temporary = tempfile.mkstemp(prefix=".volt-release-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            os.fchmod(file.fileno(), 0o600)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())


def update_env(original, updates):
    """Replace only named nonsecret assignments; preserve all other bytes/lines.

    Do not source dotenv as shell code or decode/re-encode allowlist JSON, OAuth
    configuration, integration keys or database passwords.
    """
    lines, seen, quote = [], set(), None

    def open_quote(value, current=None):
        value = value.lstrip() if current is None else value
        start = 0
        if current is None:
            if not value or value[0] not in ("'", '"'):
                return None
            current, start = value[0], 1
        escaped = False
        for character in value[start:]:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == current:
                return None
        return current

    for line in original.decode("utf-8").splitlines(keepends=True):
        if quote:
            lines.append(line)
            quote = open_quote(line, quote)
            continue
        match = ASSIGNMENT.match(line)
        key = match.group(1) if match else None
        if key in updates:
            lines.append(key + "=" + updates[key] + "\n")
            seen.add(key)
        else:
            lines.append(line)
            if match:
                quote = open_quote(line[match.end():])
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += "\n"
    lines.extend(key + "=" + value + "\n" for key, value in updates.items() if key not in seen)
    return "".join(lines).encode("utf-8")


def assignment_value(raw, key):
    found = None
    for line in raw.decode("utf-8").splitlines():
        match = ASSIGNMENT.match(line)
        if match and match.group(1) == key:
            found = line[match.end():].strip().strip("\"'")
    return found


def production_defaults():
    spec = importlib.util.spec_from_file_location("volt_release_policy", ROOT / "backend/app/runtime_policy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.environment_defaults("production", "shared"), module.SCHEMA_VERSION


@contextmanager
def backup_lock():
    descriptor = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ReleaseError("Unsafe backup/deployment lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReleaseError("A backup or another release holds the deployment lock") from None
        yield
    finally:
        os.close(descriptor)


class Release:
    def __init__(self, args):
        self.args = args
        self.log = None
        self.private = None
        self.stage = "preflight"
        self.mutated = False
        self.stack = self.api_env = None
        self.previous = {}
        self.migrate_name = "volt-debt-release-migrate-" + uuid.uuid4().hex[:12]
        self.evidence = {"format": "volt-debt-release-v1", "status": "running",
                         "started_at_utc": utc_now().isoformat(), "domain": DOMAIN,
                         "requested_revision": args.revision,
                         "requested_images": {"api": args.api_image, "web": args.web_image},
                         "requested_go_live": args.go_live, "go_live_enabled": False,
                         "checks": {}, "remaining_risks": [
                             "Single VPS; regional/high availability not established",
                             "External Google sign-in and OAuth Authorized JavaScript origin not verified by this CLI",
                             "Remote Git push is not independently verified by this CLI"]}

    def run_command(self, command, *, capture=False, timeout=180, cwd=None, check=True):
        # Compose interpolation must come only from stack.env, never similarly
        # named shell variables or an accidental remote Docker context.
        environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8",
                       "HOME": os.environ.get("HOME", "/root"),
                       "DOCKER_HOST": "unix:///var/run/docker.sock"}
        try:
            result = subprocess.run(command, cwd=cwd or ROOT, env=environment,
                                    stdout=subprocess.PIPE if capture else self.log,
                                    stderr=subprocess.PIPE, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise ReleaseError("Command timed out during " + self.stage) from None
        if self.log and result.stderr:
            self.log.write(result.stderr)
            self.log.flush()
        if check and result.returncode:
            raise ReleaseError("Command failed during " + self.stage + "; see private diagnostics")
        return result

    def compose(self, *arguments, timeout=240):
        return self.run_command(["docker", "compose", "--project-name", "volt-debt",
                                 "--env-file", str(CONFIG / "stack.env"),
                                 "--file", str(ROOT / "infra/vps/compose.yaml"),
                                 "--profile", "candidate", "--profile", "public", *arguments], timeout=timeout)

    def checkpoint(self):
        self.evidence["stage"] = self.stage
        write_json(self.args.evidence, self.evidence)
        if self.private:
            write_json(self.private / "release-evidence.json", self.evidence)

    def inspect_image(self, image):
        data = json.loads(self.run_command(["docker", "image", "inspect", image], capture=True, timeout=30).stdout)
        if len(data) != 1 or data[0].get("Id") != image:
            raise ReleaseError("Pinned image is unavailable locally or its digest differs")
        labels = (data[0].get("Config") or {}).get("Labels") or {}
        return {"id": data[0]["Id"], "repo_digests": data[0].get("RepoDigests") or [],
                "revision_label": labels.get("org.opencontainers.image.revision")}

    def current_containers(self):
        result = {}
        for service in ("api", "worker", "web", "db", "scanner", "edge"):
            ids = self.run_command([
                "docker", "ps", "--all", "--quiet", "--no-trunc",
                "--filter", "label=com.docker.compose.project=volt-debt",
                "--filter", "label=com.docker.compose.service=" + service], capture=True, timeout=30).stdout.decode().split()
            if len(ids) != 1:
                raise ReleaseError("Expected exactly one production container for " + service)
            info = json.loads(self.run_command(["docker", "inspect", ids[0]], capture=True, timeout=30).stdout)[0]
            state = info["State"]
            if not state.get("Running") or state.get("OOMKilled"):
                raise ReleaseError("Existing production service is stopped or OOM killed: " + service)
            environment = dict(item.split("=", 1) for item in info["Config"].get("Env", []) if "=" in item)
            result[service] = {"container_id": ids[0], "image_id": info["Image"],
                               "health": state.get("Health", {}).get("Status", "not-configured"),
                               "go_live_enabled": environment.get("PROD_GO_LIVE_ENABLED") == "true"}
        if result["api"]["image_id"] != result["worker"]["image_id"]:
            raise ReleaseError("API and worker image digests differ; review rollback explicitly")
        return result

    def source_evidence(self):
        revision = self.run_command(["git", "rev-parse", "HEAD"], capture=True, timeout=30).stdout.decode().strip()
        if revision != self.args.revision:
            raise ReleaseError("Requested revision differs from the local Git checkout")
        runtime_paths = ("backend", "frontend", "infra", "scripts", "tests/load",
                         ".dockerignore", ".gitignore", "README.md", "docs/odoo-comparison")
        for arguments in (("diff", "--quiet", "--", *runtime_paths),
                          ("diff", "--cached", "--quiet", "--", *runtime_paths)):
            if self.run_command(["git", *arguments], check=False, capture=True, timeout=30).returncode:
                raise ReleaseError("Tracked source changes must be committed before release")
        untracked = self.run_command(["git", "ls-files", "--others", "--exclude-standard", "-z"],
                                     capture=True, timeout=30).stdout.split(b"\0")
        if any(path.startswith((b"backend/", b"frontend/", b"infra/", b"scripts/")) for path in untracked if path):
            raise ReleaseError("Untracked application or deployment source must be committed before release")
        files = self.run_command(["git", "ls-files", "-z"], capture=True, timeout=30).stdout.split(b"\0")
        digest = hashlib.sha256()
        for raw in sorted(path for path in files if path and not path.startswith(b"reports/")):
            name = os.fsdecode(raw)
            path = ROOT / name
            if not path.is_relative_to(ROOT) or ".." in Path(name).parts:
                raise ReleaseError("Unexpected tracked source path")
            digest.update(raw + b"\0")
            if path.is_symlink():
                digest.update(b"symlink\0" + os.fsencode(os.readlink(path)))
            else:
                with path.open("rb") as file:
                    digest.update(hashlib.file_digest(file, "sha256").digest())
            digest.update(b"\0")
        upstream = self.run_command(["git", "rev-parse", "@{upstream}"], capture=True, check=False, timeout=30)
        return {"commit": revision, "tracked_source_sha256": digest.hexdigest(), "tracked_worktree_clean": True,
                "remote_tracking_available": upstream.returncode == 0,
                "remote_tracking_matches_commit": upstream.returncode == 0 and upstream.stdout.decode().strip() == revision,
                "remote_push_verified": False}

    def verified_backup(self):
        ensure_directory(BACKUPS, private=True)
        candidates = []
        for backup in BACKUPS.iterdir():
            if backup.name.startswith(".") or not backup.is_dir() or backup.is_symlink():
                continue
            try:
                completed = timestamp(read_private(backup / "COMPLETE", max_bytes=256).decode())
                restore = json.loads(read_private(backup / "restore-evidence.json"))
                age = utc_now() - completed
                if age < timedelta(minutes=-5) or age > timedelta(hours=26):
                    continue
                if restore.get("status") != "passed" or restore.get("counts_compared_with_backup") is not True:
                    continue
                restored = timestamp(restore["completed_at_utc"])
                if restored < completed or restored > utc_now() + timedelta(minutes=5):
                    continue
                if read_private(backup / "BACKUP_FORMAT", max_bytes=256).decode().strip() != "volt-debt-backup-v1":
                    continue
                candidates.append((completed, backup, restore))
            except (OSError, ValueError, KeyError, ReleaseError):
                continue
        if not candidates:
            raise ReleaseError("A completed backup from the last 26 hours with a passed restore drill is required")
        completed, backup, restore = max(candidates, key=lambda item: item[0])
        self.run_command(["sha256sum", "--check", "--status", "SHA256SUMS"], cwd=backup, timeout=180)
        offsite = None
        try:
            possible = json.loads(read_private(backup / "offsite-evidence.json"))
            if verified_offsite(backup, possible):
                offsite = {key: possible.get(key) for key in ("status", "sha256", "verified_at_utc", "encrypted")}
        except (OSError, ValueError, ReleaseError):
            pass
        if not offsite:
            self.evidence["remaining_risks"].append("No verified encrypted off-server copy found for the selected backup")
        return {"directory": str(backup), "completed_at_utc": completed.isoformat(),
                "restore_status": "passed", "restore_completed_at_utc": restore["completed_at_utc"],
                "counts_compared": True, "object_files": restore.get("object_files"),
                "object_bytes": restore.get("object_bytes"), "offsite": offsite}

    def http(self, url, *, expected=200, json_body=False, hsts=False):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        try:
            response = opener.open(urllib.request.Request(url, headers={"Accept": "application/json" if json_body else "*/*"}), timeout=10)
        except urllib.error.HTTPError as exc:
            if exc.code != expected:
                raise ReleaseError("HTTP verification failed: " + url) from None
            response = exc
        except (OSError, urllib.error.URLError):
            raise ReleaseError("Trusted connection verification failed: " + url) from None
        with response:
            if response.status != expected or response.geturl() != url:
                raise ReleaseError("Unexpected response or redirect: " + url)
            body = response.read(16385)
            if len(body) > 16384:
                raise ReleaseError("HTTP verification response exceeds its limit")
            policy = response.headers.get("Strict-Transport-Security", "")
            match = re.search(r"(?:^|;)\s*max-age\s*=\s*(\d+)", policy, re.I)
            if hsts and (not match or int(match.group(1)) == 0):
                raise ReleaseError("HSTS missing from public HTTPS response")
            if json_body:
                allowed_types = ("application/json", "application/problem+json") if expected >= 400 else ("application/json",)
                if response.headers.get_content_type() not in allowed_types:
                    raise ReleaseError("Endpoint returned a non-JSON response: " + url)
                try:
                    data = json.loads(body)
                except ValueError:
                    raise ReleaseError("Endpoint returned malformed JSON: " + url) from None
                if not isinstance(data, dict):
                    raise ReleaseError("Unexpected JSON response shape: " + url)
            else:
                data = None
            return {"url": url, "status": response.status, "tls_verified": url.startswith("https://"),
                    "hsts": bool(match and int(match.group(1)) > 0)}, data

    def public_dns(self):
        try:
            addresses = sorted({row[4][0] for row in socket.getaddrinfo(DOMAIN, 443, type=socket.SOCK_STREAM)})
        except OSError:
            raise ReleaseError("Production DNS does not resolve") from None
        if addresses != [PUBLIC_IP]:
            raise ReleaseError("Production DNS must resolve only to the authorized VPS address")
        return {"addresses": addresses, "expected_address": PUBLIC_IP, "passed": True}

    def verify(self, *, public=True):
        checks = {}
        check, ready = self.http("http://127.0.0.1:8081/readyz", json_body=True)
        if ready.get("status") != "ready":
            raise ReleaseError("Internal readiness JSON did not report ready")
        checks["internal_ready"] = check
        checks["internal_web"], _ = self.http("http://127.0.0.1:8080/healthz")
        check, config = self.http("http://127.0.0.1:8081/api/v1/auth/config", json_body=True)
        if config.get("mode") != "on" or config.get("password_enabled") is not False or not config.get("google_client_id"):
            raise ReleaseError("Production authentication configuration failed verification")
        checks["auth_configuration"] = dict(check, mode="on", password_enabled=False, google_client_id_configured=True)
        checks["unauthenticated_me"], _ = self.http("http://127.0.0.1:8081/api/v1/auth/me", expected=401, json_body=True)
        if public:
            checks["dns"] = self.public_dns()
            for label, path in (("public_ready", "/readyz"), ("public_api_ready", "/api/readyz")):
                check, ready = self.http("https://" + DOMAIN + path, json_body=True, hsts=True)
                if ready.get("status") != "ready":
                    raise ReleaseError("Public readiness JSON did not report ready")
                checks[label] = check
            check, config = self.http("https://" + DOMAIN + "/api/v1/auth/config", json_body=True, hsts=True)
            if config.get("mode") != "on" or config.get("password_enabled") is not False or not config.get("google_client_id"):
                raise ReleaseError("Public production authentication configuration failed verification")
            checks["public_auth_configuration"] = dict(check, mode="on", password_enabled=False)
            checks["public_unauthenticated_me"], _ = self.http(
                "https://" + DOMAIN + "/api/v1/auth/me", expected=401, json_body=True, hsts=True)
            checks["public_web"], _ = self.http("https://" + DOMAIN + "/", hsts=True)
        return checks

    def verify_browser_origin(self):
        path = getattr(self.args,"browser_evidence",None) or ROOT/"reports/production-20261006/browser-final.json"
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size>1048576:
            raise ReleaseError("Recent browser OAuth-origin evidence is required before go-live")
        data = json.loads(path.read_text())
        if (data.get("target") != "https://"+DOMAIN or data.get("status") != 200 or
            data.get("google_origin_denied") is not False or data.get("page_error_count") != 0 or
            data.get("failed_requests") != [] or data.get("browser_login_performed") is not True or
            data.get("authenticated_google_session") is not True or
            data.get("authenticated_session_kind") != "GOOGLE" or
            data.get("revision") != self.args.revision):
            raise ReleaseError("Successful real Google browser authentication for this revision is required; maintenance remains enabled")
        age=(utc_now()-timestamp(data["timestamp"])).total_seconds()
        if not 0 <= age <= 3600:
            raise ReleaseError("Browser OAuth-origin evidence is stale")
        self.evidence["checks"]["browser_origin"]={"passed":True,"human_login_performed":True,
                                                   "authenticated_google_session":True,
                                                   "revision":self.args.revision}

    def preflight(self):
        ensure_directory(CONFIG, private=True)
        self.stack = read_private(CONFIG / "stack.env")
        self.api_env = read_private(CONFIG / "api.env")
        for key in ("GOOGLE_CLIENT_ID", "AUTH_ALLOWLIST", "DATABASE_URL"):
            if not assignment_value(self.api_env, key):
                raise ReleaseError("Existing production configuration requires " + key)
        if assignment_value(self.api_env, "VOLT_BUSINESS_DATE"):
            raise ReleaseError("Production refuses a pinned business date")
        self.evidence["source"] = self.source_evidence()
        self.evidence["backup"] = self.verified_backup()
        self.evidence["candidate_images"] = {"api": self.inspect_image(self.args.api_image),
                                             "web": self.inspect_image(self.args.web_image)}
        for image in self.evidence["candidate_images"].values():
            if image["revision_label"] != self.args.revision:
                raise ReleaseError("Candidate images require an exact requested Git revision label")
        infrastructure = {}
        for service in ("db", "scanner", "edge"):
            image = getattr(self.args, service + "_image", None)
            if image:
                infrastructure[service] = self.inspect_image(image)
                if service == "db":
                    info = json.loads(self.run_command(["docker", "image", "inspect", image], capture=True, timeout=30).stdout)[0]
                    if "PG_MAJOR=16" not in (info.get("Config") or {}).get("Env", []):
                        raise ReleaseError("Database security update must preserve PostgreSQL major16")
        self.evidence["infrastructure_images"] = infrastructure
        if self.args.rollback_api_image:
            self.evidence["rollback_compatible_image"] = self.inspect_image(self.args.rollback_api_image)
        self.previous = self.current_containers()
        self.evidence["previous_containers"] = self.previous
        # Preflight deliberately verifies the actual public hostname, without a
        # Host-header/TLS-name workaround. Google OAuth UI remains unverified.
        preflight = self.verify(public=False)
        preflight["dns"] = self.public_dns()
        preflight["public_transport"], _ = self.http("https://" + DOMAIN + "/")
        self.evidence["checks"]["preflight"] = preflight
        self.defaults, schema_version = production_defaults()
        candidate_schema = self.image_schema_version(self.args.api_image)
        previous_schema = self.image_schema_version(self.previous["api"]["image_id"])
        self.evidence["previous_api_schema_version"] = previous_schema
        self.evidence["candidate_api_schema_version"] = candidate_schema
        if candidate_schema != schema_version:
            raise ReleaseError("Candidate API schema differs from the shared runtime policy")
        if self.args.rollback_api_image:
            self.evidence["rollback_api_schema_version"] = self.image_schema_version(self.args.rollback_api_image)
        if previous_schema != schema_version and self.evidence.get("rollback_api_schema_version") != schema_version:
            raise ReleaseError("A schema-compatible fallback API image is required before this migration")
        self.evidence["expected_schema_version"] = schema_version
        self.checkpoint()

    def verify_quality(self):
        path = getattr(self.args, "quality_evidence", None)
        if path is None:
            raise ReleaseError("All release quality evidence is required before go-live")
        try:
            outcome = validate_bundle(path, revision=self.args.revision,
                                      api_image=self.args.api_image, web_image=self.args.web_image,
                                      defer_offsite_recovery=getattr(self.args, "defer_offsite_recovery", False),
                                      reader=lambda file: read_private(file, max_bytes=16 * 1024 * 1024))
        except QualityError as exc:
            raise ReleaseError(str(exc)) from None
        self.evidence["checks"]["quality"] = outcome
        if outcome.get("deferred"):
            self.evidence["remaining_risks"].append("Offsite backup/recovery deferred by explicit user request; external RPO/RTO unverified")

    def image_schema_version(self, image):
        result = self.run_command(["docker", "run", "--rm", "--network", "none", "--read-only",
                                   "--memory", "64m", "--entrypoint", "python", image, "-c",
                                   "from app.runtime_policy import SCHEMA_VERSION; print(SCHEMA_VERSION)"],
                                  capture=True, timeout=30)
        try:
            return int(result.stdout.decode().strip())
        except (ValueError, UnicodeDecodeError):
            raise ReleaseError("API image did not report a supported schema version") from None

    def actual_schema_version(self):
        result = self.run_command(["docker", "exec", "volt-debt-db-1", "sh", "-c",
                                  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -At -v ON_ERROR_STOP=1 '
                                  '-c "select version from app.schema_version where singleton=true"'],
                                  capture=True, timeout=30)
        try:
            return int(result.stdout.decode().strip())
        except (ValueError, UnicodeDecodeError):
            raise ReleaseError("Database schema could not be verified for rollback") from None

    def up(self, *services):
        self.compose("up", "--detach", "--no-deps", "--force-recreate", "--pull", "never",
                     "--wait", "--wait-timeout", "180", *services)

    def rollback(self):
        self.stage = "rollback"
        self.evidence["go_live_enabled"] = False
        self.checkpoint()
        # A timed-out CLI must not leave its migration writing beside rollback.
        self.run_command(["docker", "stop", "--time", "30", self.migrate_name], timeout=45, check=False)
        self.compose("stop", "--timeout", "60", "api", "worker", timeout=90)
        previous_image = self.previous["api"]["image_id"]
        previous_schema = self.evidence.get("previous_api_schema_version")
        compatible_schema = self.evidence.get("rollback_api_schema_version")
        rollback_image = rollback_image_for_schema(self.actual_schema_version(), previous_image, previous_schema,
                                                  self.args.rollback_api_image, compatible_schema)
        atomic_write(CONFIG / "api.env", update_env(self.api_env, {"PROD_GO_LIVE_ENABLED": "false",
                                                                "VOLT_INDEXED_READS_ENABLED": "false",
                                                                "VOLT_CUSTOMER_SCOPES_ENABLED": "false"}))
        rollback_updates = {"API_IMAGE": rollback_image, "WEB_IMAGE": self.previous["web"]["image_id"]}
        for service,key in (("db","POSTGRES_IMAGE"),("scanner","SCANNER_IMAGE"),("edge","EDGE_IMAGE")):
            rollback_updates[key] = self.previous[service]["image_id"]
        atomic_write(CONFIG / "stack.env", update_env(self.stack, rollback_updates))
        dependencies = [service for service in ("db", "scanner") if getattr(self.args, service + "_image", None)]
        if dependencies:
            self.compose("up", "-d", "--no-deps", "--pull", "never", "--wait", "--wait-timeout", "240", *dependencies, timeout=300)
        self.up("api", "worker", "web", "edge")
        checks = self.verify(public=False)
        containers = self.current_containers()
        if containers["api"]["image_id"] != rollback_image or containers["web"]["image_id"] != self.previous["web"]["image_id"]:
            raise ReleaseError("Rollback image verification failed")
        if containers["api"]["go_live_enabled"] or containers["worker"]["go_live_enabled"]:
            raise ReleaseError("Rollback maintenance gate verification failed")
        self.evidence["rollback"] = {"status": "passed", "api_image": rollback_image,
                                     "web_image": containers["web"]["image_id"],
                                     "maintenance_enabled": True, "schema_downgraded": False,
                                     "checks": checks, "containers": containers}

    def deploy(self):
        self.preflight()
        if self.args.go_live:
            # Missing quality proof must not stop writers or mutate configuration.
            self.verify_quality()
            self.verify_browser_origin()
        if self.args.check:
            self.evidence["status"] = "preflight_passed"
            return
        ensure_directory(HISTORY, private=True, create=True)
        self.private = HISTORY / (utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
        ensure_directory(self.private, private=True, create=True)
        atomic_write(self.private / "stack.env", self.stack)
        atomic_write(self.private / "api.env", self.api_env)
        write_json(self.private / "previous-images.json", self.previous)
        self.evidence["rollback_directory"] = str(self.private)
        self.log = (self.private / "diagnostics.log").open("ab")
        self.checkpoint()
        self.stage = "maintenance_and_migration"
        self.mutated = True
        atomic_write(CONFIG / "api.env", update_env(self.api_env, self.defaults))
        image_updates = {"API_IMAGE": self.args.api_image, "WEB_IMAGE": self.args.web_image}
        for service, key in (("db", "POSTGRES_IMAGE"), ("scanner", "SCANNER_IMAGE"), ("edge", "EDGE_IMAGE")):
            image = getattr(self.args, service + "_image", None)
            if image: image_updates[key] = image
        atomic_write(CONFIG / "stack.env", update_env(self.stack, image_updates))
        self.checkpoint()
        self.compose("stop", "--timeout", "60", "api", "worker", timeout=90)
        dependencies = [service for service in ("db", "scanner") if getattr(self.args, service + "_image", None)]
        if dependencies:
            self.compose("up", "-d", "--no-deps", "--pull", "never", "--wait", "--wait-timeout", "240",
                         *dependencies, timeout=300)
        self.compose("--profile", "setup", "run", "--rm", "--no-deps", "--pull", "never",
                     "--name", self.migrate_name, "migrate", timeout=600)
        self.stage = "candidate"
        self.checkpoint()
        self.up("api", "worker", "web", "edge")
        self.compose("--profile", "public", "exec", "-T", "edge", "caddy", "validate",
                     "--config", "/etc/caddy/Caddyfile", timeout=30)
        containers = self.current_containers()
        if containers["api"]["image_id"] != self.args.api_image or containers["worker"]["image_id"] != self.args.api_image or containers["web"]["image_id"] != self.args.web_image:
            raise ReleaseError("Running candidate image digests differ from requested images")
        if containers["api"]["go_live_enabled"] or containers["worker"]["go_live_enabled"]:
            raise ReleaseError("Candidate unexpectedly opened the maintenance gate")
        for attempt in range(15):
            try:
                self.evidence["checks"]["candidate"] = self.verify()
                break
            except ReleaseError:
                if attempt == 14: raise
                time.sleep(1)
        self.evidence["actual_containers"] = containers
        if self.args.go_live:
            self.verify_browser_origin()
            self.stage = "go_live"
            self.checkpoint()
            current = read_private(CONFIG / "api.env")
            atomic_write(CONFIG / "api.env", update_env(current, {"PROD_GO_LIVE_ENABLED": "true"}))
            self.up("api", "worker")
            self.evidence["checks"]["go_live"] = self.verify()
            containers = self.current_containers()
            if not containers["api"]["go_live_enabled"] or not containers["worker"]["go_live_enabled"]:
                raise ReleaseError("Running services did not enable the authorized go-live gate")
            self.evidence["actual_containers"] = containers
            self.evidence["go_live_enabled"] = True
        self.evidence["status"] = "go_live_verified" if self.args.go_live else "candidate_verified"


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--db-image")
    parser.add_argument("--scanner-image")
    parser.add_argument("--edge-image")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--rollback-api-image")
    parser.add_argument("--browser-evidence", type=Path)
    parser.add_argument("--quality-evidence", type=Path)
    parser.add_argument("--defer-offsite-recovery", action="store_true",
                        help="Allow only an explicit, exact-candidate offsite recovery deferral; all other gates remain required")
    parser.add_argument("--go-live", action="store_true")
    parser.add_argument("--check", action="store_true", help="Verify preflight without changing production configuration or containers")
    args = parser.parse_args(argv)
    for value in (args.api_image, args.web_image, args.rollback_api_image, args.db_image, args.scanner_image, args.edge_image):
        if value is not None and not DIGEST.fullmatch(value):
            parser.error("Images must be pinned local sha256:<64 lowercase hex> IDs")
    if not REVISION.fullmatch(args.revision):
        parser.error("Revision must be a complete lowercase Git commit hash")
    if not args.evidence.is_absolute() or args.evidence.suffix != ".json":
        parser.error("Evidence must be an absolute .json path")
    if args.check and args.go_live:
        parser.error("--check and --go-live cannot be combined")
    return args


def main(argv=None):
    args = arguments(argv)
    if os.geteuid() != 0:
        raise SystemExit("Run as root")
    os.umask(0o077)
    ensure_directory(args.evidence.parent, create=True)
    release = Release(args)
    old_handlers = {}

    def interrupted(number, _frame):
        raise ReleaseError("Release interrupted by signal " + str(number))

    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        old_handlers[number] = signal.signal(number, interrupted)
    code = 0
    try:
        with backup_lock():
            try:
                release.deploy()
            except BaseException as exc:
                code = 1
                release.evidence["status"] = "failed"
                release.evidence["failed_stage"] = release.stage
                release.evidence["error"] = str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
                if release.mutated:
                    try:
                        release.rollback()
                    except BaseException as rollback_error:
                        release.evidence["rollback"] = {"status": "failed", "schema_downgraded": False,
                                                         "error": str(rollback_error) if isinstance(rollback_error, ReleaseError)
                                                         else type(rollback_error).__name__,
                                                         "manual_recovery_required": True}
            finally:
                release.evidence["completed_at_utc"] = utc_now().isoformat()
                release.checkpoint()
    except ReleaseError as exc:
        code = 1
        release.evidence.update(status="failed", error=str(exc), completed_at_utc=utc_now().isoformat())
        release.checkpoint()
    finally:
        if release.log:
            release.log.close()
        for number, handler in old_handlers.items():
            signal.signal(number, handler)
    print("Release " + release.evidence["status"] + "; evidence: " + str(args.evidence))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
