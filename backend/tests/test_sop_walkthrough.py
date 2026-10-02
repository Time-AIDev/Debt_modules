"""The seventeen-step SOP as a served position — round 7, WP2.

The SOP is rank 2 on the authority ladder and, until this module, existed nowhere in
the product. These tests pin the three boundaries that make serving it safe:

  * it states a step and never operates a gate (D26),
  * it never answers one of the deliberate refusals (OD-02/03/04, OQ-31, SVC-37),
  * it does not guess — no default step, and step 1 is never a fallback.

Every test here is an ADDITION. None edits an existing assertion.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app import sop
from app.main import app


@pytest.fixture
def client():
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _thai(s):
    return bool(s) and any('฀' <= ch <= '๿' for ch in s)


# --- the catalogue ------------------------------------------------------------------

def test_the_catalogue_is_seventeen_numbered_one_to_seventeen_with_no_gap():
    assert len(sop.STEPS) == 17
    assert [s["step"] for s in sop.STEPS] == list(range(1, 18))


def test_the_step_codes_and_order_match_the_sop():
    """Contract §3: a UX change may not reorder or rename a workflow step. This is that
    rule, mechanised — the order is the SOP's, and a reshuffle fails here."""
    assert [s["code"] for s in sop.STEPS] == [
        "CHECK_INSTALL_PLAN", "PREPARE_INVOICE_DATA", "ISSUE_INVOICE", "DELIVER_INVOICE",
        "CHECK_INSTALL_DAY", "RECEIPT_AND_MATCHING", "MONTHLY_INVOICES", "REMIND_BEFORE_DUE",
        "BUILD_ARREARS_LIST", "CONTACT_AND_RECORD", "RECORD_AND_TRACK_PTP",
        "SERVICE_COMPLAINT", "CANNOT_BE_REACHED", "MANAGER_REVIEW",
        "ARRANGEMENT_OR_RESTRUCTURE", "NPL_LEGAL_RECOVERY", "REPORT",
    ]


def test_every_step_carries_thai_english_a_lane_a_gate_and_a_screen():
    for s in sop.STEPS:
        assert _thai(s["name_th"]), s["code"]
        assert s["name_en"] and not _thai(s["name_en"]), s["code"]
        assert s["lane"] in sop.LANE_TH and s["lane"] in sop.LANE_EN, s["code"]
        assert _thai(s["gate_rule_th"]), s["code"]
        assert s["screens"], s["code"]


def test_the_three_unplaceable_steps_say_why_in_thai():
    """Steps 7, 9 and 17 are served so the officer sees all seventeen, each with the
    reason no case can stand on it — never silently omitted."""
    unplaceable = [s for s in sop.STEPS if not s["placeable"]]
    assert [s["step"] for s in unplaceable] == [7, 9, 17]
    for s in unplaceable:
        assert _thai(s["not_placeable_th"]), s["code"]


# --- D26: stating a step is not operating a gate -------------------------------------

def test_the_eight_d26_steps_are_marked_the_teams_and_name_the_open_decision():
    assert sorted(sop.D26_STEPS) == [1, 2, 3, 4, 5, 6, 7, 8]
    for n in range(1, 18):
        placed = sop._placed(n, sop._act("X", "ทดสอบ", "test"))
        if n in sop.D26_STEPS:
            assert placed["operated_by"] == "TEAM", n
            assert placed["open_decision"]["code"] == "D26", n
            assert _thai(placed["open_decision"]["question_th"]), n
        else:
            assert placed["operated_by"] == "SYSTEM", n
            assert placed["open_decision"] is None, n


def test_the_d26_note_says_the_app_states_the_position_not_that_it_runs_the_gate():
    placed = sop._placed(2, sop._act("X", "ทดสอบ", "test"))
    assert "ไม่ได้ทำด่านให้" in placed["operated_by_th"]


# --- the refusals --------------------------------------------------------------------

def _walk_values(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_values(v)


def test_the_walkthrough_carries_no_money():
    """OD-02 and OD-03 cannot be answered by arithmetic that is not here. The object
    holds exactly one number — the step index — so 'no client-side arithmetic' is
    satisfied by construction rather than by discipline."""
    case = {"customer_uid": "cu-1", "payment_status": "LATE", "broken_ptp_count": 0}
    out = sop.walkthrough(case, item={})
    money_word = re.compile(r"amount|arrears|outstanding|balance|principal|penalty|pmt|fee",
                            re.I)
    for k, v in _walk_values(out):
        if isinstance(k, str):
            assert not money_word.search(k), "money-named key %r in the walkthrough" % k
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            assert v in range(0, 18), "a number that is not the step index: %r=%r" % (k, v)


def test_npl_placement_reads_only_human_set_state_never_dpd_or_a_ladder_rung():
    """OD-04 guard. A case deep in arrears with a ladder rung drawn is NOT on step 16
    until a person declares it. Placing it from DPD would declare NPL automatically,
    which is exactly what OD-04 refuses to decide."""
    case = {"customer_uid": "cu-1", "payment_status": "LATE", "broken_ptp_count": 0}
    item = {"oldest_dpd": 400,
            "ladder": {"mode": "ASSISTED", "indicative": "NPL_DECLARED_90"}}
    out = sop.walkthrough(case, item=item)
    assert out["step"] != 16
    assert out["ladder_hint"]["is_indicative"] is True

    declared = dict(case, payment_status="NPL")
    assert sop.walkthrough(declared, item=item)["step"] == 16


def test_ladder_mode_manual_withholds_the_indicative_hint():
    case = {"customer_uid": "cu-1", "payment_status": "LATE", "broken_ptp_count": 0}
    out = sop.walkthrough(case, item={"ladder": {"mode": "MANUAL"}})
    assert out["ladder_hint"]["indicative"] is None
    assert out["ladder_hint"]["is_indicative"] is False


def test_external_collection_is_refused_with_a_structured_open_decision_and_no_code_in_prose():
    """Contract §3: a refusal stays visible and legible. Hiding the branch would tidy
    an open decision off the face, which reads as an answer."""
    case = {"customer_uid": "cu-1", "payment_status": "NPL",
            "npl_type": "NPL_3_UNCOOPERATIVE_LEGAL", "broken_ptp_count": 0}
    out = sop.walkthrough(case, item={})
    ext = next(b for b in out["branches"] if b["code"] == "EXTERNAL_COLLECTION")
    assert ext["available"] is False
    # Language pass: the decision is named structurally; codes stay off the prose.
    assert ext["open_decision"]["code"] == "D27" and ext["open_decision"]["owner"]
    for lang in ("th", "en"):
        assert ext["unavailable_reason_" + lang] and "D27" not in ext["unavailable_reason_" + lang]
    assert [b["code"] for b in out["branches"]] == [
        "LEGAL", "REPOSSESSION", "COOP_DECOMMISSION", "EXTERNAL_COLLECTION"]


def test_the_walkthrough_never_restates_a_decided_rule_as_open():
    """CF1 and OD-31 moved to DECIDED on 2026-09-09 (rulings 87-88). Naming either as
    open would re-open a ruled decision by prose."""
    case = {"customer_uid": "cu-1", "payment_status": "LATE", "broken_ptp_count": 0}
    blob = repr(sop.walkthrough(case, item={}))
    assert "CF1" not in blob and "OD-31" not in blob


# --- it does not guess ----------------------------------------------------------------

def test_an_undetermined_state_is_unplaced_with_candidates_and_never_step_one():
    """Contract §1a: a confident wrong value is graded ABOVE a visible blank. A wrong
    step number is that failure, so the module refuses rather than defaulting."""
    case = {"customer_uid": "cu-1", "payment_status": "NOT_INSTALLED",
            "broken_ptp_count": 0}
    out = sop.walkthrough(case, item={})
    assert out["placement"] == "UNPLACED"
    assert out["step"] is None
    assert _thai(out["reason_th"])
    assert out["candidates"]
    assert all(_thai(c["why_not_th"]) for c in out["candidates"])


def test_a_closed_account_is_off_journey_not_step_seventeen():
    case = {"customer_uid": "cu-1", "payment_status": "CLOSED", "broken_ptp_count": 0}
    out = sop.walkthrough(case, item={})
    assert out["placement"] == "OFF_JOURNEY"
    assert out["step"] is None


def test_a_pre_install_customer_with_no_pipeline_card_is_unplaced_not_step_one():
    out = sop.walkthrough({"customer_uid": "cu-x"}, pipeline_item=None, in_book=False)
    assert out["placement"] == "UNPLACED" and out["step"] is None


# --- the journey itself ---------------------------------------------------------------

def test_an_open_promise_places_step_eleven_and_a_broken_one_offers_renegotiate():
    base = {"customer_uid": "cu-1", "payment_status": "LATE", "broken_ptp_count": 0}
    assert sop.walkthrough(dict(base, open_ptp_uid="ptp-1"), item={})["step"] == 11

    broken = sop.walkthrough(dict(base, broken_ptp_count=1, renegotiation_count=0), item={})
    assert broken["step"] == 11
    assert broken["main_act"]["code"] == "RENEGOTIATE"


def test_a_third_promise_escalates_rather_than_renegotiating_again():
    """SOP §4 rule 6 and step 11's gate: renegotiate twice, the third escalates. The
    threshold is read from renegotiation_count — no invented number."""
    case = {"customer_uid": "cu-1", "payment_status": "LATE",
            "broken_ptp_count": 3, "renegotiation_count": 2}
    out = sop.walkthrough(case, item={})
    assert out["step"] == 11 and out["main_act"]["code"] == "ESCALATE"


def test_an_open_ticket_places_step_twelve_and_an_open_review_places_fourteen():
    base = {"customer_uid": "cu-1", "payment_status": "LATE", "broken_ptp_count": 0}
    assert sop.walkthrough(dict(base, open_issue_uid="iss-1"), item={})["step"] == 12

    rev = sop.walkthrough(dict(base, review_uid="rev-1"), item={})
    assert rev["step"] == 14
    assert rev["main_act"]["available"] is False
    assert _thai(rev["main_act"]["unavailable_reason_th"])


def test_the_four_credit_and_risk_branches_are_the_flowcharts_four():
    case = {"customer_uid": "cu-1", "payment_status": "LATE",
            "review_uid": "rev-1", "broken_ptp_count": 0}
    out = sop.walkthrough(case, item={})
    assert [b["code"] for b in out["branches"]] == [
        "CONTINUE", "ARRANGEMENT", "RESTRUCTURE", "NPL"]
    assert [b["leads_to_step"] for b in out["branches"]] == [10, 15, 15, 16]


def test_a_working_case_places_step_ten_and_offers_the_flowcharts_four_results():
    case = {"customer_uid": "cu-1", "payment_status": "LATE", "broken_ptp_count": 0}
    out = sop.walkthrough(case, item={"contact_lock": {"state": "OPEN"}})
    assert out["step"] == 10 and out["main_act"]["code"] == "LOG_CONTACT"
    assert [b["code"] for b in out["branches"]] == [
        "PTP", "SERVICE_ISSUE", "NO_CONTACT", "REFUSED"]
    assert [b["leads_to_step"] for b in out["branches"]] == [11, 12, 13, 14]


def test_a_spent_contact_slot_closes_the_counting_branches_and_leaves_no_contact_open():
    """The Act's daily slot: one counting contact per customer per day. Recording that
    nobody answered never spent a slot, so that branch stays available."""
    case = {"customer_uid": "cu-1", "payment_status": "LATE", "broken_ptp_count": 0}
    item = {"contact_lock": {"state": "LOCKED", "locked_by": "thip",
                             "locked_at_local_th": "09:14 น."}}
    out = sop.walkthrough(case, item=item)
    by_code = {b["code"]: b for b in out["branches"]}
    assert by_code["PTP"]["available"] is False
    assert by_code["REFUSED"]["available"] is False
    assert by_code["NO_CONTACT"]["available"] is True
    assert "thip" in by_code["PTP"]["unavailable_reason_th"]


def test_the_pre_install_card_walks_gates_release_deliver_and_outcome():
    item = {"uid": "pi-1", "gate_down_payment": {"state": "OPEN"},
            "gate_epc_confirmed": {"state": "OPEN"}, "history": [],
            "released_at": None, "delivery": None, "install_outcome": None}
    case = {"customer_uid": "cu-x"}

    def walk(**over):
        return sop.walkthrough(case, pipeline_item={**item, **over}, in_book=False)

    assert walk()["step"] == 1
    assert walk(gate_down_payment={"state": "PASSED"})["step"] == 2
    both = {"gate_down_payment": {"state": "PASSED"}, "gate_epc_confirmed": {"state": "PASSED"}}
    assert walk(**both)["step"] == 3
    released = walk(**both, released_at="2026-09-01")
    assert released["step"] == 3 and released["main_act"]["available"] is False
    assert walk(**both, released_at="2026-09-01", delivery={"channel": "LINE"})["step"] == 5

    postponed = walk(**both, released_at="2026-09-01", delivery={"channel": "LINE"},
                     install_outcome="POSTPONED")
    assert [b["code"] for b in postponed["branches"]] == [
        "STAND", "AMEND_DUE_DATE", "CANCEL_AND_REISSUE"]

    # Every pre-install step is one of the D26 eight.
    for over in ({}, {"gate_down_payment": {"state": "PASSED"}}, both):
        assert walk(**over)["operated_by"] == "TEAM"


# --- the wire -------------------------------------------------------------------------

def test_the_case_detail_serves_the_walkthrough(client):
    wb = client.get("/v1/workbook").json()
    uid = next(r["customer"]["uid"] for r in wb["rows"]
               if r["case"]["payment_status"] == "LATE")
    out = client.get("/v1/cases/by-customer/%s" % uid).json()
    assert "sop_step" in out
    assert out["sop_step"]["step_of"] == 17
    assert out["sop_step"]["placement"] in ("PLACED", "OFF_JOURNEY", "UNPLACED")


def test_every_case_in_the_book_gets_a_placement_and_never_a_guess(client):
    """The whole book through the endpoint. A step number appears if and only if the
    placement is PLACED; every other answer carries its reason in Thai."""
    wb = client.get("/v1/workbook").json()
    seen = set()
    for row in wb["rows"]:
        uid = row["customer"]["uid"]
        s = client.get("/v1/cases/by-customer/%s" % uid).json()["sop_step"]
        assert s["placement"] in ("PLACED", "OFF_JOURNEY", "UNPLACED"), uid
        if s["placement"] == "PLACED":
            assert isinstance(s["step"], int) and 1 <= s["step"] <= 17, uid
            assert _thai(s["name_th"]) and _thai(s["gate_rule_th"]), uid
            assert s["main_act"] is not None, uid
            seen.add(s["step"])
        else:
            assert s["step"] is None, uid
            assert _thai(s["reason_th"]), uid
    # Steps 7, 9 and 17 can never be a case's position.
    assert not seen & {7, 9, 17}


def test_the_walkthrough_is_absent_from_today_and_workbook_rows(client):
    """The guard on test_round4.py:775. That test asserts exactly seven keys differ
    between a normal and a CLOSED workbook row; adding sop_step to _work_item would
    make the septet an eight and fail it 400 lines away from this change."""
    wb = client.get("/v1/workbook").json()
    assert all("sop_step" not in r for r in wb["rows"])
    today = client.get("/v1/today").json()
    assert all("sop_step" not in i for i in today["items"])


def test_the_module_mints_no_control_that_does_not_already_exist(client):
    """'Stating a step is not operating a gate', mechanised. Every route named by a
    main act or a branch, over the whole book, must resolve against a real path — the
    module points at controls, it never invents one."""
    real = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        if path:
            real.add(re.sub(r"\{[^}]+\}", "{}", path))

    wb = client.get("/v1/workbook").json()
    checked = 0
    for row in wb["rows"][:40]:
        uid = row["customer"]["uid"]
        s = client.get("/v1/cases/by-customer/%s" % uid).json()["sop_step"]
        acts = ([s["main_act"]] if s.get("main_act") else []) + (s.get("branches") or [])
        for a in acts:
            control = a.get("control")
            if not control:
                continue
            path = control.split()[1].split(" (")[0]
            assert re.sub(r"\{[^}]+\}", "{}", path) in real, control
            checked += 1
    assert checked > 0


def test_the_steps_endpoint_serves_all_seventeen_with_lanes_and_ownership(client):
    """The catalogue the pipeline, the review queue and recovery read. It exists so
    seventeen Thai strings of rank-2 workflow content live on the wire in ONE place
    rather than being retyped into three screens, where they would drift the first
    time the SOP is amended."""
    out = client.get("/v1/sop/steps").json()
    assert out["meta"]["total"] == 17
    assert [s["step"] for s in out["steps"]] == list(range(1, 18))
    for s in out["steps"]:
        assert _thai(s["name_th"]) and _thai(s["lane_th"])
        assert s["operated_by"] in ("TEAM", "SYSTEM")
    # The D26 eight are the team's, and the catalogue names the decision that holds them.
    team = [s["step"] for s in out["steps"] if s["operated_by"] == "TEAM"]
    assert team == [1, 2, 3, 4, 5, 6, 7, 8]
    assert out["meta"]["open_decision"]["code"] == "D26"


def test_the_steps_endpoint_keeps_the_three_unplaceable_steps_visible(client):
    """An officer who could see only fourteen of seventeen would reasonably think the
    other three were missing. They are served, marked, and carry their reason."""
    out = client.get("/v1/sop/steps").json()
    unplaceable = [s for s in out["steps"] if not s["placeable"]]
    assert [s["step"] for s in unplaceable] == [7, 9, 17]
    assert all(_thai(s["not_placeable_th"]) for s in unplaceable)
