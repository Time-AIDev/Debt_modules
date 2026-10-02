import json
from datetime import datetime, timezone

from sqlalchemy import text

from app import audit, migrate, session_store_db


def _audit(conn, session_id, actor, suffix):
    head = conn.execute(text(
        "select seq, hash from audit.entry order by seq desc limit 1"
    )).mappings().first()
    entry = {key: None for key in audit.FIELDS}
    entry.update({
        "seq": (head["seq"] if head else 0) + 1,
        "at": datetime.now(timezone.utc).isoformat(),
        "business_date": "2026-10-01", "actor_claimed": actor,
        "actor_source": "SESSION", "session_id": session_id,
        "request_id": "backfill-%s" % suffix, "verb": "POST",
        "route_template": "/test", "detail": {}, "outcome": "OK", "status": 200,
    })
    entry["prev_hash"] = head["hash"] if head else audit.GENESIS
    entry["hash"] = audit.hash_entry(entry, entry["prev_hash"])
    conn.execute(text(
        "insert into audit.entry "
        "(seq, at, business_date, actor_claimed, actor_source, session_id, request_id, verb, "
        " route_template, act, subject_type, subject_uid, detail, outcome, status, error_code, "
        " prev_hash, hash, actor_role) values "
        "(:seq, :at, :business_date, :actor_claimed, :actor_source, :session_id, :request_id, "
        " :verb, :route_template, :act, :subject_type, :subject_uid, cast(:detail as jsonb), "
        " :outcome, :status, :error_code, :prev_hash, :hash, :actor_role)"
    ), {**entry, "detail": json.dumps(entry["detail"])})


def test_backfill_chooses_latest_store_row_archives_older_and_keeps_unmapped(pg_conn):
    migrate.apply(pg_conn)
    pg_conn.execute(text(
        "insert into app.session_state "
        "(session_id, key, payload, codec, code_version, updated_at) values "
        "('s-backfill-old', 'notes', :old, 'pickle-v1', 'old-rev', '2026-09-01'), "
        "('s-backfill-new', 'notes', :new, 'pickle-v1', 'new-rev', '2026-10-01'), "
        "('s-backfill-unmapped', 'notes', :unmapped, 'pickle-v1', 'old-rev', '2026-08-01')"
    ), {"old": session_store_db.dump({"value": "old"}),
        "new": session_store_db.dump({"value": "new"}),
        "unmapped": session_store_db.dump({"value": "unmapped"})})
    _audit(pg_conn, "s-backfill-old", "Owner@Example.com", 1)
    _audit(pg_conn, "s-backfill-new", "owner@example.com", 2)
    pg_conn.commit()

    migrate.apply(pg_conn)
    pg_conn.commit()

    row = pg_conn.execute(text(
        "select payload from app.user_state "
        "where principal_key='user:owner@example.com' and key='notes'"
    )).first()
    assert session_store_db.pickle.loads(row.payload) == {"value": "new"}
    assert pg_conn.execute(text(
        "select count(*) from app.user_state_archive "
        "where session_id='s-backfill-old' and reason='older_session_for_principal'"
    )).scalar() == 1
    assert pg_conn.execute(text(
        "select count(*) from app.session_state where session_id='s-backfill-unmapped'"
    )).scalar() == 1
