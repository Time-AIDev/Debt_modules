"""Applies schema.sql. main() is the debt-migrate Cloud Run Job entrypoint.

infra/cloudbuild.yaml:33 already executes a job of that name, before deploy-api
takes traffic — so a failed migration never reaches a user. This module is what
finally makes that reference resolve.
"""
import os
import re
import sys
from pathlib import Path

from sqlalchemy import text

from . import db

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def statements(schema_path=None):
    """schema.sql split on the semicolons that END a statement.

    Comments are stripped BEFORE the split, not after. Splitting first looks
    equivalent and is not: a prose comment may itself contain a semicolon, and
    then the split lands inside it and hands Postgres half a sentence. That is
    exactly what happened the first time this ran — "syntax error at or near
    'the'".

    2026-09-11: the naive split this used to do was safe "only because schema.sql
    has no function bodies, no dollar-quoting and no semicolons inside literals.
    If any of those are ever added, this must become a real parser." The audit
    table's append-only trigger is all three, so this is that parser — small, and
    only as clever as it has to be: it tracks single-quoted literals (with '' as
    an escaped quote) and $tag$ bodies, and splits nowhere else.
    """
    lines = [line for line in (schema_path or SCHEMA_PATH).read_text(encoding="utf-8").splitlines()
             if not line.strip().startswith("--")]
    sql = "\n".join(lines)

    out, buf = [], []
    i, n = 0, len(sql)
    in_literal = False
    dollar_tag = None
    while i < n:
        ch = sql[i]
        if dollar_tag:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
        elif in_literal:
            if ch == "'":
                # '' is an escaped quote, not the end of the literal.
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("''")
                    i += 2
                    continue
                in_literal = False
        elif ch == "'":
            in_literal = True
        elif ch == "$":
            end = sql.find("$", i + 1)
            # A $tag$ opener: $ … $ with only identifier characters between.
            if end != -1 and all(c.isalnum() or c == "_" for c in sql[i + 1:end]):
                dollar_tag = sql[i:end + 1]
                buf.append(dollar_tag)
                i = end + 1
                continue
        elif ch == ";":
            chunk = "".join(buf).strip()
            if chunk:
                out.append(chunk)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def apply(conn):
    """Run every statement. Returns them, in order, for the caller to log."""
    executed = []
    for statement in statements():
        conn.execute(text(statement))
        executed.append(statement.splitlines()[0])
    capacity_schema = Path(__file__).with_name("capacity_schema.sql")
    for statement in statements(capacity_schema):
        conn.execute(text(statement))
        executed.append(statement.splitlines()[0])
    from .runtime_policy import SCHEMA_VERSION
    conn.execute(text("update app.schema_version set version=:version where singleton=true"),
                 {"version": SCHEMA_VERSION})
    return executed


# Same alphabet as bootstrap_grants: a role name reaches DDL by interpolation, where
# a bound parameter is not allowed, so anything unexpected is refused not quoted.
ROLE_RE = re.compile(r"^[A-Za-z0-9@._-]+$")

RUNTIME_GRANTS = [
    "GRANT USAGE ON SCHEMA landing, app TO %s",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA landing, app TO %s",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA landing, app TO %s",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA landing, app "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %s",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA landing, app GRANT USAGE, SELECT ON SEQUENCES TO %s",
    # The audit schema, on its own terms. It is not an afterthought to the list above:
    # audit_store.append reads and inserts audit.entry on every request the middleware
    # records, a GET included, so without USAGE here every append fails — silently, as
    # the middleware swallows it, which is how staging ran with an empty log. SELECT and
    # INSERT are enough only because append serialises the chain on an advisory lock:
    # LOCK TABLE in EXCLUSIVE mode needs UPDATE, DELETE or TRUNCATE, so a lock error is
    # never fixed by widening these lines. It is NOT folded into the "landing, app" lines
    # because the rights differ and must keep differing: SELECT and INSERT, never
    # UPDATE and never DELETE. audit.entry is append-only, and schema.sql's trigger
    # says so — but the trigger binds an owner while a grant binds a role, and under
    # DB_RUNTIME_ROLE the API account owns nothing, so the grant is the near fence.
    # The sequence rights are not optional either: seq is a bigserial, and an INSERT
    # without USAGE on its sequence is refused.
    "GRANT USAGE ON SCHEMA audit TO %s",
    "GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA audit TO %s",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA audit TO %s",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT SELECT, INSERT ON TABLES TO %s",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT USAGE, SELECT ON SEQUENCES TO %s",
    # The records schema, also on its own terms — this migration creates it (schema.sql:237),
    # so under DB_RUNTIME_ROLE the API account does not own it either, and a missing SELECT
    # on records.user_account is not a degraded feature: it is sign-in returning 500 to
    # everyone. SELECT, INSERT and UPDATE — and NO DELETE, which is the one way these rights
    # differ from landing and app. Nothing in app/ hard-deletes a records row; every removal
    # there is a soft delete the UPDATE right already covers (identity_link.retired_at,
    # attachment.deleted_at, notice.deleted_at, customer_contact.active, user_account's
    # disabled state). Withholding DELETE keeps an accident from becoming a hole in a
    # customer's history. Personal message templates are the sole exception: their
    # public API explicitly promises DELETE and they are user-authored preferences,
    # not customer history, so that table receives the narrow grant below. Sequences:
    # every one of these tables has a bigserial key.
    "GRANT USAGE ON SCHEMA records TO %s",
    "GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA records TO %s",
    "GRANT DELETE ON TABLE records.message_template TO %s",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA records TO %s",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA records GRANT SELECT, INSERT, UPDATE ON TABLES TO %s",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA records GRANT USAGE, SELECT ON SEQUENCES TO %s",
    # Reviewed source evidence and installation proofs are insertion-only. The
    # preview's apply result remains mutable, but past facts cannot be rewritten.
    "REVOKE UPDATE ON records.contract_supplement, records.debt_status_observation, "
    "records.installation_confirmation FROM %s",
]


def grant_runtime(conn, role):
    """Give the service account its rights on what this migration just created.

    Safe to do here, and deliberately here rather than in the privileged bootstrap:
    this job's account OWNS these schemas, and an owner may grant, so no password is
    involved. The ALTER DEFAULT PRIVILEGES lines are what make a LATER migration's
    new tables readable without anyone re-running a grant.

    Skipped entirely when DB_RUNTIME_ROLE is unset, which is every local run and
    every CI run — there are no IAM roles there to grant to.
    """
    if not ROLE_RE.match(role):
        raise SystemExit("refusing to build DDL from an unexpected role name: %r" % role)
    done = []
    for template in RUNTIME_GRANTS:
        statement = template % ('"%s"' % role)
        conn.execute(text(statement))
        done.append(statement.split(" TO ")[0])
    return done


def runtime_roles(environ=None):
    environ = os.environ if environ is None else environ
    roles = list(dict.fromkeys(r.strip() for r in (environ.get("DB_RUNTIME_ROLES") or
                                                  environ.get("DB_RUNTIME_ROLE") or "").split(",") if r.strip()))
    if any(not ROLE_RE.fullmatch(role) for role in roles):
        raise SystemExit("refusing unexpected runtime role name")
    return roles


def main():
    if not db.configured():
        print("DATABASE_URL is not set — nothing to migrate", file=sys.stderr)
        return 2
    roles = runtime_roles()
    try:
        with db.connect() as conn:
            with conn.begin():
                executed = apply(conn)
                for runtime_role in roles:
                    executed += grant_runtime(conn, runtime_role)
    except db.DatabaseUnreachable as exc:
        print("database unreachable: %s" % exc, file=sys.stderr)
        return 1
    for line in executed:
        print("  %s" % line)
    print("migrate: %d statements applied" % len(executed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
