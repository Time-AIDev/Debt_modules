# Handoff: Volt Debt console redesign (Final v2)

## Overview

A redesign of the Volt Debt officer console covering twelve screens: Overview (team
performance), Today, Calendar, Customers / Work book, Reviews, Pre-installation
invoices, Receipts & PEAK, NPL & recovery, Reports, Settings, Data sources, Action
log, plus Login.

Three things change structurally against today's build:

1. **Every operational screen is a split view** — a list of that screen's items on the
   left, and **that screen's own work on the right** (release conditions, PEAK gates,
   NPL paths, review decision), instead of every row resolving to the customer record.
2. **Overview is a team performance dashboard** — KPI cards and charts lead, with a
   per-officer performance table. It no longer lists individual customers.
3. **Settings is role-gated and lock-aware**, and shows the officer view and the
   manager view of each value side by side.

Plus two cross-cutting additions: a **TH / EN language switch**, and a **⌘K command
palette**.

## About the design files

`Volt Debt - Final v2.dc.html` in this bundle is a **design reference written as a
single self-contained HTML prototype**. It is not production code and should not be
copied into the app. The task is to **recreate these designs inside the existing
`frontend/` React + Vite app**, using its established patterns: `react-router-dom`
routes, `api.js` for data, `prefs.jsx` for preferences and `useT()` for copy, the
existing components in `src/components/`, and the tokens in `src/tokens.css`.

Open the file in a browser to interact with it. Everything in "Interactions" below is
live in the prototype.

## Fidelity

**High fidelity.** Colours, type, spacing, row heights, chip styles and copy are final
and are taken from `src/tokens.css` (IBM Plex Sans / IBM Plex Sans Thai, amber brand,
the 5-step `--viz-sev-*` severity ramp). Recreate pixel-for-pixel using the existing
token variables — do not introduce new colour values except the dark-theme additions
listed under "Design tokens".

All data in the prototype is sample data. Every figure must come from the existing API.

---

## Screens

### Shell (`src/components/Shell.jsx`)

Keep the current rail: full-height, dark (`--rail` `#101318`), VOLT lockup top-left,
one unlabelled Dashboard row above three labelled groups (งานของฉัน / งานที่ต้องตรวจ /
ระบบ), per-row counts, live attainment strip under the wordmark, caseload footer,
collapse control. Changes:

- Rail width **248px** normal, **204px** narrow (and at viewports under 1180px),
  **60px** collapsed (icons only, count badges become corner dots).
- The collapse chevron is **inside** the rail: absolutely positioned `top:13px
  right:10px` when open; stacked under the mark when collapsed. The header reserves
  `padding-right:40px` when open so it can never cross the wordmark.
- The nav needs `min-height:0` on the scroll container, or the caseload footer rides
  over the last rows.
- Rail rows: 34px high, 8px radius, active row `rgba(255,255,255,.1)` with
  `inset 3px 0 0 var(--brand-500)`, label 13px (600 when active).
- Top bar: 52px min-height, `flex-wrap`, holding — search button (opens the palette,
  ⌘K hint), breadcrumb (hidden under 1100px), environment chip, **View** popover,
  identity menu. Under 1100px the search button flexes and the breadcrumb is dropped;
  do not let the bar overflow a fixed height.
- **View popover** (extend `PrefControls.jsx` / `Popover.jsx`): Row density
  (Compact 36px / Comfortable 44px), Theme (Light / Dark), Rail width (Normal /
  Narrow), **Language (ไทย / English)**. All four persist via `writePref`.
- **Identity menu**: signing role (Officer / Supervisor / Manager / Owner) + sign out.
  The chosen role really gates the UI (see Settings, Reports, Pre-installation).
- **Context tab strip** under the top bar, 40px: current screen + up to four recently
  opened records, each with a severity dot. Clicking one returns to that record.

### Overview — team performance (`src/screens/Dashboard.jsx`)

Purpose: how the **team** is doing. No individual-customer list.

- Header card: eyebrow ผลงานทีม, h1 ภาพรวมทีมติดตามหนี้, business day + officer count,
  amber 4px left border; a field strip beneath it (total arrears, debtors owned, team
  queue today, PTP kept rate, NPL count).
- **Four KPI cards** (4-up; 2-up under 1100px, 1-up under 620px): receipts vs target
  62.4%, PTP kept rate, contact success rate, DSO. Each is label / 27px figure /
  6px progress bar / sub-figure / note.
- **Cumulative receipts vs previous months** — 5 bars, current month in `--brand-500`.
- **NPL roll rate** — rolled in / rolled out / still in NPL, with counts and amounts.
- **Arrears by aging band** — 5 bars on the severity ramp.
- **Receipts vs target** — three progress rows (all in / installments / cash-project).
- **Performance by officer** — table: officer (with today's queue under the name),
  cases, arrears, receipts (figure + 64px bar), contact rate, PTP kept, NPL, and a
  **Team total** row in 700 weight. Contact rate and PTP colour to
  `--status-current` / `--status-overdue` against the team bar.
- **What to do next** — four queue counts linking to Reviews / Pre-installation /
  Receipts / NPL.

### Today, Customers / Work book (`Today.jsx`, `WorkBook.jsx`) → customer record

Split view. Left list groups rows under **sticky collapsible tier headers** (Today:
PTP due today / broken PTP / next action due; Work book: 90+ / 30–89 / under 30 /
current), each header carrying a severity square and a count. Rows: 54px compact /
66px comfortable, 3px severity bar at the left edge, name + sub, an **aging heat
strip** (width = DPD/120), arrears and DPD right-aligned. Selected row gets
`--brand-050` and an inset amber bar. List header has a filter select and a
**sort toggle** (money at risk / given order), defaulting to money at risk.

Right side is the customer record: severity-coloured 4px left border, status and
aging-band chips, 22px name, risk score, primary **Log contact**, Call (disabled with
a reason when no real number is on file), LINE; a six-cell field strip (arrears,
outstanding, debt age, estimated penalty, officer, next action); an **aging path**
(Salesforce-style chevrons, current step in amber) with the suggested next ladder step
and a **Do this step** action. Five tabs: Case overview, Invoices and receipts,
Contact history, Schedule (24-month grid), Issue tickets.

### Reviews (`src/screens/ReviewQueue.jsx`)

Right side is **the decision**, not the customer: request header with age chip and the
decision deadline, attached evidence list, **Reject / Approve**. Both open a drawer;
**rejection requires a reason**. Once decided the header shows the outcome chip and the
reason on record. A side card carries the debtor (arrears, debt age) and an
**Open customer case** link.

### Pre-installation invoices (`src/screens/InvoicePipeline.jsx`)

Right side is the **release gate**: progress chip (`n of 3 passed`) and a bar, then the
three conditions (contract signed, down payment received, issuing company resolved),
each a row with a state chip and an **Attach evidence** action (drawer with a drop zone
and a note). **Release invoice** is only enabled at 3/3 **and** for Manager or above —
a refusal toast explains which rule blocked it. Releasing creates a PEAK draft only.

### Receipts & PEAK (`src/screens/Payments.jsx`)

Right side is the **document's gates**: draft created in PEAK → AR approves → allocate
against arrears, each row showing passed / current / not reached (refused renders red).
A refused document offers **Fix and resubmit**, which advances it to draft. Below:
allocation rows with per-line state, and the note that unallocated money does not
reduce on-screen arrears.

### NPL & recovery (`src/screens/Recovery.jsx`)

Right side is the **path choice**: NPV outstanding in the header, then three selectable
cards (Restructure / Settlement / System recovery) each with expected recovery computed
from NPV, its rate, and its caveat. **Confirm path** records it; Restructure routes to
manager approval when the signing role is below Manager. After confirmation the chosen
path's next steps appear.

### Reports (`src/screens/Reports.jsx`)

Weekly editions table: edition, period, received, contacts, kept/total PTP, status, and
a per-row action — **Publish** for a draft (Manager only; otherwise the button reads
"Manager only" and refuses), Download for a published edition. KPI charts live on
Overview, not here.

### Settings (`src/screens/Settings.jsx`)

**No list pane** — the settings table is the full width of the content area.

Each row is three columns (single column under 1100px):
1. Setting name + a **Locked · awaiting ruling** or **Editable** chip, its note, owner.
2. **Officer view** — the value as read-only text, labelled "Read only".
3. **Manager view** — a real input/select, `disabled` when the value is locked or the
   signing role is below Manager, with a note saying which applies.

The column matching the current signing role is highlighted in amber. Editing logs one
entry to the action log after a 900ms debounce, not per keystroke. A **Users and
permissions** card follows (name, e-mail, caseload, role chip, Edit rights — Manager
only).

Locked values are those awaiting a ruling; they cannot be changed here at any role.

### Calendar (`src/screens/Calendar.jsx`)

Month grid (7×5, 92px cells, today in `--brand-050` with an amber date badge, up to two
chips per day plus "+ n more", overdue chips in red) and a week list. Month/Week
segmented control. Next-action items offer **Move date**, whose drawer requires a new
date **and** a reason; moved items re-render on the new day with a "Moved" chip.

### Data sources (`src/screens/DataSourcesMigration.jsx`)

Field strip (which rung serves the work book, rows in registry, PEAK, Odoo), then the
**inbound source order** as four ranked rungs with the serving one marked amber. Import
card: drop zone, "report first" default on, **Check file** → inspection report
(readable / new / refused with reasons / file total) → **Land rows** (Manager only) →
receipt. Export card requires a reason and states that exports carry no phone or
e-mail column.

### Action log (`src/screens/AuditLog.jsx`)

Field strip (persistence, chain verification, source of the signing name), filters for
actor and act, then the table: time, actor **with a badge when the name was claimed or
came from the test account**, act, target, result. Every action taken anywhere in the
app prepends a row here.

### Login (`src/screens/Login.jsx`)

404px card, centred: logo, centred title and subtitle, Google button, "or" divider,
test-account fields (left-aligned), and the note that the test account is a shared
password whose acts are badged as such.

---

## Interactions & behaviour

| Behaviour | Detail |
|---|---|
| ⌘K / Ctrl-K | Opens the command palette; searches screens, customers, settings and commands; Esc closes. Extend `SearchCustomer.jsx`. |
| Row → record | Selecting a list row loads it on the right and adds it to the context tab strip (max 4, most recent first). |
| Log contact | Drawer: channel, outcome, **required** next action, date, note. Saving prepends to the contact timeline, toasts, and writes to the action log. Reuse `CaseContactDrawer.jsx`. |
| Review decision | Approve/Reject drawer; reject blocks on an empty reason. |
| Attach evidence | Per-condition drawer; flips that condition to passed. |
| Release invoice | Enabled only at 3/3 and Manager+. |
| NPL path | Select → Confirm; Restructure below Manager sends for approval instead. |
| Import | Three stages: idle → inspection report → landed receipt. Preview is the default; landing is Manager+. |
| Move a calendar item | Requires new date + reason. |
| Publish a report | Manager+ only. |
| Density toggle | Table row height 36px ↔ 44px. |
| Theme toggle | `data-theme="dark"` on `documentElement`. |
| Language toggle | TH ↔ EN across the whole UI. |
| Refusals | Every role or rule refusal shows a toast naming the rule, rather than hiding the control. |
| Toasts | Bottom-centre, dark, 3.2s. |

Responsive: under 1180px the rail narrows; under 1100px the breadcrumb is dropped, the
content grids collapse to fewer tracks and the settings row becomes one column; under
860px the list pane stacks above the content (max-height 340px). Nothing uses a fixed
height that holds text.

## State

Per screen: `lens` (active screen), `sel` (selected item per screen), `tab` (active case
tab), `closed` (collapsed tier headers), `sortRisk`, `recents`.
Preferences (persist via `prefs.jsx`): `dense`, `theme`, `railOpen`, `railNarrow`,
`lang`, `role`.
Work state (server-backed in the real app): saved contacts, review decisions, attached
evidence, released invoices, resubmitted PEAK documents, chosen NPL paths, import stage,
moved calendar items, published editions, setting values.
Transient: `palette`, `drawer` + `drawerKind` + `ctx` + `form`, `toast`.

## Design tokens

All light-theme values already exist in `src/tokens.css` — use them as-is:
`--ink-900 #050505` … `--ink-400 #9ca3af`; `--surface-0 #ffffff`, `--surface-50
#f9fafb`, `--surface-100 #f3f4f6`; `--line-default #e5e7eb`, `--line-strong #818995`;
severity ramp `--viz-sev-1 #86b6ef`, `-2 #5598e7`, `-3 #2a78d6`, `-4 #1c5cab`,
`-5 #0d366b`; `--brand-500 #f2b705`, `--brand-050 #fff7dc`; status pairs
current `#15803d`/`#dcfce7`, pending `#1d4ed8`/`#dbeafe`, overdue `#b91c1c`/`#fee2e2`,
held `#4b5563`/`#f3f4f6`; band pairs early `#854d0e`/`#fef9c3`, mid `#9a3412`/`#ffedd5`,
npl `#111827`/`#e5e7eb`; open-ruling accent `--reg-open #5b21b6` on `#f5f3ff` with
`#ddd6fe` borders; rail `#101318`, rail ink `#8b93a1`, rail line `#232830`.

Type: IBM Plex Sans + IBM Plex Sans Thai. 22px/600 page titles, 20px/600 record titles,
14px/600 section headings, 13px body, 12–12.5px secondary, 11–11.5px notes,
10–10.5px/600 uppercase eyebrows with `.06–.08em` tracking. `font-variant-numeric:
tabular-nums` on every figure.

Geometry: 10px card radius, 7px control radius, 4–5px chip radius, 1px borders,
4px severity left border on record headers, 14px card padding, 14px grid gaps.

**Dark theme is new** — add a `[data-theme="dark"]` block to `tokens.css` overriding the
same names: `--surface-0 #16181d`, `--surface-50 #1b1e24`, `--surface-100 #0f1115`,
`--line-default #2b3038`, `--line-strong #6b7482`, `--ink-900 #f5f7fa` … `--ink-400
#5f6875`, severity ramp inverted (`-1 #184f95` … `-5 #cde2fb`), status backgrounds
darkened (`#0f2f1c`, `#0e2440`, `#3a1518`, `#23272e`), `--brand-050 #3a2f08`, rail
`#0b0d11`. Keep `--brand-500` unchanged. Set `color-scheme` in both blocks.

## Internationalisation

The prototype proves the switch end to end and can be mined for the English copy, but
**implement it through the existing `useT()` / `i18n-*.js` mechanism**, not the
prototype's lookup table. Two lessons from building it, both worth carrying over:

- Never compose a sentence and then try to translate the whole string — branch on
  language at composition time, or assemble from translated fragments. Counts, days and
  amounts appear inside most of this UI's sentences.
- Customer names, document ids (RV-, SO-, IV-, RC-, NPL-, WK-, IMP-) and lot codes stay
  as they are in both languages.

Internal ruling and policy codes (CF1, OD-02, OD-04, OD-31, SVC-37, DEBT-INV-0422,
DEBT-ACC-0403, DEBT-IAM-0403, C5/R12, reminder_offsets_days) were **removed from all
user-facing copy** — the meaning is stated in plain words instead. Keep them in the
code, the API and the action log; keep them off the screens.

## Assets

`assets/volt-logo.png` — the VOLT mark supplied by the client (447×447, amber ground,
black wordmark, red rays). The prototype crops it with an offset `<img>` inside an
`overflow:hidden` box to get the wordmark lockup (91×40 in the rail, 171×75 on login)
and uses the whole tile at 34px when the rail is collapsed. In the app, prefer
exporting a proper lockup SVG and the existing `rail__bolt` mark rather than shipping
the crop.

## Files in this bundle

- `Volt Debt - Final v2.dc.html` — the full interactive prototype, all twelve screens.
- `KICKOFF_PROMPT.md` — the brief to paste into Claude Code to start the build.
- `assets/volt-logo.png` — brand mark.
- `screenshots/` — every screen at 1440px:

| File | Screen |
|---|---|
| `01` | Overview, first paint |
| `02` | Overview — team performance |
| `03` | วันนี้ / Today → customer record |
| `04` | ปฏิทิน / Calendar — month grid |
| `05` | ลูกค้า / สมุดงาน — Work book |
| `06` | รอตรวจ / Reviews — decision panel |
| `07` | ใบแจ้งหนี้ก่อนติดตั้ง — release conditions |
| `08` | เงินเข้าและ PEAK — document gates |
| `09` | NPL และการเรียกคืน — path choice |
| `10` | รายงาน / Reports — weekly editions |
| `11` | ตั้งค่า / Settings — lock model, both role columns |
| `12` | แหล่งข้อมูล / Data sources |
| `13` | บันทึกการใช้งาน / Action log |
| `14` | Log-contact drawer |
| `15` | Login |

## Suggested implementation order

1. Shell: rail geometry and collapse fix, top bar, View popover (density, theme, rail
   width, language), context tab strip, command palette.
2. `tokens.css`: dark-theme block.
3. Overview as the team dashboard (new `/dashboard` content + a per-officer endpoint).
4. The split-view pattern + the customer record, then Reviews, Pre-installation,
   Receipts, NPL on top of it.
5. Settings (lock model + role gating + users), Reports publish flow.
6. Calendar move-with-reason, Data sources import stages, Action log badges.
7. Language pass through `i18n-*.js`.

## Acceptance checks

- Every rail row opens its own work panel; no screen resolves to the customer record
  unless it is Today or the work book.
- A locked setting cannot be edited at any role; an unlocked one cannot be edited below
  Manager; both states are visible simultaneously.
- Release, Land rows and Publish refuse below Manager **with a toast naming the rule**.
- Reject and Move date refuse to save without a reason.
- Overview contains no individual-customer list.
- Switching language leaves no Thai in the interface except customer names and ids.
- At 900px wide nothing overlaps: rail narrows, breadcrumb drops, grids collapse, list
  stacks.
