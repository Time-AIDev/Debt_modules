# Board Derived Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Today board's column a function of the case's own data, delete drag-and-drop, and turn the move button into a request that a Manager must approve when it makes a case look better than the data says.

**Architecture:** A new pure module `backend/app/board.py` owns one rule and three helpers. `journey.board_overlay` — today's unguarded per-session placement store — is deleted and replaced by an override record that expires the moment the derivation disagrees with it. `POST /v1/board/moves` stops being a write and becomes a request: a move toward higher severity applies with a reason, a move toward lower severity raises a `BOARD_MOVE_ASK` review through the queue `POWER_CUTOFF_ASK` already uses.

**Tech Stack:** FastAPI, Pydantic-free plain dicts, pytest + `fastapi.testclient.TestClient` (backend); React 18, Vite, Vitest + `@testing-library/react` (frontend); `scripts/e2e_check.py` for the live-API checks.

**Spec:** `docs/archive/superpowers/specs/2026-09-09-board-derived-columns-design.md`

## Global Constraints

- **The four column ids are fixed and are matched by id, never by name:** `col_01H8X` Call today · `col_01H8Y` Awaiting payment · `col_01H8Z` Promise made · `col_01H90` Escalate.
- **Severity is not the column's `order`.** `SEVERITY = {col_01H8Y: 0, col_01H8Z: 1, col_01H8X: 2, col_01H90: 3}`. The served `order` field (1,2,3,4) is the desk's reading order and is not touched.
- **`manager_review_open` must never be an input to `derive()`.** It is circular: a board-move review would push the card to Escalate, changing the derived value, which expires the override the Manager just approved. Spec §9g.
- **`aging_bucket` must never be an input to `derive()`.** It is band-set dependent and `PUT /v1/config {band_set_code}` rewrites its codes. Read contract `status == "NON_PERFORMING"` instead. Spec §9f.
- **Never write to a shared fixture object.** All mutable state is per session, through `journey.for_current()` / `cases.for_current()`. Rulings 39/40/43.
- **Every user-facing string is added in BOTH languages** — `frontend/src/i18n-today.js` has an English block and a Thai block; a key added to one and not the other is a defect.
- **Errors are RFC 9457 through `errors.Problem`**, with `code`, `status`, `title`, `detail`, `message_th`, `error_id`, `extensions` — copy the shape of `errors.destination_column_unknown` (`errors.py:309`).
- **Baseline to hold:** `./scripts/verify_all.sh` — **498 backend passed / 1 skipped**, **431 frontend across 33 files**, **29 e2e**. Backend and frontend counts rise as tests are added; they must never fall.
- **Test budget, authorised:** ONE new test file, `backend/tests/test_board_derived.py`. Edits are permitted to exactly four existing test surfaces: `frontend/src/screens/Today.board.test.jsx`, `frontend/src/screens/ReviewQueue.test.jsx`, `scripts/e2e_check.py`, and `backend/tests/test_journey_rebuild.py` (one forced edit, Task 3). No other test file is created or edited.

---

## File Structure

**Created**

| file | responsibility |
|---|---|
| `backend/app/board.py` | The rule and nothing else. Column constants, `SEVERITY`, `derive`, `direction_of`, `cause_of`, `facts_for`, `column_for`, `BoardError`. No FastAPI, no router, no I/O. |
| `backend/tests/test_board_derived.py` | Every behaviour in spec §11 that is backend-observable. |

**Modified**

| file | change |
|---|---|
| `backend/app/fixtures.py` | Delete the field, the seeding pass and the seed-time fact helper; rewrite the ruling-45 comment block as a record. |
| `backend/app/journey.py` | `board_overlay` → `board_overrides`; add `board_last_served`; fix two stale comments. |
| `backend/app/main.py` | Serve the derived column; delete `_board_overlay`; refuse deletion of a derived column; fix two stale comments. |
| `backend/app/routers/journey.py` | Serve the derived column; rewrite `board_move` as the request endpoint; fix one stale comment. |
| `backend/app/cases.py` | `BOARD_DECISIONS`; the `BOARD_MOVE_ASK` arm in `answer_review`; fix one stale comment. |
| `backend/app/dictionaries.py` | `BOARD_MOVE_ASK` in `REVIEW_REASON`; `BOARD_MOVE_APPROVE` / `BOARD_MOVE_REJECT` in `REVIEW_DECISION`. |
| `backend/app/errors.py` | Four new problems. |
| `backend/app/routers/settings.py` | Fix one stale comment. |
| `frontend/src/screens/Today.jsx` | Remove drag; the request panel; the three card markers. |
| `frontend/src/today.css` | Remove drag styles; marker styles. |
| `frontend/src/i18n-today.js` | Two rewritten captions, eight new keys, EN and TH. |
| `frontend/src/api.js` | `boardMove` payload gains `reason`. |
| `frontend/src/screens/ReviewQueue.jsx` | `boardDecisions()` mirroring `powerDecisions()`. |
| `docs/design/round-4/board/B-system.md` | §1.2 corrected, §1.4 restated, §1.7 recorded as superseded. |

---

### Task 1: The rule module

**Files:**
- Create: `backend/app/board.py`
- Test: `backend/tests/test_board_derived.py`

**Interfaces:**
- Consumes: nothing. This task is pure functions with no imports from the app.
- Produces: `board.CALL_TODAY`, `board.AWAITING_PAYMENT`, `board.PROMISE_MADE`, `board.ESCALATE`, `board.DERIVED_COLUMNS` (tuple of the four ids), `board.SEVERITY` (dict id→int), `board.BoardError` (exception carrying `.code`), `board.derive(*, npl_confirmed, npl_type, recovery_stage, dc_status, open_ptp_promise_date, dpd, business_date) -> str`, `board.direction_of(requested, current) -> "FORWARD" | "BACKWARD"` (raises `BoardError("board_move_same_column")`), `board.cause_of(previous, current, *, open_ptp_promise_date, business_date) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_board_derived.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_board_derived.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'app.board'`.

- [ ] **Step 3: Write the module**

Create `backend/app/board.py`:

```python
"""Which board column a case belongs in, and what a request to change it means.

Spec: docs/archive/superpowers/specs/2026-09-09-board-derived-columns-design.md

One rule, one place. `fixtures.py` used to own a seed-time copy of this and wrote
the answer onto the customer; that pass is gone and the column is computed where it
is served. `docs/design/round-4/board/B-system.md` §1.7 forbade exactly this and is
superseded — see spec §9f for the three reasons and how each is answered.
"""
from datetime import date

CALL_TODAY = "col_01H8X"
AWAITING_PAYMENT = "col_01H8Y"
PROMISE_MADE = "col_01H8Z"
ESCALATE = "col_01H90"

DERIVED_COLUMNS = (CALL_TODAY, AWAITING_PAYMENT, PROMISE_MADE, ESCALATE)

# How bad the case is — NOT the column's served `order` (1..4), which is the desk's
# reading order and stays as it is. Under the rule below `Awaiting payment` is the
# HEALTHY column (nothing overdue) and `Call today` the overdue one, so ranking on
# `order` would make a move into health look like progress. That is precisely the
# move this ranking exists to send to a Manager.
SEVERITY = {AWAITING_PAYMENT: 0, PROMISE_MADE: 1, CALL_TODAY: 2, ESCALATE: 3}


class BoardError(Exception):
    """Carries a `code` the router turns into an RFC 9457 problem."""

    def __init__(self, code, **extensions):
        super().__init__(code)
        self.code = code
        self.extensions = extensions


def derive(*, npl_confirmed, npl_type, recovery_stage, dc_status,
           open_ptp_promise_date, dpd, business_date):
    """The column a case's own data implies. First match wins, so the branches are
    exhaustive and exclusive and Σ columns == row count holds by construction.

    Two inputs are excluded BY NAME and must stay excluded:

    * `manager_review_open` — spec §9g. It is circular here: a backward move raises a
      review, the review would push the card to Escalate, the derived value would
      change, and §6 would expire the override the Manager had just approved. The card
      would refuse to hold the placement it was granted.
    * `aging_bucket` — spec §9f. Its codes are defined by the active band set and
      `PUT /v1/config {band_set_code}` rewrites five of them into seven different ones,
      so a tester switching band sets would reshuffle the whole board. The NPL fact is
      read from the contract's own status instead, which does not move.
    """
    if (npl_confirmed or npl_type
            or recovery_stage in ("ESCALATE", "RECOVERY")
            or dc_status == "RETRIEVE_ASSET"):
        return ESCALATE
    # A promise holds the card only while it is still live. The day after the promised
    # date this comparison fails and the card leaves on the next read — no job runs.
    if open_ptp_promise_date is not None and open_ptp_promise_date >= business_date:
        return PROMISE_MADE
    # `dpd` is the money engine's own answer, computed from the schedule's due dates.
    # `None` means the engine could not price the contract: not a licence to call.
    if dpd is not None and dpd > 0:
        return CALL_TODAY
    return AWAITING_PAYMENT


def direction_of(requested, current):
    """FORWARD only when the officer asks for a column the data ranks as WORSE than
    where the case already sits — they know something the data has not caught up to.
    Everything else is a claim that the case is better than the record says, which is
    a Manager's call."""
    if requested == current:
        raise BoardError("board_move_same_column", column_id=current)
    # An Owner may add a column beyond the derived four. It has no rank to compare, so
    # it is the largest claim an officer can make and a Manager signs for it. Indexing
    # SEVERITY here instead would raise KeyError on a live request.
    if requested not in SEVERITY or current not in SEVERITY:
        return "BACKWARD"
    return "FORWARD" if SEVERITY[requested] > SEVERITY[current] else "BACKWARD"


def cause_of(previous, current, *, open_ptp_promise_date, business_date):
    """Why a card moved on its own. A function of the transition and the CURRENT facts
    — the previous inputs are not stored, so nothing here is inferred from them."""
    if (previous == PROMISE_MADE and current != PROMISE_MADE
            and open_ptp_promise_date is not None
            and open_ptp_promise_date < business_date):
        return "PTP_DATE_PASSED"
    if previous == AWAITING_PAYMENT and current == CALL_TODAY:
        return "ARREARS_OPENED"
    if previous == CALL_TODAY and current == AWAITING_PAYMENT:
        return "ARREARS_CLEARED"
    # An NPL confirmation, a DC status, a recovery move. A real value, not a fallback
    # standing in for a branch nobody wrote.
    return "CASE_CHANGED"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_board_derived.py -q`
Expected: PASS, 30 tests.

- [ ] **Step 5: Run the whole backend suite**

Run: `cd backend && python -m pytest -q`
Expected: 528 passed, 1 skipped. Nothing imports `board.py` yet, so the 498 baseline is untouched and the 30 new tests are added to it.

- [ ] **Step 6: Commit**

```bash
git add backend/app/board.py backend/tests/test_board_derived.py
git commit -m "feat(board): the derivation rule, as a pure module"
```

---

### Task 2: Serve the derived column, delete the overlay and the seeding pass

**Files:**
- Modify: `backend/app/board.py` (append `facts_for`, `column_for`)
- Modify: `backend/app/journey.py:72` (the store), `:76`, `:104` (comments)
- Modify: `backend/app/main.py:658-660` (delete helper), `:664`, `:673` (comments), `:710` (serve)
- Modify: `backend/app/routers/journey.py:215` (comment), `:233` (serve), `:499-500` (the fifth reader — see Step 8)
- Modify: `backend/app/fixtures.py:133`, `:210-266`, `:267-330`, `:331-345`, `:346-354`, and the 14 `board_column_id=` keyword arguments
- Modify: `backend/app/cases.py:104` (comment), `backend/app/routers/settings.py:255` (comment)
- Test: `backend/tests/test_board_derived.py`

**Interfaces:**
- Consumes: `board.derive`, `board.cause_of`, `board.DERIVED_COLUMNS` from Task 1.
- Produces: `board.facts_for(customer, dpd) -> dict` (the keyword arguments `derive` takes), `board.column_for(customer, dpd) -> str`, `board.serve(customer, dpd) -> dict` with keys `board_column_id`, `auto_moved`, `auto_moved_cause`, `board_override`, `board_pending_review_uid`, `journey.JourneyState.board_overrides` (`customer_uid -> override record`), `journey.JourneyState.board_last_served` (`customer_uid -> column_id`). `journey.JourneyState.board_overlay` NO LONGER EXISTS.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_board_derived.py`:

```python
# ---------------------------------------------------------------------------------
# Served behaviour. From here the tests go through the API, because the point of the
# rule is what an officer sees.
# ---------------------------------------------------------------------------------
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


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
    before = {i["customer"]["uid"]: i["board_column_id"] for i in _items(client)}
    response = client.put("/v1/config", json={"band_set_code": "LEGACY_LDR"},
                          headers={"X-Volt-Role": "OWNER"})
    assert response.status_code in (200, 204), response.text
    after = {i["customer"]["uid"]: i["board_column_id"] for i in _items(client)}
    assert after == before


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_board_derived.py -q`
Expected: FAIL. `test_the_board_overlay_is_gone` and `test_the_stored_column_is_gone_from_the_fixture` fail on the attributes still existing; the others may pass by accident against the old seeding, which is why the two structural tests are there.

- [ ] **Step 3: Append the serving functions to `board.py`**

```python
def facts_for(customer, dpd):
    """Gather `derive`'s inputs from the live per-session stores.

    `dpd` is passed in rather than computed: both call sites already have it from
    `_customer_aggregate`, and taking it as an argument keeps this module free of an
    import back into `main`.
    """
    from . import cases as cases_domain
    from . import journey as journey_domain
    from .config import settings

    cs = cases_domain.for_current()
    js = journey_domain.for_current()
    case = cs.cases.get(customer.uid) or {}
    ptp_uid = case.get("open_ptp_uid")
    ptp = cs.ptps.get(ptp_uid) if ptp_uid else None
    promise = None
    if ptp and ptp.get("promise_date"):
        promise = date.fromisoformat(ptp["promise_date"])
    # Ruling 43: the session-scoped read. Never `contract.status` directly — a session's
    # NPL classification must not be visible to a session that never made it.
    statuses = {cases_domain.contract_field_of(k, "status") for k in customer.contracts}
    return {
        "npl_confirmed": "NON_PERFORMING" in statuses,
        "npl_type": case.get("npl_type"),
        # Overlay-aware. `main.py` serves the raw `customer.recovery_stage` on its own
        # separate line of the payload (spec §9c, left as found), but the DERIVATION
        # must see a session's recovery move or the board would ignore it on one of the
        # two paths and not the other.
        "recovery_stage": js.recovery_overlay.get(customer.uid, customer.recovery_stage),
        "dc_status": case.get("dc_status"),
        "open_ptp_promise_date": promise,
        "dpd": dpd,
        "business_date": settings.business_date,
    }


def serve(customer, dpd):
    """Everything the payload needs about this card's placement, in one call.

    `column_for` below answers only "which column" and is what the router uses for the
    direction check. This is what the two serving endpoints spread into the item: the
    column PLUS the three facts that explain it, because a card that moved on its own
    or is held pending a Manager has to say so on the card itself.
    """
    from . import journey as journey_domain

    js = journey_domain.for_current()
    # Only the move THIS call produced is news. Scanning the whole event list for the
    # customer's most recent BOARD_AUTO_MOVED would re-announce an old move whenever its
    # destination happened to match today's column — so the window is the events this
    # call appended, and nothing else.
    before = len(js.events)
    column = column_for(customer, dpd)
    fresh = next((e for e in js.events[before:]
                  if e["kind"] == "BOARD_AUTO_MOVED" and e["customer_uid"] == customer.uid),
                 None)
    override = js.board_overrides.get(customer.uid)
    pending = js.board_pending.get(customer.uid)
    return {
        "board_column_id": column,
        "auto_moved": fresh is not None,
        "auto_moved_cause": fresh["cause"] if fresh else None,
        "board_override": bool(override),
        "board_pending_review_uid": pending["review_uid"] if pending else None,
    }


def column_for(customer, dpd):
    """The column to serve, and the only place that answers the question.

    An approved override wins over the derivation, but only while the derivation it
    departed from still holds. The moment the data moves — a payment clears, a promise
    lapses, an NPL is confirmed — the override is void and the data wins. Without that
    clause one approved override would pin a card against reality for ever.
    """
    from . import journey as journey_domain
    from .config import settings

    js = journey_domain.for_current()
    derived = derive(**facts_for(customer, dpd))

    override = js.board_overrides.get(customer.uid)
    if override is not None and override["derived_at_grant"] != derived:
        del js.board_overrides[customer.uid]
        js.events.append({
            "kind": "BOARD_OVERRIDE_EXPIRED", "customer_uid": customer.uid,
            "was_column_id": override["to_column_id"], "now_column_id": derived,
            "granted_against": override["derived_at_grant"],
            "on": str(settings.business_date),
        })
        override = None

    served = override["to_column_id"] if override else derived

    previous = js.board_last_served.get(customer.uid)
    if previous is not None and previous != served and override is None:
        js.events.append({
            "kind": "BOARD_AUTO_MOVED", "customer_uid": customer.uid,
            "from_column_id": previous, "to_column_id": served,
            "cause": cause_of(previous, served,
                              open_ptp_promise_date=facts_for(customer, dpd)["open_ptp_promise_date"],
                              business_date=settings.business_date),
            "on": str(settings.business_date),
        })
    js.board_last_served[customer.uid] = served
    return served
```

- [ ] **Step 4: Replace the store in `backend/app/journey.py`**

At `:72`, replace the single `board_overlay` line with:

```python
        # Spec 2026-09-09: `board_overlay` was an unguarded per-session placement — any
        # caller could put any card anywhere and it was recorded as fact. It is replaced
        # by an override that must be justified, may need a Manager, and expires the
        # moment the data disagrees with it (board.column_for).
        self.board_overrides = {}    # customer_uid -> override record (granted)
        self.board_pending = {}      # customer_uid -> override record awaiting a Manager
        self.board_last_served = {}  # customer_uid -> column_id, for BOARD_AUTO_MOVED
```

Then update the two comments that cite the old name as the pattern's example — `:76` and `:104` — replacing `board_overlay` with `officer_overlay`, which still exists and still demonstrates the same shape.

- [ ] **Step 5: Serve it from both endpoints**

In `backend/app/main.py`: delete `_board_overlay()` at `:658-660` entirely. At `:710` replace

```python
            "board_column_id": _board_overlay().get(customer.uid, customer.board_column_id),
```

with

```python
            **board.serve(customer, oldest),
```

— which contributes `board_column_id` and the three explaining fields in one spread.
Add `from . import board` to the module imports. Update the two comments at `:664` and `:673` that cite `_board_overlay` as the example to cite `_officer_overlay` instead.

In `backend/app/routers/journey.py` at `:233` replace

```python
        "board_column_id": state.board_overlay.get(customer.uid, customer.board_column_id),
```

with

```python
        **_board().serve(customer, oldest),
```

adding a module-level helper beside the existing `_main()` / `_cases()` helpers:

```python
def _board():
    from .. import board
    return board
```

and update the comment at `:215` that names `board_overlay` to name `recovery_overlay`.

- [ ] **Step 6: Delete the seeding pass from `backend/app/fixtures.py`**

Delete four symbols and one field:

1. `board_column_id: str = "col_01H8X"` at `:133`.
2. All **14** `board_column_id=...` keyword arguments in the customer literals.
3. `_seed_time_case_facts` (`:267`) — verified used by nothing else.
4. `_derive_board_column` (`:331`).
5. `_seed_board_columns` (`:346`) and its call inside `seed()` (`:676`).

Replace the ruling-45 comment block at `:210` with a record of why it went, keeping the history rather than leaving a gap:

```python
# ---- Round 4, ruling 45: re-seeding board_column_id — SUPERSEDED 2026-09-09 --------
#
# Ruling 45 measured "Call today" holding 141/151 (93.4%) of the live desk and had this
# file compute a starting column for all 212 customers in one deterministic seed-time
# pass, writing it onto `CustomerFixture.board_column_id`. The rule it implemented is
# `docs/design/round-4/board/B-system.md` §1.2, and §1.7 of that document required the
# pass to run at seed time and FORBADE deriving the column per request.
#
# That is reversed. The column is now computed where it is served, by `app/board.py`,
# because the board has to answer to a due date passing — a promise lapsing or an
# instalment falling overdue must move a card with no officer and no nightly job. See
# `docs/archive/superpowers/specs/2026-09-09-board-derived-columns-design.md` §9f, which answers
# §1.7's three objections one at a time rather than stepping over them.
#
# The stored field went with the pass: it had four readers, all replaced, and a value
# written at seed time and read nowhere is dead state.
```

- [ ] **Step 7: De-overlay `delete_column` in the same commit**

`main.delete_column` (`:772`) calls `_board_overlay()`, which Step 5 deletes. Left for
Task 5 it would leave HEAD raising `NameError` for three tasks, and this plan commits
after every task. Replace the overlay reads and the bulk write:

```python
    def _column_of(customer):
        _t, oldest, _b, _o = _customer_aggregate(customer)
        return board.column_for(customer, oldest)

    affected = sum(1 for c in CUSTOMERS if _column_of(c) == column_id)
    destination = (body.get("destination_column_id") or "").strip()
    if not destination:
        raise errors.destination_column_required(column_id, affected)
    if destination not in known or destination == column_id:
        raise errors.destination_column_unknown(destination)

    # A card can only be standing on a non-derived column because an override put it
    # there, so relocating one is rewriting that override — never a second placement
    # store beside it.
    overrides = journey.for_current().board_overrides
    moved = []
    for customer in CUSTOMERS:
        if _column_of(customer) == column_id:
            moved.append(customer.customer_no)
            if customer.uid in overrides:
                overrides[customer.uid]["to_column_id"] = destination
```

Task 5 then adds only the refusal guard above this block.

- [ ] **Step 8: Carry `board_move` across too — the fifth reader**

`routers/journey.py:499-500` reads AND writes `state.board_overlay`:

```python
    previous = state.board_overlay.get(customer.uid, customer.board_column_id)
    state.board_overlay[customer.uid] = destination
```

Task 3 replaces this endpoint wholesale, but between the two tasks it would raise
`AttributeError` on a store that no longer exists. Carry it across minimally, preserving
today's behaviour — an unconditional move — so `test_journey_rebuild.py:337` stays green
until Task 3 gives the endpoint its real shape:

```python
    state = journey.for_current()
    _total, oldest, _band, _out = main._customer_aggregate(customer)
    previous = _board().column_for(customer, oldest)
    # PLACEHOLDER, replaced wholesale in the next task. This endpoint still moves
    # unconditionally, which is the behaviour this task is not yet changing; it simply
    # records the move as an override rather than in the store that just went away.
    state.board_overrides[customer.uid] = {
        "customer_uid": customer.uid, "to_column_id": destination,
        "derived_at_grant": previous, "direction": "FORWARD", "reason": None,
        "requested_by": None, "requested_on": str(settings.business_date),
        "review_uid": None, "approved_by": None, "approved_on": None,
    }
```

- [ ] **Step 9: Fix the two remaining stale comments**

`backend/app/cases.py:104` and `backend/app/routers/settings.py:255` both cite `board_overlay` as the reference example of the per-session overlay pattern. Replace the citation with `officer_overlay` in both. The surrounding prose is correct and stays.

- [ ] **Step 10: Run the tests**

Run: `cd backend && python -m pytest tests/test_board_derived.py -q`
Expected: PASS.

Run: `cd backend && python -m pytest -q`
Expected: PASS. `test_journey_rebuild.py:337` still passes at this point — the endpoint has not changed yet and its `col_01H90` destination is still accepted.

- [ ] **Step 11: Commit**

```bash
git add backend/app/board.py backend/app/journey.py backend/app/main.py \
        backend/app/routers/journey.py backend/app/fixtures.py backend/app/cases.py \
        backend/app/routers/settings.py backend/tests/test_board_derived.py
git commit -m "feat(board): serve the derived column, delete the overlay and the seed pass"
```

---

### Task 3: The move button becomes a request

**Files:**
- Modify: `backend/app/errors.py` (append three problems)
- Modify: `backend/app/dictionaries.py:85` (`REVIEW_REASON`), `:95` (`REVIEW_DECISION`)
- Modify: `backend/app/routers/journey.py:491-503` (`board_move`)
- Modify: `backend/tests/test_journey_rebuild.py:335-341` (one forced edit)
- Test: `backend/tests/test_board_derived.py`

**Interfaces:**
- Consumes: `board.column_for`, `board.direction_of`, `board.BoardError`, `journey.board_overrides` from Task 2.
- Produces: `POST /v1/board/moves` with body `{customer_uid, to_column_id, reason, by}` returning `{customer_uid, from_column_id, to_column_id, direction, applied: bool, review_uid: str|None, moved_on}`. `errors.board_move_reason_required(...)`, `errors.board_move_same_column(...)`, `errors.board_move_review_open(...)`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_board_derived.py`:

```python
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
    assert body["blocking_review_uid"] == raised.json()["review"]["uid"]


def test_an_unknown_destination_is_still_refused(client):
    card = _a_card_in(client, board.CALL_TODAY)
    response = _move(client, card["customer"]["uid"], "col_NOPE")
    assert response.status_code == 422
    assert response.json()["code"] == "destination_column_unknown"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_board_derived.py -q -k "forward or backward or same_column or review_open or unknown_destination"`
Expected: FAIL — the endpoint still writes unconditionally and returns no `direction`.

- [ ] **Step 3: Add the three problems to `backend/app/errors.py`**

```python
def board_move_reason_required(customer_uid, to_column_id):
    return Problem(
        code="board_move_reason_required",
        status=422,
        title="A board move must say why",
        detail="The board column is computed from the case. Moving a card away from it "
               "is a claim that the data is wrong, and a claim carries a reason.",
        message_th="การย้ายคอลัมน์ต้องระบุเหตุผล",
        error_id="DEBT-COL-0429",
        extensions={"customer_uid": customer_uid, "to_column_id": to_column_id},
    )


def board_move_same_column(column_id):
    return Problem(
        code="board_move_same_column",
        status=422,
        title="The card is already in that column",
        detail="Nothing would change.",
        message_th="การ์ดอยู่ในคอลัมน์นี้อยู่แล้ว",
        error_id="DEBT-COL-0430",
        extensions={"column_id": column_id},
    )


def board_move_review_open(customer_uid, blocking_review_uid, blocking_reason):
    return Problem(
        code="board_move_review_open",
        status=409,
        title="A review is already open on this case",
        detail="One review at a time per case. Answer %s (%s) first — a board move is "
               "the least urgent of the two." % (blocking_review_uid, blocking_reason),
        message_th="เคสนี้มีคำขอตรวจที่ยังไม่ได้ตอบอยู่แล้ว — ตอบคำขอนั้นก่อน",
        error_id="DEBT-COL-0431",
        extensions={"customer_uid": customer_uid,
                    "blocking_review_uid": blocking_review_uid,
                    "blocking_reason": blocking_reason},
    )
```

- [ ] **Step 4: Add the dictionary values**

In `backend/app/dictionaries.py`, add to `REVIEW_REASON` (after `NPL_TYPE_ASK`):

```python
        _v("BOARD_MOVE_ASK", "ขออนุมัติย้ายคอลัมน์", "Board move approval"),
```

and to `REVIEW_DECISION` (after `POWER_CUTOFF_REJECT`):

```python
        # Spec 2026-09-09: their own pair, never the POWER_CUTOFF_* codes — cutting a
        # customer's power must not be selectable as the answer to a board request.
        _v("BOARD_MOVE_APPROVE", "อนุมัติย้ายคอลัมน์", "Approve the board move"),
        _v("BOARD_MOVE_REJECT", "ปฏิเสธการย้ายคอลัมน์", "Reject the board move"),
```

- [ ] **Step 5: Rewrite `board_move` in `backend/app/routers/journey.py`**

Replace the body of `POST /v1/board/moves` (`:490-503`) with:

```python
@router.post("/v1/board/moves", status_code=201)
def board_move(body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """No longer a move. The column is derived (app/board.py), so asking for a
    different one is a claim that the case data is wrong.

    Toward higher severity the officer knows something the data has not caught up to,
    and it applies with a reason. Toward lower severity — or onto a column outside the
    derived four — it is a claim the case is healthier than the record says, which is
    the move that makes a desk look better than it is. Nothing moves; a Manager decides.
    """
    from .. import board as board_mod
    main = _main()
    customer = _customer_or_404(body.get("customer_uid"))
    destination = (body or {}).get("to_column_id")
    known = {c["column_id"] for c in main.BOARD_COLUMNS}
    if destination not in known:
        raise errors.destination_column_unknown(destination)

    reason = (body.get("reason") or "").strip()
    if not reason:
        raise errors.board_move_reason_required(customer.uid, destination)

    _total, oldest, _band, _out = main._customer_aggregate(customer)
    current = board_mod.column_for(customer, oldest)
    try:
        direction = board_mod.direction_of(destination, current)
    except board_mod.BoardError as exc:
        if exc.code == "board_move_same_column":
            raise errors.board_move_same_column(current)
        raise

    state = journey.for_current()
    cs = _cases().for_current()
    who = body.get("by") or x_volt_officer or "unknown"
    record = {
        "customer_uid": customer.uid, "to_column_id": destination,
        "derived_at_grant": current, "direction": direction, "reason": reason,
        "requested_by": who, "requested_on": str(settings.business_date),
        "review_uid": None, "approved_by": None, "approved_on": None,
    }

    if direction == "FORWARD":
        state.board_overrides[customer.uid] = record
        return {"customer_uid": customer.uid, "from_column_id": current,
                "to_column_id": destination, "direction": direction,
                "applied": True, "review_uid": None,
                "moved_on": str(settings.business_date)}

    case = cs.cases.get(customer.uid)
    if case is None:
        raise errors.not_found("case")
    open_uid = case.get("review_uid")
    if open_uid and cs.reviews[open_uid]["status"] == "OPEN":
        raise errors.board_move_review_open(customer.uid, open_uid,
                                            cs.reviews[open_uid]["reason"])
    question_th = "ขออนุมัติย้าย %s จาก %s ไป %s — %s" % (
        customer.display_name, current, destination, reason)
    review = _cases().request_review(cs, case, "BOARD_MOVE_ASK", question_th,
                                     by=who, question_th=question_th)
    record["review_uid"] = review["uid"]
    # Held, not applied. `board.column_for` never reads a record whose review is open,
    # so the card stays where the data put it until a Manager answers.
    state.board_pending[customer.uid] = record
    return {"customer_uid": customer.uid, "from_column_id": current,
            "to_column_id": destination, "direction": direction,
            "applied": False, "review_uid": review["uid"],
            "moved_on": None}
```

**Interface note for Task 4:** the pending record lives at
`journey.for_current().board_pending[customer_uid]` — its own dict, not a reserved key
inside `board_overrides`. Two dicts keyed the same way say what they are; one dict with
a magic key that must never collide with a customer uid is a trap for whoever adds the
next reader.

- [ ] **Step 6: Fix the one forced test edit**

`backend/tests/test_journey_rebuild.py:335-341` posts a board move with no `reason` and
asserts the card moved. The endpoint now requires a reason. Add one, and keep the
assertion — `col_01H90` is Escalate, the most severe column, so the move stays FORWARD
and still applies:

```python
    response = client.post("/v1/board/moves", json={
        "customer_uid": target["customer"]["uid"], "to_column_id": "col_01H90",
        "reason": "ทดสอบการย้ายไปคอลัมน์ส่งต่อผู้จัดการ"})
```

If the chosen `target` already sits in `col_01H90` the request is now a 422
`board_move_same_column`; pick the target with
`next(i for i in items if i["board_column_id"] != "col_01H90")`.

- [ ] **Step 7: Run the tests**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/errors.py backend/app/dictionaries.py backend/app/routers/journey.py \
        backend/tests/test_board_derived.py backend/tests/test_journey_rebuild.py
git commit -m "feat(board): a move becomes a request, backward goes to a Manager"
```

---

### Task 4: The Manager's answer

**Files:**
- Modify: `backend/app/cases.py:30` (`BOARD_DECISIONS`), `:1148-1190` (`answer_review`)
- Test: `backend/tests/test_board_derived.py`

**Interfaces:**
- Consumes: the pending record at `journey.for_current().board_overrides["_pending"][customer_uid]` and the `BOARD_MOVE_ASK` review from Task 3.
- Produces: `cases.BOARD_DECISIONS = ("BOARD_MOVE_APPROVE", "BOARD_MOVE_REJECT")`. On approve, the record is promoted out of `_pending` into `board_overrides[customer_uid]` with `approved_by` and `approved_on` set.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_board_derived.py`:

```python
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


def test_an_approved_override_dies_when_the_data_changes(client):
    """Spec §6 / D5. The override is pinned to the derived value it departed from."""
    from app import journey
    card = _a_card_in(client, board.CALL_TODAY)
    uid = card["customer"]["uid"]
    review_uid = _move(client, uid, board.PROMISE_MADE).json()["review_uid"]
    _answer(client, review_uid, "BOARD_MOVE_APPROVE")
    assert next(i for i in _items(client) if i["customer"]["uid"] == uid)["board_column_id"] \
        == board.PROMISE_MADE

    # Confirm the NPL: the derivation now says Escalate, which is not what the override
    # was granted against, so the override must fall away rather than pin the card.
    from app import cases as cases_domain
    cs = cases_domain.for_current()
    cases_domain.set_npl_type(cs, cs.cases[uid], "NPL_1_RESTRUCTURE", "manager-1",
                              "MANAGER", reason="ทดสอบ")
    after = next(i for i in _items(client) if i["customer"]["uid"] == uid)
    assert after["board_column_id"] == board.ESCALATE
    assert uid not in journey.for_current().board_overrides
    kinds = [e["kind"] for e in journey.for_current().events]
    assert "BOARD_OVERRIDE_EXPIRED" in kinds


def test_a_lapsed_promise_writes_an_automatic_move_event(client):
    """The automation, end to end: nothing runs but the clock.

    There is no HTTP route that moves the business date — `settings.business_date` is
    assigned directly and restored in a `finally`, the pattern `test_round2.py:184,200`
    established. The restore is NOT optional: `conftest`'s `clock.reset()` does not undo
    it, because the business date is config state and not clock state, so a leak here
    would poison every test that runs after this one.
    """
    from app import cases as cases_domain, journey
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
        moved = [e for e in journey.for_current().events
                 if e["kind"] == "BOARD_AUTO_MOVED" and e["customer_uid"] == uid]
        assert moved and moved[-1]["cause"] == "PTP_DATE_PASSED"
    finally:
        settings.business_date = saved
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_board_derived.py -q -k "approved or rejected or officer_cannot or own_two"`
Expected: FAIL — `answer_review` does not know `BOARD_MOVE_APPROVE`.

- [ ] **Step 3: Add the decision pair and the arm in `backend/app/cases.py`**

Beside `POWER_DECISIONS` at `:30`:

```python
# Spec 2026-09-09: the only two answers a BOARD_MOVE_ASK review takes. Deliberately not
# POWER_DECISIONS — cutting a customer's power is not an answer to a board request.
BOARD_DECISIONS = ("BOARD_MOVE_APPROVE", "BOARD_MOVE_REJECT")
```

In `answer_review`, after the `POWER_CUTOFF_ASK` arm and before the decision is
written, add:

```python
    if review["reason"] == "BOARD_MOVE_ASK":
        if decision not in BOARD_DECISIONS:
            raise CaseError("board_decision_required",
                            "A board move is approved or rejected, not answered",
                            message_th="คำขอย้ายคอลัมน์ต้องอนุมัติหรือปฏิเสธเท่านั้น",
                            allowed_decisions=list(BOARD_DECISIONS),
                            review_uid=review_uid)
        from . import journey as journey_domain
        js = journey_domain.for_current()
        pending = js.board_pending.pop(review["customer_uid"], None)
        if decision == "BOARD_MOVE_APPROVE" and pending is not None:
            pending["approved_by"] = by
            pending["approved_on"] = str(settings.business_date)
            js.board_overrides[review["customer_uid"]] = pending
```

and extend the existing guard at `:1183` so a board decision cannot be given as the
answer to some other review:

```python
    if (decision not in POWER_DECISIONS and decision not in BOARD_DECISIONS
            and review["reason"] not in ("POWER_CUTOFF_ASK", "BOARD_MOVE_ASK")):
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/cases.py backend/tests/test_board_derived.py
git commit -m "feat(board): a Manager approves or rejects a backward move"
```

---

### Task 5: A derived column cannot be deleted

**Files:**
- Modify: `backend/app/errors.py` (one more problem)
- Modify: `backend/app/main.py:757-793` (`delete_column`)
- Modify: `scripts/e2e_check.py:637-655` (check 15)
- Test: `backend/tests/test_board_derived.py`

**Interfaces:**
- Consumes: `board.DERIVED_COLUMNS` from Task 1.
- Produces: `errors.board_column_derived(column_id, derived)`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_board_derived.py`:

```python
# --- the four derived columns are not deletable -----------------------------------

@pytest.mark.parametrize("column_id", list(board.DERIVED_COLUMNS))
def test_a_derived_column_cannot_be_deleted(client, column_id):
    """Spec §9b. derive() returns one of these four; deleting one would leave the rule
    naming a column that does not exist."""
    response = client.request("DELETE", "/v1/board/columns/%s" % column_id,
                              json={"destination_column_id": board.ESCALATE})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "board_column_derived"
    assert set(body["derived_columns"]) == set(board.DERIVED_COLUMNS)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_board_derived.py -q -k derived_column_cannot`
Expected: FAIL — the endpoint currently deletes the column and returns 200.

- [ ] **Step 3: Add the problem to `backend/app/errors.py`**

```python
def board_column_derived(column_id, derived):
    return Problem(
        code="board_column_derived",
        status=422,
        title="This column is computed, not arranged",
        detail="The board rule can place a card in %r, so deleting it would leave the "
               "rule naming a column that does not exist." % column_id,
        message_th="คอลัมน์นี้ระบบคำนวณเอง ลบไม่ได้",
        error_id="DEBT-COL-0432",
        extensions={"column_id": column_id, "derived_columns": list(derived)},
    )
```

- [ ] **Step 4: Guard the endpoint in `backend/app/main.py`**

Immediately after the `if column_id not in known:` check in `delete_column`, add:

```python
    # Spec §9b: the four the rule can return are not the Owner's to remove. Any column
    # an Owner adds beyond them still deletes, and still relocates its cards.
    if column_id in board.DERIVED_COLUMNS:
        raise errors.board_column_derived(column_id, board.DERIVED_COLUMNS)
```

The relocation body below it was already converted off the deleted `_board_overlay()`
in Task 2 Step 7 and is not touched again here. This task adds the guard and nothing
else.

- [ ] **Step 5: Update e2e check 15**

`scripts/e2e_check.py` check 15 deletes `columns[0]`, which is now a derived column and
refuses. Rewrite it to assert the refusal, which is the behaviour that matters:

```python
@check(15, "a computed board column cannot be deleted",
       "the board rule can place a card in each of the four, so removing one would "
       "leave the rule naming a column that does not exist")
def check_delete_column(api, ctx):
    response = api.get("/v1/board/columns")
    columns = response.json().get("columns") or []
    ctx.require(columns, "the board has no columns to delete")
    column = columns[0]
    ctx.require(column.get("column_id"),
                "a column has no column_id - identity is the id, never the name")
    # `api.delete(path, body=None)` — the client's own signature (`e2e_check.py:140`),
    # not requests' `json=`.
    deleted = api.delete("/v1/board/columns/%s" % column["column_id"],
                         body={"destination_column_id": "col_01H90"})
    ctx.status(deleted, 422, "a computed column must refuse deletion, not strand its rule")
    ctx.require(deleted.json().get("code") == "board_column_derived",
                "the refusal must name itself, so the Owner learns why")
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/errors.py backend/app/main.py scripts/e2e_check.py \
        backend/tests/test_board_derived.py
git commit -m "feat(board): a derived column refuses deletion"
```

---

### Task 6: The screen — drag removed, the button becomes a request

**Files:**
- Modify: `frontend/src/screens/Today.jsx` — `:183` (state), `:317-350` (`moveCard`), `:1036` (caption testid), `:1419-1540` (`BoardView`), `:1545-1695` (`BoardCard`)
- Modify: `frontend/src/today.css:704`, `:724`, `:743`
- Modify: `frontend/src/i18n-today.js` — EN block near `:487`, TH block near `:959`
- Modify: `frontend/src/api.js:173`
- Test: `frontend/src/screens/Today.board.test.jsx`

**Interfaces:**
- Consumes: `POST /v1/board/moves` from Task 3 — body `{customer_uid, to_column_id, reason, by}`, response `{direction, applied, review_uid, from_column_id, to_column_id}`.
- Produces: no interface for later tasks; Task 7 only reads the i18n keys added here.

- [ ] **Step 1: Rewrite the test file's drag coverage**

`frontend/src/screens/Today.board.test.jsx` exists and its header documents three drag
defects. Replace the header with a record of why the coverage changed, keep the mount
setup and the column fixture verbatim, and replace every `fireEvent.dragStart` /
`dragOver` / `drop` assertion with these:

```jsx
// The board's move controls. This file began as coverage for three drag-and-drop
// defects; the 2026-09-09 spec removes drag entirely, so the drag assertions are gone
// and the mount coverage they brought is kept — this is still the only test that
// mounts BoardView. What it pins now is that the gesture is GONE and that the button
// path both works and refuses correctly.

it('no card is draggable', async () => {
  await mountBoard()
  const cards = document.querySelectorAll('.td-card')
  expect(cards.length).toBeGreaterThan(0)
  for (const card of cards) {
    expect(card.getAttribute('draggable')).toBeNull()
  }
})

it('the move panel offers every column except the one the card is in', async () => {
  await mountBoard()
  fireEvent.click(screen.getAllByRole('button', { name: /ย้าย/ })[0])
  const panel = await screen.findByRole('group', { name: /ย้าย/ })
  const buttons = [...panel.querySelectorAll('button')]
  expect(buttons).toHaveLength(4)
  expect(buttons.filter((b) => b.disabled)).toHaveLength(1)
})

it('a forward request sends a reason and reports that it applied', async () => {
  api.boardMove.mockResolvedValue({
    direction: 'FORWARD', applied: true, review_uid: null,
    to_column_id: 'col_01H90',
  })
  await mountBoard()
  await requestMove(/ส่งต่อผู้จัดการ/, 'ลูกค้าแจ้งว่าเลิกกิจการ')
  expect(api.boardMove).toHaveBeenCalledWith(expect.objectContaining({
    to_column_id: 'col_01H90', reason: 'ลูกค้าแจ้งว่าเลิกกิจการ',
  }))
  expect(await screen.findByText(/ย้ายแล้ว/)).toBeInTheDocument()
})

it('a backward request says it went to the manager and does not move the card', async () => {
  api.boardMove.mockResolvedValue({
    direction: 'BACKWARD', applied: false, review_uid: 'rv-0001',
    from_column_id: 'col_01H8X', to_column_id: 'col_01H8Z',
  })
  await mountBoard()
  const columnBefore = document.querySelector('.td-card').closest('[data-column]')
    .getAttribute('data-column')
  await requestMove(/นัดชำระแล้ว/, 'ลูกค้ารับปากทางโทรศัพท์')
  expect(await screen.findByText(/รอผู้จัดการอนุมัติ/)).toBeInTheDocument()
  expect(document.querySelector('.td-card').closest('[data-column]')
    .getAttribute('data-column')).toBe(columnBefore)
})

it('a request with no reason never reaches the API', async () => {
  await mountBoard()
  fireEvent.click(screen.getAllByRole('button', { name: /ย้าย/ })[0])
  const panel = await screen.findByRole('group', { name: /ย้าย/ })
  fireEvent.click([...panel.querySelectorAll('button')].find((b) => !b.disabled))
  expect(api.boardMove).not.toHaveBeenCalled()
  expect(await screen.findByText(/ต้องระบุเหตุผล/)).toBeInTheDocument()
})

it('a card the system moved by itself says so', async () => {
  await mountBoard([ITEM('cu-1', 'ลูกค้าทดสอบ 0187', 'col_01H8X',
                         { auto_moved: true, auto_moved_cause: 'PTP_DATE_PASSED' })])
  expect(await screen.findByText(/เลยวันนัดชำระ/)).toBeInTheDocument()
})

it('a card held for a manager says so and a granted one says that instead', async () => {
  await mountBoard([
    ITEM('cu-1', 'ลูกค้าทดสอบ 0187', 'col_01H8X', { board_pending_review_uid: 'rv-9' }),
    ITEM('cu-2', 'อารีย์ พงษ์ไพบูลย์', 'col_01H8Z', { board_override: true }),
  ])
  expect(await screen.findByText(/รอผู้จัดการอนุมัติ/)).toBeInTheDocument()
  expect(screen.getByText(/ผู้จัดการอนุมัติตำแหน่งนี้แล้ว/)).toBeInTheDocument()
})
```

**Three edits to the file's own scaffolding, not optional:**

1. `mountBoard()` takes no arguments today. Widen it to `async function mountBoard(items = RESPONSE.items)` and mock `api.today` with `{ ...RESPONSE, items }`. Every existing call site keeps working unchanged.
2. Delete the `transfer()` helper (`:99-110`). It exists only to stand in for jsdom's missing `DataTransfer` during a drag; with drag gone it is dead code, and a reviewer will flag it.
3. The file mounts in Thai — `renderIn('th', <Today />)`. Every string assertion above is therefore the Thai one. The column labels are served by `boardColumnLabel` from `board.col.<id>`: `col_01H8Z` is `นัดชำระแล้ว` and `col_01H90` is `ส่งต่อผู้จัดการ` (`i18n-today.js:977-980`).

Add the two helpers beside the existing `mountBoard`:

```jsx
async function requestMove(columnPattern, reason) {
  fireEvent.click(screen.getAllByRole('button', { name: /ย้าย/ })[0])
  const panel = await screen.findByRole('group', { name: /ย้าย/ })
  fireEvent.change(panel.querySelector('textarea'), { target: { value: reason } })
  fireEvent.click([...panel.querySelectorAll('button')]
    .find((b) => columnPattern.test(b.textContent)))
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/screens/Today.board.test.jsx`
Expected: FAIL — cards still carry `draggable`, the panel has no textarea.

- [ ] **Step 3: Add the strings to `frontend/src/i18n-today.js`**

Rewrite the two captions and add eight keys. English block:

```js
  'today.board.whatDragDoes': 'A card’s column is computed from the case — an overdue instalment, a promise still live, a confirmed NPL. Cards move on their own as those change. Asking for a different column is a claim that the data is wrong: toward a heavier column it applies with your reason, toward a lighter one a Manager decides.',
  'today.board.seedingSummary': 'Why is this card in this column?',
  'today.board.seedingNote': 'The column is computed from the case data the API already sends, on every read — never placed by hand. The rule, first match wins: Escalate when NPL is confirmed, an NPL type is set, the case sits in advanced negotiation or legal recovery, or DC status is retrieve-asset · Promise made when a promise is open AND its promised date has not passed · Call today when an instalment is overdue · Awaiting payment when nothing is overdue.',
  'today.board.requestMove': 'Request a move…',
  'today.board.reasonRequired': 'Say why this card belongs in a different column',
  'today.board.forwardApplied': 'Moved {name} to {column}',
  'today.board.backwardSent': 'Sent to a Manager. {name} stays in {column} until it is approved.',
  'today.board.awaitingManager': 'Waiting for a Manager',
  'today.board.autoMoved': 'Moved here by the system — {cause}',
  'today.board.overrideActive': 'A Manager approved this placement',
  'today.board.cause.PTP_DATE_PASSED': 'the promised date passed',
  'today.board.cause.ARREARS_OPENED': 'an instalment fell overdue',
  'today.board.cause.ARREARS_CLEARED': 'the arrears cleared',
  'today.board.cause.CASE_CHANGED': 'the case changed',
  'today.board.reviewBlocked': 'Answer the review already open on this case first — a board move is the least urgent of the two.',
```

Thai block:

```js
  'today.board.whatDragDoes': 'คอลัมน์ของการ์ดคำนวณจากข้อมูลเคส — งวดที่เลยกำหนด นัดชำระที่ยังไม่ถึงวัน หรือ NPL ที่ยืนยันแล้ว การ์ดจะขยับเองเมื่อข้อมูลเปลี่ยน การขอย้ายไปคอลัมน์อื่นคือการแย้งว่าข้อมูลไม่ตรง: ย้ายไปคอลัมน์ที่หนักกว่าทำได้ทันทีพร้อมเหตุผล ย้ายไปคอลัมน์ที่เบากว่าต้องให้ผู้จัดการอนุมัติ',
  'today.board.seedingSummary': 'ทำไมการ์ดนี้อยู่คอลัมน์นี้',
  'today.board.seedingNote': 'คอลัมน์คำนวณจากข้อมูลเคสที่ API ส่งมา ทุกครั้งที่อ่าน ไม่ได้จัดวางด้วยมือ เกณฑ์คือเข้าข้อแรกที่ตรง: ส่งต่อผู้จัดการ เมื่อเป็น NPL ยืนยันแล้ว มีประเภท NPL แล้ว อยู่ขั้นเจรจาขั้นสูงหรือดำเนินคดี หรือสถานะ DC เป็นยึดคืนอุปกรณ์ · นัดชำระแล้ว เมื่อมีนัดชำระเปิดอยู่และยังไม่เลยวันนัด · โทรวันนี้ เมื่อมีงวดเลยกำหนดชำระ · รอชำระ เมื่อไม่มีงวดใดเลยกำหนด',
  'today.board.requestMove': 'ขอย้าย…',
  'today.board.reasonRequired': 'ต้องระบุเหตุผลว่าทำไมการ์ดนี้ควรอยู่คอลัมน์อื่น',
  'today.board.forwardApplied': 'ย้าย {name} ไป {column} แล้ว',
  'today.board.backwardSent': 'ส่งให้ผู้จัดการแล้ว — {name} จะอยู่ที่ {column} จนกว่าจะได้รับอนุมัติ',
  'today.board.awaitingManager': 'รอผู้จัดการอนุมัติ',
  'today.board.autoMoved': 'ระบบย้ายมาเอง — {cause}',
  'today.board.overrideActive': 'ผู้จัดการอนุมัติตำแหน่งนี้แล้ว',
  'today.board.cause.PTP_DATE_PASSED': 'เลยวันนัดชำระแล้ว',
  'today.board.cause.ARREARS_OPENED': 'มีงวดเลยกำหนดชำระ',
  'today.board.cause.ARREARS_CLEARED': 'ชำระค่าค้างครบแล้ว',
  'today.board.cause.CASE_CHANGED': 'ข้อมูลเคสเปลี่ยน',
  'today.board.reviewBlocked': 'ตอบคำขอตรวจที่เปิดอยู่บนเคสนี้ก่อน — คำขอย้ายคอลัมน์ด่วนน้อยกว่า',
```

- [ ] **Step 4: Widen the API call in `frontend/src/api.js:173`**

```js
  boardMove: (payload) => post('/v1/board/moves', payload),
```

stays as it is — the caller now includes `reason` in `payload`. No change needed;
confirm by reading the line rather than editing it.

- [ ] **Step 5: Remove drag and rebuild the panel in `frontend/src/screens/Today.jsx`**

1. Delete `const [draggingUid, setDraggingUid] = useState(null)` at `:183` and every
   reference: the two props on `BoardView`, the `overCol` state and the
   `td-col--over` class, `onDragOver`, `onDrop`, `onDragStartCard`, `onDragEndCard`,
   `draggable`, `onDragStart`, `onDragEnd`.
2. Rename the caption testid at `:1036` from `board-drag-note` to `board-rule-note`
   and keep it rendering `t('today.board.whatDragDoes')`.
3. Change `moveCard(uid, toColumnId)` to `requestMove(uid, toColumnId, reason)`:

```jsx
  // A move is a request now. FORWARD applies and the card re-parents; BACKWARD is held
  // by the API and the card must NOT move — an optimistic re-parent here would show the
  // officer a placement a Manager has not granted.
  async function requestMove(uid, toColumnId, reason) {
    const idx = items.findIndex((i) => i.customer.uid === uid)
    if (idx === -1) return
    const card = items[idx]
    setProblem(null)
    try {
      const result = await api.boardMove({
        customer_uid: uid, to_column_id: toColumnId, reason, by: officer || undefined,
      })
      const destination = boardColumns.find((c) => c.column_id === toColumnId)
      const columnName = destination ? boardColumnLabel(destination, t) : toColumnId
      if (result.applied) {
        setData((d) => ({
          ...d,
          items: d.items.map((i) => (i.customer.uid === uid
            ? { ...i, board_column_id: toColumnId, board_override: true } : i)),
        }))
        setFlash(t('today.board.forwardApplied', { name: card.customer.display_name, column: columnName }))
        setPendingFocusUid(uid)
      } else {
        const current = boardColumns.find((c) => c.column_id === result.from_column_id)
        setData((d) => ({
          ...d,
          items: d.items.map((i) => (i.customer.uid === uid
            ? { ...i, board_pending_review_uid: result.review_uid } : i)),
        }))
        setFlash(t('today.board.backwardSent', {
          name: card.customer.display_name,
          column: current ? boardColumnLabel(current, t) : result.from_column_id,
        }))
      }
    } catch (e) {
      setProblem(fromError(e))
    }
  }
```

4. In `BoardCard`, replace the panel's column buttons with a reason field above them,
   and refuse an empty reason before the call is made:

```jsx
      {open && (
        <div className="td-move__panel" role="group" id={panelId} ref={panelRef}
              aria-label={t('today.board.movePanel', { name: item.customer.display_name })}
              onKeyDown={(e) => { if (e.key === 'Escape') { onToggle(); moveBtnRef.current?.focus() } }}>
          <label className="td-move__reason">
            <span>{t('today.board.reasonRequired')}</span>
            <textarea value={reason} rows={2}
                      onChange={(e) => { setReason(e.target.value); setReasonMissing(false) }} />
          </label>
          {reasonMissing && (
            <p className="td-move__error" role="alert">{t('today.board.reasonRequired')}</p>
          )}
          {columns.map((col) => {
            const current = col.column_id === item.board_column_id
            const name = boardColumnLabel(col, t)
            return (
              <button key={col.column_id} type="button" className="btn btn--sm" disabled={current}
                      aria-current={current ? 'true' : undefined}
                      aria-label={t('today.board.moveTo', { name: item.customer.display_name, column: name })}
                      onClick={() => {
                        if (!reason.trim()) { setReasonMissing(true); return }
                        onToggle()
                        onMove(uid, col.column_id, reason.trim())
                        setReason('')
                      }}>
                {name}{current ? ' ✓' : ''}
              </button>
            )
          })}
        </div>
      )}
```

   with `const [reason, setReason] = useState('')` and
   `const [reasonMissing, setReasonMissing] = useState(false)` beside the existing refs.

   **Move the panel's opening focus to the textarea.** `BoardCard`'s effect at
   `Today.jsx:1560-1562` currently reads:

```jsx
  useEffect(() => {
    if (open) panelRef.current?.querySelector('button:not([disabled])')?.focus()
  }, [open])
```

   That was right when the panel was four destination buttons and the first act was
   choosing one. It is wrong now: the first act is writing the reason, and landing on a
   destination button invites the officer to press it before the field they must fill
   even has focus — straight into the `reasonMissing` refusal. Change it to prefer the
   textarea and keep the button as the fallback, so the panel still traps focus (which
   is what makes the existing Esc handler reachable — `onKeyDown` only fires while focus
   is inside the panel):

```jsx
  useEffect(() => {
    if (!open) return
    const panel = panelRef.current
    if (!panel) return
    // The reason comes first now — it is the thing the request cannot go without.
    // Falling back to the first enabled button keeps focus inside the panel whatever
    // the markup becomes, which is what makes Esc reachable at all.
    const first = panel.querySelector('textarea') || panel.querySelector('button:not([disabled])')
    first?.focus()
  }, [open])
```

5. Add the three markers to the card's sub-line, beside the lock chip:

```jsx
      {item.board_pending_review_uid && (
        <span className="td-board-mark td-board-mark--pending">{t('today.board.awaitingManager')}</span>
      )}
      {item.auto_moved && (
        <span className="td-board-mark">{t('today.board.autoMoved', {
          cause: t(`today.board.cause.${item.auto_moved_cause}`),
        })}</span>
      )}
      {item.board_override && !item.board_pending_review_uid && (
        <span className="td-board-mark">{t('today.board.overrideActive')}</span>
      )}
```

6. Change the button label at the action row from `t('today.board.move')` to
   `t('today.board.requestMove')`.
7. Update the two call sites the rename breaks. At `:1040` the board is mounted with
   `onMove={moveCard}` — change to `onMove={requestMove}`. `BoardView` passes `onMove`
   straight down to `BoardCard`, so its signature widens from `(uid, columnId)` to
   `(uid, columnId, reason)` with no other edit.
8. `board_move_review_open` is a 409 the screen must explain rather than show raw. Note
   the access path: `fromError(e)` (`frontend/src/problem.js:36`) returns `e.problem` —
   the RFC 9457 body — so the code lives on THAT, never on the thrown error. The `catch`
   of `requestMove` becomes:

```jsx
    } catch (e) {
      const problem = fromError(e)
      setProblem(problem)
      // The officer is told what to DO, not only what failed: this refusal has exactly
      // one remedy, and it is on another screen.
      if (problem.code === 'board_move_review_open') {
        setFlash(t('today.board.reviewBlocked'))
      }
    }
```

- [ ] **Step 6: Update `frontend/src/today.css`**

Delete `.td-card[draggable] { cursor: grab; }` (`:724`) and the `.td-col--over` rule
(`:704`). Add, beside the existing `.td-move` rules:

```css
/* The move panel is a request now: a reason above the destinations, so the officer
   writes the claim before choosing where. */
.td-move__reason { display: block; margin-bottom: 8px; }
.td-move__reason > span { font: var(--caption-12); color: var(--ink-500); }
.td-move__reason textarea { width: 100%; font: var(--body-14); }
/* Same colour the drawer's own required-field hint uses (`.cd-hint--required`) — a
   refusal on this screen already has a look, and a second one would read as a
   different kind of problem. */
.td-move__error { font: var(--caption-12); color: var(--status-overdue); margin: 0 0 8px; }

/* Two of the three placement marks are quiet lines: they explain where the card is,
   they do not compete with the name or the money. */
.td-board-mark { font: var(--caption-12); color: var(--ink-500); }
/* The third is a chip, because "a Manager has not answered yet" is a state the card is
   IN, not a note about it — same shape as `.td-lock` above, which is the other
   card-level state chip on this screen. */
.td-board-mark--pending {
  display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 4px;
  background: var(--status-pending-bg); color: var(--status-pending); font: var(--caption-12);
}
```

These token names are verified against `frontend/src/tokens.css`: the vocabulary is
`--ink-400`…`--ink-900`, `--caption-12`, `--body-14`, `--status-pending`,
`--status-pending-bg`, `--status-overdue`. There is no `--sp-N` spacing scale in this
codebase — `today.css` writes spacing as literal pixels, and so does the block above.
Do not invent a token; if you need one that is not in `tokens.css`, use a literal and
say so in the commit message.

- [ ] **Step 7: Run the tests**

Run: `cd frontend && npx vitest run`
Expected: PASS across 33 files.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/screens/Today.jsx frontend/src/screens/Today.board.test.jsx \
        frontend/src/today.css frontend/src/i18n-today.js
git commit -m "feat(board): remove drag, the move button becomes a request"
```

---

### Task 7: The review queue, and the design record

**Files:**
- Modify: `frontend/src/screens/ReviewQueue.jsx:28-30`, `:100-103`
- Modify: `frontend/src/screens/ReviewQueue.test.jsx`
- Modify: `docs/design/round-4/board/B-system.md` §1.2, §1.4, §1.7
- Modify: `docs/design/round-6/00-ledger.md`

**Interfaces:**
- Consumes: the `BOARD_MOVE_ASK` reason and the `BOARD_MOVE_*` decisions from Tasks 3 and 4.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/screens/ReviewQueue.test.jsx`:

This file has its own idiom and you must follow it, not invent helpers. `reviews()`
returns the three-row fixture, `payload(rows)` wraps it in the full `meta` the screen
reads (`open`, `decisions`, `reasons`, `npl_types`, `sla_hours`, `business_date`,
`power_approver` — omit any of them and the screen renders wrong for unrelated
reasons), and `renderIn('en', …)` mounts it. The existing J3-06 test at
`ReviewQueue.test.jsx:130` is the exact template: copy its shape.

```jsx
  it('a board-move review offers only its own two decisions', async () => {
    setRole('MANAGER')
    const rows = payload()
    rows.reviews[2] = { ...rows.reviews[2], reason: 'BOARD_MOVE_ASK',
                        reason_label: 'Board move approval',
                        question: 'ขออนุมัติย้าย สมชาย จาก col_01H8X ไป col_01H8Z — ลูกค้ารับปาก' }
    rows.meta.decisions = [...rows.meta.decisions,
      { code: 'BOARD_MOVE_APPROVE', label_th: 'อนุมัติย้ายคอลัมน์', label_en: 'Approve the board move', active: true },
      { code: 'BOARD_MOVE_REJECT', label_th: 'ปฏิเสธการย้ายคอลัมน์', label_en: 'Reject the board move', active: true }]
    api.reviews.mockResolvedValue(rows)
    renderIn('en', <MemoryRouter><ReviewQueue /></MemoryRouter>)
    await screen.findByTestId('review-rv-3')
    const select = within(screen.getByTestId('review-rv-3')).getByRole('combobox', { name: 'Decision' })
    const codes = [...select.querySelectorAll('option')].map((o) => o.value).filter(Boolean)
    expect(codes).toEqual(['BOARD_MOVE_APPROVE', 'BOARD_MOVE_REJECT'])
    expect(codes).not.toContain('CONTINUE')
    expect(codes).not.toContain('POWER_CUTOFF_APPROVE')
  })
```

Row index 2 is `rv-3`, which the fixture already has as `status: 'OPEN'` — only an open
review renders the decision select.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/screens/ReviewQueue.test.jsx`
Expected: FAIL — every decision is offered.

- [ ] **Step 3: Mirror `powerDecisions` in `frontend/src/screens/ReviewQueue.jsx`**

Beside the existing helper at `:28`:

```js
export const BOARD_ASK = 'BOARD_MOVE_ASK'

// Same law as powerDecisions above: a request that is DECIDED takes only its own two
// verbs. Offering ติดตามต่อ here would close the request while the card stayed where it
// was, and the officer would read "answered" on a move nobody had granted.
//
// No `t`, and no back-fill of the REJECT code. powerDecisions synthesises
// POWER_CUTOFF_REJECT because the API does not always serve it; both BOARD_MOVE_ codes
// are in the REVIEW_DECISION dictionary, so a back-fill here would be a defence against
// a gap that does not exist — and would hide it if the dictionary ever lost one.
export function boardDecisions(decisions) {
  return (decisions || []).filter((d) => String(d.code || '').startsWith('BOARD_MOVE_'))
}
```

and at `:100-103`:

```js
  const isPowerAsk = review.reason === POWER_ASK
  const isBoardAsk = review.reason === BOARD_ASK
  const offered = isPowerAsk ? powerDecisions(decisions, t)
    : isBoardAsk ? boardDecisions(decisions)
    : decisions
```

- [ ] **Step 4: Record the reversal in `docs/design/round-4/board/B-system.md`**

Three edits, none deleting the history:

- **§1.2** — correct the table to the rule that runs. Clause 1 reads contract status
  `NON_PERFORMING`, not `aging_bucket == 'NPL_CONFIRMED'`, and does **not** include
  `manager_review_open > 0`; clause 2 is an open PTP whose promised date has not
  passed, not `next_action == 'FOLLOW_PTP'` or `tier == 'PTP_DUE_TODAY'`; clause 3 is
  an overdue instalment, not `next_action == 'SEND_REMINDER'`; clause 4 is the absence
  of arrears. Add a line recording that the document and the shipped code had diverged
  on this since round 4, and that `manager_review_open` is excluded by name because it
  is circular under the override mechanism.
- **§1.4** — restate: the ten hand placements and the seeding pass are both gone; the
  column is computed on every read.
- **§1.7** — retitle to
  `### 1.7 Where the rule runs — SUPERSEDED 2026-09-09` and keep the original text
  intact beneath a note giving the three objections and how each is answered, pointing
  at spec §9f. A later reader must find the old ruling and why it fell, not a gap.

- [ ] **Step 5: Append the round-6 ledger entries**

Add to `docs/design/round-6/00-ledger.md` one entry per ruling this work settled: the
board reflects the data rather than an officer's placement; severity is not the display
order; a backward move goes to a Manager through the existing queue; an override dies
when the data changes; `B-system.md` §1.7 is superseded; `manager_review_open` is
excluded by name; the four derived columns refuse deletion; and the cost — last round's
drag repair is discarded.

- [ ] **Step 6: Run everything**

Run: `./scripts/verify_all.sh`
Expected: backend and frontend green, e2e 29/29. Paste the three counts into the commit
message. Backend rises from 498 by the new file's tests; frontend rises from 431 by the
rewritten board tests and the ReviewQueue test; e2e stays at 29 — check 15 changed its
assertion, it did not add one.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/ReviewQueue.jsx frontend/src/screens/ReviewQueue.test.jsx \
        docs/design/round-4/board/B-system.md docs/design/round-6/00-ledger.md
git commit -m "feat(board): the review queue decides a move, and the record is corrected"
```
