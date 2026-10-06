"""Garbage collect transient bytes after commit; preserve attachments and evidence.

Run ``python -m app.object_retention`` to preview; ``--apply`` performs cleanup.
Objects use immutable unique names. A grace period longer than a request prevents
deleting a newly written object before its owning SQL transaction commits.
"""
import argparse
import json
import time
from sqlalchemy import text
from . import db, task_objects
from .integrations import env
from .production_unit import CURRENT

LOCK_KEY = 812049713


def cleanup(apply=False):
    if CURRENT.get() is not None:
        raise RuntimeError("Retention must run outside a business request")
    grace_hours = max(1, int(env("TRANSIENT_OBJECT_GRACE_HOURS", "24")))
    dead_days = max(1, int(env("DEAD_LETTER_RETENTION_DAYS", "7")))
    cache_hours = max(1, int(env("REQUEST_RESULT_RETENTION_HOURS", "24")))
    cutoff = time.time() - grace_hours * 3600
    summary = {"applied": apply, "upload_sessions": 0, "request_results": 0,
               "revoked_sessions": 0, "expired_sessions": 0, "projection_cursors": 0,
               "objects": 0, "bytes": 0}
    with db.connect() as conn, conn.begin():
        if not conn.execute(text("select pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar_one():
            return dict(summary, busy=True)
        stale = conn.execute(text(
            "select upload_id from app.upload_session where "
            "(consumed_at is not null and consumed_at < now()-:grace * interval '1 hour') "
            "or (consumed_at is null and created_at < now()-interval '24 hours'-:grace * interval '1 hour')"
        ), {"grace": grace_hours}).scalars().all()
        summary["upload_sessions"] = len(stale)
        summary["request_results"] = conn.execute(text(
            "select count(*) from app.request_result where created_at < now()-:h * interval '1 hour'"
        ), {"h": cache_hours}).scalar_one()
        if conn.execute(text("select to_regclass('app.projection_cursor')")).scalar():
            summary["projection_cursors"] = conn.execute(text(
                "select count(*) from app.projection_cursor where expires_at < now()"
            )).scalar_one()
            if apply:
                conn.execute(text("delete from app.projection_cursor where expires_at < now()"))
        summary["revoked_sessions"] = conn.execute(text(
            "select count(*) from app.auth_session where revoked_at < now()-interval '7 days'"
        )).scalar_one()
        expired_condition = (
            "case when jsonb_typeof(payload->'expires_at')='number' "
            "then (payload->>'expires_at')::numeric else null end "
            "< extract(epoch from now()-interval '7 days')"
        )
        summary["expired_sessions"] = conn.execute(text(
            "select count(*) from app.auth_session where revoked_at is null and " + expired_condition
        )).scalar_one()
        # Read the references under a consistent DB transaction. Every fresh
        # immutable object is also protected by its filesystem/GCS timestamp.
        referenced = set(conn.execute(text(
            "select p.object_name from app.upload_part p join app.upload_session s using(upload_id) where not ("
            "(s.consumed_at is not null and s.consumed_at < now()-:grace * interval '1 hour') or "
            "(s.consumed_at is null and s.created_at < now()-interval '24 hours'-:grace * interval '1 hour'))"
        ), {"grace": grace_hours}).scalars())
        referenced.update(conn.execute(text(
            "select payload->>'object_name' from app.task_outbox where finished_at is null "
            "or dead_lettered_at > now()-:days * interval '1 day'"
        ), {"days": dead_days}).scalars())
        if apply:
            for uid in stale:
                conn.execute(text("delete from app.upload_part where upload_id=:u"), {"u": uid})
                conn.execute(text("delete from app.upload_session where upload_id=:u"), {"u": uid})
            conn.execute(text("delete from app.request_result where created_at < now()-:h * interval '1 hour'"),
                         {"h": cache_hours})
            conn.execute(text("delete from app.auth_session where revoked_at < now()-interval '7 days'"))
            conn.execute(text("delete from app.auth_session where revoked_at is null and " + expired_condition))
    # Only after the metadata transaction commits. Never sweep CLEAN_BUCKET,
    # attachments, arbitrary prefixes, or referenced queued/dead-letter inputs.
    for obj in task_objects.list_transient_objects():
        if obj["updated"] >= cutoff or obj["name"] in referenced:
            continue
        if apply:
            task_objects.delete(obj["name"])
        summary["objects"] += 1
        summary["bytes"] += obj["size"]
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete eligible transient objects and metadata")
    args = parser.parse_args()
    print(json.dumps(cleanup(apply=args.apply), sort_keys=True))


if __name__ == "__main__":
    main()
