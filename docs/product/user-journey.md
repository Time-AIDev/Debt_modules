# The Debt-team user journey

| | |
| :-- | :-- |
| Document | The Debt team's operational journey, extracted from the six Thai flow diagrams in `docs/assets/SOP/`, mapped to the deck's 12 scenarios and to the rebuilt screen set. This document did not exist before 2026-08-30 — no persona or journey document existed anywhere in the set |
| Date | 2026-08-30 |
| Author | Arina (arina.j@volt.co.th) |
| Status | Extract of the diagrams + the R9–R12 grilling decisions; where this brief and the diagrams disagree, the diagrams win |
| Sources | `docs/assets/SOP/00-debt-flow-full-end-to-end.png` and parts 1–4; Grilling Session Record 2026-08-30 (R9–R12) |
| Read with | `docs/product/workflow-v20-epc-spv.md` (the commercial shape this journey collects for) |

## 0. Lanes and roles

The diagrams draw the journey in lanes. The people:

| Lane | Role in the journey |
| :-- | :-- |
| Sales / EPC | Pre-installation: down-payment gate, install-date confirmation, install-plan updates |
| AR (Accounting/Receivable) | Verifies and issues invoices, matches receipts, records partial payments, issues receipts, rolls status Current/Paid |
| Collection (the debt officers — "Nok") | Sends invoices to customers, notifies amount + due date, builds and works the overdue working list, calls/LINEs, records contact results and next actions |
| CS / O&M / Operations | Owns routed service issues until resolved |
| Manager | Reviews escalations, decides the Part-4 path |
| Credit & Risk | Verifies the account, assesses DPD / PTP history / payment history / service issues, confirms NPL status |
| Legal / Ops / SCM | Executes recovery: legal claims, removal, equipment return |

## 1. The journey, stage by stage

### Part 1 — Sales / EPC / AR invoice pipeline

Down-payment gate → EPC confirmation → invoice issue → installation check.

1. Sales / pre-installation: **has the customer paid the down payment?** Not yet → stay in pre-installation. Paid → next gate.
2. **Has EPC confirmed the installation date?** Not yet → wait in the Operations pipeline. Confirmed → send into the **AR invoice pipeline**.
3. AR verifies and **issues the invoice** → Collection **sends the invoice to the customer** → Collection **notifies the amount and the payment due date**.
4. **Installed on schedule?** Postponed/cancelled → EPC updates the install plan → AR reviews the original invoice → back through the pipeline. On schedule → Part 2.

### Part 2 — Payment / overdue / collection follow-up

**Has the customer paid?**

- **Paid in full** → AR verifies and **matches the money received** → AR issues the receipt → status **Current / Paid** → enters the next invoice cycle (the loop back to Part 1).
- **Paid partially** → AR records the **partial payment** → Collection **follows up the remaining balance** → joins the call/LINE follow-up below.
- **Not paid** → enters **Overdue Collection** → Collection **builds and assigns the Working List** → the officer **reviews the customer's data and history** → **calls / LINEs the customer** → **records the Contact Result and the Next Action** → Part 3.

### Part 3 — Contact-result branches

The contact result (ผลการติดตาม) branches four ways:

- **ลูกค้านัดชำระ — PTP.** Record **PTP date and PTP amount**. On the promised day: paid in full → back to AR receipt-matching; paid partially → AR records partial; **not paid → record Broken PTP → send to Manager Review**.
- **แจ้งปัญหาบริการ — service issue.** Route to **CS / O&M / Operations** → track the **owner and the fix status**. Resolved → back to call/LINE follow-up. Not yet → keep following the owner.
- **ติดต่อไม่ได้ — no contact.** Try further rounds and other channels → coordinate **Sales / CS / field team**. Reached → back to call/LINE. Still unreachable → **Manager Review**.
- **ปฏิเสธชำระ / ไม่มีข้อยุติ — refuses to pay / no agreement** → straight to **Manager Review**.

**Manager Review** → **Credit & Risk verifies the account** → assessment of **DPD / PTP record / payment history / service issues** → Part 4.

### Part 4 — Credit & Risk decision / NPL / recovery / closure

The decision (กำหนดแนวทางดำเนินการ) has four paths:

1. **ติดตามต่อ — continue following up** → back to the Working List.
2. **Repayment arrangement** — negotiate and draw up a payment plan. Customer complies → AR matches the money. Customer breaks the plan → back to **Manager Review**.
3. **Restructure** — propose and seek approval → draw up the new agreement and the **new payment schedule** → rejoins the invoice cycle.
4. **Confirm NPL** — update the status to NPL → choose a **Recovery Strategy**:
   - **Legal**: assemble documents → track the legal outcome.
   - **Repossession / Recovery**: remove the system → track the results.
   - **Cooperative decommission**: receive the equipment back → update the balance.
   - **External collection**: hand the account to an outside collector → track recovery amounts.

Then: **track the results and the recovery amounts** → **does the account have a resolution?** → **Outcome: Full Payment / Partial / No conclusion / Closed** → **Closed / Write-off when the account closure is approved**. No resolution yet → keep tracking (and the AR verify/receipt loop stays available if money arrives).

## 2. Mapping — journey stage → deck scenario → screen

| Journey stage | Deck scenario(s) | Rebuilt screen |
| :-- | :-- | :-- |
| Down-payment gate, EPC confirm, invoice issue | S01, S02 | `/ar` AR pipeline (invoice states) + Orders |
| Send invoice, notify amount/due date | S10 (docs 1, 2, 6) | AR pipeline + Customer 360 timeline |
| Receipt matching, partial payments | S01/S02 performing | AR pipeline + Customer 360 timeline |
| Overdue working list, assigned, prioritized | S07/S11 entry | `/` My Day (hero card + tiered queue, R9–R11) |
| Call / LINE, record contact result | Act rules (daily slot) | ContactDrawer (โทร + LINE actions, R12) |
| PTP recorded / kept / broken | — | ContactDrawer capture + `/queues` PTP tabs |
| Service issue routed, owner tracked | S09 boundary | ContactDrawer routing + `/queues` service tab |
| No contact, escalation | — | `/queues` no-contact tab |
| Manager review + Credit & Risk evidence | S07 60→90 gate | `/review` |
| Repayment arrangement | — | `/review` decision + arrangement plan |
| Restructure → new schedule | **S08** | `/review` decision → case detail |
| Confirm NPL → recovery strategies | **S07**, S12 | `/npl` workspace |
| Cash balance unpaid → legal/removal | **S11** | `/cash-defaults` ladder |
| Month-37 service receivable, own dunning | **S09** | `/service-billing` |
| Repossession lot → count/grade/price | **S12** | `/npl` lot panel |
| Outcome / Closed / Write-off | S04, S07, S11 | `/npl` outcome + Customer 360 |

## 3. Where the Debt Collection Act bites in this journey

From the standing collection law (Amendment v2.4, unchanged by the rebuild):

- **One counting contact per customer per day.** Stating the amount owed is what makes a call count. The drawer's counting dispositions carry the cost on the option itself; a gesture-begun contact is provisional for 90 seconds unless an amount is stated (REQ-COL-055 — "at stake, not spent").
- **The lock is per person** (PERSON level enforced), the day boundary is Asia/Bangkok, inbound never consumes the slot, SMS/email never count, LINE counts at read time.
- **Blocked accounts** follow G5/G6/G10: governed reasons, Owner review, counted for arrears but excluded from the contact-rate denominator only once approved.
- Service-fee dunning is EPC's own and **never feeds the lease NPL ladder** (deck S09) — the journey's manager-review evidence panel shows service issues as context, not as arrears.

## 4. What the journey does NOT decide

- Whether the month-37 customer may decline service (SVC-37, Jo) — the journey bills and duns either way.
- The NPL threshold (OD-04, Whan) — the ladder rungs the screens draw are indicative (deck v20.0 source); declaring NPL is always the human act in `/review` or `/npl`, and `ladder_mode: MANUAL` suppresses even the indicative rungs (R6).
- The allocation component order (OD-02) — receipts recorded in this journey move invoice/journey states but never write instalment components while OD-02 is open.
