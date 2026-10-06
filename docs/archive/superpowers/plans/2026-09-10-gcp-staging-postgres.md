# GCP Staging, Cloud SQL and the Sheet-Shaped Landing Schema — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put PostgreSQL underneath the Volt Debt prototype on `volt-debt-stg`, so a Cloud Run revision restart no longer destroys a tester's work and Odoo data lands in the same schema the sheet lands in.

**Architecture:** Two Postgres schemas — `landing` for ingested source data shaped like the *New Order Master* sheet, `app` for per-tester state. The 32 domain modules are untouched because the change stops at two seams the code already respects: `book.load_sheet()` (one function, returns the whole payload dict) and `session.Store` (one class, four methods). A thin GCP estate — one Cloud Run service, Cloud SQL reached by the native connector, two Cloud Run Jobs, one Scheduler job.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 Core (already in `requirements.txt`, currently unused), psycopg 3, PostgreSQL 16, Cloud Run, Cloud SQL, Secret Manager, Cloud Scheduler, gcloud CLI.

**Spec:** `docs/archive/superpowers/specs/2026-09-10-gcp-staging-postgres-design.md` (commit `a13b5d6`). Diagrams: `pictures/GCP design/` (commit `d8f58c6`).

## Global Constraints

- **Test contract: 569 backend passed / 1 skipped · 443 frontend (33 files) · 29 e2e.** `./scripts/verify_all.sh` is the authority.
- **A test that must change is escalated to Arina, never edited.** Adding tests is free. If a task cannot proceed without editing an existing test, **that task stops and asks**. Edit 17 is authorised but RESERVED for ruling 74 and is not a spare.
- **Run `pytest` without `-q`.** `backend/pytest.ini:4` already sets it; passing it again double-suppresses into bare dots that read exactly like a failure.
- **Credentials never appear in code, logs, commits or chat.** Only variable NAMES travel. `backend/.env` is gitignored.
- **Region `asia-southeast1`. Project `volt-debt-stg`.** Resource naming follows GCP Architecture v1.0 §3.2: `debt-{role}` services, `debt-{job}` jobs, `debt-pg-{env}` instances, `UPPER_SNAKE` secrets.
- **Money stays `Decimal`.** Never round-trip a monetary value through `float`.
- **No GCP resource may be created until Arina has authenticated** (`gcloud auth login`). Every provisioning script must support `--dry-run` and print the exact command before running it.
- **`DATABASE_URL` unset must behave exactly as the code does today.** This is not a convenience; it is what keeps the 569 tests and `infra/cloudbuild.yaml`'s bare `python:3.12-slim` test step working.

---

## File Structure

**New files**

| File | Responsibility |
|---|---|
| `backend/app/db.py` | The engine, and the three-state rule. Nothing else touches `create_engine`. |
| `backend/app/schema.sql` | Idempotent DDL for both schemas. The single source of the shape. |
| `backend/app/migrate.py` | Applies `schema.sql`; `main()` is the `debt-migrate` Cloud Run Job entrypoint. |
| `backend/app/landing.py` | Writes and raw reads of the `landing` schema. Knows tables, not precedence. |
| `backend/app/book_source.py` | Precedence across the three rungs, and payload assembly. Knows precedence, not tables. |
| `backend/app/session_store_db.py` | The Postgres backing for `session.Store`. |
| `backend/app/jobs/odoo_sync.py` | The `debt-odoo-sync` Cloud Run Job entrypoint. |
| `scripts/provision_stg.sh` | Creates the estate with gcloud. `--dry-run` by default. |
| `scripts/pg_local.sh` | Installs and runs a rootless PostgreSQL 16 for the test suite. |
| `backend/tests/test_db_states.py` | The three-state rule. |
| `backend/tests/test_landing_schema.py` | DDL applies, is idempotent, and round-trips rows. |
| `backend/tests/test_book_source.py` | Precedence, and the unconfigured path. |
| `backend/tests/test_session_persistence.py` | Tester work survives a simulated restart. |
| `backend/tests/test_odoo_pagination.py` | Every order resolves a name. |

**Modified files**

| File | Change |
|---|---|
| `backend/requirements.txt` | Add `psycopg[binary]>=3.2`. |
| `backend/app/book.py:75-79` | `load_sheet()` delegates to `book_source.load()`. Four lines. |
| `backend/app/session.py` | `Store` gains a Postgres backing behind its existing interface. |
| `backend/app/integrations/odoo.py` | Writes `landing` instead of `var/odoo_snapshot.json`; partner fetch paginated. |
| `scripts/import_master_sheet.py` | Gains `--to-postgres`. |
| `infra/cloudbuild.yaml:12` | Remove the doubled `-q`. |
| `scripts/deploy_gcp.sh` | Attach Cloud SQL, secrets and `DATABASE_URL`. |

---

## Wave map

**Wave 1** — Tasks 1–3 block Wave 2. Tasks 10 and 12 are independent and start immediately.
**Wave 2** — Tasks 4–9, parallel once Task 3 lands.
**Wave 3** — Tasks 11 and 13.

---

### Task 1: A rootless PostgreSQL 16 for the test suite

There is no Docker and no Homebrew on this machine (`~/.volt-gcloud-env` records "no root, no Homebrew"). Postgres is installed under `$HOME`, the same pattern already used for the Python 3.12 that gcloud requires.

**Files:**
- Create: `scripts/pg_local.sh`
- Modify: `backend/tests/conftest.py` (append a fixture; do not touch `fresh_app_state`)
- Modify: `backend/requirements.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: `scripts/pg_local.sh start|stop|status|url`, which prints a URL of the form `postgresql+psycopg://volt@127.0.0.1:55432/volt_test`. A pytest fixture `pg_url` returning that string, and `pg_conn` returning a live SQLAlchemy connection. Tests that need a database request `pg_url`; **every other test must be unaffected.**

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_pg_harness.py`:

```python
"""The test database harness itself. If this file fails, nothing downstream is trustworthy."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("VOLT_TEST_PG_URL"),
                                reason="no local Postgres; run scripts/pg_local.sh start")


def test_pg_url_fixture_points_at_a_live_server(pg_conn):
    from sqlalchemy import text
    assert pg_conn.execute(text("select 1")).scalar() == 1


def test_server_is_postgres_16_or_newer(pg_conn):
    from sqlalchemy import text
    version = pg_conn.execute(text("show server_version")).scalar()
    assert int(version.split(".")[0]) >= 16, version
```

- [ ] **Step 2: Run it and watch it skip, then fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pg_harness.py -v`
Expected: 2 skipped (no server yet). This proves the guard works and that the suite is unaffected when Postgres is absent — which is the whole point.

- [ ] **Step 3: Write the harness** — REVISED 2026-09-10 during execution

The plan originally called for an EnterpriseDB tarball downloaded by hand. It is not
needed: the **`pgserver`** wheel ships relocatable PostgreSQL binaries and runs them
from a directory under `$HOME` over a unix socket — no root, no Homebrew, no Docker,
no port, no manual download. Verified in place: **PostgreSQL 16.2**, reached through
SQLAlchemy + psycopg 3, with `jsonb` round-tripping Thai text correctly.

Implemented as `scripts/pg_local.py` (the work) plus `scripts/pg_local.sh` (a wrapper
that runs it out of the backend venv, where `pgserver` lives). Commands:
`start` · `url` · `stop` · `status`.

Also discovered during execution and worth recording: **`backend/.venv` is Python
3.9.6**, the macOS system Python — not the 3.12 that `infra/cloudbuild.yaml` builds
against. No code in this plan may use 3.10+ syntax.

- [ ] **Step 4: Append the fixtures to `backend/tests/conftest.py`**

Append — do **not** modify `fresh_app_state`:

```python
@pytest.fixture(scope="session")
def pg_url():
    """The local test database. Skips, never fails, when Postgres is absent —
    the suite must stay green on a machine that has none (and in CI, which has none)."""
    import os
    url = os.environ.get("VOLT_TEST_PG_URL")
    if not url:
        pytest.skip("no local Postgres; run scripts/pg_local.sh start")
    return url


@pytest.fixture
def pg_conn(pg_url):
    """A connection whose rows never outlive the test.

    Rollback alone is not enough: some tests must commit, because the code under
    test opens its OWN connection and would not otherwise see the rows. So the
    teardown rolls back what is still open AND truncates, and it truncates even
    when the test failed — a leaked row makes the next test lie.
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
                names = ", ".join('%s."%s"' % (sch, tbl) for sch, tbl in existing)
                conn.execute(text("truncate %s restart identity cascade" % names))
                conn.commit()
        finally:
            conn.close()
            engine.dispose()
```

- [ ] **Step 5: Add the driver**

Append to `backend/requirements.txt`:

```
psycopg[binary]>=3.2
```

Then: `cd backend && .venv/bin/pip install -r requirements.txt`

- [ ] **Step 6: Start the server and run the test**

Run:
```bash
./scripts/pg_local.sh start
export VOLT_TEST_PG_URL="$(./scripts/pg_local.sh url)"
cd backend && .venv/bin/python -m pytest tests/test_pg_harness.py -v
```
Expected: 2 passed.

- [ ] **Step 7: Prove the rest of the suite is untouched, both ways**

Run:
```bash
cd backend && VOLT_TEST_PG_URL= .venv/bin/python -m pytest
cd backend && .venv/bin/python -m pytest
```
Expected: both at or above **569 passed, 1 skipped** (the first adds 2 skips, the second adds 2 passes). If either drops below the baseline, **stop and report** — do not proceed.

- [ ] **Step 8: Commit**

```bash
git add scripts/pg_local.sh backend/tests/conftest.py backend/tests/test_pg_harness.py backend/requirements.txt
git commit -m "test: a rootless PostgreSQL 16 harness that skips when absent"
```

---

### Task 2: `app/db.py` — the three-state rule

The spec's §5.2.1 lives here. Three states, not two: **unset** behaves as today, **set and reachable** uses Postgres, **set but unreachable** refuses.

**Files:**
- Create: `backend/app/db.py`
- Test: `backend/tests/test_db_states.py`

**Interfaces:**
- Consumes: `app.integrations.env` (already exists; reads `backend/.env` then the real environment).
- Produces:
  - `db.configured() -> bool`
  - `db.engine() -> Engine | None`
  - `db.connect() -> Connection` — raises `db.DatabaseUnreachable` when configured but unreachable
  - `db.DatabaseUnreachable(RuntimeError)`
  - `db.reset() -> None` — test seam; disposes the cached engine

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_db_states.py`:

```python
"""§5.2.1 — configured, unconfigured, unreachable are three different states.

The middle one is the deployed path. The first is what keeps 569 tests and a
bare python:3.12-slim CI container working. The third must REFUSE: a configured
database that has gone away may never degrade to fixtures or to memory, because
that failure would look exactly like success.
"""
import pytest

from app import db


@pytest.fixture(autouse=True)
def _clean_engine(monkeypatch):
    db.reset()
    yield
    db.reset()


def test_unset_is_not_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.configured() is False
    assert db.engine() is None


def test_unset_connect_returns_none_rather_than_raising(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.connect() is None


def test_configured_and_reachable_connects(monkeypatch, pg_url):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    assert db.configured() is True
    with db.connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text("select 1")).scalar() == 1


def test_configured_but_unreachable_refuses(monkeypatch):
    monkeypatch.setenv("DATABASE_URL",
                       "postgresql+psycopg://volt@127.0.0.1:1/nothing_listens_here")
    assert db.configured() is True
    with pytest.raises(db.DatabaseUnreachable):
        db.connect()
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db_states.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write `backend/app/db.py`**

```python
"""The database seam — and the three states that are easy to collapse into two.

  DATABASE_URL unset        the code behaves exactly as it did before there was
                            a database. Unit tests, CI, a laptop with no Postgres.
  set and reachable         the deployed path.
  set but unreachable       REFUSE.

The third case is the one worth spelling out. Falling back to fixtures or to
in-memory state when a configured database has gone away would resurrect the very
defect this work exists to remove — a tester's work silently vanishing — while
looking like success. app/config.py already names the principle: RUNNING and
REFUSING are both honest, LEAKING is not.
"""
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from .integrations import env


class DatabaseUnreachable(RuntimeError):
    """Configured, and not answering. Never caught to fall back — only to report."""


_engine = None


def url():
    return env("DATABASE_URL")


def configured():
    return bool(url())


def engine():
    global _engine
    if not configured():
        return None
    if _engine is None:
        # pool_pre_ping: Cloud SQL drops idle connections, and a dead one taken from
        # the pool would surface as a random 500 on whichever request drew it.
        _engine = create_engine(url(), pool_pre_ping=True, pool_size=5,
                                max_overflow=2, future=True)
    return _engine


def connect():
    """A live connection, or None when no database is configured.

    Raises DatabaseUnreachable when one IS configured and cannot be reached.
    """
    active = engine()
    if active is None:
        return None
    try:
        return active.connect()
    except SQLAlchemyError as exc:
        raise DatabaseUnreachable(str(exc)) from exc


def reset():
    """Drop the cached engine. Test seam — never call it from a request."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_db_states.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the whole suite**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: at or above 569 passed. **Stop and report if not.**

- [ ] **Step 6: Commit**

```bash
git add backend/app/db.py backend/tests/test_db_states.py
git commit -m "feat(db): the engine seam, and the three states of DATABASE_URL"
```

---

### Task 3: Schema DDL and the `debt-migrate` job

**Files:**
- Create: `backend/app/schema.sql`, `backend/app/migrate.py`
- Test: `backend/tests/test_landing_schema.py`

**Interfaces:**
- Consumes: `db.connect()`, `db.DatabaseUnreachable`.
- Produces:
  - `migrate.apply(conn) -> list[str]` — statements executed, in order
  - `migrate.main() -> int` — process exit code; the Cloud Run Job entrypoint
  - Tables: `landing.import_run`, `landing.customer`, `landing.order`, `landing.customer_block`, `app.session_state`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_landing_schema.py`:

```python
"""The DDL applies on an empty database, twice, and round-trips a row.

Idempotence is not a nicety here: debt-migrate runs on every deploy, before the
new revision takes traffic, so a second run must be a no-op rather than an error.
"""
import pytest
from sqlalchemy import text

from app import migrate

EXPECTED_TABLES = {
    ("landing", "import_run"), ("landing", "customer"),
    ("landing", "order"), ("landing", "customer_block"),
    ("app", "session_state"),
}


def test_apply_creates_every_table(pg_conn):
    migrate.apply(pg_conn)
    rows = pg_conn.execute(text(
        "select table_schema, table_name from information_schema.tables "
        "where table_schema in ('landing','app')")).fetchall()
    assert EXPECTED_TABLES <= {(r[0], r[1]) for r in rows}


def test_apply_is_idempotent(pg_conn):
    migrate.apply(pg_conn)
    migrate.apply(pg_conn)          # must not raise
    count = pg_conn.execute(text(
        "select count(*) from information_schema.tables "
        "where table_schema in ('landing','app')")).scalar()
    assert count >= len(EXPECTED_TABLES)


def test_data_source_is_inside_the_customer_primary_key(pg_conn):
    """The property the whole overlay design rests on: a SHEET row and an ODOO
    row for the same volt_id coexist rather than overwrite."""
    migrate.apply(pg_conn)
    cols = pg_conn.execute(text("""
        select kcu.column_name
          from information_schema.table_constraints tc
          join information_schema.key_column_usage kcu
            on kcu.constraint_name = tc.constraint_name
         where tc.table_schema = 'landing' and tc.table_name = 'customer'
           and tc.constraint_type = 'PRIMARY KEY'
    """)).scalars().all()
    assert set(cols) == {"volt_id", "data_source"}


def test_a_sheet_row_and_an_odoo_row_coexist(pg_conn):
    migrate.apply(pg_conn)
    run = pg_conn.execute(text(
        "insert into landing.import_run (source_system, status) "
        "values ('SHEET','OK') returning id")).scalar()
    for source in ("SHEET", "ODOO"):
        pg_conn.execute(text(
            "insert into landing.customer (volt_id, data_source, name_roman, import_run_id) "
            "values (:v, :s, :n, :r)"),
            {"v": "VID-1", "s": source, "n": "Runjit", "r": run})
    assert pg_conn.execute(text(
        "select count(*) from landing.customer where volt_id='VID-1'")).scalar() == 2
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_landing_schema.py -v`
Expected: FAIL — `No module named 'app.migrate'`

- [ ] **Step 3: Write `backend/app/schema.sql`**

```sql
-- Volt Debt staging schema. Two schemas, five tables.
--
-- landing holds ingested source data shaped like the New Order Master sheet.
-- app holds per-tester state, which today lives in a process-local dict and dies
-- with the Cloud Run revision.
--
-- Every statement is IF NOT EXISTS: debt-migrate runs on every deploy.

CREATE SCHEMA IF NOT EXISTS landing;
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS landing.import_run (
    id                bigserial PRIMARY KEY,
    source_system     text        NOT NULL CHECK (source_system IN ('SHEET','ODOO')),
    spreadsheet_id    text,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text        NOT NULL DEFAULT 'RUNNING'
                                  CHECK (status IN ('RUNNING','OK','FAILED')),
    row_counts        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    reconciled        boolean,
    truncated_blocks  jsonb       NOT NULL DEFAULT '[]'::jsonb,
    note              text
);

-- The successful runs, newest first, are the only ones book_source reads.
CREATE INDEX IF NOT EXISTS import_run_ok_idx
    ON landing.import_run (source_system, id DESC) WHERE status = 'OK';

-- data_source sits INSIDE the primary key on purpose: a SHEET row and an ODOO row
-- for the same volt_id must coexist, or the overlay cannot be expressed at all.
CREATE TABLE IF NOT EXISTS landing.customer (
    volt_id         text NOT NULL,
    data_source     text NOT NULL CHECK (data_source IN ('SHEET','ODOO')),
    customer_no     text,
    name_roman      text,
    name_th         text,
    epc             text,
    product         text,
    sales_lead      text,
    phone_masked    text,
    phone_e164      text,
    email_masked    text,
    source_refs     jsonb  NOT NULL DEFAULT '[]'::jsonb,
    import_run_id   bigint NOT NULL REFERENCES landing.import_run(id),
    PRIMARY KEY (volt_id, data_source)
);

CREATE TABLE IF NOT EXISTS landing."order" (
    volt_id               text NOT NULL,
    data_source           text NOT NULL CHECK (data_source IN ('SHEET','ODOO')),
    no                    integer,
    crm_id                text,
    order_type            text,
    order_status          text,
    loan_status           text,
    submit_date           date,
    contract_signed_date  date,
    epc_start_date        date,
    epc_end_date          date,
    amount_total          numeric,
    source_ref            jsonb  NOT NULL DEFAULT '[]'::jsonb,
    import_run_id         bigint NOT NULL REFERENCES landing.import_run(id),
    PRIMARY KEY (volt_id, data_source)
);

-- Odoo writes ZERO rows here. sale.order and res.partner contain nothing that
-- answers leasing or tracking; the schema states that boundary rather than
-- hiding it behind columns full of NULL.
CREATE TABLE IF NOT EXISTS landing.customer_block (
    volt_id        text NOT NULL,
    block          text NOT NULL CHECK (block IN
                        ('leasing','tracking','cash','cash_invoices','asset','contact_log')),
    data_source    text NOT NULL CHECK (data_source IN ('SHEET','ODOO')),
    payload        jsonb  NOT NULL,
    import_run_id  bigint NOT NULL REFERENCES landing.import_run(id),
    PRIMARY KEY (volt_id, block, data_source)
);

CREATE TABLE IF NOT EXISTS app.session_state (
    session_id    text NOT NULL,
    key           text NOT NULL,
    payload       bytea      NOT NULL,
    codec         text       NOT NULL DEFAULT 'pickle-v1',
    code_version  text       NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, key)
);

CREATE INDEX IF NOT EXISTS session_state_updated_idx
    ON app.session_state (updated_at);
```

> **DEVIATION FROM THE SPEC — needs Arina's ruling.** The spec gives
> `app.session_state.payload` as `jsonb`. It cannot be. `Store` has **20 live
> instances** whose factories return `list`, `dict`, `set` and seven custom classes
> (`ExportLog`, `DocumentState`, `Settings`, `ImportState`, `Dictionaries`,
> `ContactLog`, and two closures) — see Task 6, which explains the choice and its
> cost in full. `landing` is unaffected and stays `jsonb` throughout.

- [ ] **Step 4: Write `backend/app/migrate.py`**

```python
"""Applies schema.sql. main() is the debt-migrate Cloud Run Job entrypoint.

infra/cloudbuild.yaml:33 already executes a job of that name, before deploy-api
takes traffic — so a failed migration never reaches a user. This module is what
finally makes that reference resolve.
"""
import sys
from pathlib import Path

from sqlalchemy import text

from . import db

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def statements():
    """schema.sql split on the semicolons that end a statement.

    Comments are stripped BEFORE the split, not after. Splitting first looks
    equivalent and is not: a prose comment may itself contain a semicolon, and
    then the split lands inside it and hands Postgres half a sentence. That is
    exactly what happened the first time this ran — "syntax error at or near
    'the'".

    Naive splitting is safe once comments are gone, and only because schema.sql
    has no function bodies, no dollar-quoting and no semicolons inside literals.
    If any of those are ever added, this must become a real parser.
    """
    lines = [line for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines()
             if not line.strip().startswith("--")]
    return [chunk.strip() for chunk in "\n".join(lines).split(";") if chunk.strip()]


def apply(conn):
    """Run every statement. Returns them, in order, for the caller to log."""
    executed = []
    for statement in statements():
        conn.execute(text(statement))
        executed.append(statement.splitlines()[0])
    return executed


def main():
    if not db.configured():
        print("DATABASE_URL is not set — nothing to migrate", file=sys.stderr)
        return 2
    try:
        with db.connect() as conn:
            with conn.begin():
                executed = apply(conn)
    except db.DatabaseUnreachable as exc:
        print("database unreachable: %s" % exc, file=sys.stderr)
        return 1
    for line in executed:
        print("  %s" % line)
    print("migrate: %d statements applied" % len(executed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_landing_schema.py -v`
Expected: 4 passed.

- [ ] **Step 6: Run it as the job would, against a real empty database**

Run:
```bash
"$HOME/.volt-postgres/bin/createdb" -h 127.0.0.1 -p 55432 -U volt migrate_check
cd backend && DATABASE_URL="postgresql+psycopg://volt@127.0.0.1:55432/migrate_check" \
  .venv/bin/python -m app.migrate
```
Expected: exit 0, statements listed. Run it a second time — expect exit 0 again.

- [ ] **Step 7: Run the whole suite, then commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: at or above 569 passed.

```bash
git add backend/app/schema.sql backend/app/migrate.py backend/tests/test_landing_schema.py
git commit -m "feat(db): landing and app schemas, and the debt-migrate entrypoint"
```

---

### Task 4: `app/landing.py` — writing and reading the landing schema

Knows tables, not precedence. Task 5 knows precedence, not tables.

**Files:**
- Create: `backend/app/landing.py`
- Test: `backend/tests/test_landing_writes.py`

**Interfaces:**
- Consumes: `db.connect()`, `migrate.apply()`.
- Produces:
  - `landing.start_run(conn, source_system, spreadsheet_id=None) -> int`
  - `landing.finish_run(conn, run_id, status, row_counts=None, reconciled=None, truncated_blocks=None, note=None) -> None`
  - `landing.write_customer(conn, run_id, data_source, rec) -> None` — `rec` keys mirror `fixtures_sheet.json` `customers[i]`
  - `landing.write_order(conn, run_id, data_source, volt_id, rec) -> None`
  - `landing.write_block(conn, run_id, data_source, volt_id, block, payload) -> None`
  - `landing.resolved_customers(conn) -> list[dict]` — one row per `volt_id`, precedence already applied by SQL
  - `landing.resolved_orders(conn) -> dict[str, dict]`
  - `landing.blocks_for(conn, volt_ids) -> dict[str, dict[str, object]]`
  - `landing.last_run(conn, source_system) -> dict | None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_landing_writes.py`:

```python
"""Rows go in, rows come back, and precedence is applied by the database.

The precedence property is the one that matters: an ODOO row for a volt_id wins
over a SHEET row for the same volt_id, and a FAILED run is invisible.
"""
import pytest
from sqlalchemy import text

from app import landing, migrate


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def test_start_run_returns_an_id_and_marks_it_running(schema):
    run = landing.start_run(schema, "SHEET", spreadsheet_id="SHEET-X")
    row = schema.execute(text("select status, spreadsheet_id from landing.import_run where id=:i"),
                         {"i": run}).one()
    assert row.status == "RUNNING" and row.spreadsheet_id == "SHEET-X"


def test_finish_run_records_counts_and_status(schema):
    run = landing.start_run(schema, "SHEET")
    landing.finish_run(schema, run, "OK", row_counts={"customers": 418}, reconciled=True)
    row = schema.execute(text("select status, row_counts, reconciled, finished_at "
                              "from landing.import_run where id=:i"), {"i": run}).one()
    assert row.status == "OK" and row.row_counts == {"customers": 418}
    assert row.reconciled is True and row.finished_at is not None


def test_write_and_resolve_a_sheet_customer(schema):
    run = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, run, "SHEET",
                           {"volt_id": "V1", "customer_no": "280", "name_roman": "Runjit",
                            "name_th": "รัญจิต", "epc": "IPW", "product": "LEASE",
                            "sales_lead": "Varunya", "phone_masked": "08x-xxx-4810",
                            "email_masked": "p•••@yahoo.co.th", "source_refs": [[13, 2]]})
    landing.finish_run(schema, run, "OK")
    rows = landing.resolved_customers(schema)
    assert len(rows) == 1
    assert rows[0]["name_th"] == "รัญจิต" and rows[0]["data_source"] == "SHEET"


def test_odoo_wins_over_sheet_for_the_same_volt_id(schema):
    sheet = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, sheet, "SHEET", {"volt_id": "V1", "name_roman": "FromSheet"})
    landing.finish_run(schema, sheet, "OK")
    odoo = landing.start_run(schema, "ODOO")
    landing.write_customer(schema, odoo, "ODOO", {"volt_id": "V1", "name_roman": "FromOdoo"})
    landing.finish_run(schema, odoo, "OK")
    rows = landing.resolved_customers(schema)
    assert len(rows) == 1 and rows[0]["name_roman"] == "FromOdoo"


def test_a_failed_run_is_invisible(schema):
    sheet = landing.start_run(schema, "SHEET")
    landing.write_customer(schema, sheet, "SHEET", {"volt_id": "V1", "name_roman": "FromSheet"})
    landing.finish_run(schema, sheet, "OK")
    odoo = landing.start_run(schema, "ODOO")
    landing.write_customer(schema, odoo, "ODOO", {"volt_id": "V1", "name_roman": "HalfWritten"})
    landing.finish_run(schema, odoo, "FAILED", note="odoo refused the login")
    rows = landing.resolved_customers(schema)
    assert rows[0]["name_roman"] == "FromSheet", "a failed run must never serve rows"


def test_blocks_round_trip_unchanged(schema):
    run = landing.start_run(schema, "SHEET")
    payload = {"days_late": 0, "months": [{"kind": "PAID", "amount": "3199.00"}]}
    landing.write_block(schema, run, "SHEET", "V1", "leasing", payload)
    landing.finish_run(schema, run, "OK")
    assert landing.blocks_for(schema, ["V1"])["V1"]["leasing"] == payload
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_landing_writes.py -v`
Expected: FAIL — `No module named 'app.landing'`

- [ ] **Step 3: Write `backend/app/landing.py`**

```python
"""The landing schema — writes, and reads with precedence applied by SQL.

This module knows tables. app/book_source.py knows what the rows mean. Keeping
those apart is what lets the precedence rule be stated once, in one ORDER BY,
instead of being re-implemented by every reader.
"""
import json

from sqlalchemy import text

BLOCKS = ("leasing", "tracking", "cash", "cash_invoices", "asset", "contact_log")

# The precedence chain of the spec, as one clause. DISTINCT ON takes the first row
# per volt_id, so ordering ODOO ahead of SHEET and newer runs ahead of older gives
# rung 1 (current ODOO run), then rung 2 (last previous ODOO run), then rung 3
# (SHEET) — and the WHERE clause makes a FAILED run invisible to all three.
_PRECEDENCE = """
    order by t.volt_id,
             case t.data_source when 'ODOO' then 0 else 1 end,
             t.import_run_id desc
"""

CUSTOMER_COLUMNS = ("volt_id", "customer_no", "name_roman", "name_th", "epc", "product",
                    "sales_lead", "phone_masked", "phone_e164", "email_masked")

ORDER_COLUMNS = ("no", "crm_id", "order_type", "order_status", "loan_status",
                 "submit_date", "contract_signed_date", "epc_start_date",
                 "epc_end_date", "amount_total")


def start_run(conn, source_system, spreadsheet_id=None):
    return conn.execute(text(
        "insert into landing.import_run (source_system, spreadsheet_id) "
        "values (:s, :g) returning id"),
        {"s": source_system, "g": spreadsheet_id}).scalar()


def finish_run(conn, run_id, status, row_counts=None, reconciled=None,
               truncated_blocks=None, note=None):
    conn.execute(text(
        "update landing.import_run set status=:st, finished_at=now(), "
        "row_counts=cast(:rc as jsonb), reconciled=:rec, "
        "truncated_blocks=cast(:tb as jsonb), note=:n where id=:i"),
        {"st": status, "rc": json.dumps(row_counts or {}), "rec": reconciled,
         "tb": json.dumps(truncated_blocks or []), "n": note, "i": run_id})


def write_customer(conn, run_id, data_source, rec):
    params = {c: rec.get(c) for c in CUSTOMER_COLUMNS}
    params.update(ds=data_source, refs=json.dumps(rec.get("source_refs") or []), run=run_id)
    conn.execute(text(
        "insert into landing.customer (%s, data_source, source_refs, import_run_id) "
        "values (%s, :ds, cast(:refs as jsonb), :run) "
        "on conflict (volt_id, data_source) do update set %s, "
        "source_refs = excluded.source_refs, import_run_id = excluded.import_run_id"
        % (", ".join(CUSTOMER_COLUMNS),
           ", ".join(":" + c for c in CUSTOMER_COLUMNS),
           ", ".join("%s = excluded.%s" % (c, c) for c in CUSTOMER_COLUMNS if c != "volt_id"))),
        params)


def write_order(conn, run_id, data_source, volt_id, rec):
    params = {c: rec.get(c) for c in ORDER_COLUMNS}
    params.update(volt_id=volt_id, ds=data_source,
                  ref=json.dumps(rec.get("source_ref") or []), run=run_id)
    conn.execute(text(
        'insert into landing."order" (volt_id, %s, data_source, source_ref, import_run_id) '
        "values (:volt_id, %s, :ds, cast(:ref as jsonb), :run) "
        "on conflict (volt_id, data_source) do update set %s, "
        "source_ref = excluded.source_ref, import_run_id = excluded.import_run_id"
        % (", ".join('"%s"' % c for c in ORDER_COLUMNS),
           ", ".join(":" + c for c in ORDER_COLUMNS),
           ", ".join('"%s" = excluded."%s"' % (c, c) for c in ORDER_COLUMNS))),
        params)


def write_block(conn, run_id, data_source, volt_id, block, payload):
    if block not in BLOCKS:
        raise ValueError("unknown block %r" % block)
    conn.execute(text(
        "insert into landing.customer_block (volt_id, block, data_source, payload, import_run_id) "
        "values (:v, :b, :ds, cast(:p as jsonb), :run) "
        "on conflict (volt_id, block, data_source) do update set "
        "payload = excluded.payload, import_run_id = excluded.import_run_id"),
        {"v": volt_id, "b": block, "ds": data_source,
         "p": json.dumps(payload, ensure_ascii=False), "run": run_id})


def _ok_runs_clause():
    return ("join landing.import_run r on r.id = t.import_run_id and r.status = 'OK'")


def resolved_customers(conn):
    rows = conn.execute(text(
        "select distinct on (t.volt_id) t.* "
        "from landing.customer t %s %s" % (_ok_runs_clause(), _PRECEDENCE))).mappings().all()
    return [dict(r) for r in rows]


def resolved_orders(conn):
    rows = conn.execute(text(
        'select distinct on (t.volt_id) t.* '
        'from landing."order" t %s %s' % (_ok_runs_clause(), _PRECEDENCE))).mappings().all()
    return {r["volt_id"]: dict(r) for r in rows}


def blocks_for(conn, volt_ids):
    if not volt_ids:
        return {}
    rows = conn.execute(text(
        "select distinct on (t.volt_id, t.block) t.volt_id, t.block, t.payload "
        "from landing.customer_block t %s where t.volt_id = any(:ids) "
        "order by t.volt_id, t.block, "
        "case t.data_source when 'ODOO' then 0 else 1 end, t.import_run_id desc"
        % _ok_runs_clause()), {"ids": list(volt_ids)}).mappings().all()
    out = {}
    for row in rows:
        out.setdefault(row["volt_id"], {})[row["block"]] = row["payload"]
    return out


def last_run(conn, source_system):
    row = conn.execute(text(
        "select * from landing.import_run where source_system=:s and status='OK' "
        "order by id desc limit 1"), {"s": source_system}).mappings().first()
    return dict(row) if row else None
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_landing_writes.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run the whole suite and commit**

```bash
cd backend && .venv/bin/python -m pytest      # at or above 569
git add backend/app/landing.py backend/tests/test_landing_writes.py
git commit -m "feat(landing): writes, and reads with precedence applied by SQL"
```

---

### Task 5: `app/book_source.py` and the one-function seam

**Files:**
- Create: `backend/app/book_source.py`
- Modify: `backend/app/book.py:75-79`
- Test: `backend/tests/test_book_source.py`

**Interfaces:**
- Consumes: `db.configured()`, `db.connect()`, `landing.resolved_customers/resolved_orders/blocks_for/last_run`.
- Produces: `book_source.load() -> dict | None` — the same payload shape `fixtures_sheet.json` has: keys `source`, `pivots`, `flow_stages`, `counts`, `warnings`, `customers`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_book_source.py`:

```python
"""The seam. book.load_sheet() must return the same shape whichever rung served it.

The unconfigured case is the one that keeps the 569-test contract and a bare
python:3.12-slim CI container working, so it is tested first and hardest.
"""
import pytest

from app import book, book_source, db, landing, migrate


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    db.reset()
    yield
    db.reset()


def test_unconfigured_reads_the_fixture_exactly_as_before(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    payload = book_source.load()
    assert payload is not None
    assert payload["source"]["spreadsheet"] == "New Order Master"
    assert len(payload["customers"]) == 418


def test_book_load_sheet_delegates_to_book_source(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert book.load_sheet()["counts"] == book_source.load()["counts"]


def test_unreachable_refuses_rather_than_falling_back(monkeypatch):
    monkeypatch.setenv("DATABASE_URL",
                       "postgresql+psycopg://volt@127.0.0.1:1/nothing_listens_here")
    with pytest.raises(db.DatabaseUnreachable):
        book_source.load()


def test_configured_reads_landing_and_keeps_the_payload_shape(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    run = landing.start_run(pg_conn, "SHEET", spreadsheet_id="SHEET-X")
    landing.write_customer(pg_conn, run, "SHEET",
                           {"volt_id": "V1", "customer_no": "280", "name_roman": "Runjit",
                            "product": "LEASE"})
    landing.write_block(pg_conn, run, "SHEET", "V1", "leasing", {"days_late": 0})
    landing.finish_run(pg_conn, run, "OK", row_counts={"customers": 1}, reconciled=True)
    pg_conn.commit()

    monkeypatch.setenv("DATABASE_URL", pg_url)
    payload = book_source.load()
    assert set(payload) >= {"source", "pivots", "flow_stages", "counts", "warnings", "customers"}
    assert len(payload["customers"]) == 1
    row = payload["customers"][0]
    assert row["volt_id"] == "V1" and row["leasing"] == {"days_late": 0}
    assert row["cash"] is None and row["cash_invoices"] == []
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_book_source.py -v`
Expected: FAIL — `No module named 'app.book_source'`

- [ ] **Step 3: Write `backend/app/book_source.py`**

```python
"""Where the book comes from — and nothing else in the domain needs to know.

load() returns exactly the dict shape backend/app/fixtures_sheet.json has, which
is exactly what book.build() already consumes. That is the whole trick: the 32
domain modules and the 158 endpoints are untouched because the shape they receive
never changes, only its origin does.

Three states (spec §5.2.1):
  DATABASE_URL unset   read the fixture, exactly as before there was a database
  set and reachable    read the landing schema
  set but unreachable  raise. Never fall back — that would look like success.
"""
import json
from pathlib import Path

from . import db, landing

FIXTURE_PATH = Path(__file__).with_name("fixtures_sheet.json")

# The block names, and the empty value each takes when the landing schema holds no
# row for it. An Odoo-only customer has none of them, which is the point.
BLOCK_DEFAULTS = {"leasing": None, "tracking": None, "cash": None,
                  "cash_invoices": [], "asset": None, "contact_log": []}


def load():
    """The payload, or None when there is nothing to read at all."""
    if not db.configured():
        return _from_fixture()
    conn = db.connect()
    try:
        return _from_landing(conn)
    finally:
        conn.close()


def _from_fixture():
    if not FIXTURE_PATH.exists():
        return None
    with open(FIXTURE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _from_landing(conn):
    customers = landing.resolved_customers(conn)
    orders = landing.resolved_orders(conn)
    blocks = landing.blocks_for(conn, [c["volt_id"] for c in customers])
    sheet_run = landing.last_run(conn, "SHEET")
    odoo_run = landing.last_run(conn, "ODOO")

    rows = []
    for customer in customers:
        volt_id = customer["volt_id"]
        record = {key: customer.get(key) for key in landing.CUSTOMER_COLUMNS}
        record["source_refs"] = customer.get("source_refs") or []
        record["data_source"] = customer.get("data_source")
        for block, empty in BLOCK_DEFAULTS.items():
            record[block] = blocks.get(volt_id, {}).get(block, empty)
        order = orders.get(volt_id)
        record["order"] = {k: order.get(k) for k in landing.ORDER_COLUMNS} if order else None
        rows.append(record)

    run = sheet_run or odoo_run or {}
    return {
        "source": {
            "spreadsheet": "New Order Master",
            "spreadsheet_id": run.get("spreadsheet_id"),
            "render": "landing schema (Cloud SQL)",
            "pii": "phone, email masked; names, VOLT IDs, amounts, statuses and notes kept",
            "blocks": run.get("truncated_blocks") or [],
        },
        # The sheet's own pivots are a property of the import, not of the rows, and
        # are carried on import_run. They are reported by app/migration.py, which
        # reads the run — not reconstructed here from rows that cannot express them.
        "pivots": {"payment_status": [], "collection_tracking": [], "cash_invoices": []},
        "flow_stages": {"stages": [], "late_fee_logic": []},
        "counts": (run.get("row_counts") or {}),
        "warnings": [],
        "customers": rows,
    }
```

- [ ] **Step 4: Change the seam in `backend/app/book.py`**

Replace lines 75–79 exactly:

```python
def load_sheet():
    if not FIXTURE_PATH.exists():
        return None
    with open(FIXTURE_PATH, encoding="utf-8") as handle:
        return json.load(handle)
```

with:

```python
def load_sheet():
    # The seam. Where the book comes from is book_source's business; this module
    # only ever needed the payload. Unconfigured, it still reads FIXTURE_PATH.
    from . import book_source
    return book_source.load()
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_book_source.py -v`
Expected: 4 passed.

- [ ] **Step 6: Run the whole suite — this is the task most likely to move it**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: at or above 569 passed. If any existing test fails, **stop and report**; do not edit it.

- [ ] **Step 7: Commit**

```bash
git add backend/app/book_source.py backend/app/book.py backend/tests/test_book_source.py
git commit -m "feat(book): load the book through one seam, from fixture or from landing"
```

---

### Task 6: Per-tester state that survives a restart

The defect this whole plan exists to kill. `session.py`'s own docstring concedes it: *"State still lives in memory and a restart clears every session. Cloud Run will restart. Testers must be told."*

**DECISION — deviation from the spec, taken 2026-09-10.** The spec says `payload jsonb`. It cannot be. There are **20 live `Store` instances** and their factories return `list`, `dict`, `set`, and the classes `ExportLog`, `DocumentState`, `Settings`, `ImportState`, `Dictionaries`, `ContactLog`, plus two closures. Writing a serializer for each would mean editing twenty domain modules — precisely what this design promised not to do.

So: **pickle into `bytea`, guarded by `code_version`.** On Cloud Run that version is `K_REVISION`, which is stable for a revision and changes on deploy. The consequences, stated plainly:

- A **restart of the same revision preserves tester work.** This is the defect, and it is fixed. At `min-instances 0` these restarts happen constantly, with no code change.
- A **new deploy resets it.** A row whose `code_version` differs is ignored, not unpickled — because the classes it holds may no longer exist. Resetting is the safe failure; unpickling a stale class is not.
- Pickle deserialises our own rows from our own database, never user input.

`landing` is unaffected and stays `jsonb` throughout.

**Files:**
- Create: `backend/app/session_store_db.py`
- Modify: `backend/app/session.py`, and the 20 `Store(...)` call sites to pass an explicit `key`
- Modify: `backend/app/main.py` (flush middleware)
- Test: `backend/tests/test_session_persistence.py`

**Interfaces:**
- Consumes: `db.configured()`, `db.connect()`.
- Produces:
  - `session.Store(factory, key)` — `key` is now **required**; a missing one is a `TypeError` at import, so a silent key collision is impossible
  - `session.REGISTRY: list[Store]`
  - `session.flush_current() -> int` — rows written for the current session
  - `session_store_db.load(conn, session_id, key) -> object | _MISSING`
  - `session_store_db.save(conn, session_id, key, value) -> None`
  - `session_store_db.CODE_VERSION: str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_session_persistence.py`:

```python
"""Tester work survives a restart — simulated by throwing away every in-memory
dict and rebuilding the Stores from Postgres, which is exactly what a Cloud Run
revision restart does to the process."""
import pytest

from app import db, migrate, session as session_domain, session_store_db


@pytest.fixture
def wired(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    yield
    db.reset()


def test_unconfigured_store_is_memory_exactly_as_before(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.reset()
    store = session_domain.Store(dict, key="test.unconfigured")
    session_domain.CURRENT.set("s-aaa")
    store.for_current()["x"] = 1
    assert store.for_current() == {"x": 1}


def test_a_written_value_survives_losing_every_in_memory_dict(wired):
    store = session_domain.Store(dict, key="test.survives")
    session_domain.CURRENT.set("s-bbb")
    store.for_current()["approved"] = ["order-1", "order-2"]
    session_domain.flush_current()

    store._by_session.clear()          # the restart
    assert store.for_current() == {"approved": ["order-1", "order-2"]}


def test_sessions_stay_separate_across_the_restart(wired):
    store = session_domain.Store(dict, key="test.separate")
    session_domain.CURRENT.set("s-ccc")
    store.for_current()["who"] = "first"
    session_domain.flush_current()
    session_domain.CURRENT.set("s-ddd")
    store.for_current()["who"] = "second"
    session_domain.flush_current()

    store._by_session.clear()
    session_domain.CURRENT.set("s-ccc")
    assert store.for_current()["who"] == "first"
    session_domain.CURRENT.set("s-ddd")
    assert store.for_current()["who"] == "second"


def test_a_row_from_another_code_version_is_ignored_not_unpickled(wired, pg_conn, monkeypatch):
    store = session_domain.Store(dict, key="test.version")
    session_domain.CURRENT.set("s-eee")
    store.for_current()["stale"] = True
    session_domain.flush_current()

    monkeypatch.setattr(session_store_db, "CODE_VERSION", "a-different-revision")
    store._by_session.clear()
    assert store.for_current() == {}, "a new revision must start fresh, not unpickle stale classes"


def test_a_set_and_a_custom_class_both_round_trip(wired):
    """JSONB could hold neither. This is why the column is bytea."""
    class Holder:
        def __init__(self):
            self.items = set()

    store = session_domain.Store(Holder, key="test.custom")
    session_domain.CURRENT.set("s-fff")
    store.for_current().items.add("removed-order-7")
    session_domain.flush_current()

    store._by_session.clear()
    assert store.for_current().items == {"removed-order-7"}
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_session_persistence.py -v`
Expected: FAIL — `No module named 'app.session_store_db'`

- [ ] **Step 3: Write `backend/app/session_store_db.py`**

```python
"""Postgres backing for the per-session Stores.

Why pickle and not JSON. Twenty Store factories return list, dict, set and seven
custom classes. JSONB can hold the first two. Writing a codec for each of the rest
would mean editing twenty domain modules, which is the one thing this design
promised not to do.

Why the version guard. A pickle holds a reference to the class that made it. After
a deploy that class may have changed shape or gone, and unpickling it would fail in
some unpredictable place, or worse, succeed into something subtly wrong. So a row
written by a different code version is IGNORED — the session starts fresh. On Cloud
Run the version is K_REVISION, which is stable for a revision and changes on deploy:
a restart keeps a tester's work, a deploy does not, and that is the honest trade.
"""
import pickle

from sqlalchemy import text

from .integrations import env

CODEC = "pickle-v1"

# K_REVISION is set by Cloud Run and is the revision name. Stable across restarts of
# the same revision; different after every deploy. Locally there is no deploy, so
# "dev" keeps state across a laptop restart too.
CODE_VERSION = env("K_REVISION") or "dev"

MISSING = object()


def load(conn, session_id, key):
    row = conn.execute(text(
        "select payload, codec, code_version from app.session_state "
        "where session_id=:s and key=:k"), {"s": session_id, "k": key}).first()
    if row is None:
        return MISSING
    if row.codec != CODEC or row.code_version != CODE_VERSION:
        return MISSING          # a different build wrote it; start fresh rather than guess
    try:
        return pickle.loads(row.payload)
    except Exception:
        # A corrupt or unreadable row must not take the request down with it.
        return MISSING


def save(conn, session_id, key, value):
    try:
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        return              # unpicklable state stays in memory; it is not worth a 500
    conn.execute(text(
        "insert into app.session_state (session_id, key, payload, codec, code_version, updated_at) "
        "values (:s, :k, :p, :c, :v, now()) "
        "on conflict (session_id, key) do update set payload=excluded.payload, "
        "codec=excluded.codec, code_version=excluded.code_version, updated_at=now()"),
        {"s": session_id, "k": key, "p": blob, "c": CODEC, "v": CODE_VERSION})
```

- [ ] **Step 4: Rewrite `Store` in `backend/app/session.py`**

Replace the `Store` class, and append `REGISTRY` and `flush_current`:

```python
REGISTRY = []


class Store:
    """A per-session container.

    `for_current()` creates the session's slot on first touch, so callers never
    have to check whether it exists — unchanged. What is new is that, when a
    database is configured, first touch also LOOKS for the slot in Postgres, and
    flush_current() writes every touched slot back after the request.

    `key` is required and must be unique across the process. It is the column
    value rows are stored under, so two Stores sharing a key would silently mix a
    tester's data. Three call sites use Store(dict), which is why this cannot be
    derived from the factory.
    """

    def __init__(self, factory, key):
        self._factory = factory
        self.key = key
        self._by_session = {}
        REGISTRY.append(self)

    def for_current(self):
        session_id = CURRENT.get()
        if session_id not in self._by_session:
            self._by_session[session_id] = self._restore(session_id)
        return self._by_session[session_id]

    def _restore(self, session_id):
        from . import db, session_store_db
        if not db.configured():
            return self._factory()
        conn = db.connect()          # raises DatabaseUnreachable — deliberately not caught
        try:
            value = session_store_db.load(conn, session_id, self.key)
        finally:
            conn.close()
        return self._factory() if value is session_store_db.MISSING else value

    def reset(self):
        """Clears EVERY session, in memory only. Test seam — never call it from a request."""
        self._by_session.clear()

    def sessions(self):
        return list(self._by_session)


def flush_current():
    """Write every Store's slot for the current session. Called after each request.

    Callers mutate the object returned by for_current() in place, so there is no
    per-mutation hook to hang a write on; the end of the request is the honest
    moment. Returns the number of rows written.
    """
    from . import db, session_store_db
    if not db.configured():
        return 0
    session_id = CURRENT.get()
    written = 0
    conn = db.connect()
    try:
        with conn.begin():
            for store in REGISTRY:
                if session_id in store._by_session:
                    session_store_db.save(conn, session_id, store.key,
                                          store._by_session[session_id])
                    written += 1
    finally:
        conn.close()
    return written
```

- [ ] **Step 5: Give all 20 call sites an explicit key**

`key` is required, so the process will not import until every site is updated. Run `grep -rn "Store(" backend/app --include='*.py' | grep -v "class Store"` and give each the dotted name of its own module and variable, for example:

```python
_default_store = Store(lambda: [None], key="criteria.default")            # criteria.py:49
_store = Store(ExportLog, key="workbook_exports.log")                     # workbook_exports.py:24
_targets_store = Store(dict, key="reports.targets")                       # reports.py:20
_focus_store = Store(dict, key="reports.focus")                           # reports.py:21
_snapshots = Store(list, key="reports.snapshots")                         # reports.py:59
_approved_store = Store(dict, key="orders.approved")                      # orders.py:36
_added_store = Store(list, key="orders.added")                            # orders.py:37
_removed_store = Store(set, key="orders.removed")                         # orders.py:38
_odoo_store = Store(lambda: {"rows": None, "meta": None}, key="orders.odoo")   # orders.py:54
```

…and so on for `peak_documents.state`, `config.settings`, `imports.state`, `cases.state`, `cases.fee_state`, `dictionaries.state`, `journey.state`, `invoice_pipeline.state`, `main.board_columns`, `money.band_sets.registry`, `collections.contact.log`.

**Watch `collections/contact.py:327`** — that `Store` is constructed inside an instance, so if more than one instance exists the key must distinguish them. Check first; if there is exactly one, `key="collections.contact.log"` is correct.

- [ ] **Step 6: Flush after each request, in `backend/app/main.py`**

Find the middleware that sets the `volt_session` cookie and sets `CURRENT`, and flush after the response is produced:

```python
    response = await call_next(request)
    # Callers mutate session state in place, so the end of the request is the only
    # honest moment to persist it. A flush failure must not corrupt a response that
    # already succeeded — it is logged and the request still returns.
    try:
        session_domain.flush_current()
    except Exception as exc:                       # noqa: BLE001
        print("session flush failed: %s" % exc, file=sys.stderr)
    return response
```

- [ ] **Step 7: Run the new tests**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_session_persistence.py -v`
Expected: 5 passed.

- [ ] **Step 8: Run the whole suite**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: at or above 569 passed. The 20 call-site edits are the risk here. **Stop and report on any existing-test failure.**

- [ ] **Step 9: Commit**

```bash
git add backend/app/session.py backend/app/session_store_db.py backend/app/main.py \
        backend/app/*.py backend/app/money/band_sets.py backend/app/collections/contact.py \
        backend/tests/test_session_persistence.py
git commit -m "feat(session): tester state survives a revision restart"
```

---

### Task 7: `import_master_sheet.py --to-postgres`

The existing parse logic is not touched — a writer is added beside the JSON one. Reconciliation against the sheet's own pivots, and the truncated-blocks report, are carried into `import_run` rather than discarded.

**Files:**
- Modify: `scripts/import_master_sheet.py` (the `main()` tail, where `payload` is assembled)
- Create: `backend/app/sheet_loader.py`
- Test: `backend/tests/test_sheet_to_postgres.py`

**Interfaces:**
- Consumes: `landing.start_run/write_customer/write_order/write_block/finish_run`.
- Produces: `sheet_loader.load_payload(conn, payload) -> dict` — returns `{"import_run_id": int, "customers": int, "orders": int, "blocks": int}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_sheet_to_postgres.py`:

```python
"""The sheet's payload goes into landing without changing shape on the way."""
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app import book_source, landing, migrate, sheet_loader

FIXTURE = Path(__file__).resolve().parent.parent / "app" / "fixtures_sheet.json"


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def test_loads_every_customer_from_the_real_export(schema):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = sheet_loader.load_payload(schema, payload)
    assert result["customers"] == 418
    assert schema.execute(text("select count(*) from landing.customer")).scalar() == 418


def test_the_run_carries_the_sheet_identity_and_counts(schema):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = sheet_loader.load_payload(schema, payload)
    row = schema.execute(text("select * from landing.import_run where id=:i"),
                         {"i": result["import_run_id"]}).mappings().one()
    assert row["source_system"] == "SHEET"
    assert row["spreadsheet_id"] == "SYNTHETIC-SPREADSHEET-ID"
    assert row["status"] == "OK"
    assert row["row_counts"]["customers"] == 418


def test_a_leasing_block_round_trips_byte_for_byte(schema):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sheet_loader.load_payload(schema, payload)
    original = next(c for c in payload["customers"] if c.get("leasing"))
    stored = landing.blocks_for(schema, [original["volt_id"]])[original["volt_id"]]["leasing"]
    assert stored == original["leasing"]


def test_the_book_reads_back_the_same_customer_count(schema, monkeypatch, pg_url):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sheet_loader.load_payload(schema, payload)
    schema.commit()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    from app import db
    db.reset()
    try:
        assert len(book_source.load()["customers"]) == 418
    finally:
        db.reset()
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_sheet_to_postgres.py -v`
Expected: FAIL — `No module named 'app.sheet_loader'`

- [ ] **Step 3: Write `backend/app/sheet_loader.py`**

```python
"""Load a New Order Master payload into the landing schema.

The payload is exactly what scripts/import_master_sheet.py assembles and what
fixtures_sheet.json holds, so this module is the only place that knows how one
maps onto the other. It does not parse anything; parsing stays in the script.
"""
from . import landing

BLOCKS = ("leasing", "tracking", "cash", "cash_invoices", "asset", "contact_log")

SPREADSHEET_ID = "SYNTHETIC-SPREADSHEET-ID"


def load_payload(conn, payload):
    """One import_run, one transaction. The caller owns the transaction so a
    failure leaves the previous run's rows serving."""
    source = payload.get("source") or {}
    run = landing.start_run(conn, "SHEET",
                            spreadsheet_id=source.get("spreadsheet_id") or SPREADSHEET_ID)
    customers = orders = blocks = 0
    for record in payload.get("customers") or []:
        volt_id = record.get("volt_id")
        if not volt_id:
            continue
        landing.write_customer(conn, run, "SHEET", record)
        customers += 1
        order = record.get("order")
        if order:
            landing.write_order(conn, run, "SHEET", volt_id, order)
            orders += 1
        for block in BLOCKS:
            value = record.get(block)
            # An empty list and None both mean "the sheet said nothing here". Writing
            # them would make an absent block indistinguishable from an empty one.
            if value in (None, [], {}):
                continue
            landing.write_block(conn, run, "SHEET", volt_id, block, value)
            blocks += 1

    counts = dict(payload.get("counts") or {})
    counts["customers"] = customers
    landing.finish_run(conn, run, "OK", row_counts=counts,
                       reconciled=None, truncated_blocks=source.get("blocks") or [])
    return {"import_run_id": run, "customers": customers, "orders": orders, "blocks": blocks}
```

- [ ] **Step 4: Add `--to-postgres` to the script**

Replace the bottom of `scripts/import_master_sheet.py`:

```python
if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

with:

```python
def to_postgres(payload):
    """Write an already-parsed payload into the landing schema.

    Imported lazily and only on this path, so the parser keeps running on a machine
    with no database and no SQLAlchemy — which is how it has always been run.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app import db, sheet_loader
    if not db.configured():
        raise SystemExit("DATABASE_URL is not set — nothing to write to")
    conn = db.connect()
    try:
        with conn.begin():
            result = sheet_loader.load_payload(conn, payload)
    finally:
        conn.close()
    print("landing: run=%(import_run_id)d customers=%(customers)d "
          "orders=%(orders)d blocks=%(blocks)d" % result)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0], args[1])
    if "--to-postgres" in sys.argv:
        with open(args[1], encoding="utf-8") as handle:
            to_postgres(json.load(handle))
```

Add `from pathlib import Path` to the imports at the top if it is not already there.

- [ ] **Step 5: Run the tests, then the suite, then commit**

```bash
cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_sheet_to_postgres.py -v   # 4 passed
cd backend && .venv/bin/python -m pytest                                                                                      # at or above 569
git add backend/app/sheet_loader.py scripts/import_master_sheet.py backend/tests/test_sheet_to_postgres.py
git commit -m "feat(import): the sheet lands in Postgres, carrying its own run report"
```

---

### Task 8: The Odoo sync writes to `landing`

Today it caches to `backend/var/odoo_snapshot.json`, which dies with the Cloud Run revision — which is why the middle rung of the fallback chain has never actually existed in a deployed environment.

**Files:**
- Modify: `backend/app/integrations/odoo.py`
- Test: `backend/tests/test_odoo_landing.py`

**Interfaces:**
- Consumes: `landing.*`, `db.configured/connect`, `sheet_loader` conventions.
- Produces: `odoo.sync()` unchanged in signature and return shape; `odoo.cached_snapshot()` reads the last OK ODOO run from Postgres when configured, the JSON file otherwise.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_odoo_landing.py`:

```python
"""The Odoo pull lands in Postgres, tagged ODOO, and writes no blocks.

The last property is the design's honesty: sale.order and res.partner contain
nothing that answers `leasing` or `tracking`, so the schema says so rather than
filling six tables with NULL.
"""
import pytest
from sqlalchemy import text

from app import landing, migrate
from app.integrations import odoo

ROWS = [
    {"volt_id": "SO001_ODOO", "crm_id": "SO001", "first_name": "Runjit", "last_name": "B",
     "thai_name": "รัญจิต", "sales_lead": "Varunya", "order_type": "Leasing",
     "loan_status": "Approved", "sheet_order_status": "sale", "province": "Bangkok",
     "phone_masked": "08x-xxx-4810", "phone_e164": "0812344810", "email_masked": "p•••@x.co",
     "submit_date": "2026-09-01", "amount_total": "307104.0", "no": 9001,
     "origin": "odoo", "data_source": "ODOO"},
]


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def test_rows_land_tagged_odoo(schema):
    run = odoo.write_landing(schema, ROWS, customers=500)
    assert schema.execute(text(
        "select count(*) from landing.customer where data_source='ODOO'")).scalar() == 1
    assert schema.execute(text(
        'select count(*) from landing."order" where data_source=\'ODOO\'')).scalar() == 1
    assert schema.execute(text("select status, source_system from landing.import_run "
                               "where id=:i"), {"i": run}).one() == ("OK", "ODOO")


def test_odoo_writes_no_blocks_at_all(schema):
    odoo.write_landing(schema, ROWS, customers=500)
    assert schema.execute(text("select count(*) from landing.customer_block")).scalar() == 0


def test_a_failed_pull_marks_the_run_failed_and_serves_nothing(schema):
    run = landing.start_run(schema, "ODOO")
    landing.finish_run(schema, run, "FAILED", note="Odoo refused the login")
    assert landing.resolved_customers(schema) == []
    assert landing.last_run(schema, "ODOO") is None
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_odoo_landing.py -v`
Expected: FAIL — `module 'app.integrations.odoo' has no attribute 'write_landing'`

- [ ] **Step 3: Add `write_landing()` to `backend/app/integrations/odoo.py`**

```python
def write_landing(conn, rows, customers=0):
    """One import_run of source ODOO. Returns the run id.

    Deliberately writes NO customer_block rows: sale.order and res.partner hold
    nothing that answers leasing, tracking, cash, asset or the contact log. The
    absence is the fact, and the schema records it by omission rather than by
    inventing empty blocks that would read as "we looked and there was nothing".
    """
    from .. import landing as landing_schema

    run = landing_schema.start_run(conn, "ODOO")
    for row in rows:
        volt_id = row.get("volt_id")
        if not volt_id:
            continue
        landing_schema.write_customer(conn, run, "ODOO", {
            "volt_id": volt_id,
            "customer_no": row.get("crm_id"),
            "name_roman": (row.get("first_name") or "").strip() or None,
            "name_th": row.get("thai_name"),
            "epc": row.get("epc"),
            "product": "LEASE" if row.get("order_type") == "Leasing" else "CASH",
            "sales_lead": row.get("sales_lead"),
            "phone_masked": row.get("phone_masked"),
            "phone_e164": row.get("phone_e164"),
            "email_masked": row.get("email_masked"),
            "source_refs": [],
        })
        landing_schema.write_order(conn, run, "ODOO", volt_id, {
            "no": row.get("no"),
            "crm_id": row.get("crm_id"),
            "order_type": row.get("order_type"),
            "order_status": row.get("sheet_order_status"),
            "loan_status": row.get("loan_status"),
            "submit_date": row.get("submit_date"),
            "amount_total": row.get("amount_total"),
            "source_ref": [],
        })
    landing_schema.finish_run(conn, run, "OK",
                              row_counts={"orders": len(rows), "customers": customers})
    return run
```

- [ ] **Step 4: Make `sync()` and `cached_snapshot()` use it**

In `sync()`, after `snapshot` is assembled and before the `return`, replace the unconditional file write with:

```python
    from .. import db
    if db.configured():
        conn = db.connect()
        try:
            with conn.begin():
                write_landing(conn, rows, customers=len(partners))
        finally:
            conn.close()
    else:
        # No database: the JSON cache is still the middle rung, as it always was.
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1))
    return snapshot
```

And in `cached_snapshot()`:

```python
def cached_snapshot():
    from .. import db, landing as landing_schema
    if db.configured():
        conn = db.connect()
        try:
            run = landing_schema.last_run(conn, "ODOO")
        finally:
            conn.close()
        if not run:
            return None
        return {"source": {"system": "Odoo UAT", "url_env": "ODOO_URL", "db_env": "ODOO_DB",
                           "synced_at": run["finished_at"].isoformat() if run["finished_at"] else None,
                           "orders": (run["row_counts"] or {}).get("orders", 0),
                           "customers": (run["row_counts"] or {}).get("customers", 0)},
                "orders": []}
    if SNAPSHOT_PATH.is_file():
        try:
            return json.loads(SNAPSHOT_PATH.read_text())
        except (ValueError, OSError):
            return None
    return None
```

- [ ] **Step 5: Run the tests, the suite, then commit**

```bash
cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_odoo_landing.py -v   # 3 passed
cd backend && .venv/bin/python -m pytest                                                                                 # at or above 569
git add backend/app/integrations/odoo.py backend/tests/test_odoo_landing.py
git commit -m "feat(odoo): the sync lands in Postgres, so the snapshot rung finally exists"
```

---

### Task 9: The Odoo 500-partner cap

`sync()` fetches partners with `{"limit": 500}` against an instance whose own code comment records ~127,963 of them, and *"missed every one of the five live orders on 2026-09-09, which is how they all rendered '(no name)'."* Rehosting that bug into a new environment is not acceptable.

**The fix is not pagination.** Fetching only the partner ids the orders in hand actually reference is bounded by the order count rather than the partner count — one request instead of 256.

**Files:**
- Modify: `backend/app/integrations/odoo.py:sync()`
- Test: `backend/tests/test_odoo_pagination.py`

**Interfaces:**
- Produces: `odoo._fetch_partners(config, uid, partner_ids) -> dict[int, dict]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_odoo_pagination.py`:

```python
"""Every order resolves a name, however many partners the instance holds.

The old code fetched the first 500 of ~127,963 partners and joined against that,
so an order whose partner sat at index 90,000 rendered "(no name)". The fix asks
for the ids the orders actually reference.
"""
from app.integrations import odoo


class FakeOdoo:
    """Stands in for execute_kw. Records what was asked for."""

    def __init__(self, partner_count=127963):
        self.partner_count = partner_count
        self.calls = []

    def __call__(self, config, uid, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        if model == "res.partner":
            domain = args[0] if args else []
            ids = []
            for clause in domain:
                if isinstance(clause, (list, tuple)) and clause[0] == "id":
                    ids = list(clause[2])
            return [{"id": i, "name": "Partner %d" % i, "phone": "0812345678",
                     "mobile": None, "email": "p%d@x.co" % i, "city": "Bangkok"}
                    for i in ids]
        return []


def test_partners_are_fetched_by_id_not_by_the_first_page(monkeypatch):
    fake = FakeOdoo()
    monkeypatch.setattr(odoo, "_execute", fake)
    partners = odoo._fetch_partners({}, 1, [90000, 90001])
    assert set(partners) == {90000, 90001}
    model, method, args, kwargs = fake.calls[0]
    assert model == "res.partner" and method == "search_read"
    assert args[0] == [("id", "in", [90000, 90001])]
    assert not (kwargs or {}).get("limit"), "a limit would reintroduce the cap"


def test_an_empty_id_list_asks_odoo_nothing(monkeypatch):
    fake = FakeOdoo()
    monkeypatch.setattr(odoo, "_execute", fake)
    assert odoo._fetch_partners({}, 1, []) == {}
    assert fake.calls == []


def test_a_partner_far_past_the_old_cap_still_resolves(monkeypatch):
    fake = FakeOdoo()
    monkeypatch.setattr(odoo, "_execute", fake)
    partners = odoo._fetch_partners({}, 1, [126000])
    assert partners[126000]["name"] == "Partner 126000"
```

- [ ] **Step 2: Run it and verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_odoo_pagination.py -v`
Expected: FAIL — `module ... has no attribute '_fetch_partners'`

- [ ] **Step 3: Add `_fetch_partners` and use it in `sync()`**

```python
def _fetch_partners(config, uid, partner_ids):
    """The partners the orders in hand actually reference — and only those.

    The old call was search_read([], limit=500) against ~127,963 partners, so the
    join hit whichever 500 Odoo happened to return first. On 2026-09-09 that was
    none of the five live orders, and every one rendered "(no name)". Asking by id
    is one request bounded by the order count, not 256 bounded by the partner count.
    """
    ids = sorted({int(i) for i in partner_ids if i})
    if not ids:
        return {}
    rows = _execute(config, uid, "res.partner", "search_read",
                    [[("id", "in", ids)]],
                    {"fields": ["name", "phone", "mobile", "email", "city"]})
    return {row["id"]: row for row in rows}
```

Then in `sync()`, delete the capped `partners = {...}` fetch, move `raw_orders` above it, and replace with:

```python
    raw_orders = _execute(
        config, uid, "sale.order", "search_read",
        [[]], {"fields": ["name", "partner_id", "amount_total", "state",
                          "date_order", "user_id"], "limit": 500})
    partners = _fetch_partners(
        config, uid, [(o.get("partner_id") or [None])[0] for o in raw_orders])
```

Delete the now-stale comment about the 500-row cap and the five orders, and leave a one-line note that the join is by id.

- [ ] **Step 4: Run the tests, the suite, then commit**

```bash
cd backend && .venv/bin/python -m pytest tests/test_odoo_pagination.py -v   # 3 passed
cd backend && .venv/bin/python -m pytest                                    # at or above 569
git add backend/app/integrations/odoo.py backend/tests/test_odoo_pagination.py
git commit -m "fix(odoo): fetch partners by id, so every order resolves a name"
```

---

### Task 10: `scripts/provision_stg.sh`

Independent of Tasks 1–9; starts immediately. **Creates nothing until Arina has authenticated**, and prints every command before running it.

**Files:**
- Create: `scripts/provision_stg.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Stand up the Volt Debt staging estate on an EXISTING project.
#
#   ./scripts/provision_stg.sh              # dry run: prints every command, changes nothing
#   ./scripts/provision_stg.sh --apply      # actually creates
#
# Thin by decision (spec §4). Cloud Run's native Cloud SQL connector needs no VPC,
# no serverless connector and no NAT, which is what keeps this to one page.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT to the GCP project id, e.g. volt-debt-stg}"
REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-volt-debt-uat}"
INSTANCE="${INSTANCE:-debt-pg-stg}"
DB_NAME="${DB_NAME:-debt}"
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1

[ -f "$HOME/.volt-gcloud-env" ] && . "$HOME/.volt-gcloud-env"

run() {
  printf '\033[36m$ %s\033[0m\n' "$*"
  [ "$APPLY" -eq 1 ] && "$@"
  return 0
}
say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

say "Preflight"
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
  echo "No active account. Run:  gcloud auth login" >&2; exit 1
fi
if ! gcloud beta billing projects describe "$PROJECT" \
     --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  echo "Billing is not enabled on $PROJECT." >&2; exit 1
fi
[ "$APPLY" -eq 1 ] || echo "DRY RUN — nothing will be created. Re-run with --apply."

say "APIs"
run gcloud services enable run.googleapis.com sqladmin.googleapis.com \
    secretmanager.googleapis.com cloudscheduler.googleapis.com \
    cloudbuild.googleapis.com artifactregistry.googleapis.com iap.googleapis.com \
    --project "$PROJECT" --quiet

say "Service accounts"
for sa in debt-api-sa debt-jobs-sa; do
  run gcloud iam service-accounts create "$sa" --project "$PROJECT" \
      --display-name "$sa" --quiet
done
for sa in debt-api-sa debt-jobs-sa; do
  for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
    run gcloud projects add-iam-policy-binding "$PROJECT" \
        --member "serviceAccount:$sa@$PROJECT.iam.gserviceaccount.com" \
        --role "$role" --quiet
  done
done

say "Cloud SQL — PostgreSQL 16, no public IP, IAM auth"
run gcloud sql instances create "$INSTANCE" --project "$PROJECT" \
    --database-version POSTGRES_16 --tier db-custom-1-3840 --region "$REGION" \
    --storage-type SSD --storage-size 20 --storage-auto-increase \
    --no-assign-ip --availability-type ZONAL \
    --database-flags cloudsql.iam_authentication=on \
    --backup-start-time 18:00 --enable-point-in-time-recovery --quiet
run gcloud sql databases create "$DB_NAME" --instance "$INSTANCE" --project "$PROJECT" --quiet
for sa in debt-api-sa debt-jobs-sa; do
  run gcloud sql users create "$sa@$PROJECT.iam" --instance "$INSTANCE" \
      --project "$PROJECT" --type CLOUD_IAM_SERVICE_ACCOUNT --quiet
done

say "Secrets — names only; values are pushed separately from backend/.env"
for name in ODOO_URL ODOO_DB ODOO_LOGIN ODOO_API_KEY \
            PEAK_UAT_CONNECT_ID PEAK_UAT_PASSWORD PEAK_UAT_USER_TOKEN; do
  run gcloud secrets create "$name" --project "$PROJECT" --replication-policy automatic --quiet
done

say "Budget alert"
echo "  (budgets need a billing account id; see the guidebook — one console step)"

cat <<OUT

Next, in order:
  1. ./scripts/push_secrets.sh --apply       # reads backend/.env, echoes no values
  2. ./scripts/deploy_gcp.sh                 # builds and deploys, attaches Cloud SQL
  3. gcloud run jobs execute debt-migrate --region $REGION
OUT
```

`chmod +x scripts/provision_stg.sh`

- [ ] **Step 2: Write `scripts/push_secrets.sh`**

```bash
#!/usr/bin/env bash
# Push the seven secret values from backend/.env into Secret Manager.
#
# Values are piped from the file straight into gcloud. They are never echoed, never
# passed as an argument (argv is visible in ps), and never written to a log. This is
# the "from a laptop, never via CI" step of GCP Architecture v1.0 §15.1.
set -euo pipefail
PROJECT="${PROJECT:?set PROJECT}"
ENV_FILE="${ENV_FILE:-backend/.env}"
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
NAMES="ODOO_URL ODOO_DB ODOO_LOGIN ODOO_API_KEY PEAK_UAT_CONNECT_ID PEAK_UAT_PASSWORD PEAK_UAT_USER_TOKEN"

[ -f "$ENV_FILE" ] || { echo "$ENV_FILE not found" >&2; exit 1; }
for name in $NAMES; do
  value="$(grep -E "^$name=" "$ENV_FILE" | head -1 | cut -d= -f2-)"
  if [ -z "$value" ]; then echo "  $name: EMPTY in $ENV_FILE — skipped"; continue; fi
  if [ "$APPLY" -eq 1 ]; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=- >/dev/null
    echo "  $name: version added"
  else
    echo "  $name: would add one version (${#value} bytes)"
  fi
done
```

`chmod +x scripts/push_secrets.sh`

- [ ] **Step 3: Verify the dry run reaches its end without touching anything**

Run: `PROJECT=volt-debt-stg ./scripts/provision_stg.sh`
Expected: it stops at the preflight with `No active account. Run: gcloud auth login` — which is correct and is itself the proof that nothing can be created before Arina authenticates.

Run: `PROJECT=volt-debt-stg ./scripts/push_secrets.sh`
Expected: seven lines reading `would add one version (N bytes)`, and **no values printed**.

- [ ] **Step 4: Commit**

```bash
git add scripts/provision_stg.sh scripts/push_secrets.sh
git commit -m "feat(gcp): provisioning and secret-push scripts, dry-run by default"
```

---

### Task 11: Cloud Run Jobs, the CI fix, and the deploy

**Files:**
- Create: `backend/app/jobs/__init__.py`, `backend/app/jobs/odoo_sync.py`
- Modify: `infra/cloudbuild.yaml:12`, `scripts/deploy_gcp.sh`

- [ ] **Step 1: Fix the doubled `-q` in CI**

`infra/cloudbuild.yaml:12` runs `pytest -q` while `backend/pytest.ini:4` already sets it. The doubled flag collapses the summary into bare dots that read exactly like a failure — the same trap the README warns about for local runs. Change `pytest -q` to `pytest`.

- [ ] **Step 2: Write the sync job entrypoint**

`backend/app/jobs/__init__.py` — empty file.

`backend/app/jobs/odoo_sync.py`:

```python
"""The debt-odoo-sync Cloud Run Job.

A Job and not an HTTP endpoint, deliberately: the service sits behind IAP, so
Scheduler → Cloud Run would have to mint an OIDC token for the IAP client id. A
Job runs this function with no HTTP and no IAP anywhere in the path.

Exit codes: 0 synced · 1 Odoo or the database refused · 2 not configured.
"""
import sys

from .. import db
from ..integrations import odoo


def main():
    if not db.configured():
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        snapshot = odoo.sync()
    except odoo.NotConfigured as exc:
        print("odoo is not configured: missing %s" % ", ".join(exc.missing), file=sys.stderr)
        return 2
    except (odoo.OdooError, db.DatabaseUnreachable) as exc:
        # The run is already recorded FAILED, so serving degrades down the chain
        # to the last good landing rows and then to the sheet. Nothing half-written
        # is ever visible.
        print("sync failed: %s" % exc, file=sys.stderr)
        return 1
    source = snapshot.get("source") or {}
    print("synced orders=%s customers=%s" % (source.get("orders"), source.get("customers")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Extend `scripts/deploy_gcp.sh`**

After the existing `gcloud run deploy`, add the Cloud SQL attachment, the secrets and `DATABASE_URL`, then create both Jobs and the Scheduler job:

```bash
say "Attaching Cloud SQL, the secrets, and DATABASE_URL"
CONN="$PROJECT:$REGION:${INSTANCE:-debt-pg-stg}"
DB_URL="postgresql+psycopg://debt-api-sa@$PROJECT.iam@/debt?host=/cloudsql/$CONN"
gcloud run services update "$SERVICE" --region "$REGION" \
  --add-cloudsql-instances "$CONN" \
  --service-account "debt-api-sa@$PROJECT.iam.gserviceaccount.com" \
  --set-env-vars "DATABASE_URL=$DB_URL" \
  --set-secrets "ODOO_URL=ODOO_URL:latest,ODOO_DB=ODOO_DB:latest,ODOO_LOGIN=ODOO_LOGIN:latest,ODOO_API_KEY=ODOO_API_KEY:latest,PEAK_UAT_CONNECT_ID=PEAK_UAT_CONNECT_ID:latest,PEAK_UAT_PASSWORD=PEAK_UAT_PASSWORD:latest,PEAK_UAT_USER_TOKEN=PEAK_UAT_USER_TOKEN:latest" \
  --quiet

say "Cloud Run Jobs"
for job in "debt-migrate:app.migrate" "debt-odoo-sync:app.jobs.odoo_sync"; do
  name="${job%%:*}"; module="${job##*:}"
  gcloud run jobs deploy "$name" --region "$REGION" --source backend \
    --command python --args "-m,$module" \
    --set-cloudsql-instances "$CONN" \
    --service-account "debt-jobs-sa@$PROJECT.iam.gserviceaccount.com" \
    --set-env-vars "DATABASE_URL=$DB_URL" --quiet
done

say "Nightly reconciliation (D-15)"
gcloud scheduler jobs create http odoo-reconcile --location "$REGION" \
  --schedule "0 2 * * *" --time-zone "Asia/Bangkok" \
  --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/debt-odoo-sync:run" \
  --http-method POST \
  --oauth-service-account-email "debt-jobs-sa@$PROJECT.iam.gserviceaccount.com" \
  --quiet || echo "  (already exists)"
```

- [ ] **Step 4: Verify what can be verified without credentials**

```bash
bash -n scripts/deploy_gcp.sh && echo "deploy_gcp.sh: syntax ok"
cd backend && .venv/bin/python -c "import app.jobs.odoo_sync, app.migrate; print('job entrypoints import')"
cd backend && DATABASE_URL= .venv/bin/python -m app.jobs.odoo_sync; echo "exit=$? (expect 2)"
grep -n "pytest" ../infra/cloudbuild.yaml
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs infra/cloudbuild.yaml scripts/deploy_gcp.sh
git commit -m "feat(gcp): both Cloud Run Jobs, the Scheduler job, and CI's doubled -q"
```

---

### Task 12: The guidebook

Independent of every other task; starts immediately. Lands in the Obsidian vault beside the two notes already there.

**Files:**
- Create, in `/Users/parattakorn/Documents/Obsidian Vault/Debt modules (self build)/`:
  - `02 - Setup Guide - What You Do.md`
  - `03 - Setup Guide - What I Do.md`
  - `04 - Gap List and Promotion to Production.md`
  - `05 - Rollback and Teardown.md`
- Modify: `00 - README & Source Map.md` (link the four)

- [ ] **Step 1: Write note 02 — the manual steps**

Every command exact, each with what it is for, what a good result looks like, and what to do when it fails. Four steps: `gcloud auth login`; confirm project and billing; the IAP OAuth consent screen (console-only, with the console path spelled out); `./scripts/push_secrets.sh --apply`. Include the `~/.volt-gcloud-env` sourcing, because gcloud refuses macOS's Python 3.9.

- [ ] **Step 2: Write note 03 — the automated steps**

The `provision_stg.sh` and `deploy_gcp.sh` command list, in order, so the work is auditable rather than opaque. State plainly that these run **as Arina**, using her credentials, after step 1 of note 02.

- [ ] **Step 3: Write note 04 — the gap list**

The seven rows of spec §7, each with what adding it would take. Cross-link `[[01 - GCP Staging Design]]`.

- [ ] **Step 4: Write note 05 — rollback and teardown**

`gcloud run services delete`, `gcloud run jobs delete`, `gcloud scheduler jobs delete`, `gcloud sql instances delete`, `gcloud secrets delete`. A staging environment that cannot be deleted is a cost leak. Include the Cloud SQL stop/start commands as the cheaper alternative to deletion.

- [ ] **Step 5: Link them from note 00 and verify every wikilink resolves**

```bash
D="/Users/parattakorn/Documents/Obsidian Vault/Debt modules (self build)"
grep -oh '\[\[[^]]*\]\]' "$D"/*.md | sort -u | sed 's/\[\[//;s/\]\]//' | \
  while read -r n; do [ -f "$D/$n.md" ] && echo "OK   $n" || echo "MISS $n"; done
```
Expected: every line `OK`.

---

### Task 13: The verification gate

**REQUIRED SUB-SKILL:** `superpowers:verification-before-completion`.

- [ ] **Step 1: The full harness, with no database configured**

```bash
cd /Users/parattakorn/volt-debt-prototype && DATABASE_URL= ./scripts/verify_all.sh
```
Expected: **EVERYTHING PASSED**, at or above **569 backend / 443 frontend (33 files) / 29 e2e**. Paste the counts. This proves acceptance criteria 1 and 2 together: the unconfigured path is unchanged.

- [ ] **Step 2: The full harness, with the local database configured**

```bash
./scripts/pg_local.sh start
cd backend && DATABASE_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m app.migrate
cd /Users/parattakorn/volt-debt-prototype && \
  DATABASE_URL="$(./scripts/pg_local.sh url)" ./scripts/verify_all.sh
```
Expected: the same counts.

- [ ] **Step 3: Acceptance criterion 4 — the sheet loads and reconciles**

```bash
cd backend && DATABASE_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -c "
import json, sys; sys.path.insert(0,'.')
from app import db, sheet_loader
payload = json.load(open('app/fixtures_sheet.json'))
conn = db.connect()
with conn.begin():
    print(sheet_loader.load_payload(conn, payload))
"
```
Expected: `customers: 418`.

- [ ] **Step 4: Acceptance criterion 6 — restart survival, end to end**

Start the API, POST something that mutates session state, kill the process, start it again with the same `DATABASE_URL` and the same cookie, and read it back. Expected: the value is still there. This is **the criterion the whole design exists to satisfy** — if it does not hold, nothing else in this plan matters.

- [ ] **Step 5: Acceptance criterion 7 — refusal, not silence**

```bash
cd backend && DATABASE_URL="postgresql+psycopg://volt@127.0.0.1:1/gone" \
  .venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from app import book_source, db
try:
    book_source.load(); print('FAIL: it fell back instead of refusing')
except db.DatabaseUnreachable as exc:
    print('ok, refused:', str(exc)[:60])
"
```
Expected: `ok, refused: ...`.

- [ ] **Step 6: Report honestly**

State: the three counts, which acceptance criteria hold, which do not, and **which cannot be tested at all without Arina's `gcloud auth login`** — that is criteria 5 and 8, and every GCP resource. Do not report a criterion as met on the strength of a dry run.
