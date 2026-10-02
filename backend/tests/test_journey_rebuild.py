"""The 2026-08-30 rebuild — journey invariants.

Covers: R11 tier order · entity routing on every new payload · PTP lifecycle and
the broken-PTP review · ladder gates (skip, missed-count, role, deed) · restructure
supersession moving the ENGINE's own DPD · manager review · S09 billing law ·
S12 lot gates · board persistence · ladder_mode · service/NPL isolation.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.entities import assert_entity_present
from app.main import app
from app.money.band_sets import assert_band_pair_present


# Opening a recovery is MANAGER+ (fix-all Leg R).
MANAGER = {"X-Volt-Role": "MANAGER"}


@pytest.fixture()
def client():
    return TestClient(app)


# --- R11: the working list --------------------------------------------------------

def test_the_working_list_orders_by_the_four_tiers(client):
    body = client.get("/v1/working-list").json()
    items = body["items"]
    # Tier 1: the PTP-due-today customer leads regardless of arrears size.
    assert items[0]["priority_reason"] == "PTP_DUE_TODAY"
    assert items[0]["customer"]["customer_no"] == "C-000912"
    # Within the rest, arrears descend (the R11 second tier).
    rest = [Decimal(i["aggregate_overdue"]) for i in items[1:]]
    assert rest == sorted(rest, reverse=True)
    # next_up names an unlocked customer with arrears, for the guided queue (R10).
    assert body["meta"]["next_up"] == items[0]["customer"]["uid"]


def test_every_working_item_explains_its_priority(client):
    for item in client.get("/v1/working-list").json()["items"]:
        assert item["priority_reason"] in (
            "PTP_DUE_TODAY", "DEEPEST_LADDER", "BROKEN_PTP", "LARGEST_ARREARS")


def test_the_working_list_refuses_an_unknown_bucket(client):
    response = client.get("/v1/working-list", params={"bucket": "EVERYTHING"})
    assert response.status_code == 422
    assert response.json()["code"] == "working_list_bucket_unknown"


def test_new_payloads_carry_entity_with_company_id_and_band_pairs(client):
    for path in ("/v1/working-list", "/v1/cases", "/v1/cash-cases",
                 "/v1/service-billing", "/v1/ar/pipeline", "/v1/intercompany/docs",
                 "/v1/recovery-cases", "/v1/repossession-lots"):
        payload = client.get(path).json()
        assert_entity_present(payload)
        assert_band_pair_present(payload)


def test_link_fields_never_replace_the_masked_display(client):
    """R12, hiding moved to the server (2026-09-20) — the displayed number stays
    masked, the full one never rides a list response, and `phone_revealable` is the
    honest answer to "is there anything to reveal" (the audited phone:reveal route
    is the only door that answers it)."""
    for item in client.get("/v1/working-list").json()["items"]:
        assert "x" in item["customer"]["phone_masked"]
        assert "phone_e164" not in item["customer"]
        if item["customer"]["phone_on_file"] is False:
            assert item["customer"]["phone_revealable"] is False


def test_service_arrears_never_reach_the_lease_aggregate(client):
    """Deck S09 — the two-entity showcase: C-002036's lease is current while a
    month-38 service invoice is overdue. The lease aggregate must stay clean."""
    items = client.get("/v1/working-list").json()["items"]
    item = next(i for i in items if i["customer"]["customer_no"] == "C-002036")
    assert Decimal(item["aggregate_overdue"]) == Decimal("0.00")
    assert item["service_billing"]["dunning_stage"] == "SVC_OVERDUE"
    assert item["service_billing"]["entity"] == "EPC"
    assert item["entity"] == "SPV"  # the lease itself is SPV's


# --- PTPs -------------------------------------------------------------------------

def test_a_customer_holds_at_most_one_open_promise(client):
    items = client.get("/v1/working-list").json()["items"]
    target = next(i for i in items if i["open_ptp"] is None
                  and Decimal(i["aggregate_overdue"]) > 0)
    uid = target["customer"]["uid"]
    first = client.post("/v1/ptps", json={
        "customer_uid": uid, "promised_amount": "5000", "promise_date": "2026-10-30"})
    assert first.status_code == 201
    second = client.post("/v1/ptps", json={
        "customer_uid": uid, "promised_amount": "6000", "promise_date": "2026-10-31"})
    assert second.status_code == 409
    assert second.json()["code"] == "ptp_already_open"


def test_a_broken_promise_opens_a_manager_review(client):
    items = client.get("/v1/working-list").json()["items"]
    ptp_uid = next(i["open_ptp"]["uid"] for i in items if i["open_ptp"])
    response = client.post("/v1/ptps/%s:close" % ptp_uid, json={"outcome": "BROKEN"})
    assert response.status_code == 200
    review_uid = response.json()["manager_review_uid"]
    assert review_uid
    reviews = client.get("/v1/manager-review").json()["reviews"]
    match = next(r for r in reviews if r["uid"] == review_uid)
    assert match["reason"] == "BROKEN_PTP"
    assert match["status"] == "OPEN"


def test_a_promise_cannot_be_dated_before_today(client):
    items = client.get("/v1/working-list").json()["items"]
    target = next(i for i in items if i["open_ptp"] is None)
    response = client.post("/v1/ptps", json={
        "customer_uid": target["customer"]["uid"],
        "promised_amount": "1000", "promise_date": "2026-10-01"})
    assert response.status_code == 422
    assert response.json()["code"] == "ptp_date_in_past"


# --- the lease ladder -------------------------------------------------------------

def _case_by_customer(client, customer_no):
    cases = client.get("/v1/cases").json()["cases"]
    for case in cases:
        item = client.get("/v1/cases/%s" % case["uid"]).json()
        found = item
        customer = found["customer_uid"]
        from app import main
        if main.BY_CUSTOMER[customer].customer_no == customer_no:
            return item
    raise AssertionError("no case for %s" % customer_no)


def test_a_rung_cannot_be_skipped_without_an_owner_reason(client):
    case = _case_by_customer(client, "C-002031")   # stands at NOTICE_30
    response = client.post("/v1/cases/%s:advance" % case["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OFFICER"})
    assert response.status_code == 422
    assert response.json()["code"] == "ladder_stage_skip"


def test_declaring_npl_is_role_gated(client):
    case = _case_by_customer(client, "C-002032")   # at RESTRUCTURE_OFFER_60
    refused = client.post("/v1/cases/%s:advance" % case["uid"],
                          json={"to_stage": "NPL_DECLARED_90", "role": "OFFICER"})
    assert refused.status_code == 422
    assert refused.json()["code"] == "authority_gap_blocks_approval"
    allowed = client.post("/v1/cases/%s:advance" % case["uid"],
                          json={"to_stage": "NPL_DECLARED_90", "role": "OWNER",
                                "by": "Owner"})
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["stage"] == "NPL_DECLARED_90"
    assert body["extensions"]["pending_decision"] == "OD-04"


def test_assignment_requires_a_declared_npl_and_executes_the_deed_once(client):
    case = _case_by_customer(client, "C-002031")
    # NOTICE_30 → RESTRUCTURE_OFFER_60 (2 missed exist) → try to assign: refused.
    client.post("/v1/cases/%s:advance" % case["uid"],
                json={"to_stage": "RESTRUCTURE_OFFER_60", "by": "ploy"})
    refused = client.post("/v1/cases/%s:advance" % case["uid"],
                          json={"to_stage": "ASSIGNED_120", "role": "OWNER",
                                "note": "skip"})
    assert refused.json()["code"] == "assignment_before_npl"


def test_the_executed_deed_pays_100_percent_and_cancels_service(client):
    """C-002034 seeded post-deed: buyback at 100%, service CANCELLED, EPC owns."""
    case = _case_by_customer(client, "C-002034")
    assert case["stage"] == "ASSIGNED_120"
    assert case["post_assignment_owner"] == "EPC"
    npl = case["npl"]
    assert npl["assignment"]["npv_basis"].startswith("100%")
    docs = client.get("/v1/intercompany/docs").json()["documents"]
    kinds = {d["doc_type"] for d in docs}
    assert {"ASSIGNMENT_DEED", "NPL_BUYBACK_PAYMENT"} <= kinds
    billing = client.get("/v1/service-billing").json()["accounts"]
    account = next(a for a in billing if a["contract_uid"] == "K-2034-1")
    assert account["status"] == "CANCELLED"
    assert account["cancelled_reason"] == "ASSIGNED_TO_EPC"


def test_manual_ladder_mode_suppresses_the_indicative_rung(client):
    put = client.put("/v1/ladder-mode", json={"ladder_mode": "MANUAL"})
    assert put.status_code == 200
    for item in client.get("/v1/working-list").json()["items"]:
        assert item["ladder"]["indicative"] is None
        assert item["ladder"]["mode"] == "MANUAL"


# --- restructure (S08) ------------------------------------------------------------

def test_an_approved_restructure_moves_the_engines_own_dpd(client):
    """The supersession law: approving the addendum changes what compute_dpd sees,
    with zero engine edits."""
    case = _case_by_customer(client, "C-002032")
    before = case["days_past_due"]
    assert before and before >= 60
    rst_uid = case["restructure"]["uid"]
    approved = client.post("/v1/restructures/%s:approve" % rst_uid,
                           json={"role": "OWNER", "by": "Owner"})
    assert approved.status_code == 200
    after = _case_by_customer(client, "C-002032")
    assert after["days_past_due"] == 0
    assert after["restructure"]["status"] == "ACTIVE"


def test_no_second_restructure_ever(client):
    case = _case_by_customer(client, "C-002035")   # already restructured
    response = client.post("/v1/cases/%s/restructures" % case["uid"], json={})
    assert response.status_code == 422
    assert response.json()["code"] == "second_restructure_forbidden"


def test_two_missed_on_the_new_schedule_locks_to_npl(client):
    case = _case_by_customer(client, "C-002035")
    rst_uid = case["restructure"]["uid"]
    client.post("/v1/restructures/%s:record-miss" % rst_uid)
    second = client.post("/v1/restructures/%s:record-miss" % rst_uid)
    body = second.json()
    assert body["restructure"]["status"] == "FAILED_TO_NPL"
    assert body["manager_review_uid"]


# --- manager review ---------------------------------------------------------------

def test_cash_reviews_do_not_offer_restructure(client):
    """The 12-scenario matrix, visible: a cash account's remedies are S11's."""
    from app import main
    cash_customer = next(c for c in main.CUSTOMERS if c.customer_no == "C-001120")
    assert cash_customer.contracts[0].product == "CASH"
    reviews = client.get("/v1/manager-review").json()["reviews"]
    row = next(r for r in reviews if r["customer"]["customer_no"] == "C-001120")
    assert "RESTRUCTURE" not in row["available_decisions"]
    assert "CONFIRM_NPL" not in row["available_decisions"]


def test_deciding_a_review_twice_is_refused(client):
    reviews = client.get("/v1/manager-review").json()["reviews"]
    open_review = next(r for r in reviews if r["status"] == "OPEN"
                       and "CONTINUE_FOLLOWUP" in r["available_decisions"])
    first = client.post("/v1/manager-review/%s:decide" % open_review["uid"],
                        json={"decision": "CONTINUE_FOLLOWUP", "role": "OWNER"})
    assert first.status_code == 200
    second = client.post("/v1/manager-review/%s:decide" % open_review["uid"],
                         json={"decision": "CONFIRM_NPL", "role": "OWNER"})
    assert second.status_code == 409
    assert second.json()["code"] == "review_already_decided"


# --- S09 service billing ----------------------------------------------------------

def test_the_billing_window_law_refuses_on_the_23rd(client):
    response = client.post("/v1/contracts/K-2036-1/service-billing:bill")
    assert response.status_code == 422
    assert response.json()["code"] == "billing_window_closed"


def test_the_prepaid_window_refuses_billing(client):
    response = client.post("/v1/contracts/K-2001-1/service-billing:bill")
    assert response.status_code == 422
    assert response.json()["code"] == "service_before_month_37"


def test_a_decline_request_is_recorded_and_changes_nothing(client):
    response = client.post("/v1/contracts/K-2036-1/service-billing:decline",
                           json={"by": "customer"})
    assert response.status_code == 202
    body = response.json()
    assert body["billing_continues"] is True
    assert body["pending_decision"] == "SVC-37"


def test_the_50000_fee_refuses_to_post(client):
    response = client.post("/v1/intercompany/docs",
                           json={"doc_type": "ACCOUNTING_FEE_50000"})
    assert response.status_code == 422
    assert response.json()["code"] == "manual_outside_erp"


# --- S12 repossession lots --------------------------------------------------------

def test_the_lot_walks_count_grade_price_sell_in_order(client):
    npl_cases = client.get("/v1/npl-cases").json()["npl_cases"]
    npl = next(n for n in npl_cases if not n.get("recovery_uid"))
    rec = client.post("/v1/npl-cases/%s/recovery" % npl["uid"],
                      json={"strategy": "REPOSSESSION"}, headers=MANAGER).json()
    lot = rec["lot"]
    # Grade before count: refused.
    graded = client.post("/v1/repossession-lots/%s:grade" % lot["uid"],
                         json={"grades": {"A": 10}})
    assert graded.status_code == 409
    # A variance needs a reason.
    counted = client.post("/v1/repossession-lots/%s:count" % lot["uid"],
                          json={"actual_count": 9})
    assert counted.status_code == 422
    counted = client.post("/v1/repossession-lots/%s:count" % lot["uid"],
                          json={"actual_count": 9, "variance_note": "one panel missing, photo attached"})
    assert counted.status_code == 200
    # Grades must cover exactly the counted units.
    mismatch = client.post("/v1/repossession-lots/%s:grade" % lot["uid"],
                           json={"grades": {"A": 5, "B": 5}})
    assert mismatch.status_code == 422
    assert mismatch.json()["code"] == "grade_count_mismatch"
    client.post("/v1/repossession-lots/%s:grade" % lot["uid"],
                json={"grades": {"A": 5, "B": 3, "C": 1}})
    # Only Dan prices; selling unpriced is blocked.
    not_dan = client.post("/v1/repossession-lots/%s:price" % lot["uid"],
                          json={"by": "Nok", "resale_price": "50000"})
    # AUTHORISED TEST EDIT 30 (Arina, 2026-09-14): pricing is a role (OPS or OWNER), refused 403. Two lines in this function.
    assert not_dan.status_code == 403
    blocked = client.post("/v1/repossession-lots/%s:sell" % lot["uid"])
    assert blocked.json()["code"] == "resale_price_unset"
    client.post("/v1/repossession-lots/%s:price" % lot["uid"],
                json={"by": "Dan", "resale_price": "50000"}, headers={"X-Volt-Role": "OPS"})
    sold = client.post("/v1/repossession-lots/%s:sell" % lot["uid"])
    assert sold.status_code == 200
    # The sale amount lands on the recovery case as a recovery entry.
    cases = client.get("/v1/recovery-cases").json()["recovery_cases"]
    parent = next(r for r in cases if r["uid"] == lot["recovery_uid"])
    assert Decimal(parent["recovered_total"]) >= Decimal("50000")


def test_write_off_needs_the_owner(client):
    cases = client.get("/v1/recovery-cases").json()["recovery_cases"]
    rec = cases[0]
    refused = client.post("/v1/recovery-cases/%s:resolve" % rec["uid"],
                          json={"outcome": "CLOSED_WRITE_OFF", "role": "OFFICER"})
    assert refused.status_code == 422
    assert refused.json()["code"] == "authority_gap_blocks_approval"


# --- board persistence + contacts -------------------------------------------------

def test_board_moves_persist_into_the_today_list(client):
    items = client.get("/v1/today-list").json()["items"]
    # col_01H90 is Escalate, the most severe column, so the move stays FORWARD and
    # still applies — but only from a card that is not already standing there.
    target = next(i for i in items if i["board_column_id"] != "col_01H90")
    move = client.post("/v1/board/moves", json={
        "customer_uid": target["customer"]["uid"], "to_column_id": "col_01H90",
        "reason": "ทดสอบการย้ายไปคอลัมน์ส่งต่อผู้จัดการ"})
    assert move.status_code == 201
    after = client.get("/v1/today-list").json()["items"]
    moved = next(i for i in after if i["customer"]["uid"] == target["customer"]["uid"])
    assert moved["board_column_id"] == "col_01H90"


def test_a_leftward_recovery_move_needs_a_reason(client):
    from app import main
    customer = next(c for c in main.CUSTOMERS if c.recovery_stage == "ESCALATE")
    refused = client.post("/v1/recovery-board/moves", json={
        "customer_uid": customer.uid, "to_stage": "CONTACT"})
    assert refused.status_code == 422
    allowed = client.post("/v1/recovery-board/moves", json={
        "customer_uid": customer.uid, "to_stage": "CONTACT",
        "reason": "dispute resolved, restart contact"})
    assert allowed.status_code == 201
    assert allowed.json()["reversal"] is True
    board = client.get("/v1/recovery-board").json()["columns"]
    contact = next(c for c in board if c["stage"] == "CONTACT")
    assert any(card["customer_uid"] == customer.uid for card in contact["cards"])


def test_a_recovery_board_card_serves_its_balance_band_words_and_payment_status(client):
    """fix-all Leg R: the card's balance line ("คงเหลือ"), the band's own words and the
    case's payment-status pill, beside the arrears the column still totals."""
    from app import cases, main
    from app.money import band_sets
    case_of = cases.for_current().cases
    columns = client.get("/v1/recovery-board").json()["columns"]
    cards = [card for column in columns for card in column["cards"]]
    assert cards
    for column in columns:
        assert Decimal(column["column_total"]) == sum((Decimal(c["arrears"]) for c in column["cards"]), Decimal("0"))
    for card in cards:
        _arrears, _oldest, band, outstanding = main._customer_aggregate(main.BY_CUSTOMER[card["customer_uid"]])
        assert card["aggregate_outstanding"] == str(outstanding)
        assert card["aging_bucket_label_th"] == band_sets.label_for(band.band_set_code, band.code)
        assert card["aging_bucket_label_en"] == band_sets.label_for(band.band_set_code, band.code, "en")
        assert card["payment_status"] == case_of[card["customer_uid"]]["payment_status"]
    assert all(c["aging_bucket_label_th"] for c in cards)


def test_refusing_to_pay_counts_and_opens_a_review(client):
    from app import main
    customer = main.CUSTOMERS[5]   # C-001188, no lock yet
    response = client.post("/v1/contacts", json={
        "customer_uid": customer.uid, "channel": "PHONE", "direction": "OUTBOUND",
        "disposition": "REFUSED_PAY", "at": "2026-10-23T10:00:00+07:00",
        "officer": "ploy"})
    assert response.status_code == 201
    body = response.json()
    assert body["counted"] is True
    assert body["raises_flag"] is True
    assert body["manager_review_uid"]
    reviews = client.get("/v1/manager-review").json()["reviews"]
    assert any(r["uid"] == body["manager_review_uid"] and r["reason"] == "REFUSE_TO_PAY"
               for r in reviews)


# --- final v2: the chosen path's next steps (prototype 673-684) ---------------------

def test_a_recovery_case_serves_the_sops_own_next_step_for_its_strategy(client):
    """The design lists a chosen path's next steps. Delta-100 REC-14: the SOP draws
    one step past the fork; for REPOSSESSION the S12 lot flow supplies two more (the
    count gate and the resale). Every label/note is vocabulary the system already
    serves — nothing is invented."""
    npl = next(n for n in client.get("/v1/npl-cases").json()["npl_cases"] if not n.get("recovery_uid"))
    opened = client.post("/v1/npl-cases/%s/recovery" % npl["uid"], json={"strategy": "REPOSSESSION"}, headers=MANAGER).json()
    steps = opened["recovery"]["next_steps"]
    assert len(steps) == 3
    step = steps[0]
    assert step["label_th"] == "ยึดคืนอุปกรณ์" and step["label_en"] == "Repossession / recovery"
    assert step["leads_to_step"] == 16 and step["available"] is True
    assert step["note_th"] and step["note_en"]
    assert [s["label_th"] for s in steps[1:]] == ["ตรวจนับอุปกรณ์ให้ตรง", "ขายต่อตามราคาล็อต"]
    for extra in steps[1:]:
        assert extra["note_th"] and extra["note_en"]
        assert extra["leads_to_step"] == 16 and extra["available"] is True
        assert extra["control"]
    # The list route serves the same step, so the chosen card renders it after a reload.
    listed = next(r for r in client.get("/v1/recovery-cases").json()["recovery_cases"]
                  if r["uid"] == opened["recovery"]["uid"])
    assert listed["next_steps"] == steps
    # Every strategy the API accepts has a served step; the refused path keeps its refusal.
    from app import journey as journey_domain
    from app import sop
    assert set(sop.RECOVERY_NEXT_STEPS) == set(journey_domain.RECOVERY_STRATEGIES)
    external = sop.RECOVERY_NEXT_STEPS["EXTERNAL_COLLECTION"]
    assert len(external) == 1 and external[0]["available"] is False
    assert "ยังไม่ชี้ขาด" in external[0]["note_th"] and external[0]["note_en"]


def test_a_one_step_strategy_documents_why_it_serves_one(client):
    """Delta-100 REC-14: where the SOP supports one step, one is served AND the
    payload says why — never a silently short list."""
    npl = next(n for n in client.get("/v1/npl-cases").json()["npl_cases"] if not n.get("recovery_uid"))
    opened = client.post("/v1/npl-cases/%s/recovery" % npl["uid"], json={"strategy": "LEGAL"}, headers=MANAGER).json()["recovery"]
    assert len(opened["next_steps"]) == 1
    assert opened["next_steps_note_th"] and opened["next_steps_note_en"]
    assert "หนึ่งขั้น" in opened["next_steps_note_th"]


# --- Delta-100 REC-6/7/9/11/16: the row's NPV, rate, status chip and risk edge ------

def test_a_recovery_row_serves_npv_rate_status_and_risk(client):
    npl = next(n for n in client.get("/v1/npl-cases").json()["npl_cases"] if not n.get("recovery_uid"))
    opened = client.post("/v1/npl-cases/%s/recovery" % npl["uid"], json={"strategy": "REPOSSESSION"}, headers=MANAGER).json()["recovery"]
    assert opened["remaining_npv"] is not None
    assert opened["rate_pct"] == "38"
    assert opened["rate_is_assumption"] is True
    assert "สมมติฐาน" in opened["rate_basis_th"] and "not a ruling" in opened["rate_basis_en"]
    # The server owns the multiplication — the figure is exact, not recomputed here.
    from decimal import Decimal
    expected = (Decimal(opened["remaining_npv"]) * Decimal("38") / Decimal("100")).quantize(Decimal("0.01"))
    assert Decimal(opened["expected_recovery"]) == expected
    assert opened["status_label_th"] and opened["status_label_en"]
    assert isinstance(opened["risk_score"], int) and 0 <= opened["risk_score"] <= 100
    # The lot's own state drives the chip: opened PLANNED, counted after the act.
    assert opened["status_label_th"] == "รอถอดระบบ"
    recovery_uid = opened["uid"]
    lot = next(l for l in client.get("/v1/repossession-lots").json()["lots"]
               if l["recovery_uid"] == recovery_uid)
    counted = client.post("/v1/repossession-lots/%s:count" % lot["uid"],
                          json={"actual_count": lot["expected_count"]})
    assert counted.status_code == 200
    listed = next(r for r in client.get("/v1/recovery-cases").json()["recovery_cases"]
                  if r["uid"] == recovery_uid)
    assert listed["status_label_th"] == "ตรวจนับแล้ว รอเกรด"


def test_an_npl_row_serves_the_path_cards_estimates_and_risk(client):
    """Before a path is chosen the cards show the declared rate and this case's own
    estimate; the refused path carries no number, only its open decision."""
    from decimal import Decimal
    rows = client.get("/v1/npl-cases").json()["npl_cases"]
    row = next(r for r in rows if r.get("recovery_paths"))
    assert row["remaining_npv"] is not None
    assert isinstance(row["risk_score"], int) and 0 <= row["risk_score"] <= 100
    assert row["status_label_th"] and row["status_label_en"]
    paths = {p["strategy"]: p for p in row["recovery_paths"]["paths"]}
    assert set(paths) == {"LEGAL", "REPOSSESSION", "COOP_DECOMMISSION", "EXTERNAL_COLLECTION"}
    for code in ("LEGAL", "REPOSSESSION", "COOP_DECOMMISSION"):
        assert paths[code]["rate_pct"] == "38"
        expected = (Decimal(row["remaining_npv"]) * Decimal("38") / Decimal("100")).quantize(Decimal("0.01"))
        assert Decimal(paths[code]["expected_recovery"]) == expected
    refused = paths["EXTERNAL_COLLECTION"]
    assert refused["rate_pct"] is None and refused["expected_recovery"] is None
    assert refused["available"] is False and refused["pending_decision"] == "D27"
