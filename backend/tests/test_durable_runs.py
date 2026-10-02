import pytest
from app import db, migrate
from app.pipelines import runs


@pytest.fixture
def durable(monkeypatch, pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    db.reset()
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ENV", "prd")
    yield
    db.reset()


def test_progress_survives_losing_process_memory(durable):
    uid = runs.start("sheet")
    runs.progress(uid, phase="reading", processed=25)
    runs._RUNS.clear()
    assert runs.get(uid)["processed"] == 25
    assert runs.get(uid)["state"] == "parsing"


def test_cancel_is_visible_after_restart(durable):
    uid = runs.start("sheet")
    runs.cancel(uid)
    runs._RUNS.clear()
    with pytest.raises(runs.RunCancelled):
        runs.checkpoint(uid)


def test_completed_runs_do_not_disappear_after_more_than_twenty_jobs(durable):
    first = runs.start("sheet")
    runs.finish(first, {"result": {"landed": 1}})
    for _ in range(21): runs.start("sheet")
    runs._RUNS.clear()
    assert runs.get(first)["state"] == "done"
