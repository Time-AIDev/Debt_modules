# screens-v2 · 01 — My Day (`/`, `src/screens/MyDay.jsx`)

The officer's first glance, rebuilt to R9–R12. The screen answers, in order:
**who do I call right now** (hero), **how is the day shaped** (tier chips),
**who comes after** (the queue), and only then **where does everything stand**
(the board, demoted and collapsed).

## Zones, top to bottom

1. **Header** — title, the tier rule spelled out in the subtitle, the run's
   business date, Refresh.
2. **Next-call hero card** (`.jy-hero`, amber left rule — the one place brand
   amber appears as emphasis). Three columns:
   - Identity: eyebrow "สายถัดไป", customer name at display-24, chip row
     (priority-reason chip, EntityChip, DataSourceChip, customer no, masked
     phone), the ladder in detail variant beneath.
   - Facts: Money pair · DPD + Band · last contact (or "ยังไม่เคยติดต่อ") ·
     open PTP when one exists.
   - Actions, stacked: **โทร** (primary, `tel:` on `phone_e164`) · **LINE**
     (`line://ti/p/~` on `line_id`) · **บันทึกผล** (opens the drawer) · ดูข้อมูล
     (Customer 360). All three call actions also open the drawer (R12).
3. **Tier chips** — `counts_by_reason` as four chips in the tier palette.
4. **The queue** — one row per customer in server order (never re-sorted
   client-side): reason chip · name + entity/source chips + "in review" tag ·
   Money pair · DPD + band · inline ladder · actions. A locked row shows
   "ติดต่อแล้ววันนี้" with the holder in the tooltip; an unlocked row carries
   โทร/LINE/บันทึกผล.
5. **The board** — a `<details>` collapsed by default with a quiet Notice naming
   R9 as the reason; columns from `/v1/board/columns`, cards placed by
   `board_column_id` (the session overlay included).

## The hero choice

The hero is the item `meta.next_up` names — the first UNLOCKED customer with
arrears in tier order — falling back to the queue's head. `aria-current` marks
the hero's row in the table so the two surfaces visibly agree.

## Honesty rules on this screen

- A sheet-derived identity has **no phone_e164**: the โทร button renders
  disabled with the reason ("เบอร์จริงไม่ได้นำเข้า") — an invented number could
  dial a stranger (R12).
- The queue order and every `priority_reason` come from the server; the screen
  never derives a tier (no-arithmetic rule).

## Data

`GET /v1/working-list` + `GET /v1/board/columns`; refetch after every drawer
action. Tests: `src/screens/MyDay.test.jsx` (hero + reason chip, disabled call
for sheet identities, board collapsed).
