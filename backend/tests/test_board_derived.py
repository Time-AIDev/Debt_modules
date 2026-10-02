"""The board column is derived from the case, not placed by an officer.

Spec: docs/archive/superpowers/specs/2026-09-09-board-derived-columns-design.md
"""
from datetime import date, timedelta

import pytest

from app import board


BD = date(2026, 9, 9)


def _derive(**over):
    """Every input at its benign value, so each test names only what it changes.
    Benign = no NPL, no promise, nothing overdue -> Awaiting payment."""
    args = {"npl_confirmed": False, "npl_type": None, "recovery_stage": None,
            "dc_status": None, "open_ptp_promise_date": None, "dpd": 0,
            "business_date": BD}
    args.update(over)
    return board.derive(**args)


# --- the four branches ------------------------------------------------------------

def test_nothing_overdue_is_awaiting_payment():
    assert _derive() == board.AWAITING_PAYMENT


def test_an_overdue_instalment_is_call_today():
    assert _derive(dpd=1) == board.CALL_TODAY


def test_a_live_promise_is_promise_made():
    assert _derive(dpd=30, open_ptp_promise_date=date(2026, 9, 30)) == board.PROMISE_MADE


def test_a_confirmed_npl_is_escalate():
    assert _derive(npl_confirmed=True) == board.ESCALATE


@pytest.mark.parametrize("field,value", [
    ("npl_type", "NPL_1_RESTRUCTURE"),
    ("recovery_stage", "ESCALATE"),
    ("recovery_stage", "RECOVERY"),
    ("dc_status", "RETRIEVE_ASSET"),
])
def test_each_escalate_clause_stands_alone(field, value):
    assert _derive(**{field: value}) == board.ESCALATE


def test_escalate_outranks_a_live_promise():
    """A confirmed NPL is not softened by a promise — clause order is the rule."""
    assert _derive(npl_confirmed=True,
                   open_ptp_promise_date=date(2026, 9, 30)) == board.ESCALATE


# --- the promise date, on all three sides ------------------------------------------

def test_a_promise_due_tomorrow_still_holds_the_card():
    assert _derive(dpd=30, open_ptp_promise_date=date(2026, 9, 10)) == board.PROMISE_MADE


def test_a_promise_due_today_still_holds_the_card():
    """The promised day has not ended. The customer has until close of business."""
    assert _derive(dpd=30, open_ptp_promise_date=BD) == board.PROMISE_MADE


def test_a_promise_due_yesterday_releases_the_card():
    """This is the automatic move. No job ran; the clock moved."""
    assert _derive(dpd=30, open_ptp_promise_date=date(2026, 9, 8)) == board.CALL_TODAY


# --- the instalment due date, crossing zero in both directions ---------------------

def test_dpd_crossing_above_zero_moves_the_card_to_call_today():
    assert _derive(dpd=0) == board.AWAITING_PAYMENT
    assert _derive(dpd=1) == board.CALL_TODAY


def test_dpd_returning_to_zero_moves_the_card_back():
    assert _derive(dpd=45) == board.CALL_TODAY
    assert _derive(dpd=0) == board.AWAITING_PAYMENT


def test_an_unknown_dpd_is_not_treated_as_overdue():
    """A contract the money engine could not price must not be called on a guess."""
    assert _derive(dpd=None) == board.AWAITING_PAYMENT


# --- severity, which is deliberately not the column's display order ---------------

def test_severity_ranks_all_four_columns_distinctly():
    assert sorted(board.SEVERITY.values()) == [0, 1, 2, 3]
    assert set(board.SEVERITY) == set(board.DERIVED_COLUMNS)


def test_awaiting_payment_is_the_healthiest_and_escalate_the_worst():
    assert board.SEVERITY[board.AWAITING_PAYMENT] == 0
    assert board.SEVERITY[board.ESCALATE] == 3


def test_call_today_outranks_promise_made():
    """Both are overdue; the one with no promise on the record is worse."""
    assert board.SEVERITY[board.CALL_TODAY] > board.SEVERITY[board.PROMISE_MADE]


# --- direction, every ordered pair -------------------------------------------------

@pytest.mark.parametrize("requested,current,expected", [
    (board.PROMISE_MADE, board.AWAITING_PAYMENT, "FORWARD"),
    (board.CALL_TODAY, board.AWAITING_PAYMENT, "FORWARD"),
    (board.ESCALATE, board.AWAITING_PAYMENT, "FORWARD"),
    (board.CALL_TODAY, board.PROMISE_MADE, "FORWARD"),
    (board.ESCALATE, board.PROMISE_MADE, "FORWARD"),
    (board.ESCALATE, board.CALL_TODAY, "FORWARD"),
    (board.AWAITING_PAYMENT, board.PROMISE_MADE, "BACKWARD"),
    (board.AWAITING_PAYMENT, board.CALL_TODAY, "BACKWARD"),
    (board.AWAITING_PAYMENT, board.ESCALATE, "BACKWARD"),
    (board.PROMISE_MADE, board.CALL_TODAY, "BACKWARD"),
    (board.PROMISE_MADE, board.ESCALATE, "BACKWARD"),
    (board.CALL_TODAY, board.ESCALATE, "BACKWARD"),
])
def test_every_ordered_pair_of_columns_has_a_direction(requested, current, expected):
    assert board.direction_of(requested, current) == expected


def test_claiming_a_promise_with_no_ptp_on_record_is_backward():
    """The named gaming move: Call today -> Promise made makes the desk look better."""
    assert board.direction_of(board.PROMISE_MADE, board.CALL_TODAY) == "BACKWARD"


def test_a_broken_promise_being_worked_today_is_forward():
    assert board.direction_of(board.CALL_TODAY, board.PROMISE_MADE) == "FORWARD"


def test_a_move_to_the_column_the_card_is_already_in_is_refused():
    with pytest.raises(board.BoardError) as exc:
        board.direction_of(board.CALL_TODAY, board.CALL_TODAY)
    assert exc.value.code == "board_move_same_column"


def test_a_column_outside_the_derived_four_is_always_backward():
    """An Owner may add a column. It has no rank, so a Manager signs for it."""
    assert board.direction_of("col_OWNERADDED", board.CALL_TODAY) == "BACKWARD"
    assert board.direction_of(board.CALL_TODAY, "col_OWNERADDED") == "BACKWARD"


# --- the cause written onto an automatic move --------------------------------------

def test_a_lapsed_promise_names_itself_as_the_cause():
    assert board.cause_of(board.PROMISE_MADE, board.CALL_TODAY,
                          open_ptp_promise_date=date(2026, 9, 8),
                          business_date=BD) == "PTP_DATE_PASSED"


def test_arrears_opening_and_clearing_each_name_themselves():
    assert board.cause_of(board.AWAITING_PAYMENT, board.CALL_TODAY,
                          open_ptp_promise_date=None,
                          business_date=BD) == "ARREARS_OPENED"
    assert board.cause_of(board.CALL_TODAY, board.AWAITING_PAYMENT,
                          open_ptp_promise_date=None,
                          business_date=BD) == "ARREARS_CLEARED"


def test_anything_else_is_reported_honestly_as_a_case_change():
    assert board.cause_of(board.CALL_TODAY, board.ESCALATE,
                          open_ptp_promise_date=None,
                          business_date=BD) == "CASE_CHANGED"


# ---------------------------------------------------------------------------------
# Served behaviour. From here the tests go through the API, because the point of the
# rule is what an officer sees.
# ---------------------------------------------------------------------------------
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    # The client and the tests' own `for_current()` reads look at the SAME session:
    # the middleware keys every store — cases, journey AND config (`_SettingsProxy`,
    # config.py:274) — on the volt_session cookie, and the test process sits in the
    # shared one. Without the pin, TestClient keeps the cookie the middleware sets on
    # the first response, and an assertion about a record the API just wrote would be
    # reading a different, untouched session. The idiom is `test_round2.py:30`.
    c = TestClient(app)
    c.cookies.set("volt_session", "shared")
    return c


def _items(client):
    response = client.get("/v1/today-list")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_every_served_column_is_one_of_the_derived_four(client):
    items = _items(client)
    assert items, "the today list is empty; the fixture did not seed"
    for item in items:
        assert item["board_column_id"] in board.DERIVED_COLUMNS, item["customer"]["customer_no"]


def test_the_two_serving_endpoints_agree_on_every_customer(client):
    """`main.py:710` and `routers/journey.py:233` served this field from two different
    expressions. They are one call now, and this is what stops them drifting apart the
    way `recovery_stage` already has (spec §9c)."""
    listed = {i["customer"]["uid"]: i["board_column_id"] for i in _items(client)}
    working = client.get("/v1/working-list")
    assert working.status_code == 200, working.text
    rows = working.json()["items"]
    assert rows, "the working list is empty; the fixture did not seed"
    overlap = 0
    for row in rows:
        uid = row["customer"]["uid"]
        if uid not in listed:
            continue
        overlap += 1
        assert row["board_column_id"] == listed[uid], uid
    assert overlap, "the two endpoints share no customer; the comparison proved nothing"


def test_the_board_overlay_is_gone(client):
    """The unguarded placement store this spec replaces. If it comes back, the
    override record and it will disagree and one of them will be a silent liar."""
    from app import journey
    assert not hasattr(journey.for_current(), "board_overlay")


def test_the_stored_column_is_gone_from_the_fixture():
    from app import fixtures
    assert not hasattr(fixtures.CustomerFixture, "board_column_id")
    assert not hasattr(fixtures, "_derive_board_column")
    assert not hasattr(fixtures, "_seed_board_columns")


def test_switching_band_set_reshuffles_no_cards(client):
    """Spec §9f reason 3, the one objection to request-time derivation that was a real
    constraint rather than a design choice. The rule reads contract status, never
    aging_bucket, so this must be a no-op for the board."""
    from app.config import settings

    before = {i["customer"]["uid"]: i["board_column_id"] for i in _items(client)}
    # `config.Settings` is session state that `conftest` does NOT reset (it resets the
    # six sibling stores, not this one), and this client shares the tester's session,
    # so the band set has to be put back or every test after this one runs against
    # LEGACY_LDR — through the same endpoint, so the switch is undone the way it was made.
    saved = settings.band_set_code
    try:
        response = client.put("/v1/config", json={"band_set_code": "LEGACY_LDR"},
                              headers={"X-Volt-Role": "OWNER"})
        assert response.status_code in (200, 204), response.text
        after = {i["customer"]["uid"]: i["board_column_id"] for i in _items(client)}
        assert after == before
    finally:
        client.put("/v1/config", json={"band_set_code": saved},
                   headers={"X-Volt-Role": "OWNER"})


def test_an_open_review_does_not_move_the_card(client):
    """Spec §9g. manager_review_open is excluded by name; if it creeps back in as an
    input the override mechanism eats itself."""
    items = _items(client)
    target = next(i for i in items if i["board_column_id"] != board.ESCALATE)
    uid = target["customer"]["uid"]
    before = target["board_column_id"]
    raised = client.post("/v1/cases/by-customer/%s/review-requests" % uid,
                         json={"reason": "NO_COMMITMENT", "question": "ทดสอบ",
                               "by": "nantapol"})
    assert raised.status_code == 201, raised.text
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == before


# --- the request endpoint ---------------------------------------------------------

def _a_card_in(client, column_id):
    for item in _items(client):
        if item["board_column_id"] == column_id:
            return item
    pytest.skip("no seeded customer sits in %s" % column_id)


def _move(client, uid, to_column_id, reason="ลูกค้าแจ้งว่าไม่มีเงินจ่าย", by="nantapol"):
    return client.post("/v1/board/moves", json={
        "customer_uid": uid, "to_column_id": to_column_id, "reason": reason, "by": by})


def test_a_forward_move_applies_at_once(client):
    card = _a_card_in(client, board.AWAITING_PAYMENT)
    uid = card["customer"]["uid"]
    response = _move(client, uid, board.ESCALATE)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["direction"] == "FORWARD"
    assert body["applied"] is True
    assert body["review_uid"] is None
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == board.ESCALATE


def test_a_forward_move_without_a_reason_is_refused(client):
    card = _a_card_in(client, board.AWAITING_PAYMENT)
    response = _move(client, card["customer"]["uid"], board.ESCALATE, reason="   ")
    assert response.status_code == 422
    assert response.json()["code"] == "board_move_reason_required"


def test_a_backward_move_moves_nothing_and_raises_a_review(client):
    card = _a_card_in(client, board.CALL_TODAY)
    uid = card["customer"]["uid"]
    before = card["board_column_id"]
    response = _move(client, uid, board.PROMISE_MADE, reason="ลูกค้ารับปากทางโทรศัพท์")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["direction"] == "BACKWARD"
    assert body["applied"] is False
    assert body["review_uid"]
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == before, "a backward move must not move the card"


def test_the_raised_review_is_a_board_move_ask(client):
    card = _a_card_in(client, board.CALL_TODAY)
    review_uid = _move(client, card["customer"]["uid"], board.PROMISE_MADE).json()["review_uid"]
    listed = client.get("/v1/reviews").json()["reviews"]
    review = next(r for r in listed if r["uid"] == review_uid)
    assert review["reason"] == "BOARD_MOVE_ASK"
    assert review["status"] == "OPEN"


def test_the_approval_question_names_the_columns_and_is_bilingual(client):
    """I4. Two defects in one call.

    The Manager was asked to approve a move between `col_01H8X` and `col_01H8Z` — raw
    identifiers, in the one place a human makes the decision, against the codebase's
    own rule of identity by id and display by name. And the Thai sentence was passed
    positionally as `question`, which `cases.request_review` treats as the ENGLISH
    text, so `question_en` came out Thai. The house idiom is the POWER_CUTOFF_ASK call
    at cases.py:1292 — English positionally, Thai as `question_th`.
    """
    card = _a_card_in(client, board.CALL_TODAY)
    uid = card["customer"]["uid"]
    review_uid = _move(client, uid, board.PROMISE_MADE,
                       reason="ลูกค้ารับปากทางโทรศัพท์").json()["review_uid"]
    listed = client.get("/v1/reviews").json()["reviews"]
    review = next(r for r in listed if r["uid"] == review_uid)
    names = {c["column_id"]: c["name"]
             for c in client.get("/v1/board/columns").json()["columns"]}

    for field in ("question", "question_th", "question_en"):
        assert "col_" not in review[field], (field, review[field])
        assert names[board.CALL_TODAY] in review[field], (field, review[field])
        assert names[board.PROMISE_MADE] in review[field], (field, review[field])
    assert review["question_en"] != review["question_th"]
    assert review["question"] == review["question_en"], "`question` is the English text"
    assert "ขออนุมัติย้าย" in review["question_th"]
    assert "ขออนุมัติย้าย" not in review["question_en"]


def test_a_move_to_the_current_column_is_refused(client):
    card = _a_card_in(client, board.CALL_TODAY)
    response = _move(client, card["customer"]["uid"], board.CALL_TODAY)
    assert response.status_code == 422
    assert response.json()["code"] == "board_move_same_column"


def test_a_request_is_refused_while_another_review_is_open(client):
    """Spec §9a. cases.py refuses a second open review per case, so the board request
    must say which one is blocking rather than failing with a bare 422."""
    card = _a_card_in(client, board.CALL_TODAY)
    uid = card["customer"]["uid"]
    raised = client.post("/v1/cases/by-customer/%s/review-requests" % uid,
                         json={"reason": "NO_COMMITMENT", "question": "ทดสอบ",
                               "by": "nantapol"})
    assert raised.status_code == 201, raised.text
    response = _move(client, uid, board.PROMISE_MADE)
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "board_move_review_open"
    # RFC 9457 (errors.Problem.response): the extras live under `extensions`, never
    # spread onto the envelope's own top level.
    assert body["extensions"]["blocking_review_uid"] == raised.json()["review"]["uid"]


def test_a_forward_move_is_refused_while_a_board_review_is_open(client):
    """I3 / spec §9a, which is written against the REQUEST and not against one
    direction: refuse the board-move request and name the review that is blocking it.

    The guard used to sit inside the BACKWARD branch only, so a forward move applied
    on top of a card that was already waiting for a Manager. The card then carried
    `board_override` AND `board_pending_review_uid` at once — the screen shows only
    the pending chip, so the officer read "รอผู้จัดการอนุมัติ" on a card that had already
    moved — and the Manager's later answer overwrote the forward move with no event
    and no marker.
    """
    from app import journey
    card = _a_card_in(client, board.CALL_TODAY)
    uid = card["customer"]["uid"]
    request = _move(client, uid, board.PROMISE_MADE, reason="ลูกค้ารับปากทางโทรศัพท์")
    assert request.status_code == 201, request.text
    assert request.json()["direction"] == "BACKWARD"
    review_uid = request.json()["review_uid"]

    forward = _move(client, uid, board.ESCALATE, reason="ลูกค้าย้ายออกจากที่อยู่เดิมแล้ว")
    assert forward.status_code == 409, forward.text
    body = forward.json()
    assert body["code"] == "board_move_review_open"
    assert body["extensions"]["blocking_review_uid"] == review_uid
    assert uid not in journey.for_current().board_overrides

    held = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert held["board_column_id"] == board.CALL_TODAY
    assert held["board_override"] is False
    assert held["board_pending_review_uid"] == review_uid

    # And the two records still never coexist once the Manager has answered: the
    # answer pops the pending record, which is why the applied path needs no clear.
    assert _answer(client, review_uid, "BOARD_MOVE_APPROVE").status_code == 200
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_override"] is True
    assert after["board_pending_review_uid"] is None


def test_an_unknown_destination_is_still_refused(client):
    card = _a_card_in(client, board.CALL_TODAY)
    response = _move(client, card["customer"]["uid"], "col_NOPE")
    assert response.status_code == 422
    assert response.json()["code"] == "destination_column_unknown"


# --- the Manager's answer ---------------------------------------------------------

def _answer(client, review_uid, decision, role="MANAGER"):
    return client.post("/v1/reviews/%s:answer" % review_uid,
                       json={"decision": decision, "comment": "ตรวจแล้ว", "by": "manager-1"},
                       headers={"X-Volt-Role": role})


def test_an_approved_backward_move_places_the_card(client):
    card = _a_card_in(client, board.CALL_TODAY)
    uid = card["customer"]["uid"]
    review_uid = _move(client, uid, board.PROMISE_MADE).json()["review_uid"]
    assert _answer(client, review_uid, "BOARD_MOVE_APPROVE").status_code == 200
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == board.PROMISE_MADE


def test_a_rejected_backward_move_leaves_the_card_derived(client):
    card = _a_card_in(client, board.CALL_TODAY)
    uid, before = card["customer"]["uid"], card["board_column_id"]
    review_uid = _move(client, uid, board.PROMISE_MADE).json()["review_uid"]
    assert _answer(client, review_uid, "BOARD_MOVE_REJECT").status_code == 200
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == before


def test_an_officer_cannot_answer_a_board_review(client):
    card = _a_card_in(client, board.CALL_TODAY)
    review_uid = _move(client, card["customer"]["uid"], board.PROMISE_MADE).json()["review_uid"]
    assert _answer(client, review_uid, "BOARD_MOVE_APPROVE", role="OFFICER").status_code == 403


def test_a_board_review_takes_only_its_own_two_decisions(client):
    """A narrative answer leaves the request neither granted nor refused, and a power
    code must never be answerable here."""
    card = _a_card_in(client, board.CALL_TODAY)
    review_uid = _move(client, card["customer"]["uid"], board.PROMISE_MADE).json()["review_uid"]
    assert _answer(client, review_uid, "CONTINUE").status_code == 422
    assert _answer(client, review_uid, "POWER_CUTOFF_APPROVE").status_code == 422


def test_a_second_override_survives_the_read_that_follows_it(client):
    """C1. The expiry pin is the DERIVED column, never the column being served.

    `column_for` answers "what do I show", so it returns the LIVE override's column
    once one exists. Pinning a fresh override against that answer pins the record
    against itself: the pin can never equal `derive()`, so §6 deletes the grant on the
    very next read and writes a BOARD_AUTO_MOVED the case never earned. The API said
    `applied: true` and the card came back on the raw derived column.
    """
    from app import journey
    card = _a_card_in(client, board.AWAITING_PAYMENT)
    uid = card["customer"]["uid"]
    first = _move(client, uid, board.PROMISE_MADE)
    assert first.status_code == 201, first.text
    # Severity, not display order: Call today is WORSE than Promise made, so this is a
    # second FORWARD move and it applies without a Manager.
    second = _move(client, uid, board.CALL_TODAY)
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["direction"] == "FORWARD"
    assert body["applied"] is True
    # `from_column_id` is what the officer was looking at — the first override.
    assert body["from_column_id"] == board.PROMISE_MADE

    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == board.CALL_TODAY
    assert after["board_override"] is True
    assert after["auto_moved"] is False, "nothing about the case changed"
    record = journey.for_current().board_overrides.get(uid)
    assert record is not None, "the second grant was deleted on the next read"
    assert record["to_column_id"] == board.CALL_TODAY


def test_an_approved_backward_move_survives_the_read_that_follows_it(client):
    """C1, scenario 2 — the same pin, on the path the approval exists to protect.

    A Manager signs a backward move on a card an officer had already moved forward.
    The pending record is pinned when the request is raised, so it carried the served
    override's column and the approval was discarded on the next read.
    """
    from app import journey
    card = _a_card_in(client, board.AWAITING_PAYMENT)
    uid = card["customer"]["uid"]
    assert _move(client, uid, board.ESCALATE).status_code == 201
    request = _move(client, uid, board.CALL_TODAY, reason="ลูกค้ารับปากทางโทรศัพท์")
    assert request.status_code == 201, request.text
    assert request.json()["direction"] == "BACKWARD"
    review_uid = request.json()["review_uid"]
    assert _answer(client, review_uid, "BOARD_MOVE_APPROVE").status_code == 200
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == board.CALL_TODAY
    assert uid in journey.for_current().board_overrides


def test_a_board_decision_cannot_answer_someone_elses_review(client):
    """I1 / spec §5. The mirror of the power arm: `POWER_CUTOFF_APPROVE` on a foreign
    review is refused because no cut-off is waiting for it, and a board decision must
    be refused for the same reason — no board move is waiting for it.

    Without this a Supervisor closes an NPL or broken-promise review with
    "อนุมัติย้ายคอลัมน์", the case's review_uid is cleared, and the audit row records a
    decision that answers a question nobody asked.
    """
    card = _a_card_in(client, board.CALL_TODAY)
    uid = card["customer"]["uid"]
    raised = client.post("/v1/cases/by-customer/%s/review-requests" % uid,
                         json={"reason": "NO_COMMITMENT", "question": "ทดสอบ",
                               "by": "nantapol"})
    assert raised.status_code == 201, raised.text
    foreign = raised.json()["review"]["uid"]
    refused = _answer(client, foreign, "BOARD_MOVE_APPROVE")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "board_decision_not_applicable"
    # The refusal is total: the review is untouched and still waiting for its answer.
    listed = client.get("/v1/reviews").json()["reviews"]
    review = next(r for r in listed if r["uid"] == foreign)
    assert review["status"] == "OPEN"
    assert review["decision"] is None

    # The other direction: the same decision on the review it belongs to still lands.
    answered = _answer(client, foreign, "CONTINUE")
    assert answered.status_code == 200, answered.text
    request = _move(client, uid, board.PROMISE_MADE, reason="ลูกค้ารับปากทางโทรศัพท์")
    assert request.status_code == 201, request.text
    assert _answer(client, request.json()["review_uid"],
                   "BOARD_MOVE_APPROVE").status_code == 200


def test_an_approved_override_dies_when_the_data_changes(client):
    """Spec §6 / D5. The override is pinned to the derived value it departed from."""
    from app import journey
    card = _a_card_in(client, board.CALL_TODAY)
    uid = card["customer"]["uid"]
    review_uid = _move(client, uid, board.PROMISE_MADE).json()["review_uid"]
    _answer(client, review_uid, "BOARD_MOVE_APPROVE")
    assert next(i for i in _items(client) if i["customer"]["uid"] == uid)["board_column_id"] \
        == board.PROMISE_MADE

    # Move the case on: the derivation now says Escalate, which is not what the
    # override was granted against, so the override must fall away rather than pin the
    # card. `board.facts_for` reads the session's recovery overlay, so this is a real
    # officer act through the API moving one of `derive`'s own inputs.
    #
    # Not `cases.set_npl_type`, which is where this test first reached: round-4 J4-12
    # gates the NPL type on `payment_status == "NPL"` (cases.py:800) and a Call-today
    # card is LATE, so that act refuses before the derivation could ever move.
    from app import cases as cases_domain
    moved = client.post("/v1/recovery-board/moves", json={
        "customer_uid": uid, "to_stage": "ESCALATE",
        "reason": "ทดสอบว่าสิทธิ์ที่อนุมัติไว้ต้องหมดอายุเมื่อข้อมูลเปลี่ยน"})
    assert moved.status_code == 201, moved.text
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == board.ESCALATE
    assert uid not in journey.for_current().board_overrides
    # One audit trail per case — cases.CaseState.events, where PTP_BROKEN lands.
    kinds = [e["kind"] for e in cases_domain.for_current().events]
    assert "BOARD_OVERRIDE_EXPIRED" in kinds


def test_a_lapsed_promise_writes_an_automatic_move_event(client):
    """The automation, end to end: nothing runs but the clock.

    There is no HTTP route that moves the business date — `settings.business_date` is
    assigned directly and restored in a `finally`, the pattern `test_round2.py:184,200`
    established. The restore is NOT optional: `conftest`'s `clock.reset()` does not undo
    it, because the business date is config state and not clock state, so a leak here
    would poison every test that runs after this one.
    """
    from app import cases as cases_domain
    from app.config import settings

    card = _a_card_in(client, board.PROMISE_MADE)
    uid = card["customer"]["uid"]
    cs = cases_domain.for_current()
    case = cs.cases.get(uid) or {}
    ptp = cs.ptps.get(case.get("open_ptp_uid")) if case.get("open_ptp_uid") else None
    if not ptp:
        pytest.skip("the seeded Promise-made card carries no open PTP to lapse")

    saved = settings.business_date
    try:
        settings.business_date = date.fromisoformat(ptp["promise_date"]) + timedelta(days=1)
        served = next(i for i in _items(client) if i["customer"]["uid"] == uid)
        assert served["board_column_id"] != board.PROMISE_MADE
        assert served["auto_moved"] is True
        assert served["auto_moved_cause"] == "PTP_DATE_PASSED"
        moved = [e for e in cases_domain.for_current().events
                 if e["kind"] == "BOARD_AUTO_MOVED" and e["customer_uid"] == uid]
        assert moved and moved[-1]["cause"] == "PTP_DATE_PASSED"
    finally:
        settings.business_date = saved


@pytest.mark.parametrize("body,code", [
    ({}, "destination_column_required"),
    ({"destination_column_id": "col_NOPE"}, "destination_column_unknown"),
    ({"destination_column_id": board.ESCALATE}, "board_column_derived"),
])
def test_a_refused_column_deletion_touches_no_customer(client, body, code):
    """I2. `board.column_for` is a WRITER — it expires outlived overrides, appends the
    board's audit events and consumes the one-read `auto_moved` marker. Counting the
    customers on a column with it ran that writer over every customer before the
    request had been validated at all, so a DELETE refused for any of these three
    reasons still ate the news the officer was about to be shown.

    All three refusals are exercised because the count sat in front of all three
    guards, and because their relative order is load-bearing (main.py, the comment
    above `board_column_derived`).
    """
    from app import cases as cases_domain
    from app.config import settings

    card = _a_card_in(client, board.PROMISE_MADE)
    uid = card["customer"]["uid"]
    cs = cases_domain.for_current()
    case = cs.cases.get(uid) or {}
    ptp = cs.ptps.get(case.get("open_ptp_uid")) if case.get("open_ptp_uid") else None
    if not ptp:
        pytest.skip("the seeded Promise-made card carries no open PTP to lapse")

    saved = settings.business_date
    try:
        settings.business_date = date.fromisoformat(ptp["promise_date"]) + timedelta(days=1)
        before = len(cases_domain.for_current().events)
        refused = client.request("DELETE", "/v1/board/columns/%s" % board.CALL_TODAY,
                                 json=body)
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == code
        if code == "destination_column_required":
            # The count still has to be a real one — the Owner is being told how many
            # customers they must find a destination for.
            assert refused.json()["extensions"]["affected_customers"] > 0
        assert len(cases_domain.for_current().events) == before, \
            "a refused deletion wrote board events"

        # And the news survives for the read it was written for.
        served = next(i for i in _items(client) if i["customer"]["uid"] == uid)
        assert served["auto_moved"] is True
        assert served["auto_moved_cause"] == "PTP_DATE_PASSED"
    finally:
        settings.business_date = saved


# --- the four derived columns are not deletable -----------------------------------

@pytest.mark.parametrize("column_id", list(board.DERIVED_COLUMNS))
def test_a_derived_column_cannot_be_deleted(client, column_id):
    """Spec §9b. derive() returns one of these four; deleting one would leave the rule
    naming a column that does not exist."""
    # The destination must differ from the column under test: `destination == column_id`
    # is refused as `destination_column_unknown` before the policy guard is reached.
    elsewhere = (board.AWAITING_PAYMENT if column_id == board.ESCALATE else board.ESCALATE)
    response = client.request("DELETE", "/v1/board/columns/%s" % column_id,
                              json={"destination_column_id": elsewhere})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "board_column_derived"
    assert set(body["extensions"]["derived_columns"]) == set(board.DERIVED_COLUMNS)
