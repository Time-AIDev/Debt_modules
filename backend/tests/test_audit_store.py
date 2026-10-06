"""The persisted chain. Skipped entirely when no database is configured — the
DATABASE_URL-unset path is Task 4's business, not this file's."""
import pytest
from sqlalchemy import text

from app import audit, audit_store, db, migrate

@pytest.fixture(autouse=True)
def schema(pg_url, pg_conn, monkeypatch):
    # Opt in only to the disposable fixture; conftest intentionally clears any
    # ambient DATABASE_URL before collection so deployed databases stay safe.
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    db.reset()
    yield
    db.reset()


def _fields(**over):
    base = dict(actor_claimed="nantapol", actor_source="HEADER", session_id="s-1",
                request_id="r-1", verb="POST", route_template="/v1/x", act="X",
                subject_type="customer", subject_uid="cus-1", detail={"a": 1},
                outcome="OK", status=200, error_code=None)
    base.update(over)
    return base


def test_an_appended_entry_comes_back_with_its_chain_intact():
    first = audit_store.append(_fields())
    second = audit_store.append(_fields(act="Y"))
    assert second["prev_hash"] == first["hash"]
    assert second["seq"] > first["seq"]
    assert audit_store.verify()["ok"] is True


def test_the_database_refuses_an_update():
    entry = audit_store.append(_fields())
    with pytest.raises(Exception) as err:
        with db.connect() as conn:
            with conn.begin():
                conn.execute(text("UPDATE audit.entry SET actor_claimed = 'someone' "
                                  "WHERE seq = :s"), {"s": entry["seq"]})
    assert "append-only" in str(err.value)


def test_the_database_refuses_a_delete():
    entry = audit_store.append(_fields())
    with pytest.raises(Exception) as err:
        with db.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM audit.entry WHERE seq = :s"),
                             {"s": entry["seq"]})
    assert "append-only" in str(err.value)


def test_the_database_refuses_a_truncate():
    # A row-level trigger never fires on TRUNCATE, and verify() on an empty table
    # reports ok — so without a statement-level guard this is the one tamper the
    # chain design cannot see. It must be refused just as loudly as UPDATE/DELETE.
    audit_store.append(_fields())
    with pytest.raises(Exception) as err:
        with db.connect() as conn:
            with conn.begin():
                conn.execute(text("TRUNCATE audit.entry"))
    assert "append-only" in str(err.value)


def test_reading_back_filters_by_actor_and_by_subject():
    audit_store.append(_fields(actor_claimed="thip", subject_uid="cus-9"))
    rows = audit_store.read({"actor": "thip"}, limit=50, before_seq=None)
    assert rows and all(r["actor_claimed"] == "thip" for r in rows)
    rows = audit_store.read({"subject_uid": "cus-9"}, limit=50, before_seq=None)
    assert rows and all(r["subject_uid"] == "cus-9" for r in rows)


def test_reading_back_filters_by_since_on_the_database_path_too():
    # Final-review finding 3, the DB half: the router now hands down a parsed,
    # timezone-aware datetime rather than a raw string, so a future `since`
    # must exclude a row just written, and a past one must not.
    from datetime import datetime, timedelta, timezone
    audit_store.append(_fields(actor_claimed="since-db-test"))
    future = datetime.now(timezone.utc) + timedelta(days=1)
    rows = audit_store.read({"actor": "since-db-test", "since": future}, limit=50, before_seq=None)
    assert rows == []
    past = datetime.now(timezone.utc) - timedelta(days=1)
    rows = audit_store.read({"actor": "since-db-test", "since": past}, limit=50, before_seq=None)
    assert rows and all(r["actor_claimed"] == "since-db-test" for r in rows)


def test_persisted_says_true_when_a_database_is_configured():
    assert audit_store.persisted() is True


def test_a_failed_insert_does_not_desynchronise_seq_from_the_hash():
    # The reviewer's exact reproduction: Postgres sequences are not
    # transactional, so if the app-computed seq baked into the hash were left
    # to a bigserial DEFAULT nextval(), a rolled-back insert (a CHECK
    # violation, here) would burn a sequence value with no row committed, and
    # the next append would hash a seq one lower than what Postgres actually
    # stores next -- verify() would then report broken_at on a row nobody
    # tampered with. Binding :seq explicitly (see the comment above _INSERT)
    # is what keeps this from happening: MAX(seq) is unaffected by a rolled
    # back transaction, so the next append recomputes the same seq the failed
    # one would have used.
    audit_store.append(_fields())
    try:
        audit_store.append(_fields(outcome="BOGUS"))  # violates the outcome CHECK
        assert False, "expected the CHECK constraint to refuse this insert"
    except Exception:
        pass
    audit_store.append(_fields())
    assert audit_store.verify()["ok"] is True


def test_the_database_path_also_refuses_an_unknown_field():
    # Ruling on Finding 2: the in-memory path (audit.Chain.append) already
    # raises ValueError on a field outside audit.FIELDS -- Ruling 6, an
    # unhashed field is an unprotected field. The database path must refuse
    # the same way rather than silently dropping the misspelled key, so the
    # same mistake is not a loud crash with no database and silent data loss
    # with one.
    with pytest.raises(ValueError, match="fields the chain does not hash"):
        audit_store.append(_fields(unknown_field="nope"))


def test_verify_scopes_its_gap_count_to_this_instance_on_the_database_path():
    # Ruling 20 (final review): MEMORY.gaps() only ever counts writes THIS process
    # failed to record. Reported as "gaps"/"complete" next to each other, that pair
    # asserted log-wide completeness from a per-instance counter -- on more than
    # one Cloud Run instance, a gap on instance A is invisible to a verify() served
    # by instance B. The persisted path must not make that claim: the field name
    # says what it actually counts, and `complete` is None, not a boolean.
    audit_store.append(_fields())
    body = audit_store.verify()
    assert body["persisted"] is True
    assert "gaps_this_instance" in body
    assert "gaps" not in body
    assert body["complete"] is None


def test_distinct_values_runs_the_real_sql_and_excludes_nulls():
    # Fix round 2: distinct_values()'s Postgres branch (a plain SELECT DISTINCT)
    # had no test that ever executed it -- two Critical bugs in this same module
    # (the unstored `at`, the bigserial-default `seq`) were both invisible until
    # someone actually ran the database path, so a third untested SQL branch here
    # is not a risk worth carrying forward.
    #
    # audit.entry is append-only and shared across this whole test file (no
    # truncate between tests), so this asserts the values just written are
    # PRESENT -- a subset check -- never that the lists equal exactly what this
    # test inserted.
    audit_store.append(_fields(actor_claimed="nantapol-d2", act="ACT_ONE"))
    audit_store.append(_fields(actor_claimed="thip-d2", act="ACT_TWO"))
    # An unenriched act is recorded with act=None (test_audit_chain.py's second
    # entry does the same); it must never surface as a selectable filter option.
    audit_store.append(_fields(actor_claimed="thip-d2", act=None))

    result = audit_store.distinct_values()

    assert set(result.keys()) == {"actors", "acts"}
    assert {"nantapol-d2", "thip-d2"} <= set(result["actors"])
    assert {"ACT_ONE", "ACT_TWO"} <= set(result["acts"])
    assert None not in result["actors"]
    assert None not in result["acts"]
    assert "" not in result["actors"]
    assert "" not in result["acts"]
    assert result["actors"] == sorted(result["actors"])
    assert result["acts"] == sorted(result["acts"])


def test_actor_role_is_stored_served_and_hashed_and_a_null_row_still_verifies():
    # R13: a role-less row (every row from before the column) and a signed row, side by
    # side in one chain; both come back and the whole chain verifies.
    unsigned = audit_store.append(_fields())
    signed = audit_store.append(_fields(actor_role="MANAGER"))
    rows = {r["seq"]: r for r in audit_store.read({}, limit=10, before_seq=None)}
    assert rows[unsigned["seq"]]["actor_role"] is None
    assert rows[signed["seq"]]["actor_role"] == "MANAGER"
    assert audit_store.verify()["ok"] is True


def test_the_database_refuses_an_unknown_actor_role():
    with pytest.raises(Exception) as err:
        audit_store.append(_fields(actor_role="GOD"))
    assert "entry_actor_role_check" in str(err.value)
