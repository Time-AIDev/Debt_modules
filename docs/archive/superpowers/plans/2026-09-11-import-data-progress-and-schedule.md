# Import Data — progress, schedule, and the page's own name

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Manager choose their door — their own file, or Odoo right now — watch a real Odoo fetch progress row by row with an elapsed clock, and optionally have it refetch every 15 minutes.

**Architecture:** The Odoo door moves to a background thread with a process-wide run registry; the screen polls it. `ingress` and `writer` gain an optional `on_progress` callback, so progress is reported by the code doing the work rather than estimated by the code watching it. The 15-minute refetch is a daemon thread that calls the same entry point the button does — one code path, two triggers.

**Tech Stack:** Python 3, FastAPI + `starlette.concurrency.run_in_threadpool`, `threading` for the scheduler, React 18 + Vite. No new dependencies.

**Spec:** `docs/archive/superpowers/specs/2026-09-11-odoo-crm-lead-pipeline-design.md` (this extends it; the rules file and the landing contract are unchanged)

## Global Constraints

- **The rail label does not change.** `nav.dataSources` is the rank-2 SOP's own word and ruling 70 left it alone deliberately. Only `mig.title` and the page heading become "Import Data" / "นำเข้าข้อมูล". No edit to `Shell.test.jsx`, no authorised test edit spent.
- **Progress is reported, never estimated.** The bar shows counts the pipeline actually emitted. A percentage is only shown once `total` is known; before that the bar is indeterminate and says so.
- **The scheduler is off by default and opt-in per process.** It is in-memory: it dies with the API, and on Cloud Run — where the service scales to zero and to N instances — it would run zero or N times. The screen must say so, and the deployed answer stays the existing Cloud Scheduler job.
- **One code path, two triggers.** The button and the scheduler both call `pipelines.service.run_odoo(...)`. A second copy of the run sequence for the timer would be ruling 36's second-pattern MAJOR.
- **Manager-only** for starting a run and for changing the schedule, matching `routers/pipelines.py:_manager_only`.
- **Bilingual**: every new string in both `ADMIN_EN` and `ADMIN_TH`, under the `mig.` prefix (`pipe.` belongs to the invoice-pipeline screen — the i18n parity test enforces this).
- **Test contract:** the suites must stay green — frontend 515+, e2e 30+. The two failing `test_audit_*` tests are pre-existing and owned by parallel work; do not touch `app/audit.py`.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/pipelines/runs.py` | Process-wide registry of pipeline runs and their progress. No HTTP, no DB |
| `backend/app/pipelines/service.py` | `run_odoo(rules, registry_uid)` — the one sequence both triggers call |
| `backend/app/pipelines/schedule.py` | The 15-minute daemon thread and its state |
| `backend/app/routers/pipelines.py` | + `:start`, `runs/{uid}`, `GET`/`PUT schedule` |
| `backend/app/pipelines/ingress.py` | + `on_progress` on `from_odoo` |
| `backend/app/pipelines/writer.py` | + `on_progress` on `write` |
| `frontend/src/components/RunProgress.jsx` | The bar, the counts and the elapsed clock |
| `frontend/src/screens/DataSourcesMigration.jsx` | The door choice, the progress, the schedule toggle |

---

### Task 1: A run registry that knows how far it got

**Files:**
- Create: `backend/app/pipelines/runs.py`
- Test: `backend/tests/test_pipeline_runs.py`

**Interfaces:**
- Produces: `runs.start(kind) -> str` (a uid); `runs.progress(uid, **fields)`; `runs.finish(uid, result)`; `runs.fail(uid, problem)`; `runs.get(uid) -> dict|None`; `runs.latest() -> dict|None`; `runs.reset()` (test seam).
- A run dict is `{"uid", "kind", "state", "read", "total", "landed", "rejected", "overwrote", "started_at", "finished_at", "elapsed_seconds", "problem"}` with `state` in `("running", "done", "failed")`.

- [ ] **Step 1: Write the failing test**

```python
"""A run you can watch from another request."""
import time

from app.pipelines import runs


def setup_function():
    runs.reset()


def test_a_started_run_is_visible_immediately_and_says_it_is_running():
    uid = runs.start("odoo")
    row = runs.get(uid)
    assert row["state"] == "running"
    assert row["read"] == 0 and row["total"] is None
    assert row["started_at"] and row["finished_at"] is None


def test_progress_accumulates_and_elapsed_keeps_counting_while_it_runs():
    uid = runs.start("odoo")
    runs.progress(uid, read=500, total=34336)
    time.sleep(0.01)
    row = runs.get(uid)
    assert (row["read"], row["total"]) == (500, 34336)
    assert row["elapsed_seconds"] > 0


def test_a_finished_run_freezes_its_elapsed_time():
    uid = runs.start("odoo")
    runs.finish(uid, {"landed": 3, "rejected": 1, "overwrote": 0})
    first = runs.get(uid)["elapsed_seconds"]
    time.sleep(0.02)
    assert runs.get(uid)["elapsed_seconds"] == first
    assert runs.get(uid)["state"] == "done"
    assert runs.get(uid)["landed"] == 3


def test_a_failed_run_carries_its_problem_and_is_not_pretended_to_be_done():
    uid = runs.start("odoo")
    runs.fail(uid, {"code": "integration_unavailable", "detail": "Odoo refused"})
    row = runs.get(uid)
    assert row["state"] == "failed"
    assert row["problem"]["code"] == "integration_unavailable"


def test_latest_is_the_most_recently_started_run():
    runs.start("odoo")
    second = runs.start("upload")
    assert runs.latest()["uid"] == second


def test_an_unknown_uid_is_none_rather_than_an_invented_run():
    assert runs.get("no-such-run") is None


def test_the_registry_is_bounded_so_a_long_session_cannot_grow_forever():
    for _ in range(runs.KEEP + 10):
        runs.start("odoo")
    assert len(runs.all()) == runs.KEEP
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_runs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipelines.runs'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Where a pipeline run's progress lives while it is happening.

Process-wide and NOT per-session (app/session.py), deliberately: the work happens
on a background thread, which has no request and therefore no session contextvar,
and the point of the feature is that an officer can navigate away and come back to
a run that is still going.

In memory, so it dies with the process. That is honest for a prototype and is
stated on the screen; the durable record of what a run did is the import_run row
the writer already creates.
"""
import threading
import time
import uuid
from collections import OrderedDict

KEEP = 20                    # a laptop session's worth; the oldest fall off

_LOCK = threading.Lock()
_RUNS = OrderedDict()


def reset():
    """Test seam. Never called from a request."""
    with _LOCK:
        _RUNS.clear()


def start(kind):
    uid = "run-" + uuid.uuid4().hex[:12]
    with _LOCK:
        _RUNS[uid] = {"uid": uid, "kind": kind, "state": "running",
                      "read": 0, "total": None, "landed": 0, "rejected": 0,
                      "overwrote": 0, "started_at": time.time(),
                      "finished_at": None, "problem": None}
        while len(_RUNS) > KEEP:
            _RUNS.popitem(last=False)
    return uid


def progress(uid, **fields):
    with _LOCK:
        run = _RUNS.get(uid)
        if run and run["state"] == "running":
            run.update(fields)


def finish(uid, result):
    with _LOCK:
        run = _RUNS.get(uid)
        if run:
            run.update(result)
            run["state"] = "done"
            run["finished_at"] = time.time()


def fail(uid, problem):
    with _LOCK:
        run = _RUNS.get(uid)
        if run:
            run["state"] = "failed"
            run["problem"] = problem
            run["finished_at"] = time.time()


def _view(run):
    """Elapsed counts up while running and freezes when it ends — a clock that kept
    running after the run finished would make every old run look eternal."""
    end = run["finished_at"] or time.time()
    return dict(run, elapsed_seconds=round(end - run["started_at"], 1))


def get(uid):
    with _LOCK:
        run = _RUNS.get(uid)
        return _view(run) if run else None


def all():
    with _LOCK:
        return [_view(r) for r in _RUNS.values()]


def latest():
    rows = all()
    return rows[-1] if rows else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_runs.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/runs.py backend/tests/test_pipeline_runs.py
git commit -m "feat(pipelines): a run you can watch from another request"
```

---

### Task 2: The work reports its own progress

**Files:**
- Modify: `backend/app/pipelines/ingress.py` — `from_odoo`
- Modify: `backend/app/pipelines/writer.py` — `write`
- Test: `backend/tests/test_pipeline_ingress.py` (append), `backend/tests/test_pipeline_writer.py` (append)

**Interfaces:**
- Produces: `ingress.from_odoo(rules, execute=None, on_progress=None)` calling `on_progress(read=<int>, total=<int>)` after each page; `writer.write(conn, records, verdicts, batch=1000, on_progress=None)` calling `on_progress(landed=<int>)` after each batch.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pipeline_ingress.py`:

```python
def test_the_pull_reports_its_progress_page_by_page(monkeypatch):
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    seen = []
    ingress.from_odoo(FakeExecute(total=1200), execute=FakeExecute(total=1200),
                      on_progress=lambda **kw: seen.append(kw)) if False else None
    fake = FakeExecute(total=1200)
    ingress.from_odoo(RULES, execute=fake, on_progress=lambda **kw: seen.append(kw))
    assert seen == [{"read": 500, "total": 1200},
                    {"read": 1000, "total": 1200},
                    {"read": 1200, "total": 1200}]
```

Append to `backend/tests/test_pipeline_writer.py`:

```python
def test_the_writer_reports_a_batch_at_a_time(schema):
    seen = []
    records = [_record("VL%07d" % i) for i in range(2500)]
    writer.write(schema, records, [], batch=1000,
                 on_progress=lambda **kw: seen.append(kw))
    assert seen == [{"landed": 1000}, {"landed": 2000}, {"landed": 2500}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_pipeline_ingress.py tests/test_pipeline_writer.py -v`
Expected: FAIL — `TypeError: from_odoo() got an unexpected keyword argument 'on_progress'`

- [ ] **Step 3: Write minimal implementation**

In `ingress.py`, replace the body of `from_odoo`:

```python
def from_odoo(rules, execute=None, on_progress=None):
    """`on_progress(read=, total=)` after each page — reported by the code doing the
    work, so the bar can never claim progress the pull did not make."""
    execute = execute or odoo._execute
    config = odoo._config()
    uid = odoo._login(config)
    fields = _fields(rules)
    total = execute(config, uid, "crm.lead", "search_count", [[]])
    rows, offset = [], 0
    while offset < total:
        page = execute(config, uid, "crm.lead", "search_read", [[]],
                       {"fields": fields, "limit": PAGE, "offset": offset,
                        "order": "id"})
        if not page:
            break
        rows.extend(page)
        offset += len(page)
        if on_progress:
            on_progress(read=len(rows), total=total)
    return rows
```

In `writer.py`, change the landing loop:

```python
    landed = 0
    for start in range(0, len(records), batch):
        for record in records[start:start + batch]:
            landing.write_customer(conn, run, "ODOO", record)
            order = dict(record.get("order") or {})
            order.setdefault("reason", record["reason"])
            landing.write_order(conn, run, "ODOO", record["volt_id"], order)
            landed += 1
        if on_progress:
            on_progress(landed=landed)
```

and its signature:

```python
def write(conn, records, verdicts, batch=1000, on_progress=None):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_pipeline_ingress.py tests/test_pipeline_writer.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/ingress.py backend/app/pipelines/writer.py backend/tests/test_pipeline_ingress.py backend/tests/test_pipeline_writer.py
git commit -m "feat(pipelines): the work reports its own progress, so the bar cannot invent it"
```

---

### Task 3: One sequence, two triggers

**Files:**
- Create: `backend/app/pipelines/service.py`
- Test: `backend/tests/test_pipeline_service.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: `service.run_odoo(uid=None) -> dict` — starts or adopts a registry run, pulls, normalises, writes, finishes; returns the run view. `service.run_upload(raw, filename, uid=None) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
"""The button and the timer call the same function."""
import pytest

from app import migrate
from app.pipelines import runs, service


@pytest.fixture
def schema(pg_conn):
    migrate.apply(pg_conn)
    return pg_conn


def setup_function():
    runs.reset()


def test_an_upload_run_records_progress_and_finishes(schema, monkeypatch):
    monkeypatch.setattr(service.db, "connect", lambda: schema)
    monkeypatch.setattr(schema, "begin", lambda: _NullTx())
    raw = ("Volt ID,Phone,Order Status\r\n"
           "VL0000143,0925423597,Order - Done\r\n").encode("utf-8-sig")
    view = service.run_upload(raw, "x.csv")
    assert view["state"] == "done"
    assert view["landed"] == 1
    assert view["kind"] == "upload"
    assert view["elapsed_seconds"] >= 0


def test_a_refusal_from_odoo_fails_the_run_rather_than_finishing_it(monkeypatch):
    from app.integrations import odoo as odoo_client

    def refuse(rules, execute=None, on_progress=None):
        raise odoo_client.OdooError("Odoo refused the login")
    monkeypatch.setattr(service.ingress, "from_odoo", refuse)
    view = service.run_odoo()
    assert view["state"] == "failed"
    assert "refused" in view["problem"]["detail"]


class _NullTx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_pipeline_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipelines.service'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The run sequence, once. The button calls it, the 15-minute timer calls it, and a
test calls it — a second copy for the timer would be ruling 36's second-pattern
MAJOR on the one sequence that matters.

Every exit goes through the registry: finished runs finish, refused runs fail with
their problem. A run that ends without saying which of the two it was is the
dishonesty the whole pipeline is built against.
"""
from .. import db
from ..integrations import odoo as odoo_client
from . import crm_lead, ingress, rules as rules_mod, runs, writer


class PipelineRefused(Exception):
    def __init__(self, problem):
        super().__init__(problem.get("detail") or problem.get("code"))
        self.problem = problem


def _land(uid, raw_rows, rules):
    records, verdicts = crm_lead.normalise(raw_rows, rules)
    if not db.configured():
        raise PipelineRefused({"code": "database_required",
                               "detail": "The pipeline lands rows in the landing "
                                         "schema; set DATABASE_URL"})
    conn = db.connect()
    try:
        with conn.begin():
            result = writer.write(conn, records, verdicts,
                                  on_progress=lambda **kw: runs.progress(uid, **kw))
    finally:
        conn.close()
    return result


def run_odoo(uid=None):
    uid = uid or runs.start("odoo")
    try:
        rules = rules_mod.load()
        raw_rows = ingress.from_odoo(
            rules, on_progress=lambda **kw: runs.progress(uid, **kw))
        result = _land(uid, raw_rows, rules)
    except PipelineRefused as exc:
        runs.fail(uid, exc.problem)
    except rules_mod.RulesError as exc:
        runs.fail(uid, {"code": "rules_unreadable", "detail": str(exc)})
    except odoo_client.NotConfigured as exc:
        runs.fail(uid, {"code": "integration_not_configured",
                        "detail": "missing " + ", ".join(exc.missing)})
    except odoo_client.OdooError as exc:
        runs.fail(uid, {"code": "integration_unavailable", "detail": str(exc)})
    except Exception as exc:                      # noqa: BLE001 — recorded, never swallowed
        runs.fail(uid, {"code": "pipeline_failed",
                        "detail": "%s: %s" % (exc.__class__.__name__, exc)})
    else:
        runs.finish(uid, result)
    return runs.get(uid)


def run_upload(raw, filename, uid=None):
    uid = uid or runs.start("upload")
    try:
        rules = rules_mod.load()
        raw_rows = ingress.from_upload(raw, filename, rules)
        runs.progress(uid, read=len(raw_rows), total=len(raw_rows))
        result = _land(uid, raw_rows, rules)
    except PipelineRefused as exc:
        runs.fail(uid, exc.problem)
    except Exception as exc:                      # noqa: BLE001
        runs.fail(uid, {"code": "pipeline_failed",
                        "detail": "%s: %s" % (exc.__class__.__name__, exc)})
    else:
        runs.finish(uid, result)
    return runs.get(uid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest tests/test_pipeline_service.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/service.py backend/tests/test_pipeline_service.py
git commit -m "feat(pipelines): one run sequence, for the button and the timer alike"
```

---

### Task 4: The 15-minute timer, off until someone asks

**Files:**
- Create: `backend/app/pipelines/schedule.py`
- Test: `backend/tests/test_pipeline_schedule.py`

**Interfaces:**
- Consumes: Task 3.
- Produces: `schedule.state() -> dict` with `{"enabled", "interval_minutes", "last_run_at", "next_run_at", "last_run_uid", "in_process_only"}`; `schedule.enable(interval_minutes=15)`; `schedule.disable()`; `schedule.tick(now)` (the pure decision: should it run?); `schedule.INTERVAL_DEFAULT = 15`.

- [ ] **Step 1: Write the failing test**

```python
"""A timer that is off until someone turns it on, and says what it cannot promise."""
from app.pipelines import schedule


def setup_function():
    schedule.disable()


def test_it_is_off_by_default_and_says_so():
    state = schedule.state()
    assert state["enabled"] is False
    assert state["next_run_at"] is None


def test_enabling_sets_the_interval_and_a_next_run():
    schedule.enable(15)
    state = schedule.state()
    assert state["enabled"] is True
    assert state["interval_minutes"] == 15
    assert state["next_run_at"] > state["now"]


def test_it_states_that_it_cannot_survive_the_process():
    # The screen must be able to say this without coining the sentence itself.
    assert schedule.state()["in_process_only"] is True


def test_tick_refuses_before_the_interval_has_passed():
    schedule.enable(15)
    schedule._STATE["last_run_at"] = 1000.0
    assert schedule.tick(now=1000.0 + 14 * 60) is False
    assert schedule.tick(now=1000.0 + 15 * 60) is True


def test_tick_is_false_while_disabled_however_long_it_has_been():
    schedule.disable()
    assert schedule.tick(now=10 ** 9) is False


def test_a_first_tick_after_enabling_waits_a_full_interval():
    # Enabling must not fire a 34k-row fetch the same second the box is ticked.
    schedule.enable(15)
    assert schedule.tick(now=schedule.state()["now"] + 60) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipelines.schedule'`

- [ ] **Step 3: Write minimal implementation**

```python
"""The 15-minute refetch: a daemon thread, off until a Manager turns it on.

Three things it deliberately is NOT, all of which the screen states:

  - It is not durable. It lives in this process and dies with it. The durable
    schedule is the Cloud Scheduler job in scripts/deploy_gcp.sh.
  - It is not safe to assume on Cloud Run, where the service scales to zero and to
    N instances: the timer would fire zero times or N times. `in_process_only` is
    how a caller learns that without having to know it.
  - It does not fire on enable. Ticking a box must not start a 34k-row fetch in the
    same second; the first run is one full interval away.

`tick()` is the whole decision and is pure, so the interval logic is tested without
waiting fifteen minutes for it.
"""
import threading
import time

INTERVAL_DEFAULT = 15

_LOCK = threading.Lock()
_STATE = {"enabled": False, "interval_minutes": INTERVAL_DEFAULT,
          "last_run_at": None, "last_run_uid": None}
_THREAD = None


def enable(interval_minutes=INTERVAL_DEFAULT):
    with _LOCK:
        _STATE.update(enabled=True,
                      interval_minutes=max(1, int(interval_minutes)),
                      last_run_at=time.time())      # the clock starts now, not the run
    _ensure_thread()
    return state()


def disable():
    with _LOCK:
        _STATE.update(enabled=False, last_run_at=None)
    return state()


def tick(now=None):
    """Should a run start at `now`? Pure — no threads, no pipeline."""
    now = time.time() if now is None else now
    with _LOCK:
        if not _STATE["enabled"]:
            return False
        last = _STATE["last_run_at"]
        if last is None:
            return True
        return (now - last) >= _STATE["interval_minutes"] * 60


def state():
    with _LOCK:
        now = time.time()
        last = _STATE["last_run_at"]
        nxt = None
        if _STATE["enabled"] and last is not None:
            nxt = last + _STATE["interval_minutes"] * 60
        return {"enabled": _STATE["enabled"],
                "interval_minutes": _STATE["interval_minutes"],
                "last_run_at": last, "next_run_at": nxt,
                "last_run_uid": _STATE["last_run_uid"], "now": now,
                "in_process_only": True}


def _loop():
    from . import service
    while True:
        time.sleep(5)
        if not tick():
            continue
        with _LOCK:
            _STATE["last_run_at"] = time.time()
        view = service.run_odoo()
        with _LOCK:
            _STATE["last_run_uid"] = view["uid"] if view else None


def _ensure_thread():
    global _THREAD
    if _THREAD is None or not _THREAD.is_alive():
        _THREAD = threading.Thread(target=_loop, name="crm-lead-schedule", daemon=True)
        _THREAD.start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_schedule.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipelines/schedule.py backend/tests/test_pipeline_schedule.py
git commit -m "feat(pipelines): a 15-minute refetch that is off until asked and honest about dying with the process"
```

---

### Task 5: Start it, watch it, schedule it

**Files:**
- Modify: `backend/app/routers/pipelines.py`
- Test: `backend/tests/test_pipeline_router.py` (append)

**Interfaces:**
- Produces: `POST /v1/pipelines/crm-lead:start` → `202 {"uid", "state", ...}`; `GET /v1/pipelines/crm-lead/runs/{uid}` → the run view or 404; `GET /v1/pipelines/crm-lead/schedule`; `PUT /v1/pipelines/crm-lead/schedule` with `{"enabled": bool, "interval_minutes": int}`.

- [ ] **Step 1: Write the failing test**

```python
def test_starting_a_run_answers_at_once_with_a_uid_to_watch():
    r = client.post("/v1/pipelines/crm-lead:start", json={"source": "odoo"},
                    headers={"X-Volt-Role": "MANAGER"})
    assert r.status_code == 202
    body = r.json()
    assert body["uid"].startswith("run-")
    assert body["state"] in ("running", "done", "failed")


def test_an_officer_may_not_start_a_run():
    r = client.post("/v1/pipelines/crm-lead:start", json={"source": "odoo"},
                    headers={"X-Volt-Role": "OFFICER"})
    assert r.status_code == 403


def test_an_unknown_run_is_a_404_not_an_invented_one():
    r = client.get("/v1/pipelines/crm-lead/runs/run-nope")
    assert r.status_code == 404


def test_the_schedule_is_off_until_a_manager_turns_it_on():
    assert client.get("/v1/pipelines/crm-lead/schedule").json()["enabled"] is False
    refused = client.put("/v1/pipelines/crm-lead/schedule",
                         json={"enabled": True}, headers={"X-Volt-Role": "OFFICER"})
    assert refused.status_code == 403
    on = client.put("/v1/pipelines/crm-lead/schedule",
                    json={"enabled": True, "interval_minutes": 15},
                    headers={"X-Volt-Role": "MANAGER"})
    assert on.status_code == 200
    assert on.json()["enabled"] is True
    assert on.json()["interval_minutes"] == 15
    assert on.json()["in_process_only"] is True
    client.put("/v1/pipelines/crm-lead/schedule", json={"enabled": False},
               headers={"X-Volt-Role": "MANAGER"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_router.py -v`
Expected: FAIL — 404 on `:start`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/app/routers/pipelines.py`:

```python
import threading

from fastapi.responses import JSONResponse

from ..pipelines import runs, schedule as schedule_mod, service


@router.post("/v1/pipelines/crm-lead:start", status_code=202)
async def start_crm_lead(request: Request,
                         x_volt_role: str = Header(default="OFFICER"),
                         x_volt_filename: str = Header(default=None)):
    """Answer at once with a uid to watch, and do the work on a thread.

    A 34k-row pull takes a minute and a half. Holding the request open for it gives
    the officer a spinner that cannot say whether anything is happening — which is
    the question they actually ask at eighty seconds.
    """
    _manager_only(x_volt_role)
    raw = await _body(request)
    is_json = "application/json" in (request.headers.get("content-type") or "")
    if raw and not is_json:
        filename = re.sub(r"[^\w.\- ]", "", Path(x_volt_filename or "").name)[:120] or None
        uid = runs.start("upload")
        threading.Thread(target=service.run_upload, args=(raw, filename, uid),
                         daemon=True).start()
    else:
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        if (body or {}).get("source") != "odoo":
            raise errors.validation_failed([{
                "pointer": "/source", "code": "invalid",
                "message": 'source must be "odoo", or send the file as the body',
                "message_th": "ต้องระบุ source เป็น odoo หรือส่งไฟล์มาใน body"}])
        uid = runs.start("odoo")
        threading.Thread(target=service.run_odoo, args=(uid,), daemon=True).start()
    return JSONResponse(status_code=202, content=runs.get(uid))


@router.get("/v1/pipelines/crm-lead/runs/{uid}")
def get_run(uid: str):
    run = runs.get(uid)
    if run is None:
        raise errors.not_found("pipeline run")
    return run


@router.get("/v1/pipelines/crm-lead/schedule")
def get_schedule():
    return schedule_mod.state()


@router.put("/v1/pipelines/crm-lead/schedule")
def put_schedule(body: dict = Body(default=None),
                 x_volt_role: str = Header(default="OFFICER")):
    _manager_only(x_volt_role)
    body = body or {}
    if body.get("enabled"):
        return schedule_mod.enable(body.get("interval_minutes",
                                            schedule_mod.INTERVAL_DEFAULT))
    return schedule_mod.disable()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline_router.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/pipelines.py backend/tests/test_pipeline_router.py
git commit -m "feat(pipelines): start a run, watch it, and turn the refetch on"
```

---

### Task 6: The bar, the clock, and the choice

**Files:**
- Create: `frontend/src/components/RunProgress.jsx`
- Create: `frontend/src/components/RunProgress.test.jsx`
- Modify: `frontend/src/api.js`, `frontend/src/i18n-admin.js`, `frontend/src/screens/DataSourcesMigration.jsx`, `frontend/src/journey.css`

**Interfaces:**
- Consumes: Task 5.
- Produces: `<RunProgress run={run} />`; `api.startCrmLeadPipeline(fileOrNull)`, `api.crmLeadRun(uid)`, `api.crmLeadSchedule()`, `api.setCrmLeadSchedule(enabled, minutes)`.

- [ ] **Step 1: Write the failing test**

```jsx
import { render, screen } from '@testing-library/react'
import RunProgress from './RunProgress.jsx'

const running = { uid: 'run-1', state: 'running', kind: 'odoo', read: 18400,
                  total: 34336, landed: 18270, rejected: 130, elapsed_seconds: 42.3 }

test('a known total gives a real percentage, not a guess', () => {
  render(<RunProgress run={running} />)
  const bar = screen.getByRole('progressbar')
  expect(bar).toHaveAttribute('aria-valuenow', '53')
  expect(bar).toHaveAttribute('aria-valuemax', '100')
  expect(screen.getByText(/18,400/)).toBeInTheDocument()
})

test('before the total is known the bar makes no claim about how far along it is', () => {
  render(<RunProgress run={{ ...running, total: null, read: 0 }} />)
  const bar = screen.getByRole('progressbar')
  expect(bar).not.toHaveAttribute('aria-valuenow')
})

test('the elapsed clock is shown in minutes and seconds', () => {
  render(<RunProgress run={running} />)
  expect(screen.getByTestId('run-elapsed')).toHaveTextContent('0:42')
})

test('a failed run shows its reason rather than an empty bar', () => {
  render(<RunProgress run={{ ...running, state: 'failed',
                             problem: { code: 'integration_unavailable',
                                        detail: 'Odoo refused' } }} />)
  expect(screen.getByText(/Odoo refused/)).toBeInTheDocument()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/RunProgress.test.jsx`
Expected: FAIL — cannot resolve `./RunProgress.jsx`

- [ ] **Step 3: Write minimal implementation**

```jsx
/**
 * A progress bar that only claims what the run reported.
 *
 * Until `total` arrives from the first page, there is no percentage and the bar
 * carries no aria-valuenow — an indeterminate bar that pretends to be at 30% is
 * worse than one that admits it does not know.
 */
export default function RunProgress({ run }) {
  if (!run) return null
  const { state, read = 0, total, landed = 0, rejected = 0, elapsed_seconds: elapsed = 0 } = run
  const pct = total ? Math.min(100, Math.round((read / total) * 100)) : null
  const clock = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, '0')}`
  const n = (v) => v.toLocaleString('en-US')

  if (state === 'failed') {
    return (
      <p className="ad-quiet" data-testid="run-failed" role="status">
        {run.problem?.detail || run.problem?.code || 'failed'}
      </p>
    )
  }
  return (
    <div className="runprog" data-testid="run-progress" data-state={state}>
      <div className="runprog__track"
           role="progressbar"
           aria-label="import progress"
           {...(pct === null ? {} : { 'aria-valuenow': String(pct), 'aria-valuemin': '0', 'aria-valuemax': '100' })}>
        <div className={'runprog__fill' + (pct === null ? ' runprog__fill--idk' : '')}
             style={pct === null ? undefined : { width: pct + '%' }} />
      </div>
      <p className="runprog__counts">
        <span data-testid="run-read">{n(read)}{total ? ` / ${n(total)}` : ''}</span>
        {' · '}<span data-testid="run-elapsed">{clock}</span>
        {state === 'done' && <> · {n(landed)} / {n(rejected)}</>}
      </p>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/RunProgress.test.jsx`
Expected: 4 passed

- [ ] **Step 5: Wire the screen, the api client, the strings and the CSS**

`api.js`:

```js
  startCrmLeadPipeline: (file) => (file
    ? postRaw('/v1/pipelines/crm-lead:start', file)
    : post('/v1/pipelines/crm-lead:start', { source: 'odoo' })),
  crmLeadRun: (uid) => get(`/v1/pipelines/crm-lead/runs/${uid}`),
  crmLeadSchedule: () => get('/v1/pipelines/crm-lead/schedule'),
  setCrmLeadSchedule: (enabled, minutes) =>
    put('/v1/pipelines/crm-lead/schedule', { enabled, interval_minutes: minutes }),
```

In `DataSourcesMigration.jsx`, replace `runPipeline` with a start-then-poll version, polling every 1000 ms while `state === 'running'` and clearing the interval on unmount; render `<RunProgress run={pipeRun} />`; add the schedule checkbox reading `in_process_only` to render its caveat line.

New `mig.*` strings, EN and TH: `schedTitle`, `schedEvery`, `schedOff`, `schedNext`, `schedLast`, `schedInProcess` ("This timer lives in the running server and stops when it restarts. The scheduled job on Google Cloud is the durable one."), `runElapsed`, `runReading`.

`journey.css` — tokens only, no hex (the file's own header promises it, and `journey.test.js` enforces it):

```css
.runprog__track { height: 8px; border-radius: 99px; background: var(--surface-100); overflow: hidden; }
.runprog__fill { height: 100%; background: var(--status-pending); transition: width .25s ease; }
.runprog__fill--idk { width: 40%; animation: runprog-slide 1.2s ease-in-out infinite; }
.runprog__counts { margin: 4px 0 0; font: var(--caption-12); color: var(--ink-500); font-variant-numeric: tabular-nums; }
@keyframes runprog-slide { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
@media (prefers-reduced-motion: reduce) {
  .runprog__fill { transition: none; }
  .runprog__fill--idk { animation: none; width: 100%; opacity: .4; }
}
```

- [ ] **Step 6: Run the whole frontend suite**

Run: `cd frontend && npx vitest run`
Expected: 519+ passed, 0 failed

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/RunProgress.jsx frontend/src/components/RunProgress.test.jsx frontend/src/api.js frontend/src/i18n-admin.js frontend/src/screens/DataSourcesMigration.jsx frontend/src/journey.css
git commit -m "feat(import data): a bar that only claims what the run reported, and a clock that stops when it stops"
```

---

### Task 7: The page's own name, and the whole thing checked

**Files:**
- Modify: `frontend/src/i18n-admin.js` — `mig.title`, `mig.sub`
- Modify: `scripts/e2e_check.py` — check 31
- Test: every suite

**Interfaces:**
- Consumes: Tasks 1–6.

- [ ] **Step 1: Rename the page, not the rail**

`mig.title`: EN `Import Data` (TH `นำเข้าข้อมูล`). `mig.sub` keeps describing both directions, since the page still exports.

**Do not touch** `nav.dataSources` in `i18n-journey.js` or `Shell.jsx`: ruling 70 keeps the rail on the rank-2 SOP's word, and `Shell.test.jsx` pins it. Add a comment beside `mig.title` recording that this rename was authorised on 2026-09-11 and that the rail was deliberately left.

- [ ] **Step 2: Write the failing e2e check**

```python
@check(31, "a started run can be watched, and the schedule is off until asked",
       "2026-09-11 - progress is reported by the work, and a 15-minute refetch is opt-in")
def check_run_is_watchable(api, ctx):
    schedule = api.get("/v1/pipelines/crm-lead/schedule")
    ctx.status(schedule, 200)
    ctx.equal(schedule.json()["enabled"], False, "the refetch must be off until a Manager asks")
    ctx.equal(schedule.json()["in_process_only"], True, "the timer must say it dies with the process")

    refused = api.call("PUT", "/v1/pipelines/crm-lead/schedule", {"enabled": True},
                       extra_headers={"X-Volt-Role": "OFFICER"})
    ctx.status(refused, 403)

    raw = b"Volt ID,Phone,Order Status\r\nVL9999002,0912345679,Order - Done\r\n"
    started = api.call("POST", "/v1/pipelines/crm-lead:start", raw_body=raw,
                       extra_headers={"X-Volt-Role": "MANAGER",
                                      "X-Volt-Filename": "x.csv",
                                      "content-type": "text/csv"})
    ctx.status(started, 202)
    uid = started.json()["uid"]
    for _ in range(40):
        run = api.get("/v1/pipelines/crm-lead/runs/%s" % uid).json()
        if run["state"] != "running":
            break
        time.sleep(0.25)
    ctx.require(run["state"] in ("done", "failed"), "the run must reach an end state")
    if run["state"] == "done":
        ctx.equal(run["landed"], 1, "the one identifiable row lands")
    ctx.require(run["elapsed_seconds"] >= 0, "a run must report how long it took")
    ctx.note("run %s -> %s in %.1fs" % (uid, run["state"], run["elapsed_seconds"]))
```

Add `import time` at the top of `scripts/e2e_check.py` if absent.

- [ ] **Step 3: Run every suite**

```bash
cd backend && VOLT_TEST_PG_URL="$(../scripts/pg_local.sh url)" .venv/bin/python -m pytest -q
cd ../frontend && npx vitest run
cd .. && DATABASE_URL="postgresql+psycopg://postgres:@/volt_local?host=$HOME/.volt-postgres/data" scripts/run_prototype.sh
```

Expected: backend green except the two pre-existing `test_audit_*` failures owned by parallel work; frontend 519+; e2e 31 of 31.

- [ ] **Step 4: Drive it in a real browser**

```bash
node scripts/uat_browser.mjs /data-sources --role MANAGER --lang th --profile sched \
  --actions actions.json --shot progress.png
```

with an actions file that clicks the Odoo door, waits 10 s, and screenshots — the bar must be somewhere between 0 and 100%, with a clock that has moved. **Look at the screenshot.**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n-admin.js scripts/e2e_check.py
git commit -m "feat(import data): the page names the act; the rail keeps the SOP's word"
```

---

## Self-Review

**Coverage of the request.** Rail rename → Task 7, as page-title-only per your choice, with the reason recorded. Door choice → already shipped; Task 6 re-points it at `:start`. Progress bar + time count → Tasks 1, 2, 6. 15-minute schedule → Tasks 4, 5, 6.

**Placeholders:** none in Tasks 1–5. Task 6 Step 5 describes the screen wiring in prose rather than a full diff, because the file is 700 lines and the edit is three insertions into code the executor will have open; every new string, endpoint and CSS rule it needs is named exactly.

**Type consistency:** the run dict's keys are identical in `runs.py` (Task 1), `service.py` (Task 3), the router (Task 5), `RunProgress.jsx` (Task 6) and check 31 (Task 7): `uid, kind, state, read, total, landed, rejected, overwrote, started_at, finished_at, elapsed_seconds, problem`. `on_progress(read=, total=)` in ingress matches `runs.progress(uid, **fields)`. `schedule.state()` keys match the router's passthrough and the screen's reads.

**One risk worth naming before execution.** `service.run_odoo` on a background thread opens its own database connection outside the request lifecycle. `db.engine()` is a module-level pooled engine with `pool_size=5, max_overflow=2`, so a 90-second run holds one of seven connections for its whole duration. With the timer on, that is one connection busy ~every 15 minutes for 90 seconds. Acceptable, and worth watching if the interval is ever shortened.
