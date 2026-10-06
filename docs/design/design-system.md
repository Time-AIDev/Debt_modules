# Volt Debt — Design System Master

> When building a page, first check `design-system/volt-debt/pages/[page].md`. If it exists, its rules override this file. Otherwise follow this file exactly.

**Project:** Volt Debt (the Debt team's working tool)
**Generated:** 2026-09-02 from `ui-ux-pro-max --design-system` (Minimalism & Swiss, dense dashboard, subtle motion), then reconciled with the house rules in `src/tokens.css` and the Volt brand. Where this file and the generator disagree, this file wins; the generator's dark-first, Fira, green-accent output was rejected for the reasons below.

## Who uses it
Two collection officers and one lead, Thai speakers, eight hours a day, on a laptop, often with LINE and PEAK open beside it. Speed of reading beats decoration. Every screen answers "what do I do next" before anything else.

## Style
Minimalism & Swiss: white ground, strong type hierarchy, grid, no ornament. Density 8/10 — a table row is 36px, a card padding 12px, section gap 16px. Motion 2/10 — 150–200ms hover and panel transitions only; `prefers-reduced-motion` disables them.

## Colour — tokens live in `src/tokens.css`, never hex in components
| Role | Token | Value (light) | Rule |
|---|---|---|---|
| Page ground | `--surface-100` | #f3f4f6 | Dark theme keeps roles, see tokens.css |
| Card | `--surface-0` | #ffffff | |
| Text | `--ink-800` / `--ink-600` | #111827 / #4b5563 | `--ink-400` is decoration only |
| Line | `--line-default` | #e5e7eb | |
| Brand | `--brand-500` | #f2b705 (amber) | **Never a status colour.** Wordmark, focus ring on brand actions only |
| Status current / paid | `--status-current` | #16a34a | |
| Status pending / PTP / draft | `--status-pending` | #2563eb | PEAK draft state uses this |
| Status overdue / broken / rejected | `--status-overdue` | #dc2626 | |
| Status held / closed | `--status-held` | #6b7280 | |
| Open decision | `--reg-open` | #5b21b6 | Only on Settings and the pending register |
| Bands | `--band-early-*`, `--band-mid-*`, `--band-npl-*` | see tokens | Always with the band set name |

Light is the default. Dark is supported through the same tokens (auto/light/dark, see `prefs.jsx`). The generator's "avoid light default" note is wrong for an office tool used in daylight.

## Typography
IBM Plex Sans for everything, with IBM Plex Sans Thai second in `--font-sans` for the Thai glyphs Plex Sans lacks. There is no monospace face: `--font-mono` is kept as the name of the literal role (ids, codes, money in tables) and points at `--font-sans`; Plex figures are tabular by default, so number columns still align. Scale from tokens: display-24, title-20, heading-16, body-14, label-13, caption-12. Body never below 13px. Money: arrears large (title-20) with outstanding small (caption-12) beneath — the house Money pair.

## Layout
Left rail 232px with grouped navigation ordered by the officer's day: วันนี้ · ลูกค้า · สมุดงาน · รอตรวจ · ใบแจ้งหนี้ก่อนติดตั้ง · เงินเข้าและ PEAK · NPL และการเรียกคืน · รายงาน · ตั้งค่า · แหล่งข้อมูล. Top bar 56px, and it STATES rather than controls: the environment badge on the left, then feedback, an identity menu naming the role and the person every act is signed with, and a View menu holding theme and language. Three controls, not eleven — role, theme and language are set-once viewer settings and do not earn permanent space beside the work. A page's own footnotes (reconciliation notes, method notes) go in a `<details class="page-note">` under the subtitle, never open by default. Content max 1208px, 12-column grid, 16px gutters. Tables scroll inside their own container; the page never scrolls sideways. Drawers slide from the right and keep the list visible behind them.

## Components (house idioms, see `docs/archive/briefs/screens-v2/README.md`)
- **Money** pair: arrears large, outstanding small, never a bare number.
- **Band** chip: bucket code with its band set; refuses to render without both.
- **EntityChip**: EPC / SPV; refuses to render without an entity.
- **StatusPair**: payment_status and dc_status side by side, two chips, never merged.
- **NextAction** strip: action label + date + overdue mark; red when past.
- **PeakState** chip: PENDING / DRAFT_CREATED / APPROVED_IN_PEAK / REJECTED / UNSENT, with the PEAK number when approved.
- **TierChip**: the Today tier name in words, never a number alone.
- **MonthGrid**: M1…Mn cells exactly as the sheet shows them; amounts in mono; tokens (Late, Link Sent, Restructure…) as text chips.
- **DataTable**: sticky first two columns, sortable, filter row, saved views, CSV export, 36px rows.
- **Problem**: RFC 9457 renderer, title + Thai message + code.
- **Notice**: dismissible, never a modal. Confirms name the cost of the act (e.g. "this counts as today's contact").

## Interaction rules
- One tap from any list row to โทร (tel:), LINE, and บันทึกผล (drawer).
- The drawer cannot close a contact without a next action unless a PTP or issue was created.
- Every refusal from the API is shown in place with the Thai message; nothing is silently swallowed.
- Keyboard: every action reachable by Tab; focus ring visible (2px `--status-pending`, brand ring only on the primary brand button).
- Touch targets 40px minimum in lists; 44px for primary actions.
- No emoji as icons; inline SVG (Lucide shapes) with `aria-hidden` and a text label.

## Language
Thai default, English toggle; keys with parity test. Loanwords PTP, DPD, NPL, PEAK stay Latin inside Thai copy. Dates dd/mm/yyyy in the UI regardless of the sheet's two formats.

## Pre-delivery checklist
- [ ] Contrast 4.5:1 on every text/background pair in both themes
- [ ] No horizontal page scroll at 1024, 1280, 1440
- [ ] Every table inside `overflow-x:auto`
- [ ] Focus visible on every control
- [ ] `prefers-reduced-motion` respected
- [ ] No hex outside tokens.css
- [ ] Amber appears only as brand
- [ ] Every money figure is the Money pair
- [ ] Every bucket carries its band set; every entity chip its entity
