"""The review fence in production mode — the refusal, its repair, the forced confirm.

The fence itself (app/preview_review.py, app/production_unit.py) refuses a
confirm whose review no longer stands: anything that commits a business mutation
moves the version the review was made against, so the answer is `preview_stale`
(409, DEBT-PRD-001) with the Thai sentence that says to re-check. This file tests
the doors around that answer: the re-check that repairs the fence, the manager's
forced confirm (reason-named, role-gated, fence-free job) and the refusals that
guard both. ADDITIONS to test_upload_operational.py.
"""
import json

import pytest
from sqlalchemy import text

from app import db, landing, task_objects
from app.pipelines import peak_writer
from tests.test_peak_router import _exact, _inv, _parsed
from tests.test_production_http import production as production

# A customer_no the served book need not carry: only the fence moves here, the
# apply itself is never executed (the job stays queued without a relay).
NO = "28001000001"


@pytest.fixture
def objects(monkeypatch):
    held = {}
    monkeypatch.setattr(task_objects, "put", lambda name, raw: held.setdefault(name, raw) and name)
    monkeypatch.setattr(task_objects, "get", lambda name: held[name])
    return held


@pytest.fixture
def go_live(monkeypatch):
    monkeypatch.setenv("PROD_GO_LIVE_ENABLED", "true")


def _stage(conn):
    written = peak_writer.write(conn, _parsed(_inv("IVT-90300", NO)), [_exact(NO)],
                                door="upload", filename="export_as_of_20240101_20260914.xlsx")
    conn.commit()
    return written["run_id"]


def _current(conn):
    return conn.execute(text("select version from app.business_version where singleton")).scalar_one()


def _fence(conn, run_id, version):
    conn.execute(text("update landing.import_run set meta = meta || "
                      "jsonb_build_object('review_state_version', cast(:v as text)) where id = :r"),
                 {"v": str(version), "r": run_id})
    conn.commit()


def _job(conn, uid):
    return conn.execute(text("select payload from app.task_outbox where uid=:u"), {"u": uid}).scalar()


def _reviewed_staged_run():
    """A staged run whose fence is current — and the version that now stands."""
    with db.connect() as conn:
        run_id = _stage(conn)
        _fence(conn, run_id, _current(conn))
    return run_id


def _move_version():
    with db.connect() as conn, conn.begin():
        conn.execute(text("update app.business_version set version=version+1"))
        return _current(conn)


def test_a_confirm_whose_review_moved_is_refused_and_the_recheck_repairs_it(production, objects, go_live):
    api, headers = production
    actor = headers("owner@volt.co.th", "OWNER", "owner")
    actor.update({"Content-Type": "application/json"})
    run_id = _reviewed_staged_run()
    # The version moves after the review: every business mutation does this —
    # including the staging of another file or any other officer's write.
    current = _move_version()

    refused = api.post("/api/v1/pipelines/peak-report/landing-runs/%d:apply" % run_id, json={}, headers=actor)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "preview_stale"
    assert "ตรวจ" in refused.json()["message_th"]

    rechecked = api.post("/api/v1/pipelines/peak-report/landing-runs/%d:recheck" % run_id, json={}, headers=actor)
    assert rechecked.status_code == 200, rechecked.text
    assert rechecked.json()["review_state_version"] == str(current)
    with db.connect() as conn, conn.begin():
        meta = landing.get_run(conn, run_id)["meta"]
    assert meta["review_state_version"] == str(current) and meta["review_state_version_at"]

    applied = api.post("/api/v1/pipelines/peak-report/landing-runs/%d:apply" % run_id,
                       json={"review_state_version": rechecked.json()["review_state_version"]}, headers=actor)
    assert applied.status_code == 202, applied.text
    with db.connect() as conn, conn.begin():
        payload = _job(conn, applied.json()["uid"])
    assert payload["expected_state_version"] == str(current)
    assert "force_state_change" not in payload


def test_a_forced_confirm_needs_a_reason_and_a_manager(production, objects, go_live):
    api, headers = production
    manager = headers("owner@volt.co.th", "OWNER", "owner")
    officer = headers("thip@volt.co.th", "OFFICER", "thip")
    for actor in (manager, officer):
        actor.update({"Content-Type": "application/json"})
    run_id = _reviewed_staged_run()
    _move_version()

    # An officer cannot cross the fence, with or without a reason.
    assert api.post("/api/v1/pipelines/peak-report/landing-runs/%d:apply" % run_id,
                    json={"force_state_change": True}, headers=officer).status_code == 403
    assert api.post("/api/v1/pipelines/peak-report/landing-runs/%d:apply" % run_id,
                    json={"force_state_change": True, "reason": "my own other import moved it"},
                    headers=officer).status_code == 403
    # A manager's forced confirm names its reason: no reason, no act.
    silent = api.post("/api/v1/pipelines/peak-report/landing-runs/%d:apply" % run_id,
                      json={"force_state_change": True}, headers=manager)
    assert silent.status_code == 422 and silent.json()["errors"][0]["pointer"] == "/reason"


def test_a_forced_confirm_crosses_the_fence_and_its_job_carries_no_fence(production, objects, go_live):
    api, headers = production
    actor = headers("owner@volt.co.th", "OWNER", "owner")
    actor.update({"Content-Type": "application/json"})
    run_id = _reviewed_staged_run()
    _move_version()
    reason = "the change was my own other import; I reviewed both"

    forced = api.post("/api/v1/pipelines/peak-report/landing-runs/%d:apply" % run_id,
                      json={"force_state_change": True, "reason": reason}, headers=actor)
    assert forced.status_code == 202, forced.text
    uid = forced.json()["uid"]
    with db.connect() as conn, conn.begin():
        payload = _job(conn, uid)
    assert payload["force_state_change"] is True
    assert payload.get("expected_state_version") is None, "the job carries no fence of its own"
    # The reason travels with the job: the worker's audit row keeps it.
    assert json.loads(objects["jobs/%s/body" % uid])["reason"] == reason
