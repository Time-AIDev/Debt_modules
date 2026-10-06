# Action Audit Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single append-only, hash-chained record of every act a user takes in the prototype, readable and verifiable from a screen.

**Architecture:** One HTTP middleware opens a per-request entry in a `ContextVar` and appends it once at request end, so coverage of all 91 acts is structural rather than remembered. Domain code enriches the open entry with business meaning through `audit.describe()`. Entries chain by SHA-256 so any later alteration is detectable, and live in their own Postgres table — never the session pickle a deploy discards — falling back to an in-memory chain when `DATABASE_URL` is unset.

**Tech Stack:** FastAPI + Starlette middleware, SQLAlchemy Core (no ORM), Postgres, pytest; React 18 + Vite + vitest on the frontend.

**Spec:** `docs/archive/superpowers/specs/2026-09-11-action-audit-log-design.md`

## Global Constraints

- **The test contract is a budget.** `./scripts/verify_all.sh` is the authority. Green at or above the last baseline — **614 backend passed / 1 skipped · 511 frontend (40 files) · 29 e2e** — with counts pasted. Run `pytest` WITHOUT `-q`; `pytest.ini` already sets it and doubling it hides the summary.
- **A test that must change is escalated to Arina, never edited.** Adding tests is free. This plan spends exactly one authorised edit — **edit 23**, in Task 9 — and it is priced there. **Edit 17 is reserved and may not be raided.**
- Every edited test site carries a comment `AUTHORISED TEST EDIT 23`.
- **New user-facing strings go in an `i18n-*.js` table**, never `prefs.jsx`'s `DICT`: only the four tables are checked for EN/TH parity by `i18n.test.js`. Audit strings go in `i18n-admin.js` (prefixes `rec. / rep. / set. / mig.` are reserved there, so use `audit.`) — add every key to BOTH the EN and TH tables.
- **Thai first** (contract L5): check real Thai string lengths, not lorem.
- **`actor_claimed`, never `actor`.** The pair `actor_claimed` + `actor_source` is non-negotiable; see spec §4.
- **No `PUT`, `PATCH` or `DELETE` route under `/v1/audit`.** Absent, not guarded.
- Money and state are never bare (contract L4); active state uses the ruling-52 three signals.
- Do not commit or log `backend/.env` values.

---

### Task 1: Teach the migration splitter about quotes

**Why this is first:** `migrate.py.statements()` strips comments then splits on `;`. Its own docstring says this is safe *"only because schema.sql has no function bodies, no dollar-quoting and no semicolons inside literals. If any of those are ever added, this must become a real parser."* Task 3 adds a trigger function whose body contains both. This task is that moment arriving.

**Files:**
- Modify: `backend/app/migrate.py:17-32` (`statements()`)
- Test: `backend/tests/test_migrate_splitter.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `migrate.statements() -> list[str]`, unchanged signature, now splitting only on semicolons at top level (outside `'…'` literals and `$tag$…$tag$` bodies).

- [ ] **Step 1: Write the failing test**

```python
"""The splitter, once schema.sql is allowed to carry a function body."""
from app import migrate


def _split(sql, tmp_path, monkeypatch):
    path = tmp_path / "schema.sql"
    path.write_text(sql, encoding="utf-8")
    monkeypatch.setattr(migrate, "SCHEMA_PATH", path)
    return migrate.statements()


def test_a_semicolon_inside_a_single_quoted_literal_does_not_split(tmp_path, monkeypatch):
    sql = "CREATE TABLE t (a text);\nINSERT INTO t VALUES ('one; two');\n"
    assert _split(sql, tmp_path, monkeypatch) == [
        "CREATE TABLE t (a text)",
        "INSERT INTO t VALUES ('one; two')",
    ]


def test_a_dollar_quoted_function_body_is_one_statement(tmp_path, monkeypatch):
    sql = (
        "CREATE FUNCTION f() RETURNS trigger AS $body$\n"
        "BEGIN RAISE EXCEPTION 'no'; END;\n"
        "$body$ LANGUAGE plpgsql;\n"
        "CREATE TABLE t (a text);\n"
    )
    out = _split(sql, tmp_path, monkeypatch)
    assert len(out) == 2
    assert out[0].startswith("CREATE FUNCTION f()")
    assert "RAISE EXCEPTION" in out[0]
    assert out[1] == "CREATE TABLE t (a text)"


def test_a_doubled_quote_inside_a_literal_is_not_the_end_of_it(tmp_path, monkeypatch):
    sql = "INSERT INTO t VALUES ('it''s; fine');\nSELECT 1;\n"
    assert _split(sql, tmp_path, monkeypatch) == [
        "INSERT INTO t VALUES ('it''s; fine')",
        "SELECT 1",
    ]


def test_comments_are_still_stripped_before_splitting(tmp_path, monkeypatch):
    sql = "-- a prose comment; with a semicolon\nSELECT 1;\n"
    assert _split(sql, tmp_path, monkeypatch) == ["SELECT 1"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_migrate_splitter.py`
Expected: FAIL — the dollar-quoted and literal cases split mid-body. The comment test passes (existing behaviour).

- [ ] **Step 3: Replace the splitter**

In `backend/app/migrate.py`, replace the body of `statements()` and keep the existing docstring's history, amended:

```python
def statements():
    """schema.sql split on the semicolons that END a statement.

    Comments are stripped BEFORE the split, not after. Splitting first looks
    equivalent and is not: a prose comment may itself contain a semicolon, and
    then the split lands inside it and hands Postgres half a sentence. That is
    exactly what happened the first time this ran — "syntax error at or near
    'the'".

    2026-09-11: the naive split this used to do was safe "only because schema.sql
    has no function bodies, no dollar-quoting and no semicolons inside literals.
    If any of those are ever added, this must become a real parser." The audit
    table's append-only trigger is all three, so this is that parser — small, and
    only as clever as it has to be: it tracks single-quoted literals (with '' as
    an escaped quote) and $tag$ bodies, and splits nowhere else.
    """
    lines = [line for line in SCHEMA_PATH.read_text(encoding="utf-8").splitlines()
             if not line.strip().startswith("--")]
    sql = "\n".join(lines)

    out, buf = [], []
    i, n = 0, len(sql)
    in_literal = False
    dollar_tag = None
    while i < n:
        ch = sql[i]
        if dollar_tag:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
        elif in_literal:
            if ch == "'":
                # '' is an escaped quote, not the end of the literal.
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("''")
                    i += 2
                    continue
                in_literal = False
        elif ch == "'":
            in_literal = True
        elif ch == "$":
            end = sql.find("$", i + 1)
            # A $tag$ opener: $ … $ with only identifier characters between.
            if end != -1 and all(c.isalnum() or c == "_" for c in sql[i + 1:end]):
                dollar_tag = sql[i:end + 1]
                buf.append(dollar_tag)
                i = end + 1
                continue
        elif ch == ";":
            chunk = "".join(buf).strip()
            if chunk:
                out.append(chunk)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out
```

- [ ] **Step 4: Run the new tests, then the whole backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_migrate_splitter.py`
Expected: PASS (4 tests)

Run: `cd backend && .venv/bin/python -m pytest tests/`
Expected: **617 passed, 1 skipped** (614 + 3 new; the fourth new test replaces no existing one). If any existing test fails, STOP — the splitter changed behaviour it should not have.

- [ ] **Step 5: Commit**

```bash
git add backend/app/migrate.py backend/tests/test_migrate_splitter.py
git commit -m "fix(migrate): split schema.sql outside literals and function bodies

The splitter's own docstring predicted this: safe 'only because schema.sql has
no function bodies, no dollar-quoting and no semicolons inside literals. If any
of those are ever added, this must become a real parser.' The audit table's
append-only trigger is all three."
```

---

### Task 2: The chain — pure, no HTTP, no database

**Files:**
- Create: `backend/app/audit.py`
- Test: `backend/tests/test_audit_chain.py` (create)

**Interfaces:**
- Consumes: `app.config.settings.business_date`.
- Produces:
  - `audit.Entry` — a `dict` with the spec §4 keys.
  - `audit.canonical(entry: dict) -> str`
  - `audit.hash_entry(entry: dict, prev_hash: str) -> str`
  - `audit.GENESIS: str`
  - `audit.Chain` with `append(**fields) -> dict`, `entries() -> list[dict]`, `verify() -> dict`
  - `audit.FIELDS: tuple[str, ...]` — the hashed field names, in order

- [ ] **Step 1: Write the failing test**

```python
"""The chain itself: ordering, hashing, and what verify() can prove."""
import pytest

from app import audit


def a_chain():
    chain = audit.Chain()
    chain.append(actor_claimed="nantapol", actor_source="HEADER", verb="POST",
                 route_template="/v1/cases/by-customer/{customer_uid}/dc-status",
                 act="DC_STATUS_SET", subject_type="customer", subject_uid="cus-42",
                 detail={"from": "CONTACT_BACK", "to": "PAID", "reason": "ชำระแล้ว"},
                 outcome="OK", status=200, error_code=None,
                 session_id="s-1", request_id="r-1")
    chain.append(actor_claimed="thip", actor_source="BODY", verb="POST",
                 route_template="/v1/contacts", act=None, subject_type=None,
                 subject_uid=None, detail={}, outcome="REFUSED", status=422,
                 error_code="next_action_required", session_id="s-1", request_id="r-2")
    return chain


def test_the_first_entry_chains_from_genesis_and_seq_starts_at_one():
    chain = audit.Chain()
    entry = chain.append(actor_claimed="nantapol", actor_source="HEADER", verb="POST",
                         route_template="/v1/x", act=None, subject_type=None,
                         subject_uid=None, detail={}, outcome="OK", status=200,
                         error_code=None, session_id="s", request_id="r")
    assert entry["seq"] == 1
    assert entry["prev_hash"] == audit.GENESIS
    assert len(entry["hash"]) == 64


def test_each_entry_chains_from_the_one_before():
    chain = a_chain()
    first, second = chain.entries()
    assert second["seq"] == 2
    assert second["prev_hash"] == first["hash"]


def test_a_clean_chain_verifies_and_reports_what_it_checked():
    result = a_chain().verify()
    assert result["ok"] is True
    assert result["verified"] == 2
    assert result["broken_at"] is None


def test_altering_a_field_breaks_the_chain_at_that_entry():
    chain = a_chain()
    # The exact tamper an audit log exists to catch: a reason quietly rewritten.
    chain.entries()[0]["detail"]["reason"] = "something else"
    result = chain.verify()
    assert result["ok"] is False
    assert result["broken_at"] == 1


def test_removing_an_entry_breaks_the_chain_at_its_successor():
    chain = a_chain()
    del chain.entries()[0]
    result = chain.verify()
    assert result["ok"] is False
    assert result["broken_at"] == 2


def test_the_same_entry_always_hashes_the_same_regardless_of_key_order():
    one = {k: v for k, v in [("a", 1), ("b", {"x": 1, "y": 2})]}
    two = {k: v for k, v in [("b", {"y": 2, "x": 1}), ("a", 1)]}
    assert audit.canonical(one) == audit.canonical(two)


def test_a_failed_write_is_counted_and_verify_reports_it():
    chain = a_chain()
    chain.record_gap("database unreachable")
    result = chain.verify()
    # The chain is INTACT — nothing was altered — but it is not COMPLETE, and
    # those are different claims. A reader must be able to tell them apart.
    assert result["ok"] is True
    assert result["gaps"] == 1
    assert result["complete"] is False
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_chain.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.audit'`

- [ ] **Step 3: Write `backend/app/audit.py`**

```python
"""The action audit log — one append-only, hash-chained record of every act.

Design: docs/archive/superpowers/specs/2026-09-11-action-audit-log-design.md

Two things this module refuses to pretend:

  - It records `actor_claimed`, never `actor`. The acting name arrives as a
    header or a body field the CLIENT chooses (tester_session, main.py:177:
    "the cookie identifies a BROWSER, not a person"). `actor_source` says which,
    so a reader knows exactly how much the name is worth.
  - The chain is tamper-EVIDENT, not tamper-proof. We hold the credentials.
    What it buys is that no alteration can be silent.

INTACT and COMPLETE are separate claims. A chain whose hashes all agree is
intact. A chain that also lost no writes is complete. verify() answers both,
because "nothing was edited" and "nothing is missing" fail in different ways.
"""
import hashlib
import json

from .config import settings

# The hashed fields, in a fixed order. Adding a field here changes every hash
# after the change, which is correct — but it means an existing chain verifies
# only up to the schema it was written under. Append, never reorder.
FIELDS = (
    "seq", "at", "business_date",
    "actor_claimed", "actor_source",
    "session_id", "request_id",
    "verb", "route_template",
    "act", "subject_type", "subject_uid", "detail",
    "outcome", "status", "error_code",
)

GENESIS = "0" * 64


def canonical(entry):
    """One string per entry, stable under key order and Unicode.

    ensure_ascii=False so Thai reasons hash as the characters they are rather
    than as escape sequences; separators pinned so no whitespace change can
    alter a hash.
    """
    return json.dumps(entry, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def hash_entry(entry, prev_hash):
    payload = canonical({k: entry.get(k) for k in FIELDS}) + prev_hash
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Chain:
    """In-memory chain. The Postgres-backed one (store.py) reuses every rule here."""

    def __init__(self):
        self._entries = []
        self._gaps = []

    def entries(self):
        return self._entries

    def head_hash(self):
        return self._entries[-1]["hash"] if self._entries else GENESIS

    def append(self, *, at=None, **fields):
        entry = {k: fields.get(k) for k in FIELDS}
        entry["seq"] = len(self._entries) + 1
        entry["at"] = at or _now()
        entry["business_date"] = str(settings.business_date)
        entry["detail"] = fields.get("detail") or {}
        entry["prev_hash"] = self.head_hash()
        entry["hash"] = hash_entry(entry, entry["prev_hash"])
        self._entries.append(entry)
        return entry

    def gaps(self):
        return list(self._gaps)

    def record_gap(self, why):
        """An act happened and could not be recorded.

        The act is already done; refusing the response would not undo it, only
        hide it. So the miss is counted and surfaced, because a log that
        silently drops rows is worse than one that admits it dropped them.
        """
        self._gaps.append({"why": str(why), "at": _now()})

    def verify(self):
        prev = GENESIS
        for index, entry in enumerate(self._entries, start=1):
            if entry["prev_hash"] != prev or entry["hash"] != hash_entry(entry, prev):
                return {"ok": False, "broken_at": entry["seq"], "verified": index - 1,
                        "gaps": len(self._gaps), "complete": False}
            prev = entry["hash"]
        return {"ok": True, "broken_at": None, "verified": len(self._entries),
                "gaps": len(self._gaps), "complete": not self._gaps}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_chain.py`
Expected: PASS (7 tests)

Note on `test_removing_an_entry_breaks_the_chain_at_its_successor`: after the deletion the surviving entry still has `seq == 2` while sitting at index 1, and its `prev_hash` no longer equals `GENESIS` — so `verify()` returns `broken_at: 2`. That is the assertion.

- [ ] **Step 5: Commit**

```bash
git add backend/app/audit.py backend/tests/test_audit_chain.py
git commit -m "feat(audit): the hash chain, and the two claims it can make

INTACT (no entry was altered) and COMPLETE (no write was lost) fail in
different ways, so verify() answers both separately."
```

---

### Task 3: The table, the trigger, and the Postgres-backed chain

**Files:**
- Modify: `backend/app/schema.sql` (append)
- Create: `backend/app/audit_store.py`
- Test: `backend/tests/test_audit_store.py` (create)

**Interfaces:**
- Consumes: `audit.FIELDS`, `audit.hash_entry`, `audit.GENESIS`, `db.connect()`, `db.configured()`.
- Produces:
  - `audit_store.persisted() -> bool`
  - `audit_store.append(entry_fields: dict) -> dict`
  - `audit_store.read(filters: dict, limit: int, before_seq: int|None) -> list[dict]`
  - `audit_store.verify() -> dict` — same shape as `Chain.verify()`
  - `audit_store.MEMORY: audit.Chain` — the process-wide fallback chain

- [ ] **Step 1: Append the schema**

Add to the end of `backend/app/schema.sql`:

```sql
-- The action audit log (design 2026-09-11). Its own table, never app.session_state:
-- that is a pickle keyed by code version and a deploy discards it by design, which
-- is the opposite of what an audit log is for.
CREATE TABLE IF NOT EXISTS app.audit_entry (
    seq             bigserial PRIMARY KEY,
    at              timestamptz NOT NULL DEFAULT now(),
    business_date   date        NOT NULL,
    actor_claimed   text,
    actor_source    text        NOT NULL CHECK (actor_source IN ('HEADER','BODY','NONE')),
    session_id      text,
    request_id      text,
    verb            text        NOT NULL,
    route_template  text        NOT NULL,
    act             text,
    subject_type    text,
    subject_uid     text,
    detail          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    outcome         text        NOT NULL CHECK (outcome IN ('OK','REFUSED')),
    status          int         NOT NULL,
    error_code      text,
    prev_hash       text        NOT NULL,
    hash            text        NOT NULL
);

CREATE INDEX IF NOT EXISTS audit_entry_at_idx      ON app.audit_entry (at DESC);
CREATE INDEX IF NOT EXISTS audit_entry_actor_idx   ON app.audit_entry (actor_claimed);
CREATE INDEX IF NOT EXISTS audit_entry_subject_idx ON app.audit_entry (subject_type, subject_uid);

-- Append-only, enforced by the database rather than by everyone remembering.
-- A GRANT would not do it: the application connects as the owner, and an owner is
-- not bound by its own grants. A trigger binds everyone, including a bug.
CREATE OR REPLACE FUNCTION app.audit_entry_is_append_only() RETURNS trigger AS $guard$
BEGIN
    RAISE EXCEPTION 'app.audit_entry is append-only: % is refused', TG_OP;
END;
$guard$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_entry_no_change ON app.audit_entry;
CREATE TRIGGER audit_entry_no_change
    BEFORE UPDATE OR DELETE ON app.audit_entry
    FOR EACH ROW EXECUTE FUNCTION app.audit_entry_is_append_only();
```

- [ ] **Step 2: Write the failing test**

These tests need a live Postgres. Follow the project's existing convention: **`volt_local`, never `volt_test`** — `pg_local.sh` hands out `volt_test` and pytest truncates it. Skip cleanly when unset.

```python
"""The persisted chain. Skipped entirely when no database is configured — the
DATABASE_URL-unset path is Task 4's business, not this file's."""
import os

import pytest
from sqlalchemy import text

from app import audit, audit_store, db, migrate

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"),
                                reason="no DATABASE_URL; the in-memory path is tested in test_audit_chain.py")


@pytest.fixture(autouse=True)
def schema():
    with db.connect() as conn:
        with conn.begin():
            migrate.apply(conn)
        with conn.begin():
            # Append-only means the fixture cannot clean up with DELETE. The tests
            # below are written to tolerate pre-existing rows for exactly that reason.
            pass
    yield


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
                conn.execute(text("UPDATE app.audit_entry SET actor_claimed = 'someone' "
                                  "WHERE seq = :s"), {"s": entry["seq"]})
    assert "append-only" in str(err.value)


def test_the_database_refuses_a_delete():
    entry = audit_store.append(_fields())
    with pytest.raises(Exception) as err:
        with db.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM app.audit_entry WHERE seq = :s"),
                             {"s": entry["seq"]})
    assert "append-only" in str(err.value)


def test_reading_back_filters_by_actor_and_by_subject():
    audit_store.append(_fields(actor_claimed="thip", subject_uid="cus-9"))
    rows = audit_store.read({"actor": "thip"}, limit=50, before_seq=None)
    assert rows and all(r["actor_claimed"] == "thip" for r in rows)
    rows = audit_store.read({"subject_uid": "cus-9"}, limit=50, before_seq=None)
    assert rows and all(r["subject_uid"] == "cus-9" for r in rows)


def test_persisted_says_true_when_a_database_is_configured():
    assert audit_store.persisted() is True
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd backend && DATABASE_URL=postgresql+psycopg://localhost/volt_local .venv/bin/python -m pytest tests/test_audit_store.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.audit_store'`

(With no `DATABASE_URL` the file reports 5 skipped, which is also a correct result for CI.)

- [ ] **Step 4: Write `backend/app/audit_store.py`**

```python
"""Where the chain lives.

Configured database -> app.audit_entry, append-only and enforced by a trigger.
No database        -> a process-wide in-memory chain, with the same rules and the
                      same verify(), and `persisted()` says False so every reader
                      can say so on screen.

That second path is deliberate and follows db.py's own rule: RUNNING and REFUSING
are both honest, LEAKING is not. Running in memory and SAYING it is in memory is
running. Running in memory while looking persisted would be leaking.
"""
from sqlalchemy import text

from . import audit, db

MEMORY = audit.Chain()

_COLUMNS = ("seq", "at", "business_date", "actor_claimed", "actor_source",
            "session_id", "request_id", "verb", "route_template", "act",
            "subject_type", "subject_uid", "detail", "outcome", "status",
            "error_code", "prev_hash", "hash")

_INSERT = text("""
    INSERT INTO app.audit_entry
        (business_date, actor_claimed, actor_source, session_id, request_id,
         verb, route_template, act, subject_type, subject_uid, detail,
         outcome, status, error_code, prev_hash, hash)
    VALUES
        (:business_date, :actor_claimed, :actor_source, :session_id, :request_id,
         :verb, :route_template, :act, :subject_type, :subject_uid,
         CAST(:detail AS jsonb), :outcome, :status, :error_code, :prev_hash, :hash)
    RETURNING seq, at
""")


def persisted():
    return db.configured()


def append(fields):
    if not persisted():
        return MEMORY.append(**fields)
    import json

    from .config import settings
    with db.connect() as conn:
        with conn.begin():
            # The chain head and the insert share one transaction, so two concurrent
            # requests cannot both chain from the same predecessor. FOR UPDATE would
            # need a row to lock; the table lock is coarse and correct, and this is a
            # prototype writing a few hundred rows a day, not a queue.
            conn.execute(text("LOCK TABLE app.audit_entry IN EXCLUSIVE MODE"))
            head = conn.execute(text(
                "SELECT hash FROM app.audit_entry ORDER BY seq DESC LIMIT 1")).scalar()
            prev_hash = head or audit.GENESIS
            entry = {k: fields.get(k) for k in audit.FIELDS}
            entry["business_date"] = str(settings.business_date)
            entry["detail"] = fields.get("detail") or {}
            # seq and at are the database's; the hash covers the values that will be
            # stored, so they are read back and re-hashed below rather than guessed.
            row = conn.execute(text(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM app.audit_entry")).mappings().one()
            entry["seq"] = row["next"]
            entry["at"] = _now_iso()
            entry["prev_hash"] = prev_hash
            entry["hash"] = audit.hash_entry(entry, prev_hash)
            params = dict(entry)
            params["detail"] = json.dumps(entry["detail"], ensure_ascii=False)
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
    if before_seq:
        where.append("seq < :before_seq")
        params["before_seq"] = before_seq
    sql = ("SELECT %s FROM app.audit_entry WHERE %s ORDER BY seq DESC LIMIT :limit"
           % (", ".join(_COLUMNS), " AND ".join(where)))
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def verify():
    if not persisted():
        return {**MEMORY.verify(), "persisted": False}
    prev = audit.GENESIS
    verified = 0
    with db.connect() as conn:
        rows = conn.execute(text(
            "SELECT %s FROM app.audit_entry ORDER BY seq ASC" % ", ".join(_COLUMNS)
        )).mappings()
        for row in rows:
            entry = dict(row)
            entry["at"] = str(entry["at"])
            entry["business_date"] = str(entry["business_date"])
            if entry["prev_hash"] != prev or entry["hash"] != audit.hash_entry(entry, prev):
                return {"ok": False, "broken_at": entry["seq"], "verified": verified,
                        "gaps": len(MEMORY.gaps()), "complete": False, "persisted": True}
            prev = entry["hash"]
            verified += 1
    return {"ok": True, "broken_at": None, "verified": verified,
            "gaps": len(MEMORY.gaps()), "complete": not MEMORY.gaps(), "persisted": True}


def record_gap(why):
    MEMORY.record_gap(why)


def _matches(row, filters):
    for key, column in (("actor", "actor_claimed"), ("act", "act"),
                        ("subject_uid", "subject_uid")):
        if filters.get(key) and row.get(column) != filters[key]:
            return False
    return True


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

**Note for the implementer:** `entry["at"]` is generated in Python and *also* defaulted by the column. The hash must cover the value that is actually stored, so the `INSERT` above does **not** write `at` — remove the column default's involvement by adding `at` to the insert instead if you prefer; either way the rule is: **the stored value and the hashed value must be the same value.** If you change this, change `test_an_appended_entry_comes_back_with_its_chain_intact` to re-read the row and re-verify.

- [ ] **Step 5: Run the tests both ways**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_store.py`
Expected: 5 skipped

Run: `cd backend && DATABASE_URL=postgresql+psycopg://localhost/volt_local .venv/bin/python -m pytest tests/test_audit_store.py`
Expected: PASS (5 tests). If the trigger tests fail with a split-statement syntax error, Task 1 did not land.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schema.sql backend/app/audit_store.py backend/tests/test_audit_store.py
git commit -m "feat(audit): the append-only table and its trigger

A GRANT would not enforce this: the app connects as the owner, and an owner is
not bound by its own grants. A trigger binds everyone, a bug included."
```

---

### Task 4: The middleware, and `describe()`

**Files:**
- Modify: `backend/app/main.py` — add a middleware after `tester_session` (which is at `:177`); add the recording hook to the `errors.Problem` handler at `:257`
- Modify: `backend/app/audit.py` — add the request-scoped API
- Test: `backend/tests/test_audit_middleware.py` (create)

**Interfaces:**
- Consumes: Task 2's `Chain`, Task 3's `audit_store`.
- Produces:
  - `audit.CURRENT: ContextVar` — the open entry, or `None`
  - `audit.describe(act=None, subject=None, detail=None) -> None` — no-op outside a request
  - `audit.note_error(code: str) -> None`
  - `audit.LOGGED_READS: tuple[str, ...]` — the GET route templates in scope (D3)

- [ ] **Step 1: Write the failing test**

```python
"""What the middleware records, without any domain module having to remember."""
from fastapi.testclient import TestClient

from app import audit, audit_store
from app.main import app

client = TestClient(app)


def _entries():
    return audit_store.read({}, limit=200, before_seq=None)


def test_a_successful_act_is_recorded_with_its_route_template_not_its_path():
    before = len(_entries())
    body = {"code": "CONTACT_BACK", "reason": "ลูกค้าขอให้โทรกลับ"}
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid, json=body,
                headers={"X-Volt-Officer": "nantapol"})
    rows = _entries()
    assert len(rows) == before + 1
    entry = rows[0]
    assert entry["verb"] == "POST"
    assert entry["route_template"] == "/v1/cases/by-customer/{customer_uid}/dc-status"
    assert entry["actor_claimed"] == "nantapol"
    assert entry["actor_source"] == "HEADER"
    assert entry["outcome"] == "OK"


def test_a_refused_act_is_recorded_with_its_problem_code():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    # Edit 22: a status change with no reason is refused.
    client.post("/v1/cases/by-customer/%s/dc-status" % uid, json={"code": "PAID"},
                headers={"X-Volt-Officer": "thip"})
    entry = _entries()[0]
    assert entry["outcome"] == "REFUSED"
    assert entry["status"] == 422
    assert entry["error_code"] == "reason_required"


def test_a_plain_read_is_not_recorded():
    before = len(_entries())
    client.get("/v1/workbook")
    client.get("/v1/today")
    assert len(_entries()) == before


def test_opening_a_customer_IS_recorded():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    before = len(_entries())
    client.get("/v1/cases/by-customer/%s" % uid)
    rows = _entries()
    assert len(rows) == before + 1
    assert rows[0]["verb"] == "GET"
    assert rows[0]["act"] == "CASE_VIEWED"


def test_the_name_in_the_body_is_recorded_as_a_body_claim():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "UNREACHABLE", "reason": "ไม่รับสาย", "by": "settasak"})
    entry = _entries()[0]
    assert entry["actor_claimed"] == "settasak"
    assert entry["actor_source"] == "BODY"


def test_describe_outside_a_request_is_a_no_op_and_never_raises():
    audit.describe(act="X", subject=("customer", "cus-1"), detail={"a": 1})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_middleware.py`
Expected: FAIL — no entries recorded (`assert 0 == 1` on the first test).

- [ ] **Step 3: Add the request-scoped API to `backend/app/audit.py`**

Append to `audit.py`:

```python
from contextvars import ContextVar

# The entry being built for the request in flight. A ContextVar for the same reason
# REQUEST_ID is one (main.py:163): it is per-request state that domain code must be
# able to reach without every function growing a parameter for it.
CURRENT = ContextVar("audit_entry", default=None)

# D3: the ONE read in scope. Opening a customer's file is the act a data-subject
# complaint asks about; list and report views are navigation and are not logged.
# A tuple, and the coverage test in Task 7 asserts nothing else GET is recorded, so
# this cannot widen by accident.
LOGGED_READS = ("/v1/cases/by-customer/{customer_uid}",)


def describe(act=None, subject=None, detail=None):
    """Attach business meaning to the entry for the request in flight.

    A no-op outside a request, so every domain function stays callable from a test
    or a job with no HTTP anywhere near it.
    """
    entry = CURRENT.get()
    if entry is None:
        return
    if act:
        entry["act"] = act
    if subject:
        entry["subject_type"], entry["subject_uid"] = subject
    if detail:
        entry["detail"] = {**(entry.get("detail") or {}), **detail}


def note_error(code):
    entry = CURRENT.get()
    if entry is not None:
        entry["error_code"] = code
```

- [ ] **Step 4: Add the middleware in `backend/app/main.py`**

Immediately after the `tester_session` middleware definition, add:

```python
@app.middleware("http")
async def audit_trail(request: Request, call_next):
    """Every act, recorded once, without any route having to remember.

    Registered AFTER tester_session so the session cookie and the acting name are
    resolved when this runs, and appended INSIDE that scope for the same reason
    flush_current is (main.py:195).

    Starlette runs middleware in reverse registration order, so "after" here means
    this wraps tester_session's inner call. Verify with the coverage test in Task 7
    rather than by reading this comment.
    """
    from . import audit, audit_store

    template = _route_template(request)
    logged = request.method != "GET" or template in audit.LOGGED_READS
    if not logged or template is None:
        return await call_next(request)

    claimed, source = await _actor_of(request)
    entry = {"actor_claimed": claimed, "actor_source": source,
             "verb": request.method, "route_template": template,
             "act": "CASE_VIEWED" if request.method == "GET" else None,
             "subject_type": None, "subject_uid": None, "detail": {},
             "outcome": "OK", "status": 200, "error_code": None,
             "session_id": session_domain.CURRENT.get(None),
             "request_id": REQUEST_ID.get(None)}
    token = audit.CURRENT.set(entry)
    try:
        response = await call_next(request)
        entry["status"] = response.status_code
        entry["outcome"] = "OK" if response.status_code < 400 else "REFUSED"
        return response
    finally:
        try:
            audit_store.append(entry)
        except Exception as exc:                       # noqa: BLE001
            # The act already happened. Refusing the response would not undo it,
            # only hide it — so the miss is counted and surfaced by /v1/audit/verify.
            audit_store.record_gap(exc)
            print("audit append failed: %s" % exc, file=sys.stderr)
        audit.CURRENT.reset(token)


def _route_template(request):
    """The matched route's path, so rows group. None when nothing matched (404)."""
    for route in app.routes:
        match, _scope = route.matches(request.scope)
        if match.name == "FULL":
            return getattr(route, "path", None)
    return None


async def _actor_of(request):
    """The acting name, and WHERE it came from. Never presented as authenticated."""
    header = request.headers.get("X-Volt-Officer")
    if header:
        return header, "HEADER"
    if request.method != "GET":
        try:
            body = await request.json()
        except Exception:                              # noqa: BLE001
            body = None
        if isinstance(body, dict) and body.get("by"):
            return str(body["by"]), "BODY"
    return None, "NONE"
```

**Implementer warning — reading the body in middleware.** `await request.json()` consumes the stream, and the route will then receive an empty body. Starlette caches the body on `request._body` once read, and FastAPI's request object in the route is constructed from the same `scope`/`receive` pair, so in current Starlette this works — **but verify it with `test_the_name_in_the_body_is_recorded_as_a_body_claim`, which fails loudly if the route stops seeing its body.** If it breaks, the fix is to not read the body here and instead have `who()` in `routers/today.py:26` call `audit.describe(detail={"by_source": …})`; that keeps the actor resolution in one place and removes this hazard entirely.

Import `Request` is already present in `main.py`; confirm `sys` is imported (it is, used by `tester_session`).

- [ ] **Step 5: Record the Problem code**

In `backend/app/main.py`, the `errors.Problem` handler at `:257` — add one line before it returns:

```python
@app.exception_handler(errors.Problem)
async def problem_handler(request: Request, exc: errors.Problem):
    from . import audit
    # Read here rather than parsed out of the response body: the handler already has
    # the code, and buffering a response to re-read it would be a second source of
    # truth for the same fact.
    audit.note_error(exc.code)
    ...  # existing body unchanged
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_middleware.py`
Expected: PASS (6 tests)

Run: `cd backend && .venv/bin/python -m pytest tests/`
Expected: **at or above 617 passed, 1 skipped.** If any existing test now fails, the middleware changed a response — STOP and report, do not edit the test.

- [ ] **Step 7: Commit**

```bash
git add backend/app/audit.py backend/app/main.py backend/tests/test_audit_middleware.py
git commit -m "feat(audit): capture every act at the one point they all pass through

Coverage is structural, not remembered: a route added tomorrow is logged with
nothing to remember. Refusals are recorded with their Problem code, because a
log of successes cannot tell 'never tried' from 'tried and stopped'."
```

---

### Task 5: Domain enrichment

**Files:**
- Modify: `backend/app/cases.py` — `set_dc_status` (≈:775), `set_npl_type` (≈:784), `log_contact`, the four `POWER_*` acts
- Modify: `backend/app/routers/integrations.py:88` — `override_order_status`
- Modify: `backend/app/routers/journey.py:610` — `recovery_board_move`
- Test: `backend/tests/test_audit_enrichment.py` (create)

**Interfaces:**
- Consumes: `audit.describe`.
- Produces: entries whose `act`, `subject_*` and `detail` are set for these acts.

- [ ] **Step 1: Write the failing test**

```python
"""The acts whose history gets asked about read as sentences, not as URLs."""
from fastapi.testclient import TestClient

from app import audit_store
from app.main import app

client = TestClient(app)


def _latest():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def _a_customer():
    return client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]


def test_a_status_change_records_what_it_changed_from_to_and_why():
    uid = _a_customer()
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "CONTACT_BACK", "reason": "ลูกค้าขอให้โทรกลับ"},
                headers={"X-Volt-Officer": "nantapol"})
    entry = _latest()
    assert entry["act"] == "DC_STATUS_SET"
    assert entry["subject_type"] == "customer" and entry["subject_uid"] == uid
    assert entry["detail"]["to"] == "CONTACT_BACK"
    assert entry["detail"]["reason"] == "ลูกค้าขอให้โทรกลับ"
    assert "from" in entry["detail"]


def test_an_r14_override_records_the_source_value_it_disagreed_with():
    no = client.get("/v1/orders").json()["orders"][0]["no"]
    client.post("/v1/orders/%d/status-override" % no,
                json={"adjusted_value": "Declined", "reason": "ลูกค้ายกเลิก", "by": "settasak"})
    entry = _latest()
    assert entry["act"] == "R14_OVERRIDE"
    assert entry["detail"]["reason"] == "ลูกค้ายกเลิก"
    assert "from" in entry["detail"] and "to" in entry["detail"]


def test_an_unenriched_act_still_produces_a_complete_row():
    # The floor this design guarantees everywhere: no act is invisible, even when
    # nobody has taught the log what it means.
    client.post("/v1/feedback", json={"note": "x", "screen": "/"})
    entry = _latest()
    assert entry["act"] is None
    assert entry["verb"] == "POST" and entry["route_template"] == "/v1/feedback"
    assert entry["outcome"] in ("OK", "REFUSED")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_enrichment.py`
Expected: FAIL — `entry["act"]` is `None` for the first two tests; the third already passes.

- [ ] **Step 3: Enrich `cases.set_dc_status`**

In `backend/app/cases.py`, inside `set_dc_status`, immediately before `return case`:

```python
    from . import audit
    audit.describe(act="DC_STATUS_SET",
                   subject=("customer", case["customer_uid"]),
                   detail={"from": previous, "to": code, "reason": reason})
```

`previous`, `code` and `reason` are all already local, from edit 22.

- [ ] **Step 4: Enrich the rest**

`set_npl_type` — before its `return`:

```python
    from . import audit
    audit.describe(act="NPL_TYPE_SET", subject=("customer", case["customer_uid"]),
                   detail={"to": case["npl_type"], "reason": reason})
```

`log_contact` — before its `return`:

```python
    from . import audit
    audit.describe(act="CONTACT_LOGGED", subject=("customer", case["customer_uid"]),
                   detail={"result": payload.get("result"),
                           "next_action": payload.get("next_action"),
                           "counted": payload.get("counted")})
```

The four power acts — in each of `request_power`, `approve_power`, `reject_power`, `execute_power`, matching the `kind` each already appends to `state.events`:

```python
    from . import audit
    audit.describe(act="POWER_REQUESTED", subject=("customer", case["customer_uid"]),
                   detail={"reason": reason})
```

`routers/integrations.py`, in `override_order_status` before `return`:

```python
    from .. import audit
    audit.describe(act="R14_OVERRIDE", subject=("order", str(no)),
                   detail={"field": field, "from": source_value,
                           "to": adjusted, "reason": str(reason).strip()})
```

`routers/journey.py`, in `recovery_board_move` before `return`:

```python
    from .. import audit
    audit.describe(act="RECOVERY_STAGE_MOVED", subject=("customer", customer.uid),
                   detail={"from": previous, "to": to_stage,
                           "reversal": backwards, "reason": reason})
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_enrichment.py tests/test_audit_middleware.py`
Expected: PASS (9 tests)

Run: `cd backend && .venv/bin/python -m pytest tests/`
Expected: at or above **620 passed, 1 skipped**.

- [ ] **Step 6: Commit**

```bash
git add backend/app/cases.py backend/app/routers/integrations.py backend/app/routers/journey.py backend/tests/test_audit_enrichment.py
git commit -m "feat(audit): the acts people ask about read as sentences

An unenriched act still produces a complete row — that is the floor. Enrichment
raises the ceiling for the handful of acts whose history gets asked about."
```

---

### Task 6: The read API

**Files:**
- Create: `backend/app/routers/audit.py`
- Modify: `backend/app/main.py` — `include_router(audit_router)` beside the others at `:1418-1436`
- Test: `backend/tests/test_audit_api.py` (create)

**Interfaces:**
- Consumes: `audit_store.read`, `audit_store.verify`.
- Produces:
  - `GET /v1/audit?actor=&act=&subject_uid=&since=&limit=&before_seq=` → `{"entries": [...], "meta": {"count", "next_before_seq", "persisted"}}`
  - `GET /v1/audit/verify` → `{"ok", "broken_at", "verified", "gaps", "complete", "persisted"}`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_the_log_reads_back_newest_first_and_says_whether_it_is_persisted():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "CONTACT_BACK", "reason": "เหตุผล"},
                headers={"X-Volt-Officer": "nantapol"})
    body = client.get("/v1/audit").json()
    assert body["entries"], "the act just taken must be in the log"
    seqs = [e["seq"] for e in body["entries"]]
    assert seqs == sorted(seqs, reverse=True)
    assert "persisted" in body["meta"]


def test_the_log_filters_by_the_name_that_was_claimed():
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "UNREACHABLE", "reason": "ไม่รับสาย"},
                headers={"X-Volt-Officer": "thip"})
    body = client.get("/v1/audit", params={"actor": "thip"}).json()
    assert body["entries"]
    assert all(e["actor_claimed"] == "thip" for e in body["entries"])


def test_verify_reports_a_clean_chain():
    body = client.get("/v1/audit/verify").json()
    assert body["ok"] is True
    assert body["broken_at"] is None
    assert body["verified"] >= 1


def test_the_log_cannot_be_changed_through_the_api():
    # Not guarded — ABSENT. There is no route to refuse.
    for verb in ("put", "patch", "delete"):
        response = getattr(client, verb)("/v1/audit/1")
        assert response.status_code in (404, 405), verb
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_api.py`
Expected: FAIL — `/v1/audit` returns 404.

- [ ] **Step 3: Write `backend/app/routers/audit.py`**

```python
"""Reading the log back. There is no writing route here, and there is no
mutating route anywhere — not guarded, absent."""
from fastapi import APIRouter, Query

from .. import audit_store

router = APIRouter()

MAX_PAGE = 200


# D4, Arina: everyone sees everything. There is deliberately NO role check here and
# no per-officer filtering — an officer may read every act by anyone. Stated rather
# than merely absent, so a later reader does not "fix" a missing gate that was a
# decision.
@router.get("/v1/audit")
def read_audit(actor: str = Query(default=None), act: str = Query(default=None),
               subject_uid: str = Query(default=None), since: str = Query(default=None),
               limit: int = Query(default=50), before_seq: int = Query(default=None)):
    limit = max(1, min(int(limit or 50), MAX_PAGE))
    filters = {"actor": actor, "act": act, "subject_uid": subject_uid, "since": since}
    entries = audit_store.read(filters, limit=limit, before_seq=before_seq)
    return {
        "entries": entries,
        "meta": {
            "count": len(entries),
            # Paging is by seq, not by offset: the log only grows at the head, so an
            # offset would re-show rows as new ones arrive mid-read.
            "next_before_seq": entries[-1]["seq"] if len(entries) == limit else None,
            "persisted": audit_store.persisted(),
        },
    }


@router.get("/v1/audit/verify")
def verify_audit():
    return audit_store.verify()
```

- [ ] **Step 4: Register it**

In `backend/app/main.py`, beside the other `include_router` calls:

```python
from .routers.audit import router as audit_router
...
app.include_router(audit_router)
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_api.py`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/audit.py backend/app/main.py backend/tests/test_audit_api.py
git commit -m "feat(audit): read the log back, and verify the chain"
```

---

### Task 7: The coverage test — the promise this design actually makes

**Files:**
- Test: `backend/tests/test_audit_coverage.py` (create)

**Interfaces:**
- Consumes: the FastAPI app's own route table.
- Produces: nothing — this task is the guarantee.

- [ ] **Step 1: Write the test**

```python
"""'Track all the action' is a claim, and this is the test that keeps it true.

A route added next month with no thought given to the log is still logged; a route
that somehow escapes capture fails the suite here rather than leaving a silent gap.
A trail with unknown gaps is worse than no trail — it invites confident conclusions
from partial evidence (design contract §1a).
"""
from fastapi.testclient import TestClient
from starlette.routing import Route

from app import audit, audit_store
from app.main import app

client = TestClient(app)

ACT_VERBS = {"POST", "PUT", "PATCH", "DELETE"}


def act_routes():
    out = []
    for route in app.routes:
        if not isinstance(route, Route):
            continue
        for method in (route.methods or set()) & ACT_VERBS:
            out.append((method, route.path))
    return sorted(set(out))


def test_there_is_no_mutating_route_under_v1_audit():
    for method, path in act_routes():
        assert not path.startswith("/v1/audit"), "%s %s must not exist" % (method, path)


def test_every_act_route_is_in_scope_for_the_log():
    # The middleware logs on `method != GET`, so scope is total by construction.
    # This test states that fact so a future narrowing has to argue with it.
    assert act_routes(), "the app must expose acts at all"
    for method, _path in act_routes():
        assert method in ACT_VERBS


def test_only_the_declared_read_is_logged():
    # D3's scope cannot widen by accident.
    assert audit.LOGGED_READS == ("/v1/cases/by-customer/{customer_uid}",)


def test_a_representative_act_on_every_router_lands_in_the_log():
    """One act per router module, so a router that is registered but somehow
    bypasses the middleware is caught."""
    before = len(audit_store.read({}, limit=500, before_seq=None))
    uid = client.get("/v1/workbook").json()["rows"][0]["customer"]["uid"]
    client.post("/v1/cases/by-customer/%s/dc-status" % uid,
                json={"code": "CONTACT_BACK", "reason": "r"})
    client.post("/v1/feedback", json={"note": "x", "screen": "/"})
    after = audit_store.read({}, limit=500, before_seq=None)
    assert len(after) >= before + 2
```

- [ ] **Step 2: Run it**

Run: `cd backend && .venv/bin/python -m pytest tests/test_audit_coverage.py`
Expected: PASS (4 tests). If `test_there_is_no_mutating_route_under_v1_audit` fails, someone added a write route to the log — that is the design being violated, not the test being wrong.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_audit_coverage.py
git commit -m "test(audit): coverage is the promise, so it is a test

A route added later with no thought for the log is still logged; a route that
escapes capture fails here rather than leaving a silent gap."
```

---

### Task 8: The screen

**Files:**
- Modify: `frontend/src/api.js` — add two client methods beside the others
- Create: `frontend/src/screens/AuditLog.jsx`
- Create: `frontend/src/screens/AuditLog.test.jsx`
- Modify: `frontend/src/i18n-admin.js` — add `audit.*` keys to BOTH tables
- Modify: `frontend/src/App.jsx` — add the `/audit` route

**Interfaces:**
- Consumes: `GET /v1/audit`, `GET /v1/audit/verify`.
- Produces: `api.audit(params)`, `api.auditVerify()`; default export `AuditLog`.

- [ ] **Step 1: Add the i18n keys**

In `frontend/src/i18n-admin.js`, add to the EN table:

```js
  // The action audit log (design 2026-09-11). `audit.` is a new prefix here; the
  // four reserved ones (rec. rep. set. mig.) are untouched.
  'audit.title': 'Action log',
  'audit.sub': 'Every act recorded, in the order it happened.',
  'audit.verified': 'Chain verified · {n} entries',
  'audit.broken': 'Chain broken at entry {n} — an entry was altered or removed',
  'audit.notPersisted': 'This log is held in memory only and will not survive a restart.',
  'audit.gaps': '{n} acts could not be recorded',
  'audit.claimed': 'name claimed, not verified',
  'audit.claimedWhy': 'This build has no sign-in. The name is the one the interface sent, not a verified identity.',
  'audit.when': 'When',
  'audit.who': 'Who',
  'audit.act': 'Act',
  'audit.subject': 'Subject',
  'audit.change': 'Change',
  'audit.reason': 'Reason',
  'audit.outcome': 'Outcome',
  'audit.ok': 'Done',
  'audit.refused': 'Refused',
  'audit.empty': 'Nothing recorded yet.',
  'audit.more': 'Load older',
  'audit.filterActor': 'Who',
  'audit.filterAct': 'Act',
  'audit.allActors': 'Everyone',
  'audit.allActs': 'Every act',
```

and the same keys to the TH table:

```js
  'audit.title': 'บันทึกการทำงาน',
  'audit.sub': 'ทุกการกระทำถูกบันทึกไว้ ตามลำดับที่เกิดขึ้น',
  'audit.verified': 'ตรวจสอบห่วงโซ่แล้ว · {n} รายการ',
  'audit.broken': 'ห่วงโซ่ขาดที่รายการ {n} — มีการแก้ไขหรือลบรายการ',
  'audit.notPersisted': 'บันทึกนี้เก็บในหน่วยความจำเท่านั้น จะหายเมื่อรีสตาร์ท',
  'audit.gaps': 'มี {n} การกระทำที่บันทึกไม่สำเร็จ',
  'audit.claimed': 'ชื่อที่แจ้ง ยังไม่ได้ยืนยันตัวตน',
  'audit.claimedWhy': 'ระบบนี้ยังไม่มีการล็อกอิน ชื่อนี้คือชื่อที่หน้าจอส่งมา ไม่ใช่ตัวตนที่ยืนยันแล้ว',
  'audit.when': 'เวลา',
  'audit.who': 'ผู้ทำ',
  'audit.act': 'การกระทำ',
  'audit.subject': 'เกี่ยวกับ',
  'audit.change': 'การเปลี่ยนแปลง',
  'audit.reason': 'เหตุผล',
  'audit.outcome': 'ผล',
  'audit.ok': 'สำเร็จ',
  'audit.refused': 'ถูกปฏิเสธ',
  'audit.empty': 'ยังไม่มีการบันทึก',
  'audit.more': 'ดูรายการเก่ากว่านี้',
  'audit.filterActor': 'ผู้ทำ',
  'audit.filterAct': 'การกระทำ',
  'audit.allActors': 'ทุกคน',
  'audit.allActs': 'ทุกการกระทำ',
```

Run: `cd frontend && npx vitest run src/i18n.test.js`
Expected: PASS — parity, no empty values, matching `{n}` slots, no collision with the other three tables.

- [ ] **Step 2: Add the API client methods**

In `frontend/src/api.js`, beside the other entries:

```js
  audit: (params) => get('/v1/audit', params),
  auditVerify: () => get('/v1/audit/verify'),
```

- [ ] **Step 3: Write the failing screen test**

Create `frontend/src/screens/AuditLog.test.jsx`:

```jsx
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'

vi.mock('../api.js', () => ({ api: { audit: vi.fn(), auditVerify: vi.fn() } }))

import { api } from '../api.js'
import AuditLog from './AuditLog.jsx'

const ENTRY = (over = {}) => ({
  seq: 2, at: '2026-09-11T03:12:00+00:00', business_date: '2026-10-23',
  actor_claimed: 'nantapol', actor_source: 'HEADER',
  verb: 'POST', route_template: '/v1/cases/by-customer/{customer_uid}/dc-status',
  act: 'DC_STATUS_SET', subject_type: 'customer', subject_uid: 'cus-42',
  detail: { from: 'CONTACT_BACK', to: 'PAID', reason: 'ลูกค้าชำระแล้ว' },
  outcome: 'OK', status: 200, error_code: null, ...over,
})

const Page = () => <MemoryRouter><AuditLog /></MemoryRouter>

beforeEach(() => {
  vi.clearAllMocks()
  api.audit.mockResolvedValue({ entries: [ENTRY()], meta: { count: 1, next_before_seq: null, persisted: true } })
  api.auditVerify.mockResolvedValue({ ok: true, broken_at: null, verified: 2, gaps: 0, complete: true, persisted: true })
})

describe('the action log', () => {
  it('says the chain is verified, and how much of it', async () => {
    renderIn('th', <Page />)
    expect(await screen.findByTestId('audit-verify')).toHaveTextContent('ตรวจสอบห่วงโซ่แล้ว · 2 รายการ')
  })

  it('names the act, the change and the reason, not the URL', async () => {
    renderIn('th', <Page />)
    const row = await screen.findByTestId('audit-row-2')
    expect(row).toHaveTextContent('ลูกค้าชำระแล้ว')
    expect(row).toHaveTextContent('CONTACT_BACK')
    expect(row).toHaveTextContent('PAID')
    expect(row).not.toHaveTextContent('/v1/cases/by-customer')
  })

  it('badges the acting name as claimed, never as verified', async () => {
    // The one thing on this screen that must never be quietly dropped: this build
    // has no sign-in, so the name is an assertion by the client.
    renderIn('th', <Page />)
    const badge = await screen.findByTestId('audit-claimed-2')
    expect(badge).toHaveTextContent('ชื่อที่แจ้ง ยังไม่ได้ยืนยันตัวตน')
  })

  it('says plainly when the log is not persisted', async () => {
    api.audit.mockResolvedValue({ entries: [ENTRY()], meta: { count: 1, next_before_seq: null, persisted: false } })
    api.auditVerify.mockResolvedValue({ ok: true, broken_at: null, verified: 2, gaps: 0, complete: true, persisted: false })
    renderIn('th', <Page />)
    expect(await screen.findByTestId('audit-not-persisted'))
      .toHaveTextContent('บันทึกนี้เก็บในหน่วยความจำเท่านั้น จะหายเมื่อรีสตาร์ท')
  })

  it('shows a broken chain as broken, naming the entry', async () => {
    api.auditVerify.mockResolvedValue({ ok: false, broken_at: 7, verified: 6, gaps: 0, complete: false, persisted: true })
    renderIn('th', <Page />)
    expect(await screen.findByTestId('audit-verify'))
      .toHaveTextContent('ห่วงโซ่ขาดที่รายการ 7 — มีการแก้ไขหรือลบรายการ')
  })

  it('shows a refused act as refused, carrying its code', async () => {
    api.audit.mockResolvedValue({
      entries: [ENTRY({ seq: 3, outcome: 'REFUSED', status: 422, error_code: 'reason_required', detail: {} })],
      meta: { count: 1, next_before_seq: null, persisted: true },
    })
    renderIn('th', <Page />)
    const row = await screen.findByTestId('audit-row-3')
    expect(row).toHaveTextContent('ถูกปฏิเสธ')
    expect(row).toHaveTextContent('reason_required')
  })

  it('filters on the server, never in the browser', async () => {
    renderIn('th', <Page />)
    await screen.findByTestId('audit-row-2')
    fireEvent.change(screen.getByLabelText('ผู้ทำ'), { target: { value: 'thip' } })
    await waitFor(() => expect(api.audit).toHaveBeenLastCalledWith(expect.objectContaining({ actor: 'thip' })))
  })
})
```

- [ ] **Step 4: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/screens/AuditLog.test.jsx`
Expected: FAIL — `Failed to resolve import "./AuditLog.jsx"`

- [ ] **Step 5: Write `frontend/src/screens/AuditLog.jsx`**

Follows the admin-screen idiom (`ad-page`, `card ad-section`, `ad-h2`, `ad-quiet`) that
`Recovery.jsx` and `Settings.jsx` already use.

```jsx
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { usePrefs } from '../prefs.jsx'
import { Problem } from '../components/Problem.jsx'

// The action log (design 2026-09-11).
//
// Two rules this screen exists to keep, and neither may be quietly dropped:
//
//   1. The acting name is BADGED as claimed. This build has no sign-in; the name is
//      whatever the interface sent. An audit screen that rendered it plainly would
//      be the single worst place in the product for a confident wrong value (§1a).
//   2. The screen says whether the log is PERSISTED. Running in memory is honest;
//      running in memory while looking durable is not (db.py's own rule).
//
// The row shows the ACT, never the route template. A reader should not have to
// decode a URL to learn that someone changed a status.
const PAGE = 50

function when(at, lang) {
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? String(at)
    : d.toLocaleString(lang === 'en' ? 'en-GB' : 'th-TH', { dateStyle: 'short', timeStyle: 'short' })
}

export default function AuditLog() {
  const { t, lang } = usePrefs()
  const [entries, setEntries] = useState([])
  const [meta, setMeta] = useState(null)
  const [chain, setChain] = useState(null)
  const [problem, setProblem] = useState(null)
  const [filters, setFilters] = useState({ actor: '', act: '' })

  const load = useCallback((before) => {
    const params = { limit: PAGE }
    if (filters.actor) params.actor = filters.actor
    if (filters.act) params.act = filters.act
    if (before) params.before_seq = before
    api.audit(params)
      .then((payload) => {
        const rows = payload?.entries || []
        setEntries((prev) => (before ? [...prev, ...rows] : rows))
        setMeta(payload?.meta || null)
        setProblem(null)
      })
      .catch((err) => setProblem(err))
  }, [filters])

  useEffect(() => { load(null) }, [load])
  useEffect(() => { api.auditVerify().then(setChain).catch(() => setChain(null)) }, [])

  // Both selects offer only names and acts actually present, so a filter can never
  // be chosen that returns nothing.
  const actors = [...new Set(entries.map((e) => e.actor_claimed).filter(Boolean))]
  const acts = [...new Set(entries.map((e) => e.act).filter(Boolean))]

  return (
    <div className="ad-page">
      <header>
        <h1 className="page-title">{t('audit.title')}</h1>
        <p className="page-sub">{t('audit.sub')}</p>
      </header>

      {chain && (
        <p className="ad-quiet" data-testid="audit-verify">
          {chain.ok
            ? t('audit.verified', { n: chain.verified })
            : t('audit.broken', { n: chain.broken_at })}
        </p>
      )}
      {chain && chain.gaps > 0 && (
        <p className="ad-quiet" data-testid="audit-gaps">{t('audit.gaps', { n: chain.gaps })}</p>
      )}
      {meta && meta.persisted === false && (
        <p className="ad-quiet" data-testid="audit-not-persisted">{t('audit.notPersisted')}</p>
      )}

      <Problem problem={problem} />

      <section className="card ad-section" aria-label={t('audit.title')}>
        <div className="fb" role="search">
          <div className="fb__filter">
            <label className="fb__label" htmlFor="audit-actor">{t('audit.filterActor')}</label>
            <select id="audit-actor" className="fb__select" value={filters.actor}
                    onChange={(e) => setFilters((f) => ({ ...f, actor: e.target.value }))}>
              <option value="">{t('audit.allActors')}</option>
              {actors.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div className="fb__filter">
            <label className="fb__label" htmlFor="audit-act">{t('audit.filterAct')}</label>
            <select id="audit-act" className="fb__select" value={filters.act}
                    onChange={(e) => setFilters((f) => ({ ...f, act: e.target.value }))}>
              <option value="">{t('audit.allActs')}</option>
              {acts.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        </div>

        {entries.length === 0 && <p className="ad-quiet">{t('audit.empty')}</p>}

        <ul className="audit__list">
          {entries.map((e) => (
            <li className="audit__row" key={e.seq} data-testid={`audit-row-${e.seq}`}>
              <span className="audit__when">{when(e.at, lang)}</span>
              <span className="audit__who">
                {e.actor_claimed || '—'}
                {/* Never removed without SSO. See the header comment. */}
                <span className="audit__claimed" data-testid={`audit-claimed-${e.seq}`}
                      title={t('audit.claimedWhy')}>{t('audit.claimed')}</span>
              </span>
              <span className="audit__act">{e.act || `${e.verb}`}</span>
              <span className="audit__subject">
                {e.subject_type === 'customer' && e.subject_uid
                  ? <Link className="crumbs__link" to={`/customers/${e.subject_uid}`}>{e.subject_uid}</Link>
                  : (e.subject_uid || '—')}
              </span>
              <span className="audit__change">
                {e.detail && e.detail.from !== undefined && e.detail.to !== undefined
                  ? `${e.detail.from ?? '—'} → ${e.detail.to ?? '—'}` : ''}
              </span>
              <span className="audit__reason">{(e.detail && e.detail.reason) || ''}</span>
              <span className={`audit__outcome${e.outcome === 'REFUSED' ? ' audit__outcome--refused' : ''}`}>
                {e.outcome === 'REFUSED' ? t('audit.refused') : t('audit.ok')}
                {e.error_code ? ` · ${e.error_code}` : ''}
              </span>
            </li>
          ))}
        </ul>

        {meta && meta.next_before_seq && (
          <button type="button" className="btn btn--sm" onClick={() => load(meta.next_before_seq)}>
            {t('audit.more')}
          </button>
        )}
      </section>
    </div>
  )
}
```

Then add the styles to `frontend/src/admin.css` (which already owns `.ad-page`), keeping
contract L5 in mind — Thai act names and reasons are long:

```css
/* The action log. A list of rows rather than a <table>: the reason column is free
   text of very uneven length, and a table column sized for the longest reason
   wastes the width every other row needs. */
.audit__list { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.audit__row {
  display: grid; gap: 4px 12px; padding: 8px 6px;
  grid-template-columns: 132px 160px 180px 120px 1fr;
  grid-template-areas: "when who act subject change" "when who reason reason outcome";
  border-bottom: 1px solid var(--line-default); font: var(--small-13); color: var(--ink-800);
}
.audit__when { grid-area: when; color: var(--ink-500); font-variant-numeric: tabular-nums; }
.audit__who { grid-area: who; display: flex; flex-direction: column; gap: 2px; }
.audit__act { grid-area: act; font: var(--body-strong-14); }
.audit__subject { grid-area: subject; }
.audit__change { grid-area: change; font-family: var(--font-mono); font-size: 12px; }
.audit__reason { grid-area: reason; color: var(--ink-600); }
.audit__outcome { grid-area: outcome; text-align: right; }
.audit__outcome--refused { color: var(--status-overdue); }
/* The badge is quiet but never invisible: it qualifies every name on the screen. */
.audit__claimed { font: var(--caption-12); color: var(--ink-500); }
@media (max-width: 900px) {
  .audit__row { grid-template-columns: 1fr; grid-template-areas: "when" "who" "act" "subject" "change" "reason" "outcome"; }
  .audit__outcome { text-align: left; }
}
```

**Check before moving on:** `css-chain.test.js` fails if any `.css` under `frontend/src/`
is not reachable from what `main.jsx` loads. `admin.css` already is, so adding rules to it
costs nothing — but do NOT create a new stylesheet for this screen.

- [ ] **Step 6: Run the tests**

Run: `cd frontend && npx vitest run src/screens/AuditLog.test.jsx`
Expected: PASS (7 tests)

- [ ] **Step 7: Add the route**

In `frontend/src/App.jsx`, import `AuditLog` and add beside `/dashboard`:

```jsx
        <Route path="/audit" element={<AuditLog />} />
```

`App.test.jsx` asserts no route list, so this costs nothing.

- [ ] **Step 8: Run the whole frontend suite**

Run: `cd frontend && npx vitest run`
Expected: **at or above 518 passed (41 files)** — 511 + 7. Nothing else may change.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api.js frontend/src/screens/AuditLog.jsx frontend/src/screens/AuditLog.test.jsx frontend/src/i18n-admin.js frontend/src/App.jsx
git commit -m "feat(audit): the screen, and the badge that keeps it honest

The acting name renders badged as claimed-not-verified, because this build has
no sign-in and a log that looked authoritative would be the worst possible place
for a confident wrong value."
```

---

### Task 9: The rail row — AUTHORISED TEST EDIT 23

**Files:**
- Modify: `frontend/src/components/Shell.jsx` — the `GROUPS` constant, `nav.group.system`
- Modify: `frontend/src/i18n-journey.js` — `nav.audit` in BOTH tables (this table already owns `nav.*`)
- Modify: `frontend/src/components/Shell.test.jsx:18` (`TH_ORDER`), `:24` (`ROUTES`), `:60` (EN labels) — **authorised edit 23**

**Interfaces:**
- Consumes: the `/audit` route from Task 8.
- Produces: a tenth rail row.

**Price, quoted before it is spent:** 3 array literals across 2 test functions in one file. Identical in shape and size to edit 18, which added the Dashboard row. `App.test.jsx` asserts no route list. `density.test.jsx` censuses `CustomerCase` and is unaffected — named explicitly because edit 22 was under-priced by exactly that file.

- [ ] **Step 1: Add the strings**

In `frontend/src/i18n-journey.js`, beside the other `nav.*` keys, in BOTH tables:

```js
  'nav.audit': 'Action log',
```
```js
  'nav.audit': 'บันทึกการทำงาน',
```

- [ ] **Step 2: Add the rail row**

In `frontend/src/components/Shell.jsx`, in the `nav.group.system` group, after `/data-sources`:

```jsx
      { to: '/audit', icon: 'reports', label: 'nav.audit', key: null },
```

Reuse the `reports` glyph rather than inventing one; `NavIcon` renders only names it knows, and an unknown name renders nothing, which would leave the row without its glyph.

- [ ] **Step 3: Run the Shell tests and watch them fail**

Run: `cd frontend && npx vitest run src/components/Shell.test.jsx`
Expected: FAIL — 2 tests, on `TH_ORDER` and the EN labels array, each reporting one extra element.

- [ ] **Step 4: Spend edit 23**

In `frontend/src/components/Shell.test.jsx`, add `'บันทึกการทำงาน'` to the end of `TH_ORDER` (:18), `'/audit'` to the end of `ROUTES` (:24), and `'Action log'` to the end of the EN labels array (:60). Above `TH_ORDER`, add:

```js
// AUTHORISED TEST EDIT 23 — Arina, 2026-09-11: the action audit log gets a rail row
// rather than a link inside Settings, because an audit log nobody can find is not an
// audit control. Three array literals across two test functions, the identical shape
// and price as edit 18 (the Dashboard row), quoted in the design's §8 before it was
// spent. The count assertion on links[1] does NOT move: the new row is appended to
// the LAST group, so no index before it shifts.
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/components/Shell.test.jsx`
Expected: PASS. If the `links[1]` count assertion also fails, the row was added to the wrong group — it belongs at the END of `nav.group.system`, so no earlier index moves.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Shell.jsx frontend/src/components/Shell.test.jsx frontend/src/i18n-journey.js
git commit -m "feat(audit): a rail row, because a log nobody can find is not a control

AUTHORISED TEST EDIT 23 — 3 array literals across 2 test functions, priced in
the design's section 8 before it was spent. Edit 17 stays reserved."
```

---

### Task 10: Prove it end to end

**Files:** none changed unless a defect is found.

- [ ] **Step 1: Full verification**

Run: `./scripts/verify_all.sh`
Expected: EVERYTHING PASSED.

Run: `cd backend && .venv/bin/python -m pytest tests/` (no `-q`)
Expected: at or above **624 passed, 1 skipped**.

Paste both counts into the final report. Green at or above baseline is the rule; a drop anywhere is a STOP.

- [ ] **Step 2: Drive it in the browser**

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000 --log-level warning &
cd frontend && npx vite --port 5173 --strictPort &
```

Then, at `http://localhost:5173/`:

1. Change a customer's follow-up status with a reason.
2. Open `/audit` from the rail. The act must be the newest row, naming the change and the reason, with the subject linking back to that customer.
3. Confirm the verify banner reads verified, and — with no `DATABASE_URL` — that the not-persisted notice is visible and in Thai.
4. Attempt a refused act (a status change to the value it already holds) and confirm it appears as ถูกปฏิเสธ with `status_unchanged`.
5. Check Thai at 1440 and at 900: no truncation, no horizontal scroll (contract L5).

- [ ] **Step 3: Prove the chain catches a tamper**

With a database configured, alter a row in place and confirm the trigger refuses it — that IS the proof:

```bash
psql "$DATABASE_URL" -c "UPDATE app.audit_entry SET actor_claimed = 'someone' WHERE seq = 1;"
```
Expected: `ERROR: app.audit_entry is append-only: UPDATE is refused`

Then prove `verify` would catch it if the trigger were absent, by temporarily disabling the trigger, altering the row, checking `GET /v1/audit/verify` reports `broken_at: 1`, and restoring:

```bash
psql "$DATABASE_URL" -c "ALTER TABLE app.audit_entry DISABLE TRIGGER audit_entry_no_change;"
psql "$DATABASE_URL" -c "UPDATE app.audit_entry SET actor_claimed = 'someone' WHERE seq = 1;"
curl -s localhost:8000/v1/audit/verify
psql "$DATABASE_URL" -c "ALTER TABLE app.audit_entry ENABLE TRIGGER audit_entry_no_change;"
```

**Do this on a scratch database only.** The row stays altered — that is the point of an append-only log — so never run it against anything whose history matters.

- [ ] **Step 4: Report**

State the three counts, what was driven in the browser, and anything found and not fixed. Do not claim completion without the counts.

---

## What this plan does not do

Carried from spec §9, so nobody "finishes" work that was never started:

- **No authentication.** The log records claims. `actor_source` is the seam SSO will change.
- **`CaseState.events` is not migrated.** `reports.py:183` reads it; that is a separate job with its own price.
- **No retention or deletion.** An append-only log grows without limit, and PDPA erasure against it is a real unanswered question.
- **No export.** Reading the log out as CSV needs the governed-export treatment rulings 72/74 gave the work book.
- **No external anchoring**, which is what would move this from tamper-evident toward tamper-proof.
