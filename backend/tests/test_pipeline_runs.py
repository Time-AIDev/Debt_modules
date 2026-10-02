"""A run you can watch from another request."""
import time

from app.pipelines import runs


def setup_function():
    runs.reset()


def test_a_started_run_is_visible_immediately_and_says_it_is_queued():
    uid = runs.start("odoo")
    row = runs.get(uid)
    assert row["state"] == "queued"
    assert row["read"] == 0 and row["total"] is None
    assert (row["phase"], row["processed"], row["phase_total"]) == ("queued", 0, None)
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
    assert runs.get(uid)["phase"] == "done"
    assert runs.get(uid)["landed"] == 3


def test_a_failed_run_carries_its_problem_and_is_not_pretended_to_be_done():
    uid = runs.start("odoo")
    runs.fail(uid, {"code": "integration_unavailable", "detail": "Odoo refused"})
    row = runs.get(uid)
    assert row["state"] == "failed"
    assert row["phase"] == "failed"
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


def test_latest_filters_by_kind_and_still_defaults_to_any():
    runs.reset()
    a = runs.start("upload"); runs.finish(a, {})
    b = runs.start("odoo"); runs.finish(b, {})
    assert runs.latest()["uid"] == b
    assert runs.latest(kind="upload")["uid"] == a
