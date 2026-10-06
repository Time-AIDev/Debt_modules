# screens-v2 · 05 — NPL & recovery (`/npl`) · Cash defaults (`/cash-defaults`) · Service billing (`/service-billing`)

## NPL & recovery (`src/screens/NplWorkspace.jsx`)

One card per NPL case:
- **Head** — contract uid, declared on/by, the provisioning-only sentence, SPV
  entity chip, the OD-04 PendingBadge.
- **Deed** — executed: the buyback line ("100% of remaining NPV — no discount,
  not 90") with the OQ-31 badge on the indicative NPV. Not executed: the quiet
  Notice that the 120-day window is open on purpose (the customer may come back).
- **Strategy** — the flow's four as buttons until one is chosen
  (`POST /v1/npl-cases/{uid}/recovery`); REPOSSESSION arrives with its lot.
- **Recovery amounts** — the server-summed total, the entry list, an add form.
- **Lot panel** — the S12 walk as staged forms: count (variance demands a note),
  grade A/B/C (must cover the count), price (placeholder says "THB (Dan)" —
  anyone else refuses), sell (blocked chip until priced; the sale posts to the
  recovery total). The shelf line (`PANEL-550-R @ WH/REFURB`) and the uninstall
  fee (THB 5/W × watt) are always visible.
- **Outcome** — four buttons; the write-off note names the Owner requirement;
  refusals render verbatim.

## Cash defaults (`src/screens/CashLadder.jsx`)

S11 as three fixed columns (NOTICE_30 · SETTLEMENT_PLAN_60 ·
DEFAULT_CONFIRMED_90) — deliberately the board idiom so it reads as kin to
`/board`, but NOT draggable: a cash rung is an act with a precondition, taken by
button and logged by the server. Cards carry contract uid, `EPC · เงินสด`,
arrears, DPD, and the chosen path chip once confirmed. At 60 the two terminal
buttons appear: ฟ้องร้อง and ถอดระบบ (→ S12). The standing Notice states the
90-day split's rule. No SPV column exists because no SPV leg exists.

## Service billing 37+ (`src/screens/ServiceBilling.jsx`)

Two standing Notices before any row: the isolation rule (service arrears never
feed the lease ladder), and the SVC-37 open decision with its PendingBadge and a
link to /pending — flagged where the billing happens, not in a footnote.

Rows: customer · `เดือนที่ {n}` + status chip (รวมในราคาแล้ว 1–36 / เรียกเก็บ
37+ / ยกเลิกพร้อมสัญญาเช่า) · monthly amount with the QR + 25–30 window line ·
dunning stage + invoice list · actions. **ออกบิลเดือนนี้** exists so its refusal
can teach: on the fixture's 23rd it renders `billing_window_closed` verbatim —
the law demonstrated live. **บันทึกคำขอปฏิเสธ** records the decline request
(202) and the confirmation states billing continues.
