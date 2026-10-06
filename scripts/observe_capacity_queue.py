#!/usr/bin/env python3
"""Record actual isolated queue counts before/after load; never infer stability."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from build_capacity_evidence import IMAGE, REVISION, RUN_ID, private_output
from capacity_health_guard import owned_inventory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--api-container", required=True)
    parser.add_argument("--db-container", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not REVISION.fullmatch(args.revision) or not IMAGE.fullmatch(args.api_image) or not RUN_ID.fullmatch(args.run_id):
        parser.error("Expected immutable source/image and known diagnostic run identifier")
    try:
        output = private_output(args.output)
        owned_inventory(args.api_container, args.db_container)
        template = '{{.Image}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
        binding = subprocess.run(["docker", "inspect", "--format", template, args.api_container],
            capture_output=True, text=True, timeout=5, check=True).stdout.strip().split()
        if binding != [args.api_image, args.revision]:
            raise ValueError("Target changed")
        runtime = json.loads(args.runtime.read_text())
        url = make_url(runtime["DATABASE_URL"])
        if (runtime.get("VOLT_LOAD_TEST_DATABASE") != "true" or url.host != "127.0.0.1"
                or url.database != "hardening_load_capacity" or url.username != "load_admin"):
            raise ValueError("Queue counters require the explicitly owned synthetic target")
        engine = create_engine(url, future=True, hide_parameters=True)
        try:
            with engine.connect() as conn, conn.begin():
                conn.execute(text("set transaction read only"))
                pending = conn.execute(text("select count(*) from app.task_outbox "
                    "where finished_at is null and dead_lettered_at is null")).scalar_one()
        finally:
            engine.dispose()
        data = json.loads(output.read_text()) if output.exists() else {}
        previous = data.get(args.run_id) or {}
        if previous and (previous.get("revision") != args.revision or previous.get("api_image") != args.api_image):
            raise ValueError("Queue observation binding changed")
        data[args.run_id] = dict(previous, revision=args.revision, api_image=args.api_image, isolated_read_only=True,
            **{"pending_" + args.phase: pending, args.phase + "_observed_at_utc": datetime.now(timezone.utc).isoformat()})
        output.write_text(json.dumps(data, indent=2) + "\n")
        output.chmod(0o600)
        print("Isolated pending-queue observation recorded: " + str(pending))
        return 0
    except Exception:
        print("Queue observation refused or unavailable; no queue stability claim recorded")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
