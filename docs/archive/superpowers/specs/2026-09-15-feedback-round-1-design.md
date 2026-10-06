# 10 — Feedback Round 1 (14 Sep 2026) — Design, for review

**Status: DRAFT for Arina's review. Nothing here is built.** Written 2026-09-15 from [[Feedback]]
(the debt manager's system feedback and the six UI screenshots), against branch `design-team` at
`f8acc2e`. The plan cut from this design is [[11 - Feedback Round 1 - Implementation Plan]].

How to read this note:

1. §1 turns the feedback into work packages, in the order you asked for — **journey and system
   first, UI second**, extra features last.
2. §2 is what I measured before designing. The PEAK export you linked was read row by row.
3. §3 is the design, one section per work package.
4. **§4 is the decision register (F1–F19).** Each row has the options, what each costs, and my
   recommendation. Approve, change, or strike each one. The plan is written to the
   recommendations; a different ruling re-cuts only the tasks that cite it.
5. §5 is the test price (measured pins, not guesses). §6 is the build order.
6. §8 is a short Thai summary that can go to the debt manager.

Authority: Requirements Amendment v2.6 §1 ladder. This note carries no rank; where it and a
ranked document disagree, the ranked document wins, and I say so at the place (F2 is the one
that touches §3.6).

---

## 1. The feedback as work packages

| #   | Feedback (short)                                                                                                                                                                                                                        | Priority | Work package                                                      |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------- |
| 1   | PEAK invoice export does not match Odoo `crm.lead`; reference `VC…/VRC…` (อ้างอิง) mismatches; Debt judges monthly payment status from the PEAK export "as a rule"; names differ Thai/English                                           | **P1**   | **WP1 — PEAK invoice reconciliation**                             |
| 2   | Import from `crm.lead` only **new** customers; never touch contracts already in the Debt platform                                                                                                                                       | **P1**   | **WP2 — Import "new only" mode**                                  |
| 3   | First: contract scorecard (payment volume per customer). Second: monthly payment picture per contract. Show on the case and on the Save-contact dialog. Manager add-on: per case, how many invoices are paid and how many unpaid remain | **P1**   | **WP3 — Scorecard first, month strip second, paid/unpaid counts** |
| 4   | Save contact: more than one note, optional files (.png .svg .csv .xlsx .pdf .docx), malware protection; activity history at the bottom, scrollable                                                                                      | **P1**   | **WP4 — Notes, attachments, history in the dialog**               |
| 5   | PEAK API or webhook to fetch invoices automatically (spare door, deep-dive later, untested)                                                                                                                                             | P3       | **WP5 — PEAK API door (port only)**                               |
| 6   | Notice calendar like Google Calendar: click, edit, set notices                                                                                                                                                                          | P3       | **WP6 — Calendar**                                                |
| 7   | Today list and Kanban: remove the reminder tab; turn "Whole team today" and the status tags into table filters; remove the messy notices on every screen                                                                                | **P2**   | **WP7 — Today and board header**                                  |
| 8   | Case page: too much detail in the header; put it elsewhere and make it editable                                                                                                                                                         | P2       | **WP8 — Case header**                                             |
| 9   | Phone number visible, copyable, editable per case                                                                                                                                                                                       | P2       | **WP9 — Phone on the case**                                       |
| 10  | Settings: friendlier, like the screenshot; a sub-tab for the e-mail allow-list (invite outside users) and a display name                                                                                                                | P2       | **WP10 — Settings redesign + Users tab**                          |
| 11  | Today greets the signed-in user by display name (or e-mail user part)                                                                                                                                                                   | P2       | **WP11 — Greeting**                                               |
| 12  | Weekly report: like the screenshot, or better                                                                                                                                                                                           | P2       | **WP12 — Weekly figures the API does not send yet**               |

---

## 2. What I measured first

### 2.1 The PEAK export (the manager's spreadsheet)

File `invoice_บริษัท_โวลต์_จำกัด_export_as_of_20240101_20260914_20260914_155330.xlsx`, 2.7 MB, one
sheet `รายงานใบแจ้งหนี้`, header on row 11, **7,999 invoice lines = 7,638 invoices**, 56 columns.
Parsed with the repo's own `imports.read_xlsx` — no new library needed.

| Column | What it holds | Measured |
|---|---|---|
| `เลขที่เอกสาร` | invoice number | `IVT-` 5,794 · `IV-` 2,204 |
| `สถานะ` | PEAK's own payment state | `รับชำระแล้ว` 7,120 · `เกินเวลารับชำระ` 752 · `รอชำระ` 124 · `ร่าง` 2 |
| `รหัสผู้ติดต่อ` | **PEAK contact code** | 1,267 distinct: **645 V-ids** (VC/VRC/VL/VRL), **339 eleven-digit CRM ids**, **282 composite/odd** |
| `อ้างอิง` | the reference the manager named | filled 7,449; V-id 1,512 rows; **11-digit CRM id on 5,877 rows**; empty 550; odd 55 |
| `ชื่อลูกค้า` | customer name | **Latin 7,455 · Thai 471 · mixed 72** |
| `เลขที่ 13 หลัก` | citizen / tax id | filled on 7,991 rows, 1,261 distinct |
| `คำอธิบาย` | line text | **"M n/N" cycle mark on 6,796 of 7,999 lines** (e.g. `Installment_M14/48`) |
| `วันที่` · `เลขที่ใบเสร็จ` · `จำนวนเงิน` | payment date, receipt no (`RE-`/`RT-`), amount paid | 7,138 lines carry a payment |
| `วันที่ครบกำหนด` · `ต้องชำระ` · `มูลค่ารอรับชำระ` | due date, amount due, amount still awaiting | |
| `กลุ่มย่อย` | Solar Leasing 1,669 · Cash 642 · blank 5,680 | |

Three findings that decide the design:

- **The reference is Odoo's key, not the sheet's.** 612 of the 645 V-id contact codes exist as
  `crm.lead.volt_id` (94.9 %). The **book** (the sheet-derived 418 customers) carries a V-id
  prefix on only 213 rows and matches 102 of those codes. So PEAK ↔ Odoo mostly agrees on the
  V-id; it is the sheet-shaped book that cannot see it.
- **The 11-digit CRM id is a second key that already works.** 188 of the 339 eleven-digit contact
  codes equal a book `customer_no` (the book has 418 customers; the export covers ~1,267
  contacts, so the ceiling is coverage, not the key).
- **The "package change without deleting the old contract" is visible in the data.** 282 contact
  codes are composites like `VL0010239,VC0010687`, `99999000194,C0010423`, `VL0010696,697`,
  `VC001059` (six digits). These are exactly the old-id/new-id pairs the manager described, plus
  typing errors. `อ้างอิง` equals the contact code on only 892 rows and differs on 6,557.

Coverage today: **2,824 of 7,999 lines** hit the book by an exact key (customer_no or V-id). The
rest need the Odoo bridge (V-id → `crm.lead` → phone → book), a repaired composite, or a person.

### 2.2 What the code already has (so the design reuses instead of inventing)

| Already in the tree                                                                                     | Where                                                                      | Consequence                                                                                                              |
| ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Two-door pipeline (drop a file / pull from Odoo), runs with a progress bar, 15-min timer                | `pipelines/*`, `DataSourcesMigration.jsx`                                  | WP1 and WP2 are new doors and modes on this, not a new subsystem                                                         |
| Raw-body upload with size cap and magic-byte sniff, no `python-multipart`                               | `routers/imports.py`, `api.js postRaw`                                     | Attachments and the PEAK report use the same shape                                                                       |
| Payment overview per cycle, one `<path>` per status (density-safe)                                      | `payment_summary.py`, `PaymentOverview.jsx`                                | WP3 reorders and re-sources it; it does not redraw it                                                                    |
| A person may change `payment_status` with a reason; `PAYMENT_STATUS_SET` events                         | spec 2026-09-14                                                            | The transition log WP12 needs now exists (since 2026-09-14)                                                              |
| Plan 2026-09-11 §1.1 `payment_position` (paid/open counts, oldest unpaid, last money in, source, as-of) | Task 1 (`captured_on`) built; **the block itself (Tasks 2–7) never built** | WP1/WP3 build it; the manager's "paid vs unpaid invoices per case" is exactly this block                                 |
| PEAK writes are DRAFT_ONLY; `integrations/peak.py` pinned to four functions (PKD-001)                   | `peak_documents.py`                                                        | WP1/WP5 read invoices in a **new** module; the pinned one is untouched                                                   |
| Weekly overview with dashed "not sent by the API yet" cards                                             | `WeeklyOverview.jsx` — **staged, uncommitted** on design-team              | WP12 fills the cards; the staged work must be committed first (F18)                                                      |
| Login allow-list is a JSON secret; `me` has no display name                                             | `auth.py`, `routers/login.py`                                              | WP10/WP11 add a DB-backed list and a profile                                                                             |
| Per-tester `Store` + `app.session_state` (discarded on deploy); `audit` schema append-only              | `session.py`, `schema.sql`                                                 | Things that must outlive a deploy (links, attachments, allow-list, profiles) need their own durable tables (F4, F7, F13) |
| Terraform names a private `docs` bucket, unapplied; provisioning has no bucket                          | `infra/terraform`                                                          | Attachments go to Postgres now, GCS later (F7)                                                                           |

---

## 3. Design

### WP1 — PEAK invoice reconciliation (P1)

**Purpose.** Make the PEAK invoice report the source the Debt team judges monthly payment
status from, with every invoice tied to a customer by a rule a person can read, and every
unmatched row visible and linkable — never guessed.

**Shape.** The same three-step intake desk the crm.lead pipeline uses: choose a door → the run
reads, matches and **proposes** → a person applies. One new source card on the Data sources
screen: **"รายงานใบแจ้งหนี้ PEAK"**.

**Door 1 (built now) — upload the report.** `POST /v1/pipelines/peak-report:run` and `:start`,
raw body + `X-Volt-Filename`, csv/xlsx, 25 MB cap, Manager-only like the crm.lead endpoints.
Door 2 is WP5.

**Parser — `backend/app/pipelines/peak_report.py` (pure).** Finds the header row by the pair
`เลขที่เอกสาร` + `อ้างอิง` (so a column moved by PEAK is a refusal naming the missing header, not
a silent shift). One normalised line record:

```
doc_no, doc_kind (IVT|IV), issued_on, due_on, reference, system_reference, status,
contact_code, customer_name, tax_id_13 (in-run only, see F5), product_code, description,
cycle {n, of} | None, amount_total, amount_due, amount_awaiting,
payment {on, channel, amount, receipt_no} | None, note, created_by, approved_by,
report_as_of (from the file name "…export_as_of_<from>_<to>_…", else the run date)
```

Status map, fixed and closed: `รับชำระแล้ว → PAID`, `เกินเวลารับชำระ → OVERDUE`,
`รอชำระ → AWAITING`, `ร่าง → DRAFT`. An unknown Thai status is **rejected with the value printed**,
never mapped to the nearest. Lines are grouped into invoices by `doc_no`. Dates `dd/mm/yyyy`.

**Matcher — `backend/app/pipelines/peak_match.py` (pure).** Every invoice gets one verdict:

| Rung | Key | Result |
|---|---|---|
| 0 | `identity_link` register (links a person confirmed before) | EXACT |
| 1 | contact code or reference is an 11-digit id == book `customer_no` | EXACT |
| 2 | contact code or reference is a V-id == book `volt_id` prefix (normalised: upper-case, spaces stripped) | EXACT |
| 3 | V-id → `landing.customer` ODOO row (`crm.lead.volt_id`) → its phone → book customer with that phone | EXACT via Odoo, rule named |
| 4 | composite `A,B` split on comma; short suffix `VL0010696,697` expanded to `VL0010697`; six-digit `VC001059` zero-padded — each candidate re-run through rungs 1–3 | **CANDIDATE** (a person confirms) |
| 5 | name — titles stripped (นาย/นาง/นางสาว/คุณ/Mr/Ms/Mrs), spaces and case normalised, compared with `name_roman` and `name_th` | CANDIDATE only, never EXACT (language mismatch) |
| — | nothing above | UNMATCHED, listed with the customer name, contact code, invoice count and the money it carries |

F1 decides which rungs auto-apply. Recommendation: EXACT rungs apply on "apply", CANDIDATE
rows wait for a click, UNMATCHED rows wait for a link.

**The link register — `records.identity_link`** (durable, not per-session): `peak_contact_code`,
`customer_uid`, `contract_uid | null`, `rule`, `confirmed_by`, `confirmed_at`, `reason`,
`active`. One customer may hold several codes (the old and the new V-id after a package
change), which is how an invoice under the old id still lands on the right person. Confirming,
rejecting and retiring a link are audited acts.

**Where the facts land — `landing.peak_invoice`** (F4), run-scoped like every landing row, one
row per invoice with its lines as JSONB, plus the verdict. `book_source.load()` adds a `peak`
block to each matched customer (`{report_as_of, invoices: [...]}`), so the domain sees PEAK the
way it sees the sheet's blocks — through the one seam.

**What the engine does with them.**

- `journey._seed_migrated_invoices` prefers the `peak` block when a contract has one: invoice
  records carry `peak_number`, the PEAK state, `due_date`, `cycle`, and the receipt (number, date,
  amount) as a receipt record with `source: "PEAK_REPORT"`. The sheet path stays for customers
  with no PEAK facts.
- `payment_summary` gains `source` per contract (`PEAK` | `SHEET_DERIVED`) and the provenance
  line changes with it: "PEAK ณ วันที่ 14/09/2026" against today's "walked back from the sheet,
  indicative". Where PEAK gives a cycle mark, that cycle's status is PEAK's; where it does not
  (1,203 of 7,999 lines), the invoice is shown under the contract without a cycle slot and the
  strip says so.
- **`payment_position` (plan 2026-09-11 §1.1) is built** and served beside `money_position` on
  the work item, the case, and the book row: paid count, open count, oldest unpaid, last money
  in, `source`, `as_of`, stale mark. This is the manager's "how many invoices paid and how many
  unpaid remain".
- The case's `payment_status_system` follows PEAK when the customer is linked (F2), through the
  existing "system wins, logged" path — so a person's adjustment ends with a visible event, never
  silently.
- OD-02: a PEAK line with a receipt number and a payment date is PEAK's own allocation. F3 asks
  whether it may be recorded as allocated. Recommendation: yes, for PEAK-sourced receipts only.

**Screens.**

- **Data sources → PEAK report card:** the manifest (read · invoices · matched exact · candidates
  · unmatched · applied), the run bar, then three lists: *candidates* (confirm / not this one),
  *unmatched* (a `SearchCustomer` picker + reason → link), *links* (retire). Each row prints the
  rule that produced it.
- **Case page:** the overview says which source it is drawn from; the invoices card shows the
  PEAK number, PEAK state and receipt per invoice; a customer with no PEAK facts gets one quiet
  line: "ยังไม่มีใบแจ้งหนี้ PEAK ผูกกับลูกค้ารายนี้ — ผูกได้ที่หน้านำเข้าข้อมูล".
- **Work Book:** `position=unpaid | stale` filters and the `oldest_unpaid` sort (plan §1.6).

**Errors.** Header missing → refuse, name the header. Unknown status value → the row is rejected
and counted under `status_unknown` with the value. A report older than the one already applied
→ refuse (`report_as_of` goes backwards) unless the person ticks "apply an older report".
Duplicate `doc_no` across runs → the newer run's row wins, the older stays in its run. A run that
dies → `runs.fail()` with the reason; the previous run keeps serving.

**Not in WP1.** OCR of PDFs (still rejected, plan §0). Writing anything to PEAK. Matching by
citizen id across runs (F5). Automatic pulls (WP5).

### WP2 — Import "new only" (P1)

**Purpose.** A crm.lead run adds customers the Debt platform has never seen and leaves every
existing customer and contract exactly as it is.

**Design.** `pipelines/service.run(mode)` gains `mode = NEW_ONLY | OVERWRITE`; **NEW_ONLY is the
default** and the only mode the button offers; OVERWRITE stays reachable under "ขั้นสูง" for the
Manager (F6). In NEW_ONLY the writer:

1. resolves each incoming lead against the book by the join ladder the rules file already
   declares and the code never used (§12 item 1 of the crm.lead design): `customer_no`, phone,
   V-id prefix;
2. **writes only the leads that resolve to nobody**;
3. for a lead that resolves to an existing customer, writes nothing and appends a **proposal**
   to `import_run.meta.proposals`: `{customer_uid, volt_id_seen, fields_differ: [{field, book, odoo}]}`;
4. for a lead whose V-id is new but whose phone/customer_no is an existing customer — the
   "new contract for an old customer" case — a proposal of kind `NEW_CONTRACT_FOR_EXISTING`.

The Data sources manifest gains three counts: **ใหม่ (landed) · เดิม ไม่แตะ (skipped) · มีความต่าง
(proposals)**, and a "ความต่าง" list a Manager can read. Nothing in the list applies itself; a
later WP can add "apply this field" if wanted (not asked, not built).

This also fixes the overwrite ledger reading `overwrote 0` for the wrong reason (§7 of the
crm.lead design), because the join is now real.

### WP3 — Scorecard first, month strip second, paid/unpaid counts (P1)

**Purpose.** The manager's reading order: the customer's payment volume first, the monthly
picture second, on the case and inside the Save-contact dialog.

**Design.**

- `PaymentOverview.jsx` is reordered, not redrawn: **card 1 "สรุปสัญญา"** — paid amount,
  outstanding, overdue, **จ่ายแล้ว n ใบ · ค้าง m ใบ** (from `payment_position`), last money in
  (amount, date, source), the source line. **Card 2** — the existing per-contract cycle strip and
  legend. Both figures are served; nothing is added up in the browser.
- A **compact scorecard** (`PaymentOverview compact`) is mounted in `CaseContactDrawer` under the
  "ติดต่อล่าสุด" block, so the officer sees paid/unpaid before dialling. Today's drawer gets it
  too, from the `/v1/cases/by-customer/{uid}` fetch it already does for the SOP step.
- Density: the case page is at 104/123. The reorder is neutral; the two count lines are +2. The
  drawer is measured before the mount (§5).

### WP4 — Notes, attachments and history in the Save-contact dialog (P1)

**Notes.** A contact row gains `notes: [{uid, text, by, at, attachment_uids}]`. The dialog's one
note box becomes a repeatable row ("+ เพิ่มบันทึก"), and after the contact is saved more notes
can still be added to it (`POST /v1/contacts/{uid}/notes`). A note without a contact is also
allowed on the case (`POST /v1/cases/by-customer/{uid}/notes`): it is **not** a contact, never
counts, never takes the daily slot — the dialog says so on the button.

**Attachments.** `POST /v1/attachments` (raw body, `X-Volt-Filename`, `X-Volt-Attach-To:
contact:<uid> | note:<uid>`), `GET /v1/attachments/{uid}` (download only:
`Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, never rendered inline —
SVG in particular), `DELETE` by the uploader or a Manager, all three audited. Stored in
`records.attachment` (`uid, sha256, content_type (sniffed, never the client's), size, filename,
uploaded_by, uploaded_at, scan_state, scan_note, bytes`) — Postgres now, GCS later (F7). Caps:
10 MB per file, 5 files per note; sha256 de-duplicates.

**The malware guard — `backend/app/attachments/guard.py`, standard library only.** A file is
stored only after every rule passes; a failure is an RFC 9457 problem naming the rule.

| Type | Accepted when | Refused when |
|---|---|---|
| PNG | magic `89 50 4E 47 0D 0A 1A 0A`; chunk walk with CRC check; ends at IEND | truncated, bad CRC, trailing bytes after IEND |
| SVG | well-formed XML, root `<svg>` | any `<script>`, any `on*=` attribute, `javascript:` or external `href`/`xlink:href`, `<foreignObject>`, `<iframe>`/`<embed>`, DOCTYPE entities |
| CSV | decodes as UTF-8 (BOM ok) or TIS-620 | a cell starting with `=`, `+`, `-`, `@`, or a tab/CR-prefixed formula (spreadsheet injection); the cell address is named |
| XLSX / DOCX | zip with `[Content_Types].xml` and `xl/` or `word/`; ≤ 2,000 entries; inflates ≤ 50 MB | `vbaProject.bin` or a macro content type, `oleObject*.bin`, `externalLink*`, DDE fields (`DDEAUTO`, `INSTRTEXT … DDE`), `.xlsm/.docm` types |
| PDF | starts `%PDF-`, `%%EOF` present, ≤ 10 MB | `/JavaScript`, `/JS`, `/Launch`, `/AA`, `/OpenAction` with an action, `/EmbeddedFile`, `/RichMedia`, `/XFA` |
| all | extension agrees with the sniffed type; filename sanitised as `imports.py` does | anything else, including a PNG named `.pdf` |

Then a **scanner port**: `ClamdScanner` (INSTREAM over TCP to `CLAMAV_HOST:CLAMAV_PORT`) when
configured, else `RulesOnly`. The house rule applies: **configured but unreachable refuses the
upload**; not configured stores the file marked `RULES_ONLY` with the label "ตรวจตามกฎรูปแบบไฟล์
ยังไม่ผ่านโปรแกรมสแกนไวรัส" beside every such attachment, so nobody mistakes it for a scanned one
(F8). On GCP a ClamAV Cloud Run service is a later, priced addition.

**History at the bottom.** The dialog gains a **"ประวัติ"** section after the form: the case's
own timeline (contacts, notes, events — the same rows the case page draws), newest first, in a
scroll region (`max-height` ≈ 40 vh), with the attachment names as download links and a "ดูทั้งหมด
ในหน้าเคส" link. The case page passes its timeline in; Today's drawer fetches it.

### WP5 — PEAK API door, port only (P3)

`backend/app/integrations/peak_reports.py`, **a new module** (PKD-001 pins the existing one):
`list_invoices(since, instance)` behind `PEAK_REPORT_API_*` env names. Until the endpoint is
verified against PEAK's documentation, the adapter answers `not_configured` / `untested`, and
the Data sources card lists door 2 with that state in words — the same honesty as the UNSENT
draft state. No webhook receiver is built: a receiver written against a payload nobody has seen
is a guess (F19).

### WP6 — Calendar (P3)

Route `/calendar`, rail item **"ปฏิทิน"**. `GET /v1/calendar?from&to` serves one list of dated
things the stores already hold: next actions, PTP promise dates, reminder batches (D-3/D0 — the
block leaving Today in WP7 lands here), review SLA deadlines, service-issue deadlines,
restructure and settlement dates, NPL buy-back dates. Plus personal **notices**
(`records.notice`: owner, title, on, time, customer_uid, text, done) with create/edit/delete.
Month grid and week list; click → the case page or the dialog; a next action can be moved to
another day (it calls the existing `set_next_action`, reason required). No recurrence, no
sharing, no e-mail (F16).

### WP7 — Today and the board header (P2)

- **The reminders block leaves Today** (list and board). Until WP6 lands it lives on
  `/reminders`, same component, same test ids (F11).
- **The tier strip and "Whole team today" become a `FilterBar`** above the list, the exact
  component Work Book uses: filters `ระดับ` (the seven tiers, counts in the option labels),
  `เจ้าหน้าที่` (roster with today's counts — this is the team-workload data), `สถานะการชำระ`,
  `สถานะติดตาม`, `ผลิตภัณฑ์`, plus the search box. The board keeps the same bar; a filtered
  board shows filtered cards.
- **The standing notices fold into one line**: OD-04 indicative, CF1 reminder offsets, "call is
  off on n rows", the PTP-history note and "pick an officer" move into a single
  `<details>` **"หมายเหตุระบบ (n)"** at the end of the header. The refusals stay reachable — the
  design contract §3 says deliberate refusals stay refused — but they no longer sit on the face
  (F10). `Recovery.jsx`'s eight and `InvoicePipeline.jsx`'s one notice get the same fold;
  `InvoicePipeline.test.jsx:102` pins one of them by role, so that one keeps its `role="status"`
  inside the fold.
- Density: Today's chrome cap is 112 elements; the filter bar costs about 5 × 7 = 35 and the
  three blocks leaving it give back more than that. Measured before spending (§5).

### WP8 — Case header (P2)

The header keeps **figures only**: name, ids, entity, officer, phone (WP9), last contact,
arrears/outstanding, DPD and the ladder line, the two status chips, next action, and the
actions. Everything that explains a figure — "Details", "Allocation pending OD-02", "How this
figure is worked out", the penalty formula — moves to a **"รายละเอียดการคำนวณ"** fold beside the
history fold at the bottom of the page, closed by default (F12).

"Made it editable" is read as two things, both flagged for you: (a) the values that are
**settings** (penalty rate, grace days) get a "แก้ไขที่ตั้งค่า" link visible to the Owner, opening
the WP10 form at that field; (b) the values that are **per case** are editable in place —
payment status and follow-up status already are; next action already is; the phone becomes so
in WP9. If you meant something else by "editable", F12 is the place to say it.

### WP9 — Phone on the case (P2)

A durable, audited override: `records.customer_contact` (`customer_uid, phone_e164, set_by,
set_at, reason, active`). The case header shows the number with a **copy** button and an
**edit** control (reason required, E.164 normalised, Thai mobile/landline shapes validated); the
dialog shows the same; Today's dial buttons use it when present (`phone_on_file` becomes true).
The sheet's masked number stays visible beside it as "ชีตระบุ 08x-xxx-4810". Who may edit and
whether real numbers may be stored at all is F9 (PDPA).

### WP10 — Settings redesign + Users tab (P2)

**Form, not table.** `/v1/config` rows are grouped into sections with Thai headings: ค่าปรับและ
ผ่อนผัน · การเตือน · NPL · การตัดไฟ · ใบแจ้งหนี้ · ค่าถอด · ช่วงอายุหนี้ · PEAK (locked). Each field:
label (TH/EN), input with unit, a state badge (รอตัดสิน / ตัดสินแล้ว / ล็อก), the source line
("Decision log · ruling 87"), a lock icon when the caller's role may not edit it, and **"แก้ไข
ล่าสุดโดย … เมื่อ …"**. The last-changed line needs the config store to keep `changed_by` and
`changed_at` per key — a small backend addition; today only the audit log knows. Dictionaries,
band sets and assignment keep their sections, restyled the same way.

**Users tab (ผู้ใช้).** A DB-backed allow-list, `records.user_account` (`email | username, kind,
role, officer, display_name, invited_by, invited_at, disabled_at`). The env `AUTH_ALLOWLIST`
stays as the seed; rows added here are merged over it at start-up and on each Google sign-in;
a disabled row wins over the seed. Owner and Manager may invite (e-mail + role + officer) and
disable; every act is audited. Any signed-in person may set **their own display name** from the
identity menu (WP11 reads it). Password test accounts are unchanged (F13, F14).

### WP11 — Greeting (P2)

`GET /v1/auth/me` gains `display_name` (the profile's, else the e-mail's user part, else the
username). Today's title becomes **"สวัสดี {name}"** with one short, positive line under it
(rotating from a small i18n list, never a number). With login off, the name is the chosen
officer's `display_name_th`.

### WP12 — Weekly figures the API does not send yet (P2)

The screenshot is the overview already built (staged, uncommitted). What makes it "better" is
the four dashed cards turning into figures. `reports.weekly()` gains, each with its definition
line in Thai on the card:

| Card | Definition | Source |
|---|---|---|
| MoM ค่างวด / เงินสด | this calendar month's receipts vs the same span of last month, SPV vs EPC | `jstate.receipts` (incl. WP1's PEAK receipts) |
| ลูกค้าที่จ่ายสัปดาห์นี้ · WoW | distinct customers with a receipt in the 7-day period vs the prior 7 days | receipts |
| เข้า NPL / ออกจาก NPL สัปดาห์นี้ | `PAYMENT_STATUS_SET` events into / out of `NPL` in the period, plus NPL declarations opened in the period; both counted, the note says which | `cs.events`, `npl_cases` |
| หนี้ค้างจริง vs พักไว้ฝั่งบริษัท | arrears on customers under an allocation hold (OD-02) or an open service issue = held; the rest = true; per instalment/cash line | `_allocation_hold_in_period`, issues |
| การเปลี่ยนกลุ่ม Late/NPL | every `PAYMENT_STATUS_SET` in the period (from → to, by, reason), not only `NPL_TYPE_SET` | events |

Definitions are F15. The Excel export writes the same figures.

---

## 4. Decision register — for Arina

Costs are stated so the choice is yours. **Rec.** = my recommendation; the plan is cut to it.

| # | Question | Options and their cost | Rec. |
|---|---|---|---|
| **F1** | Which match rungs may apply without a click? | (a) EXACT rungs 0–3 apply on "apply"; CANDIDATE (repaired composites, names) and UNMATCHED wait for a person — some rows wait · (b) also repaired composites — faster, but a wrong repair lands money on the wrong customer · (c) everything waits for a click — safest, ~1,267 clicks on the first run | **a** |
| **F2** | When a customer is linked to PEAK, does the case's system payment status follow PEAK? | (a) yes — PEAK facts drive `payment_status_system`; a person's adjustment ends with a logged event (this **partly supersedes v2.6 §3.6 again**, recorded at the code site) · (b) no — PEAK shown beside, status unchanged; the manager's "rule" is not enforced · (c) both values shown, status unchanged — twice the density | **a** |
| **F3** | OD-02: may a PEAK receipt (number + date in the report) be recorded as an allocation for the invoices it names? | (a) yes, for PEAK-sourced receipts only; slip receipts stay unallocated. The receipt is marked allocated and the invoice's PEAK "awaiting" amount is served beside the engine's arrears; **moving the engine's own arrears figure needs the allocation engine (OD-02) and is priced separately, not in Round A** · (b) no — the position moves, the arrears do not, and the weekly cash/ratio caveat stays | **a** |
| **F4** | Where PEAK facts live | (a) `landing.peak_invoice` + `records.identity_link`, survive a deploy — needs a migration · (b) per-session run only — gone on restart, and every tester re-uploads | **a** |
| **F5** | The 13-digit id on the report | (a) used in-run only, never stored — no cross-run matching by it · (b) stored as a salted hash in the link register — cross-run matching, PDPA exposure limited to a hash · (c) stored plain — simplest, a PDPA decision you would have to own | **a** |
| **F6** | crm.lead run mode | (a) NEW_ONLY default, OVERWRITE under ขั้นสูง, proposals listed · (b) keep today's overwrite — the manager's ask is not met · (c) NEW_ONLY with no proposals — cheaper, differences invisible | **a** |
| **F7** | Attachment store and retention | (a) Postgres `records.attachment`, 10 MB/file, 5/note, kept while the case exists — needs a migration; fine for UAT · (b) GCS bucket now — needs provisioning, signed URLs, IAM; production-shaped · (c) session memory — lost on restart, testers lose evidence | **a** now, b at go-live |
| **F8** | Malware guard level | (a) format rules + quarantine label + optional ClamAV port · (b) format rules only — no path to a real scanner · (c) require ClamAV — uploads refuse until it is provisioned | **a** |
| **F9** | Phone override | (a) real number stored in `records`, any officer may edit with a reason, audited; staging is in Singapore (PDPA flag stands) · (b) Owner/Manager edit only · (c) not stored — copy from the sheet only, the ask is not met | **a** |
| **F10** | The notices | (a) one folded "หมายเหตุระบบ" per screen; refusals stay reachable · (b) delete — needs a written supersession of contract §3 and loses the CF1/OD-04 record on screen · (c) keep | **a** |
| **F11** | Reminders home | (a) `/reminders` now, the calendar later · (b) delete the batch view — the act stays on the case page only · (c) keep on Today | **a** |
| **F12** | Case header | (a) figures only; explanations fold to a bottom section; "editable" = settings link + in-place case fields · (b) side sheet — new component · state what else "editable" should mean | **a** |
| **F13** | Allow-list admin | (a) DB-backed, env as seed, Owner/Manager invite — migration + merge rule · (b) keep the JSON secret — the ask is not met | **a** |
| **F14** | Display name | (a) each person sets their own; fallback e-mail user part · (b) Manager sets names — more admin | **a** |
| **F15** | Weekly definitions | (a) as in WP12's table · change any definition here | **a** |
| **F16** | Calendar scope | (a) read + move a next action + personal notices · (b) read-only · (c) recurrence, sharing, e-mail — not now | **a** |
| **F17** | Test edits | authorise the measured price in §5 as edits **35–39**; 17 stays reserved | — |
| **F18** | Branch | (a) a worktree off HEAD with its own test database (the shared-branch rule); **the staged weekly work on design-team is committed first — say whose commit it is** · (b) build on the shared checkout | **a** |
| **F19** | PEAK API door | (a) port + honest "not configured / untested" state now, adapter when PEAK's endpoint is verified · (b) nothing until then · (c) code against guessed endpoints — no | **a** |

---

## 5. Test price (measured on the tree, 2026-09-15)

Rule of the house: a pinned test is never edited without an authorised number; adding tests is
free. These are the pins the work would touch. Each is **re-measured before it is spent**.

| Pin | File | What moves it | Price |
|---|---|---|---|
| Reminders strip on Today | `Today.test.jsx:270-280` (1 test), `api.test.js` (1 line) | WP7 moves the block to `/reminders` | 1 test re-targeted, 1 line |
| Tier strip anchors, hero ladder line, offsets conflict | `Today.test.jsx`, `round4.test.jsx` — 13 lines | WP7 filter bar + fold; **zero** if the folded children keep their test ids (house rule: children always render, `hidden` closes) — the tier anchors are the real cost | ≤ 13 lines, measured |
| `getByRole('status')` | `InvoicePipeline.test.jsx:102` | WP7 fold — kept by leaving that notice's role inside the fold | 0 |
| Density caps 104 / 123 | `density.test.jsx` | WP3 +2 lines, WP8 −(details) , WP9 +copy/edit ≈ +4 | measured; expected at or under cap |
| Today chrome 112 / row 31 / page 1,662 | `today-density.test.jsx` | WP7: −3 blocks, +filter bar | measured; expected under |
| Seven-key CLOSED-row diff | `test_round4.py:775` | WP1 adds `payment_position` to **both** rows | 0 |
| e2e 31 checks | `e2e_check.py` | additive keys only | 0 |

Backend and frontend counts are re-measured in the plan's Task 0 (the recorded figure always
lags the branch).

---

## 6. Build order and estimates

| Round | Work packages | Estimate |
|---|---|---|
| **A — journey and system** | WP1 → WP2 → WP3 → WP4 | 9–11 working days |
| **B — UI** | WP7 → WP8 → WP9 → WP10 → WP11 → WP12 | 6–8 days |
| **C — extras** | WP5 → WP6 | 4–5 days |

Round A is tasked in full in note 11. Rounds B and C are listed there as task headers (files,
interfaces and tests named) and are cut to step level in notes 12 and 13 after Round A lands and
the rulings are in, because WP7 and WP12 depend on what WP1 serves.

---

## 7. Risks and what stays out

- **PDPA.** Real phone numbers (F9), attachments carrying documents, and the 13-digit id (F5)
  are all new personal data in a Singapore-region database. The design keeps each behind a
  ruling and stores nothing it was not told to.
- **PEAK's API is unverified.** WP5 builds a port and a truthful state, not a client.
- **Two registers of PTP/review/issue** (memory note) stay as they are; the calendar reads both
  and names which.
- **Shared branch.** Other sessions commit to `design-team` mid-run; the staged weekly work is
  someone's uncommitted build. F18.
- **The platform branch** is moving state to per-workspace documents (Stage 3a). New durable
  tables here go in a `records` schema, not `app`, so they neither collide with that move nor get
  truncated by the test harness on principle.
- Out: OCR, PEAK writes beyond DRAFT_ONLY, calendar sharing/recurrence, hiding screens by role,
  a permission registry.

---

## 8. สรุปภาษาไทย (สำหรับส่งต่อผู้จัดการทีมทวงหนี้)

- **ข้อมูล PEAK ไม่ตรงกับ Odoo:** ตรวจไฟล์ส่งออกใบแจ้งหนี้ PEAK แล้ว 7,999 บรรทัด พบว่ารหัสผู้ติดต่อ
  (VC/VRC/VL) ตรงกับ `crm.lead` ของ Odoo ถึง 95% ที่ไม่ตรงคือ "สมุดลูกหนี้" ที่มาจากชีต และรหัสที่พิมพ์
  รวมสองสัญญาไว้ด้วยกัน (เช่น `VL0010239,VC0010687`) ซึ่งคือกรณีเปลี่ยนแพ็กเกจแล้วไม่ลบสัญญาเก่า
  ระบบใหม่จะจับคู่ตามลำดับกฎ (รหัส CRM 11 หลัก → รหัส V → ผ่าน Odoo → เบอร์โทร) แถวที่จับคู่ไม่ได้
  จะแสดงให้คนกดผูกเอง และระบบจำไว้ใช้ครั้งต่อไป ไม่เดา
- **สถานะการชำระรายเดือน** จะอ่านจากใบแจ้งหนี้ PEAK (จ่ายแล้ว / เกินกำหนด / รอชำระ) ต่อรอบ M n/N
  และแต่ละเคสจะบอกว่า **จ่ายแล้วกี่ใบ ค้างกี่ใบ** ทั้งบนหน้าเคสและในหน้าต่างบันทึกการติดต่อ
- **นำเข้าจาก `crm.lead`** จะเพิ่มเฉพาะลูกค้าใหม่ ไม่แตะสัญญาเดิม ส่วนที่ต่างกันจะแสดงเป็นรายการให้ดู
- **บันทึกการติดต่อ** เพิ่มได้หลายข้อความ แนบไฟล์ได้ (png svg csv xlsx pdf docx) ผ่านการตรวจไฟล์
  ก่อนเก็บ และมีประวัติทั้งหมดอยู่ท้ายหน้าต่าง เลื่อนดูได้
- **หน้าวันนี้/บอร์ด** ย้ายรายการเตือนออก เปลี่ยนป้ายสถานะและทีมเป็นตัวกรองตาราง ย้ายข้อความแจ้ง
  ไปไว้ในบรรทัดพับได้ **หน้าตั้งค่า** ปรับเป็นฟอร์ม และเพิ่มแท็บผู้ใช้สำหรับเชิญอีเมลและตั้งชื่อที่แสดง
- **ปฏิทินแจ้งเตือน** และ **การดึงข้อมูลจาก PEAK API** อยู่ในรอบถัดไป
