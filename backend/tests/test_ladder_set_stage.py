"""Q1 / F05 — the hand-moved ladder stage (feedback-r2 TASK-110/111).

`:advance` stays the officer's forward step; its pinned backward refusal
(`test_adversarial_regressions.py:30`) is expected UNTOUCHED — numbered edit 41 is
spent only if that test itself must change, and it does not. Every test here is an
ADDITION.
"""
import pytest
from fastapi.testclient import TestClient

from app import journey
from app.main import app

MANAGER = {"X-Volt-Role": "MANAGER", "X-Volt-Officer": "settasak"}
OWNER = {"X-Volt-Role": "OWNER", "X-Volt-Officer": "owner"}
OFFICER = {"X-Volt-Role": "OFFICER", "X-Volt-Officer": "nantapol"}
SUPERVISOR = {"X-Volt-Role": "SUPERVISOR", "X-Volt-Officer": "thip"}


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


@pytest.fixture
def state():
    return journey.for_current()


def _case(state, stage):
    return next(c for c in state.cases.values() if c["stage"] == stage)


def _set(client, case_uid, **body):
    return client.post("/v1/cases/%s:set-stage" % case_uid, headers=MANAGER,
                       json={"role": "MANAGER", **body})


def test_officer_and_supervisor_are_refused_and_nothing_moves(client, state):
    case = _case(state, "NOTICE_30")
    for headers in (OFFICER, SUPERVISOR):
        response = client.post("/v1/cases/%s:set-stage" % case["uid"], headers=headers,
                               json={"to_stage": "NORMAL", "reason": "ทดสอบ"})
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"
    assert case["stage"] == "NOTICE_30"


def test_a_manager_must_give_a_reason(client, state):
    case = _case(state, "NOTICE_30")
    response = _set(client, case["uid"], to_stage="NORMAL")
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "reason_required"
    assert case["stage"] == "NOTICE_30"


def test_the_same_stage_is_refused_as_a_no_op(client, state):
    case = _case(state, "NOTICE_30")
    response = _set(client, case["uid"], to_stage="NOTICE_30", reason="ทดสอบ")
    assert response.status_code == 409 and response.json()["code"] == "stage_unchanged"


def test_a_manager_moves_a_stage_back_with_a_reason_and_a_trail(client, state):
    case = _case(state, "RESTRUCTURE_OFFER_60")
    response = _set(client, case["uid"], to_stage="NOTICE_30", reason="บันทึกขั้นผิด",
                    by="settasak", role="MANAGER")
    assert response.status_code == 200, response.text
    assert case["stage"] == "NOTICE_30"
    last = case["stage_history"][-1]
    assert last["manual"] is True and last["from"] == "RESTRUCTURE_OFFER_60"
    assert last["reason"] == "บันทึกขั้นผิด" and last["role"] == "MANAGER"
    entry = next(e for e in client.get("/v1/audit").json()["entries"] if e["act"] == "LADDER_STAGE_SET")
    assert entry["subject_uid"] == case["uid"]
    assert entry["detail"]["direction"] == "back" and entry["detail"]["to"] == "NOTICE_30"
    # a backward move leaves NPL state alone (this case never declared, so none appears)
    assert case.get("npl_uid") is None


def test_back_then_forward_across_npl_never_declares_it_twice(client, state):
    case = _case(state, "NPL_DECLARED_90")
    declared = case["npl_uid"]
    assert declared and len(state.npl_cases) == 2
    back = _set(client, case["uid"], to_stage="RESTRUCTURE_OFFER_60", reason="ทบทวนก่อนประกาศ")
    assert back.status_code == 200 and case["stage"] == "RESTRUCTURE_OFFER_60"
    assert case["npl_uid"] == declared, "a backward move never touches npl_uid"
    forward = _set(client, case["uid"], to_stage="NPL_DECLARED_90", reason="ยืนยันประกาศเดิม")
    assert forward.status_code == 200, forward.text
    assert case["stage"] == "NPL_DECLARED_90"
    assert case["npl_uid"] == declared
    assert len(state.npl_cases) == 2, "the forward move re-declared nothing"


def test_a_manager_may_skip_forward_when_the_rung_gate_is_met(client, state):
    case = _case(state, "NOTICE_30")
    response = _set(client, case["uid"], to_stage="NPL_DECLARED_90", reason="ยกระดับทันที")
    # missed=2 on this case meets the NPL rung's min_missed; the skip itself is the
    # manager's call now (the old OWNER-only skip rule is not this act's rule).
    assert response.status_code == 200, response.text
    assert case["stage"] == "NPL_DECLARED_90" and case["npl_uid"]
    assert len(state.npl_cases) == 3


def test_the_min_missed_gate_still_refuses_a_forward_move(client, state):
    case = _case(state, "NORMAL")
    response = _set(client, case["uid"], to_stage="NPL_DECLARED_90", reason="ข้ามขั้น")
    assert response.status_code == 422
    assert response.json()["code"] == "stage_requires_missed_count"


def test_a_cash_case_mirrors_the_act(client, state):
    cash = next(iter(state.cash_cases.values()))
    officer = client.post("/v1/cash-cases/%s:set-stage" % cash["uid"], headers=OFFICER,
                          json={"to_stage": "NOTICE_30", "reason": "x"})
    assert officer.status_code == 403
    response = client.post("/v1/cash-cases/%s:set-stage" % cash["uid"], headers=MANAGER,
                           json={"to_stage": "NOTICE_30", "reason": "ย้อนขั้นเพื่อทบทวน", "role": "MANAGER"})
    assert response.status_code == 200, response.text
    assert cash["stage"] == "NOTICE_30"
    assert cash["stage_history"][-1]["manual"] is True
    unknown = client.post("/v1/cash-cases/%s:set-stage" % cash["uid"], headers=MANAGER,
                          json={"to_stage": "NPL_DECLARED_90", "reason": "x", "role": "MANAGER"})
    assert unknown.status_code == 422 and unknown.json()["code"] == "ladder_stage_unknown"


def test_an_owner_may_also_move_it(client, state):
    case = _case(state, "RESTRUCTURE_OFFER_60")
    response = client.post("/v1/cases/%s:set-stage" % case["uid"], headers=OWNER,
                           json={"to_stage": "NOTICE_30", "reason": "เจ้าของสั่งทบทวน", "role": "OWNER"})
    assert response.status_code == 200 and case["stage"] == "NOTICE_30"


def test_a_manager_role_in_the_body_never_lets_an_officer_through(client, state):
    """fix-all Leg R: the role is the X-Volt-Role header (rewritten from the session by
    the auth middleware), never the body — this path is not on auth.ACTOR_ROLE_BODY."""
    case = _case(state, "NOTICE_30")
    lease = client.post("/v1/cases/%s:set-stage" % case["uid"], headers=OFFICER,
                        json={"to_stage": "NORMAL", "reason": "ทดสอบ", "role": "MANAGER"})
    assert lease.status_code == 403 and lease.json()["code"] == "forbidden"
    assert case["stage"] == "NOTICE_30" and not case["stage_history"][-1].get("manual")
    cash = next(iter(state.cash_cases.values()))
    before = (cash["stage"], len(cash["stage_history"]))
    refused = client.post("/v1/cash-cases/%s:set-stage" % cash["uid"], headers=OFFICER,
                          json={"to_stage": "NOTICE_30", "reason": "x", "role": "OWNER"})
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    assert (cash["stage"], len(cash["stage_history"])) == before


def test_the_cash_advance_only_moves_forward_and_confirming_a_default_is_a_managers_act(client, state):
    """fix-all Leg R audit: POST /v1/cash-cases/{uid}:advance had no role and no
    direction check, so an OFFICER could confirm a default — which opens a recovery and
    its lot — or walk a case back. It now keeps the lease :advance's rule (forward, one
    rung; a skip is the OWNER's with a note) and the default is MANAGER+ by header."""
    cash = next(iter(state.cash_cases.values()))
    cash["stage"], cash["recovery_uid"] = "NOTICE_30", None
    recoveries = len(state.recovery_cases)
    url = "/v1/cash-cases/%s:advance" % cash["uid"]

    skip = client.post(url, headers=MANAGER, json={"to_stage": "DEFAULT_CONFIRMED_90", "path": "REMOVAL"})
    assert skip.status_code == 422 and skip.json()["code"] == "ladder_stage_skip"
    step = client.post(url, headers=OFFICER, json={"to_stage": "SETTLEMENT_PLAN_60"})
    assert step.status_code == 200 and cash["stage"] == "SETTLEMENT_PLAN_60"   # an officer's ordinary rung
    for headers in (OFFICER, MANAGER):
        back = client.post(url, headers=headers, json={"to_stage": "NOTICE_30"})
        assert back.status_code == 422 and back.json()["code"] == "ladder_move_not_forward"
    officer = client.post(url, headers=OFFICER,
                          json={"to_stage": "DEFAULT_CONFIRMED_90", "path": "REMOVAL", "role": "MANAGER"})
    assert officer.status_code == 403 and officer.json()["code"] == "forbidden"
    assert cash["stage"] == "SETTLEMENT_PLAN_60" and not cash.get("recovery_uid")
    assert len(state.recovery_cases) == recoveries

    manager = client.post(url, headers=MANAGER, json={"to_stage": "DEFAULT_CONFIRMED_90", "path": "REMOVAL"})
    assert manager.status_code == 200, manager.text
    assert cash["stage"] == "DEFAULT_CONFIRMED_90" and len(state.recovery_cases) == recoveries + 1
    assert state.recovery_cases[cash["recovery_uid"]]["strategy"] == "REPOSSESSION"
