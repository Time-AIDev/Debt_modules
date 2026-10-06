# Decided Constants and Decision Provenance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply Arina's rulings 87–89 to the three money constants, add a `DECIDED` config state so a ruled value can stay Owner-tunable, and switch penalty invoicing on.

**Architecture:** `backend/app/config.py` gains a `DecidedRule` dataclass and a `DECIDED` registry beside the existing `PendingRule`/`PENDING`. `backend/app/routers/settings.py` derives the row `state` from dict membership (`LOCKED` → `OPEN` → `DECIDED` → `SET`) and must fold `DECIDED` into its Owner-only computation. The money engine itself does not change: `money/penalty.py:43`'s `accrue()` already takes `rate` and `grace_days` as parameters.

**Tech Stack:** Python 3 / FastAPI / dataclasses / pytest (backend). React 18 / Vite / vitest / testing-library (frontend). No new dependencies.

**Spec:** `docs/archive/superpowers/specs/2026-09-09-decided-constants-design.md`

## Global Constraints

- **Test baseline, hold at or above: 401 backend / 312 frontend (28 files) / 29 e2e.** `./scripts/verify_all.sh` is the authority.
- **Run `pytest` WITHOUT `-q`.** `backend/pytest.ini` already sets it; doubling it hides the summary line.
- **Authorised test-edit budget is exactly these 7 files.** Touching any other test file is out of budget and must stop and escalate to Arina: `backend/tests/test_round1_p3.py`, `backend/tests/test_round3.py`, `backend/tests/test_penalty.py`, `backend/tests/test_today_and_pipeline.py`, `backend/tests/test_peak_documents.py`, `backend/tests/test_api.py`, `frontend/src/screens/Settings.test.jsx`. **Adding new tests is free and not charged to the budget.**
- **The evidence rule (spec §5).** Where `0.3 %/day` states *our rate*, it becomes `0.03 %/day`. Where it states *an external fact* — agreement §13.1's text, what `IVT-20260700089` billed, the sheet's Late Fee Logic tab, the CF1 source conflict — **it stays unchanged.**
- **Every user-facing string is bilingual.** Thai and English pairs in `frontend/src/i18n-admin.js`. Never hard-code copy in a component.
- **`peak_write_mode` is LOCKED to `DRAFT_ONLY` (C3).** Never change it.
- **Never remove** `PenaltyRow.rate` or `PenaltyRow.rate_resolution_level` (`money/penalty.py:38`). They are what make an Owner-tunable rate safe.
- **Do not touch** `backend/app/collection_kpi.py:335` or `:439`. Those `indicative` flags are R5-F16 / L4 and unrelated to CF1.
- Commit after every task. Branch is `design-team`; do not switch branches.

---

### Task 1: `DecidedRule`, the three constants, and the `DECIDED` config state

**Files:**
- Modify: `backend/app/config.py` (add `DecidedRule` + `DECIDED`; remove two `PENDING` entries; change three constants)
- Modify: `backend/app/routers/settings.py:10-31, 90-110, 114-135`
- Test: `backend/tests/test_round1_p3.py:307-317` (budget file 1 of 7)
- Test: `backend/tests/test_round3.py:340-344, 398-400` (budget file 2 of 7)

**Interfaces:**
- Produces: `config.DecidedRule` dataclass, `config.DECIDED` dict keyed by config key. `/v1/config` rows gain `state: "DECIDED"` plus `decided_by`, `decided_on`, `ruling`, `basis`. Later tasks read `settings.late_payment_daily_rate == Decimal("0.0003")` and `settings.late_payment_grace_days == 0`.

- [ ] **Step 1: Write the failing test — a decided rule reports DECIDED and stays Owner-only**

Add to `backend/tests/test_round1_p3.py`, directly below `test_j53_grace_days_and_daily_rate_are_owner_only_alike`:

```python
def test_r6_87_decided_rules_report_decided_and_stay_owner_only(client):
    """Rulings 87/88: CF1 and OD-31 are closed. The rows must say DECIDED and carry
    their provenance — and a MANAGER must still be refused, because Arina ruled them
    configurable by the Owner, not by anyone."""
    config = client.get("/v1/config", headers=OWNER).json()["config"]
    for key, decision, ruling in (("late_payment_daily_rate", "CF1", 87),
                                  ("late_payment_grace_days", "OD-31", 88)):
        row = config[key]
        assert row["state"] == "DECIDED"
        assert row["decision"] == decision
        assert row["ruling"] == ruling
        assert row["decided_by"] == "Arina"
        assert row["decided_on"] == "2026-09-09"
        assert row["basis"]
        assert row["editable_by"] == "OWNER"
    r = client.put("/v1/config", json={"late_payment_daily_rate": "0.01"}, headers=MANAGER)
    assert r.status_code == 403 and r.json()["extensions"]["editable_by"] == "OWNER"


def test_r6_87_the_three_ruled_constants_hold_their_ruled_values():
    assert settings.late_payment_daily_rate == Decimal("0.0003")   # ruling 87
    assert settings.late_payment_grace_days == 0                   # ruling 88
    assert settings.uninstall_fee_thb_per_watt == Decimal("5")     # ruling 89
```

Ensure `from decimal import Decimal` is imported at the top of that file; add it if absent.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_round1_p3.py -k r6_87 -v
```
Expected: FAIL — `KeyError: 'decision'` or `assert 'OPEN' == 'DECIDED'`.

- [ ] **Step 3: Add `DecidedRule` and `DECIDED` to `config.py`**

Insert immediately after the `PendingRule` dataclass definition (after `surfaces_as: str`):

```python
@dataclass(frozen=True)
class DecidedRule:
    """A decision that HAS been taken and whose value stays tunable by the Owner.

    PendingRule says "nobody has chosen". This says "Arina chose, here is when and on
    what". The distinction matters on screen: an officer told a settled thing is still
    open cannot trust either state.
    """

    key: str
    decision: str        # the code this closes, e.g. "CF1"
    decided_by: str
    decided_on: date
    ruling: int          # the entry in docs/design/round-6/00-ledger.md
    basis: str           # what the decision was taken on — cite something checkable
    editable_by: str = "OWNER"


DECIDED = {
    "late_payment_daily_rate": DecidedRule(
        key="late_payment_daily_rate",
        decision="CF1",
        decided_by="Arina",
        decided_on=date(2026, 9, 9),
        ruling=87,
        basis="Arina 2026-09-09, reaffirmed on challenge. Evidence read 0.3 %/day "
              "(agreement VL0010399 §13.1; three late-fee lines on IVT-20260700089); "
              "0.03 %/day = 10.95 %/yr, inside §13.2's 15 %/yr ceiling and close to the "
              "10 %/yr Volt's own lawyer claimed in Notice.pdf.",
    ),
    "late_payment_grace_days": DecidedRule(
        key="late_payment_grace_days",
        decision="OD-31",
        decided_by="Arina",
        decided_on=date(2026, 9, 9),
        ruling=88,
        basis="IVT-20260700089 — three instalments with three different due dates, all "
              "billed to one as-of date 2026-07-15, matching 0.3 %/day with zero days "
              "deducted. Penalty runs from the due date.",
    ),
}
```

- [ ] **Step 4: Remove the two closed entries from `PENDING`**

Delete the `"late_payment_daily_rate"` and `"late_payment_grace_days"` `PendingRule(...)` entries from the `PENDING` dict in `backend/app/config.py`. They are decided; a decided rule must not appear in the pending register.

- [ ] **Step 5: Change the three constants**

In `backend/app/config.py`, class `Settings`:

```python
    # --- decided, and still Owner-tunable (see DECIDED above) ----------------
    # Ruling 87 (CF1), Arina 2026-09-09. Evidence said 0.3 %/day; she ruled 0.03 %/day
    # = 10.95 %/yr, which is what Volt's lawyer actually claims. NOTE: PEAK still bills
    # 0.3 %/day, so our figures are 10x lower until AR moves PEAK's setting.
    late_payment_daily_rate: Decimal = Decimal("0.0003")
    # Ruling 88 (OD-31), Arina 2026-09-09. Penalty runs from the due date, no grace.
    late_payment_grace_days: int = 0
```

and, in the deck-constants block:

```python
    # Ruling 89, Arina 2026-09-09: 5, not 3. The signed agreement §16.1 and the
    # lawyer's demand in Notice.pdf both say 5 THB/watt (6.3 kWp -> THB 31,500).
    uninstall_fee_thb_per_watt: Decimal = Decimal("5")
```

Leave the surrounding `# --- pending, with a shipped default that is NOT a decision ---` comment attached to the entries that are still pending (`allocation_component_order`, `early_settlement_method`, `npl_dpd_threshold_days`, and the rest).

- [ ] **Step 6: Teach the router about `DECIDED`**

In `backend/app/routers/settings.py`, change the import on line 5 and the registries:

```python
from ..config import DECIDED, PENDING, settings
```

Remove the two decided keys from the `OPEN` dict — it now reads:

```python
OPEN = {
    "invoice_owner_role": "OQ-42 — Owner", "npl_review_dpd": "OD-04 extended — Owner, Whan",
    "npl_review_missed_no_contact": "OD-04 extended — Owner, Whan", "power_restriction_approver": "OQ-44 — Owner",
}
```

Then widen the Owner-only rule. **This line is load-bearing** — without `DECIDED` in it, a Manager silently gains the right to edit the late-fee rate:

```python
# Judge J-53: an OPEN value (a decision nobody has closed) is edited by the Owner only.
# Round 6 ruling 100: a DECIDED value stays Owner-only too — Arina ruled these
# configurable by the Owner, not by anyone with a Manager token.
OWNER_ONLY = tuple(k for k in EDITABLE if k in OPEN or k in DECIDED)
```

- [ ] **Step 7: Emit the decided state and its provenance**

In `_config_rows`, replace the `keys[key] = {...}` assignment (currently `settings.py:98-102`) with:

```python
        decided = DECIDED.get(key)
        keys[key] = {"value": str(value) if value is not None else None,
                     "state": "LOCKED" if key in LOCKED else (
                         "OPEN" if key in OPEN else ("DECIDED" if decided else "SET")),
                     "owner": OPEN.get(key),
                     # J-53: `editable` is answered for the CALLER's role; `editable_by` names the floor.
                     "editable": _may_edit(key, role), "editable_by": _editable_by(key)}
        if decided:
            # Ruling 100: a decided value carries who decided it, when, and on what —
            # so the screen can stop calling it undecided without going silent instead.
            keys[key].update({"decision": decided.decision, "decided_by": decided.decided_by,
                              "decided_on": decided.decided_on.isoformat(),
                              "ruling": decided.ruling, "basis": decided.basis})
```

- [ ] **Step 8: Fix the PUT refusal so it stops calling a decided rule open**

In `put_config`, replace the `_may_edit` failure branch (currently `settings.py:127-130`):

```python
        if not _may_edit(key, role):
            decided = DECIDED.get(key)
            detail = ("%s was decided by %s (ruling %d) and stays Owner-tunable; only the Owner may change it"
                      % (key, decided.decided_by, decided.ruling)) if decided else (
                     "%s is an OPEN decision (%s); only the Owner may change it" % (key, OPEN.get(key)))
            raise errors.Problem(code="forbidden", status=403, title="Owner only", detail=detail,
                                 message_th="ค่านี้แก้ไขได้เฉพาะเจ้าของระบบ",
                                 error_id="DEBT-IAM-0403",
                                 extensions={"key": key, "editable_by": "OWNER", "owner": OPEN.get(key)})
```

- [ ] **Step 9: Run the new tests — they must pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_round1_p3.py -k r6_87 -v
```
Expected: 2 passed.

- [ ] **Step 10: Update the two existing assertions that pin the old values**

`backend/tests/test_round1_p3.py` — in `test_j53_grace_days_and_daily_rate_are_owner_only_alike`, the loop asserting `state == "OPEN"` no longer describes these keys. Narrow that test to keys that are still open and let the new test cover the decided pair:

```python
def test_j53_grace_days_and_daily_rate_are_owner_only_alike(client):
    """Round 6: CF1 and OD-31 are DECIDED (rulings 87/88) and their coverage moved to
    test_r6_87_decided_rules_report_decided_and_stay_owner_only. What this test still
    guards is the ORIGINAL J-53 finding — that an Owner-only key is not editable by a
    Manager — on the keys that remain open."""
    for role in ("OFFICER", "MANAGER"):
        config = client.get("/v1/config", headers={"X-Volt-Role": role}).json()["config"]
        for key in ("invoice_owner_role", "npl_review_dpd"):
            assert config[key]["editable"] is False and config[key]["editable_by"] == "OWNER"
            assert config[key]["state"] == "OPEN" and config[key]["owner"]
    config = client.get("/v1/config", headers=OWNER).json()["config"]
    assert config["invoice_owner_role"]["editable"] is True and config["npl_review_dpd"]["editable"] is True
    r = client.put("/v1/config", json={"invoice_owner_role": "AR"}, headers=MANAGER)
    assert r.status_code == 403 and r.json()["extensions"]["editable_by"] == "OWNER"
```

`backend/tests/test_round3.py:344` — change the literal:

```python
    assert block["late_payment_grace_days"] == settings.late_payment_grace_days == 0
```

`backend/tests/test_round3.py:400` — change the literal:

```python
    assert money["penalty_grace_days"] == 0
```

- [ ] **Step 11: Run the full backend suite**

```bash
cd backend && .venv/bin/python -m pytest tests/
```
Expected: at or above 401 passed. Paste the summary line. If any test outside the 7 budget files fails, STOP and escalate — do not edit it.

- [ ] **Step 12: Commit**

```bash
git add backend/app/config.py backend/app/routers/settings.py \
        backend/tests/test_round1_p3.py backend/tests/test_round3.py
git commit -m "Rulings 87-89 — the three constants, and a DECIDED config state

Late fee 0.003 -> 0.0003, grace 14 -> 0, uninstall 3 -> 5 THB/W.
A ruled value can now be decided AND Owner-tunable, which the config
model could not express. OWNER_ONLY folds in DECIDED so moving the keys
out of OPEN does not hand a Manager the late-fee rate.

Budget: 2 of 7 authorised test files."
```

---

### Task 2: Penalty invoicing goes live

**Files:**
- Modify: `backend/app/config.py` (`penalty_invoicing_enabled`)
- Modify: `backend/app/peak_documents.py:103-104`
- Test: `backend/tests/test_peak_documents.py:97-100` (budget file 3 of 7)
- Test: `backend/tests/test_api.py:162` (budget file 4 of 7)
- Test: `backend/tests/test_today_and_pipeline.py:224` (budget file 5 of 7)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `settings.penalty_invoicing_enabled is True`. `raise_document(..., intent="PENALTY_INVOICE", ...)` now returns records instead of raising `PeakDocumentError("feature_disabled", ...)`.

- [ ] **Step 1: Write the failing test — a penalty draft is created, not refused**

Add to `backend/tests/test_peak_documents.py`:

```python
def test_r6_87_penalty_invoicing_is_live_and_creates_a_draft():
    """Ruling 87: CF1 is decided, so the gate opens. C3 still holds — what is created
    is a DRAFT; nothing here approves anything."""
    state = pkd.for_current()
    assert settings.penalty_invoicing_enabled is True
    records = pkd.raise_document(state, "PENALTY_INVOICE", "k-1", "SPV",
                                 {"amount": "236.85"}, by="x")
    assert records
    assert settings.peak_write_mode == "DRAFT_ONLY"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_peak_documents.py -k r6_87 -v
```
Expected: FAIL — `PeakDocumentError: feature_disabled`.

- [ ] **Step 3: Turn the flag on**

In `backend/app/config.py`, replace the feature-flag comment and value:

```python
    # --- feature flags -------------------------------------------------------
    # Ruling 87 (Arina, 2026-09-09): CF1 is decided, so this goes live. The rate is
    # Owner-tunable and every PenaltyRow snapshots the rate it used, so a later change
    # never restates history. C3 still holds: what reaches PEAK is a DRAFT.
    # ACCEPTED RISK, on the record: PEAK bills 0.3 %/day today and we now compute
    # 0.03 %/day, so our drafts read one tenth of the customer's own tax invoice until
    # AR moves PEAK's setting.
    penalty_invoicing_enabled: bool = True
```

- [ ] **Step 4: Restate the refusal so it names the live condition**

`backend/app/peak_documents.py:103-104` — the refusal is KEPT (the flag is Owner-tunable, so the disabled path stays reachable) but must stop citing a closed decision:

```python
    if intent == "PENALTY_INVOICE" and not settings.penalty_invoicing_enabled:
        raise PeakDocumentError("feature_disabled",
                                "Penalty invoicing is disabled by configuration (penalty_invoicing_enabled)")
```

- [ ] **Step 5: Run the new test — it must pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_peak_documents.py -k r6_87 -v
```
Expected: 1 passed.

- [ ] **Step 6: Update the three assertions that pin the flag off**

`backend/tests/test_peak_documents.py:97-100` — the existing test asserts the refusal. Rewrite it to prove the refusal still works when an Owner turns the flag off, which is the behaviour that now matters:

```python
def test_penalty_invoicing_refuses_when_an_owner_disables_it(monkeypatch):
    """The gate is kept because ruling 87 made the flag Owner-tunable. Turned off, it
    must still refuse — and its reason must name the configuration, not CF1."""
    monkeypatch.setattr(settings, "penalty_invoicing_enabled", False)
    state = pkd.for_current()
    with pytest.raises(pkd.PeakDocumentError) as err:
        pkd.raise_document(state, "PENALTY_INVOICE", "k-1", "SPV", {"amount": "150"}, by="x")
    assert err.value.code == "feature_disabled"
    assert "CF1" not in str(err.value)
```

Confirm `import pytest` and `from app.config import settings` are present at the top of that file; add whichever is missing.

`backend/tests/test_api.py:162` — read the surrounding test first. It asserts a `feature_disabled` code from an HTTP route. Apply the same `monkeypatch.setattr(settings, "penalty_invoicing_enabled", False)` inside that test so it continues to exercise the disabled path, and leave its assertion unchanged.

`backend/tests/test_today_and_pipeline.py:224` — change the literal:

```python
        assert mp["penalty_invoicing_enabled"] is True
```

- [ ] **Step 7: Run the full backend suite**

```bash
cd backend && .venv/bin/python -m pytest tests/
```
Expected: at or above 401 passed. Paste the summary line.

- [ ] **Step 8: Commit**

```bash
git add backend/app/config.py backend/app/peak_documents.py \
        backend/tests/test_peak_documents.py backend/tests/test_api.py \
        backend/tests/test_today_and_pipeline.py
git commit -m "Ruling 87 — penalty invoicing goes live

The gate is kept, not deleted: the flag is Owner-tunable, so the disabled
path must stay reachable and its reason now names the configuration
instead of a closed decision.

Budget: 5 of 7 authorised test files."
```

---

### Task 3: `is_indicative` — flip the default, audit the callers

**Files:**
- Modify: `backend/app/money/penalty.py:43` (default) and `:12` (docstring)
- Modify: `backend/app/main.py:830-835`
- Test: `backend/tests/test_penalty.py` (budget file 6 of 7)

**Interfaces:**
- Consumes: `settings.late_payment_grace_days == 0` from Task 1.
- Produces: `accrue(...)` returns `PenaltyRow(is_indicative=False)` by default. `PenaltyRow.rate` and `.rate_resolution_level` are unchanged and MUST remain.

- [ ] **Step 1: Audit every caller before changing anything**

```bash
cd /Users/parattakorn/volt-debt-prototype
grep -rn "accrue(\|accrue_range(\|is_indicative" backend/app --include='*.py'
```

Write the caller list into the commit message. **If any caller depends on the old `True` default, pass `is_indicative=True` explicitly at that call site rather than reverting the default.** Do not touch `backend/app/collection_kpi.py:335` or `:439` — those `indicative` flags are R5-F16 / L4 and unrelated.

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/test_penalty.py`:

```python
def test_r6_87_penalty_rows_are_no_longer_indicative_but_still_snapshot_their_rate():
    """Ruling 87 closed CF1, and penalty.py's own docstring conditioned `indicative` on
    'until Legal rules'. Legal ruled. The rate snapshot stays — it is what makes an
    Owner-tunable rate safe, because yesterday's rows keep yesterday's rate."""
    row = accrue(fx_c1_line(), accrual_date=date(2026, 10, 23),
                 rate=Decimal("0.0003"), grace_days=0)
    assert row.is_indicative is False
    assert row.rate == Decimal("0.0003")
    assert row.rate_resolution_level == "SYSTEM_DEFAULT"
```

- [ ] **Step 3: Run it and watch it fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_penalty.py -k r6_87 -v
```
Expected: FAIL — `assert True is False`.

- [ ] **Step 4: Flip the default and rewrite the docstring**

`backend/app/money/penalty.py` — the `accrue` signature:

```python
def accrue(instalment, accrual_date, rate, grace_days, frozen_days=0, reset_days=0,
           rate_resolution_level="SYSTEM_DEFAULT", is_indicative=False) -> PenaltyRow:
```

And replace the `⚠ CF1 IS OPEN` paragraph in the module docstring (currently lines 12-16):

```
CF1 IS DECIDED (ruling 87, Arina 2026-09-09): 0.03 %/day, and penalty invoicing to PEAK
is live. The evidence read 0.3 %/day — agreement VL0010399 §13.1 and three late-fee
lines on IVT-20260700089 — and she ruled 0.03 %/day, which is 10.95 %/yr and inside
§13.2's own ceiling. No rate is hard-coded here; the rate is Owner-tunable and every
row snapshots the rate it used, so a later change never restates history.

NOTE: PEAK still bills 0.3 %/day. Our figures are one tenth of the customer's own tax
invoice until AR moves PEAK's setting.
```

- [ ] **Step 5: Stop `main.py` hard-coding an indicative penalty**

`backend/app/main.py:830-835` currently hard-codes `"is_indicative": True` and `"pending_decision": "CF1"`. Replace both:

```python
        # Ruling 87: CF1 is decided, so this figure is no longer indicative and a PEAK
        # penalty draft may be created from it (C3 keeps that a draft).
        "is_indicative": False,
        "decided_by_ruling": 87,
```

Then check whether any test or frontend component reads `pending_decision` from this payload:

```bash
grep -rn "pending_decision" backend frontend/src --include='*.py' --include='*.jsx' --include='*.js'
```

If a **non-test** consumer reads it, keep the key and set it to `None` rather than removing it. If a **test outside the 7 budget files** reads it, STOP and escalate.

- [ ] **Step 6: Rewrite the stale spec-150 guard**

`backend/tests/test_penalty.py` — `test_the_spec_150_baht_worked_example_is_deliberately_not_implemented` now guards an abandoned rule. Its own docstring says *"if it ever goes green at 150.00 someone has quietly reopened a known contradiction"* — ruling 88 reopens it deliberately. Replace the whole test:

```python
def test_r6_88_the_spec_150_baht_worked_example_is_now_implemented():
    """Spec §15.2 ex.1: 5,000 x rate x 10 days, counting from day 1. §15.3 said penalty
    started on day 15 and the two contradicted; REQ-MNY-018 noted the 150 figure 'is not
    implemented'. Ruling 88 (Arina, 2026-09-09) closed that contradiction in §15.2's
    favour — grace is 0 and the count starts at the due date.

    At the ruled rate of 0.0003 the same ten days give 15.00, not 150.00: the shape of
    §15.2 is now implemented, at ruling 87's rate rather than the spec's.
    """
    line = Instalment(
        due_date=FIRST_DUE,
        category="REGULAR",
        principal_amount=Decimal("5000.00"),
        interest_amount=Decimal("0.00"),
        fee_amount=Decimal("0.00"),
    )
    row = accrue(line, accrual_date=date(2026, 10, 11), rate=Decimal("0.0003"), grace_days=0)

    assert row.days_past_due == 10
    assert row.chargeable_days == 10
    assert row.cumulative_amount == Decimal("15.00")
    # And at the rate the spec itself wrote, the example reproduces exactly.
    legacy = accrue(line, accrual_date=date(2026, 10, 11), rate=Decimal("0.003"), grace_days=0)
    assert legacy.cumulative_amount == Decimal("150.00")
```

Leave `RATE_DEBT_SPEC`, `RATE_PAY_SPEC` and `GRACE` at the top of the file untouched — every other test in it passes them explicitly and must keep passing unchanged.

- [ ] **Step 7: Run the full backend suite**

```bash
cd backend && .venv/bin/python -m pytest tests/
```
Expected: at or above 401 passed. Paste the summary line.

- [ ] **Step 8: Commit**

```bash
git add backend/app/money/penalty.py backend/app/main.py backend/tests/test_penalty.py
git commit -m "Ruling 87/88 — penalty figures are no longer indicative

penalty.py conditioned `indicative` on 'until Legal rules'. Legal ruled.
The rate and rate_resolution_level snapshots stay: they are what make an
Owner-tunable rate safe.

The spec-150 guard was rewritten rather than left green — it stood watch
over the §15.2/§15.3 contradiction that ruling 88 deliberately closed.

Caller audit: <paste the grep result here>

Budget: 6 of 7 authorised test files."
```

---

### Task 4: The runtime strings that still say CF1 is open

**Files:**
- Modify: `backend/app/uat_tasks.py:169-170`
- Modify: `backend/app/migration.py:93`
- Modify: `backend/app/routers/journey.py:126-127` and `:183`

**Interfaces:**
- Consumes: nothing. Produces: nothing. Copy only.
- No test budget. If any assertion breaks on this text, STOP and escalate — the budget is spent.

- [ ] **Step 1: Rewrite the UAT limitation**

`backend/app/uat_tasks.py` — replace the first entry of `LIMITATIONS`:

```python
    "Penalty figures use the rate decided in ruling 87 (Arina, 2026-09-09): 0.03 %/day. "
    "PEAK still bills 0.3 %/day, so a figure here reads one tenth of the customer's own "
    "tax invoice until AR moves PEAK's setting.",
```

- [ ] **Step 2: Fix the migration method string — line 93 only**

`backend/app/migration.py:93` — the interpolated numbers already follow `settings`, so only the trailing clause changes:

```python
                   "method": "each instalment aged separately, simple, %s%%/day after %d days grace — decided, ruling 87"
                             % (settings.late_payment_daily_rate * 100, settings.late_payment_grace_days)},
```

**Do NOT touch line 91.** `"cumulative balance in monthly blocks at 0.3%/day (Late Fee Logic tab)"` describes **the sheet's** method — an external fact under the evidence rule. Two adjacent lines, opposite treatment.

- [ ] **Step 3: Fix the two journey strings**

`backend/app/routers/journey.py:126-127`, inside the docstring:

```
    at the decided rate (ruling 87); the penalty IS now invoiced to PEAK as a draft, and
    the sheet's own late-fee cell is shown beside it so the officer sees both books."""
```

`backend/app/routers/journey.py:183`:

```python
        "note_en": "amount to ask = instalments overdue; penalty accrues at the decided rate (ruling 87) and is raised to PEAK as a draft; the sheet's late-fee cell is shown for comparison",
```

Then read the `note_th` built above line 182 and make the Thai say the same thing. **Both languages must move together** — a Thai string still saying `CF1` while the English says "decided" is the defect this task exists to remove.

- [ ] **Step 4: Prove no string still claims CF1 is open**

```bash
cd /Users/parattakorn/volt-debt-prototype
grep -rn "CF1 IS OPEN\|CF1 is open\|is not agreed\|while CF1" backend/app --include='*.py'
```
Expected: no output.

- [ ] **Step 5: Run the full backend suite**

```bash
cd backend && .venv/bin/python -m pytest tests/
```
Expected: at or above 401 passed, no new failures. Paste the summary line.

- [ ] **Step 6: Commit**

```bash
git add backend/app/uat_tasks.py backend/app/migration.py backend/app/routers/journey.py
git commit -m "Ruling 87 — the runtime strings stop saying CF1 is open

Five user-visible strings asserted an open decision that is now closed.
migration.py:91 is deliberately unchanged: it describes the sheet's own
method, which is evidence, not our rate."
```

---

### Task 5: The Settings screen renders a decided rule

**Files:**
- Modify: `frontend/src/screens/Settings.jsx:214, 247-248` (and the `row.state` branch near `:539-542`)
- Modify: `frontend/src/i18n-admin.js` (both the English and the Thai block)
- Test: `frontend/src/screens/Settings.test.jsx` (budget file 7 of 7)

**Interfaces:**
- Consumes: `/v1/config` rows carrying `state: "DECIDED"`, `decided_by`, `decided_on`, `ruling`, `decision` from Task 1.

- [ ] **Step 1: Add the bilingual strings**

`frontend/src/i18n-admin.js` — in the English block, beside `'set.ownerOnly'`:

```js
  'set.decidedRow': 'decided · {by} · {on} · {decision}',
  'set.decidedTunable': 'decided — Owner may still tune it',
```

In the Thai block, beside the Thai `'set.ownerOnly'`:

```js
  'set.decidedRow': 'ตัดสินแล้ว · {by} · {on} · {decision}',
  'set.decidedTunable': 'ตัดสินแล้ว — เจ้าของระบบยังปรับได้',
```

- [ ] **Step 2: Write the failing test**

In `frontend/src/screens/Settings.test.jsx`, add a decided row to the config mock used by the suite (beside the existing `late_payment_grace_days` entry):

```js
    late_payment_daily_rate: {
      value: '0.0003', state: 'DECIDED', owner: null, editable: true, editable_by: 'OWNER',
      decision: 'CF1', decided_by: 'Arina', decided_on: '2026-09-09', ruling: 87,
      basis: 'agreement VL0010399 §13.1; IVT-20260700089',
    },
```

and add the test:

```js
  it('a DECIDED rule shows who decided it and stays Owner-only', async () => {
    renderSettings({ role: 'OWNER' })
    const row = await screen.findByTestId('cfg-late_payment_daily_rate')
    expect(row).toHaveAttribute('data-state', 'DECIDED')
    expect(within(row).getByTestId('cfg-decided-late_payment_daily_rate'))
      .toHaveTextContent('Arina')
    expect(within(row).queryByTestId('cfg-open-late_payment_daily_rate')).not.toBeInTheDocument()
    expect(within(row).getByTestId('cfg-edit-late_payment_daily_rate')).toBeInTheDocument()
  })

  it('a MANAGER cannot edit a DECIDED rule', async () => {
    renderSettings({ role: 'MANAGER' })
    const row = await screen.findByTestId('cfg-late_payment_daily_rate')
    expect(within(row).queryByTestId('cfg-edit-late_payment_daily_rate')).not.toBeInTheDocument()
  })
```

Match `renderSettings` to whatever helper the file already uses — read the top of the file first and follow its existing pattern rather than inventing one.

- [ ] **Step 3: Run it and watch it fail**

```bash
cd frontend && npx vitest run src/screens/Settings.test.jsx
```
Expected: FAIL — `cfg-decided-late_payment_daily_rate` not found.

- [ ] **Step 4: Widen the owner-only gate — the trap**

`frontend/src/screens/Settings.jsx:214`. Without this, a Manager gains the edit control on the late-fee rate the moment Task 1 moves the keys out of `OPEN`:

```js
                // An OPEN decision (nobody has closed it) and a DECIDED one (ruling 87/88,
                // Owner-tunable) are both Owner-only. SET keys keep the Manager/Owner rule.
                const ownerOnly = row.state === 'OPEN' || row.state === 'DECIDED'
```

- [ ] **Step 5: Render the provenance chip**

`frontend/src/screens/Settings.jsx`, immediately after the existing `row.state === 'OPEN' && (...)` block at `:247-248`:

```jsx
                      {row.state === 'DECIDED' && (
                        <span className="ad-quiet" data-testid={`cfg-decided-${key}`}> · {t('set.decidedRow', {
                          by: row.decided_by || '—', on: row.decided_on || '—', decision: row.decision || '—',
                        })}</span>
                      )}
```

Then read the `row.state === 'LOCKED'` / `row.state === 'OPEN'` branch near `:539-542` and add a `DECIDED` arm returning `t('set.decidedTunable')`, following whatever shape the two existing arms use.

- [ ] **Step 6: Run the frontend suite**

```bash
cd frontend && npx vitest run
```
Expected: at or above 312 passed across 28 files. Paste the summary line. If a test outside `Settings.test.jsx` fails, STOP and escalate — the budget is spent.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/Settings.jsx frontend/src/i18n-admin.js \
        frontend/src/screens/Settings.test.jsx
git commit -m "Ruling 100 — Settings renders a decided rule

The officer stops being told a settled thing is undecided. ownerOnly now
covers DECIDED as well as OPEN: without it, moving the keys out of OPEN
hands a Manager the late-fee rate.

Budget: 7 of 7 authorised test files."
```

---

### Task 6: The Thai divergence note on penalty drafts

**Files:**
- Modify: `backend/app/peak_documents.py` (in `raise_document`, after the intent gates)
- Test: `backend/tests/test_peak_documents.py` — **a NEW test, which is free and not charged to the budget**

**Interfaces:**
- Consumes: `settings.late_payment_daily_rate` from Task 1, the open gate from Task 2.
- Produces: every `PENALTY_INVOICE` payload carries a `note_th` key.

- [ ] **Step 1: Write the failing test**

```python
def test_r6_87_a_penalty_draft_carries_a_thai_note_naming_the_peak_divergence():
    """Our rate is 0.03 %/day; PEAK bills 0.3 %/day. AR approves these drafts, so she is
    the one person who can catch the gap — she should not have to derive it."""
    state = pkd.for_current()
    records = pkd.raise_document(state, "PENALTY_INVOICE", "k-1", "SPV",
                                 {"amount": "236.85"}, by="x")
    note = records[0].payload["note_th"]
    assert "0.03" in note and "PEAK" in note
    assert len(note) <= 500          # PEAK's หมายเหตุ column caps at 500 characters
```

Read how `raise_document` stores records first and address `payload` the way the existing tests in that file do.

- [ ] **Step 2: Run it and watch it fail**

```bash
cd backend && .venv/bin/python -m pytest tests/test_peak_documents.py -k divergence -v
```
Expected: FAIL — `KeyError: 'note_th'`.

- [ ] **Step 3: Attach the note**

In `raise_document`, after the `PENALTY_INVOICE` gate and before the records are built:

```python
    if intent == "PENALTY_INVOICE":
        # A5 §2b: PEAK's import carries หมายเหตุ (column R, max 500 chars). Our rate is
        # ruling 87's 0.03 %/day while PEAK bills 0.3 %/day, so a draft reads one tenth
        # of the customer's own tax invoice. AR approves these — say it on the document
        # rather than leaving her to derive it.
        payload = dict(payload)
        payload["note_th"] = (
            "ค่าปรับคำนวณที่อัตรา %s%%/วัน ตามการตัดสิน CF1 (ruling 87, 2026-09-09) "
            "ขณะนี้ PEAK ยังตั้งค่าที่ 0.3%%/วัน ยอดในเอกสารนี้จึงต่างจากใบแจ้งหนี้เดิมของลูกค้า "
            "กรุณาตรวจสอบก่อนอนุมัติ" % (settings.late_payment_daily_rate * 100)
        )[:500]
```

- [ ] **Step 4: Run the new test — it must pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_peak_documents.py -k divergence -v
```
Expected: 1 passed.

- [ ] **Step 5: Run the full backend suite**

```bash
cd backend && .venv/bin/python -m pytest tests/
```
Expected: **above** 401 — this task adds a test without spending budget. Paste the summary line.

- [ ] **Step 6: Commit**

```bash
git add backend/app/peak_documents.py backend/tests/test_peak_documents.py
git commit -m "Ruling 87 — penalty drafts state the PEAK rate divergence in Thai

A silent 10x gap becomes a sentence at the desk of the only person who
can catch it. Fits PEAK's หมายเหตุ column (A5 2b, 500 chars).

New test, not charged to the budget."
```

---

### Task 7: The documentation sweep

**Files:** ~23 files across `backend/app`, `briefs/`, `docs/`. `briefs/spec-money-engine.md` alone carries 19 occurrences (2 rate + 17 grace).

**Interfaces:** none. Prose only. **No test budget** — if any test asserts on this prose, STOP and escalate.

- [ ] **Step 1: Enumerate the surface**

```bash
cd /Users/parattakorn/volt-debt-prototype
grep -rn "0\.3 %/day\|0\.3%/day\|0\.3 % ต่อวัน\|0\.3% ต่อวัน\|ร้อยละ 0\.3" \
  backend/app briefs docs --include='*.py' --include='*.md' --include='*.html'
grep -rn "grace 14\|14-day grace\|day 15\|ผ่อนผัน 14" \
  backend/app briefs docs --include='*.py' --include='*.md' --include='*.html'
```

- [ ] **Step 2: Classify every hit before editing any of it**

Apply the evidence rule from spec §5 to each occurrence:

| kind | example | action |
|---|---|---|
| a claim about **our** rate or grace | *"the app draws 0.3 %/day"*, *"after 14 days grace"* | → `0.03 %/day`, → grace `0` |
| an **external fact** | agreement §13.1's text · what `IVT-20260700089` billed · the sheet's Late Fee Logic tab · the CF1 source conflict (`0.3` Debt spec vs `0.1` PAY v1.2) | **leave unchanged** |

**`docs/design/round-6/A4-drive-folder-evidence.md` and the ruling-87 entry in `docs/design/round-6/00-ledger.md` keep their `0.3 %` figures in full.** They are the record of the evidence Arina overrode; ruling 87 is only legible if they survive.

- [ ] **Step 3: Update the live spec**

`briefs/spec-money-engine.md` — the heaviest single file. Update every statement of our rule. Add at the top of its penalty section:

```markdown
> **Superseded 2026-09-09 by rulings 87 and 88.** The late-fee rate is **0.03 %/day**
> and there is **no grace period** — penalty runs from the due date. Passages below that
> quote source documents (agreement VL0010399 §13.1, PAY v1.2, the sheet's Late Fee
> Logic tab) keep their original figures: they are evidence, not our rate.
```

- [ ] **Step 4: Update the historical records, each with a correction stamp**

Arina's instruction was *"no adjust in all history document"* — history included. Update the figures **and** stamp each file, at the top, so the change is legible rather than silent:

```markdown
> **Corrected 2026-09-09.** This record was written when the late-fee rate was
> 0.3 %/day with 14 days' grace. Rulings 87 and 88 set 0.03 %/day and no grace;
> the figures below have been updated to match. See
> `docs/design/round-6/00-ledger.md` rulings 87–88.
```

Files: `docs/uat/round-2/{nantapol,settasak,thip}.md` · `docs/uat/round-3/judge.md` · `docs/uat/round-4/{nantapol,judge}.md` · `docs/uat/round-5/{nantapol,judge}.md` · `docs/uat/round-5.md` · `docs/uat/round-6/settasak.md` · `docs/design/round-1/cluster-1/C-review.md` · `docs/design/round-3/cluster-3/{D-audit,F-api,api-change-request}.md` · `docs/design/round-4/board/B-system.md` · `docs/Debt_Time_Build_Evidence_Addendum.md`

- [ ] **Step 5: Verify nothing was missed and nothing was over-swept**

```bash
grep -rn "0\.3 %/day\|0\.3%/day" backend/app briefs docs --include='*.py' --include='*.md' --include='*.html'
```

Every remaining hit must be an external fact you can name. If you cannot say which source a surviving `0.3 %` quotes, it was missed — fix it.

- [ ] **Step 6: Run the whole verification**

```bash
cd /Users/parattakorn/volt-debt-prototype && ./scripts/verify_all.sh
```
Expected: **401 backend / 312 frontend (28 files) / 29 e2e or above.** Paste all three counts.

- [ ] **Step 7: Commit**

```bash
git add briefs docs backend/app
git commit -m "Rulings 87-88 — the documentation sweep

Every statement of our own rate and grace updated. Historical records
carry a correction stamp rather than a silent edit. Source quotations —
agreement 13.1, PAY v1.2, the sheet's Late Fee Logic tab — keep their
original figures: ruling 87 only reads as a decision if the evidence it
overrode survives."
```

---

## Done when

- [ ] `./scripts/verify_all.sh` reports **401 / 312 (28 files) / 29 or above**, counts pasted
- [ ] Exactly the 7 authorised test files were edited, and no others
- [ ] `grep -rn "while CF1\|CF1 is open\|CF1 IS OPEN" backend/app` returns nothing
- [ ] A `PENALTY_INVOICE` draft can be created and carries its Thai divergence note
- [ ] A MANAGER is still refused on `late_payment_daily_rate` and `late_payment_grace_days`
- [ ] `docs/design/round-6/00-ledger.md` and `A4-drive-folder-evidence.md` still contain `0.3 %`

## Not in this plan

VAT in the money engine (#2) · the PEAK invoice export and G1–G5 (#4) · the billing note (#5) · document templates and `.docx`/`.pdf` export (#6) · PDPA storage (#7) · the D3 join-key spike (#8). Rulings 90, 94 and 95 inherit the `DecidedRule` shape built here but are not implemented.

### The coupling to expect, so Task 6 is not mistaken for a finished integration

`A5` established that a PEAK late-fee line needs product code **`P00042`** and `อัตราภาษี = NO`. The draft Task 6 creates has **neither** — product codes are gap **G2**, which belongs to piece #4.

**Penalty invoicing goes live for the figure; the draft is not import-shaped.** Two different mechanisms reach PEAK — `peak_documents.raise_document` (drafts, this plan) and the file export (`A5`, piece #4) — and completing this plan does not complete the second.

## Arina's action, which no task can do

**Aynaz must be told, and PEAK's own late-fee setting has to move to 0.03 %/day.** Until it does, every penalty draft this system creates reads one tenth of the tax invoice the customer already received. Task 6's note makes that visible; it does not fix it.
