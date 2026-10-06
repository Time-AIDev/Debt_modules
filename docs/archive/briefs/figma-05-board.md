# UI brief — 05 · Board, customer tracking

> **SUPERSEDED AS BUILD TARGET (2026-08-30).** Documents Figma "Product UI v0.1"; kept as the record. The rebuilt board persists moves via the API and its stage ladder gains the deck v20.0 EPC/SPV context — see `docs/archive/briefs/screens-v2/`, `docs/product/workflow-v20-epc-spv.md` and `docs/product/user-journey.md`.

**Source** Figma file `dAIFet044WF2P0FbUJfoT7`, page `0:1` "Volt Debt — UI v0.1", frame `18:2` "05 · Board, customer tracking" (canvas x=6080, y=0).
**Purpose** Build this screen without reopening Figma. Every string, number, size and colour below was read out of the file or measured off the 1:1 render.

---

## 0 · Words used on this screen

Read this first if you have not worked on Volt Debt before.

| Word on screen | What it means |
|---|---|
| **Arrears** | The money that is late right now. This is the big number on every card and in every column head. |
| **Outstanding / owed** | The whole remaining balance of the customer's contracts, late or not. Always the small number underneath the arrears. |
| **Recovery stage** | How far down the collection ladder a customer has been pushed: Current → Reminder → Demand letter → Restriction → Legal and recovery. The five board columns *are* the ladder. |
| **DPD ("41 d")** | Days past due — how long the oldest unpaid amount has been late. Shown as a chip on the right of the money row. |
| **natural person / juristic** | An individual customer vs. a registered company. Thai lending distinction; drives who may sign. |
| **Permit hold** | Work is paused waiting on a government permit reply. |
| **Restriction** | Physically throttling or cutting the customer's output/service. Cannot be applied until a restriction notice has been sent. |
| **Restoration** | Undoing a restriction after the customer pays. It has its own deadline, which can be breached even when arrears are ฿0. |
| **Claim pending** | The customer says they paid an amount that Volt has not matched to a receipt yet. |
| **Ple / Nok / Owner** | Owner initials on a card. "Owner" is the portfolio Owner role, not a person's name. |

---

## 1 · What this screen is — and how its columns differ from screen 01

This board and the board on screen 01 look alike and mean completely different things. Getting this wrong is the single most expensive mistake available here.

| | **01 · Today List** (frame `3:2`) | **05 · Customer tracking** (frame `18:2`) |
|---|---|---|
| Page title | `Today List` | `Customer tracking` |
| Board is | a *section* inside the day's worklist, above a work table | the whole page |
| Unit of a card | one **account** ("18 accounts, same 18 as the table") | one **customer** — "One card per customer, not per contract" |
| Population | today's 18 accounts | the whole portfolio, 184 customers |
| Grouped by | **Work today** — *"What you have done about them today"* | **Recovery stage** — *"The ladder, as on the tracking board"* |
| Columns | `To contact` · `Contacting` · `Awaiting reply` · `Blocked` · `Done today` · `+ Add` | `Current` · `Reminder` · `Demand letter` · `Restriction` · `Legal and recovery` |
| Column meaning | *your handling state today* — resets daily, an account can sit in `Done today` while still deeply in arrears | *where the debt has got to in the ladder* — persists across days, only a human act advances it |
| Who owns the columns | the team; the Owner edits them. Screen 01 carries a `Group by` select, an `Edit columns` button, a `+ Add` column, and a notice that reads *"The Owner changed the board. Awaiting reply is now Waiting…"* | **nobody** — this screen has **no** group-by control, **no** edit-columns button and **no** add-column affordance. The ladder is fixed |
| Cross-reference in the file | the `Group by` popover on 01 lists `Recovery stage — The ladder, as on the tracking board` as an alternative grouping | — |

Both boards drag-and-drop, and a drag on either is a real act, not a tidy-up. On 01 a drag spends the day's permitted contact. On 05 a drag changes the recovery stage.

**Implementation consequence:** a customer's position on screen 05 must be stored on the *customer*, must not be derived from DPD or from any timer, and must be independent of whatever column that customer sits in on screen 01. `ประเสริฐ ใจงาม` proves it — ฿0 arrears, chip `Paid`, still sitting in `Restriction`.

---

## 2 · Frame and layout

Fixed desktop artboard, **1440 × 1024**. Page background behind Main is `surface/100 #f3f4f6`.

```
 0 ┌──────────────────────────────────────────────────────────────┐ 1440
   │ Top bar                                    1440 × 56         │
56 ├───────────────┬──────────────────────────────────────────────┤
   │ Nav           │ Main                                         │
   │ 232 × 968     │ 1208 × 968                                   │
   │               │   Page header   1160 × 54   @ (24, 20)       │
   │               │   Rule note     1160 × 34   @ (24, 90)       │
   │               │   Board         1160 × 821  @ (24,140)       │
1024└───────────────┴──────────────────────────────────────────────┘
   0              232                                          1440
```

### 2.1 Top bar — `18:3`, 1440 × 56 @ (0,0)
`surface/0` fill, 1px bottom border `line/default`. Flex row, `align-items:center`, `padding: 0 20px`, `gap 16`.

| Part | Node | Box | Spec |
|---|---|---|---|
| Wordmark | `18:4` | 109 × 24 @ x=20, y=16 | flex row gap 8 |
| ↳ Bolt icon | `18:5` | 20 × 20 @ y+2 | SVG, brand amber |
| ↳ `VOLT` | `18:7` | 38 × 24 @ x+28 | Heading/16 600, `ink/900` |
| ↳ `Debt` | `18:8` | 35 × 24 @ x+74 | Heading/16 600, `ink/500` |
| Spacer | `18:9` | flex-1 (851 as drawn) | — |
| Search | `18:10` | 280 × 34 @ (1012, 11) | `surface/50` fill, 1px `line/default`, radius 6, padding 7/12 |
| ↳ placeholder | `18:11` | @ (12, 8) | Small/13 400, `ink/500` |
| Officer | `18:12` | 112 × 28 @ (1308, 14) | flex row gap 8 |
| ↳ avatar | `18:13` | 28 × 28 circle | fill `brand/050 #fff7dc`, stroke `brand/500 #f2b705` |
| ↳ label | `18:14` | @ x+36 | Small/13 400, `ink/700` |

### 2.2 Nav — `18:15`, 232 × 968 @ (0,56)
`surface/0` fill, 1px **right** border `line/default`. Flex column, `padding: 16px 12px`, `gap 2`.

- **Nav item** ×6 — 208 × 38, `padding: 9px 12px`, radius 6, flex row gap 8: label, flex-1 spacer, count. Pitch is 40px (38 + 2 gap); y = 16, 56, 96, 136, 176, 216 inside Nav.
- **Spacer** `18:39` — 208 × 16 @ y=256.
- **Workload** `18:40` — 208 × **78** @ y=274, `surface/50` fill, 1px `line/default`, radius 8, `padding 12`, flex column gap 6:
  - `Your caseload` — Caption/12 500, `ink/500`
  - `46 of 200 customers` — BodyStrong/14 500, `ink/800`
  - **Cap bar** `18:43` — 180 × 6, radius 3, track `line/default`; fill `18:44` = **166 × 6**, radius 3, `brand/500 #f2b705`.
  - Screen 01's Workload is 100 tall and carries an extra line `Contact rate measured on 44`. **This screen omits that line** — do not copy it in.

### 2.3 Main — `18:338`, 1208 × 968 @ (232,56)

**Page header** `18:339`, 1160 × 54 @ (24,20) — flex row, `align-items:center`, gap 16.
- `Titles` `18:340`: flex column gap 4. H1 `Customer tracking` Display/24 600 `ink/900` (202×32); subtitle Small/13 400 `ink/500`.
- flex-1 spacer.
- **View switch** `18:344` 118 × 36: `surface/100` fill, 1px `line/default`, radius 6, `overflow:hidden`. Two segments, each `padding: 8px 14px`. `List` = Body/14 400 `ink/500`, transparent. `Board` = BodyStrong/14 500 `ink/900` on `surface/0`. **`Board` is the selected segment on this screen.**
- **Button/ghost** `18:349` 101 × 38: `surface/0`, 1px `line/default`, radius 6, `padding: 9px 14px`; `Officer: Nok` BodyStrong/14 500 `ink/700`.

**Rule note** `18:351`, 1160 × 34 @ (24,90) — `surface/0`, 1px `line/default`, radius 6, `padding: 9px 12px`; text Caption/12 500 `ink/600`, one line at this width.

**Board** `18:353`, 1160 × 821 @ (24,140) — flex row, `gap 12`, columns **top-aligned**, each column `flex: 1`.
- 5 columns × 222.4 + 4 gaps × 12 = 1160 exactly. Do not hardcode 222.4; use `flex:1` with `gap:12`.
- Column heights as drawn: Current 185, Reminder 821, Demand letter 640, Restriction 444, Legal and recovery 357. Board height = tallest column.
- The tallest column ends at absolute y=1017, 7px short of the frame edge. **In a real build the board region must scroll** — either the board as a whole or each column independently; the artboard shows the no-scroll case exactly filled.
- Each column is a flex column with **`gap 8`** between head, cards and the more-pill.

---

## 3 · Components and states

### 3.1 `ColumnHead` — 222.4 × 82
`padding: 10px 12px`, radius 8, `overflow:hidden`, flex column `gap 3`.
Row 1 (`R`): flex row gap 8 — title `flex:1`, count `shrink:0`; both BodyStrong/14 500 in the **stage colour**.
Row 2: arrears, BodyStrong/14 500, `ink/900 #050505`.
Row 3: owed, Caption/12 500, `ink/600 #4b5563`.

| State | Used by | Background | Title + count |
|---|---|---|---|
| `current` | Current | `status/current bg #dcfce7` | `status/current #16a34a` |
| `held` (neutral) | Reminder | `status/held bg #f3f4f6` | `status/held #6b7280` |
| `overdue` | Demand letter, Restriction, Legal and recovery | `status/overdue bg #fee2e2` | `status/overdue #dc2626` |

Note the shape of the ladder in colour: green at the left, one neutral step, then red for the last three. **`brand/500 #f2b705` appears nowhere in this board** — it is only the wordmark bolt, the avatar ring/fill and the caseload cap bar. Amber is the brand and can never be a status.

*Known drift:* the `No arrears` layer in the Current head (`18:359`) renders as pure `#000000`, unlike its four siblings which are `ink/900 #050505`. Build it as `ink/900`.

### 3.2 `CustomerCard` — 222.4 × 173 (with flags) or × 146 (without)
`surface/0` fill, **1px** border, radius 8, `padding: 11px 12px`, `overflow:hidden`, flex column **`gap 7`**.

Rows top to bottom:
1. **Name** — BodyStrong/14 500, `ink/900`, full width, wraps.
2. **Meta** — Caption/12 500, `ink/500`. Literal form `N contract  ·  natural person` — **two spaces either side of the middle dot U+00B7**, plural `contracts` for N > 1.
3. **Money row** — flex row `gap 8`, `align-items:center`: **arrears** BodyStrong/14 500 `ink/900`; flex-1 spacer; **status chip** right-aligned.
4. **Outstanding** — Caption/12 500, `ink/500`, literal form `of ฿X outstanding`.
5. **Flags row** *(optional)* — flex row `gap 5`, chips left-aligned, wraps.
6. **Divider** — 1px full-width `line/default`.
7. **Foot** — flex row `gap 8`, `align-items:center`, Caption/12 500: left text `flex:1`; right owner initials `shrink:0`, `ink/500`.

The 27px height difference between the two card heights is exactly the flags row (20) plus one gap (7).

**Card states**

| State | Border | Foot-left colour | Drawn by |
|---|---|---|---|
| default | `line/default #e5e7eb` | `ink/600 #4b5563` | 9 of the 10 cards |
| **breach** | `status/overdue #dc2626` | `status/overdue #dc2626` | `ประเสริฐ ใจงาม` only |

The breach state is **not** selection or hover. It marks a deadline that has already been blown — here, restoration overdue while the customer is fully paid up. Nothing else on the card changes.

### 3.3 `Chip` — height 20
`padding: 2px 6px`, radius 4, Caption/12 500, single line, no wrap.

**Money-row chip (DPD / paid)** — exactly one per card, always present.

| Variant | Background | Text colour | Content |
|---|---|---|---|
| DPD, under threshold | `status/held bg #f3f4f6` | **`ink/900 #050505`** | `9 d`, `12 d`, `18 d` |
| DPD, over threshold | `status/overdue bg #fee2e2` | `status/overdue #dc2626` | `41 d`, `47 d`, `52 d`, `63 d`, `128 d` |
| arrears cleared | `status/current bg #dcfce7` | `status/current #16a34a` | `Paid` |

The under-threshold DPD chip uses **dark ink text on grey**, which is *not* the same as a neutral flag chip (grey text on grey). Keep them apart.
**Threshold:** as drawn the file gives grey ≤ 18 d and red ≥ 41 d. Nothing on this screen pins the exact cut. Choose one (30 is the obvious candidate), put it in one constant, and apply it to every DPD chip in the app.

**Flag chip** — zero, one or two per card.

| Variant | Background | Text colour | Instances |
|---|---|---|---|
| neutral / held | `status/held bg #f3f4f6` | `status/held #6b7280` | `Permit hold`, `Contacted today`, `Letter sent 22 Aug`, `Collateral valued` |
| pending | `status/pending bg #dbeafe` | `status/pending #2563eb` | `Claim pending ฿4,000` |
| overdue | `status/overdue bg #fee2e2` | `status/overdue #dc2626` | `Promise broken twice`, `Notice not sent`, `No signatory`, `Restoration overdue`, `With Legal` |

*File hygiene note:* neutral chips are bound to `--status/heldbg`/`--status/held` on some layers and to `--surface/100`/`--ink/500` on others. Both resolve to `#f3f4f6` / `#6b7280`. Use the `status/held` pair so the intent survives a token change.

### 3.4 `MorePill` — full column width × 34
`surface/100 #f3f4f6` fill, radius 8, `padding: 9px 0`, contents centred, Caption/12 500 `ink/500`. Content `N more`. Sits last in the column, same 8px gap as a card. Appears only when the column count exceeds the cards rendered.

### 3.5 `SummaryCard` — Current column only, 222.4 × 95
`surface/50 #f9fafb` fill, 1px `line/default`, radius 8, `padding: 11px 12px`, flex column `gap 5`.
Title BodyStrong/14 500 `ink/700`; body Caption/12 500 `ink/500`, wraps to 3 lines at this width.
Its whole job is to say why this column draws no cards.

### 3.6 `NoteCard` — Legal and recovery column only, 222.4 × 86
Same box as SummaryCard (`surface/50`, 1px `line/default`, radius 8, `padding: 11px 12px`) with **no gap** — one text node, Caption/12 500 `ink/500`, wraps to 4 lines. Sits *after* the single card, in the card slot, and is **not** counted as a card.

### 3.7 `NavItem` — 208 × 38
`padding: 9px 12px`, radius 6, flex row gap 8: label, flex-1 spacer, count badge.

| State | Background | Label | Badge | Drawn by |
|---|---|---|---|---|
| default | none | Body/14 400 `ink/600` | Caption/12 500 `ink/500` | Promises, Exceptions, Modifications |
| default, no badge | none | Body/14 400 `ink/600` | — | Reports |
| emphasis | none | **BodyStrong/14 500** `ink/600` | Caption/12 500 **`ink/700`** | Today List |
| **active** | `brand/050 #fff7dc` | Body/14 400 **`ink/900`** | Caption/12 500 `ink/500` | **Contracts** |

Two things to keep: the active item on this screen is **Contracts**, not Today List — the customer-tracking board lives under the portfolio, not under the day's work. And `brand/050` as the active tint is the one sanctioned use of brand colour in navigation; it carries no status meaning.

### 3.8 `ViewSwitch`, `Button/ghost`, `RuleNote`
Covered in §2.3. The switch has exactly two states — the active segment gets `surface/0` and `ink/900` at weight 500, the inactive gets transparent and `ink/500` at weight 400.

---

## 4 · Verbatim text

Every string below is exact. `·` is U+00B7; where it appears between two spaces on each side that spacing is in the design and must be preserved. `฿` is U+0E3F.

### 4.1 Chrome
```
VOLT
Debt
Search customer, contract or invoice
Nok  ·  Officer
Today List
Contracts
Promises
Exceptions
Modifications
Reports
Your caseload
46 of 200 customers
```

### 4.2 Page header, switch, rule note
```
Customer tracking
One card per customer, not per contract  ·  184 customers  ·  ฿972,800 in arrears against ฿13,318,300 outstanding
List
Board
Officer: Nok
A card moves right only when a human acts. Nothing on this board advances a stage on its own, and dragging a card left is a reversal that asks for a reason.
```

### 4.3 Column heads (title / count / arrears / owed)
```
Current              165   No arrears          of ฿9,170,500 owed
Reminder              12   ฿186,300 arrears    of ฿776,400 owed
Demand letter          4   ฿402,100 arrears    of ฿1,088,500 owed
Restriction            2   ฿74,000 arrears     of ฿1,429,300 owed
Legal and recovery     1   ฿310,400 arrears    of ฿853,600 owed
```
Only the Current head substitutes the words `No arrears` for a money figure. Every other head is `฿N arrears`.

### 4.4 Summary, note, more-pills
```
165 paying on time
Not shown as cards. A customer appears here only when something is due about them.

Nothing reaches this column automatically. A person flags it, reminders stop, and the file goes to Legal.

8 more
1 more
```

### 4.5 Cards, in board order

**Reminder**

| # | Name | Meta | Arrears | Chip | Outstanding | Flags | Foot | Owner |
|---|---|---|---|---|---|---|---|---|
| 1 | `มาลี จันทร์เพ็ญ` | `1 contract  ·  natural person` | `฿5,600` | `41 d` red | `of ฿33,600 outstanding` | `Permit hold` | `Permit reply overdue 6 d` | `Nok` |
| 2 | `วิไล ศรีสุข` | `1 contract  ·  natural person` | `฿45,200` | `18 d` grey | `of ฿180,800 outstanding` | `Contacted today` | `Next contact 26 Aug` | `Nok` |
| 3 | `ณัฐพงษ์ อินทรวิชัย` | `1 contract  ·  natural person` | `฿62,900` | `12 d` grey | `of ฿251,600 outstanding` | — | `No contact since 20 Aug` | `Nok` |
| 4 | `บริษัท สยามกรีน เอ็นเนอร์จี` | `2 contracts  ·  juristic` | `฿212,300` | `9 d` grey | `of ฿842,000 outstanding` | `Claim pending ฿4,000` blue | `Claim 4 d unconfirmed` | `Nok` |
| | more-pill `8 more` |

**Demand letter**

| # | Name | Meta | Arrears | Chip | Outstanding | Flags | Foot | Owner |
|---|---|---|---|---|---|---|---|---|
| 1 | `สมชาย ทองดี` | `1 contract  ·  natural person` | `฿128,750` | `47 d` red | `of ฿515,000 outstanding` | `Letter sent 22 Aug` | `Escalates 29 Aug` | `Nok` |
| 2 | `วัชระ ตั้งจิตมั่น` | `2 contracts  ·  natural person` | `฿311,400` | `52 d` red | `of ฿1,246,000 outstanding` | `Promise broken twice` red | `Review for legal 27 Aug` | `Ple` |
| 3 | `กนกวรรณ สุขใจ` | `1 contract  ·  natural person` | `฿648,350` | `41 d` red | `of ฿2,593,400 outstanding` | — | `Letter due 26 Aug` | `Ple` |
| | more-pill `1 more` |

**Restriction**

| # | Name | Meta | Arrears | Chip | Outstanding | Flags | Foot | Owner |
|---|---|---|---|---|---|---|---|---|
| 1 | `บริษัท ไทยรุ่ง จำกัด` | `1 contract  ·  juristic` | `฿74,000` | `63 d` red | `of ฿1,192,000 outstanding` | `Notice not sent` red, `No signatory` red | `Blocked until notice sent` | `Nok` |
| 2 | `ประเสริฐ ใจงาม` **breach card** | `1 contract  ·  natural person` | `฿0` | `Paid` green | `of ฿237,300 outstanding` | `Restoration overdue` red | `Still restricted 1 d 19 h` *(red)* | `Ple` |

**Legal and recovery**

| # | Name | Meta | Arrears | Chip | Outstanding | Flags | Foot | Owner |
|---|---|---|---|---|---|---|---|---|
| 1 | `บริษัท เอ็นซี พลัส จำกัด` | `3 contracts  ·  juristic` | `฿853,600` | `128 d` red | `of ฿3,414,400 outstanding` | `With Legal` red, `Collateral valued` grey | `Assignment deed drafted` | `Owner` |
| | NoteCard (see §4.4) |

**Current** draws no cards — SummaryCard only.

---

## 5 · Every number on the screen

### 5.1 Numbers and what they label

| Number | Labels |
|---|---|
| `18` | Nav badge — Today List |
| `712` | Nav badge — Contracts |
| `31` | Nav badge — Promises |
| `9` | Nav badge — Exceptions |
| `4` | Nav badge — Modifications |
| `46 of 200 customers` | Officer Nok's caseload against her cap |
| `184 customers` | total customers on this board (page subtitle) |
| `฿972,800` | total arrears across the board (page subtitle) |
| `฿13,318,300` | total outstanding across the board (page subtitle) |
| `165` / `12` / `4` / `2` / `1` | customer counts per column |
| `฿9,170,500` / `฿776,400` / `฿1,088,500` / `฿1,429,300` / `฿853,600` | owed per column |
| `฿186,300` / `฿402,100` / `฿74,000` / `฿310,400` | arrears per column (Current shows `No arrears`) |
| `165 paying on time` | SummaryCard headline in Current |
| `8 more` / `1 more` | hidden cards in Reminder / Demand letter |
| card arrears | `฿5,600` `฿45,200` `฿62,900` `฿212,300` `฿128,750` `฿311,400` `฿648,350` `฿74,000` `฿0` `฿853,600` |
| card outstanding | `฿33,600` `฿180,800` `฿251,600` `฿842,000` `฿515,000` `฿1,246,000` `฿2,593,400` `฿1,192,000` `฿237,300` `฿3,414,400` |
| DPD chips | `41 d` `18 d` `12 d` `9 d` `47 d` `52 d` `41 d` `63 d` `128 d` (+ `Paid`) |
| in-flag / in-foot | `฿4,000` (claim), `6 d`, `4 d`, `1 d 19 h` |
| dates in foots/flags | `26 Aug` ×2, `20 Aug`, `22 Aug`, `29 Aug`, `27 Aug` |
| contract counts | `1`, `1`, `1`, `2`, `1`, `2`, `1`, `1`, `1`, `3` = 14 contracts across the 10 visible cards |
| cap bar | fill is **166 of 180 px** (≈92%) |

### 5.2 Reconciliation audit — READ THIS BEFORE SEEDING

House rule: *a fully-drawn column must reconcile exactly to its cards; a column with a "more" card need only exceed what is visible.*

**Page header vs column heads — exact, all three:**

| | sum of column heads | page subtitle | |
|---|---|---|---|
| customers | 165 + 12 + 4 + 2 + 1 = **184** | `184 customers` | ✅ |
| arrears | 0 + 186,300 + 402,100 + 74,000 + 310,400 = **฿972,800** | `฿972,800` | ✅ |
| owed | 9,170,500 + 776,400 + 1,088,500 + 1,429,300 + 853,600 = **฿13,318,300** | `฿13,318,300` | ✅ |

Card counts also reconcile everywhere: 4 visible + 8 more = 12; 3 + 1 = 4; 2 + 0 = 2; 1 + 0 = 1.

**Column heads vs their cards — three columns fail:**

| Column | Rule that applies | Head arrears | Visible-card arrears | Head owed | Visible-card outstanding | Verdict |
|---|---|---|---|---|---|---|
| Current | count only (no cards) | — | — | ฿9,170,500 | — | ✅ n/a |
| Reminder | head must **exceed** visible | ฿186,300 | **฿326,000** | ฿776,400 | **฿1,308,000** | ❌ head is *below* what is visible |
| Demand letter | head must **exceed** visible | ฿402,100 | **฿1,088,500** | ฿1,088,500 | **฿4,354,400** | ❌ head is *below* what is visible |
| Restriction | fully drawn — must be **exact** | ฿74,000 | ฿74,000 | ฿1,429,300 | ฿1,429,300 | ✅ exact |
| Legal and recovery | fully drawn — must be **exact** | ฿310,400 | **฿853,600** | ฿853,600 | **฿3,414,400** | ❌ neither figure matches |

Restriction is the column that is right, and it is right to the baht — treat it as the worked example. The Legal column has one card and no more-pill (a NoteCard is not a card), so it is fully drawn and must be exact; it is not.

There is a visible tell in the broken columns: the Demand-letter head's *owed* (฿1,088,500) is exactly the sum of its visible card *arrears*, and the Legal head's *owed* (฿853,600) is exactly its card's *arrears*. The two figures were crossed when the mock data was written.

**Decide once, then seed:** keep the column heads (they are the set that rolls up cleanly to the page total) and generate card figures that fit under them; or keep the cards and recompute heads *and* the page subtitle. Do not ship the Figma numbers as-is.

Second defect: the caseload cap bar is drawn at 166/180 ≈ 92% while its own label reads `46 of 200 customers` ≈ 23%. Bind the fill width to the ratio.

---

## 6 · Interactions and overlay layers

**Frame `18:2` contains exactly three children — Top bar, Nav, Main. There is no overlay, popover, dialog or hidden state layer on this screen.** (For contrast, screen 01 carries `55:2` `Popover/Columns — overlay state, hide this layer to see the board beneath`, 360 × 773 @ (1046,246).)

Interactions the design states or implies:

1. **Drag a card between columns.** The rule note is the specification: *"A card moves right only when a human acts. Nothing on this board advances a stage on its own, and dragging a card left is a reversal that asks for a reason."*
   - Rightward drag = advance the recovery stage. Never automatic — no timer, no DPD threshold, no nightly job may move a card.
   - Leftward drag = reversal, and must open a reason prompt and store the reason. **That prompt is not drawn anywhere in the file** — it needs designing, and the file's own principle line elsewhere is *"Every escalation, priority and stage change stores the reason that produced it."*
   - The nearest drawn precedent is on screen 04: `Panel/CONFIRM · A DRAG SPENDS THE DAILY SLOT` (`61:3`), a 452-wide dialog on a backdrop with `Cancel, put it back` / `Start the contact`. **That dialog belongs to screen 01's work-today board** (its body names `Contacting`); reuse its shape, not its copy.
2. **View switch** `List` ↔ `Board`. `Board` is active here. The `List` view of Customer tracking is not drawn in this file.
3. **`Officer: Nok` ghost button** — scopes the board to one officer. Agrees with the top-bar identity `Nok  ·  Officer` and with `46 of 200 customers`. Opens a picker; not drawn.
4. **`N more` pill** — reveals the remaining cards in that column (8 in Reminder, 1 in Demand letter). Expand-in-place or scroll; either way the pill must disappear once nothing is hidden.
5. **Card click** — opens the customer. This board is one card per *customer*, but the only detail screen in the file is `02 · Contract card`. A customer with more than one contract (`สยามกรีน` 2, `วัชระ` 2, `เอ็นซี พลัส` 3) needs a customer-level view or a contract chooser. Unresolved in the design.
6. **Board columns must not be re-orderable, addable or renameable** on this screen. No affordance is drawn and the ladder is fixed. Any such control belongs on screen 01.
7. **Search**, **nav items with counts**, and the **Current column's SummaryCard** are non-interactive as drawn — the SummaryCard explains an absence, it is not a "show 165 cards" button.
8. **Scrolling.** Reminder already reaches the bottom of the viewport at 1024. Any real dataset overflows; give the board region its own scroll and keep the top bar, nav, page header and rule note fixed.

---

## 7 · Fixture requirements

Seed data that makes this screen render truthfully.

**Clock.** `today = Tuesday 25 August 2026` — screen 01's header says `Tuesday 25 August 2026` and every date on this board is consistent with it (`20 Aug` and `22 Aug` past; `26`, `27`, `29 Aug` future; `Contacted today` alongside `Next contact 26 Aug`). Freeze the fixture clock there; do not use the real date.

**Shape of the population**
- 184 customers, one row per customer, split across five recovery stages: 165 / 12 / 4 / 2 / 1.
- 712 contracts overall (nav badge). A customer owns 1..3 contracts; the board must aggregate arrears and outstanding **up to the customer**, never show one row per contract.
- Both `natural person` and `juristic` customers, including juristic customers with 2 and 3 contracts.
- At least three owner identities so the foot renders `Nok`, `Ple` and `Owner`. Officer Nok holds 46 customers against a cap of 200.

**Cases that must exist or a state on this screen cannot be reached**
| Fixture | Why |
|---|---|
| A customer with **฿0 arrears still in `Restriction`**, with an overdue restoration deadline | Only source of the `Paid` green chip, the breach-bordered card, and the red foot. Proves recovery stage is not derived from payment state. |
| A **juristic** customer in `Restriction` with **no restriction notice sent** and **no signatory on file** | Only source of a two-chip flags row and of `Blocked until notice sent`. The database must refuse a restriction whose notice is unsent. |
| A customer with an **unmatched claim of ฿4,000**, 4 days unconfirmed | Only source of the blue `pending` chip. |
| A customer on **permit hold** with a permit reply 6 days overdue | Only source of a `held` flag paired with an over-threshold DPD chip. |
| A customer with **two broken promises** in `Demand letter` | Only source of a red flag chip on a non-Restriction card. |
| A customer in `Legal and recovery` with collateral valued and an assignment deed drafted, owned by `Owner` | Only card in that column; also the only `Owner` foot. |
| At least one customer with **no flags at all** in a column that has flagged siblings | Produces the 146px card and proves the flags row is optional. |
| **DPD values on both sides of the chip threshold** — the file uses 9, 12, 18 (grey) and 41, 47, 52, 63, 128 (red) | Otherwise one chip variant never renders. |
| At least one `Reminder` and one `Demand letter` customer **beyond the visible page** | Produces the `8 more` and `1 more` pills. |
| `Current` customers that generate **no due item** | The Current column must render its SummaryCard and **zero** cards even though 165 customers sit in that stage. |

**Money invariants the fixture must satisfy** (the Figma values do not — see §5.2)
- Every customer carries `arrears` and `outstanding`, with `arrears ≤ outstanding`. `arrears = 0` is legal and must still render `฿0` with the outstanding line beneath.
- Column head arrears/owed = the sum over **all** customers in that stage, not the visible ones.
- Where a column renders every one of its customers, head totals must equal the card totals **to the baht**.
- Where a column has a more-pill, head totals must be **strictly greater** than the sum of the visible cards.
- Page subtitle totals must equal the sum of the five column heads for count, arrears and owed.
- The Current column head has no arrears figure at all; it renders the literal `No arrears`, so a stage total of zero must not print `฿0` there.

**Formatting**
- Thai baht sign `฿` prefixed, thousands separated with commas, no decimals anywhere on this screen.
- Names are Thai; company names carry the `บริษัท … จำกัด` form. The card name wraps at 198.4px, so seed at least one name long enough to wrap.
- Dates render `D MMM` in English abbreviation (`26 Aug`), durations as `41 d` / `6 d` / `1 d 19 h`.

---

## 8 · House-rule checklist before you call it done

- [ ] `#f2b705` appears **only** in the wordmark bolt, the officer avatar and the caseload cap bar — never on a card, chip or column head.
- [ ] `brand/050 #fff7dc` is used only as the active nav tint.
- [ ] Every money figure on the screen is **arrears large, outstanding small beneath it** — cards and column heads alike. There is no place on this screen where a balance appears without its arrears above it.
- [ ] `Restriction` reconciles to the baht. `Legal and recovery` reconciles to the baht. `Reminder` and `Demand letter` heads strictly exceed their visible cards.
- [ ] No code path moves a card between columns without a human gesture, and a leftward move records a reason.
- [ ] No group-by, edit-columns or add-column control exists on this screen.
