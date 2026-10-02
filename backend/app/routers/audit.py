"""Reading the log back. There is no writing route here, and there is no
mutating route anywhere — not guarded, absent."""
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from .. import audit_store, errors

router = APIRouter()

MAX_PAGE = 200


def _parse_since(value):
    """`since` as an ISO date or datetime, or a 422 through the project's normal
    Problem shape — never an unfiltered result and never a bare 500.

    Final-review finding: this used to reach the DB path as a raw string bound
    straight into `at >= :since`, so `since=xyz` fell through to Postgres and came
    back as an unhandled 500, and on the in-memory path it was silently ignored
    outright — accepted, and then never applied. Both halves were wrong in the
    same call: one over-trusted the input, the other dropped it. Parsing once,
    here, fixes both: a bad value never reaches either storage path, and a good
    one is a real, timezone-aware instant both paths can compare against.
    """
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            # A bare date names the whole day, from its first instant, UTC.
            dt = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise errors.validation_failed([{
            "pointer": "/since", "code": "not_a_date",
            "message": "since must be an ISO date (YYYY-MM-DD) or datetime",
            "message_th": "รูปแบบวันที่ของ since ไม่ถูกต้อง"}])


def _signing_source(counts):
    """Delta-100 AL2: the '91% from a session' strip, computed from the whole log —
    value and note in both languages, with the raw counts beside them so a reader
    can check the arithmetic. The prototype's note ('the rest are badged as
    claimed') is served only when it is literally true; TEST_ACCOUNT rows get an
    honest sentence naming them instead."""
    total = counts["total"]
    if total == 0:
        return {**counts, "value_th": None, "value_en": None,
                "note_th": "ยังไม่มีรายการในบันทึก", "note_en": "No entries in the log yet"}
    value_th = "%d%% จากการเข้าสู่ระบบ" % counts["session_pct"]
    value_en = "%d%% from a session" % counts["session_pct"]
    only_claimed = counts["claimed"] == total - counts["from_session"]
    note_th = "ที่เหลือติดป้ายว่าอ้างเอง" if only_claimed else "ที่เหลือมาจากชื่อที่อ้างเองหรือบัญชีทดสอบ"
    note_en = ("The rest are badged as claimed" if only_claimed
               else "The rest come from claimed names or test accounts")
    return {**counts, "value_th": value_th, "value_en": value_en,
            "note_th": note_th, "note_en": note_en}


# D4, Arina: everyone sees everything. There is deliberately NO role check here and
# no per-officer filtering — an officer may read every act by anyone. Stated rather
# than merely absent, so a later reader does not "fix" a missing gate that was a
# decision.
@router.get("/v1/audit")
def read_audit(actor: str = Query(default=None), act: str = Query(default=None),
               subject_uid: str = Query(default=None), since: str = Query(default=None),
               limit: int = Query(default=50), before_seq: int = Query(default=None)):
    limit = max(1, min(int(limit or 50), MAX_PAGE))
    filters = {"actor": actor, "act": act, "subject_uid": subject_uid,
               "since": _parse_since(since)}
    entries = audit_store.read(filters, limit=limit, before_seq=before_seq)
    # The filter options come from the WHOLE log, not from the page just read: a
    # name that fell off the first page must still be a choosable filter, or the
    # one screen built for finding a particular person's actions among thousands
    # cannot find someone who isn't on screen already.
    distinct = audit_store.distinct_values()
    return {
        "entries": entries,
        "meta": {
            "count": len(entries),
            # Paging is by seq, not by offset: the log only grows at the head, so an
            # offset would re-show rows as new ones arrive mid-read.
            "next_before_seq": entries[-1]["seq"] if len(entries) == limit else None,
            "persisted": audit_store.persisted(),
            "actors": distinct["actors"],
            "acts": distinct["acts"],
            # Delta-100 AL2: the strip's own statistic, over the whole log.
            "signing_source": _signing_source(audit_store.actor_source_counts()),
        },
    }


@router.get("/v1/audit/verify")
def verify_audit():
    return audit_store.verify()
