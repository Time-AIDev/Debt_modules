# screens-v2 · 04 — Follow-ups (`/queues`) + Manager review (`/review`)

## Follow-ups (`src/screens/FollowUpQueues.jsx`)

Flow part 3's branches as four deep-linkable tabs (`?tab=`): **นัดชำระ**
(PTP_DUE) · **ผิดนัดชำระ** (BROKEN_PTP) · **ปัญหาบริการ** (SERVICE_ISSUE) ·
**ติดต่อไม่ได้** (UNREACHABLE). One table shape for all four — membership and
order come from `GET /v1/working-list?bucket=`, never computed client-side.

Per-tab fourth column and actions:
- PTP_DUE: the promise (amount · date); actions ชำระตามนัด (`:close` KEPT) and
  ผิดนัด (`:close` BROKEN — the response's review uid is the routing made
  visible) plus บันทึกผล.
- BROKEN_PTP / UNREACHABLE: last contact; rows already routed show the
  "อยู่ในคิว Manager Review แล้ว" tag rather than a second escalate button.
- SERVICE_ISSUE: the routed owner + status chip; ปิดเรื่อง (`:resolve`) returns
  the customer to the follow-up loop.

Empty states are real sentences per tab ("ไม่มีนัดชำระถึงกำหนดวันนี้"), never a
dash. The drawer opens from any row.

## Manager review (`src/screens/ManagerReview.jsx`)

Flow parts 3→4: master-detail. The standing Notice states decisions are taken
as Owner (the Debt Manager post is vacant — REQ-IAM-015).

- **List** — one row per review: customer, trigger chip (broken PTP / refused /
  unreachable / arrangement broken / restructure failed), open date or the
  decided line.
- **Detail** — the Credit & Risk evidence exactly as the flow names it:
  DPD + band, arrears, the PTP tally (made · kept · broken), open service
  issues. Then a note field and the decision buttons — **only**
  `available_decisions`: a cash customer is offered neither restructure nor
  confirm-NPL, and the `cash_note` says why (S11's remedies are legal or
  removal). Decide → `POST :decide` with role OWNER; the returned `effect`
  (arrangement uid / case uid / npl uid) renders so the consequence is visible;
  409 `review_already_decided` renders verbatim on a second attempt.
