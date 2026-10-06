# screens-v2 · 06 — Data sources (`/data-sources`, `src/screens/DataSources.jsx`)

R13–R16 made visible: where the book comes from, what a human adjusted, what
reached PEAK. The standing Notice states the fallback chain — Odoo → cached
snapshot → sheet fixtures — and that every row says which rung served it.

## Zones

1. **Odoo card** — configured state (missing env VARIABLE NAMES when not — never
   values); the last good snapshot's timestamp; four actions: **ซิงก์จาก Odoo**
   (`:sync` — the confirmation counts the orders), **ใช้สแนปช็อตล่าสุด**
   (`:use-snapshot`), **กลับไปใช้ข้อมูลชีท** (`:use-sheet`), **สำรวจโมเดล**
   (`/discovery` — the model/records table renders beneath, the mapping
   proposal with it). A dead Odoo renders `integration_unavailable` verbatim;
   the app keeps running on the lower rungs.
2. **PEAK card** — configured state + reachability probe; the mode sentence:
   full write in UAT (R15), failures keep the local record marked UNSENT.
3. **Overrides card** — every R14 override as a timeline line:
   "{source} ระบุ {was} · ปรับเป็น {now} โดย {by} — {reason}", with the
   "source changed since" warning when a re-sync moved the ground underneath.
   Empty state: "ไม่มีการปรับด้วยมือ".

## Rules this screen carries

- Credentials appear as variable names only, everywhere, always (R16).
- Odoo is never written; an adjustment is a local override with provenance —
  the same idiom as the Orders screen's "sheet says X" (R14).
- The sync is process-wide (a fact about the data); overrides are per session
  (a fact about a tester's run).
