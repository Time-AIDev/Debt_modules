# Board columns become derived, and a manual move becomes a request

**Written 2026-09-09.** Design spec for the Today board's move controls, arising from
Arina's ruling: *"On Kanban board made user cannot easily move customer card status.
they can limit a move cannot drag n drop, just use only move button to move. if want
to revert order status back need to ask manager. made it automate move by duedate."*

Five decisions were taken during brainstorming and are binding on this spec:

| # | question | ruling |
|---|---|---|
| D1 | Is the board a personal record or a real status? | **The board reflects the data. An officer does not place cards.** |
| D2 | Does the move button survive? | **Yes — as an exception path, not a move.** Backward needs a Manager. |
| D3 | Which due dates move a card? | **The PTP promise date and the instalment due date.** Not `next_action_on`. |
| D4 | When does the column get computed? | **On every read**, with an event written when the served value changes. |
| D5 | How long does an approved override last? | **Until the derived value changes.** |

---

## 1. What is wrong today

`board_column_id` is a stored field. `fixtures.py::_seed_board_columns` computes it
once at seed time and writes it onto the customer; `journey.board_overlay` then lets
any caller of `POST /v1/board/moves` overwrite it, per session, with no role check, no
ordering rule, no reason and no record beyond the response body.

Four specific consequences:

1. **The placement goes stale the moment it is written.** A promise made on 2026-09-01
   for 2026-09-05 leaves the card in *Promise made* on 2026-09-30. Nothing recomputes.
2. **Anyone can put any card anywhere.** `routers/journey.py::board_move` validates
   only that the destination id exists. An OFFICER can move a confirmed-NPL card out
   of *Escalate* into *Awaiting payment* and the API records it as a fact.
3. **The seed rule ranks on an officer-settable field.** `_derive_board_column` sends
   a card to *Awaiting payment* when `next_action == "SEND_REMINDER"` — a value an
   officer sets. The column an officer's own choice produces is not evidence.
4. **The declared automation has never run.** `cases.py:1066 detect_broken_ptps`
   documents itself as *"Nightly (02:30) and on demand"* and has **zero callers** in
   the repository. A promise whose date has passed is not marked BROKEN unless a test
   calls the function directly.

The on-screen caption `today.board.whatDragDoes` (ruling R-CAP-1) tells the officer the
truth about today's design — *"Moving a card here is your own record of how far today's
handling has got. It does not change the priority order, the mandatory next action, the
collection ladder, or the exported work book."* That caption becomes false under this
spec and is rewritten in §7.

---

## 2. The model

`board_column_id` stops being stored state and becomes a function of the case:

```
column(customer) = override.to_column   when a live approved override exists
                 = derive(...)          otherwise
```

`CustomerFixture.board_column_id` is **deleted**, along with the seeding pass that
writes it. An earlier draft of this spec kept the field as "the seed's own record"; a
grep settles it instead — the stored column has exactly four readers,
`main.py:710`, `main.py:775`, `routers/journey.py:233` and `routers/journey.py:499`,
and §8 replaces all four. Nothing else in the backend reads it: not the workbook
exports, not `book.py`, not any test (`test_api_gaps.py:55` asserts the *served* value
is one of the four valid ids, which still holds). A field written at seed time and read
nowhere is dead state, and this codebase treats a second mechanism for a job as a MAJOR
finding — the same argument that deletes `board_overlay` deletes this.

Four symbols go with it, all in `fixtures.py`: the dataclass field (`:133`), its 14
hand-placed keyword arguments in the customer literals, `_derive_board_column`,
`_seed_board_columns`, and `_seed_time_case_facts` — the last used by nothing else
(verified: two hits in the repository, its definition and its single call). The
ruling-45 comment block at `fixtures.py:210` is **rewritten, not deleted**, to record
that the seed-time pass it authorises has been superseded by request-time derivation
and why, so a later reader finds the history rather than a gap.

`journey.board_overlay` — `customer_uid -> column_id`, today's free-for-all store — is
**replaced**, not extended, by `journey.board_overrides`:

```python
# journey.JourneyState.__init__
self.board_overrides = {}    # customer_uid -> override record
```

An override record:

```python
{
  "customer_uid": str,
  "to_column_id": str,          # the column the officer asked for
  "derived_at_grant": str,      # what derive() returned when the override was granted
  "direction": "FORWARD" | "BACKWARD",
  "reason": str,                # required, non-blank, in either direction
  "requested_by": str,          # officer uid
  "requested_on": str,          # business date
  "review_uid": str | None,     # set for BACKWARD, None for FORWARD
  "approved_by": str | None,    # manager uid, BACKWARD only
  "approved_on": str | None,
}
```

`board_overlay` is deleted from `JourneyState`. It has **four** functional sites today,
all named in §8, and **eight further mentions in comments** — `cases.py:109`,
`fixtures.py:224`, `journey.py:76`, `journey.py:104`, `main.py:664`, `main.py:673`,
`routers/settings.py:255`, `routers/journey.py:215` — which cite it as the reference
example of the per-session overlay pattern that rulings 39/40/43 established. Those
comments go stale the moment the field is deleted. They are updated to cite
`officer_overlay` or `recovery_overlay`, which keep the pattern, rather than left
pointing at a name that no longer exists. No test references `board_overlay`.

---

## 3. The derivation

A new module `backend/app/board.py` owns the rule. `fixtures.py` imports it for
seeding; the request path imports it for serving. One rule, one place.

```python
# backend/app/board.py

CALL_TODAY       = "col_01H8X"
AWAITING_PAYMENT = "col_01H8Y"
PROMISE_MADE     = "col_01H8Z"
ESCALATE         = "col_01H90"

DERIVED_COLUMNS = (CALL_TODAY, AWAITING_PAYMENT, PROMISE_MADE, ESCALATE)

# Severity, which is NOT the column's display `order`. `order` is the reading
# order of the desk (call first, escalations last); this is how bad the case is.
SEVERITY = {AWAITING_PAYMENT: 0, PROMISE_MADE: 1, CALL_TODAY: 2, ESCALATE: 3}


def derive(*, npl_confirmed, npl_type, recovery_stage, dc_status,
           open_ptp_promise_date, dpd, business_date):
    """The board column a case's own data implies. Every input is either money-engine
    output or a field an officer cannot set alone. First match wins."""
    if (npl_confirmed or npl_type
            or recovery_stage in ("ESCALATE", "RECOVERY")
            or dc_status == "RETRIEVE_ASSET"):
        return ESCALATE
    if open_ptp_promise_date is not None and open_ptp_promise_date >= business_date:
        return PROMISE_MADE
    if dpd is not None and dpd > 0:
        return CALL_TODAY
    return AWAITING_PAYMENT
```

### Where each input comes from

| input | source | note |
|---|---|---|
| `npl_confirmed` | `"NON_PERFORMING" in {cases.contract_field_of(c, "status") for c in customer.contracts}` | session-scoped read, ruling 43 |
| `npl_type` | `cases.for_current().cases[uid]["npl_type"]` | Manager-only field (`cases.py:783`) |
| `recovery_stage` | `journey.for_current().recovery_overlay.get(uid, customer.recovery_stage)` | **overlay-aware — see §9c** |
| `dc_status` | `cases.for_current().cases[uid]["dc_status"]` | |
| `open_ptp_promise_date` | `cases.for_current().ptps[case["open_ptp_uid"]]["promise_date"]`, as a `date`, or `None` | **D3, due date one** |
| `dpd` | the `oldest` already computed by `main._customer_aggregate` | **D3, due date two** |
| `business_date` | `settings.business_date` | the prototype's clock |

### How the two due dates move a card

**The promise date.** `open_ptp_promise_date >= business_date` is a *live* promise.
The day after the promised date, the comparison fails and the card leaves *Promise
made* on the next read — no job, no officer action. This is the automation D4 asks for
and it is why `detect_broken_ptps` having no caller stops mattering for the board.
(It still matters for the PTP's own `BROKEN` status, which this spec does not change.)

**The instalment due date.** `dpd` is computed by `money/dpd.py` from the amortisation
schedule's `due_date` values. `dpd > 0` means an instalment came due and was not paid.
The card is in *Call today*. When a payment clears and `dpd` returns to 0, the card
returns to *Awaiting payment* on the next read.

### What changes from the seed rule

`fixtures.py::_derive_board_column` is **replaced by** `board.derive`, not wrapped. Three
substantive differences:

- The `next_action == "SEND_REMINDER"` term is **removed.** It ranked on an
  officer-settable field. *Awaiting payment* is now the absence of arrears, which is
  the money engine's answer, not an officer's.
- The `open_ptp` term **gains its date comparison.** Today an open PTP holds the card
  in *Promise made* forever; now only until the promised day.
- The `dc_status == "PTP"` arm of the *Promise made* clause is **removed.** *(Recorded
  2026-09-09, after the whole-branch review found it undeclared — the spec had said
  two differences and shipped three.)* `dc_status` is officer-settable, so this is the
  same argument that removed `SEND_REMINDER`, applied to the same clause: a promise
  holds a card because a **dated** promise exists, not because someone set a status
  field to say one does. The observable change: `derive(dc_status="PTP",
  open_ptp_promise_date=None, dpd=5)` now returns *Call today* where the seed rule
  returned *Promise made*.

`_seed_board_columns` keeps its job and calls `board.derive` with seed-time facts, so
the seeded value and the served value agree on day one. `docs/design/round-4/board/B-system.md §1.2` and
`§1.4` describe the old rule and are updated with it.

---

## 4. What the move button does

`ย้าย…` no longer moves a card. It opens a request, and the request's direction decides
what happens.

```python
def direction_of(requested, current):
    """FORWARD only when the officer asks for a column the data ranks as WORSE
    than where the case already sits. Everything else is a Manager's call."""
    if requested == current:
        raise BoardError("board_move_same_column")
    if requested not in SEVERITY or current not in SEVERITY:
        return "BACKWARD"                       # an Owner-added column — see below
    return "FORWARD" if SEVERITY[requested] > SEVERITY[current] else "BACKWARD"
```

**FORWARD** — the officer is claiming the case is worse than the data has caught up to
(a customer said they are insolvent; a device was found removed). Applies immediately.
A non-blank reason is required. An override record is written with
`direction: "FORWARD"`, `review_uid: None`.

**BACKWARD** — the officer is claiming the case is better than the data says. This is
the move that makes a desk look healthier than it is, and it is the one Arina named.
**Nothing moves.** A review is raised, the card shows *รอผู้จัดการอนุมัติ*, and the card
stays where `derive()` put it until a Manager answers.

**Columns outside the derived four.** `SEVERITY` ranks only the four columns
`derive()` can return. An Owner may add a fifth column through
`GET /v1/board/columns`' own registry, and a request naming it has no rank to compare —
indexing `SEVERITY` would raise. Such a request is **always BACKWARD**: it departs from
the derived set entirely, which is the largest claim an officer can make about a case,
so a Manager signs it. The same arm covers the mirror case, a card sitting on an
Owner-added column by an earlier override.

The four severities are distinct, so `requested == current` and equal severity are the
same condition, and it is refused before `direction_of` is reached. There is no third
outcome.

### Why severity is not `order`

The four columns carry `order` 1–4: Call today, Awaiting payment, Promise made,
Escalate. That is the desk's reading order — what to work first. Under §3, *Awaiting
payment* is the **healthy** column (nothing overdue) and *Call today* is the **overdue**
one. Ranking reversal on `order` would make a move from *Call today* (1) to *Awaiting
payment* (2) a forward move, when it is precisely the gaming move to stop. `SEVERITY`
is therefore a separate mapping and `order` is left alone.

Two worked cases:

- *Call today* → *Promise made* is BACKWARD (2 → 1). An officer claiming a promise that
  no PTP record supports. Manager.
- *Promise made* → *Call today* is FORWARD (1 → 2). The promise broke and the officer
  wants the case worked today. Applies with a reason.

---

## 5. The approval path

No new approval machinery. The existing review queue is the mechanism.

**Raise.** `cases.request_review(state, case, "BOARD_MOVE_ASK", question, by=officer)`
— the same call `POWER_CUTOFF_ASK` uses (`cases.py:1274`). A `BOARD_MOVE_ASK` value is
added to the `REVIEW_REASON` dictionary in `dictionaries.py:85`:

```python
_v("BOARD_MOVE_ASK", "ขออนุมัติย้ายคอลัมน์", "Board move approval"),
```

**Answer.** `POST /v1/reviews/{uid}:answer`, unchanged route, Supervisor/Manager/Owner
only (`cases.answer_review` already refuses everyone else at `cases.py:1130`).
`answer_review` gains a `BOARD_MOVE_ASK` arm beside the `POWER_CUTOFF_ASK` arm it
already has:

- it accepts only `BOARD_MOVE_APPROVE` / `BOARD_MOVE_REJECT`, refusing a narrative
  answer the way a cut-off request already does;
- on `BOARD_MOVE_APPROVE` it writes the override record with `approved_by` and
  `approved_on`;
- on `BOARD_MOVE_REJECT` it writes nothing and the card stays derived.

The decisions are their own pair, not the power one. `POWER_DECISIONS` is
`("POWER_CUTOFF_APPROVE", "POWER_CUTOFF_REJECT")` (`cases.py:30`) — codes specific to
cutting a customer's power, which must never be selectable as the answer to a board
request. Two values join the `REVIEW_DECISION` dictionary beside them:

```python
_v("BOARD_MOVE_APPROVE", "อนุมัติย้ายคอลัมน์", "Approve the board move"),
_v("BOARD_MOVE_REJECT",  "ปฏิเสธการย้ายคอลัมน์", "Reject the board move"),
```

and `cases.py` gains `BOARD_DECISIONS = ("BOARD_MOVE_APPROVE", "BOARD_MOVE_REJECT")`
mirroring the constant above it. `answer_review`'s existing guard at `cases.py:1183` —
`if decision not in POWER_DECISIONS and review["reason"] != "POWER_CUTOFF_ASK"` — is
extended so a board decision is not accepted as the answer to some other review.

**Render.** ReviewQueue already lists open reviews and renders their reason label from
the dictionary, so a `BOARD_MOVE_ASK` review appears there with no screen change beyond
the new label and the from/to columns in the question text.

---

## 6. The audit trail, and when an override dies

**D4 — the card moved by itself.** The session records the last column it served per
customer, `journey.board_last_served` (`customer_uid -> column_id`). When a read
computes a column different from the recorded one, it appends to the same
`state.events` list `PTP_BROKEN` uses:

```python
{"kind": "BOARD_AUTO_MOVED", "customer_uid": uid,
 "from_column_id": previous, "to_column_id": current,
 "cause": "PTP_DATE_PASSED" | "ARREARS_OPENED" | "ARREARS_CLEARED" | "CASE_CHANGED",
 "on": str(settings.business_date)}
```

and updates the record. The card carries `auto_moved: true` and the cause on the wire
for one read, so the officer is told *why* the card is somewhere new rather than finding
it moved.

`cause` is a function of the transition and the current facts — the previous inputs are
not stored, so it is never inferred from them:

```python
def cause_of(previous, current, *, open_ptp_promise_date, business_date):
    if (previous == PROMISE_MADE and current != PROMISE_MADE
            and open_ptp_promise_date is not None
            and open_ptp_promise_date < business_date):
        return "PTP_DATE_PASSED"
    if previous == AWAITING_PAYMENT and current == CALL_TODAY:
        return "ARREARS_OPENED"
    if previous == CALL_TODAY and current == AWAITING_PAYMENT:
        return "ARREARS_CLEARED"
    return "CASE_CHANGED"
```

`CASE_CHANGED` is the honest answer for every transition the three named causes do not
explain — an NPL confirmation, a DC status, a recovery move. It is a real value, not a
fallback that hides a missing branch.

**D5 — the override dies when the data changes.** An override stores
`derived_at_grant`. On every read the column function compares it to the current
`derive()`:

```python
current_derived = board.derive(...)
override = state.board_overrides.get(uid)
if override and override["derived_at_grant"] != current_derived:
    del state.board_overrides[uid]
    state.events.append({"kind": "BOARD_OVERRIDE_EXPIRED", ...})
    override = None
return override["to_column_id"] if override else current_derived
```

A card cannot be pinned against reality: the moment a payment clears, a promise lapses,
or an NPL is confirmed, the override falls away and the data wins. This is the rule that
keeps §2 honest — without it, one approved override freezes a card permanently.

---

## 7. What is removed from the screen

**Drag and drop, entirely.** In `frontend/src/screens/Today.jsx`: the `draggable`
attribute, `onDragStart`, `onDragEnd`, `onDragOver`, `onDrop`, the `draggingUid` state
and its two setters, the `overCol` drop-target highlight, and the `dataTransfer`
handling. In `frontend/src/today.css`: `.td-card[draggable] { cursor: grab; }` and the
drop-target column rule.

**Two captions are now false and are rewritten in both languages.**

`today.board.whatDragDoes` — currently *"Moving a card here is your own record… It does
not change the priority order, the mandatory next action, the collection ladder, or the
exported work book."* Replaced by a statement of the new law: the column is computed
from the case, a move is a request, and a move toward a lighter column needs a Manager.
The `data-testid="board-drag-note"` is renamed `board-rule-note`.

`today.board.seedingNote` — recites the old rule verbatim in EN and TH, including
*"Awaiting payment when the next action is a reminder"*, which §3 deletes. Rewritten to
recite `board.derive`, including both due dates.

New strings, EN and TH both:

| key | purpose |
|---|---|
| `today.board.requestMove` | the button's new label — a request, not a move |
| `today.board.reasonRequired` | reason field label, both directions |
| `today.board.forwardApplied` | flash: the move applied |
| `today.board.backwardSent` | flash: sent to the Manager |
| `today.board.awaitingManager` | the card's pending marker |
| `today.board.autoMoved` | the card's "this moved by itself" marker, with cause |
| `today.board.overrideActive` | the card's "a Manager approved this placement" marker |
| `today.board.reviewBlocked` | refusal when another review is already open (§9a) |

---

## 8. The read sites

`board_overlay` has four functional sites. Every one changes:

| site | what it does today | after |
|---|---|---|
| `main.py:710` | `/v1/today-list` serves `_board_overlay().get(uid, customer.board_column_id)` | `board.column_for(customer)` |
| `routers/journey.py:233` | the customer payload serves `state.board_overlay.get(uid, customer.board_column_id)` | `board.column_for(customer)` |
| `routers/journey.py:499-500` | `POST /v1/board/moves` reads `previous` and writes the destination unconditionally | becomes the request endpoint of §4 — reads `board.column_for`, writes an override or raises a review |
| `main.py:772` | `delete_column` reads every customer's column and rewrites the overlay in bulk | refuses the four derived columns (§9b); the bulk rewrite goes with them |

`main.py:658-660`'s `_board_overlay()` helper is deleted with the field. The two serving
sites become the same call, so the divergence §9c describes for `recovery_stage` cannot
open up for `board_column_id`.

---

## 9. Conflicts this creates, and the rulings

**a. One open review per case.** `cases.py:1084` refuses a second review while one is
open on a case. An officer whose case already carries an open NPL or power-cut-off
review cannot request a board move.

> **Ruling:** refuse the board-move request and name the review that is blocking it, in
> the RFC 9457 problem body. A board move is the least urgent of the three, and a second
> approval queue for the same job is the duplicated-pattern defect this codebase treats
> as MAJOR. The officer waits for the open review to be answered.

**b. `DELETE /v1/board/columns/{id}`** reassigns every card standing on a column and
then drops the column. Under §3 the derivation returns one of four fixed ids, so
deleting one leaves `derive()` naming a column that does not exist, and the reassignment
it performs is undone by the next read.

> **Ruling:** the endpoint refuses any id in `board.DERIVED_COLUMNS`, with a 422 naming
> the four. It keeps working for any column an Owner adds beyond them. The alternative —
> a fallback when `derive()` names a missing column — invents a failure mode to serve a
> capability nobody has asked for.

**c. `recovery_stage` has two answers today.** `journey.py:234` reads it overlay-aware
(`state.recovery_overlay.get(uid, customer.recovery_stage)`); `main.py:718` reads
`customer.recovery_stage` raw. The derivation depends on this field, so on the
`/v1/today-list` path a recovery move would not reach the board.

> **Ruling:** `board.column_for` takes the overlay-aware read on both paths. The raw
> read at `main.py:718` — the `"recovery_stage"` field of the item payload, a separate
> line from the board column — is a pre-existing divergence outside this spec's scope
> and is left as found, with a note in the ledger.

**d. `Today.board.test.jsx`** (245 lines, untracked, written last round) exists to
cover the three drag defects Arina reported as *"drag and drop, especially on Promise
made"*. §7 removes the feature it tests.

> **Ruling:** keep the file and its mount coverage — it is the only test that mounts
> `BoardView` at all — and replace the drag assertions with derived-column and
> request-path assertions. The file was never committed, so nothing is lost from
> history. Its header comment is rewritten to record why the drag coverage went away.

**e. Last round's drag repair is discarded.** Three real defects were found and fixed;
this spec deletes the surface they were on. Recorded as a cost of the decision, not an
argument against it.

**f. `docs/design/round-4/board/B-system.md §1.7` forbids this spec's central move.**
The section is titled *"Where the rule runs — seed time, once, never per request"* and
states: ***"FORBIDDEN: deriving the column at request time."*** It gives three reasons,
each load-bearing at the time it was written. This spec reverses the ruling, so each is
answered rather than stepped over.

> *1. "The card would move by itself. A request-time rule would silently re-file a card
> the officer had deliberately placed, and the officer would have no way to tell their
> own drag from the system's."*

Answered by the design, not waived. The card moving by itself is now the **requirement**
(D3, D4) — Arina asked for it in the words *"made it automate move by duedate"*. The
objection's real content is the second clause: the officer could not tell their move from
the system's. Under this spec there is no drag to confuse it with, a move is a request
with a recorded direction and reason, and §6 writes `BOARD_AUTO_MOVED` with a cause and
marks the card. The officer is told which moves were theirs and which were the data's.

> *2. "It would fight `board_overlay`. A second placement mechanism evaluated beside it
> is a second pattern for the same job — a MAJOR finding waiting to happen."*

Answered by deletion. §2 **removes** `board_overlay` from `JourneyState`. There is no
second mechanism because the first one is gone: `board.column_for` is the only thing that
answers "which column", and the override record is subordinate to it — §6 expires an
override the moment the derivation disagrees. This spec would be indefensible if it kept
both; it keeps one.

> *3. "Clause 1 reads a band-set-dependent code. `aging_bucket == 'NPL_CONFIRMED'` is
> defined by the active band set, and `PUT /v1/config {band_set_code}` rewrites 5 codes
> into 7 different ones. Evaluated per request, the whole board reshuffles when a tester
> changes band set."*

This one does not apply to §3's rule, and did not apply to the shipped code either. The
`derive()` in §3 takes `npl_confirmed` from the **contract status** —
`"NON_PERFORMING" in {contract_field_of(c, "status")}` — which is not band-set derived
and does not move when `band_set_code` changes. `aging_bucket` is not an input. A tester
switching band sets reshuffles no cards. The constraint is nonetheless binding as a
constraint, and §11 pins it: a test changes `band_set_code` and asserts every card's
column is unchanged.

> **Ruling:** §1.7 is superseded for the board column. Reasons 1 and 2 are answered by
> this design; reason 3 does not reach it and is pinned by a test. `docs/design/round-4/board/B-system.md`
> is updated with the reversal recorded in place — §1.7 is rewritten rather than deleted,
> so a later reader finds the old ruling and why it fell, not a gap.

**g. That document's §1.2 and the shipped code already disagree, and one of the clauses
would make this spec eat itself.** `B-system.md §1.2` clause 1 sends a card to *Escalate*
when `aging_bucket == 'NPL_CONFIRMED'` **or** … **or** `manager_review_open > 0`. The
implemented `fixtures.py::_derive_board_column` has neither the `aging_bucket` term (it
reads contract status, per f above) nor the `manager_review_open` term at all. Clause 2
likewise lists `next_action == 'FOLLOW_PTP'` and `tier == 'PTP_DUE_TODAY'`, which the code
does not read.

The `manager_review_open` clause is not merely absent — under this spec it would be
**circular**. A backward request raises a review; the review makes `manager_review_open`
non-zero; the card jumps to *Escalate*; the derived value has now changed, so §6 expires
the override the Manager approves a moment later. The card would refuse to hold the
placement it was just granted.

> **Ruling:** the shipped code is the truth and §3 is written from it. `manager_review_open`
> is **excluded from `derive()` by name**, with the circularity recorded in a comment in
> `board.py` so it is not helpfully re-added later. §11 pins it: a case with an open review
> derives the same column it derived without one. `B-system.md §1.2` is corrected to
> describe what runs.

---

## 10. Errors

New RFC 9457 problems, in `errors.py`, following the existing shape:

| code | status | when |
|---|---|---|
| `board_move_reason_required` | 422 | a request in either direction with a blank reason |
| `board_move_same_column` | 422 | requested column equals the current column |
| `board_move_review_open` | 409 | §9a — another review is open on the case; names it |
| `board_column_derived` | 422 | §9b — an attempt to delete one of the four derived columns |

`destination_column_unknown` is kept as-is for an unknown destination id.

---

## 11. Testing

**The behaviours that must be pinned:**

*Derivation.* Each of the four branches, from real case data. The promise-date boundary
on all three sides — promised date in the future, equal to the business date, and one
day past. `dpd` crossing zero in both directions. A confirmed NPL beating a live promise.

*Direction.* Every ordered pair of the four columns classified FORWARD or BACKWARD, so
the `SEVERITY`-not-`order` decision is pinned against a future reader who assumes they
are the same. Equal-column refusal.

*Forward.* Applies at once; override written with `review_uid: None`; blank reason
refused with `board_move_reason_required`.

*Backward.* Nothing moves; a `BOARD_MOVE_ASK` review is raised; the card reports
pending; a Manager `APPROVE` writes the override and the card moves; a `REJECT` leaves
it derived; an OFFICER answering is refused by the existing role check.

*Override lifetime.* An approved override survives a read where nothing changed, and is
gone from the read after the underlying `derive()` changes — with `BOARD_OVERRIDE_EXPIRED`
in the events.

*Automatic move.* Advance `settings.business_date` past a promise date and read: the
card is in a new column and `BOARD_AUTO_MOVED` is in the events with the right cause.

*Refusals.* §9a with another review open; §9b deleting a derived column.

*The two constraints inherited from the superseded ruling (§9f, §9g).* `PUT /v1/config
{band_set_code}` is applied and every card's column is asserted unchanged — the rule reads
contract status, never `aging_bucket`. And a case carrying an open review derives the same
column it derives without one, so `manager_review_open` cannot creep back in as an input.

*Screen.* No `draggable` attribute anywhere in the board. The request panel offers the
three columns that are not the current one. The pending marker renders. The two rewritten
captions render in both languages.

**Baseline to hold:** `./scripts/verify_all.sh` — 498 backend, 431 frontend across 33
files, 29 e2e. The frontend and e2e counts change with the screen work; the plan states
the new numbers, and the test-file budget is Arina's to authorise before execution.

---

## 12. Files

**Created**

- `backend/app/board.py` — `DERIVED_COLUMNS`, `SEVERITY`, `derive`, `column_for`, `direction_of`
- `backend/tests/test_board_derived.py` — §11's backend cases

**Modified**

- `backend/app/fixtures.py` — `_derive_board_column` deleted; `_seed_board_columns` calls `board.derive`
- `backend/app/journey.py` — `board_overlay` → `board_overrides`; add `board_last_served`
- `backend/app/main.py` — `/v1/today-list` board column; `delete_column` refusal (§9b); `_board_overlay` removed
- `backend/app/routers/journey.py` — customer payload board column; `board_move` becomes the request endpoint
- `backend/app/cases.py` — `answer_review` gains the `BOARD_MOVE_ASK` arm
- `backend/app/dictionaries.py` — `BOARD_MOVE_ASK` in `REVIEW_REASON`;
  `BOARD_MOVE_APPROVE` and `BOARD_MOVE_REJECT` in `REVIEW_DECISION`
- `backend/app/errors.py` — the four problems in §10
- `frontend/src/screens/Today.jsx` — drag removed; request panel; pending/auto/override markers
- `frontend/src/screens/Today.board.test.jsx` — §9d
- `frontend/src/today.css` — drag styles removed; marker styles
- `frontend/src/i18n-today.js` — two rewrites, eight new keys, EN and TH
- `frontend/src/screens/ReviewQueue.jsx` — `BOARD_MOVE_ASK` rendering
- `docs/design/round-4/board/B-system.md` — §1.2 corrected to the rule that runs (§9g),
  §1.4 restated, §1.7 rewritten to record that it is superseded and why (§9f)
- `scripts/e2e_check.py` — the board assertions

---

## 13. Out of scope, stated so it is not assumed

- **The Recovery board.** `POST /v1/recovery-board/moves` has its own stage ladder and
  its own reversal-reason rule. Untouched here.
- **`detect_broken_ptps` gaining a caller.** The board no longer depends on it, but the
  PTP's own `BROKEN` status still does. A separate decision.
- **`main.py:718`'s raw `recovery_stage` read.** §9c — noted, left as found.
- **Persistence.** Overrides live in session state like everything else in this
  prototype. The database plan (`docs/archive/superpowers/plans/`) covers durability.
