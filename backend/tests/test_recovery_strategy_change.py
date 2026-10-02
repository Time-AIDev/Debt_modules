"""Q2 / F08 — the recovery strategy board (feedback-r2 TASK-112/113).

A strategy change supersedes the old recovery and opens a new one; the NPL board's
columns are served with their availability, EXTERNAL_COLLECTION visible and disabled
on D27. Every test here is an ADDITION.
"""
import pytest
from fastapi.testclient import TestClient

from app import journey
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


@pytest.fixture
def state():
    return journey.for_current()


def _open_recovery(client, strategy="LEGAL"):
    npl = next(n for n in client.get("/v1/npl-cases").json()["npl_cases"] if not n.get("recovery_uid"))
    opened = client.post("/v1/npl-cases/%s/recovery" % npl["uid"], json={"strategy": strategy},
                         headers=MANAGER)
    assert opened.status_code == 201, opened.text
    return npl, opened.json()["recovery"]


def _change(client, rec_uid, **body):
    return client.post("/v1/recovery-cases/%s:change-strategy" % rec_uid, headers=MANAGER,
                       json={"role": "MANAGER", **body})


def test_the_board_columns_are_served_with_availability(client):
    meta = client.get("/v1/npl-cases").json()["meta"]
    strategies = {s["strategy"]: s for s in meta["strategies"]}
    assert set(strategies) == set(journey.RECOVERY_STRATEGIES)
    assert all(s["label_th"] and s["label_en"] for s in strategies.values())
    assert strategies["LEGAL"]["available"] is True
    assert strategies["EXTERNAL_COLLECTION"]["available"] is False
    assert strategies["EXTERNAL_COLLECTION"]["pending_decision"] == "D27"
    assert strategies["LEGAL"]["rate_pct"] == "38"
    assert strategies["EXTERNAL_COLLECTION"]["rate_pct"] is None


def test_the_rows_carry_the_open_recoverys_strategy(client):
    _, rec = _open_recovery(client, "LEGAL")
    rows = client.get("/v1/npl-cases").json()["npl_cases"]
    row = next(r for r in rows if r.get("recovery_uid") == rec["uid"])
    assert row["strategy"] == "LEGAL"
    plain = next(r for r in rows if not r.get("recovery_uid"))
    assert plain["strategy"] is None


def test_an_officer_may_not_change_the_strategy(client):
    _, rec = _open_recovery(client)
    response = client.post("/v1/recovery-cases/%s:change-strategy" % rec["uid"], headers=OFFICER,
                           json={"strategy": "REPOSSESSION", "reason": "x"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_the_refusals_name_their_rule(client, state):
    _, rec = _open_recovery(client)
    assert _change(client, rec["uid"], strategy="REPOSSESSION").status_code == 422  # no reason
    assert _change(client, rec["uid"], strategy="REPOSSESSION").json()["errors"][0]["code"] == "reason_required"
    same = _change(client, rec["uid"], strategy="LEGAL", reason="退回เดิม")
    assert same.status_code == 409 and same.json()["code"] == "strategy_unchanged"
    ext = _change(client, rec["uid"], strategy="EXTERNAL_COLLECTION", reason="ส่งออก")
    assert ext.status_code == 422 and ext.json()["code"] == "recovery_strategy_unavailable"
    assert ext.json()["extensions"]["pending_decision"] == "D27"
    unknown = _change(client, rec["uid"], strategy="AUCTION", reason="x")
    assert unknown.status_code == 422 and unknown.json()["code"] == "recovery_strategy_unknown"


def test_a_manager_supersedes_legal_with_repossession_and_the_board_follows(client, state):
    npl, rec = _open_recovery(client, "LEGAL")
    lots_before = len(state.lots)
    response = _change(client, rec["uid"], strategy="REPOSSESSION", reason="ลูกค้ายอมให้ยึดคืน",
                       by="settasak", role="MANAGER")
    assert response.status_code == 200, response.text
    body = response.json()
    old, new = body["superseded"], body["recovery"]
    assert old["uid"] == rec["uid"] and old["status"] == "SUPERSEDED"
    assert old["superseded_by"] == new["uid"] and old["superseded_reason"] == "ลูกค้ายอมให้ยึดคืน"
    assert new["strategy"] == "REPOSSESSION" and new["supersedes"] == rec["uid"]
    assert new["status"] == "IN_PROGRESS"
    assert body["lot"] and len(state.lots) == lots_before + 1
    assert body["note_th"] and body["note_en"]
    # the NPL row follows the new recovery, and superseded rows stay visible
    row = next(r for r in client.get("/v1/npl-cases").json()["npl_cases"] if r["uid"] == npl["uid"])
    assert row["recovery_uid"] == new["uid"] and row["strategy"] == "REPOSSESSION"
    listed = client.get("/v1/recovery-cases").json()["recovery_cases"]
    assert {r["uid"] for r in listed} >= {old["uid"], new["uid"]}
    # the audit names the change
    entry = next(e for e in client.get("/v1/audit").json()["entries"] if e["act"] == "RECOVERY_STRATEGY_CHANGED")
    assert entry["subject_uid"] == rec["uid"]
    assert entry["detail"]["from"] == "LEGAL" and entry["detail"]["to"] == "REPOSSESSION"


def test_a_resolved_recovery_cannot_change_strategy(client, state):
    _, rec = _open_recovery(client, "LEGAL")
    resolved = client.post("/v1/recovery-cases/%s:resolve" % rec["uid"], headers=MANAGER,
                           json={"outcome": "FULL", "by": "settasak"})
    assert resolved.status_code == 200, resolved.text
    response = _change(client, rec["uid"], strategy="REPOSSESSION", reason="x")
    assert response.status_code == 409 and response.json()["code"] == "recovery_not_open"


def test_the_sop_walkthrough_still_places_step_sixteen_after_a_change(client):
    npl, rec = _open_recovery(client, "LEGAL")
    _change(client, rec["uid"], strategy="REPOSSESSION", reason="ยึดคืน")
    case = journey.for_current().cases[npl["case_uid"]]
    detail = client.get("/v1/cases/by-customer/%s" % case["customer_uid"]).json()
    assert detail["sop_step"]["step"] == 16
    assert detail["sop_step"]["code"] == "NPL_LEGAL_RECOVERY"


def test_a_manager_role_in_the_body_never_lets_an_officer_change_it(client, state):
    """fix-all Leg R: the role comes from the X-Volt-Role header, never the body."""
    _, rec = _open_recovery(client)
    before = len(state.recovery_cases)
    response = client.post("/v1/recovery-cases/%s:change-strategy" % rec["uid"], headers=OFFICER,
                           json={"strategy": "REPOSSESSION", "reason": "x", "role": "MANAGER"})
    assert response.status_code == 403 and response.json()["code"] == "forbidden"
    assert state.recovery_cases[rec["uid"]]["status"] == "IN_PROGRESS"
    assert state.recovery_cases[rec["uid"]]["strategy"] == "LEGAL"
    assert len(state.recovery_cases) == before
