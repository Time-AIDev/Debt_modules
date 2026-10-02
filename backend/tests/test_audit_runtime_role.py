"""The audit chain appends as the deployed service account does.

Staging, 2026-09-27 (rev 00040-d8g): every append failed "permission denied for
table entry". The service account holds what migrate.grant_runtime hands it —
SELECT and INSERT on audit.entry, never UPDATE, DELETE or TRUNCATE, and it owns
nothing — while append took LOCK TABLE audit.entry IN EXCLUSIVE MODE, which needs
one of those three. Local runs connect as the owner, so no test here ever saw it.
This one connects as a role holding exactly the runtime grants.
"""
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

from app import audit_store, db, migrate

ROLE = "volt_audit_runtime_test"


def test_the_runtime_grants_are_enough_to_append_to_the_chain(pg_url, pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    # Roles are cluster-wide, so another database's run may have made it already.
    # Kept afterwards: dropping it needs DROP OWNED in every database it was granted in.
    pg_conn.execute(text('DO $$ BEGIN CREATE ROLE "%s" LOGIN; EXCEPTION WHEN '
                         'duplicate_object OR unique_violation THEN NULL; END $$' % ROLE))
    migrate.grant_runtime(pg_conn, ROLE)
    held = [p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
            if pg_conn.execute(text("select has_table_privilege(:r, 'audit.entry', :p)"),
                               {"r": ROLE, "p": p}).scalar()]
    assert held == ["SELECT", "INSERT"], "the role must be as narrow as staging's, and own nothing"
    pg_conn.commit()

    monkeypatch.setenv("DATABASE_URL", make_url(pg_url).set(username=ROLE, password=None)
                       .render_as_string(hide_password=False))
    db.reset()
    try:
        fields = dict(actor_claimed="runtime-role", actor_source="HEADER", verb="POST",
                      route_template="/v1/x", outcome="OK", status=200)
        first = audit_store.append(fields)
        second = audit_store.append(fields)
        assert second["prev_hash"] == first["hash"]
        assert audit_store.verify()["ok"] is True
    finally:
        db.reset()
