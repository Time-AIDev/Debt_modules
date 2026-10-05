"""Test isolation.

The app holds its state in module-level singletons — there is no database in the
prototype. Without a reset between tests the suite is order-dependent: one test spends
a customer's daily contact slot and a later one sees a 409 it never caused, and the
column-deletion test permanently moves customers onto a different board column.

Tests that pass alone and fail together are worse than tests that fail, because the
failure looks like a product bug. This fixture makes each test start from seed.
"""
import os

# The business date follows today in Bangkok when a database is configured
# (config.resolve_business_date). The suite runs on the demo date whatever the
# calendar says, database tests included — pinned BEFORE the app is imported.
os.environ.setdefault("VOLT_BUSINESS_DATE", "2026-10-23")

import pytest  # noqa: E402

from app import main  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_app_state(tmp_path):
    os.environ["TERMINATION_ARCHIVE_PATH"] = str(tmp_path / "archive.sqlite3")
    from app.fixtures import seed

    from app import customer_search, journey
    from app import orders as orders_domain

    from app import book as _book
    from app.fixtures import identities as _identities, seed as _seed
    _book.invalidate()               # book.build() is cached since 2026-09-20
    loaded = _book.build()
    main.CUSTOMERS = _seed(loaded)
    taken = {c.uid for c in main.CUSTOMERS}
    main.IDENTITIES = [c for c in _identities(loaded) if c.uid not in taken]
    main.BY_CUSTOMER = {c.uid: c for c in main.CUSTOMERS + main.IDENTITIES}
    main.BY_CONTRACT = {k.uid: (c, k) for c in main.CUSTOMERS for k in c.contracts}
    # Task 10 fix round 1 (Minor): the book is rebuilt above on every test, but
    # payment_position's memoised sheet capture date was never forgotten with it —
    # a DB-backed test could leak a stale capture date into the next test. Imported
    # here, not at module level, to match this fixture's own local-import style.
    from app import payment_position
    payment_position.forget_capture_date()
    main.contact_log.reset()          # J-12c: the contact log is per session now
    main._RETRACTABLE.clear()
    main._IDEMPOTENCY.clear()
    journey.reset()
    customer_search.reset()
    orders_domain.reset()
    from app import clock, dictionaries, cases, peak_documents, invoice_pipeline
    clock.reset()                     # Round-3 J3-19: one business clock, per test
    dictionaries.reset()
    cases.reset()
    peak_documents.reset()
    invoice_pipeline.reset()
    from app import reports
    from app.money import band_sets
    reports.reset()                   # J-52: weekly snapshots are per session
    band_sets.INACTIVE_SETS.clear()   # J-54: deactivation is process-wide state
    from app import data_epoch, refresh
    data_epoch.reset_cache()          # 2026-09-20 sync audit: the epoch is process-cached
    refresh.reset()                   # and the last landing refresh is process-wide
    from app import import_sync
    import_sync.reset()               # and a session's seen epoch must not leak between tests
    from app import workbook_exports
    workbook_exports.reset()          # Round-5 rulings 72/74: the export log is per session
    from app import imports as imports_domain
    imports_domain.reset()            # Round-5 ruling 71: staged import runs are per session
    from app.attachments import store as attachments_store
    attachments_store.reset()         # Task 21: attachment memory store is per session
    from app import notices
    notices.reset()                   # Final fix F-H: notice memory store is per session, like the rest
    from app import customer_contact
    customer_contact.reset()          # WP9: person-entered phone numbers, memory store
    from app import payment_claims
    payment_claims.reset()             # amount-led pending claims and reminder idempotency
    from app.pipelines import schedule
    schedule.shutdown()               # no timer from an earlier test may mutate this one
    schedule.reset()                  # 2026-09-21: the crm.lead refetch is on by default
    main.BOARD_COLUMNS[:] = [
        {"column_id": "col_01H8X", "name": "Call today", "order": 1},
        {"column_id": "col_01H8Y", "name": "Awaiting payment", "order": 2},
        {"column_id": "col_01H8Z", "name": "Promise made", "order": 3},
        {"column_id": "col_01H90", "name": "Escalate", "order": 4},
    ]
    yield
    schedule.shutdown()


@pytest.fixture(scope="session")
def pg_url():
    """The local test database, or a skip.

    Skipping and not failing is deliberate: the suite must stay green on a machine
    with no Postgres, and infra/cloudbuild.yaml runs pytest in a bare
    python:3.12-slim container that has none. Start one with scripts/pg_local.sh.
    """
    import os

    url = os.environ.get("VOLT_TEST_PG_URL")
    if not url:
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent / "scripts"))
            import pg_local
            url = pg_local.url()
        except Exception:
            pytest.skip("no local Postgres; run ./scripts/pg_local.sh start")
    return url


@pytest.fixture
def pg_conn(pg_url):
    """A connection whose rows never outlive the test.

    Rollback alone is not enough: some tests must commit, because the code under
    test opens its OWN connection and would not otherwise see the rows. So teardown
    rolls back whatever is still open AND truncates — and truncates even when the
    test failed, because a leaked row makes the next test lie.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url, future=True)
    conn = engine.connect()
    try:
        yield conn
    finally:
        try:
            if conn.in_transaction():
                conn.rollback()
            existing = conn.execute(text(
                "select table_schema, table_name from information_schema.tables "
                "where table_schema in ('landing','app')")).fetchall()
            if existing:
                names = ", ".join('%s."%s"' % (schema, table) for schema, table in existing)
                conn.execute(text("truncate %s restart identity cascade" % names))
                conn.commit()
        finally:
            conn.close()
            engine.dispose()


@pytest.fixture(autouse=True)
def _clear_persisted_session_state():
    """With DATABASE_URL set, session state outlives the process — which is the
    point in production and poison in a test suite. fresh_app_state resets the
    in-memory stores; this clears their rows, so a test still starts from seed
    whether or not a database is configured.

    Purely additive: it resets no assertion and touches no existing fixture.
    """
    from app import session as _session

    _session.clear_all_persisted()
    yield
