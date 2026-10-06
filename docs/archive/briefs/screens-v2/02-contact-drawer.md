# screens-v2 · 02 — ContactDrawer (`src/components/ContactDrawer.jsx`)

The core loop of flow parts 2–3, as a right-side drawer (480px; full-screen
under 860px) so the queue stays visible behind it. One component, reused from
My Day, Customer 360 and Follow-ups — one form, one contract, no drift.

## Zones

1. **Head** — customer name, number, masked phone, EntityChip; Close.
2. **Script context** — Money pair, DPD + Band, ladder (detail), the open PTP if
   any, and the standing sentence: the slot is "put at stake, not spent" until
   an amount is stated or 90 s pass (REQ-COL-055).
3. **Channel** — PHONE · LINE · SMS · EMAIL · VISIT · LETTER as chips.
4. **Disposition grid** — the closed dictionary, split ติดต่อได้ / ติดต่อไม่ได้.
   The cost is stated ON the option (G1's lesson): counting options carry
   "นับเป็นการติดต่อ · ใช้ช่องของวันนี้" in overdue red; LINE_SENT_UNREAD says
   "นับเมื่ออ่าน"; flag-raisers (REFUSED_PAY, LINE_BLOCKED) say so.
5. **Branch panels**, by selection:
   - **นัดชำระ (PTP)** on ANS_DISCUSSED — date + amount; entering an amount sets
     `amount_stated` and the panel says, BEFORE submit, that the slot is then
     spent immediately with no retraction.
   - **แจ้งปัญหาบริการ** — route CS/O&M/Ops + summary; the confirmation names
     the returned owner and states the DPD clock does not stop.
   - **REFUSED_PAY** — states the routing: straight to Manager Review.
6. **Submit** → `POST /v1/contacts` (+ `POST /v1/ptps`, `POST /v1/service-issues`
   as chosen). The response's `manager_review_uid` is surfaced by name.
7. **After a counting save** — the retraction strip: a mono countdown (display
   only — the SERVER holds the clock; expiry greys the strip), ยกเลิกการบันทึก →
   `POST /v1/contacts/{id}:retract`; with `amount_stated` the strip says the slot
   is spent and offers no countdown. Then **ถัดไป → {next}** (guided queue, R10)
   and Close.

## Refusals

409 `contact_locked` renders verbatim with the EXISTING lock's holder; the
override control appears only when `override_allowed` (the drawer submits as
OFFICER, so normally never). Field errors land at the fields with `message_th`.
