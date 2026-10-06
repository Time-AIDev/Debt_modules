# Money Engine — Spec Brief for the Volt Debt Prototype

> **v1.0 EXTRACT — baseline, ladder rank 7 (banner added 2026-08-30).** Read with `spec-deltas-v21-v24.md` and `spec-deltas-v25-rebuild.md`. **Deck v20.0 contradicts this brief in two places a builder must not miss:** §2.6 cash plans — Cash 2 and Cash 3 (with its 5% surcharge) are RETIRED; the only cash format is a deposit from THB 5,000 then the whole remaining balance, and the retired plans come OUT of Debt spec §5.2. Any 85%-of-NPV figure is stale — the acquisition and the NPL buyback are both 100% of customer NPV.

**Date:** 2026-08-26 · **Author:** Arina (arina.j@volt.co.th) · **Status:** extraction, not a decision

**Scope.** Every rule the money engine must implement, extracted from the LOCAL spec repo at
`/Users/parattakorn/volt-debt-collection/`. No Drive source was read. Where the five named sources
disagree with each other, this brief quotes both sides and marks the item OPEN rather than
reconciling it.

**Sources read (all local):**

| # | File | Lines |
|---|---|---|
| S1 | `/Users/parattakorn/volt-debt-collection/docs/00-prd/PRD.md` | 809 |
| S2 | `/Users/parattakorn/volt-debt-collection/docs/05-data/Data_Model.md` | 4781 |
| S3 | `/Users/parattakorn/volt-debt-collection/docs/06-workflow/Collection_Workflow_Alignment.md` | 693 |
| S4 | `/Users/parattakorn/volt-debt-collection/docs/07-testing/TEST-CASES-MNY.md` | 209 |
| S5 | `/Users/parattakorn/volt-debt-collection/docs/07-testing/TEST-CASES-COL.md` | 206 |

Corroborating files consulted to verify the traps (cited where used):
`docs/01-architecture/adr/ADR-006-debt-owns-schedule-append-only-money.md`,
`docs/04-security/Security_Requirements.md`, `docs/07-testing/TEST-CASES-CFG.md`,
`docs/07-testing/Traceability_Matrix.md`, `docs/01-architecture/eraser-diagrams.md`,
`docs/03-integrations/PEAK_Integration.md`.

---

## 0. Jargon and codes, for a first-time reader

| Term | What it means here |
|---|---|
| **REQ-MNY-nnn / REQ-COL-nnn** | Numbered requirements in PRD §5.2 (Money Engine) and §5.3 (Collections). PRD.md line = `204 + nnn` for MNY, `239 + nnn` for COL. |
| **TC-MNY-nnn / TC-COL-nnn** | Test cases. TEST-CASES-MNY.md line = `85 + nnn`; TEST-CASES-COL.md line = `81 + nnn`. |
| **Spec §x.y** | The upstream *VOLT Debt Collection Module Business Specification v3.1 rev B / v3.3 AS-BUILT*. **Not in this repo** — every §-citation below is a quotation-of-a-quotation via S1–S5. |
| **CF1** | Conflict 1: the penalty rate. 0.3 %/day vs 0.1 %/day. Unresolved. |
| **D-nn / A-nn / OD-nn** | Decision / Assumption / Open Decision from the Decisions Brief, restated in PRD §12, §13 and §10. |
| **DPD** | Days Past Due. |
| **PTP** | Promise To Pay. |
| **Flat rate** | Interest on the *full* original loan for the *full* term. Not declining-balance, not effective-interest. |
| **Satang** | 1/100 baht. Every money figure must agree to this unit across card, ledger, statement and PDF. |
| **Indicative** | A computed money figure that is displayed but is not yet contractually binding, because CF1 is open. |
| **LOCKED=false** | A configuration key an authorised role may still change; LOCKED CONTRACT/LAW keys may not. |

---

## 1. Verdict at a glance

| Area | Status | One-line reason |
|---|---|---|
| Flat-rate schedule formula, worked example, rounding | **SETTLED** | REQ-MNY-001/002/003; TC-MNY-001..003 are permanent acceptance tests. |
| Terms, down-payment tiers, first due date | **SETTLED** for financing; **OPEN** for cash | `financing_first_due_offset_days` 30 is seeded; `cash_first_due_offset_days` is **null** and a cash build must fail loudly. |
| DPD definition, freeze, restructure, terminal stop | **SETTLED** | REQ-MNY-015 + `money.fn_dpd` (S2 §7.1) agree. |
| Business-day handling of DPD/penalty | **SETTLED — there is none** | `day_count_basis CALENDAR`. Business days are used only for SLAs. |
| Arrears vs outstanding balance | **SETTLED in SQL**, **loose in prose** | Both are defined by the S2 §7.2 ledger query; the PRD never states them side by side. |
| Penalty formula, base, simple-not-compounding | **SETTLED** | REQ-MNY-017; `money.penalty` stores every input. |
| Penalty **rate** | **SUPERSEDED 2026-09-09 — ruling 87 sets 0.03 %/day** | Was 0.003 vs 0.001, same agreement clause, HIGH severity; the source conflict itself is unresolved history. See §5's banner, §10.1. |
| Penalty **grace** | **SUPERSEDED 2026-09-09 — ruling 88 sets no grace** | Was settled at 14 / start day 15 inside this repo: 11 independent statements, zero dissent. See §5's banner, §10.3. |
| The spec's own 150-baht worked example | **OPEN — known contradiction** | The repo deliberately does *not* implement it and says so. See §10.2. |
| Aging buckets 0 / 1–7 / 8–29 / 30+ | **SETTLED** | REQ-MNY-016; seeded reference data with a non-overlap constraint. |
| `band_set_code` | **DOES NOT EXIST** | Zero hits repo-wide. See §6.2. |
| Hold types and what each freezes | **SETTLED** | REQ-COL-039; `hold_types` is LOCKED policy. |
| Allocation: oldest instalment first | **SETTLED** | REQ-MNY-011. |
| Allocation: **component order within an instalment** | **OPEN (OD-02)** | Engine must **refuse**, not guess. See §8. |
| Dual-rate storage (REQ-MNY-019) | **OPEN — required but unimplementable as specified** | No column exists. See §10.4. |
| Early settlement | **OPEN (OD-03)** | Quote and accept both refuse while `early_settlement_method` is unset. |
| Append-only money, reversals, idempotency | **SETTLED** | REQ-MNY-010; DB triggers + absent PUT/DELETE. |

---

## 2. The instalment schedule model

### 2.1 The formula — SETTLED

> **REQ-MNY-001** — "For FINANCING contracts the system shall generate the repayment schedule with
> the flat-rate formula: Total Interest = Loan × Annual Rate × Years; Total Amount = Loan + Total
> Interest; Monthly Instalment = Total Amount ÷ Number of Instalments; interest is calculated on the
> full loan amount for the full term, not on a declining balance"
> — S1 `PRD.md:205`, Spec §6.1, MVP, note "A-07: Volt Debt owns the schedule"

`Years = term_months / 12`. The rate is a **percent per year**, stored as a percentage, not a
fraction (S2 `Data_Model.md:4500`: `annual_interest_rate_financing | 7.9 (percent per year, flat;
stored as a percentage, not a fraction)`). 7.9 is the seeded default and is **Owner-only** to edit.

### 2.2 The permanent acceptance test — SETTLED

> **REQ-MNY-002** — "The worked example shall be a permanent acceptance test: product price 300,000;
> 20 percent down 60,000 (Sales collects pre-installation); loan principal 240,000; total interest
> 240,000 × 7.9 percent × 5 = 94,800; total amount 334,800; monthly instalment 334,800 ÷ 60 =
> 5,580.00" — S1 `PRD.md:206`, Spec §6.2

The Traceability Matrix calls this out as structural, not incidental: *"REQ-MNY-002, the worked
example of Spec §6.2, is a permanent acceptance test rather than a unit test"*
(`Traceability_Matrix.md:153`).

**Fixtures to seed the prototype with** (S4 `TEST-CASES-MNY.md:41-49`):

| Fixture | Price | Down | Principal | Rate | Term | Total interest | Total amount | Instalment | Final instalment |
|---|---|---|---|---|---|---|---|---|---|
| FX-C1 | 300,000 | 20 % = 60,000 | 240,000 | 7.9 | 60 | 94,800.00 | 334,800.00 | 5,580.00 | 5,580.00 |
| FX-C2 | 300,000 | 30 % = 90,000 | 210,000 | 7.9 | 36 | 49,770.00 | 259,770.00 | 7,215.83 | **7,215.95** |
| FX-C3 | 300,000 | 0 % | 300,000 | 7.9 | 60 | 118,500.00 | 418,500.00 | 6,975.00 | — |
| FX-C4 | 300,000 | 10 % = 30,000 | 270,000 | 7.9 | 60 | 106,650.00 | 376,650.00 | 6,277.50 | — |

FX-C1 first due date is 2026-10-01 from mark-complete 2026-09-01.

### 2.3 Rounding and the balancing final instalment — SETTLED

> **REQ-MNY-003** — "Instalment amounts shall be rounded half-up to the satang and the final
> instalment shall be the balancing figure so that the sum of scheduled instalments equals
> total_amount exactly; the principal and interest split per instalment is constant (principal ÷
> term, interest ÷ term) with the final row absorbing rounding"
> — S1 `PRD.md:207`, note "A-07. Whan must be told the last instalment may differ (critic I6)"

Implementation constraints:

- `rounding_rule` column defaults to `'HALF_UP_SATANG'` (S2 `Data_Model.md:1531`).
- All money is `NUMERIC(14,2)`. ADR-006 §Decision 2 requires **Python `Decimal`**, not float:
  `installment_amount = round_half_up(total_amount / term, 2)`.
- Per-line split for FX-C1 (TC-MNY-002, `TEST-CASES-MNY.md:87`): lines 1–59 carry
  `principal_amount 4,000.00`, `interest_amount 1,580.00`, `fee_amount 0.00`; line 60 carries the
  balancing figures.
- FX-C2 is the non-dividing case: lines 1–35 at 7,215.83 give 252,554.05; line 36 is **7,215.95**;
  sum exactly 259,770.00 "with no residue" (TC-MNY-003, `TEST-CASES-MNY.md:88`).
- The schedule header must **state** that the final line differs.

`money.repayment_schedule` carries `installment_amount` *and* `final_installment_amount` as separate
NOT NULL columns (S2 `Data_Model.md:1527-1528`), so the balancing figure is stored, never recomputed.

Carried as an accepted open item, not a defect: *"The final instalment differs from the regular
instalment whenever the total does not divide exactly … Accepted — Accounting must be told before the
first customer statement is issued"* (S4 `TEST-CASES-MNY.md:208`, owner Whan with Accounting).

### 2.4 What the schedule stores — SETTLED

> **REQ-MNY-004** — "The schedule shall store, per contract: principal_amount (price minus down
> payment), annual_interest_rate (locked at signature, never changed retroactively), term_months,
> total_interest, total_amount, installment_amount, installments_paid (running count) and
> remaining_balance (computed live); per instalment: number, due date, scheduled principal, scheduled
> interest, scheduled fee, scheduled total, status" — S1 `PRD.md:208`, Spec §6.3

**Implementation gap to be aware of:** there is **no `remaining_balance` column** anywhere in S2.
It is realised as `money.daily_ledger.closing_balance` and as `installments_paid` on the same ledger
row (S2 `Data_Model.md:1663, 1671`). "Computed live" therefore means *read from the current
provisional ledger row*, not *stored on the schedule*. Do not add a mutable balance column — that is
exactly the behaviour Spec §12a criticises ("recomputes balances on demand and retains nothing", per
ADR-006 §Alternatives).

Per-instalment statuses are the closed enum `instalment_status`: `SCHEDULED, DUE, PARTIALLY_PAID,
PAID, DEFERRED, WAIVED, VOIDED` (S2 `Data_Model.md:203`).
Instalment categories: `REGULAR, PENALTY, ADJUSTMENT` (S2 `Data_Model.md:202`).

### 2.5 Terms and tiers — SETTLED

- `financing_term_options_months`: **24, 36, 48, 60, 72; default 60** (S2 `Data_Model.md:4509`).
- `down_payment_tiers_percent`: **0, 10, 20, 30** (S2 `Data_Model.md:4510`).

> **REQ-MNY-007** — "Financing down-payment tiers shall be handled as follows: 0 percent tier has
> instalment 1 collected before queueing for installation (reference only) and Volt Debt collects
> instalment 2 onward with instalment 2 due = mark complete date + financing_first_due_offset_days
> (default 30); 10, 20 and 30 percent tiers have all instalments collected by Volt Debt with
> instalment 1 due = mark complete date + 30 days" — S1 `PRD.md:211`, Spec §5.3

For the 0 % tier, TC-MNY-008 (`TEST-CASES-MNY.md:93`) requires line 1 stored with **status PAID** and
a pre-installation reference marker, read-only, and "**DPD never counts line 1**". TC-MNY-016
(`:101`) adds that instalment 1 "has no Debt due date and is excluded from DPD, penalty and the Today
List".

A tier Odoo sends that Debt does not configure (15 % or 25 %) is **rejected, not coerced**:
HTTP 422 `down_payment_tier_not_configured`, no schedule, contract stays `PRE_COLLECTION` with
`DPD null` (TC-MNY-011, `TEST-CASES-MNY.md:96`). This is OD-27, owner Debt Manager with Sales.

### 2.6 Cash plans — SETTLED in shape, OPEN in one parameter

> **REQ-MNY-006** — "Cash contracts shall be represented with payment_type = CASH_INSTALLMENT and
> their remaining instalments: Cash 1 (full payment) remaining balance after the 5,000 deposit, due
> per cash_first_due_offset_days; Cash 2 (50/50) instalment 2 = 50 percent due at the offset; Cash 3
> (50/25/25) instalment 2 = 25 percent at the offset and instalment 3 = 25 percent one month later,
> with the 5 percent surcharge already applied at the quote and never treated as interest"
> — S1 `PRD.md:210`, Spec §5.1, §5.2

- `basis = 'CASH_PLAN'`, `annual_interest_rate 0`, `total_interest 0.00`; the Cash 3 surcharge is
  **principal, never interest**, and "no interest line appears on any document" (TC-MNY-012).
- A cash line "participates in DPD and penalty exactly like a financing line" (TC-MNY-014).
- **OPEN:** `cash_first_due_offset_days` is seeded **null** — *"pending, not stated in Spec §22; a
  cash schedule build fails loudly rather than defaulting"* (S2 `Data_Model.md:4513`). OD-30 names
  30 as the *shipped default assumption* (S1 `PRD.md:704`), which the Data Model then declines to
  seed. **Prototype rule: fail loudly; parameterise the test.**

### 2.7 Due dates — SETTLED

- Instalment 1 (or 2 for the 0 % tier) due = `mark_complete_at` + offset for the payment type.
- Subsequent instalments: **monthly on the same day-of-month with end-of-month clamping**
  (ADR-006 §Decision 3; S2 `Data_Model.md:1530` — `due_day_of_month … clamped to month end`).
- **No business-day rolling.** Nothing in any source rolls a due date off a weekend or holiday.
- Stored ISO, displayed Buddhist-era on Thai printouts (TC-MNY-015).
- `invoice_payment_terms_days` (7) is the **invoice term**, a different thing from the due date and a
  different thing from grace. TC-MNY-017 (`TEST-CASES-MNY.md:102`) asserts the 7-day term "never
  overwrites due_date".

### 2.8 Lock and versioning — SETTLED

> **REQ-MNY-005** — "The schedule shall be locked at origination and never recomputed on read; a
> modification creates a new schedule version labelled by effective date and archives the old, both
> readable" — S1 `PRD.md:209`, Spec §10.4, §17.2

- `locked_at` set when `ACTIVE`; lines immutable after that; `checksum BYTEA` = sha256 over all lines
  (S2 `Data_Model.md:1539, 1542`).
- `schedule_status`: `DRAFT, CANDIDATE, ACTIVE, ARCHIVED, DISCARDED`.
- Unique partial index: **at most one ACTIVE schedule per contract** (`uq_schedule_active`).
- A restructure-created schedule may not be ACTIVE without an acknowledgement document:
  `CHECK (status <> 'ACTIVE' OR created_from_modification_id IS NULL OR acknowledgement_document_id IS NOT NULL)`.
- TC-MNY-006 asserts two reads six weeks apart, with a config edit in between, are **byte-identical**.

> **REQ-MNY-008** — "The interest rate applies to new contracts only; a configuration change to
> annual_interest_rate_financing never alters an existing contract's locked rate"
> — S1 `PRD.md:212`

Enforced twice: by `fn_contract_legal_entity_lock()` which "rejects any change to legal_entity,
principal_amount, annual_interest_rate, term_months after status leaves PENDING_ACTIVATION"
(S2 `Data_Model.md:136`), and by the effective-dated config resolver (TC-CFG-017).

### 2.9 Schedule vs Odoo — a tolerance disagreement worth resolving

Debt generates its own schedule and compares it to Odoo's `payment_schedule_json`. Two different
tolerances are stated:

- ADR-006 §Decision 1: *"a mismatch beyond **0.01 THB** per instalment raises an INT exception and
  holds the contract at PRE_COLLECTION"*.
- S3 `Collection_Workflow_Alignment.md:112` and S2 `Data_Model.md:4579`:
  `schedule_mismatch_tolerance_baht`, **default 1.00**, LOCKED POLICY, VERIFY.

**Minor OPEN.** Not in the five named sources' requirement text; flagged so the prototype picks the
config key (1.00) and does not hard-code 0.01.

---

## 3. DPD computation

### 3.1 The rule — SETTLED

> **REQ-MNY-015** — "DPD shall be recalculated daily at 02:00 as today minus the due date of the
> oldest unpaid instalment; DPD is null in PRE_COLLECTION and zero once collection has begun; a
> pending service issue freezes the clock; an approved restructure replaces the schedule and DPD
> recalculates against it; payment in full sets Resolved and closes the contract"
> — S1 `PRD.md:219`, Spec §12, §12.1

Reference semantics: `money.fn_dpd(p_contract_id, p_as_of)` (S2 `Data_Model.md:3906-3960`).

```
dpd = GREATEST(0, (as_of - oldest_due) - frozen_days - reset_days)
```

with

```
oldest_due = MIN(due_date) over money.instalment
             WHERE schedule.status = 'ACTIVE'
               AND category = 'REGULAR'
               AND due_date < as_of
               AND outstanding_amount > 0
```

### 3.2 What starts it

- **Event-driven at the moment the due date passes without sufficient allocation.** REQ-COL-011:
  "Entry into the collection queue shall be event-driven: the moment a due date passes without
  sufficient payment the queue record is created; the 02:30 batch is an idempotent reconciling safety
  net that may never create a duplicate" (S1 `PRD.md:250`). S3 `:471` times it precisely:
  *"event-driven at 00:00 on due date + 1 on the instalment, with the 02:00 batch as the idempotent
  safety net"*, producing DPD 1 and `evt.money.arrears_entered`.
- **"Sufficient payment" is defined**: TC-MNY-045 (`TEST-CASES-MNY.md:130`) — 5,000.00 paid against a
  5,580.00 line leaves DPD at 22 because 580.00 remains. S2 §7.1 rule 1: *"'sufficient payment' means
  outstanding_amount on the REGULAR line is zero after allocation"*.
- **Only a REGULAR line drives DPD.** TC-MNY-050 (`:135`) asserts DPD 0 / bucket Current while a
  billed PENALTY line of 133.92 and an ADJUSTMENT line remain unpaid — "the arrears block still shows
  the outstanding penalty separately so the officer is not misled".

### 3.3 What stops it

| Stopper | Effect | Source |
|---|---|---|
| `dpd_applies = false` on the status | DPD is **NULL**, not 0. False for `PENDING_ACTIVATION`, `PRE_COLLECTION` and every terminal status | S2 `Data_Model.md:389` |
| ACTIVE `PENALTY_SERVICE_HOLD` | clock frozen; `frozen_days` subtracted; ledger row carries `service_issue_frozen true` | REQ-MNY-023; TC-MNY-046 |
| Confirmed PEAK allocation clearing the oldest line | oldest unpaid moves forward; DPD recomputes | TC-MNY-045 |
| Payment in full | status `SETTLED`, dpd 0, bucket Resolved, queue closed by the same event path, "no further penalty accrues" | TC-MNY-049 |
| Terminal state entry | `intake.contract.dpd_stopped_at` set — *"Spec §24a.4a DPD stops on entry to a terminal state"* | S2 `Data_Model.md:1225` |
| Approved restructure | new ACTIVE schedule; **"the archived version is not consulted"**; DPD may legitimately drop to 0 | TC-MNY-048 |

**Critical non-stopper:** a restructure does **not** reset the NPL clock. TC-MNY-048: *"npl_first_flagged_at
is untouched and the NON_PERFORMING threshold continues to be evaluated through RESTRUCTURED and
MORATORIUM; a restructure must not reset that clock."* Enforced by trigger
`fn_npl_first_flagged_once()`.

**NULL ≠ 0.** REQ-MNY-013 states "dpd_on_date (null while PRE_COLLECTION; zero is a valid value
distinct from null)". TC-MNY-043 (`:128`) makes it a failing test: *"a report that renders NULL as 0
fails the test"*.

### 3.4 The three freeze-resolution options — SETTLED

> **REQ-MNY-023** — "A pending service issue shall freeze both DPD and penalty accrual from the flag
> date; on resolution the clock resumes from the resolution date with the reset option chosen
> (continue from frozen by Officer; partial reset by Officer with evidence; full reset by Supervisor
> or Manager); frozen days are marked service_issue_frozen in the ledger"
> — S1 `PRD.md:227`, Spec §16.1, §16.2, §12.1

`dpd_reset_option` enum: `CONTINUE_FROM_FROZEN, PARTIAL, FULL`.

| Option | Authority | Guard | Failure mode asserted |
|---|---|---|---|
| CONTINUE_FROM_FROZEN | Officer | none | resumes at the frozen DPD (10 in the fixture) |
| PARTIAL | Officer **with evidence** | `dpd_reset_evidence_upload_id` required | HTTP 422 `validation_failed` when absent |
| FULL | Supervisor or Manager | approval | HTTP 403 `approval_authority` for an Officer |

A FULL reset is recorded as `dpd_reset_days` **equal to the days accrued**, "so the arithmetic stays
uniform" (TC-MNY-047; S2 §7.1 rule 2). This matters: the engine has exactly one subtraction path.

TC-COL-067 adds the invariant that binds §3 to §5: *"the DPD and penalty arithmetic use the same
frozen day count so the two can never diverge"* (S5 `TEST-CASES-COL.md:148`).

### 3.5 Business-day handling — SETTLED, and the answer is "none"

**DPD and penalty are pure calendar-day arithmetic.** `day_count_basis` is seeded `CALENDAR`
(S2 `Data_Model.md:4506`) and hard-coded as the literal `'CALENDAR'` in the accrual INSERT
(S2 `Data_Model.md:4079`). Grace is "14 **calendar** days". The ledger is "one row per contract per
**calendar** day".

Business days exist in the model but never touch DPD or penalty:

- `ref.holiday` (S2 `Data_Model.md:505-515`) — Thai public and company holidays, `is_bank_holiday`,
  seeded per year by Accounting.
- `fn_business_days_between(d1, d2)` — IMMUTABLE, "Uses ref.holiday, Monday to Friday"
  (S2 `Data_Model.md:145`). Attached to **SLA columns only**.
- Consumers: `restructure_default_review_sla_days` 7 working days;
  `refund_execution_sla_business_days` 7; "Accounting corrects or resubmits within one business day".
- Separately, `contact_hours_weekday` 08:00–20:00 vs `contact_hours_holiday` 08:00–18:00 (both LOCKED
  LAW) make holidays matter to the **contact guard**, not to the money engine.

**"Today" is the Asia/Bangkok calendar day.** NFR-020 (S1 `PRD.md:499`): "All timestamps stored UTC
with Asia/Bangkok as the business timezone; 'today' for the contact lock, the Today List and DPD is
the Bangkok calendar day … Unit tests around midnight and year boundaries."

### 3.6 Job times — one deviation to carry

| Job | Spec §22.2 | Seeded in S2 | Note |
|---|---|---|---|
| DPD recalculation | 02:00 | **02:05** | *"shifted to follow odoo-reconcile"* (`Data_Model.md:4526`) |
| PTP autocheck | 02:00 | **02:15** | *"shifted to preserve the after-DPD ordering"* |
| Today List | 02:30 | 02:30 | must run **after** DPD completes (REQ-COL-007) |
| Penalty accrual | 03:00 | 03:00 | |
| Daily ledger close | not named in spec | **23:30** | fixed by the DECISIONS topology, S4 §2 |

The requirement text (REQ-MNY-015) still says 02:00. Read the config key, do not hard-code either.

---

## 4. Arrears vs outstanding balance

Neither term is defined side by side in prose anywhere. Both are defined **precisely and only** by
the daily-ledger query, S2 `Data_Model.md:3979-4058`. Take these as the definitions.

### 4.1 Outstanding balance — `closing_balance`

```
closing_balance = SUM(instalment.outstanding_amount)
                  WHERE schedule.status = 'ACTIVE'
                    AND instalment.category = 'REGULAR'
```

All REGULAR lines on the ACTIVE schedule, **due or not yet due**. Its companions on the same row:
`principal_outstanding = SUM(GREATEST(principal_amount - paid_principal, 0))` and
`interest_outstanding` likewise. `opening_balance` = previous day's `closing_balance`, falling back
to `contract.total_amount` on day one. **Invariant:** yesterday's `closing_balance` equals today's
`opening_balance` (TC-MNY-039).

`outstanding_amount` is itself a **generated stored column**:
`total_amount - paid_principal - paid_interest - paid_fee`, where
`total_amount = principal_amount + interest_amount + fee_amount` is also generated
(S2 `Data_Model.md:1564, 1568`). Neither can drift.

### 4.2 Arrears — `cumulative_arrears`

```
cumulative_arrears = SUM(instalment.outstanding_amount)
                     WHERE schedule.status = 'ACTIVE'
                       AND instalment.due_date < ledger_date
                       AND instalment.outstanding_amount > 0
```

Only the **past-due** slice. Decomposed on the same row into `arrears_principal`, `arrears_interest`,
`arrears_fee` (each `SUM(GREATEST(scheduled - paid, 0))`), plus `overdue_instalment_count`.

**⚠ One asymmetry an implementer must decide deliberately.** The `bal` (outstanding) CTE filters
`AND i.category = 'REGULAR'`. The `arr` (arrears) CTE **does not**. As written, a billed PENALTY line
or an ADJUSTMENT line past due **is counted in `cumulative_arrears`** but is **not** counted in
`closing_balance`, and does **not** drive DPD (TC-MNY-050). That is defensible — an officer collecting
"arrears payable today" wants the billed penalty in the figure — but it is not stated anywhere in
prose, and it means `cumulative_arrears` is not a subset of `closing_balance`. Mirror the SQL exactly
and write a test that pins the intent.

### 4.3 Full payoff

```
full_payoff_amount = closing_balance + penalty_accrued_unbilled
```

(S2 `Data_Model.md:4004`.) The column note adds: *"uses early_settlement_method when set, else total
outstanding"* (`:1679`) — i.e. this simple sum is the **fallback**, live only because
`early_settlement_method` is unset (OD-03).

> **REQ-MNY-027** — "Full payoff (remaining principal plus accrued interest to date plus accrued
> penalty plus fees, less any rebate shown per REQ-MNY-024) shall be computed server-side from the
> ledger and returned by the single summary endpoint; the interface performs no arithmetic"
> — S1 `PRD.md:231`

### 4.4 The arrears block — a **fixed field order** the tests enforce

> **REQ-COL-027** — "The arrears block shall be ordered: total arrears payable today; days past due
> and aging bucket; accrued penalty with the composition of the arrears; next due date; next
> instalment amount; full payoff; all figures computed server-side and returned by one endpoint
> sourced from the daily ledger, so header and drill-down agree to the satang"
> — S1 `PRD.md:266`, Spec §10.3, §12a

TC-COL-052 (`TEST-CASES-COL.md:133`): *"a response that leads with the next instalment **fails the
test**"*. S2 §7.8 (`:4251`) restates the same order and adds: *"No arithmetic is performed in the API
layer or the interface."*

The endpoint reads **yesterday's closed row plus today's provisional row**.

Worked expectation, FX-ARR-1 on 2026-10-23 (TC-MNY-042, `TEST-CASES-MNY.md:127`): total arrears
5,580.00; DPD 22, bucket Mid Overdue 8–29; accrued penalty 133.92 with composition principal 4,000.00
/ interest 1,580.00 / fee 0.00; next due 2026-11-01; next instalment 5,580.00; full payoff; plus
`basis_ledger_date`.

Multi-contract aggregation is a COL concern, not a re-computation: FX-CUS-A's two contracts give
aggregate overdue **9,780.00** (5,580.00 + 4,200.00) and oldest DPD **22** (TC-COL-003, TC-COL-017,
TC-COL-053). Penalty accrued / billed / paid / waived are shown as **four separate figures and never
netted into one** (TC-COL-053).

---

## 5. Penalty

> **Superseded 2026-09-09 by rulings 87 and 88.** The late-fee rate is **0.03 %/day**
> and there is **no grace period** — penalty runs from the due date. Passages below that
> quote source documents (agreement VL0010399 §13.1, PAY v1.2, the sheet's Late Fee
> Logic tab) keep their original figures: they are evidence, not our rate.

### 5.1 The formula — SETTLED

> **REQ-MNY-017** — "Penalty shall be computed as overdue_installment_amount ×
> late_payment_daily_rate × days_overdue_after_grace, simple and not compounding, where
> overdue_installment_amount is the sum of unpaid instalments past due excluding penalty itself, and
> days_overdue_after_grace = days past due minus the grace period; accrual runs daily at 03:00 and
> continues until payment in full"
> — S1 `PRD.md:221`, Spec §15.1, note "Calculation shown as indicative until CF1 closes (A-03)"

### 5.2 The base it accrues on

Per instalment, not per contract. From the accrual INSERT (S2 `Data_Model.md:4073`):

```
overdue_base_amount = i.outstanding_amount - GREATEST(i.fee_amount - i.paid_fee, 0)
```

i.e. the unpaid principal + interest of that REGULAR line, with the fee portion stripped out so that
**penalty never accrues on penalty**. The column note is explicit: "unpaid amount of the instalment
past due, excluding penalty itself (Spec §15.1)" (S2 `Data_Model.md:1697`). TC-MNY-053 asserts
`overdue_base_amount 5,580.00 excludes penalty itself`.

Accrual scope: `i.category = 'REGULAR' AND i.due_date < :accrual_date AND i.outstanding_amount > 0`,
on the ACTIVE schedule only, and only where the contract status has `dpd_applies`.

Grain: **one row per (instalment, accrual date)**, `UNIQUE (instalment_id, accrual_date)`,
`ON CONFLICT DO NOTHING` — the job is idempotent by construction.

Per-day and cumulative are both stored:

```
amount            = ROUND(base * rate, 2)                        -- 0 if frozen or inside grace
cumulative_amount = ROUND(base * rate * chargeable_days, 2)
chargeable_days   = GREATEST(days_past_due - grace_days, 0)
days_past_due     = (accrual_date - due_date) - frozen_days - reset_days
```

Simple, not compounding: TC-MNY-055 (`TEST-CASES-MNY.md:140`) runs 30 consecutive days and asserts
`5,580.00 × 0.003 × 30 = 502.20`, each daily row 16.74, and "**no day computes on a base that
includes prior penalty**".

### 5.3 Grace — superseded 2026-09-09 by ruling 88 (no grace); was SETTLED at 14 inside this repo

> **REQ-MNY-018** — "Grace shall be 14 calendar days from the due date with
> interest_rate_during_grace = 0; penalty starts on day 15 (penalty_start_day 15); the acceptance
> examples are: instalment 5,580 paid 22 days late gives 8 chargeable days and 5,580 × 0.003 × 8 =
> 133.92; two instalments 11,160 at 22 days late give 11,160 × 0.003 × 8 = 267.84; an instalment paid
> 10 days late attracts no penalty"
> — S1 `PRD.md:222`, Spec §15.2, §15.3
> Note column, verbatim: *"Spec §15.2 first example (150) contradicts §15.3 and is not implemented;
> the engine follows §15.1"*

Boundary test, TC-MNY-054 (`TEST-CASES-MNY.md:139`): 2026-10-15 is **day 14** → `chargeable_days 0`,
`amount 0.00`, **and a row is still written "so the zero is explainable"**. 2026-10-16 is **day 15** →
`chargeable_days 1`, `amount 16.74`. Nothing else accrues inside grace because
`interest_rate_during_grace` is 0.

See §10.3 for the 0 / 11 / 14 claim.

### 5.4 Every stated worked example

| # | Input | Stated result | Status | Source |
|---|---|---|---|---|
| E1 | instalment **5,000**, paid **10 days** late, `5,000 × 0.003 × 10` | **150** | ❌ **NOT IMPLEMENTED — known contradiction.** Engine returns **0.00**. See §10.2 | Spec §15.2 ex.1, via REQ-MNY-018 note and TC-MNY-057 |
| E2 | instalment **5,580**, **22 days** late, grace 14 → 8 chargeable | **133.92** | ✅ implemented; per-day row 16.74 | REQ-MNY-018; TC-MNY-053 |
| E3 | **two** instalments **11,160**, **22 days** late → 8 chargeable | **267.84** | ⚠️ implemented **only when both lines share days past due** — see below | REQ-MNY-018; TC-MNY-056 |
| E4 | 30 consecutive days on 5,580 | **502.20** | ✅ implemented; proves non-compounding | TC-MNY-055 |
| E5 | **100,000** outstanding, **30 days past grace**, 0.003 vs 0.001 | **4,800 vs 1,600** | ✅ the CF1 impact figure | REQ-MNY-019; TC-MNY-058 |
| E6 | FX-ARR-2: two instalments at 2026-11-23 | **652.86 + 133.92 = 786.78** | ✅ this is what the engine actually produces | FX-ARR-2; TC-MNY-056 |

**E3 is a third, quieter contradiction.** TC-MNY-056 (`TEST-CASES-MNY.md:141`) spells it out: the
267.84 figure *"reproduces only when both instalments carry the same days past due, because the engine
accrues **per instalment**: at 2026-11-23 FX-ARR-2 gives 652.86 on instalment 1 and 133.92 on
instalment 2, total 786.78; the reconciliation between the aggregate presentation and the per-line
engine is carried as an open item"* — owner **Debt Manager with Accounting**
(`TEST-CASES-MNY.md:201`). REQ-MNY-018 presents 267.84 as an acceptance example without that caveat.
**Prototype: accrue per instalment. Reproduce 267.84 only in the unit harness.**

### 5.5 The rate — superseded 2026-09-09 by ruling 87; was **OPEN (CF1)**

Covered in full at §10.1. As extracted 2026-08-26, the engine read `late_payment_daily_rate`;
default **0.003**; `is_pending_rule true`; `locked false`; every screen and document labelled
*"indicative — CF1 pending"*. Ruling 87 supersedes the default with **0.0003** (0.03 %/day) —
see §5's banner.

### 5.6 Settings resolution — SETTLED

> **REQ-MNY-020** — "Penalty settings shall resolve through the standard order of REQ-CFG-005
> (product, product group, legal entity, system default) for late_payment_grace_days,
> late_payment_daily_rate, interest_rate_during_grace, day_count_basis (CALENDAR), accrual_method,
> rate_type (FIXED; VARIABLE rejected with an explicit error) and penalty_start_day; the resolved
> value and the level that answered are both returned by the API"
> — S1 `PRD.md:224`
> Note: *"Spec §15.5 states three levels; the legal-entity level is added per Spec §19.2 per-entity
> adapter resolution and Spec §5.4."*

Single resolver: `config.fn_resolve_numeric(key, product_id, product_group_id, legal_entity, as_of)`
returning `(rate, level, value_id)` — *"the single resolver every engine uses"*
(S2 `Data_Model.md:4098`). Both the value **and** `rate_resolution_level` **and**
`rate_config_value_id` are snapshotted onto every `money.penalty` row.

`rate_type = VARIABLE` → HTTP 422 `rate_type_variable_not_supported`, **no schedule, no partial
lines**, alert to Finance (TC-MNY-005).

### 5.7 Lifecycle — superseded 2026-09-09 by ruling 87 (billing is ON); was SETTLED, with billing gated OFF

> **REQ-MNY-021** — "Penalty shall have the lifecycle accrued and unbilled, billed, paid or waived;
> the four figures are stored and displayed separately; billing is a request to ACC (REQ-ACC-006) on
> the day-15 event and is feature-flagged OFF until CF1 closes" — S1 `PRD.md:225`

Ruling 87 turns billing on: `penalty_invoicing_enabled` now defaults **true**, so a penalty draft is
raised to PEAK on the day-15 event rather than withheld — see §5's banner. The gate itself is kept,
not removed: the flag stays Owner-tunable, so an Owner may still switch billing off, and the refusal
below is what fires when they do.

`penalty_status`: `ACCRUED, BILLED, PAID, WAIVED, VOIDED`. Four cumulative ledger columns:
`penalty_accrued_unbilled`, `penalty_billed`, `penalty_paid`, `penalty_waived`.

`POST /v1/penalties/{uid}:bill` while `penalty_invoicing_enabled = false` → **HTTP 422
`feature_disabled`: "Penalty invoicing is disabled by configuration (`penalty_invoicing_enabled`)";
no PEAK call; no idempotency key consumed** (TC-MNY-061; superseded 2026-09-09, ruling 87 — was:
naming CF1 and its owner). The no-key-consumed clause matters because every PEAK create is billable.

**Accrued unbilled penalty is not an allocable line.** TC-MNY-022 (`TEST-CASES-MNY.md:107`): a payment
of exactly 133.92 allocates to the oldest REGULAR instalment, **not** to the penalty; the penalty
stays ACCRUED. Only a **billed** PENALTY line participates in allocation, as bucket `FEE`, aging
`OVERDUE` (TC-MNY-023).

### 5.8 Waivers — SETTLED except one limit

> **REQ-MNY-022** — "A penalty waiver shall be a modification of type PENALTY_WAIVER (REQ-MOD-001),
> never a direct edit, with approver per Spec §15.7: first occurrence of 7 days or less by the
> Supervisor scoped to a rolling 12 months per customer; beyond 7 days or a repeat customer by the
> Debt Manager; above the policy limit by the Credit & Risk Manager then COO or CEO; a negotiated
> penalty may be rejected by the Supervisor" — S1 `PRD.md:226`

- `supervisor_penalty_waive_max_dpd = 7`; **7 passes, 8 does not** (TC-MNY-063).
- Rolling window is **per customer, not per contract**, and inclusive at exactly 12 months: a prior
  waiver dated 2025-09-03 is *still inside* the window on 2026-09-03 and outside on 2026-09-04
  (TC-MNY-064). Index `idx_penalty_waiver_customer ON (customer_id, created_at DESC)` exists for it.
- **OPEN (OD-29):** `penalty_waiver_policy_limit` is seeded **null**. TC-MNY-065: where it has no
  value the request is refused with `configuration_missing` **"rather than defaulting to allow"**.
  PRD OD-29 names 5,000 as the shipped default; the Data Model declines to seed it. **Refuse.**
- The waived figure appears in the *waived* column and **never as a reduction of the accrued figure**
  (TC-MNY-062).

---

## 6. Aging buckets and `band_set_code`

### 6.1 Buckets — SETTLED

> **REQ-MNY-016** — "Aging buckets shall be: Current DPD 0 (green); Early Overdue 1–7 (yellow, Today
> List priority 6); Mid Overdue 8–29 (orange, priority 5); Risk Review 30 or more (red, NPL
> eligibility starts); NPL Confirmed (black, Manager-flagged); Resolved (green); Closed (grey,
> write-off or cancellation)" — S1 `PRD.md:220`, Spec §12.2
> Note, verbatim: *"Boundaries are seeded reference data in ref.aging_bucket (Data_Model §6.1.2), not
> a Spec §22 configuration key; Spec §12.2 states them and Spec §22 does not mark them configurable,
> so **a change is a migration, not a panel edit**."*

`ref.aging_bucket` (S2 `Data_Model.md:361-378`):

| code | min_dpd | max_dpd | colour | today_list_priority |
|---|---|---|---|---|
| CURRENT | 0 | 0 | green | — |
| EARLY_OVERDUE | 1 | 7 | yellow | 6 |
| MID_OVERDUE | 8 | 29 | orange | 5 |
| RISK_REVIEW | 30 | NULL (open) | red | — |
| NPL_CONFIRMED | NULL | NULL | black | — |
| RESOLVED | NULL | NULL | green | — |
| CLOSED | NULL | NULL | grey | — |

Two constraints worth porting verbatim:

- `EXCLUDE USING gist (int4range(min_dpd, max_dpd, '[]') WITH &&) WHERE (min_dpd IS NOT NULL)` —
  ranges **cannot overlap**, at the database level.
- `CHECK (min_dpd IS NULL OR max_dpd IS NULL OR min_dpd <= max_dpd)`.

**Status wins over the number.** `money.fn_aging_bucket(status, dpd)` (S2 `Data_Model.md:3962`) reads
`ref.contract_status.aging_bucket_override` **first** and only falls through to the numeric band:
`NON_PERFORMING → NPL_CONFIRMED`, `SETTLED` and `RESTRUCTURED → RESOLVED`, `WRITTEN_OFF` and
`CANCELLED → CLOSED`. TC-MNY-052 asserts NON_PERFORMING at DPD 45 → NPL Confirmed, WRITTEN_OFF at DPD
120 → Closed, and PRE_COLLECTION with DPD null → **null bucket, not Current**.

Boundary test TC-MNY-051 asserts DPD 0, 1, 7, 8, 29, 30, 31 and requires that "no DPD value falls
between two buckets or into none".

**Buckets are not lifecycle statuses.** S3 `Collection_Workflow_Alignment.md:323` design rule 3:
they are "a derived attribute of PAST_DUE (and of RESTRUCTURED or MORATORIUM when arrears exist)".
The same rule adds **reporting-only** bands the spec does not define: *"the app additionally reports
30–59, 60–89 and 90+ for the portfolio-at-risk indicators 11–13 (Spec §20.2) … as reporting bands
only"*, plus *"Day 15 is the penalty start inside Mid Overdue"*.

**NPL is never automatic.** S3 design rule 6: "The system raises the review at DPD 30+ … a human
flags." `npl_dpd_threshold_days` is seeded **null** (OD-04).

### 6.2 `band_set_code` — **DOES NOT EXIST IN THE SPEC REPO**

A recursive grep over the entire repo (`/Users/parattakorn/volt-debt-collection`, all file types)
returns **zero hits** for `band_set_code` or `band_set`. It is not a spec term. Do not introduce it
as though it were.

The three real, and distinct, "band" concepts:

1. **Aging bucket** — `ref.aging_bucket.code`. **Unversioned**; a change is a migration
   (REQ-MNY-016 note).
2. **Collections risk band** — `collections.risk_score.band ∈ {LOW, MEDIUM, HIGH}`, cut by
   `collection_score_cutoff` (seeded "LOW below 30, MEDIUM 30 to 59, HIGH 60 and above (VERIFY)").
   Denormalised onto `today_list_item.risk_band`. **OPEN** — cut-offs are Manager-set placeholders
   (S2 §13.20).
3. **`config.scoring_weight_set`** (S2 `Data_Model.md:974-988`) — the *only* versioned band
   container. Columns `version` (UNIQUE), `weights` JSONB, `band_cutoffs` JSONB, `effective_from`.
   REQ-COL-043: *"weight changes apply forward only and the weight-set version is persisted with each
   score"*.

If a caller means "the versioned identifier of the band definition in force", the spec's answer is
**`config.scoring_weight_set.version`**, and it applies to the **risk score only** — never to aging.

---

## 7. Holds — what each one freezes

### 7.1 The three types — SETTLED, LOCKED policy

> **REQ-COL-039** — "Three hold types shall exist and no single stop button: CONTACT_HOLD stops
> outbound contact on every channel through one server-side guard; LEGAL_HOLD records a legal
> position and does not stop contact; PENALTY_SERVICE_HOLD suspends penalty accrual and DPD counting
> while contact may continue; behaviours by case: deceased (contact hold, Legal designates new
> contact, estate contactable), litigation (legal hold), government complaint (disputed activity
> pauses until cleared), system fault (penalty and enforcement pause until O&M confirms), restructure
> negotiation (contact hold to appointment date with mandatory expiry)"
> — S1 `PRD.md:278`, Spec §16.5, note "hold_types LOCKED policy"

| Hold | Clock (DPD) | Penalty accrual | Outbound contact | Daily-lock denominator | KPI / NPL |
|---|---|---|---|---|---|
| **CONTACT_HOLD** | runs | runs | **stopped, all channels** | **not counted; slot preserved** | unaffected |
| **LEGAL_HOLD** | runs | runs | **continues** | counted normally | unaffected |
| **PENALTY_SERVICE_HOLD** | **frozen** | **frozen** | continues | counted normally | `excluded_from_kpi = true` |

TC-COL-063 (`TEST-CASES-COL.md:144`) asserts all three in one test and adds the negative:
*"no endpoint, flag or field stops everything at once"*.

**The collection denominator detail.** REQ-COL-020: "A customer under a CONTACT_HOLD shall not be
counted against the lock and shall receive nothing on any channel; the hold guard and the lock guard
are one server-side check and never double-count" (S1 `PRD.md:259`). TC-COL-040 makes it testable: the
call returns **HTTP 409 `contact_on_hold`, distinct from `contact_locked`**; no lock row is created or
consumed; the reminder is written `SUPPRESSED` with `suppression_cause HOLD`; and *"when the hold
expires the customer's daily slot is intact and unused, so the hold has not silently spent it"*.

`suppression_cause` enum: `PAID, HOLD, NEW_AGREEMENT, AGENCY, OPT_OUT, DEDUP`.

### 7.2 Mandatory fields — SETTLED

> **REQ-COL-040** — "Every hold shall require a reason code from the dictionary, an approver, a start
> date and an expiry; a hold without reason or expiry cannot be created; on expiry the case returns to
> normal automatically and the owning officer is notified; early release requires a configured
> approver and is audited; setting a legal status that maps to a hold creates the hold automatically"
> — S1 `PRD.md:279`, Spec §16.6

Enforced by CHECK constraints, not application code (S2 `Data_Model.md:137`):
`reason_code NOT NULL`, `approver_user_id NOT NULL`, `expiry_date NOT NULL`,
`CHECK (expiry_date > start_date)`, and
`CHECK ((released_at IS NULL) = (release_reason IS NULL))`.

`hold_status`: `ACTIVE, EXPIRED, RELEASED` — **never deleted**, "so a freeze can no longer be applied
and forgotten" (TC-COL-070).

Auto-creation from legal status: DECEASED → CONTACT_HOLD (estate still contactable via
`stakeholder_type ESTATE`); litigation → LEGAL_HOLD with contact continuing (TC-COL-065).

### 7.3 How the freeze reaches the money engine

`money.fn_dpd` computes `frozen_days` by summing hold windows, clipped to the DPD window
(S2 `Data_Model.md:3930-3944`):

```
frozen_days = SUM(GREATEST(0,
    LEAST(COALESCE(h.ticket_resolved_at::date, h.expiry_date, p_as_of), p_as_of)
    - GREATEST(h.start_date, o.oldest_due)))
WHERE h.hold_type = 'PENALTY_SERVICE_HOLD' AND h.start_date <= p_as_of
```

Note the resolution precedence: `ticket_resolved_at`, else `expiry_date`, else `as_of`.

The accrual query calls the **same function** and writes `is_frozen_day` with `amount 0.00` — a row
is still written *"so the day is explainable rather than missing"* (TC-MNY-060). This is the
mechanism that makes TC-COL-067's "can never diverge" true.

**Freeze is unbounded.** OD-15 / REQ-COL-042: CF3 is unresolved (OPS T1 2h/T2 1d/T3 3d vs Debt
Emergency 4h/High 8h/Normal 24h), so `sla_tier` is **informational only** and TC-COL-069 asserts the
hold *"stays ACTIVE and DPD stays frozen rather than resuming automatically"*, with
`escalated_to_manager_at` set and a Manager task raised.

**Abuse detection records but does not act.** `hold_audit_sample.retroactive_dpd_applied` is
*"open D6 — recorded, not enforced"* (S2 `Data_Model.md:2267`). Default: **no retroactive DPD**
(OD-19).

---

## 8. Payment allocation — **the component order is OPEN**

### 8.1 What is settled

> **REQ-MNY-011** — "One central allocation rule shall settle the oldest due instalment first and
> then apply the configured component order within that instalment (allocation_component_order,
> default principal, interest, fee, **LOCKED=false, VERIFY**); the identical allocation detail is
> served to the ledger, the customer screen and any invoice mirror, three presentations of one
> calculation" — S1 `PRD.md:215`, Spec §6.6
> Note, verbatim: *"A-03. **Order is pending Accounting with Legal from agreement VL0010399**;
> illustration: two instalments of 5,580 (11,160) plus 268 penalty and a payment of 6,000 produce
> different escalation answers by order"*

**Settled:** oldest-due-instalment-first. Seeded as
`allocation_order = OLDEST_INSTALMENT_FIRST then component order PENDING` (S2 `Data_Model.md:4563`).

> **REQ-MNY-009** — "Every amount received shall land in exactly one bucket, principal, interest or
> fee, each split into a current and an overdue portion, giving six separately reportable figures; no
> amount may be untyped" — S1 `PRD.md:213`, Spec §6.5

`allocation_bucket ∈ {PRINCIPAL, INTEREST, FEE}` × `allocation_aging ∈ {CURRENT, OVERDUE}`.
`aging = OVERDUE when instalment.due_date < transaction.effective_date` (S2 `Data_Model.md:1638`).

Worked expectation, TC-MNY-019 (`TEST-CASES-MNY.md:104`) — FX-ARR-1, confirmed PEAK receipt 6,000.00:

| | principal | interest | fee |
|---|---|---|---|
| overdue | 4,000.00 | 1,580.00 | 0.00 |
| current | 420.00 | 0.00 | 0.00 |

Total 6,000.00; instalment 1 → PAID, instalment 2 → PARTIALLY_PAID; `is_allocated true`.

### 8.2 What is OPEN — **OD-02, rank HIGH**

> **OD-02** — "Allocation component order within an instalment for a short payment" · Rank **HIGH** ·
> Owner **Accounting with Legal** · Default shipped: "principal, interest, fee after
> oldest-instalment-first" · Gates REQ-MNY-011 · Source Spec §6.6, §30.1
> — S1 `PRD.md:677`

**The engine must refuse, not guess.** TC-MNY-026 (`TEST-CASES-MNY.md:111`), with
`allocation_component_order` unset:

- Manual path `POST /v1/contracts/{uid}/transactions` → **HTTP 422 `allocation_rule_pending`, writes
  nothing**.
- PEAK webhook path → **records the transaction with `is_allocated false` and raises an ACC
  exception, "so the payment is never lost"**.
- Both audited; both name the pending decision **and its owner**.

That asymmetry is itself flagged as an engineering choice, not a spec rule:
*"The webhook path recording an unallocated transaction where the manual endpoint returns 422 is an
engineering rule, not a spec rule — VERIFY, owner Arina with Accounting"*
(`TEST-CASES-MNY.md:207`).

**Both orders must be reachable by configuration, with no code branch.** TC-MNY-020 vs TC-MNY-021:
under the default order the 6,000.00 clears instalment 1 and puts 420.00 on instalment 2; under
`FEE,PRINCIPAL,INTEREST` the 267.84 penalty settles first, then 5,732.16 flows to the instalments.
TC-MNY-021 asserts *"no code branch changed"* and that
**"historical transactions keep the version they were allocated under and are never re-allocated"**.

Every allocation row carries `rule_version` and `rule_step` — "position in the order applied, for the
explanation screen" (S2 `Data_Model.md:1642`). Every transaction carries
`allocation_rule_version`.

### 8.3 Allocation edge cases

| Case | Required behaviour | Source |
|---|---|---|
| Payment lands on a fully settled contract | `is_allocated false` + unapplied-receipt exception for Accounting; **no negative allocation row; nothing silently absorbed into principal** | TC-MNY-024 |
| Payment on a terminal contract (SETTLED/WRITTEN_OFF/CANCELLED/REPOSSESSED) | recorded, allocation refused, exception names the terminal status, no DPD movement | REQ-MNY-030; TC-MNY-025 |
| Billed PENALTY line dated later than the REGULAR line it belongs to | oldest-first still settles the instalment first: 5,580.00 to instalment 1, then 20.00 to the penalty as bucket FEE / aging OVERDUE | TC-MNY-023 |
| Officer tries to record a payment | **HTTP 403** — recording is an Accounting action; the officer's path is a payment claim | TC-MNY-070 |

### 8.4 What is allowed to move DPD — SETTLED (A-08)

> **REQ-MNY-025** — "A payment confirmed by PEAK (REQ-ACC-003) shall be allocated by REQ-MNY-011 with
> effective_date = value date, update installments_paid and remaining_balance, re-derive DPD on the
> next run or immediately on request, and, where it clears arrears, close the collection queue record
> through the same event path that opened it" — S1 `PRD.md:229`
> Note: *"A-08: **PEAK confirmation is the only thing that resets DPD**"*

> **REQ-MNY-026** — "A claimed payment created from an uploaded slip (REQ-DOC-010) shall be shown as
> PENDING on the card and the Today List, never allocated and never used to reset DPD until Accounting
> confirms it against a PEAK receipt" — S1 `PRD.md:230`

TC-MNY-028: claim → HTTP 201 `PENDING`, **no `money.transaction`, no allocation, DPD stays 22**;
`expires_at = submitted_at + claim_expiry_days (5)`. `claim_status`:
`PENDING, CONFIRMED, REJECTED, EXPIRED`.

### 8.5 The two dates — SETTLED, with a pending sub-rule

> **REQ-MNY-012** — "Every transaction shall carry record_date (entered) and effective_date (takes
> effect) as separate columns; the accounting period is derived from effective_date with
> legal_entity; a transaction whose effective_date falls in a closed period is held with status
> PENDING and surfaced on the exceptions screen until Accounting's closed-period rule is configured"
> — S1 `PRD.md:216`, Spec §6.7

`accounting_period CHAR(7)` is **GENERATED ALWAYS AS `to_char(effective_date,'YYYY-MM')` STORED**.
TC-MNY-034: *"no rule silently sets one from the other"*; the statement orders by `effective_date`,
the audit by `record_date`.

**OPEN (OD-11):** `closed_period_rule` is seeded null. Behaviour: store the row, `posting_status
PENDING`, `closed_period_override false`, surface on the Daily Exception Dashboard, post nothing,
return problem code `closed_period`, **name the decision owner in the exception** (TC-MNY-036).
Override requires a reason: without one, HTTP 422 `reason_required` (TC-MNY-037).

---

## 9. Invariants a test can assert

Ordered roughly by how cheaply a prototype can enforce them.

### 9.1 Append-only money

> **REQ-MNY-010** — "Money rows shall never be updated or deleted; a correction posts a reversal, a
> mirror entry cancelling the original, linked to it, visible behind a show-inactive filter; reports
> read net amounts" — S1 `PRD.md:214`
> Note: *"Enforced by database trigger **and** by the absence of PUT and DELETE endpoints on money
> resources"*

- Column set **S2**: `fn_reject_write()` BEFORE UPDATE OR DELETE raises `append_only`, with a single
  escape — `app.maintenance = 'retention'` on a retention DELETE (S2 `Data_Model.md:131`).
- TC-MNY-033: PATCH and DELETE on `/v1/transactions/{uid}` and `/v1/contracts/{uid}/schedule` →
  **HTTP 405 `money_immutable` on every verb and path**, *"and the database trigger also refuses the
  UPDATE if it is attempted directly, so an SQL client cannot bypass the API"*. Both refusals write
  an audit row.
- Reversal pairing: mirror carries `reverses_transaction_id`, original gains
  `reversed_by_transaction_id`, `CHECK (reverses_transaction_id <> transaction_id)`; the original row
  is otherwise **unchanged in every column**; net reporting shows 0.00 for the pair (TC-MNY-030).
- Reverse twice → **HTTP 409 `reversal_target_already_reversed`** (TC-MNY-032).
- `show_inactive=false` hides **both** rows and excludes both from the balance; `=true` shows both
  with the link; allocation rows carry negative amounts equal and opposite; instalment paid roll-ups
  return to pre-payment values (TC-MNY-031). Note `money.allocation.amount` has
  `CHECK (amount <> 0)` — zero is illegal, negative is legal.
- The DB role `volt_debt_app` has **no DELETE grant** on any money table (S2 `Data_Model.md:121`).

### 9.2 Idempotency

- `money.transaction.idempotency_key VARCHAR(80) NOT NULL UNIQUE`, *"deterministic: txn_type,
  contract_id, source reference, amount, effective_date hashed; **stored before any PEAK call**"*
  (S2 `Data_Model.md:1603`).
- `money.penalty`: `UNIQUE (instalment_id, accrual_date)` + `ON CONFLICT DO NOTHING`.
- `money.daily_ledger`: `PK (contract_id, ledger_date)` + `ON CONFLICT DO NOTHING` with the inline
  comment *"closed day is never recalculated"*.
- `money.allocation`: unique index on
  `(transaction_id, instalment_id, bucket, aging, COALESCE(reverses_allocation_id,0))`.
- Re-running the 23:30 job reports **"0 rows written and 1 row already closed"**; back-fill creates
  only the missing days, **in ascending date order, each opening from the prior closing**
  (TC-MNY-040).
- Re-running PTP detection for a past date **changes nothing** (REQ-COL-035).
- The 02:30 arrears safety net **may never create a duplicate** queue row (REQ-COL-011; TC-COL-016).

### 9.3 The closed day

> **REQ-MNY-014** — "A closed ledger day shall never be recalculated; a later correction is written
> as a dated adjustment row on the day it is made; month-end accruals are read from the ledger, and
> the summary card figures must equal the ledger rows to the satang" — S1 `PRD.md:218`

Trigger: *"reject UPDATE where is_closed"* (S2 `Data_Model.md:1685`). TC-MNY-041 asserts an attempted
UPDATE of `penalty_accrued_today` on a closed row is rejected.

### 9.4 Ledger completeness

> **REQ-MNY-013** — "A daily ledger job at 23:30 shall write one row per contract per calendar day
> from agreement start, idempotently, with: opening balance, payments received, interest for the day,
> penalty for the day, closing balance, cumulative arrears, principal outstanding,
> service_issue_frozen, penalty_accrued_today, dpd_on_date (null while PRE_COLLECTION; zero is a valid
> value distinct from null)" — S1 `PRD.md:217`

Row scope: `WHERE cs.is_collecting OR c.closed_at::date = :ledger_date` — a contract's final day gets
a row even as it closes.

Assertable: for every collecting contract and every Bangkok date from `activated_at` to today, a row
exists; `closing_balance(d) = opening_balance(d+1)`; `is_closed = false` only for today's provisional
row.

### 9.5 One-truth agreement to the satang

- G2 (S1 `PRD.md:65`): "Summary card, daily ledger, schedule printout and exported statement agree to
  the satang for every contract, every day."
- NFR-018 (S1 `PRD.md:497`): "Money NUMERIC(14,2); all rounding half-up to the satang; schedule totals
  equal to the satang; ledger equals card equals statement; foreign keys and check constraints on
  every enum; no nullable posting status. **Property-based tests on schedule and allocation.**"
- TC-MNY-027 (e2e): the six allocation figures are **byte-identical** across the ledger endpoint, the
  summary card and the accounting mirror; *"a discrepancy fails the test rather than being reconciled
  in the interface"*.

### 9.6 Legal entity on every money row

> **REQ-MNY-029** — "Every money row shall carry legal_entity resolved from the product group; a
> contract whose group cannot resolve an entity fails loudly on any money operation and posts
> nothing" — S1 `PRD.md:233`

`fn_transaction_legal_entity()` BEFORE INSERT copies from the contract and **raises on mismatch**.
TC-MNY-038: `entity_unresolved` naming the product group; **no money row of any kind; no partial
ledger row**; alert to Finance.

### 9.7 Schedule integrity

- Sum of scheduled lines = `total_amount` **exactly**, no residue (TC-MNY-003).
- At most one ACTIVE schedule per contract (`uq_schedule_active`).
- `checksum` unchanged across reads with a config edit in between (TC-MNY-006).
- `CHECK ((category = 'REGULAR') = (seq_no IS NOT NULL))`.
- `outstanding_amount` and `total_amount` are generated columns — they cannot be written wrong.

### 9.8 Row-level security is not cosmetic

TC-MNY-069: an officer not assigned the customer gets **HTTP 403 on the ledger, the arrears block and
the schedule**, the refusal is logged, and *"no figure, **not even a count**, leaks in the error
body"*.

---

## 10. The four known traps — verified against the text

*(Rulings 87 and 88, 2026-09-09, superseded the rate and grace figures this section analyses —
see the banner at the top of §5. The trap analysis below is preserved as the evidentiary record
of the pre-ruling source conflict.)*

### 10.1 CF1: 0.3 %/day vs 0.1 %/day — **CONFIRMED, UNRESOLVED, HIGH**

Both readings cite the same clause of the same agreement.

> **REQ-MNY-019** note, verbatim — "**CF1: 0.3 percent per day (this spec, CRM v6.7) versus 0.1
> percent per day (PAY v1.2); on 100,000 outstanding for 30 days past grace that is 4,800 versus
> 1,600** (owner: Win with Legal and Accounting)" — S1 `PRD.md:223`

> **OD-01** — "Penalty rate: 0.3 percent per day (this spec, CRM v6.7) or 0.1 percent per day (PAY
> v1.2) **from agreement VL0010399 §13.1 (CF1)**" · Rank **HIGH** · Owner **Win with Legal and
> Accounting** · Default shipped: "late_payment_daily_rate 0.003, labelled indicative; both figures
> stored; penalty invoicing flag OFF" · Gates REQ-MNY-019, REQ-ACC-006 — S1 `PRD.md:676`

> S4 `TEST-CASES-MNY.md:199` — "CF1 penalty rate: 0.3 percent per day in Spec §15.1, §22.1 and CRM
> v6.7 §9.8 against 0.1 percent per day in PAY v1.2, **both claiming the same clause of agreement
> VL0010399 verbatim** … the agreement must be opened once"

Corroborated outside the five sources:
`Security_Requirements.md:73` — *"Governs the penalty rate (§13.1; **this specification reads 0.3% per
day and PAY v1.2 reads 0.1% per day from the same clause** — CF1 is open, Spec §15.4)"*;
`PEAK_Integration.md:723`; `eraser-diagrams.md:858`.

**Verdict: the trap is real and stated accurately.** The agreement clause reference is
**VL0010399 §13.1**. Consequences the prototype must honour:

1. `late_payment_daily_rate` default **0.003**, `is_pending_rule true`, `locked false`.
2. Every screen and document showing a penalty carries **"indicative — CF1 pending"**.
3. `money.penalty.is_indicative` defaults **true**; false only when `penalty_invoicing_enabled` is on
   **and** CF1 is closed.
4. `penalty_invoicing_enabled = false`. Billing returns 422 `feature_disabled` naming CF1 and its
   owner.
5. **Do not resolve CF1 in code.** The single unblocking action is reading agreement VL0010399 once
   (S1 `PRD.md:644`).
6. Once confirmed, the key rises to `locked_category CONTRACT` and *"a change to any CONTRACT key
   triggers a **recomputation preview report** rather than an automatic back-dated recalculation"*
   (`Security_Requirements.md:443`, SEC-086).

### 10.2 The 150-baht worked example vs day-15 start — **CONFIRMED CONTRADICTION, DELIBERATELY UNRESOLVED**

Side A — the example, restated inside REQ-MNY-018's own acceptance list, then contradicted by the
same requirement:

> **REQ-MNY-018**, requirement text: "… **an instalment paid 10 days late attracts no penalty**"
> **REQ-MNY-018**, note column: "**Spec §15.2 first example (150) contradicts §15.3 and is not
> implemented; the engine follows §15.1**" — S1 `PRD.md:222`

Side B — §15.3, quoted verbatim in the repo:

> `PEAK_Integration.md:723` — Spec §15.3: **"A grace period of 14 calendar days runs from the due date
> … Penalty begins on day 15"**

The arithmetic of the disputed example is `5,000 × 0.003 × 10 = 150` — i.e. it counts from **day 1**,
which is only reachable with **grace = 0**.

The repo's chosen resolution, stated four independent times:

> S4 `TEST-CASES-MNY.md:142` (TC-MNY-057) — "Under Spec §15.1 a payment ten days late falls entirely
> within grace and attracts no penalty at all … **chargeable_days 0 and penalty 0.00, not 150; the
> implementation follows §15.1 and not the example; the deviation is printed in the module notes and
> carried as an open item for the Debt Manager until §15.2 is corrected or the grace rule restated**"

> S4 `TEST-CASES-MNY.md:200` (open issues) — "Spec §15.2 first worked example charges 150 on an
> instalment 10 days late, **which contradicts the 14-day grace of §15.1 and §15.3**" · Status:
> "Deviation stated: the engine follows §15.1 and TC-MNY-057 expects 0.00; **the example must be
> corrected or the grace rule restated**" · Owner **Debt Manager**

> S2 `Data_Model.md:4098` — "The first example in Spec §15.2 (10 days, 150 baht) is inside grace and
> yields 0, **as the spec's own notice requires**."

> `eraser-diagrams.md:858` — "The Spec §15.2 first worked example (10 days late, 150 baht) **is not
> implemented** — the engine follows §15.1 and charges nothing inside the 14-day grace."

**Verdict: the trap is real and the repo already flags it — but it is flagged as a DEVIATION, not as
a resolution.** The underlying document still contains an example that is arithmetically incompatible
with its own grace rule. Nobody has amended §15.2, and the owner (Debt Manager) has not decided.

**Marked KNOWN CONTRADICTION. Not reconciled here.** The prototype implements §15.1/§15.3 (0.00 at
10 days late) and must surface the deviation in module notes, exactly as TC-MNY-057 demands. The
open item stays open.

**Third, quieter instance of the same class:** the §15.2 *third* example (267.84) aggregates two
instalments at one days-late figure while the engine accrues per instalment. See §5.4 E3.

### 10.3 Grace at 0 / 11 / 14 — **NOT REPRODUCIBLE IN THIS REPO**

**Finding: the LOCAL spec repo is unanimous on 14. There is no 0/11/14 debate in the text.**

I grepped the whole repo for grace values. Every hit says 14 / start day 15. Eleven independent
statements, zero dissent:

| Where | Statement |
|---|---|
| S1 `PRD.md:222` | REQ-MNY-018: "Grace shall be **14 calendar days** … penalty starts on day 15 (penalty_start_day 15)" |
| S1 `PRD.md:390` | REQ-CFG-002 seed: "late_payment_grace_days **14** (Owner)" |
| S1 `PRD.md:580` | Journey J5: "days **1–14 are grace** with no penalty" |
| S1 `PRD.md:721` | Glossary: "Grace period · ระยะผ่อนผัน · **14 calendar days** from due date with no penalty; penalty starts day 15" |
| S2 `Data_Model.md:1701` | `money.penalty.grace_days SMALLINT NOT NULL` — default note "**14**" |
| S2 `Data_Model.md:4502` | Seed: `late_payment_grace_days | **14** | no | OWNER | §22.1` |
| S2 `Data_Model.md:4067` | "§15.3 grace **14** days and penalty start day 15" |
| S3 `:198` | "penalty at **day 15**" |
| S3 `:585` | "From **day 15** after the due date (**14-day grace**)" |
| S3 `:628` | X7, **marked "Closed"**: "late_payment_grace_days **14**, penalty_start_day 15 … Open only on CF1 value; **design closed**" |
| S4 `:50`, `:139`, `:177` | FX-CFG-MNY `late_payment_grace_days 14`; TC-MNY-054 day-14/day-15 boundary |

Corroborated by `TEST-CASES-CFG.md:98` (TC-CFG-022 seed assertion: "late_payment_grace_days **14
days** from the invoice due date; penalty_start_day **15**").

**The only other numbers that appear are not policy alternatives:**

- **21 and 10** (`TEST-CASES-CFG.md:78-79`) — arbitrary product-group and product override values
  used to exercise the four-level resolver. Not candidate policies.
- **7** (`ADR-002:74`) — an ERPNext/Frappe **spike** value, explicitly disowned:
  *"spike parameters (8.5%, 18%, 7-day grace) were **test values, not Volt decisions**"*, restated in
  S3 X7: *"the spike numbers are Frappe test values, not Volt decisions"*.
- **0** appears only as `interest_rate_during_grace = 0` — a *rate*, not a *duration*.

**11 does not appear anywhere in the repo in connection with grace.** Zero hits.

**How grace is nevertheless "open", precisely:**

1. It is **configuration, not code**: `late_payment_grace_days`, `locked_category NONE`,
   `LOCKED=false`, Owner-editable, effective-dated (TC-CFG-028 shows 14 → 21 versioning), and
   resolvable at product / product-group / legal-entity / system level.
2. **CF1's resolution is expected to move it.** SEC-020: *"keys with locked_category CONTRACT
   (penalty_calculation_method today; **late_payment_daily_rate, allocation order and grace join them
   once CF1 and the allocation order close**)"*. SEC-086 lists *"grace 14 days"* among "the VL0010399
   values" carrying `is_pending_rule true` until the Owner confirms. So **grace is legally
   unconfirmed even though it is numerically undisputed in this repo** — the agreement has not been
   read.
3. PRD `:644` lists what reading VL0010399 closes: *"CF1 penalty rate, allocation order, day-count
   basis, **grace treatment**, early settlement"*.

**Verdict on the trap as stated:** *"genuinely open at 0 / 11 / 14"* is **not supported by the local
spec repo**. The 0 and 11 figures come from outside these five documents — the vault note records a
2026-08-25 live-sheet reality check finding grace unsettled at 0/11/14 in the operational sheet. That
is real-world evidence that **production practice may differ from the spec**, and it is a strong
reason to keep `late_payment_grace_days` configurable and resolvable per product group. But it is
**not** a contradiction inside the spec, and the brief must not present it as one.

**Prototype rule, as extracted 2026-08-26:** implement **14 / start day 15** as the seeded system
default. Never hard-code it — read the key through the resolver. Keep the boundary test (day 14 =
0.00, day 15 = 16.74) so a migration to 0 or 11 is a config change plus a re-run of one test, not a
code change. If the live sheet's 0/11/14 is confirmed, that becomes a **new open decision** with an
owner, and it should be raised against the Debt Manager alongside the §15.2 deviation.

**Superseded 2026-09-09.** Ruling 88 is exactly that migration: `late_payment_grace_days` moved to
**0** (no grace; penalty runs from the due date), as the config change this paragraph anticipated —
see §5's banner.

### 10.4 REQ-MNY-019 dual-rate storage — **CONFIRMED: REQUIRED, TESTED, AND NOT MODELLED**

The requirement:

> **REQ-MNY-019** — "The penalty rate shall be the configuration key late_payment_daily_rate with
> default 0.003 and LOCKED=false, labelled 'indicative — CF1 pending' on every screen and document
> until the Owner marks the key confirmed; **the engine also evaluates the alternative 0.001 and
> stores both figures in the ledger so that a later correction is a dated adjustment and not a
> recalculation**" — S1 `PRD.md:223`, Spec §15.4, §22.1, MVP

The test that depends on it:

> **TC-MNY-058** (`TEST-CASES-MNY.md:143`) — "Both candidate rates are stored so a later correction is
> a dated adjustment and not a recalculation … **Primary cumulative_amount 133.92 at 0.003 and the
> parallel figure 44.64 at 0.001 both recorded against the accrual row**; is_indicative true on every
> row…" · P0 · integration

The workflow doc assumes it too:

> S3 `:473` — "15: penalty accrual starts (**indicative, both 0.003 and 0.001 stored**)"
> S3 `:628` (X7) — "late_payment_daily_rate 0.003 **with the alternative 0.001 also evaluated and
> stored**"

**What Data Model v1.0 actually provides.** `money.penalty` (S2 `Data_Model.md:1687-1715`) has
exactly these amount/rate columns:

```
overdue_base_amount, daily_rate, rate_resolution_level, rate_config_value_id,
grace_days, days_past_due, chargeable_days, day_count_basis,
amount, cumulative_amount, is_frozen_day, is_indicative, status, engine_version
```

`daily_rate` is **singular** (`NUMERIC(9,6)`, "resolved late_payment_daily_rate, e.g. 0.003000").
`amount` and `cumulative_amount` are **singular**. There is **no** `alternative_rate`,
`alternative_amount`, `alternative_cumulative_amount`, or equivalent.

The accrual INSERT (S2 §7.3, `:4069-4093`) resolves `late_payment_daily_rate` **once** via
`config.fn_resolve_numeric` and computes **one** amount. Nothing evaluates 0.001.

`money.daily_ledger` (S2 `:1647-1685`) has `penalty_accrued_today`, `penalty_accrued_unbilled`,
`penalty_billed`, `penalty_paid`, `penalty_waived` — **five single-rate figures, no parallel set**.

A grep for `0.001` across the whole Data Model returns exactly **one** hit — the prose in the config
seed table (`:4501`) explaining what PAY claims. Not a column, not a computation.

The Data Model's own open register (S2 §13.7) tracks pending rules only as
*"config keys with is_pending_rule; **money.penalty.is_indicative**; money.early_settlement_quote.formula_version"* —
i.e. a **boolean flag**, which is a *different and weaker* mechanism than storing both figures.

**Verdict: the trap is real and precisely as described.** REQ-MNY-019's dual-rate storage clause was
never carried into Data Model v1.0. A P0 integration test (TC-MNY-058) asserts a column that does not
exist. This is a genuine spec-to-schema defect, not a misreading.

**Options for the prototype, in preference order:**

1. **Add the columns** (smallest change, keeps REQ-MNY-019 and TC-MNY-058 both true):
   `alt_daily_rate NUMERIC(9,6)`, `alt_amount NUMERIC(14,2)`, `alt_cumulative_amount NUMERIC(14,2)`
   on `money.penalty`; optionally `penalty_accrued_today_alt` / `penalty_accrued_unbilled_alt` on
   `money.daily_ledger` so the ledger claim in the requirement ("stores both figures **in the
   ledger**") is literally satisfied. Source the alternative from a second config key rather than a
   hard-coded 0.001, so a third candidate rate costs nothing.
2. **Amend REQ-MNY-019 and TC-MNY-058** to require only `is_indicative` plus the snapshotted
   `daily_rate`/`rate_config_value_id`, and rely on SEC-086's *recomputation preview report* when CF1
   closes.

Do **not** silently ship option 2's behaviour while leaving option 1's requirement text standing —
that is how the gap arose. Raise it as a defect against Data_Model.md v1.0, owner Arina with
Accounting.

---

## 11. Configuration keys the money engine reads

All resolve through `config.fn_resolve_numeric(key, product_id, product_group_id, legal_entity,
as_of)` → `(value, level_answered, value_id)`. The API returns **both the value and the level**
(REQ-MNY-020). Cache staleness is bounded: a removed product-level row is picked up "without any cache
flush older than 60 seconds" (TC-CFG-003).

| Key | Seeded | Locked | Editor | Status |
|---|---|---|---|---|
| `annual_interest_rate_financing` | 7.9 (percent/yr, flat) | no | OWNER | SETTLED |
| `late_payment_daily_rate` | 0.0003 (fraction/day) — superseded 2026-09-09, ruling 87; was 0.003 | no, decided | OWNER | **SUPERSEDED — ruling 87** |
| `late_payment_grace_days` | 0 — superseded 2026-09-09, ruling 88; was 14 | no | OWNER | **SUPERSEDED — ruling 88**; see §10.3 |
| `penalty_start_day` | 1 — superseded 2026-09-09, ruling 88; was 15 | no | OWNER | **SUPERSEDED — ruling 88**; see §10.3 |
| `interest_rate_during_grace` | 0 | no | OWNER | SETTLED |
| `penalty_calculation_method` | SIMPLE | **CONTRACT** | — | SETTLED, locked |
| `accrual_method` | SIMPLE | **CONTRACT** | — | SETTLED, locked |
| `day_count_basis` | CALENDAR | no | OWNER | SETTLED |
| `rate_type` | FIXED | no | OWNER | SETTLED; VARIABLE → 422 |
| `financing_term_options_months` | 24/36/48/60/72, default 60 | no | DEBT_MANAGER | SETTLED |
| `down_payment_tiers_percent` | 0/10/20/30 | no | OWNER | SETTLED (15/25 → 422) |
| `financing_first_due_offset_days` | 30 | no | OWNER | SETTLED |
| `cash_first_due_offset_days` | **null** | no, pending | OWNER | **OPEN — fail loudly** |
| `invoice_payment_terms_days` | 7 | no | OWNER | SETTLED (≠ grace) |
| `cash_3_surcharge_percent` | 5 | no | OWNER | SETTLED (priced at quote) |
| `pre_install_deposit_baht` | 5000 | no | OWNER | SETTLED |
| `pre_install_lease_deposit_equals_first_installment` | true | no | OWNER | SETTLED |
| `allocation_order` | OLDEST_INSTALMENT_FIRST **then component order PENDING** | no, pending | ACCOUNTING | **OPEN — OD-02** |
| `early_settlement_method` | **null** | no, pending | OWNER | **OPEN — OD-03** |
| `closed_period_rule` | **null** | no, pending | ACCOUNTING | **OPEN — OD-11** |
| `npl_dpd_threshold_days` | **null** | no, pending | OWNER | **OPEN — OD-04** |
| `vat_basis` | **null** | no, pending | ACCOUNTING | **OPEN — OD-05** |
| `penalty_waiver_policy_limit` | **null** | no | OWNER | **OPEN — OD-29** |
| `supervisor_penalty_waive_max_dpd` | 7 | no | OWNER | SETTLED |
| `service_issue_dpd_reset_partial_authority` | OFFICER_WITH_EVIDENCE | no | DEBT_MANAGER | SETTLED |
| `service_issue_dpd_reset_full_authority` | SUPERVISOR_OR_MANAGER | no | DEBT_MANAGER | SETTLED |
| `hold_types` | 3 types | **POLICY** | — | SETTLED |
| `hold_reason_required` / `hold_expiry_required` | true / true | **POLICY** | — | SETTLED |
| `collection_queue_entry_mode` | EVENT_DRIVEN | no | DEBT_MANAGER | SETTLED |
| `claim_expiry_days` | 5 | no | ACCOUNTING | SETTLED |
| `schedule_mismatch_tolerance_baht` | 1.00 | POLICY | DEBT_MANAGER | minor OPEN vs ADR-006's 0.01 |
| `accounting_adapter_per_legal_entity` | SPV: PEAK_SPV, EPC: null | no | OWNER + ACCOUNTING | SETTLED (D-13) |
| `dpd_recalculation_time` / `penalty_accrual_time` / `today_list_generation_time` | 02:05 / 03:00 / 02:30 | no | DEBT_MANAGER | SETTLED (02:05 is a deviation) |
| feature flag `penalty_invoicing_enabled` | **true** — superseded 2026-09-09, ruling 87; was **false** | — | — | **SUPERSEDED — ruling 87**; see §5.7 |
| feature flag `penalty_display_indicative` | true | — | — | SETTLED |

---

## 12. Open items the prototype must carry visibly

Every one of these must make the engine **refuse or label**, never guess.

| Item | Ref | Owner | Required engine behaviour |
|---|---|---|---|
| Penalty rate 0.003 vs 0.001 — superseded 2026-09-09, ruling 87 | CF1 / OD-01 / REQ-MNY-019 | Win + Legal + Accounting | **SUPERSEDED — ruling 87.** CF1 is DECIDED at 0.0003 (0.03 %/day); this item is no longer open and billing is no longer flagged off. Was: compute at 0.003, label indicative, store both (see §10.4), billing flag OFF |
| Allocation component order | OD-02 / REQ-MNY-011 | Accounting + Legal | manual 422 `allocation_rule_pending`; webhook records unallocated + ACC exception |
| Early settlement method | OD-03 / REQ-MNY-024 | Owner + Accounting + Legal | 422 `early_settlement_rule_pending` on quote **and** on accept, for any quote status |
| NPL DPD threshold | OD-04 / REQ-MOD-014 | Owner | null; DPD-30 review raised; flagging stays **manual** |
| VAT basis | OD-05 | Tax adviser | out of Debt; expose principal/interest split per instalment |
| Closed-period rule | OD-11 / REQ-MNY-012 | Accounting | hold PENDING, exceptions screen, name the owner |
| §15.2 first example (150) | REQ-MNY-018 note / TC-MNY-057 | Debt Manager | return 0.00; **print the deviation in module notes** |
| §15.2 third example (267.84) aggregate vs per-line | TC-MNY-056 | Debt Manager + Accounting | accrue per instalment; record both readings |
| `cash_first_due_offset_days` | OD-30 / S2 §13.13 | Debt Manager | **fail loudly**, do not default to 30 |
| `penalty_waiver_policy_limit` | OD-29 / S2 §13.16 | Credit & Risk Mgr + Owner | `configuration_missing`, never default-to-allow |
| Maintenance SLA tiers (CF3) | OD-15 / REQ-COL-042 | Win + OPS | freeze unbounded; `sla_tier` informational; escalate to Manager |
| Retroactive DPD on service-issue abuse | OD-19 / D6 | Debt Manager | record `retroactive_dpd_applied`, **do not enforce** |
| Down-payment tiers 15 / 25 from Odoo | OD-27 / TC-MNY-011 | Debt Manager + Sales | 422; hold at PRE_COLLECTION with DPD null |
| Schedule-vs-Odoo tolerance 0.01 vs 1.00 | ADR-006 vs S2 seed | Arina + Debt Manager | read the config key |

---

## 13. Reading order for an implementer

1. `PRD.md:205-234` — the thirty REQ-MNY rows. Twenty minutes; the whole contract.
2. `Data_Model.md:3906-4099` — §7.1 DPD, §7.2 daily ledger, §7.3 penalty accrual. **This SQL is the
   specification.** "Application code (SQLAlchemy) must produce the same answers."
3. `TEST-CASES-MNY.md:41-51` — the fixtures. Seed these exact numbers.
4. `TEST-CASES-MNY.md:86-160` — the seventy cases, in order.
5. `TEST-CASES-MNY.md:196-209` — the eleven open issues this module carries.
6. `ADR-006` — why the schedule lives here and why money is append-only.
