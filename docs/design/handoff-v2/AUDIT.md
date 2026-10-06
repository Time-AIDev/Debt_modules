# Final v2 fidelity worklist

Audit of the rebuilt app against `Volt Debt - Final v2.dc.html` (prototype line
numbers below). Items are grouped by screen and classified:

- **DO** — the app diverges from the prototype and no test asserts the
  divergence. Rebuild to match.
- **SKIP (ruling)** — the divergence is asserted by a `*.test.jsx` (a ruling made
  during the v2 build, or an API truth). Leave it and note it in the outcome.
- **CHECK** — the prototype element may need API data the app does not serve.
  Add it only if the data is already on the payload; otherwise leave and note it.

Rules for the pass: use existing tokens and components; no new colours; never
edit a `*.test.jsx`; if a test goes red, revert that change and record it.

## Overview — Dashboard.jsx (prototype 779-932)

- **DO** — field strip cells carry a third note line (prototype 788-794):
  "198 อยู่ในขอบเขต", "ทำแล้ว 67", "รักษานัด 16 จาก 39", "เกณฑ์ยังไม่ตัดสิน".
  Add per cell if the team payload serves it.
- **DO** — strip values: arrears and NPL in the overdue tone (prototype 2275,
  2279); other values ink-900.
- **DO** — the officers table and the "what to do next" panel share one row
  1.3fr : 1fr (prototype 839, 2110-2111). They are stacked full-width today.
- **DO** — "what to do next" is a stacked list: tone count chip, underlined
  label, then a "why" sentence (prototype 916-928). Today it is four bordered
  cards without the why line.
- **DO** — trend heading carries the unit "% ของเป้าเดือน" (prototype 812-813).
- SKIP (ruling) — KPI progress bar only on receipts (R5/R20); aging table with
  arrears column (not bars); rate colouring by served flags; header accent
  ink-800.
- SKIP (language pass) — KPI label wording, scope clause, target row labels,
  roll title/note, next-item labels (documented as copy deltas).

## Today + Work book + record — Today.jsx, WorkBook.jsx, CustomerCase.jsx (prototype 227-484)

- **DO** — row DPD turns `--status-overdue` at ≥ 30 (prototype 2037). Wire
  `metaTone: 'overdue'` in the row builders (SplitView supports it now).
- **DO** — row aging heat strip (prototype 2038, heat = DPD/120 capped) in Today
  and Work book rows.
- **DO** — record field strip restores the per-cell note line where served
  (prototype 317-325: "ค่างวดค้าง n งวด", "ตามสัญญา 24 งวด", band label,
  "ยังไม่ออกใบแจ้งหนี้") and the cell dividers (split-today.css).
- **DO** — pass the pane's bottom note to SplitView (prototype 274; Today lens
  note 1317, book lens note 1318 — penalties held / phone off / masked
  phone-email).
- **CHECK** — the record overview is a card stack today; the prototype has a
  two-column overview (339-403) with การติดต่อล่าสุด, สิ่งที่ค้างอยู่ and
  ตำแหน่งเงิน. Add the missing panels **additively** if the case payload serves
  the figures; do not remove the existing cards.
- **DO** — split list/work wrapper: drop the rounded border card so the pane is
  a flat aside (prototype 228, 2101).
- SKIP (ruling) — officer filter in the page bar; tier groups; greeting/board/
  filter additions; tabs replaced by stacked cards; ladder step controls;
  month grid; holds card.

## Calendar — Calendar.jsx (prototype 933-1001)

- **DO** — header is one card with a 4px `--brand-500` left edge holding title,
  sub, the month/week segmented control and the ghost button (prototype 935-946).
- **CHECK** — 4-field strip (เลยกำหนด / สัปดาห์นี้ / นัดชำระถึงกำหนด /
  ชุดแจ้งเตือน) (prototype 947-955). Add if the calendar payload serves the
  counts.
- **DO** — week rows carry the kind chip and the state chip (prototype 991-993).
- **DO** — month chips: 2px severity left accent; overdue tint on the left edge
  only (prototype 2340).
- **DO** — month card chrome: weekday header on `--surface-50` with column
  dividers; card border/radius around the grid (prototype 959-965).

## Reviews — ReviewQueue.jsx (prototype 486-543)

- **CHECK** — evidence panel "หลักฐานที่แนบมากับคำขอ" with its three rows and
  footer note (prototype 519-529). Add if evidence is on the request payload.
- **DO** — restore the sentence "คำตอบจะกลับไปอยู่ในรายการของผู้ขอบนหน้าวันนี้"
  (prototype 509-516 note; copy key `rq.answerBack`).
- **DO** — pass the list footer note to SplitView (prototype 274 / lens note
  1324).
- **CHECK** — show the review reference (RV-…) in the row and work header if
  served (prototype 1994, 2035).
- SKIP (ruling) — decision form with comment; age instead of money; no sort.

## Pre-installation — InvoicePipeline.jsx (prototype 544-582)

- **DO** — restore the status strip under the header (prototype 561 note;
  blocked/ready/released sentence).
- **DO** — restore the list filter select (prototype 236) beside the show-all
  checkbox; keep the checkbox.
- **DO** — row heat strip (prototype 2038) if the case DPD is served.
- **DO** — progress bar 180×6 in the right column under the release action
  (prototype 557).
- SKIP (ruling) — three conditions changed; inline gate forms; extra
  after-release card; disabled release button.

## Receipts & PEAK — Payments.jsx (prototype 583-629)

- **DO** — the gates footnote is the allocation rule: "เงินที่ยังไม่จัดสรรไม่ลด
  ยอดค้างบนหน้าจอ — ยังไม่ตัดสินลำดับการจัดสรร" (prototype 625). Today it shows
  a slip-matching sentence; add the correct key and use it.
- **DO** — passed gate mark renders ✓ (prototype 2541-2542).
- **DO** — gate state on the right is the shared chip (prototype 2543).
- **DO** — gate row fills: current = brand border + brand-050; refused = red
  border + white (prototype 2545).
- **DO** — row heat strip + list footer note (prototype 2038, 274 / lens note
  1330).
- **DO** — header eyebrow "เอกสาร PEAK" (prototype 589).
- SKIP (ruling) — no fix-and-resubmit; no allocation lines (R12).

## NPL & recovery — Recovery.jsx (prototype 630-687)

- **CHECK** — after a path is chosen, show "ขั้นตอนถัดไปของแนวทางนี้"
  (prototype 673-684) if the chosen strategy's steps are on the payload.
- **DO** — list footer note (prototype 274 / lens note 1333) and the strategy
  filter + sort toggle inside the NPL tab (prototype 236-240) if the data
  supports them.
- **DO** — header eyebrow "เคส NPL" (prototype 636) and the case reference in
  the row identity if served (prototype 1291-1294).
- **DO** — row heat strip from the risk score (prototype 2038, 257).
- SKIP (ruling) — four strategies, no figures/rates (R11); confirmation card.

## Reports — Reports.jsx (prototype 688-720)

- **DO** — editions card titled "รายงานประจำสัปดาห์" with its sub (prototype
  690-694), and the table footer note `reportNote` (prototype 716).
- **DO** — list sub names the current edition; group label "ต้องตรวจก่อน
  เผยแพร่"; period filter + sort toggle if usable (prototype 1335).
- **DO** — action column header empty (prototype 699, blank header cell), draft
  button "เผยแพร่", published "ดาวน์โหลดฉบับเต็ม" (prototype 2588-2591) unless a
  test pins the current label.
- SKIP (ruling) — KPI panels on Reports; reason-required export; drafts edit.

## Settings — Settings.jsx (prototype 721-778)

- **DO** — one header card: title + sub + the three-column header row, 4px
  `--brand-500` left edge (prototype 723-732). Column labels are role-aware
  (prototype 2618-2619).
- **DO** — restore the per-row owner line where served (prototype 736-742).
- **DO** — "แก้ไขได้" chip uses the current (green) tone (prototype 2601); user
  role chips toned by role (prototype 2623).
- **CHECK** — enumerated settings render a select with the served option list
  (prototype 2605-2606, 1384-1389) instead of free text.
- SKIP (ruling) — grouped register; per-row save/reset; lock chip wording;
  users table.

## Data sources — DataSourcesMigration.jsx (prototype 1002-1083)

- **DO** — page title/sub "แหล่งข้อมูล" / "ข้อมูลเข้ามาจากไหน…" (prototype
  1006-1007) and one header card holding the title and the strip (1004-1018);
  strip label "สมุดงานใช้ข้อมูลจาก" with its notes (2361-2366).
- **DO** — import card title "นำเข้าชีต"; checkbox "ดูรายงานก่อน ไม่ลงข้อมูลจริง";
  hint ".xlsx หรือ .csv · ไม่เกิน 20 MB"; buttons "ตรวจไฟล์" (primary) and
  "ลงข้อมูลจริง" (manager-gated) (prototype 1038-1050) — keep the separate land
  act; restore the default note (1454-1455).
- **DO** — import/receipt banners wording (1051-1065); receipt heading
  "ใบรับรองการนำเข้าครั้งล่าสุด" (1067).
- **DO** — export: one-line reason input (placeholder "เหตุผลในการส่งออก ·
  จำเป็น"), button "ส่งออก · บันทึกลงบันทึกการใช้งาน", note "ไฟล์ส่งออกไม่มี
  คอลัมน์เบอร์โทรและอีเมล" (1075-1078).
- **DO** — two-column grid: import left, receipt + export right (1037, 1080).
- SKIP (ruling) — PEAK card, registry, migration status, gap list; serving
  chain controls.

## Action log — AuditLog.jsx (prototype 1084-1120)

- **DO** — one header card holding title/sub + the three-field strip (1086-1100);
  strip labels "บันทึกถาวร / ตรวจความต่อเนื่อง / ที่มาของชื่อผู้ลงนาม"
  (2386-2388).
- **DO** — "แสดง 50 รายการล่าสุด" at the right of the filter bar (1102-1107).
- **DO** — footer bar with "โหลดรายการเก่ากว่านี้" and the note about unenriched
  rows (1132-1134).
- **DO** — claimed-name badge inline beside the actor (1118-1122).
- **CHECK** — pending outcome tone (prototype 2390-2393) if the API serves it.
- SKIP (ruling) — 8-column grid table; visible filter labels.

## Completion pass — 2026-09-18

The "CHECK — not served" items above were closed by serving the data honestly,
then wiring the UI. Everything is additive; no key was removed or renamed.

- Overview: `team.in_scope` + `team.cases_total` served; in-scope and
  "criterion not yet ruled" notes render. Queue done-of-total stays out — the
  today queue has no per-case completion record, so the queue cell keeps two
  lines instead of three.
- Calendar: `meta.reminders` (batch label, offsets, SOP-conflict, notes) served;
  the four-field strip computes overdue / this week / PTP due / batches from the
  payload.
- Reviews: every request row carries `evidence` — last ≤3 contact-log entries,
  PTP kept/broken from the snapshot, the requester's reason; the panel renders.
- Pipeline: `waiting_days` (business date − planned install) + case DPD served;
  rows draw the heat strip.
- Payments: `waiting_days` per document + `meta.business_date` served; rows draw
  the heat strip.
- Settings: enumerated rows carry `options` (band sets, reminder presets); the
  design's pending keys surface as locked rows. od04 keeps `value: null` — the
  shipped value is "refusing", so 90 is not printed as the setting.
- Recovery: per-strategy `next_steps` served from the SOP's own labels and
  gates; the chosen path's steps panel renders after confirmation.
- Data sources: the import time travels from the landing store through
  `book.build()` to `/v1/migration/report`; the registry note renders when it
  exists (fixtures hold null).
- Action log: open reviews are joined frontend-side so request rows read as
  pending. The hashed `outcome` contract is untouched — a third outcome would
  change every stored signature.
- Login: complete end-to-end; `scripts/run_prototype_login.sh` starts the stack
  with `AUTH_MODE=on`, a generated secret and per-role test accounts (hashes
  only), verified with the login card, a signed-in role and auth-off regression.

Remaining honest omissions: queue done-of-total (above), the od04 value (above),
and Google sign-in needing the demo origin on the OAuth client (operator-side,
test accounts unaffected).

## 100% pass — 2026-09-18

The completion pass above was superseded by the DELTA-100 rebuild
(`DELTA-100.md`): every remaining divergence was re-audited element by element,
the decisions D1-D5 were taken, and all twelve screens were rebuilt to the
prototype with the missing data modelled and served. UAT (scripted walk of every
screen, TH/EN, acceptance list) and its findings live in `.v2-outcome/uat/`.

