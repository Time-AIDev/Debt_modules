# Decided constants and decision provenance — design

**Date:** 2026-09-09 · **Author:** orchestrator, with Arina · **Status:** approved, ready for planning
**Round:** 6, piece #1 of 8 · **Rulings implemented:** 87, 88, 89, and the config half of 100

Brainstormed 2026-09-09 in four approved sections. Companion documents:
`docs/design/round-6/00-ledger.md` (rulings 87–100), `A4-drive-folder-evidence.md` (the evidence),
`A5-peak-export-column-spec.md` (piece #4, which this one does not touch).

---

## 1. Why this exists

Three money constants in this prototype are wrong against decisions Arina took on 2026-09-09, and the
config system has no way to say a decision has been *made*. A rule here is either an **open decision**
(Owner-only, rendered to officers as *"รอตัดสิน"*) or a bare constant with no story. Arina's rulings
90, 94 and 95 all take the shape **"X as default, configurable later"**, which is neither.

This piece changes the three constants, adds the missing state, and switches penalty invoicing on.
It is the smallest piece of round 6 and it establishes the provenance shape three later rulings reuse.

**Path note.** This began as a bounded constant change and was upgraded to architectural mid-session,
because adding a state to the config model changes the `/v1/config` response shape that other code
reads. The upgrade was announced, not absorbed.

---

## 2. Scope

**In:** the three constants · a `DecidedRule` config state · `penalty_invoicing_enabled` → `True` ·
the seven runtime strings asserting CF1 is open · the Settings screen's rendering of a decided rule ·
a divergence note on penalty drafts · a documentation sweep.

**Out:** VAT in the money engine (#2) · the PEAK invoice export and gaps G1–G5 (#4) · the billing note
(#5) · document templates and `.docx`/`.pdf` export (#6) · PDPA storage (#7) · the D3 join-key spike
(#8). Rulings 90, 94 and 95 **inherit** the `DecidedRule` shape built here but are **not implemented**
in this piece.

---

## 3. The rulings

| ruling | decision | change |
|---|---|---|
| **87** (CF1) | late fee **0.03 %/day** | `late_payment_daily_rate: 0.003 → 0.0003` |
| **88** (OD-31) | **no grace** — penalty runs from the due date | `late_payment_grace_days: 14 → 0` |
| **89** (L2/I-7) | uninstall **5 THB/watt** | `uninstall_fee_thb_per_watt: 3 → 5` |
| **87** (extension) | **penalty invoicing ON**, rate Owner-configurable | `penalty_invoicing_enabled: False → True` |
| **100** (config half) | decided rules stay tunable | new `DecidedRule` state |

### 3.1 Ruling 87 was challenged once and reaffirmed

Every source says `0.3 %/day`: agreement VL0010399 §13.1 and its worked example
(`0.3% × 10 × ฿5,000 = ฿150`), and three late-fee lines on `IVT-20260700089` matching `0.003` to the
satang across three different day counts. Arina was shown that and answered `0.03 confirm`.

**It is coherent as policy.** `0.3 %/day` is 109.5 %/yr; **`0.03 %/day` is 10.95 %/yr** — inside the
agreement's own §13.2 ceiling of 15 %/yr, and close to the **10 %/yr Volt's own lawyer claimed in
`Notice.pdf`**. The system will bill what Volt is willing to defend, not the contract's headline rate.

### 3.2 The figures this moves

The two rulings pull opposite ways — grace 0 adds 14 chargeable days, the rate cut removes 90 % — and
the rate wins:

| ฿8,399 instalment, 94 days past due | figure |
|---|---|
| today (`0.003`, grace 14 → 80 chargeable days) | ฿2,015.76 |
| **ruled** (`0.0003`, grace 0 → 94 chargeable days) | **฿236.85** |
| what PEAK actually billed this customer | ฿2,368.52 |

Uninstall on a 6,300 W lot: **฿18,900 → ฿31,500**.

### 3.3 Accepted risk, recorded

**Our penalty figures become one tenth of PEAK's.** PEAK bills `0.3 %/day` today, proven. Arina chose
to switch penalty invoicing on anyway, having been shown this.

Two things make it survivable, and both already exist:

- **`peak_write_mode` is LOCKED to `DRAFT_ONLY` (C3).** Every penalty document is a *draft*; Aynaz
  approves inside PEAK. A human sees the figure before a customer does.
- The exposure is **under-billing**, which is the direction the ruling intends.

**Arina carries one action this design cannot:** Aynaz must be told, and PEAK's own late-fee setting
has to move to `0.03 %/day`, or our drafts will permanently contradict the tax invoices those
customers already received.

---

## 4. Design

### 4.1 The `DecidedRule` config state

`backend/app/config.py` today models `PendingRule` with states `RUNNING` / `REFUSING` / `LEAKING`
(config.py:17–22) — these describe **whether a figure is produced**, not whether a decision is made.
Add a rule kind that carries decision provenance, in the idiom this codebase already uses everywhere
(`data_source`, `source_ref`, `basis`):

```
decision     "CF1"                                     the code it closes
decided_by   "Arina"
decided_on   2026-09-09
ruling       87                                        the ledger entry
basis        "agreement VL0010399 §13.1; IVT-20260700089"
editable_by  "OWNER"                                   still tunable
```

**Applied to:** `late_payment_daily_rate` (CF1 → ruling 87) and `late_payment_grace_days`
(OD-31 → ruling 88). Both leave the pending register.

**`/v1/config` response:** the `state` field gains the value **`"DECIDED"`**, alongside today's
`"OPEN"`. Any consumer reading `state` must handle it. This is the interface change that made this
piece architectural.

**Not a new mechanism.** `editable_by: "OWNER"` already exists and already works; what changes is that
a rule can be **editable and decided at the same time**, which today it cannot express.

### 4.2 The three constants

`config.py:156` `late_payment_daily_rate: Decimal("0.003") → Decimal("0.0003")`
`config.py` `late_payment_grace_days: 14 → 0`
`config.py:172` `uninstall_fee_thb_per_watt: Decimal("3") → Decimal("5")`

**No engine change.** `money/penalty.py:43` — `accrue(instalment, accrual_date, rate, grace_days, …)`
takes rate and grace as parameters and hard-codes neither. This is genuinely configuration.

**Behaviour check at grace 0:** `chargeable_days = max(days_past_due - grace_days, 0)`. On the due
date `days_past_due == 0`, so `chargeable_days == 0` and the explainable zero row (TC-MNY-054) is
still written. That behaviour survives; its window narrows from 14 days to the due date itself.

**Ruling 89 is free and self-correcting.** `uninstall_fee_thb_per_watt` has **zero** test references.
`i18n-journey.js:219` already renders `'Uninstall fee {amount} (THB 5/W × {watt} W)'` beside an
amount computed at 3 (`journey.py:499`) — a §1a honesty defect. Setting the constant to 5 makes the
label true; no separate fix is needed.

### 4.3 Penalty invoicing goes live

`config.py:199` `penalty_invoicing_enabled: False → True`.

`peak_documents.py:103-104` refuses `PENALTY_INVOICE` with *"Penalty invoicing is OFF while CF1 is
open"*. **The refusal is kept, not deleted** — the flag is Owner-configurable, so the disabled path
stays reachable — but its message must name the live condition, not a closed decision. It becomes:
**"Penalty invoicing is disabled by configuration (`penalty_invoicing_enabled`)"**. CF1 is not
mentioned, because CF1 no longer gates anything.

**The safeguard that makes "configurable" survivable already exists.** `PenaltyRow` snapshots `rate`
and `rate_resolution_level` on every row (`penalty.py:38`), commented *"so a later rate change never
silently restates history."* Written for an undecided rate, it is now the reason an Owner may tune the
rate at all: yesterday's rows keep the rate they were computed at. **Do not remove it.**

**UI consequence — expected, not a regression.** `MoneyPosition.jsx:17` exports `penaltyHeld()`,
shared by `Today.jsx` and `WorkBook.jsx`:

```js
return mp?.penalty_invoicing_enabled === false && owner !== ''
```

With the flag `true` this returns false everywhere, so the CF1 refusal sentence, band marks and column
marks built by rulings R1-C02 / R2-D02 / R3-D01 stop rendering. **That is correct** — they exist to
say "not billing, CF1 undecided", and CF1 is decided. **Keep the machinery**: an Owner switching the
flag off must still get the held state. It goes quiet, not away.

### 4.4 The seven runtime strings

These are text the system shows people, not comments. All seven become false when ruling 87 lands and
must move in the same change:

| file:line | claim |
|---|---|
| `peak_documents.py:104` | *"Penalty invoicing is OFF while CF1 is open"* — the API refusal |
| `routers/journey.py:183` | `note_en`: *"…not invoiced while CF1 is open"* — served on the wire |
| `routers/journey.py:126` | the same claim in the governing docstring |
| `uat_tasks.py:169` | *"…the rate is decision CF1 and is not agreed"* — shown to UAT testers |
| `migration.py:93` | *"INDICATIVE while CF1 is open"* |
| `main.py:832` | *"CF1 is open. Every figure here is indicative…"* |
| `money/penalty.py:12` | *"⚠ CF1 IS OPEN. The rate is 0.3 %/day…"* |

Leaving any of them is the R6-A01 defect class: the interface asserting what the system no longer
believes.

### 4.5 The Settings screen

`Settings.jsx:210` renders an open decision as *"รอตัดสิน · เจ้าของ OD-31 — Legal"*. A decided rule
renders its provenance instead — decided by, when, and the ruling — and keeps its Owner edit control,
because it is still tunable. The officer stops being told a decided thing is undecided.

**Bilingual, like every other label in this app:** the new string needs a Thai and an English form in
`i18n-admin.js` (e.g. `ตัดสินแล้ว · Arina · 2026-09-09 · CF1` / `Decided · Arina · 2026-09-09 · CF1`).
It must not be hard-coded in the component.

### 4.6 The divergence note on penalty drafts

Our drafts will read `฿236.85` where PEAK's invoices for the same customer read `฿2,368.52`. Aynaz
must not have to derive that.

Every `PENALTY_INVOICE` draft carries a note stating the rate used and that it differs from PEAK's
setting, until PEAK's rate moves — **in Thai, because its reader is AR**, naming the rate applied and
that PEAK's own setting has not yet moved to match. It is written by the server onto the document, not
composed in the interface. PEAK's own import template provides the field —
**`หมายเหตุ`, column R, max 500 characters** (`A5` §2b). One line of text that converts a silent 10×
discrepancy into a sentence at the desk of the only person who can catch it.

### 4.7 `is_indicative` — decided here, verified in implementation

`accrue()` takes `is_indicative=True` as its default (`penalty.py:43`), and the module docstring
conditions it explicitly: *"Until Legal rules, every figure this module produces is INDICATIVE."*
**Legal has now ruled.**

**Decision: the default flips to `False`.** The parameter and the per-row field both stay — a caller
may still mark a row indicative, and the field is snapshotted per row for the same reason `rate` is.

**Verification required during implementation, not assumed here:** every caller of `accrue()` and
`accrue_range()` must be audited, plus every consumer reading `is_indicative` downstream
(`collection_kpi.py` carries its own separate `indicative` flags at `:335` and `:439`, which are
**R5-F16 / L4 and unrelated** — they must not be swept up in this change). If the audit finds a caller
that depends on the old default, it is named and passed explicitly rather than the default being
reverted silently.

### 4.8 The documentation sweep

Arina's instruction: *"fix for all related document"*, and on being offered a history exemption:
*"no adjust in all history document"* — **all documents, history included.**

Measured surface: **~23 files**. Rate `0.3 %/day` — 16 files, 24 occurrences. Grace `14` / `day 15` —
17 files, 41 occurrences. `briefs/spec-money-engine.md` alone carries 19.

**Historical files** (`docs/uat/round-*`, `docs/design/round-1|3|4/*`,
`docs/Debt_Time_Build_Evidence_Addendum.md`) are updated **and stamped** with a correction line naming
what the file previously said, the ruling that changed it, and the date — so the figures are current
without erasing that a correction occurred.

---

## 5. What must NOT change — the evidence rule

`0.3 %/day` appears as two different things, and a blanket find-and-replace would break ruling 87
itself.

| kind | example | action |
|---|---|---|
| **a claim about our rate** | *"0.003, in every indicative penalty figure the app draws"* (`config.py:49`) | → `0.0003` |
| **an external fact** | agreement §13.1's text · what `IVT-20260700089` actually billed · the CF1 source conflict (`0.3` Debt spec vs `0.1` PAY v1.2) | **unchanged** |

Ruling 87 is only legible if the evidence it overrode survives. `A4-drive-folder-evidence.md` and the
ruling-87 entry in `00-ledger.md` therefore **keep** their `0.3 %` figures.

---

## 6. Test contract

**Baseline to hold at or above: 401 backend / 312 frontend (28 files) / 29 e2e.** Counts pasted, not
summarised.

**Authorised by Arina 2026-09-09: 7 files.** Every one pins a policy deliberately reversed — none is a
test bent to fit broken code.

| file | what moves |
|---|---|
| `backend/tests/test_round1_p3.py` | `:312` `state == "OPEN"`; `:317` `settings.late_payment_grace_days == 14` |
| `backend/tests/test_round3.py` | `:344` and `:400`, literal `14` |
| `backend/tests/test_penalty.py` | `test_the_spec_150_baht_worked_example_is_deliberately_not_implemented` — rewritten |
| `backend/tests/test_today_and_pipeline.py` | `:224` `penalty_invoicing_enabled is False` |
| `backend/tests/test_peak_documents.py` | `:97–100` — `feature_disabled` now succeeds instead of raising |
| `backend/tests/test_api.py` | `:162` `code == "feature_disabled"` |
| `frontend/src/screens/Settings.test.jsx` | mock + assertions for the decided state |

### 6.1 The stale guard, and why it must be rewritten rather than left green

`test_penalty.py`'s spec-150 test warns in its own docstring: *"if it ever goes green at 150.00
someone has quietly reopened a known contradiction."* **Ruling 88 reopens it deliberately and closes
it in §15.2's favour.** The test passes `GRACE = 14` by hand, so it will keep passing while standing
guard over an abandoned rule. A green test defending dead policy is a worse signal than a red one.

### 6.2 Tests that do NOT move

`test_penalty.py` (beyond 6.1), `test_contract_accrual.py` and `test_customer_rollup.py` define their
own `RATE = Decimal("0.003")` / `GRACE = 14` and pass them **explicitly** to `accrue()`. They test the
function's arithmetic, not the configuration, and stay green untouched.

`CustomerCase.jsx:1176` reads `recon.late_payment_grace_days` from the API and follows automatically.

---

## 7. Verification

`./scripts/verify_all.sh` is the authority: backend units → frontend components → the app running →
black-box checks. Run `pytest` **without** `-q` — `pytest.ini` already sets it, and doubling it hides
the summary line.

---

## 8. Sequence

1. `DecidedRule` model, the three constants, `penalty_invoicing_enabled: True`
2. The seven runtime strings
3. Settings screen renders the decided state
4. The `หมายเหตุ` divergence note on penalty drafts
5. The ~23-file documentation sweep with correction stamps
6. Tests — last, against the authorised 7-file budget

---

## 9. Coupling to name

`A5` established that a PEAK late-fee line needs product code **`P00042`** and `อัตราภาษี = NO`. Our
penalty draft has neither; product codes are gap **G2**, which belongs to piece #4.

**Penalty invoicing goes live for the figure, but the draft is not import-shaped until G2 lands.**
Two different paths reach PEAK — `peak_documents.raise_document` (drafts, this piece) and the file
export (`A5`, piece #4) — and they are not the same mechanism. Stated here so it does not surface
later as a defect.
