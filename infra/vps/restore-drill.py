#!/usr/bin/env python3
"""Restore a completed backup into a disposable, network-isolated PostgreSQL."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run as root.")
    backup = args.backup.resolve(strict=True)
    if not backup.is_relative_to(Path("/srv/volt-debt-backups")) or backup.name.startswith("."):
        raise SystemExit("Choose a completed production backup directory.")
    if (backup / "BACKUP_FORMAT").read_text().strip() != "volt-debt-backup-v1" or not (backup / "COMPLETE").is_file():
        raise SystemExit("Backup is not complete.")
    os.umask(0o077)
    container = "volt-debt-restore-drill-" + uuid.uuid4().hex[:12]
    created = False
    admin = "volt_restore_admin"
    started = datetime.now(timezone.utc).isoformat()
    diagnostics = backup / "restore-drill.log"
    with diagnostics.open("a") as log:
        def run(command, *, stdin=None, capture=False, timeout=180):
            result = subprocess.run(command, stdin=stdin, stdout=subprocess.PIPE if capture else log,
                                    stderr=log, timeout=timeout, check=True)
            return result.stdout.decode().strip() if capture else None

        try:
            subprocess.run(["sha256sum", "--check", "--status", "SHA256SUMS"], cwd=backup,
                           stdout=log, stderr=log, check=True, timeout=180)
            image = (backup / "database-image-id.txt").read_text().strip()
            if not image.startswith("sha256:") or len(image) != 71:
                raise ValueError("invalid recorded database image")
            run(["docker", "run", "--detach", "--name", container, "--network", "none",
                 "--memory", "512m", "--label", "volt-debt.restore-drill=true",
                 "--env", f"POSTGRES_USER={admin}", "--env", "POSTGRES_DB=postgres",
                 "--env", "POSTGRES_HOST_AUTH_METHOD=trust", image])
            created = True
            for attempt in range(60):
                # The image starts a temporary Unix-socket-only server during init.
                # TCP readiness waits for the final server after that process exits.
                result = subprocess.run(["docker", "exec", container, "pg_isready", "--host", "127.0.0.1",
                                         "--username", admin, "--dbname", "postgres"],
                                        stdout=log, stderr=log, timeout=10)
                if result.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("isolated database startup timed out")
            with (backup / "globals.sql").open("rb") as file:
                run(["docker", "exec", "--interactive", container, "psql", "--username", admin,
                     "--dbname", "postgres", "--set=ON_ERROR_STOP=1"], stdin=file)
            run(["docker", "exec", container, "createdb", "--username", admin,
                 "--owner", "debt_migrate", "debt"])
            with (backup / "database.dump").open("rb") as file:
                run(["docker", "exec", "--interactive", container, "pg_restore", "--username", admin,
                     "--dbname", "debt", "--exit-on-error"], stdin=file, timeout=900)
            query = """SELECT 'schema_version', version FROM app.schema_version WHERE singleton=true;
SELECT 'app.business_record', count(*) FROM app.business_record;
SELECT 'audit.entry', count(*) FROM audit.entry;
SELECT 'app.auth_session', count(*) FROM app.auth_session;
SELECT 'app.task_outbox', count(*) FROM app.task_outbox;
SELECT 'application_tables', count(*) FROM information_schema.tables
WHERE table_schema IN ('app','audit','landing','records') AND table_type='BASE TABLE';"""
            rows = run(["docker", "exec", container, "psql", "--username", admin, "--dbname", "debt",
                        "--no-psqlrc", "--tuples-only", "--no-align", "--field-separator", "\t",
                        "--set=ON_ERROR_STOP=1", "--command", query], capture=True)
            counts = dict(line.split("\t") for line in rows.splitlines())
            counts = {key: int(value) for key, value in counts.items()}
            if counts["schema_version"] not in (1, 2, 3):
                raise ValueError("restored schema version does not match application")
            expected_file = backup / "database-counts.tsv"
            if expected_file.is_file():
                expected = dict(line.split("\t") for line in expected_file.read_text().splitlines())
                expected = {key: int(value) for key, value in expected.items()}
                if any(counts.get(key) != value for key, value in expected.items()):
                    raise ValueError("restored database counts differ from backup metadata")
            with tempfile.TemporaryDirectory(prefix="volt-debt-restore-objects-", dir="/srv/volt-debt-backups") as directory:
                with tarfile.open(backup / "objects.tar.gz", "r:gz") as archive:
                    archive.extractall(directory, filter="data")
                objects = [p for p in (Path(directory) / "objects").rglob("*") if p.is_file()]
                files, size = len(objects), sum(p.stat().st_size for p in objects)
                manifest = dict(line.split("=", 1) for line in (backup / "manifest.txt").read_text().splitlines())
                if "application_table_count" in manifest and counts["application_tables"] != int(manifest["application_table_count"]):
                    raise ValueError("restored application table count differs from backup metadata")
                if files != int(manifest["object_regular_file_count"]) or size != int(manifest["object_regular_file_bytes"]):
                    raise ValueError("restored object counts differ from backup metadata")
            evidence = {"status": "passed", "started_at_utc": started,
                        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "database_image": image, "network": "none", "counts": counts,
                        "counts_compared_with_backup": expected_file.is_file(),
                        "object_files": files, "object_bytes": size}
            (backup / "restore-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
            print("Restore drill passed: database schema/counts and private objects verified.")
        except Exception as exc:
            log.write(f"Drill failure: {type(exc).__name__}: {exc}\n")
            print(f"Restore drill failed; private diagnostics: {diagnostics}")
            raise SystemExit(1) from None
        finally:
            if created:
                try:
                    run(["docker", "rm", "--force", "--volumes", container])
                except Exception:
                    print(f"Could not remove isolated drill container: {container}")
                    raise SystemExit(1) from None


if __name__ == "__main__":
    main()
