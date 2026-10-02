"""What `app.migrate.grant_runtime` actually hands the deployed service account.

Split roles (deploy_gcp.sh hands `DB_RUNTIME_ROLE` to the migrate job) mean this list
is the whole of the Cloud Run account's rights — it owns nothing, so anything missing
here is a permission denied in production and nothing here is covered by ownership.

The two things this file pins are opposites of each other:
  * the audit schema MUST be reachable — audit_store.append LOCKs and INSERTs into
    audit.entry on every request the middleware records, a GET included, so a missing
    USAGE is not a degraded feature, it is every route returning 500;
  * and it must be reachable ONLY for append — SELECT and INSERT, never UPDATE or
    DELETE. schema.sql's trigger already refuses those, but a trigger and a grant fence
    different things and the log deserves both.
"""
import re

from sqlalchemy import text

from app import migrate


class _Recorder:
    """Stands in for a connection: keeps the DDL instead of running it."""

    def __init__(self):
        self.statements = []

    def execute(self, clause):
        assert isinstance(clause, type(text("x"))), "grant_runtime must go through sqlalchemy.text"
        self.statements.append(str(clause))


ROLE = "debt-api-sa@some-project.iam"
QUOTED = '"%s"' % ROLE


def _run():
    conn = _Recorder()
    migrate.grant_runtime(conn, ROLE)
    return conn.statements


def _matching(statements, schema, kind):
    """Every statement granting something on `kind` ('TABLES'/'SEQUENCES') in `schema`.

    Covers both spellings the list uses, and they are NOT interchangeable:
    `GRANT … ON ALL TABLES IN SCHEMA s` covers the tables this migration just made,
    `ALTER DEFAULT PRIVILEGES IN SCHEMA s GRANT … ON TABLES` covers the ones a later
    migration will make. A schema needs both, so the caller counts them.
    """
    out = []
    for s in statements:
        # The schema list runs to the next keyword: " GRANT " in the ALTER spelling,
        # " TO " in the plain one. Stopping at neither is how this used to read the
        # role name as part of the schema name and quietly match nothing.
        schemas = re.search(r"IN SCHEMA (.+?)(?: GRANT | TO )", s)
        if not schemas or schema not in [p.strip() for p in schemas.group(1).split(",")]:
            continue
        if re.search(r"GRANT (.+?) ON (?:ALL )?%s\b" % kind, s):
            out.append(s)
    return out


def _privileges_on(statements, schema, kind):
    """The privilege words granted on `kind` in `schema`, both spellings together."""
    found = set()
    for s in _matching(statements, schema, kind):
        grant = re.search(r"GRANT (.+?) ON (?:ALL )?%s\b" % kind, s)
        found |= {p.strip() for p in grant.group(1).split(",")}
    return found


def test_every_grant_names_the_role_that_was_asked_for():
    for statement in _run():
        assert QUOTED in statement


def test_the_runtime_role_can_reach_the_audit_schema_at_all():
    # Without this one line the service account cannot LOCK or INSERT audit.entry, and
    # since the audit middleware runs on every request, not one route answers.
    assert 'GRANT USAGE ON SCHEMA audit TO %s' % QUOTED in _run()


def test_the_audit_schema_is_granted_append_only_rights():
    statements = _run()
    for kind in ("TABLES", "SEQUENCES"):
        assert _privileges_on(statements, "audit", kind), \
            "nothing grants %s in the audit schema — an INSERT needs the table AND its sequence" % kind
    assert _privileges_on(statements, "audit", "TABLES") == {"SELECT", "INSERT"}
    assert _privileges_on(statements, "audit", "SEQUENCES") == {"USAGE", "SELECT"}


def test_nothing_hands_the_runtime_role_update_or_delete_on_audit():
    # audit.entry is append-only. schema.sql's trigger says so to an owner; this says so
    # to a role. If these ever appear, the near fence is gone and only the trigger is left.
    for forbidden in ("UPDATE", "DELETE", "TRUNCATE", "ALL"):
        assert forbidden not in _privileges_on(_run(), "audit", "TABLES")


def test_the_working_schemas_keep_their_full_table_rights():
    # The audit lines are additions, not a re-slicing of what landing and app already had.
    statements = _run()
    for schema in ("landing", "app"):
        assert _privileges_on(statements, schema, "TABLES") == {"SELECT", "INSERT", "UPDATE", "DELETE"}
        assert _privileges_on(statements, schema, "SEQUENCES") == {"USAGE", "SELECT"}


def test_the_runtime_role_can_reach_the_records_schema_at_all():
    # This migration creates the records schema too, so the API account does not own it
    # either. A missing SELECT on records.user_account is not a lost feature — it is
    # sign-in returning 500 to everyone who tries.
    assert 'GRANT USAGE ON SCHEMA records TO %s' % QUOTED in _run()


def test_the_records_schema_is_granted_read_write_but_never_delete():
    statements = _run()
    assert _privileges_on(statements, "records", "TABLES") == {"SELECT", "INSERT", "UPDATE"}
    assert _privileges_on(statements, "records", "SEQUENCES") == {"USAGE", "SELECT"}


def test_nothing_hands_the_runtime_role_delete_on_records():
    # The one way records differs from landing and app. Nothing in app/ hard-deletes a
    # records row: identity_link retires, attachment and notice carry deleted_at,
    # customer_contact flips active. Soft deletes need UPDATE, not DELETE, and
    # withholding DELETE keeps an accident from becoming a hole in a customer's history.
    for forbidden in ("DELETE", "TRUNCATE", "ALL"):
        assert forbidden not in _privileges_on(_run(), "records", "TABLES")


def test_message_templates_are_the_one_records_table_with_hard_delete_rights():
    """The personal-template DELETE endpoint is an intentional hard delete.

    Keep the broad records-schema grant delete-free, but grant DELETE narrowly on
    this table so the deployed runtime role can honour the documented API.
    """
    assert "GRANT DELETE ON TABLE records.message_template TO %s" % QUOTED in _run()


def test_every_granted_schema_covers_both_todays_tables_and_tomorrows():
    # ALTER DEFAULT PRIVILEGES alone leaves the tables this migration just created
    # unreachable; the plain GRANT alone leaves the next migration's unreachable.
    # Each schema needs one of each, for tables and for sequences.
    statements = _run()
    for schema in ("landing", "app", "audit", "records"):
        for kind in ("TABLES", "SEQUENCES"):
            found = _matching(statements, schema, kind)
            assert len(found) == 2, \
                "%s/%s is granted by %d statement(s), not one plain and one default" % (
                    schema, kind, len(found))
            assert sum(s.startswith("ALTER DEFAULT PRIVILEGES") for s in found) == 1


def test_an_unexpected_role_name_is_refused_rather_than_quoted():
    conn = _Recorder()
    for bad in ('bob"; DROP SCHEMA audit CASCADE --', "bob smith", ""):
        try:
            migrate.grant_runtime(conn, bad)
        except SystemExit:
            continue
        raise AssertionError("grant_runtime built DDL from %r" % bad)
    assert conn.statements == []
