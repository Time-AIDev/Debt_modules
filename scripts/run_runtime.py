#!/usr/bin/env python3
"""Run an isolated dev/staging stack with the production application artifacts.

Example: scripts/run_runtime.py staging up --generate-test-account
Credentials are generated only by explicit flag and written to a private file.
Ports bind loopback; no command changes the production Compose project or volumes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.runtime_policy import environment_defaults

COMPOSE = ROOT / "infra/runtime/compose.yaml"
POSTGRES_IMAGE = "postgres@sha256:1a6ab3f5345eb6dbe04a1349529caabdb0ab09293a09590fad07b2246bfa4b54"
SCANNER_IMAGE = "clamav/clamav@sha256:ebec5bc138401b36ae987caa1a3fa3c3b2a21ed3d51f0bfa5852825e663e67b0"
PINNED = re.compile(r"(?:sha256:[a-f0-9]{64}|[^\s]+@sha256:[a-f0-9]{64})\Z")
LOCKED = {"ENV", "DEPLOYMENT_ENV", "VOLT_SHARED_STATE_ENABLED", "AUTH_MODE", "DATABASE_URL",
          "AUTH_SESSION_POLICY", "OBJECT_STORAGE_BACKEND", "OBJECT_STORAGE_ROOT", "TASK_QUEUE_BACKEND",
          "CLAMAV_HOST", "CLAMAV_PORT", "REQUIRE_DEPENDENCY_READINESS", "PEAK_OUTBOUND_ENABLED"}
BUILD_SOURCE_PATHS = ("backend/app", "frontend", "infra/production/Dockerfile.api",
                      "infra/production/requirements.lock", "scripts/import_master_sheet.py",
                      "docs/odoo-comparison/odoo_compare.md", ".dockerignore")


def run(command, capture=False):
    return subprocess.run(command, cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def private_write(path, content):
    path = Path(path)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Runtime settings must not be symlinks")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Invalid dotenv syntax; use plain KEY=value lines")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def dotenv(values):
    # Docker dotenv uses single quoting to suppress interpolation of password
    # hashes containing '$'. Never source generated settings as shell code.
    result = []
    for key, value in values.items():
        value = str(value)
        if any(char in value for char in ("\n", "\r", "\x00", "'")):
            raise ValueError("Runtime setting cannot be represented safely")
        result.append(key + "='" + value + "'\n")
    return "".join(result)


def _local_password_hash(password):
    # The backend's check_password contract is covered by the parity regression.
    salt = secrets.token_hex(16)
    rounds = 600000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode("ascii"), rounds).hex()
    return "pbkdf2_sha256$%s$%s$%s" % (rounds, salt, digest)


def configure(environment, directory, supplied=None, generate_test_account=False):
    directory = Path(directory)
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError("Private runtime directory must not be a symlink")
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    credentials_file = directory / "credentials.json"
    if credentials_file.is_symlink():
        raise ValueError("Private credentials must not be a symlink")
    credentials = json.loads(credentials_file.read_text()) if credentials_file.exists() else {
        "database_password": secrets.token_hex(24), "auth_session_secret": secrets.token_urlsafe(48),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    values = environment_defaults(environment, "shared")
    supplied = supplied or {}
    if any(key in LOCKED and supplied[key] != values.get(key) for key in supplied):
        raise ValueError("Supplied settings must not override isolated shared-state wiring")
    values.update(supplied)
    if generate_test_account:
        credentials.setdefault("username", "owner.test")
        credentials.setdefault("password", secrets.token_urlsafe(18))
        values["AUTH_TEST_ACCOUNTS"] = json.dumps({credentials["username"]: {
            "hash": _local_password_hash(credentials["password"]), "role": "OWNER", "officer": "owner"
        }}, separators=(",", ":"))
        values["AUTH_ALLOW_TEST_ACCOUNTS"] = "true"
        # Also makes the identity registry independent of whether the local book
        # is empty; this address is never a production account.
        allowlist = json.loads(values.get("AUTH_ALLOWLIST", "{}"))
        allowlist.setdefault("owner.runtime@example.invalid", {"role": "OWNER", "officer": "owner"})
        values["AUTH_ALLOWLIST"] = json.dumps(allowlist, separators=(",", ":"))
    elif not ((values.get("GOOGLE_CLIENT_ID") and values.get("AUTH_ALLOWLIST")) or
              (values.get("AUTH_TEST_ACCOUNTS") and values.get("AUTH_ALLOW_TEST_ACCOUNTS") == "true")):
        raise ValueError("Supply Google login settings or explicitly --generate-test-account")
    values.update(DATABASE_URL="postgresql+psycopg://debt_local:" + credentials["database_password"] + "@db/debt",
                  AUTH_SESSION_SECRET=values.get("AUTH_SESSION_SECRET", credentials["auth_session_secret"]),
                  AUTH_COOKIE_SECURE="false", OBJECT_STORAGE_BACKEND="filesystem",
                  OBJECT_STORAGE_ROOT="/private-objects", UPLOADS_BUCKET="uploads", CLEAN_BUCKET="clean",
                  DOCS_BUCKET="documents", TASK_QUEUE_BACKEND="postgres", CLAMAV_HOST="scanner", CLAMAV_PORT="3310",
                  REQUIRE_DEPENDENCY_READINESS="true", PEAK_OUTBOUND_ENABLED="false")
    private_write(credentials_file, json.dumps(credentials, indent=2) + "\n")
    private_write(directory / "api.env", dotenv(values))
    return credentials, values


def proxy_config():
    base = (ROOT / "frontend/nginx.conf").read_text()
    location = """  # Same web image, private Docker API upstream on this isolated stack.
  location /api/ {
    proxy_pass http://api:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
  location = /readyz {
    proxy_pass http://api:8080/readyz;
  }
  location = /api/readyz {
    proxy_pass http://api:8080/readyz;
  }

"""
    if base.count("server {") != 1:
        raise ValueError("The shared nginx configuration has changed; review the API proxy")
    return base.replace("server {", "server {\n" + location, 1)


def source_fingerprint():
    digest = hashlib.sha256()
    sources = [ROOT / "backend/app", ROOT / "frontend", ROOT / "infra/production/Dockerfile.api",
               ROOT / "infra/production/requirements.lock", ROOT / "scripts/import_master_sheet.py",
               ROOT / "infra/vps/Dockerfile.db.no_xml", ROOT / "infra/vps/Dockerfile.scanner",
               ROOT / "scripts/check_elf_dependencies.py",
               ROOT / ".dockerignore",
               ROOT / "docs/odoo-comparison/odoo_compare.md"]
    ignored = {"node_modules", "dist", "__pycache__", ".vite"}
    files = []
    for source in sources:
        if source.is_file():
            files.append(source)
        else:
            for parent, dirs, names in os.walk(source):
                dirs[:] = [name for name in dirs if name not in ignored]
                files.extend(Path(parent) / name for name in names if not name.startswith(".env") and not name.endswith(".pyc"))
    for source in sorted(files):
        digest.update(str(source.relative_to(ROOT)).encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()[:16]


def images(args, build):
    if bool(args.api_image) != bool(args.web_image):
        raise ValueError("Supply both --api-image and --web-image from one tested release")
    if args.api_image:
        if not PINNED.fullmatch(args.api_image) or not PINNED.fullmatch(args.web_image):
            raise ValueError("Release images must use an immutable sha256 digest")
        return args.api_image, args.web_image
    revision = run(["git", "rev-parse", "HEAD"], capture=True).strip()
    if not re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", revision):
        raise ValueError("A committed Git revision is required for canonical runtime images")
    fingerprint = source_fingerprint()
    dirty = bool(run(["git", "status", "--porcelain", "--untracked-files=normal", "--", *BUILD_SOURCE_PATHS], capture=True).strip())
    # Local edits remain runnable, but cannot impersonate a committed artifact.
    # Production requires an exact commit label and therefore refuses this suffix.
    revision_label = revision + "-dirty-" + fingerprint if dirty else revision
    result = []
    for service, dockerfile, context in (("api", "infra/production/Dockerfile.api", "."),
                                        ("web", "frontend/Dockerfile", "frontend")):
        tag = "volt-debt-%s:runtime-%s-%s-%s" % (service, revision[:12], fingerprint, "dirty" if dirty else "clean")
        if not build:
            result.append(tag)
            continue
        format_value = '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
        found = subprocess.run(["docker", "image", "inspect", tag, "--format", format_value],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        fields = found.stdout.strip().split()
        if found.returncode or len(fields) != 2 or fields[1] != revision_label:
            run(["docker", "build", "--build-arg", "VOLT_GIT_REVISION=" + revision_label,
                 "--file", dockerfile, "--tag", tag, context])
            found = subprocess.run(["docker", "image", "inspect", tag, "--format", format_value],
                                   check=True, stdout=subprocess.PIPE, text=True)
            fields = found.stdout.strip().split()
        if len(fields) != 2 or fields[1] != revision_label or not re.fullmatch(r"sha256:[a-f0-9]{64}", fields[0]):
            raise ValueError("Canonical runtime image lacks the requested revision label")
        result.append(fields[0])
    return tuple(result)


def infrastructure_images(args, build):
    """Build the same patched database/scanner recipes used for VPS promotion."""
    fingerprint = source_fingerprint()
    result = []
    for service, supplied, dockerfile in (
            ('db', args.postgres_image, 'infra/vps/Dockerfile.db.no_xml'),
            ('scanner', args.scanner_image, 'infra/vps/Dockerfile.scanner')):
        if supplied:
            if not PINNED.fullmatch(supplied):
                raise ValueError('Scanner and database images must use immutable digests')
            result.append(supplied)
            continue
        tag = 'volt-debt-%s:runtime-%s' % (service, fingerprint)
        if not build:
            result.append(tag)
            continue
        found = subprocess.run(['docker', 'image', 'inspect', tag, '--format', '{{.Id}}'],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if found.returncode:
            run(['docker', 'build', '--memory=512m', '--cpu-period=100000', '--cpu-quota=100000',
                 '--file', dockerfile, '--tag', tag, '.'])
            found = subprocess.run(['docker', 'image', 'inspect', tag, '--format', '{{.Id}}'],
                                   check=True, stdout=subprocess.PIPE, text=True)
        result.append(found.stdout.strip())
    return tuple(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=("dev", "staging", "stg"))
    parser.add_argument("action", choices=("render", "up", "down", "status", "logs"))
    parser.add_argument("--env-file", type=Path, help="Private auth/integration settings; never production DATABASE_URL")
    parser.add_argument("--generate-test-account", action="store_true")
    parser.add_argument("--api-image")
    parser.add_argument("--web-image")
    parser.add_argument("--scanner-image", help="Promote a tested immutable scanner digest; otherwise build the hardened recipe")
    parser.add_argument("--postgres-image", help="Promote a tested immutable PostgreSQL 16 digest; otherwise build the hardened recipe")
    parser.add_argument("--web-port", type=int)
    parser.add_argument("--api-port", type=int)
    args = parser.parse_args()
    environment = "dev" if args.environment == "dev" else "staging"
    project = "volt-debt-" + environment
    directory = ROOT / ".runtime" / environment
    compose_env = directory / "compose.env"
    command = ["docker", "compose", "--project-name", project, "--env-file", str(compose_env), "--file", str(COMPOSE)]
    if args.action in ("down", "status", "logs"):
        if not compose_env.is_file():
            raise SystemExit("No isolated runtime settings exist for this environment")
        run(command + {"down": ["down"], "status": ["ps"], "logs": ["logs", "--tail", "100"]}[args.action])
        return
    web_port = args.web_port or (18000 if environment == "dev" else 19000)
    api_port = args.api_port or (18001 if environment == "dev" else 19001)
    if any(not 1024 <= value <= 65535 for value in (web_port, api_port)) or web_port == api_port:
        raise ValueError("Choose separate non-privileged loopback ports")
    if any(value and not PINNED.fullmatch(value) for value in (args.scanner_image, args.postgres_image)):
        raise ValueError("Scanner and database images must use immutable digests")
    if args.env_file:
        supplied = read_env(args.env_file)
    elif (directory / "api.env").exists():
        supplied = read_env(directory / "api.env")
        # Existing private values were written by this tool; remove wiring keys
        # and deserialize dotenv single quotes before applying current defaults.
        supplied = {key: value for key, value in supplied.items() if key not in LOCKED}
    else:
        supplied = {}
    credentials, _ = configure(environment, directory, supplied, args.generate_test_account)
    api, web = images(args, build=args.action == "up")
    postgres, scanner = infrastructure_images(args, build=args.action == 'up')
    private_write(directory / "nginx.conf", proxy_config())
    private_write(compose_env, dotenv({"RUNTIME_PROJECT": project, "RUNTIME_ENVIRONMENT": environment,
                  "RUNTIME_API_ENV": directory / "api.env", "RUNTIME_NGINX_CONFIG": directory / "nginx.conf",
                  "RUNTIME_API_PORT": api_port, "RUNTIME_WEB_PORT": web_port,
                  "POSTGRES_PASSWORD": credentials["database_password"], "API_IMAGE": api, "WEB_IMAGE": web,
                  "SCANNER_IMAGE": scanner, "POSTGRES_IMAGE": postgres}))
    private_write(directory / "images.json", json.dumps({"api": api, "web": web, "scanner": scanner,
                  "postgres": postgres}, indent=2) + "\n")
    if args.action == "render":
        print("Isolated runtime settings prepared; no containers were started")
        return
    run(command + ["up", "--detach", "db"])
    run(command + ["--profile", "setup", "run", "--rm", "migrate"])
    run(command + ["up", "--detach", "--wait", "--wait-timeout", "600"])
    print("Ready at http://127.0.0.1:%d; credentials remain in %s" % (web_port, directory / "credentials.json"))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit("Runtime refused: " + str(exc)) from None
