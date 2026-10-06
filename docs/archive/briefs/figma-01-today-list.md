# UI brief — 01 Today List

> **SUPERSEDED AS BUILD TARGET (2026-08-30).** This brief documents Figma "Product UI v0.1" and is kept as the record of that design. The rebuild's screen set is briefed in `docs/archive/briefs/screens-v2/`; the deck extraction `docs/product/workflow-v20-epc-spv.md` and `docs/product/user-journey.md` govern the new screens. In particular, R9 (Grilling 2026-08-30) inverts this screen's layout: a next-call hero card comes first and the status board is demoted below the table.

figms

Source: Figma file `dAIFet044WF2P0FbUJfoT7`, page "Volt Debt — UI v0.1", frame **`3:2` "01 · Today List"** (1440 × 1616).
Overlay layer documented separately: **`55:2` "Popover/Columns — overlay state, hide this layer to see the board beneath"**.
Extracted 2026-08-26. Every literal, number and measurement below was read out of the Figma node tree or measured off a 1:1 render — nothing here is invented.

---

## 0. Read this first — the words and codes on this screen

Written for someone who has never seen the Volt debt app. Nothing in this section is decoration; the screen is unreadable without it.

| Term on screen | What it means |
|---|---|
| **Today List** | The officer's queue for today: the accounts the system says to work on. Generated overnight (the screen shows the generation timestamp). |
| **Officer** | The collections agent using the screen. Here: "Nok". One officer owns a customer — see the table footer rule. |
| **Owner** | The team lead / supervisor. The Owner controls the shared column set on the status board; the officer controls only their own show/hide/order. |
| **Arrears** | The money currently past due on the contract. The only money figure drawn on this screen. |
| **DPD** | Days Past Due. On board cards it is written as a chip, e.g. `47 d`; in the table it is a bare number in the `DPD` column. |
| **P1 / P2 / P3** | Priority band of the account. P1 is most urgent. Rendered as a coloured dot plus the literal text. |
| **Stage** | Where the account sits on the recovery ladder: Reminder → Demand letter → Restriction due → etc. Also carries hold states (Permit hold) and claim states (Claim pending). |
| **Promise** | A customer's commitment to pay on a date. "Promise due" = that date has arrived. |
| **Claim** | A recovery claim lodged with a third party (e.g. insurer/guarantor). "Claim pending" = lodged, not yet confirmed. |
| **Blocked** | Work that cannot proceed today for a legal/consent/document reason — not a payment state. A block is either **Approved** by the Owner or **Pending Owner review**. |
| **Held** | Filter/stage wording for an account under a hold (e.g. `Permit hold`). Note: *Held* (a stage) and *Blocked* (a board column) are different taxonomies and their counts do not match — see §4.5. |
| **Contact rate** | The share of the officer's caseload actually contacted. The screen states a block that is *pending* approval still counts against it. |
| **Natural person / Juristic** | Thai legal-entity classes: an individual vs a registered company. Juristic customers can have a "signatory missing" exception. |
| **C-YYYY-NNNN** | Contract number format, e.g. `C-2024-0188`. |
| **฿** | Thai baht. All amounts are baht, thousands-separated with commas, no decimals. |

**House rule that governs colour:** amber `#f2b705` is the Volt **brand** colour. It is used for the wordmark bolt, the primary button fill, the active nav row tint, the selected group-by option tint, and the caseload bar. It is **never** used to mean a status. Status meaning is carried only by the four status pairs (current/green, pending/blue, overdue/red, held/grey).

---

## 1. Frame, top bar, nav and main — pixel layout

### 1.1 Frame
- `3:2` — **1440 × 1616**, origin (0,0). Desktop only; no responsive variants exist in this file.
- Page background behind Main: `surface/100 #f3f4f6`.

### 1.2 Three-part split

| Region | Node | Position | Size | Background |
|---|---|---|---|---|
| Top bar | `3:3` | (0, 0) | **1440 × 56** | `surface/0 #ffffff`, 1px bottom border `line/default #e5e7eb` |
| Nav (left rail) | `3:15` | (0, 56) | **232 × 1560** | `surface/0 #ffffff`, 1px right border `#e5e7eb` |
| Main | `4:2` | (232, 56) | **1208 × 1560** | `surface/100 #f3f4f6` |

Main has a **24 px gutter on all sides**, so its content column is **1160 px** wide, running from absolute x = 256 to x = 1416.

### 1.3 Top bar internals (`3:3`)
Flex row, `padding: 0 20px`, `gap: 16px`, `align-items: center`.

| Child | Node | x, y (in bar) | Size | Spec |
|---|---|---|---|---|
| Wordmark | `3:4` | 20, 16 | 109 × 24 | flex row, gap 8 |
| ├ Bolt glyph | `3:5` | +0, +2 | **20 × 20** | SVG lightning, amber `brand/500 #f2b705` |
| ├ "VOLT" | `3:7` | +28, +0 | 38 × 24 | Heading/16 600, `ink/900 #050505` |
| └ "Debt" | `3:8` | +74, +0 | 35 × 24 | Heading/16 600, `ink/500 #6b7280` |
| Spacer | `3:9` | 145, 0 | 851 × 56 | `flex: 1` |
| Search | `3:10` | 1012, 11 | **280 × 34** | bg `surface/50 #f9fafb`, 1px `#e5e7eb`, radius **6**, padding 12/7 |
| └ placeholder | `3:11` | +12, +8 | 210 × 18 | Small/13 400, `ink/500 #6b7280` |
| Officer | `3:12` | 1308, 14 | 112 × 28 | flex row, gap 8 |
| ├ Avatar | `3:13` | +0, +0 | **28 × 28** | circle, fill `brand/050 #fff7dc`. No initials, no photo. |
| └ Name | `3:14` | +36, +5 | 76 × 18 | Small/13 400, `ink/700 #374151` |

### 1.4 Nav internals (`3:15`)
Six nav rows, each **208 × 38** at x = 12, pitch **40 px** (y = 16, 56, 96, 136, 176, 216).
Row spec: flex row, `padding: 9px 12px`, `gap: 8px`, radius **6**; label — flex-1 spacer — count.

- **Active** (Today List): bg `brand/050 #fff7dc`; label BodyStrong/14 500 `ink/900 #050505`; count Caption/12 500 `ink/700 #374151`.
- **Inactive**: transparent bg; label BodyStrong/14 500 `ink/600 #4b5563`; count Caption/12 500 `ink/500 #6b7280`.
- Reports has **no** count.

Below the rows: a 208 × 16 spacer (`3:39`, y = 256), then the **Workload card** `3:40` at (12, 274), **208 × 100**:
- bg `surface/50 #f9fafb`, 1px `#e5e7eb`, radius **8**, `padding: 12px`, flex-column `gap: 6px`.
- "Your caseload" — Caption/12 500 `ink/500`.
- "46 of 200 customers" — BodyStrong/14 500 `ink/800 #111827`.
- "Contact rate measured on 44" — Caption/12 500 `ink/500`.
- **Cap bar** `3:43`: track **180 × 6**, radius 3, `line/default #e5e7eb`; fill `3:44` **166 × 6**, radius 3, `brand/500 #f2b705`. See §4.2 — the fill width is hard-coded and is **not** derivable from either printed number.

### 1.5 Main stack (y measured inside `4:2`; add 56 for absolute)

| Block | Node | y | Size | Abs. y span |
|---|---|---|---|---|
| Page header | `4:3` | 20 | 1160 × 54 | 76 – 130 |
| Filters | `4:12` | 94 | 1160 × 30 | 150 – 180 |
| Status board | `53:2` | 144 | 1160 × 604 | 200 – 804 |
| Work table | `6:2` | 768 | 1160 × 768 | 824 – 1592 |

Vertical rhythm between blocks: **20 px**. Bottom gutter 24 px.

**Page header** `4:3` — flex row, gap 16, items-center, bg white:
- Titles `4:4`: flex-column gap 4. "Today List" Display/24 600 `ink/900`; subtitle Small/13 400 `ink/500`.
- Spacer `4:7` flex-1, h 8.
- `Button/ghost` "Export" `4:8` — 71 × 38 at x 932; white, 1px `#e5e7eb`, radius 6, padding 9/14, label BodyStrong/14 500 **`ink/700 #374151`**.
- `Button/primary` "Start next contact" `4:10` — 141 × 38 at x 1019; bg `brand/500 #f2b705`, **no border**, radius 6, padding 9/14, label BodyStrong/14 500 **`ink/900 #050505`**.

**Filters** `4:12` — a 30 px-tall row of five pill chips, gap 8:
`All 18` (x 0, w 58) · `Overdue 11` (x 66, w 89) · `Promise due 4` (x 163, w 110) · `Claim pending 2` (x 281, w 122) · `Held 1` (x 411, w 62).

**Status board panel** `53:2` — white card, 1px `#e5e7eb`, radius **10**. Internal bands (y within panel):
- `53:3` header row, 0 – 50, bg `surface/50 #f9fafb`, 1px bottom border, padding 10/14, gap 10.
- `64:2` Owner-changed notice, 50 – 86, bg `status/pendingbg #dbeafe`, 1px bottom border, padding 9/14, gap 10.
- `53:14` Columns area, 86 – 570, bg `surface/0 #ffffff`.
- `53:98` footer note, 570 – 604, bg `surface/50 #f9fafb`, 1px top border.

**Board column grid** (inside `53:14`, first column at x = 14, y = 12): column width **186.4**, pitch **196.4** (gap 10).
`To contact` x 14 · `Contacting` x 210.4 · `Awaiting reply` x 406.8 · `Blocked` x 603.2 · `Done today` x 799.6 · `Add a column` x 996 (width **150**).
Column heights are content-driven: 124 / 124 / 124 / **460** / 140 / 32.

**Work table panel** `6:2` — white card, 1px `#e5e7eb`, radius **10**:
- Head row `6:3`, 0 – 36, bg `surface/50 #f9fafb`.
- 12 body rows, 58 px each, y = 36, 94, 152, 210, 268, 326, 384, 442, 500, 558, 616, 674.
- Footer `6:270`, 732 – 768, bg `surface/50 #f9fafb`, padding 10/16, gap 12.

**Table column geometry** — row is a flex row with `padding: 10px 16px` and `gap: 12px`; every cell is a fixed-width `Td`:

| # | Td width | x (in row) | Heading | Align |
|---|---|---|---|---|
| 1 | 52 | 16 | *(none — priority)* | left |
| 2 | 250 | 80 | `CUSTOMER` | left |
| 3 | 130 | 342 | `CONTRACT` | left |
| 4 | 120 | 484 | `ARREARS` | **right** |
| 5 | 52 | 616 | `DPD` | **right** |
| 6 | 140 | 680 | `STAGE` | left |
| 7 | 130 | 832 | `LAST CONTACT` | left |
| 8 | 170 | 974 | *(none — action)* | **right** |

Widths + gaps + padding sum to exactly 1160.

### 1.6 Popover placement (`55:2`)
Absolute **(1046, 246)**, **360 × 773**, so its bottom edge is y = 1019.
- Its right edge (1406) sits **10 px inside** the status-board panel's right edge (1416) — it is aligned to the panel, **not** to the "Edit columns" button (whose right edge is 1346).
- Its top (246) is **6 px below** the "Edit columns" button's bottom (240), which means it overlaps the panel header band by 4 px.
- It is the last child of the frame, so it paints above Main. **There is no scrim** — the board and table around it are at full contrast.

---

## 2. Components and their states

### 2.1 Shared primitives

| Component | Spec | States present in this frame |
|---|---|---|
| `Button/primary` | bg `brand/500 #f2b705`, no border, radius 6, label `ink/900` | 38 px tall (page header, padding 9/14, BodyStrong/14) and 32 px tall (popover, padding 7/12, Label/13). Only two on the screen: "Start next contact", "Apply". |
| `Button/ghost` | bg `surface/0 #ffffff`, 1px `line/default #e5e7eb`, radius 6, label `ink/700 #374151` | Three sizes: 38 px (padding 9/14, BodyStrong/14 — "Export"), 30 px (padding 6/11, Label/13 — "Edit columns", table row actions), 32 px (padding 7/12, Label/13 — "Reset"). |
| `Button/disabled` | bg `surface/100 #f3f4f6`, **no border**, radius 6, padding 6/12, label Label/13 500 `ink/400 #9ca3af` | One instance: "Contacted today" (table row 3). |
| `Chip` (filter) | pill, 30 px tall, padding 6/12, Label/13 | **Selected**: bg `ink/900 #050505`, label and count both `surface/0 #ffffff`. **Unselected**: bg white, 1px `#e5e7eb`, label `ink/600 #4b5563`, count `ink/500`. |
| `Badge` (table stage) | radius 4, `padding: 3px 8px`, Caption/12 500 | overdue `#fee2e2`/`#dc2626`; pending `#dbeafe`/`#2563eb`; held `#f3f4f6`/`#6b7280`. |
| `Chip` (card DPD) | radius 4, `padding: 2px 6px`, Caption/12 500 | overdue `#fee2e2`/`#dc2626`; neutral `#f3f4f6`/**`#374151`** (note: `ink/700`, *not* the `#6b7280` used by table badges). |
| `Select/Group by` | white, 1px `#e5e7eb`, radius 6, padding 6/11, gap 10; value Label/13 500 `ink/900`, affordance Caption/12 500 `ink/500` | Shown with value "Work today" and the affordance word "**open**". **There is no chevron glyph** — the affordance is the literal word. |
| `Toggle` | 28 × 16 pill, radius 8, white knob | **On**: track `status/current #16a34a`, knob right. **Off**: track `line/default #e5e7eb`, knob left. |
| Priority dot | circle | P1 `#dc2626` · P2 `ink/500 #6b7280` · P3 `ink/400 #9ca3af`. **6 px** on board cards, **7 px** in table rows. |

> **Icon inventory — the design is deliberately icon-light.** The only vector art in the whole frame is: the 20 px wordmark bolt, the 28 px officer avatar circle, the priority dots, and the toggle pills. There is **no** search magnifier, **no** select chevron, **no** drag-handle glyph (the handle is the literal word `drag`), **no** close "×" (it is the literal word `close`), and **no** row-expand caret. Do not add icons the design does not have.

### 2.2 `Board column` (`Col/*`)
Flex-column, `gap: 8px`.
- **Header** — full width × 32, radius **6**, `padding: 7px 10px`, gap 8; name flex-1, count right. Type Label/13 500 both sides. Colour is per-column semantic:
  - `To contact` — bg `surface/100 #f3f4f6`, text `ink/700 #374151` (neutral)
  - `Contacting`, `Awaiting reply` — bg `#dbeafe`, text `#2563eb` (`status/pending`)
  - `Blocked` — bg `#fee2e2`, text `#dc2626` (`status/overdue`)
  - `Done today` — bg `#dcfce7`, text `#16a34a` (`status/current`)
- **Optional sub-line** (Blocked only, `60:2`): 16 px tall, Caption/12 500 `ink/600 #4b5563`, sits between header and first card.
- **Add-a-column placeholder** (`53:96`): 150 × 32, 1px **dashed** `#e5e7eb`, radius 6, padding 7/10, label Label/13 500 `ink/500`.

### 2.3 `Board card` (`Card/<customer>`)
bg `surface/0 #ffffff`, 1px `line/default #e5e7eb`, radius **6**, `padding: 9px 10px`, flex-column `gap: 5px`.

Rows, in order:
1. **Identity row** — gap 6: priority dot (6 px) · customer name BodyStrong/14 500 `ink/900` (flex-1) · priority code Caption/12 500 `ink/500`.
2. **Money row** — gap 6: **arrears** Small/13 400 `ink/800 #111827` (flex-1) · DPD chip.
3. **Note line** — Caption/12 500, full width, wraps to 2 lines when long. Colour is semantic:
   - `ink/500 #6b7280` — neutral progress ("Demand letter sent 22 Aug", "Dialling now", "Claim 4 d unconfirmed", "Customer in hospital, family asked us to stop")
   - `status/overdue #dc2626` — a problem ("No signatory on file", "Permit awaited, clock running", "Still counted in your contact rate until approved")
   - `status/current #16a34a` — a good outcome ("Contacted 09:14, promised 31 Aug")
4. **Optional status chip row** (Blocked cards only) — `Approved` chip: bg `#fee2e2`, text `#dc2626`. `Pending Owner review, 1 d` chip: bg `#f3f4f6`, text `#374151`.
5. **Optional trailing note** — a second Caption/12 line below the chip.

**Card states drawn:**
| State | Border | Height | Example |
|---|---|---|---|
| Normal (3 rows) | solid 1px `#e5e7eb` | 84 | `Card/สมชาย ทองดี` |
| Done-today (wrapped note) | solid | 100 | `Card/วิไล ศรีสุข` |
| Blocked, approved | solid | 109 | `Card/บริษัท ไทยรุ่ง จำกัด` |
| **Blocked, pending review** | **1px dashed `#e5e7eb`** | 162 | `Card/กนกวรรณ สุขใจ` |

The dashed border is the visual signal for "not yet approved". Nothing else on the screen uses a dashed border except the two "add a column" placeholders.

### 2.4 `Table row`
`padding: 10px 16px`, `gap: 12px`, 1px bottom border `#e5e7eb`, height 58.
- **Default**: bg transparent/white.
- **Highlighted** (row 1 only): bg `brand/050 #fff7dc`, full-bleed — **no left accent bar**.
- Cell type: priority Caption/12 500 `ink/600`; customer name BodyStrong/14 500 `ink/900` + sub-line Caption/12 500 (`ink/500` normally, **`#dc2626` when it carries an exception**); contract Small/13 400 `ink/600`; **arrears BodyStrong/14 500 `ink/900`, right-aligned**; DPD BodyStrong/14 500 `ink/900`, right-aligned; stage badge; last contact Small/13 400 `ink/600`; action button right-aligned.

### 2.5 Table head / footer
- Head cells: Caption/12 500 `ink/500`, **uppercase as authored** (the strings are literally uppercase in Figma, not CSS-transformed), letter-spacing 0.
- Footer: both texts Caption/12 500 `ink/500`, left item and right item pushed apart by a flex-1 spacer.

### 2.6 `Notice/Owner changed the board` (`64:2`)
bg `status/pendingbg #dbeafe`, 1px bottom border, padding 9/14, gap 10, flex row:
sentence Caption/12 500 `ink/700 #374151` (flex-1) · "See what changed" Label/13 500 `status/pending #2563eb` (link) · "Dismiss" Caption/12 500 `ink/500`.
Dismissible — so build the board to render correctly with this band absent (the board area then starts 36 px higher).

---

## 3. Every literal string, verbatim

> **Separator convention:** the middot separator is authored as **two spaces, `·`, two spaces** (`  ·  `). This is confirmed on every separator string in the frame. Reproduce it exactly or the rhythm changes.

### 3.1 Chrome
- `VOLT` / `Debt`
- `Search customer, contract or invoice`  *(placeholder)*
- `Nok  ·  Officer`
- Nav: `Today List`, `Contracts`, `Promises`, `Exceptions`, `Modifications`, `Reports`
- `Your caseload`
- `46 of 200 customers`
- `Contact rate measured on 44`

### 3.2 Page header and filters
- `Today List`
- `Tuesday 25 August 2026  ·  generated 02:31  ·  18 accounts`
- `Export`
- `Start next contact`
- Chips: `All 18`, `Overdue 11`, `Promise due 4`, `Claim pending 2`, `Held 1`

### 3.3 Status board
- `Status board`
- `18 accounts, same 18 as the table`
- `Group by`
- `Work today` / `open`
- `Edit columns`
- `collapse`
- Notice: `The Owner changed the board. Awaiting reply is now Waiting, and it kept your position for it. Chasing was removed and its 3 customers moved to Contacting.`
- `See what changed`
- `Dismiss`
- Column headings: `To contact`, `Contacting`, `Awaiting reply`, `Blocked`, `Done today`, `Add a column`
- Blocked sub-line: `2 approved  ·  1 pending`
- Footer: `Columns are yours to change. Moving a card here records the same act as the table below, so the two never disagree.`

### 3.4 Board card content (Thai names verbatim)
| Column | Customer | Pri | Arrears | DPD | Note line | Chip |
|---|---|---|---|---|---|---|
| To contact | `สมชาย ทองดี` | `P1` | `฿128,750` | `47 d` | `Demand letter sent 22 Aug` | — |
| Contacting | `ณัฐพงษ์ อินทรวิชัย` | `P2` | `฿62,900` | `12 d` | `Dialling now` | — |
| Awaiting reply | `บริษัท สยามกรีน` | `P2` | `฿212,300` | `9 d` | `Claim 4 d unconfirmed` | — |
| Blocked | `บริษัท ไทยรุ่ง จำกัด` | `P1` | `฿74,000` | `63 d` | `No signatory on file` | `Approved` |
| Blocked | `มาลี จันทร์เพ็ญ` | `P2` | `฿5,600` | `41 d` | `Permit awaited, clock running` | `Approved` |
| Blocked | `กนกวรรณ สุขใจ` | `P2` | `฿648,350` | `41 d` | `Customer in hospital, family asked us to stop` then `Still counted in your contact rate until approved` | `Pending Owner review, 1 d` |
| Done today | `วิไล ศรีสุข` | `P2` | `฿45,200` | `18 d` | `Contacted 09:14, promised 31 Aug` | — |

### 3.5 Table headings
`CUSTOMER` · `CONTRACT` · `ARREARS` · `DPD` · `STAGE` · `LAST CONTACT` — columns 1 and 8 have **no** heading text.

### 3.6 Table rows — verbatim, in the drawn visual order

| # | Pri | Customer | Sub-line | Contract | Arrears | DPD | Stage | Last contact | Action |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `P1` | `สมชาย ทองดี` | `Natural person` | `C-2024-0188` | `฿128,750` | `47` | `Demand letter` | `22 Aug` | `Call` |
| 2 | `P1` | `บริษัท ไทยรุ่ง จำกัด` | `Juristic  ·  signatory missing` *(red)* | `C-2023-0912` | `฿74,000` | `63` | `Restriction due` | `21 Aug` | `Call` |
| 3 | `P2` | `วิไล ศรีสุข` | `Natural person` | `C-2024-0421` | `฿45,200` | `18` | `Reminder` | `Today 09:14` | `Contacted today` *(disabled)* |
| 4 | `P2` | `ณัฐพงษ์ อินทรวิชัย` | `Natural person` | `C-2025-0077` | `฿62,900` | `12` | `Reminder` | `20 Aug` | `Call` |
| 5 | `P2` | `บริษัท สยามกรีน เอ็นเนอร์จี` | `Juristic` | `C-2024-0655` | `฿212,300` | `9` | `Claim pending` | `24 Aug` | `Chase claim` |
| 6 | `P2` | `ธนกร วงศ์สถาพร` | `Natural person` | `C-2024-0512` | `฿74,800` | `8` | `Promise due` | `23 Aug` | `Call` |
| 7 | `P2` | `มาลี จันทร์เพ็ญ` | `Natural person` | `C-2024-0790` | `฿5,600` | `41` | `Permit hold` | `15 Aug` | `View` |
| 8 | `P3` | `ปรีชา มั่นคง` | `Natural person` | `C-2023-0338` | `฿88,100` | `5` | `Reminder` | `19 Aug` | `Call` |
| 9 | `P3` | `อรุณี พรหมมา` | `Natural person` | `C-2025-0143` | `฿19,450` | `3` | `Reminder` | `18 Aug` | `Call` |
| 10 | `P3` | `บริษัท ภูมิใจ พร็อพเพอร์ตี้` | `Juristic` | `C-2024-0904` | `฿141,000` | `2` | `Reminder` | `18 Aug` | `Call` |
| 11 | `P3` | `สุนีย์ แก้วมณี` | `Natural person` | `C-2025-0201` | `฿27,300` | `2` | `Reminder` | `17 Aug` | `Call` |
| 12 | `P3` | `กิตติศักดิ์ เรืองฤทธิ์` | `Natural person` | `C-2024-0667` | `฿56,900` | `1` | `Reminder` | `16 Aug` | `Call` |

> **Layer-name trap:** the Figma layers for visual rows 7 and 8 are named `Row 8` and `Row 7` respectively — the *names* are transposed relative to the *drawn order*. Trust the y-coordinates (y = 384 is `มาลี จันทร์เพ็ญ`, y = 442 is `ปรีชา มั่นคง`), which is what the table above records.

### 3.7 Table footer
- `Showing 12 of 18`
- `One officer per customer  ·  one counting contact per customer per day`

### 3.8 Popover (`55:2`) — every string
- `Columns` · `close`
- `GROUP BY  ·  TEAM SET, CHANGED BY THE OWNER`
- `Work today` / `What you have done about them today`
- `Recovery stage` / `The ladder, as on the tracking board`
- `Payment state` / `Current, promised, claimed, overdue`
- `Custom` / `The Owner defines it, everyone reads the same names`
- `YOUR ARRANGEMENT  ·  SURVIVES AN OWNER EDIT`
- Column rows, each prefixed with the literal word `drag`: `To contact`, `Contacting`, `Awaiting reply`, `Blocked`, `Done today`, `Not due today`
- `Ask the Owner to add a column`
- Note: `Names are the team’s and cannot be renamed here. Hiding and reordering are yours alone and survive a rename, because a column is identified by more than its label. A column the Owner adds appears where they put it, visible, until you move or hide it. Every change, yours and the Owner’s, is written to the action log.`
  *(the two apostrophes are typographic U+2019, not ASCII)*
- `Arrangement saved for you  ·  logged` · `Reset` · `Apply`

---

## 4. Every number on the screen, and what it labels

### 4.1 Nav counts
`Today List 18` · `Contracts 712` · `Promises 31` · `Exceptions 9` · `Modifications 4` · `Reports` (none).

### 4.2 Caseload widget
- `46 of 200 customers` — officer's assigned caseload / cap.
- `Contact rate measured on 44` — denominator of the contact-rate metric.
- Cap bar: fill **166 px of a 180 px track = 92.2 %**.
  **This ratio matches neither printed number** (46/200 = 23 %, 44/46 = 95.7 %). The fill width is a literal 166 px in the design. The fixture must therefore supply the bar ratio as its own field; do not compute it from the caseload text or the bar will render visibly wrong.

### 4.3 Page header
`Tuesday 25 August 2026` (the "today" of the screen) · `generated 02:31` · `18 accounts`.

### 4.4 Filter chips
`All 18` · `Overdue 11` · `Promise due 4` · `Claim pending 2` · `Held 1`.
Reconciles: 11 + 4 + 2 + 1 = **18** = All.

### 4.5 Board column counts
`To contact 6` · `Contacting 1` · `Awaiting reply 3` · `Blocked 3` · `Done today 5` → **sum 18** ✓, matching "18 accounts, same 18 as the table".
Blocked sub-line `2 approved  ·  1 pending` reconciles to the 3 Blocked cards (two `Approved`, one `Pending Owner review, 1 d`).

**Column reconciliation against the house rule** ("a fully-drawn column must reconcile exactly to its cards; a column with a *more* card need only exceed what is visible"):

| Column | Header count | Cards drawn | Verdict |
|---|---|---|---|
| To contact | 6 | 1 | **Truncated, and the design draws no "more" card.** |
| Contacting | 1 | 1 | Fully drawn, reconciles exactly ✓ |
| Awaiting reply | 3 | 1 | **Truncated, no "more" card.** |
| Blocked | 3 | 3 | Fully drawn, reconciles exactly ✓ (and 2+1 sub-line ✓) |
| Done today | 5 | 1 | **Truncated, no "more" card.** |

Blocked is the reference column: it is the only one where the mock proves the reconciliation contract. The build must either render every card in a column or add an explicit "+N more" card — the Figma has no such affordance drawn, so it has to be designed in.

### 4.6 Card numbers
Arrears: `฿128,750`, `฿62,900`, `฿212,300`, `฿74,000`, `฿5,600`, `฿648,350`, `฿45,200`.
DPD chips: `47 d`, `12 d`, `9 d`, `63 d`, `41 d`, `41 d`, `18 d`.
Other: `Demand letter sent 22 Aug`, `Claim 4 d unconfirmed`, `Contacted 09:14, promised 31 Aug`, `Pending Owner review, 1 d`.

**DPD chip colour threshold, as drawn:** red (`#fee2e2`/`#dc2626`) for **41, 47, 63**; neutral (`#f3f4f6`/`#374151`) for **9, 12, 18**. The switch point therefore lies somewhere in **19…40** and the design does not pin it. 30 is the conventional Volt boundary — confirm before coding, and do not guess silently.

### 4.7 Table numbers
Arrears column, top to bottom: `฿128,750`, `฿74,000`, `฿45,200`, `฿62,900`, `฿212,300`, `฿74,800`, `฿5,600`, `฿88,100`, `฿19,450`, `฿141,000`, `฿27,300`, `฿56,900`.
DPD column: `47, 63, 18, 12, 9, 8, 41, 5, 3, 2, 2, 1`.
Contract numbers and dates are in the §3.6 table.
Footer: `Showing 12 of 18`.

### 4.8 Popover counts
`To contact 7` · `Contacting 1` · `Awaiting reply 3` · `Blocked 2` · `Done today 5` · `Not due today 0` → **sum 18** ✓.

### 4.9 The two count sets disagree — decide this before building
The board headers and the popover column list both total 18, but distribute differently:

| Column | Board header | Popover row | Δ |
|---|---|---|---|
| To contact | **6** | **7** | +1 |
| Blocked | **3** | **2** | −1 |
| others | same | same | 0 |

The one-account swing is exactly `กนกวรรณ สุขใจ`, the card whose block is `Pending Owner review, 1 d` and whose own note says `Still counted in your contact rate until approved`. The consistent reading is: **the board places a pending-hold account in Blocked; the popover counter still counts it under To contact because the hold is not approved yet.** That reading is coherent, but it is an inference from the mock, not a stated rule — get it confirmed. Whichever way it is resolved, the two surfaces must be fed from the **same** counting function or they will drift, which is precisely what the board footer promises will never happen.

### 4.10 Counts that intentionally do *not* line up
- `Held 1` (filter, a *stage*) vs `Blocked 3` (board, a *work-today* column) — different taxonomies. Only one visible table row carries `Permit hold`. Do not try to make these equal.
- `Overdue 11` is not derivable from the 12 drawn rows (all 12 have DPD ≥ 1); it is a filter over all 18.
- `Claim pending 2` vs one `Claim pending` badge visible — consistent, because only 12 of 18 rows are shown.

---

## 5. Interactions and overlay layers

### 5.1 Implied interactions

| Element | Behaviour implied by the design |
|---|---|
| Search field | Free-text search over customer, contract, invoice. Placeholder only — no focus/typed state drawn. |
| Officer chip | Account/identity affordance. No menu drawn. |
| Nav rows | Navigate; single active row (`Today List`); counts are live badges. |
| `Export` | Export the current list. Secondary. |
| `Start next contact` | The screen's single primary CTA — advances the officer to the next account to work. |
| Filter chips | Single-select filter, `All` currently selected. Because the panel says "18 accounts, same 18 as the table", a chip must filter **board and table together**. |
| `collapse` | Collapses the whole status-board panel, leaving header + table. |
| `Group by` select | Opens the same popover as `Edit columns`. Its affordance word already reads `open`, consistent with the popover being on screen. Options are the four in §5.3; default and current value is **Work today**. |
| `Edit columns` | Opens `Popover/Columns` (`55:2`). |
| `See what changed` | Opens the change record for the Owner's board edit. |
| `Dismiss` | Removes the notice band; the board shifts up 36 px. |
| Board cards | **Drag between columns.** The footer states the contract explicitly: "Moving a card here records the same act as the table below, so the two never disagree" — a drag must write the same action a table action writes, and both views must re-derive from it. |
| `Add a column` (board) | Not a create action — it is the same request as the popover's `Ask the Owner to add a column`. Only the Owner can create columns. |
| Table rows | Open the contract card (frame `8:2` "02 · Contract card"). Row 1 is drawn in the highlighted state — read it as current/selected focus. |
| Row actions | `Call` (default), `Chase claim` (claim-pending rows), `View` (held rows), `Contacted today` (**disabled**, when a counting contact already happened today — paired with `LAST CONTACT = Today 09:14`). |
| Table footer rules | `One officer per customer` and `one counting contact per customer per day` are business invariants restated as UI text; the disabled action in row 3 is the second rule enforced. |

### 5.2 Overlay inventory
Exactly **one** overlay layer in this frame: `55:2`, the Columns popover. It has **no backdrop scrim**. It paints above Main and, at its drawn position, occludes:
- the right portion of the notice band,
- the Done-today column and the Add-a-column placeholder,
- the right side of the Blocked column,
- the `STAGE` / `LAST CONTACT` / action cells of table rows 1–3.

Nothing beneath it is dimmed, so all of that content must still be rendered and correct.

### 5.3 `Popover/Columns` — full component spec
Container: 360 × 773, bg `surface/0 #ffffff`, radius **10**, 1px `line/default #e5e7eb`, plus a soft drop shadow (approximately `0 8px 24px rgba(0,0,0,.10)` — measured from the export's ~28 px bleed; the exact Figma shadow values were not read).

**Band 1 — header `55:3`** (0 – 42): bg `surface/50 #f9fafb`. `Columns` Heading/16 600 `ink/900` at x 14 · `close` Small/13 400 `ink/500` at x 317.

**Band 2 — Group by `55:6`** (42 – 314): bg white.
- Section label `GROUP BY  ·  TEAM SET, CHANGED BY THE OWNER`, Caption/12 500 `ink/500`, at (14, 12).
- Four radio options, each **332 × 51** at x 14, y = 35, 93, 151, 209 (pitch **58**). Option spec: radius 6, `padding: 7px 9px`, `gap: 9px`; 13 px radio; label block flex-1 with `gap: 1px` — title BodyStrong/14 500 `ink/900`, description Caption/12 500 `ink/500`.
  - **Selected** (`Work today`): bg `brand/050 #fff7dc`, radio filled solid `ink/900 #050505`.
  - **Unselected**: transparent bg, radio = white circle with a light grey ring.
- Order and content: `Work today` / `Recovery stage` / `Payment state` / `Custom` — **Work today is the default and the current selection.**

**Band 3 — Column list `55:28`** (314 – 601): bg white, 1px bottom border, `padding: 12px 14px`, flex-column `gap: 5px`.
- Section label `YOUR ARRANGEMENT  ·  SURVIVES AN OWNER EDIT`, Caption/12 500 `ink/500`.
- Six column rows, **332 × 30** at x 14, y = 33, 68, 103, 138, 173, 208 (pitch **35**). Row spec: radius 6, `padding: 6px 8px`, `gap: 9px`; `drag` Caption/12 500 `ink/500` · label Small/13 400 (flex-1) · count Caption/12 500 `ink/500` · toggle 28 × 16.
  - **Visible row**: transparent bg, label `ink/800 #111827`, toggle **on** (`#16a34a`).
  - **Hidden row** (`Not due today`, count 0): bg `surface/50 #f9fafb`, label **`ink/500 #6b7280`**, toggle **off** (`#e5e7eb`). The `drag` handle stays present.
- `Ask the Owner to add a column` `55:66`: 332 × 32, 1px **dashed** `#e5e7eb`, radius 6, `padding: 7px 8px`, Small/13 400 `ink/600 #4b5563`.

**Band 4 — Note `55:68`** (601 – 719): bg `surface/50 #f9fafb`, text at (14, 11), 332 × 96, Small/13 400.

**Band 5 — footer `55:70`** (719 – 773): bg white, 1px top border, `padding: 11px 14px`, `gap: 8px`.
`Arrangement saved for you  ·  logged` Caption/12 500 `ink/500` (flex-1) · `Button/ghost` **Reset** (57 × 32) · `Button/primary` **Apply** (60 × 32, amber).

**Interactions the popover implies**
1. Group-by is a **radio group** — exactly one of four; changing it re-derives the whole column set.
2. Each column row's toggle **shows/hides** that column on the board. `Not due today` is off, which is why the board draws five columns, not six.
3. Rows are **reorderable by drag**; board column order follows the popover order top-to-bottom (verified: To contact, Contacting, Awaiting reply, Blocked, Done today).
4. Hiding and reordering are **per-officer** and persist across an Owner rename, because "a column is identified by more than its label" — i.e. columns need a stable id independent of the display name. This is the load-bearing sentence in the whole popover.
5. A column the Owner adds appears **where the Owner put it, visible**, until the officer moves or hides it.
6. `Reset` returns to the team default; `Apply` commits. The footer already reads "saved for you · logged", implying changes are persisted and **written to the action log** — every change, the officer's and the Owner's.
7. `close` dismisses without a scrim click-target being drawn; assume click-outside also closes.
8. Column creation is **not** available to the officer — the affordance is a request to the Owner.

---

## 6. Fixture requirements

Seed data the screen needs in order to render truthfully. Anything marked **must** is something the drawn design depends on.

**Officer / session**
- Officer `Nok`, role label `Officer`, avatar with no image (tinted circle only).
- Caseload: assigned **46**, cap **200**, contact-rate denominator **44**, and a **separate explicit bar ratio ≈ 0.92** (see §4.2).
- Nav counters: 18 / 712 / 31 / 9 / 4, Reports with none.

**The list itself**
- Business date **Tuesday 25 August 2026**, generation timestamp **02:31**.
- Exactly **18** accounts in today's list; the table must be **paginated to 12** so the footer reads "Showing 12 of 18".
- Filter tallies over all 18: Overdue 11, Promise due 4, Claim pending 2, Held 1 (they must partition the 18).

**Accounts — must exist with these exact values**
- The 12 table rows of §3.6, in that order, with the Thai names, contract numbers, arrears, DPD, stage, last-contact values as listed.
- **`กนกวรรณ สุขใจ` (P2, `฿648,350`, DPD 41, Blocked / Pending Owner review 1 d) must exist as one of the 18 but must NOT be in the first 12 table rows.** She appears only on the board. A fixture that seeds only the 12 visible rows will render the Blocked column with two cards and break its 3-count and its `2 approved · 1 pending` sub-line.
- `บริษัท สยามกรีน เอ็นเนอร์จี` needs a **short display form** `บริษัท สยามกรีน` for the card: the board card's name field is only ~134 px wide and the design shows the shortened name with **no ellipsis**. Either seed a short name or implement shortening — CSS truncation would render `บริษัท สยามกรีน เอ็นเนอ…`, which is not what is drawn.
- `บริษัท ไทยรุ่ง จำกัด` must carry a juristic exception flag so its table sub-line renders `Juristic  ·  signatory missing` in red.
- `วิไล ศรีสุข` must have a **counting contact already recorded today at 09:14** plus a promise dated **31 Aug**, so her row shows `Today 09:14` and the disabled `Contacted today` action, and her card sits in Done today with the green note.
- Priority mix across the 12 rows: 2 × P1, 5 × P2, 5 × P3.
- Stage mix across the 12 rows: Reminder × 7, Demand letter × 1, Restriction due × 1, Claim pending × 1, Promise due × 1, Permit hold × 1.

**Board state**
- Group-by = **Work today** (the default).
- Officer's column arrangement, in order: To contact (visible), Contacting (visible), Awaiting reply (visible), Blocked (visible), Done today (visible), **Not due today (hidden, count 0)**.
- Each column needs a **stable id separate from its display name** — the popover's own copy requires arrangement to survive an Owner rename.
- Blocked needs its approval split: 2 approved blocks, 1 pending, and the pending one dated **1 d** ago.
- Card notes are per-account free text with a severity so the note line can pick `ink/500` / red / green (see §2.3).

**Owner-change event (drives the notice band)**
- A recent Owner board edit with: `Awaiting reply` renamed to `Waiting` (position preserved), and `Chasing` removed with its **3** customers reassigned to `Contacting`.
- Note the internal tension in the mock: the notice says the rename to `Waiting` has happened, yet the board header and the popover row both still read `Awaiting reply`. Treat the notice as describing a change **not yet applied to this render**, or fix the copy — but do not ship both readings.
- The notice must be dismissible, and the board must lay out correctly without it.

**Cross-surface invariant**
- Board counts and popover counts must come from one counting function (see §4.9), and a card drag must write the same action a table action writes, per the board footer's promise.

---

## 7. House-rule compliance — one deviation to resolve

**Amber is never a status** — obeyed throughout. `#f2b705` appears only on the bolt, the two primary buttons, the active nav tint (`brand/050`), the selected group-by tint (`brand/050`), the highlighted table row (`brand/050`) and the caseload bar. All status meaning is carried by green / blue / red / grey.

**Column reconciliation** — obeyed by Blocked (3 = 3 cards = 2 approved + 1 pending) and by Contacting (1 = 1). To contact, Awaiting reply and Done today are truncated and the design draws **no "more" card**; that affordance has to be added. See §4.5.

**Money: arrears large, outstanding balance small beneath — NOT drawn on this screen.**
This frame contains exactly **19** money strings and every one of them is a lone arrears figure. There is no second, smaller balance line anywhere; grep of the node tree for an outstanding/balance field returns nothing. Worse, the board card renders arrears at **Small/13 400 `ink/800`**, which is *smaller and lighter than the customer name above it* (BodyStrong/14 500 `ink/900`) — the opposite of "arrears large". The table does treat arrears as the emphatic figure (BodyStrong/14 500 `ink/900`, right-aligned), but still with no balance beneath.

Do not silently invent the sub-line. Either (a) the rule does not apply to 01 Today List and the frame is correct as drawn, or (b) the frame predates the rule and needs a revision before build. This needs a decision from the design owner, and it changes card height (each card grows ~16 px) and therefore every column height on the board.

---

## Appendix — node id map for re-opening in Figma

| Region | Node |
|---|---|
| Frame | `3:2` |
| Top bar / Wordmark / Search / Officer | `3:3` / `3:4` / `3:10` / `3:12` |
| Nav / first nav item / Workload / Cap bar | `3:15` / `3:16` / `3:40` / `3:43` |
| Main / Page header / Filters | `4:2` / `4:3` / `4:12` |
| Status board / header / notice / columns / footer | `53:2` / `53:3` / `64:2` / `53:14` / `53:98` |
| Board columns (L→R) | `53:15`, `53:29`, `53:43`, `53:57`, `53:81`, `53:95` |
| Board cards | `53:19`, `53:33`, `53:47`, `53:61`, `53:71`, `60:9`, `53:85` |
| Work table / head / footer | `6:2` / `6:3` / `6:270` |
| Table rows (visual order) | `6:18`, `6:39`, `6:60`, `6:81`, `6:102`, `6:123`, **`6:165`**, **`6:144`**, `6:186`, `6:207`, `6:228`, `6:249` |
| Popover / header / group-by / column list / note / footer | `55:2` / `55:3` / `55:6` / `55:28` / `55:68` / `55:70` |
