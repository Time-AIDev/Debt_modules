# UI brief — "03 · Exception dashboard"

> **SUPERSEDED AS BUILD TARGET (2026-08-30).** Documents Figma "Product UI v0.1"; kept as the record. The rebuilt Exceptions screen keeps this brief's refusal flow but gains the EPC/SPV entity axis — see `docs/archive/briefs/screens-v2/` and `docs/product/workflow-v20-epc-spv.md`.

Source: Figma file `dAIFet044WF2P0FbUJfoT7`, page `0:1` "Volt Debt — UI v0.1", frame `10:4` "03 · Exception dashboard".
Extracted 2026-08-26. Every value below is measured from the frame; nothing is inferred unless the line says so.

---

## 0. Plain language — what the words and codes on this screen mean

Read this first if you have not worked on Volt Debt before. The screen is dense with in-house vocabulary.

| Term as it appears | What it actually means |
|---|---|
| **Exception** | A row that the nightly reconciliation could not settle by itself. It needs a named human to act. |
| **Posting exception** | Volt Debt tried to push a document into the accounting system and the push failed. Owner is IT. |
| **Claim exception** | A customer sent a payment slip, Accounting has not yet confirmed a receipt against it. Until a receipt exists the money does not count as paid. |
| **Restoration overdue** | The customer has already cleared their arrears but their service is still throttled. Nothing in software fixes this — somebody must go and physically restore output. |
| **Reconciled 03:00** | The batch that produces this screen runs at 03:00. Everything on screen is as of that run. |
| **Correction window** | 17:00 same day. After that the day's exceptions harden and roll to the next cycle. |
| **Owner** | The accountable role for a queue (IT, Accounting, or the account Owner), printed on each card so nobody has to ask whose job it is. |
| **Chase** | A nudge sent to Accounting asking them to confirm an outstanding claim. The count beside it is how many have already gone. |
| **Period locked** | The accounting period is closed, so the document cannot post. |
| **Rate limited** | The accounting API throttled us. Transient — it will retry. |
| **Auth failure** | Our credential was rejected. Not transient — a human must act. |
| **P1** | Highest severity. Used here because the customer has already paid and is still being penalised. |
| **Service level** | The agreed age at which an unconfirmed claim is late. Seeded at 2 days on this screen. |
| **Seeded / backfilled** | The value came from migration seed data, not from live operation. |
| **C-YYYY-NNNN** | Contract identifier. |
| **฿** | Thai baht. |
| **DPD / arrears / outstanding balance** | Days past due; money overdue now; total still owed. Note: **no arrears figure appears on this screen** — see §7. |

---

## 1. Frame, and the top-bar / nav / main split

Frame `10:4` is **1440 × 1024**, fixed. Three regions, no gaps between them, no overlap.

| Region | Node | Origin (x,y) | Size | Background | Border |
|---|---|---|---|---|---|
| Top bar | `10:5` | 0, 0 | **1440 × 56** | `surface/0` #ffffff | bottom 1px `line/default` #e5e7eb |
| Nav | `10:17` | 0, 56 | **232 × 968** | `surface/0` #ffffff | right 1px `line/default` #e5e7eb |
| Main | `10:340` | 232, 56 | **1208 × 968** | `surface/100` **#f3f4f6** | none |

**Main is not white.** It is the grey canvas `surface/100` #f3f4f6; the cards sitting on it are white. Getting this backwards flattens the whole screen.

### 1.1 Top bar internals
`display:flex; align-items:center; gap:16px; padding:0 20px;`

| Child | Node | x | Size | Notes |
|---|---|---|---|---|
| Wordmark | `10:6` | 20 | 109 × 24 | flex, gap 8, align center |
| — Bolt icon | `10:7` | +0 | 20 × 20 | SVG, stroke `brand/500` #F2B705, `stroke-width:1.66667`, round cap+join, no fill. Path: `M10.8333 8.33333V2.5L3.33333 11.6667H9.16667V17.5L16.6667 8.33333H10.8333Z` on `viewBox="0 0 20 20"` |
| — "VOLT" | `10:9` | +28 | 38 × 24 | Heading/16, `ink/900` #050505 |
| — "Debt" | `10:10` | +74 | 35 × 24 | Heading/16, `ink/500` #6b7280 |
| Spacer | `10:11` | 145 | flex-1 (851 here) | `flex:1 0 0; min-width:0` |
| Search | `10:12` | 1012, y 11 | **280 × 34** | bg `surface/50` #f9fafb, 1px `line/default`, radius **6**, padding 7px 12px |
| Officer | `10:14` | 1308, y 14 | 112 × 28 | flex, gap 8 |
| — Avatar | `10:15` | +0 | 28 × 28 | SVG circle `r=13.5`, fill `brand/050` **#FFF7DC**, stroke `brand/500` **#F2B705** 1px. No photo, no initials. |
| — Label | `10:16` | +36 | 76 × 18 | Small/13, `ink/700` #374151 |

### 1.2 Nav internals
`display:flex; flex-direction:column; gap:2px; padding:16px 12px;`

Every nav item: **width 208 (100%), height 38**, `padding:9px 12px; border-radius:6px; display:flex; align-items:center; gap:8px`, with a `flex:1 0 0; height:8px` spacer between label and count.

Item origins (nav-local y): 16, 56, 96, 136, 176, 216. After the last item: a **16px spacer** frame (`10:41`) at y=256. Total painted nav block = 16 + 6×38 + 5×2 = **254px**; everything below y=270 in the nav is bare white.

### 1.3 Main internals
`display:flex; flex-direction:column; gap:18px; padding:20px 24px 0;` — content column width **1160**.

| Block | Node | Main-local y | Size |
|---|---|---|---|
| Page header | `10:341` | 20 | 1160 × 54 |
| Tiles | `10:350` | 92 | 1160 × 98 |
| Queues | `11:2` | 208 | 1160 × 310 |
| Restoration overdue card | `12:2` | 536 | 1160 × 130 |

Content ends at Main-local y **666** (absolute y 722). **The bottom 302px of Main is bare #f3f4f6** — verified pixel-uniform across the full width. There is no footer, no pagination, no empty-state panel, no "load more". Do not put anything there.

The gap is **18px**, not 16 or 20. It is consistent across all four blocks.

---

## 2. Components and their states

### 2.1 `NavItem`
| State | Background | Label type + colour | Count type + colour |
|---|---|---|---|
| **Active** (Exceptions) | `brand/050` **#fff7dc** | Body/14 (Kanit Regular 14/20), `ink/900` #050505 | Caption/12, `ink/500` #6b7280 |
| **Emphasised** (Today List) | transparent | **BodyStrong/14 (Kanit Medium 14/20)**, `ink/600` #4b5563 | Caption/12, **`ink/700` #374151** |
| **Default** (Contracts, Promises, Modifications) | transparent | Body/14 Regular, `ink/600` #4b5563 | Caption/12, `ink/500` #6b7280 |
| **No count** (Reports) | transparent | Body/14 Regular, `ink/600` #4b5563 | count element **absent entirely** — not "0", not an empty span |
| Hover / focus / pressed | **not drawn** — you must author them |

Two traps here:
1. **Active is not bold.** Active = tinted background + `ink/900` label at *Regular* weight. The only Medium-weight label in the nav is "Today List", which is *not* the active item. If you bold the active row you have invented a state.
2. **"Today List" is emphasised, "Exceptions" is active.** They are different treatments and both appear at once.

### 2.2 `Button/primary`
`bg brand/500 #f2b705; border-radius:6px; padding:9px 14px; no border;` label BodyStrong/14 `ink/900` #050505.
Two instances: "Open oldest" (105 × 38), "Raise restoration order" (173 × 38).
Height 38 in both cases. No hover/disabled/loading state drawn.

### 2.3 `Button/ghost` — two sizes, both used
| Variant | Padding | Radius | Label | Size on screen |
|---|---|---|---|---|
| Large (`10:346`) | 9px 14px | **6** | BodyStrong/14 `ink/700` #374151 | 168 × 38 ("Export for Accounting") |
| Small (`11:86` etc.) | 4px 10px | **5** | Caption/12 `ink/700` #374151 | 53 × 24 ("Chase") |

Both: `bg surface/0 #ffffff; border 1px line/default #e5e7eb`. Note the radius differs (6 vs 5) — it is not a rounding artefact, it is authored.

### 2.4 `Tile` (metric tile)
`flex:1 0 0; min-width:0; display:flex; flex-direction:column; gap:5px; padding:12px 14px; border-radius:8px; border:1px solid; overflow:hidden;`
Three stacked lines: label (Caption/12) → value (Display/24, Kanit SemiBold 24/32) → caption (Caption/12).

| State | Border | Background | Label | Value | Caption |
|---|---|---|---|---|---|
| **Default** | `line/default` #e5e7eb | `surface/0` #ffffff | `ink/500` #6b7280 | **`ink/900` #050505** | `ink/500` #6b7280 |
| **Alert** (tile 1 only) | **`status/overdue` #dc2626** | **`status/overdue` bg #fee2e2** | **#dc2626** | **#dc2626** | `ink/500` #6b7280 (stays grey) |
| **Zero** (tile 6 only) | `line/default` #e5e7eb | `surface/0` #ffffff | `ink/500` | **`ink/500` #6b7280** | `ink/500` |

The **zero state** is the only difference between tile 6 and a default tile: the value drops from `ink/900` to `ink/500`. Chrome is identical. A `0` rendered in #050505 is wrong.
In the alert tile the caption stays `ink/500` grey while label and value go red — do not tint the whole tile red.

### 2.5 `Card` (queue card)
`bg surface/0 #ffffff; border 1px line/default #e5e7eb; border-radius:8px; overflow:hidden; display:flex; flex-direction:column;`

**Card head** — `padding:13px 16px 12px; gap:3px; border-bottom:1px line/default`
- Title row: `flex; align-items:center; gap:8px` → title (Heading/16, `ink/900`) + `flex:1 0 0; height:8px` spacer + owner note (Caption/12, `ink/500`, right).
- Description line: Caption/12, `ink/500`, full width.
- Head height **68px** in both cards.

**Th row** — `bg surface/50 #f9fafb; padding:8px 16px; gap:12px; align-items:center; border-bottom:1px line/default;` height **32px**.
Each `Th`: Caption/12, `ink/500`, **UPPERCASE**, `letter-spacing:0.48px`.

**Row** — `padding:9px 16px; gap:12px; align-items:center; border-bottom:1px line/default`. **The last row in each card has no bottom border** (the card's own border closes it).
Row height is content-driven, and the two cards differ:
- Posting rows: **40px** (tallest child is the 22px badge → 9+22+9)
- Claim rows: **42px** (tallest child is the 24px Chase button → 9+24+9)

Do not hard-code a single row height; one card will break.

### 2.6 `Badge` (posting REASON column)
`padding:3px 7px; border-radius:4px; no border;` label Caption/12. Height 22px.

| Text | Background | Text colour | Token |
|---|---|---|---|
| Period locked | #fee2e2 | #dc2626 | `status/overdue` |
| Rate limited | **#dbeafe** | **#2563eb** | `status/pending` |
| Auth failure | #fee2e2 | #dc2626 | `status/overdue` |

Reading of the rule: **blue = transient, will retry on its own; red = stuck, needs a human.** "Rate limited" is the only blue one.

### 2.7 `Card/Restoration overdue` (full-width alert card)
`bg surface/0 #ffffff; border 1px status/overdue #dc2626; border-radius:8px; overflow:hidden;`
- **Head** `12:3`: `bg status/overdue-bg #fee2e2; padding:13px 16px 12px; gap:3px;` height **68**. Title Heading/16 **#dc2626**; description Caption/12 **`ink/600` #4b5563** (darker than the queue-card descriptions, which are `ink/500`).
- **Row** `12:6`: `bg #ffffff; padding:12px 16px; gap:16px; align-items:center;` height **62**. No divider line between head and row — the pink simply stops.
- Row children: four stacked `Td`s of fixed width **230 / 160 / 150 / 180**, then a `flex:1 0 0; height:8px` spacer (155px here), then the primary button.

**The two stack orders in this row are different and both are intentional:**
- `Td` 1 (identity): **value on top** — name BodyStrong/14 `ink/900`, contract Caption/12 `ink/500` beneath. gap 2.
- `Td` 2–4 (facts): **label on top** — label Caption/12 `ink/500`, value BodyStrong/14 beneath. gap 2.

### 2.8 `Search`
Static box with placeholder only. No focus ring, no caret, no clear button, no results list drawn.

---

## 3. Verbatim text — every string on the screen

Copy these exactly. **The separator is two spaces, U+00B7 MIDDLE DOT, two spaces** (`"  ·  "`). It is used in four places and is double-spaced in all four.

### Top bar
- `VOLT`
- `Debt`
- `Search customer, contract or invoice`  (placeholder)
- `Nok  ·  Officer`

### Nav
- `Today List`
- `Contracts`
- `Promises`
- `Exceptions`
- `Modifications`
- `Reports`

Hidden nav block `10:42` (see §6.3), authored but not visible:
- `Your caseload`
- `46 of 200 customers`

### Page header
- `Exceptions`
- `Reconciled 03:00  ·  digest sent to the Owner 08:00  ·  correction window closes at 17:00`
- `Export for Accounting`
- `Open oldest`

### Tiles (label / caption)
1. `Restoration overdue` / `P1  ·  customer has paid`
2. `Posting failures` / `oldest 6 h`
3. `Claims past service level` / `2 days seeded`
4. `Duplicate invoice groups` / `same payer, amount, date`
5. `Terms differences` / `schedule governs`
6. `Restriction without notice` / `baseline 18 backfilled`

### Card — Posting exceptions
- Title: `Posting exceptions`
- Owner note: `Owner: IT, corrected within one business day`
- Description: `What Volt Debt failed to send to the accounting system.`
- Column headings: `CONTRACT` · `DOCUMENT` · `AMOUNT` · `REASON` · `AGE`
- Cell strings: `C-2024-0188`, `Penalty invoice`, `Period locked` · `C-2023-0912`, `Closure void`, `Rate limited` · `C-2024-0655`, `Adjustment`, `Auth failure`

### Card — Claim exceptions
- Title: `Claim exceptions`
- Owner note: `Owner: Accounting`
- Description: `What Accounting has not confirmed. A slip is not a payment until a receipt exists.`
- Column headings: `CONTRACT` · `CLAIMED` · `SUBMITTED` · `AGE` · `CHASES`
- Contract ids: `C-2024-0655`, `C-2025-0077`, `C-2024-0421`, `C-2023-0338`, `C-2025-0201`
- Chase counters: `2 sent`, `1 sent`, `1 sent`, `0 sent`, `0 sent`
- Button label (×5): `Chase`

### Card — Restoration overdue
- Title: `Restoration overdue  ·  1 account`
- Description: `The customer cleared their arrears and their output is still reduced. No engineer can fix this: the fix is a field action, so it goes to the Owner, not to the on-call rota.`
- Customer name (Thai): `ประเสริฐ ใจงาม`
- Field labels: `Arrears cleared` · `Still restricted for` · `Output now`
- Button: `Raise restoration order`

Thai renders in Kanit at BodyStrong/14 (14/20). Kanit covers Thai; do not fall back to a Latin-only face. `ประเสริฐ ใจงาม` measures 87px wide inside a 230px `Td`, so there is headroom for longer names, but the `Td` is fixed-width and clips (`overflow:hidden`) — longer names will be cut, not wrapped.

---

## 4. Every number on the screen, and what it labels

### Nav counts (Caption/12, right-aligned)
| Item | Number |
|---|---|
| Today List | **18** |
| Contracts | **712** |
| Promises | **31** |
| Exceptions | **9** |
| Modifications | **4** |
| Reports | *(no count element)* |

### Page header — times inside the subtitle
`03:00` reconciliation run · `08:00` digest to Owner · `17:00` correction window closes.

### Tiles — value, plus any number inside the caption
| # | Label | Value | Numbers in caption |
|---|---|---|---|
| 1 | Restoration overdue | **1** | `P1`, i.e. severity 1 |
| 2 | Posting failures | **3** | oldest **6 h** |
| 3 | Claims past service level | **5** | **2** days seeded |
| 4 | Duplicate invoice groups | **2** | — |
| 5 | Terms differences | **15** | — |
| 6 | Restriction without notice | **0** | baseline **18** backfilled |

### Posting exceptions — 3 rows
| Contract | Document | Amount | Reason | Age |
|---|---|---|---|---|
| C-2024-0188 | Penalty invoice | **฿1,240** | Period locked | **6 h** |
| C-2023-0912 | Closure void | **฿48,000** | Rate limited | **3 h** |
| C-2024-0655 | Adjustment | **฿2,100** | Auth failure | **1 h** |

### Claim exceptions — 5 rows
| Contract | Claimed | Submitted | Age | Chases |
|---|---|---|---|---|
| C-2024-0655 | **฿4,000** | **21 Aug 09:40** | **4 d** (red) | **2 sent** |
| C-2025-0077 | **฿12,000** | **22 Aug 14:02** | **3 d** (red) | **1 sent** |
| C-2024-0421 | **฿8,500** | **23 Aug 11:15** | **2 d** (blue) | **1 sent** |
| C-2023-0338 | **฿15,000** | **23 Aug 16:48** | **2 d** (blue) | **0 sent** |
| C-2025-0201 | **฿6,300** | **24 Aug 10:07** | **1 d** (grey) | **0 sent** |

### Restoration overdue — 1 row
`ประเสริฐ ใจงาม` / **C-2023-0455** · Arrears cleared **23 Aug 15:22** · Still restricted for **1 d 19 h** (red) · Output now **30 percent**.

Note `30 percent` is spelled out as a word. There is no `%` glyph anywhere on this screen.

### 4.1 The reconciliation ledger — check this before you ship

House rule: *a fully-drawn column must reconcile exactly to its cards; a column with a "more" card need only exceed what is visible.*

**There is no "more" card anywhere on this screen.** All three drawn queues are fully drawn, so all three must reconcile **exactly**:

| Tile | Value | Drawn rows | Verdict |
|---|---|---|---|
| Restoration overdue | 1 | Card head says `1 account`, 1 row | exact ✓ |
| Posting failures | 3 | 3 rows | exact ✓ |
| Claims past service level | 5 | 5 rows | exact ✓ |

Two derived numbers must also hold:
- Tile 2 caption **`oldest 6 h`** = `max(6 h, 3 h, 1 h)` from its own rows. If you reorder or reseed the posting rows, this caption must move with them.
- Card head **`1 account`** must equal both tile 1 and the row count.

**The nav badge is the sharpest constraint.** Nav `Exceptions = 9` = **1 + 3 + 5**, the three *drawn* queues only. It is **not** the sum of all six tiles (which is 26). Tiles 4 (2), 5 (15) and 6 (0) are counted and displayed but are **not** part of the Exceptions badge. If your badge computes from all exception types you will render 26 and silently break the design's arithmetic.

**Tiles 4, 5 and 6 have no drawn destination on this frame.** `Duplicate invoice groups` (2), `Terms differences` (15) and `Restriction without notice` (0) are counts with no corresponding card, table or list anywhere on the screen. That is deliberate — they are informational, not actionable today — but it means clicking them has no designed target (see §5).

---

## 5. Interactions implied, and overlay layers

### 5.1 There are no overlays
The frame contains **no** modal, popover, tooltip, dropdown, menu, toast, drawer or context menu — no such node exists, visible or hidden. The **only** hidden node in the entire frame is the nav Workload block (`10:42`, §6.3). If your build needs a confirmation dialog for "Raise restoration order" or "Chase", it is unspecified and you are inventing it — flag it rather than guessing.

### 5.2 Implied actions
| Control | Implied behaviour | Specified? |
|---|---|---|
| Search field | Typeahead across customer, contract and invoice (per its own placeholder) | Field drawn; focus/results **not drawn** |
| Nav item | Navigate; active row takes `brand/050` tint | Active drawn; hover/focus **not drawn** |
| `Export for Accounting` | Produce the accounting hand-off for the current exception set | Trigger only; format, scope and success feedback **not drawn** |
| `Open oldest` | Jump to the single oldest open exception. **Ambiguous** — across queues the oldest is the 4 d claim (C-2024-0655); within posting it is 6 h; restoration is 1 d 19 h. The ranking rule is not specified. Decide and document it. | Trigger only |
| `Chase` (×5) | Send a nudge to Accounting; must increment the `N sent` counter in the same `Td` | Trigger only; no sent/disabled/cooldown state drawn |
| `Raise restoration order` | Dispatch the field action to the account Owner (explicitly *not* to the on-call rota, per the card's own description) | Trigger only |
| Tile 1–3 | Presumably filter/scroll to the matching queue | **Not drawn** |
| Tile 4–6 | No destination exists on this screen | **Not drawn** |
| Table row | Contract ids are plain `Small/13` `ink/700` text — **no underline, no brand colour, no link styling**. If rows are clickable it is whole-row navigation, not a link. | **Not drawn** |

### 5.3 State-driven colour rules you must implement

**Claim AGE column** — BodyStrong/14 (Kanit Medium 14/20), right-aligned:
- age **> 2 d** → `status/overdue` #dc2626  (4 d, 3 d)
- age **= 2 d** → `status/pending` #2563eb  (both 2 d rows)
- age **< 2 d** → `ink/500` #6b7280  (1 d)

The 2-day threshold is named by tile 3's caption `2 days seeded`.

**Posting AGE column is a different component.** It is `Small/13` **Regular** and **always** `ink/500` #6b7280 — 6 h, 3 h and 1 h are all grey, with no escalation at all. Two columns both headed `AGE`, different type and different colour rule. This is the single easiest thing to get wrong on this screen.

**`Still restricted for` value** in the restoration banner is `status/overdue` #dc2626; the other two values in that row (`23 Aug 15:22`, `30 percent`) are `ink/900`.

---

## 6. Empty, zero and unset states

### 6.1 The unfiltered dashboard is NOT drawn — this is the important gap
The dashboards are specified to return **422 `population_filter_unset`** until a population filter is authored. **This frame does not draw that state, and it does not draw the control that would author the filter.**

Verified absences:
- **No population-filter control anywhere.** Not in the top bar (wordmark, spacer, search, officer — that is all), not in the nav (six links, nothing else), not in the page header (title, subtitle, `Export for Accounting`, `Open oldest` — that is all). There are no filter chips, no segmented control, no date-range picker, no scope selector, no "showing N of M" line.
- **No empty-state panel.** The 302px below the restoration card is pixel-uniform `#f3f4f6`.
- **No zero-row state for any queue card.** All three cards are drawn populated.

So this frame is **the populated, filter-already-authored state only**. Before you build, you must resolve:
1. What authors the population filter, and where that control lives (nothing on this screen can do it).
2. What the screen looks like when the API returns 422 — the whole main column, or per-card?
3. Whether the tiles render at all when unfiltered, and if so with what values.

Do not silently render this layout with zeroes as a stand-in for the 422 state. The one authored zero treatment (§6.2) is a *legitimate* zero, not an error, and reusing it for 422 would tell the operator "nothing is wrong" when the truth is "nothing has been asked".

### 6.2 The one authored zero state
Tile 6 `Restriction without notice` = **0**. The value renders in `ink/500` #6b7280 instead of `ink/900` #050505. Border, background, label and caption are unchanged from a default tile. This is "a real count that happens to be zero" — muted, not alarmed, not hidden.

Its caption `baseline 18 backfilled` says the zero is trustworthy *because* 18 historical records were seeded. Preserve that pairing: a bare `0` with no provenance caption reads as "not loaded".

### 6.3 The hidden nav Workload block
Node `10:42` "Workload" (nav-local 12, 274; 208 × 78) is authored but **`hidden`** on this frame. It contains:
- `Your caseload` — Caption/12
- `46 of 200 customers` — BodyStrong/14
- `Cap bar` (`10:45`) — 180 × 6 progress bar

It is the only hidden node in the frame. On this screen the nav simply ends after the 16px spacer. Build the nav so this block is a conditional, not a deletion — it evidently appears on other screens (Today List).

### 6.4 Absent vs zero
`Reports` has **no count element at all** — not a `0`, not an empty span. Distinguish "this destination has no counter" from "this counter reads zero". They look different and mean different things.

---

## 7. House-rule compliance notes

### 7.1 Amber is the brand and is never a status
`brand/500` #f2b705 and `brand/050` #fff7dc appear in exactly four places on this screen, all of them brand or interaction, never status:
1. Bolt icon stroke (brand mark)
2. Officer avatar — fill `brand/050`, stroke `brand/500` (identity chip)
3. Active nav row background `brand/050` (selection)
4. The two `Button/primary` fills (primary action)

Every status meaning is carried by red, blue or grey only. The clearest demonstration: the **Restoration overdue** card — the most urgent thing on the screen — is red `#dc2626` on `#fee2e2`, and the amber `Raise restoration order` button sits *inside* it. **Red states the problem; amber offers the action.** Never tint a tile, badge, age or row amber to mean "warning".

Also note `#f2b705` fails contrast against white for text — it is used only as a fill behind `ink/900` #050505 labels, never as a text or border colour.

### 7.2 Arrears large / outstanding balance small — does not fire on this screen
The house rule is *every money figure shows arrears large with outstanding balance small beneath it.* **No money figure on this screen is an arrears figure**, so the two-line treatment correctly does not appear:
- Posting `AMOUNT` (฿1,240 / ฿48,000 / ฿2,100) is the **document** amount that failed to post.
- Claim `CLAIMED` (฿4,000 / ฿12,000 / ฿8,500 / ฿15,000 / ฿6,300) is the amount **asserted on a slip** that Accounting has not confirmed.

Both render single-line, **BodyStrong/14, `ink/900`, right-aligned**. Do not bolt a second line under them.

**Watch for the false positive:** the restoration banner's `Td`s *are* two-line stacks and look like the arrears pattern. They are not. `Arrears cleared / 23 Aug 15:22` is a **label above a timestamp** (small-then-large), the opposite order from arrears-over-balance (large-then-small). The only large-then-small stack on the screen is `ประเสริฐ ใจงาม / C-2023-0455` — name over contract id, not money. If a real arrears figure is ever added to this screen, it takes the large/small treatment; nothing currently on it does.

### 7.3 Token usage audit
**Used:** `ink/900` `ink/700` `ink/600` `ink/500`; `surface/0` `surface/50` `surface/100`; `line/default`; `brand/050` `brand/500`; `status/overdue` (#dc2626 on #fee2e2); `status/pending` (#2563eb on #dbeafe).
**Not used on this screen:** `ink/800` #111827; `ink/400` #9ca3af; `status/current` (#16a34a on #dcfce7); `status/held` (#6b7280 on #f3f4f6); type token `Label/13` (Kanit Medium 13/18).

Do not reach for `ink/400` #9ca3af as a "lighter grey" — it fails contrast on white and this screen deliberately bottoms out at `ink/500` #6b7280.
Beware that `status/held`'s background value is `#f3f4f6`, the same hex as `surface/100`, the Main canvas. Keep them as separate tokens; a held chip on the Main canvas would be invisible.

**Type tokens in use:**
- Display/24 (SemiBold 24/32) — `Exceptions` H1, all six tile values
- Heading/16 (SemiBold 16/24) — `VOLT`, `Debt`, both card titles, banner title
- BodyStrong/14 (Medium 14/20) — nav `Today List`, all button labels, all money, claim AGE, banner values, Thai name
- Body/14 (Regular 14/20) — the other five nav labels
- Small/13 (Regular 13/18) — search placeholder, officer name, header subtitle, contract ids, document names, posting AGE, submitted timestamps, `N sent`
- Caption/12 (Medium 12/16) — nav counts, tile labels + captions, owner notes, card descriptions, all TH headings (`letter-spacing:0.48px`, uppercase), badge text, `Chase` label, banner description, banner field labels, banner contract id

---

## 8. Fixture requirements — seed data for a truthful render

The screen is only truthful if the fixtures satisfy the reconciliation ledger in §4.1. Counts are **exact**, not minimums, because no queue has a "more" card.

**Population filter:** one must already be authored and applied, or the dashboard returns 422 and none of the below renders. Seed the filter first.

**Officer / session:** display name `Nok`, role `Officer`. Avatar is a generated `brand/050` disc with a `brand/500` ring — no image asset needed.

**Batch metadata:** reconciliation run stamped `03:00`; Owner digest stamped `08:00`; correction window closing `17:00`. These are literals in the subtitle, but should come from the batch record so they stay honest.

**Nav counters:** Today List **18**, Contracts **712**, Promises **31**, Modifications **4**, Reports **none**. Exceptions must be **derived** as `restoration_overdue + posting_failures + claim_exceptions` = 1+3+5 = **9** — not from all exception types.

**Posting exceptions — exactly 3, ages descending, oldest 6 h:**
| contract | document | amount | reason | age |
|---|---|---|---|---|
| C-2024-0188 | Penalty invoice | 1240 THB | `period_locked` (red) | 6 h |
| C-2023-0912 | Closure void | 48000 THB | `rate_limited` (**blue**) | 3 h |
| C-2024-0655 | Adjustment | 2100 THB | `auth_failure` (red) | 1 h |

Reason vocabulary must include at least one transient (`rate_limited` → `status/pending`) and two terminal (`period_locked`, `auth_failure` → `status/overdue`), or the badge rule is untestable.

**Claim exceptions — exactly 5, service level seeded at 2 days:**
| contract | claimed | submitted | age | chases_sent |
|---|---|---|---|---|
| C-2024-0655 | 4000 THB | 21 Aug 09:40 | 4 d | 2 |
| C-2025-0077 | 12000 THB | 22 Aug 14:02 | 3 d | 1 |
| C-2024-0421 | 8500 THB | 23 Aug 11:15 | 2 d | 1 |
| C-2023-0338 | 15000 THB | 23 Aug 16:48 | 2 d | 0 |
| C-2025-0201 | 6300 THB | 24 Aug 10:07 | 1 d | 0 |

This set is deliberately chosen to exercise all three AGE colours (>2 d red, =2 d blue, <2 d grey) and both chase counters (0 and non-zero). Keep at least one of each or the colour rule goes unverified.
**`C-2024-0655` appears in both queues** — once as a posting exception and once as a claim exception. That overlap is intentional; do not de-duplicate across queues.

**Restoration overdue — exactly 1 account:**
- customer name `ประเสริฐ ใจงาม` (**Thai**, required — this is the only non-Latin string on the screen and it is what proves the Kanit Thai subset is loading)
- contract `C-2023-0455`
- arrears cleared at `23 Aug 15:22`
- still restricted for `1 d 19 h`
- current output `30 percent` (rendered as the word, not `%`)
- must be P1 severity, and must carry the "customer has paid" condition that drives tile 1's caption

**Counters with no drawn queue** — seed as scalars only, no row data needed:
- duplicate invoice groups = **2** (grouping key: same payer, amount, date)
- terms differences = **15**
- restriction without notice = **0**, with **18** backfilled baseline records behind it so the zero is provably real rather than unloaded

**Date context:** the newest timestamp is `24 Aug 10:07` and the header says the correction window closes at 17:00 today, so fixtures should be read as a run on or shortly after **24 Aug**. Ages (`4 d`, `1 d 19 h`) must be computed against that reference instant, not against wall-clock now, or the ages will drift away from the tile captions and break §4.1.

**Deliberately absent from fixtures** — do not add these or the screen stops matching the design:
- any 4th posting exception, 6th claim, or 2nd restoration account
- any "and N more" row or pagination cursor
- any arrears/outstanding-balance pair (no money on this screen is arrears)
- any record that would put a `status/current` or `status/held` chip on screen
- any caseload/workload figure (the `46 of 200 customers` block is hidden here)
