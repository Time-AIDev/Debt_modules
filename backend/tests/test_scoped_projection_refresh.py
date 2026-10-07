"""Scoped derivation preserves financial rows without reading the portfolio."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import uuid

import pytest
from sqlalchemy import text

from app import cases, db, journey, main, migrate, read_projection, request_context, session, today
from app.config import settings
from app.production_unit import CURRENT, flush
from app.routers.today import _legacy_workbook


@contextmanager
def request_unit(conn, uid=None, mutation=False):
    slot = "TEST-scoped-projection:" + uuid.uuid4().hex
    value = {"conn": conn, "capacity": True, "mutation": mutation,
             "book_exclusive": uid is None, "subject": "TEST-owner", "version": 0}
    if uid:
        value["customer_uid"] = uid
    tokens = (CURRENT.set(value), session.CURRENT.set(slot), session.TOUCHED.set(set()),
              main._VIEW_MEMO.set({}), request_context.begin_read())
    try:
        yield value
    finally:
        for store in session.REGISTRY:
            store._by_session.pop(slot, None)
            store._written.pop(slot, None)
        request_context.end_read(tokens[4])
        main._VIEW_MEMO.reset(tokens[3])
        session.TOUCHED.reset(tokens[2])
        session.CURRENT.reset(tokens[1])
        CURRENT.reset(tokens[0])


@pytest.fixture
def projected_book(pg_conn, pg_url, monkeypatch):
    from app import production_runtime
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setattr(production_runtime, "prepare_book", lambda **_kwargs: None)
    db.reset()
    with request_unit(pg_conn):
        read_projection.rebuild(pg_conn)
    pg_conn.commit()
    yield pg_conn
    if pg_conn.in_transaction():
        pg_conn.rollback()
    db.reset()


def rows(conn):
    return {row["customer_uid"]: dict(row) for row in conn.execute(text(
        "select p.* from app.customer_projection p join app.projection_current c on p.generation=c.generation"
    )).mappings()}


def blocked(*_args, **_kwargs):
    raise AssertionError("Scoped refresh must not read the collection portfolio")


def test_selected_today_rows_equal_default_rows_without_portfolio_metadata(monkeypatch):
    expected = today.build()
    assert expected["items"]
    selected = [journey.customer_by_uid(row["customer"]["uid"]) for row in expected["items"][:2]]
    expected_rows = {row["customer"]["uid"]: row for row in expected["items"][:2]}
    with monkeypatch.context() as scoped:
        for name in ("book_customers", "identity_customers"):
            scoped.setattr(journey, name, blocked)
        for name in ("officer_totals", "known_officers", "unassigned_total"):
            scoped.setattr(today, name, blocked)
        actual = today.build(_customers=selected, _rows_only=True)
    assert set(actual) == {"items"}
    assert {row["customer"]["uid"]: row for row in actual["items"]} == expected_rows
    assert today.build() == expected  # default API metadata, sort and money unchanged


@pytest.mark.parametrize("entity", ["SPV", "EPC"])
def test_scoped_action_projection_matches_legacy_and_preserves_other_rows(projected_book, monkeypatch, entity):
    from app import book_source, landing
    from app.routers import today as router
    conn = projected_book
    uid = next(uid for uid, row in rows(conn).items()
               if not row["identity_only"] and row["today"] is not None and row["entity"] == entity)
    before = rows(conn)
    metadata = conn.execute(text("select metadata from app.projection_generation where id="
                                 "(select generation from app.projection_current where singleton)")).scalar_one()
    with request_unit(conn):
        cursor = read_projection.workbook({}, limit=1)["page"]["next_cursor"]
        baseline_total = read_projection.workbook({})["meta"]["total"]
    conn.commit()
    with request_unit(conn, uid, mutation=True):
        cs = cases.for_current()
        cases.set_next_action(cs, cs.cases[uid], "CALL", str(settings.business_date + timedelta(days=2)),
                              by="TEST operator", note="TEST next action")
        cases.add_case_note(cs, cs.cases[uid], "TEST isolated note", "TEST operator")
        assert flush()
        with monkeypatch.context() as scoped:
            scoped.setattr(router, "_legacy_workbook", blocked)
            scoped.setattr(book_source, "source_summary", blocked)
            scoped.setattr(landing, "count_customers", blocked)
            scoped.setattr(landing, "resolved_customers", blocked)
            scoped.setattr(journey, "book_customers", blocked)
            scoped.setattr(journey, "identity_customers", blocked)
            scoped.setattr(today.pkd, "for_current", blocked)
            for name in ("officer_totals", "known_officers", "unassigned_total"):
                scoped.setattr(today, name, blocked)
            read_projection.refresh_customers(conn, {uid})
    conn.commit()
    after = rows(conn)
    assert all(after[key] == value for key, value in before.items() if key != uid)
    assert after[uid]["overdue"] == before[uid]["overdue"]
    assert after[uid]["outstanding"] == before[uid]["outstanding"]
    assert after[uid]["workbook"]["case"]["next_action"] == "CALL"
    assert after[uid]["workbook"]["invoice_state"] == before[uid]["workbook"]["invoice_state"]
    assert conn.execute(text("select metadata from app.projection_generation where id="
                             "(select generation from app.projection_current where singleton)")).scalar_one() == metadata
    with request_unit(conn):
        expected_book = next(row for row in _legacy_workbook(identities="1", _projection_all=True)["rows"]
                             if row["customer"]["uid"] == uid)
        expected_today = next(row for row in today.build()["items"] if row["customer"]["uid"] == uid)
        today.annotate_worked([expected_today], settings.business_date)
        assert after[uid]["workbook"] == expected_book
        assert after[uid]["today"] == expected_today
        assert read_projection.workbook({})["meta"]["total"] == baseline_total
        if cursor:
            with pytest.raises(Exception) as stale:
                read_projection.workbook({}, limit=1, cursor=cursor)
            assert stale.value.code == "workbook_cursor_stale"


@pytest.mark.parametrize("status", ["CLOSED", "TERMINATED"])
def test_closed_scope_keeps_legacy_row_and_stays_off_today(projected_book, status):
    conn = projected_book
    uid = next(uid for uid, row in rows(conn).items() if not row["identity_only"] and row["today"] is not None)
    with request_unit(conn, uid, mutation=True):
        cs = cases.for_current()
        cs.cases[uid]["payment_status"] = status
        flush()
        read_projection.refresh_customers(conn, {uid})
    conn.commit()
    actual = rows(conn)[uid]
    assert actual["today"] is None
    with request_unit(conn):
        expected = next(row for row in _legacy_workbook()["rows"] if row["customer"]["uid"] == uid)
    assert actual["workbook"] == expected
    assert actual["workbook"]["tier"] == "ROUTINE"


def test_rollback_never_publishes_scoped_case_or_projection(projected_book):
    conn = projected_book
    uid = next(uid for uid, row in rows(conn).items() if not row["identity_only"] and row["today"] is not None)
    before = deepcopy(rows(conn))
    ordering = conn.execute(text("select ordering_version from app.projection_current where singleton")).scalar_one()
    conn.commit()
    with request_unit(conn, uid, mutation=True):
        cs = cases.for_current()
        cases.set_next_action(cs, cs.cases[uid], "CALL", str(settings.business_date + timedelta(days=3)),
                              by="TEST operator", note="TEST rolled-back action")
        flush()
        read_projection.refresh_customers(conn, {uid})
        with conn.engine.connect() as reader:
            assert rows(reader) == before
    conn.rollback()
    assert rows(conn) == before
    assert conn.execute(text("select ordering_version from app.projection_current where singleton")).scalar_one() == ordering


def test_identity_and_absent_preinstall_never_gain_collection_money(projected_book, monkeypatch):
    from types import SimpleNamespace
    conn = projected_book
    identity = SimpleNamespace(uid="TEST-identity", customer_no="TEST-id", display_name="TEST identity",
                               contracts=[], product="LEASE", sheet={}, data_source={"identity":"ODOO"})
    monkeypatch.setattr(main, "BY_CUSTOMER", {**main.BY_CUSTOMER, identity.uid: identity})
    monkeypatch.setattr(main, "IDENTITIES", [*main.IDENTITIES, identity])
    with request_unit(conn, identity.uid, mutation=True):
        read_projection.refresh_customers(conn, {identity.uid})
    actual = rows(conn)[identity.uid]
    assert actual["today"] is None and actual["identity_only"] is True
    assert actual["overdue"] == actual["outstanding"] == 0
    assert actual["workbook"]["case"]["payment_status"] is None
    with request_unit(conn):
        expected = next(row for row in _legacy_workbook(identities="1", _projection_all=True)["rows"]
                        if row["customer"]["uid"] == identity.uid)
    assert actual["workbook"] == expected
    with request_unit(conn, "TEST-preinstall-absent", mutation=True):
        read_projection.refresh_customers(conn, {"TEST-preinstall-absent"})
    assert "TEST-preinstall-absent" not in rows(conn)


@pytest.mark.parametrize("commit", [True, False])
def test_board_transition_keeps_news_flags_and_atomic_history(projected_book, commit):
    from app import board, business_records
    conn = projected_book
    before = rows(conn)
    uid = next(uid for uid, row in before.items() if row["today"] is not None
               and row["workbook"]["board_column_id"] != board.ESCALATE
               and not row["workbook"]["board_override"])
    with request_unit(conn):
        old_journey, _ = business_records.load(conn, "journey.state")
        old_cases, _ = business_records.load(conn, "cases.state")
        old_column = old_journey.board_last_served[uid]
        old_events = deepcopy(old_cases.events)
    conn.commit()
    with request_unit(conn, uid, mutation=True):
        cs = cases.for_current()
        cases.set_dc_status(cs, cs.cases[uid], "RETRIEVE_ASSET", by="TEST operator", note="TEST retrieve status")
        flush()
        read_projection.refresh_customers(conn, {uid})
        actual = rows(conn)[uid]
        assert actual["today"]["auto_moved"] is True
        assert actual["today"]["auto_moved_cause"] == "CASE_CHANGED"
        assert actual["workbook"]["auto_moved"] is False
        assert actual["workbook"]["auto_moved_cause"] is None
        saved_journey, _ = business_records.load(conn, "journey.state")
        saved_cases, _ = business_records.load(conn, "cases.state")
        assert saved_journey.board_last_served[uid] == board.ESCALATE
        moves = [event for event in saved_cases.events if event.get("kind") == "BOARD_AUTO_MOVED"]
        assert len(moves) == 1 and moves[0]["from_column_id"] == old_column
        with conn.engine.connect() as observer:
            assert rows(observer) == before
    conn.commit() if commit else conn.rollback()
    with request_unit(conn):
        saved_journey, _ = business_records.load(conn, "journey.state")
        saved_cases, _ = business_records.load(conn, "cases.state")
        if commit:
            assert saved_journey.board_last_served[uid] == board.ESCALATE
            assert sum(event.get("kind") == "BOARD_AUTO_MOVED" and event.get("customer_uid") == uid
                       for event in saved_cases.events) == 1
            expected = next(row for row in _legacy_workbook()["rows"] if row["customer"]["uid"] == uid)
            assert rows(conn)[uid]["workbook"] == expected
        else:
            assert saved_journey.board_last_served[uid] == old_column
            assert saved_cases.events == old_events
            assert rows(conn) == before


def test_scope_reuses_only_unchanged_peak_waiting_after_global_publication(projected_book, monkeypatch):
    from app import peak_documents
    conn = projected_book
    uid = next(uid for uid, row in rows(conn).items() if row["today"] is not None)
    with request_unit(conn, mutation=True):
        docs = peak_documents.for_current()
        docs.documents.update({
            "TEST-own-rejected": {"uid":"TEST-own-rejected", "customer_uid":uid,
                                  "state":"REJECTED", "rejection_reason":"TEST own rejection"},
            "TEST-other-rejected": {"uid":"TEST-other-rejected", "customer_uid":"TEST-other",
                                    "state":"REJECTED", "rejection_reason":"TEST unrelated rejection"},
        })
        flush()
        read_projection.rebuild(conn)
    conn.commit()
    for state in ("REJECTED", "DRAFT_CREATED"):
        if state == "DRAFT_CREATED":
            with request_unit(conn, mutation=True):
                peak_documents.for_current().documents["TEST-own-rejected"]["state"] = state
                flush()
                read_projection.rebuild(conn)
            conn.commit()
        with request_unit(conn, uid, mutation=True):
            cs = cases.for_current()
            cs.today_items.append({"uid":"TEST-new-waiting-" + state, "customer_uid":uid,
                                   "kind":"REVIEW_ANSWERED", "done":False})
            flush()
            with monkeypatch.context() as scoped:
                scoped.setattr(peak_documents, "for_current", blocked)
                read_projection.refresh_customers(conn, {uid})
        conn.commit()
        actual = rows(conn)[uid]
        waiting = actual["today"]["waiting"]
        assert any(entry["kind"] == "REVIEW_ANSWERED" for entry in waiting)
        rejected = [entry for entry in waiting if entry["kind"] == "PEAK_REJECTED"]
        assert rejected == ([{"kind":"PEAK_REJECTED", "ref":"TEST-own-rejected", "text":"TEST own rejection"}]
                            if state == "REJECTED" else [])
        with request_unit(conn):
            expected = next(row for row in _legacy_workbook()["rows"] if row["customer"]["uid"] == uid)
        assert actual["workbook"] == expected
