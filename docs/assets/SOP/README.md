# Current Debt Collection Flow — Diagrams

> **These ARE the authority ladder's rank-2 four flowcharts.** *(Established 2026-09-06 by byte-size
> match against the Drive folder "Origin workflow": `VOLT ERP Flowchart Part 1–4` = 124,485 /
> 142,464 / 183,270 / 185,224 bytes and `mermaid-diagram.png` = 2,119,506 — identical to `01`–`04`
> and `00` here.)* Requirements Amendment v2.6 §1 ranks *"Team SOP: docx, four flowcharts,
> seventeen-step workflow"* at **rank 2, second only to the 2026-09-01 interview** — so these images
> outrank the PRD, the API Surface and every amendment below v2.6. The line below — *"exported from
> Downloads on 2026-08-30"* — is true of how the files arrived and **caused a real error**: it led
> the orchestrator to reason they sat at rank 5. Do not repeat it. The SOP text is in Drive, not
> this repo: `Debt Collection Workflow.docx` (the seventeen steps) and `Volt-Debt-Collection-EN.docx`
> (ten sections); both were read on 2026-09-06 — findings in `docs/design/round-4/00-ledger.md` and
> `docs/design/findings.md` (R4-F66…F70).

Source: exported from Downloads on 2026-08-30. Flowcharts are in Thai with English
lane/stage labels. Parts 1–4 are the same end-to-end flow split for readability;
`00` is the full uncut version.

| File | What it shows |
| --- | --- |
| `00-debt-flow-full-end-to-end.png` | Complete AR → collection → NPL → closure flow in one tall diagram (all 4 parts combined). |
| `01-debt-flow-part1-sales-epc-ar-invoice.png` | Sales / EPC / AR Invoice — down payment gate → EPC install confirmation → invoice issue → installation check. Lanes: Sales/EPC, AR, Collection. |
| `02-debt-flow-part2-payment-overdue-collection.png` | Payment & Overdue Collection — due-date follow-up, partial payment, entry into overdue collection. |
| `03-debt-flow-part3-ptp-service-issue-manager-review.png` | PTP / Service Issue / Manager Review — contact result, PTP & broken PTP, CS/O&M service issues, escalation to manager review. |
| `04-debt-flow-part4-credit-risk-npl-recovery-closure.png` | Credit & Risk Decision / NPL / Recovery / Closure — repayment arrangement, restructure, NPL recovery strategies, closed / write-off. Lanes: Credit & Risk, Arrangement/Restructure, NPL Recovery. |
| `05-debt-collection-ar-system-architecture-mvp-gcp.png` | System architecture (not a process flow) — Volt ERP Debt Collection & AR, MVP → GCP target. |

Reading order: `01` → `02` → `03` → `04`, or `00` for the whole picture.

Documented as a journey, with scenario and screen mapping, in `docs/product/user-journey.md` (2026-08-30).
