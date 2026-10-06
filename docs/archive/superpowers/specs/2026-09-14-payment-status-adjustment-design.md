# Design — a person may change the case's payment status, with a reason

**Written 2026-09-14** through `superpowers:brainstorming`, against branch `design-team` at
`10e40bc`. Every decision below was made by Arina in that session. **Nothing here has been
built.**

---

## 0. Standing

Arina, 2026-09-14:

> "made the payment status of entirely contract can adjust with reason and keep in the activity log."

**This overrules part of Requirements Amendment v2.6 §3.6 (REQ-COL-075)**, which reads:
"payment_status is computed by the system: CURRENT, LATE, NPL, CLOSED, NOT_INSTALLED."
After this change the system still works the status out, but a person may change it with a reason.
The system's own answer is kept beside the person's value and stays on screen. The other half
of §3.6 does not change: payment_status and dc_status stay two separate fields, and neither one
sets the other.

The supersession is recorded here, in the commit message, and at the code site
(`cases.set_payment_status`).

---

## 1. What is true of the tree today

Everything below was read or measured, not assumed.

**1.1 — The payment status is worked out once.** `cases._payment_status(customer)` runs when a
session's cases are seeded (`cases.py` `_seed`), and nothing writes `case["payment_status"]` again.

**1.2 — Contract changes do not reach it.** A contract's status changes in three places, all through
the one write path `cases._set_contract_fields`: an NPL declaration (`routers/journey.py`,
ladder advance), an NPL confirmed from a manager review, and a write-off. None of them updates the
case. Measured: advancing C-002032 to NPL_DECLARED_90 returned 200, and the case still read
`LATE`.

**1.3 — The model to copy already exists.** `cases.set_dc_status` refuses a missing reason
(`reason_required`) and a change to the same value (`status_unchanged`). It writes a
`DC_STATUS_SET` event with `from`, `code`, `by`, `reason` and `on`, and it calls
`audit.describe(act="DC_STATUS_SET", ...)`. The case page form is a SearchSelect with a reason box
and a Save button, and the reason box and button only appear once a value is chosen.

**1.4 — The case page is at its density cap.** `density.test.jsx` measured 97 of 97 for a
pre-contact case with the overview, and 116 of 116 for a worked case. Any new always-visible element
fails it.

**1.5 — Many screens read the field.** Today's order and hiding of closed cases (`today.py`),
Work Book's filter and CSV (`routers/today.py`), the weekly report's counts (`reports.py`), the NPL
list's payment-status rows (`routers/journey.py`), the SOP step (`sop.py`), and the NPL type gate
(`cases.set_npl_type` refuses unless the status is `NPL`).

---

## 2. Decisions (Arina, 2026-09-14)

| # | Question | Options and their cost | Chosen |
|---|---|---|---|
| 1 | Which payment status? | Case status (overrules v2.6 §3.6 and moves other screens) · each cycle's status (money totals would disagree with the changed cycles) · both (twice the cost) | **Case status** |
| 2 | Who may change it? | Anyone, like dc_status (the status that sets Today's order can be changed by the person it measures) · Supervisor, Manager, Owner · Manager and Owner only | **Anyone** |
| 3 | The system's answer changes later — what happens to a person's change? | System wins, logged (a person may need to change it again) · the person's change stays (a paid customer can stay "late" for good) | **System wins, logged** |
| 4 | Where does the control go, given the density cap? | Open dropdown like dc_status (test edit, caps about +7) · small fold (test edit, caps +2) · inside the history fold (no test edit, hard to find) | **Open dropdown** |
| 5 | Which cases re-check when a contract changes? | Every case (also fixes 1.2; other screens change after a declaration or write-off) · only cases a person changed (two customers declared the same way can show different statuses) | **Every case** |
| 6 | Branch | Commit the overview work first · build on top of it uncommitted · worktree off HEAD | **Commit first** — done as `54c268e` and `10e40bc` |

---

## 3. Design

### 3.1 What the case holds

`_blank_case` gains four fields:

| Field | Meaning |
|---|---|
| `payment_status` | Unchanged name. **The value every screen reads**: a person's change while it stands, the system's answer otherwise. |
| `payment_status_system` | The system's own answer, `_payment_status(customer)`, as last worked out. It is seeded with the same value as `payment_status`. |
| `payment_status_set_by` | Who made the change that stands. `None` when no person's change stands. |
| `payment_status_reason` | That person's reason. `None` when no person's change stands. |

A person's change **stands** exactly when `payment_status_set_by` is not `None`. A pre-install case
has no customer in the book, so its `payment_status_system` stays the seeded value.

### 3.2 The act — `cases.set_payment_status(state, case, code, by, reason)`

Checked in this order. Each refusal is a `CaseError` with a Thai message:

1. `code` is not one of `CURRENT, LATE, NPL, CLOSED, NOT_INSTALLED` → `payment_status_unknown`
   (422, new id **DEBT-COL-0459**, "ไม่รู้จักสถานะการชำระนี้").
2. No reason, or only spaces → `reason_required` (422, "ต้องระบุเหตุผลในการเปลี่ยนสถานะการชำระ").
3. `code` equals the current `payment_status` → `status_unchanged` (409,
   "สถานะการชำระเป็นค่านี้อยู่แล้ว เลือกค่าอื่นหากต้องการเปลี่ยน").

Then:

- `payment_status` becomes `code`.
- If `code` equals `payment_status_system`, the person has put it back to the system's answer.
  Nothing is left to overrule, so `set_by` and `reason` are cleared.
- Otherwise `set_by = by` and `reason = reason`.
- One event and one audit detail are written (3.4, 3.5).

**Route:** `POST /v1/cases/by-customer/{customer_uid}/payment-status` with body `{code, reason}`.
It returns `{"case": case}`. `note` is accepted as another name for `reason`, as on dc-status. The
act is signed with `who(body, x_volt_officer)` like dc-status, so under login the session's officer
signs it. There is no role gate (decision 2). `CaseError` goes through `problem_from`, which gains
the `payment_status_unknown` row.

### 3.3 The system wins — `cases.follow_system_payment_status(contract)`

`_set_contract_fields` calls it whenever `status` is among the fields it writes. That is the only
write path for a contract's status, so the NPL declaration, the review confirmation, the write-off,
and any future writer all pass through it.

For the customer that owns the contract:

1. Work out `new = _payment_status(customer)`.
2. If `new == payment_status_system`, stop. The system's answer did not change.
3. Otherwise set `payment_status_system = new` and `payment_status = new`.
4. If a person's change stood, it **ends**: `set_by` and `reason` are cleared. The event records
   whose change ended and what it was.
5. One event (3.4) and one audit detail (3.5).

This applies to **every** case (decision 5). Measured with a throwaway copy of this rule on
`10e40bc`: the backend suite stayed at **821 passed, 11 skipped**, so no existing test moves, and
C-002032 read `NPL` after its declaration.

### 3.4 Case history — the `PAYMENT_STATUS_SET` event

Both the person's act and the system's re-check append one event to `state.events`:

```
{"kind": "PAYMENT_STATUS_SET", "case_uid", "from", "code", "system", "by", "reason", "on",
 "ended": {"by", "code", "reason"} | None}
```

- A person's act: `by` is the person, `reason` is theirs, and `ended` is `None`.
- The system's re-check: `by` is `"SYSTEM"` and `reason` is `None`. `ended` is filled only when a
  person's change stood.

The case page draws the row from these fields; no sentence is baked in on the server, so both
languages work. The status label is in bold. The reason goes on the note line for a person's act.
When the system ended a person's change, the note line reads "ระบบคำนวณใหม่เป็น {status} ·
การปรับของ {who} ({old}) สิ้นสุด".

### 3.5 Audit log

- **The person's act:** `audit.describe(act="PAYMENT_STATUS_SET", subject=("customer", uid),
  detail={"from", "to", "system", "reason"})`.
- **The system's re-check:** it runs inside another act's request (the declaration, the review
  decision, the write-off). It adds detail only, `detail={"payment_status_followed_system": {"from",
  "to", "ended"}}`, and never sets an act name. `audit.describe` resets detail only when an
  act name *changes*, so this detail stays on the outer act's row whichever describes first. A
  test pins this for the ladder advance.

The AuditLog screen shows act names as they are, so it needs no change.

### 3.6 The case page

In the statuses card, under the existing follow-up status form, add a second form built the same
way:

- A SearchSelect with testid `cs-ps`, labelled "สถานะการชำระ", offering the five statuses with the
  existing `status.*` labels.
- Once a value is chosen, a reason box (`cs-ps-reason`) and a Save button appear. The same three
  hints as the dc form come with them: need a reason (`ps-save-why`), already this value
  (`ps-save-same`), and Save disabled until the form is valid.
- **While a person's change stands** (`ps-adjusted`), one line: "ระบบคำนวณได้ {system} · ปรับเป็น
  {status} โดย {who} · {reason}". When nothing stands, the line is absent, so the resting page
  costs only the dropdown.
- `api.setPaymentStatus(customerUid, {code, reason, by})`.
- The history row, as in 3.4.
- New strings go in `i18n-today.js` beside the `case.dc*` keys, so `i18n.test.js` checks EN/TH
  parity.

### 3.7 Other screens

Nothing to build. They already read `payment_status`, so they follow a change:

- Setting **ปิดบัญชี (CLOSED)** takes the customer off Today and out of Work Book's default view.
- Setting **NPL** puts them on the NPL list and lets a Manager set the NPL type.
- The weekly report's live counts move. Published editions are frozen and do not.

**Except where NPL leaves records behind.** Measured by the final review on 2026-09-14: a
person moving a case *out of* NPL does not clear what NPL left on it. See §5, the first two
entries.

---

## 4. Test price

- **New tests are free:**
  - Backend: the domain rules (3.2), the route and its refusals, the re-check with and without a
    standing change (3.3), the event shape (3.4), and the audit detail on the outer row (3.5).
  - Frontend: the form and its three hints, the adjusted line, the history row, and the api call.
- **Existing tests:** none moves for the re-check (measured, 3.3). The frontend change is additive.
- **Authorised test edit 34 — the density caps.** A closed SearchSelect inside its form is 7
  elements: form, div, label span, button, text span, svg, path. The quote is **97 → 104 and
  116 → 123**, four assertion lines in `density.test.jsx` (each cap is asserted twice), commented
  `AUTHORISED TEST EDIT 34`. The number is measured after the build. **If it differs from +7, the
  build stops and comes back with the measured price before spending.**
- Any other existing test that must change comes back to Arina; it is never edited in passing.

---

## 5. Not in this change (open register)

- **Leaving NPL leaves its records behind (final review I1).** A person moving a case from NPL
  to another status leaves `npl_type` set, so `sop.py` (`ps == "NPL" or npl_type`) still
  places step 16 and the walkthrough says "choose a recovery strategy" under a status that
  reads LATE. A seeded NPL case's open `NPL_TYPE_ASK` review stays open, and answering it with
  `NPL_TYPE_SET` is refused (`npl_type_not_applicable`, 409). A declared customer's
  `state.npl_cases` row stays on the NPL list and in its badge, so the badge no longer equals
  the weekly report's NPL head-count. Arina to rule: clear or close these when a person leaves
  NPL, or keep them.
- **Anyone may set NPL, but declaring NPL is gated (final review I2).** Declaring NPL on the
  ladder is OWNER/MANAGER only (`routers/journey.py`, OD-04). Under decision 2 an OFFICER can
  now put a customer on the NPL list, into the weekly NPL head-count and onto SOP step 16. It is
  not a declaration (no `npl_cases` row, no buyback), but the read screens do not tell the two
  apart. Decision 2's stated cost named only Today's order. Arina to rule: keep "anyone", or
  gate the NPL value.
- **The audit screen shows the system's ending only in detail (final review M1).** On the NPL
  declaration, the review decision and the write-off, the row carries no act and no subject,
  so `/audit` shows the route and "—"; the ended change is in
  `detail.payment_status_followed_system` and on the case history.
- **A session that has not opened its cases yet (final review M3).** If a declaration is the
  session's first touch of the cases, the cases seed already reading NPL: no
  `PAYMENT_STATUS_SET` event is written and the seed opens an `NPL_TYPE_ASK` review. In a
  session that already loaded them, the case gets the event and no review. No person's change
  can be lost this way.
- **The system following to NPL opens no NPL-type review either (final review M4).** Same as
  the person's NPL entry below. Still a gain: before this change a declared case read LATE and
  `set_npl_type` refused it.
- **Review snapshots take the person's value unmarked (final review M6).** `cases.py` copies
  `payment_status` into a review's snapshot without `payment_status_system` or who set it.
- **"The system wins" rarely fires (final review, recommendation 4).** Only an NPL declaration,
  an NPL confirmed from review, or a write-off moves the system's answer. A person's CURRENT on
  a LATE customer usually stands until another person changes it.
- **A person's NPL does not open the NPL-type review.** The seed opens a review for an NPL case with
  no type (`cases.py` `_seed`). A person's change to NPL does not, so a Manager has to notice it.
- **Today and Work Book rows do not mark a changed status.** The mark and the system's answer are
  on the case page only. Marking the rows costs density on Today (31 elements per row).
- **A session reset clears every change,** as it clears every other act in the session. The audit
  log keeps the record.
- **The follow-up status history rows still do not show their reason.** `DC_STATUS_SET` carries
  `reason`, but the history row reads only `text_th / note_th / note`. Not widened here, so no
  existing row changes.
