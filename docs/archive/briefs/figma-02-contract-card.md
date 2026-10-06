# UI Brief — "02 · Contract card"

> **SUPERSEDED AS BUILD TARGET (2026-08-30).** Documents Figma "Product UI v0.1"; kept as the record. The rebuild absorbs this screen into Customer 360 (`docs/archive/briefs/screens-v2/`); `docs/product/workflow-v20-epc-spv.md` and `docs/product/user-journey.md` govern the new screens.

Source: Figma file `dAIFet044WF2P0FbUJfoT7`, page `0:1` "Volt Debt — UI v0.1", frame `8:2` "02 · Contract card".
All node ids below are Figma node ids, kept so any detail can be re-checked without hunting.

---

## 0. How to read this document (jargon and codes)

| Term on screen | What it means |
|---|---|
| **Arrears** | Money that is due *now and unpaid*. The sum of the unpaid part of every instalment whose due date has passed. |
| **Outstanding** | The whole remaining debt on the contract, arrears included, plus every instalment not yet due. Always the larger number. |
| **DPD / Days past due** | Days since the *oldest* still-unpaid instalment fell due. Drives the ageing band. |
| **Band 61 to 90** | The DPD bucket the contract sits in. Buckets are used for recovery policy, not just reporting. |
| **Instalment no.** | Position in the contract's fixed schedule, 1-based. This contract runs to 84. |
| **Counting contact** | A customer contact that consumes the one legally permitted contact per customer per day (Debt Collection Act). A non-counting note does not. |
| **Restriction** | The recovery action of reducing service output (here to 30 percent). It is legally gated on a notice having been sent first. |
| **Juristic** | A company / legal entity rather than a natural person. Must be contacted through a director or an authorised signatory. |
| **PEAK** | The accounting system the app reconciles cash against. |
| **Claim** | A payment the customer says they made that has not yet matched a PEAK posting. |
| **C-2023-0912** | Contract code. Format `C-<year signed>-<sequence>`. |
| **R-0041** | Restructure / modification record code. |
| `•` in a value | A masked digit. Uses U+2022 BULLET, never `*`. |

---

## 1. Frame size and layout split

Frame `8:2` — **1440 × 1024**. Frame ground colour **surface/100 `#f3f4f6`** (the ground shows through wherever no card covers it, notably the large empty area under the schedule card).

Three regions, no gaps between them:

| Region | Node | x, y | w × h | Fill / border |
|---|---|---|---|---|
| Top bar | `8:3` | 0, 0 | **1440 × 56** | `surface/0` + 1px bottom border `line/default` |
| Nav (left rail) | `8:15` | 0, 56 | **232 × 968** | `surface/0` + 1px right border `line/default` |
| Main | `8:338` | 232, 56 | **1208 × 968** | transparent — shows frame ground `surface/100` |

### 1.1 Top bar internals (px-20, `display:flex`, `align-items:center`, gap 16)

| Item | Node | x, y | w × h |
|---|---|---|---|
| Wordmark | `8:4` | 20, 16 | 109 × 24 |
| Spacer (flex-1) | `8:9` | 145, 0 | 851 × 56 |
| Search field | `8:10` | 1012, 11 | **280 × 34** |
| Officer chip | `8:12` | 1308, 14 | 112 × 28 |

### 1.2 Nav internals (px-12, py-16, column, gap 2)

Six nav items each **208 × 38**, `border-radius: 6`, px-12 py-9, row layout with a flex-1 spacer between label and count.

| Item | Node | y (within nav) |
|---|---|---|
| Today List | `8:16` | 16 |
| Contracts *(active)* | `8:20` | 56 |
| Promises | `8:24` | 96 |
| Exceptions | `8:28` | 136 |
| Modifications | `8:32` | 176 |
| Reports | `8:36` | 216 |
| 16px spacer | `8:39` | 256 |
| Workload card | `8:40` | 274 (208 × 78) |

### 1.3 Main internals — padding 24 left/right, content width **1160**

| Block | Node | y (within Main) | w × h |
|---|---|---|---|
| Breadcrumb | `8:339` | 18 | 1160 × 16 |
| Contract header | `8:343` | 50 | 1160 × 56 |
| Summary strip | `8:365` | 122 | 1160 × 96 |
| Body | `9:2` | 234 | 1160 × 664 |

Vertical gap between every block is **16px**; top padding is 18px. Body ends at y=898 inside a 968-tall Main, leaving **70px of empty ground** at the bottom.

### 1.4 Body split — two columns, 16px gutter

| Column | Node | x (within Body) | w × h |
|---|---|---|---|
| Left (tab panel) | `9:3` | 0 | **804 × 395** |
| Rail | `9:110` | 820 | **340 × 664** |

**Critical:** the Left card is only **395** tall and does **not** stretch. The Rail (664) sets the Body height. Below the Left card sits 269px of bare `surface/100` ground. Do not make the two columns equal height — the design deliberately lets the schedule card end where its rows end.

Left card height reconciles exactly: tabs 45 + head 34 + (7 rows × 40) 280 + footer 36 = **395**.
Rail height reconciles exactly: 263 + 12 + 244 + 12 + 133 = **664**.

---

## 2. Tokens

Use the project token names verbatim:

`ink/900 #050505`, `ink/800 #111827`, `ink/700 #374151`, `ink/600 #4b5563`, `ink/500 #6b7280`, `ink/400 #9ca3af`,
`surface/0 #ffffff`, `surface/50 #f9fafb`, `surface/100 #f3f4f6`, `line/default #e5e7eb`,
`brand/050 #fff7dc`, `brand/500 #f2b705`,
`status/current #16a34a` on `#dcfce7`, `status/pending #2563eb` on `#dbeafe`,
`status/overdue #dc2626` on `#fee2e2`, `status/held #6b7280` on `#f3f4f6`.

Type, all Kanit: `Display/24` 600/32, `Heading/16` 600/24, `BodyStrong/14` 500/20, `Body/14` 400/20, `Label/13` 500/18, `Small/13` 400/18, `Caption/12` 500/16.

**One extra style is present in the file and is not in the supplied token list — add it:**
`Title/20` = **Kanit SemiBold 20 / line-height 28 / letter-spacing 0**. Every one of the five summary stat values uses `Title/20`, **not** `Display/24`. `Display/24` is used exactly once on this screen: the customer name. Getting this wrong makes the summary strip 4px too tall per row and visibly overpowers the name.

Two letter-spacing values are applied and are easy to miss:
- Summary stat **labels** (`Arrears`, `Days past due`, …): `Caption/12` + **`letter-spacing: 0.36px`**.
- Schedule **column heads** (`NO`, `DUE DATE`, …): `Caption/12` + **`letter-spacing: 0.48px`**, and the text is literally uppercase in the file (not `text-transform`).

---

## 3. Components and their states

### 3.1 `Wordmark` (`8:4`)
Row, gap 8. Bolt icon **20 × 20** SVG — a lightning path **stroked** `#f2b705`, `stroke-width 1.66667`, round caps/joins, **no fill**. Then `VOLT` `Heading/16` `ink/900`, then `Debt` `Heading/16` `ink/500`. One state.

### 3.2 `Search` (`8:10`)
280 × 34, `surface/50` fill, 1px `line/default`, radius 6, px-12 py-7. Shown in **placeholder / unfocused** state only: text `Small/13` `ink/500`. No icon, no clear button, no focus ring is drawn — you must invent focus/filled/results states.

### 3.3 `Officer chip` (`8:12`)
Row, gap 8. Avatar = **28px circle**, fill `brand/050 #fff7dc`, 1px stroke `brand/500 #f2b705`, r=13.5 (stroke inset). No initials inside. Label `Small/13` `ink/700`. One state.

### 3.4 `Nav item` (`8:16`–`8:36`) — **two states drawn**
- **Default:** transparent background; label `Body/14` (Kanit **Regular**) `ink/600`; count `Caption/12` `ink/500`.
- **Active** (`Contracts`, `8:20`): background `brand/050 #fff7dc`, radius 6; label `Body/14` Regular **`ink/900`**; count `Caption/12` `ink/500`. **There is no left accent bar and no weight change** — the tint plus the darker label is the whole active treatment.
- `Reports` (`8:36`) has **no count** at all — the count slot is absent, not zero.
- Hover, focus and disabled are not drawn.

> **Two literal inconsistencies in the file, recorded so you decide once rather than guessing per item.** `Today List` (`8:17`) is the only label set in **Kanit Medium** (`BodyStrong/14`) while every other label is Kanit Regular; and its count `18` (`8:19`) is the only count in **`ink/700`** while every other count is `ink/500`. This looks like residue from screen 01 where Today List is the active item. Recommendation: normalise all inactive items to Regular / `ink/500` and keep the amber tint + `ink/900` as the only active signal.

### 3.5 `Workload` card (`8:40`)
208 × 78, `surface/50` fill, 1px `line/default`, radius 8, padding 12, column gap 6.
`Your caseload` `Caption/12` `ink/500` → `46 of 200 customers` `BodyStrong/14` `ink/800` → **Cap bar** (`8:43`) 180 × 6, radius 3, track `line/default`, fill `brand/500` (`8:44`) **166 × 6** from the left.

> **Defect to resolve before building.** 166 of 180 is **92%**, but `46 of 200` is **23%**. The drawn bar and the stated numbers disagree. Amber here is legitimate (brand as capacity meter, not status). Recommendation: drive the bar from the fixture (23% → 41px) and treat the Figma 166px as a drafting artefact — but flag it to the designer, because if the bar was meant to read "nearly at cap" then the caseload numbers are wrong instead.

### 3.6 `Breadcrumb` (`8:339`)
Row, gap 6, all `Caption/12` (Kanit Medium). `Today List` `ink/500` → `/` `ink/500` → `C-2023-0912` `ink/700`. The trailing segment is the current page (darker); the first segment is the back link. No chevron icons — a literal `/` text node.

### 3.7 `Badge` — one component, five colourways on this screen
Shape is identical everywhere: `padding: 3px 8px`, `border-radius: 4`, height **22**, text `Caption/12` (Kanit Medium), content-width.

| Colourway | Background | Text | Used by |
|---|---|---|---|
| neutral / meta | `surface/100 #f3f4f6` | `ink/700` | `JURISTIC` |
| status/current | `#dcfce7` | `#16a34a` | `Paid` |
| status/pending | `#dbeafe` | `#2563eb` | `Part paid` |
| status/overdue | `#fee2e2` | `#dc2626` | `RESTRICTION DUE`, `Overdue 63 d`, `Overdue 33 d` |
| status/held | `#f3f4f6` | `#6b7280` | `Not due` |

Note `JURISTIC` (a *classification*) and `Not due` (a *status*) share the same grey `#f3f4f6` background but differ in text colour: `ink/700` vs `status/held #6b7280`. Keep them as separate variants so the classification badge never picks up status semantics.

**House rule check — amber never appears in this table.** No badge on this screen is amber, and none may become amber.

### 3.8 `Button/ghost` (`8:361`)
`surface/0` fill, 1px `line/default`, radius 6, `padding: 9px 14px` → **height 38**. Label `BodyStrong/14` `ink/700`. Only the default state is drawn.

### 3.9 `Button/primary` — two sizes drawn
- **Inline** (`8:363`, `Log contact`): `brand/500` fill, **no border**, radius 6, `padding: 9px 14px` → height 38, 103 wide. Label `BodyStrong/14` **`ink/900`** (dark text on amber — never white).
- **Block** (`9:127`, `Send restriction notice`): `brand/500` fill, radius 6, `padding: 10px 0`, **full width 308 × 40**, content centred. Label `BodyStrong/14` `ink/900`.

The 38 vs 40 height difference is real in the file (py-9 vs py-10). Either normalise to one primary height or keep two named sizes — do not let it happen by accident.

**House rule check — this is brand amber as *the one primary action*, not as status.** The design contract on frame `12:22` states it explicitly: amber "marks the product, the next-up row, and the one primary action on a screen. It is never a status."

### 3.10 `Stat` (`8:366`, `8:370`, `8:374`, `8:378`, `8:382`)
Five instances filling the Summary strip, each `flex: 1 0 0` → **232 wide**, `padding: 14px 18px`, column, gap 4. Stats 2–5 carry a **1px left border `line/default`**; stat 1 does not. The strip itself is `surface/0`, 1px `line/default`, radius 8, `overflow: hidden` (so the dividers stop at the rounded corners).

Three lines, always:
1. **Label** — `Caption/12` `ink/500`, letter-spacing 0.36px.
2. **Value** — `Title/20` (Kanit SemiBold 20/28). Colour is `ink/900` **except** where the value is itself a breach: `Days past due` and `Recovery stage` are `status/overdue #dc2626`.
3. **Caption** — `Caption/12` `ink/500`.

**This component carries the arrears-large / balance-small rule — see §7.1.**

### 3.11 `Tabs` (`9:4`) — **two states drawn**
Strip: `surface/50` fill, 1px bottom border `line/default`, `padding: 8px 12px 0`, row, gap 4. Height 45.
- **Active** (`Schedule`, `9:5`): `surface/0` fill, **2px bottom border `brand/500 #f2b705`**, `padding: 8px 12px 9px`, label `BodyStrong/14` `ink/900`.
- **Inactive:** no fill, no border, same padding, label `Body/14` (Regular) `ink/500`.
- The count is **inside the same text node** as the label, separated by **two spaces** — e.g. the literal string `Contact log  24`. It is not a separate badge. The active tab `Schedule` has **no** count.

Amber is used here as a *selection* marker, which is allowed and is not a status.

### 3.12 `Sch head` / `Th` (`9:15`)
Row, `padding: 9px 16px`, gap **16**, 1px bottom border `line/default`, height 34, background transparent (i.e. `surface/0` from the card). Column widths and alignment are fixed:

| Th | Node | Width | Align |
|---|---|---|---|
| `NO` | `9:16` | 46 | left |
| `DUE DATE` | `9:18` | 150 | left |
| `AMOUNT` | `9:20` | 130 | **right** |
| `PAID` | `9:22` | 130 | **right** |
| `STATUS` | `9:24` | 150 | left |

Total: 16 + 46 + 16 + 150 + 16 + 130 + 16 + 130 + 16 + 150 = 686, inside an 804 card → 118px of unclaimed space to the right of STATUS. STATUS is left-aligned in its 150px box and the row does not stretch. (The design contract text says "12 px between columns"; the frame actually uses **16**. Build 16 — the drawn frame wins.)

### 3.13 `Sch row` / `Td` (`9:26`, `9:38`, `9:50`, `9:62`, `9:74`, `9:86`, `9:98`)
Height **40**, `padding: 9px 16px`, gap 16, 1px bottom border `line/default` — **except the last row (`9:98`), which has no bottom border** (the footer supplies the line). No zebra striping, no row fill, and **no hover or selected state is drawn**.

Cell typography, fixed per column:
- `NO` — `Small/13` (Regular 13) `ink/500`.
- `DUE DATE` — `Body/14` (Regular) `ink/700`.
- `AMOUNT` — `BodyStrong/14` (**Medium**) `ink/900`, right-aligned. This is the only Medium-weight cell; it is the number read down the column.
- `PAID` — `Body/14` (Regular) `ink/700` when there is a figure; `ink/500` when the value is the em dash `—`.
- `STATUS` — a Badge, left-aligned in the cell. Per the design contract: "badges never centred in a column".

### 3.14 `Sch footer` (`10:2`)
`surface/50` fill, **1px top border `line/default`**, `padding: 10px 16px`, height 36. Single line of `Caption/12` `ink/500`. This is a **provenance line, not a pager** — see §6.5.

### 3.15 `Card/Next action` (`9:111`) — the only amber-bordered card
340 × 263. Fill **`brand/050 #fff7dc`**, **1px border `brand/500 #f2b705`**, radius 8. Inner `padding: 14px 16px`, column, gap 10.

- Title `Next action` — `Heading/16` `ink/900`.
- **`Sequence`** (`9:114`) — column, gap 7, three `Step` rows each 20 tall, row layout gap 8, containing a **16 × 16 circle** then text. Three step states are drawn:

| Step | Dot fill | Text style | Meaning |
|---|---|---|---|
| 1 done | `#16a34a` (`status/current`) | `BodyStrong/14` `ink/800` | completed |
| 2 current | `#050505` (`ink/900`) | `BodyStrong/14` `ink/800` | the step you are on |
| 3 pending | `#e5e7eb` (`line/default`) | `Body/14` (Regular) **`ink/500`** | not reachable yet |

The pending step is the only one in Regular weight and muted ink — weight and colour both carry the state.

- **`Precondition`** (`9:124`) — full width, **`surface/0` fill** (deliberately white *inside* the amber card), 1px `line/default`, radius 6, `padding: 8px 10px`, column gap 3. Line 1 `Caption/12` **`status/overdue #dc2626`**; line 2 `Caption/12` `ink/600`, **wraps to 2 lines** (block height 32, total box 67).
- **`Button/primary`** block, 308 × 40 — see §3.9.

### 3.16 `Card/Contact rules` (`9:129`) and `Card/Accounting` (`9:153`)
Both: 340 wide, `surface/0` fill, 1px `line/default`, radius 8, inner `padding: 14px 16px`, column gap **9**. Heights 244 and 133 respectively.

- Title — `Heading/16` `ink/900`.
- **`Rule`** row (repeated) — height 18, row layout, gap 8: label `Small/13` (Regular) `ink/500` on the left, a **flex-1 spacer**, value `Label/13` (Medium) on the right. Value colour is `ink/800` by default, with two exceptions on this screen:
  - `Not on file` (`9:147`) → **`status/overdue #dc2626`** — a missing signatory is a breach, not neutral data.
  - `1  ·  ฿4,000` (`9:163`) → **`status/pending #2563eb`** — waiting on someone else (the accounting match). Blue here also reads as the affordance to open the claim.
- **Footnote** (`9:152`, Contact rules only) — `Caption/12` `ink/500`, full width, **wraps to 3 lines** (height 48).

The `Accounting` card has no footnote and no amber.

---

## 4. Literal text content — verbatim

> Reproduce these strings **exactly**, including the **double space either side of the middle dot `·`** wherever noted. That spacing is a deliberate convention across this file and reads wrong if collapsed to a single space. Masked digits are U+2022 `•`. The empty-cell mark is U+2014 `—`.

### Top bar
- `VOLT`
- `Debt`
- `Search customer, contract or invoice`  *(placeholder)*
- `Nok  ·  Officer`  *(two spaces around `·`)*

### Nav
- `Today List`
- `Contracts`
- `Promises`
- `Exceptions`
- `Modifications`
- `Reports`
- `Your caseload`
- `46 of 200 customers`

### Breadcrumb
- `Today List`
- `/`
- `C-2023-0912`

### Contract header
- `บริษัท ไทยรุ่ง จำกัด`  *(Thai, `Display/24`)*
- `JURISTIC`
- `RESTRICTION DUE`
- Meta row — five separate text nodes, 10px flex gap, rendered as: `C-2023-0912` · `Tax ID 0105556••••1` · `84 months from Mar 2023` · `Officer: Nok`
  (the three `·` are their own text nodes in `ink/500`; the four values are `ink/600`)
- `Statement`
- `Log contact`

### Summary strip — five stats, in order
| Label | Value | Caption |
|---|---|---|
| `Arrears` | `฿74,000` | `of ฿1,192,000 outstanding` |
| `Days past due` | `63` | `band 61 to 90` |
| `Next instalment` | `฿26,000` | `due 23 Sep 2026` |
| `Penalty accrued` | `฿7,842` | `on arrears, indicative  ·  accruing` *(two spaces around `·`)* |
| `Recovery stage` | `Restriction due` | `notice not yet sent` |

### Tabs — single text node each, two spaces before the count
- `Schedule`  *(active, no count)*
- `Contact log  24`
- `Promises  3`
- `Documents  11`
- `Modifications  1`

### Schedule column headings
- `NO`
- `DUE DATE`
- `AMOUNT`
- `PAID`
- `STATUS`

### Schedule rows — all seven, verbatim
| NO | DUE DATE | AMOUNT | PAID | STATUS |
|---|---|---|---|---|
| `37` | `23 Apr 2026` | `฿26,000` | `฿26,000` | `Paid` |
| `38` | `23 May 2026` | `฿26,000` | `฿26,000` | `Paid` |
| `39` | `23 Jun 2026` | `฿26,000` | `฿0` | `Overdue 63 d` |
| `40` | `23 Jul 2026` | `฿26,000` | `฿0` | `Overdue 33 d` |
| `41` | `23 Aug 2026` | `฿26,000` | `฿4,000` | `Part paid` |
| `42` | `23 Sep 2026` | `฿26,000` | `—` | `Not due` |
| `43` | `23 Oct 2026` | `฿26,000` | `—` | `Not due` |

### Schedule footer
`Instalment ฿26,000 carried from the signed contract, not recomputed  ·  schedule regenerated 12 Jun 2026 after restructure R-0041`
*(two spaces around `·`)*

### Rail — Next action
- `Next action`
- `Notice generated  ·  22 Aug`  *(two spaces around `·`)*
- `Notice sent to the customer`
- `Reduce output to 30 percent`
- `Step 3 is blocked`
- `The database refuses a restriction whose notice has not been sent. Send the notice first.`
- `Send restriction notice`

### Rail — Contact rules
- `Contact rules`
- `Assigned officer` → `Nok  ·  since 12 Jun`  *(two spaces around `·`)*
- `Counting contacts today` → `0 of 1`
- `Quiet hours` → `20:00 to 08:00`
- `Authorised signatory` → `Not on file`
- `Verified number` → `02-••••-4471`
- `A juristic customer must be contacted through a director or an authorised signatory. Overriding this needs the Owner.`

### Rail — Accounting
- `Accounting`
- `PEAK reconciled` → `Today 03:00`
- `Claims pending` → `1  ·  ฿4,000`  *(two spaces around `·`)*
- `Posting exceptions` → `None`

---

## 5. Every number on the screen

| Number as shown | What it labels |
|---|---|
| `18` | Today List nav count — open items on today's work list |
| `712` | Contracts nav count — contracts in scope |
| `31` | Promises nav count |
| `9` | Exceptions nav count |
| `4` | Modifications nav count |
| *(Reports)* | **no count** — the slot is absent |
| `46 of 200 customers` | Officer caseload against the 200-customer cap |
| `C-2023-0912` | Contract code, in breadcrumb and again in the header meta row |
| `0105556••••1` | Masked Thai tax ID (13 digits, middle 4 masked, first 7 and last 1 shown) |
| `84 months from Mar 2023` | Contract term and start month |
| `฿74,000` | **Arrears** — money due now and unpaid |
| `฿1,192,000` | **Outstanding balance** — whole remaining debt |
| `63` | Days past due on the oldest unpaid instalment |
| `61 to 90` | The DPD ageing band the contract falls in |
| `฿26,000` | Next instalment amount (also the amount of every schedule row) |
| `23 Sep 2026` | Next instalment due date |
| `฿7,842` | Penalty accrued on arrears — flagged `indicative` and still `accruing` |
| `24` | Contact log tab count — logged contacts on this contract |
| `3` | Promises tab count |
| `11` | Documents tab count |
| `1` | Modifications tab count |
| `37`–`43` | Instalment numbers of the seven visible rows (of 84) |
| `23 Apr 2026`, `23 May 2026`, `23 Jun 2026`, `23 Jul 2026`, `23 Aug 2026`, `23 Sep 2026`, `23 Oct 2026` | The seven due dates |
| `฿26,000` × 7 | AMOUNT of each of the seven rows |
| `฿26,000`, `฿26,000`, `฿0`, `฿0`, `฿4,000`, `—`, `—` | PAID per row, in order |
| `63 d` / `33 d` | Days overdue inside the two Overdue badges |
| `฿26,000` (footer) | The contract instalment, stated as carried, not recomputed |
| `12 Jun 2026` | Date the schedule was regenerated |
| `R-0041` | The restructure that caused the regeneration |
| `22 Aug` | Date the restriction notice was generated |
| `30 percent` | Output level the restriction would reduce to |
| `Step 3` | Which step of the three is blocked |
| `12 Jun` | Date the officer was assigned |
| `0 of 1` | Counting contacts used today, against the daily legal cap of 1 |
| `20:00 to 08:00` | Quiet hours during which contact is not permitted |
| `02-••••-4471` | Masked verified phone number |
| `03:00` | Time of the last PEAK reconciliation (`Today 03:00`) |
| `1` and `฿4,000` | Count and value of pending claims |

---

## 6. Interactions and overlay layers

**No overlay, popover, menu or dialog layer is drawn inside frame `8:2`.** Everything on the screen is in the base layer. The overlays this screen leads into live on the sibling frame `12:22` "04 · States" and are described in 6.2 and 6.3.

### 6.1 Base-layer interactions implied
- **Nav items** — navigate; `Contracts` is the active item because this contract was reached from a contract route. Note the breadcrumb says `Today List / C-2023-0912`, so the *route* came from Today List while the *nav* highlights Contracts. Pick one and make it consistent, or highlight from the route.
- **Breadcrumb `Today List`** — back link to frame `3:2`.
- **Search** — global search over customer, contract or invoice. Placeholder state only.
- **Officer chip** — presumed account menu. Nothing drawn.
- **`Statement`** (ghost) — produce the contract statement.
- **`Log contact`** (primary, header) — opens the contact-logging flow. This is the control governed by `Counting contacts today 0 of 1`.
- **Tabs** — swap the Left panel content. `Schedule` is active; `Contact log`, `Promises`, `Documents`, `Modifications` panels are not drawn anywhere and must be designed or stubbed.
- **`Claims pending  1  ·  ฿4,000`** — rendered in `status/pending` blue, which in this file marks "waiting on someone else". Treat as a link to the claim that matches the `฿4,000` part payment on instalment 41.
- **Schedule rows** — no hover, selection, expand or row menu is drawn. If rows need to be clickable, that state has to be invented.

### 6.2 `Send restriction notice` — read the refusal carefully
The `Step 3 is blocked` box does **not** disable the button. It explains that *step 3* (`Reduce output to 30 percent`) is blocked, and the button performs *step 2* (`Notice sent to the customer`) — which is exactly what unblocks step 3. **The button is enabled and fully amber.** A naive implementation that disables the primary action whenever a precondition box is present would dead-end the screen.

The design contract (`15:42`) states this refusal as: "Restriction blocked until the notice is sent, **lifted by nobody**." There is therefore **no override affordance** for this one — do not add a "request override" path here.

Pressing it should advance step 2 from current to done, step 3 from pending to current, clear the precondition box, and change `Recovery stage` from `Restriction due` / `notice not yet sent`.

### 6.3 `Log contact` — the overlay it leads to
`Counting contacts today` is at `0 of 1`, so the first press proceeds. Once the slot is spent, the flow hits the **`BLOCKED · DAILY CONTACT LOCK`** overlay defined on frame `14:33`: a scrim `Backdrop` with a centred **`Dialog` 452 wide**, containing a `Heading` title, an explanatory paragraph, a `Note` block, and an action row of one `Button/ghost` + one `Button/primary` (`Log a non-counting note` / `Request override`). Per design contract `15:41`, this refusal **is** liftable — "lifted by the Owner, recorded and reviewed monthly."

There is a second dialog of the same shape at `61:7` (`CONFIRM · A DRAG SPENDS THE DAILY SLOT`) belonging to the board screen, not to this one. Build one shared `Dialog` component: 452 wide, 20px inner padding, title `Heading/16`, body, optional `Note` block, action row right-aligned with ghost then primary.

### 6.4 `Authorised signatory — Not on file`
Red value plus the footnote establishes the third refusal from the design contract (`15:43`): "Signatory not on file, **overridden by the Owner** on a juristic customer." No control for this is drawn on this screen; the block would surface inside the `Log contact` flow.

### 6.5 The schedule shows 7 of 84 rows and offers no way to reach the rest
There is **no pager, no "show more", no scroll affordance and no date filter**. The `Sch footer` is provenance text only. This is a genuine gap you must fill — a window control is required before this screen is usable on an 84-instalment contract. Whatever you add must not disturb the 40px row height or the reconciliation in §7.

---

## 7. House rules — where each one lands on this screen

### 7.1 Arrears large, outstanding balance small beneath — **exactly one place**
It appears in the `Arrears` stat (`8:366`) and nowhere else:

```
Arrears                          Caption/12  ink/500   (letter-spacing 0.36px)
฿74,000                          Title/20    ink/900   ← arrears, large
of ฿1,192,000 outstanding        Caption/12  ink/500   ← outstanding balance, small, beneath
```

Two things follow that are easy to get wrong:
- The rule is **not** applied to the schedule table. `AMOUNT` and `PAID` are peer columns of a single instalment, not an arrears/balance pair. Do not stack them.
- The other four stats reuse the same three-line shape but their third line is a qualifier, not a balance (`band 61 to 90`, `due 23 Sep 2026`, `on arrears, indicative  ·  accruing`, `notice not yet sent`). Build one `Stat` component with a generic caption slot; the arrears instance is the one whose caption happens to be the balance.

### 7.2 Amber is the brand and never a status
On this screen `brand/500 #f2b705` appears in exactly five places, all legitimately non-status: the bolt icon stroke, the officer avatar ring, the caseload cap-bar fill, the active tab's 2px underline, and the two primary buttons. `brand/050 #fff7dc` appears twice: the active nav item and the Next action card. **No badge, no stat value and no schedule cell is amber**, and none may become amber — including any "warning" or "due soon" state you add later. Status is carried by four colours only: green current, red overdue or breached, blue awaiting someone else, grey held or not due.

### 7.3 Reconciliation
The schedule here is a **window** (rows 37–43 of 84), not a fully-drawn column, so it must *exceed* rather than equal what is visible. It does both, and the arithmetic is exact — keep it that way:

- **Arrears `฿74,000` reconciles exactly to the visible rows.** Unpaid portion of every row already due: `฿26,000` (row 39) + `฿26,000` (row 40) + `฿22,000` (row 41: 26,000 − 4,000) = **฿74,000**. Rows 42 and 43 are `Not due` and contribute nothing.
- **Outstanding `฿1,192,000` requires the 36 invisible rows above.** 84 × ฿26,000 = ฿2,184,000 total contract value. Received = 38 full instalments (฿988,000) + ฿4,000 on instalment 41 = ฿992,000. ฿2,184,000 − ฿992,000 = **฿1,192,000**. This only holds if instalments 1–36 are all fully paid in the fixture.
- **`63` days past due** is row 39's badge (`Overdue 63 d`), the oldest unpaid — not row 40's 33, and not row 41's 2. `63` sits inside `band 61 to 90`. Correct.
- **The two overdue counts fix the as-of date.** 23 Jun 2026 + 63 d = **25 Aug 2026**; 23 Jul 2026 + 33 d = **25 Aug 2026**. Both agree. Every relative string on the screen (`Today 03:00`, `22 Aug`, `0 of 1`) must be computed against **25 Aug 2026**.
- **Row 41 is `Part paid`, not overdue**, though it is 2 days past due on 25 Aug 2026. Part-paid outranks overdue in the status precedence.
- **`Next instalment ฿26,000 due 23 Sep 2026`** is row 42, the first `Not due` row — not the first unpaid row.
- **`Claims pending 1 · ฿4,000`** is the same ฿4,000 as row 41's PAID cell. One claim, one amount, two places. They must move together.
- **Due dates reconcile to the contract start.** `84 months from Mar 2023` with instalment *n* due on the 23rd of the *n*-th month after Mar 2023 gives n=37 → 23 Apr 2026 and n=43 → 23 Oct 2026. Both match.

---

## 8. Fixture requirements

Seed data needed for this screen to render truthfully. Every figure below is forced by §7.3 — changing one breaks the reconciliation.

**Clock**
- Freeze "today" at **25 Aug 2026**. Non-negotiable: it is the only date that makes both `Overdue 63 d` and `Overdue 33 d` true.

**Customer**
- Name `บริษัท ไทยรุ่ง จำกัด`, type **juristic** (drives the `JURISTIC` badge and the whole Contact rules footnote).
- Tax ID: 13 digits rendering to `0105556••••1` under the mask rule "show first 7 and last 1".
- Verified phone rendering to `02-••••-4471`; **no authorised signatory on file** (must be genuinely absent, not empty-string, so the red `Not on file` is real).

**Contract**
- Code `C-2023-0912`; start **Mar 2023**; term **84 monthly instalments**; instalment amount **฿26,000** flat, carried from the signed contract and explicitly *not* recomputed; due day-of-month **23**. Instalment 1 = 23 Apr 2023, instalment 84 = 23 Mar 2030.
- Total contract value ฿2,184,000.
- Assigned officer `Nok`, assigned **12 Jun 2026**.

**Schedule ledger** — all 84 rows must exist, not just the seven visible:
- Instalments **1–38**: fully paid, ฿26,000 each (= ฿988,000). Rows 1–36 are off-screen but are what makes `฿1,192,000` correct.
- Instalment **39** (23 Jun 2026): paid ฿0 → `Overdue 63 d`.
- Instalment **40** (23 Jul 2026): paid ฿0 → `Overdue 33 d`.
- Instalment **41** (23 Aug 2026): paid ฿4,000 of ฿26,000 → `Part paid`.
- Instalments **42–84**: unpaid and not yet due → `Not due`, PAID renders as `—` (null, not zero — `฿0` and `—` are different states in this table).
- Derived: arrears ฿74,000; outstanding ฿1,192,000; received to date ฿992,000.
- A **restructure record `R-0041`** dated **12 Jun 2026** that regenerated the schedule.

**Penalty**
- Accrued **฿7,842**, computed on arrears, flagged `indicative` and still accruing. Not derived from any other figure on screen — seed it as a literal.

**Recovery**
- Stage = `Restriction due`; restriction notice **generated 22 Aug 2026**, **not yet sent**. Step state: step 1 done, step 2 current, step 3 (`Reduce output to 30 percent`) blocked on the send.

**Contact rules**
- Counting contacts used today = **0**, daily cap = **1**.
- Quiet hours **20:00–08:00**.

**Accounting**
- Last PEAK reconciliation **25 Aug 2026 03:00** (renders `Today 03:00` against the frozen clock).
- Exactly **1** pending claim, value **฿4,000**, matched to instalment 41.
- **0** posting exceptions (renders `None`, not `0`).

**Related-record counts** (drive the tab labels; the panels themselves are not designed)
- Contact log **24**, Promises **3**, Documents **11**, Modifications **1**.

**Officer / global counts**
- Officer `Nok`, role `Officer`.
- Caseload **46** of cap **200**.
- Nav counts: Today List **18**, Contracts **712**, Promises **31**, Exceptions **9**, Modifications **4**. Reports has no count.

---

## 9. Open items to settle before or during build

1. **Caseload bar geometry contradicts its own label** (§3.5) — 166/180 drawn vs 46/200 stated.
2. **`Title/20` is missing from the token list** (§2) — add it, or the summary strip will be built at the wrong size.
3. **Nav highlights `Contracts` while the breadcrumb comes from `Today List`** (§6.1).
4. **`Today List` nav item uses a different weight and count colour** from its five siblings (§3.4).
5. **Primary button exists at two heights**, 38 and 40 (§3.9).
6. **No way to page through the other 77 instalments** (§6.5).
7. **Four tab panels are undesigned** — `Contact log`, `Promises`, `Documents`, `Modifications` (§6.1).
8. **No hover, focus, selected or disabled states are drawn anywhere on this frame.** Every one of them has to be invented; keep amber out of all of them except selection and primary action.
