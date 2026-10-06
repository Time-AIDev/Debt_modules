# Payment status adjustment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let anyone change a case's payment status with a reason. The change goes into the case history and the audit log. The system's own answer wins again whenever a contract's status changes.

**Architecture:** The case dict gains `payment_status_system`, `payment_status_set_by` and `payment_status_reason` next to the existing `payment_status`, which every screen already reads. A new domain act, `cases.set_payment_status`, copies `set_dc_status`. A new hook, `cases.follow_system_payment_status`, runs from `_set_contract_fields`, the only write path for a contract's status. The case page gains a second status form built like the follow-up status form, one line showing the system's answer, and a history row.

**Tech Stack:** FastAPI + pytest (backend, in-memory session state), React 18 + Vitest + Testing Library (frontend).

**Spec:** `docs/archive/superpowers/specs/2026-09-14-payment-status-adjustment-design.md` (commit a5989a1). Read it before starting.

## Global Constraints

- The five payment statuses, exactly: `CURRENT, LATE, NPL, CLOSED, NOT_INSTALLED`.
- New refusal: `payment_status_unknown`, 422, error id **`DEBT-COL-0459`**, Thai "ไม่รู้จักสถานะการชำระนี้". Reuse `reason_required` (422) and `status_unchanged` (409).
- The event kind is `PAYMENT_STATUS_SET`. Its fields: `kind, case_uid, from, code, system, by, reason, on, ended` (`ended` is `{by, code, reason}` or `None`).
- The audit act is `PAYMENT_STATUS_SET` with detail `{from, to, system, reason}`. The system's re-check writes **detail only**: `{"payment_status_followed_system": {from, to, ended}}`. It never writes an act name.
- No role gate on the act. It is signed with `who(body, x_volt_officer)`, the same as dc-status.
- **Test contract:** green at or above the Task 0 baseline, with counts pasted. **Never edit an existing test.** The only exception is AUTHORISED TEST EDIT 34, the density caps in Task 4, and only if it measures exactly +7. Any other existing test that has to change means: stop and report to Arina.
- UI strings go in `frontend/src/i18n-today.js`, with EN and TH added together, because `i18n.test.js` checks that they match.
- **Shared branch.** `design-team` holds other sessions' uncommitted work (font, weekly report, deploy, pictures). Commit only this plan's files, by explicit path. `frontend/src/api.js` is already modified by the weekly-report work, so stage only this plan's block with the helper in Task 0. Never run `git add -A` or `git add .`, and never stash or reset other files.
- Write plain comments that name who asked and why, the way the neighbouring code does (e.g. `// Arina, 2026-09-14: ...`).

---

### Task 0: Baseline and the staging helper

**Files:**
- Create (scratchpad, not the repo): `$SCRATCH/stage_block.py`, where `SCRATCH=/private/tmp/claude-502/-Users-parattakorn-volt-debt-prototype/7e657d65-e401-4f36-bd42-8504188ff9da/scratchpad`

- [ ] **Step 1: Check nobody else is editing right now**

Run:
```bash
cd /Users/parattakorn/volt-debt-prototype && git log --oneline -3 && date +%H:%M && \
for f in $(git diff --name-only | grep -v '^pictures/'); do stat -f '%Sm %N' -t '%m-%d %H:%M' "$f"; done | sort | tail -3
```
Expected: HEAD is `a5989a1` or a later commit from this plan, and no file was modified in the last hour. If something was, stop and tell Arina that another session is active.

- [ ] **Step 2: Measure the backend baseline**

Run: `cd /Users/parattakorn/volt-debt-prototype/backend && .venv/bin/python -m pytest 2>&1 | tail -3`
Record the summary line. Failures that already exist come from other sessions' uncommitted work: the pipeline tests fed by `docs/odoo-comparison/odoo_compare.md`, last seen as 6 failed + 2 errors. Note their names so they aren't mistaken for yours later: `.venv/bin/python -m pytest 2>&1 | grep -E "^(FAILED|ERROR)"`.

- [ ] **Step 3: Measure the frontend baseline**

Run: `cd /Users/parattakorn/volt-debt-prototype/frontend && npx vitest run 2>&1 | grep -E "Test Files|Tests "`
Record both lines.

- [ ] **Step 4: Write the block-staging helper**

Write `$SCRATCH/stage_block.py`:
```python
"""Stage only the change blocks of a file whose text contains a marker, leaving the
working tree and every other block alone.
usage: python3 stage_block.py <path> <marker>"""
import difflib, subprocess, sys
path, marker = sys.argv[1], sys.argv[2]
head = subprocess.run(["git", "show", "HEAD:" + path], capture_output=True, text=True, check=True).stdout.splitlines(keepends=True)
work = open(path, encoding="utf-8").read().splitlines(keepends=True)
out, kept = [], 0
for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, head, work, autojunk=False).get_opcodes():
    if tag == "equal":
        out += head[i1:i2]
    elif marker in "".join(work[j1:j2]):
        out += work[j1:j2]; kept += 1
    else:
        out += head[i1:i2]
if kept == 0:
    sys.exit("no block contains %r" % marker)
blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], input="".join(out), capture_output=True, text=True, check=True).stdout.strip()
subprocess.run(["git", "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path)], check=True)
print("staged %d block(s) of %s containing %r" % (kept, path, marker))
```
No commit in this task.

---

### Task 1: The domain act — `cases.set_payment_status`

**Files:**
- Modify: `backend/app/cases.py`: add a constant near `GOVERNED_DC_STATUSES` (line ~44), three fields in `_blank_case` (after `"payment_status": payment_status,`, line ~195), and a new function directly after `set_dc_status` (ends line ~815)
- Create: `backend/tests/test_payment_status_adjust.py`

**Interfaces:**
- Produces: `cases.PAYMENT_STATUSES` (tuple of 5 str); `cases.set_payment_status(state, case, code, by, reason=None) -> case`, which raises `CaseError` with code `payment_status_unknown`, `reason_required` or `status_unchanged`; case keys `payment_status_system`, `payment_status_set_by`, `payment_status_reason`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_payment_status_adjust.py`:
```python
"""A person may change the case's payment status, with a reason (Arina, 2026-09-14).

Spec: docs/archive/superpowers/specs/2026-09-14-payment-status-adjustment-design.md
"""
import pytest

from app import cases
from app.cases import CaseError


@pytest.fixture
def state():
    return cases.for_current()


def late_case(state):
    return next(c for c in state.cases.values() if c["payment_status"] == "LATE")


def events(state):
    return [e for e in state.events if e["kind"] == "PAYMENT_STATUS_SET"]


# --- the act (spec §3.1, §3.2) ------------------------------------------------------

def test_a_seeded_case_holds_the_system_answer_and_no_person_change(state):
    for case in state.cases.values():
        assert case["payment_status_system"] == case["payment_status"]
        assert case["payment_status_set_by"] is None
        assert case["payment_status_reason"] is None


def test_a_person_changes_it_with_a_reason_and_the_system_answer_stays_beside_it(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="ลูกค้าโอนครบแล้ว รอ PEAK")
    assert case["payment_status"] == "CURRENT"
    assert case["payment_status_system"] == "LATE"
    assert case["payment_status_set_by"] == "thip"
    assert case["payment_status_reason"] == "ลูกค้าโอนครบแล้ว รอ PEAK"
    event = events(state)[-1]
    assert (event["from"], event["code"], event["system"]) == ("LATE", "CURRENT", "LATE")
    assert event["by"] == "thip" and event["reason"] == "ลูกค้าโอนครบแล้ว รอ PEAK"
    assert event["ended"] is None and event["on"]


def test_no_reason_is_refused_and_changes_nothing(state):
    case = late_case(state)
    for blank in (None, "", "   "):
        with pytest.raises(CaseError) as err:
            cases.set_payment_status(state, case, "CURRENT", by="thip", reason=blank)
        assert err.value.code == "reason_required"
    assert case["payment_status"] == "LATE"
    assert events(state) == []


def test_an_unknown_status_is_refused_before_the_reason_is_checked(state):
    case = late_case(state)
    with pytest.raises(CaseError) as err:
        cases.set_payment_status(state, case, "PAID", by="thip", reason=None)
    assert err.value.code == "payment_status_unknown"
    assert case["payment_status"] == "LATE"


def test_the_value_it_already_holds_is_refused(state):
    case = late_case(state)
    with pytest.raises(CaseError) as err:
        cases.set_payment_status(state, case, "LATE", by="thip", reason="ซ้ำ")
    assert err.value.code == "status_unchanged"
    assert events(state) == []


def test_putting_it_back_to_the_system_answer_clears_the_person_change(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    cases.set_payment_status(state, case, "LATE", by="nantapol", reason="ยอดยังไม่เข้า")
    assert case["payment_status"] == "LATE"
    assert case["payment_status_set_by"] is None and case["payment_status_reason"] is None
    assert [e["by"] for e in events(state)] == ["thip", "nantapol"]
```

- [ ] **Step 2: Run them to check they fail**

Run: `cd /Users/parattakorn/volt-debt-prototype/backend && .venv/bin/python -m pytest tests/test_payment_status_adjust.py`
Expected: FAIL. The seed test fails with `KeyError: 'payment_status_system'`, and the rest fail with `AttributeError: module 'app.cases' has no attribute 'set_payment_status'`.

- [ ] **Step 3: Add the constant**

In `backend/app/cases.py`, directly after the `GOVERNED_DC_STATUSES = (...)` tuple:
```python
# Arina, 2026-09-14 (spec 2026-09-14-payment-status-adjustment-design.md): the five
# values REQ-COL-075 names. A person may now choose one, with a reason.
PAYMENT_STATUSES = ("CURRENT", "LATE", "NPL", "CLOSED", "NOT_INSTALLED")
```

- [ ] **Step 4: Add the three case fields**

In `_blank_case`, directly after the line `"payment_status": payment_status,`:
```python
        # The system's own answer, kept beside the value every screen reads, and who
        # overruled it and why while a person's change stands (spec §3.1).
        "payment_status_system": payment_status,
        "payment_status_set_by": None,
        "payment_status_reason": None,
```

- [ ] **Step 5: Add the act**

Directly after `set_dc_status` (after its `return case`), add:
```python
def set_payment_status(state, case, code, by, reason=None):
    """A person's payment status, with a reason (Arina, 2026-09-14).

    SUPERSEDES PART OF Requirements Amendment v2.6 §3.6 (REQ-COL-075), which reads
    "payment_status is computed by the system". The system still computes it:
    `payment_status_system` keeps that answer, and follow_system_payment_status puts
    it back the moment it changes. But a person may now overrule it.
    Spec: docs/archive/superpowers/specs/2026-09-14-payment-status-adjustment-design.md

    Same order as set_dc_status: the code is checked BEFORE the reason, so an unknown
    code is never hidden behind the reason refusal.
    """
    if code not in PAYMENT_STATUSES:
        raise CaseError("payment_status_unknown",
                        "%r is not a payment status; use one of %s" % (code, ", ".join(PAYMENT_STATUSES)),
                        message_th="ไม่รู้จักสถานะการชำระนี้", known=list(PAYMENT_STATUSES))
    if not reason or not str(reason).strip():
        raise CaseError("reason_required", "Changing the payment status needs a reason",
                        message_th="ต้องระบุเหตุผลในการเปลี่ยนสถานะการชำระ")
    reason = str(reason).strip()
    # R14's rule, as on set_dc_status: a change that changes nothing would still leave
    # a record claiming someone changed something.
    if case["payment_status"] == code:
        raise CaseError("status_unchanged", "The payment status already reads %s" % code,
                        message_th="สถานะการชำระเป็นค่านี้อยู่แล้ว เลือกค่าอื่นหากต้องการเปลี่ยน",
                        code_value=code)
    previous = case["payment_status"]
    system = case.get("payment_status_system")
    case["payment_status"] = code
    if code == system:
        # Put back to the system's own answer: nothing is left to overrule.
        case["payment_status_set_by"], case["payment_status_reason"] = None, None
    else:
        case["payment_status_set_by"], case["payment_status_reason"] = by, reason
    state.events.append({"kind": "PAYMENT_STATUS_SET", "case_uid": case["uid"],
                         "from": previous, "code": code, "system": system, "by": by,
                         "reason": reason, "on": str(settings.business_date), "ended": None})
    from . import audit
    audit.describe(act="PAYMENT_STATUS_SET", subject=("customer", case["customer_uid"]),
                   detail={"from": previous, "to": code, "system": system, "reason": reason})
    return case
```

- [ ] **Step 6: Run the new tests**

Run: `cd /Users/parattakorn/volt-debt-prototype/backend && .venv/bin/python -m pytest tests/test_payment_status_adjust.py`
Expected: `6 passed`.

- [ ] **Step 7: Run the whole backend suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: the Task 0 passed count plus 6, and no failure outside the Task 0 list.

- [ ] **Step 8: Commit**

```bash
cd /Users/parattakorn/volt-debt-prototype
git add -- backend/app/cases.py backend/tests/test_payment_status_adjust.py
git commit -m "feat(case): a person may change the payment status, with a reason

cases.set_payment_status refuses an unknown status, a missing reason and a
no-op; keeps the system's own answer beside the person's value; writes a
PAYMENT_STATUS_SET event and audit act. Partly supersedes Amendment v2.6
§3.6. Spec 2026-09-14-payment-status-adjustment-design.md §3.1-3.2.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UHXYThDWp1AZ91CXVstTPs"
```

---

### Task 2: The system wins — `cases.follow_system_payment_status`

**Files:**
- Modify: `backend/app/cases.py`: `_set_contract_fields` (line ~155), plus a new function directly after it
- Test: `backend/tests/test_payment_status_adjust.py` (append)

**Interfaces:**
- Consumes: `cases._payment_status(customer)`, `cases.for_current()`, `main.BY_CONTRACT[uid] -> (customer, contract)`, and the Task 1 case fields.
- Produces: `cases.follow_system_payment_status(contract) -> case | None`, called automatically whenever `_set_contract_fields(contract, status=...)` runs.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_payment_status_adjust.py` (the first import block gains two lines):
```python
from fastapi.testclient import TestClient

from app import audit_store
from app.main import app


def _contract_of(case):
    from app import main
    return main.BY_CUSTOMER[case["customer_uid"]].contracts[0]


# --- the system wins (spec §3.3) ----------------------------------------------------

def test_a_contract_status_change_moves_the_case_to_the_system_answer(state):
    """Before this, nothing re-worked the status: declaring NPL on C-002032 left LATE."""
    case = late_case(state)
    cases._set_contract_fields(_contract_of(case), status="NON_PERFORMING")
    assert case["payment_status"] == "NPL"
    assert case["payment_status_system"] == "NPL"
    event = events(state)[-1]
    assert (event["from"], event["code"], event["by"], event["ended"]) == ("LATE", "NPL", "SYSTEM", None)


def test_the_system_ends_a_person_change_and_says_whose_it_was(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    cases._set_contract_fields(_contract_of(case), status="NON_PERFORMING")
    assert case["payment_status"] == "NPL"
    assert case["payment_status_set_by"] is None and case["payment_status_reason"] is None
    event = events(state)[-1]
    assert (event["by"], event["from"], event["code"]) == ("SYSTEM", "CURRENT", "NPL")
    assert event["ended"] == {"by": "thip", "code": "CURRENT", "reason": "โอนแล้ว"}


def test_a_status_write_that_leaves_the_system_answer_alone_keeps_the_person_change(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    before = len(events(state))
    cases._set_contract_fields(_contract_of(case), status="PAST_DUE")   # still LATE
    assert case["payment_status"] == "CURRENT" and case["payment_status_set_by"] == "thip"
    assert len(events(state)) == before


def test_a_write_without_status_does_not_re_work_it(state):
    case = late_case(state)
    cases.set_payment_status(state, case, "CURRENT", by="thip", reason="โอนแล้ว")
    before = len(events(state))
    cases._set_contract_fields(_contract_of(case), fee_state="SERVICE_HOLD_FAULT_CONFIRMED")
    assert case["payment_status"] == "CURRENT"
    assert len(events(state)) == before


def _journey_case(client, customer_no):
    from app import main
    for jc in client.get("/v1/cases").json()["cases"]:
        if main.BY_CUSTOMER[jc["customer_uid"]].customer_no == customer_no:
            return jc
    raise AssertionError("no journey case for %s" % customer_no)


def _latest_audit():
    return audit_store.read({}, limit=1, before_seq=None)[0]


def test_declaring_npl_moves_the_case_and_the_declaration_row_says_so():
    """C-002032 read LATE after its NPL declaration before this change (spec §1.2)."""
    client = TestClient(app)
    jc = _journey_case(client, "C-002032")
    uid = jc["customer_uid"]
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "LATE"
    response = client.post("/v1/cases/%s:advance" % jc["uid"],
                           json={"to_stage": "NPL_DECLARED_90", "role": "OWNER", "note": "ครบ 90 วัน"})
    assert response.status_code == 200
    # Read the audit row BEFORE the next GET: opening a case is itself a logged read.
    entry = _latest_audit()
    assert entry["route_template"] == "/v1/cases/{uid}:advance"
    assert entry["detail"]["payment_status_followed_system"] == {"from": "LATE", "to": "NPL", "ended": None}
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "NPL"
```

- [ ] **Step 2: Run them to check they fail**

Run: `.venv/bin/python -m pytest tests/test_payment_status_adjust.py`
Expected: 3 FAIL: "moves the case", "ends a person change" and "declaring npl", e.g. `assert 'LATE' == 'NPL'`. 8 pass: the 6 from Task 1, plus "keeps the person change" and "without status". Those two guard against the hook doing too much, so they pass before it exists.

- [ ] **Step 3: Call the hook from the only write path**

In `backend/app/cases.py`, replace the body of `_set_contract_fields`:
```python
def _set_contract_fields(contract, **fields):
    """The only write path for the fields this overlay covers. Lands in the current
    session's overlay, never on the shared Contract object."""
    slot = _fee_overlay().setdefault(contract.uid, {})
    slot.update(fields)
    if "status" in fields:
        # Spec 2026-09-14 §3.3: a contract's status changes only through here, so this
        # is the one place the case's payment status can follow the system.
        follow_system_payment_status(contract)
```

- [ ] **Step 4: Add the hook**

Directly after `_set_contract_fields`, before the back-compat aliases:
```python
def follow_system_payment_status(contract):
    """The system wins (Arina, 2026-09-14: decision 3, for every case: decision 5).

    Before this, nothing re-worked `payment_status` after the seed: declaring NPL on
    C-002032 left the case reading LATE. Now, when a contract's status changes, the
    owning customer's answer is worked out again. If it moved, the case shows it, and
    a person's change that stood ends. The history and the audit row say whose.
    """
    from . import main
    found = main.BY_CONTRACT.get(contract.uid)
    if not found:
        return None
    customer = found[0]
    state = for_current()
    case = state.cases.get(customer.uid)
    if case is None:
        return None
    new = _payment_status(customer)
    if new == case.get("payment_status_system"):
        return None
    previous = case["payment_status"]
    ended = None
    if case.get("payment_status_set_by"):
        ended = {"by": case["payment_status_set_by"], "code": previous,
                 "reason": case.get("payment_status_reason")}
    case["payment_status_system"] = new
    case["payment_status"] = new
    case["payment_status_set_by"], case["payment_status_reason"] = None, None
    state.events.append({"kind": "PAYMENT_STATUS_SET", "case_uid": case["uid"],
                         "from": previous, "code": new, "system": new, "by": "SYSTEM",
                         "reason": None, "on": str(settings.business_date), "ended": ended})
    from . import audit
    # Detail only, never an act name. This runs inside another act's request (the NPL
    # declaration, the review decision, the write-off), and that act owns the row.
    # audit.describe resets detail only when an act NAME changes, so this survives.
    audit.describe(detail={"payment_status_followed_system": {"from": previous, "to": new, "ended": ended}})
    return case
```

- [ ] **Step 5: Run the new tests**

Run: `.venv/bin/python -m pytest tests/test_payment_status_adjust.py`
Expected: `11 passed`.

- [ ] **Step 6: Run the whole backend suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: the Task 0 count plus 11, and no failure outside the Task 0 list. The spec measured that no existing test moves. **If an existing test fails here, stop and report it to Arina with its name and assertion. Do not edit it.**

- [ ] **Step 7: Commit**

```bash
git add -- backend/app/cases.py backend/tests/test_payment_status_adjust.py
git commit -m "feat(case): the payment status follows the system when a contract's status changes

_set_contract_fields, the only write path for a contract's status, now calls
follow_system_payment_status: every case re-works its answer, a person's change
that stood ends, and the history and the outer act's audit row say whose.
Closes the gap where declaring NPL left the case reading LATE (C-002032).
Spec 2026-09-14-payment-status-adjustment-design.md §3.3-3.5.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UHXYThDWp1AZ91CXVstTPs"
```

---

### Task 3: The route — `POST /v1/cases/by-customer/{uid}/payment-status`

**Files:**
- Modify: `backend/app/routers/today.py`: add a row to `problem_from`'s mapping (next to `status_unchanged`, line ~77), and a new route directly after `set_dc_status` (line ~929-953)
- Test: `backend/tests/test_payment_status_adjust.py` (append)

**Interfaces:**
- Consumes: `cases_domain.set_payment_status` (Task 1), and `who`, `problem_from`, `_case_or_404` already in `routers/today.py`.
- Produces: `POST /v1/cases/by-customer/{customer_uid}/payment-status` with body `{code, reason}` (or `note`), which returns `{"case": {...}}`. The frontend (Task 4) calls it.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_payment_status_adjust.py`:
```python
# --- the route (spec §3.2, §3.5) ----------------------------------------------------

def _late_customer(client):
    rows = client.get("/v1/workbook").json()["rows"]
    return next(r["customer"]["uid"] for r in rows if r["case"]["payment_status"] == "LATE")


def test_the_route_changes_it_and_the_audit_row_says_from_to_system_and_why():
    client = TestClient(app)
    uid = _late_customer(client)
    response = client.post("/v1/cases/by-customer/%s/payment-status" % uid,
                           json={"code": "CURRENT", "reason": "ลูกค้าโอนครบแล้ว"},
                           headers={"X-Volt-Officer": "thip"})
    assert response.status_code == 200
    body = response.json()["case"]
    assert body["payment_status"] == "CURRENT" and body["payment_status_system"] == "LATE"
    assert body["payment_status_set_by"] == "thip"
    assert body["payment_status_reason"] == "ลูกค้าโอนครบแล้ว"
    entry = _latest_audit()
    assert entry["act"] == "PAYMENT_STATUS_SET"
    assert (entry["subject_type"], entry["subject_uid"]) == ("customer", uid)
    assert entry["detail"]["from"] == "LATE" and entry["detail"]["to"] == "CURRENT"
    assert entry["detail"]["system"] == "LATE" and entry["detail"]["reason"] == "ลูกค้าโอนครบแล้ว"


def test_note_is_accepted_as_the_reason():
    client = TestClient(app)
    uid = _late_customer(client)
    response = client.post("/v1/cases/by-customer/%s/payment-status" % uid,
                           json={"code": "NPL", "note": "ผู้จัดการยืนยัน"})
    assert response.status_code == 200
    assert response.json()["case"]["payment_status_reason"] == "ผู้จัดการยืนยัน"


def test_the_route_refuses_no_reason_an_unknown_status_and_the_same_status():
    client = TestClient(app)
    uid = _late_customer(client)
    url = "/v1/cases/by-customer/%s/payment-status" % uid
    no_reason = client.post(url, json={"code": "CURRENT"})
    assert (no_reason.status_code, no_reason.json()["code"]) == (422, "reason_required")
    unknown = client.post(url, json={"code": "PAID", "reason": "x"})
    assert (unknown.status_code, unknown.json()["code"]) == (422, "payment_status_unknown")
    assert unknown.json()["error_id"] == "DEBT-COL-0459"
    assert unknown.json()["message_th"] == "ไม่รู้จักสถานะการชำระนี้"
    same = client.post(url, json={"code": "LATE", "reason": "x"})
    assert (same.status_code, same.json()["code"]) == (409, "status_unchanged")
    assert client.get("/v1/cases/by-customer/%s" % uid).json()["case"]["payment_status"] == "LATE"


def test_an_unknown_customer_is_a_404():
    client = TestClient(app)
    response = client.post("/v1/cases/by-customer/no-such-customer/payment-status",
                           json={"code": "CURRENT", "reason": "x"})
    assert response.status_code == 404
```

- [ ] **Step 2: Run them to check they fail**

Run: `.venv/bin/python -m pytest tests/test_payment_status_adjust.py -k "route or note or unknown_customer"`
Expected: 3 FAIL, all on status code (`405` or `404` where `200` or `422` is expected), because the route does not exist. `test_an_unknown_customer_is_a_404` passes before the route exists (FastAPI answers an unknown path with 404) and stays as the guard that the route keeps it so.

- [ ] **Step 3: Add the refusal row**

In `routers/today.py` `problem_from`, directly after the `"status_unchanged": (...)` entry:
```python
        # Arina, 2026-09-14: a person's payment status is one of the five names
        # REQ-COL-075 gives (cases.PAYMENT_STATUSES).
        "payment_status_unknown": (422, "DEBT-COL-0459", "Unknown payment status",
                                   "ไม่รู้จักสถานะการชำระนี้"),
```

- [ ] **Step 4: Add the route**

Directly after the `set_dc_status` route function (after its `return {"case": case}`):
```python
@router.post("/v1/cases/by-customer/{customer_uid}/payment-status")
def set_payment_status(customer_uid: str, body: dict = Body(...), x_volt_officer: str = Header(default=None)):
    """A person's payment status, with a reason (Arina, 2026-09-14). Any role, the same
    as dc-status; the system takes it back when a contract's status changes
    (cases.follow_system_payment_status).
    Spec: docs/archive/superpowers/specs/2026-09-14-payment-status-adjustment-design.md

    `note` is accepted as another name for `reason`, as on dc-status."""
    cs = cases_domain.for_current()
    case = _case_or_404(cs, customer_uid)
    reason = body.get("reason") or body.get("note")
    try:
        cases_domain.set_payment_status(cs, case, body.get("code"), by=who(body, x_volt_officer),
                                        reason=reason)
    except CaseError as exc:
        raise problem_from(exc)
    return {"case": case}
```

- [ ] **Step 5: Run the new tests**

Run: `.venv/bin/python -m pytest tests/test_payment_status_adjust.py`
Expected: `15 passed`.

- [ ] **Step 6: Run the whole backend suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: the Task 0 count plus 15, and no failure outside the Task 0 list. `test_audit_coverage.py` must stay green: the new POST is logged by construction.

- [ ] **Step 7: Commit**

```bash
git add -- backend/app/routers/today.py backend/tests/test_payment_status_adjust.py
git commit -m "feat(case): POST /v1/cases/by-customer/{uid}/payment-status

Any role, signed like dc-status; refusals reason_required (422),
payment_status_unknown (422, DEBT-COL-0459) and status_unchanged (409).
Spec 2026-09-14-payment-status-adjustment-design.md §3.2.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UHXYThDWp1AZ91CXVstTPs"
```

---

### Task 4: The case page form, plus AUTHORISED TEST EDIT 34

**Files:**
- Modify: `frontend/src/api.js`: one line after `setDcStatus` (line ~268)
- Modify: `frontend/src/i18n-today.js`: EN keys after `'case.dcSame'` (line ~76), TH keys after `'case.dcSame'` (line ~632)
- Modify: `frontend/src/screens/CustomerCase.jsx`: a constant after `PAYABLE_STATES` (line ~32), state after `dcForm` (line ~180), a `psLabel` helper after the `label` useMemo (line ~230), and the form directly after the dc-status `</form>` (line ~796)
- Create: `frontend/src/screens/CustomerCase.paymentStatus.test.jsx`
- Modify (AUTHORISED TEST EDIT 34, only as measured): `frontend/src/density.test.jsx` lines 359, 371, 431, 442

**Interfaces:**
- Consumes: the Task 3 route, and the case keys from Task 1.
- Produces: `api.setPaymentStatus(customerUid, {code, reason, by})`; testids `ps-status-form`, `cs-ps`, `ps-save-why`, `ps-save-same`; i18n keys `case.psStatus`, `case.psReason`, `case.psSave`, `case.psNeed`, `case.psSame`; the in-component helper `psLabel(code) -> string`, which Task 5 uses.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/CustomerCase.paymentStatus.test.jsx`:
```jsx
// Arina, 2026-09-14: "made the payment status of entirely contract can adjust with
// reason and keep in the activity log". ADDED tests; no existing test is edited here.
// Spec: docs/archive/superpowers/specs/2026-09-14-payment-status-adjustment-design.md
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { renderIn } from '../test-utils.jsx'
import { api } from '../api.js'
import { setRole, setOfficer } from '../components/role.jsx'
import CustomerCase from './CustomerCase.jsx'

vi.mock('../api.js', () => ({
  api: {
    caseDetail: vi.fn(), recordLinkSent: vi.fn(), dictionary: vi.fn(), setNextAction: vi.fn(),
    setDcStatus: vi.fn(), setPaymentStatus: vi.fn(), setNplType: vi.fn(), logContact: vi.fn(),
    logCaseContact: vi.fn(), retractContact: vi.fn(), closeCasePtp: vi.fn(), renegotiatePtp: vi.fn(),
    requestReview: vi.fn(), closeCaseIssue: vi.fn(), requestPower: vi.fn(), powerAct: vi.fn(), confirmSlip: vi.fn(),
  },
}))

const Page = () => (
  <MemoryRouter initialEntries={['/customers/cu-1']}>
    <Routes><Route path="/customers/:customerUid" element={<CustomerCase />} /></Routes>
  </MemoryRouter>
)

const CASE = {
  uid: 'case-1', customer_uid: 'cu-1', customer_no: '99999000112', volt_id: '99999000112_VOLT',
  product: 'LEASE', officer_uid: 'nantapol',
  payment_status: 'LATE', payment_status_system: 'LATE', payment_status_set_by: null, payment_status_reason: null,
  dc_status: 'CONTACT_BACK', dc_status_note: null, npl_type: null,
  next_action: 'CALL', next_action_on: '2026-10-29', next_action_set_by: 'SEED', next_action_note: null,
  last_contact_at: null, last_contact_by: null, last_result: null,
  open_ptp_uid: null, broken_ptp_count: 0, kept_ptp_count: 0, renegotiation_count: 0,
  open_issue_uid: null, power_state: 'ON', power_uid: null, review_uid: null, delay_cause: null, sheet: {},
}

// A small case that renders the whole page (probed 2026-09-14): one contract, no
// contacts, no promises. Tests override the case fields and the events.
const detail = (caseOver = {}, events = []) => ({
  case: { ...CASE, ...caseOver },
  work_item: {
    customer: { uid: 'cu-1', customer_no: '99999000112', display_name: 'ลูกค้าทดสอบ 0187',
                phone_masked: null, phone_e164: null, line_id: null, contract_count: 1, officer: 'nantapol' },
    entity: 'SPV', company_id: 'CO-SPV', aggregate_overdue: '2999.00', aggregate_outstanding: '212928.99',
    oldest_dpd: 13, aging_bucket: 'MID_OVERDUE', band_set_code: 'OPERATIONAL', fee_state: null,
    open_ptp: null, contact_lock: { state: 'OPEN' }, session_last_contact: null,
  },
  customer: { uid: 'cu-1', customer_no: '99999000112', display_name: 'ลูกค้าทดสอบ 0187',
              volt_id: '99999000112_VOLT', phone_masked: null, phone_e164: null, line_id: null, officer: 'nantapol' },
  contracts: [{ uid: 'K-1-L', product: 'LEASE', entity: 'SPV', status: 'PAST_DUE', principal: '176411.76',
                term_months: 96, first_due: '2024-09-10', paid_through: 25, derivation: {}, fee_state: null }],
  month_grid: [], contact_log: [], ptps: [], issues: [], reviews: [], power: [], sheet_row: {},
  invoices: [], receipts: [], events,
})

beforeEach(() => {
  vi.clearAllMocks()
  setRole('OFFICER')
  setOfficer('nantapol')
  api.caseDetail.mockResolvedValue(detail())
  api.dictionary.mockImplementation((name) => Promise.resolve({ name, values: [] }))
  api.setPaymentStatus.mockResolvedValue({ case: {} })
})

async function openCase() {
  const view = renderIn('th', <Page />)
  await screen.findByRole('heading', { level: 1, name: 'ลูกค้าทดสอบ 0187' })
  return { form: screen.getByTestId('ps-status-form'), container: view.container }
}

async function choose(form, name) {
  fireEvent.click(within(form).getByLabelText('สถานะการชำระ'))
  fireEvent.click(await within(form).findByRole('option', { name }))
}

describe('the case payment status: a person may change it, with a reason', () => {
  it('offers the five payment statuses to an officer, and no reason box until one is chosen', async () => {
    const { form } = await openCase()
    fireEvent.click(within(form).getByLabelText('สถานะการชำระ'))
    const names = (await within(form).findAllByRole('option')).map((o) => o.textContent)
    expect(names).toEqual(['— เลือก —', 'ปกติ', 'ค้างชำระ', 'NPL', 'ปิดบัญชี', 'ยังไม่ติดตั้ง'])
    expect(within(form).queryByLabelText('เหตุผลที่เปลี่ยนสถานะการชำระ')).toBeNull()
  })

  it('will not save until a reason is typed, says why, and whitespace is not a reason', async () => {
    const { form } = await openCase()
    await choose(form, 'ปกติ')
    expect(api.setPaymentStatus).not.toHaveBeenCalled()
    expect(within(form).getByRole('button', { name: 'บันทึกสถานะการชำระ' })).toBeDisabled()
    expect(within(form).getByTestId('ps-save-why')).toBeInTheDocument()
    fireEvent.change(within(form).getByLabelText('เหตุผลที่เปลี่ยนสถานะการชำระ'), { target: { value: '   ' } })
    expect(within(form).getByRole('button', { name: 'บันทึกสถานะการชำระ' })).toBeDisabled()
  })

  it('says when the chosen status is the one it already has', async () => {
    const { form } = await openCase()
    await choose(form, 'ค้างชำระ')
    fireEvent.change(within(form).getByLabelText('เหตุผลที่เปลี่ยนสถานะการชำระ'), { target: { value: 'ซ้ำ' } })
    expect(within(form).getByTestId('ps-save-same')).toBeInTheDocument()
    expect(within(form).getByRole('button', { name: 'บันทึกสถานะการชำระ' })).toBeDisabled()
  })

  it('sends the status and the trimmed reason, signed by the top-bar identity, then closes', async () => {
    setOfficer('thip')
    const { form } = await openCase()
    await choose(form, 'ปกติ')
    fireEvent.change(within(form).getByLabelText('เหตุผลที่เปลี่ยนสถานะการชำระ'),
      { target: { value: '  ลูกค้าโอนครบแล้ว รอ PEAK  ' } })
    fireEvent.click(within(form).getByRole('button', { name: 'บันทึกสถานะการชำระ' }))
    await waitFor(() => expect(api.setPaymentStatus).toHaveBeenCalledWith('cu-1',
      { code: 'CURRENT', reason: 'ลูกค้าโอนครบแล้ว รอ PEAK', by: 'thip' }))
    await waitFor(() => expect(screen.queryByLabelText('เหตุผลที่เปลี่ยนสถานะการชำระ')).toBeNull())
  })
})
```

- [ ] **Step 2: Run them to check they fail**

Run: `cd /Users/parattakorn/volt-debt-prototype/frontend && npx vitest run src/screens/CustomerCase.paymentStatus.test.jsx`
Expected: 4 FAIL with `Unable to find an element by: [data-testid="ps-status-form"]`. If the failure is a render crash instead, fix the fixture, not the component.

- [ ] **Step 3: Add the API call**

In `frontend/src/api.js`, directly after the `setDcStatus:` line:
```js
  // Arina, 2026-09-14: a person's payment status, with a reason (spec 2026-09-14).
  setPaymentStatus: (customerUid, payload) => post(`/v1/cases/by-customer/${customerUid}/payment-status`, payload),
```

- [ ] **Step 4: Add the strings**

In `frontend/src/i18n-today.js`, EN table, directly after `'case.dcSame': 'That is the status it already has',`:
```js
  // Arina, 2026-09-14: the payment status is a person's to change too, with a reason
  // (spec 2026-09-14-payment-status-adjustment-design.md).
  'case.psStatus': 'Payment status',
  'case.psReason': 'Reason for changing the payment status',
  'case.psSave': 'Save payment status',
  'case.psNeed': 'Choose a payment status and give a reason before saving',
  'case.psSame': 'That is the payment status it already has',
```
TH table, directly after `'case.dcSame': 'เป็นสถานะเดิมอยู่แล้ว',`:
```js
  'case.psStatus': 'สถานะการชำระ',
  'case.psReason': 'เหตุผลที่เปลี่ยนสถานะการชำระ',
  'case.psSave': 'บันทึกสถานะการชำระ',
  'case.psNeed': 'เลือกสถานะการชำระและกรอกเหตุผลก่อนบันทึก',
  'case.psSame': 'เป็นสถานะการชำระเดิมอยู่แล้ว',
```

- [ ] **Step 5: Add the constant, the state and the label helper**

In `CustomerCase.jsx`, directly after the `const PAYABLE_STATES = [...]` line:
```jsx
// Arina, 2026-09-14: the five payment statuses a person may choose (REQ-COL-075's
// names; backend cases.PAYMENT_STATUSES).
const PAYMENT_STATUSES = ['CURRENT', 'LATE', 'NPL', 'CLOSED', 'NOT_INSTALLED']
```
Directly after `const [dcForm, setDcForm] = useState({ code: '', reason: '' })`:
```jsx
  const [psForm, setPsForm] = useState({ code: '', reason: '' })
```
Directly after the `const label = useMemo(...)` block closes:
```jsx
  // Payment statuses carry their labels in `status.*` (i18n-journey.js). A code with
  // no label shows as itself, never as a key.
  const psLabel = (code) => {
    const key = `status.${code}`
    return t(key) === key ? code : t(key)
  }
```

- [ ] **Step 6: Add the form**

Directly after the dc-status form's closing `</form>` and before `{managerish && !isNpl && (`:
```jsx
          {/* Arina, 2026-09-14: "made the payment status of entirely contract can adjust
              with reason and keep in the activity log". The same three parts as the
              follow-up status form above: a searchable list, a required reason, and a save
              that says why it is disabled. The reason and the save exist only once a
              status is chosen, so the resting card costs the dropdown alone
              (density.test.jsx, AUTHORISED TEST EDIT 34). This overrules part of
              Amendment v2.6 §3.6: spec 2026-09-14-payment-status-adjustment-design.md. */}
          <form className="cs-field" data-testid="ps-status-form" onSubmit={(e) => {
            e.preventDefault()
            if (!psForm.code || !psForm.reason.trim() || psForm.code === kase.payment_status) return
            act(() => api.setPaymentStatus(customerUid, { code: psForm.code, reason: psForm.reason.trim(), by }))
              .then((ok) => { if (ok) setPsForm({ code: '', reason: '' }) })
          }}>
            <SearchSelect
              className="cs-field"
              labelClassName="cs-field__label"
              triggerClassName="cs-field__select"
              label={t('case.psStatus')}
              value={psForm.code}
              options={PAYMENT_STATUSES.map((code) => ({ value: code, label: psLabel(code) }))}
              emptyLabel={t('case.choose')}
              onChange={(code) => setPsForm((f) => ({ ...f, code }))}
              testid="cs-ps"
            />
            {psForm.code && (
              <>
                <label htmlFor="cs-ps-reason">{t('case.psReason')}</label>
                <textarea id="cs-ps-reason" rows={2} value={psForm.reason} required disabled={busy}
                          onChange={(e) => setPsForm((f) => ({ ...f, reason: e.target.value }))} />
                <div className="cs-row" style={{ marginTop: 6 }}>
                  <button type="submit" className="btn btn--sm"
                          disabled={busy || !psForm.reason.trim() || psForm.code === kase.payment_status}>
                    {t('case.psSave')}
                  </button>
                  {!psForm.reason.trim() && (
                    <span className="td-quiet" data-testid="ps-save-why">{t('case.psNeed')}</span>
                  )}
                  {psForm.code === kase.payment_status && (
                    <span className="td-quiet" data-testid="ps-save-same">{t('case.psSame')}</span>
                  )}
                </div>
              </>
            )}
          </form>
```

- [ ] **Step 7: Run the new tests**

Run: `npx vitest run src/screens/CustomerCase.paymentStatus.test.jsx`
Expected: `4 passed`.

- [ ] **Step 8: Measure the density cost before spending edit 34**

Run: `npx vitest run src/density.test.jsx 2>&1 | grep -E "PRE-CONTACT|WORKED|RICH|Tests "`
Expected: `PRE-CONTACT+PAY ... visible=104` and `WORKED+PAY ... visible=123`, which is +7 on the Task 0 figures of 97 and 116, with two tests failing their caps. **If either number is not exactly +7, STOP. Do not touch `density.test.jsx`; report the measured numbers to Arina.**

- [ ] **Step 9: Spend AUTHORISED TEST EDIT 34, only when Step 8 measured +7**

In `frontend/src/density.test.jsx`, on the two `toBeLessThanOrEqual(97)` assertions (lines ~359 and ~431), change `97` to `104`, and put this comment directly above each one:
```jsx
    // AUTHORISED TEST EDIT 34 (Arina, 2026-09-14): 97 → 104. The reason is the
    // payment-status dropdown she asked for: a closed SearchSelect in its form is 7
    // always-visible elements (form, div, label, button, text, svg, path), measured.
```
On the two `toBeLessThanOrEqual(116)` assertions (lines ~371 and ~442), change `116` to `123`, with the same comment but `116 → 123`. Change nothing else in the file.

- [ ] **Step 10: Run the whole frontend suite**

Run: `npx vitest run 2>&1 | grep -E "Test Files|Tests |FAIL"`
Expected: the Task 0 count plus 4 tests and plus 1 file, with no FAIL. `i18n.test.js` passes because EN and TH were added together. **If an existing test other than density fails, stop and report it; do not edit it.**

- [ ] **Step 11: Commit**

```bash
cd /Users/parattakorn/volt-debt-prototype
git add -- frontend/src/i18n-today.js frontend/src/screens/CustomerCase.jsx \
  frontend/src/screens/CustomerCase.paymentStatus.test.jsx frontend/src/density.test.jsx
python3 /private/tmp/claude-502/-Users-parattakorn-volt-debt-prototype/7e657d65-e401-4f36-bd42-8504188ff9da/scratchpad/stage_block.py frontend/src/api.js setPaymentStatus
git diff --cached --stat   # expect exactly these 5 files; api.js shows +2 lines only
git commit -m "feat(case): the payment status form on the case page (authorised test edit 34)

A searchable list of the five statuses, a required reason and a save that says
why it is disabled, the same three parts as the follow-up status form. Edit 34:
density caps 97 -> 104 and 116 -> 123, the measured +7 of the closed dropdown.
Spec 2026-09-14-payment-status-adjustment-design.md §3.6, §4.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UHXYThDWp1AZ91CXVstTPs"
```

---

### Task 5: The system's answer beside a person's change, and the history row

**Files:**
- Modify: `frontend/src/i18n-today.js`: EN keys after `'case.psSame'`, TH keys after `'case.psSame'`; `'case.event.PAYMENT_STATUS_SET'` after `'case.event.DC_STATUS_SET'` in both tables (lines ~127, ~676)
- Modify: `frontend/src/screens/CustomerCase.jsx`: inside the ps form, after the `{psForm.code && (...)}` block; and in the history event row (line ~1360 and the note span below it)
- Test: `frontend/src/screens/CustomerCase.paymentStatus.test.jsx` (append inside the `describe`)

**Interfaces:**
- Consumes: `psLabel`, the `ps-status-form` from Task 4, and the event shape from Task 1/2 (`from, code, system, by, reason, on, ended`).
- Produces: testid `ps-adjusted`; i18n keys `case.psAdjusted`, `case.psEnded`, `case.event.PAYMENT_STATUS_SET`.

- [ ] **Step 1: Write the failing tests**

Append inside the `describe(...)` block of `CustomerCase.paymentStatus.test.jsx`:
```jsx
  it('shows the system answer beside a person change that stands', async () => {
    api.caseDetail.mockResolvedValue(detail({
      payment_status: 'CURRENT', payment_status_system: 'LATE',
      payment_status_set_by: 'thip', payment_status_reason: 'ลูกค้าโอนครบแล้ว',
    }))
    await openCase()
    expect(screen.getByTestId('ps-adjusted')).toHaveTextContent(
      'ระบบคำนวณได้ ค้างชำระ · ปรับเป็น ปกติ โดย thip · ลูกค้าโอนครบแล้ว')
  })

  it('shows no such line when the status is the system answer', async () => {
    await openCase()
    expect(screen.queryByTestId('ps-adjusted')).toBeNull()
  })

  it('puts a person change on the history, with who and why', async () => {
    api.caseDetail.mockResolvedValue(detail({}, [
      { kind: 'PAYMENT_STATUS_SET', case_uid: 'case-1', from: 'LATE', code: 'CURRENT', system: 'LATE',
        by: 'thip', reason: 'ลูกค้าโอนครบแล้ว', on: '2026-10-29', ended: null },
    ]))
    const { container } = await openCase()
    const row = container.querySelector('li[data-kind="PAYMENT_STATUS_SET"]')
    expect(row).not.toBeNull()
    expect(row).toHaveTextContent('เปลี่ยนสถานะการชำระ')
    expect(row).toHaveTextContent('ปกติ')
    expect(row).toHaveTextContent('thip')
    expect(row).toHaveTextContent('ลูกค้าโอนครบแล้ว')
  })

  it('says on the history when the system ended a person change', async () => {
    api.caseDetail.mockResolvedValue(detail({ payment_status: 'NPL', payment_status_system: 'NPL' }, [
      { kind: 'PAYMENT_STATUS_SET', case_uid: 'case-1', from: 'CURRENT', code: 'NPL', system: 'NPL',
        by: 'SYSTEM', reason: null, on: '2026-10-30', ended: { by: 'thip', code: 'CURRENT', reason: 'โอนแล้ว' } },
    ]))
    const { container } = await openCase()
    const row = container.querySelector('li[data-kind="PAYMENT_STATUS_SET"]')
    expect(row).toHaveTextContent('ระบบคำนวณใหม่เป็น NPL · การปรับของ thip (ปกติ) สิ้นสุด')
  })
```

- [ ] **Step 2: Run them to check they fail**

Run: `npx vitest run src/screens/CustomerCase.paymentStatus.test.jsx`
Expected: FAIL. The adjusted-line test can't find `ps-adjusted`, and the history tests can't find the row text. "Shows no such line" passes already.

- [ ] **Step 3: Add the strings**

EN table, directly after `'case.psSame': ...`:
```js
  'case.psAdjusted': 'The system worked out {system} · changed to {status} by {who} · {reason}',
  'case.psEnded': 'The system worked it out again as {status} · the change by {who} ({old}) ended',
```
EN table, directly after `'case.event.DC_STATUS_SET': 'DC status set',`:
```js
  'case.event.PAYMENT_STATUS_SET': 'Payment status set',
```
TH table, directly after `'case.psSame': ...`:
```js
  'case.psAdjusted': 'ระบบคำนวณได้ {system} · ปรับเป็น {status} โดย {who} · {reason}',
  'case.psEnded': 'ระบบคำนวณใหม่เป็น {status} · การปรับของ {who} ({old}) สิ้นสุด',
```
TH table, directly after `'case.event.DC_STATUS_SET': 'เปลี่ยนสถานะติดตาม',`:
```js
  'case.event.PAYMENT_STATUS_SET': 'เปลี่ยนสถานะการชำระ',
```

- [ ] **Step 4: Add the system's-answer line**

Inside the ps form in `CustomerCase.jsx`, directly after the `{psForm.code && (...)}` block and before `</form>`:
```jsx
            {/* Spec §3.6: while a person's change stands, the system's own answer sits
                beside it, the house "sheet says X · adjusted to Y" line. It is absent
                otherwise, so the resting card costs nothing more. */}
            {kase.payment_status_set_by && (
              <p className="td-quiet" data-testid="ps-adjusted">
                {t('case.psAdjusted', {
                  system: psLabel(kase.payment_status_system), status: psLabel(kase.payment_status),
                  who: kase.payment_status_set_by, reason: kase.payment_status_reason || '—',
                })}
              </p>
            )}
```

- [ ] **Step 5: Add the history row**

In the history event row, directly after the line
`{row.event.kind === 'DC_STATUS_SET' && <strong>{label.dc(row.event.code) || row.event.code}</strong>}`, add:
```jsx
                      {row.event.kind === 'PAYMENT_STATUS_SET' && <strong>{psLabel(row.event.code)}</strong>}
```
Directly after the generic note span
`{(row.event.text_th || row.event.note_th || row.event.note) && <span className="cs-tl__note">...</span>}`, add:
```jsx
                    {/* Spec §3.4: a person's reason, or whose change the system ended. */}
                    {row.event.kind === 'PAYMENT_STATUS_SET' && row.event.reason && (
                      <span className="cs-tl__note">{row.event.reason}</span>
                    )}
                    {row.event.kind === 'PAYMENT_STATUS_SET' && row.event.ended && (
                      <span className="cs-tl__note">{t('case.psEnded', {
                        status: psLabel(row.event.code), who: row.event.ended.by, old: psLabel(row.event.ended.code),
                      })}</span>
                    )}
```

- [ ] **Step 6: Run the new tests**

Run: `npx vitest run src/screens/CustomerCase.paymentStatus.test.jsx`
Expected: `8 passed`.

- [ ] **Step 7: Run the whole frontend suite, density included**

Run: `npx vitest run 2>&1 | grep -E "Test Files|Tests |FAIL"`, then `npx vitest run src/density.test.jsx 2>&1 | grep -E "\+PAY"`
Expected: no FAIL; the count is Task 4's plus 4; density still reads 104 / 123, because the new line is absent in its fixtures and history rows sit inside a closed fold.

- [ ] **Step 8: Commit**

```bash
git add -- frontend/src/i18n-today.js frontend/src/screens/CustomerCase.jsx \
  frontend/src/screens/CustomerCase.paymentStatus.test.jsx
git commit -m "feat(case): the system's answer beside a person's payment status, and its history row

While a person's change stands the statuses card says what the system worked
out; the history shows each change with who and why, and says whose change the
system ended. Spec 2026-09-14-payment-status-adjustment-design.md §3.4, §3.6.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UHXYThDWp1AZ91CXVstTPs"
```

---

### Task 6: Verify end to end

**Files:** none changed, unless verification finds a defect.

- [ ] **Step 1: Run everything**

Run: `cd /Users/parattakorn/volt-debt-prototype && ./scripts/verify_all.sh 2>&1 | tail -25`
Expected: backend = the Task 0 count + 15; frontend = the Task 0 count + 8 tests and + 1 file; the black-box checks pass. The only failures allowed are the ones Task 0 listed. `verify_all.sh` does not enforce counts, so compare them yourself.

- [ ] **Step 2: See it working in the running app**

Start the app with `KEEP_UP=1 ./scripts/run_prototype.sh` (API on :8000, web on :5173). If a local Postgres is involved, point it at `volt_local`, never `volt_test`, which pytest truncates. There is no Playwright in the repo; borrow `playwright-core` from `~/tiktok-api-explore` with the cached chromium, and sign in as `owner.test` first if login is on (passwords in `~/.volt-test-accounts.json`). Open one LATE customer and:
1. Change the payment status to ปกติ with a reason. Check the chip, the system's-answer line, the history row, and the `/audit` screen row with act `PAYMENT_STATUS_SET`.
2. Try Save with no reason, and with the same status. Check the hints.

If a browser can't be driven, say so plainly in the report rather than claiming it was seen.

- [ ] **Step 3: Report**

Paste the before and after counts from Task 0 and Step 1, list the commits, and state that edit 34 was spent at the measured +7. List the §5 register items that stay open.
