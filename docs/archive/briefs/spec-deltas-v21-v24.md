# Volt Debt Prototype — Spec Deltas from the v1.0 Baseline

| | |
|:--|:--|
| Document | What changed between the local v1.0 spec repo and the current Drive authority, and what the prototype must do about it |
| Baseline | `/Users/parattakorn/volt-debt-collection/docs` — v1.0, committed 2026-08-21 |
| Written | 2026-08-26 |
| Covers | Only what DIFFERS from a v1.0 reading. Everything not named here is unchanged and v1.0 remains the authority for it. |
| Verdict | All ten questions put to this review are **CONFIRMED**. None was refuted. Four carry a trap that the question did not ask about, and those are flagged inline. |

## 0. How to read this document

This section explains the codes and words used below. Nothing here is a delta. Skip to section 1 if you already know the project.

### 0.1 The authority ladder

> **Note (2026-08-30):** this ladder is superseded by the ladder in `spec-deltas-v25-rebuild.md` §0, which adds the deck "SPV/EPC Scenario Workflows v20.0" and Requirements Amendment v2.5. The deltas below remain in force.

Later documents beat earlier ones, and a document that *names* a requirement beats one that merely implies it. In descending order:

| Rank | Document | Date | Authority |
|:--|:--|:--|:--|
| 1 | **Requirements Amendment v2.4** | 2026-08-26 | Highest, **for what it names only**. Where it amends a requirement, its text "replaces the text in version 2.1 **in full**". |
| 2 | **Grilling Session Record** | 2026-08-26 | The 14 decisions G1–G14 the amendment is built from. Use it for *why*, not for *what* — see the counting error at section 3.1. |
| 3 | **Case Register v1.2**, **Runbook Alignment v2.3** | 2026-08-26 | Downstream applications of the same decisions. Consistent with the amendment. |
| 4 | **PRD v2.1**, **Data Model v2.1** | 2026-08-25 | Authority for everything the amendment does not name. **Pre-dates G1–G14**, so parts of it are already overridden — see section 3.2. |
| 5 | Local repo v1.0 | 2026-08-21 | Baseline. In force only where nothing above touches it. |

### 0.2 The codes

| Code | What it points at |
|:--|:--|
| `REQ-XXX-NNN` | A numbered requirement. `MNY` money, `COL` collections, `KPI` reporting, `AUD` audit, `MOD` modifications and recovery, `IAM` identity. |
| `G1`–`G14` | A decision taken 2026-08-26 (Grilling Session Record). |
| `D1`–`D16` | A decision taken 2026-08-25. `D13` is amended by `G7`. |
| `A-03`, `A-08`, `A-11` | An assumption recorded 2026-08-21. |
| `RA-01`–`RA-03` | Open items raised by the amendment. All three closed. |
| The clock | How many days a payment is overdue, and whether that count is running. |
| The fee | The late charge. **Since G7 this is a separate thing from the clock.** |
| Counting contact | A contact that uses up the customer's one permitted contact for the day. **Stating the amount owed is what makes it count.** |

### 0.3 The one idea that changed

Quoted from Amendment v2.4 §0.2, because every money delta below descends from it:

> Before this session, being late and being charged for it were the same thing. A hold either stopped both or stopped neither, and there was one rule. Decision G7 separated them. [...] There are now states where a customer is visibly, increasingly late and is not being charged a satang for it, and that is deliberate.
>
> **The fee stops when the delay is not the customer's doing and not in dispute. It keeps running when the customer's own account of events has not yet been verified.**

Apply that sentence to any state not in the table at section 2.2.

---

## 1. Verdict on the ten questions

| # | Question | Verdict | Trap |
|:--|:--|:--|:--|
| 1 | Penalty accrues on arrears only, not the outstanding balance | **CONFIRMED** | Yes — §2.1 |
| 2 | Permit hold pauses the fee but not the clock; two rules not one | **CONFIRMED** | Yes — §3.1 |
| 3 | Power restriction is live; approver Owner with Legal; 18 backfilled, no approver | **CONFIRMED** | Yes — §3.3 |
| 4 | Restoration same business day before 15:00, next business day after | **CONFIRMED** | Yes — §2.4 |
| 5 | Two named collection indicators, not one | **CONFIRMED** | — |
| 6 | `REQ-COL-054` stable column identifier; delete needs a nominated destination | **CONFIRMED** | — |
| 7 | `REQ-COL-055` 90-second retraction window on the daily slot | **CONFIRMED** | — |
| 8 | `REQ-IAM-015` refuses to seed a vacant approval path; Owner absorbs Debt Manager | **CONFIRMED** | — |
| 9 | Collection denominator excludes service-held, permit-held and closing | **CONFIRMED** | — |
| 10 | `band_set_code` must travel beside every `aging_bucket` | **CONFIRMED** | — |

---

## 2. The deltas

### 2.1 The penalty base — and the per-day rule underneath it

**RULE.** What the late fee accrues on.

**v1.0 said** (`REQ-MNY-017`):

> Penalty shall be computed as `overdue_installment_amount × late_payment_daily_rate × days_overdue_after_grace`, simple and not compounding, where `overdue_installment_amount` is the sum of unpaid instalments past due excluding penalty itself

**Current authority says** (`REQ-MNY-017`, AMENDED by G2 — Amendment v2.4 §1):

> **The fee shall accrue on arrears only.** The daily late fee is computed on the sum of instalments that are overdue on that day, and never on the outstanding balance of the contract. **Where arrears change during the period of lateness, the fee for each day is computed on the arrears as they stood on that day, so a fee cannot be recomputed by multiplying a final arrears figure by a total number of days.**

**WHAT THE PROTOTYPE MUST DO.**

1. Accrue **per day, on that day's arrears**. Store one accrual row per contract per day. Never compute the fee as one multiplication over a day span.
2. Reject the balance-based figure. Grilling G2 records that the balance option "is what screen 07 P6 currently shows" — the Figma is wrong, not the requirement.
3. Label every fee figure with its base and state (`REQ-MNY-018` as amended): accruing / paused-with-state-and-start-date / reversed-with-reason, and the word **indicative** while `A-03` is open, with **no accounting document created from it**.

> **TRAP — the v1.0 formula and its acceptance examples are only valid on a constant-arrears window.** The v1.0 worked example `5,580 × 0.003 × 8 = 133.92` still gives the right answer, but only because arrears do not move across those 8 days. The moment a second instalment falls due or a partial payment lands mid-window, the v1.0 arithmetic and the current rule diverge. Build the day loop, not the multiplication, even though the fixture agrees.

> **TRAP — `REQ-MNY-018` has been overwritten with a different subject.** In PRD v2.1 `REQ-MNY-018` is the **grace period** requirement ("Grace shall be a configured number of calendar days from the due date with no interest during it, and penalty starts the day after"). Amendment v2.4 names `REQ-MNY-018` as AMENDED and gives it text about **fee labelling** instead — and the amendment's own §0.1 says its text "replaces the text in version 2.1 in full". Read literally, the grace requirement is now orphaned. Do not infer that grace is abolished: Amendment §4 lists "The rate, the grace period and the other pending rules under A-03" as *unchanged and still pending*. **Prototype: keep grace as configuration, implement the labelling rule as well, and raise the renumbering with Arina.** Live grace values are unsettled at 0 / 11 / 14 days (three positions in live use, D8 declined to choose).

---

### 2.2 The fee and the clock are two rules, not one

**RULE.** Which states stop the lateness clock, and which stop the fee.

**v1.0 said** (`REQ-COL-039`): three hold types, and the fee and clock always moved together —

> `PENALTY_SERVICE_HOLD` **suspends penalty accrual and DPD counting** while contact may continue

with `hold_types three (LOCKED policy)` in `REQ-CFG-003`, and a single boolean `is_frozen_day` on the daily ledger.

**Current authority says** (`REQ-MNY-032`, NEW, from G7/G9/G13 — Amendment v2.4 §1):

> **The fee and the lateness clock are separate.** A state may stop one, both, or neither. The system shall hold a **single table of states** and their effect on each, and every screen and job that reads one shall read it from that table rather than deriving it.

| State | Lateness clock | Late fee |
|:--|:--|:--|
| Service hold, fault confirmed | **Stops** | **Stops** |
| Permit hold, authority awaited | Runs | **Stops** |
| Deceased flag set | Runs | **Stops** |
| Property sold, novation unresolved | Runs | **Stops** |
| Juristic customer dissolved | Runs | **Stops** |
| Dispute or complaint under review | Runs | Runs |
| Claim pending | Runs | Runs |

Answering the sub-questions directly:

- **Does a permit hold pause the fee but not the clock?** Yes. G7, "Decision, amending D13. A permit hold pauses the fee and does not pause the clock. **D13 becomes two rules.**"
- **Which other states pause the fee?** Four: service hold (which also stops the clock), deceased, property sold with novation unresolved, juristic customer dissolved. **Five rows stop the fee in total.**
- **Does a dispute pause it?** **No.** `REQ-MNY-033`: "An open dispute or harassment complaint **shall not** pause the fee. The fee continues to accrue during the review." G9 originally paused it; **G13 reversed that**. The reasoning, worth keeping: "A pause on complaint makes a complaint worth money, and word of that travels faster than any collections letter."

**WHAT THE PROTOTYPE MUST DO.**

1. Replace the single freeze attribute with a **governed state table carrying two independent booleans** — `stops_clock`, `stops_fee`. Amendment §3 is explicit that these "are different columns because they are different facts."
2. **Every consumer reads the table.** No screen and no job may derive pause behaviour from a hold type. This is the whole point of `REQ-MNY-032`.
3. Add the **fourth hold type** (external permit hold). v1.0 locks the list at three.
4. Mark a paused day in the daily ledger **with the state that paused it**, in a column distinct from the existing frozen-day marker. "The fee shall not be recomputed for a paused day at any later time, whatever the eventual outcome of the state" — except where a reversal rule below applies.
5. Implement the nightly **reconciliation** (`REQ-MNY-036`, closing RA-02) at **03:50**, job `fee-state-check`: compare states in force against fee accrued for every contract, raise an exception on exactly two disagreements — a fee that accrued while a pausing state was in force, and a fee that did not accrue while none was. P2 for a handful; **P1 above ten in one night**, because that many means the state table itself is being read wrongly.
6. **Decompose every fee total** on any report or screen into: fee accrued, fee not accrued by reason of a pausing state broken down by state, and fee reversed broken down by reason.

> There is **no runbook procedure** for the individual pause states, and that is deliberate. `REQ-MNY-036`: "a runbook entry begins with a detection signal and none of those four states produces one. Nothing fails. A fee pausing is the system working."

---

### 2.3 Reversals — the date, and the period boundary

**RULE.** When an accrued fee is unwound, to what date, and whether history moves.

**v1.0 said** (`REQ-MNY-014`): "A closed ledger day shall never be recalculated. A later correction is a dated adjustment row on the day it is made." Append-only, no exceptions, no effective-date concept.

**Current authority says.**

`REQ-MNY-034` (from G8, G11) — **claim confirmed**:

> Where a claim is subsequently confirmed against a receipt, the fee accrued shall be reversed to the **value date of the receipt**, being the day the money left the customer's account, and not to the date the slip was uploaded or the date Accounting confirmed it. Where the claim is rejected, nothing is reversed.

`REQ-MNY-033` (from G13) — **complaint substantiated**:

> If the review finds that a breach occurred, the fee accrued **from the date the complaint was received** shall be reversed by an audited entry carrying the review outcome as its reason. If the review finds no breach, nothing is reversed and nothing is back-charged, because nothing was paused.

`REQ-MNY-035` (from G14) — **the boundary**:

> A reversal whose effective date falls inside the **current open** accounting period shall **restate** the daily ledger rows from that date forward, so that each day reads correctly.
>
> A reversal whose effective date falls inside a **closed** accounting period shall **not restate anything**. It is posted on the current date carrying the earlier effective date as an attribute, and the closed period is never altered.

**WHAT THE PROTOTYPE MUST DO.**

1. Give the reversal entry an **effective date distinct from the posting date**, plus a flag recording whether it restated rows or was posted forward.
2. Branch on period state, not on age. Open period → restate daily rows from the effective date forward. Closed period → post today, carry the effective date as an attribute, touch nothing.
3. Two different reversal anchors — **receipt value date** for a confirmed claim, **complaint received date** for a substantiated breach. Do not collapse them into one.
4. Expect and do not "fix" this: "a claim confirmed with a value date in a closed month produces a correction that does not appear in that month, so a reader comparing two months will find them disagreeing by the amount of the reversal. **That is correct, and it will be reported as a defect at least once.**"

---

### 2.4 Power restriction and restoration

**RULE.** Reducing a customer's solar output as a collections instrument, and putting it back.

**v1.0 said.** Nothing. Power restriction is **absent from the v1.0 PRD entirely** — the only `restrict` hits in the baseline are about encrypted data. The v1.0 Data Model carries only a `power_status` column on the contract, "prepared for a later phase, which records a state but not an act." There was no approver, no notice precondition, no restoration rule and no restoration deadline.

**Current authority says** (`REQ-MOD-029`, PRD v2.1, AMENDED by D3, D5, D6, D9, D10, D15):

> A power restriction modification shall cover any deliberate reduction or suspension of a customer's system output used as a collections instrument. It requires a reason code, **approval by the Owner with Legal consulted on the legal basis**, a legal basis reference, **a customer notice document that has been sent**, and a restriction date. It shall record a mandatory restoration path with the restoration trigger and the restoration date when output is restored; the restoration trigger shall be **any confirmed payment, executed by a supervisor or customer operations and not by the officer who confirmed the payment**. **Restoration shall be due the same business day where the payment is confirmed before a published cut-off time, and the next business day otherwise.** No restriction may be recorded retrospectively, with one bounded exception: **the restrictions already in force at cut-over shall be recorded through an audited backfill, flagged as backfilled, carrying no approver, and shall never trigger a customer message. The feature ships switched on.**

Supporting decisions:

- **D5** — "The Owner approves each restriction, with Legal consulted on the legal basis. **CHANGES the approver from a vacant manager role to a named person.**"
- **D9** — "The 18 restrictions already in force stay backfilled with no approver [...] Recorded so that a reader who finds 18 rows with a null approver knows it is intended."
- **D15** — "**The restoration cut-off is 15:00.** [...] Publishable on the restriction notice, so the customer is told the rule rather than left to infer it."
- Data Model v2.1 seed change: "`power_restoration_sla_hours` **is withdrawn** and replaced by `power_restoration_basis`" = `SAME_BUSINESS_DAY_BEFORE_CUTOFF` and `power_restoration_cutoff_time` = "**15:00**, in Asia slash Bangkok [...] **Stored as a time, not a timestamp, and read with the holiday table** so that next business day means what it says". The withdrawn key "version 2.0 seeded at a rolling 24 and which **promised something weekend staffing cannot deliver**."

**WHAT THE PROTOTYPE MUST DO.**

1. Ship power restriction **on**, not behind a flag. Set `power_restriction_enabled` true and `power_restriction_approver_role` to OWNER with LEGAL consulted.
2. Enforce the **sent notice** as a database-level precondition, not a procedure. The runbook expects the failure mode an engineer sees to be "a refused write rather than an unlawful act" — a 422 with a precondition code.
3. Compute restoration due time as **business-day arithmetic against a 15:00 Asia/Bangkok time value read with the holiday table**. **Not a rolling 24 hours.** Confirmed before 15:00 → same business day; at or after → next business day.
4. Trigger restoration on a **confirmed receipt only**. Case P3: "A confirmed receipt starts the restoration clock; **a pending claim does not**. This is the only place where the difference between the two reaches the customer as reduced electricity."
5. **Separation of duties**: the officer who confirmed the payment may not execute the restoration. Supervisor or customer operations only.
6. Seed the **18 backfilled rows** with `is_backfilled` true, a **null approver**, and a hard suppression on customer messaging. They are excluded from the "restriction without notice" alert **by the backfill marker, not by their age**.
7. Refuse any retrospective restriction outside that backfill.

> **TRAP — the Data Model contradicts itself on the switch.** Data Model v2.1 §3.4.1 still carries the v2.0 sentence "**It ships behind a switch that is off**, so the structure exists whichever way OQ-29 is decided." Its own decisions table two sections earlier says `power_restriction_enabled` **becomes true**, and PRD v2.1 `REQ-MOD-029` says "The feature ships switched on", with OQ-29 and OQ-30 **closed**. The §3.4.1 prose is stale. **Ship it on.**

---

### 2.5 Two collection indicators, not one

**RULE.** How collected amount is measured and reported.

**v1.0 said** (`REQ-KPI-001`): nine core indicators, of which the first is a single figure — "1 collection amount (actual collected, primary)". One definition, one number.

**Current authority says** (`REQ-KPI-017`, PRD v2.1, AMENDED by D14):

> There shall be **two collected-amount indicators, not one, each a separate definition rather than one definition with a parameter**. The **cash-received** indicator counts a payment in the month the cash arrived and reconciles to the bank and to the accounting receipts. The **due-month** indicator counts it in the month the instalment it settles was due, and **is the performance figure**. Both shall report actual against the configured monthly target for portfolio, team and officer, both shall state which measure they used wherever they are displayed or exported, and **neither shall be the default when a caller omits the measure**. Both shall decompose the shortfall into at least: amount held behind an open fault or permit hold; amount on contracts in a **closing or pending-cancellation** state; amount under an active promise; and **amount genuinely unworked**.

D14: "Two named collection indicators rather than one: cash received in the month, and due-month attainment. **A single figure cannot both keep a closed month stable and reflect late payments landing.**"

**WHAT THE PROTOTYPE MUST DO.**

1. Build **two distinct indicators**, not one function with a `measure` argument.
2. **No default.** A caller that omits the measure gets an error, not a figure. This is the discipline that makes two figures in circulation safe.
3. Stamp the measure on **every** display and export.
4. Emit the **four-line shortfall decomposition** with every figure. Roughly half the current shortfall is faults and dead-contract invoices rather than collection failure; the residual "genuinely unworked" line is the management number.

---

### 2.6 The collection denominator

**RULE.** Which contracts count in the denominator of a collection figure.

**v1.0 said** (`REQ-KPI-007`): "**Service-issue-held accounts** shall be excluded from officer KPIs and NPL assessment for the held period." One hold type, and no mention of the collection target denominator or of closing contracts.

**Current authority says.**

`REQ-KPI-007` (PRD v2.1, AMENDED, confirmed by D7):

> Accounts under a **fault hold or an external permit hold** shall be excluded from officer indicators, **from the collection target denominator** and from non-performing assessment for the held period.

**D7**, verbatim:

> The collection denominator **excludes contracts that cannot be worked: service-held, permit-held, already closing.** They remain visible as the held and closing lines of the shortfall.

Scale, from the `REQ-KPI-007` note: "Applied to the current book this removes roughly **THB 3.1 million of cash arrears and 30 lease contracts** from the overdue figures, which is correct behaviour and must be explained before it happens."

**WHAT THE PROTOTYPE MUST DO.**

1. Exclude all three classes — **service-held, permit-held, already closing** — from the collection denominator.
2. **Exclude but do not hide.** Each excluded class reappears as a named line of the shortfall decomposition (§2.5). Excluded from the denominator, present on the report.
3. Keep the **non-performing exclusion** for the held period. The `REQ-KPI-007` note calls it "load-bearing rather than cosmetic": since D13 removed the clock freeze from the permit hold, a permit-delayed contract keeps ageing while no officer indicator counts it, and only this exclusion stops that becoming an automatic non-performing classification.
4. Note the different rule for **blocked** accounts — see §2.9. Blocked and held are not the same exclusion.

---

### 2.7 `band_set_code` beside every `aging_bucket`

**RULE.** How an aging band is identified.

**v1.0 said.** `ref.aging_bucket` has `code` as its **sole primary key**, with a non-overlap exclusion constraint across all rows, and seed values `CURRENT, EARLY_OVERDUE, MID_OVERDUE, RISK_REVIEW, NPL_CONFIRMED, RESOLVED, CLOSED`. `money.daily_ledger` carries a bare `aging_bucket_code`. One set of boundaries existed, so a code alone was unambiguous.

**Current authority says.**

`REQ-MNY-016` (PRD v2.1, AMENDED, LC-11):

> Reporting bands of 30 to 59, 60 to 89 and 90 or more support the portfolio indicators. **The band boundaries in force when a report was produced shall be recorded with that report**, and the reporting layer shall additionally be able to reproduce the **legacy boundaries at 30, 45, 60, 75 and 90 days** for as long as figures are compared across the cut-over.

Data Model v2.1 §4.3 — the structural change:

> `band_set_code VARCHAR(20) NOT NULL DEFAULT 'OPERATIONAL'`, FK `ref.aging_band_set`. **ALTER the primary key from code alone to code with `band_set_code`**, so the same code may exist in two sets with different boundaries. **ALTER the non-overlap exclusion constraint to apply within a band set** rather than across all rows. [...] The design bands and the legacy reporting bands **overlap by construction**, so the existing constraint would reject the second set. **This is the one structural change in this version that is not additive**, and section 7 gives it its own migration step.

New table `ref.aging_band_set`: `band_set_code` PK, seeded `OPERATIONAL` (the design bands used by the queue) and `LEGACY_LDR` (the boundaries the existing reporting uses); `purpose` CHECK in `QUEUE, REPORTING`; `is_default_for_queue` and `is_default_for_reporting`, each exactly one true.

Case Register UC10 states the consumer-side rule: "**Every published figure names its population, its band set and its discount rate version on its face.**"

**WHAT THE PROTOTYPE MUST DO.**

1. Treat an aging bucket code as **meaningless on its own**. Every read, write, join, API filter, event payload and ledger row that carries `aging_bucket` must carry `band_set_code` beside it.
2. Key the bucket table on **(`code`, `band_set_code`)** and scope the non-overlap constraint **within a band set**. The two sets overlap on purpose; a global constraint rejects the legacy set.
3. Seed both sets: `OPERATIONAL` (0 / 1–7 / 8–29 / 30+) and `LEGACY_LDR` (30 / 45 / 60 / 75 / 90 plus the current and non-performing markers the live report uses).
4. **Stamp the band set on every produced report** alongside the population filter and the discount rate version. Runbook `RB-KPI-01` makes this a validity test: "Read the report's own face: population filter, band set, discount rate version. **If any is absent the run is void.**"
5. Order the migration correctly — the aging bucket key change (`0017_aging_band_sets`) "must precede anything that writes a band set", and the population filter (`0020`) "must exist before any indicator is re-seeded."

---

### 2.8 The board — stable column identifiers (`REQ-COL-054`)

**RULE.** What a board column is identified by, and what happens when the team set changes.

**v1.0 said.** Nothing. There is no status board in v1.0 — it "was added to the first screen on 2026-08-26". No column set, no per-officer arrangement, no identifiers.

**Current authority says** (`REQ-COL-054`, NEW, closing RA-01 — Amendment v2.4 §2):

> **A column shall carry a stable identifier that is not its name.** An officer's private arrangement is stored as a set of hidden column identifiers and, **only once that officer has reordered the board**, an explicit order of identifiers. **Until an officer reorders, no order is stored and the team order is followed**, so that a reordering by the Owner reaches every officer who has not expressed a preference of their own.

| The Owner does this | What happens to an officer's arrangement |
|:--|:--|
| Renames a column | **Nothing.** The identifier has not changed, so the column keeps its position and its hidden state, and the new name appears on it. |
| Reorders the team set | Officers who have **never** reordered follow the new order. Officers who **have** reordered keep their own. |
| Adds a column | It appears **visible**, at the position the Owner gave it, in **every** view including those with an explicit order. |
| Deletes a column | The identifier is removed from every officer's hidden set and explicit order. Nothing else moves. |

And the hazard the original options missed:

> A column may have customers on it. Deleting it would remove those customers from the board without removing them from the book. **The Owner shall be required to nominate a destination column at the moment of deletion, every customer moved shall be recorded individually in the action log, and a deletion with customers on the column and no destination nominated is refused.**

**WHAT THE PROTOTYPE MUST DO.**

1. Model a column as a **surrogate identifier plus a mutable name**. Never key anything on the name.
2. Team set owned by the Owner (`REQ-COL-051`). An officer may **hide and reorder only** — not rename, not delete, not create.
3. Store the per-officer arrangement as `{hidden: [ids], order: [ids] | null}` where **null means inherit**. Do not materialise an order on first view; only on first reorder.
4. **Refuse a deletion** that has customers on the column and no nominated destination. Write **one audit row per customer moved**.
5. **No modal.** A changed team set produces "a dismissible notice naming what changed and what it did to their view. It blocks nothing and asks nothing."
6. Log everything (`REQ-AUD-041`): every team-set change and every private arrangement change, with actor, timestamp, previous value and new value — Owner edits and officer reorders alike. Recorded verbatim from the session: "always keep action log from users."

---

### 2.9 The daily slot and the 90-second retraction (`REQ-COL-055`)

**RULE.** When a customer's one permitted counting contact per day is spent.

**v1.0 said.** The slot is consumed when the contact is logged. `TC-COL-027` shows the one nuance v1.0 had: a LINE message consumes the lock "at that moment" the read receipt returns, "not at send time". There is no board, no drag gesture, and no retraction concept.

**Current authority says** (`REQ-COL-055`, NEW, closing RA-03 — Amendment v2.4 §2):

> **The retraction window.** A counting contact begun by a direct gesture **shall not consume the customer's daily slot at the moment it is begun**. The slot is consumed at **the earlier of two events**: the officer marking that the amount owed was stated, which is the act that makes a contact counting; **or ninety seconds elapsing from the start**. Before either, the officer may retract, and the contact is recorded as a **non-counting contact attempt with the retraction logged**.
>
> **Why the loophole is closed by the same switch.** Retraction is available only while no amount has been stated. The moment the officer marks the amount as stated the contact is counting and **cannot be retracted**, so an officer cannot hold a real conversation, receive an answer they dislike, and take the slot back.

And the automatic consequence that replaced the rejected metric:

> The system shall measure the rate of contacts begun by gesture that are retracted or that expire with no outcome recorded. **Where that rate exceeds a configured threshold over a rolling week, the gesture shall cease to perform the act and the board shall become re-file-only for that team, until the Owner reviews and re-enables it.**

Paired with `REQ-COL-050` (AMENDED): a gesture that would consume the slot is preceded by a confirmation naming the customer and the cost, and "**The text of the confirmation shall state that the slot is put at stake, not that it is spent**, because under `REQ-COL-055` it is not yet spent at that moment."

**WHAT THE PROTOTYPE MUST DO.**

1. A gesture-begun contact writes a **provisional** row with a start timestamp — it does **not** take the lock.
2. Consume the slot at **`min(amount_stated_at, start + 90s)`**. Two timers, first one wins.
3. Allow retraction **only while no amount has been stated**. After amount-stated, retraction is refused. Record a retraction as a **non-counting attempt**, logged.
4. Contact record columns: provisional flag, start timestamp, and **either** an amount-stated timestamp **or** a retraction timestamp. "The daily slot is consumed by the first of those two, **not by the row existing**."
5. Implement the **auto-disable**: rolling-week rate of retracted-or-expired gesture contacts above the configured threshold → the board drops to **re-file-only for that team** until the Owner re-enables. "An accepted risk with no automatic response is an accepted risk that nobody will notice becoming real."
6. Confirmation copy says **at stake**, not spent.
7. Unchanged and still true: one officer per customer, one counting contact per customer per day. `REQ-COL-055` "changes **when** the day's contact is counted as spent, not **how many** are permitted."

**Related, and separate — blocked accounts** (`REQ-COL-052`, `REQ-COL-053`, `REQ-KPI-007` as amended by G6):

- An officer may block with a reason from a governed list; it takes effect immediately for the officer's queue and reaches the Owner's review queue the same day.
- **A pending block excludes the account from nothing.** It stays in every denominator including contact rate until the Owner approves. "An officer who blocks a difficult customer to improve a number improves no number until somebody agrees with them."
- Officer measurement runs on **two populations**, and every report and screen must state which it uses:

| Measure | Population |
|:--|:--|
| Book size, arrears, collection | Every customer assigned to the officer, whatever their state, **including blocked** |
| Contact rate, activity, promise conversion | Every customer assigned to the officer **excluding those under an approved block** |

---

### 2.10 Approval paths may not be seeded into a vacancy (`REQ-IAM-015`)

**RULE.** What happens when a role named in the approval matrix has nobody in it.

**v1.0 said.** Nothing — the baseline stops at `REQ-IAM-014`. v1.0 assumed three Debt Managers (`A-02`) and seeded `modification_approval_route` rows naming `DEBT_MANAGER` with no check that anyone holds the post. The v1.0 repo names the Debt Manager as owner of at least six open decisions.

**Current authority says** (`REQ-IAM-015`, PRD v2.1, NEW):

> **Every approval authority in the modification matrix shall resolve to at least one named person currently in post.** Where a role named in the matrix is vacant, the configuration **shall not silently fall back**: the system shall **refuse to seed that approval path**, list the affected modification types and requirements on the configuration screen, and require the Owner either to appoint a holder or to **reassign the authority explicitly with a recorded reason and an end date**.

Its note closes the question for launch:

> NEW, and satisfied at launch by decision D2 rather than left to bite. **The manager role that holds most approvals, including the sole authority to flag a loan non-performing, is vacant. The Owner absorbs every route it holds as one acting reassignment with a recorded reason and a review date**, which is the second of the two paths this requirement allows. OQ-15 is closed. **The review date is the point: it makes the arrangement expire rather than harden.**

Supporting: `REQ-MOD-002` — "The matrix names a Debt Manager for most approvals and **that role is currently vacant**." Data Model v2.1 on D2 — "`iam.authority_reassignment` holds **one row covering the vacant role**, and the editor column on **six configuration values** now reads `OWNER acting for DEBT_MANAGER` so that the arrangement is visible where it bites rather than only in the identity tables." Runbook Alignment §2 on D2 — "The book names the Debt Manager in **more than forty places** across its three parts. Until the post is filled, every one of those is the Owner. **An escalation to a vacant post is an escalation to nobody, and the failure is silent.**"

**WHAT THE PROTOTYPE MUST DO.**

1. **Fail seeding loudly.** Refuse to seed any approval route whose role has no holder in post. No silent fallback, no default-to-Owner, no orphaned route.
2. Surface the refusal on the configuration screen as a **list of affected modification types and requirements**.
3. Accept exactly two remedies: appoint a holder, **or** an explicit reassignment carrying a **recorded reason and an end date**.
4. Seed the launch state: **one `authority_reassignment` row** giving the Owner every `DEBT_MANAGER` route, with reason and review date. The end date is load-bearing — without it the arrangement hardens.
5. Render the acting arrangement **where it bites**: six configuration values read `OWNER acting for DEBT_MANAGER`, not only the identity tables.
6. Anywhere the prototype hard-codes "Debt Manager" as an approver or escalation target, resolve it through the reassignment. **In the current org that is the Owner, every time.**

---

## 3. Traps, contradictions and stale text

### 3.1 "Six states pause the fee" is wrong — it is five

Grilling Session Record §7 opens "**Six** states pause the fee and two deliberately do not", and Runbook Alignment v2.3 §3.3 repeats "**Six** states now stop the fee and two deliberately do not." Both then print a **seven-row** table in which **five** rows stop the fee and **two** do not.

The count is stale: it was written when G9 still paused the fee on dispute, and **G13 reversed that** later in the same session. Amendment v2.4 — the highest authority — states no count at all and prints the same seven rows.

**Prototype: five pausing states. Trust the table, not the sentence.**

### 3.2 PRD v2.1 still says a permit hold accrues penalty

PRD v2.1, in the `REQ-COL-047` exposure note, says of a permit-delayed contract that it "keeps accruing days past due **and keeps accruing penalty**, because the delay no longer excuses the debt."

That is pre-G7 text. PRD v2.1 is dated **2026-08-25**; G7 was taken **2026-08-26** and `REQ-MNY-032` now says the permit hold **stops the fee**. The amendment wins.

**Prototype: permit hold → clock runs, fee stops.** Expect the same stale claim anywhere else PRD v2.1 or Data Model v2.1 discusses permit-hold exposure.

### 3.3 The amendment's data-model consequences exist nowhere yet

Data Model v2.1 is dated **2026-08-25** and therefore **pre-dates every G-decision**. Verified by search: the words `retraction`, `retract`, `pause` and `fee_paused` appear **zero** times in it, and it has no board, column-set or per-officer-arrangement tables.

So all five data-model consequences in Amendment v2.4 §3 are **specified but unimplemented in any published schema**. The prototype is the first place they exist:

| Area | Change required | From |
|:--|:--|:--|
| Hold and flag states | A single governed table of states carrying **two independent booleans** — stops the clock, stops the fee — **replacing the current single freeze attribute** | `REQ-MNY-032` |
| Daily ledger row | A paused day carries **the state that paused it**, alongside the existing frozen-day marker. **Two different columns because they are different facts** | `REQ-MNY-032` |
| Reversal entry | An **effective date** attribute distinct from the posting date, and a flag recording whether the reversal **restated rows or posted forward** | `REQ-MNY-035` |
| Board configuration | Team column set with **surrogate identifier + mutable name**; per-officer arrangement with hidden-id set and **nullable** explicit order (null = inherit); deletion requires a destination id and produces **one audit row per customer moved** | `REQ-COL-051`, `REQ-COL-054` |
| Contact record | Provisional flag, start timestamp, and **either** an amount-stated timestamp **or** a retraction timestamp | `REQ-COL-055` |

### 3.4 Data Model v2.1 contradicts itself on the restriction switch

See §2.4. §3.4.1 prose says the feature ships behind a switch that is off; the decisions table and PRD `REQ-MOD-029` both say it ships on. **Ships on.**

### 3.5 `REQ-MNY-018` renumbering

See §2.1. The amendment overwrites the grace-period requirement with a labelling requirement. Implement both; raise with Arina.

---

## 4. Values that are configuration, not code

Do not hard-code these. Every one is expected to move.

| Value | Current | Owner |
|:--|:--|:--|
| Retraction window | **90 seconds** — "a number to tune rather than a question to answer" | Collections, review after first month live |
| Gesture auto-disable threshold | Unset. "The threshold is configuration and its initial value is an open question for Collections, **but the mechanism is not**" | Collections |
| `power_restoration_cutoff_time` | **15:00** Asia/Bangkok, stored as a **time**, read with the holiday table | Owner, acting for Debt Manager |
| `power_restoration_basis` | `SAME_BUSINESS_DAY_BEFORE_CUTOFF` (replaces the withdrawn `power_restoration_sla_hours`) | Owner, acting for Debt Manager |
| `power_restriction_enabled` | **true** | Owner with Legal |
| `default_population_filter` | **null, deliberately unset** — "no dashboard may display an indicator until it is answered" (`REQ-KPI-015`) | Owner |
| Late fee rate and grace period | **Both unsettled** under `A-03`. Grace has three live values: 0 / 11 / 14 | Owner with Legal and Accounting |
| Fee state table | All **seven rows** seeded and one `fee-state-check` run with zero exceptions, before go-live | Arina, signed by Accounting |

## 5. Assumptions that did not move

Load-bearing, and unchanged:

- **`A-08`** — a payment is real when the accounting system confirms it. A slip is evidence of an attempt, not of receipt. Load-bearing for `REQ-MNY-034` and for the restoration trigger.
- **`A-11`** — no customer portal in this phase.
- Money rows are **append-only** and corrections are reversals — with the open-period boundary of `REQ-MNY-035` as its **one** qualification.
- One officer per customer; one counting contact per customer per day.
- `D13` as to the **clock** — a permit hold does not stop it. Only the fee half was amended.
