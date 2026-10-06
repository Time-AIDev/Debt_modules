# Workflow authority — VOLT ERP SPV/EPC Scenario Workflows v20.0

| | |
| :-- | :-- |
| Document | Repo-local extraction of the deck "VOLT ERP — SPV/EPC Scenario Workflows v20.0", so nobody needs the deck open to build |
| Date | 2026-08-30 |
| Author | Arina (arina.j@volt.co.th) |
| Status | Extract, not a new contract — where this brief and the deck disagree, the deck wins |
| Source | Google Slides `1s0Pfc8YMbBrw2Pklu37rngCPsZFVyJybNTtYEYqvxyo`, v20.0 |
| Read with | `docs/product/user-journey.md` (the operational journey), `docs/product/spec-deltas-v25-rebuild.md` (what this forces on the spec line) |

## 0. The two version lines and the authority ladder

The deck lives on its **own version line** — scenario workflows v9 → v20 (change notes survive at v9.0, v10.0, v11.0, v17.0, v19.0, v20.0). The spec line runs v1.0 → PRD v2.1 → Amendment v2.4 → Amendment v2.5. **A larger number on one line says nothing about the other.** Never cite "v20" as if it superseded "v2.4" numerically; it supersedes it only where the ladder below says so.

| Rank | Document | Authority |
| :-- | :-- | :-- |
| 1 | Requirements Amendment v2.5 (rebuild) | Highest, for what it names only |
| 2 | Deck "VOLT ERP — SPV/EPC Scenario Workflows v20.0" | Final authority on scenario workflows 1–12. Its version line (v9→v20) is separate from the spec line (v1.0→v2.x); a larger number on one line says nothing about the other. Where it conflicts with requirement text below and v2.5 has not yet named the conflict, the scenario shape wins and the gap is raised for the next amendment |
| 3 | Requirements Amendment v2.4 | For what it names and nothing above touches |
| 4 | Grilling Session Records (2026-08-30 rebuild; 2026-08-26) | The why, not the what |
| 5 | Case Register v1.3, Runbook Alignment v2.4 | Downstream applications of the decisions |
| 6 | PRD v2.1, Data Model v2.1 + v2.2 delta | Authority for everything not named above |
| 7 | Local repo v1.0 | Baseline, in force only where nothing above touches it |

## 1. The frame — one contract, two entities, prepaid service

Headline facts, stated once on the deck's title slide and never contradicted inside it:

- **12 flows** · acquisition at **100% of customer NPV** · months 1 to 36 of service **PRE-PAID inside the sale price** · **one cash format only** · service billed on the **25th to 30th** · live by **end of September 2026**.
- **THE CONTRACT RULE** — one sale contract per customer, and 36 months of service already inside the price. LEASE customer: the lease, **with SPV, always**. CASH customer: the sale contract, **with EPC**. **SPV never appears on a cash order at all.**
- **Months 1–36**: service is ALREADY PAID FOR — the 36 months of O&M are priced INTO the cash sellout price and into the lease NPV **before anything is quoted**, so nobody is invoiced again — not the customer, not SPV. Prepaid, not a giveaway: EPC is not carrying it.
- **Month 37 onward**: the prepaid window ends and service costs **THB 399+ per system per month** on a contract with EPC, billed on the **25th to 30th** of each month. EPC is the service entity for the end customer either way.
- **CASH — ONE FORMAT ONLY** (Win, 26 Aug): a deposit **from THB 5,000, scaling upward with system size**, then instalment 2 for the **WHOLE remaining balance**. Split payments are dropped: **Cash 2 and Cash 3 (with its 5% surcharge) are retired** — and must come OUT of Debt spec §5.2. Any month-37 service contract is cancelled if the sale contract ends early, by settlement or by NPL.
- Every customer invoice is issued by **PEAK with its own QR code and is paid by QR only, never by bank transfer**. No service is billed at all in months 1–36. Any month-37 EPC→SPV service fee would be ONE bulk invoice a month, raised manually — never auto-generated per system.
- Consolidation between EPC and SPV is manual. The THB 50,000 accounting fee is a one-off, raised by manual invoice **outside the ERP**.

### 1.1 The two entities

**EPC — the operating company.** Owns the CASH customer end to end, and is the service entity for every customer, cash and lease alike. Sells each lease project to SPV at 100% of customer NPV, then installs and runs O&M for it. Carries 36 months of O&M already priced into the sale, then bills THB 399+ per month from month 37. On NPL takes the lease contract back, pays SPV 100% of the remaining NPV, then repossesses and redeploys the asset.

**SPV — the financing vehicle.** Lessor of record — underwrites the credit, holds the receivable and owns the asset while the lease performs. Buys each project from EPC at 100% of customer NPV; no separate install-service payment. Has no employees — EPC services every lease on its instruction and is paid nothing for it in months 1–36. On NPL assigns the contract back to EPC, is repaid the remaining NPV in full and exits with no further exposure.

### 1.2 Commercial terms

| Term | Value |
| :-- | :-- |
| Project acquisition | SPV buys the project from EPC at **100% of customer NPV** (was 85%, changed 25 Aug) |
| Service fee | Months 1–36 PRE-PAID inside the sale price; from month 37: **THB 399+ per system per month**, billed 25th–30th |
| Accounting fee | **THB 50,000 flat, once** — EPC invoices SPV, money moves SPV → EPC; manual, outside the ERP |
| NPL buyback | EPC pays SPV **100% of remaining NPV**, executed only after **120 days past due** |
| Uninstall / decommissioning fee | **THB 5 per watt**, billed to the customer; removal fee and uninstall fee are the same fee |

### 1.3 System architecture (deck slide 2)

Odoo Community (single operational DB: CRM · OPS/Field Service · SCM) → **Debt module, built external** (DEBT Cash = EPC receivables; DEBT Lease = SPV receivables) → **PEAK, book of record, two separate instances** (PEAK Cash = EPC statutory books; PEAK Lease = SPV statutory books; Thai e-Tax, WHT, PND, VAT), linked by API in both directions. Odoo holds no accounting — PEAK is the book of record for both entities. The Debt module feeds both PEAK instances; **each document is routed on `company_id`**, so the routing rule is one field, not a set of conditions.

## 2. The 12 scenarios

| # | Scenario | Owner | One line |
| :-- | :-- | :-- | :-- |
| S01 | CASH ORDER | EPC only | One sale contract with EPC · 36 months of service inside the price · ONE cash format: deposit from 5,000, then the whole balance |
| S02 | LEASE ORDER | SPV lease · EPC service | Lease signed with SPV · SPV buys the project at 100% of customer NPV · 36 months of service priced into the NPV |
| S03 | CANCEL BEFORE INSTALL — CAUSE: CUSTOMER | Money forfeited | Customer's change of mind = breach: EPC keeps the deposit, SPV keeps instalment 1 |
| S04 | CANCELLATION — AFTER INSTALLATION | Settle or NPL | Not a cancellation — settle (CLOSED) or stop paying (NPL → S07); any month-37 service contract is cancelled with it |
| S05 | CANCEL BEFORE INSTALL — CAUSE: VOLT | Full refund | 60-day SLA breach, or a survey-approved site that cannot be installed: 100% refund, weekly batch |
| S06 | CANNOT INSTALL — RE-QUOTE & RE-SIGN | Two parallel tracks | Contract re-issued against the revised package; acquisition re-prices at 100% of the NEW customer NPV |
| S07 | NPL — CONTRACT ASSIGNED BACK TO EPC | EPC executes everything | 30/60/90/120-day ladder — restructure offered at 60, NPL declared at 90, contract assigned at 120 against 100% of remaining NPV · only missed LEASE instalments count |
| S08 | LEASE RESTRUCTURE | SPV, with an NPL exit | Entered at 60 days, BEFORE NPL · two missed payments on the new schedule declares NPL immediately |
| S09 | SERVICE ORDER FLOW | EPC only | Months 1–36 prepaid, so nobody is billed · from month 37 THB 399+ per system per month, billed 25th–30th |
| S10 | INVOICE & MONEY FLOW | EPC ⇄ SPV ⇄ customer | Every document that moves between the three parties: who invoices whom, on what basis, when, with which tax, into which books |
| S11 | CASH DEFAULT — BALANCE NOT PAID | EPC only | Cash customer who does not pay the WHOLE remaining balance after installation · 30/60/90 ladder → legal claim or removal (S12) |
| S12 | REPOSSESSION & REDEPLOYMENT | EPC only | Removal, grading, repricing, Dan's manual resale price · serials live only in the PDF, so resale runs on a COUNT at removal |

### S01 · Cash order — EPC owns the cash customer end to end

Sequence: `[CONFIG]` sellout price (cash version, Management) → `[CASE]` lead qualified → `[OFFER]` package + price (margin = sellout − EPC cost) → `[CONTRACT]` sale contract signed with EPC (signature before payment; 36 months of O&M inside this price) → `[SURVEY]` evidence captured, minimum feasibility → `[CONTRACT]` evidence accepted, site confirmed installable → `[CASH/AR]` **deposit received** (from THB 5,000, scaling with system size — received by EPC; the deposit triggers the work) → `[MATERIAL]` crew + stock planned → `[PROJECT]` installed + QC passed → `[HANDOVER]` customer accepted (utility coordination completed) → `[CASH/AR]` **balance invoiced** (the WHOLE remaining balance = sellout − deposit) → `[CASH/AR]` payment settled in full by EPC → `[CONTRACT]` sale contract closed; the prepaid 36 months run on → S09. If the balance is not paid after handover, the case moves to **S11**. SPV does not appear anywhere in this track — no project order, no acquisition price, no accounting fee.

### S02 · Lease order — lease with SPV, 36 months of O&M priced into the NPV

Customer: enquiry → submits application → **signs LEASE contract with SPV** → free service starts (36 months, no contract — with EPC) → pays instalment 1 → accepts handover → pays instalments 2–60 (+ the EPC service invoice from month 37).
SPV: `[CONFIG]` sellout price (lease version, customer NPV basis) → `[FINANCING CASE]` submitted → `[CREDIT]` approved (down payment tier 0–30%) → `[CONTRACT]` lease effective (**always with SPV**) → `[RECEIVABLE]` schedule active (60 instalments, starts pre-install) → `[PROJECT ORDER]` placed to EPC (**triggered by instalment 1 — this is the IC step**) → `[ACQUISITION]` system accepted + paid (**100% of customer NPV, no install-service line**) → `[RECEIVABLE]` performing cycle (instalments 2–60) → `[CONTRACT]` lease closed (all 60 paid · status closed, not cancelled; any month-37 service continues).
EPC: `[CONFIG]` project cost + acquisition price (sold to SPV at 100% of customer NPV) → `[GUARANTEE]` buyback undertaking issued (on NPL EPC repurchases at 100% of remaining NPV) → `[SERVICE]` 36 months prepaid inside the NPV, charged only from month 37 → survey → project order confirmed (acquisition price snapshot; **no asset assigned until paid**) → install + QC + handover → `[INVOICE]` project sold to SPV (100% of customer NPV, single line) → `[SERVICE]` O&M runs continuously; billing starts at month 37 → S09.

### S03 · Cancellation before installation — cause: the customer (money forfeited)

The cause test is the FIRST step: customer → forfeit, stay here; VOLT → full refund, S05. Lease: lease terminated (cause: customer), project order cancelled **before any acquisition is paid** (no asset assigned, nothing settles between SPV and EPC), instalment 1 forfeited — logged as revenue. Cash: product contract terminated, materials returned to stock, deposit forfeited — recognised as EPC revenue. The free service never starts: no contract exists in the free period, so there is nothing to cancel or bill.

### S04 · Cancellation — after installation (settle CLOSED, or stop paying → NPL)

Once installed there is no cancellation any more. Pay the settlement amount (remaining NPV + arrears and fees) and the contract is **CLOSED, not cancelled** — the asset transfers to the customer. Stop paying and the NPL ladder (S07) starts. In BOTH outcomes any PAID service contract goes with it — but before month 37 there is none to cancel; the free service simply stops (re-buy under S09). CASH: possession passes at handover, title only on full payment — an unpaid balance is **S11, not a cancellation**.

### S05 · Cancellation before installation — cause: VOLT (full refund)

Two triggers: the **60-day SLA** passes without installation, or the site turns out not to be installable **although our own survey approved it**. Cash: EPC refunds the deposit 100%. Lease: SPV refunds instalment 1 100%. Refund paid in the **weekly batch, 7 business days**. Same moment as S03 — only the cause, and therefore who keeps the money, differs.

### S06 · Cannot install — re-quote & re-sign

The site cannot take the original package but the customer accepts a revised one. **No refund** — money already paid is carried over to the new order and the difference adjusted. The contract is re-issued against the revised package. Cash rejoins S01. Lease rejoins S02 with the acquisition re-priced at **100% of the NEW customer NPV** (the replacement project order cancels & replaces the old). The 36 free months restart from the new handover.

### S07 · NPL — lease contract assigned back to EPC (LEASE customers only)

The ladder: **30 days** = 1 instalment missed → notice and cure. **60 days** = 2 instalments missed → a restructure is **OFFERED** (S08). **90 days** = restructure refused, unanswered or failed → **NPL is DECLARED — risk and provisioning only, the contract is not moved yet**. **120 days** = the customer still has not paid → only NOW is the assignment deed executed: lease contract + asset assigned back to EPC against **100% of the remaining NPV** (no discount, not 90%). The month-4 window exists on purpose: the customer may still come back and pay.

**Only missed LEASE instalments count towards this ladder** — service-fee arrears are a separate EPC receivable with their own dunning and **never trigger NPL**. A CASH customer who stops paying goes to S11.

After assignment, EPC executes everything: recovery case opened (feasibility informs the disposition, not whether to remove), removal authorised and proceeds in all cases, custody + transport (ownership already sits with EPC), uninstall fee THB 5/watt billed to the customer, late fees + outstanding rates collected by EPC, repossession + redeployment → S12, resale as an EPC cash sale priced by Dan → S01. Any month-37 service contract is cancelled with the lease at assignment. SPV exits: receivable derecognised, no further exposure.

### S08 · Lease restructure — entered at 60 days, before NPL

SPV re-profiles the lease onto a new schedule instead of assigning it back. `[COLLECTION]` restructure offered at 60 days past due → `[RECOVERY CASE]` assessed (affordability + eligibility; refused or unanswered → back to S07) → `[RISK]` approved (extend term / lower instalment / payment holiday) → `[CONTRACT]` lease addendum (new schedule supersedes old; lease stays with SPV) → `[RECEIVABLE]` re-profiled (net investment re-aged, ECL updated) → performing again. EPC keeps servicing exactly as before, no asset is removed, and the buyback undertaking is **re-based to the new schedule** (100% of remaining NPV). **If the customer accepts and then misses two instalments on the NEW schedule, NPL is declared straight away — no second restructure** → S07.

### S09 · Service order flow — 36 months prepaid, then THB 399+ a month

Months 1–36: ALREADY PAID FOR — priced into the cash sellout and the lease NPV before the quote; nobody is invoiced in that window; no service fee is charged to SPV. From month 37: a service contract with EPC, **OPTIONAL — whether the customer may decline is the one item still open (Jo to settle; register entry SVC-37; the deck bills 399 from month 37 either way)**. `[CONFIG]` service price from THB 399 per system per month, scales with system/panel size. `[INVOICE]` PEAK issues it with its own QR code, QR payment only. `[INVOICE]` bulk to SPV — MANUAL: month 37+, raised 25th–30th by hand, ONE document, every active system, **3% WHT**, never auto-generated. `[COLLECTION]` separate EPC dunning — service arrears are chased by EPC alone and **NEVER feed the lease NPL ladder**. Standalone service is sold as its own product (a customer whose contract ended early can re-buy). Renewal on the same terms; cancelled if the sale contract ends early.

### S10 · Invoice & money flow — the document ledger

DIRECTION is the DOCUMENT direction — who issues to whom; money moves the other way on every invoice. EPC books into DEBT Cash → PEAK Cash; SPV books into DEBT Lease → PEAK Lease. No service is billed between the entities before month 37.

| # | From → To | Document | Amount / basis | When | Tax | Booked in |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 1 | SPV → Customer | Lease instalment invoice — PEAK, QR | Per schedule, from customer NPV | Monthly, instalments 1–60 · QR only | VAT · e-Tax by SPV | DEBT Lease → PEAK Lease |
| 2 | EPC → Customer | Cash order invoice — PEAK, QR | Deposit from THB 5,000, then the whole remaining balance | At deposit and at handover · QR only | VAT · e-Tax by EPC | DEBT Cash → PEAK Cash |
| 3 | EPC → SPV | Project sale invoice | 100% of customer NPV, single line | Once, on system acceptance | VAT · e-Tax | PEAK Cash out · PEAK Lease in |
| 4 | SPV → EPC | Payment of the project invoice | Same amount | On acceptance | — | Both PEAK instances |
| 5 | EPC → SPV | Accounting fee invoice · SPV pays | THB 50,000 flat | Once — the only standing inter-company fee | VAT | **Manual — outside the ERP** |
| 6 | EPC → Customer | Service invoice — PEAK, QR | From THB 399/month, scales with size | Month 37 onward, raised 25th–30th | VAT · e-Tax by EPC | DEBT Cash → PEAK Cash |
| 7 | SPV → EPC | Assignment deed | Lease contract + asset | After 120 days past due | — | Legal · both books |
| 8 | EPC → SPV | NPL buyback payment | 100% of remaining NPV — no discount | After 120 days, against the deed | — | Both PEAK instances |
| 9 | EPC → Customer | Uninstall / decommissioning invoice | THB 5 per watt | After a lease NPL (S07) or cash default (S11) | VAT · e-Tax by EPC | DEBT Cash → PEAK Cash |
| 10 | EPC → Customer | Late fees + outstanding rates / balance | Per the assigned lease, or the unpaid cash balance | After S07 or S11 | VAT · e-Tax by EPC | DEBT Cash → PEAK Cash |
| 11 | SPV → Customer | Refund — cause VOLT | 100% of instalment 1 | S05, weekly batch | Credit note | DEBT Lease → PEAK Lease |
| 12 | EPC → Customer | Refund — cause VOLT | 100% of the deposit | S05, weekly batch | Credit note | DEBT Cash → PEAK Cash |
| 13 | EPC → Customer | Service arrears — separate EPC collection | Overdue service invoices only | Own dunning — never part of the lease NPL ladder | — | DEBT Cash → PEAK Cash |

### S11 · Cash default — balance not paid after installation (CASH customers only)

The system is on the roof and the balance is not paid — EPC's real cash exposure. **No SPV leg**: EPC owns the contract, the receivable and the asset, so there is no assignment deed, no buyback, no remaining NPV to settle. Ladder mirrors the lease: **30 days** notice + cure → **60 days** settlement plan offered (instalment plan on the outstanding balance) → **90 days** default confirmed (plan refused, unanswered or failed). From there: **PATH A** legal claim for the balance, or **PATH B** removal when recovery beats litigation — the removal runs as S12. Title stays with EPC until paid in full. Uninstall fee THB 5/watt (same single fee as S07). SETTLED in v20.0: cash has ONE format, so the only thing that can go unpaid here is the single closing payment.

### S12 · Repossession & redeployment — the loop that has to be CUT, not closed

Serials live only inside the signed installation report PDF, never as data in Odoo (CF5) — so a removed system cannot be matched unit-by-unit against what was installed. **THE CUT: resale needs a COUNT at removal, a grade, a price and a shelf of its own.** The link back to the original contract sits on the lot for audit only; nothing downstream waits on it.

Sequence: `[WORK ORDER]` removal scheduled (the signed installation report is pulled first — the only record of what went in) → `[SITE]` disconnect + isolate → `[CUSTODY]` **lot opened, EXPECTED vs ACTUAL** (e.g. RP-2026-0148; EXPECTED typed off the report, ACTUAL counted on site; a variance needs a reason and a photo) → `[CASH/AR]` uninstall fee THB 5/watt → `[INSPECTION]` condition grading **A / B / C** per component, photographic record, grades may differ inside one lot → `[MATERIAL]` grades A and B refurbished, **grade C scrapped and written off** (never returns to sellable stock) → `[ASSET]` derecognised from the lease — off the register and into stock at written-down value (an inventory adjustment, NOT a purchase order) → `[DEBT MODULE]` repriced; **recovery value goes BACK to the collection case to offset the balance**; deficiency follows Legal → `[SCM]` received but **NOT SELLABLE** until a price exists. Three rules: (1) its own PRODUCT CODE — `PANEL-550-R`, never `PANEL-550` (a shared code blends refurb cost into new stock); (2) its own STOCK LOCATION — `WH/REFURB`, a separate Odoo location and physical shelf (a new order can never pull from it); (3) the LOT carries history (origin contract, removal date, site, grade, written-down value — audit only). → `[PRICING]` **Dan prices for resale, MANUAL** — a task lands on Dan with the grading photos and the written-down value; **saving a price unblocks the stock** → `[NOTIFY]` not by serial — CRM/Sales just see on-hand qty of the refurb product; Dan gets a task, Debt an API call → `[OFFER]` refurbished package sold (quote must SAY refurbished, own shorter warranty — no manufacturer claim without a serial) → rejoins S01.

Still to decide (deck): cash-only resale until Jo rules on whether SPV will finance a used asset at 100% of NPV.

## 3. Conflicts with the v1.0 extracts in this repo

| Where | The extract says | Deck v20.0 says |
| :-- | :-- | :-- |
| `spec-money-engine.md` §2.6 (cash plans, REQ-MNY-006) | Cash 1/2/3 plans, Cash 3 with a 5% surcharge | ONE cash format: deposit ≥ THB 5,000 + whole balance. **Cash 2 and Cash 3 are retired and come OUT of Debt spec §5.2** |
| Any NPV figure of 85% | Acquisition at 85% of customer NPV | **100% of customer NPV** (changed 25 Aug) |
| `spec-money-engine.md` §6 / band tables | Aging buckets are the only day-structure | The **NPL ladder 30/60/90/120 is a different instrument** from aging bands — see `spec-deltas-v25-rebuild.md` §2 |
| v1.0 spec generally | No cash-default flow after installation | **S11** exists; ladder 30/60/90 → legal or removal |
| v1.0 spec generally | No service-billing shape | **S09**: months 1–36 prepaid; month 37+ THB 399+, billed 25th–30th, QR-only, own dunning, never feeds lease NPL |

## 4. Open decisions carried by this brief

| Code | Question | Owner | State |
| :-- | :-- | :-- | :-- |
| SVC-37 | May the customer decline the month-37 service contract? The deck bills 399 either way; what is open is whether they may refuse. It matters on a LEASE, where the asset is SPV's until month 60 | Jo | OPEN — billed either way meanwhile (R1) |
| OD-04 | `npl_dpd_threshold_days` — the deck's 90-day declaration is recorded as the indicative source; NPL is never automatic, a human flags | Whan | OPEN — ladder shown, declaration manual (R6) |
| — | Cash-only resale of refurbished assets until Jo rules on SPV financing a used asset at 100% NPV | Jo | OPEN (deck S12) |

## 5. What the rebuild must do

1. Route every receivable, invoice and case on `entity` (EPC/SPV) + `company_id`; SPV never appears on a cash order.
2. Implement the lease ladder S07 (30/60/90/120, restructure offered at 60, human declaration at 90, deed at 120 with 100%-NPV buyback and service cancellation) and the cash ladder S11 (30/60/90 → legal or removal).
3. Implement S08 restructure as a superseding schedule the money engine follows; two missed on the new schedule locks the case to NPL.
4. Implement S09 service billing (prepaid window, month-37 counter, 399 floor, 25th–30th window, QR-only, own dunning, isolation from lease NPL).
5. Implement S12 repossession as count-based lots (expected vs actual, A/B/C grades, `PANEL-550-R` @ `WH/REFURB`, Dan's price unblocks stock, recovery value offsets the case).
6. Record every S10 inter-company document; refuse to post the THB 50,000 fee (manual, outside the ERP).
7. Retire Cash 2/Cash 3 everywhere; keep S03/S05/S06 cancellation splits on the cause test.
