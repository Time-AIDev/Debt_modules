"""Cold publication must preserve a customer writer that commits at its barrier."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
import threading
import time
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from app import business_records, cases, db, main, migrate, read_projection, request_context, session
from app.config import settings
from app.production_runtime import BookRefreshRequired
from app.production_unit import CURRENT, LOCK_KEY, ProductionUnitMiddleware, flush
from app.routers.today import router


@contextmanager
def publication_unit(conn, customer_uid=None, mutation=False, book_exclusive=True):
    slot = "TEST-publication:" + uuid.uuid4().hex
    unit = {"conn": conn, "capacity": True, "mutation": mutation, "book_exclusive": book_exclusive,
            "subject": "TEST-publication-owner", "version": 0}
    if customer_uid:
        unit["customer_uid"] = customer_uid
    tokens = (CURRENT.set(unit), session.CURRENT.set(slot), session.TOUCHED.set(set()),
              main._VIEW_MEMO.set({}), request_context.begin_read())
    try:
        yield unit
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
def publication(pg_conn, pg_url, monkeypatch):
    """One genuine synthetic domain customer; all writes stay in disposable PG."""
    migrate.apply(pg_conn)
    pg_conn.execute(text(Path(read_projection.__file__).with_name("capacity_schema.sql").read_text()))
    pg_conn.execute(text("update app.schema_version set version=3 where singleton"))
    pg_conn.commit()
    customer = main.CUSTOMERS[0]
    monkeypatch.setattr(main, "CUSTOMERS", [customer])
    monkeypatch.setattr(main, "IDENTITIES", [])
    monkeypatch.setattr(main, "BY_CUSTOMER", {customer.uid: customer})
    monkeypatch.setattr(main, "BY_CONTRACT", {contract.uid: (customer, contract) for contract in customer.contracts})
    from app import production_runtime
    # The fixture is the domain seed, not an imported landing snapshot. Keep its
    # book while exercising the actual SQL publication and financial serializers.
    monkeypatch.setattr(production_runtime, "prepare_book", lambda **_kwargs: None)
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("VOLT_INDEXED_READS_ENABLED", "true")
    monkeypatch.setenv("VOLT_CUSTOMER_SCOPES_ENABLED", "true")
    db.reset()
    with publication_unit(pg_conn):
        generation = read_projection.rebuild(pg_conn)
    pg_conn.commit()
    # Same epoch/day, different interpretation: the real HTTP GET must retry
    # under the exclusive publication barrier rather than serve this generation.
    pg_conn.execute(text("update app.projection_generation set metadata=metadata||"
                         "jsonb_build_object('code_fingerprint','TEST-old-interpretation') where id=:g"),
                    {"g": generation})
    pg_conn.commit()
    yield pg_conn, customer.uid, generation
    if pg_conn.in_transaction():
        pg_conn.rollback()
    db.reset()


def customer_writer(conn, uid):
    conn.execute(text("select pg_advisory_xact_lock_shared(:k)"), {"k": LOCK_KEY})
    conn.execute(text("select pg_advisory_xact_lock(hashtextextended(:u,0))"), {"u": "volt-customer:" + uid})
    with publication_unit(conn, uid, mutation=True, book_exclusive=False):
        state = cases.for_current()
        case = state.cases[uid]
        due = str(settings.business_date + timedelta(days=1))
        cases.set_next_action(state, case, "CALL", due, by="TEST operator", note="TEST publication concurrency")
        note = cases.add_case_note(state, case, "TEST note committed while publication waits", "TEST operator")
        assert flush() is True
        read_projection.refresh_customers(conn, {uid})
        conn.execute(text("update app.customer_version set version=version+1 where customer_uid=:u"), {"u": uid})
        conn.execute(text("update app.business_version set version=version+1 where singleton"))
    return note["uid"], due


def note_proof(conn, uid, note_uid):
    rows = conn.execute(text("select id,payload,payload::text as encoded from app.business_list_record "
                             "where store_key='cases.state' and attribute='events' and customer_uid=:u order by id"),
                        {"u": uid}).mappings()
    matching = [row for row in rows if business_records.decode(row["payload"]).get("uid") == note_uid]
    assert len(matching) == 1
    return matching[0]["id"], matching[0]["encoded"]


def assert_preserved(conn, uid, note_uid, due, proof):
    assert note_proof(conn, uid, note_uid) == proof
    with publication_unit(conn):
        saved, found = business_records.load(conn, "cases.state")
        assert found and saved.cases[uid]["next_action"] == "CALL"
        assert saved.cases[uid]["next_action_on"] == due
        assert sum(row.get("uid") == note_uid for row in saved.events) == 1


def test_exclusive_cold_http_read_waits_for_writer_then_publishes_its_committed_work(publication):
    writer, uid, old_generation = publication
    note_uid, due = customer_writer(writer, uid)
    proof = note_proof(writer, uid, note_uid)
    writer_pid = writer.execute(text("select pg_backend_pid()")).scalar_one()
    waiting, reader_pids, isolation = threading.Event(), [], []

    def observe_global_barrier(conn, _cursor, statement, parameters, _context, _many):
        if "pg_advisory_xact_lock(:" in statement:
            return  # SQLAlchemy has already rendered placeholders for psycopg.
        if "pg_advisory_xact_lock(" in statement and parameters.get("k") == LOCK_KEY:
            reader_pids.append(conn.connection.driver_connection.info.backend_pid)
            isolation.append(conn.get_isolation_level())
            waiting.set()

    target = db.engine()
    event.listen(target, "before_cursor_execute", observe_global_barrier)
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
    try:
        with TestClient(app, raise_server_exceptions=False) as client, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.get, "/v1/workbook")
            try:
                assert waiting.wait(3), "Cold GET did not acquire the actual global publication barrier"
                deadline = time.monotonic() + 3
                while not writer.execute(text("select :w=any(pg_blocking_pids(:r))"),
                                         {"w": writer_pid, "r": reader_pids[0]}).scalar_one():
                    assert time.monotonic() < deadline, "Cold GET did not wait behind the customer writer"
                    time.sleep(.01)
                assert not future.done()
                assert isolation[0] == "READ COMMITTED"
                writer.commit()
                response = future.result(timeout=10)
            finally:
                if writer.in_transaction():
                    writer.rollback()
            assert response.status_code == 200, response.text
            row = next(row for row in response.json()["rows"] if row["customer"]["uid"] == uid)
            assert row["case"]["next_action"] == "CALL" and row["case"]["next_action_on"] == due
            pointer = writer.execute(text("select generation,dirty from app.projection_current where singleton")).one()
            assert pointer.generation != old_generation and pointer.dirty is False
            assert_preserved(writer, uid, note_uid, due, proof)
    finally:
        event.remove(target, "before_cursor_execute", observe_global_barrier)


def test_raw_repeatable_read_snapshot_cannot_publish_over_a_newer_customer_commit(publication):
    writer, uid, _old_generation = publication
    with writer.engine.connect().execution_options(isolation_level="REPEATABLE READ") as stale:
        transaction = stale.begin()
        with publication_unit(stale):
            # Restore source state as well as the pointer before the other writer
            # commits. A lock acquired later cannot make this RR snapshot fresh.
            cases.for_current()
            stale.execute(text("select generation from app.projection_current where singleton")).scalar_one()
            note_uid, due = customer_writer(writer, uid)
            proof = note_proof(writer, uid, note_uid)
            writer.commit()
            before = writer.execute(text("select generation,ordering_version,dirty from app.projection_current where singleton")).one()
            generations = writer.execute(text("select count(*) from app.projection_generation")).scalar_one()
            with pytest.raises(DBAPIError) as rejected:
                read_projection.rebuild(stale)
            assert getattr(rejected.value.orig, "sqlstate", None) == "40001"
        transaction.rollback()
        after = writer.execute(text("select generation,ordering_version,dirty from app.projection_current where singleton")).one()
        assert after == before
        assert writer.execute(text("select count(*) from app.projection_generation")).scalar_one() == generations
        assert_preserved(writer, uid, note_uid, due, proof)


def test_scoped_rebuild_retries_before_upgrading_shared_locks_or_taking_build_lock(publication):
    writer, uid, _old_generation = publication
    with writer.engine.connect() as peer, peer.begin():
        writer.execute(text("set local lock_timeout='250ms'"))
        writer.execute(text("select pg_advisory_xact_lock_shared(:k)"), {"k": LOCK_KEY})
        writer.execute(text("select pg_advisory_xact_lock(hashtextextended(:u,0))"), {"u": "volt-customer:" + uid})
        peer.execute(text("select pg_advisory_xact_lock_shared(:k)"), {"k": LOCK_KEY})
        attempted = []

        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            attempted.append(statement)

        event.listen(writer, "before_cursor_execute", observe)
        try:
            with publication_unit(writer, uid, mutation=True, book_exclusive=False) as context:
                with pytest.raises(BookRefreshRequired):
                    read_projection.rebuild(writer)
                assert context["customer_uid"] == uid and "seeding" not in context
            assert attempted == []
        finally:
            event.remove(writer, "before_cursor_execute", observe)
        assert peer.execute(text("select pg_try_advisory_xact_lock(:k)"), {"k": read_projection.BUILD_LOCK}).scalar_one() is True
        assert peer.execute(text("select pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar_one() is False
