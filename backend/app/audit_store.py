"""Where the chain lives.

Configured database -> audit.entry, append-only and enforced by a trigger.
No database        -> a process-wide in-memory chain, with the same rules and the
                      same verify(), and `persisted()` says False so every reader
                      can say so on screen.

That second path is deliberate and follows db.py's own rule: RUNNING and REFUSING
are both honest, LEAKING is not. Running in memory and SAYING it is in memory is
running. Running in memory while looking persisted would be leaking.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import text

from . import audit, db
from .config import settings

MEMORY = audit.Chain()

_COLUMNS = ("seq", "at", "business_date", "actor_claimed", "actor_source",
            "session_id", "request_id", "verb", "route_template", "act",
            "subject_type", "subject_uid", "detail", "outcome", "status",
            "error_code", "prev_hash", "hash", "actor_role")

# `at` AND `seq` are both bound explicitly rather than left to the column's
# DEFAULT (now() / nextval()): the hash covers the exact `at` and `seq` values
# computed below, and letting Postgres supply either independently could store
# a DIFFERENT value than the one that was hashed, so a persisted row would fail
# its own verify(). The stored value and the hashed value must be the same
# value for every hashed column, not just `at` — `seq` is a bigserial PRIMARY
# KEY only for the convenience of a plain default when nothing else is writing
# concurrently; nothing here reads that default, because it cannot be trusted
# to agree with the value already baked into `hash`. Postgres sequences are not
# transactional — a failed insert under the chain lock would burn a nextval() and
# desynchronise the app-computed seq from the stored one, permanently, with no
# tampering at all. Binding :seq explicitly under the chain lock below is what
# keeps the two the same value.
_INSERT = text("""
    INSERT INTO audit.entry
        (seq, at, business_date, actor_claimed, actor_source, session_id, request_id,
         verb, route_template, act, subject_type, subject_uid, detail,
         outcome, status, error_code, prev_hash, hash, actor_role)
    VALUES
        (:seq, :at, :business_date, :actor_claimed, :actor_source, :session_id, :request_id,
         :verb, :route_template, :act, :subject_type, :subject_uid,
         CAST(:detail AS jsonb), :outcome, :status, :error_code, :prev_hash, :hash, :actor_role)
""")
# `RETURNING seq` used to be here; dead the moment `entry["seq"]` was bound
# explicitly above (Task 3's own fix for the bigserial-default bug) — nothing
# ever read the returned value.

# The chain lock. An advisory lock, not LOCK TABLE ... IN EXCLUSIVE MODE: that mode
# needs UPDATE, DELETE or TRUNCATE on the table (or ownership), and the service
# account is given SELECT and INSERT only (migrate.RUNTIME_GRANTS), so on staging
# every append failed "permission denied for table entry" from 2026-09-21 on. An
# advisory lock needs no table right. Five bytes ("AUDIT"), past int4, so no
# hashtext() key (customer_contact.py) and no four-byte key (CRML, PEAK) can equal it.
AUDIT_LOCK_KEY = 0x4155444954


def persisted():
    return db.configured()


def append(fields):
    # Both paths must agree on what an unknown key means. audit.Chain.append
    # (the in-memory path, reached below) already raises ValueError on a key
    # outside audit.FIELDS — Ruling 6: an unhashed field is an unprotected
    # field, and that must be a loud error, not a silent drop. The DB path
    # used to build its entry with {k: fields.get(k) for k in audit.FIELDS},
    # which drops a misspelled key instead of raising it — the same mistake
    # was a crash with no database and silent data loss with one. Checking
    # here, before either branch, makes both paths refuse the same way.
    unknown = set(fields) - set(audit.FIELDS)
    if unknown:
        raise ValueError("audit entry has fields the chain does not hash: %s"
                         % ", ".join(sorted(unknown)))
    if not persisted():
        return MEMORY.append(**fields)
    with db.connect() as conn:
        with conn.begin():
            # The chain head and the insert share one transaction, so two concurrent
            # requests cannot both chain from the same predecessor. FOR UPDATE would
            # need a row to lock; the chain lock is coarse and correct — every writer
            # to audit.entry comes through here — and this is a prototype writing a
            # few hundred rows a day, not a queue.
            #
            # SET LOCAL lock_timeout, scoped to this transaction only, and an advisory
            # wait honours it like any other: without it, a writer queued behind
            # another holding the chain lock waits with no cap of its own, tying up
            # one of the pool's 5+2 connections (db.py) for as long as the lock is
            # held. Enough of those queued at once and a LATER writer cannot even
            # check out a connection, and fails only after
            # riding out SQLAlchemy's own 30s pool timeout — a much slower, much
            # less legible failure than the one below.
            conn.execute(text("SET LOCAL lock_timeout = '2s'"))
            conn.execute(text("select pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
            head = conn.execute(text(
                "SELECT hash FROM audit.entry ORDER BY seq DESC LIMIT 1")).scalar()
            prev_hash = head or audit.GENESIS
            next_seq = conn.execute(text(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM audit.entry"
            )).mappings().one()["next"]

            entry = {k: fields.get(k) for k in audit.FIELDS}
            entry["seq"] = next_seq
            entry["at"] = _now_iso()
            entry["business_date"] = str(settings.business_date)
            entry["detail"] = fields.get("detail") or {}
            entry["prev_hash"] = prev_hash
            entry["hash"] = audit.hash_entry(entry, prev_hash)

            params = dict(entry)
            # default=str, matching audit.canonical(): without it, a `detail` value
            # that canonical() happily stringifies for hashing (a Decimal, a date)
            # raises TypeError right here instead — the entry hashes fine and then
            # the DB write crashes on the exact value the hash already covers.
            params["detail"] = json.dumps(entry["detail"], ensure_ascii=False, default=str)
            conn.execute(_INSERT, params)
            return entry


def read(filters, limit, before_seq):
    if not persisted():
        rows = list(reversed(MEMORY.entries()))
        rows = [r for r in rows if _matches(r, filters)]
        if before_seq:
            rows = [r for r in rows if r["seq"] < before_seq]
        return rows[:limit]
    where, params = ["1=1"], {"limit": limit}
    if filters.get("actor"):
        where.append("actor_claimed = :actor")
        params["actor"] = filters["actor"]
    if filters.get("act"):
        where.append("act = :act")
        params["act"] = filters["act"]
    if filters.get("subject_uid"):
        where.append("subject_uid = :subject_uid")
        params["subject_uid"] = filters["subject_uid"]
    if filters.get("since"):
        where.append("at >= :since")
        params["since"] = filters["since"]
    if filters.get("until"):
        where.append("at < :until")
        params["until"] = filters["until"]
    if filters.get("outcome"):
        where.append("outcome = :outcome")
        params["outcome"] = filters["outcome"]
    if filters.get("q"):
        where.append("(strpos(lower(coalesce(subject_uid, '')), lower(:q)) > 0 OR strpos(lower(coalesce(request_id, '')), lower(:q)) > 0 OR subject_uid = ANY(CAST(:subjects AS text[])) OR detail->'contract_terminated'->>'contract_uid' = ANY(CAST(:subjects AS text[])))")
        params["q"] = filters["q"]
        params["subjects"] = filters.get("matching_subjects") or []
    if before_seq:
        where.append("seq < :before_seq")
        params["before_seq"] = before_seq
    sql = ("SELECT %s FROM audit.entry WHERE %s ORDER BY seq DESC LIMIT :limit"
           % (", ".join(_COLUMNS), " AND ".join(where)))
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def distinct_values():
    """Every actor and act ever recorded, not just the ones on the page a reader
    happens to be looking at. The filter selects on this screen must offer a name
    that is somewhere in the whole log, or the one screen built for finding a
    particular person's actions among thousands quietly fails at its own job."""
    if not persisted():
        entries = MEMORY.entries()
        actors = sorted({e["actor_claimed"] for e in entries if e.get("actor_claimed")})
        acts = sorted({e["act"] for e in entries if e.get("act")})
        return {"actors": actors, "acts": acts}
    with db.connect() as conn:
        actors = [row[0] for row in conn.execute(text(
            "SELECT DISTINCT actor_claimed FROM audit.entry "
            "WHERE actor_claimed IS NOT NULL ORDER BY actor_claimed"))]
        acts = [row[0] for row in conn.execute(text(
            "SELECT DISTINCT act FROM audit.entry "
            "WHERE act IS NOT NULL ORDER BY act"))]
    return {"actors": actors, "acts": acts}


def actor_source_counts():
    """Delta-100 AL2: where every signing name in the WHOLE log came from — the
    '91% from a session' strip. Counted from the stored rows themselves, on both
    storage paths, so a page of 50 can never stand in for the log."""
    if not persisted():
        sources = [e.get("actor_source") or "NONE" for e in MEMORY.entries()]
        counts = {}
        for source in sources:
            counts[source] = counts.get(source, 0) + 1
    else:
        with db.connect() as conn:
            counts = {row[0] or "NONE": row[1] for row in conn.execute(text(
                "SELECT actor_source, COUNT(*) FROM audit.entry GROUP BY actor_source"))}
    total = sum(counts.values())
    from_session = counts.get("SESSION", 0)
    claimed = counts.get("HEADER", 0) + counts.get("BODY", 0) + counts.get("NONE", 0)
    test_account = counts.get("TEST_ACCOUNT", 0)

    def pct(n):
        return int(round(100.0 * n / total)) if total else None
    return {
        "total": total,
        "from_session": from_session,
        "from_test_account": test_account,
        "claimed": claimed,
        "none": counts.get("NONE", 0),
        "session_pct": pct(from_session),
        "test_account_pct": pct(test_account),
        "claimed_pct": pct(claimed),
    }


def verify():
    if not persisted():
        return {**MEMORY.verify(), "persisted": False}
    prev = audit.GENESIS
    verified = 0
    with db.connect() as conn:
        rows = conn.execute(text(
            "SELECT %s FROM audit.entry ORDER BY seq ASC" % ", ".join(_COLUMNS)
        )).mappings()
        for row in rows:
            entry = dict(row)
            # Two traps here, neither a real tamper:
            #  - str(datetime) and datetime.isoformat() disagree (space vs "T"),
            #    so re-hashing must use .isoformat() to match what append() hashed.
            #  - the session reads timestamptz back in the SERVER's zone (this
            #    Postgres reports Asia/Bangkok), not UTC, even though the column
            #    stores an absolute instant. append() hashed the UTC isoformat
            #    string, so the value must be normalised back to UTC before
            #    re-hashing, or every row fails verify() on its offset alone.
            entry["at"] = entry["at"].astimezone(timezone.utc).isoformat()
            entry["business_date"] = str(entry["business_date"])
            if entry["prev_hash"] != prev or entry["hash"] != audit.hash_entry(entry, prev):
                return {"ok": False, "broken_at": entry["seq"], "verified": verified,
                        "gaps_this_instance": len(MEMORY.gaps()), "complete": None,
                        "persisted": True}
            prev = entry["hash"]
            verified += 1
    # Ruling 20 (final review): MEMORY.gaps() only ever counted writes THIS
    # process failed to record. On more than one Cloud Run instance, a gap on
    # instance A is invisible to a `verify()` served by instance B — so reporting
    # it as "gaps" next to a "complete" boolean asserted log-wide completeness
    # from a per-instance counter. Not fixable by building distributed gap
    # tracking (out of scope, and a different kind of feature); fixed by scoping
    # the CLAIM instead: the field name says what it actually counts, and
    # `complete` is None — not True, not False — because completeness is not a
    # claim this instance can make about the whole log once the log is shared.
    # The in-memory (unpersisted) path above is exempt: there is exactly one
    # process holding the entire log, so "gaps" and "complete" there are already
    # log-wide, not per-instance.
    return {"ok": True, "broken_at": None, "verified": verified,
            "gaps_this_instance": len(MEMORY.gaps()), "complete": None, "persisted": True}


def record_gap(why):
    MEMORY.record_gap(why)


def _matches(row, filters):
    for key, column in (("actor", "actor_claimed"), ("act", "act"),
                        ("subject_uid", "subject_uid")):
        if filters.get(key) and row.get(column) != filters[key]:
            return False
    # Final-review finding: `since` was accepted by the router and bound into the
    # DB query, but never checked here — the in-memory path returned every row,
    # unfiltered, with nothing on the response to say so. The router now hands
    # down a parsed, timezone-aware datetime (see routers/audit.py's
    # `_parse_since`); `at` is stored as an ISO string, so it is parsed back for
    # the comparison.
    if filters.get("outcome") and row.get("outcome") != filters["outcome"]:
        return False
    if filters.get("q"):
        q = filters["q"].casefold()
        if not (q in str(row.get("subject_uid") or "").casefold() or q in str(row.get("request_id") or "").casefold() or row.get("subject_uid") in (filters.get("matching_subjects") or []) or ((row.get("detail") or {}).get("contract_terminated") or {}).get("contract_uid") in (filters.get("matching_subjects") or [])):
            return False
    until = filters.get("until")
    if until is not None:
        at = row.get("at")
        row_at = datetime.fromisoformat(at) if isinstance(at, str) else at
        if row_at is None or row_at >= until:
            return False
    since = filters.get("since")
    if since is not None:
        at = row.get("at")
        try:
            row_at = datetime.fromisoformat(at) if isinstance(at, str) else at
        except ValueError:
            return False
        if row_at is None or row_at < since:
            return False
    return True


def _now_iso():
    return datetime.now(timezone.utc).isoformat()
