"""Board derivation history and its durable placement share publication."""
from copy import deepcopy

import pytest

from app import board, business_records, cases, journey, read_projection, session
from app.production_runtime import BookRefreshRequired
from app.production_unit import flush
from tests.test_scoped_projection_refresh import projected_book as _book_fixture, request_unit, rows

projected_book = _book_fixture


@pytest.mark.parametrize("commit", [True, False])
def test_override_expiry_is_immutable_atomic_history(projected_book, commit):
    conn = projected_book
    initial = rows(conn)
    uid = next(uid for uid,row in initial.items() if row["today"] is not None
               and row["workbook"]["board_column_id"] != board.ESCALATE
               and not row["workbook"]["board_override"])
    derived = initial[uid]["workbook"]["board_column_id"]
    override = board.AWAITING_PAYMENT if derived != board.AWAITING_PAYMENT else board.CALL_TODAY
    with request_unit(conn, mutation=True):
        journey.for_current().board_overrides[uid] = {
            "to_column_id":override, "derived_at_grant":derived,
            "approved_by":"TEST manager", "reason":"TEST approved fixture override"}
        flush()
        read_projection.rebuild(conn)
    conn.commit()
    before = deepcopy(rows(conn))
    with request_unit(conn):
        old_cases, _ = business_records.load(conn, "cases.state")
        old_events = deepcopy(old_cases.events)
    conn.commit()
    with request_unit(conn, uid, mutation=True):
        state = cases.for_current()
        cases.set_dc_status(state, state.cases[uid], "RETRIEVE_ASSET", by="TEST operator", note="TEST expire override")
        flush()
        read_projection.refresh_customers(conn, {uid})
        state, _ = business_records.load(conn, "cases.state")
        js, _ = business_records.load(conn, "journey.state")
        expiry = [event for event in state.events if event.get("kind") == "BOARD_OVERRIDE_EXPIRED"]
        assert len(expiry) == 1
        assert expiry[0]["was_column_id"] == override and expiry[0]["now_column_id"] == board.ESCALATE
        assert uid not in js.board_overrides and js.board_last_served[uid] == board.ESCALATE
        assert rows(conn)[uid]["today"]["auto_moved"] is True
        assert rows(conn)[uid]["workbook"]["auto_moved"] is False
    conn.commit() if commit else conn.rollback()
    with request_unit(conn):
        state, _ = business_records.load(conn, "cases.state")
        js, _ = business_records.load(conn, "journey.state")
        if commit:
            assert uid not in js.board_overrides and js.board_last_served[uid] == board.ESCALATE
            assert sum(event.get("kind") == "BOARD_OVERRIDE_EXPIRED" and event.get("customer_uid") == uid
                       for event in state.events) == 1
        else:
            assert uid in js.board_overrides and js.board_last_served[uid] == override
            assert state.events == old_events and rows(conn) == before


def test_new_last_served_column_without_new_event_is_saved(projected_book):
    conn = projected_book
    uid = next(uid for uid,row in rows(conn).items() if row["today"] is not None)
    with request_unit(conn, uid, mutation=True):
        js = journey.for_current()
        js.board_last_served.pop(uid)
        flush()
    conn.commit()
    with request_unit(conn, uid, mutation=True):
        state = cases.for_current()
        before = deepcopy(state.events)
        read_projection.refresh_customers(conn, {uid})
        saved, _ = business_records.load(conn, "journey.state")
        assert saved.board_last_served[uid] == rows(conn)[uid]["workbook"]["board_column_id"]
        assert state.events == before  # placement changed without an appended movement
    conn.commit()
    with request_unit(conn):
        saved, _ = business_records.load(conn, "journey.state")
        assert uid in saved.board_last_served


def test_unexpected_peak_touch_cannot_reuse_cached_dependency(projected_book):
    from app import peak_documents
    conn = projected_book
    before = rows(conn)
    uid = next(uid for uid,row in before.items() if row["today"] is not None)
    with request_unit(conn, uid, mutation=True):
        session.TOUCHED.get().add(peak_documents._store)
        with pytest.raises(BookRefreshRequired):
            read_projection.refresh_customers(conn, {uid})
    conn.rollback()
    assert rows(conn) == before
