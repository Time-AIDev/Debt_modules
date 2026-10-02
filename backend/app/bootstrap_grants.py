"""One privileged statement, and nothing more — the Cloud SQL bootstrap gap.

Cloud SQL creates IAM database users with no privileges at all, and an IAM user
cannot grant itself any: only a holder of cloudsqlsuperuser can, which on Cloud SQL
means the built-in `postgres` user and therefore a password. Ruled 2026-09-13:
that password exists for one execution of this job and is then rotated to a value
nobody keeps.

So this does the least that must be done privileged:

  CONNECT on the database for both service accounts
  CREATE  on the database for the jobs account, so it can make the schemas

Everything else is NOT here on purpose. Once the jobs account creates the schemas it
OWNS them, and an owner can grant — so the runtime account's table rights are granted
by app/migrate.py as an ordinary IAM user, with no password anywhere near them.

  DATABASE_URL   the privileged (postgres) URL — from Secret Manager, never a flag
  DB_JOBS_ROLE   the account that will own the schemas
  DB_API_ROLE    the account the service runs as
"""
import os
import re
import sys

from sqlalchemy import text

from . import db

# Role names travel through the environment and are interpolated into DDL, where
# bound parameters are not allowed. Cloud SQL IAM roles look like
# "debt-api-sa@project-id.iam", so anything outside this alphabet is refused rather
# than quoted and hoped for.
ROLE_RE = re.compile(r"^[A-Za-z0-9@._-]+$")


def quoted(role):
    if not role or not ROLE_RE.match(role):
        raise SystemExit("refusing to build DDL from an unexpected role name: %r" % role)
    return '"%s"' % role


def statements(database, jobs_role, api_role):
    return [
        "GRANT CONNECT ON DATABASE %s TO %s, %s" % (quoted(database), quoted(api_role), quoted(jobs_role)),
        "GRANT CREATE ON DATABASE %s TO %s" % (quoted(database), quoted(jobs_role)),
    ]


def main():
    if not db.configured():
        print("DATABASE_URL is not set — nothing to grant", file=sys.stderr)
        return 2
    jobs_role = os.environ.get("DB_JOBS_ROLE")
    api_role = os.environ.get("DB_API_ROLE")
    if not jobs_role or not api_role:
        print("DB_JOBS_ROLE and DB_API_ROLE must both be set", file=sys.stderr)
        return 2

    from sqlalchemy.engine.url import make_url
    database = make_url(db.url()).database

    try:
        with db.connect() as conn:
            with conn.begin():
                for statement in statements(database, jobs_role, api_role):
                    conn.execute(text(statement))
                    print("  %s" % statement)
    except db.DatabaseUnreachable as exc:
        print("database unreachable: %s" % exc, file=sys.stderr)
        return 1
    print("bootstrap_grants: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
